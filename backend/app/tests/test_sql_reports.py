"""
backend/app/tests/test_sql_reports.py

실행 기록(run_tracks) SQL 분석 테스트. 손으로 정답을 셀 수 있는 작은 합성 기록을 넣고 쿼리 결과를 정확히 비교한다.
시뮬레이션 환경을 읽지 않아 빠르다.

기록 (run A):
  seq turn agent          action                    cell  total grade
   1   0   UGV_Alpha_1    MISSION                   (4,4)  0.20  G
   2   0   UGV_Alpha_1    SOS_SENSOR                (5,5)  0.70  R
   3   1   UGV_Alpha_1    BLIND                     (5,5)  0.70  R
   4   2   OP_Alpha       INTERVENE->UGV_Alpha_1    (5,5)  0.70  R     ← Alpha_1 은 2턴 기다렸다
   5   3   UGV_Alpha_1    MISSION                   (6,5)  0.40  A
   6   1   UGV_Bravo_1    SOS_MOBILITY              (5,5)  0.65  R
   7   5   OP_Bravo       INTERVENE->UGV_Bravo_1    (5,5)  0.65  R     ← Bravo_1 은 4턴 기다렸다
   8   2   UGV_Bravo_2    SOS_MOBILITY              (6,6)  0.50  A     ← 끝내 개입을 받지 못했다
"""

import pytest
from httpx import AsyncClient

from app.analysis.sql_reports import mode_comparison, run_report
from app.db.models.track import RunTrack
from app.db.session import AsyncSessionLocal

ROWS = [
    (1, 0, "UGV_Alpha_1", "MISSION", 4, 4, 0.20, "G"),
    (2, 0, "UGV_Alpha_1", "SOS_SENSOR", 5, 5, 0.70, "R"),
    (3, 1, "UGV_Alpha_1", "BLIND", 5, 5, 0.70, "R"),
    (4, 2, "OP_Alpha", "INTERVENE->UGV_Alpha_1", 5, 5, 0.70, "R"),
    (5, 3, "UGV_Alpha_1", "MISSION", 6, 5, 0.40, "A"),
    (6, 1, "UGV_Bravo_1", "SOS_MOBILITY", 5, 5, 0.65, "R"),
    (7, 5, "OP_Bravo", "INTERVENE->UGV_Bravo_1", 5, 5, 0.65, "R"),
    (8, 2, "UGV_Bravo_2", "SOS_MOBILITY", 6, 6, 0.50, "A"),
]


async def insert_tracks(run_id: int, rows=ROWS) -> None:
    async with AsyncSessionLocal() as db:
        db.add_all(
            RunTrack(run_id=run_id, seq_idx=seq, turn_idx=turn, agent_id=agent, action=action, row=row, col=col,
                     lat=54.4 + row * 0.001, lon=18.4 + col * 0.001, ap=0, total=total, mob=total, sen=total, grade=grade)
            for seq, turn, agent, action, row, col, total, grade in rows
        )
        await db.commit()


async def report(run_id: int) -> dict:
    async with AsyncSessionLocal() as db:
        return await run_report(db, run_id)


def by(rows: list[dict], key: str) -> dict:
    return {r[key]: r for r in rows}


@pytest.mark.asyncio
async def test_sos_by_team_counts_events_per_team_and_kind(run_id: int):
    await insert_tracks(run_id)
    rows = (await report(run_id))["sos_by_team"]
    assert {(r["team"], r["kind"], r["events"]) for r in rows} == {("Alpha", "SOS_SENSOR", 1), ("Bravo", "SOS_MOBILITY", 2)}


@pytest.mark.asyncio
async def test_intervention_wait_links_each_sos_to_the_next_intervention_for_the_same_ugv(run_id: int):
    await insert_tracks(run_id)
    rows = by((await report(run_id))["intervention_wait"], "agent_id")
    assert rows["UGV_Alpha_1"]["wait_turns"] == 2 and rows["UGV_Alpha_1"]["sos_turn"] == 0
    assert rows["UGV_Bravo_1"]["wait_turns"] == 4                       # 다른 제대의 개입(Alpha, turn 2)과 섞이지 않는다
    assert rows["UGV_Bravo_2"]["wait_turns"] is None                    # 개입을 받지 못한 고장은 대기 시간이 없다 (0 으로 속이지 않는다)


@pytest.mark.asyncio
async def test_wait_summary_uses_only_resolved_events_and_nearest_rank_percentiles(run_id: int):
    await insert_tracks(run_id)
    s = (await report(run_id))["wait_summary"]
    assert s["resolved"] == 2 and s["mean_turns"] == pytest.approx(3.0) and s["max_turns"] == 4
    assert s["p50_turns"] == 2 and s["p95_turns"] == 4


@pytest.mark.asyncio
async def test_queue_by_turn_tracks_waiting_ugvs_backlog_and_running_totals(run_id: int):
    await insert_tracks(run_id)
    rows = (await report(run_id))["queue_by_turn"]
    assert [r["turn_idx"] for r in rows] == [0, 1, 2, 3, 5]
    assert [r["waiting_ugvs"] for r in rows] == [1, 2, 1, 0, 0]
    assert [r["interventions"] for r in rows] == [0, 0, 1, 0, 1]
    assert [r["cumulative_interventions"] for r in rows] == [0, 0, 1, 1, 2]
    assert [r["backlog"] for r in rows] == [1, 2, 0, 0, -1]
    assert [r["queue_change"] for r in rows] == [None, 1, -1, -1, 0]       # LAG 윈도우: 첫 턴은 비교 대상이 없다


@pytest.mark.asyncio
async def test_risk_by_team_only_counts_ugv_rows(run_id: int):
    await insert_tracks(run_id)
    rows = by((await report(run_id))["risk_by_team"], "team")
    assert rows["Alpha"]["steps"] == 4 and rows["Alpha"]["red_steps"] == 2 and rows["Alpha"]["red_pct"] == pytest.approx(50.0)
    assert rows["Alpha"]["mean_risk"] == pytest.approx(0.5)               # 운용자 행(OP_Alpha)은 제외
    assert rows["Bravo"]["steps"] == 2 and rows["Bravo"]["mean_risk"] == pytest.approx(0.575)


@pytest.mark.asyncio
async def test_hot_cells_rank_cells_by_repeated_sos(run_id: int):
    await insert_tracks(run_id)
    rows = (await report(run_id))["hot_cells"]
    assert (rows[0]["row"], rows[0]["col"], rows[0]["sos_events"]) == (5, 5, 2)
    assert rows[0]["mean_risk"] == pytest.approx(0.675)
    assert (rows[1]["row"], rows[1]["col"], rows[1]["sos_events"]) == (6, 6, 1)


@pytest.mark.asyncio
async def test_sos_rate_rises_with_risk_band(run_id: int):
    await insert_tracks(run_id)
    rows = by((await report(run_id))["sos_rate_by_risk"], "risk_band")
    assert (rows["0.0-0.3"]["entries"], rows["0.0-0.3"]["sos_pct"]) == (1, 0.0)
    assert (rows["0.3-0.6"]["entries"], rows["0.3-0.6"]["sos_pct"]) == (2, 50.0)
    assert (rows["0.6-1.0"]["entries"], rows["0.6-1.0"]["sos_pct"]) == (2, 100.0)


@pytest.mark.asyncio
async def test_mode_comparison_joins_runs_of_the_same_mission(auth_client: AsyncClient, mission_id: int, run_id: int):
    await insert_tracks(run_id)                                                     # 균형(selected_mode 없음 → balanced)
    other = (await auth_client.post(f"/api/missions/{mission_id}/runs?mode=recon")).json()["id"]
    await insert_tracks(other, [
        (1, 0, "UGV_Alpha_1", "MISSION", 4, 4, 0.2, "G"),
        (2, 3, "UGV_Alpha_1", "SOS_SENSOR", 5, 5, 0.9, "R"),
        (3, 4, "OP_Alpha", "INTERVENE->UGV_Alpha_1", 5, 5, 0.9, "R"),
    ])
    async with AsyncSessionLocal() as db:
        rows = by(await mode_comparison(db, mission_id), "mode")
    assert set(rows) == {"balanced", "recon"}
    assert rows["balanced"]["sos_events"] == 3 and rows["balanced"]["interventions"] == 2 and rows["balanced"]["ugvs"] == 3
    assert rows["balanced"]["turns"] == 6                                           # max(turn_idx) + 1
    assert rows["recon"]["sos_events"] == 1 and rows["recon"]["interventions"] == 1 and rows["recon"]["ugvs"] == 1
    assert rows["recon"]["red_pct"] == pytest.approx(50.0)


@pytest.mark.asyncio
async def test_analysis_runs_are_isolated_from_each_other(auth_client: AsyncClient, mission_id: int, run_id: int):
    await insert_tracks(run_id)
    other = (await auth_client.post(f"/api/missions/{mission_id}/runs")).json()["id"]
    assert (await report(other))["sos_by_team"] == []                              # 다른 run 의 기록이 섞이지 않는다
    assert (await report(other))["wait_summary"] == {"resolved": 0, "mean_turns": None, "max_turns": None, "p50_turns": None, "p95_turns": None}


# ── API ──────────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_analysis_endpoint_is_commander_only_and_validates_the_run(auth_client: AsyncClient, login_as, run_id: int):
    assert (await auth_client.get(f"/api/runs/{run_id}/analysis")).status_code == 404     # 기록 없음
    assert (await auth_client.get("/api/runs/99999/analysis")).status_code == 404
    await insert_tracks(run_id)
    body = (await auth_client.get(f"/api/runs/{run_id}/analysis")).json()
    assert {"sos_by_team", "wait_summary", "queue_by_turn", "hot_cells", "mode_comparison"} <= set(body)
    assert body["mode_comparison"][0]["run_id"] == run_id
    user1 = await login_as("user1")                                                       # 제대를 가로지르는 집계는 지휘관 전용
    assert (await user1.get(f"/api/runs/{run_id}/analysis")).status_code == 403
