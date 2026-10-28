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
DEFAULT_TEAM_MODE = "balance"
ASSIGNED_KEY, ASSIGNED_LABEL = "assigned", "지정 편성"      # 제대마다 지정한 모드의 기록을 합친 보기
SEQ_STRIDE = 30_000          # 합칠 때 제대마다 순번을 이만큼 띄운다 (프런트가 턴 x 100000 + 순번으로 프레임을 매기므로 3 x 이 값 + 기록 순번 < 100000)


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


def team_modes_of(mission: Mission | None) -> dict[str, str]:
    """제대별 지정 모드. 저장된 값이 없거나 알 수 없는 값이면 균형이다."""
    saved = (mission.team_modes if mission is not None else None) or {}
    return {t: saved[t] if saved.get(t) in MODES else DEFAULT_TEAM_MODE for t in TEAMS}


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


def check_mode_access(run: SimulationRun, mission: Mission | None, team: str | None) -> None:
    """통제관은 담당 제대에 지정된 모드의 기록만 볼 수 있다. 화면에서 숨기는 것으로 끝내지 않고 서버가 거부한다."""
    if team is None:
        return
    mode = MODE_OF.get(run.selected_mode or "balanced", DEFAULT_TEAM_MODE)
    if mode != team_modes_of(mission)[team]:
        raise RunDataError(403, "담당 제대에 지정된 모드의 기록만 볼 수 있습니다.")


async def check_run_access(db: AsyncSession, run_id: int, user: TokenPayload) -> None:
    """run 단위 API 공통 검사. 지휘관은 통과, 통제관은 지정된 모드의 run 만. run 이 없으면 통과(각 API 가 404 를 낸다)."""
    if user.role in COMMANDER_ROLES:
        return
    run = await db.get(SimulationRun, run_id)
    if run is None:
        return
    check_mode_access(run, await db.get(Mission, run.mission_id), team_scope(user))


async def _frame_of_run(db: AsyncSession, run_id: int) -> pd.DataFrame:
    rows = (await db.execute(
        select(RunTrack).where(RunTrack.run_id == run_id).order_by(RunTrack.seq_idx)
    )).scalars().all()
    if not rows:
        raise RunDataError(404, "아직 저장된 이동 기록이 없습니다.")
    return pd.DataFrame([{
        "seq_idx": r.seq_idx, "turn_idx": r.turn_idx, "agent_id": r.agent_id, "row": r.row, "col": r.col,
        "lat": r.lat, "lon": r.lon, "action": r.action, "ap": r.ap, "risk_grade": r.grade or "G",
        "normalized_c_total": r.total, "c_mob_prime": r.mob, "c_sen_prime": r.sen,
    } for r in rows])


async def load_run_data(db: AsyncSession, run_id: int, user: TokenPayload) -> RunData:
    run = await db.get(SimulationRun, run_id)
    if run is None:
        raise RunDataError(404, "run을 찾을 수 없습니다.")
    mission = await db.get(Mission, run.mission_id)
    team = team_scope(user)
    check_mode_access(run, mission, team)             # 기록을 읽기 전에 거부한다
    frame = await _frame_of_run(db, run_id)
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


async def build_assigned_mode(db: AsyncSession, mission_id: int) -> tuple[dict, list[tuple[float, float]], Mission, dict[str, str]]:
    """제대마다 지정된 모드의 기록을 합쳐 재생 데이터를 만든다 (재계산 없음).

    제대 i 의 기록은 지정된 모드의 실행에서 가져온다. 제대끼리 서로 영향을 주지 않는다는 가정(docs/formation_planner.md 의 검증)이 전제이고,
    실제로 이 조합을 한 번에 돌린 결과와는 운용자 대기열이나 난수 순서 때문에 조금 다를 수 있다.
    제대마다 순번(seq_idx)을 떼어 놓아 한 제대의 이벤트가 다른 제대의 것과 섞여 집계되지 않게 한다.
    """
    mission = await db.get(Mission, mission_id)
    if mission is None:
        raise RunDataError(404, "임무를 찾을 수 없습니다.")
    runs = (await db.execute(select(SimulationRun).where(SimulationRun.mission_id == mission_id).order_by(SimulationRun.id))).scalars().all()
    by_mode = {MODE_OF.get(r.selected_mode or "balanced", DEFAULT_TEAM_MODE): r for r in runs}
    modes = team_modes_of(mission)
    cache: dict[str, pd.DataFrame] = {}
    parts = []
    for i, team in enumerate(TEAMS):
        run = by_mode.get(modes[team])
        if run is None:
            raise RunDataError(409, f"{team} 제대에 지정된 {MODES[modes[team]]} 모드의 실행이 없습니다.")
        if run.status != "COMPLETED":
            raise RunDataError(409, f"{MODES[modes[team]]} 모드 실행이 아직 끝나지 않았습니다.")
        if modes[team] not in cache:
            cache[modes[team]] = await _frame_of_run(db, run.id)
        part = filter_team(cache[modes[team]], team)
        if not part.empty:
            if part.seq_idx.max() >= SEQ_STRIDE:
                raise RunDataError(500, "이동 기록이 너무 길어 제대별로 합칠 수 없습니다.")
            parts.append(part.assign(seq_idx=part.seq_idx + i * SEQ_STRIDE))
    if not parts:
        raise RunDataError(404, "합칠 이동 기록이 없습니다.")
    pois = await mission_pois(db, mission_id)
    from app.simulation.algo.sim_config import SimAlgoConfig

    poi_cells = [SimAlgoConfig.latlon_to_grid(lat, lon) for lat, lon in pois]
    mode_data = build_mode(pd.concat(parts, ignore_index=True), ASSIGNED_KEY, ASSIGNED_LABEL, poi_cells)
    return mode_data, pois, mission, modes


SERVER_MODE_OF = {v: k for k, v in MODE_OF.items()}          # balance → balanced, explore → recon, rush → rapid


async def assigned_server_mode(db: AsyncSession, user: TokenPayload) -> str | None:
    """통제관이면 가장 최근 임무에서 담당 제대에 지정된 모드(balanced | recon | rapid), 지휘관이면 None."""
    team = team_scope(user)
    if team is None:
        return None
    mission_id = (await db.execute(select(SimulationRun.mission_id).order_by(SimulationRun.id.desc()).limit(1))).scalar_one_or_none()
    mission = await db.get(Mission, mission_id) if mission_id is not None else None
    return SERVER_MODE_OF[team_modes_of(mission)[team]]
