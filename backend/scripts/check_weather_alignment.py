"""
backend/scripts/check_weather_alignment.py

ERA5 기상 지표(app/weather/scenario_index.py)의 시간 변화가 시나리오 위험도(실황 31장)의 시간 변화와 맞는지 본다.
시나리오 날짜 표기가 엇갈려서(2023-06-30 / 2023-07-26 / 2024-07-03) 받은 ERA5 날짜가 위험도 지도가 만들어진 날씨와 같은지 확인되지 않았다.
이 스크립트가 그 확인의 첫 단계다: 두 시계열이 같은 방향으로 움직이면 같은 날씨일 가능성이 있고, 반대이거나 무관하면 의심한다.
(맞는다고 증명하지는 못한다. 31개 시각의 상관은 추세 하나만 보여 준다.)

    cd backend
    python scripts/check_weather_alignment.py [--file data/weather/era5_scenario.nc] [--utc-offset-h 0]
    # 시각 오프셋 후보를 비교하려면 --utc-offset-h 를 바꿔 여러 번 실행한다 (현지 시각이면 폴란드 여름 +2)
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--file", default=None)
    ap.add_argument("--utc-offset-h", type=float, default=None)
    args = ap.parse_args()
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
    if args.file:
        os.environ["WEATHER_ERA5_PATH"] = str(Path(args.file).resolve())
    if args.utc_offset_h is not None:
        os.environ["WEATHER_UTC_OFFSET_H"] = str(args.utc_offset_h)

    from datetime import timedelta

    import numpy as np

    from app.simulation.shared_env import get_environment
    from app.weather.scenario_index import WeatherUnavailable, get_weather

    try:
        w = get_weather()
    except WeatherUnavailable as exc:
        sys.exit(str(exc))
    env = get_environment()
    risk, index, rain, fog = [], [], [], []
    for t in range(31):
        try:
            m = w.area_mean(t)
        except WeatherUnavailable as exc:
            sys.exit(str(exc))
        grid = env.latest_actual_at(env.start_time + timedelta(minutes=10 * t), "total")
        risk.append(float(np.nanmean(grid)))
        index.append(m["index"]), rain.append(m["rain_mmph"]), fog.append(m["fog"])
    risk, index = np.array(risk), np.array(index)
    r = np.corrcoef(risk, index)[0, 1] if index.std() > 1e-9 and risk.std() > 1e-9 else float("nan")
    print(f"자료: {w.source}  UTC {w.coverage()[0]} ~ {w.coverage()[1]}  (시나리오 시각 - UTC = {w.offset_h:+g}시간)")
    print(f"위험도(종합) 구역 평균: T+0 {risk[0]:.3f} → T+5h {risk[-1]:.3f}   기상 지표: T+0 {index[0]:.3f} → T+5h {index[-1]:.3f}")
    print(f"31개 시각의 피어슨 상관 = {r:.2f}  (양수면 같은 방향, 위험도가 완화되면 기상 지표도 낮아졌다는 뜻)")
    print(f"강수 평균(mm/h) 최대 {max(rain):.2f}, 안개 가능성 평균 최대 {max(fog):.2f}")
    print("해석 주의: 두 시계열 모두 한 방향으로 변하는 추세라 상관이 높아도 같은 날씨라는 증거는 약하다. 낮거나 음수면 날짜/시각 불일치를 의심한다.")


if __name__ == "__main__":
    main()
