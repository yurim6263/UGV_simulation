"""
backend/scripts/make_report.py

최적화 결과(pareto.json)에서 보고서(docs/optimization_report.md)를 만든다. 숫자를 손으로 옮기지 않는다.

    python backend/scripts/make_report.py
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
LABEL = {"rush": "신속", "balance": "균형", "explore": "정밀"}
REF_LABEL = {
    "reference_balance": "팀원 기준 · 균형 (3-4-2)", "reference_explore": "팀원 기준 · 정밀 (3-3-3)",
    "reference_rush": "팀원 기준 · 신속 (4-2-3)", "weather_blind": "날씨 무시 기준선 (3-4-2)",
}


def pct(v: float, ci: float | None = None, digits: int = 0) -> str:
    return f"{v * 100:.{digits}f}%" + (f" ±{ci * 100:.{digits}f}" if ci is not None else "")


def row(name: str, v: dict) -> str:
    return (f"| {name} | {pct(v['arrival'], v['arrival_ci95'])} | {pct(v['arrival_p5'])} | "
            f"{pct(v['v1'], v['v1_ci95'], 1)} | {v['v2']:.0f} ±{v['v2_ci95']:.0f} | {v['v3']:.1f} ±{v['v3_ci95']:.1f} | {v['sos']:.1f} |")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", type=Path, default=ROOT / "backend" / "data" / "optimization" / "pareto.json")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "optimization_report.md")
    args = ap.parse_args()
    d = json.loads(args.data.read_text(encoding="utf-8"))
    m, front, arche, refs = d["meta"], d["front"], d["archetypes"], d["references"]
    n_val = len(m["val_seeds"]) * len(m["scales"])
    header = "| 전술 | 도착률 | 도착률 하위 5% | 수색 면적(V1) | 작전 시간(V2, 분) | 운용자 과부하(V3, 분) | SOS 건수 |\n|---|---|---|---|---|---|---|"

    lines = [
        "# 전술 최적화 결과 (NSGA-II + 몬테카를로)",
        "",
        "> 이 문서는 `backend/scripts/make_report.py`가 `backend/data/optimization/pareto.json`에서 자동으로 만든다.",
        "",
        "> **이 보고서의 쓰임 (편성 계산기 도입 이후)**: 아래의 편성(제대별 UGV 수)과 제대-목표 배정은 팀원 시나리오의 **기본 목표 3곳**에서 찾은 값이다. "
        "서버 실행은 이 편성·배정을 쓰지 않고, 편성은 목표 위치에서 계산하고(`docs/formation_planner.md`) 배정은 입력 순서(목표 i → i제대)로 한다. "
        "이 보고서에서 서버 실행에 쓰이는 것은 모드의 **전술 성향(유전자)**뿐이며, 표의 숫자는 기본 목표에서의 비교 실험 결과로 읽어야 한다.",
        "",
        "## 1. 무엇을 최적화했나",
        "",
        "- **탐색 변수**: 제대별 UGV 수(총 %d대, 제대당 2~5), 제대별 목표 배정(순열 6가지), 산개 가중치, 기상 민감도, 제대별 출격 지연(0~4턴), 목줄 임계값(대기/복귀)." % m["total_ugv"],
        "- **목표**: V1 수색 면적 비율(최대화), V2 작전 시간(최소화), V3 운용자 과부하 시간(최소화) — 세 목표가 서로 상충한다.",
        "- **제약**: 평균 도착률 ≥ %s (생존 제약). 이를 만족하지 못하는 개체는 도태된다." % pct(m["min_arrival"]),
        "- **평가 방법**: 한 개체를 시나리오 강도 %s × 시드 %s(공통 난수)로 %d회 평가한 평균을 목표값으로 쓴다." % (m["scales"], m["train_seeds"], len(m["scales"]) * len(m["train_seeds"])),
        "- **탐색 설정**: 개체 %d, %d세대(총 평가 %d회), 초기 개체에 팀원 기준 프리셋 3종을 포함. 소요 %d분." % (m["pop"], m["gens"], d["history"][-1]["evals"], round(m["elapsed_sec"] / 60)),
        "",
        "## 2. 검증 방법",
        "",
        "최적화에 쓰지 않은 **새 시드 %d개 × 강도 %d개 = %d회**의 몬테카를로로 모든 파레토 해와 비교 대상을 다시 평가했다. "
        "표의 값은 평균 ± 95%% 신뢰구간이고, '도착률 하위 5%%'는 최악의 경우에도 얼마나 도착하는지(꼬리 위험)를 본다." % (len(m["val_seeds"]), len(m["scales"]), n_val),
        "",
        "## 3. 결과: 전술 메뉴 vs 비교 대상",
        "",
        header,
    ]
    for mode in ("rush", "balance", "explore"):
        if mode in arche:
            item = front[arche[mode]]
            lines.append(row(f"**최적화 · {LABEL[mode]}** ({'-'.join(map(str, item['formation']))})", item["validation"]))
    for key, v in refs.items():
        lines.append(row(REF_LABEL.get(key, key), v))

    metrics = [("arrival", "도착률", True), ("v1", "수색 면적", True), ("v2", "작전 시간", False), ("v3", "운용자 과부하", False)]

    def verdict(a: dict, b: dict, key: str, higher_better: bool) -> str:
        """a(최적화)가 b(비교 대상)보다 좋은가. 95% 신뢰구간이 겹치면 단정하지 않는다."""
        diff = a[key] - b[key]
        better = diff > 0 if higher_better else diff < 0
        if abs(diff) <= a[f"{key}_ci95"] + b[f"{key}_ci95"]:
            return "개선 방향, 구간 겹침(단정 불가)" if better else "악화 방향, 구간 겹침(단정 불가)"
        return "**뚜렷한 개선**" if better else "**뚜렷한 악화**"

    comparisons = []
    if "balance" in arche and "weather_blind" in refs:
        comparisons.append(("최적화 균형 vs 날씨 무시 기준선", front[arche["balance"]]["validation"], refs["weather_blind"]))
    for mode, ref in (("balance", "reference_balance"), ("rush", "reference_rush"), ("explore", "reference_explore")):
        if mode in arche and ref in refs:
            comparisons.append((f"최적화 {LABEL[mode]} vs 팀원 기준 {LABEL[mode]}", front[arche[mode]]["validation"], refs[ref]))

    lines += ["", "## 4. 해석", "",
              "95% 신뢰구간이 겹치면 두 값의 차이를 통계적으로 뚜렷하다고 말할 수 없다. 아래 판정은 구간이 겹치는지로만 정한다.", "",
              "| 비교 | 도착률 | 수색 면적 | 작전 시간 | 운용자 과부하 |", "|---|---|---|---|---|"]
    for name, a_v, b_v in comparisons:
        lines.append(f"| {name} | " + " | ".join(verdict(a_v, b_v, k, hb) for k, _, hb in metrics) + " |")

    clear = [f"{n}의 {lbl}" for n, a_v, b_v in comparisons for k, lbl, hb in metrics if "뚜렷한 개선" in verdict(a_v, b_v, k, hb)]
    lines.append("")
    lines.append("- **구간이 겹치지 않아 말할 수 있는 것**: " + ", ".join(clear) + "." if clear else "- 구간이 겹치지 않는 뚜렷한 개선은 없었다.")
    lines.append("- 나머지 비교는 점추정만 개선 방향일 뿐 표본(30회) 대비 변동이 커서 최적화의 이득이라고 단정할 수 없다. 시드 수를 늘리면 구간이 좁아져 판정이 바뀔 수 있다.")
    best = front[arche["balance"]]["validation"] if "balance" in arche else None
    blind = refs.get("weather_blind")
    if best and blind:
        lines.append(f"- **SOS 건수는 줄지 않았다**: 날씨 무시 기준선 {blind['sos']:.1f}건, 최적화 균형 {best['sos']:.1f}건. "
                     f"기준선은 도착률({pct(blind['arrival'])})과 수색 면적({pct(blind['v1'], None, 1)})이 모두 낮아 이동량이 적었을 가능성이 있으나, 이 실험에서는 확인하지 않았다.")
    lines += [
        f"- 대표 전술은 최적화 때의 평가값으로 골랐고(`archetype_selection: {m.get('archetype_selection', 'validation')}`), 표의 값은 선택에 쓰지 않은 새 시드의 결과다.",
        f"- 파레토 해는 {len(front)}개이며 제약 만족 여부: {'만족' if m['feasible'] else '**만족하는 해 없음** (위반이 가장 작은 해를 보여준다)'}.",
        "",
        "## 5. 세대별 진행",
        "",
        "| 세대 | 누적 평가 | 제약 만족 | 최고 V1 | 최단 V2(분) | 최소 V3(분) |",
        "|---|---|---|---|---|---|",
    ]
    for h in d["history"]:
        lines.append(f"| {h['gen']} | {h['evals']} | {h['feasible']}/{h['pop']} | "
                     f"{h.get('best_v1', float('nan')) * 100:.1f}% | {h.get('best_v2', float('nan')):.0f} | {h.get('best_v3', float('nan')):.0f} |")

    lines += [
        "",
        "## 6. 한계 (결과를 읽을 때 주의)",
        "",
        "- **날씨 데이터는 한 사례**(기본 시나리오: 그단스크 2022-08-20 밤 5시간, ERA5 실제 날씨로 우리가 직접 만든 위험도, 구역 평균 종합 위험도 0.82 → 0.56)를 강도(0.2~0.4)만 바꿔 쓴 것이다. 다른 기상 패턴에서의 일반화는 검증하지 않았다. 위험도 식은 팀 원본이 아니라 우리 정의다 (docs/ltwr_generation.md). 팀 원본 위험도(2023-06-30 사례)에서 한 이전 최적화는 data/optimization/pareto_team_map_20km.json 에 보관했다.",
        "- 사고 확률, 개입 AP, 지형 계수는 팀원 기록과 대조해 정한 **가정값**이다 (`docs/data_contract.md`). 실제 운용 데이터로 검증된 값이 아니다.",
        "- 시나리오 강도는 데이터의 위험도에 곱한 배율이라 실제 기상의 시공간 구조 변화를 모두 반영하지 않는다.",
        "- 최적화에 쓴 시드와 검증에 쓴 시드를 분리했지만, 시나리오(출발지, 정찰지, 총 9대)는 같다.",
        "- 표본 수가 작아 신뢰구간이 넓다. 같은 시드를 공유하므로 짝지은(paired) 차이로 비교하면 더 좁은 구간을 얻을 수 있으나 에피소드별 값을 저장하지 않아 하지 못했다.",
        "",
    ]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    print("saved", args.out)


if __name__ == "__main__":
    main()
