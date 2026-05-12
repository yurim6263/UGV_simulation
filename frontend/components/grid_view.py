import solara
import solara.lab
import time
import asyncio

from services.api_client import (
    BACKEND_HTTP_BASE,
    map_selection,
    set_map_selection,
    ratio_x,
    UGV_ICONS,
    replan_available,
    request_replan,
)

from components.state import (
    timer_running,
    timer_end_ts,
    remaining_time_text_global,
    timer_remaining_secs,
    video_should_play,
    active_btn,
    ARRIVAL_TIMES_BY_MODE,
    departure_times,
    selected_mission_mode,
    mission_toast_count,
    mission_toast_message,
)
from components.mission_actions import deliver_mission


@solara.component
def GridView(current_user="admin"):
    #current_user = logged_in_user.value

    is_active = solara.use_reactive(False)
    last_toggle_time = solara.use_reactive(time.time())

    current_time_text = solara.use_reactive(time.strftime("%Y.%m.%d %H:%M"))
    remaining_display = solara.use_reactive(remaining_time_text_global.value)

    backend_alive = solara.use_reactive(True)
    sim_available = solara.use_reactive(False)
    video_available = solara.use_reactive(False)

    @solara.lab.use_task
    async def clock_loop():
        while True:
            if timer_running.value and timer_end_ts.value is not None:
                secs = timer_remaining_secs.value - 600
                if secs <= 0:
                    remaining_time_text_global.value = "00:00:00"
                    remaining_display.value = "00:00:00"
                    timer_running.value = False
                    timer_end_ts.value = None
                    timer_remaining_secs.value = 0
                else:
                    timer_remaining_secs.value = secs
                    h = secs // 3600
                    m = (secs % 3600) // 60
                    txt = f"{h:02d}:{m:02d}:00"
                    remaining_time_text_global.value = txt
                    remaining_display.value = txt

            await asyncio.sleep(0.5)

    @solara.lab.use_task
    async def health_check_loop():
        import requests as _hreq

        def _check():
            try:
                _hreq.get(f"{BACKEND_HTTP_BASE}/health", timeout=2)
                alive = True
            except Exception:
                alive = False

            sim = False
            video = False

            if alive:
                try:
                    r = _hreq.get(
                        f"{BACKEND_HTTP_BASE}/api/map/video/status", timeout=2
                    ).json()
                    video = r.get("available", False)
                except Exception:
                    video = False

                try:
                    r = _hreq.get(
                        f"{BACKEND_HTTP_BASE}/api/map/sim/status", timeout=2
                    ).json()
                    sim = r.get("available", False)
                except Exception:
                    sim = False

            return alive, sim, video

        while True:
            _alive, _sim, _video = await asyncio.to_thread(_check)
            backend_alive.value = _alive
            sim_available.value = _sim
            video_available.value = _video
            await asyncio.sleep(5)

    def handle_replan_click():
        if is_active.value:
            request_replan()
            is_active.value = False
            last_toggle_time.value = time.time()

    def handle_mission_delivery():
        deliver_mission()
        mission_toast_message.value = "임무 하달이 완료되었습니다."
        mission_toast_count.value += 1

    def handle_mission_confirm():
        mission_toast_message.value = "임무 확인이 완료되었습니다."
        mission_toast_count.value += 1

    is_admin = current_user == "admin"

    button_label = "임무 하달" if is_admin else "임무 확인"
    button_handler = handle_mission_delivery if is_admin else handle_mission_confirm
    
    
    solara.Style("""
        .gridview-root {
            width: 100%;
            height: 100%;
            min-height: 0;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            box-sizing: border-box;
            background: transparent !important;
        }

        .map-top-controls {
            background: transparent !important;
            display: flex;
            justify-content: flex-start;
            align-items: center;
            gap: 10px;
            flex: 0 0 auto;
            margin-bottom: 8px;
        }

        .map-main-display {
            position: relative;
            flex: 1 1 auto;
            min-height: 0;
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            border: 1px dashed rgba(148, 163, 184, 0.2);
            border-radius: 8px;
            margin-bottom: 0px;
            overflow: hidden;
            box-sizing: border-box;
            background-color: rgba(15, 23, 38, 0.38) !important;
        }

        .action-btn {
            height: 34px !important;
            width: 82px !important;
            font-size: 14px !important;
            font-weight: bold !important;
            border-radius: 6px !important;
            padding: 0 !important;
        }

        .btn-active {
            background-color: #e67e22 !important;
            color: white !important;
            opacity: 1.0 !important;
        }

        .btn-default {
            background-color: #2d3a54 !important;
            color: white !important;
            opacity: 0.8 !important;
        }

        .replan-btn {
            min-width: 110px !important;
            max-width: 110px !important;
            height: 34px !important;
            font-size: 14px !important;
            font-weight: bold !important;
            border-radius: 6px !important;
            flex-shrink: 0;
            transition: all 0.3s ease;
        }

        .gridview-root > div,
        .gridview-root .v-sheet,
        .map-main-display > div,
        .map-main-display .v-sheet {
            background: transparent !important;
            box-shadow: none !important;
        }

        .map-time-panel {
            position: absolute;
            top: 12px;
            right: 12px;
            display: flex;
            flex-direction: column;
            gap: 8px;
            z-index: 20;
            align-items: flex-end;
        }

        .time-chip {
            min-width: 190px;
            height: 38px;
            padding: 0 16px;
            border-radius: 8px;
            background: rgba(37, 52, 82, 0.35);
            border: 1px solid rgba(148, 163, 184, 0.12);
            color: white;
            font-size: 15px;
            font-weight: 700;
            display: flex;
            align-items: center;
            justify-content: center;
            box-sizing: border-box;
            white-space: nowrap;
        }

        .map-bottom-bar {
            width: 100%;
            margin-top: 10px;
            flex-shrink: 0;
        }

        .map-legend-bar {
            display: flex;
            align-items: center;
            width: 100%;
            gap: 12px;
        }

        .map-legend-left {
            display: flex;
            align-items: center;
            gap: 14px;
            flex-wrap: nowrap;
        }

        .map-legend-right {
            margin-left: auto;
            display: flex;
            align-items: center;
            flex-shrink: 0;
        }

        .legend-item {
            display: flex;
            flex-direction: row;
            align-items: center;
            gap: 6px;
            white-space: nowrap;
            color: #cbd5e1;
            font-size: 14px;
        }

        .mission-delivery-btn {
            width: 100%;
            height: 34px !important;
            border-radius: 8px !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            background: linear-gradient(90deg, #ff3d9a 0%, #ff2f7f 100%) !important;
            color: white !important;
            padding: 0 18px !important;
            white-space: nowrap;
            border: none !important;
            box-shadow: 0 4px 18px rgba(255, 61, 154, 0.22) !important;
        }
    """)

    with solara.Div(classes=["gridview-root"]):
        with solara.Div(classes=["map-main-display"]):
            import os

            mode_html_map = {
                "균형": "animated_gar_overlay_with_paths_persistent_alerts_balance_14.html",
                "정밀": "animated_gar_overlay_with_paths_persistent_alerts_explore_14.html",
                "신속": "animated_gar_overlay_with_paths_persistent_alerts_rush_14.html",
            }

            selected_mode = selected_mission_mode.value
            selected_html_file = mode_html_map.get(selected_mode)

            if not selected_html_file:
                solara.HTML(
                    tag="div",
                    unsafe_innerHTML="""
                    <div style="
                        position:absolute;
                        top:0;
                        left:0;
                        width:100%;
                        height:100%;
                        display:flex;
                        align-items:center;
                        justify-content:center;
                        background:#0f1726;
                        color:#94a3b8;
                        font-size:16px;
                        font-weight:600;
                        border:none;
                    ">
                        임무 모드를 선택하면 상황도가 표시됩니다.
                    </div>
                    """,
                )
            else:
                _html_path = os.path.join(
                    os.path.dirname(os.path.abspath(__file__)),
                    "..", "static",
                    selected_html_file
                )

                try:
                    with open(_html_path, "r", encoding="utf-8") as f:
                        _local_html = f.read()
                except Exception:
                    _local_html = """
                    <body style='margin:0;background:#0f1726;color:#94a3b8;display:flex;align-items:center;justify-content:center;height:100vh;'>
                        파일 로딩 실패
                    </body>
                    """

                solara.HTML(
                    tag="iframe",
                    attributes={
                        "srcdoc": _local_html,
                        "style": "position:absolute; top:0; left:0; width:100%; height:100%; border:none;",
                    },
                )

        with solara.Div(classes=["map-bottom-bar"]):
            with solara.Div(classes=["map-legend-bar"]):
                with solara.Div(classes=["map-legend-left"]):
                    with solara.Div(classes=["legend-item"]):
                        solara.HTML(
                            tag="div",
                            unsafe_innerHTML=(
                                '<svg width="18" height="22" viewBox="0 0 24 24" fill="none">'
                                '<path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z" fill="#f97316"/>'
                                '<circle cx="12" cy="9" r="3" fill="white"/></svg>'
                            ),
                        )
                        solara.Text("출발지")

                    with solara.Div(classes=["legend-item"]):
                        solara.HTML(
                            tag="div",
                            unsafe_innerHTML=(
                                '<svg width="18" height="22" viewBox="0 0 24 24" fill="none">'
                                '<path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z" fill="#3b82f6"/>'
                                '<circle cx="12" cy="9" r="3" fill="white"/></svg>'
                            ),
                        )
                        solara.Text("도착지1")

                    with solara.Div(classes=["legend-item"]):
                        solara.HTML(
                            tag="div",
                            unsafe_innerHTML=(
                                '<svg width="18" height="22" viewBox="0 0 24 24" fill="none">'
                                '<path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z" fill="#52c41a"/>'
                                '<circle cx="12" cy="9" r="3" fill="white"/></svg>'
                            ),
                        )
                        solara.Text("도착지2")

                    with solara.Div(classes=["legend-item"]):
                        solara.HTML(
                            tag="div",
                            unsafe_innerHTML=(
                                '<svg width="18" height="22" viewBox="0 0 24 24" fill="none">'
                                '<path d="M12 2C8.13 2 5 5.13 5 9C5 14.25 12 22 12 22C12 22 19 14.25 19 9C19 5.13 15.87 2 12 2Z" fill="#a855f7"/>'
                                '<circle cx="12" cy="9" r="3" fill="white"/></svg>'
                            ),
                        )
                        solara.Text("도착지3")

                    with solara.Div(classes=["legend-item"]):
                        solara.Text("★", style={"color": "#cbd5e1", "font-size": "14px"})
                        solara.Text("통제관")

                    with solara.Div(classes=["legend-item"]):
                        solara.Text("●", style={"color": "#cbd5e1", "font-size": "14px"})
                        solara.Text("UGV")

                with solara.Div(classes=["map-legend-right"]):
                    solara.Button(
                        button_label,
                        on_click=button_handler,
                        classes=["mission-delivery-btn"]
                    )