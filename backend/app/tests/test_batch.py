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


# ── 깨진 프로세스 풀 복구 ────────────────────────────────────────────────

def test_broken_pool_is_recovered_by_rerunning_only_the_unfinished_jobs(monkeypatch):
    """윈도우에서 작업 프로세스가 갑자기 죽으면(BrokenProcessPool) 25분짜리 최적화가 통째로 사라진 적이 있다."""
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool

    import app.simulation.batch as batch

    log = {"pools": 0, "executed": []}

    class FlakyPool:
        def __init__(self, max_workers, initializer=None):
            log["pools"] += 1
            self.first, self.submitted = log["pools"] == 1, 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def submit(self, fn, arg):
            fut = Future()
            if self.first and self.submitted >= 2:               # 첫 풀은 2개를 끝내고 깨진다
                fut.set_exception(BrokenProcessPool("worker died"))
            else:
                log["executed"].append(arg[0].seed)
                fut.set_result(fn(arg))
            self.submitted += 1
            return fut

    monkeypatch.setattr(batch, "ProcessPoolExecutor", FlakyPool)
    jobs = _jobs()
    results = batch.run_batch(jobs, workers=2)

    assert log["pools"] == 2                                      # 한 번 깨진 뒤 새 풀로 이어서 실행
    assert log["executed"] == [1, 2, 3, 4]                        # 끝난 작업(1, 2)은 다시 돌리지 않았다
    assert [r.job.seed for r in results] == [1, 2, 3, 4]
    assert all(r.metrics for r in results)


def test_pool_that_keeps_breaking_eventually_raises(monkeypatch):
    from concurrent.futures import Future
    from concurrent.futures.process import BrokenProcessPool

    import app.simulation.batch as batch

    class AlwaysBroken:
        def __init__(self, max_workers, initializer=None):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def submit(self, fn, arg):
            fut = Future()
            fut.set_exception(BrokenProcessPool("worker died"))
            return fut

    monkeypatch.setattr(batch, "ProcessPoolExecutor", AlwaysBroken)
    with pytest.raises(BrokenProcessPool):
        batch.run_batch(_jobs(), workers=2, retries=1)
