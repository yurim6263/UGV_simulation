"""
backend/app/simulation/presets.py

운용 모드(균형 / 정밀 / 신속) 프리셋.

편성(제대별 UGV 수)과 목표 배정은 팀원 시뮬레이터의 추천 결과를 그대로 가져왔다 (3-4-2, 3-3-3, 4-2-3).
연속 유전자(산개, 기상 민감도)는 모드의 성격에 맞춘 **임시 값**이며, NSGA-II 최적화 결과(파레토 원형)로 대체할 자리다.
"""

from __future__ import annotations

from app.simulation.algo.episode import Genes, ScenarioSpec

# 팀원 시뮬레이션 노트북의 출발지 / 정찰지 (lat, lon)
DEFAULT_START = (54.48, 18.32)
DEFAULT_POIS = ((54.40, 18.54), (54.33, 18.36), (54.37, 18.50))

# 시나리오 강도: 데이터의 위험도에 곱하는 배율 (노션 설계의 Clear / Moderate / Severe)
WEATHER_SCALES = {"clear": 0.15, "moderate": 0.3, "severe": 1.0}

MODE_PRESETS: dict[str, dict] = {
    "balance": {   # 균형: 안정성과 속도의 절충
        "formation": (3, 4, 2), "assignment": (2, 0, 1),
        "genes": Genes(dispersion_weight=1.0, weather_sensitivity=1.0),
    },
    "explore": {   # 정밀(탐색): 산개를 키우고 위험에 민감하게 — 시간은 더 걸리지만 넓게 훑는다
        "formation": (3, 3, 3), "assignment": (1, 0, 2),
        "genes": Genes(dispersion_weight=1.8, weather_sensitivity=1.3),
    },
    "rush": {      # 신속: 위험을 덜 피하고 곧장 이동
        "formation": (4, 2, 3), "assignment": (0, 1, 2),
        "genes": Genes(dispersion_weight=0.3, weather_sensitivity=0.6),
    },
}


def preset(mode: str, weather_scale: float = WEATHER_SCALES["moderate"], max_turns: int = 24,
           start=DEFAULT_START, pois=DEFAULT_POIS) -> tuple[ScenarioSpec, Genes]:
    p = MODE_PRESETS[mode]
    spec = ScenarioSpec(
        start=tuple(start), pois=tuple(tuple(x) for x in pois),
        formation=p["formation"], assignment=p["assignment"],
        max_turns=max_turns, weather_scale=weather_scale,
    )
    return spec, p["genes"]
