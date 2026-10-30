"""
frontend/components/map_view.py

ipyleaflet 기반 지도 컴포넌트.

레이어 구성:
  1. 그리드 레이어  — land_cover_type 별 색상 원(CircleMarker)
  2. 위험 히트맵    — total_cost 기반 Heatmap
  3. .tif 오버레이  — 백엔드 StaticFiles URL → ImageOverlay
  4. 최적 경로      — GeoJSON LineString → Polyline
"""

import solara
import ipyleaflet as L
import ipywidgets as widgets
from ipyleaflet import Map, CircleMarker, LayerGroup, Heatmap, GeoJSON, ImageOverlay, Polyline, Marker, DivIcon

import state

# CGLS 토지피복 → 색상 매핑
LC_COLORS = {
    "농경지": "#f5e642",
    "초지":   "#a8d08a",
    "관목지": "#c4a35a",
    "시가지": "#b0b0b0",
    "산림":   "#2d6a2d",
    "수계":   "#4a90d9",
    "습지":   "#7fbfbf",
    "unknown": "#888888",
}

# 위험도 색상 (total_cost 0→1)
def _risk_color(cost: float) -> str:
    if cost < 0.33:
        return "#00cc44"   # 녹색
    elif cost < 0.66:
        return "#ffaa00"   # 황색
    return "#cc2200"       # 적색


@solara.component
def MapView():
    """
    메인 지도 컴포넌트.
    state 변화(grid_cells, weather_data, optimal_paths)를 감지해 레이어 자동 갱신.
    """
    # 지도 초기 중심 (샘플 데이터 기준 한반도 중부)
    center = [37.5, 127.5]
    zoom = 11

    # ── 레이어 구성 ──────────────────────────────

    # 1. 그리드 레이어 (토지피복 색상 원)
    grid_markers = []
    for cell in state.grid_cells.value[:3000]:   # 성능상 최대 3,000개 표시
        color = LC_COLORS.get(cell.get("land_cover_type", "unknown"), "#888")
        marker = CircleMarker(
            location=[cell["lat"], cell["lon"]],
            radius=4,
            color=color,
            fill_color=color,
            fill_opacity=0.7,
            weight=0,
            title=f"{cell.get('land_cover_type')} / {'안전' if cell.get('is_safe_area') else '위험'}",
        )
        grid_markers.append(marker)
    grid_layer = LayerGroup(layers=grid_markers, name="그리드")

    # 2. 위험 히트맵 (total_cost 기반)
    heat_data = [
        [w["lat"], w["lon"], w["total_cost"]]
        for w in state.weather_data.value
        if w.get("total_cost") is not None
    ]
    heatmap_layer = Heatmap(
        locations=heat_data,
        min_opacity=0.3,
        max_zoom=18,
        radius=15,
        blur=10,
        name="위험 히트맵",
    )

    # 3. 최적 경로 레이어
    path_layers = []
    has_pending = state.pending_route.value is not None
    colors = ["#e63946", "#457b9d", "#2a9d8f", "#e9c46a", "#f4a261"]
    for i, p in enumerate(state.optimal_paths.value):
        geom = p.get("path_geom", {})
        coords = geom.get("coordinates", [])
        if not coords:
            continue
        latlons = [[c[1], c[0]] for c in coords]
        polyline = Polyline(
            locations=latlons,
            color=colors[i % len(colors)],
            weight=4,
            # 제안 경로가 있으면 현재 경로를 흐리게
            opacity=0.35 if has_pending else 0.9,
            dash_array="6 4" if has_pending else None,
            name=f"현재 경로 ({p.get('unit_id', i)})",
        )
        path_layers.append(polyline)

    # 제안 경로 (replan_suggested) — 노란색 점선으로 표시
    if has_pending:
        pending = state.pending_route.value
        pgeom = pending.get("path_geom", {})
        pcoords = pgeom.get("coordinates", [])
        if pcoords:
            platlons = [[c[1], c[0]] for c in pcoords]
            path_layers.append(Polyline(
                locations=platlons,
                color="#facc15",
                weight=5,
                opacity=1.0,
                dash_array="10 6",
                name=f"제안 경로 ({pending.get('trigger', '환경 변화')})",
            ))

    paths_layer = LayerGroup(layers=path_layers, name="경로")

    # 4. .tif 오버레이 (latest_result에 tif_paths 있을 때)
    tif_layers = []
    if state.latest_result.value and state.latest_result.value.get("tif_paths"):
        import os
        backend_url = os.getenv("BACKEND_URL", "http://localhost:8000")
        bounds_default = [[37.0, 127.0], [38.0, 128.0]]  # 실제 범위로 교체 필요
        for tif_key, tif_path in state.latest_result.value["tif_paths"].items():
            # 백엔드 StaticFiles URL: /tif-files/<파일명>
            filename = tif_path.split("/")[-1]
            url = f"{backend_url}/tif-files/{filename}"
            overlay = ImageOverlay(
                url=url,
                bounds=bounds_default,
                opacity=0.6,
                name=f"TIF: {tif_key}",
            )
            tif_layers.append(overlay)

    # 5. UGV 마커 레이어
    ugv_markers = []
    ugv_colors = ["#f97316", "#3b82f6", "#22c55e", "#a855f7"]  # UGV별 색상
    for i, ugv in enumerate(state.ugv_positions.value):
        color = ugv_colors[i % len(ugv_colors)]
        icon = DivIcon(
            html=f"""<div style="
                width:28px; height:28px;
                background:{color};
                border:2px solid white;
                border-radius:50%;
                display:flex; align-items:center; justify-content:center;
                font-size:11px; font-weight:bold; color:white;
                box-shadow:0 2px 6px rgba(0,0,0,0.5);
            ">{i+1}</div>""",
            icon_size=[28, 28],
            icon_anchor=[14, 14],
        )
        marker = Marker(
            location=[ugv["lat"], ugv["lon"]],
            icon=icon,
            title=ugv["unit_id"],
            draggable=False,
        )
        ugv_markers.append(marker)
    ugv_layer = LayerGroup(layers=ugv_markers, name="UGV")

    # ── 지도 렌더링 ─────────────────────────────
    all_layers = [grid_layer, heatmap_layer, paths_layer] + tif_layers + [ugv_layer]

    solara.display(
        Map(
            center=center,
            zoom=zoom,
            layers=[L.basemap_to_tiles(L.basemaps.OpenStreetMap.Mapnik)] + all_layers,
            layout=widgets.Layout(width="100%", height="100%"),
            scroll_wheel_zoom=True,
        )
    )

    # 레이어 범례
    with solara.Row():
        for lc, color in LC_COLORS.items():
            solara.Text(
                f"■ {lc}",
                style={"color": color, "marginRight": "12px", "fontSize": "0.8rem"},
            )
