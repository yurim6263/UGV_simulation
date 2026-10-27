"""
backend/app/services/run_data.py

run 의 이동 기록(run_tracks)을 사용자 권한에 맞게 불러온다. 재생 API 와 LLM 어시스턴트 도구가 같은 함수를 쓴다.
(권한 필터를 두 곳에 복사해 두면 한쪽이 어긋났을 때 다른 제대의 기록이 새므로 한 곳에서만 정의한다.)

지휘관은 전체, 통제관은 담당 제대의 기록만 본다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import echelon_of
from app.core.security import TokenPayload
from app.db.models.mission import Mission, MissionTarget
from app.db.models.simulation_run import SimulationRun
from app.db.models.track import RunTrack
from app.simulation.presets import DEFAULT_POIS
from app.simulation.replay import MODES, TEAMS, build_mode

MODE_OF = {"balanced": "balance", "recon": "explore", "rapid": "rush"}
COMMANDER_ROLES = ("commander", "admin")


class RunDataError(Exception):
    """권한/상태 때문에 기록을 줄 수 없을 때. status_code 는 HTTP 의미를 그대로 따른다."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code, self.detail = status_code, detail


@dataclass
class RunData:
    run: SimulationRun
    mission: Mission
    frame: pd.DataFrame            # 사용자 권한으로 걸러진 이동 기록
    team: str | None               # 통제관이면 담당 제대(Alpha/Bravo/Charlie), 지휘관이면 None

    @property
    def mode_key(self) -> str:
        return MODE_OF.get(self.run.selected_mode or "balanced", "balance")


def team_scope(user: TokenPayload) -> str | None:
    """지휘관은 None(전체), 통제관은 담당 제대 이름."""
    if user.role in COMMANDER_ROLES:
        return None
    try:
        return TEAMS[echelon_of(user) - 1]
    except HTTPException as exc:
        raise RunDataError(exc.status_code, str(exc.detail)) from exc
    except IndexError as exc:
        raise RunDataError(403, "담당 제대를 확인할 수 없습니다.") from exc


def filter_team(frame: pd.DataFrame, team: str | None) -> pd.DataFrame:
    if team is None:
        return frame
    return frame[frame.agent_id.str.endswith(f"_{team}") | frame.agent_id.str.contains(f"_{team}_")]


async def load_run_data(db: AsyncSession, run_id: int, user: TokenPayload) -> RunData:
    run = await db.get(SimulationRun, run_id)
    if run is None:
        raise RunDataError(404, "run을 찾을 수 없습니다.")
    mission = await db.get(Mission, run.mission_id)
    rows = (await db.execute(
        select(RunTrack).where(RunTrack.run_id == run_id).order_by(RunTrack.seq_idx)
    )).scalars().all()
    if not rows:
        raise RunDataError(404, "아직 저장된 이동 기록이 없습니다.")

    frame = pd.DataFrame([{
        "seq_idx": r.seq_idx, "turn_idx": r.turn_idx, "agent_id": r.agent_id, "row": r.row, "col": r.col,
        "lat": r.lat, "lon": r.lon, "action": r.action, "ap": r.ap, "risk_grade": r.grade or "G",
        "normalized_c_total": r.total, "c_mob_prime": r.mob, "c_sen_prime": r.sen,
    } for r in rows])

    team = team_scope(user)
    frame = filter_team(frame, team)
    if frame.empty:             # 이 임무에는 해당 제대가 편성되지 않았다 (예: 목표 2곳인 임무의 3제대)
        raise RunDataError(404, f"이 임무에는 {team} 제대의 기록이 없습니다.")
    return RunData(run=run, mission=mission, frame=frame, team=team)


async def mission_pois(db: AsyncSession, mission_id: int) -> list[tuple[float, float]]:
    targets = (await db.execute(
        select(MissionTarget).where(MissionTarget.mission_id == mission_id).order_by(MissionTarget.seq)
    )).scalars().all()
    return [(t.lat, t.lon) for t in targets] or list(DEFAULT_POIS)


async def build_run_mode(db: AsyncSession, data: RunData) -> tuple[dict, list[tuple[float, float]]]:
    """(재생/KPI 데이터, 정찰지 목록). KPI 는 이동 기록에서 집계한 값이다."""
    from app.simulation.algo.sim_config import SimAlgoConfig   # 지형 파일은 필요할 때만 읽는다

    pois = await mission_pois(db, data.mission.id)
    poi_cells = [SimAlgoConfig.latlon_to_grid(lat, lon) for lat, lon in pois]
    return build_mode(data.frame, data.mode_key, MODES[data.mode_key], poi_cells), pois
