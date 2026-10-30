"""
backend/app/api/weather_map.py

GET /api/map/weather/info        "기상 악영향" 지표가 만들어졌는지, 가정과 한계, 턴별 구역 평균 (요인별 값 포함)
GET /api/map/weather/{turn}.png  턴별 지표 오버레이 (0~1 고정 척도, 위험도 G/A/R 과 다른 색)

원시 기상(ERA5-Land) 자료가 없거나 시나리오 시각을 덮지 못하면 지표를 만들지 않고 이유를 알린다.
다른 날의 값으로 대신하지 않는다. 계산과 한계는 app/weather/scenario_index.py 에 있다.
위험도 오버레이(/api/map/overlay)처럼 <img> 로 불러오므로 인증 헤더를 요구하지 않는 공개 데이터다.
"""

import io

import numpy as np
from fastapi import APIRouter, HTTPException, Response
from PIL import Image

from app.weather import scenario_index as si

router = APIRouter(prefix="/map/weather", tags=["weather"])
MAX_TURN = 30                        # 실황 데이터 범위 (31개 시각), 위험도 오버레이와 같다

# 0~1 → RGBA. 위험도(G/A/R: 초록·주황·빨강)와 헷갈리지 않게 파랑 → 보라 계열, 낮은 값은 거의 투명.
STOPS = np.array([0.0, 0.15, 0.4, 0.7, 1.0])
COLORS = np.array([[40, 120, 255, 0], [70, 150, 255, 70], [90, 120, 255, 130], [150, 90, 255, 175], [235, 70, 255, 205]], dtype=float)


def weather_png(grid: np.ndarray) -> Image.Image:
    v = np.clip(np.nan_to_num(grid, nan=0.0), 0.0, 1.0)
    rgba = np.stack([np.interp(v, STOPS, COLORS[:, c]) for c in range(4)], axis=-1).astype(np.uint8)
    return Image.fromarray(rgba, mode="RGBA")


def _weather():
    try:
        return si.get_weather()
    except si.WeatherUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/info", summary="기상 악영향 지표의 가용 여부, 가정, 턴별 구역 평균")
def weather_info():
    base = {"weights": si.WEIGHTS, "notes": si.NOTES,
            "scales": {"wind_full_ms": si.WIND_FULL_MS, "fog": "ΔT, 풍속, 최근 3시간 강수의 로지스틱 (app/weather/fog.py)", "rain_soil": "팀 노트북 강수 임계 구간 기준 곡선 (app/weather/curves.py)"}}
    try:
        w = si.get_weather()
    except si.WeatherUnavailable as exc:
        return {**base, "available": False, "reason": str(exc)}
    turns, outside = [], []
    from datetime import timedelta

    import numpy as np

    from app.simulation.shared_env import get_environment

    env = get_environment()
    walkable = ~np.asarray(env.blocked)

    def risk_mean(t: int):
        """같은 시점의 위험도(종합) 구역 평균 (통행 가능한 칸). 기상 지표와 한 그래프에 겹쳐 그려 날씨가 위험도에 어떻게 반영되는지 보여 준다."""
        g = np.asarray(env.latest_actual_at(env.start_time + timedelta(minutes=10 * t), "total"))
        ok = np.isfinite(g) & walkable
        return round(float(g[ok].mean()), 4) if ok.any() else None

    for t in range(MAX_TURN + 1):
        try:
            turns.append({"turn": t, **w.area_mean(t), "risk_total": risk_mean(t)})
        except si.WeatherUnavailable:
            turns.append(None)
            outside.append(t)
    if len(outside) == len(turns):
        return {**base, "available": False, "reason": f"ERA5 자료(UTC {w.coverage()[0]} ~ {w.coverage()[1]})가 시나리오 시각(UTC 오프셋 {w.offset_h:+g}시간 적용)을 덮지 않습니다."}
    return {**base, "available": True, "reason": None, "source": w.source, "utc_offset_h": w.offset_h,
            "data_range_utc": list(w.coverage()), "turns": turns, "turns_outside_data": outside}


@router.get("/{turn}.png", summary="턴별 기상 악영향 오버레이 (0~1 고정 척도)")
def weather_image(turn: int):
    from app.simulation.algo.sim_config import SimAlgoConfig

    if not 0 <= turn <= MAX_TURN:
        raise HTTPException(status_code=404, detail=f"턴은 0~{MAX_TURN} 범위입니다.")
    w = _weather()
    meta = SimAlgoConfig.meta()
    try:
        grid = w.on_grid(turn, np.asarray(meta.lat), np.asarray(meta.lon))["index"]
    except si.WeatherUnavailable as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    buf = io.BytesIO()
    weather_png(grid).save(buf, format="PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=60"})
