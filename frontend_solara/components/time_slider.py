"""
frontend/components/time_slider.py

타임슬라이더 컴포넌트.
time_steps 목록을 슬라이더로 탐색하며, 선택된 time_step에 해당하는
기상/위험 데이터를 백엔드에서 가져와 지도 레이어를 갱신합니다.
"""

import solara

import state
import api_client


@solara.component
def TimeSlider():
    """
    기상 time_step 슬라이더.

    - time_steps 목록이 있어야 렌더링됨
    - 슬라이더 이동 → current_time_step 갱신 → 기상/위험 데이터 재조회
    """
    steps     = solara.use_state_reactive(state.time_steps)
    cur_step  = solara.use_state_reactive(state.current_time_step)
    scenario  = solara.use_state_reactive(state.selected_scenario_id)
    loading   = solara.use_state_reactive(state.loading)

    if not steps.value:
        solara.Text("time_step 없음 — 시나리오를 먼저 선택하세요.",
                    style={"color": "#888", "fontSize": "0.85rem"})
        return

    # 슬라이더 인덱스 → time_step 문자열
    idx, set_idx = solara.use_state(0)

    def on_slider(value: int):
        set_idx(value)
        selected = steps.value[value]
        state.current_time_step.value = selected
        _load_weather(scenario.value, selected)

    def _load_weather(scenario_id: str, time_step: str):
        if not scenario_id or not time_step:
            return
        loading.value = True
        try:
            weather = api_client.fetch_weather(scenario_id, time_step)
            state.weather_data.value = weather
        except Exception as e:
            state.error_message.value = f"기상 데이터 로드 실패: {e}"
        finally:
            loading.value = False

    with solara.Column():
        solara.Text(
            f"시간 스텝: {steps.value[idx] if steps.value else '-'}",
            style={"fontWeight": "bold", "marginBottom": "4px"},
        )
        solara.SliderInt(
            label="",
            value=idx,
            min=0,
            max=len(steps.value) - 1,
            on_value=on_slider,
            thumb_label=True,
            tick_labels={
                0: steps.value[0][:10] if steps.value else "",
                len(steps.value) - 1: steps.value[-1][:10] if steps.value else "",
            },
        )
        # 앞/뒤 이동 버튼
        with solara.Row():
            solara.Button(
                "◀ 이전",
                on_click=lambda: on_slider(max(0, idx - 1)),
                disabled=idx == 0,
                small=True,
            )
            solara.Button(
                "다음 ▶",
                on_click=lambda: on_slider(min(len(steps.value) - 1, idx + 1)),
                disabled=idx >= len(steps.value) - 1,
                small=True,
            )
