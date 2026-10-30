"""
backend/app/assistant/grounding.py

답변이 도구 결과(근거)에 실제로 기대고 있는지 확인한다. LLM 의 숫자 환각을 잡는 장치다.

확인하는 것
  1) 답변의 숫자가 어떤 근거 값과도 일치하지 않으면 "근거 없는 숫자".
     일치로 인정하는 변환: 같은 값, x10(턴→분), x100(비율→%), x0.1, x0.01, 그리고 답변이 쓴 소수 자릿수로 반올림한 값.
  2) [E7] 처럼 인용한 근거가 실제로 존재하는지.
  3) 숫자가 있는데 인용이 하나도 없으면 경고.

문서 검색(search_docs) 결과는 본문 속 숫자도 근거로 인정한다.

한계(휴리스틱): 10 미만의 정수("3대", "2제대")는 식별자/개수일 가능성이 커서 검사하지 않는다. 숫자를 맞게 쓰고
의미를 틀리게 해석한 경우(예: SOS 건수를 도착 대수로 말함)는 잡지 못한다. 그런 오류는 평가셋(evals)의 정답 비교로 본다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from app.assistant.schema import Evidence

CITATION = re.compile(r"\[E(\d+)\]")
NUMBER = re.compile(r"(?<![\w.])-?\d+(?:\.\d+)?")
LIST_MARKER = re.compile(r"(?m)^\s*\d+[.)]\s")
MULTIPLIERS = (1.0, 10.0, 100.0, 0.1, 0.01)
SKIP_BELOW = 10          # 이 값 미만의 정수는 검사하지 않는다


@dataclass
class GroundingReport:
    ungrounded_numbers: list[str]
    unknown_citations: list[str]
    cited: list[str]
    has_checkable_numbers: bool

    @property
    def ok(self) -> bool:
        return not self.ungrounded_numbers and not self.unknown_citations

    def warnings(self) -> list[str]:
        out = []
        if self.ungrounded_numbers:
            out.append("근거에서 찾을 수 없는 숫자: " + ", ".join(self.ungrounded_numbers))
        if self.unknown_citations:
            out.append("존재하지 않는 근거를 인용함: " + ", ".join(self.unknown_citations))
        if self.has_checkable_numbers and not self.cited:
            out.append("숫자가 있지만 근거 표기([E1] 형식)가 없음")
        return out


def numeric_leaves(value) -> list[float]:
    """근거 결과에서 숫자 값을 모두 모은다 (bool 제외)."""
    out: list[float] = []
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out.append(float(value))
    elif isinstance(value, dict):
        for v in value.values():
            out += numeric_leaves(v)
    elif isinstance(value, (list, tuple)):
        for v in value:
            out += numeric_leaves(v)
    return out


def _decimals(token: str) -> int:
    return len(token.split(".")[1]) if "." in token else 0


def _matches(token: str, pool: list[float]) -> bool:
    x = float(token)
    d = _decimals(token)
    tol = 0.5 * 10 ** (-d) + 1e-9
    for v in pool:
        for m in MULTIPLIERS:
            if abs(x - v * m) <= tol or abs(abs(x) - abs(v * m)) <= tol:
                return True
    return False


def check_answer(answer: str, evidences: list[Evidence]) -> GroundingReport:
    ids = {e.id for e in evidences}
    cited = CITATION.findall(answer)
    unknown = sorted({f"[E{n}]" for n in cited if f"E{n}" not in ids})

    text = LIST_MARKER.sub(" ", CITATION.sub(" ", answer))
    pool = [n for e in evidences if not e.error for n in numeric_leaves(e.result)]
    # 문서 검색 결과는 숫자 필드가 아니라 본문 문장 속에 숫자가 있으므로 본문에서 뽑는다
    for e in evidences:
        if e.tool == "search_docs" and not e.error:
            for hit in e.result.get("results", []):
                pool += [float(t) for t in NUMBER.findall(str(hit.get("text", "")))]
    # 실패한 도구의 숫자 필드는 근거가 아니지만, 오류 문구 속 숫자("[404] ...")는 답이 인용할 수 있다
    pool += [float(t) for e in evidences if e.error for t in NUMBER.findall(str(e.result.get("error", "")))]
    checkable, ungrounded = [], []
    for token in NUMBER.findall(text):
        x = float(token)
        if x == int(x) and "." not in token and abs(x) < SKIP_BELOW:
            continue
        checkable.append(token)
        if not _matches(token, pool):
            ungrounded.append(token)
    return GroundingReport(sorted(set(ungrounded), key=ungrounded.index), unknown, [f"E{n}" for n in cited], bool(checkable))
