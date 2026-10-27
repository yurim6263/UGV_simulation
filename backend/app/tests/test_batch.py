"""
backend/app/tests/test_batch.py

병렬 배치 실행기 테스트: 프로세스를 나눠도 순차 실행과 결과가 같아야 한다.
"""

import time

import pytest

from app.simulation.algo.episode import Genes, ScenarioSpec
from app.simulation.algo.sim_config import SimAlgoConfig as Cfg
from app.simulation.batch import Job, run_batch
from app.simulation.shared_env import get_environment
from app.simulation.algo.episode import run_episode

pytestmark = pytest.mark.skipif(
    Cfg.DATASET != "map_20km", reason="20km 데이터셋 기준 테스트 (SIM_DATASET=map_20km)"
)

SPEC = ScenarioSpec(
    start=(54.48, 18.32),
    pois=((54.40, 18.54), (54.33, 18.36), (54.37, 18.50)),
    formation=(1, 1, 1),
    assignment=(2, 0, 1),
    weather_scale=0.3,
    max_turns=5,
)


def _jobs():
    return [Job(SPEC, Genes(), seed) for seed in (1, 2, 3, 4)]


def test_parallel_results_match_sequential_results_in_order():
    parallel = run_batch(_jobs(), workers=2)
    env = get_environment()
    for res in parallel:
        expected = run_episode(env, res.job.spec, res.job.genes, res.job.seed).metrics
        assert res.metrics == expected, f"seed {res.job.seed}: 프로세스를 나누면 결과가 달라짐"
    assert [r.job.seed for r in parallel] == [1, 2, 3, 4]       # 입력 순서 유지


def test_logs_are_only_returned_when_requested():
    assert run_batch(_jobs()[:1], workers=1)[0].log is None
    assert run_batch(_jobs()[:1], workers=1, keep_log=True)[0].log


def test_different_seeds_are_actually_different():
    metrics = [r.metrics for r in run_batch(_jobs(), workers=2)]
    assert len({(m["sos_events"], m["v1_coverage"]) for m in metrics}) > 1
