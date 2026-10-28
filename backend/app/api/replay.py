"""
backend/app/api/replay.py

GET /api/runs/{run_id}/replay — 저장된 이동 기록(run_tracks)을 재생 화면 형식으로 반환.

정적 JSON(export_replay.py / run_episode.py)과 같은 형식이라, 프론트는 파일 대신 이 API 를 읽어도 된다.
통제관은 자기 제대의 기록만 받는다.
"""

import io
from functools import lru_cache
from typing import Literal

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, require_roles
from app.analysis.sql_reports import mode_comparison, run_report
from app.db.models.simulation_run import SimulationRun
from app.services.run_data import RunDataError, build_run_mode, load_run_data
from app.simulation.presets import DEFAULT_START
from app.simulation.replay import MODES, grid_bounds

router = APIRouter(tags=["replay"])

_MODE_OF = {"balanced": "balance", "recon": "explore", "rapid": "rush"}


@router.get("/runs/{run_id}/replay", summary="시뮬레이션 재생 데이터")
async def get_replay(run_id: int, db: DBSession, user: CurrentUser):
    from app.simulation.algo.sim_config import SimAlgoConfig   # 지형 파일은 이 API 를 쓸 때만 읽는다

    try:
        data = await load_run_data(db, run_id, user)           # 통제관은 자기 제대의 기록만 받는다
        mode_data, pois = await build_run_mode(db, data)
    except RunDataError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc

    from app.simulation.shared_env import get_environment

    meta = SimAlgoConfig.meta()
    start_time = get_environment().start_time
    return {
        "scenario": {
            "start_time": start_time.isoformat() if start_time else None,      # 데이터의 시작 시각 (표준 시간대 정보 없음)
            "turn_minutes": 10,
            "turns": int(data.frame.turn_idx.max()) + 1,
            "bounds": grid_bounds(meta.lat, meta.lon),
            "start": [data.mission.departure_lat, data.mission.departure_lon] if data.mission else list(DEFAULT_START),
            "pois": [{"id": i + 1, "lat": p[0], "lon": p[1]} for i, p in enumerate(pois)],
            "modes": [{"key": data.mode_key, "label": MODES[data.mode_key]}],
        },
        "mode": mode_data,
    }


# ── 위험도 지도 이미지 (재생 화면의 오버레이) ────────────────────────────
# <img>/Leaflet 은 인증 헤더를 보낼 수 없고, 지형·위험도 지도는 다른 지도 API(/api/map/tactical)처럼 공개 데이터다.

_OVERLAY_KINDS = {"total": "total", "mobility": "mob", "sensor": "sen"}
_MAX_OVERLAY_TURN = 30      # 실황 데이터 범위 (31개 레이어)


@lru_cache(maxsize=16)
def _overlay_setup(kind: str, scale: float):
    """종류/강도별 턴 격자와 G/A/R 경계(전 턴 공통 30/70 분위수). 최초 1회만 계산한다."""
    from datetime import timedelta

    from app.simulation.shared_env import get_environment

    env = get_environment()
    grids = [np.clip(env.latest_actual_at(env.start_time + timedelta(minutes=10 * t), _OVERLAY_KINDS[kind]) * scale, 0, 1)
             for t in range(_MAX_OVERLAY_TURN + 1)]
    lo, hi = np.percentile(np.concatenate([g[np.isfinite(g)] for g in grids]), [30, 70])
    return grids, float(lo), float(hi)


@router.get("/map/overlay/{kind}/{turn}.png", summary="턴별 위험도 오버레이 이미지 (G/A/R)")
def overlay_image(kind: Literal["total", "mobility", "sensor"], turn: int, scale: float | None = None):
    from app.simulation.real_runner import _weather_scale
    from app.simulation.replay import overlay_png

    if not 0 <= turn <= _MAX_OVERLAY_TURN:
        raise HTTPException(status_code=404, detail=f"턴은 0~{_MAX_OVERLAY_TURN} 범위입니다.")
    grids, lo, hi = _overlay_setup(kind, round(scale if scale is not None else _weather_scale(), 3))
    buf = io.BytesIO()
    overlay_png(grids[turn], lo, hi).save(buf, format="PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# ── 예보 위험도 지도 ─────────────────────────────────────────────────────
# 현재 시각(턴)에 이미 발표되어 있던 가장 최근 예보에서, 현재 + lead 분 뒤의 위험도를 보여준다.
# 예보가 없는 시각을 실황이나 지속성으로 채우지 않는다 (예보가 아닌 것을 예보처럼 보이게 하지 않기 위해).

_MAX_LEAD_MIN = 180


def _forecast_target(kind: str, turn: int, lead_min: int):
    from datetime import timedelta

    from app.simulation.shared_env import get_environment

    if not 0 <= turn <= _MAX_OVERLAY_TURN:
        raise HTTPException(status_code=404, detail=f"턴은 0~{_MAX_OVERLAY_TURN} 범위입니다.")
    if not 0 <= lead_min <= _MAX_LEAD_MIN or lead_min % 10:
        raise HTTPException(status_code=422, detail=f"lead_min 은 0~{_MAX_LEAD_MIN} 사이의 10분 단위여야 합니다.")
    env = get_environment()
    now = env.start_time + timedelta(minutes=10 * turn)
    model_time = env.model_time_at(now)
    target = now + timedelta(minutes=lead_min)
    grid = env.forecast_layer(_OVERLAY_KINDS[kind], model_time, target) if model_time is not None else None
    return env, now, model_time, target, grid


def _grade_shares(grid, lo: float, hi: float) -> dict:
    """위험도 격자의 G/A/R 칸 비율 (데이터 없는 칸 제외). 지도 색과 같은 경계를 쓴다."""
    v = grid[np.isfinite(grid)]
    if v.size == 0:
        return {"G": 0.0, "A": 0.0, "R": 0.0}
    return {"G": float((v <= lo).mean()), "A": float(((v > lo) & (v <= hi)).mean()), "R": float((v > hi).mean())}


@router.get("/map/forecast-info", summary="예보 지도의 발표 시각/대상 시각, 예보 존재 여부, 예보와 실황의 등급 비율")
def forecast_info(turn: int, lead_min: int = 60, kind: Literal["total", "mobility", "sensor"] = "total", scale: float | None = None):
    from app.simulation.real_runner import _weather_scale

    env, now, model_time, target, grid = _forecast_target(kind, turn, lead_min)
    reason = None
    if model_time is None:
        reason = "이 시각 이전에 발표된 예보가 없습니다."
    elif grid is None:
        reason = "이 발표의 예보 범위(발표 후 3시간)를 벗어난 시각입니다."
    out = {"current_time": now.isoformat(), "model_time": model_time.isoformat() if model_time else None,
           "target_time": target.isoformat(), "lead_min": lead_min, "available": grid is not None, "reason": reason,
           "forecast_share": None, "actual_share": None}
    if grid is not None:
        sc = round(scale if scale is not None else _weather_scale(), 3)
        _, lo, hi = _overlay_setup(kind, sc)
        out["forecast_share"] = _grade_shares(np.clip(grid * sc, 0, 1), lo, hi)
        actual = env.actual_at(target, _OVERLAY_KINDS[kind])          # 그 시각의 실제 값 (실황 데이터가 끝난 뒤면 None)
        if actual is not None:
            out["actual_share"] = _grade_shares(np.clip(actual * sc, 0, 1), lo, hi)
    return out


@router.get("/map/forecast/{kind}/{turn}/{lead_min}.png", summary="예보 위험도 오버레이 이미지 (G/A/R)")
def forecast_image(kind: Literal["total", "mobility", "sensor"], turn: int, lead_min: int, scale: float | None = None):
    from app.simulation.real_runner import _weather_scale
    from app.simulation.replay import overlay_png

    _, _, _, _, grid = _forecast_target(kind, turn, lead_min)
    if grid is None:
        raise HTTPException(status_code=404, detail="이 시각의 예보가 없습니다.")
    _, lo, hi = _overlay_setup(kind, round(scale if scale is not None else _weather_scale(), 3))      # 실황 지도와 같은 등급 경계
    buf = io.BytesIO()
    overlay_png(np.clip(grid * round(scale if scale is not None else _weather_scale(), 3), 0, 1), lo, hi).save(buf, format="PNG", optimize=True)
    return Response(buf.getvalue(), media_type="image/png", headers={"Cache-Control": "public, max-age=3600"})


# ── 실행 기록 SQL 분석 ───────────────────────────────────────────────────

@router.get(
    "/runs/{run_id}/analysis",
    summary="실행 기록 SQL 분석 (SOS, 개입 대기, 대기열, 위험 구간, 모드 비교)",
    dependencies=[Depends(require_roles("commander"))],
)
async def run_analysis(run_id: int, db: DBSession):
    """지휘관 전용(전체 제대를 가로지르는 집계). 쿼리는 app/analysis/sql_reports.py 에 있다."""
    run = await db.get(SimulationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    report = await run_report(db, run_id)
    if not report["queue_by_turn"]:
        raise HTTPException(status_code=404, detail="아직 저장된 이동 기록이 없습니다.")
    report["mode_comparison"] = await mode_comparison(db, run.mission_id)
    return report
