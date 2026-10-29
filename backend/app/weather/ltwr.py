"""
backend/app/weather/ltwr.py

LTWR(Land Tactical Weather Risk, 지상 작전 기상 위험도) 생성기. 팀 결과보고서의 구조(변수별 0~1 위험도 → 기동성/센서 → 0.6 : 0.4 결합 + 복합 악조건 보정)를
따르되, **팀 원본 생성 코드는 저장소에 없어서 세부 식과 기준값은 우리가 정했다. 원본과 같다고 주장하지 않는다.**

원본에서 확인할 수 있었던 것 (기존 위험도 parquet 를 분석)
  - normalized_c_total = 0.6 * c_mob_prime + 0.4 * c_sen_prime  (오차 1e-16). synergy 보정은 기동/센서 값 안에 들어 있다.
  - 값은 0~1, 칸마다 매끈하게 변한다 (이웃 칸 평균 차이 0.016, 전체 표준편차 0.196). 지형만으로 설명되는 분산은 17~20%.
  - 팀 노트북의 임계 구간: 강수 0.5(경미), 2(중간), 5(강함, 소프트 회피, "5 mm/h 에서 센서 성능 붕괴 보고"), 8 mm/h(매우 강함, 하드 회피).
  - 안개 확률 식(app/weather/fog.py).
우리가 정한 것 (가정값, 관측으로 보정하지 않았다)
  - 변수별 위험 곡선: 위 임계 구간을 기준점으로 단조 PCHIP 곡선 (RAIN_ANCHORS, SOIL_ANCHORS, SNOW_ANCHORS).
  - 기동성: 강수, 토양수분(연약지반), 적설의 noisy-OR.  센서: 강수, 안개의 noisy-OR.
  - 지형 보정: 토지 피복별 바탕 위험(BASE_MOB/BASE_SEN)과 젖은 땅 민감도(SOFTNESS), 도로 50m 안이면 젖은 땅 영향 반감.
  - synergy: 강수 x 토양수분(기동), 강수 x 안개(센서) 곱을 더한다 (SYNERGY).
  - 수역(80)은 엔진이 통행 불가로 막으므로 위험도 계산에서 지형 보정 없이 날씨 값만 둔다.
  - 시간: 시간별 값을 10분 단위로 선형 보간한다. 팀은 "보수적 선형보간"이라 했지만 정확한 정의를 알 수 없어 보수화 없이 선형 보간만 했다.
  - 공간: ERA5-Land(0.1°, 약 11km) 값을 200m 격자로 쌍선형 보간한다. 세부 위치별 날씨 차이를 말해 주지 않는다 (보간은 정보를 늘리지 않는다).
  - 적설과 풍속: 풍속은 안개 식에만 쓰인다. 적설은 8월에는 0이다.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.interpolate import PchipInterpolator, RegularGridInterpolator

from app.weather.fog import fog_probability, wet_3h
from app.weather.scenario_index import fill_nearest

W_MOB, W_SEN = 0.6, 0.4

RAIN_ANCHORS = ([0, 0.5, 2, 5, 8, 15], [0, 0.10, 0.35, 0.80, 0.97, 1.0])        # mm/h → 0~1 (팀 노트북 임계 구간)
SOIL_ANCHORS = ([0.0, 0.20, 0.30, 0.40, 0.50, 0.7], [0, 0, 0.2, 0.6, 1.0, 1.0])  # 체적 토양수분 m3/m3 → 0~1 (연약지반)
SNOW_ANCHORS = ([0, 0.02, 0.10, 0.30, 1.0], [0, 0.2, 0.6, 1.0, 1.0])             # 적설 깊이(수당량) m → 0~1
_CURVES = {k: PchipInterpolator(*v, extrapolate=False) for k, v in (("rain", RAIN_ANCHORS), ("soil", SOIL_ANCHORS), ("snow", SNOW_ANCHORS))}

W_RAIN_MOB, W_SOIL_MOB, W_SNOW_MOB = 0.70, 0.80, 0.80
W_RAIN_SEN, W_FOG_SEN = 0.90, 0.90
SYNERGY = 0.15
ROAD_SOIL_FACTOR = 0.5                    # 포장도로(50m 안)에서는 젖은 땅의 영향이 절반
# WorldCover 코드별: 바탕 위험(날씨 없이도 가는 어려움), 젖은 땅 민감도, 센서 가림(식생/건물)
BASE_MOB = {10: 0.25, 20: 0.18, 30: 0.10, 40: 0.10, 50: 0.05, 60: 0.15, 70: 0.30, 80: 0.0, 90: 0.40, 95: 0.40, 100: 0.20}
SOFTNESS = {10: 0.6, 20: 0.7, 30: 0.8, 40: 1.0, 50: 0.3, 60: 0.9, 70: 0.9, 80: 0.0, 90: 1.2, 95: 1.2, 100: 0.8}
BASE_SEN = {10: 0.15, 20: 0.08, 30: 0.02, 40: 0.02, 50: 0.10, 60: 0.02, 70: 0.05, 80: 0.0, 90: 0.05, 95: 0.10, 100: 0.05}
DEFAULT_CODE = 40


def curve(name: str, x: np.ndarray) -> np.ndarray:
    lo, hi = {"rain": RAIN_ANCHORS, "soil": SOIL_ANCHORS, "snow": SNOW_ANCHORS}[name][0][0], {"rain": RAIN_ANCHORS, "soil": SOIL_ANCHORS, "snow": SNOW_ANCHORS}[name][0][-1]
    return np.nan_to_num(_CURVES[name](np.clip(x, lo, hi)), nan=0.0).astype("float32")


def _by_code(table: dict, codes: np.ndarray) -> np.ndarray:
    return np.vectorize(lambda c: table.get(int(c), table[DEFAULT_CODE]), otypes=[float])(codes).astype("float32")


class Terrain:
    """정적 격자에서 위험도 계산에 필요한 셀별 값."""

    def __init__(self, static: pd.DataFrame):
        s = static.sort_values(["row", "col"]).reset_index(drop=True)
        self.static = s
        self.base_mob = _by_code(BASE_MOB, s.lc_code.values)
        self.base_sen = _by_code(BASE_SEN, s.lc_code.values)
        self.softness = _by_code(SOFTNESS, s.lc_code.values)
        self.road_factor = np.where(s.roads_has_drivable_road.values, ROAD_SOIL_FACTOR, 1.0).astype("float32")
        self.lat2d = s.lat.values.reshape(-1)
        self.lon2d = s.lon.values.reshape(-1)


def risks(rain, soil, snow, fog, terrain: Terrain) -> dict[str, np.ndarray]:
    """200m 격자 위(1차원, 셀 순서) 날씨 값 → 기동성/센서/종합 위험도"""
    r, s, n = curve("rain", rain), curve("soil", soil), curve("snow", snow)
    mob_w = 1 - (1 - W_RAIN_MOB * r) * (1 - W_SOIL_MOB * s * terrain.softness * terrain.road_factor) * (1 - W_SNOW_MOB * n)
    sen_w = 1 - (1 - W_RAIN_SEN * r) * (1 - W_FOG_SEN * fog)
    mob = terrain.base_mob + (1 - terrain.base_mob) * mob_w + SYNERGY * r * s * terrain.softness * terrain.road_factor
    sen = terrain.base_sen + (1 - terrain.base_sen) * sen_w + SYNERGY * r * fog
    mob, sen = np.clip(mob, 0, 1).astype("float32"), np.clip(sen, 0, 1).astype("float32")
    return {"mob": mob, "sen": sen, "total": (W_MOB * mob + W_SEN * sen).astype("float32")}


def coarse_fields(data: np.ndarray, times_rain_hist: np.ndarray | None = None) -> dict[str, np.ndarray]:
    """data: (T, C, H, W) 연속된 시간별 물리값(채널은 dataset.CHANNELS 순서) → 각 시각의 rain, swvl1, sde, fog (T, H, W). 안개의 wet_3h 는 이 T 안에서 계산한다."""
    rain, t2m, d2m, u10, v10, swvl1, sde = (data[:, i] for i in range(7))
    wind = np.hypot(u10, v10)
    return {"rain": rain, "swvl1": swvl1, "sde": sde, "fog": fog_probability(t2m, d2m, wind, wet_3h(rain, axis=0))}


class GridResampler:
    """거친 격자(위도 내림차순 가능) → 작전 구역 200m 격자 쌍선형 보간. 바다 칸(NaN)은 가장 가까운 육지 값으로 채운다."""

    def __init__(self, lat: np.ndarray, lon: np.ndarray, land: np.ndarray, terrain: Terrain):
        self.order = np.argsort(lat)
        self.lat, self.lon, self.land = lat[self.order], lon, land[self.order]
        self.pts = np.stack([terrain.lat2d, terrain.lon2d], axis=-1)

    def __call__(self, field: np.ndarray) -> np.ndarray:
        f = fill_nearest(field[self.order], self.land)
        return RegularGridInterpolator((self.lat, self.lon), f, bounds_error=False, fill_value=None)(self.pts).astype("float32")


def hourly_layers(fields: dict[str, np.ndarray], resampler: GridResampler, terrain: Terrain) -> list[dict[str, np.ndarray]]:
    """시각별 coarse 장 → 시각별 위험도 (200m 격자)"""
    out = []
    for k in range(fields["rain"].shape[0]):
        g = {n: resampler(fields[n][k]) for n in ("rain", "swvl1", "sde", "fog")}
        out.append(risks(g["rain"], g["swvl1"], g["sde"], g["fog"], terrain))
    return out


def interpolate_minutes(layers: list[dict[str, np.ndarray]], step_min: int = 10, hours_between: int = 1, count: int | None = None) -> list[dict[str, np.ndarray]]:
    """시간별 위험도를 step_min 분 간격으로 선형 보간한다 (count 를 주면 앞에서 그 개수만)."""
    per = 60 * hours_between // step_min
    out = []
    for k in range(len(layers) - 1):
        for j in range(per):
            w = j / per
            out.append({n: ((1 - w) * layers[k][n] + w * layers[k + 1][n]).astype("float32") for n in ("mob", "sen")})
    out.append({n: layers[-1][n] for n in ("mob", "sen")})
    for o in out:
        o["total"] = (W_MOB * o["mob"] + W_SEN * o["sen"]).astype("float32")
    return out[:count] if count else out


def to_frame(layer: dict[str, np.ndarray], terrain: Terrain) -> pd.DataFrame:
    s = terrain.static
    return pd.DataFrame({"cell_id": s.cell_id.values, "row": s.row.values, "col": s.col.values, "x_m": s.x_m.values, "y_m": s.y_m.values,
                         "lon": s.lon.values, "lat": s.lat.values, "normalized_c_total": layer["total"], "c_mob_prime": layer["mob"], "c_sen_prime": layer["sen"]})
