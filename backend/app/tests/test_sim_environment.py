"""
backend/app/tests/test_sim_environment.py

시뮬레이션 환경(좌표 변환, 데이터 로더, 경로 탐색 간선 처리) 테스트.
저장소에 포함된 그단스크 20km 데이터(111×111, 200m)를 그대로 사용한다.
"""

from datetime import datetime

import numpy as np
import pytest

from app.simulation.algo.environment import BLOCKED_COST, Environment, parse_stamp
from app.simulation.algo.planner import GridPlanner
from app.simulation.algo.sim_config import SimAlgoConfig as Cfg

pytestmark = pytest.mark.skipif(
    Cfg.DATASET != "map_20km", reason="20km 데이터셋 기준 테스트 (SIM_DATASET=map_20km)"
)

# 팀원 시뮬레이션 노트북의 출발지 / 정찰지 (lon, lat)
START = (18.32, 54.48)
POIS = [(18.54, 54.40), (18.36, 54.33), (18.50, 54.37)]


@pytest.fixture(scope="module")
def env():
    e = Environment(Cfg())
    e.load_base_layer()
    e.load_all_data()
    return e


# ── 좌표 변환 ────────────────────────────────────────────────────────────

def test_grid_size_comes_from_data():
    assert Cfg.GRID_SIZE == (111, 111)


def test_latlon_roundtrip_every_cell_within_one_cell():
    meta = Cfg.meta()
    rng = np.random.default_rng(0)
    for r, c in zip(rng.integers(0, 111, 200), rng.integers(0, 111, 200)):
        lat, lon = Cfg.grid_to_latlon(int(r), int(c))
        assert Cfg.latlon_to_grid(lat, lon) == (int(r), int(c))
    assert meta.lat.shape == (111, 111)


def test_start_and_pois_map_to_distinct_cells():
    cells = [Cfg.latlon_to_grid(lat, lon) for lon, lat in [START, *POIS]]
    assert len(set(cells)) == len(cells), cells


def test_out_of_domain_coordinate_is_rejected():
    """예전에는 서울 좌표계 때문에 모든 입력이 같은 셀로 clamp 되었다."""
    with pytest.raises(ValueError, match="작전 구역 밖"):
        Cfg.latlon_to_grid(37.51, 127.0)


# ── 시각 표기 ────────────────────────────────────────────────────────────

def test_midnight_overflow_timestamps_are_normalized():
    assert parse_stamp("20230630_2400") == datetime(2023, 7, 1, 0, 0)
    assert parse_stamp("20230630_2710") == datetime(2023, 7, 1, 3, 10)
    assert parse_stamp("20230630_2250") == datetime(2023, 6, 30, 22, 50)


# ── 로더 ─────────────────────────────────────────────────────────────────

def test_all_actual_files_are_loaded(env):
    """실황 31개 파일 중 24xx 시각 때문에 19개가 버려지던 문제의 회귀 테스트."""
    assert len(env.actual_data_pool) == 31
    assert max(env.actual_data_pool) == datetime(2023, 7, 1, 3, 0)


def test_forecast_pool_is_separate_from_actual(env):
    assert len(env.global_time_pool) == 54  # 모델 시각 3개 × 18
    assert env._model_times == [
        datetime(2023, 6, 30, 22, 0),
        datetime(2023, 6, 30, 23, 0),
        datetime(2023, 7, 1, 0, 0),
    ]


def test_base_layer_matches_grid_and_blocks_only_water(env):
    assert env.base_layer.shape == Cfg.GRID_SIZE
    assert not np.isnan(env.base_layer).any()
    assert env.blocked.any()
    assert (env.base_layer[env.blocked] >= BLOCKED_COST).all()


def test_missing_cells_are_nan_not_zero(env):
    """동적 파일은 경로 버퍼 안의 셀만 담는다. 나머지는 '위험 없음'이 아니라 '데이터 없음'이다."""
    layer = env.actual_data_pool[datetime(2023, 6, 30, 22, 0)]
    assert layer.shape == Cfg.GRID_SIZE
    assert 0.0 < np.isnan(layer).mean() < 0.5
    assert np.nanmin(layer) >= 0.0 and np.nanmax(layer) <= 1.0


def test_planning_cube_uses_forecast_and_never_peeks_at_future_actuals(env):
    env.sim_time = datetime(2023, 6, 30, 22, 0)
    env.current_model_time = env.sim_time
    cube = env.get_active_time_cube()
    assert cube.shape == (Cfg.NT, *Cfg.GRID_SIZE)

    model = datetime(2023, 6, 30, 22, 0)
    target = datetime(2023, 6, 30, 23, 30)  # i = 9
    assert np.array_equal(cube[9], env.global_time_pool[(model, target)], equal_nan=True)
    # 계획 레이어(예보)와 같은 시각의 실황(정답)은 달라야 한다 — 같다면 정답을 보고 있다는 뜻
    assert not np.array_equal(cube[9], env.actual_data_pool[target], equal_nan=True)


def test_planning_cube_falls_back_to_persistence_when_forecast_is_missing(env):
    env.sim_time = datetime(2023, 7, 1, 2, 30)
    env.current_model_time = env.sim_time
    before = env.stats["persistence_layers"]
    cube = env.get_active_time_cube()
    assert env.stats["persistence_layers"] > before
    assert np.array_equal(cube[-1], cube[-2], equal_nan=True)


# ── 경로 탐색: 실제 지도 ─────────────────────────────────────────────────

def test_planner_reaches_far_pois_without_entering_blocked_cells(env):
    """이전 PathFinder3D 는 18개 레이어 = 17칸 한계 때문에 20km 지도에서 경로를 못 찾았다."""
    t0 = env.start_time
    pl = GridPlanner(*Cfg.GRID_SIZE, env.base_layer, env.blocked, Cfg.NT)
    cube = pl.ap_cube(env.time_cube(t0, "mob"), env.time_cube(t0, "sen"))
    start = Cfg.latlon_to_grid(START[1], START[0])
    for lon, lat in POIS:
        goal = Cfg.latlon_to_grid(lat, lon)
        plan = pl.plan(cube, start, goal)
        assert plan.reachable, f"{goal} 경로 없음"
        assert len(plan.cells) > 40
        assert not any(env.blocked[r, c] for r, c in plan.cells)
