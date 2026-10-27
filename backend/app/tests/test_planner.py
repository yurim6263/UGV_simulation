"""
backend/app/tests/test_planner.py

시간 의존 경로 탐색기(GridPlanner) 테스트. 합성 격자만 쓰므로 데이터 파일이 필요 없다.
"""

import numpy as np

from app.simulation.algo.ap_resolver import AP_TURN
from app.simulation.algo.planner import GridPlanner

NT = 18


def make(ny=30, nx=30, blocked=None):
    blocked = np.zeros((ny, nx), dtype=bool) if blocked is None else blocked
    return GridPlanner(ny, nx, np.ones((ny, nx)), blocked, NT)


def cube(planner, risk):
    """위험도 risk(nt, ny, nx) → 계획용 AP 큐브. 기동/센서 위험을 같은 값으로 둔다."""
    return planner.ap_cube(risk, risk)


def test_plans_farther_than_the_old_17_cell_limit():
    """이전 PathFinder3D 는 '1칸 = 시간 1단계'라 18개 레이어로 17칸까지만 계획할 수 있었다."""
    pl = make(ny=60, nx=60)
    risk = np.zeros((NT, 60, 60), dtype=np.float32)
    plan = pl.plan(cube(pl, risk), (0, 0), (59, 59))
    assert plan.reachable
    assert len(plan.cells) - 1 == 59          # 대각선 59칸
    assert plan.cells[0] == (0, 0) and plan.cells[-1] == (59, 59)


def test_path_steps_are_adjacent_cells():
    pl = make()
    plan = pl.plan(cube(pl, np.zeros((NT, 30, 30), np.float32)), (3, 4), (25, 20))
    for (r0, c0), (r1, c1) in zip(plan.cells[:-1], plan.cells[1:]):
        assert max(abs(r1 - r0), abs(c1 - c0)) == 1


def test_never_enters_blocked_cells_and_detours():
    blocked = np.zeros((30, 30), dtype=bool)
    blocked[:, 14] = True
    blocked[10:20, 14] = False   # 벽의 틈
    pl = make(blocked=blocked)
    plan = pl.plan(cube(pl, np.zeros((NT, 30, 30), np.float32)), (15, 2), (15, 27))
    assert plan.reachable
    assert not any(blocked[r, c] for r, c in plan.cells)


def test_unreachable_goal_returns_empty_plan():
    blocked = np.zeros((30, 30), dtype=bool)
    blocked[:, 14] = True        # 완전한 벽
    pl = make(blocked=blocked)
    plan = pl.plan(cube(pl, np.zeros((NT, 30, 30), np.float32)), (15, 2), (15, 27))
    assert not plan.reachable and plan.cells == []


def test_cells_without_data_are_not_entered():
    risk = np.zeros((NT, 30, 30), dtype=np.float32)
    risk[:, 5:25, 14] = np.nan   # 데이터 없는 세로 띠
    pl = make()
    plan = pl.plan(cube(pl, risk), (15, 2), (15, 27))
    assert plan.reachable
    assert not any(np.isnan(risk[0, r, c]) for r, c in plan.cells)


def test_avoids_a_persistent_high_risk_band():
    risk = np.zeros((NT, 30, 30), dtype=np.float32)
    risk[:, 8:22, 14:16] = 1.0   # 모든 시간대에 위험한 띠 (위아래로 우회 가능)
    pl = make()
    plan = pl.plan(cube(pl, risk), (15, 2), (15, 27))
    assert plan.reachable
    assert not any(8 <= r < 22 and 14 <= c < 16 for r, c in plan.cells)


def test_time_dependence_goes_through_a_band_that_clears_before_arrival():
    """띠가 0번 레이어에서만 위험하고 이후 사라진다면, 늦게 도착하는 경로는 그 띠를 그대로 통과해야 한다.
    (시간을 무시하고 현재 날씨만 보면 불필요하게 돌아간다.)"""
    ny = nx = 60
    risk = np.zeros((NT, ny, nx), dtype=np.float32)
    risk[0, 20:40, 45:50] = 1.0   # 출발 직후에만 위험, 먼 거리라 도착 시점엔 이미 지나간 날씨
    pl = make(ny, nx)
    plan = pl.plan(cube(pl, risk), (30, 2), (30, 57))
    crossed = [(r, c) for r, c in plan.cells if 20 <= r < 40 and 45 <= c < 50]
    assert crossed, "위험이 사라진 뒤에 도착하므로 띠를 통과해야 한다"
    assert len(plan.cells) - 1 == 55          # 직선 최단 거리


def test_higher_risk_costs_more_ap():
    pl = make()
    calm = pl.plan(cube(pl, np.zeros((NT, 30, 30), np.float32)), (5, 5), (5, 25))
    stormy = pl.plan(cube(pl, np.full((NT, 30, 30), 0.8, np.float32)), (5, 5), (5, 25))
    assert stormy.est_ap > calm.est_ap * 2


def test_dispersion_penalty_pushes_the_next_path_away():
    pl = make()
    c = cube(pl, np.zeros((NT, 30, 30), np.float32))
    first = pl.plan(c, (15, 2), (15, 27))
    pen = np.zeros((30, 30))
    for r, col in first.cells:
        pen[max(0, r - 3):r + 4, col] = 2.0   # 첫 경로 주변에 큰 점유 페널티
    second = pl.plan(c, (15, 2), (15, 27), penalty=pen)
    assert second.cells != first.cells


def test_turn_ap_constant():
    assert AP_TURN == 1_000_000
