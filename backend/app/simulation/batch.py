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
from concurrent.futures import ProcessPoolExecutor, as_completed
from concurrent.futures.process import BrokenProcessPool
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


def run_batch(jobs: list[Job], workers: int | None = None, keep_log: bool = False, retries: int = 2) -> list[BatchResult]:
    """jobs 를 병렬로 실행해 같은 순서의 결과를 돌려준다. workers=1 이면 현재 프로세스에서 순차 실행.

    윈도우에서 작업 프로세스가 갑자기 죽어 풀이 깨지는 일이 있다(BrokenProcessPool). 그때는 이미 끝난
    결과를 보존하고 남은 작업만 새 풀로 다시 돌린다 (최대 retries 번). 에피소드는 시드가 같으면 결과가 같으므로
    다시 돌려도 안전하다.
    """
    workers = min(workers or default_workers(), max(1, len(jobs)))
    if workers == 1:
        _init_worker()
        return [_run_job((j, keep_log)) for j in jobs]

    results: list[BatchResult | None] = [None] * len(jobs)
    pending = list(range(len(jobs)))
    for attempt in range(retries + 1):
        futures: dict = {}
        try:
            with ProcessPoolExecutor(max_workers=workers, initializer=_init_worker) as pool:
                futures = {pool.submit(_run_job, (jobs[i], keep_log)): i for i in pending}
                for fut in as_completed(futures):
                    results[futures[fut]] = fut.result()
            return results                                    # type: ignore[return-value]
        except BrokenProcessPool:
            for fut, i in futures.items():                    # 깨지기 전에 끝난 결과를 건진다
                if fut.done() and not fut.cancelled() and fut.exception() is None:
                    results[i] = fut.result()
            pending = [i for i in pending if results[i] is None]
            if attempt == retries or not pending:
                raise
    return results                                            # type: ignore[return-value]
