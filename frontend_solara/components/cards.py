"""
frontend/components/cards.py

우측 LTWR 패널 컴포넌트.

LtwrMapPanel() — T+0 ~ T+3 슬롯에 백엔드 서빙 HTML을 iframe으로 임베드.

동작:
  1. 컴포넌트 마운트 시 /api/ltwr/slots 호출 → 슬롯 URL 갱신
  2. 슬롯 URL이 있으면 <iframe src="http://localhost:8000/ltwr-maps/Tx.html"> 렌더
  3. URL이 없으면 "수신 대기 중..." 플레이스홀더 표시
  4. 새로고침 버튼으로 수동 재조회 가능
"""

import solara
from services.api_client import (
    BACKEND_HTTP_BASE,
    ltwr_labels,
    ltwr_slots,
    refresh_ltwr_slots,
)

SLOTS = ["T0", "T1", "T2", "T3"]


@solara.component
def LtwrMapPanel():
    """우측 스크롤 박스 — T+0 ~ T+3 기상 예측 지도 슬롯 (iframe 임베드)."""

    # 컴포넌트 마운트 시 1회 슬롯 조회
    def _on_mount():
        refresh_ltwr_slots()

    solara.use_effect(_on_mount, [])

    slots  = ltwr_slots.value
    labels = ltwr_labels.value

    with solara.Column(classes=["right-sidebar-area"], style={"padding-top": "18px"}):

        # 헤더 + 새로고침 버튼
        with solara.Row(style={"justify-content": "space-between", "align-items": "center",
                                "margin-bottom": "12px", "margin-top": "4px"}):
            solara.Text("LTWR 현황", style={"color": "#94a3b8", "font-weight": "bold"})
            solara.Button(
                "↺",
                on_click=refresh_ltwr_slots,
                style={
                    "background": "transparent",
                    "color": "#64748b",
                    "border": "1px solid #2d3a54",
                    "border-radius": "4px",
                    "padding": "2px 8px",
                    "cursor": "pointer",
                    "font-size": "14px",
                },
            )

        for slot in SLOTS:
            label = labels.get(slot, slot)
            url   = slots.get(slot)
            # 백엔드 절대 URL로 변환 (프론트는 8765, 백엔드는 8000)
            iframe_src = f"{BACKEND_HTTP_BASE}{url}" if url else None

            with solara.Column(style={"margin-bottom": "18px"}):
                solara.Text(
                    label,
                    style={
                        "color": "#94a3b8",
                        "font-weight": "600",
                        "font-size": "14px",
                        "margin-bottom": "6px",
                        "padding-left": "2px",
                    },
                )

                if iframe_src:
                    # HTML 파일을 iframe으로 임베드
                    solara.HTML(
                        tag="iframe",
                        attributes={
                            "src": iframe_src,
                            "width": "100%",
                            "height": "200",
                            "frameborder": "0",
                            "scrolling": "no",
                            "style": (
                                "border-radius:8px;"
                                "border:1px solid #1e293b;"
                                "display:block;"
                                "background:#0f172a;"
                            ),
                        },
                    )
                else:
                    # 파일 없음 — 플레이스홀더
                    with solara.Div(
                        style={
                            "width": "100%",
                            "height": "120px",
                            "background-color": "#0f172a",
                            "border": "1px solid #1e293b",
                            "border-radius": "8px",
                            "display": "flex",
                            "align-items": "center",
                            "justify-content": "center",
                        }
                    ):
                        solara.Text(
                            "수신 대기 중...",
                            style={"color": "#334155", "font-size": "12px"},
                        )
