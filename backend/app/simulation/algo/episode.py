"""
backend/app/simulation/algo/episode.py

에피소드 시뮬레이터 (DB/서버와 무관한 순수 코어).

    run_episode(env, spec, genes, seed) -> EpisodeResult

구조: 3개 제대(Alpha/Bravo/Charlie) × [유인기 1 + 운용자(OP) 1 + UGV 2~4]
시간: 1턴 = 10분, 에이전트당 턴 AP 1,000,000. 잔여 AP 가 가장 큰 UGV 가 먼저 행동한다.
날씨: 계획은 실황+예보(Planning), 이동 결과 판정은 실황(Execution)으로 분리한다.

턴마다 제대별로:
  1) 운용자: 대기열의 UGV 를 우선순위대로 개입 (AP 소모). 개입한 UGV 는 다음 턴에 복귀.
  2) UGV: 턴 시작에 경로 재계획(산개 페널티 반영) → AP 가 남는 동안 한 칸씩 이동.
          칸에 들어갈 때마다 사고를 1회 판정(지연 평가). 사고가 나면 그 자리에서 SOS.
          유인기와의 거리로 대기(HOLD_PACE)/복귀(RECALL) 상태가 된다.
  3) 유인기: UGV 를 일정 거리(follow_gap) 뒤에서 따라간다. 제대 내 SOS 가 있으면 정지(HOLD_EMERGENCY).

기록(log)은 팀원 시뮬레이터의 이동 기록 CSV 와 같은 컬럼을 가져 재생 화면에서 바로 쓸 수 있다.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

import numpy as np
from scipy.ndimage import distance_transform_edt

from app.simulation.algo.ap_resolver import (
    AP_TURN, DIAGONAL_COEFF, ap_orthogonal, resolve_critical_event,
)
from app.simulation.algo.planner import GridPlanner
from app.simulation.algo.sim_config import SimAlgoConfig

TEAM_NAMES = ("Alpha", "Bravo", "Charlie")
CELL_KM = SimAlgoConfig.CELL_SIZE_M / 1000.0
DISPERSION_RADIUS_CELLS = 10        # 선행 UGV 경로 주변 2km 에 점유 페널티
INTERVENE_BASE_AP = 500_000         # 운용자 개입 기본 AP (악조건·원거리일수록 증가)
SENSOR_RADIUS_MAX = 10              # 센서 시야 최대 반경(셀) = 2km


@dataclass(frozen=True)
class Genes:
    """전술 유전자. NSGA-II 가 탐색할 값 (현재는 프리셋으로 지정)."""
    launch_delay: tuple = (0, 0, 0)       # 제대별 출격 지연(턴)
    dispersion_weight: float = 1.0        # 산개 가중치: UGV 간 경로 겹침을 피하는 강도
    weather_sensitivity: float = 1.0      # 기상 민감도: 계획 시 위험도를 몇 배로 볼지
    hold_km: float = 1.5                  # 유인기와 이 거리를 넘으면 대기
    recall_km: float = 1.8                # 이 거리 이상이면 유인기 쪽으로 복귀
    resume_km: float = 1.2                # 복귀 중 이 거리 이내가 되면 임무 재개


@dataclass(frozen=True)
class ScenarioSpec:
    start: tuple                           # (lat, lon)
    pois: tuple                            # ((lat, lon), ...) 정찰지
    formation: tuple = (3, 3, 3)           # 제대별 UGV 수
    assignment: tuple = (0, 1, 2)          # 제대별 목표 POI 인덱스
    max_turns: int = 24                    # 데드라인(턴)
    weather_scale: float = 1.0             # 시나리오 강도: 위험도 배율 (Clear≈0.15 / Moderate≈0.3 / Severe=1.0)
    dwell_turns: tuple = ()                # 제대별 정찰(체류) 시간(턴). 도착 후 이만큼 머문 뒤 임무 종료. 비우면 0
    follow_gap_cells: int = 5              # 유인기가 UGV 뒤에서 유지하는 거리(셀) = 1km


@dataclass
class EpisodeResult:
    log: list[dict]
    metrics: dict
    teams: list[str]
    poi_cells: list[tuple]
    start_cell: tuple
    start_time: datetime
    # 편성 계산기가 제대별 결과를 합칠 때 쓰는 값 (수색한 칸 마스크, 운용자 과부하였던 턴, 끝난 턴). 지표(metrics)에는 넣지 않는다.
    detail: dict | None = None


class _Unit:
    __slots__ = ("id", "kind", "team", "pos", "ap", "state", "path", "pi", "sos_kind", "sos_turn", "repair_turn", "arrived_turn")

    def __init__(self, uid: str, kind: str, team: str, pos: tuple):
        self.id, self.kind, self.team, self.pos = uid, kind, team, pos
        self.ap = AP_TURN
        self.state = "READY"        # READY | MISSION | RECALL | SOS | ARRIVED
        self.path: list = []
        self.pi = 0                 # path 안에서 현재 위치 인덱스
        self.sos_kind: str | None = None
        self.sos_turn: int | None = None
        self.repair_turn: int | None = None
        self.arrived_turn: int | None = None


class _Team:
    def __init__(self, name: str, idx: int, ugvs: list[_Unit], manned: _Unit, op: _Unit, target: tuple, launch: int):
        self.name, self.idx, self.ugvs, self.manned, self.op = name, idx, ugvs, manned, op
        self.target, self.launch = target, launch
        self.queue: list[_Unit] = []          # 운용자 개입을 기다리는 UGV
        self.dwell = 0                        # 정찰(체류) 턴 수
        self.arrived_turn: int | None = None  # 제대 전원(유인기 포함)이 정찰지에 도착한 턴
        self.done = False                     # 정찰까지 끝나 임무가 종료됨


def _planner_for(env) -> GridPlanner:
    pl = getattr(env, "_grid_planner", None)
    if pl is None:
        pl = GridPlanner(env.ny, env.nx, env.base_layer, env.blocked, env.config.NT)
        env._grid_planner = pl
    return pl


def risk_thresholds(env) -> tuple[float, float]:
    """G/A/R 등급 경계: 전체 실황 종합 위험도의 30/70 분위수 (오버레이 색과 같은 기준)."""
    cached = getattr(env, "_risk_thresholds", None)
    if cached is None:
        vals = np.concatenate([g[np.isfinite(g)] for g in env._actual["total"].values()])
        lo, hi = np.percentile(vals, [30, 70])
        cached = (float(lo), float(hi))
        env._risk_thresholds = cached
    return cached


def _dist_cells(a: tuple, b: tuple) -> float:
    return math.hypot(a[0] - b[0], a[1] - b[1])


def _valid_start(env, cell: tuple, mob0: np.ndarray) -> tuple:
    """시작 셀이 통행 불가/데이터 없음이면 가장 가까운 유효 셀로 옮긴다."""
    ok = (~env.blocked) & np.isfinite(mob0)
    if ok[cell]:
        return cell
    ys, xs = np.nonzero(ok)
    i = int(np.argmin((ys - cell[0]) ** 2 + (xs - cell[1]) ** 2))
    return int(ys[i]), int(xs[i])


def _spawn_cells(env, center: tuple, n: int, ok: np.ndarray) -> list[tuple]:
    """center 주변에서 서로 겹치지 않는 유효 셀 n개."""
    out, seen = [], set()
    for radius in range(0, 6):
        for dy in range(-radius, radius + 1):
            for dx in range(-radius, radius + 1):
                c = (center[0] + dy, center[1] + dx)
                if c in seen or not (0 <= c[0] < env.ny and 0 <= c[1] < env.nx) or not ok[c]:
                    continue
                seen.add(c)
                out.append(c)
                if len(out) == n:
                    return out
    return out + [center] * (n - len(out))


def run_episode(env, spec: ScenarioSpec, genes: Genes | None = None, seed: int = 0) -> EpisodeResult:
    genes = genes or Genes()
    rng = np.random.default_rng(seed)
    planner = _planner_for(env)
    lo, hi = risk_thresholds(env)
    start_time = env.start_time
    cfg = SimAlgoConfig

    start_cell = cfg.latlon_to_grid(*spec.start)
    poi_cells = [cfg.latlon_to_grid(lat, lon) for lat, lon in spec.pois]
    mob0 = env.latest_actual_at(start_time, "mob")
    start_cell = _valid_start(env, start_cell, mob0)
    ok_cells = (~env.blocked) & np.isfinite(mob0)

    # ── 편성 ─────────────────────────────────────────────────────────────
    teams: list[_Team] = []
    for ti, n_ugv in enumerate(spec.formation):
        name = TEAM_NAMES[ti]
        cells = _spawn_cells(env, start_cell, n_ugv + 1, ok_cells)
        ugvs = [_Unit(f"UGV_{name}_{i + 1}", "UGV", name, cells[i + 1]) for i in range(n_ugv)]
        manned = _Unit(f"Manned_{name}", "Manned", name, cells[0])
        op = _Unit(f"OP_{name}", "OP", name, cells[0])
        target = poi_cells[spec.assignment[ti]]
        team = _Team(name, ti, ugvs, manned, op, target, genes.launch_delay[ti] if ti < len(genes.launch_delay) else 0)
        team.dwell = spec.dwell_turns[ti] if ti < len(spec.dwell_turns) else 0
        teams.append(team)

    log: list[dict] = []
    seq = 0
    stats = {"sos": [], "interventions": 0, "waits": [], "op_ap_used": 0, "op_ap_avail": 0, "overload_turns": 0, "overload_set": []}
    visited: dict[tuple, int] = {}          # 셀 → 그 셀에서 본 최대 센서 반경 (V1)
    done_turn: int | None = None

    sc = float(spec.weather_scale)

    def grade(total: float) -> str:
        return "G" if total <= lo * sc else ("A" if total <= hi * sc else "R")

    def emit(turn: int, unit: _Unit, action: str, A_tot, A_mob, A_sen) -> None:
        nonlocal seq
        r, c = unit.pos
        lat, lon = cfg.grid_to_latlon(r, c)
        tot = float(A_tot[r, c])
        log.append({
            "seq_idx": seq, "turn_idx": turn, "agent_id": unit.id, "y": r, "x": c, "row": r, "col": c,
            "lat": lat, "lon": lon, "action": action, "ap": int(unit.ap),
            "normalized_c_total": tot, "c_mob_prime": float(A_mob[r, c]), "c_sen_prime": float(A_sen[r, c]),
            "risk_grade": grade(tot),
        })
        seq += 1

    def mark_visit(unit: _Unit, A_sen) -> None:
        r, c = unit.pos
        radius = int(np.clip(round(SENSOR_RADIUS_MAX * (1.0 - float(A_sen[r, c]))), 2, SENSOR_RADIUS_MAX))
        if visited.get((r, c), 0) < radius:
            visited[(r, c)] = radius

    for turn in range(spec.max_turns):
        t = start_time + timedelta(minutes=10 * turn)
        mob_plan = np.clip(env.time_cube(t, "mob") * sc, 0.0, 1.0)
        sen_plan = np.clip(env.time_cube(t, "sen") * sc, 0.0, 1.0)
        cube = planner.ap_cube(mob_plan, sen_plan, genes.weather_sensitivity)
        cube_plain = cube if genes.weather_sensitivity == 1.0 else planner.ap_cube(mob_plan, sen_plan, 1.0)

        # 실행(Execution) 레이어: 이동 결과는 실황으로 판정한다
        A_mob = np.clip(np.nan_to_num(env.latest_actual_at(t, "mob"), nan=0.0) * sc, 0.0, 1.0)
        A_sen = np.clip(np.nan_to_num(env.latest_actual_at(t, "sen"), nan=0.0) * sc, 0.0, 1.0)
        A_tot = np.clip(np.nan_to_num(env.latest_actual_at(t, "total"), nan=0.0) * sc, 0.0, 1.0)
        ap_actual = ap_orthogonal(A_mob, A_sen)

        def step_cost(a: tuple, b: tuple) -> int:
            diag = a[0] != b[0] and a[1] != b[1]
            return int(ap_actual[b] * (DIAGONAL_COEFF if diag else 1.0))

        any_overload = False
        for tm in teams:
            for u in (*tm.ugvs, tm.manned):
                u.ap = AP_TURN

            # 출격 전
            if turn < tm.launch:
                for u in (*tm.ugvs, tm.manned, tm.op):
                    emit(turn, u, "IDLE", A_tot, A_mob, A_sen)
                continue
            for u in tm.ugvs:
                if u.state == "READY":
                    u.state = "MISSION"

            # 1) 운용자 개입 -------------------------------------------------
            for u in tm.ugvs:                       # 지난 턴에 개입한 UGV 는 이번 턴에 복귀
                if u.state == "SOS" and u.repair_turn is not None and u.repair_turn < turn:
                    u.state, u.sos_kind, u.repair_turn, u.sos_turn = "MISSION", None, None, None
            op_ap = AP_TURN
            queue = sorted((u for u in tm.queue), key=lambda u: u.sos_turn)
            tm.queue = []
            served_this_turn: list[_Unit] = []
            for u in queue:
                r, c = u.pos
                d_km = _dist_cells(u.pos, tm.manned.pos) * CELL_KM
                risk = float(ap_orthogonal(A_mob[r, c], A_sen[r, c]) - 80_000) / 320_000  # 0~1 환산 위험
                cost = int(INTERVENE_BASE_AP * (1.0 + 0.5 * risk + 0.15 * d_km))
                if op_ap >= cost:
                    op_ap -= cost
                    stats["op_ap_used"] += cost
                    stats["interventions"] += 1
                    stats["waits"].append(turn - u.sos_turn)
                    u.repair_turn = turn
                    served_this_turn.append(u)
                    tm.op.pos = tm.manned.pos
                    tm.op.ap = op_ap
                    emit(turn, tm.op, f"INTERVENE->{u.id}", A_tot, A_mob, A_sen)
                else:
                    tm.queue.append(u)
            stats["op_ap_avail"] += AP_TURN
            if tm.queue:
                any_overload = True
            if not served_this_turn:
                tm.op.pos, tm.op.ap = tm.manned.pos, op_ap
                emit(turn, tm.op, "IDLE", A_tot, A_mob, A_sen)

            # 2) 경로 재계획 (산개 페널티 반영) ---------------------------------
            penalty = np.zeros((env.ny, env.nx))
            for u in tm.ugvs:
                if u.state not in ("MISSION", "RECALL"):
                    continue
                goal = tm.manned.pos if u.state == "RECALL" else tm.target
                plan = planner.plan(cube, u.pos, goal, penalty if genes.dispersion_weight > 0 else None)
                u.path, u.pi = plan.cells, 0
                if plan.reachable and genes.dispersion_weight > 0:
                    mask = np.ones((env.ny, env.nx), dtype=bool)
                    for cell in plan.cells:
                        mask[cell] = False
                    d = distance_transform_edt(mask)
                    penalty += genes.dispersion_weight * np.clip(1.0 - d / DISPERSION_RADIUS_CELLS, 0.0, 1.0)
            mplan = planner.plan(cube_plain, tm.manned.pos, tm.target)
            tm.manned.path, tm.manned.pi = mplan.cells, 0

            # 3) UGV 이동: 잔여 AP 가 가장 큰 개체부터 한 칸씩 ---------------------
            active = [u for u in tm.ugvs if u.state in ("MISSION", "RECALL")]
            held: set[str] = set()
            no_ap: set[str] = set()
            moved = False                       # 이번 턴에 유인기가 움직였는지
            guard = 0
            while guard < 5000:
                guard += 1
                runnable = [u for u in active if u.id not in held and u.id not in no_ap and u.state in ("MISSION", "RECALL")]
                if not runnable:
                    break
                u = max(runnable, key=lambda x: (x.ap, -tm.ugvs.index(x)))
                d_km = _dist_cells(u.pos, tm.manned.pos) * CELL_KM

                if u.state == "RECALL" and d_km <= genes.resume_km:        # 복귀 완료 → 임무 재개
                    u.state = "MISSION"
                    plan = planner.plan(cube, u.pos, tm.target)
                    u.path, u.pi = plan.cells, 0
                elif u.state == "MISSION" and d_km >= genes.recall_km:     # 통신 한계 → 복귀
                    u.state = "RECALL"
                    plan = planner.plan(cube_plain, u.pos, tm.manned.pos)
                    u.path, u.pi = plan.cells, 0
                    emit(turn, u, "RECALL", A_tot, A_mob, A_sen)
                    continue
                elif (u.state == "MISSION" and d_km > genes.hold_km        # 유인기보다 앞서 있으면 기다림
                      and _dist_cells(u.pos, tm.target) < _dist_cells(tm.manned.pos, tm.target)):
                    emit(turn, u, "HOLD_PACE", A_tot, A_mob, A_sen)
                    held.add(u.id)
                    continue

                if u.pi >= len(u.path) - 1:                                # 경로 끝 또는 경로 없음
                    if u.state == "MISSION" and u.pos == tm.target:
                        u.state, u.arrived_turn = "ARRIVED", turn
                        emit(turn, u, "ARRIVED", A_tot, A_mob, A_sen)
                    elif u.state == "RECALL":                              # 유인기 위치에 도달했거나 경로 없음
                        u.state = "MISSION" if d_km <= genes.recall_km else "RECALL"
                        held.add(u.id)
                    else:
                        emit(turn, u, "NO_PATH", A_tot, A_mob, A_sen)
                        no_ap.add(u.id)
                    continue

                nxt = u.path[u.pi + 1]
                cost = step_cost(u.pos, nxt)
                if u.ap < cost:
                    u.ap = 0
                    emit(turn, u, "NO_AP", A_tot, A_mob, A_sen)
                    no_ap.add(u.id)
                    continue
                u.pos, u.ap, u.pi = nxt, u.ap - cost, u.pi + 1
                mark_visit(u, A_sen)

                event = resolve_critical_event(A_mob[nxt], A_sen[nxt], rng)   # 타일 진입 시 1회 판정
                if event != "NORMAL":
                    u.state, u.sos_kind, u.sos_turn, u.ap = "SOS", event, turn, 0
                    tm.queue.append(u)
                    stats["sos"].append({"team": tm.name, "ugv": u.id, "kind": event, "turn": turn})
                    emit(turn, u, event, A_tot, A_mob, A_sen)
                else:
                    emit(turn, u, "RECALL" if u.state == "RECALL" else "MISSION", A_tot, A_mob, A_sen)
                    if u.state == "MISSION" and u.pos == tm.target:
                        u.state, u.arrived_turn = "ARRIVED", turn
                        emit(turn, u, "ARRIVED", A_tot, A_mob, A_sen)

                moved |= _follow(tm, spec, A_tot, A_mob, A_sen, step_cost, emit, turn, mark_visit)

            # 4) 턴 마무리: 이동하지 못한 개체의 상태 기록 --------------------------
            moved |= _follow(tm, spec, A_tot, A_mob, A_sen, step_cost, emit, turn, mark_visit)
            for u in tm.ugvs:
                if u.state == "SOS" and u.sos_turn != turn:        # 개입 대기 중이거나 이번 턴에 개입을 받는 중
                    emit(turn, u, "BLIND" if u.sos_kind == "SOS_SENSOR" else "SOS_WAIT", A_tot, A_mob, A_sen)
            unsafe = any(u.state in ("SOS", "RECALL") for u in tm.ugvs)
            all_arrived = all(u.state == "ARRIVED" for u in tm.ugvs)
            if tm.done:
                emit(turn, tm.manned, "TEAM_DONE", A_tot, A_mob, A_sen)
            elif tm.arrived_turn is not None:               # 도착 후 정찰 중: UGV 는 정찰지 주변을 훑는다
                for u in tm.ugvs:
                    mark_visit(u, A_sen)
                    emit(turn, u, "PATROL", A_tot, A_mob, A_sen)
                emit(turn, tm.manned, "IDLE", A_tot, A_mob, A_sen)
                if turn - tm.arrived_turn >= tm.dwell:
                    tm.done = True
            elif all_arrived and _dist_cells(tm.manned.pos, tm.target) <= spec.follow_gap_cells:
                tm.arrived_turn = turn
                emit(turn, tm.manned, "ARRIVED", A_tot, A_mob, A_sen)
                if tm.dwell == 0:
                    tm.done = True
            elif unsafe:
                emit(turn, tm.manned, "HOLD_EMERGENCY", A_tot, A_mob, A_sen)
            elif not moved:
                emit(turn, tm.manned, "IDLE", A_tot, A_mob, A_sen)

        if any_overload:
            stats["overload_turns"] += 1
            stats["overload_set"].append(turn)
        if all(tm.done for tm in teams):
            done_turn = turn
            break

    detail: dict = {}
    return EpisodeResult(
        log=log,
        metrics=_metrics(env, spec, teams, stats, visited, done_turn, log, detail),
        teams=[t.name for t in teams],
        poi_cells=poi_cells,
        start_cell=start_cell,
        start_time=start_time,
        detail={**detail, "overload_turns": list(stats["overload_set"]), "done_turn": done_turn},
    )


def _follow(tm: _Team, spec: ScenarioSpec, A_tot, A_mob, A_sen, step_cost, emit, turn: int, mark_visit) -> bool:
    """유인기가 UGV 뒤 follow_gap 거리를 유지하며 따라간다. 제대 내 SOS/복귀가 있으면 정지. 움직였으면 True."""
    m = tm.manned
    moved = False
    if any(u.state in ("SOS", "RECALL") for u in tm.ugvs):
        return moved
    while m.pi < len(m.path) - 1:
        nxt = m.path[m.pi + 1]
        active = [u for u in tm.ugvs if u.state != "ARRIVED"]
        if active:
            # 가장 먼 UGV 까지의 거리가 follow_gap 이내가 되면 멈춘다 (중심점 기준이면 선두 UGV 가
            # 목줄 한계(hold_km)에 걸려 서로 기다리는 교착이 생긴다)
            if max(_dist_cells(m.pos, u.pos) for u in active) <= spec.follow_gap_cells:
                return moved
            if _dist_cells(nxt, tm.target) < min(_dist_cells(u.pos, tm.target) for u in active):
                return moved                                               # 선두 UGV 보다 앞서지 않는다
        elif _dist_cells(m.pos, tm.target) <= spec.follow_gap_cells:
            return moved
        cost = step_cost(m.pos, nxt)
        if m.ap < cost:
            if m.ap > 0:
                m.ap = 0
                emit(turn, m, "NO_AP", A_tot, A_mob, A_sen)
                moved = True
            return moved
        m.pos, m.ap, m.pi = nxt, m.ap - cost, m.pi + 1
        mark_visit(m, A_sen)
        emit(turn, m, "MISSION", A_tot, A_mob, A_sen)
        moved = True
    return moved


def _metrics(env, spec: ScenarioSpec, teams: list[_Team], stats: dict, visited: dict, done_turn, log: list, detail: dict | None = None) -> dict:
    ugvs = [u for tm in teams for u in tm.ugvs]
    arrived = [u for u in ugvs if u.state == "ARRIVED"]
    turns_used = (done_turn if done_turn is not None else spec.max_turns - 1) + 1
    completed = done_turn is not None and len(arrived) == len(ugvs)

    # V1: 센서로 훑은 면적 비율 (시야 반경은 위험도에 따라 줄어든다)
    arsenal = env.mask_arsenal()
    seen = np.zeros((env.ny, env.nx), dtype=bool)
    for (r, c), radius in visited.items():
        mask = arsenal[radius]
        top, left = r - radius, c - radius
        y0, y1 = max(0, top), min(env.ny, r + radius + 1)
        x0, x1 = max(0, left), min(env.nx, c + radius + 1)
        seen[y0:y1, x0:x1] |= mask[y0 - top:y1 - top, x0 - left:x1 - left]
    valid = (~env.blocked) & np.isfinite(env.latest_actual_at(env.start_time, "mob"))
    coverage = float((seen & valid).sum() / max(1, valid.sum()))
    if detail is not None:
        detail["seen"] = seen & valid                       # 합집합을 구할 수 있게 마스크를 내보낸다
        detail["valid_cells"] = int(valid.sum())

    waits = stats["waits"]
    per_team = {}
    for tm in teams:
        ev = [e for e in stats["sos"] if e["team"] == tm.name]
        per_team[tm.name] = {
            "ugv": len(tm.ugvs),
            "arrived": sum(u.state == "ARRIVED" for u in tm.ugvs),
            "arrive_turn": max((u.arrived_turn for u in tm.ugvs if u.arrived_turn is not None), default=None),
            "sos": len(ev),
        }
    return {
        "completed": completed,
        "turns": turns_used,
        "ugv_total": len(ugvs),
        "ugv_arrived": len(arrived),
        "arrival_rate": round(len(arrived) / len(ugvs), 3),
        "sos_events": len(stats["sos"]),
        "sos_by_kind": {k: sum(e["kind"] == k for e in stats["sos"]) for k in ("SOS_MOBILITY", "SOS_SENSOR", "SOS_COMPLEX_FAILURE")},
        "interventions": stats["interventions"],
        "wait_turns_mean": round(float(np.mean(waits)), 2) if waits else 0.0,
        "operator_utilization": round(stats["op_ap_used"] / max(1, stats["op_ap_avail"]), 3),
        # 최적화 목표 (NSGA-II)
        "v1_coverage": round(coverage, 4),                       # 최대화
        "v2_minutes": turns_used * 10,                           # 최소화
        "v3_overload_minutes": stats["overload_turns"] * 10,     # 최소화: 대기열이 처리되지 못하고 남은 시간
        "per_team": per_team,
    }
