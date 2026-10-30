# 실행 기록 SQL 분석

시뮬레이션이 남기는 이동/이벤트 기록(`run_tracks`, 한 행 = 한 에이전트의 한 번의 행동) 위에서 돌아가는 분석 쿼리 모음이다.
쿼리는 `backend/app/analysis/sql_reports.py`에 있고, `GET /api/runs/{run_id}/analysis`(지휘관 전용)로 한 번에 받을 수 있다.

표준 SQL(CTE, 윈도우 함수, 상관 서브쿼리)만 써서 **PostgreSQL과 SQLite(≥ 3.25)에서 같은 결과**를 낸다. 백분위수는 DB마다 함수가 달라 `ROW_NUMBER` 기반 nearest-rank로 직접 구했다.

| 쿼리 | 답하려는 질문 | 쓰는 기법 |
|---|---|---|
| `sos_by_team` | 어느 제대에서 어떤 고장이 몇 번 났나? | 조건부 그룹화 |
| `intervention_wait` | SOS 후 운용자 개입까지 몇 턴 기다렸나? 개입을 못 받은 고장은? | 상관 서브쿼리(같은 UGV의 다음 개입) |
| `wait_summary` | 대기 시간의 평균/중앙값/p95는? | CTE + `ROW_NUMBER()`/`COUNT() OVER` |
| `queue_by_turn` | 대기열이 처리량을 넘어서는 병목 턴은 언제인가? | `SUM() OVER`(누적), `LAG()`(변화량), LEFT JOIN |
| `risk_by_team` | 어느 제대가 고위험 구간을 더 많이 지났나? | 조건부 집계 |
| `hot_cells` | SOS가 반복되는 격자(위험 지점)는? | GROUP BY 격자 |
| `sos_rate_by_risk` | 위험도가 높을수록 SOS가 늘어나는가? (모델 타당성 점검) | CASE 구간화 |
| `mode_comparison` | 같은 임무의 균형/정밀/신속 비교 | run 사이의 JOIN |

## 읽을 때 주의

- **개입을 받지 못한 고장의 대기 시간은 `NULL`이다.** 0으로 채우면 평균 대기가 실제보다 좋아 보인다. `wait_summary`는 해결된 고장만 센다(`resolved`).
- `sos_rate_by_risk`는 모델이 확률을 위험도의 제곱에 비례하게 두었으므로 위험이 높은 구간에서 SOS 비율이 높게 나오는 것이 정상이다. 이 쿼리는 모델이 의도대로 동작하는지 확인하는 용도이지 **현실의 증거가 아니다.**
- 모드 비교는 시뮬레이션 1회(같은 시드)의 기록이다. 통계적 결론은 `docs/optimization_report.md`의 몬테카를로를 본다.

## 테스트

`backend/app/tests/test_sql_reports.py`는 손으로 정답을 셀 수 있는 8행짜리 합성 기록을 넣고 각 쿼리의 결과를 정확히 비교한다(다른 제대의 개입과 섞이지 않는지, run끼리 격리되는지 포함).
