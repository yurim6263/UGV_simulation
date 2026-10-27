"""
frontend/components/map_html_builder.py

Leaflet 지도 HTML 빌더 — Solara 컴포넌트 컨텍스트와 완전히 격리된 순수 Python 모듈.
이 파일은 @solara.component 데코레이터를 일절 사용하지 않음.

백엔드 이미지 오버레이:
  /api/map/tactical/terrain-image        — lc_code 기반 지형 색상 PNG
  /api/map/tactical/buffer-image         — 경로 버퍼 마스크 PNG
  /api/map/tactical/cost-image?layer=X   — 위험도/기동성/센서 비용 레이어 PNG
"""

from __future__ import annotations
import json

# 지도 고정 경계 (parquet 실측값, WGS84)
_MAP_BOUNDS = {
    "min_lat": 54.2977,
    "max_lat": 54.5209,
    "min_lng": 18.2640,
    "max_lng": 18.6479,
}

# 탭명 → API layer 파라미터 매핑
_LAYER_MAP: dict[str, str] = {
    "위험도": "risk",
    "기동성": "mobility",
    "센서":   "sensor",
}


def build_base_map_html(backend_url: str, selected_layer: str = "위험도", markers: list[dict] | None = None) -> str:
    markers = markers or []
    markers_json = json.dumps(markers, ensure_ascii=False)
    """
    지형 PNG + 버퍼 오버레이 + 비용 레이어 Leaflet HTML 문자열 반환.

    backend_url     : 예) "http://127.0.0.1:8000"
    selected_layer  : "위험도" | "기동성" | "센서"
    """
    b = _MAP_BOUNDS
    center_lat = (b["min_lat"] + b["max_lat"]) / 2
    center_lng = (b["min_lng"] + b["max_lng"]) / 2
    layer_key  = _LAYER_MAP.get(selected_layer, "risk")

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
  .legend {{
    background: rgba(15,25,50,0.88);
    border: 1px solid rgba(255,255,255,0.12);
    border-radius: 8px; padding: 8px 12px;
    color: #e2e8f0; font-size: 11px; line-height: 1.8;
    pointer-events: none;
  }}
  .dot {{ display:inline-block; width:10px; height:10px;
          border-radius:50%; margin-right:4px; vertical-align:middle; }}
  .grad-bar {{
    width: 100px; height: 10px; border-radius: 3px;
    background: linear-gradient(to right, rgba(0,180,0,0.7), rgba(220,220,0,0.7), rgba(220,0,0,0.9));
    display: inline-block; vertical-align: middle; margin: 0 4px;
  }}
</style>
</head>
<body>
<div id="map"></div>
<script>
(function() {{
  var BACKEND = '{backend_url}';
  var bounds = [
    [{b["min_lat"]:.6f}, {b["min_lng"]:.6f}],
    [{b["max_lat"]:.6f}, {b["max_lng"]:.6f}]
  ];

  var map = L.map('map', {{
    zoomControl: true,
    attributionControl: false,
    preferCanvas: true
  }}).setView([{center_lat:.5f}, {center_lng:.5f}], 10);

  // 베이스 타일
  L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
    maxZoom: 18, opacity: 0.5
  }}).addTo(map);

  // 1) 지형 레이어 (lc_code 색상 PNG)
  L.imageOverlay(
    BACKEND + '/api/map/tactical/terrain-image',
    bounds,
    {{ opacity: 0.70, interactive: false }}
  ).addTo(map);

  // 2) TIF 버퍼 레이어 (route_buffer_mask — 황색 반투명)
  L.imageOverlay(
    BACKEND + '/api/map/tactical/buffer-image',
    bounds,
    {{ opacity: 0.50, interactive: false }}
  ).addTo(map);

  // 3) 비용 레이어 (위험도 / 기동성 / 센서) — 초기값은 Python에서 embed
  var costLayer = L.imageOverlay(
    BACKEND + '/api/map/tactical/cost-image?layer={layer_key}&_t=' + Date.now(),
    bounds,
    {{ opacity: 0.78, interactive: false }}
  ).addTo(map);

  map.fitBounds(bounds, {{ padding: [8, 8] }});

  // ── postMessage 핸들러 ─────────────────────────────────
  var initialMarkers = {markers_json};
  var mks = {{}};

  function makeIcon(c) {{
    return L.divIcon({{
      html: '<div style="background:'+c+';width:16px;height:16px;border-radius:50%;' +
            'border:2.5px solid #fff;box-shadow:0 0 8px rgba(0,0,0,.6);"></div>',
      iconSize: [16,16], iconAnchor: [8,8], className: ''
    }});
  }}
  
  function drawMarkers(markers) {{
    Object.keys(mks).forEach(function(id) {{
      map.removeLayer(mks[id]);
    }});
    mks = {{}};

    markers.forEach(function(m) {{
      var lat = parseFloat(m.lat), lng = parseFloat(m.lng);
      if (!isNaN(lat) && !isNaN(lng)) {{
        mks[m.id] = L.marker([lat, lng], {{ icon: makeIcon(m.color || '#e67e22') }})
          .bindTooltip(m.label || m.id, {{
            permanent: true, direction: 'top', offset: [0, -12]
          }})
          .addTo(map);
      }}
    }});
  }}

  drawMarkers(initialMarkers);

  window.addEventListener('message', function(e) {{
    if (!e.data) return;

    // 마커 업데이트
    if (e.data.type === 'setMarkers') {{
      Object.keys(mks).forEach(function(id) {{
        map.removeLayer(mks[id]);
      }});
      mks = {{}};

      e.data.markers.forEach(function(m) {{
        var lat = parseFloat(m.lat), lng = parseFloat(m.lng);
        if (!isNaN(lat) && !isNaN(lng)) {{
          mks[m.id] = L.marker([lat, lng], {{ icon: makeIcon(m.color || '#e67e22') }})
            .bindTooltip(m.label || m.id, {{
              permanent: true, direction: 'top', offset: [0, -12]
            }})
            .addTo(map);
        }}
      }});
    }}

    // 레이어 교체 (postMessage로도 전환 가능)
    if (e.data.type === 'setLayer') {{
      map.removeLayer(costLayer);
      costLayer = L.imageOverlay(
        BACKEND + '/api/map/tactical/cost-image?layer=' + e.data.layer + '&_t=' + Date.now(),
        bounds,
        {{ opacity: 0.78, interactive: false }}
      ).addTo(map);
    }}
  }});
}})();
</script>
</body>
</html>"""
