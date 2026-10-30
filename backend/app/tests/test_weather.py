"""
backend/app/tests/test_weather.py

ERA5 전처리와 강수 예측 모델 테스트. 합성 데이터만 쓰므로 ERA5 파일이 필요 없고 빠르다.
조용히 틀리기 쉬운 곳(누적 강수 초기화 규칙, 지연 값 정렬, 데이터 누수)에 집중한다.
"""

import numpy as np
import pytest

from app.weather.era5 import assert_hourly, compare_deaccumulation, rain_rate_mm, rain_rate_team_rule_mm
from app.weather.rain_model import (
    N_LAGS, Split, bootstrap_csi, build_split, contingency, daily_counts, evaluate, persistence, scores,
    time_features,
)


def hourly(start: str, n: int) -> np.ndarray:
    return np.datetime64(start, "h") + np.arange(n) * np.timedelta64(1, "h")


# ── 누적 강수 → 시간당 강수 ──────────────────────────────────────────────

def test_rain_rate_resets_only_at_01_utc():
    """ERA5-Land tp 는 UTC 0시부터의 누적이고 01시에 초기화된다 (00시 값 = 전날 24시간 합계)."""
    times = hourly("2022-07-01T22:00", 6)                        # 22, 23, 00, 01, 02, 03 시
    tp_m = np.array([[0.010], [0.012], [0.0125], [0.0003], [0.0010], [0.0010]])   # 00시 값은 전날 합계
    rate = rain_rate_mm(tp_m, times)[:, 0]
    assert np.isnan(rate[0])
    assert rate[1] == pytest.approx(2.0)                         # 12.0 - 10.0
    assert rate[2] == pytest.approx(0.5)                         # 00시: 전날 합계 12.5 - 12.0
    assert rate[3] == pytest.approx(0.3)                         # 01시 초기화: 값 자체가 그 한 시간 강수
    assert rate[4] == pytest.approx(0.7)
    assert rate[5] == pytest.approx(0.0)


def test_tiny_decreases_are_float_noise_not_resets():
    """누적값이 오후에 아주 조금 줄어드는 것은 부동소수점 오차다. 이것을 초기화로 보면 하루 누적 합계가 강수가 된다."""
    times = hourly("2022-07-01T09:00", 4)                        # 09, 10, 11, 12 시
    tp_m = np.array([[0.000351], [0.000351 - 1e-9], [0.000352], [0.000352 - 1e-9]])
    assert np.nanmax(rain_rate_mm(tp_m, times)) < 0.01           # 모두 거의 0mm/h
    assert np.nanmax(rain_rate_team_rule_mm(tp_m)) > 0.3         # 팀 규칙은 0.35mm 를 강수로 만든다 (가짜 강수)


def test_compare_counts_spurious_hours_outside_the_reset_hour():
    times = hourly("2022-07-01T09:00", 4)
    tp_m = np.array([[0.000351], [0.000351 - 1e-9], [0.000352], [0.000352 - 1e-9]])
    stats = compare_deaccumulation(tp_m, times)
    assert stats["spurious_hours"] == 2 and stats["spurious_outside_reset_hour"] == 2
    assert stats["max_mmph_team_rule"] > stats["max_mmph_correct"]


def test_rain_rate_handles_a_grid_and_keeps_nan_for_sea_cells():
    times = hourly("2022-07-01T05:00", 3)
    tp_m = np.zeros((3, 2, 2))
    tp_m[:, 0, 0] = [0.001, 0.003, 0.003]
    tp_m[:, 1, 1] = np.nan                                       # 바다 (육지 전용 데이터)
    rate = rain_rate_mm(tp_m, times)
    assert rate[1, 0, 0] == pytest.approx(2.0) and np.isnan(rate[1, 1, 1])


def test_non_hourly_time_axis_is_rejected():
    times = np.array(["2022-01-01T00", "2022-01-01T01", "2022-01-01T03"], dtype="datetime64[h]")
    with pytest.raises(ValueError, match="연속되지"):
        assert_hourly(times)


# ── 데이터 셋 구성 ───────────────────────────────────────────────────────

def make_rain(T=600, C=3, seed=0):
    rng = np.random.default_rng(seed)
    times = hourly("2022-01-01T00:00", T)
    rain = (rng.random((T, C)) < 0.2) * rng.exponential(1.0, (T, C))
    rain = rain.astype(np.float32)
    rain[0] = np.nan                                             # 첫 시각은 앞 값이 없어 NaN
    return rain, times


def test_features_align_lags_with_the_forecast_origin_and_target_with_t_plus_h():
    rain, times = make_rain()
    h = 3
    s = build_split(rain, times, h, "2022-01-10T00:00", "2022-01-12T00:00")
    assert len(s) > 0
    C = rain.shape[1]
    # 첫 표본: 대상 시각 인덱스 tg, 예측 시점 t = tg - h
    tg = int(np.searchsorted(times, np.datetime64("2022-01-10T00:00", "h")))
    t = tg - h
    for k in range(N_LAGS):
        assert s.X[0, k] == rain[t - k, 0]                       # lag_k = k 시간 전 강수
    assert s.y[0] == rain[tg, 0]                                 # 대상 = t + h
    assert s.X.shape[1] == N_LAGS + 4


def test_no_leakage_target_never_appears_in_its_own_features_and_splits_do_not_overlap():
    rain, times = make_rain()
    h = 2
    train = build_split(rain, times, h, "2022-01-01T00:00", "2022-01-15T00:00")
    test = build_split(rain, times, h, "2022-01-15T00:00", "2022-01-25T00:00")
    # 대상 시각은 분할 경계를 넘지 않는다
    assert train.day.max() < np.datetime64("2022-01-15", "D").astype(np.int64)
    assert test.day.min() >= np.datetime64("2022-01-15", "D").astype(np.int64)
    # 예측 시점(lag_0)은 대상보다 h 시간 앞이다: 지속성 예측이 '정답을 보는' 일이 없다
    full = build_split(rain, times, h, "2022-01-10T00:00", "2022-01-12T00:00")
    tg0 = int(np.searchsorted(times, np.datetime64("2022-01-10T00:00", "h")))
    assert full.X[0, 0] == rain[tg0 - h, 0]                       # lag_0 은 예측 시점의 값이다
    assert full.y[0] == rain[tg0, 0]                              # 대상은 h 시간 뒤의 값이다
    # 입력 어디에도 대상 시각 이후의 값은 없다: 대상 시각의 값을 바꿔도 특징은 그대로여야 한다
    changed = rain.copy()
    changed[tg0, 0] += 100.0
    again = build_split(changed, times, h, "2022-01-10T00:00", "2022-01-12T00:00")
    assert np.array_equal(again.X[0], full.X[0]) and again.y[0] != full.y[0]


def test_nan_rows_are_dropped_and_subsampling_is_reproducible():
    rain, times = make_rain()
    rain[100:105, 1] = np.nan
    s = build_split(rain, times, 1, "2022-01-01T00:00", "2022-01-30T00:00")
    assert np.isfinite(s.X).all() and np.isfinite(s.y).all()
    a = build_split(rain, times, 1, "2022-01-01T00:00", "2022-01-30T00:00", keep_frac=0.4, seed=7)
    b = build_split(rain, times, 1, "2022-01-01T00:00", "2022-01-30T00:00", keep_frac=0.4, seed=7)
    assert len(a) < len(s) and np.array_equal(a.X, b.X)
    assert 0.3 < len(a) / len(s) < 0.5


def test_time_features_are_cyclic():
    t = np.array(["2022-01-01T00", "2022-12-31T23"], dtype="datetime64[h]")
    f = time_features(t)
    assert f.shape == (2, 4)
    assert f[0, 3] == pytest.approx(1.0) and f[1, 3] == pytest.approx(np.cos(2 * np.pi * 23 / 24), abs=1e-5)


# ── 평가 지표 ────────────────────────────────────────────────────────────

def test_contingency_and_scores_match_hand_counts():
    y = np.array([0.0, 0.2, 0.5, 1.0, 0.0, 0.0])
    pred = np.array([0.0, 0.2, 0.0, 0.0, 0.3, 0.0])
    hits, misses, fa = contingency(y, pred, 0.1)
    assert (hits, misses, fa) == (1, 2, 1)
    s = scores(hits, misses, fa)
    assert s["pod"] == pytest.approx(1 / 3) and s["far"] == pytest.approx(1 / 2) and s["csi"] == pytest.approx(1 / 4)
    assert np.isnan(scores(0, 0, 0)["csi"])                       # 사건도 경보도 없으면 정의되지 않는다 (0 으로 속이지 않는다)


def test_evaluate_reports_errors_and_threshold_scores():
    y = np.array([0.0, 0.0, 2.0, 0.0])
    split = Split(np.zeros((4, N_LAGS + 4), np.float32), y, np.arange(4))
    out = evaluate(split, np.array([0.0, 0.0, 1.0, 0.0]))
    assert out["mae"] == pytest.approx(0.25) and out["bias"] == pytest.approx(-0.25)
    assert out["thr_0.5"]["pod"] == 1.0 and out["thr_0.5"]["far"] == 0.0


def test_persistence_uses_the_most_recent_observation():
    rain, times = make_rain()
    s = build_split(rain, times, 2, "2022-01-10T00:00", "2022-01-12T00:00")
    assert np.array_equal(persistence(s), s.X[:, 0])


# ── 블록 부트스트랩 ──────────────────────────────────────────────────────

def test_bootstrap_detects_a_clearly_better_model_and_not_two_identical_ones():
    days = 60
    good = np.tile([8, 1, 1], (days, 1))                          # CSI 0.8
    bad = np.tile([3, 6, 4], (days, 1))                           # CSI 0.23
    r = bootstrap_csi(good, bad, n_boot=300)
    assert r["a_better_significant"] and not r["b_better_significant"] and r["diff"][0] > 0
    same = bootstrap_csi(good, good, n_boot=300)
    assert not same["a_better_significant"] and not same["b_better_significant"]
    assert same["diff"][0] <= 0 <= same["diff"][1]


def test_daily_counts_sum_to_the_overall_contingency():
    y = np.array([0.0, 1.0, 1.0, 0.0, 2.0, 0.0])
    pred = np.array([0.5, 1.0, 0.0, 0.0, 2.0, 0.5])
    split = Split(np.zeros((6, N_LAGS + 4), np.float32), y, np.array([1, 1, 2, 2, 3, 3]))
    days, counts = daily_counts(split, pred, 0.5)
    assert list(days) == [1, 2, 3]
    assert tuple(counts.sum(axis=0)) == contingency(y, pred, 0.5)
