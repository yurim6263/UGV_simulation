# 모든 모델을 한 곳에서 임포트하여 Alembic autogenerate가 감지하도록 함
from app.db.models.alert import RunAlert
from app.db.models.assistant_log import AssistantLog
from app.db.models.data_asset import DataAsset, MissionAsset, RunInputAsset
from app.db.models.mission import Mission, MissionForceMixCandidate, MissionTarget
from app.db.models.patrol import RunPatrolEvent
from app.db.models.route import RunKpi, RunMapLayer, RunRecommendation, RunRoute, RunRouteEffect
from app.db.models.run_asset_status import RunAssetStatus
from app.db.models.simulation_run import SimulationRun
from app.db.models.snapshot import RunStatusSnapshot, RunTimeSeriesPanel
from app.db.models.track import RunTrack
from app.db.models.unit_state import RunQueueEvent, RunSosEvent, RunUnit
from app.db.models.refresh_token import RefreshToken
from app.db.models.user import User

__all__ = [
    "User",
    "RefreshToken",
    "Mission",
    "MissionTarget",
    "MissionForceMixCandidate",
    "DataAsset",
    "MissionAsset",
    "RunInputAsset",
    "SimulationRun",
    "RunStatusSnapshot",
    "RunTimeSeriesPanel",
    "RunUnit",
    "RunQueueEvent",
    "RunAlert",
    "RunRoute",
    "RunMapLayer",
    "RunKpi",
    "RunRecommendation",
    "RunPatrolEvent",
    "RunRouteEffect",
    "RunSosEvent",
    "RunAssetStatus",
    "RunTrack",
    "AssistantLog",
]
