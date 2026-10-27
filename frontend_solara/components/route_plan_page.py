"""
frontend/components/route_plan_page.py

경로 계획 확인 + 파레토 분석 페이지 (3페이지).

좌측: ipyleaflet 경로 지도 (A/B/C 세 경로)
우측: 파레토 곡선(SVG) + 경로 비교 테이블 + 경로 선택 버튼
"""

import ipyleaflet as L
import ipywidgets as widgets
import solara
from ipyleaflet import Map, Marker, Polyline

from services.api_client import (
    confirm_route,
    current_page,
    route_options,
    selected_route_id,
)

ROUTE_COLORS = {"A": "#e74c3c", "B": "#3b82f6", "C": "#22c55e"}


# ── SVG 파레토 차트 ──────────────────────────────────────
def _pareto_svg(routes: list, selected: str) -> str:
    W, H = 390, 260
    ML, MR, MT, MB = 42, 18, 28, 32

    x_min, x_max = 0, 35
    y_min, y_max = 55, 95

    def sx(d: float) -> float:
        return ML + (d - x_min) / (x_max - x_min) * (W - ML - MR)

    def sy(s: float) -> float:
        return H - MB - (s - y_min) / (y_max - y_min) * (H - MT - MB)

    # 눈금선 + 축 레이블
    grid_lines = ""
    for d in [0, 10, 20, 30]:
        x = sx(d)
        grid_lines += (
            f'<line x1="{x:.1f}" y1="{MT}" x2="{x:.1f}" y2="{H-MB}"'
            f' stroke="#2d3a54" stroke-width="1"/>'
            f'<text x="{x:.1f}" y="{H-MB+16}" fill="#64748b"'
            f' font-size="9" text-anchor="middle">{d}%</text>'
        )
    for s in [60, 70, 80, 90]:
        y = sy(s)
        grid_lines += (
            f'<line x1="{ML}" y1="{y:.1f}" x2="{W-MR}" y2="{y:.1f}"'
            f' stroke="#2d3a54" stroke-width="1"/>'
            f'<text x="{ML-5}" y="{y+3:.1f}" fill="#64748b"'
            f' font-size="9" text-anchor="end">{s}%</text>'
        )

    # 파레토 프론트 점선
    pts_sorted = sorted(routes, key=lambda r: r["damage_rate"])
    line_pts = " ".join(
        f"{sx(r['damage_rate']):.1f},{sy(r['success_rate']):.1f}"
        for r in pts_sorted
    )
    pareto_line = (
        f'<polyline points="{line_pts}" fill="none"'
        f' stroke="#475569" stroke-width="1.5" stroke-dasharray="5,4"/>'
    )

    # 데이터 포인트 + 레이블
    circles = labels = ""
    for r in routes:
        cx, cy = sx(r["damage_rate"]), sy(r["success_rate"])
        color = ROUTE_COLORS.get(r["id"], "#888")
        is_sel = r["id"] == selected
        radius = 10 if is_sel else 6
        stroke = 'stroke="white" stroke-width="2.5"' if is_sel else ""
        circles += f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="{radius}" fill="{color}" {stroke}/>'
        labels += (
            f'<text x="{cx+13:.1f}" y="{cy-3:.1f}" fill="white"'
            f' font-size="11" font-weight="bold">{r["id"]}안</text>'
        )

    axes = (
        f'<line x1="{ML}" y1="{MT}" x2="{ML}" y2="{H-MB}" stroke="#475569" stroke-width="1.5"/>'
        f'<line x1="{ML}" y1="{H-MB}" x2="{W-MR}" y2="{H-MB}" stroke="#475569" stroke-width="1.5"/>'
    )

    return f"""<svg width="{W}" height="{H}"
        style="background:#0f172a; border-radius:8px; display:block;">
        {grid_lines}
        {axes}
        {pareto_line}
        {circles}
        {labels}
        <text x="{W//2}" y="17" fill="white" font-size="12"
              font-weight="bold" text-anchor="middle">파레토 최적 경로</text>
        <text x="{W//2}" y="{H-2}" fill="#94a3b8" font-size="10"
              text-anchor="middle">자산피해율 (%)</text>
        <text x="10" y="{H//2}" fill="#94a3b8" font-size="10"
              text-anchor="middle"
              transform="rotate(-90, 10, {H//2})">임무성공률 (%)</text>
    </svg>"""


# ── 컴포넌트 ─────────────────────────────────────────────
@solara.component
def RoutePlanPage():
    solara.Style("""
        html, body, #app, .v-application, .v-application--wrap,
        .solara-content-main, .solara-app, .v-main {
            background-color: #0b1426 !important;
            color: white !important;
            width: 100% !important;
            height: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
        }

        .rp-root {
            width: 100vw;
            height: 100vh;
            background: #0b1426;
            padding: 20px 24px;
            box-sizing: border-box;
            display: flex;
            flex-direction: column;
            gap: 14px;
        }

        .rp-header {
            display: flex;
            align-items: center;
            gap: 14px;
            flex-shrink: 0;
        }

        .rp-title {
            font-size: 20px;
            font-weight: bold;
            color: white;
        }

        .rp-body {
            flex: 1;
            min-height: 0;
            display: grid;
            grid-template-columns: minmax(0, 1fr) 420px;
            gap: 14px;
        }

        .rp-map-panel {
            background-color: rgba(15, 23, 38, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px;
            padding: 14px;
            display: flex;
            flex-direction: column;
            min-height: 0;
            overflow: hidden;
            box-sizing: border-box;
        }

        .rp-right-panel {
            background-color: rgba(15, 23, 38, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px;
            padding: 12px 14px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            overflow-y: hidden;
            box-sizing: border-box;
        }

        .rp-right-panel::-webkit-scrollbar { width: 6px; }
        .rp-right-panel::-webkit-scrollbar-track { background: transparent; }
        .rp-right-panel::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 6px; }

        .rp-panel-label {
            color: #94a3b8 !important;
            font-size: 13px;
            font-weight: bold;
            margin-bottom: 4px;
        }

        .rp-route-row {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 6px 10px;
            border-radius: 8px;
            margin-bottom: 3px;
            cursor: pointer;
        }

        .rp-route-selected {
            background-color: rgba(230, 126, 34, 0.15) !important;
            border: 1px solid rgba(230, 126, 34, 0.45) !important;
        }

        .rp-route-default {
            background-color: rgba(45, 58, 84, 0.25) !important;
            border: 1px solid rgba(45, 58, 84, 0.3) !important;
        }

        .rp-sel-btn {
            height: 36px !important;
            font-size: 13px !important;
            font-weight: bold !important;
            border-radius: 6px !important;
            flex: 1;
        }

        .rp-sel-active {
            color: white !important;
            opacity: 1 !important;
        }

        .rp-sel-default {
            background-color: #1e293b !important;
            color: #94a3b8 !important;
        }

        .rp-confirm-btn {
            height: 50px !important;
            width: 100% !important;
            font-size: 15px !important;
            font-weight: bold !important;
            background-color: #e67e22 !important;
            color: white !important;
            border-radius: 10px !important;
        }

        .rp-back-btn {
            height: 38px !important;
            background-color: #1e293b !important;
            color: #94a3b8 !important;
            border-radius: 6px !important;
            font-size: 14px !important;
        }

        .rp-map-panel > div,
        .rp-map-panel .v-sheet,
        .rp-right-panel > div,
        .rp-right-panel .v-sheet {
            background-color: transparent !important;
        }

        .rp-map-panel ::-webkit-scrollbar,
        .rp-map-panel ::-webkit-scrollbar-horizontal {
            display: none !important;
            height: 0 !important;
        }
        .rp-map-panel {
            scrollbar-width: none !important;
        }

        .rp-legend-dot {
            width: 12px;
            height: 12px;
            border-radius: 50%;
            display: inline-block;
            margin-right: 6px;
            flex-shrink: 0;
        }
    """)

    routes = route_options.value
    selected = selected_route_id.value

    with solara.Div(classes=["rp-root"]):

        # ── 헤더 ─────────────────────────────────────
        with solara.Div(classes=["rp-header"]):
            solara.Button(
                "← 뒤로",
                on_click=lambda: current_page.set("input"),
                classes=["rp-back-btn"],
            )
            solara.Text("경로 계획 확인", classes=["rp-title"])

        # ── 본문 ─────────────────────────────────────
        with solara.Div(classes=["rp-body"]):

            # 좌측: 지도
            with solara.Div(classes=["rp-map-panel"]):
                solara.Text("경로 지도", classes=["rp-panel-label"])

                # 범례
                with solara.Row(gap="16px", style={"margin-bottom": "8px"}):
                    for r in routes:
                        color = ROUTE_COLORS.get(r["id"], "#888")
                        with solara.Row(gap="4px", style={"align-items": "center"}):
                            solara.HTML(
                                tag="span",
                                attributes={"class": "rp-legend-dot"},
                                style={"background-color": color},
                            )
                            solara.Text(
                                r["label"],
                                style={"color": color, "font-size": "13px", "font-weight": "bold"},
                            )

                # 지도
                layers = []
                for r in routes:
                    color = ROUTE_COLORS.get(r["id"], "#888")
                    is_sel = r["id"] == selected
                    layers.append(Polyline(
                        locations=r["path"],
                        color=color,
                        weight=6 if is_sel else 3,
                        opacity=1.0 if is_sel else 0.45,
                        name=r["label"],
                    ))

                layers += [
                    Marker(location=[37.45, 127.42], title="출발지 🚩", draggable=False),
                    Marker(location=[37.55, 127.58], title="도착지 ⭐", draggable=False),
                ]

                solara.display(
                    Map(
                        center=[37.50, 127.50],
                        zoom=12,
                        layers=[L.basemap_to_tiles(L.basemaps.OpenStreetMap.Mapnik)] + layers,
                        layout=widgets.Layout(width="100%", height="460px"),
                        scroll_wheel_zoom=True,
                    )
                )

            # 우측: 파레토 + 비교 + 선택
            with solara.Div(classes=["rp-right-panel"]):

                # 파레토 곡선 (SVG)
                solara.Text("파레토 분석", classes=["rp-panel-label"])
                solara.display(
                    widgets.HTML(value=_pareto_svg(routes, selected))
                )

                # 경로 비교 테이블
                solara.Text(
                    "경로 비교",
                    classes=["rp-panel-label"],
                    style={"margin-top": "2px"},
                )
                for r in routes:
                    is_sel = r["id"] == selected
                    color = ROUTE_COLORS.get(r["id"], "#888")
                    with solara.Div(
                        classes=[
                            "rp-route-row",
                            "rp-route-selected" if is_sel else "rp-route-default",
                        ]
                    ):
                        solara.Text(
                            r["label"],
                            style={
                                "color": color,
                                "font-weight": "bold",
                                "font-size": "13px",
                                "min-width": "80px",
                            },
                        )
                        solara.Text(
                            f"성공 {r['success_rate']}%",
                            style={"color": "#4ade80", "font-size": "12px"},
                        )
                        solara.Text(
                            f"피해 {r['damage_rate']}%",
                            style={"color": "#fb7185", "font-size": "12px"},
                        )
                        solara.Text(
                            f"{r['eta_min']}분",
                            style={"color": "#94a3b8", "font-size": "12px"},
                        )

                # 경로 선택 버튼
                solara.Text(
                    "경로 선택",
                    classes=["rp-panel-label"],
                    style={"margin-top": "2px"},
                )
                with solara.Row(gap="6px"):
                    for r in routes:
                        color = ROUTE_COLORS.get(r["id"], "#888")
                        is_sel = r["id"] == selected
                        solara.Button(
                            f"{r['id']}안",
                            on_click=lambda x=r["id"]: selected_route_id.set(x),
                            classes=[
                                "rp-sel-btn",
                                "rp-sel-active" if is_sel else "rp-sel-default",
                            ],
                            style={
                                "background-color": color if is_sel else "#1e293b",
                            },
                        )

                # 확정 버튼
                solara.Button(
                    "경로 확정  →  임무 시작",
                    on_click=confirm_route,
                    classes=["rp-confirm-btn"],
                    style={"margin-top": "2px"},
                )
