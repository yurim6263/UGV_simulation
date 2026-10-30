"""
backend/app/simulation/replay.py

이동 기록(로그) → 프론트 재생 화면용 데이터.

입력은 팀원 시뮬레이션 CSV 든 엔진(run_episode)의 로그든 같은 컬럼을 가진 DataFrame 이면 된다:
    seq_idx, turn_idx, agent_id, row, col, lat, lon, action, ap, risk_grade,
    normalized_c_total, c_mob_prime, c_sen_prime  (+ 선택: rain_mmph, swvl1, sde_m, fog_prob, vis_class)

화면은 이 데이터만 읽는다. 서버 API(GET /api/runs/{id}/replay)가 이 형식을 쓴다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from PIL import Image

MODES = {"balance": "균형", "explore": "정밀", "rush": "신속"}
TEAMS = ["Alpha", "Bravo", "Charlie"]
SOS_ACTIONS = ("SOS_MOBILITY", "SOS_SENSOR", "SOS_COMPLEX_FAILURE")
GRADES = ["G", "A", "R"]
# 오버레이 색. 안전(G)은 거의 투명하게 해서 아래 지도가 비치고, 주의·고위험만 눈에 띄게 한다.
GAR = {"G": (63, 182, 139, 45), "A": (242, 181, 68, 135), "R": (240, 100, 78, 150)}
OVERLAY_COLUMNS = {"total": "normalized_c_total", "mobility": "c_mob_prime", "sensor": "c_sen_prime"}
OPTIONAL_COLUMNS = ["rain_mmph", "swvl1", "sde_m", "fog_prob", "vis_class"]


def log_to_frame(log: list[dict]) -> pd.DataFrame:
    return pd.DataFrame(log)


def _round(v, nd=4):
    return None if v is None or pd.isna(v) else round(float(v), nd)


def _episodes(df: pd.DataFrame) -> list[dict]:
    """UGV 별 SOS 에피소드를 찾아 시작/종료 턴을 계산한다. 종료 = 운용자 개입 시작 턴."""
    ops = df[df.action.str.startswith("INTERVENE")][["turn_idx", "seq_idx", "action"]].copy()
    ops["target"] = ops.action.str.split("->").str[1]
    episodes = []
    for ugv, g in df[df.agent_id.str.startswith("UGV")].sort_values(["turn_idx", "seq_idx"]).groupby("agent_id"):
        prev_action = None
        for r in g.itertuples(index=False):
            is_sos = r.action in SOS_ACTIONS
            # 수리/대기 상태(SOS_WAIT, BLIND) 다음에 다시 고장 행이 나오면 새 에피소드다 (수리 직후 재고장)
            if is_sos and (prev_action not in SOS_ACTIONS or prev_action is None):
                start = (int(r.turn_idx), int(r.seq_idx))
                end_turn = int(g.turn_idx.max())
                later = ops[(ops.target == ugv) & ((ops.turn_idx > start[0]) | ((ops.turn_idx == start[0]) & (ops.seq_idx >= start[1])))]
                if len(later):
                    end_turn = int(later.iloc[0].turn_idx)
                episodes.append({"ugv": ugv, "team": ugv.split("_")[1], "kind": r.action,
                                 "start_turn": start[0], "end_turn": end_turn, "wait_turns": end_turn - start[0]})
            prev_action = r.action
    return episodes


def build_mode(df: pd.DataFrame, mode: str, label: str, poi_cells: list[tuple]) -> dict:
    """모드(=한 번의 시뮬레이션 기록) 하나를 재생 데이터로 변환한다."""
    df = df.copy()
    for col in OPTIONAL_COLUMNS:
        if col not in df.columns:
            df[col] = np.nan
    df = df.sort_values(["turn_idx", "seq_idx", "agent_id"], kind="stable").reset_index(drop=True)

    agents = []
    for aid in sorted(df.agent_id.unique(), key=lambda a: (a.split("_")[0] != "Manned", a.split("_")[0] != "UGV", a)):
        kind, team, *no = aid.split("_")
        agents.append({"id": aid, "kind": kind, "team": team, "no": int(no[0]) if no else None})
    agent_idx = {a["id"]: i for i, a in enumerate(agents)}
    actions = sorted(df.action.unique())

    steps = [
        [int(r.turn_idx), int(r.seq_idx), agent_idx[r.agent_id], round(r.lat, 6), round(r.lon, 6),
         actions.index(r.action), int(r.ap), GRADES.index(r.risk_grade),
         _round(r.normalized_c_total), _round(r.c_mob_prime), _round(r.c_sen_prime),
         _round(r.rain_mmph), _round(r.swvl1), _round(r.sde_m), _round(r.fog_prob),
         -1 if pd.isna(r.vis_class) else int(r.vis_class)]
        for r in df.itertuples(index=False)
    ]

    turns = int(df.turn_idx.max()) + 1
    ugvs = df[df.agent_id.str.startswith("UGV")]
    episodes = _episodes(df)
    intervene = df[df.action.str.startswith("INTERVENE")]
    intervene_starts = int((intervene.action != intervene.action.shift()).sum()) if len(intervene) else 0

    # 도착 판정: ARRIVED/TEAM_DONE 은 유인기에만 기록되는 기록(CSV)이 있어, "UGV 의 마지막 위치가 정찰지 셀인가"로 판단한다.
    last = ugvs.sort_values(["turn_idx", "seq_idx"]).groupby("agent_id").tail(1)
    arrival_turn = {}
    for r in last.itertuples(index=False):
        cell = (int(r.row), int(r.col))
        if cell in poi_cells:
            first = ugvs[(ugvs.agent_id == r.agent_id) & (ugvs.row == cell[0]) & (ugvs.col == cell[1])]
            arrival_turn[r.agent_id] = int(first.turn_idx.min())
    team_poi = {}
    for t in TEAMS:
        cells = [(int(r.row), int(r.col)) for r in last[last.agent_id.str.contains(f"_{t}_")].itertuples(index=False)]
        modal = max(set(cells), key=cells.count) if cells else None
        team_poi[t] = poi_cells.index(modal) + 1 if modal in poi_cells else None

    sos_by_turn = [0] * turns
    for e in episodes:
        sos_by_turn[e["start_turn"]] += 1
    iv_by_turn = [0] * turns
    prev = None
    for r in intervene.itertuples(index=False):
        key = (r.agent_id, r.action)
        if key != prev:
            iv_by_turn[int(r.turn_idx)] += 1
        prev = key

    per_team = {}
    for t in TEAMS:
        ids = [a for a in ugvs.agent_id.unique() if f"_{t}_" in a]
        if not ids:
            continue
        arrived_ids = [a for a in ids if a in arrival_turn]
        te = [e for e in episodes if e["team"] == t]
        per_team[t] = {
            "ugv": len(ids), "arrived": len(arrived_ids), "poi": team_poi[t],
            "arrive_turn": max(arrival_turn[a] for a in arrived_ids) if arrived_ids else None,
            "sos": len(te),
            "wait_turns_mean": round(float(np.mean([e["wait_turns"] for e in te])), 2) if te else 0.0,
        }

    n_ugv = ugvs.agent_id.nunique()
    return {
        "mode": mode, "label": label, "agents": agents, "actions": actions, "grades": GRADES,
        "columns": ["turn", "seq", "agent", "lat", "lon", "action", "ap", "grade",
                    "total", "mob", "sen", "rain", "swvl1", "sde", "fog", "vis"],
        "steps": steps,
        "kpi": {
            "basis": "이 시뮬레이션 1회의 이동 기록에서 집계 (몬테카를로 평균 아님)",
            "turns": turns,
            "ugv_total": int(n_ugv),
            "ugv_arrived": len(arrival_turn),
            "arrival_rate": round(len(arrival_turn) / n_ugv, 3),
            "mission_turns": max(arrival_turn.values()) + 1 if arrival_turn else turns,
            "sos_events": len(episodes),
            "sos_mobility": sum(e["kind"] == "SOS_MOBILITY" for e in episodes),
            "sos_sensor": sum(e["kind"] == "SOS_SENSOR" for e in episodes),
            "interventions": intervene_starts,
            "wait_turns_mean": round(float(np.mean([e["wait_turns"] for e in episodes])), 2) if episodes else 0.0,
            "red_step_ratio": round(float((ugvs.risk_grade == "R").mean()), 3),
            "per_team": per_team,
            "timeline": {"sos": sos_by_turn, "intervene": iv_by_turn},
        },
    }


def grid_bounds(lat: np.ndarray, lon: np.ndarray) -> list[list[float]]:
    """셀 중심이 아니라 셀 가장자리 기준의 [[남,서],[북,동]] 경계."""
    half_lat = abs(float(np.nanmean(lat[1:, :] - lat[:-1, :]))) / 2
    half_lon = abs(float(np.nanmean(lon[:, 1:] - lon[:, :-1]))) / 2
    return [
        [float(np.nanmin(lat)) - half_lat, float(np.nanmin(lon)) - half_lon],
        [float(np.nanmax(lat)) + half_lat, float(np.nanmax(lon)) + half_lon],
    ]


def overlay_png(grid: np.ndarray, lo: float, hi: float) -> Image.Image:
    """위험도 격자(NaN=데이터 없음) → G/A/R 반투명 PNG."""
    rgba = np.zeros((*grid.shape, 4), dtype=np.uint8)
    ok = np.isfinite(grid)
    rgba[ok & (grid <= lo)] = GAR["G"]
    rgba[ok & (grid > lo) & (grid <= hi)] = GAR["A"]
    rgba[ok & (grid > hi)] = GAR["R"]
    return Image.fromarray(rgba, mode="RGBA")
