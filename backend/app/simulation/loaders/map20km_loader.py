"""
backend/app/simulation/loaders/map20km_loader.py

20km x 20km 맵 전용 로더 (신규 추가 — 기존 로더 비침범).

담당 데이터:
  backend/data/map_20km/static/Test_sim_input_200m_bbox_20km.parquet
      컬럼: cell_id, row, col, x_m, y_m, lat, lon, lc_code, mask_good,
             roads_dist_to_drivable_road_m, roads_has_drivable_road
  backend/data/map_20km/dynamic/actual/sim_cost_map_YYYYMMDD_HHMM.parquet
      컬럼: cell_id, row, col, x_m, y_m, lon, lat,
             normalized_c_total, c_mob_prime, c_sen_prime

그리드 실제 크기: 111 × 111 (200m 해상도, ~20km × 20km)
좌표 범위: lat 54.30~54.52, lon 18.27~18.64 (폴란드 북부)
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

from app.simulation.terrain import DEFAULT_COST_MULT, LC_COST_MULT

# ── 경로 상수 ─────────────────────────────────────────────
_BASE_DIR = Path(__file__).resolve().parents[3] / "data" / os.getenv("MAP20KM_DIR", "map_20km")      # sim_config.MAP20KM_DIR 와 같은 폴더
_STATIC_DIR = _BASE_DIR / "static"
_TERRAIN_PATH = _STATIC_DIR / "Test_sim_input_200m_bbox_20km.parquet"
_BUFFER_TIF   = _STATIC_DIR / "route_buffer_mask_5km_200m.tif"
_ACTUAL_DIR   = _BASE_DIR / "dynamic" / "actual"
_FORECAST_DIR = _BASE_DIR / "dynamic" / "forecast"

# 실제 그리드 크기 (parquet 실측)
GRID_NY = 111
GRID_NX = 111

# lc_code → 지형 통행 계수 (경로 계획용, app/simulation/terrain.py 가 단일 정의)
_LC_COST: dict[int, float] = LC_COST_MULT

# lc_code → RGBA 색상 (Leaflet 오버레이 PNG용)
LC_COLORS_RGBA: dict[int, tuple[int, int, int, int]] = {
    10: (160, 210, 140, 200),   # 농지: 연두색
    20: (200, 230, 170, 180),   # 초원
    30: (40,  120,  40, 220),   # 숲: 진녹
    40: (150, 150, 150, 200),   # 도시: 회색
    50: (50,  130, 240, 220),   # 수역: 파랑 (통행불가)
    60: (230, 200,  90, 200),   # 도로: 황색
    80: (200,  50,  50, 230),   # 위험지형: 적색 (통행불가)
    90: (30,   80, 200, 230),   # 하천: 남색 (통행불가)
    100: (180, 180, 200, 180),  # 기타
}


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _read_dynamic_grid(path: str | Path, column: str = "normalized_c_total") -> np.ndarray:
    """동적 parquet → (ny, nx) float32 배열."""
    df = pd.read_parquet(path)
    ny = int(df["row"].max()) + 1
    nx = int(df["col"].max()) + 1
    grid = np.zeros((ny, nx), dtype=np.float32)
    rows  = df["row"].values.astype(int)
    cols  = df["col"].values.astype(int)
    costs = df[column].values.astype(np.float32)
    mask  = (rows < ny) & (cols < nx)
    grid[rows[mask], cols[mask]] = costs[mask]
    return grid


def _lc_to_cost(code: float) -> float:
    return _LC_COST.get(int(code), DEFAULT_COST_MULT)


_v_lc_cost = np.vectorize(_lc_to_cost)


# ── 공개 API ──────────────────────────────────────────────

def load_terrain_df() -> pd.DataFrame:
    """정적 지형 전체 DataFrame 반환 (lat/lon 포함)."""
    if not _TERRAIN_PATH.exists():
        raise FileNotFoundError(f"지형 파일 없음: {_TERRAIN_PATH}")
    return pd.read_parquet(_TERRAIN_PATH)


def load_terrain_grid() -> np.ndarray:
    """
    정적 지형 parquet → (ny, nx) float32 비용 배열.
    lc_code → 통행 비용 (999.0 = 통행불가).
    """
    df = load_terrain_df()
    ny = int(df["row"].max()) + 1
    nx = int(df["col"].max()) + 1

    grid = np.zeros((ny, nx), dtype=np.float32)
    rows  = df["row"].values.astype(int)
    cols  = df["col"].values.astype(int)
    codes = df["lc_code"].values.astype(float)
    grid[rows, cols] = codes

    return _v_lc_cost(grid).astype(np.float32)


def get_map_bounds() -> dict:
    """위경도 경계 + 중심 반환."""
    df = load_terrain_df()
    return {
        "min_lat": float(df["lat"].min()),
        "max_lat": float(df["lat"].max()),
        "min_lng": float(df["lon"].min()),
        "max_lng": float(df["lon"].max()),
        "center_lat": float(df["lat"].mean()),
        "center_lng": float(df["lon"].mean()),
    }


def load_latest_actual(column: str = "normalized_c_total") -> Optional[np.ndarray]:
    """가장 최근 실황 동적 레이어 반환. 파일 없으면 None."""
    files = sorted(glob.glob(str(_ACTUAL_DIR / "*.parquet")))
    if not files:
        return None
    return _read_dynamic_grid(files[-1], column=column)


def load_actual_at(time_str: str, column: str = "normalized_c_total") -> Optional[np.ndarray]:
    """특정 시각 실황 레이어 반환. time_str 예: '20230630_2200'"""
    path = _ACTUAL_DIR / f"sim_cost_map_{time_str}.parquet"
    if not path.exists():
        return None
    return _read_dynamic_grid(path, column=column)


def list_actual_times() -> list[str]:
    """사용 가능한 실황 시간 문자열 목록 (정렬)."""
    files = sorted(glob.glob(str(_ACTUAL_DIR / "*.parquet")))
    return [
        os.path.basename(f).replace("sim_cost_map_", "").replace(".parquet", "")
        for f in files
    ]


def get_map_metadata() -> dict:
    """중앙 맵에서 쓸 격자 메타 정보 반환."""
    return {
        "grid_size": {"ny": GRID_NY, "nx": GRID_NX},
        "resolution_m": 200,
        "area_km": "20x20",
        "actual_times": list_actual_times(),
    }


def grid_to_cells(grid: np.ndarray, threshold: Optional[float] = None) -> list[dict]:
    """2D 배열 → [{row, col, value}, ...] 직렬화."""
    ny, nx = grid.shape
    result = []
    for r in range(ny):
        for c in range(nx):
            v = float(grid[r, c])
            if threshold is None or v >= threshold:
                result.append({"row": r, "col": c, "value": round(v, 4)})
    return result
