"""
backend/app/assistant/scripted.py

LLM 이 아닌 **테스트/평가 하네스 전용** 모델.

  ScriptedModel   미리 정한 턴을 차례로 돌려준다 (에이전트 루프, 권한, 근거 확인을 검증할 때).
  RuleBasedModel  키워드로 도구를 고르고 도구 결과로 답을 템플릿에 채운다. 평가 하네스와 파이프라인이
                  모델 없이도 끝까지 도는지 확인하는 용도이며, 언어 이해 능력을 측정하는 값이 아니다.
"""

from __future__ import annotations

from typing import Callable

from app.assistant.schema import Message, ModelTurn, ToolCall, ToolSpec


class ScriptedModel:
    name = "scripted"

    def __init__(self, turns: list[ModelTurn | Callable[[list[Message]], ModelTurn]]):
        self._turns = list(turns)
        self.calls: list[list[Message]] = []          # 모델이 받은 대화 기록 (검증용)
        self.tools_seen: list[list[str]] = []

    async def next(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        self.calls.append(list(messages))
        self.tools_seen.append([t.name for t in tools])
        if not self._turns:
            raise AssertionError("ScriptedModel 의 준비된 턴이 부족합니다.")
        turn = self._turns.pop(0)
        return turn(messages) if callable(turn) else turn


def call(name: str, **args) -> ModelTurn:
    return ModelTurn(tool_calls=[ToolCall(name, args)])


def say(text: str) -> ModelTurn:
    return ModelTurn(text=text)


def last_tool_data(messages: list[Message], index: int = -1) -> dict:
    """마지막 도구 메시지의 index 번째 결과(data)."""
    tool_msgs = [m for m in messages if m.role == "tool"]
    return tool_msgs[-1].tool_results[index][1]["data"]


def last_evidence_id(messages: list[Message], index: int = -1) -> str:
    tool_msgs = [m for m in messages if m.role == "tool"]
    return tool_msgs[-1].tool_results[index][1]["evidence_id"]


# ── 규칙 기반 모델 ───────────────────────────────────────────────────────

class RuleBasedModel:
    """질문 속 키워드 → 도구 한 개 호출 → 결과를 근거 번호와 함께 문장으로."""
    name = "rule-based"

    ROUTES = [
        (("최적화", "파레토", "전술 메뉴", "편성"), "get_optimization_results"),
        (("예보", "정확도", "지속성"), "get_forecast_quality"),
        (("모드 비교", "모드별", "균형", "정밀", "신속"), "compare_modes"),
        (("병목", "대기열", "sql", "위험 지점", "핫"), "run_sql_analysis"),
        (("언제", "사건", "이벤트", "시간순"), "get_run_events"),
        (("요약", "도착", "sos", "개입", "성공"), "get_run_summary"),
    ]

    async def next(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        allowed = {t.name for t in tools}
        if any(m.role == "tool" for m in messages):
            return ModelTurn(text=self._answer(messages))
        question = next(m.text for m in messages if m.role == "user").lower()
        for keywords, tool in self.ROUTES:
            if any(k in question for k in keywords):
                args = {"report": "queue_by_turn"} if tool == "run_sql_analysis" else {}
                # 보이지 않는 도구라도 일부러 호출해 본다: 권한이 실행 단계에서도 막히는지 평가하기 위해서다.
                return ModelTurn(tool_calls=[ToolCall(tool, args)])
        return ModelTurn(text="이 도구들로는 답할 수 없는 질문입니다.")

    @staticmethod
    def _answer(messages: list[Message]) -> str:
        results = [r for m in messages if m.role == "tool" for r in m.tool_results]
        call, payload = results[-1]
        data, eid = payload["data"], payload["evidence_id"]
        if "error" in data:
            return f"요청한 정보를 가져오지 못했습니다: {data['error']} [{eid}]"
        if call.name == "get_run_summary":
            return (f"{data['scope']} 기준 도착 UGV {data['ugv_arrived']}/{data['ugv_total']}대, SOS {data['sos_events']}건, "
                    f"운용자 개입 {data['interventions']}회, 평균 개입 대기 {data['mean_wait_minutes']}분입니다 [{eid}]. 시뮬레이션 1회 기록입니다.")
        if call.name == "get_optimization_results":
            parts = [f"{m} 전술 편성 {'-'.join(map(str, v['formation']))}, 도착률 {v['arrival'] * 100:.0f}% [{eid}]" for m, v in data["optimized"].items()]
            return "; ".join(parts) + ". 구간이 겹치는 비교는 단정할 수 없습니다."
        if call.name == "get_forecast_quality":
            return f"예보의 평균 skill은 {data['mean_skill']:.2f}로 지속성보다 낮습니다 [{eid}]."
        if call.name == "compare_modes":
            parts = [f"{r['mode']} 모드 작전 시간 {r['mission_minutes']}분, SOS {r['sos_events']}건" for r in data["modes"]]
            return "; ".join(parts) + f" [{eid}]. 모드별 1회 실행 기록입니다."
        return f"조회한 결과입니다 [{eid}]."
