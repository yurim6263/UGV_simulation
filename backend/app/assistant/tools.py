"""
backend/app/assistant/tools.py

어시스턴트가 부를 수 있는 도구. 모두 **읽기 전용**이다 (상태를 바꾸는 도구는 없다. 지휘관의 확정은 사람이 한다).

권한은 프롬프트가 아니라 코드로 강제한다.
  1) 역할이 쓸 수 없는 도구는 모델에게 아예 보여 주지 않고 (visible_tools),
  2) 모델이 그래도 호출하면 실행 단계에서 다시 거부한다 (execute_tool).
  3) 통제관의 기록 조회는 담당 제대의 기록만 받는다 (services/run_data.py 의 필터를 그대로 사용).

도구 결과에는 숫자와 열거값만 담는다. 사용자가 입력한 자유 텍스트(임무 이름 등)는 넣지 않는다
(그런 텍스트가 모델에게 "지시"처럼 읽히는 프롬프트 주입을 구조적으로 막는다).
"""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from sqlalchemy import select

from app.analysis.sql_reports import QUERIES, mode_comparison, run_report
from app.assistant.schema import Evidence, ToolCall, ToolContext, ToolError, ToolSpec
from app.db.models.simulation_run import SimulationRun
from app.services.run_data import COMMANDER_ROLES, MODE_OF, RunDataError, build_run_mode, load_run_data
from app.simulation.presets import PARETO_PATH

ROOT_DATA = Path(__file__).resolve().parents[2] / "data"
FORECAST_SKILL_PATH = ROOT_DATA / "weather" / "forecast_skill.json"
SERVER_MODES = ("balanced", "recon", "rapid")
MODE_LABEL = {"balanced": "균형", "recon": "정밀", "rapid": "신속"}
EVENT_LIMIT = 30
SOS = ("SOS_MOBILITY", "SOS_SENSOR", "SOS_COMPLEX_FAILURE")


def role_of(user: Any) -> str:
    return "commander" if user.role in COMMANDER_ROLES else "operator"


def jsonable(value: Any) -> Any:
    """numpy/NaN 을 JSON 으로 보낼 수 있는 값으로 바꾼다 (NaN 은 None — 숫자로 위장하지 않는다)."""
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [jsonable(v) for v in value]
    if hasattr(value, "item") and not isinstance(value, (str, bytes)):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    return value


# ── 인자 처리 ────────────────────────────────────────────────────────────

def _opt_int(args: dict, key: str) -> int | None:
    v = args.get(key)
    if v is None or v == "":
        return None
    try:
        if isinstance(v, bool) or (isinstance(v, float) and not v.is_integer()):
            raise ValueError
        return int(v)
    except (TypeError, ValueError):
        raise ToolError(f"'{key}' 는 정수여야 합니다: {v!r}")


def _mode(args: dict) -> str:
    mode = args.get("mode") or "balanced"
    if mode not in SERVER_MODES:
        raise ToolError(f"'mode' 는 {list(SERVER_MODES)} 중 하나여야 합니다: {mode!r}")
    return mode


async def _latest_runs(ctx: ToolContext) -> list[SimulationRun]:
    mission_id = (await ctx.db.execute(select(SimulationRun.mission_id).order_by(SimulationRun.id.desc()).limit(1))).scalar_one_or_none()
    if mission_id is None:
        raise ToolError("아직 실행된 시뮬레이션이 없습니다.")
    return list((await ctx.db.execute(
        select(SimulationRun).where(SimulationRun.mission_id == mission_id).order_by(SimulationRun.id)
    )).scalars().all())


async def _resolve_run_id(ctx: ToolContext, args: dict) -> int:
    """run_id 가 있으면 그것을, 없으면 가장 최근 임무에서 mode(기본 균형)의 run 을 쓴다."""
    run_id = _opt_int(args, "run_id")
    if run_id is not None:
        return run_id
    mode = _mode(args)
    for run in await _latest_runs(ctx):
        if (run.selected_mode or "balanced") == mode:
            return run.id
    raise ToolError(f"가장 최근 임무에 '{mode}' 모드의 실행이 없습니다.")


def _run_error(exc: RunDataError) -> ToolError:
    return ToolError(f"[{exc.status_code}] {exc.detail}")


# ── 도구 구현 ────────────────────────────────────────────────────────────

async def list_runs(ctx: ToolContext, args: dict) -> dict:
    runs = await _latest_runs(ctx)
    return {"mission_id": runs[0].mission_id,
            "runs": [{"run_id": r.id, "mode": r.selected_mode or "balanced", "mode_label": MODE_LABEL[r.selected_mode or "balanced"],
                      "status": r.status} for r in runs]}


async def get_run_summary(ctx: ToolContext, args: dict) -> dict:
    run_id = await _resolve_run_id(ctx, args)
    try:
        data = await load_run_data(ctx.db, run_id, ctx.user)
        mode_data, _ = await build_run_mode(ctx.db, data)
    except RunDataError as exc:
        raise _run_error(exc) from exc
    k = mode_data["kpi"]
    scope = "전체" if data.team is None else f"{data.team} 제대만"
    ugv = data.frame[data.frame.agent_id.str.startswith("UGV")]
    mean_risk = ugv["normalized_c_total"].mean() if len(ugv) else None
    out = {
        "run_id": run_id, "mode": data.run.selected_mode or "balanced", "scope": scope,
        "basis": "이 시뮬레이션 1회의 이동 기록에서 집계한 값 (통계 평균이 아님)",
        "ugv_total": k["ugv_total"], "ugv_arrived": k["ugv_arrived"],
        "mission_minutes": k["mission_turns"] * 10,
        "sos_events": k["sos_events"], "sos_mobility": k["sos_mobility"], "sos_sensor": k["sos_sensor"],
        "interventions": k["interventions"], "mean_wait_minutes": round(k["wait_turns_mean"] * 10, 1),
        "red_step_pct": round(k["red_step_ratio"] * 100, 1),
        "red_step_note": "red_step_pct 는 전 시간대 위험도 상위 30%(상대 등급 R)에서 보낸 UGV 기록 비율이다. 절대 위험이 아니다.",
        "mean_risk_0_1": None if mean_risk is None else round(float(mean_risk), 3),
        "per_team": {t: {"ugv": v["ugv"], "arrived": v["arrived"], "sos": v["sos"],
                         "arrive_minutes": None if v["arrive_turn"] is None else (v["arrive_turn"] + 1) * 10}
                     for t, v in k["per_team"].items()},
    }
    return out


async def get_run_events(ctx: ToolContext, args: dict) -> dict:
    run_id = await _resolve_run_id(ctx, args)
    kind = args.get("kind") or "all"
    if kind not in ("sos", "intervene", "all"):
        raise ToolError("'kind' 는 sos | intervene | all 중 하나여야 합니다.")
    limit = min(_opt_int(args, "limit") or 15, EVENT_LIMIT)
    try:
        data = await load_run_data(ctx.db, run_id, ctx.user)
    except RunDataError as exc:
        raise _run_error(exc) from exc
    f = data.frame
    sel = f.action.isin(SOS) if kind == "sos" else f.action.str.startswith("INTERVENE->") if kind == "intervene" \
        else f.action.isin(SOS) | f.action.str.startswith("INTERVENE->")
    rows = f[sel].sort_values("seq_idx").head(limit)
    return {"run_id": run_id, "scope": "전체" if data.team is None else f"{data.team} 제대만", "kind": kind,
            "total_matching": int(sel.sum()), "shown": len(rows),
            "events": [{"minute": int(r.turn_idx) * 10, "agent": r.agent_id, "action": r.action} for r in rows.itertuples()]}


async def run_sql_analysis(ctx: ToolContext, args: dict) -> dict:
    report = args.get("report")
    if report not in QUERIES and report != "all":
        raise ToolError(f"'report' 는 {sorted(QUERIES)} 중 하나여야 합니다.")
    run_id = await _resolve_run_id(ctx, args)
    result = await run_report(ctx.db, run_id)
    if not result["queue_by_turn"]:
        raise ToolError("아직 저장된 이동 기록이 없습니다.")
    return {"run_id": run_id, "report": report, "data": result if report == "all" else {report: result[report]},
            "units": "turn_idx, sos_turn, *_turns 는 모두 '10분 단위 턴' 수다. 분으로 말하려면 x10 한다 (턴 3 = 30분)."}


async def compare_modes(ctx: ToolContext, args: dict) -> dict:
    runs = await _latest_runs(ctx)
    rows = await mode_comparison(ctx.db, runs[0].mission_id)
    for r in rows:                                   # 턴(10분 단위)을 그대로 두면 모델이 "9턴"을 "9분"으로 읽는다 (실제 Gemini 평가에서 발견)
        r["mission_minutes"] = r.pop("turns") * 10
    return {"mission_id": runs[0].mission_id, "modes": rows,
            "basis": "같은 임무, 같은 시드로 모드별 1회씩 실행한 기록 (통계적 비교가 아님)",
            "units": "mission_minutes 는 분, red_pct 는 %"}


async def get_optimization_results(ctx: ToolContext, args: dict) -> dict:
    if not PARETO_PATH.exists():
        raise ToolError("최적화 결과 파일이 없습니다 (backend/scripts/run_nsga2.py 로 만든다).")
    d = json.loads(PARETO_PATH.read_text(encoding="utf-8"))
    pick = lambda v: {k: v[k] for k in ("arrival", "arrival_ci95", "arrival_p5", "v1", "v1_ci95", "v2", "v2_ci95", "v3", "v3_ci95", "sos") if k in v}
    return {
        "meta": {k: d["meta"][k] for k in ("scales", "val_seeds", "min_arrival", "total_ugv", "pop", "gens") if k in d["meta"]},
        "caveat": ("평균 ± 95% 신뢰구간. 구간이 겹치면 차이를 단정할 수 없다. 날씨 데이터는 한 사례를 강도만 바꿔 쓴 것이며 "
                   "사고 확률 등은 가정값이다."),
        "optimized": {mode: {"formation": d["front"][i]["formation"], "assignment": d["front"][i]["assignment"], **pick(d["front"][i]["validation"])}
                      for mode, i in d["archetypes"].items()},
        "references": {name: pick(v) for name, v in d["references"].items()},
    }


async def get_forecast_quality(ctx: ToolContext, args: dict) -> dict:
    if not FORECAST_SKILL_PATH.exists():
        raise ToolError("예보 오차 분석 파일이 없습니다 (backend/scripts/make_weather_report.py 로 만든다).")
    t = json.loads(FORECAST_SKILL_PATH.read_text(encoding="utf-8"))["total"]
    keep = {0, 30, 60, 90, 120, 170}
    return {
        "forecast_issue_times": t["models"],
        "by_lead": [r for r in t["by_lead"] if r["lead_min"] in keep],
        "mean_skill": t["mean_skill"], "share_leads_better_than_persistence": t["share_leads_better_than_persistence"],
        "how_to_read": "skill = 1 - MAE(예보)/MAE(지속성). 음수면 예보가 지속성(발표 시각 실황 유지)보다 나쁘다. 편향이 음수면 위험을 낮게 본 것.",
        "caveat": "예보 발표 시각이 3개뿐이고 모두 같은 밤의 사례다.",
    }


# ── 레지스트리 ───────────────────────────────────────────────────────────

_RUN_ARGS = {
    "run_id": {"type": "integer", "description": "실행 번호. 생략하면 가장 최근 임무에서 mode 의 실행을 쓴다."},
    "mode": {"type": "string", "enum": list(SERVER_MODES), "description": "balanced(균형) | recon(정밀) | rapid(신속). 생략하면 balanced."},
}
BOTH = ("commander", "operator")

TOOLS: dict[str, ToolSpec] = {t.name: t for t in [
    ToolSpec("list_runs", "가장 최근 임무의 실행(run) 목록과 모드, 상태를 본다. 어떤 run_id 가 있는지 모를 때 먼저 쓴다.",
             {"type": "object", "properties": {}}, BOTH, list_runs),
    ToolSpec("get_run_summary", "한 실행의 요약 지표(도착 UGV, 작전 시간, SOS, 운용자 개입, 평균 개입 대기, 상대 고위험 구간 비율, 평균 위험도, 제대별 결과). "
             "통제관은 담당 제대 값만 받는다. 시뮬레이션 1회의 기록이다.",
             {"type": "object", "properties": _RUN_ARGS}, BOTH, get_run_summary),
    ToolSpec("get_run_events", "한 실행의 SOS/운용자 개입 사건을 시간순으로 본다 (언제, 누가, 무슨 일). 통제관은 담당 제대만.",
             {"type": "object", "properties": {**_RUN_ARGS,
              "kind": {"type": "string", "enum": ["sos", "intervene", "all"], "description": "사건 종류. 기본 all."},
              "limit": {"type": "integer", "description": f"최대 {EVENT_LIMIT}건. 기본 15."}}}, BOTH, get_run_events),
    ToolSpec("run_sql_analysis", "실행 기록의 SQL 분석(제대별 SOS, 개입 대기, 대기열 병목, 고위험 비율, SOS 위험 지점, 위험도별 SOS 비율). "
             "제대를 가로지르는 집계라 지휘관 전용.",
             {"type": "object", "properties": {**_RUN_ARGS, "report": {"type": "string", "enum": sorted(QUERIES) + ["all"],
              "description": "보고서 이름 또는 all"}}, "required": ["report"]}, ("commander",), run_sql_analysis),
    ToolSpec("compare_modes", "가장 최근 임무의 균형/정밀/신속 실행을 SOS, 개입, 작전 시간, 고위험 비율로 비교한다. 지휘관 전용. 1회 실행 비교다.",
             {"type": "object", "properties": {}}, ("commander",), compare_modes),
    ToolSpec("get_optimization_results", "NSGA-II 최적화 결과: 신속/정밀/균형 전술의 편성과 몬테카를로 검증 성능(평균 ± 95% 신뢰구간)을 기준 전술과 비교. "
             "통계적으로 말할 수 있는 것과 없는 것을 구분하려면 반드시 이 도구의 신뢰구간을 쓴다.",
             {"type": "object", "properties": {}}, BOTH, get_optimization_results),
    ToolSpec("get_forecast_quality", "저장소 위험도 예보의 정확도(리드타임별 오차와 지속성 기준선 대비 skill).",
             {"type": "object", "properties": {}}, BOTH, get_forecast_quality),
]}


def visible_tools(role: str) -> list[ToolSpec]:
    """이 역할이 쓸 수 있는 도구만 (모델에게 보여 주는 목록)."""
    return [t for t in TOOLS.values() if role in t.roles]


async def execute_tool(ctx: ToolContext, call: ToolCall, evidence_id: str) -> Evidence:
    """도구를 실행해 근거를 만든다. 권한이 없거나 오류여도 예외를 던지지 않고 근거에 기록한다 (모델이 보고 대응한다)."""
    spec = TOOLS.get(call.name)
    if spec is None:
        return Evidence(evidence_id, call.name, call.args, {"error": f"알 수 없는 도구: {call.name}"}, error="unknown tool")
    if ctx.role not in spec.roles:                                  # 모델이 보이지 않는 도구를 불러도 막는다
        msg = f"권한 없음: '{call.name}' 은(는) {'/'.join(spec.roles)} 만 쓸 수 있습니다."
        return Evidence(evidence_id, call.name, call.args, {"error": msg}, denied=True, error=msg)
    try:
        result = jsonable(await spec.handler(ctx, call.args))
        return Evidence(evidence_id, call.name, call.args, result)
    except ToolError as exc:
        return Evidence(evidence_id, call.name, call.args, {"error": str(exc)}, error=str(exc))
