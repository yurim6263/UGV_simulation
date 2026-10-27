"""
backend/app/simulation/shared_env.py

읽기 전용 시뮬레이션 환경(정적 지형 + 31개 실황 + 54개 예보)을 프로세스에서 한 번만 적재해 공유한다.
적재에 수 초가 걸리고, 에피소드는 환경을 바꾸지 않으므로 여러 run 이 같은 객체를 써도 된다.
"""

import threading

from app.simulation.algo.environment import Environment
from app.simulation.algo.sim_config import SimAlgoConfig

_lock = threading.Lock()
_env: Environment | None = None


def get_environment() -> Environment:
    global _env
    if _env is None:
        with _lock:
            if _env is None:
                env = Environment(SimAlgoConfig())
                env.load_base_layer()
                env.load_all_data()
                _env = env
    return _env
