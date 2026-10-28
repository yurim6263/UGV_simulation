"""
backend/app/assistant/knowledge.py

운용 규칙·분석 문서 검색 (RAG의 검색 부분). AI 어시스턴트의 `search_docs` 도구가 쓴다.

검색 대상: backend/data/knowledge/*.md (시스템 운용 규칙) + 저장소의 docs/*.md (분석 보고서, 있을 때만).
실제 군 교범이 아니다. 이 시스템의 규칙과 분석 문서이며, 운용 규칙의 숫자는 테스트가 코드 상수와 대조한다.

검색 방식: BM25 (어휘 기반). 한국어는 조사 때문에 단어 단위 일치가 어려워 글자 2개 묶음(bigram)과 영숫자 토큰으로 자른다.
의미 기반(임베딩) 검색은 쓰지 않았다: 문서가 작고(수십 개 구간), 임베딩 API 호출은 무료 키의 하루 한도를 쓰며, 어휘 검색은
오프라인에서 결정적으로 테스트할 수 있다. 문서가 커지거나 표현이 달라 못 찾는 질문이 많아지면 임베딩 검색을 더하는 것이 다음 단계다.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[2]
KNOWLEDGE_DIRS = [BACKEND / "data" / "knowledge", BACKEND.parent / "docs"]
MAX_CHUNK_CHARS = 700
K1, B = 1.5, 0.75
# AI 어시스턴트 자신의 평가 문서는 검색하지 않는다: 평가 질문("드론 배터리", "주식")이 적혀 있어 "문서에 없는 질문" 검사를 망가뜨리고,
# 어시스턴트가 자기 점수를 근거로 답하는 순환도 만든다.
EXCLUDED_DOCS = {"assistant.md"}
MIN_COVERAGE = 0.34        # 질문 토큰 중 이 비율 이상이 구간에 있어야 결과로 인정 (관련 없는 질문에 억지로 답하지 않는다)

_WORD = re.compile(r"[0-9a-z]+(?:\.[0-9]+)?|[가-힣]+")
_HANGUL = re.compile(r"[가-힣]+")


@dataclass(frozen=True)
class Chunk:
    id: str
    source: str            # 파일 경로 (저장소 기준)
    title: str             # 문서 제목 (# )
    heading: str           # 구간 제목 (## )
    text: str


def tokenize(text: str) -> list[str]:
    """영숫자/숫자는 그대로, 한글은 글자 2개 묶음(한 글자 단어는 그대로)으로 자른다."""
    out: list[str] = []
    for w in _WORD.findall(text.lower()):
        if _HANGUL.fullmatch(w):
            out += [w[i:i + 2] for i in range(len(w) - 1)] if len(w) > 1 else [w]
        else:
            out.append(w)
    return out


def _split_long(text: str) -> list[str]:
    """MAX_CHUNK_CHARS 를 넘는 구간은 줄(목록 항목) 단위로 나눈다."""
    if len(text) <= MAX_CHUNK_CHARS:
        return [text]
    parts, cur = [], ""
    for line in text.split("\n"):
        if cur and len(cur) + len(line) + 1 > MAX_CHUNK_CHARS:
            parts.append(cur)
            cur = ""
        cur = f"{cur}\n{line}" if cur else line
    if cur:
        parts.append(cur)
    return parts


def chunk_markdown(path: Path, rel: str) -> list[Chunk]:
    title, heading, buf, chunks = path.stem, "", [], []

    def flush():
        body = "\n".join(buf).strip()
        if body:
            for part in _split_long(body):
                chunks.append(Chunk(f"{rel}#{len(chunks) + 1}", rel, title, heading or title, part))
        buf.clear()

    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# "):
            flush()
            title = line[2:].strip()
            heading = ""
        elif line.startswith("## ") or line.startswith("### "):
            flush()
            heading = line.lstrip("#").strip()
        else:
            buf.append(line)
    flush()
    return chunks


class Index:
    def __init__(self, chunks: list[Chunk]):
        self.chunks = chunks
        # 제목도 검색에 쓰이도록 본문에 붙여 토큰화한다
        self.docs = [Counter(tokenize(f"{c.title} {c.heading} {c.heading} {c.text}")) for c in chunks]
        self.lens = [sum(d.values()) for d in self.docs]
        self.avg = (sum(self.lens) / len(self.lens)) if self.lens else 0.0
        self.df: Counter = Counter()
        for d in self.docs:
            self.df.update(d.keys())

    def idf(self, term: str) -> float:
        n = len(self.chunks)
        return math.log(1 + (n - self.df[term] + 0.5) / (self.df[term] + 0.5))

    def search(self, query: str, k: int = 3) -> list[tuple[Chunk, float]]:
        terms = list(dict.fromkeys(tokenize(query)))
        if not terms or not self.chunks:
            return []
        scored = []
        for chunk, tf, length in zip(self.chunks, self.docs, self.lens):
            hit = [t for t in terms if tf[t] > 0]
            if len(hit) / len(terms) < MIN_COVERAGE:
                continue
            score = sum(self.idf(t) * tf[t] * (K1 + 1) / (tf[t] + K1 * (1 - B + B * length / self.avg)) for t in hit)
            scored.append((chunk, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]


@lru_cache(maxsize=1)
def default_index() -> Index:
    chunks: list[Chunk] = []
    for d in KNOWLEDGE_DIRS:
        if d.is_dir():
            for path in sorted(d.glob("*.md")):
                if path.name in EXCLUDED_DOCS:
                    continue
                chunks += chunk_markdown(path, f"{d.parent.name}/{d.name}/{path.name}" if d.name == "knowledge" else f"docs/{path.name}")
    return Index(chunks)
