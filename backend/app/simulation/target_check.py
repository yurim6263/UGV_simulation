"""
backend/app/simulation/target_check.py

정찰 목표 위치 검사: 작전 구역 안이어도 수역(통행 불가)이거나 출발지에서 갈 수 없는 고립된 땅이면 그 제대는 경로가 없어(NO_PATH)
시뮬레이션이 오류 없이 끝나면서 제의 UGV 가 출발지에서 움직이지 않는다 (실제로 지도 모서리의 호수를 목표로 입력해서 겪었다).
그래서 목표를 받을 때(API), AI 문장 입력을 검증할 때, 화면에서 핀을 놓을 때 같은 함수로 막는다.

"도달 가능"은 플래너와 같은 8방향 이동으로 통행 가능한 셀들의 연결 성분이 출발지와 같은가로 판단한다.
"""

from __future__ import annotations

from functools import lru_cache

import numpy as np
from scipy.ndimage import label

from app.simulation.algo.sim_config import SimAlgoConfig
from app.simulation.presets import DEFAULT_START


@lru_cache(maxsize=1)
def _grid():
    from app.simulation.shared_env import get_environment

    env = get_environment()
    free = ~np.asarray(env.blocked).reshape(env.ny, env.nx)
    labels, _ = label(free, structure=np.ones((3, 3)))
    return np.asarray(env.blocked).reshape(env.ny, env.nx), labels


def check_target(lat: float, lon: float, start: tuple[float, float] = DEFAULT_START) -> str | None:
    """목표로 쓸 수 없으면 이유(한국어 문장), 쓸 수 있으면 None."""
    try:
        r, c = SimAlgoConfig.latlon_to_grid(lat, lon)
    except ValueError:
        return "작전 구역 밖입니다."
    blocked, labels = _grid()
    if blocked[r, c]:
        return "수역(통행 불가)이라 목표로 쓸 수 없습니다. 육지로 옮겨 주세요."
    try:
        sr, sc = SimAlgoConfig.latlon_to_grid(*start)
    except ValueError:
        return None                                   # 출발지를 모르면 도달 가능성은 판단하지 않는다
    if labels[sr, sc] and labels[r, c] != labels[sr, sc]:
        return "출발지에서 갈 수 없는 고립된 땅입니다."
    return None
