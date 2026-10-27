"""
backend/app/simulation/real_runner.py

엔진(algo/episode.py)을 사용한 시뮬레이션 실행기. orchestrator 에서 SIMULATION_MODE=real 일 때 호출한다.

흐름:
  1. 임무(DB) → 시나리오: 출발지, 정찰지(목표), 편성, 모드(유전자), 날씨 강도
  2. 엔진 실행 (CPU 작업이므로 스레드에서) — 선택한 모드와, 날씨를 무시하는 기준선(A/B 비교용) 두 번
  3. 이동/이벤트 기록(run_tracks)을 DB 에 저장
  4. 턴마다 WebSocket 으로 흘려보내며 스냅샷/유닛/대기열/SOS 를 갱신 (실행 중 취소하면 즉시 중단)
  5. 엔진 지표로 KPI 확정 — 랜덤/상수 값은 쓰지 않는다

환경변수:
  SIM_WEATHER_SCALE   clear | moderate(기본) | severe 또는 0~1 숫자 (날씨 강도, algo/presets.py 참고)
  SIM_TICK_SLEEP      턴 사이 대기 초 (기본 0.5, 테스트는 0)
"""

import asyncio
import logging
import math
import os
from collections import defaultdict
from dataclasses import replace
from datetime import datetime, timezone

from sqlalchemy import delete, select

from app.core.websocket_manager import ws_manager
from app.db.models.mission import Mission, MissionTarget
from app.db.models.patrol import RunPatrolEvent
from app.db.models.route import RunKpi, RunRecommendation, RunRoute, RunRouteEffect
from app.db.models.simulation_run import SimulationRun
from app.db.models.snapshot import RunStatusSnapshot, RunTimeSeriesPanel
from app.db.models.track import RunTrack
from app.db.models.unit_state import RunQueueEvent, RunSosEvent, RunUnit
from app.db.session import AsyncSessionLocal
from app.simulation.algo.episode import TEAM_NAMES, Genes, ScenarioSpec, run_episode
from app.simulation.contracts import WsEvent, make_event
from app.simulation.presets import DEFAULT_POIS, MODE_PRESETS, WEATHER_SCALES, preset
from app.simulation.shared_env import get_environment

logger = logging.getLogger(__name__)

SOS_ACTIONS = ("SOS_MOBILITY", "SOS_SENSOR", "SOS_COMPLEX_FAILURE")
# DB 의 selected_mode 값 → 프리셋 키
MODE_ALIASES = {"balanced": "balance", "balance": "balance", "recon": "explore", "explore": "explore",
                "rapid": "rush", "rush": "rush"}


def _tick_sleep() -> float:
    return float(os.getenv("SIM_TICK_SLEEP", "0.5"))


def _weather_scale() -> float:
    raw = os.getenv("SIM_WEATHER_SCALE", "moderate")
    return WEATHER_SCALES.get(raw) if raw in WEATHER_SCALES else float(raw)


# ── 시나리오 구성 ────────────────────────────────────────────────────────

def even_split(total: int, parts: int) -> tuple:
    base, extra = divmod(total, parts)
    return tuple(base + (1 if i < extra else 0) for i in range(parts))


def build_scenario(mission: dict, mode: str, weather_scale: float) -> tuple[ScenarioSpec, Genes]:
    """임무 정보 → (ScenarioSpec, Genes). 목표 수만큼 제대를 만들고(최대 3) UGV 를 나눠 배정한다."""
    pois = [tuple(p) for p in mission["targets"]] or list(DEFAULT_POIS)
    n_teams = max(1, min(3, len(pois), mission["total_ugv"]))
    pois = pois[:n_teams]
    spec, genes = preset(
        mode, weather_scale=weather_scale,
        max_turns=max(6, min(31, mission["duration_min"] // 10)),
        start=(mission["departure_lat"], mission["departure_lon"]), pois=pois,
    )
    preset_formation = MODE_PRESETS[mode]["formation"]
    if n_teams == len(preset_formation) and sum(preset_formation) == mission["total_ugv"]:
        formation, assignment = preset_formation, MODE_PRESETS[mode]["assignment"]
    else:                                   # 편성이 프리셋과 다르면 균등 분배, 제대 i → 목표 i
        formation, assignment = even_split(mission["total_ugv"], n_teams), tuple(range(n_teams))
    # 정찰 시간: 제대 i 가 향하는 목표의 patrol_duration_sec 를 턴(10분)으로 올림
    patrol = mission.get("patrol_sec") or []
    dwell = tuple(
        math.ceil(patrol[assignment[i]] / 600) if assignment[i] < len(patrol) else 0
        for i in range(n_teams)
    )
    return replace(spec, pois=tuple(pois), formation=formation, assignment=assignment, dwell_turns=dwell), genes


def baseline_genes() -> Genes:
    """A/B 비교용 기준선: 날씨를 고려하지 않고(민감도 0) 경로를 분산하지도 않는 '무식한 돌파형'."""
    return Genes(weather_sensitivity=0.0, dispersion_weight=0.0)


# ── 진입점 ───────────────────────────────────────────────────────────────

async def run_real(run_id: int) -> None:
    logger.info("real_runner started run_id=%d", run_id)
    mission, mode_key = await _load_mission(run_id)
    spec, genes = build_scenario(mission, mode_key, _weather_scale())

    await _reset_outputs(run_id)          # 같은 run 을 다시 실행해도 이전 산출물이 중복되지 않게
    env = await asyncio.to_thread(get_environment)
    seed = run_id
    result = await asyncio.to_thread(run_episode, env, spec, genes, seed)
    baseline = await asyncio.to_thread(run_episode, env, spec, baseline_genes(), seed)

    units = _unit_table(result)
    await _save_tracks(run_id, result.log)
    completed = await _stream(run_id, result, units, mission, spec)
    if completed:
        await _finalize(run_id, result, baseline, units, mode_key, genes)
    logger.info("real_runner finished run_id=%d completed=%s", run_id, completed)


async def _load_mission(run_id: int) -> tuple[dict, str]:
    async with AsyncSessionLocal() as db:
        run = (await db.execute(select(SimulationRun).where(SimulationRun.id == run_id))).scalar_one_or_none()
        if run is None:
            raise ValueError(f"run_id={run_id} not found")
        mission = await db.get(Mission, run.mission_id)
        if mission is None:
            raise ValueError(f"mission_id={run.mission_id} not found")
        targets = (await db.execute(
            select(MissionTarget).where(MissionTarget.mission_id == mission.id).order_by(MissionTarget.seq)
        )).scalars().all()
        mode = MODE_ALIASES.get(run.selected_mode or "balanced", "balance")
        return {
            "total_ugv": max(1, mission.total_ugv),
            "departure_lat": mission.departure_lat,
            "departure_lon": mission.departure_lon,
            "targets": [(t.lat, t.lon) for t in targets],
            "patrol_sec": [t.patrol_duration_sec for t in targets],
            "duration_min": mission.mission_duration_min,
        }, mode


# ── 기록 ─────────────────────────────────────────────────────────────────

def _unit_table(result) -> dict:
    """UGV agent_id → (unit_no, asset_code). 제대 순서(Alpha, Bravo, Charlie) → 번호 순."""
    ids = sorted({r["agent_id"] for r in result.log if r["agent_id"].startswith("UGV_")})
    return {agent: (i + 1, f"UGV-{agent}") for i, agent in enumerate(ids)}


async def _reset_outputs(run_id: int) -> None:
    """이전 실행이 남긴 산출물을 지운다 (run 자체와 임무 정보는 유지)."""
    async with AsyncSessionLocal() as db:
        for model in (RunTrack, RunKpi, RunRouteEffect, RunRecommendation, RunRoute, RunStatusSnapshot,
                      RunTimeSeriesPanel, RunQueueEvent, RunSosEvent, RunPatrolEvent, RunUnit):
            await db.execute(delete(model).where(model.run_id == run_id))
        await db.commit()


async def _save_tracks(run_id: int, log: list[dict]) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            RunTrack(
                run_id=run_id, turn_idx=r["turn_idx"], seq_idx=r["seq_idx"], agent_id=r["agent_id"],
                row=r["row"], col=r["col"], lat=r["lat"], lon=r["lon"], action=r["action"], ap=r["ap"],
                total=r["normalized_c_total"], mob=r["c_mob_prime"], sen=r["c_sen_prime"], grade=r["risk_grade"],
            )
            for r in log
        )
        await db.commit()


def _unit_status(action: str) -> str:
    if action in SOS_ACTIONS:
        return "SOS"
    if action in ("SOS_WAIT", "BLIND"):
        return "QUEUED"
    if action == "ARRIVED":
        return "DONE"
    return "MOVING"


async def _is_cancelled(run_id: int) -> bool:
    async with AsyncSessionLocal() as db:
        run = (await db.execute(select(SimulationRun).where(SimulationRun.id == run_id))).scalar_one_or_none()
        return run is None or run.status in ("CANCELLED", "FAILED")


async def _stream(run_id: int, result, units: dict, mission: dict, spec: ScenarioSpec) -> bool:
    """턴 단위로 기록을 DB/WebSocket 에 반영한다. 실행 중 취소되면 False."""
    by_turn = defaultdict(list)
    for r in result.log:
        by_turn[r["turn_idx"]].append(r)
    total_turns = result.metrics["turns"]
    total_ugv = len(units)

    last_row: dict[str, dict] = {}
    arrived: set[str] = set()
    had_sos: set[str] = set()
    open_sos: dict[str, int] = {}       # 개입을 기다리는 UGV → SOS 가 난 턴
    aoi_total_sec = mission["duration_min"] * 60

    for turn in range(total_turns):
        if await _is_cancelled(run_id):
            logger.info("real_runner cancelled run_id=%d at turn %d", run_id, turn)
            return False
        await asyncio.sleep(_tick_sleep())

        alerts, queue_enter, queue_exit, patrol_new = [], [], [], []
        for r in by_turn.get(turn, []):
            agent = r["agent_id"]
            if agent.startswith("UGV_"):
                last_row[agent] = r
                if r["action"] == "ARRIVED":
                    arrived.add(agent)
                    patrol_new.append(r)
                if r["action"] in SOS_ACTIONS:
                    had_sos.add(agent)
                    open_sos[agent] = turn
                    queue_enter.append(r)
                    alerts.append(f"[SOS] {agent}: {r['action']}")
                elif r["action"] == "RECALL":
                    alerts.append(f"[복귀] {agent}: 통신 한계 — 유인기 쪽으로 복귀")
            elif r["action"].startswith("INTERVENE->"):
                target = r["action"].split("->")[1]
                if target in open_sos:
                    queue_exit.append((target, (turn - open_sos.pop(target)) * 600, r))

        progress = int((turn + 1) / total_turns * 100)
        success_rate = round(len(arrived) / max(1, total_ugv) * 100, 1)
        damage_rate = round(len(had_sos) / max(1, total_ugv) * 100, 1)   # 고장을 겪은 UGV 비율
        queue_len = len(open_sos)
        remaining = max(0, (total_turns - turn - 1) * 600)

        async with AsyncSessionLocal() as db:
            db.add(RunStatusSnapshot(
                run_id=run_id, status="RUNNING", phase="EXECUTION", progress_pct=progress,
                mission_success_rate=success_rate, asset_damage_rate=damage_rate,
                remaining_time_sec=remaining,
                aoi_remaining_sec=max(0, int(aoi_total_sec * (1 - (turn + 1) / total_turns))),
                queue_length=queue_len,
            ))
            for agent, (unit_no, code) in units.items():
                row = last_row.get(agent)
                if row is None:
                    continue
                unit = (await db.execute(select(RunUnit).where(RunUnit.run_id == run_id, RunUnit.unit_no == unit_no))).scalar_one_or_none()
                status = _unit_status(row["action"]) if agent not in arrived else "DONE"
                if unit is None:
                    db.add(RunUnit(run_id=run_id, unit_no=unit_no, asset_code=code, status=status, lat=row["lat"], lon=row["lon"]))
                else:
                    unit.status, unit.lat, unit.lon = status, row["lat"], row["lon"]
            for r in queue_enter:
                code = units[r["agent_id"]][1]
                db.add(RunQueueEvent(run_id=run_id, asset_code=code, event_type="ENTER", wait_time_sec=0))
                db.add(RunSosEvent(run_id=run_id, unit_no=units[r["agent_id"]][0], asset_code=code,
                                   event_type="SOS", lat=r["lat"], lon=r["lon"]))
            for agent, wait_sec, r in queue_exit:
                code = units[agent][1]
                db.add(RunQueueEvent(run_id=run_id, asset_code=code, event_type="EXIT", wait_time_sec=wait_sec))
                sos_rows = (await db.execute(select(RunSosEvent).where(
                    RunSosEvent.run_id == run_id, RunSosEvent.unit_no == units[agent][0],
                    RunSosEvent.resolved_at.is_(None)))).scalars().all()
                for ev in sos_rows:
                    ev.event_type, ev.resolved_at = "SOS_RESOLVED", datetime.now(timezone.utc)
            for r in patrol_new:                  # 정찰지 도착 → 정찰 카운트다운 시작
                ti = TEAM_NAMES.index(r["agent_id"].split("_")[1])
                poi = spec.assignment[ti]
                dwell = spec.dwell_turns[ti] if ti < len(spec.dwell_turns) else 0
                db.add(RunPatrolEvent(
                    run_id=run_id, unit_no=units[r["agent_id"]][0], asset_code=units[r["agent_id"]][1],
                    target_seq=poi + 1, target_lat=spec.pois[poi][0], target_lon=spec.pois[poi][1],
                    patrol_duration_sec=max(1, dwell * 600),
                ))
            for slot, ahead in zip(("T0", "T1", "T2", "T3"), (0, 6, 12, 18)):
                # 시뮬레이션을 미리 돌려 둔 결과의 값이다 (예측 모델의 출력이 아님)
                db.add(RunTimeSeriesPanel(run_id=run_id, panel_type=slot, data={
                    "success_rate": success_rate, "damage_rate": damage_rate, "tick": turn,
                    "lookahead_turns": ahead, "basis": "episode_lookahead",
                }))
            await db.commit()

        for agent, (unit_no, code) in units.items():
            row = last_row.get(agent)
            if row is None:
                continue
            await ws_manager.broadcast(run_id, make_event(WsEvent.RUN_PROGRESS, run_id, {
                "unit_no": unit_no, "asset_code": code,
                "status": "DONE" if agent in arrived else _unit_status(row["action"]),
                "lat": row["lat"], "lon": row["lon"], "action": row["action"], "risk_grade": row["risk_grade"],
            }))
        await ws_manager.broadcast(run_id, make_event(WsEvent.RUN_PROGRESS, run_id, {
            "status": "RUNNING", "phase": "EXECUTION", "progress_pct": progress,
            "mission_success_rate": success_rate, "asset_damage_rate": damage_rate,
            "remaining_time_sec": remaining, "queue_length": queue_len,
        }))
        for text in alerts:
            await ws_manager.broadcast(run_id, make_event(WsEvent.ALERT_CREATED, run_id, {"alert_type": "sos", "message": text}))
    return True


async def _finalize(run_id: int, result, baseline, units: dict, mode: str, genes: Genes) -> None:
    m, b = result.metrics, baseline.metrics
    success = round(m["arrival_rate"] * 100, 1)
    base_success = round(b["arrival_rate"] * 100, 1)
    sos_ugvs = {r["agent_id"] for r in result.log if r["action"] in SOS_ACTIONS and r["agent_id"].startswith("UGV_")}
    damage = round(len(sos_ugvs) / max(1, m["ugv_total"]) * 100, 1)
    base_sos = {r["agent_id"] for r in baseline.log if r["action"] in SOS_ACTIONS and r["agent_id"].startswith("UGV_")}
    base_damage = round(len(base_sos) / max(1, b["ugv_total"]) * 100, 1)

    async with AsyncSessionLocal() as db:
        run = (await db.execute(select(SimulationRun).where(SimulationRun.id == run_id))).scalar_one_or_none()
        if run and run.status == "RUNNING":
            run.status, run.progress_pct, run.finished_at = "COMPLETED", 100, datetime.now(timezone.utc)

        waits = [r for r in result.log if r["action"].startswith("INTERVENE->")]
        db.add(RunKpi(
            run_id=run_id, success_rate=success, damage_rate=damage, makespan_sec=m["turns"] * 600,
            queue_kpi={
                "avg_wait_sec": round(m["wait_turns_mean"] * 600), "total_events": m["sos_events"],
                "interventions": len(waits), "operator_utilization": m["operator_utilization"],
                "v1_coverage": m["v1_coverage"], "v2_minutes": m["v2_minutes"], "v3_overload_minutes": m["v3_overload_minutes"],
            },
            bottleneck_index=round(m["v3_overload_minutes"] / max(1, m["turns"] * 10), 3),
        ))
        # 날씨를 고려한 경로 vs 날씨를 무시한 기준선 (같은 시드)
        db.add(RunRouteEffect(
            run_id=run_id, optimal_success_rate=success, optimal_damage_rate=damage,
            alt_success_rate=base_success, alt_damage_rate=base_damage,
            success_rate_delta=round(success - base_success, 1), damage_rate_delta=round(damage - base_damage, 1),
        ))
        db.add(RunRecommendation(run_id=run_id, score=m["arrival_rate"], is_selected=True, rationale={
            "algo": "episode_engine", "mode": mode, "baseline": "weather_blind",
            "genes": genes.__dict__, "metrics": {k: m[k] for k in ("v1_coverage", "v2_minutes", "v3_overload_minutes")},
        }))

        paths = defaultdict(list)
        for r in result.log:
            if r["agent_id"] in units and (not paths[r["agent_id"]] or paths[r["agent_id"]][-1] != [r["lon"], r["lat"]]):
                paths[r["agent_id"]].append([r["lon"], r["lat"]])
        for agent, coords in paths.items():
            db.add(RunRoute(run_id=run_id, unit_no=units[agent][0], route_type="ACTUAL", geojson={
                "type": "Feature", "geometry": {"type": "LineString", "coordinates": coords},
                "properties": {"unit_no": units[agent][0], "agent_id": agent},
            }))
        await db.commit()

    await ws_manager.broadcast(run_id, make_event(WsEvent.RUN_FINISHED, run_id, {
        "status": "COMPLETED", "phase": "DONE", "progress_pct": 100,
        "mission_success_rate": success, "asset_damage_rate": damage, "remaining_time_sec": 0, "queue_length": 0,
    }))
