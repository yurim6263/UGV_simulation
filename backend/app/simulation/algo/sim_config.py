"""
backend/app/simulation/algo/sim_config.py

시뮬레이션 알고리즘 설정 + 격자↔위경도 변환.

격자 크기와 좌표계는 하드코딩하지 않고 정적 지형 parquet(row, col, lat, lon)에서 읽는다.
기본 데이터셋은 그단스크 인근 20km (200m 해상도, 111×111).

데이터셋 선택:
    환경변수 SIM_DATASET=map_20km (기본) | map_2km (소규모 개발용 샘플)
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from functools import lru_cache

import numpy as np
import pandas as pd

# backend/ 루트 기준 절대 경로
_BASE = os.path.dirname(os.path.dirname(os.path.dirname(
    os.path.dirname(os.path.abspath(__file__))
)))

_DATASETS = {
    "map_20km": {
        "terrain": os.path.join(_BASE, "data", "map_20km", "static",
                                "Test_sim_input_200m_bbox_20km.parquet"),
        "dynamic": os.path.join(_BASE, "data", "map_20km", "dynamic"),
    },
    "map_2km": {
        "terrain": os.path.join(_BASE, "data", "map", "static",
                                "Test_sim_input_200m_bbox_2km.parquet"),
        "dynamic": os.path.join(_BASE, "data", "map", "dynamic"),
    },
}

DATASET = os.getenv("SIM_DATASET", "map_20km")
if DATASET not in _DATASETS:
    raise ValueError(f"SIM_DATASET={DATASET!r} 는 {sorted(_DATASETS)} 중 하나여야 합니다.")


@dataclass(frozen=True)
class GridMeta:
    """정적 격자 메타데이터. 행(row)은 북→남, 열(col)은 서→동 방향이다."""
    ny: int
    nx: int
    lat: np.ndarray            # (ny, nx) 셀 중심 위도
    lon: np.ndarray            # (ny, nx) 셀 중심 경도
    lat_coef: tuple            # lat ≈ a0 + a1·row + a2·col
    lon_coef: tuple            # lon ≈ b0 + b1·row + b2·col

    @property
    def bounds(self) -> dict:
        return {
            "min_lat": float(self.lat.min()), "max_lat": float(self.lat.max()),
            "min_lon": float(self.lon.min()), "max_lon": float(self.lon.max()),
        }


@lru_cache(maxsize=4)
def load_grid_meta(terrain_path: str) -> GridMeta:
    if not os.path.exists(terrain_path):
        raise FileNotFoundError(f"지형 파일 없음: {terrain_path}")
    df = pd.read_parquet(terrain_path, columns=["row", "col", "lat", "lon"])
    rows = df["row"].to_numpy(dtype=int)
    cols = df["col"].to_numpy(dtype=int)
    ny, nx = int(rows.max()) + 1, int(cols.max()) + 1
    if len(df) != ny * nx:
        raise ValueError(f"격자가 완전하지 않습니다: {len(df)}행 != {ny}×{nx}")

    lat = np.full((ny, nx), np.nan)
    lon = np.full((ny, nx), np.nan)
    lat[rows, cols] = df["lat"].to_numpy()
    lon[rows, cols] = df["lon"].to_numpy()

    design = np.c_[np.ones(len(df)), rows, cols]
    lat_coef, *_ = np.linalg.lstsq(design, df["lat"].to_numpy(), rcond=None)
    lon_coef, *_ = np.linalg.lstsq(design, df["lon"].to_numpy(), rcond=None)
    return GridMeta(ny, nx, lat, lon, tuple(lat_coef), tuple(lon_coef))


_META = load_grid_meta(_DATASETS[DATASET]["terrain"])


class SimAlgoConfig:
    """Environment / PathFinder3D / SimulationEngine 에 전달되는 설정 객체."""

    DATASET: str = DATASET

    # ── 데이터 경로 ───────────────────────────────────────────────────────
    TERRAIN_PATH: str = _DATASETS[DATASET]["terrain"]
    DYNAMIC_DIR: str = _DATASETS[DATASET]["dynamic"]

    # ── 그리드 설정 (정적 데이터에서 읽음) ────────────────────────────────
    GRID_SIZE: tuple = (_META.ny, _META.nx)
    CELL_SIZE_M: float = 200.0

    # 시공간 그래프 타임 레이어 수 (10분 × 18 = 180분 예보)
    NT: int = 18

    # ── AP 설정 ──────────────────────────────────────────────────────────
    AP_UNIT_COST: float = 100_000.0  # 타일 비용 → AP 변환 계수 (레거시 경로용)

    @classmethod
    def meta(cls) -> GridMeta:
        return _META

    @classmethod
    def bounds(cls) -> dict:
        return _META.bounds

    @classmethod
    def grid_to_latlon(cls, row: float, col: float) -> tuple[float, float]:
        """그리드 (row, col) → (lat, lon). 정수 좌표는 실제 셀 중심값, 소수 좌표는 선형 보간."""
        r, c = float(row), float(col)
        if r.is_integer() and c.is_integer():
            ri, ci = int(r), int(c)
            if 0 <= ri < _META.ny and 0 <= ci < _META.nx:
                return float(_META.lat[ri, ci]), float(_META.lon[ri, ci])
        a0, a1, a2 = _META.lat_coef
        b0, b1, b2 = _META.lon_coef
        return a0 + a1 * r + a2 * c, b0 + b1 * r + b2 * c

    @classmethod
    def latlon_to_grid(cls, lat: float, lon: float, margin_cells: float = 1.0) -> tuple[int, int]:
        """(lat, lon) → 가장 가까운 그리드 (row, col).

        작전 구역 밖(경계에서 margin_cells 초과)이면 ValueError.
        예전처럼 조용히 경계로 clamp 하면 모든 입력이 같은 셀로 뭉개지기 때문이다.
        """
        a0, a1, a2 = _META.lat_coef
        b0, b1, b2 = _META.lon_coef
        # 2×2 선형계 [a1 a2; b1 b2]·[row, col] = [lat-a0, lon-b0]
        det = a1 * b2 - a2 * b1
        row_f = ((lat - a0) * b2 - a2 * (lon - b0)) / det
        col_f = (a1 * (lon - b0) - b1 * (lat - a0)) / det

        if not (-margin_cells <= row_f <= _META.ny - 1 + margin_cells
                and -margin_cells <= col_f <= _META.nx - 1 + margin_cells):
            b = _META.bounds
            raise ValueError(
                f"좌표 ({lat:.5f}, {lon:.5f}) 가 작전 구역 밖입니다. "
                f"허용 범위: 위도 {b['min_lat']:.4f}~{b['max_lat']:.4f}, "
                f"경도 {b['min_lon']:.4f}~{b['max_lon']:.4f}"
            )

        r0 = int(np.clip(round(row_f), 0, _META.ny - 1))
        c0 = int(np.clip(round(col_f), 0, _META.nx - 1))
        # 투영 왜곡 보정: 주변 3×3 중 실제 셀 중심이 가장 가까운 셀 선택
        cos_lat = math.cos(math.radians(lat))     # 경도 1도의 길이는 위도에 따라 줄어든다
        best, best_d = (r0, c0), float("inf")
        for rr in range(max(0, r0 - 1), min(_META.ny, r0 + 2)):
            for cc in range(max(0, c0 - 1), min(_META.nx, c0 + 2)):
                d = (_META.lat[rr, cc] - lat) ** 2 + ((_META.lon[rr, cc] - lon) * cos_lat) ** 2
                if d < best_d:
                    best, best_d = (rr, cc), d
        return best
