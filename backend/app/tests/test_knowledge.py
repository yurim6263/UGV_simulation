"""
backend/app/tests/test_knowledge.py

운용 규칙 검색(RAG의 검색 부분) 테스트.

  1) 문서의 숫자가 엔진 상수와 같은가 (문서가 코드와 어긋나면 AI가 틀린 규칙을 근거와 함께 말하게 된다)
  2) 검색이 질문에 맞는 구간을 찾고, 관련 없는 질문에는 결과를 내지 않는가
  3) search_docs 도구와 근거 검증(문서 속 숫자 인정)이 동작하는가
"""

import inspect

import pytest

from app.assistant import knowledge
from app.assistant.grounding import check_answer
from app.assistant.knowledge import Index, chunk_markdown, default_index, tokenize
from app.assistant.schema import Evidence, ToolCall, ToolContext
from app.assistant.tools import execute_tool, role_of, visible_tools
from app.core.security import TokenPayload
from app.simulation.algo import episode
from app.simulation.algo.ap_resolver import (
    AP_MAX, AP_MIN, AP_TURN, ALPHA_MOB, DIAGONAL_COEFF, P_MAX_MOB, P_MAX_SEN,
)
from app.simulation.algo.episode import CELL_KM, INTERVENE_BASE_AP, Genes, ScenarioSpec
from app.simulation.presets import WEATHER_SCALES

RULES = (knowledge.BACKEND / "data" / "knowledge" / "operating_rules.md").read_text(encoding="utf-8")


def has(text: str) -> bool:
    return text in RULES


# ── 편성 계산 규칙 ──────────────────────────────────────────────────────────

def test_rules_document_describes_the_formation_planner_with_the_real_constants():
    from app.simulation import formation

    assert has(f"제대마다 {formation.MIN_PER_TEAM}~{formation.MAX_PER_TEAM}대")
    assert has(f"도착률 {int(formation.MIN_ARRIVAL * 100)}% 이상")
    assert has(f"수색 {int(formation.TIE_COVERAGE * 100)}%p") and has(f"시간 {formation.TIE_MINUTES}분")
    assert "모드마다 제대별 UGV 수" not in RULES                      # 모드에 고정된 편성이 있다는 옛 설명이 남아 있지 않다
    assert "3-3-3" not in RULES and "4-3-2" not in RULES


# ── 문서 ↔ 코드 ──────────────────────────────────────────────────────────

def test_rules_document_numbers_match_engine_constants():
    assert has(f"{AP_TURN:,}")                                              # 턴당 AP
    assert has(f"{int(AP_MIN):,} + {int(AP_MAX - AP_MIN):,} × r²")          # 이동 AP 식
    assert has(f"{DIAGONAL_COEFF}배")
    assert has(f"기동 위험 {int(ALPHA_MOB * 100)}%와 센서 위험 {int(round((1 - ALPHA_MOB) * 100))}%의 가중합")
    assert has(f"{int(P_MAX_MOB * 100)}%") and has(f"{int(P_MAX_SEN * 100)}%")
    assert has(f"{INTERVENE_BASE_AP:,} × (1 + 0.5 × 위험 + 0.15 × 거리km)")
    g = Genes()
    assert has(f"{g.hold_km}km를 넘으면 대기") and has(f"{g.recall_km}km 이상이면") and has(f"{g.resume_km}km 이내")


def test_rules_document_matches_geometry_and_defaults():
    spec = ScenarioSpec(start=(0, 0), pois=())
    assert has(f"{spec.follow_gap_cells}칸({spec.follow_gap_cells * CELL_KM:g}km)")
    assert has(f"{spec.max_turns}턴({spec.max_turns * 10}분)")
    assert has(f"맑음 {WEATHER_SCALES['clear']}") and has(f"보통 {WEATHER_SCALES['moderate']}") and has(f"악천후 {WEATHER_SCALES['severe']}")
    assert "INTERVENE_BASE_AP * (1.0 + 0.5 * risk + 0.15 * d_km)" in inspect.getsource(episode)      # 개입 비용식이 문서와 같은 식인지
    assert "[30, 70]" in inspect.getsource(episode.risk_thresholds)                         # 등급 경계 30/70


def test_rules_document_minimum_arrival_matches_optimizer_default():
    from app.simulation.optimize import TacticalProblem

    sig = inspect.signature(TacticalProblem.__init__)
    assert sig.parameters["min_arrival"].default == 0.8 and has("평균 도착률 80% 이상")


# ── 토큰화와 구간 나누기 ─────────────────────────────────────────────────

def test_tokenize_splits_korean_into_bigrams_and_keeps_numbers_and_latin():
    assert tokenize("목줄 1.5km AP") == ["목줄", "1.5", "km", "ap"]
    t = tokenize("유인기는 정지한다")
    assert "유인" in t and "인기" in t and "정지" in t
    assert tokenize("한") == ["한"] and tokenize("") == []


def test_chunks_follow_headings_and_stay_short():
    chunks = chunk_markdown(knowledge.BACKEND / "data" / "knowledge" / "operating_rules.md", "data/knowledge/operating_rules.md")
    assert {"시간과 행동력(AP)", "사고(SOS)", "운용자 개입", "유인기와 목줄(tether)"} <= {c.heading for c in chunks}
    assert all(len(c.text) <= knowledge.MAX_CHUNK_CHARS + 200 for c in chunks)
    assert all(c.title == "시뮬레이션 운용 규칙" for c in chunks)


# ── 검색 품질 ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("query, heading, must_contain", [
    ("한 칸 이동할 때 AP는 어떻게 계산해?", "시간과 행동력(AP)", "320,000"),
    ("기동 고장 확률은 얼마야", "사고(SOS)", "20%"),
    ("운용자 개입 비용 계산", "운용자 개입", "500,000"),
    ("유인기에서 얼마나 멀어지면 대기하나", "유인기와 목줄(tether)", "1.5km"),
    ("위험 등급 G A R은 무슨 뜻이야", "위험 등급과 KPI", "상대 등급"),
    ("최적화 제약 조건이 뭐야", "모드와 최적화", "80%"),
])
def test_search_finds_the_right_section_in_the_top_results(query, heading, must_contain):
    hits = default_index().search(query, k=3)
    assert hits, query
    assert any(c.heading == heading and must_contain in c.text for c, _ in hits), [(c.heading, round(s, 2)) for c, s in hits]


def test_search_returns_nothing_for_questions_the_documents_do_not_cover():
    for q in ("삼성전자 주식을 사야 할까", "드론 배터리 교체 절차", "오늘 점심 메뉴 추천", "zzzz qqqq"):
        assert default_index().search(q) == [], q
    assert default_index().search("") == []


def test_ranking_prefers_the_section_where_query_terms_are_concentrated():
    idx = Index([
        knowledge.Chunk("a#1", "a.md", "A", "고양이", "고양이는 우유를 좋아한다. 고양이 사료."),
        knowledge.Chunk("a#2", "a.md", "A", "강아지", "강아지는 산책을 좋아한다."),
        knowledge.Chunk("a#3", "a.md", "A", "새", "새는 하늘을 난다."),
    ])
    assert idx.search("고양이 우유")[0][0].heading == "고양이"
    assert idx.search("산책")[0][0].heading == "강아지"


def test_index_includes_project_docs_when_present():
    sources = {c.source for c in default_index().chunks}
    assert "data/knowledge/operating_rules.md" in sources
    assert any(s.startswith("docs/") for s in sources)
    assert "docs/assistant.md" not in sources                       # 평가 질문이 적힌 문서는 검색하지 않는다


# ── 도구와 근거 검증 ─────────────────────────────────────────────────────

CTX = ToolContext(db=None, user=TokenPayload(sub="2", role="operator", unit="2제대"), role="operator")


@pytest.mark.asyncio
async def test_search_docs_tool_is_visible_to_both_roles_and_returns_sources():
    assert "search_docs" in {t.name for t in visible_tools("operator")} and "search_docs" in {t.name for t in visible_tools("commander")}
    e = await execute_tool(CTX, ToolCall("search_docs", {"query": "AP 계산식"}), "E1")
    assert not e.error and e.result["results"][0]["source"].endswith(".md") and "문서" in e.result["note"]


@pytest.mark.asyncio
async def test_search_docs_reports_missing_content_and_rejects_empty_query():
    none = await execute_tool(CTX, ToolCall("search_docs", {"query": "드론 배터리 교체"}), "E1")
    assert none.result["results"] == [] and "모른다" in none.result["note"]
    assert (await execute_tool(CTX, ToolCall("search_docs", {"query": "  "}), "E2")).error
    many = await execute_tool(CTX, ToolCall("search_docs", {"query": "위험 AP 사고 개입", "k": 99}), "E3")
    assert len(many.result["results"]) <= 5


@pytest.mark.asyncio
async def test_numbers_quoted_from_documents_are_grounded_but_invented_ones_are_not():
    ev = await execute_tool(CTX, ToolCall("search_docs", {"query": "AP 계산식 직선 이동"}), "E1")
    ok = check_answer("한 칸 이동 AP는 80,000 + 320,000 × r² 이고 대각선은 1.4배입니다 [E1].", [ev])
    assert ok.ok, ok.warnings()
    bad = check_answer("한 칸 이동 AP는 90,000 + 450,000 × r² 입니다 [E1].", [ev])
    assert "90" in bad.ungrounded_numbers or "450" in bad.ungrounded_numbers


def test_document_numbers_do_not_count_as_evidence_for_other_tools():
    fake = Evidence("E1", "get_run_summary", {}, {"results": [{"text": "320,000"}]})
    assert "320" in check_answer("320,000 입니다 [E1]", [fake]).ungrounded_numbers
