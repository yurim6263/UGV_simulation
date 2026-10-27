"""
frontend/app.py

파이브웨더즈 UGV 전술 지원 시스템 — Solara 프론트엔드 메인 앱

페이지 플로우 (팀원 코드: 역할 기반 라우팅):
    지휘관: LoginPage → CommanderInputPage → LoadingPage → CommanderPage
    통제관: LoginPage → UserMissionPage → UserPage
"""

import os
import sys
import solara

# ── 경로 설정 (내 코드: 기존 경로 인식 로직 유지) ─────────────────
HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

# ── 팀원 코드: static 폴더 연결 (지도 HTML 파일 서빙용) ───────────
STATIC_DIR = os.path.join(HERE, "static")
solara.settings.main.static_path = STATIC_DIR

# ── 팀원 코드: 역할 기반 페이지 컴포넌트 임포트 ───────────────────
from components.pages import (
    LoginPage,
    CommanderInputPage,
    LoadingPage,
    CommanderPage,
    UserMissionPage,
    UserPage,
)

# ── 팀원 코드: 워크플로우 상태 임포트 ─────────────────────────────
from services.api_client import (
    is_logged_in,
    user_role,
    workflow_step,
    commander_data_ready,
    destination_data,
    mission_note,
    mission_settings,
)


# ── 팀원 코드: 역할/단계 기반 라우팅 Page 컴포넌트 ────────────────
@solara.component
def Page():
    """
    라우팅 규칙:
      - 미로그인           → LoginPage
      - 지휘관 step=0      → CommanderInputPage  (좌표 입력)
      - 지휘관 step=1      → LoadingPage         (시뮬레이션 대기)
      - 지휘관 step=2+     → CommanderPage        (지휘관 메인 대시보드)
      - 통제관 (미준비)    → LoginPage            (지휘관 준비 전 차단)
      - 통제관 step=0      → UserMissionPage      (임무 하달 확인)
      - 통제관 step=1+     → UserPage             (통제관 메인 대시보드)
    """
    if not is_logged_in.value:
        return LoginPage()

    role = user_role.value
    step = workflow_step.value

    # 지휘관 흐름
    if role == "commander":
        if step == 0:
            return CommanderInputPage()
        elif step == 1:
            return LoadingPage()
        else:
            return CommanderPage()

    # 통제관 흐름
    if role == "controller":
        if not commander_data_ready.value:
            return LoginPage()
        if step == 0:
            return UserMissionPage()
        else:
            return UserPage()

    return LoginPage()


app = Page
