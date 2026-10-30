"""
backend/app/simulation/algo/ap_resolver.py

AP(행동력) 변환과 사고 판정.

AP 변환식은 팀원 시뮬레이션 기록(CSV)과 대조해 검증했다:
  UGV 이동 557건 중 약 70%가 정확히 일치, 평균 오차 약 3.7%.
  (식의 형태는 맞지만 팀원 시뮬레이터는 레이어 선택 등이 조금 다를 수 있다.)
"""

import numpy as np

AP_TURN = 1_000_000        # 턴(10분)당 AP
AP_MIN = 80_000.0          # 위험도 0 일 때 한 칸 이동 AP
AP_MAX = 400_000.0         # 위험도 1 일 때 한 칸 이동 AP
AP_EXPONENT = 2.0          # 비선형 지수 (클수록 고위험 구간 AP 급증)
DIAGONAL_COEFF = 1.4       # 대각선 이동 보정
ALPHA_MOB = 0.6            # 종합 위험도에서 기동 위험의 비중 (센서는 1 - ALPHA_MOB)

P_MAX_MOB = 0.20           # 기동 위험도 1.0 일 때 타일 진입당 기동 고장 확률
P_MAX_SEN = 0.15           # 센서 위험도 1.0 일 때 타일 진입당 센서 고장 확률


def combined_risk(c_mob, c_sen, alpha: float = ALPHA_MOB):
    """기동/센서 위험도(0~1)를 하나로 합친다. 배열도 받는다."""
    return np.clip(alpha * np.asarray(c_mob) + (1.0 - alpha) * np.asarray(c_sen), 0.0, 1.0)


def ap_orthogonal(c_mob, c_sen, alpha: float = ALPHA_MOB):
    """직선(상하좌우) 한 칸 이동의 AP. 스칼라/배열 모두 가능, NaN 은 NaN 으로 전파."""
    r = combined_risk(c_mob, c_sen, alpha)
    return AP_MIN + (AP_MAX - AP_MIN) * np.power(r, AP_EXPONENT)


def resolve_tile_entry(
    C_mob_prime: float,
    C_sen_prime: float,
    is_diagonal: bool,
    alpha: float = ALPHA_MOB,
) -> int:
    """타일 진입에 드는 AP. 통행 불가(block) 타일은 호출 전에 걸러져야 한다."""
    base = float(ap_orthogonal(C_mob_prime, C_sen_prime, alpha))
    return int(base * (DIAGONAL_COEFF if is_diagonal else 1.0))


def resolve_critical_event(
    C_mob_prime: float,
    C_sen_prime: float,
    rng: np.random.Generator | None = None,
) -> str:
    """
    타일에 진입하는 순간 1회 판정하는 사고(지연 평가).
    확률은 위험도의 제곱에 비례한다. 반환: NORMAL | SOS_MOBILITY | SOS_SENSOR | SOS_COMPLEX_FAILURE
    """
    rng = rng if rng is not None else np.random.default_rng()
    mob_hit = rng.random() < P_MAX_MOB * float(C_mob_prime) ** 2
    sen_hit = rng.random() < P_MAX_SEN * float(C_sen_prime) ** 2
    if mob_hit and sen_hit:
        return "SOS_COMPLEX_FAILURE"
    if mob_hit:
        return "SOS_MOBILITY"
    if sen_hit:
        return "SOS_SENSOR"
    return "NORMAL"
