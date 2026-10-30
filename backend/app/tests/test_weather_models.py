"""
backend/app/tests/test_weather_models.py

직접 구현한 기상 예측(ConvLSTM), 안개 식, 위험도(LTWR) 생성기, 정적 지형 격자의 테스트.
큰 원자료(ERA5, WorldCover)를 읽지 않고 합성 값과 저장소에 있는 정적 파일로 확인한다.
"""

import numpy as np
import pandas as pd
import pytest
import torch

from app.geo import static_grid as sg
from app.weather import ltwr
from app.weather.convlstm import Seq2SeqConvLSTM
from app.weather.dataset import CHANNELS, HORIZON, LOOKBACK, Normalizer, split_of, time_features
from app.weather.fog import fog_probability, vis_class, wet_3h
from app.weather.weather_eval import block_bootstrap_diff, derived, verdict


# ── 안개 (팀 노트북 식) ──────────────────────────────────────────────────

def test_fog_probability_matches_the_team_formula_at_known_points():
    k = 273.15
    # ΔT=2, U=3, 젖음 없음 → z=0 → 0.5
    assert float(fog_probability(np.array(k + 12.0), np.array(k + 10.0), np.array(3.0), 0.0)) == pytest.approx(0.5)
    # ΔT=0, U=0, 젖음 → z = 4.4 + 3.6 + 0.8 = 8.8
    assert float(fog_probability(np.array(k), np.array(k), np.array(0.0), 1.0)) == pytest.approx(1 / (1 + np.exp(-8.8)), rel=1e-5)
    # 건조하고 바람 센 날 → 거의 0
    assert float(fog_probability(np.array(k + 25.0), np.array(k + 5.0), np.array(8.0), 0.0)) < 1e-6


def test_fog_is_monotone_in_dewpoint_gap_wind_and_wetness():
    k = 273.15
    base = lambda dt=2.0, u=3.0, w=0.0: float(fog_probability(np.array(k + dt), np.array(k), np.array(u), w))  # noqa: E731
    assert base(dt=1.0) > base(dt=3.0) and base(u=1.0) > base(u=5.0) and base(w=1.0) > base(w=0.0)


def test_visibility_class_follows_the_team_thresholds():
    k = 273.15
    cls = lambda dt, u: int(vis_class(np.array(k + dt), np.array(k), np.array(u)))  # noqa: E731
    assert cls(0.5, 1.0) == 2 and cls(1.8, 3.0) == 1 and cls(5.0, 1.0) == 0 and cls(0.7, 4.0) == 2


def test_wet_3h_sums_the_last_three_hours_including_the_current_one():
    rain = np.array([0.0, 0.1, 0.0, 0.0, 0.0, 0.3])
    assert wet_3h(rain).tolist() == [0.0, 0.0, 0.0, 0.0, 0.0, 1.0]      # 0.1 하나로는 0.2 미달, 마지막은 0.3
    rain2 = np.array([0.15, 0.1, 0.0, 0.0, 0.0])
    assert wet_3h(rain2).tolist() == [0.0, 1.0, 1.0, 0.0, 0.0]            # 0.15+0.1 이 2시간 동안 창 안에 있다


# ── ConvLSTM ─────────────────────────────────────────────────────────────

def test_convlstm_output_shape_and_it_starts_as_a_persistence_forecast():
    m = Seq2SeqConvLSTM(n_phys=7, hidden=(8, 8), horizon=3).eval()
    past = torch.randn(2, LOOKBACK, 7, 10, 11)
    pt, ft = torch.randn(2, LOOKBACK, 4), torch.randn(2, 3, 4)
    mask = torch.ones(2, 1, 10, 11)
    out = m(past, pt, ft, mask)
    assert out.shape == (2, 3, 7, 10, 11)
    for j in range(3):                                                    # 머리 가중치가 0 이라 학습 전에는 직전 프레임 그대로 (지속성)
        assert torch.allclose(out[:, j], past[:, -1])


def test_convlstm_gradients_flow_after_a_few_steps():
    torch.manual_seed(0)
    m = Seq2SeqConvLSTM(n_phys=7, hidden=(8,), horizon=3)
    past = torch.randn(4, LOOKBACK, 7, 6, 6)
    pt, ft, mask = torch.randn(4, LOOKBACK, 4), torch.randn(4, 3, 4), torch.ones(4, 1, 6, 6)
    target = past[:, -1:].repeat(1, 3, 1, 1, 1) + 0.5                     # 지속성에서 일정하게 벗어난 목표
    opt = torch.optim.Adam(m.parameters(), lr=1e-2)
    first = last = None
    for _ in range(25):
        loss = ((m(past, pt, ft, mask) - target) ** 2).mean()
        opt.zero_grad(); loss.backward(); opt.step()
        first = first if first is not None else loss.item()
        last = loss.item()
    assert last < first * 0.7


# ── 자료 전처리와 평가 ───────────────────────────────────────────────────

def test_normalizer_round_trips_and_keeps_rain_non_negative_and_soil_in_range():
    rng = np.random.default_rng(0)
    data = rng.random((50, 7, 3, 3)).astype("float32")
    data[:, 0] *= 5                                                        # 강수 mm/h
    data[:, 1] += 280                                                      # 기온 K
    n = Normalizer.fit(data, 50)
    back = n.decode(n.encode(data)[None])[0]
    assert np.allclose(back[:, 0], data[:, 0], atol=1e-3) and np.allclose(back[:, 1], data[:, 1], atol=1e-2)
    z = np.full((1, 7, 3, 3), -50.0, dtype="float32")
    dec = n.decode(z[None])[0]
    assert (dec[:, 0] >= 0).all() and (dec[:, 5] >= 0).all() and (dec[:, 5] <= 1).all()


def test_split_is_by_the_farthest_forecast_time_so_windows_do_not_leak_across_the_boundary():
    times = np.arange(np.datetime64("2021-12-31T00:00"), np.datetime64("2022-01-02T00:00"), np.timedelta64(1, "h"))
    # 입력 마지막 시각이 2021-12-31 23:00 이면 가장 먼 예측(+3h)은 2022-01-01 02:00 → 검증
    k = int(np.where(times == np.datetime64("2021-12-31T23:00"))[0][0])
    assert split_of(times, k) == "val"
    assert split_of(times, k - HORIZON) == "train"


def test_time_features_are_periodic():
    t = np.array([np.datetime64("2022-08-20T00:00"), np.datetime64("2022-08-21T00:00")])
    f = time_features(t)
    assert np.allclose(f[:, 0], f[0, 0]) and np.allclose(f[0, :2], [0, 1], atol=1e-6)        # 같은 시각이면 같은 값


def test_derived_fog_uses_observed_rain_history_for_wet_3h():
    c = len(CHANNELS)
    x = np.zeros((1, 3, c, 1, 1), dtype="float32")
    x[:, :, CHANNELS.index("t2m")] = 283.15
    x[:, :, CHANNELS.index("d2m")] = 281.15                                 # ΔT=2
    x[:, :, CHANNELS.index("u10")] = 3.0                                    # U=3 → z=0
    dry = derived(x, np.zeros((1, 2, 1, 1), dtype="float32"))["fog"]
    wet = derived(x, np.full((1, 2, 1, 1), 0.2, dtype="float32"))["fog"]
    assert np.allclose(dry, 0.5)
    assert (wet[0, :2] > 0.5).all() and wet[0, 2, 0, 0] == pytest.approx(0.5)      # 관측 강수는 앞 두 시각의 3시간 창에만 들어간다 (젖음 항 +0.8)


def test_block_bootstrap_flags_a_clear_difference_and_a_noisy_one():
    rng = np.random.default_rng(1)
    days = np.repeat(np.arange(40), 5)
    base = rng.normal(1.0, 0.1, 200)
    mean, lo, hi = block_bootstrap_diff(base - 0.3, base, days)
    assert verdict(lo, hi) == "모델 우세(뚜렷)" and mean == pytest.approx(-0.3, abs=1e-6)
    noisy = rng.normal(0.0, 1.0, 200)
    _, lo2, hi2 = block_bootstrap_diff(noisy, np.zeros(200), days)
    assert verdict(lo2, hi2) == "단정 불가"


# ── LTWR ─────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def terrain():
    ref = pd.read_parquet(sg.BACKEND / "data" / "map_20km_rebuilt" / "static" / "Test_sim_input_200m_bbox_20km.parquet")
    return ltwr.Terrain(ref)


def _risk(terrain, rain=0.0, soil=0.2, snow=0.0, fog=0.0):
    n = len(terrain.static)
    f = lambda v: np.full(n, v, dtype="float32")  # noqa: E731
    return ltwr.risks(f(rain), f(soil), f(snow), f(fog), terrain)


def test_total_is_exactly_the_0_6_0_4_blend_of_mobility_and_sensor(terrain):
    r = _risk(terrain, rain=3.0, soil=0.4, fog=0.5)
    assert np.allclose(r["total"], 0.6 * r["mob"] + 0.4 * r["sen"], atol=1e-6)
    assert 0.0 <= float(min(r["mob"].min(), r["sen"].min())) and float(max(r["mob"].max(), r["sen"].max())) <= 1.0


def test_risk_rises_with_rain_fog_and_wet_ground(terrain):
    dry, wet = _risk(terrain), _risk(terrain, rain=5.0, soil=0.45, fog=0.8)
    assert wet["mob"].mean() > dry["mob"].mean() + 0.2 and wet["sen"].mean() > dry["sen"].mean() + 0.3
    assert _risk(terrain, rain=5.0)["mob"].mean() > _risk(terrain, rain=1.0)["mob"].mean()
    assert _risk(terrain, soil=0.45)["mob"].mean() > _risk(terrain, soil=0.25)["mob"].mean()


def test_rain_curve_passes_through_the_team_threshold_anchors():
    c = ltwr.curve("rain", np.array([0.0, 0.5, 2.0, 5.0, 8.0, 40.0]))
    assert c.tolist() == pytest.approx([0.0, 0.10, 0.35, 0.80, 0.97, 1.0], abs=1e-5)
    assert np.all(np.diff(ltwr.curve("rain", np.linspace(0, 20, 200))) >= -1e-6)               # 단조


def test_roads_soften_wet_ground_and_water_has_no_terrain_baseline(terrain):
    r = _risk(terrain, soil=0.45)
    s = terrain.static
    farm = s.lc_code.values == 40
    on_road, off_road = farm & s.roads_has_drivable_road.values, farm & ~s.roads_has_drivable_road.values
    assert r["mob"][on_road].mean() < r["mob"][off_road].mean()
    water = s.lc_code.values == 80
    assert np.allclose(r["mob"][water], 0.0) and np.allclose(_risk(terrain)["sen"][water], 0.0)


def test_synergy_adds_risk_when_rain_and_wet_soil_occur_together(terrain, monkeypatch):
    with_syn = _risk(terrain, rain=4.0, soil=0.42, fog=0.6)
    monkeypatch.setattr(ltwr, "SYNERGY", 0.0)
    without = _risk(terrain, rain=4.0, soil=0.42, fog=0.6)
    assert (with_syn["mob"] >= without["mob"]).all() and with_syn["mob"].mean() > without["mob"].mean()
    assert with_syn["sen"].mean() > without["sen"].mean()


def test_minute_interpolation_gives_31_layers_for_6_hourly_points_and_keeps_the_blend(terrain):
    hourly = [_risk(terrain, rain=r) for r in (4.0, 3.0, 2.0, 1.0, 0.5, 0.0)]
    out = ltwr.interpolate_minutes(hourly)
    assert len(out) == 31
    assert np.allclose(out[0]["mob"], hourly[0]["mob"]) and np.allclose(out[-1]["mob"], hourly[-1]["mob"])
    mid = out[3]["mob"].mean()                                              # 30분 = 0 시와 1 시의 한가운데
    assert mid == pytest.approx((hourly[0]["mob"].mean() + hourly[1]["mob"].mean()) / 2, abs=1e-5)
    assert np.allclose(out[7]["total"], 0.6 * out[7]["mob"] + 0.4 * out[7]["sen"], atol=1e-6)
    assert len(ltwr.interpolate_minutes(hourly[:4], count=18)) == 18


def test_grid_resampler_keeps_a_constant_field_constant_and_fills_sea_cells(terrain):
    lat, lon = np.array([54.7, 54.6, 54.5, 54.4, 54.3, 54.2]), np.arange(18.1, 18.9, 0.1)
    land = np.ones((6, len(lon)), bool)
    land[:, 0] = False                                                      # 서쪽 열은 바다
    field = np.full((6, len(lon)), 2.0, dtype="float32")
    field[~land] = np.nan
    out = ltwr.GridResampler(lat, lon, land, terrain)(field)
    assert np.allclose(out, 2.0) and out.shape == (len(terrain.static),)


def test_frame_has_the_same_columns_as_the_team_dynamic_files(terrain):
    layer = _risk(terrain, rain=1.0)
    df = ltwr.to_frame(layer, terrain)
    old = pd.read_parquet(sg.BACKEND / "data" / "map_20km" / "dynamic" / "actual" / "sim_cost_map_20230630_2200.parquet")
    assert list(df.columns) == list(old.columns) and len(df) == 111 * 111


# ── 정적 지형 격자 ───────────────────────────────────────────────────────

def test_grid_frame_reproduces_the_team_cell_centers_and_latlon():
    ref = pd.read_parquet(sg.BACKEND / "data" / "map_20km" / "static" / "Test_sim_input_200m_bbox_20km.parquet")
    new = sg.grid_frame()
    j = new.merge(ref, on=["row", "col"], suffixes=("", "_ref"))
    assert len(j) == len(ref) == 111 * 111
    assert np.allclose(j.x_m, j.x_m_ref) and np.allclose(j.y_m, j.y_m_ref) and np.abs(j.lat - j.lat_ref).max() < 1e-9 and np.abs(j.lon - j.lon_ref).max() < 1e-9


def test_road_distance_uses_only_drivable_types_and_caps_at_5000m():
    ln = lambda hw, x0: {"tags": {"highway": hw}, "geometry": [{"lat": 54.4, "lon": 18.4}, {"lat": 54.41, "lon": 18.4}]}  # noqa: E731
    to = sg.Transformer.from_crs(4326, 3035, always_xy=True)
    x, y = to.transform(18.4, 54.405)
    d_drive = sg.road_distance(np.array([x + 30.0]), np.array([y]), [ln("residential", 0)])
    assert 25.0 < float(d_drive[0]) < 35.0                                  # 길에서 약 30m (경도 방향 투영 오차 포함)
    assert float(sg.road_distance(np.array([x]), np.array([y]), [ln("footway", 0)])[0]) == 5000.0     # 보행로만 있으면 주행 가능 도로 없음
    assert float(sg.road_distance(np.array([x + 9000.0]), np.array([y]), [ln("primary", 0)])[0]) == 5000.0


def test_compare_with_reports_perfect_agreement_against_itself():
    ref = pd.read_parquet(sg.BACKEND / "data" / "map_20km" / "static" / "Test_sim_input_200m_bbox_20km.parquet")
    r = sg.compare_with(ref, ref)
    assert r["lc_code_agree"] == r["mask_good_agree"] == r["road_has_agree"] == 1.0 and r["road_dist_mae_m"] == 0.0


def test_rebuilt_static_file_agrees_with_the_team_file_within_the_documented_margins():
    new = pd.read_parquet(sg.BACKEND / "data" / "map_20km_rebuilt" / "static" / "Test_sim_input_200m_bbox_20km.parquet")
    ref = pd.read_parquet(sg.BACKEND / "data" / "map_20km" / "static" / "Test_sim_input_200m_bbox_20km.parquet")
    r = sg.compare_with(new, ref)
    assert r["lc_code_agree"] > 0.99 and r["mask_good_agree"] > 0.99 and r["road_has_agree"] > 0.99 and r["road_dist_mae_m"] < 5.0
