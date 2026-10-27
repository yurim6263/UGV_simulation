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
from fastapi import APIRouter, HTTPException, Response
from sqlalchemy import select

from app.api.deps import CurrentUser, DBSession, echelon_of
from app.db.models.mission import Mission, MissionTarget
from app.db.models.simulation_run import SimulationRun
from app.db.models.track import RunTrack
from app.simulation.presets import DEFAULT_POIS, DEFAULT_START
from app.simulation.replay import MODES, TEAMS, build_mode, grid_bounds

router = APIRouter(tags=["replay"])

_MODE_OF = {"balanced": "balance", "recon": "explore", "rapid": "rush"}


@router.get("/runs/{run_id}/replay", summary="시뮬레이션 재생 데이터")
async def get_replay(run_id: int, db: DBSession, user: CurrentUser):
    from app.simulation.algo.sim_config import SimAlgoConfig   # 지형 파일은 이 API 를 쓸 때만 읽는다

    run = await db.get(SimulationRun, run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="run을 찾을 수 없습니다.")
    mission = await db.get(Mission, run.mission_id)

    rows = (await db.execute(
        select(RunTrack).where(RunTrack.run_id == run_id).order_by(RunTrack.seq_idx)
    )).scalars().all()
    if not rows:
        raise HTTPException(status_code=404, detail="아직 저장된 이동 기록이 없습니다.")

    df = pd.DataFrame([{
        "seq_idx": r.seq_idx, "turn_idx": r.turn_idx, "agent_id": r.agent_id, "row": r.row, "col": r.col,
        "lat": r.lat, "lon": r.lon, "action": r.action, "ap": r.ap, "risk_grade": r.grade or "G",
        "normalized_c_total": r.total, "c_mob_prime": r.mob, "c_sen_prime": r.sen,
    } for r in rows])

    if user.role not in ("commander", "admin"):                 # 통제관은 자기 제대만
        team = TEAMS[echelon_of(user) - 1]
        df = df[df.agent_id.str.endswith(f"_{team}") | df.agent_id.str.contains(f"_{team}_")]
        if df.empty:                       # 이 임무에는 해당 제대가 편성되지 않았다 (예: 목표 2곳인 임무의 3제대)
            raise HTTPException(status_code=404, detail=f"이 임무에는 {team} 제대의 기록이 없습니다.")

    targets = (await db.execute(
        select(MissionTarget).where(MissionTarget.mission_id == mission.id).order_by(MissionTarget.seq)
    )).scalars().all()
    pois = [(t.lat, t.lon) for t in targets] or list(DEFAULT_POIS)
    poi_cells = [SimAlgoConfig.latlon_to_grid(lat, lon) for lat, lon in pois]

    mode = _MODE_OF.get(run.selected_mode or "balanced", "balance")
    meta = SimAlgoConfig.meta()
    return {
        "scenario": {
            "turn_minutes": 10,
            "turns": int(df.turn_idx.max()) + 1,
            "bounds": grid_bounds(meta.lat, meta.lon),
            "start": [mission.departure_lat, mission.departure_lon] if mission else list(DEFAULT_START),
            "pois": [{"id": i + 1, "lat": p[0], "lon": p[1]} for i, p in enumerate(pois)],
            "modes": [{"key": mode, "label": MODES[mode]}],
        },
        "mode": build_mode(df, mode, MODES[mode], poi_cells),
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
