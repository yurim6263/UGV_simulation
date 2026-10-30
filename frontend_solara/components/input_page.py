"""
frontend/components/input_page.py

임무 입력 페이지 — PDF 3페이지 디자인.

레이아웃:
  좌 60%: ipyleaflet 위성 지도 (클릭 → 선택 제대의 정찰지 좌표 설정)
  우 40%: 제대별 정찰지 좌표 / 정찰 시간 테이블 + 완료 버튼
"""

import ipyleaflet as L
import ipywidgets as widgets
import solara
from ipyleaflet import Map, Marker

from services.api_client import (
    current_page,
    logged_in_user,
    NICKNAMES,
    echelon_targets,
    active_echelon_idx,
    submit_mission,
)


def _hms_to_sec(hms: str) -> int:
    """HH:MM:SS → 초"""
    try:
        p = hms.strip().split(":")
        return int(p[0]) * 3600 + int(p[1]) * 60 + int(p[2])
    except Exception:
        return 1800


def _safe_float(v: str, default: float) -> float:
    try:
        return float(v)
    except (ValueError, TypeError):
        return default


@solara.component
def InputPage():
    unit_name = NICKNAMES.get(logged_in_user.value, logged_in_user.value or "지휘관")

    # 현재 선택된 제대 인덱스 (지역 상태)
    active_idx, set_active_idx = solara.use_state(active_echelon_idx.value)

    solara.Style("""
        html, body, #app,
        .v-application, .v-application--wrap,
        .solara-content-main, .v-main, .v-main__wrap {
            background-color: #0b1426 !important;
            color: white !important;
            width: 100% !important; height: 100% !important;
            margin: 0 !important; padding: 0 !important;
            overflow: hidden !important;
        }

        .ip-root {
            width: 100vw; height: 100vh;
            background: #0b1426;
            display: flex; flex-direction: column;
            box-sizing: border-box;
            padding: 16px 20px;
            gap: 12px;
        }

        /* ── 헤더 ── */
        .ip-header {
            display: flex; align-items: center;
            justify-content: space-between;
            flex-shrink: 0;
            background: transparent !important;
        }
        .ip-header > .v-sheet,
        .ip-header > div > .v-sheet { background: transparent !important; }
        .ip-header-title {
            font-size: 15px; font-weight: bold; color: white !important;
            letter-spacing: 1px;
            background: transparent !important;
        }
        .ip-header-sub {
            font-size: 13px; color: rgba(255,255,255,0.45) !important;
            margin-left: 12px;
            background: transparent !important;
        }

        /* ── 본문 (지도 + 우측 패널) ── */
        .ip-body {
            flex: 1; min-height: 0;
            display: grid;
            grid-template-columns: minmax(0, 1fr) 380px;
            gap: 14px;
        }

        /* ── 지도 패널 ── */
        .ip-map-panel {
            background: rgba(15, 23, 38, 0.85) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px;
            padding: 12px;
            display: flex; flex-direction: column;
            min-height: 0; overflow: hidden;
            box-sizing: border-box;
        }
        .ip-map-panel > .v-sheet,
        .ip-map-panel > div > .v-sheet { background: transparent !important; }
        /* ipyleaflet 위젯이 flex:1 공간을 채우도록 */
        .ip-map-panel .jupyter-widgets { flex: 1 !important; min-height: 0 !important; }
        .ip-map-panel .leaflet-container { height: 100% !important; }
        .ip-panel-label {
            font-size: 12px; color: #94a3b8;
            font-weight: bold; letter-spacing: 1px;
            text-transform: uppercase; margin-bottom: 8px;
            flex-shrink: 0;
        }
        .ip-map-hint {
            font-size: 11px; color: rgba(255,255,255,0.35);
            margin-bottom: 6px; flex-shrink: 0;
        }

        /* ── 우측 패널 ── */
        .ip-right-panel {
            background: rgba(15, 23, 38, 0.85) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px;
            padding: 18px 16px;
            display: flex; flex-direction: column;
            gap: 0; box-sizing: border-box;
        }
        .ip-right-panel > .v-sheet,
        .ip-right-panel > div > .v-sheet { background: transparent !important; }

        /* ── 테이블 헤더 ── */
        .ip-tbl-header {
            display: grid;
            grid-template-columns: 72px 1fr 1fr;
            gap: 8px;
            padding: 0 8px 10px;
            border-bottom: 1px solid rgba(45, 58, 84, 0.6);
            margin-bottom: 4px;
        }
        .ip-tbl-header span {
            font-size: 11px; color: #64748b;
            font-weight: bold; letter-spacing: 1px;
            text-transform: uppercase; text-align: center;
        }
        .ip-tbl-header span:first-child { text-align: left; }

        /* ── 테이블 행 ── */
        .ip-row {
            display: grid;
            grid-template-columns: 72px 1fr 1fr;
            gap: 8px;
            padding: 10px 8px;
            border-radius: 8px;
            cursor: pointer;
            margin-bottom: 4px;
            align-items: center;
            border: 1px solid transparent;
            transition: background 0.15s;
        }
        .ip-row-active {
            background: rgba(230, 126, 34, 0.12) !important;
            border-color: rgba(230, 126, 34, 0.40) !important;
        }
        .ip-row-default {
            background: rgba(22, 34, 56, 0.50) !important;
        }
        .ip-row:hover { background: rgba(45, 58, 84, 0.5) !important; }

        .ip-row-label {
            font-size: 13px; font-weight: bold;
            color: white; text-align: left;
        }
        .ip-row-label-active { color: #e67e22 !important; }

        /* ── 좌표/시간 입력 ── */
        .ip-coord-cell, .ip-time-cell {
            display: flex; flex-direction: column; gap: 3px;
        }
        .ip-coord-cell input, .ip-time-cell input {
            background: rgba(22, 34, 56, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.6) !important;
            border-radius: 5px !important;
            color: rgba(255,255,255,0.85) !important;
            font-size: 11px !important;
            padding: 4px 6px !important;
            caret-color: white !important;
            text-align: center !important;
        }
        .ip-coord-cell .v-label, .ip-time-cell .v-label {
            font-size: 10px !important;
            color: rgba(255,255,255,0.3) !important;
        }
        .ip-coord-cell .v-input__slot::before,
        .ip-coord-cell .v-input__slot::after,
        .ip-time-cell .v-input__slot::before,
        .ip-time-cell .v-input__slot::after { display: none !important; }
        .ip-coord-cell .v-text-field,
        .ip-time-cell .v-text-field { margin: 0 !important; padding: 0 !important; }
        .ip-coord-cell .v-input__control,
        .ip-time-cell .v-input__control { min-height: 28px !important; }

        /* ── 구분선 ── */
        .ip-divider {
            border: none;
            border-top: 1px solid rgba(45, 58, 84, 0.4);
            margin: 16px 0 12px;
        }

        /* ── 완료 버튼 ── */
        .ip-submit .v-btn, .ip-submit button {
            background: #e67e22 !important;
            color: white !important;
            width: 100% !important; height: 50px !important;
            font-size: 15px !important; font-weight: bold !important;
            border-radius: 10px !important;
            box-shadow: 0 2px 12px rgba(230,126,34,0.35) !important;
            letter-spacing: 1.5px !important;
        }
        .ip-submit .v-btn:hover, .ip-submit button:hover {
            background: #d35400 !important;
        }

        /* 지도 leaflet 스크롤바 숨김 */
        .ip-map-panel ::-webkit-scrollbar { display: none !important; }
        .ip-map-panel { scrollbar-width: none !important; }

        .ip-spacer { flex: 1; }
    """)

    targets = echelon_targets.value

    # ── 지도 상호작용: 클릭 시 활성 제대 좌표 업데이트 ──────────────────
    def _on_map_interaction(**kwargs):
        if kwargs.get("type") != "click":
            return
        coords = kwargs.get("coordinates")
        if not coords:
            return
        lat, lon = float(coords[0]), float(coords[1])
        new_targets = [dict(t) for t in echelon_targets.value]
        idx = active_echelon_idx.value
        new_targets[idx] = {**new_targets[idx], "lat": lat, "lon": lon}
        echelon_targets.set(new_targets)

    # ── 지도 레이어 ──────────────────────────────────────────────────────
    ECHELON_COLORS = ["#e67e22", "#3b82f6", "#22c55e"]
    map_layers = [L.basemap_to_tiles(L.basemaps.Esri.WorldImagery)]
    for i, t in enumerate(targets):
        if t["lat"] is not None and t["lon"] is not None:
            marker = Marker(
                location=[t["lat"], t["lon"]],
                title=t["label"],
                draggable=False,
                icon=L.AwesomeIcon(
                    name="map-marker",
                    marker_color="orange" if i == 0 else ("blue" if i == 1 else "green"),
                    icon_color="white",
                ),
            )
            map_layers.append(marker)

    m = Map(
        center=[37.50, 127.00],
        zoom=12,
        layers=map_layers,
        layout=widgets.Layout(width="100%", height="570px"),
        scroll_wheel_zoom=True,
    )
    m.on_interaction(_on_map_interaction)

    # ── 렌더링 ──────────────────────────────────────────────────────────
    with solara.Div(classes=["ip-root"]):

        # 헤더
        with solara.Div(classes=["ip-header"]):
            with solara.Row(gap="4px", style={"align-items": "center"}):
                solara.HTML(tag="span", classes=["ip-header-title"], unsafe_innerHTML="임무 목표 설정")
            solara.HTML(
                tag="span",
                style={"font-size": "11px", "color": "rgba(255,255,255,0.35)"},
                unsafe_innerHTML="지도를 클릭해 제대별 정찰지를 지정하세요",
            )

        # 본문
        with solara.Div(classes=["ip-body"]):

            # ── 좌측: 지도 ──────────────────────────────────────────────
            with solara.Div(classes=["ip-map-panel"]):
                solara.HTML(tag="div", classes=["ip-panel-label"], unsafe_innerHTML="정찰 지도")
                solara.display(m)

            # ── 우측: 테이블 + 완료 ─────────────────────────────────────
            with solara.Div(classes=["ip-right-panel"]):
                solara.HTML(tag="div", classes=["ip-panel-label"], unsafe_innerHTML="제대 편성")

                # 테이블 헤더
                with solara.Div(classes=["ip-tbl-header"]):
                    solara.HTML(tag="span", unsafe_innerHTML="제대")
                    solara.HTML(tag="span", unsafe_innerHTML="정찰지 좌표")
                    solara.HTML(tag="span", unsafe_innerHTML="정찰 시간")

                # 테이블 행 × 3  (행 전체가 클릭 가능 — Button으로 감쌈)
                for i, t in enumerate(targets):
                    is_active = i == active_idx
                    lat_str = f"{t['lat']:.5f}" if t["lat"] is not None else ""
                    lon_str = f"{t['lon']:.5f}" if t["lon"] is not None else ""
                    ECHELON_COLORS = ["#e67e22", "#3b82f6", "#22c55e"]
                    row_color = ECHELON_COLORS[i]

                    with solara.Div(
                        classes=["ip-row", "ip-row-active" if is_active else "ip-row-default"],
                    ):
                        # 제대명 — 클릭 시 활성 전환
                        solara.Button(
                            t["label"],
                            on_click=lambda x=i: (set_active_idx(x), active_echelon_idx.set(x)),
                            style={
                                "font-size": "13px", "font-weight": "bold",
                                "color": row_color if is_active else "rgba(255,255,255,0.6)",
                                "background": "transparent", "box-shadow": "none",
                                "min-height": "0", "height": "100%",
                                "padding": "0 4px", "align-self": "stretch",
                            },
                        )

                        # 좌표 입력 (클릭 시 해당 제대로 전환 후 입력)
                        with solara.Div(
                            classes=["ip-coord-cell"],
                            on_click=lambda x=i: (set_active_idx(x), active_echelon_idx.set(x)),
                        ):
                            solara.InputText(
                                "위도", value=lat_str,
                                on_value=lambda v, idx=i: _update_coord(idx, "lat", _safe_float(v, None)),
                                continuous_update=False,
                            )
                            solara.InputText(
                                "경도", value=lon_str,
                                on_value=lambda v, idx=i: _update_coord(idx, "lon", _safe_float(v, None)),
                                continuous_update=False,
                            )

                        # 정찰 시간 입력
                        with solara.Div(
                            classes=["ip-time-cell"],
                            on_click=lambda x=i: (set_active_idx(x), active_echelon_idx.set(x)),
                        ):
                            solara.InputText(
                                "HH:MM:SS", value=t["patrol_time"],
                                on_value=lambda v, idx=i: _update_time(idx, v),
                                continuous_update=False,
                            )

                # 스페이서
                solara.Div(classes=["ip-spacer"])

                # 구분선
                solara.HTML(tag="hr", attributes={"class": "ip-divider"})

                # 완료 버튼
                with solara.Div(classes=["ip-submit"]):
                    solara.Button("완  료", on_click=submit_mission)


def _update_coord(idx: int, key: str, value) -> None:
    new_targets = [dict(t) for t in echelon_targets.value]
    new_targets[idx] = {**new_targets[idx], key: value}
    echelon_targets.set(new_targets)


def _update_time(idx: int, value: str) -> None:
    new_targets = [dict(t) for t in echelon_targets.value]
    new_targets[idx] = {**new_targets[idx], "patrol_time": value}
    echelon_targets.set(new_targets)
