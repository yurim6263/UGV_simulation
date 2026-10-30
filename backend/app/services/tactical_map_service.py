"""
backend/app/services/tactical_map_service.py

전술 맵 데이터 조립 서비스 (신규 — dashboard_service.py 비침범).

담당:
  - map20km_loader 호출 → JSON 직렬화 가능한 응답 조립
  - 위험도 / 기동성 / 센서 탭별 레이어 선택
  - 지휘관/통제관 역할 기반 경로 필터링
  - 지형 PNG 이미지 생성 (Leaflet imageOverlay용)
  - 비용 레이어 PNG 이미지 생성
  - Leaflet HTML 템플릿 문자열 생성

레이어 컬럼 매핑 (동적 parquet):
  위험도(risk)    : normalized_c_total  (0~1, 높을수록 위험)
  기동성(mobility): c_mob_prime         (0~1, 높을수록 기동 어려움)
  센서(sensor)    : c_sen_prime         (0~1, 높을수록 탐지 위험)

username → unit_no 매핑:
  user1 → 1, user2 → 2, user3 → 3
"""

from __future__ import annotations

import io
import logging
from functools import lru_cache
from typing import Optional

import numpy as np

from app.simulation.terrain import BLOCKED_COST

from app.simulation.loaders.map20km_loader import (
    _ACTUAL_DIR,
    _BASE_DIR,
    GRID_NX,
    GRID_NY,
    LC_COLORS_RGBA,
    get_map_bounds,
    get_map_metadata,
    grid_to_cells,
    load_latest_actual,
    load_terrain_df,
    load_terrain_grid,
)
from app.db.schemas.tactical_map import (
    CommanderMapOut,
    GridCell,
    GridSize,
    MapBaseOut,
    MapLayerOut,
    MapMetaOut,
    OperatorMapOut,
    RoutePoint,
    UnitRoute,
)

logger = logging.getLogger(__name__)

_TERRAIN_THRESHOLD = 1.0
_DYNAMIC_THRESHOLD = 0.05

_USERNAME_TO_UNIT: dict[str, int] = {
    "user1": 1,
    "user2": 2,
    "user3": 3,
}

# 비용 레이어 컬럼 매핑
_LAYER_COLUMN: dict[str, str] = {
    "risk":     "normalized_c_total",
    "mobility": "c_mob_prime",
    "sensor":   "c_sen_prime",
}

# Leaflet 마커 색상 (제대별)
_UNIT_COLORS = ["#e67e22", "#3b82f6", "#10b981"]


# ── 내부 헬퍼 ─────────────────────────────────────────────

def _make_grid_size() -> GridSize:
    return GridSize(ny=GRID_NY, nx=GRID_NX)


def _make_meta() -> MapMetaOut:
    raw = get_map_metadata()
    return MapMetaOut(
        grid_size=GridSize(**raw["grid_size"]),
        resolution_m=raw["resolution_m"],
        area_km=raw["area_km"],
        actual_times=raw["actual_times"],
    )


def _terrain_to_base_out(terrain: np.ndarray) -> MapBaseOut:
    cells = [
        GridCell(row=d["row"], col=d["col"], value=d["value"])
        for d in grid_to_cells(terrain, threshold=_TERRAIN_THRESHOLD)
    ]
    return MapBaseOut(cells=cells, grid_size=_make_grid_size(), meta=_make_meta())


def _dynamic_to_layer_out(
    dynamic: np.ndarray, layer_type: str, time_str: Optional[str] = None
) -> MapLayerOut:
    cells = [
        GridCell(row=d["row"], col=d["col"], value=d["value"])
        for d in grid_to_cells(dynamic, threshold=_DYNAMIC_THRESHOLD)
    ]
    return MapLayerOut(
        layer_type=layer_type, time_str=time_str,
        cells=cells, grid_size=_make_grid_size(),
    )


def _make_mobility_layer(terrain: np.ndarray) -> MapLayerOut:
    """지형 통행 계수 → 기동 어려움(0~1). 통행 불가는 1, 계수가 클수록 1에 가깝다.

    (이전에는 `1 - 비용/최대`라 비용이 높을수록 값이 낮아지는 반대 방향이었다.)
    """
    blocked = terrain >= BLOCKED_COST
    passable = terrain[~blocked]
    if passable.size and passable.max() > passable.min():
        scaled = (terrain - passable.min()) / (passable.max() - passable.min())
        normalized = np.where(blocked, 1.0, 0.1 + 0.8 * scaled)
    else:
        normalized = np.where(blocked, 1.0, 0.0)
    return _dynamic_to_layer_out(normalized.astype(np.float32), "mobility")


def _run_routes(run_id: int) -> list[UnitRoute]:
    """향후 DB run_route 테이블 연동으로 확장."""
    return []


# ── PNG 이미지 생성 ───────────────────────────────────────

@lru_cache(maxsize=1)
def generate_terrain_png_bytes() -> bytes:
    """
    지형 lc_code → RGBA PNG bytes (L.imageOverlay용).
    lru_cache: 최초 1회 생성 후 메모리 캐시.
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Pillow 패키지가 필요합니다: pip install Pillow")

    df = load_terrain_df()
    ny = int(df["row"].max()) + 1
    nx = int(df["col"].max()) + 1

    img_array = np.zeros((ny, nx, 4), dtype=np.uint8)

    for code, color in LC_COLORS_RGBA.items():
        mask = df["lc_code"].values == code
        rows = df["row"].values[mask].astype(int)
        cols = df["col"].values[mask].astype(int)
        valid = (rows < ny) & (cols < nx)
        img_array[rows[valid], cols[valid]] = color

    # 2× 업스케일 (각 셀 → 2×2 픽셀)
    img = Image.fromarray(img_array, "RGBA")
    img = img.resize((nx * 2, ny * 2), Image.NEAREST)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


def generate_cost_png_bytes(layer_type: str = "risk") -> bytes:
    """
    동적 비용 레이어 → RGBA PNG bytes.
    낮은 비용(0) = 투명, 높은 비용(1) = 붉은 반투명.
    """
    try:
        from PIL import Image
    except ImportError:
        raise RuntimeError("Pillow 패키지가 필요합니다: pip install Pillow")

    column = _LAYER_COLUMN.get(layer_type, "normalized_c_total")
    grid = load_latest_actual(column=column)

    if grid is None:
        # 데이터 없으면 빈 투명 이미지
        img = Image.new("RGBA", (GRID_NX * 2, GRID_NY * 2), (0, 0, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        return buf.getvalue()

    ny, nx = grid.shape
    img_array = np.zeros((ny, nx, 4), dtype=np.uint8)

    # 색상 매핑: 0 → 투명 초록, 1 → 불투명 빨강
    norm = np.clip(grid, 0.0, 1.0)
    r = (norm * 220).astype(np.uint8)
    g = ((1.0 - norm) * 180).astype(np.uint8)
    b = np.zeros_like(r)
    a = (norm * 180 + 30).astype(np.uint8)  # threshold 미만 셀은 거의 투명

    img_array[:, :, 0] = r
    img_array[:, :, 1] = g
    img_array[:, :, 2] = b
    img_array[:, :, 3] = np.where(norm < 0.05, 0, a)

    img = Image.fromarray(img_array, "RGBA")
    img = img.resize((nx * 2, ny * 2), Image.NEAREST)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=1)
def generate_buffer_png_bytes() -> bytes:
    """
    route_buffer_mask_5km_200m.tif → RGBA PNG bytes.
    값 1(버퍼 내부) = 반투명 황색, 0 = 완전 투명.
    rasterio + PIL 사용. lru_cache로 최초 1회만 생성.
    """
    try:
        from PIL import Image
        import rasterio
        from rasterio.warp import reproject, Resampling
        from rasterio.crs import CRS
    except ImportError as e:
        raise RuntimeError(f"필요 패키지 없음: {e}")

    _tif_path = _BASE_DIR / "static" / "route_buffer_mask_5km_200m.tif"
    if not _tif_path.exists():
        raise FileNotFoundError(f"TIF 파일 없음: {_tif_path}")

    with rasterio.open(_tif_path) as ds:
        # EPSG:3035 → EPSG:4326 (WGS84) 리프로젝션
        dst_crs = CRS.from_epsg(4326)
        from rasterio.warp import calculate_default_transform
        transform, width, height = calculate_default_transform(
            ds.crs, dst_crs, ds.width, ds.height, *ds.bounds
        )
        out_arr = np.zeros((height, width), dtype=np.uint8)
        reproject(
            source=rasterio.band(ds, 1),
            destination=out_arr,
            src_transform=ds.transform,
            src_crs=ds.crs,
            dst_transform=transform,
            dst_crs=dst_crs,
            resampling=Resampling.nearest,
        )

    # 버퍼 내부(1) = 반투명 황색, 외부(0) = 투명
    ny, nx = out_arr.shape
    img_array = np.zeros((ny, nx, 4), dtype=np.uint8)
    mask = out_arr == 1
    img_array[mask] = (255, 200, 0, 140)  # 황색, alpha=140

    img = Image.fromarray(img_array, "RGBA")
    # 시각적으로 선명하게 2× 업스케일
    img = img.resize((nx * 2, ny * 2), Image.NEAREST)

    buf = io.BytesIO()
    img.save(buf, format="PNG", optimize=True)
    return buf.getvalue()


# ── Leaflet HTML 생성 ────────────────────────────────────

def generate_leaflet_html(
    backend_url: str,
    markers: Optional[list[dict]] = None,
) -> str:
    """
    CommanderInputPage 용 Leaflet HTML 문자열 반환.

    backend_url: 백엔드 HTTP 주소 (예: http://127.0.0.1:8000)
    markers: [{"id":"u1","lat":54.41,"lng":18.46,"label":"1제대","color":"#e67e22"}, ...]

    지형 PNG: backend_url/api/map/tactical/terrain-image 에서 로드.
    마커:     markers 리스트를 JS 초기화 코드로 직접 embed.
    postMessage 수신도 지원 → 마커 동적 업데이트 가능.
    """
    bounds = get_map_bounds()
    min_lat = bounds["min_lat"]
    max_lat = bounds["max_lat"]
    min_lng = bounds["min_lng"]
    max_lng = bounds["max_lng"]
    center_lat = bounds["center_lat"]
    center_lng = bounds["center_lng"]

    # JS용 마커 배열 문자열
    markers_json = "[]"
    if markers:
        import json
        markers_json = json.dumps(markers, ensure_ascii=False)

    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:100%; height:100%; background:#0b1a2e; }}
  #map {{ width:100%; height:100%; }}
  .legend {{
    background: rgba(15,25,50,0.85);
    border: 1px solid rgba(255,255,255,0.15);
    border-radius: 8px;
    padding: 8px 12px;
    color: #e2e8f0;
    font-size: 12px;
    line-height: 1.7;
  }}
  .legend-dot {{
    display: inline-block;
    width: 12px; height: 12px;
    border-radius: 50%;
    margin-right: 5px;
    vertical-align: middle;
  }}
</style>
</head>
<body>
<div id="map"></div>
<script>
(function() {{
  var map = L.map('map', {{
    zoomControl: true,
    attributionControl: false,
    preferCanvas: true
  }}).setView([{center_lat:.5f}, {center_lng:.5f}], 11);

  // 베이스 타일 (약간 어둡게)
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 18,
    opacity: 0.55
  }}).addTo(map);

  // 지형 오버레이 (백엔드 PNG)
  var imageBounds = [[{min_lat:.6f}, {min_lng:.6f}], [{max_lat:.6f}, {max_lng:.6f}]];
  L.imageOverlay(
    '{backend_url}/api/map/tactical/terrain-image',
    imageBounds,
    {{ opacity: 0.75, interactive: false }}
  ).addTo(map);

  // 지도 범위 표시
  map.fitBounds(imageBounds, {{ padding: [10, 10] }});

  // 범례
  var legend = L.control({{ position: 'bottomleft' }});
  legend.onAdd = function() {{
    var div = L.DomUtil.create('div', 'legend');
    div.innerHTML =
      '<b style="font-size:13px;">지형 범례</b><br>' +
      '<span class="legend-dot" style="background:#a0d28c"></span>농지<br>' +
      '<span class="legend-dot" style="background:#287828"></span>숲<br>' +
      '<span class="legend-dot" style="background:#969696"></span>도시<br>' +
      '<span class="legend-dot" style="background:#3282f0"></span>수역<br>' +
      '<span class="legend-dot" style="background:#e6c85a"></span>도로<br>' +
      '<span class="legend-dot" style="background:#c83232"></span>통행불가';
    return div;
  }};
  legend.addTo(map);

  // ── 목적지 마커 ───────────────────────────────────────
  var markers = {{}};

  function makeIcon(color) {{
    return L.divIcon({{
      html: '<div style="background:' + color + ';width:16px;height:16px;border-radius:50%;border:2.5px solid white;box-shadow:0 0 8px rgba(0,0,0,0.6);"></div>',
      iconSize: [16, 16],
      iconAnchor: [8, 8],
      className: ''
    }});
  }}

  function updateMarkers(data) {{
    data.forEach(function(m) {{
      if (markers[m.id]) {{ map.removeLayer(markers[m.id]); delete markers[m.id]; }}
      var lat = parseFloat(m.lat), lng = parseFloat(m.lng);
      if (!isNaN(lat) && !isNaN(lng) && lat !== 0 && lng !== 0) {{
        markers[m.id] = L.marker([lat, lng], {{ icon: makeIcon(m.color || '#e67e22') }})
          .bindTooltip(m.label || m.id, {{ permanent: true, direction: 'top', offset: [0, -10],
            className: 'leaflet-tooltip-dark' }})
          .addTo(map);
      }}
    }});
  }}

  // 초기 마커 (Python에서 embed)
  var initialMarkers = {markers_json};
  if (initialMarkers.length > 0) {{
    updateMarkers(initialMarkers);
  }}

  // postMessage로도 마커 업데이트 가능
  window.addEventListener('message', function(e) {{
    if (e.data && e.data.type === 'setMarkers') {{
      updateMarkers(e.data.markers);
    }}
  }});
}})();
</script>
</body>
</html>"""
    return html


# ── 공개 서비스 메서드 (run_id 기반) ─────────────────────

def get_map_base(run_id: int) -> MapBaseOut:
    terrain = load_terrain_grid()
    return _terrain_to_base_out(terrain)


def get_map_layer(run_id: int, layer_type: str) -> MapLayerOut:
    terrain = load_terrain_grid()
    if layer_type == "mobility":
        return _make_mobility_layer(terrain)
    column = _LAYER_COLUMN.get(layer_type, "normalized_c_total")
    dynamic = load_latest_actual(column=column)
    if dynamic is None:
        logger.warning("동적 레이어 없음 — 빈 레이어 반환")
        dynamic = np.zeros((GRID_NY, GRID_NX), dtype=np.float32)
    return _dynamic_to_layer_out(dynamic, layer_type)


def get_commander_map(run_id: int) -> CommanderMapOut:
    terrain = load_terrain_grid()
    dynamic = load_latest_actual() or np.zeros((GRID_NY, GRID_NX), dtype=np.float32)
    return CommanderMapOut(
        base=_terrain_to_base_out(terrain),
        layer=_dynamic_to_layer_out(dynamic, "risk"),
        routes=_run_routes(run_id),
    )


def get_operator_map(run_id: int, username: str) -> OperatorMapOut:
    unit_no = _USERNAME_TO_UNIT.get(username, 0)
    terrain = load_terrain_grid()
    dynamic = load_latest_actual() or np.zeros((GRID_NY, GRID_NX), dtype=np.float32)
    all_routes = _run_routes(run_id)
    my_route = next((r for r in all_routes if r.unit_no == unit_no), None)
    return OperatorMapOut(
        base=_terrain_to_base_out(terrain),
        layer=_dynamic_to_layer_out(dynamic, "risk"),
        my_route=my_route,
        unit_no=unit_no,
    )


# ── 그리드 셀 JSON (Leaflet rectangle 렌더링용) ───────────

_LAT_STEP = 0.000213
_LON_STEP = 0.000357


@lru_cache(maxsize=1)
def get_terrain_cells_json() -> dict:
    """
    정적 지형 셀 JSON (lc_code 색상).
    lru_cache로 최초 1회 생성 후 메모리 캐시.
    반환: {lat_step, lon_step, cells: [[lat, lon, r, g, b, a], ...]}
    """
    import glob as _glob
    df = load_terrain_df()

    codes = df["lc_code"].values.astype(int)
    default_rgba = (128, 128, 128, 150)
    r_arr = np.array([LC_COLORS_RGBA.get(c, default_rgba)[0] for c in codes], dtype=np.uint8)
    g_arr = np.array([LC_COLORS_RGBA.get(c, default_rgba)[1] for c in codes], dtype=np.uint8)
    b_arr = np.array([LC_COLORS_RGBA.get(c, default_rgba)[2] for c in codes], dtype=np.uint8)
    a_arr = np.array([LC_COLORS_RGBA.get(c, default_rgba)[3] for c in codes], dtype=np.uint8)

    lats = df["lat"].values.round(5)
    lons = df["lon"].values.round(5)

    cells = np.column_stack([lats, lons, r_arr, g_arr, b_arr, a_arr]).tolist()
    return {"lat_step": _LAT_STEP, "lon_step": _LON_STEP, "cells": cells}


def get_risk_cells_json(layer: str) -> dict:
    """
    동적 비용 레이어 셀 JSON (위험도/기동성/센서).
    값 0.05 미만 셀은 제외 (성능).
    반환: {lat_step, lon_step, cells: [[lat, lon, r, g, b, a], ...]}
    """
    import glob as _glob
    import pandas as _pd

    column = _LAYER_COLUMN.get(layer, "normalized_c_total")
    files = sorted(_glob.glob(str(_ACTUAL_DIR / "*.parquet")))
    if not files:
        return {"lat_step": _LAT_STEP, "lon_step": _LON_STEP, "cells": []}

    df = _pd.read_parquet(files[-1], columns=["lat", "lon", column])
    df = df[df[column] >= 0.05].copy()
    if df.empty:
        return {"lat_step": _LAT_STEP, "lon_step": _LON_STEP, "cells": []}

    v = df[column].values.clip(0.0, 1.0)
    r_arr = (v * 220).astype(np.uint8)
    g_arr = ((1.0 - v) * 180).astype(np.uint8)
    b_arr = np.zeros(len(v), dtype=np.uint8)
    a_arr = (v * 190 + 30).astype(np.uint8)

    lats = df["lat"].values.round(5)
    lons = df["lon"].values.round(5)

    cells = np.column_stack([lats, lons, r_arr, g_arr, b_arr, a_arr]).tolist()
    return {"lat_step": _LAT_STEP, "lon_step": _LON_STEP, "cells": cells}


def generate_grid_map_html(layer: str = "risk") -> str:
    """
    그리드 맵 전용 Leaflet HTML.
    /api/map/grid/html?layer=risk 에서 서빙.
    지형(terrain) + 선택 레이어(risk/mobility/sensor)를 rectangle로 렌더링.
    """
    bounds = get_map_bounds()
    min_lat  = bounds["min_lat"]
    max_lat  = bounds["max_lat"]
    min_lng  = bounds["min_lng"]
    max_lng  = bounds["max_lng"]
    center_lat = bounds["center_lat"]
    center_lng = bounds["center_lng"]

    layer_labels = {
        "risk":     "위험도",
        "mobility": "기동성",
        "sensor":   "센서",
    }
    layer_label = layer_labels.get(layer, layer)

    return f"""<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8"/>
<link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css"/>
<script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
<style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:100%; height:100%; background:#0b1a2e; }}
  #map {{ width:100%; height:100%; }}
  #loading {{
    position:absolute; top:50%; left:50%; transform:translate(-50%,-50%);
    color:#94a3b8; font-size:14px; font-family:sans-serif; z-index:1000;
    background:rgba(11,26,46,0.85); padding:12px 24px; border-radius:8px;
  }}
  .legend {{
    background:rgba(15,25,50,0.88); border:1px solid rgba(255,255,255,0.12);
    border-radius:8px; padding:8px 12px; color:#e2e8f0; font-size:11px; line-height:1.9;
    pointer-events:none;
  }}
  .dot {{ display:inline-block; width:10px; height:10px;
          border-radius:50%; margin-right:4px; vertical-align:middle; }}
  .grad {{ display:inline-block; width:80px; height:8px; vertical-align:middle;
           margin:0 4px; border-radius:3px;
           background:linear-gradient(to right,rgba(0,180,0,0.8),rgba(255,200,0,0.8),rgba(220,20,0,0.9)); }}
</style>
</head>
<body>
<div id="map"></div>
<div id="loading">지도 데이터 로딩 중...</div>
<script>
(function() {{
  var map = L.map('map', {{
    zoomControl: true,
    attributionControl: false,
    preferCanvas: true
  }}).setView([{center_lat:.5f}, {center_lng:.5f}], 11);

  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 18, opacity: 0.35
  }}).addTo(map);

  var bounds = [[{min_lat:.6f},{min_lng:.6f}],[{max_lat:.6f},{max_lng:.6f}]];
  map.fitBounds(bounds, {{padding:[8,8]}});

  var LAT_HALF = 0.000213 / 2;
  var LON_HALF = 0.000357 / 2;

  var terrainLayer = L.layerGroup().addTo(map);
  var riskLayer    = L.layerGroup().addTo(map);

  function renderCells(cells, targetLayer) {{
    cells.forEach(function(c) {{
      var lat=c[0], lon=c[1], r=c[2], g=c[3], b=c[4], a=c[5]/255;
      L.rectangle(
        [[lat-LAT_HALF, lon-LON_HALF],[lat+LAT_HALF, lon+LON_HALF]],
        {{ weight:0, fillColor:'rgb('+r+','+g+','+b+')', fillOpacity:a, interactive:false }}
      ).addTo(targetLayer);
    }});
  }}

  function hideLoading() {{
    var el = document.getElementById('loading');
    if (el) el.style.display='none';
  }}

  // 지형 + 비용 레이어 병렬 로드
  Promise.all([
    fetch('/api/grid/cells?layer=terrain').then(function(r){{return r.json();}}),
    fetch('/api/grid/cells?layer={layer}').then(function(r){{return r.json();}})
  ]).then(function(results) {{
    renderCells(results[0].cells, terrainLayer);
    renderCells(results[1].cells, riskLayer);
    hideLoading();
  }}).catch(function(err) {{
    console.error('셀 로드 실패:', err);
    hideLoading();
  }});

  // 마커 postMessage 핸들러
  var mks = {{}};
  function makeIcon(c) {{
    return L.divIcon({{
      html:'<div style="background:'+c+';width:16px;height:16px;border-radius:50%;border:2.5px solid #fff;box-shadow:0 0 8px rgba(0,0,0,.6);"></div>',
      iconSize:[16,16], iconAnchor:[8,8], className:''
    }});
  }}
  window.addEventListener('message', function(e) {{
    if (!e.data || e.data.type !== 'setMarkers') return;
    e.data.markers.forEach(function(m) {{
      if (mks[m.id]) map.removeLayer(mks[m.id]);
      var lat=parseFloat(m.lat), lng=parseFloat(m.lng);
      if (!isNaN(lat) && !isNaN(lng)) {{
        mks[m.id] = L.marker([lat,lng],{{icon:makeIcon(m.color||'#e67e22')}})
          .bindTooltip(m.label||m.id,{{permanent:true,direction:'top',offset:[0,-12]}})
          .addTo(map);
      }}
    }});
  }});

  // 범례
  var legend = L.control({{position:'bottomleft'}});
  legend.onAdd = function() {{
    var d = L.DomUtil.create('div','legend');
    d.innerHTML =
      '<b style="font-size:12px;">지형</b><br>' +
      '<span class="dot" style="background:#a0d28c"></span>농지/초원<br>' +
      '<span class="dot" style="background:#287828"></span>숲<br>' +
      '<span class="dot" style="background:#969696"></span>도시<br>' +
      '<span class="dot" style="background:#3282f0"></span>수역<br>' +
      '<span class="dot" style="background:#c83232"></span>통행불가<br>' +
      '<hr style="border-color:rgba(255,255,255,0.2);margin:4px 0"/>' +
      '<b style="font-size:12px;">{layer_label}</b><br>' +
      '낮음<span class="grad"></span>높음';
    return d;
  }};
  legend.addTo(map);
}})();
</script>
</body>
</html>"""
