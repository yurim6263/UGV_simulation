"""
backend/app/analysis/sql_reports.py

시뮬레이션 이동 기록(run_tracks) 위의 SQL 분석.

모든 쿼리는 표준 SQL(CTE, 윈도우 함수, 상관 서브쿼리)이라 PostgreSQL 과 SQLite(>= 3.25) 에서 같은 결과를 낸다.
(백분위수는 DB 마다 함수가 달라서 ROW_NUMBER 기반 nearest-rank 로 직접 구한다.)

run_tracks 한 행 = 한 에이전트의 한 번의 행동. 이벤트의 정의:
    SOS        action in (SOS_MOBILITY, SOS_SENSOR, SOS_COMPLEX_FAILURE)   UGV 가 고장나 개입을 요청
    대기       action in (SOS_WAIT, BLIND)                                  개입을 기다리는 중
    개입       action = 'INTERVENE->UGV_<제대>_<번호>'                       운용자가 해당 UGV 를 수리
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

SOS_LIST = "('SOS_MOBILITY', 'SOS_SENSOR', 'SOS_COMPLEX_FAILURE')"
WAIT_LIST = "('SOS_MOBILITY', 'SOS_SENSOR', 'SOS_COMPLEX_FAILURE', 'SOS_WAIT', 'BLIND')"

# agent_id 의 제대 이름 (UGV_Alpha_1 / Manned_Alpha / OP_Alpha)
TEAM_OF = """CASE WHEN agent_id LIKE '%Alpha%' THEN 'Alpha'
                  WHEN agent_id LIKE '%Bravo%' THEN 'Bravo'
                  WHEN agent_id LIKE '%Charlie%' THEN 'Charlie' END"""

QUERIES: dict[str, str] = {
    # 1) 제대별/종류별 SOS 건수
    "sos_by_team": f"""
        SELECT {TEAM_OF} AS team, action AS kind, COUNT(*) AS events
        FROM run_tracks
        WHERE run_id = :run_id AND action IN {SOS_LIST}
        GROUP BY team, action
        ORDER BY team, events DESC
    """,

    # 2) SOS 후 운용자 개입까지 걸린 턴 수 (상관 서브쿼리: 같은 UGV 의 다음 개입)
    "intervention_wait": f"""
        WITH sos AS (
            SELECT seq_idx, turn_idx, agent_id, {TEAM_OF} AS team
            FROM run_tracks
            WHERE run_id = :run_id AND action IN {SOS_LIST}
        )
        SELECT s.team, s.agent_id, s.turn_idx AS sos_turn,
               (SELECT MIN(i.turn_idx) FROM run_tracks i
                 WHERE i.run_id = :run_id AND i.action = 'INTERVENE->' || s.agent_id
                   AND i.seq_idx > s.seq_idx) - s.turn_idx AS wait_turns
        FROM sos s
        ORDER BY s.seq_idx
    """,

    # 3) 개입 대기 시간의 요약 (nearest-rank 백분위수, 윈도우 함수)
    "wait_summary": f"""
        WITH sos AS (
            SELECT s.seq_idx,
                   (SELECT MIN(i.turn_idx) FROM run_tracks i
                     WHERE i.run_id = :run_id AND i.action = 'INTERVENE->' || s.agent_id
                       AND i.seq_idx > s.seq_idx) - s.turn_idx AS wait_turns
            FROM run_tracks s
            WHERE s.run_id = :run_id AND s.action IN {SOS_LIST}
        ), ranked AS (
            SELECT wait_turns,
                   ROW_NUMBER() OVER (ORDER BY wait_turns) AS rn,
                   COUNT(*) OVER () AS n
            FROM sos WHERE wait_turns IS NOT NULL
        )
        SELECT COUNT(*) AS resolved, AVG(wait_turns) AS mean_turns, MAX(wait_turns) AS max_turns,
               MIN(CASE WHEN rn >= 0.50 * n THEN wait_turns END) AS p50_turns,
               MIN(CASE WHEN rn >= 0.95 * n THEN wait_turns END) AS p95_turns
        FROM ranked
    """,

    # 4) 턴별 대기열과 운용자 부하 (누적 합 윈도우). 대기열이 처리량보다 커지는 병목 턴을 찾는다.
    "queue_by_turn": f"""
        WITH waiting AS (
            SELECT turn_idx, COUNT(DISTINCT agent_id) AS waiting_ugvs
            FROM run_tracks
            WHERE run_id = :run_id AND action IN {WAIT_LIST}
            GROUP BY turn_idx
        ), served AS (
            SELECT turn_idx, COUNT(*) AS interventions
            FROM run_tracks
            WHERE run_id = :run_id AND action LIKE 'INTERVENE->%'
            GROUP BY turn_idx
        ), turns AS (
            SELECT DISTINCT turn_idx FROM run_tracks WHERE run_id = :run_id
        )
        SELECT t.turn_idx,
               COALESCE(w.waiting_ugvs, 0) AS waiting_ugvs,
               COALESCE(s.interventions, 0) AS interventions,
               SUM(COALESCE(s.interventions, 0)) OVER (ORDER BY t.turn_idx) AS cumulative_interventions,
               COALESCE(w.waiting_ugvs, 0) - COALESCE(s.interventions, 0) AS backlog,
               COALESCE(w.waiting_ugvs, 0) - LAG(COALESCE(w.waiting_ugvs, 0)) OVER (ORDER BY t.turn_idx) AS queue_change
        FROM turns t
        LEFT JOIN waiting w ON w.turn_idx = t.turn_idx
        LEFT JOIN served s ON s.turn_idx = t.turn_idx
        ORDER BY t.turn_idx
    """,

    # 5) 제대별 고위험(R) 구간 비율 (조건부 집계)
    "risk_by_team": f"""
        SELECT {TEAM_OF} AS team,
               COUNT(*) AS steps,
               SUM(CASE WHEN grade = 'R' THEN 1 ELSE 0 END) AS red_steps,
               ROUND(100.0 * SUM(CASE WHEN grade = 'R' THEN 1 ELSE 0 END) / COUNT(*), 1) AS red_pct,
               ROUND(AVG(total), 3) AS mean_risk
        FROM run_tracks
        WHERE run_id = :run_id AND agent_id LIKE 'UGV%'
        GROUP BY team
        ORDER BY red_pct DESC
    """,

    # 6) SOS 가 자주 난 격자 (위험 지점). 같은 칸에서 반복되면 지형/기상 요인이 의심된다.
    "hot_cells": f"""
        SELECT row, col, ROUND(AVG(lat), 5) AS lat, ROUND(AVG(lon), 5) AS lon,
               COUNT(*) AS sos_events, ROUND(AVG(total), 3) AS mean_risk
        FROM run_tracks
        WHERE run_id = :run_id AND action IN {SOS_LIST}
        GROUP BY row, col
        ORDER BY sos_events DESC, mean_risk DESC
        LIMIT 10
    """,

    # 7) 위험도 구간별 SOS 발생률 (위험이 높을수록 사고가 늘어나는가: 모델의 타당성 점검)
    "sos_rate_by_risk": f"""
        WITH moves AS (
            SELECT CASE WHEN total < 0.3 THEN '0.0-0.3' WHEN total < 0.6 THEN '0.3-0.6' ELSE '0.6-1.0' END AS risk_band,
                   CASE WHEN action IN {SOS_LIST} THEN 1 ELSE 0 END AS is_sos
            FROM run_tracks
            WHERE run_id = :run_id AND agent_id LIKE 'UGV%' AND action IN ('MISSION', 'RECALL', 'SOS_MOBILITY', 'SOS_SENSOR', 'SOS_COMPLEX_FAILURE')
        )
        SELECT risk_band, COUNT(*) AS entries, SUM(is_sos) AS sos_events,
               ROUND(100.0 * SUM(is_sos) / COUNT(*), 2) AS sos_pct
        FROM moves GROUP BY risk_band ORDER BY risk_band
    """,
}

# 같은 임무의 모드 비교 (run 사이의 JOIN)
MODE_COMPARISON = f"""
    SELECT r.id AS run_id, COALESCE(r.selected_mode, 'balanced') AS mode, r.status,
           SUM(CASE WHEN t.action IN {SOS_LIST} THEN 1 ELSE 0 END) AS sos_events,
           SUM(CASE WHEN t.action LIKE 'INTERVENE->%' THEN 1 ELSE 0 END) AS interventions,
           COUNT(DISTINCT CASE WHEN t.agent_id LIKE 'UGV%' THEN t.agent_id END) AS ugvs,
           MAX(t.turn_idx) + 1 AS turns,
           ROUND(100.0 * SUM(CASE WHEN t.agent_id LIKE 'UGV%' AND t.grade = 'R' THEN 1 ELSE 0 END)
                 / NULLIF(SUM(CASE WHEN t.agent_id LIKE 'UGV%' THEN 1 ELSE 0 END), 0), 1) AS red_pct
    FROM simulation_runs r
    JOIN run_tracks t ON t.run_id = r.id
    WHERE r.mission_id = :mission_id
    GROUP BY r.id, r.selected_mode, r.status
    ORDER BY r.id
"""


async def _rows(db: AsyncSession, sql: str, **params) -> list[dict]:
    result = await db.execute(text(sql), params)
    return [dict(row) for row in result.mappings().all()]


async def run_report(db: AsyncSession, run_id: int) -> dict:
    """한 run 의 분석 결과 전체."""
    out = {name: await _rows(db, sql, run_id=run_id) for name, sql in QUERIES.items()}
    out["wait_summary"] = out["wait_summary"][0] if out["wait_summary"] else {}
    return out


async def mode_comparison(db: AsyncSession, mission_id: int) -> list[dict]:
    return await _rows(db, MODE_COMPARISON, mission_id=mission_id)
