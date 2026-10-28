"""
backend/app/assistant/gemini.py

Gemini(google-genai) 어댑터. 공통 대화 기록(Message)을 Gemini 형식으로 바꿔 한 턴을 호출한다.

설계 메모
  - 무상태: 호출마다 전체 대화를 다시 만든다. 단, 모델이 이전에 돌려준 응답 원본(raw)은 **그대로** 되돌려 보낸다.
    (일부 모델은 함수 호출 응답에 사고 서명(thought_signature)을 담고, 다음 요청에 그대로 있어야 한다.)
  - 자동 함수 호출은 끈다. 도구는 우리 코드(권한 확인, 근거 id 부여)가 직접 실행한다.
  - 인자가 없는 도구는 parameters 를 생략한다 (빈 객체 스키마를 거부하는 버전이 있다).
  - 오류 메시지에서 API 키를 지운다.

주의: 이 어댑터는 실제 Gemini API 와 통신해 검증하지 못했다 (키 없음). SDK 객체 생성과 응답 해석은 테스트에서
SDK 의 실제 타입으로 확인하지만, 네트워크 호출 자체는 키를 넣고 `scripts/eval_assistant.py --live` 로 확인해야 한다.
"""

from __future__ import annotations

import asyncio
from typing import Any

from app.assistant.schema import Message, ModelError, ModelTurn, ToolCall, ToolSpec


TRANSIENT = (429, 500, 502, 503, 504)      # 잠시 뒤 다시 하면 되는 오류 (한도 초과, 서버 과부하)
RETRIES = 4
BACKOFF_SEC = 3.0                            # 3, 6, 12, 24초 간격으로 다시 시도


class GeminiClient:
    name: str

    def __init__(self, api_key: str, model: str, client: Any = None, temperature: float = 0.0):
        if not api_key:
            raise ModelError("GEMINI_API_KEY 가 설정되지 않았습니다.")
        self._api_key, self.model, self.temperature = api_key, model, temperature
        self.name = f"gemini:{model}"
        if client is None:
            from google import genai

            client = genai.Client(api_key=api_key)
        self._client = client

    # ── 변환 ─────────────────────────────────────────────────────────────

    @staticmethod
    def declarations(tools: list[ToolSpec]):
        from google.genai import types

        out = []
        for t in tools:
            has_args = bool(t.parameters.get("properties"))
            out.append(types.FunctionDeclaration(name=t.name, description=t.description,
                                                 parameters_json_schema=t.parameters if has_args else None))
        return [types.Tool(function_declarations=out)] if out else []

    @staticmethod
    def contents(messages: list[Message]):
        from google.genai import types

        out = []
        for m in messages:
            if m.role == "user":
                out.append(types.Content(role="user", parts=[types.Part(text=m.text or "")]))
            elif m.role == "model":
                if m.raw is not None:                       # 사고 서명 등을 보존하려고 원본을 그대로 쓴다
                    out.append(m.raw)
                else:
                    parts = [types.Part(text=m.text)] if m.text else []
                    parts += [types.Part(function_call=types.FunctionCall(name=c.name, args=c.args)) for c in m.tool_calls]
                    out.append(types.Content(role="model", parts=parts))
            elif m.role == "tool":
                out.append(types.Content(role="user", parts=[
                    types.Part.from_function_response(name=call.name, response={"result": result}) for call, result in m.tool_results
                ]))
            else:
                raise ValueError(f"알 수 없는 role: {m.role}")
        return out

    @staticmethod
    def parse(response: Any) -> ModelTurn:
        candidates = getattr(response, "candidates", None) or []
        if not candidates or candidates[0].content is None:
            reason = getattr(candidates[0], "finish_reason", None) if candidates else getattr(getattr(response, "prompt_feedback", None), "block_reason", None)
            raise ModelError(f"모델이 응답을 만들지 못했습니다 (사유: {reason}).")
        content = candidates[0].content
        text, calls = [], []
        for part in content.parts or []:
            fc = getattr(part, "function_call", None)
            if fc is not None and getattr(fc, "name", None):
                calls.append(ToolCall(fc.name, dict(fc.args or {})))
            elif getattr(part, "text", None) and not getattr(part, "thought", False):
                text.append(part.text)
        meta = getattr(response, "usage_metadata", None)
        usage = {"prompt_tokens": getattr(meta, "prompt_token_count", 0) or 0,
                 "output_tokens": getattr(meta, "candidates_token_count", 0) or 0} if meta else {}
        return ModelTurn(text="".join(text) or None, tool_calls=calls, raw=content, usage=usage)

    # ── 호출 ─────────────────────────────────────────────────────────────

    async def next(self, system: str, messages: list[Message], tools: list[ToolSpec]) -> ModelTurn:
        from google.genai import types

        config = types.GenerateContentConfig(
            system_instruction=system, tools=self.declarations(tools) or None, temperature=self.temperature,
            automatic_function_calling=types.AutomaticFunctionCallingConfig(disable=True),
        )
        for attempt in range(RETRIES + 1):
            try:
                response = await self._client.aio.models.generate_content(model=self.model, contents=self.contents(messages), config=config)
                break
            except ModelError:
                raise
            except Exception as exc:  # noqa: BLE001 — 공급자 예외 종류가 많다. 키를 지우고 하나의 오류로 바꾼다.
                if getattr(exc, "code", None) in TRANSIENT and attempt < RETRIES:
                    await asyncio.sleep(BACKOFF_SEC * 2 ** attempt)
                    continue
                raise ModelError(f"Gemini 호출 실패 ({type(exc).__name__}): {str(exc).replace(self._api_key, '***')[:300]}") from exc
        return self.parse(response)
