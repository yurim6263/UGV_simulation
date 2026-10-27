"""
backend/app/services/simulation_service.py

run 생성/시작/취소/조회.
실제 시뮬레이션은 BackgroundTask로 orchestrator에 위임.
"""

import logging
from datetime import datetime, timezone

from fastapi import BackgroundTasks
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models.mission import Mission
from app.db.models.simulation_run import SimulationRun

logger = logging.getLogger(__name__)


class SimulationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def create_run(self, mission_id: int, mode: str | None = None) -> SimulationRun | None:
        mission = await self.db.get(Mission, mission_id)
        if mission is None:
            return None
        run = SimulationRun(mission_id=mission_id, status="CREATED", selected_mode=mode)
        self.db.add(run)
        await self.db.commit()
        await self.db.refresh(run)
        return run

    async def get_run(self, run_id: int) -> SimulationRun | None:
        return await self.db.get(SimulationRun, run_id)

    async def start_run(
        self, run_id: int, background_tasks: BackgroundTasks
    ) -> SimulationRun | None:
        run = await self.db.get(SimulationRun, run_id)
        if run is None:
            return None
        run.status = "RUNNING"
        run.started_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(run)

        # 시뮬레이션을 백그라운드 태스크로 실행
        from app.simulation.orchestrator import run_simulation
        background_tasks.add_task(run_simulation, run_id)
        logger.info("run_id=%d started", run_id)
        return run

    async def cancel_run(self, run_id: int) -> SimulationRun | None:
        run = await self.db.get(SimulationRun, run_id)
        if run is None:
            return None
        if run.status in ("COMPLETED", "FAILED", "CANCELLED"):
            return run
        run.status = "CANCELLED"
        run.finished_at = datetime.now(timezone.utc)
        await self.db.commit()
        await self.db.refresh(run)
        return run
