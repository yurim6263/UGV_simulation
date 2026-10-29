"""
backend/app/weather/curves.py

변수별 위험 곡선 (강수, 토양수분, 적설 → 0~1). LTWR 위험도(ltwr.py)와 "기상 악영향" 지표(scenario_index.py)가 같은 곡선을 쓰도록 한 곳에 둔다.
기준점은 팀 노트북의 강수 임계 구간(0.5 경미, 2 중간, 5 강함(소프트 회피, "5 mm/h 에서 센서 성능 붕괴"), 8 mm/h 매우 강함(하드 회피))에서 가져왔고,
토양수분/적설 기준점은 우리가 정한 가정값이다. 단조 PCHIP 곡선이라 기준점을 지나면서 부드럽다.
"""

import numpy as np
from scipy.interpolate import PchipInterpolator

RAIN_ANCHORS = ([0, 0.5, 2, 5, 8, 15], [0, 0.10, 0.35, 0.80, 0.97, 1.0])        # mm/h → 0~1 (팀 노트북 임계 구간)
SOIL_ANCHORS = ([0.0, 0.20, 0.30, 0.40, 0.50, 0.7], [0, 0, 0.2, 0.6, 1.0, 1.0])  # 체적 토양수분 m3/m3 → 0~1 (연약지반, 가정)
SNOW_ANCHORS = ([0, 0.02, 0.10, 0.30, 1.0], [0, 0.2, 0.6, 1.0, 1.0])             # 적설 깊이(수당량) m → 0~1 (가정)
ANCHORS = {"rain": RAIN_ANCHORS, "soil": SOIL_ANCHORS, "snow": SNOW_ANCHORS}
_CURVES = {k: PchipInterpolator(*v, extrapolate=False) for k, v in ANCHORS.items()}


def curve(name: str, x: np.ndarray) -> np.ndarray:
    lo, hi = ANCHORS[name][0][0], ANCHORS[name][0][-1]
    return np.nan_to_num(_CURVES[name](np.clip(x, lo, hi)), nan=0.0).astype("float32")
