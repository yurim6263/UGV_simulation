"""
backend/app/geo/static_grid.py

정적 지형 격자(200m, EPSG:3035, 111 x 111)를 원자료에서 직접 만든다. 기존 파일(`Test_sim_input_200m_bbox_20km.parquet`)은 팀원이 만든 것이고
생성 코드가 저장소에 없어서, 같은 결과가 나오도록 방법을 역산해 구현했다. 기존 파일과 대조한 일치율(build_static_grid.py 가 출력):

  lc_code     ESA WorldCover 2021 v200 의 10m 지도를 각 셀에서 nearest 로 뽑는다 (rasterio.reproject, Resampling.nearest)   일치 99.6%
              (최빈값/평균/쌍선형으로 합치면 81% 이하였다 → 팀은 nearest 를 썼다)
  mask_good   WorldCover InputQuality 밴드 3(무효 Sentinel-2 관측 비율 %)이 50 이하이면 True                                일치 99.9%
  roads_*     OSM highway 중 motorway/trunk/primary/secondary/tertiary/unclassified/residential(+_link), living_street, service 를
              "주행 가능 도로"로 보고, 셀 중심에서 가장 가까운 도로까지의 거리(m, 최대 5000). 거리 50m 이하면 has=True               has 일치 99.6%, 거리 평균오차 1.1m
              (track 과 footway/path 는 넣으면 오히려 틀렸다.)

기존 파일과 다른 점/한계:
  - 도로는 오늘(2026-10) 내려받은 OSM 이고 팀은 몇 달 전 것이라 조금 다르다. WorldCover 는 같은 2021 버전이다.
  - 위험도 파일이 담는 10,048칸(경로 버퍼)의 정의는 역산하지 못했다. 직선 버퍼, 마스크 tif 팽창으로 맞지 않았다. 그래서 새로 만드는 위험도는 전체 12,321칸을 담는다.
  - 원자료(WorldCover 타일 약 1GB, OSM 도로 JSON 약 100MB)는 저장소에 넣지 않는다. 환경변수 WORLDCOVER_DIR, 도로 캐시 backend/data/osm/roads_raw.json.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path

# 이 PC 처럼 PostgreSQL 이 PROJ_LIB 를 가리키면 rasterio 가 EPSG 데이터베이스 버전 오류를 낸다. rasterio 가 가진 PROJ 데이터를 쓰게 한다 (rasterio import 전에).
_spec = importlib.util.find_spec("rasterio")
if _spec and _spec.submodule_search_locations:
    _proj = Path(list(_spec.submodule_search_locations)[0]) / "proj_data"
    if _proj.exists():
        os.environ["PROJ_LIB"] = os.environ["PROJ_DATA"] = str(_proj)

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
import shapely  # noqa: E402
from pyproj import Transformer  # noqa: E402
from rasterio.crs import CRS  # noqa: E402
from rasterio.transform import Affine  # noqa: E402
from rasterio.warp import Resampling, reproject  # noqa: E402
from shapely import STRtree  # noqa: E402
from shapely.geometry import LineString  # noqa: E402

BACKEND = Path(__file__).resolve().parents[2]
GRID_N, STEP_M = 111, 200.0
X0_CENTER, Y0_CENTER = 4857700.0, 3521300.0          # 셀(row 0, col 0)의 중심 (EPSG:3035). 기존 정적 파일의 x_m, y_m 에서 읽은 값
ROADS_CACHE = BACKEND / "data" / "osm" / "roads_raw.json"
BBOX_ROADS = "54.25,18.19,54.57,18.72"                 # 격자 + 5km 여유 (거리 상한이 5000m)
DRIVABLE = {"motorway", "trunk", "primary", "secondary", "tertiary", "unclassified", "residential",
            "motorway_link", "trunk_link", "primary_link", "secondary_link", "tertiary_link", "living_street", "service"}
ROAD_CAP_M, ROAD_NEAR_M = 5000.0, 50.0
BAD_S2_PCT = 50.0
OVERPASS = ["https://overpass-api.de/api/interpreter", "https://maps.mail.ru/osm/tools/overpass/api/interpreter"]
TILE = "N54E018"


def worldcover_dir() -> Path:
    default = BACKEND.parents[2] / "ERA5_기상데이터_자료" / "ESA_worldcover" / "WORLDCOVER" / "ESA_WORLDCOVER_10M_2021_V200" / "MAP"
    return Path(os.getenv("WORLDCOVER_DIR") or default)


def grid_frame() -> pd.DataFrame:
    rows, cols = np.meshgrid(np.arange(GRID_N), np.arange(GRID_N), indexing="ij")
    x = X0_CENTER + cols * STEP_M
    y = Y0_CENTER - rows * STEP_M
    lon, lat = Transformer.from_crs(3035, 4326, always_xy=True).transform(x.ravel(), y.ravel())
    return pd.DataFrame({"cell_id": np.arange(GRID_N * GRID_N), "row": rows.ravel(), "col": cols.ravel(), "x_m": x.ravel(), "y_m": y.ravel(),
                         "lat": lat, "lon": lon})


def _transform() -> Affine:
    return Affine(STEP_M, 0, X0_CENTER - STEP_M / 2, 0, -STEP_M, Y0_CENTER + STEP_M / 2)


def _sample(path: Path, band: int) -> np.ndarray:
    """WorldCover 타일의 한 밴드를 200m 격자로 nearest 재투영 (111 x 111)."""
    out = np.zeros((GRID_N, GRID_N), dtype=np.float32)
    with rasterio.open(path) as ds:
        reproject(rasterio.band(ds, band), out, dst_transform=_transform(), dst_crs=CRS.from_epsg(3035), resampling=Resampling.nearest)
    return out


def land_cover_and_quality(root: Path | None = None) -> tuple[np.ndarray, np.ndarray]:
    base = (root or worldcover_dir()) / f"ESA_WorldCover_10m_2021_v200_{TILE}_Map"
    lc = _sample(base / f"ESA_WorldCover_10m_2021_v200_{TILE}_Map.tif", 1).astype("int16")
    bad = _sample(base / f"ESA_WorldCover_10m_2021_v200_{TILE}_InputQuality.tif", 3)
    return lc, bad <= BAD_S2_PCT


def fetch_roads(cache: Path = ROADS_CACHE, force: bool = False, retries: int = 4) -> list[dict]:
    """OSM highway 를 Overpass 로 받는다 (한 번 받으면 cache 를 쓴다). 서버가 혼잡하면 다른 서버와 재시도한다."""
    if cache.exists() and not force:
        return json.loads(cache.read_text(encoding="utf-8"))["elements"]
    import requests

    query = f'[out:json][timeout:240];way["highway"]({BBOX_ROADS});out tags geom;'
    last = ""
    for attempt in range(retries):
        for url in OVERPASS:
            try:
                r = requests.post(url, data={"data": query}, headers={"User-Agent": "five-weathers-portfolio/1.0 (student project)"}, timeout=280)
                if r.status_code == 200 and r.content.startswith(b"{"):
                    cache.parent.mkdir(parents=True, exist_ok=True)
                    cache.write_text(json.dumps({"bbox": BBOX_ROADS, "fetched": time.strftime("%Y-%m-%d"), "source": url, "elements": r.json()["elements"]}, ensure_ascii=False), encoding="utf-8")
                    return json.loads(cache.read_text(encoding="utf-8"))["elements"]
                last = f"{url} {r.status_code}"
            except Exception as exc:  # noqa: BLE001
                last = f"{url} {type(exc).__name__}"
        time.sleep(20 * (attempt + 1))
    raise RuntimeError(f"Overpass 에서 도로를 받지 못했습니다 ({last}). 잠시 뒤 다시 시도하세요.")


def road_distance(x_m: np.ndarray, y_m: np.ndarray, elements: list[dict]) -> np.ndarray:
    to3035 = Transformer.from_crs(4326, 3035, always_xy=True)
    lines = []
    for w in elements:
        g = w.get("geometry")
        if not g or len(g) < 2 or w.get("tags", {}).get("highway") not in DRIVABLE:
            continue
        xs, ys = to3035.transform([p["lon"] for p in g], [p["lat"] for p in g])
        lines.append(LineString(list(zip(xs, ys))))
    if not lines:
        return np.full(len(x_m), ROAD_CAP_M, dtype="float32")
    pts = shapely.points(x_m, y_m)
    arr = np.array(lines, dtype=object)
    near = arr[STRtree(arr).nearest(pts)]
    return np.minimum(shapely.distance(pts, near), ROAD_CAP_M).astype("float32")


def build_static_grid(roads: list[dict] | None = None, root: Path | None = None) -> pd.DataFrame:
    df = grid_frame()
    lc, good = land_cover_and_quality(root)
    dist = road_distance(df.x_m.values, df.y_m.values, roads if roads is not None else fetch_roads())
    df["lc_code"] = lc[df.row.values, df.col.values]
    df["mask_good"] = good[df.row.values, df.col.values]
    df["roads_dist_to_drivable_road_m"] = dist
    df["roads_has_drivable_road"] = dist <= ROAD_NEAR_M
    return df


def compare_with(new: pd.DataFrame, ref: pd.DataFrame) -> dict:
    """팀 원본(ref)과 셀별로 맞춰 본다."""
    j = new.merge(ref, on=["row", "col"], suffixes=("", "_ref"))
    return {"cells": int(len(j)),
            "lc_code_agree": float((j.lc_code == j.lc_code_ref).mean()),
            "mask_good_agree": float((j.mask_good == j.mask_good_ref).mean()),
            "road_has_agree": float((j.roads_has_drivable_road == j.roads_has_drivable_road_ref).mean()),
            "road_dist_mae_m": float(np.abs(j.roads_dist_to_drivable_road_m - j.roads_dist_to_drivable_road_m_ref).mean()),
            "latlon_max_diff_deg": float(max(np.abs(j.lat - j.lat_ref).max(), np.abs(j.lon - j.lon_ref).max()))}
