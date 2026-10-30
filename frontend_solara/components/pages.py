"""
frontend/components/pages.py

파이브웨더즈 UGV 전술 지원 시스템 — 페이지 컴포넌트 모음

[팀원 코드] LoginPage, CommanderPage, UserPage, CommanderInputPage,
            LoadingPage, UserMissionPage, MapCard, BaseAssetEditor,
            UnitAssetEditor, 차트 헬퍼 함수(build_line_chart_svg 등)
[내 코드]   MainPage, CommanderHomeHeader, OperatorHomeHeader
"""
import json
import os
import time
import solara
from datetime import datetime, timedelta
import threading
from components.grid_view import GridView
from components.cards import LtwrMapPanel
from components.map_html_builder import build_base_map_html
from components.state import (
    timer_running,
    timer_end_ts,
    remaining_time_text_global,
    timer_remaining_secs,
    video_should_play,
    toast_trigger,
    departure_times,
    ARRIVAL_TIMES_BY_MODE,
    selected_mission_mode,
    operating_ugv_plan,
    active_btn,
    asset_data,
    mission_settings,
    mission_delivery_data,
    DEST_INFO_BY_MODE,
    mission_toast_count,
    MISSION_UGV_PLAN_BY_MODE,
    mission_toast_count,
    mission_toast_message,
)
from services.api_client import (
    BACKEND_HTTP_BASE,
    # ── 공통 ──────────────────────────────────────────────
    input_username,
    input_password,
    login_error,
    attempt_login,
    logged_in_user,
    NICKNAMES,
    go_home,
    #active_btn,
    set_active_button,
    success_rate,
    asset_damage,
    status,
    time_left,
    ratio_x,
    effect_success,
    effect_damage,
    queue_data,
    message_text,
    is_logged_in,
    active_run_id,
    # ── 팀원 코드: 역할/워크플로우 상태 ─────────────────────
    user_role,
    workflow_step,
    destination_data,
    mission_note,
    commander_data_ready,
    simulation_done,
    zoom_levels,
    recon_time,
    # ── 내 코드: 홈 대시보드 상태 ───────────────────────────
    patrol_area,
    home_role,
    home_role_label,
    home_current_time,
    home_remaining_time,
    home_mission_notice,
    home_unit_label,
    home_asset_modes,
    selected_asset_mode,
    set_selected_asset_mode,
    post_operator_mission_config,
    fetch_operator_briefing,
    unit_kpi_data,
)
from components import ws_client
#from components.mission_actions import deliver_mission

# ── 팀원 코드: 자산 현황 팝업 전역 상태 ──────────────────────────
asset_popup_tab = solara.reactive("부대 기본자산")

# asset_data = solara.reactive({
#     "base": {
#         "total_units": 3,
#         "total_controllers": 3,
#         "total_ugv": 13,
#         "lost_ugv": 1,
#     },
#     "user1": {
#         "controllers": 1,
#         "total_ugv": 4,
#         "lost_ugv": 0,
#         "available_ugv": 2,
#         "target_lat": "39.12",
#         "target_lon": "12.45",
#     },
#     "user2": {
#         "controllers": 1,
#         "total_ugv": 4,
#         "lost_ugv": 0,
#         "available_ugv": 4,
#         "target_lat": "",
#         "target_lon": "",
#     },
#     "user3": {
#         "controllers": 1,
#         "total_ugv": 5,
#         "lost_ugv": 1,
#         "available_ugv": 3,
#         "target_lat": "",
#         "target_lon": "",
#     },
# })


# ── 팀원 코드: 임무 하달용 전역 상태 ──────────────────────────────
#### state.py로 옮김 (pages에서도 쓰고 grid_view에서도 쓰고 mission_actions에서도 써서,,)
#### 균형/신속/정밀 일때 도착예정시각 / 출발예정시각





# mission_delivery_data = solara.reactive({
#     "delivered": False,
#     "base_summary": {
#         "total_units": 0,
#         "total_controllers": 0,
#         "total_recon_ugv": 0,
#         "total_lost_ugv": 0,
#     },
#     "units": {
#         "user1": {"controllers": 0, "total_recon_ugv": 0, "lost_ugv": 0, "available_ugv": 0, "target_lat": "", "target_lon": ""},
#         "user2": {"controllers": 0, "total_recon_ugv": 0, "lost_ugv": 0, "available_ugv": 0, "target_lat": "", "target_lon": ""},
#         "user3": {"controllers": 0, "total_recon_ugv": 0, "lost_ugv": 0, "available_ugv": 0, "target_lat": "", "target_lon": ""},
#     },
#     "mission_info": {
#         "user1": {"mission_mode": "", "operating_ugv_count": 0, "departure_time": "", "arrival_time": "", "recon_time": ""},
#         "user2": {"mission_mode": "", "operating_ugv_count": 0, "departure_time": "", "arrival_time": "", "recon_time": ""},
#         "user3": {"mission_mode": "", "operating_ugv_count": 0, "departure_time": "", "arrival_time": "", "recon_time": ""},
#     },
# })


### 현재시간 나타내기
# 시뮬레이션 기준 시작 시각
sim_base_time = datetime(2023, 7, 27, 3, 0, 0)
# 앱이 시작된 실제 시각 (웹 서버/커널 켜진 시점)
app_start_ts = time.time()
# 단순 리렌더 유도용 tick
tick = solara.reactive(0)



#### 도착지 별 위도 경도 #####
commander_input_state = solara.reactive({
    "user1": {"lat": "", "lng": "", "recon": ""},
    "user2": {"lat": "", "lng": "", "recon": ""},
    "user3": {"lat": "", "lng": "", "recon": ""},
})

#### 도착지 별 위도 경도 반영 버튼 ####
commander_marker_state = solara.reactive({
    "user1": None,
    "user2": None,
    "user3": None,
})

# ──────────────────────────────────────────────────────────────
# [팀원 코드] 부대 기본자산 편집 컴포넌트
# ──────────────────────────────────────────────────────────────
@solara.component
def BaseAssetEditor():
    total_units, set_total_units = solara.use_state("")
    total_controllers, set_total_controllers = solara.use_state("")
    total_ugv, set_total_ugv = solara.use_state("")
    lost_ugv, set_lost_ugv = solara.use_state("")

    def _sync():
        d = asset_data.value["base"]
        set_total_units(str(d["total_units"]))
        set_total_controllers(str(d["total_controllers"]))
        set_total_ugv(str(d["total_ugv"]))
        set_lost_ugv(str(d["lost_ugv"]))

    solara.use_effect(_sync, [])

    def save_base_asset():
        updated = dict(asset_data.value)
        updated_base = dict(updated["base"])
        updated_base["total_units"] = total_units
        updated_base["total_controllers"] = total_controllers
        updated_base["total_ugv"] = total_ugv
        updated_base["lost_ugv"] = lost_ugv
        updated["base"] = updated_base
        asset_data.value = updated

    def reset_base_asset():
        latest = asset_data.value["base"]
        set_total_units(str(latest["total_units"]))
        set_total_controllers(str(latest["total_controllers"]))
        set_total_ugv(str(latest["total_ugv"]))
        set_lost_ugv(str(latest["lost_ugv"]))

    with solara.Div(classes=["asset-form-card"]):
        with solara.Div(classes=["asset-form-row"]):
            solara.Text("총 제대 수", classes=["asset-form-label"])
            solara.InputText("", value=total_units, on_value=set_total_units)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("총 통제관 수", classes=["asset-form-label"])
            solara.InputText("", value=total_controllers, on_value=set_total_controllers)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("총 정찰 UGV 수", classes=["asset-form-label"])
            solara.InputText("", value=total_ugv, on_value=set_total_ugv)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("총 손실 UGV 수", classes=["asset-form-label"])
            solara.InputText("", value=lost_ugv, on_value=set_lost_ugv)

        # with solara.Div(classes=["asset-form-action-row"]):
        #     solara.Button("저장", on_click=save_base_asset, classes=["asset-save-btn"])
        #     solara.Button("취소", on_click=reset_base_asset, classes=["asset-cancel-btn"])


# ──────────────────────────────────────────────────────────────
# [팀원 코드] 제대별 기본자산 편집 컴포넌트
# ──────────────────────────────────────────────────────────────
@solara.component
def UnitAssetEditor(unit_key: str, title: str):
    controllers, set_controllers = solara.use_state("")
    total_ugv, set_total_ugv = solara.use_state("")
    lost_ugv, set_lost_ugv = solara.use_state("")
    available_ugv, set_available_ugv = solara.use_state("")
    target_lat, set_target_lat = solara.use_state("")
    target_lon, set_target_lon = solara.use_state("")

    # unit_key가 바뀔 때(탭 전환)마다 asset_data에서 값 재동기화
    def _sync():
        d = asset_data.value[unit_key]
        set_controllers(str(d["controllers"]))
        set_total_ugv(str(d["total_ugv"]))
        set_lost_ugv(str(d["lost_ugv"]))
        set_available_ugv(str(d["available_ugv"]))
        set_target_lat(str(d["target_lat"]))
        set_target_lon(str(d["target_lon"]))

    solara.use_effect(_sync, [unit_key])

    def save_unit_asset():
        updated = dict(asset_data.value)
        updated_unit = dict(updated[unit_key])
        updated_unit["controllers"] = controllers
        updated_unit["total_ugv"] = total_ugv
        updated_unit["lost_ugv"] = lost_ugv
        updated_unit["available_ugv"] = available_ugv
        updated_unit["target_lat"] = target_lat
        updated_unit["target_lon"] = target_lon
        updated[unit_key] = updated_unit
        asset_data.value = updated

    def reset_unit_asset():
        latest = asset_data.value[unit_key]
        set_controllers(str(latest["controllers"]))
        set_total_ugv(str(latest["total_ugv"]))
        set_lost_ugv(str(latest["lost_ugv"]))
        set_available_ugv(str(latest["available_ugv"]))
        set_target_lat(str(latest["target_lat"]))
        set_target_lon(str(latest["target_lon"]))

    with solara.Div(classes=["asset-form-card"]):
        with solara.Div(classes=["asset-form-row"]):
            solara.Text("통제관 수", classes=["asset-form-label"])
            solara.InputText("", value=controllers, on_value=set_controllers)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("총 정찰 UGV 수", classes=["asset-form-label"])
            solara.InputText("", value=total_ugv, on_value=set_total_ugv)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("손실 UGV 수", classes=["asset-form-label"])
            solara.InputText("", value=lost_ugv, on_value=set_lost_ugv)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("운용 가능 UGV 수", classes=["asset-form-label"])
            solara.InputText("", value=available_ugv, on_value=set_available_ugv)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("목표 위도", classes=["asset-form-label"])
            solara.InputText("", value=target_lat, on_value=set_target_lat)

        with solara.Div(classes=["asset-form-row"]):
            solara.Text("목표 경도", classes=["asset-form-label"])
            solara.InputText("", value=target_lon, on_value=set_target_lon)

        # with solara.Div(classes=["asset-form-action-row"]):
        #     solara.Button("저장", on_click=save_unit_asset, classes=["asset-save-btn"])
        #     solara.Button("취소", on_click=reset_unit_asset, classes=["asset-cancel-btn"])


# ──────────────────────────────────────────────────────────────
# [팀원 코드] 로그인 페이지
# static/loginpage_picture_3.png 를 base64로 읽어 배경 이미지로 사용.
# 클릭 시 로그인 폼 오버레이 표시.
# ──────────────────────────────────────────────────────────────
@solara.component
def LoginPage():
    import base64

    # 이미지 파일 경로: frontend/static/loginpage_picture_3.png
    HERE_LP = os.path.dirname(os.path.abspath(__file__))
    img_path = os.path.join(os.path.dirname(HERE_LP), "static", "loginpage_picture_4.png")
    img_base64 = ""
    try:
        with open(img_path, "rb") as f:
            img_base64 = base64.b64encode(f.read()).decode("utf-8")
    except Exception as e:
        print(f"[LoginPage] 이미지 로드 실패: {e}")

    show_login_overlay, set_show_login_overlay = solara.use_state(False)

    # 마운트 시 이전 세션의 비밀번호 잔류값 초기화
    def _clear_on_mount():
        input_username.set("")
        input_password.set("")
        login_error.set(False)
    solara.use_effect(_clear_on_mount, [])

    def open_login_overlay():
        set_show_login_overlay(True)

    def handle_login():
        attempt_login()

    solara.Style("""
        html, body, #app, .v-application, .v-application__wrap {
            width: 100%;
            height: 100%;
            margin: 0 !important;
            padding: 0 !important;
            overflow: hidden !important;
            background-color: #0b1426 !important;
        }

        .login-page-root {
            position: fixed;
            inset: 0;
            width: 100vw;
            height: 100vh;
            overflow: hidden;
            background-color: #0b1426;
        }

        .bg-image {
            position: absolute;
            inset: 0;
            width: 100%;
            height: 100%;
            object-fit: contain;
            object-position: center center;
            display: block;
            background-color: #0b1426;
            z-index: 1;
        }

        /* 전체화면 투명 클릭 버튼 */
        .overlay-open-button {
            position: absolute !important;
            inset: 0 !important;
            width: 100vw !important;
            height: 100vh !important;
            min-width: 100vw !important;
            min-height: 100vh !important;
            z-index: 2 !important;
            opacity: 0 !important;
            background: transparent !important;
            border: none !important;
            box-shadow: none !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        .overlay-open-button * {
            opacity: 0 !important;
        }

        /* 깜빡이는 힌트 텍스트 */
        .splash-hint {
            position: absolute;
            bottom: 36px;
            left: 50%;
            transform: translateX(-50%);
            color: rgba(255, 255, 255, 0.78);
            font-size: 15px;
            animation: blink 1.5s infinite;
            z-index: 3;
            margin: 0;
            pointer-events: none;
        }

        /* 로그인 오버레이 레이어 */
        .login-overlay {
            position: absolute;
            inset: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            background: rgba(11, 20, 38, 0.18);
            z-index: 4;
        }

        /* 로그인 카드 */
        .login-card {
            padding: 40px;
            background-color: rgba(22, 34, 56, 0.8) !important;
            border: 1px solid #2d3a54 !important;
            border-radius: 22px;
            width: 400px;
            color: white !important;
            box-shadow: 0 12px 32px rgba(0, 0, 0, 0.35);
        }

        .login-card * {
            color: white;
        }

        input {
            color: white !important;
        }

        .v-label {
            color: #aab4c8 !important;
        }

        @keyframes blink {
            0%, 100% { opacity: 1; }
            50% { opacity: 0.3; }
        }
    """)

    with solara.Div(classes=["login-page-root"]):
        # 배경 이미지 (base64 인라인)
        solara.HTML(
            tag="img",
            attributes={
                "src": f"data:image/png;base64,{img_base64}",
                "alt": "background",
                "class": "bg-image",
            },
        )

        if not show_login_overlay:
            # 전체화면 투명 버튼 — 클릭으로 로그인 폼 표시
            solara.Button(
                label=" ",
                on_click=open_login_overlay,
                classes=["overlay-open-button"],
            )
            solara.HTML(
                tag="p",
                unsafe_innerHTML="Click to continue...",
                attributes={"class": "splash-hint"},
            )

        if show_login_overlay:
            with solara.Div(classes=["login-overlay"]):
                with solara.Div(classes=["login-card"]):
                    solara.HTML(
                        tag="div",
                        unsafe_innerHTML=(
                            "<div style='text-align:center; margin-bottom:30px;'>"
                            "<span style='font-size:28px; font-weight:bold; color:white;'>UGV</span><br>"
                            "<span style='font-size:22px; font-weight:bold; color:#aab4c8;'>Tactical Decision Support</span>"
                            "</div>"
                        ),
                    )

                    solara.InputText(
                        "USER ID",
                        value=input_username.value,
                        on_value=input_username.set,
                    )

                    def on_password_enter(v):
                        input_password.set(v)
                        handle_login()

                    solara.InputText(
                        "PASSWORD",
                        value=input_password.value,
                        on_value=on_password_enter,
                        password=True,
                        continuous_update=False,
                    )

                    if login_error.value:
                        solara.Text(
                            message_text.value if message_text.value else "정보가 올바르지 않습니다.",
                            style={
                                "color": "#fb7185",
                                "font-size": "14px",
                                "margin-top": "10px",
                                "display": "block",
                                "text-align": "center",
                            },
                        )

                    solara.Button(
                        "Login to Dashboard",
                        on_click=handle_login,
                        style={
                            "background-color": "#2d3a54",
                            "color": "white",
                            "height": "50px",
                            "width": "100%",
                            "margin-top": "20px",
                        },
                    )


# ──────────────────────────────────────────────────────────────
# [팀원 코드] LTWR 맵 카드 (우측 사이드바용)
# frontend/static/ 폴더의 HTML 파일을 iframe srcdoc으로 로드.
# ──────────────────────────────────────────────────────────────
@solara.component
def MapCard(title, file_name, zoom_level):
    CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
    ROOT_DIR = os.path.dirname(CURRENT_DIR)
    full_path = os.path.join(ROOT_DIR, "static", file_name)

    html_content = ""
    try:
        if os.path.exists(full_path):
            with open(full_path, "r", encoding="utf-8") as f:
                html_content = f.read()
        else:
            html_content = f"<h3 style='color:red;'>파일 없음: {full_path}</h3>"
    except Exception as e:
        html_content = f"<h3>에러 발생: {str(e)}</h3>"

    with solara.Div(style={
        "margin-bottom": "15px",
        "background": "rgba(45, 58, 84, 0.55)",
        "border": "1px solid rgba(148, 163, 184, 0.18)",
        "border-radius": "8px",
        "padding": "5px",
    }):
        solara.Text(title, style={"color": "white", "margin-left": "10px", "font-size": "14px"})
        solara.HTML(
            tag="iframe",
            attributes={
                "srcdoc": html_content,
                "style": "width: 100%; height: 250px; border: none; border-radius: 4px; background: black;",
            },
        )


# ──────────────────────────────────────────────────────────────
# [팀원 코드] 임무 성공률 / 위험률 SVG 라인 차트 헬퍼
# ──────────────────────────────────────────────────────────────
def build_line_chart_svg(title, labels, values, point_colors=None, line_color="#d1d5db"):
    width = 320
    height = 110
    left, right, top, bottom = 42, 18, 14, 24
    plot_w = width - left - right
    plot_h = height - top - bottom
    y_min, y_max = 0, 100
    x_pad = 22
    if point_colors is None:
        point_colors = ["#ef4444", "#3b82f6", "#22c55e"]  # 1제대, 2제대, 3제대

    def px_x(i):
        if len(labels) == 1:
            return left + plot_w / 2
        usable_w = plot_w - (x_pad * 2)
        return left + x_pad + (usable_w * i / (len(labels) - 1))

    def px_y(v):
        ratio = (v - y_min) / (y_max - y_min)
        return top + plot_h - (plot_h * ratio)

    points = [(px_x(i), px_y(v)) for i, v in enumerate(values)]
    polyline_points = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)
    y_ticks = [0, 20, 40, 60, 80, 100]

    grid_lines = []
    tick_labels = []
    for t in y_ticks:
        y = px_y(t)
        grid_lines.append(
            f'<line x1="{left}" y1="{y:.1f}" x2="{left + plot_w}" y2="{y:.1f}" '
            f'stroke="rgba(148,163,184,0.18)" stroke-width="1"/>'
        )
        tick_labels.append(
            f'<text x="{left - 8}" y="{y + 4:.1f}" text-anchor="end" '
            f'fill="#94a3b8" font-size="11">{t}</text>'
        )

    x_labels = [
        f'<text x="{px_x(i):.1f}" y="{height - 10}" text-anchor="middle" '
        f'fill="#cbd5e1" font-size="12">{label}</text>'
        for i, label in enumerate(labels)
    ]

    point_circles = []
    value_labels = []
    for i, ((x, y), v) in enumerate(zip(points, values)):
        point_circles.append(
            f'<circle cx="{x:.1f}" cy="{y:.1f}" r="5" fill="{point_colors[i]}"/>'
        )
        value_labels.append(
            f'<text x="{x:.1f}" y="{y - 12:.1f}" text-anchor="middle" '
            f'fill="#e5e7eb" font-size="12" font-weight="700">{v}</text>'
        )

    return f"""
    <div style="width:100%;height:100%;min-height:0;display:flex;align-items:center;
                justify-content:center;background:#1e293b;border-radius:10px;overflow:hidden;">
        <svg viewBox="0 0 {width} {height}" preserveAspectRatio="none"
             style="width:100%; height:100%; display:block;">
            <rect x="0" y="0" width="{width}" height="{height}" fill="#1e293b" rx="10"/>
            {''.join(grid_lines)}
            {''.join(tick_labels)}
            {''.join(x_labels)}
            <polyline fill="none" stroke="{line_color}" stroke-width="2.5" stroke-opacity="0.3"
                points="{polyline_points}" stroke-linecap="round" stroke-linejoin="round"/>
            {''.join(point_circles)}
            {''.join(value_labels)}
        </svg>
    </div>
    """


def make_success_chart_svg():
    kpi = unit_kpi_data.value
    values = [
        kpi.get("user1", {}).get("success", 0),
        kpi.get("user2", {}).get("success", 0),
        kpi.get("user3", {}).get("success", 0),
    ]
    return build_line_chart_svg("제대별 임무 성공률", ["1제대", "2제대", "3제대"], values)


def make_risk_chart_svg():
    kpi = unit_kpi_data.value
    values = [
        kpi.get("user1", {}).get("risk", 0),
        kpi.get("user2", {}).get("risk", 0),
        kpi.get("user3", {}).get("risk", 0),
    ]
    return build_line_chart_svg("제대별 임무 위험률", ["1제대", "2제대", "3제대"], values)




# ──────────────────────────────────────────────────────────────
# [팀원 코드] 지휘관 메인 페이지
# 상단: 역할/자산현황 버튼 + 임무모드 선택 + 제대별 현황 테이블
# 좌측: 임무성공률/위험률 SVG 차트 + 실행/종료/임무하달 버튼
# 중앙: 전술 맵 (GridView)
# 우측: LTWR 맵 패널 또는 자산현황 편집 팝업
# ──────────────────────────────────────────────────────────────
@solara.component
def CommanderPage():
    current_user = logged_in_user.value
    user_label = "지휘관" if current_user == "admin" else "통제관"

    recon_times = mission_settings.value.get("recon_times", {})
    unit1_recon = recon_times.get("user1", "-")
    unit2_recon = recon_times.get("user2", "-")
    unit3_recon = recon_times.get("user3", "-")

    run_state, set_run_state = solara.use_state("")
    show_asset_popup, set_show_asset_popup = solara.use_state(False)
    asset_tab, set_asset_tab = solara.use_state("부대 기본자산")
    #toastcount, settoastcount = solara.use_state(0)
    # current_time_text, set_current_time_text = solara.use_state(
    #     datetime.now().strftime("%Y.%m.%d %H:%M:%S"))
    #start_time = datetime(2023, 7, 26, 15, 0, 0)
    #current_time_text = sim_current_time.value.strftime("%Y.%m.%d %H:%M:%S")
    
    # 임무 모드별 상단 KPI 값 정의
    MISSION_KPI_DATA = {
        "균형": {
            "mission_success": 98.0,    # 임무 성공률
            "worst_success": 89.0,      # 최저 성공률
            "arrived_ugv": 8.8,         # 도착 UGV 수
            "sos_count": 18.9,          # SOS 요청 건수
            "per_sos_queue": 10.0,      # 건당 대기열 (분)
            "controller_util": 27.0,    # 통제관 가동률
        },
        "신속": {
            # TODO: 신속 모드 값 채우기
            "mission_success": 98.0,
            "worst_success": 78.0,
            "arrived_ugv": 8.8,
            "sos_count": 15.9,
            "per_sos_queue": 9.0,
            "controller_util": 24.0,
        },
        "정밀": {
            # TODO: 정밀 모드 값 채우기
            "mission_success": 96.0,
            "worst_success": 78.0,
            "arrived_ugv": 8.6,
            "sos_count": 19.4,
            "per_sos_queue": 10.0,
            "controller_util": 27.0,
        },
    }
    
    
    def update_clock(cancel):
        while not cancel.is_set():
            time.sleep(1)
            tick.value += 1   # 1초마다 리렌더만 유도

    solara.use_thread(update_clock, dependencies=[])
    
    # tick을 읽어서 이 컴포넌트가 tick에 의존한다고 알려줌
    _ = tick.value

    # 여기서부터는 매번 "경과 시간"으로 현재 시뮬레이션 시각 계산
    elapsed_seconds = int(time.time() - app_start_ts)
    current_sim_time = sim_base_time + timedelta(seconds=elapsed_seconds)
    current_time_text = current_sim_time.strftime("%Y.%m.%d %H:%M:%S")


    def start_execution():
        set_run_state("run")
        timer_running.value = True
        timer_end_ts.value = time.time() + 3 * 3600
        timer_remaining_secs.value = 10800   # 3시간
        remaining_time_text_global.value = "03:00:00"
        video_should_play.value = True

    def stop_execution():
        set_run_state("stop")
        timer_running.value = False
        timer_end_ts.value = None
        timer_remaining_secs.value = 0
        remaining_time_text_global.value = "00:00:00"
        video_should_play.value = False
       
    def go_back():
        workflow_step.set(0)

    


    map_label_1 = "h+1"
    map_label_2 = "h+2"
    map_label_3 = "h+3"
    
    
    current_arrival_times = ARRIVAL_TIMES_BY_MODE.get(active_btn.value, {})

    current_arrival_times = ARRIVAL_TIMES_BY_MODE.get(active_btn.value, {})

    unit_info_rows = [
        {
            "unit": "1제대",
            "ugv": asset_data.value.get("user1", {}).get("available_ugv", 0),
            "depart": departure_times.value.get("user1", "-"),
            "arrive": current_arrival_times.get("user1", "-"),
            "recon": unit1_recon or "-"
        },
        {
            "unit": "2제대",
            "ugv": asset_data.value.get("user2", {}).get("available_ugv", 0),
            "depart": departure_times.value.get("user2", "-"),
            "arrive": current_arrival_times.get("user2", "-"),
            "recon": unit2_recon or "-"
        },
        {
            "unit": "3제대",
            "ugv": asset_data.value.get("user3", {}).get("available_ugv", 0),
            "depart": departure_times.value.get("user3", "-"),
            "arrive": current_arrival_times.get("user3", "-"),
            "recon": unit3_recon or "-"
        },
    ]

    solara.Style("""
        .status-item-box > div, .status-item-box .v-sheet,
        .sub-inner-card > div, .sub-inner-card .v-sheet,
        .right-sidebar-area > div, .right-sidebar-area .v-sheet,
        .v-application, .v-application--wrap, .v-main, .v-card {
            background-color: transparent !important;
            box-shadow: none !important;
            border: none !important;
        }

        html, body, #app, .v-application, .v-application--wrap,
        .solara-content-main, .solara-app, .v-main {
            background-color: #0b1426 !important;
            color: white !important;
            width: 100% !important;
            height: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        .page-root {
            width: 100vw;
            height: 100vh;
            background: #0b1426;
            overflow: hidden;
            box-sizing: border-box;
            padding: 16px;
        }

        .page-shell {
            width: 100%; height: 100%;
            min-height: 0;
            display: grid;
            /* 3컬럼 구조 고정 */
            grid-template-columns: 380px minmax(0, 1fr) 390px;
            /* 행 구조: 상단바(auto), 맵(1fr) */
            grid-template-rows: auto 1fr;
            column-gap: 12px;
            row-gap: 4px; /* 상하 간격 조절 (더 붙이고 싶으면 값을 줄이세요) */
            box-sizing: border-box;
        }

        .top-sidebar-bar {
            grid-column: 1 / 3;
            grid-row: 1;
            display: grid;
            grid-template-columns: 380px minmax(0, 1fr);
            gap: 12px;
            align-items: end; /* 중요: 상단 패널들을 아래쪽 라인에 맞춤 */
            margin-bottom: 0; /* 아래 컨텐츠와 딱 붙도록 설정 */
        }

        .top-left-panel {
            grid-column: 1;
            grid-row: 1;
            align-self: stretch;
            background-color: rgba(22, 34, 56, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.55) !important;
            border-radius: 16px; padding: 8px;
            display: flex; flex-direction: column;
            gap: 5px; box-sizing: border-box;
        }

        .top-right-panel {
            grid-column: 2;
            grid-row: 1;
            width: 100%;
            align-self: end; /* 아래쪽으로 밀착 */
            align-self: start;
            width: 100%;
            min-height: 0; height: 100%;
            justify-self: stretch;
            background-color: rgba(22, 34, 56, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.55) !important;
            border-radius: 16px;
            padding: 6px 18px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            box-sizing: border-box;
            overflow: hidden;
        }

        .top-user-row { display: flex; align-items: center; gap: 8px; }

        .mission-mode-card {
            background-color: rgba(15, 23, 38, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.45) !important;
            border-radius: 13px; padding: 9px 10px;
            display: flex; flex-direction: column; gap: 7px;
        }

        .mode-title { color: #9ca3af !important; font-size: 12px; font-weight: 700; margin: 0; line-height: 1; }

        .mode-btn-row { display: flex; gap: 6px; }


        .mode-btn-active  { background-color: #e67e22 !important; color: white !important; }
        .mode-btn-default { background-color: #0f1b33 !important; color: white !important; }

        .unit-summary-header, .unit-summary-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            gap: 8px;
            padding-left: 6px;
            padding-right: 8px;
            box-sizing: border-box;
        }

        .unit-summary-header {
            padding: 0 0 5px 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.16);
            margin-bottom: 2px;
        }

        .unit-summary-row {
            padding: 5px 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.08);
        }

        .unit-summary-row:last-child { border-bottom: none; }

        .col-unit {
            flex: 0.9;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: flex-start;
            text-align: left;
            padding-left: 20px;
        }
        .col-ugv {
            flex: 0.9;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }
        .col-time {
            flex: 1.25;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }
        .col-dest {
            flex: 1.35;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }
        
        .summary-head-text  { color: #94a3b8 !important; font-size: 10.5px !important; font-weight: 700 !important; white-space: nowrap; letter-spacing: -0.2px; text-align: center; width: 100%; }
        .summary-unit-text  { color: #d1d5db !important; font-size: 13px !important; font-weight: 700 !important; white-space: nowrap; text-align: left; width: 100%; }
        .summary-value-text { color: white !important; font-size: 13px !important; font-weight: 600 !important; white-space: nowrap; text-align: center; width: 100%; }

        .ugv-badge {
            width: 30px; height: 24px; border-radius: 7px; background: #e67e22;
            display: flex; align-items: center; justify-content: center;
            color: white; font-weight: 800; font-size: 14px; margin: 0 auto;
        }

        .content-grid-left {
            grid-column: 1 / 3;
            grid-row: 2;
            display: grid;
            grid-template-columns: 380px minmax(0, 1fr);
            gap: 12px;
            align-items: stretch;
            margin-top: 0; /* 상단 바와 밀착 */
        }

        /* 왼쪽 칼럼 전체를 화면 남는 높이만큼 쓰게 */
        .left-sub-sidebar {
            position: relative;
            flex: 1;
            display: flex;
            flex-direction: column;
            gap: 16px;
            min-height: 0;
            overflow: hidden;
        }

        /* 차트 카드는 위쪽 내용물만큼만 */
        .mission-chart-card {
            background-color: rgba(15, 23, 38, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px; padding: 10px 10px 4px 10px;
            display: flex; flex-direction: column; gap: 8px;
            box-sizing: border-box; overflow: hidden;
            flex: 0 0 auto;
            height: 355px;
        }

        .chart-block {
            display: flex;
            flex-direction: column;
            gap: 8px;
            min-height: 0;
            flex: 0 0 auto;
        }

        .chart-title {
            color: #cbd5e1 !important;
            font-size: 15px;
            font-weight: 700;
            margin: 0;
            flex-shrink: 0;
        }

        .chart-placeholder {
            border-radius: 10px;
            background: rgba(30, 41, 59, 0.65);
            border: 1px solid rgba(148, 163, 184, 0.18);
            display: flex; align-items: stretch; justify-content: stretch;
            padding: 6px; overflow: hidden;
            flex: 0 0 auto;
        }

        .chart-divider {
            height: 1px;
            background: rgba(148, 163, 184, 0.22);
            margin: 0;
            flex-shrink: 0;
        }

        /* 버튼 카드는 아래로 밀기 */
        .sub-inner-card {
            background-color: rgba(15, 23, 38, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px; padding: 15px;
            display: flex; flex-direction: column; box-sizing: border-box;
            margin-top: auto;
            flex-shrink: 0;
        }

        .center-map-area {
            grid-column: 2;
            grid-row: 2;
            min-height: 0; height: 100%;
            display: flex;
            flex-direction: column;
            align-self: stretch;
            width: 100%;
            display: flex;
            flex-direction: column;
            background-color: rgba(15, 23, 38, 0.72) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px;
            padding: 12px;
            box-sizing: border-box;
            overflow: hidden;
        }

        .center-map-inner {
            flex: 1; 
            min-height: 0; 
            height: 100%; 
            width: 100%;
            display: flex; 
            flex-direction: column;
            overflow: hidden; 
            border-radius: 10px; 
            background: transparent !important;
        }

        .center-map-inner > div, .center-map-inner .v-sheet {
            flex: 1 1 auto; min-height: 0; height: 100%; background: transparent !important;
        }

        .center-map-inner iframe { width: 100%; height: 100%; border: none; background: transparent !important; }

        .right-sidebar-area {
            grid-column: 3;
            grid-row: 1 / 3;
            min-width: 0;
            min-height: 0; height: 100%;
            display: flex;
            flex-direction: column;
            background-color: rgba(11, 20, 38, 0.96) !important;
            border: 1px solid rgba(45, 58, 84, 0.8) !important;
            border-radius: 12px;
            padding: 5px 1px 5px 10px;
            box-sizing: border-box;
            overflow-y: auto;
            scrollbar-gutter: stable;
        }

        .right-sidebar-area::-webkit-scrollbar {
            width: 10px;
        }

        .right-sidebar-area::-webkit-scrollbar-track {
            background: rgba(30, 41, 59, 0.95);
            border-radius: 999px;
        }

        .right-sidebar-area::-webkit-scrollbar-thumb {
            background: rgba(148, 163, 184, 0.35);
            border-radius: 999px;
            border: 2px solid rgba(30, 41, 59, 0.95);
        }

        .right-sidebar-area::-webkit-scrollbar-thumb:hover {
            background: rgba(203, 213, 225, 0.55);
        }

        @supports not selector(::-webkit-scrollbar) {
            .right-sidebar-area {
                scrollbar-width: thin;
                scrollbar-color: rgba(148, 163, 184, 0.35) rgba(30, 41, 59, 0.95);
            }
        }

        .map-card-container {
            background-color: rgba(15, 23, 42, 0.96) !important;   /* 거의 불투명 카드 */
            border: 1px solid rgba(148, 163, 184, 0.22) !important; /* 연한 회색 테두리 */
            border-radius: 12px;
            padding: 12px 12px 10px;
            margin-bottom: 14px;
            position: relative;
            overflow: hidden;
        }
        .map-frame-wrapper { 
            width: 100%;
            height: 140px;
            border-radius: 8px;
            overflow: hidden;
            background: #000000;
        }
        .map-controls { position: absolute; right: 18px; top: 45px; display: flex; flex-direction: column; gap: 4px; z-index: 10; }

        .zoom-btn {
            min-width: 28px !important; height: 28px !important;
            background-color: rgba(30, 41, 59, 0.9) !important;
            color: white !important; border: 1px solid rgba(255,255,255,0.2) !important;
            border-radius: 4px !important; padding: 0 !important; font-size: 16px !important;
        }

        .card-label { color: #94a3b8 !important; font-size: 14px; font-weight: bold; margin-bottom: 8px; }

        .control-btn-card {
            background-color: rgba(15, 23, 38, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px; padding: 12px;
            display: flex; flex-direction: column; gap: 10px;
            box-sizing: border-box; flex-shrink: 0;
        }

        .control-btn-row { display: flex; gap: 10px; width: 100%; }

        .run-btn, .stop-btn {
            flex: 1; height: 34px !important; border-radius: 8px !important;
            font-size: 14px !important; font-weight: 700 !important; padding: 0 !important;
        }

        .btn-selected   { background-color: #e68a00 !important; color: white !important; }
        .btn-unselected { background-color: #0f172a !important; color: white !important; }

        .mission-delivery-btn {
            width: 100%; height: 34px !important; border-radius: 8px !important;
            font-size: 14px !important; font-weight: 700 !important;
            background: linear-gradient(90deg, #ff3d9a 0%, #ff2f7f 100%) !important;
            color: white !important; padding: 0 !important;
        }

        .mission-toast {
            position: fixed;
            bottom: 36px;
            left: 50%;
            transform: translateX(-50%);
            background: rgba(30, 41, 59, 0.96);
            border: 1px solid rgba(255, 61, 154, 0.55);
            border-radius: 10px;
            padding: 12px 28px;
            color: white;
            font-size: 15px;
            font-weight: 600;
            z-index: 9999;
            box-shadow: 0 4px 24px rgba(255, 61, 154, 0.25);
            display: flex;
            align-items: center;
            gap: 10px;
            pointer-events: none;
            animation: toast-lifecycle 2.5s ease forwards;
        }

        @keyframes toast-lifecycle {
            0%   { opacity: 0; transform: translateX(-50%) translateY(12px); }
            12%  { opacity: 1; transform: translateX(-50%) translateY(0); }
            75%  { opacity: 1; transform: translateX(-50%) translateY(0); }
            100% { opacity: 0; transform: translateX(-50%) translateY(0); }
        }
        
        .asset-popup-overlay-left {
            position: absolute;
            inset: 0;
            z-index: 1000;
            display: flex;
            border-radius: 12px;
        }

        .asset-popup-panel {
            width: 100%;
            height: 100%;
            min-height: 0;
            display: flex;
            flex-direction: column;
            background-color: rgba(15, 23, 38, 1) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px;
            padding: 8px 6px;
            box-sizing: border-box;
            overflow: hidden;
        }

        .asset-popup-header {
            display: flex; align-items: center; justify-content: space-between;
            margin-bottom: 3px; padding: 6px 6px 2px 8px; flex-shrink: 0;
        }

        .asset-popup-title { color: #94a3b8 !important; font-size: 20px !important; font-weight: 800 !important; }

        .asset-popup-close-btn {
            min-width: 34px !important; width: 34px !important; height: 34px !important;
            border-radius: 8px !important; background-color: #1e293b !important;
            color: white !important; font-size: 16px !important; padding: 0 !important;
        }

        .asset-popup-body {
            flex: 1; min-height: 0; border-radius: 10px;
            background: rgba(30, 41, 59, 0.45);
            border: 1px solid rgba(148, 163, 184, 0.12);
            display: flex; align-items: stretch; justify-content: flex-start; overflow: hidden;
        }

        .asset-tab-col {
            display: flex; flex-direction: column;
            justify-content: flex-start; align-items: center;
            gap: 10px; padding-top: 8px; flex-shrink: 0; width: 68px;
        }

        .asset-tab-btn2 {
            width: 52px !important; min-width: 52px !important;
            height: 46px !important; border-radius: 10px !important;
            font-size: 13px !important; font-weight: 700 !important;
            justify-content: center !important; padding: 0 !important;
        }

        .asset-tab-btn2-active  { background-color: #2f4b78 !important; color: #f8fafc !important; }
        .asset-tab-btn2-default { background-color: #1b2c47 !important; color: #d1d5db !important; }

        .asset-tab-content {
            flex: 1;
            min-height: 0;
            padding-top: 8px;
            padding-bottom: 8px;
            overflow-y: auto;
            padding-right: 5px;
            scrollbar-width: thin;
            scrollbar-color: #4b6387 #162133;
        }
        .asset-tab-content::-webkit-scrollbar {
            width: 10px;
        }

        .asset-tab-content::-webkit-scrollbar-track {
            background: #162133;
            border-radius: 999px;
        }

        .asset-tab-content::-webkit-scrollbar-thumb {
            background: #4b6387;
            border-radius: 999px;
            border: 2px solid #162133;
        }

        .asset-tab-content::-webkit-scrollbar-thumb:hover {
            background: #5f7aa3;
        }

        .asset-form-card {
            background: rgba(30, 41, 59, 0.55);
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 14px;
            padding: 4px 20px;
            min-height: 100%;
            display: flex; flex-direction: column;
            justify-content: flex-start; gap: 2px;
        }

        .asset-form-title { color: #e5e7eb !important; font-size: 15px !important; font-weight: 800 !important; margin-bottom: 4px; }

        .asset-form-row {
            display: grid; grid-template-columns: 130px 1fr;
            align-items: center; gap: 10px; min-height: 55px;
        }

        .asset-form-label {
            color: #d1d5db !important; font-size: 14px !important;
            font-weight: 700 !important; line-height: 1;
            display: flex; align-items: center; height: 100%;
        }

        .asset-form-action-row { display: flex; gap: 10px; margin-top: auto; }

        .asset-save-btn {
            flex: 1; height: 38px !important; border-radius: 8px !important;
            font-size: 14px !important; font-weight: 700 !important;
            background-color: #f59e0b !important; color: white !important;
        }

        .asset-cancel-btn {
            flex: 1; height: 38px !important; border-radius: 8px !important;
            font-size: 14px !important; font-weight: 700 !important;
            background-color: #f59e0b !important; color: white !important;
        }

        .asset-form-card input {
            color: white !important;
            -webkit-text-fill-color: white !important;
            text-align: right !important;
        }

        .asset-form-card .v-input {
            margin-top: 0 !important; padding-top: 0 !important;
            display: flex !important; align-items: center !important;
        }

        .asset-form-card .v-input__control { min-height: 44px !important; }

        .asset-form-card .v-input__slot,
        .asset-form-card .v-text-field > .v-input__control > .v-input__slot {
            min-height: 44px !important; display: flex !important;
            align-items: center !important; padding: 0 10px !important;
        }

        .v-btn.back-btn {
            min-width: 72px !important;
            height: 32px !important;
            padding: 0 12px !important;
        }

        .v-btn.back-btn .v-btn__content {
            font-size: 13px !important;
            font-weight: 700 !important;
            letter-spacing: 0px !important;
        }
        
        .current-time-card-inline {
            margin-top: auto;
            background-color: rgba(15, 23, 38, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.45) !important;
            border-radius: 13px;
            padding: 9px 10px;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            box-sizing: border-box;
            flex-wrap: nowrap;
        }
        
        .current-time-label-inline {
            color: #94a3b8 !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            white-space: nowrap;
            flex: 0 0 auto;
            margin: 0 !important;
        }
        
        .current-time-value-inline {
            color: white !important;
            font-size: 18px !important;
            font-weight: 800 !important;
            margin-left: auto;
            text-align: right;
            white-space: nowrap;
            flex: 0 0 auto;
            line-height: 1.2;
            letter-spacing: 0.2px;
        }
        
        .current-time-card {
            margin-top: auto;
            background-color: rgba(15, 23, 38, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.45) !important;
            border-radius: 13px;
            padding: 10px 12px;
            display: flex;
            flex-direction: column;
            gap: 6px;
            box-sizing: border-box;
        }

        .current-time-label {
            color: #94a3b8 !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            line-height: 1;
        }

        .current-time-value {
            color: #f8fafc !important;
            font-size: 18px !important;
            font-weight: 800 !important;
            line-height: 1.2;
            letter-spacing: 0.2px;
        }
        
        .top-user-row {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .home-btn {
            min-width: 60px !important;
            height: 32px !important;
            background-color: #0f172a !important;
            color: white !important;
            border-radius: 10px !important;
            font-size: 13px !important;
            font-weight: 700 !important;
            padding: 0 8px !important;
        }

        .back-nav-btn {
            min-width: 32px !important;
            width: 32px !important;
            height: 32px !important;
            background-color: #0f172a !important;
            color: white !important;
            border-radius: 10px !important;
            font-size: 18px !important;
            font-weight: 700 !important;
            padding: 0 !important;
        }

        .v-btn.user-role-tab {
            min-width: 80px !important;
            height: 32px !important;
            border-radius: 10px !important;
            font-size: 15px !important;
            font-weight: 700 !important;
            padding: 0 12px !important;
            background-color: #0f172a !important;
            color: white !important;
            border: 2px solid #f59e0b !important;
        }

        .asset-tab-btn {
            flex: 1;
            height: 32px !important;
            border-radius: 10px !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            background-color: #203250 !important;
            color: white !important;
            padding: 0 10px !important;
        }
        
        .mission-mode-card-inline {
            background-color: rgba(15, 23, 38, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.45) !important;
            border-radius: 13px;
            padding: 6px 8px;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            box-sizing: border-box;
            flex-wrap: nowrap;
        }

        .mode-title-inline {
            color: #94a3b8 !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            white-space: nowrap;
            flex: 0 0 auto;
            margin: 0 !important;
        }

        .mode-btn-row-inline {
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: flex-end;
            gap: 6px;
            flex: 1 1 auto;
            min-width: 0;
            flex-wrap: nowrap;
        }

        .mode-btn {
            flex: 1 1 0;
            min-width: 0 !important;
            height: 30px !important;
            border-radius: 9px !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            padding: 0 10px !important;
            color: white !important;
            white-space: nowrap;
        }

        .mode-btn .v-btn__content {
            color: white !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            white-space: nowrap;
        }

        .mode-btn-active {
            background-color: #e67e22 !important;
            color: white !important;
        }

        .mode-btn-default {
            background-color: #0f1b33 !important;
            color: white !important;
        }

        .mode-btn-active .v-btn__content,
        .mode-btn-default .v-btn__content {
            color: white !important;
        }
        
        
        
        .ltwr-scroll-area::-webkit-scrollbar {
            width: 10px;
        }

        .ltwr-scroll-area::-webkit-scrollbar-track {
            background: rgba(30, 41, 59, 0.95);
            border-radius: 999px;
        }

        .ltwr-scroll-area::-webkit-scrollbar-thumb {
            background: rgba(148, 163, 184, 0.35);
            border-radius: 999px;
            border: 2px solid rgba(30, 41, 59, 0.95);
        }

        .ltwr-scroll-area::-webkit-scrollbar-thumb:hover {
            background: rgba(203, 213, 225, 0.55);
        }

        @supports not selector(::-webkit-scrollbar) {
            .ltwr-scroll-area {
                scrollbar-width: thin;
                scrollbar-color: rgba(148, 163, 184, 0.35) rgba(30, 41, 59, 0.95);
            }
        }
        .right-top-summary-box,
        .right-bottom-ltwr-box {
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22);
        }

        .card-label {
            color: #94a3b8 !important;
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 8px;
        }
        
        
        .asset-popup-overlay-right {
            position: absolute;
            inset: 0;
            z-index: 30;
            display: flex;
            background: rgba(15, 23, 38, 0.72);
            border-radius: 12px;
        }

        .asset-popup-panel-right {
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            background: #0f1726;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.18);
            box-sizing: border-box;
        }
    """)

    with solara.Div(classes=["page-root"]):

        if mission_toast_count.value > 0:
            solara.HTML(
                tag="div",
                unsafe_innerHTML=f"✅&nbsp;&nbsp;{mission_toast_message.value}",
                attributes={"class": "mission-toast"},
            )

        # 1. 전체 쉘에 그리드와 높이 고정 (화면 밖 짤림 방지)
        with solara.Div(classes=["page-shell"], style={
            "display": "grid",
            "grid-template-columns": "380px minmax(0, 1fr) 390px",
            "grid-template-rows": "auto 1fr",
            "column-gap": "12px",
            "row-gap": "4px",
            "height": "100%",
            "min-height": "0",
            "padding": "0",
            "box-sizing": "border-box",
        }):

            # ── [좌측 컬럼] 상단 패널 + 차트 영역 ──────────────────
            with solara.Div(style={
                "grid-column": "1",
                "grid-row": "1",
                "display": "flex",
                "flex-direction": "column",
                "min-height": "0",
            }):
                # 상단 좌측 패널
                with solara.Div(classes=["top-left-panel"], style={"width": "100%", "height": "100%"}):
                    with solara.Div(classes=["top-user-row"]):
                        solara.Button("HOME", on_click=go_home, classes=["home-btn"])
                        solara.Button("←", on_click=go_back, classes=["back-nav-btn"])
                        solara.Button(user_label, classes=["user-role-tab"])
                        solara.Button(
                            "자산 현황",
                            on_click=lambda: set_show_asset_popup(not show_asset_popup),
                            classes=["asset-tab-btn"],
                        )

                    with solara.Div(classes=["mission-mode-card-inline"]):
                        solara.Text("임무 모드", classes=["mode-title-inline"])
                        with solara.Div(classes=["mode-btn-row-inline"]):
                            for b in ["균형", "정밀", "신속"]:
                                solara.Button(
                                    b,
                                    on_click=lambda x=b: set_active_button(x),
                                    classes=[
                                        "mode-btn",
                                        "mode-btn-active" if active_btn.value == b else "mode-btn-default",
                                    ],
                                )

                    with solara.Div(classes=["current-time-card-inline"]):
                        solara.Text("현재 시각", classes=["current-time-label-inline"])
                        solara.Text(current_time_text, classes=["current-time-value-inline"])


            # 센터 상단 (운용정보 테이블만) — col 2, row 1
            with solara.Div(style={
                "grid-column": "2",
                "grid-row": "1",
                "display": "flex",
                "flex-direction": "column",
                "min-height": "0",
            }):
                with solara.Div(classes=["top-right-panel"], style={"margin-bottom": "0px"}):
                    with solara.Div(classes=["unit-summary-header"]):
                        with solara.Div(classes=["col-unit"]):
                            solara.Text("", classes=["summary-head-text"])
                        with solara.Div(classes=["col-ugv"]):
                            solara.Text("운용 UGV 수", classes=["summary-head-text"])
                        with solara.Div(classes=["col-dest"]):
                            solara.Text("도착지 정보", classes=["summary-head-text"])
                        with solara.Div(classes=["col-time"]):
                            solara.Text("출발 예정 시각", classes=["summary-head-text"])
                        with solara.Div(classes=["col-time"]):
                            solara.Text("도착 예정 시각", classes=["summary-head-text"])

                    unit_key_map = {
                        "1제대": "user1",
                        "2제대": "user2",
                        "3제대": "user3",
                    }

                    display_rows = []
                    current_mode = selected_mission_mode.value
                    dest_map_for_mode = DEST_INFO_BY_MODE.get(current_mode, {})

                    for row in unit_info_rows:
                        new_row = dict(row)
                        key = unit_key_map.get(row["unit"])

                        if key:
                            # 운용 UGV 수
                            new_row["ugv"] = operating_ugv_plan.value.get(key)
                            # 출발 예정 시각
                            new_row["depart"] = departure_times.value.get(key)
                            # 도착지 정보 (모드별 매핑)
                            new_row["dest_info"] = dest_map_for_mode.get(row["unit"])
                        else:
                            new_row["ugv"] = None
                            new_row["depart"] = None
                            new_row["dest_info"] = None

                        display_rows.append(new_row)

                    for row in display_rows:
                        with solara.Div(classes=["unit-summary-row"]):
                            with solara.Div(classes=["col-unit"]):
                                solara.Text(row["unit"], classes=["summary-unit-text"])

                            ugv_color_map = {
                                "1제대": "rgba(249, 115, 22, 1)",
                                "2제대": "rgba(34, 211, 238, 1)",
                                "3제대": "rgba(244, 114, 182, 1)",
                            }

                            # 운용 UGV 수
                            with solara.Div(classes=["col-ugv"]):
                                color = ugv_color_map.get(row["unit"], "#e67e22")
                                ugv_value = "-" if row["ugv"] is None else row["ugv"]
                                solara.HTML(
                                    tag="div",
                                    unsafe_innerHTML=(
                                        "<div style='width:30px;height:24px;border-radius:7px;"
                                        f"background:{color};display:flex;align-items:center;justify-content:center;"
                                        "color:white;font-weight:800;font-size:14px;margin:0 auto;'>"
                                        f"{ugv_value}</div>"
                                    ),
                                )

                            # 도착지 정보
                            with solara.Div(classes=["col-dest"]):
                                dest_value = "-" if row.get("dest_info") is None else row["dest_info"]
                                solara.Text(dest_value, classes=["summary-value-text"])

                            # 출발 예정 시각
                            with solara.Div(classes=["col-time"]):
                                depart_value = "-" if row.get("depart") is None else row["depart"]
                                solara.Text(depart_value, classes=["summary-value-text"])

                            # 도착 예정 시각 (기존 로직 유지)
                            with solara.Div(classes=["col-time"]):
                                if (
                                    (active_btn.value == "균형" and row["unit"] == "3제대")
                                    or
                                    (active_btn.value == "정밀" and row["unit"] == "1제대")
                                ):
                                    solara.Text(
                                        row["arrive"],
                                        style={
                                            "color": "#ef4444",
                                            "font-size": "13px",
                                            "font-weight": "600",
                                            "white-space": "nowrap",
                                            "text-align": "center",
                                            "width": "100%",
                                        },
                                    )
                                else:
                                    solara.Text(row["arrive"], classes=["summary-value-text"])

            # 센터 맵 — col 1~2 전체, row 2
            with solara.Div(style={
                "grid-column": "1 / 3",
                "grid-row": "2",
                "display": "flex",
                "flex-direction": "column",
                "min-height": "0",
            }):
                with solara.Div(classes=["center-map-area"], style={
                    "flex": "1",
                    "display": "flex",
                    "flex-direction": "column",
                    "min-height": "0",
                }):
                    with solara.Div(classes=["center-map-inner"], style={
                        "flex": "1",
                        "display": "flex",
                        "flex-direction": "column",
                    }):
                        GridView(current_user=current_user)

            # ── [우측 컬럼] 큰 남색 박스 안에 상/하 2분할 ────────────────────
            with solara.Div(classes=["right-sidebar-area"], style={
                "grid-column": "3",
                "grid-row": "1 / 3",
                "min-height": "0",
                "min-width": "0",
            }):
                with solara.Div(classes=["right-sidebar-inner"], style={
                    "width": "100%",
                    "height": "100%",
                    "display": "flex",
                    "flex-direction": "column",
                    "gap": "5px",
                    "min-height": "0",
                }):

                    # [위] 임무 요약 박스 + 자산현황 팝업 영역
                    with solara.Div(classes=["right-top-panel"], style={
                        "flex": "1",
                        "min-height": "0",
                        "background": "rgba(15, 23, 42, 0.55)",
                        "border": "1px solid rgba(148, 163, 184, 0.12)",
                        "border-radius": "12px",
                        "padding": "8px",
                        "box-sizing": "border-box",
                        "display": "flex",
                        "flex-direction": "column",
                        "position": "relative",
                    }):
                        solara.Text(
                            "임무 요약",
                            classes=["card-label"],
                            style={
                                "font-size": "15px",
                                "margin-bottom": "5px",
                                "margin-left": "5px",
                            },
                        )

                        # 현재 임무 모드에 따른 KPI 값 가져오기
                        kpi_data = MISSION_KPI_DATA.get(active_btn.value) if active_btn.value else None

                        def kpi_row(label: str, value_text: str, unit_text: str, is_last: bool = False):
                            with solara.Div(style={
                                "display": "flex",
                                "align-items": "baseline",
                                "justify-content": "space-between",
                                "padding": "4px 0 6px 0",
                                "margin-bottom": "8px" if not is_last else "0px",
                                "border-bottom": "none" if is_last else "1px solid rgba(71, 85, 105, 0.25)",
                            }):
                                # 왼쪽 라벨
                                solara.Text(label, style={
                                    "font-size": "16px",
                                    "font-weight": "400",
                                    "color": "#abb1b9",
                                })

                                # 오른쪽 숫자 + 단위 묶음
                                with solara.Div(style={
                                    "display": "flex",
                                    "align-items": "baseline",
                                    "gap": "2px",
                                }):
                                    solara.Text(value_text, style={
                                        "font-size": "20px",
                                        "font-weight": "700",
                                        "color": "#e5e7eb",
                                        "text-align": "right",
                                    })
                                    solara.Text(unit_text, style={
                                        "font-size": "18px",
                                        "font-weight": "600",
                                        "color": "#475569",
                                    })

                        # 내부 요약 박스
                        with solara.Div(classes=["summary-inner-box"], style={
                            "flex": "1",
                            "min-height": "0",
                            "background": "rgba(30, 41, 59, 0.38)",
                            "border": "1px solid rgba(71, 85, 105, 0.28)",
                            "border-radius": "9px",
                            "padding": "10px 12px",
                            "box-sizing": "border-box",
                            "display": "flex",
                            "flex-direction": "column",
                            "justify-content": "flex-start",
                        }):
                            # 1. 임무 성공률
                            kpi_row("임무 성공률", f"{kpi_data['mission_success']:.1f}" if kpi_data else "-", "%" if kpi_data else "")
                            # 2. 최저 성공률
                            kpi_row("최저 성공률", f"{kpi_data['worst_success']:.1f}" if kpi_data else "-", "%" if kpi_data else "")
                            # 3. 도착 UGV 수
                            kpi_row("도착 UGV 수", f"{kpi_data['arrived_ugv']:.1f}" if kpi_data else "-", "대" if kpi_data else "")
                            # 4. SOS 요청 건수
                            kpi_row("SOS 요청 건수", f"{kpi_data['sos_count']:.1f}" if kpi_data else "-", "건" if kpi_data else "")
                            # 5. 건당 대기열
                            kpi_row("건당 대기열", f"{kpi_data['per_sos_queue']:.1f}" if kpi_data else "-", "분" if kpi_data else "")
                            # 6. 통제관 가동률
                            kpi_row("통제관 가동률", f"{kpi_data['controller_util']:.1f}" if kpi_data else "-", "%" if kpi_data else "", is_last=True)

                        # ✅ 자산 현황 팝업: 임무 요약 박스 크기에 맞춰 overlay
                        if show_asset_popup:
                            with solara.Div(classes=["asset-popup-overlay-right"]):
                                with solara.Div(classes=["asset-popup-panel-right"]):
                                    with solara.Div(classes=["asset-popup-header"]):
                                        solara.Text("기본자산", classes=["asset-popup-title"])
                                        solara.Button(
                                            "✕",
                                            on_click=lambda: set_show_asset_popup(False),
                                            classes=["asset-popup-close-btn"],
                                        )

                                    with solara.Div(classes=["asset-popup-body"]):
                                        with solara.Div(classes=["asset-tab-col"]):
                                            for tab_name, label in [
                                                ("부대 기본자산", "부대"),
                                                ("1제대 기본자산", "1제대"),
                                                ("2제대 기본자산", "2제대"),
                                                ("3제대 기본자산", "3제대"),
                                            ]:
                                                solara.Button(
                                                    label,
                                                    on_click=lambda t=tab_name: set_asset_tab(t),
                                                    classes=[
                                                        "asset-tab-btn2",
                                                        "asset-tab-btn2-active" if asset_tab == tab_name else "asset-tab-btn2-default",
                                                    ],
                                                )

                                        with solara.Div(classes=["asset-tab-content"]):
                                            if asset_tab == "부대 기본자산":
                                                BaseAssetEditor()
                                            elif asset_tab == "1제대 기본자산":
                                                UnitAssetEditor("user1", "1제대 기본자산")
                                            elif asset_tab == "2제대 기본자산":
                                                UnitAssetEditor("user2", "2제대 기본자산")
                                            elif asset_tab == "3제대 기본자산":
                                                UnitAssetEditor("user3", "3제대 기본자산")

                    # [아래] LTWR 박스
                    with solara.Div(classes=["right-bottom-panel"], style={
                        "flex": "1",
                        "min-height": "0",
                        "display": "flex",
                        "flex-direction": "column",
                        "background": "rgba(15, 23, 42, 0.55)",
                        "border": "1px solid rgba(148, 163, 184, 0.12)",
                        "border-radius": "12px",
                        "padding": "8px",
                        "box-sizing": "border-box",
                        "overflow": "hidden",
                    }):
                        solara.Text(
                            "지상 작전 기상 위험도 - LTWR",
                            classes=["card-label"],
                            style={"font-size": "15px", "margin-bottom": "5px", "margin-left": "5px"},
                        )

                        with solara.Div(
                            classes=["ltwr-scroll-area"],
                            style={
                                "flex": "1",
                                "min-height": "0",
                                "display": "flex",
                                "flex-direction": "column",
                                "gap": "12px",
                                "overflow-y": "auto",
                                "padding-right": "4px",
                            },
                        ):
                            MapCard(map_label_1, "map_01_Tactical_Weighted_Cost_1h.html", None)
                            MapCard(map_label_2, "map_01_Tactical_Weighted_Cost_2h.html", None)
                            MapCard(map_label_3, "map_01_Tactical_Weighted_Cost_3h.html", None)
                            
                            
# ──────────────────────────────────────────────────────────────
# [팀원 코드] 통제관 메인 페이지
# CommanderPage 레이아웃 그대로 사용, 통제관 전용 데이터로 변경
# 상단: 통제관 + 자기 제대 1줄 표시
# 좌측: 실행 / 종료 / 확인 완료 버튼
# 중앙: GridView (맵)
# 우측: LTWR 패널 기본 / 자산현황 클릭 시 자산 패널 오버레이
# ──────────────────────────────────────────────────────────────



@solara.component
def UserPage():
    current_user = logged_in_user.value
    my_unit_label = {
        "user1": "1제대",
        "user2": "2제대",
        "user3": "3제대",
    }.get(current_user, "제대")

    run_state, set_run_state = solara.use_state("")
    show_asset_popup, set_show_asset_popup = solara.use_state(False)
    asset_tab, set_asset_tab = solara.use_state("부대 기본자산")
    toast_count, set_toast_count = solara.use_state(0)

    fixed_mission_mode = selected_mission_mode.value if selected_mission_mode.value else "균형"

    MISSION_KPI_DATA = {
        "균형": {
            "mission_success": 98.0,
            "worst_success": 89.0,
            "arrived_ugv": 8.8,
            "sos_count": 18.9,
            "per_sos_queue": 10.0,
            "controller_util": 27.0,
        },
        "신속": {
            "mission_success": 98.0,
            "worst_success": 78.0,
            "arrived_ugv": 8.8,
            "sos_count": 15.9,
            "per_sos_queue": 9.0,
            "controller_util": 24.0,
        },
        "정밀": {
            "mission_success": 96.0,
            "worst_success": 78.0,
            "arrived_ugv": 8.6,
            "sos_count": 19.4,
            "per_sos_queue": 10.0,
            "controller_util": 27.0,
        },
    }

    ugv_color_map = {
        "1제대": "rgba(249, 115, 22, 1)",
        "2제대": "rgba(34, 211, 238, 1)",
        "3제대": "rgba(244, 114, 182, 1)",
    }

    def update_clock(cancel):
        while not cancel.is_set():
            time.sleep(1)
            tick.value += 1

    solara.use_thread(update_clock, dependencies=[])
    _ = tick.value

    elapsed_seconds = int(time.time() - app_start_ts)
    current_sim_time = sim_base_time + timedelta(seconds=elapsed_seconds)
    current_time_text = current_sim_time.strftime("%Y.%m.%d %H:%M:%S")

    current_arrival_times = ARRIVAL_TIMES_BY_MODE.get(fixed_mission_mode, {})
    current_dest_map = DEST_INFO_BY_MODE.get(fixed_mission_mode, {})

    my_ugv_value = operating_ugv_plan.value.get(current_user, "-")
    my_depart_value = departure_times.value.get(current_user, "-")
    my_arrive_value = current_arrival_times.get(current_user, "-")
    my_dest_value = current_dest_map.get(my_unit_label, "-")

    my_ugv_color = ugv_color_map.get(my_unit_label, "#e67e22")
    kpi_data = MISSION_KPI_DATA.get(fixed_mission_mode, MISSION_KPI_DATA["균형"])

    map_label_1 = "h+1"
    map_label_2 = "h+2"
    map_label_3 = "h+3"

    def go_back():
        workflow_step.set(0)

    def confirm_mission():
        try:
            set_toast_count(int(toast_count) + 1)
        except Exception:
            set_toast_count(1)

    solara.Style("""
        .status-item-box > div, .status-item-box .v-sheet,
        .sub-inner-card > div, .sub-inner-card .v-sheet,
        .right-sidebar-area > div, .right-sidebar-area .v-sheet,
        .v-application, .v-application--wrap, .v-main, .v-card {
            background-color: transparent !important;
            box-shadow: none !important;
            border: none !important;
        }

        html, body, #app, .v-application, .v-application--wrap,
        .solara-content-main, .solara-app, .v-main {
            background-color: #0b1426 !important;
            color: white !important;
            width: 100% !important;
            height: 100% !important;
            margin: 0 !important;
            padding: 0 !important;
        }

        .page-root {
            width: 100vw;
            height: 100vh;
            background: #0b1426;
            overflow: hidden;
            box-sizing: border-box;
            padding: 16px;
        }

        .page-shell {
            width: 100%;
            height: 100%;
            min-height: 0;
            display: grid;
            grid-template-columns: 380px minmax(0, 1fr) 390px;
            grid-template-rows: auto 1fr;
            column-gap: 12px;
            row-gap: 4px;
            box-sizing: border-box;
        }

        .page-shell > * {
            min-height: 0;
        }

        .top-left-panel {
            grid-column: 1;
            grid-row: 1;
            align-self: stretch;
            background-color: rgba(22, 34, 56, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.55) !important;
            border-radius: 16px;
            padding: 8px;
            display: flex;
            flex-direction: column;
            gap: 5px;
            box-sizing: border-box;
        }

        .top-right-panel {
            grid-column: 2;
            grid-row: 1;
            width: 100%;
            min-height: 0;
            height: 100%;
            justify-self: stretch;
            background-color: rgba(22, 34, 56, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.55) !important;
            border-radius: 16px;
            padding: 6px 18px;
            display: flex;
            flex-direction: column;
            justify-content: center;
            box-sizing: border-box;
            overflow: hidden;
        }

        .top-user-row {
            display: flex;
            align-items: center;
            gap: 8px;
        }

        .unit-summary-header, .unit-summary-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            width: 100%;
            gap: 8px;
            padding-left: 6px;
            padding-right: 8px;
            box-sizing: border-box;
        }

        .unit-summary-header {
            padding: 0 0 6px 0;
            border-bottom: 1px solid rgba(148, 163, 184, 0.20);
            margin-bottom: 4px;
        }

        .unit-summary-row {
            padding: 7px 0;
            border-bottom: none;
        }

        .col-unit {
            flex: 1.0;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: flex-start;
            text-align: left;
            padding-left: 20px;
        }

        .col-ugv {
            flex: 0.9;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }

        .col-time {
            flex: 1.35;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }

        .col-dest {
            flex: 1.6;
            min-width: 0;
            display: flex;
            align-items: center;
            justify-content: center;
            text-align: center;
        }

        .summary-head-text {
            color: #94a3b8 !important;
            font-size: 12px !important;
            font-weight: 800 !important;
            white-space: nowrap;
            letter-spacing: -0.1px;
            text-align: center;
            width: 100%;
        }

        .summary-unit-text {
            color: #d1d5db !important;
            font-size: 14px !important;
            font-weight: 800 !important;
            white-space: nowrap;
            text-align: left;
            width: 100%;
        }

        .summary-value-text {
            color: white !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            white-space: nowrap;
            text-align: center;
            width: 100%;
        }

        .center-map-area {
            grid-column: 1 / 3;
            grid-row: 2;
            min-height: 0;
            height: 100%;
            display: flex;
            flex-direction: column;
            align-self: stretch;
            width: 100%;
            background-color: rgba(15, 23, 38, 0.72) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px;
            padding: 12px;
            box-sizing: border-box;
            overflow: hidden;
        }

        .center-map-inner {
            flex: 1;
            min-height: 0;
            height: 100%;
            width: 100%;
            display: flex;
            flex-direction: column;
            overflow: hidden;
            border-radius: 10px;
            background: transparent !important;
        }

        .center-map-inner > div,
        .center-map-inner .v-sheet {
            flex: 1 1 auto;
            min-height: 0;
            height: 100%;
            background: transparent !important;
        }

        .center-map-inner iframe {
            width: 100%;
            height: 100%;
            border: none;
            background: transparent !important;
        }

        .right-sidebar-area {
            grid-column: 3;
            grid-row: 1 / 3;
            min-width: 0;
            min-height: 0;
            height: 100%;
            display: flex;
            flex-direction: column;
            background-color: rgba(11, 20, 38, 0.96) !important;
            border: 1px solid rgba(45, 58, 84, 0.8) !important;
            border-radius: 12px;
            padding: 5px 1px 5px 10px;
            box-sizing: border-box;
            overflow-y: auto;
            scrollbar-gutter: stable;
        }

        .right-sidebar-area::-webkit-scrollbar {
            width: 10px;
        }

        .right-sidebar-area::-webkit-scrollbar-track {
            background: rgba(30, 41, 59, 0.95);
            border-radius: 999px;
        }

        .right-sidebar-area::-webkit-scrollbar-thumb {
            background: rgba(148, 163, 184, 0.35);
            border-radius: 999px;
            border: 2px solid rgba(30, 41, 59, 0.95);
        }

        .right-sidebar-area::-webkit-scrollbar-thumb:hover {
            background: rgba(203, 213, 225, 0.55);
        }

        .right-top-panel,
        .right-bottom-panel {
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.22);
        }

        .card-label {
            color: #94a3b8 !important;
            font-size: 14px;
            font-weight: bold;
            margin-bottom: 8px;
        }

        .map-card-container {
            background-color: rgba(15, 23, 42, 0.96) !important;
            border: 1px solid rgba(148, 163, 184, 0.22) !important;
            border-radius: 12px;
            padding: 12px 12px 10px;
            margin-bottom: 14px;
            position: relative;
            overflow: hidden;
        }

        .map-frame-wrapper {
            width: 100%;
            height: 140px;
            border-radius: 8px;
            overflow: hidden;
            background: #000000;
        }

        .map-controls {
            position: absolute;
            right: 18px;
            top: 45px;
            display: flex;
            flex-direction: column;
            gap: 4px;
            z-index: 10;
        }

        .zoom-btn {
            min-width: 28px !important;
            height: 28px !important;
            background-color: rgba(30, 41, 59, 0.9) !important;
            color: white !important;
            border: 1px solid rgba(255,255,255,0.2) !important;
            border-radius: 4px !important;
            padding: 0 !important;
            font-size: 16px !important;
        }

        .mission-toast {
            position: fixed;
            bottom: 36px;
            left: 50%;
            background: rgba(30, 41, 59, 0.96);
            border: 1px solid rgba(255, 61, 154, 0.55);
            border-radius: 10px;
            padding: 12px 28px;
            color: white;
            font-size: 15px;
            font-weight: 600;
            z-index: 9999;
            box-shadow: 0 4px 24px rgba(255, 61, 154, 0.25);
            display: flex;
            align-items: center;
            gap: 10px;
            pointer-events: none;
            animation: toast-lifecycle 2.5s ease forwards;
        }

        @keyframes toast-lifecycle {
            0%   { opacity: 0; transform: translateX(-50%) translateY(12px); }
            12%  { opacity: 1; transform: translateX(-50%) translateY(0); }
            75%  { opacity: 1; transform: translateX(-50%) translateY(0); }
            100% { opacity: 0; transform: translateX(-50%) translateY(0); }
        }

        .asset-popup-header {
            display: flex;
            align-items: center;
            justify-content: space-between;
            margin-bottom: 3px;
            padding: 6px 6px 2px 8px;
            flex-shrink: 0;
        }

        .asset-popup-title {
            color: #94a3b8 !important;
            font-size: 20px !important;
            font-weight: 800 !important;
        }

        .asset-popup-close-btn {
            min-width: 34px !important;
            width: 34px !important;
            height: 34px !important;
            border-radius: 8px !important;
            background-color: #1e293b !important;
            color: white !important;
            font-size: 16px !important;
            padding: 0 !important;
        }

        .asset-popup-body {
            flex: 1;
            min-height: 0;
            border-radius: 10px;
            background: rgba(30, 41, 59, 0.45);
            border: 1px solid rgba(148, 163, 184, 0.12);
            display: flex;
            align-items: stretch;
            justify-content: flex-start;
            overflow: hidden;
        }

        .asset-tab-col {
            display: flex;
            flex-direction: column;
            justify-content: flex-start;
            align-items: center;
            gap: 10px;
            padding-top: 8px;
            flex-shrink: 0;
            width: 68px;
        }

        .asset-tab-btn2 {
            width: 52px !important;
            min-width: 52px !important;
            height: 46px !important;
            border-radius: 10px !important;
            font-size: 13px !important;
            font-weight: 700 !important;
            justify-content: center !important;
            padding: 0 !important;
        }

        .asset-tab-btn2-active  { background-color: #2f4b78 !important; color: #f8fafc !important; }
        .asset-tab-btn2-default { background-color: #1b2c47 !important; color: #d1d5db !important; }

        .asset-tab-content {
            flex: 1;
            min-height: 0;
            padding-top: 8px;
            padding-bottom: 8px;
            overflow-y: auto;
            padding-right: 5px;
            scrollbar-width: thin;
            scrollbar-color: #4b6387 #162133;
        }

        .current-time-card-inline {
            margin-top: auto;
            background-color: rgba(15, 23, 38, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.45) !important;
            border-radius: 13px;
            padding: 9px 10px;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            box-sizing: border-box;
            flex-wrap: nowrap;
        }

        .current-time-label-inline {
            color: #94a3b8 !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            white-space: nowrap;
            flex: 0 0 auto;
            margin: 0 !important;
        }

        .current-time-value-inline {
            color: white !important;
            font-size: 18px !important;
            font-weight: 800 !important;
            margin-left: auto;
            text-align: right;
            white-space: nowrap;
            flex: 0 0 auto;
            line-height: 1.2;
            letter-spacing: 0.2px;
        }

        .home-btn {
            min-width: 60px !important;
            height: 32px !important;
            background-color: #0f172a !important;
            color: white !important;
            border-radius: 10px !important;
            font-size: 13px !important;
            font-weight: 700 !important;
            padding: 0 8px !important;
        }

        .back-nav-btn {
            min-width: 32px !important;
            width: 32px !important;
            height: 32px !important;
            background-color: #0f172a !important;
            color: white !important;
            border-radius: 10px !important;
            font-size: 18px !important;
            font-weight: 700 !important;
            padding: 0 !important;
        }

        .v-btn.user-role-tab {
            min-width: 80px !important;
            height: 32px !important;
            border-radius: 10px !important;
            font-size: 15px !important;
            font-weight: 700 !important;
            padding: 0 12px !important;
            background-color: #0f172a !important;
            color: white !important;
            border: 2px solid #f59e0b !important;
        }

        .asset-tab-btn {
            flex: 1;
            height: 32px !important;
            border-radius: 10px !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            background-color: #203250 !important;
            color: white !important;
            padding: 0 10px !important;
        }

        .mission-mode-card-inline {
            background-color: rgba(15, 23, 38, 0.82) !important;
            border: 1px solid rgba(45, 58, 84, 0.45) !important;
            border-radius: 13px;
            padding: 6px 8px;
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: space-between;
            gap: 10px;
            box-sizing: border-box;
            flex-wrap: nowrap;
        }

        .mode-title-inline {
            color: #94a3b8 !important;
            font-size: 12px !important;
            font-weight: 700 !important;
            white-space: nowrap;
            flex: 0 0 auto;
            margin: 0 !important;
        }

        .mode-btn-row-inline {
            display: flex;
            flex-direction: row;
            align-items: center;
            justify-content: flex-end;
            gap: 6px;
            flex: 1 1 auto;
            min-width: 0;
            flex-wrap: nowrap;
        }

        .single-mode-btn {
            min-width: 88px !important;
            height: 30px !important;
            border-radius: 9px !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            padding: 0 14px !important;
            background-color: #e67e22 !important;
            color: white !important;
        }

        .asset-popup-overlay-right {
            position: absolute;
            inset: 0;
            z-index: 30;
            display: flex;
            background: rgba(15, 23, 38, 0.72);
            border-radius: 12px;
        }

        .asset-popup-panel-right {
            width: 100%;
            height: 100%;
            display: flex;
            flex-direction: column;
            background: #0f1726;
            border-radius: 12px;
            border: 1px solid rgba(148, 163, 184, 0.18);
            box-sizing: border-box;
        }

        .ltwr-scroll-area::-webkit-scrollbar {
            width: 10px;
        }

        .ltwr-scroll-area::-webkit-scrollbar-track {
            background: rgba(30, 41, 59, 0.95);
            border-radius: 999px;
        }

        .ltwr-scroll-area::-webkit-scrollbar-thumb {
            background: rgba(148, 163, 184, 0.35);
            border-radius: 999px;
            border: 2px solid rgba(30, 41, 59, 0.95);
        }

        .ltwr-scroll-area::-webkit-scrollbar-thumb:hover {
            background: rgba(203, 213, 225, 0.55);
        }
        .asset-form-label {
            color: #d1d5db !important;
            font-size: 14px !important;
            font-weight: 700 !important;
            line-height: 1 !important;
            white-space: nowrap;
            flex: 0 0 auto;
        }
        .asset-form-row input {
            color: #f8fafc !important;
        }

        .asset-form-row input::placeholder {
            color: #94a3b8 !important;
        }
        .asset-form-row {
            display: flex;
            align-items: center;
            justify-content: space-between;
            gap: 12px;
            min-height: 44px;
            width: 100%;
        }
        .asset-form-card .v-input {
            margin-top: 0 !important;
            padding-top: 0 !important;
            display: flex !important;
            align-items: center !important;
            justify-content: flex-end !important;
            flex: 0 0 120px !important;
            min-width: 120px !important;
        }
        .asset-form-card {
            background: rgba(30, 41, 59, 0.55);
            border: 1px solid rgba(148, 163, 184, 0.12);
            border-radius: 14px;
            padding: 4px 20px;
            min-height: 100%;
            display: flex; flex-direction: column;
            justify-content: flex-start; gap: 1px;
        }

        .asset-form-card .v-input__slot,
        .asset-form-card .v-text-field .v-input__control .v-input__slot {
            min-height: 36px !important;
            display: flex !important;
            align-items: center !important;
            justify-content: flex-end !important;
            padding: 0 10px !important;
        }

        .asset-form-card input {
            color: white !important;
            -webkit-text-fill-color: white !important;
            text-align: right !important;
        }
    """)
    
    
    current_user = logged_in_user.value
    user_label = "통제관"

    toast_initialized, set_toast_initialized = solara.use_state(False)

    if not toast_initialized:
        mission_toast_count.value = 0
        mission_toast_message.value = ""
        set_toast_initialized(True)

    with solara.Div(classes=["page-root"]):
        if mission_toast_count.value > 0:
            solara.HTML(
                tag="div",
                unsafe_innerHTML=f"✅&nbsp;&nbsp;{mission_toast_message.value}",
                attributes={"class": "mission-toast"},
            )

        with solara.Div(classes=["page-shell"], style={
            "display": "grid",
            "grid-template-columns": "380px minmax(0, 1fr) 390px",
            "grid-template-rows": "auto 1fr",
            "column-gap": "12px",
            "row-gap": "4px",
            "height": "100%",
            "min-height": "0",
            "padding": "0",
            "box-sizing": "border-box",
        }):
            # 좌측 상단
            with solara.Div(style={
                "grid-column": "1",
                "grid-row": "1",
                "display": "flex",
                "flex-direction": "column",
                "min-height": "0",
            }):
                with solara.Div(classes=["top-left-panel"], style={"width": "100%", "height": "100%"}):
                    with solara.Div(classes=["top-user-row"]):
                        solara.Button("HOME", on_click=go_home, classes=["home-btn"])
                        solara.Button("←", on_click=go_back, classes=["back-nav-btn"])
                        solara.Button(my_unit_label, classes=["user-role-tab"])
                        solara.Button(
                            "자산 현황",
                            on_click=lambda: set_show_asset_popup(not show_asset_popup),
                            classes=["asset-tab-btn"],
                        )

                    with solara.Div(classes=["mission-mode-card-inline"]):
                        solara.Text("임무 모드", classes=["mode-title-inline"])
                        with solara.Div(classes=["mode-btn-row-inline"]):
                            solara.Button(fixed_mission_mode, classes=["single-mode-btn"])

                    with solara.Div(classes=["current-time-card-inline"]):
                        solara.Text("현재 시각", classes=["current-time-label-inline"])
                        solara.Text(current_time_text, classes=["current-time-value-inline"])

            # 센터 상단
            with solara.Div(style={
                "grid-column": "2",
                "grid-row": "1",
                "display": "flex",
                "flex-direction": "column",
                "min-height": "0",
            }):
                with solara.Div(classes=["top-right-panel"], style={"margin-bottom": "0px"}):
                    with solara.Div(classes=["unit-summary-header"]):
                        with solara.Div(classes=["col-unit"]):
                            solara.Text("", classes=["summary-head-text"])
                        with solara.Div(classes=["col-ugv"]):
                            solara.Text("운용 UGV 수", classes=["summary-head-text"])
                        with solara.Div(classes=["col-dest"]):
                            solara.Text("도착지 정보", classes=["summary-head-text"])
                        with solara.Div(classes=["col-time"]):
                            solara.Text("출발 예정 시각", classes=["summary-head-text"])
                        with solara.Div(classes=["col-time"]):
                            solara.Text("도착 예정 시각", classes=["summary-head-text"])

                    with solara.Div(classes=["unit-summary-row"]):
                        with solara.Div(classes=["col-unit"]):
                            solara.Text(my_unit_label, classes=["summary-unit-text"])

                        with solara.Div(classes=["col-ugv"]):
                            solara.HTML(
                                tag="div",
                                unsafe_innerHTML=(
                                    "<div style='width:32px;height:26px;border-radius:7px;"
                                    f"background:{my_ugv_color};display:flex;align-items:center;justify-content:center;"
                                    "color:white;font-weight:800;font-size:15px;margin:0 auto;'>"
                                    f"{my_ugv_value}</div>"
                                ),
                            )

                        with solara.Div(classes=["col-dest"]):
                            solara.Text(str(my_dest_value), classes=["summary-value-text"])

                        with solara.Div(classes=["col-time"]):
                            solara.Text(str(my_depart_value), classes=["summary-value-text"])

                        with solara.Div(classes=["col-time"]):
                            solara.Text(str(my_arrive_value), classes=["summary-value-text"])

            # 센터 맵 (통제관일 때만 하단에 임무 확인 버튼)
            with solara.Div(style={
                "grid-column": "1 / 3",
                "grid-row": "2",
                "display": "flex",
                "flex-direction": "column",
                "min-height": "0",
            }):
                with solara.Div(classes=["center-map-area"], style={
                    "flex": "1",
                    "display": "flex",
                    "flex-direction": "column",
                    "min-height": "0",
                }):
                    with solara.Div(classes=["center-map-inner"], style={
                        "flex": "1",
                        "display": "flex",
                        "flex-direction": "column",
                    }):
                        GridView(current_user=current_user)

                    # 통제관( user1/2/3 )일 때만 센터 맵 하단에 표시
                    # if current_user in ["user1", "user2", "user3"]:
                    #     with solara.Div(style={
                    #         "margin-top": "8px",
                    #         "display": "flex",
                    #         "justify-content": "flex-end",
                    #     }):
                    #         solara.Button(
                    #             "임무 확인",
                    #             on_click=confirm_mission,
                    #             style={
                    #                 "background": "#ff2f7f",
                    #                 "color": "white",
                    #                 "font-weight": "700",
                    #                 "border-radius": "10px",
                    #                 "height": "38px",
                    #                 "padding": "0 18px",
                    #             },
                    #         )

            # 우측 패널
            with solara.Div(classes=["right-sidebar-area"], style={
                "grid-column": "3",
                "grid-row": "1 / 3",
                "min-height": "0",
                "min-width": "0",
            }):
                with solara.Div(classes=["right-sidebar-inner"], style={
                    "width": "100%",
                    "height": "100%",
                    "display": "flex",
                    "flex-direction": "column",
                    "gap": "5px",
                    "min-height": "0",
                    "min-width": "0",
                }):
                    # 우측 상단 임무 요약
                    with solara.Div(classes=["right-top-panel"], style={
                        "flex": "1",
                        "min-height": "0",
                        "background": "rgba(15, 23, 42, 0.55)",
                        "border": "1px solid rgba(148, 163, 184, 0.12)",
                        "border-radius": "12px",
                        "padding": "8px",
                        "box-sizing": "border-box",
                        "display": "flex",
                        "flex-direction": "column",
                        "position": "relative",
                    }):
                        solara.Text(
                            "임무 요약",
                            classes=["card-label"],
                            style={
                                "font-size": "15px",
                                "margin-bottom": "5px",
                                "margin-left": "5px",
                            },
                        )

                        def kpi_row(label: str, value_text: str, unit_text: str, is_last: bool = False):
                            with solara.Div(style={
                                "display": "flex",
                                "align-items": "baseline",
                                "justify-content": "space-between",
                                "padding": "0 0 8px 0",
                                "margin-bottom": "7px" if not is_last else "0px",
                                "border-bottom": "none" if is_last else "1px solid rgba(71, 85, 105, 0.25)",
                            }):
                                solara.Text(label, style={
                                    "font-size": "16px",
                                    "font-weight": "400",
                                    "color": "#abb1b9",
                                })

                                with solara.Div(style={
                                    "display": "flex",
                                    "align-items": "baseline",
                                    "gap": "2px",
                                }):
                                    solara.Text(value_text, style={
                                        "font-size": "20px",
                                        "font-weight": "700",
                                        "color": "#e5e7eb",
                                        "text-align": "right",
                                    })
                                    solara.Text(unit_text, style={
                                        "font-size": "18px",
                                        "font-weight": "600",
                                        "color": "#475569",
                                    })

                        with solara.Div(style={
                            "flex": "1",
                            "min-height": "0",
                            "background": "rgba(30, 41, 59, 0.38)",
                            "border": "1px solid rgba(71, 85, 105, 0.28)",
                            "border-radius": "9px",
                            "padding": "10px 12px",
                            "box-sizing": "border-box",
                            "display": "flex",
                            "flex-direction": "column",
                            "justify-content": "flex-start",
                        }):
                            kpi_row("임무 성공률", f"{kpi_data['mission_success']:.1f}", "%")
                            kpi_row("최저 성공률", f"{kpi_data['worst_success']:.1f}", "%")
                            kpi_row("도착 UGV 수", f"{kpi_data['arrived_ugv']:.1f}", "대")
                            kpi_row("SOS 요청 건수", f"{kpi_data['sos_count']:.1f}", "건")
                            kpi_row("건당 대기열", f"{kpi_data['per_sos_queue']:.1f}", "분")
                            kpi_row("통제관 가동률", f"{kpi_data['controller_util']:.1f}", "%", is_last=True)

                        if show_asset_popup:
                            with solara.Div(classes=["asset-popup-overlay-right"]):
                                with solara.Div(classes=["asset-popup-panel-right"]):
                                    with solara.Div(classes=["asset-popup-header"]):
                                        solara.Text("기본자산", classes=["asset-popup-title"])
                                        solara.Button(
                                            "✕",
                                            on_click=lambda: set_show_asset_popup(False),
                                            classes=["asset-popup-close-btn"],
                                        )

                                    with solara.Div(classes=["asset-popup-body"]):
                                        with solara.Div(classes=["asset-tab-col"]):
                                            for tab_name, label in [
                                                ("부대 기본자산", "부대"),
                                                (f"{my_unit_label} 기본자산", my_unit_label),
                                            ]:
                                                solara.Button(
                                                    label,
                                                    on_click=lambda t=tab_name: set_asset_tab(t),
                                                    classes=[
                                                        "asset-tab-btn2",
                                                        "asset-tab-btn2-active" if asset_tab == tab_name else "asset-tab-btn2-default",
                                                    ],
                                                )

                                        with solara.Div(
                                            classes=["asset-tab-content"],
                                            style={
                                                "color": "#ffffff",
                                                "width": "100%",
                                                "min-width": "0",
                                                "display": "flex",
                                                "flex-direction": "column",
                                            }
                                        ):
                                            if asset_tab == "부대 기본자산":
                                                BaseAssetEditor()
                                            else:
                                                UnitAssetEditor(current_user, f"{my_unit_label} 기본자산")

                    # 우측 하단 LTWR
                    with solara.Div(classes=["right-bottom-panel"], style={
                        "flex": "1",
                        "min-height": "0",
                        "display": "flex",
                        "flex-direction": "column",
                        "background": "rgba(15, 23, 42, 0.55)",
                        "border": "1px solid rgba(148, 163, 184, 0.12)",
                        "border-radius": "12px",
                        "padding": "8px",
                        "box-sizing": "border-box",
                        "overflow": "hidden",
                    }):
                        solara.Text(
                            "지상 작전 기상 위험도 - LTWR",
                            classes=["card-label"],
                            style={"font-size": "15px", "margin-bottom": "5px", "margin-left": "5px"},
                        )

                        with solara.Div(
                            classes=["ltwr-scroll-area"],
                            style={
                                "flex": "1",
                                "min-height": "0",
                                "display": "flex",
                                "flex-direction": "column",
                                "gap": "12px",
                                "overflow-y": "auto",
                                "padding-right": "4px",
                            },
                        ):
                            MapCard(map_label_1, "map_01_Tactical_Weighted_Cost_1h.html", None)
                            MapCard(map_label_2, "map_01_Tactical_Weighted_Cost_2h.html", None)
                            MapCard(map_label_3, "map_01_Tactical_Weighted_Cost_3h.html", None)

        # 통제관용 센터 버튼으로 옮겼으니 여기 고정 버튼은 제거
        # with solara.Div(...): 임무 확인 버튼 부분은 삭제됨




@solara.component
def MarkerMessenger(markers_json: str):
    def effect():
        solara.HTML(
            tag="script",
            unsafe_innerHTML=f"""
            (function() {{
                const send = () => {{
                    const frame = document.getElementById('commander-map-frame');
                    if (!frame || !frame.contentWindow) return;

                    frame.contentWindow.postMessage({{
                        type: 'setMarkers',
                        markers: {markers_json}
                    }}, '*');
                }};

                setTimeout(send, 150);
                setTimeout(send, 400);
            }})();
            """
        )
    solara.use_effect(effect, [markers_json])

# ──────────────────────────────────────────────────────────────
# [팀원 코드] 지휘관 입력 페이지 (좌표 + 정찰시간 입력)
# workflow_step=0 → 제출 시 workflow_step=1 (LoadingPage로 이동)
# ──────────────────────────────────────────────────────────────
@solara.component
def CommanderInputPage():
    form = commander_input_state.value

    unit1_lat = form["user1"]["lat"]
    unit1_lng = form["user1"]["lng"]
    unit1_recon = form["user1"]["recon"]

    unit2_lat = form["user2"]["lat"]
    unit2_lng = form["user2"]["lng"]
    unit2_recon = form["user2"]["recon"]

    unit3_lat = form["user3"]["lat"]
    unit3_lng = form["user3"]["lng"]
    unit3_recon = form["user3"]["recon"]
    
    def set_field(user_key, field, value):
        current = commander_input_state.value
        commander_input_state.set({
            **current,
            user_key: {
                **current[user_key],
                field: value,
            }
        })

    def handle_submit():
        form = commander_input_state.value

        destination_data.set({
            "user1": {"lat": form["user1"]["lat"], "lng": form["user1"]["lng"]},
            "user2": {"lat": form["user2"]["lat"], "lng": form["user2"]["lng"]},
            "user3": {"lat": form["user3"]["lat"], "lng": form["user3"]["lng"]},
        })

        mission_settings.set({
            **mission_settings.value,
            "recon_times": {
                "user1": form["user1"]["recon"],
                "user2": form["user2"]["recon"],
                "user3": form["user3"]["recon"],
            },
        })

        updated = dict(asset_data.value)
        for key in ["user1", "user2", "user3"]:
            updated[key] = {
                **updated[key],
                "target_lat": str(form[key]["lat"]),
                "target_lon": str(form[key]["lng"]),
            }
        asset_data.set(updated)

        mission_note.set("지휘관 입력 완료")
        workflow_step.set(1)  # -> LoadingPage

    solara.Style("""
        html, body, #app, .v-application, .v-application__wrap,
        .solara-content-main, .solara-app, .v-main {
            margin: 0 !important; padding: 0 !important;
            width: 100% !important; height: 100% !important;
            overflow: hidden !important; background: #0b1426 !important;
        }

        .commander-input-root { width: 100vw; height: 100dvh; overflow: hidden; background: #0b1426; box-sizing: border-box; padding: 16px; }

        .commander-input-shell {
            width: 100%; height: 100%;
            display: grid; grid-template-columns: 1.95fr 1.05fr;
            gap: 16px; min-height: 0;
        }

        .commander-map-panel {
            background: linear-gradient(180deg, rgba(9,20,42,0.96), rgba(8,18,38,0.98));
            border: 1px solid rgba(45,58,84,0.7); border-radius: 18px; padding: 20px;
            display: flex; flex-direction: column; min-height: 0; height: 100%;
            box-sizing: border-box; overflow: hidden;
        }

        .commander-map-header { color: white; font-size: 24px; font-weight: 800; margin-bottom: 8px; }
        .commander-map-sub    { color: #94a3b8; font-size: 14px; margin-bottom: 16px; line-height: 1.45; }

        .commander-map-box {
            flex: 1; min-height: 0; border-radius: 16px;
            border: 1px solid rgba(45,58,84,0.55);
            overflow: hidden; position: relative;
        }
        .commander-map-box iframe {
            width: 100%; height: 100%; border: none; display: block;
        }

        .commander-map-title   { font-size: 22px; font-weight: 700; color: white; margin-bottom: 4px; }
        .commander-map-caption { font-size: 15px; color: #cbd5e1; line-height: 1.5; }

        .commander-side-panel {
            background: rgba(11, 18, 32, 0.96);
            border: 1px solid rgba(45, 58, 84, 0.85);
            border-radius: 18px;
            padding: 18px 16px;
            display: flex;
            flex-direction: column;
            gap: 12px;
            min-height: 0;
            height: 100%;
            box-sizing: border-box;
            overflow: hidden;
        }

        .commander-section-card {
            background: rgba(11,20,38,0.92); border: 1px solid rgba(45,58,84,0.65);
            border-radius: 14px; padding: 14px; flex: 1; min-height: 0;
            display: flex; flex-direction: column; justify-content: center;
            box-sizing: border-box; overflow: hidden;
        }

        .commander-section-title { color: white; font-size: 16px; font-weight: 700; margin-bottom: 10px; flex-shrink: 0; }

        .commander-input-group { display: flex; flex-direction: column; gap: 10px; flex: 1; justify-content: center; min-height: 0; }

        .commander-field-row { display: grid; grid-template-columns: 72px 1fr; align-items: center; gap: 10px; min-height: 0; }

        .commander-field-label-inline { color: #cbd5e1; font-size: 14px; font-weight: 600; text-align: left; white-space: nowrap; }

        .commander-submit-wrap { margin-top: 0; padding-top: 0; flex-shrink: 0; }

        .commander-side-panel .v-input              { margin-top: 0 !important; padding-top: 0 !important; }
        .commander-side-panel .v-input__control     { min-height: auto !important; }
        .commander-side-panel .v-text-field         { margin-top: 0 !important; }
        .commander-side-panel .v-label              { display: none !important; }
        .commander-side-panel .v-input__slot,
        .commander-side-panel .v-text-field > .v-input__control > .v-input__slot {
            background: rgba(23, 33, 52, 0.95) !important; border-radius: 10px !important;
            box-shadow: none !important; min-height: 46px !important; padding: 0 12px !important;
        }
        .commander-side-panel input { color: white !important; font-size: 15px !important; }
    """)
    
    marker_payload = []
    
    # ① 항상 표시할 출발지 마커 (고정)
    marker_payload.append({
        "id": "start",
        "lat": "54.48",
        "lng": "18.32",
        "label": "출발지",
        "color": "#e67e22",  # 주황색 등 눈에 띄는 색
    })
    
    # ② 나머지 도착지 마커 (사용자 입력 기반)
    marker_state = commander_marker_state.value

    for user_key, label, color in [
        ("user1", "도착지1", "#3b82f6"),
        ("user2", "도착지2", "#52c41a"),
        ("user3", "도착지3", "#a855f7"),
    ]:
        marker = marker_state.get(user_key)
        if marker and str(marker.get("lat", "")).strip() and str(marker.get("lng", "")).strip():
            marker_payload.append({
                "id": user_key,
                "lat": str(marker["lat"]).strip(),
                "lng": str(marker["lng"]).strip(),
                "label": label,
                "color": color,
            })

    #markers_json = json.dumps(marker_payload, ensure_ascii=False)
    
    def apply_marker(user_key):
        form = commander_input_state.value
        lat = str(form[user_key]["lat"]).strip()
        lng = str(form[user_key]["lng"]).strip()

        if not lat or not lng:
            return

        current = commander_marker_state.value
        commander_marker_state.set({
            **current,
            user_key: {
                "lat": lat,
                "lng": lng,
            }
        })
    
    # def send_markers_effect():
    #     solara.HTML(
    #         tag="script",
    #         unsafe_innerHTML=f"""
    #         (function() {{
    #             const send = () => {{
    #                 const frame = document.getElementById('commander-map-frame');
    #                 if (!frame || !frame.contentWindow) return;

    #                 frame.contentWindow.postMessage({{
    #                     type: 'setMarkers',
    #                     markers: {markers_json}
    #                 }}, '*');
    #             }};

    #             setTimeout(send, 150);
    #             setTimeout(send, 400);
    #         }})();
    #         """
    #     )

    # solara.use_effect(send_markers_effect, [markers_json])

    with solara.Div(classes=["commander-input-root"]):
        with solara.Div(classes=["commander-input-shell"]):
            # 좌측: 지도 영역 (Leaflet 지형 + 버퍼 오버레이)
            with solara.Div(classes=["commander-map-panel"]):
                solara.HTML(tag="div", unsafe_innerHTML="<div class='commander-map-header'>작전 지역</div>")
                solara.HTML(tag="div", unsafe_innerHTML="<div class='commander-map-sub'>지형 지도에서 제대별 도착지를 확인하세요.</div>")
                with solara.Div(classes=["commander-map-box"]):
                    _map_html = build_base_map_html(BACKEND_HTTP_BASE, markers=marker_payload)
                    solara.HTML(
                        tag="iframe",
                        attributes={
                            "id": "commander-map-frame",
                            "srcdoc": _map_html,
                            "style": "width:100%; height:100%; border:none; display:block;",
                        },
                    )
                    # solara.HTML(
                    #     tag="script",
                    #     unsafe_innerHTML=f"""
                    #     setTimeout(function() {{
                    #         const frame = document.getElementById('commander-map-frame');
                    #         if (!frame || !frame.contentWindow) return;

                    #         frame.contentWindow.postMessage({{
                    #             type: 'setMarkers',
                    #             markers: {markers_json}
                    #         }}, '*');
                    #     }}, 100);
                    #     """,
                    # )

            # 우측: 입력 패널 (1~3제대 좌표 + 정찰시간)
            with solara.Div(classes=["commander-side-panel"]):
                for (user_key, title, lat_v, lng_v) in [
                    ("user1", "도착지1 입력", unit1_lat, unit1_lng),
                    ("user2", "도착지2 입력", unit2_lat, unit2_lng),
                    ("user3", "도착지3 입력", unit3_lat, unit3_lng),
                ]:
                    with solara.Div(classes=["commander-section-card"]):
                        solara.HTML(tag="div", unsafe_innerHTML=f"<div class='commander-section-title'>{title}</div>")
                        with solara.Div(classes=["commander-input-group"]):
                            with solara.Div(classes=["commander-field-row"]):
                                solara.HTML(tag="div", unsafe_innerHTML="<div class='commander-field-label-inline'>위도</div>")
                                solara.InputText(
                                    "",
                                    value=lat_v,
                                    on_value=lambda v, user_key=user_key: set_field(user_key, "lat", v),
                                    #continuous_update=True,
                                )
                            with solara.Div(classes=["commander-field-row"]):
                                solara.HTML(tag="div", unsafe_innerHTML="<div class='commander-field-label-inline'>경도</div>")
                                solara.InputText(
                                    "",
                                    value=lng_v,
                                    on_value=lambda v, user_key=user_key: set_field(user_key, "lng", v),
                                    #continuous_update=True,
                                )
                            solara.Button(
                                f"{title.replace(' 입력', '')} 표시",
                                on_click=lambda user_key=user_key: apply_marker(user_key),
                                style={
                                    "background-color": "rgba(30, 41, 59, 0.78)",
                                    "color": "white",
                                    "height": "32px",
                                    "width": "150px",
                                    "border-radius": "8px",
                                    "font-weight": "700",
                                    "font-size": "14px",
                                    "margin-top": "8px",
                                    "margin-left": "auto",
                                    "margin-right": "auto",
                                    "display": "block",
                                },
                            )

                with solara.Div(classes=["commander-submit-wrap"]):
                    solara.Button(
                        "시뮬레이션 실행",
                        on_click=handle_submit,
                        style={
                            "background-color": "#e67e22", "color": "white",
                            "height": "46px", "width": "100%",
                            "border-radius": "10px", "font-weight": "bold", "font-size": "16px",
                        },
                    )


# ──────────────────────────────────────────────────────────────
# [팀원 코드] 로딩 페이지 (세로 막대 애니메이션)
# workflow_step=1 → 버튼 클릭 시 commander_data_ready=True, workflow_step=2
# ──────────────────────────────────────────────────────────────
@solara.component
def LoadingPage():
    def go_to_commander_page():
        simulation_done.set(True)
        commander_data_ready.set(True)
        workflow_step.set(2)
        # active_run_id가 설정되어 있으면 WS 연결 시작
        rid = active_run_id.value
        if rid:
            ws_client.start_live_updates(rid)
            
    def auto_redirect():
        time.sleep(2)
        go_to_commander_page()

    solara.use_thread(auto_redirect, dependencies=[])    

    solara.Style("""
        html, body, #app, .v-application, .v-application__wrap,
        .solara-content-main, .solara-app, .v-main {
            margin: 0 !important; padding: 0 !important;
            width: 100% !important; height: 100% !important;
            overflow: hidden !important; background: #111827 !important; color: white !important;
        }

        .loading-page-root { width: 100vw; height: 100dvh; display: flex; align-items: center; justify-content: center; background: #111827; }

        #container { width: 100%; max-width: 640px; margin: 0 auto; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 18px; text-align: center; }

        .sticks-row { display: flex; gap: 6px; justify-content: center; align-items: center; width: 100%; margin-bottom: 30px; }

        .stick { width: 10px; height: 40px; background: #f97316; border-radius: 999px; animation: stick-bounce 1s ease-in-out infinite; box-shadow: 0 0 12px rgba(249,115,22,0.5); }

        .stick:nth-child(1) { animation-delay: 0s; }
        .stick:nth-child(2) { animation-delay: 0.08s; }
        .stick:nth-child(3) { animation-delay: 0.16s; }
        .stick:nth-child(4) { animation-delay: 0.24s; }
        .stick:nth-child(5) { animation-delay: 0.32s; }
        .stick:nth-child(6) { animation-delay: 0.40s; }

        @keyframes stick-bounce {
            0%, 100% { transform: scaleY(0.6); opacity: 0.6; }
            50%       { transform: scaleY(1.4); opacity: 1; }
        }

        .loading-title-wrap { width: 100%; display: flex; justify-content: center; align-items: center; }
        .loading-title   { margin: 0; color: white; font-size: 24px; font-weight: 700; text-align: center; }
        .loading-caption { width: 100%; margin-top: 4px; font-size: 14px; color: #9ca3af; text-align: center; line-height: 1.5; }
        .loading-button-wrap { margin-top: 18px; display: flex; justify-content: center; width: 100%; }
    """)

    with solara.Div(classes=["loading-page-root"]):
        with solara.Div(id="container"):
            with solara.Div(classes=["sticks-row"]):
                for _ in range(6):
                    solara.Div(classes=["stick"])

            solara.HTML(
                tag="div",
                unsafe_innerHTML='<div class="loading-title-wrap"><div class="loading-title">시뮬레이션 실행 중...</div></div>',
            )
            solara.HTML(
                tag="div",
                unsafe_innerHTML=(
                    "<div class='loading-caption'>"
                    #"지휘관이 입력한 목적지 데이터로 시뮬레이션을 수행하고 있습니다.<br>"
                    #"현재는 백엔드 미연동 상태이므로, 버튼으로 다음 단계로 이동합니다."
                    "</div>"
                ),
            )

            # with solara.Div(classes=["loading-button-wrap"]):
            #     solara.Button(
            #         "지휘관 메인 대시보드로 이동",
            #         on_click=go_to_commander_page,
            #         style={
            #             "background-color": "#f97316", "color": "white",
            #             "height": "46px", "width": "260px",
            #             "border-radius": "999px", "font-weight": "bold",
            #         },
            #     )


# ──────────────────────────────────────────────────────────────
# [팀원 코드] 통제관 임무 하달 확인 페이지 (3-카드 브리핑 레이아웃)
# 지휘관이 하달한 임무 정보를 3개 카드로 표시 → 확인 후 UserPage로 이동
# ──────────────────────────────────────────────────────────────
@solara.component
def UserMissionPage():
    current_user = logged_in_user.value

    unit_label_map = {"user1": "1제대", "user2": "2제대", "user3": "3제대"}
    my_unit_label = unit_label_map.get(current_user, "미확인")

    # 마운트 시 백엔드 브리핑 API 호출 → mission_delivery_data 갱신
    def _fetch_briefing_on_mount():
        import threading
        def _call():
            data = fetch_operator_briefing(current_user)
            if not data:
                return
            base = data.get("base_assets", {})
            unit = data.get("unit_assets", {})
            mission = data.get("mission", {})
            
            # 현재 임무 모드 결정
            mission_mode_value = mission.get("mode", "") or selected_mission_mode.value or active_btn.value or "균형"
            
            # 그 모드에서 현재 유저의 운용 UGV 수 결정
            operating_count_value = MISSION_UGV_PLAN_BY_MODE.get(mission_mode_value, {}).get(current_user, 0)
            
            # 백엔드 응답을 mission_delivery_data 구조로 매핑
            updated = dict(mission_delivery_data.value)
            updated["delivered"] = True
            updated["base_summary"] = {
                "total_units":       base.get("total_units", 3),
                "total_controllers": base.get("total_controllers", 3),
                "total_ugv":         base.get("total_ugv", 13),
                "total_lost_ugv":    base.get("lost_ugv", 0),
            }
            units = dict(updated.get("units", {}))
            units[current_user] = {
                "controllers":   unit.get("controllers", 1),
                "total_ugv":     unit.get("total_ugv", 5),
                "lost_ugv":      unit.get("lost_ugv", 0),
                "available_ugv": unit.get("available_ugv", 5),
                "target_lat":    unit.get("target_lat", ""),
                "target_lon":    unit.get("target_lon", ""),
            }
            updated["units"] = units
            mission_info = dict(updated.get("mission_info", {}))
            mission_info[current_user] = {
                "mission_mode": mission_mode_value,
                "operating_ugv_count": operating_count_value,
                "departure_time": mission.get("depart_time", "-"),
                "arrival_time": mission.get("arrive_time", "-"),
                #"recon_time":         mission.get("recon_time", "-"),
            }
            updated["mission_info"] = mission_info
            mission_delivery_data.set(updated)
        threading.Thread(target=_call, daemon=True).start()

    solara.use_effect(_fetch_briefing_on_mount, [current_user])

    # 임무 하달 데이터 (mission_delivery_data 우선, 없으면 개별 상태에서)
    delivered = mission_delivery_data.value
    base_summary = delivered.get("base_summary", {})
    unit_assets = delivered.get("units", {}).get(current_user, {})
    mission_info = delivered.get("mission_info", {}).get(current_user, {})

    # fallback: mission_settings에서도 읽기
    #recon = mission_info.get("recon_time", "") or mission_settings.value.get("recon_times", {}).get(current_user, "")
    depart = mission_info.get("departure_time", "-")
    arrive = mission_info.get("arrival_time", "-")
    mode = mission_info.get("mission_mode", selected_mission_mode.value) or selected_mission_mode.value or active_btn.value

    operating_count = MISSION_UGV_PLAN_BY_MODE.get(mode, {}).get(current_user, "-")

    def go_to_user_page():
        workflow_step.set(1)

    solara.Style("""
        html, body, #app, .v-application, .v-application__wrap,
        .solara-content-main, .solara-app, .v-main {
            background-color: #0b1426 !important;
            color: white !important; margin: 0 !important;
            padding: 0 !important; width: 100% !important;
            height: 100% !important; overflow: hidden !important;
        }

        .briefing-root {
            width: 100vw; height: 100dvh;
            display: flex; flex-direction: column;
            background: #0b1426; box-sizing: border-box;
            padding: 24px 32px; gap: 20px; overflow: hidden;
        }

        .briefing-header {
            display: flex; flex-direction: column;
            align-items: center; gap: 6px; flex-shrink: 0;
        }

        .briefing-title {
            color: white; font-size: 26px; font-weight: 800;
            margin: 0; text-align: center;
        }

        .briefing-subtitle {
            color: #94a3b8; font-size: 15px; text-align: center; margin: 0;
        }

        .briefing-cards-row {
            flex: 1; min-height: 0;
            display: grid; grid-template-columns: repeat(3, 1fr);
            gap: 16px;
        }

        .briefing-card {
            background: rgba(22, 34, 56, 0.82);
            border: 1px solid rgba(45, 58, 84, 0.6);
            border-radius: 16px; padding: 20px;
            display: flex; flex-direction: column; gap: 12px;
            overflow-y: auto;
        }

        .briefing-card-title {
            color: #94a3b8; font-size: 13px; font-weight: 700;
            text-transform: uppercase; letter-spacing: 0.05em;
            border-bottom: 1px solid rgba(148,163,184,0.18);
            padding-bottom: 8px; flex-shrink: 0;
        }

        .briefing-row {
            display: flex; justify-content: space-between;
            align-items: center; padding: 6px 0;
            border-bottom: 1px solid rgba(148,163,184,0.08);
        }

        .briefing-row:last-child { border-bottom: none; }

        .briefing-key { color: #9ca3af; font-size: 13px; font-weight: 600; }

        .briefing-val {
            color: white; font-size: 14px; font-weight: 700;
            text-align: right;
        }

        .briefing-val-highlight {
            color: #f59e0b; font-size: 18px; font-weight: 800;
        }

        .briefing-footer {
            flex-shrink: 0; display: flex;
            justify-content: center; padding-top: 4px;
        }
    """)

    with solara.Div(classes=["briefing-root"]):
        # 헤더
        with solara.Div(classes=["briefing-header"]):
            solara.HTML(
                tag="div",
                unsafe_innerHTML=f"<div class='briefing-title'>{my_unit_label} 통제관 임무 브리핑</div>",
            )
            solara.HTML(
                tag="div",
                unsafe_innerHTML="<div class='briefing-subtitle'>지휘관이 하달한 임무 정보를 확인하세요.</div>",
            )

        # 3-카드 그리드
        with solara.Div(classes=["briefing-cards-row"]):

            # 카드 1: 부대 기본자산
            with solara.Div(classes=["briefing-card"]):
                solara.HTML(tag="div", unsafe_innerHTML="<div class='briefing-card-title'>부대 기본자산</div>")
                for key, val in [
                    ("총 제대 수", base_summary.get("total_units", "-")),
                    ("총 통제관 수", base_summary.get("total_controllers", "-")),
                    ("총 정찰 UGV 수", base_summary.get("total_recon_ugv", "-")),
                    ("총 손실 UGV 수", base_summary.get("total_lost_ugv", "-")),
                ]:
                    with solara.Div(classes=["briefing-row"]):
                        solara.Text(key, classes=["briefing-key"])
                        solara.Text(str(val), classes=["briefing-val"])

            # 카드 2: 제대 자산 현황
            with solara.Div(classes=["briefing-card"]):
                solara.HTML(tag="div", unsafe_innerHTML=f"<div class='briefing-card-title'>{my_unit_label} 자산 현황</div>")
                for key, val in [
                    ("통제관 수", unit_assets.get("controllers", "-")),
                    ("총 정찰 UGV 수", unit_assets.get("total_recon_ugv", "-")),
                    ("손실 UGV 수", unit_assets.get("lost_ugv", "-")),
                    ("운용 가능 UGV 수", unit_assets.get("available_ugv", "-")),
                    ("목표 위도", unit_assets.get("target_lat", "-") or "-"),
                    ("목표 경도", unit_assets.get("target_lon", "-") or "-"),
                ]:
                    with solara.Div(classes=["briefing-row"]):
                        solara.Text(key, classes=["briefing-key"])
                        solara.Text(str(val), classes=["briefing-val"])

            # 카드 3: 임무 정보
            with solara.Div(classes=["briefing-card"]):
                solara.HTML(tag="div", unsafe_innerHTML="<div class='briefing-card-title'>임무 정보</div>")
                for key, val, highlight in [
                    ("임무 모드", mode, True),
                    ("운용 UGV 수", operating_count, True),
                    ("출발 예정 시각", depart, False),
                    ("도착 예정 시각", arrive, False),
                    #("정찰 예정 시간", recon or "-", False),
                ]:
                    with solara.Div(classes=["briefing-row"]):
                        solara.Text(key, classes=["briefing-key"])
                        solara.Text(
                            str(val),
                            classes=["briefing-val-highlight" if highlight else "briefing-val"],
                        )

        # 하단 버튼
        with solara.Div(classes=["briefing-footer"]):
            solara.Button(
                "통제관 메인 페이지로 넘어가기",
                on_click=go_to_user_page,
                style={
                    "background-color": "#e67e22", "color": "white",
                    "height": "50px", "min-width": "260px",
                    "border-radius": "12px", "font-weight": "bold",
                    "font-size": "16px",
                },
            )


# ──────────────────────────────────────────────────────────────
# [내 코드] 지휘관 홈 헤더 (CommanderHomeHeader)
# MainPage 상단에서 사용.
# ──────────────────────────────────────────────────────────────
@solara.component
def CommanderHomeHeader():
    with solara.Div(
        style={
            "display": "flex", "align-items": "center", "justify-content": "space-between",
            "width": "100%", "height": "100%",
            "padding": "0 16px", "box-sizing": "border-box", "gap": "18px",
        }
    ):
        with solara.Row(gap="14px", style={"align-items": "center"}):
            solara.Button(
                "⬅",
                on_click=go_home,
                style={"background-color": "#1e293b", "color": "white", "min-width": "58px", "height": "48px", "font-size": "24px", "border-radius": "8px"},
            )
            with solara.Column(gap="0px"):
                solara.Text(home_current_time.value, style={"font-size": "14px", "color": "#cbd5e1", "font-weight": "600"})
                solara.Text(home_role_label.value,   style={"font-size": "22px", "color": "white",   "font-weight": "700"})

        with solara.Column(gap="0px", style={"align-items": "center"}):
            solara.Text("남은시간", style={"font-size": "12px", "color": "#94a3b8"})
            solara.Text(home_remaining_time.value, style={"font-size": "24px", "font-weight": "700", "color": "white"})

        with solara.Column(gap="6px", style={"align-items": "center", "min-width": "340px"}):
            solara.Text("자산현황", style={"font-size": "12px", "color": "#94a3b8"})
            with solara.Row(gap="10px"):
                for item in home_asset_modes.value:
                    is_active = selected_asset_mode.value == item["key"]
                    with solara.Column(gap="2px", style={"align-items": "center"}):
                        solara.Button(
                            item["label"],
                            on_click=lambda key=item["key"]: set_selected_asset_mode(key),
                            style={
                                "background-color": "#e67e22" if is_active else "#2d3a54",
                                "color": "white", "min-width": "72px", "height": "38px",
                                "font-weight": "700", "border-radius": "8px",
                                "opacity": "1" if is_active else "0.85",
                            },
                        )
                        solara.Text(str(item["count"]), style={"font-size": "22px", "font-weight": "700", "color": "white"})


# ──────────────────────────────────────────────────────────────
# [내 코드] 통제관 홈 헤더 (OperatorHomeHeader)
# MainPage 상단에서 사용.
# ──────────────────────────────────────────────────────────────
@solara.component
def OperatorHomeHeader():
    with solara.Div(
        style={
            "display": "flex", "align-items": "center", "justify-content": "space-between",
            "width": "100%", "height": "100%",
            "padding": "0 16px", "box-sizing": "border-box", "gap": "18px",
        }
    ):
        with solara.Row(gap="14px", style={"align-items": "center"}):
            solara.Button(
                "⬅",
                on_click=go_home,
                style={"background-color": "#1e293b", "color": "white", "min-width": "58px", "height": "48px", "font-size": "24px", "border-radius": "8px"},
            )
            with solara.Column(gap="0px"):
                solara.Text(home_current_time.value, style={"font-size": "14px", "color": "#cbd5e1", "font-weight": "600"})
                solara.Text(home_role_label.value,   style={"font-size": "22px", "color": "white",   "font-weight": "700"})

        with solara.Column(gap="0px", style={"align-items": "center"}):
            solara.Text("남은시간", style={"font-size": "12px", "color": "#94a3b8"})
            solara.Text(home_remaining_time.value, style={"font-size": "24px", "font-weight": "700", "color": "white"})

        with solara.Column(gap="6px", style={"align-items": "center"}):
            solara.Text("자산현황", style={"font-size": "12px", "color": "#94a3b8"})
            with solara.Row(gap="10px", style={"align-items": "center"}):
                for item in home_asset_modes.value:
                    is_active = selected_asset_mode.value == item["key"]
                    with solara.Column(gap="2px", style={"align-items": "center"}):
                        solara.Button(
                            item["label"],
                            on_click=lambda key=item["key"]: set_selected_asset_mode(key),
                            style={
                                "background-color": "#e67e22" if is_active else "#2d3a54",
                                "color": "white", "min-width": "72px", "height": "38px",
                                "font-weight": "700", "border-radius": "8px",
                                "opacity": "1" if is_active else "0.85",
                            },
                        )
                        solara.Text(str(item["count"]), style={"font-size": "22px", "font-weight": "700", "color": "white"})

            if home_mission_notice.value:
                solara.Text(f"-{home_mission_notice.value}-", style={"font-size": "14px", "color": "white", "font-weight": "600"})

            if home_unit_label.value:
                solara.Text(home_unit_label.value, style={"font-size": "18px", "color": "white", "font-weight": "700"})


# ──────────────────────────────────────────────────────────────
# [내 코드] 메인 대시보드 페이지 (MainPage)
# 백엔드 API 연동 KPI 표시 / 맵 / LTWR 우측 패널
# ──────────────────────────────────────────────────────────────
@solara.component
def MainPage():
    from services.api_client import NICKNAMES as _N
    unit_name = home_unit_label.value or _N.get(logged_in_user.value, logged_in_user.value or "미확인")

    solara.Style("""
        html, body, #app, .v-application, .v-application--wrap,
        .solara-content-main, .solara-app, .v-main {
            background-color: #0b1426 !important; color: white !important;
            width: 100% !important; height: 100% !important;
            margin: 0 !important; padding: 0 !important; overflow: hidden !important;
        }

        .page-root { width: 100vw; height: 100vh; background: #0b1426; overflow: hidden; box-sizing: border-box; padding: 10px 14px; }

        .page-shell {
            width: 100%; height: 100%;
            display: grid;
            grid-template-columns: 260px minmax(0, 1fr) 360px;
            grid-template-rows: 88px minmax(0, 1fr);
            gap: 10px; box-sizing: border-box;
        }

        .top-sidebar-bar {
            grid-column: 1 / 3; grid-row: 1;
            width: 100%; height: 88px;
            display: flex; align-items: center; justify-content: space-between;
            background-color: rgba(22, 34, 56, 0.7) !important;
            border-radius: 12px; padding: 10px 12px; box-sizing: border-box; overflow: hidden;
        }

        .content-grid-left {
            grid-column: 1 / 3; grid-row: 2; width: 100%; min-height: 0;
            display: grid; grid-template-columns: 260px minmax(0, 1fr);
            gap: 10px; box-sizing: border-box;
        }

        .status-item-box {
            background-color: rgba(15, 23, 38, 0.7) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 8px;
            display: flex; flex-direction: column; align-items: flex-start; justify-content: center;
            padding: 0 14px !important; gap: 2px; min-width: 0; box-sizing: border-box; overflow: hidden;
        }

        .item-title  { color: #64748b !important; font-size: 11px !important; font-weight: 600; letter-spacing: 0.04em; text-transform: uppercase; white-space: nowrap; line-height: 1.2; }
        .item-value  { font-size: 24px !important; font-weight: 700; color: white !important; white-space: nowrap; line-height: 1.1; }
        .item-sub    { font-size: 12px !important; color: #94a3b8 !important; white-space: nowrap; line-height: 1.2; }

        .action-btn  { height: 36px !important; width: 72px !important; font-size: 14px !important; font-weight: bold !important; border-radius: 6px !important; padding: 0 !important; transition: all 0.2s ease; }
        .btn-active  { background-color: #e67e22 !important; color: white !important; opacity: 1 !important; }
        .btn-default { background-color: #2d3a54 !important; color: white !important; opacity: 0.8 !important; }

        .left-sub-sidebar { min-width: 0; min-height: 0; display: flex; flex-direction: column; gap: 14px; }

        .sub-inner-card {
            background-color: rgba(15, 23, 38, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px; padding: 15px;
            display: flex; flex-direction: column; box-sizing: border-box;
        }

        .center-map-area {
            min-width: 0; min-height: 0;
            display: flex; flex-direction: column;
            background-color: rgba(15, 23, 38, 0.8) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px; padding: 14px; box-sizing: border-box; overflow: hidden;
        }

        .right-sidebar-area {
            grid-column: 3; grid-row: 1 / 3;
            min-width: 0; min-height: 0;
            display: flex; flex-direction: column;
            background-color: rgba(22, 34, 56, 0.5) !important;
            border: 1px solid rgba(45, 58, 84, 0.5) !important;
            border-radius: 12px; padding: 14px; box-sizing: border-box; overflow-y: auto;
        }

        .right-sidebar-area::-webkit-scrollbar { width: 8px; }
        .right-sidebar-area::-webkit-scrollbar-track { background: rgba(11, 20, 38, 0.5); }
        .right-sidebar-area::-webkit-scrollbar-thumb { background: #1e293b; border-radius: 10px; }
        .right-sidebar-area::-webkit-scrollbar-thumb:hover { background: #2d3a54; }

        .card-label   { color: #94a3b8 !important; font-size: 14px; font-weight: bold; margin-bottom: 8px; }
        .effect-label { color: #cbd5e1 !important; }

        .status-item-box > div, .status-item-box .v-sheet,
        .sub-inner-card > div:not(.queue-danger-item), .sub-inner-card .v-sheet,
        .center-map-area > div, .center-map-area .v-sheet,
        .right-sidebar-area > div, .right-sidebar-area .v-sheet {
            background-color: transparent !important;
        }

        .queue-danger-item { background-color: #6a3844 !important; }

        .content-grid-left > .v-sheet.theme--light.elevation-0.d-flex.ma-0 {
            background: transparent !important; background-color: transparent !important; box-shadow: none !important;
        }
    """)

    with solara.Div(classes=["page-root"]):
        with solara.Div(classes=["page-shell"]):

            # ── 상단 메인 헤더 ──────────────────────────────────
            with solara.Div(classes=["top-sidebar-bar"]):
                if home_role.value == "commander":
                    CommanderHomeHeader()
                else:
                    OperatorHomeHeader()

            # ── 하단 본문 ───────────────────────────────────────
            with solara.Div(classes=["content-grid-left"]):
                with solara.Div(classes=["left-sub-sidebar"]):
                    # 부대 정보 / 운용 UGV 수
                    with solara.Div(classes=["sub-inner-card"], style={"padding": "0"}):
                        with solara.Row(style={"flex": "1", "gap": "0px", "padding": "15px"}):
                            with solara.Column(style={"flex": "1", "padding": "0"}):
                                solara.Text("부대 정보", classes=["card-label"], style={"margin-left": "5px"})
                                solara.Text(unit_name, style={"font-size": "24px", "font-weight": "bold", "text-align": "center", "color": "white"})
                            with solara.Column(style={"flex": "1", "padding": "0", "border-left": "1px solid rgba(45,58,84,0.3)"}):
                                solara.Text("운용 UGV 수", classes=["card-label"], style={"margin-left": "15px"})
                                solara.Text(str(ratio_x.value), style={"font-size": "24px", "font-weight": "bold", "text-align": "center", "color": "white"})

                    # 현재경로 효과
                    with solara.Div(classes=["sub-inner-card"]):
                        solara.Text("현재경로 효과", classes=["card-label"])
                        with solara.Div(style={"display": "flex", "justify-content": "space-between", "margin-bottom": "4px"}):
                            solara.Text("임무성공률", classes=["effect-label"])
                            es_val = effect_success.value
                            solara.Text(f"+{es_val}%" if es_val >= 0 else f"{es_val}%", style={"color": "#4ade80", "font-weight": "bold"})
                        with solara.Div(style={"display": "flex", "justify-content": "space-between"}):
                            solara.Text("자산피해율", classes=["effect-label"])
                            ed_val = effect_damage.value
                            solara.Text(f"+{ed_val}%" if ed_val >= 0 else f"{ed_val}%", style={"color": "#fb7185", "font-weight": "bold"})

                    # 대기열
                    with solara.Div(classes=["sub-inner-card"], style={"flex": "1", "min-height": "0"}):
                        solara.Text("대기열", classes=["card-label"])
                        solara.Text("UGV's in danger", style={"font-size": "12px", "color": "#64748b", "margin-top": "-8px"})
                        for item in queue_data.value[:4]:
                            with solara.Div(
                                classes=["queue-danger-item"],
                                style={"border-radius": "8px", "padding": "10px 12px", "margin-top": "10px", "display": "flex", "justify-content": "space-between", "align-items": "center"},
                            ):
                                solara.Text(item["id"], style={"font-weight": "bold", "color": "white", "font-size": "14px"})
                                solara.Text(item["dist"], style={"color": "white", "font-size": "14px", "font-weight": "600"})

                # 중앙 전술 맵
                GridView()

            # 우측 LTWR 패널
            LtwrMapPanel()
