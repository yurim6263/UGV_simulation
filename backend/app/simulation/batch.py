"""
backend/app/simulation/batch.py

에피소드 병렬 배치 실행 (최적화/몬테카를로용).

에피소드는 서로 독립이고 환경은 읽기 전용이므로 프로세스 단위로 나눠 돌린다.
프로세스마다 환경(지형+실황+예보)을 한 번만 적재하고(initializer), 결과는 지표만 돌려준다
(이동 기록 전체를 프로세스 사이로 옮기면 느려진다. 필요하면 keep_log=True).

사용 예:
    jobs = [Job(spec, genes, seed) for seed in range(30)]
    results = run_batch(jobs, workers=8)          # jobs 와 같은 순서로 BatchResult 를 돌려준다
"""

from __future__ import annotations

import os
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass

from app.simulation.algo.episode import Genes, ScenarioSpec, run_episode


@dataclass(frozen=True)
class Job:
    spec: ScenarioSpec
    genes: Genes
    seed: int


@dataclass
class BatchResult:
    job: Job
    metrics: dict
    log: list | None = None


def _init_worker() -> None:
    from app.simulation.shared_env import get_environment
    get_environment()                      # 프로세스당 한 번 적재


def _run_job(args: tuple) -> BatchResult:
    job, keep_log = args
    from app.simulation.shared_env import get_environment
    result = run_episode(get_environment(), job.spec, job.genes, job.seed)
    return BatchResult(job=job, metrics=result.metrics, log=result.log if keep_log else None)


def default_workers() -> int:
    """코어 수보다 하나 적게 (나머지는 OS/서버용)."""
    return max(1, (os.cpu_count() or 2) - 1)


def run_batch(jobs: list[Job], workers: int | None = None, keep_log: bool = False) -> list[BatchResult]:
    """jobs 를 병렬로 실행해 같은 순서의 결과를 돌려준다. workers=1 이면 현재 프로세스에서 순차 실행."""
    workers = min(workers or default_workers(), max(1, len(jobs)))
    if workers == 1:
        _init_worker()
        return [_run_job((j, keep_log)) for j in jobs]
    with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
        return list(pool.map(_run_job, [(j, keep_log) for j in jobs], chunksize=1))
