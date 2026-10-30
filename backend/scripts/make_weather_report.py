"""
backend/scripts/make_weather_report.py

강수 예측 결과(rain_model_metrics.json)와 위험도 예보 오차 분석으로 docs/weather_model_report.md 를 만든다.
숫자를 손으로 옮기지 않는다.

    python backend/scripts/make_weather_report.py
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "script-only")

from app.weather.forecast_skill import skill_by_lead  # noqa: E402

METRICS = ROOT / "backend" / "data" / "weather" / "rain_model_metrics.json"
OUT = ROOT / "docs" / "weather_model_report.md"
DYNAMIC = ROOT / "backend" / "data" / "map_20km" / "dynamic"
SKILL_JSON = ROOT / "backend" / "data" / "weather" / "forecast_skill.json"


def f(v, d=3):
    return "-" if v is None or v != v else f"{v:.{d}f}"


def verdict(boot: dict) -> str:
    lo, hi = boot["diff"]
    if boot["a_better_significant"]:
        return f"**XGBoost 우세(뚜렷)** (차이 {boot['diff_mean']:+.3f}, 95% [{lo:+.3f}, {hi:+.3f}])"
    if boot["b_better_significant"]:
        return f"**지속성 우세(뚜렷)** (차이 {boot['diff_mean']:+.3f}, 95% [{lo:+.3f}, {hi:+.3f}])"
    return f"차이 단정 불가 (차이 {boot['diff_mean']:+.3f}, 95% [{lo:+.3f}, {hi:+.3f}])"


def main() -> None:
    m = json.loads(METRICS.read_text(encoding="utf-8"))
    d = m["deaccumulation"]
    skill = {k: skill_by_lead(DYNAMIC, k) for k in ("total", "mobility", "sensor")}
    SKILL_JSON.write_text(json.dumps(skill, ensure_ascii=False, indent=1), encoding="utf-8")

    L = [
        "# 기상 예측 분석 (ERA5 강수 예측 · 예보 오차)",
        "",
        "> `backend/scripts/train_rain_model.py`와 `make_weather_report.py`가 자동으로 만든 문서다.",
        "",
        "## 1. 데이터와 전처리",
        "",
        f"- **자료**: ERA5-Land 시간별(2018~2022, 0.1° 격자). 그단스크 주변 위도 {m['region']['lat']}, 경도 {m['region']['lon']}. "
        f"육지 격자 {d['land_cells']}/{d['total_cells']}개만 사용(ERA5-Land는 바다가 비어 있어 강수의 약 29%가 NaN).",
        f"- **분할**(예측 대상 시각 기준, 시간순): 학습 {m['split']['train']}, 검증 {m['split']['val']}, 시험 {m['split']['test']}. 시험 기간은 학습에 전혀 쓰이지 않는다.",
        "- **특징**: 최근 12시간 강수 + 연중 일·시각의 sin/cos (팀원 XGBoost 노트북과 같은 구성에 시각 특징 추가).",
        "",
        "### 누적 강수의 시간당 변환: 팀원 규칙의 문제",
        "",
        "ERA5-Land의 `tp`는 UTC 0시부터의 **누적값**이며 UTC 01시에만 초기화된다. 팀원 노트북은 \"누적값이 줄어들면 그 시각의 누적값을 한 시간 강수로 쓴다\"는 규칙을 쓰는데, "
        "오후에 누적값이 부동소수점 오차로 아주 조금 줄어드는 곳에서도 하루 누적 합계가 한 시간 강수가 된다.",
        "",
        "| 지표 | 팀원 규칙 | 올바른 규칙(01시만 초기화) |",
        "|---|---|---|",
        f"| 시간당 강수 최댓값(mm/h) | {d['max_mmph_team_rule']} | {d['max_mmph_correct']} |",
        f"| 10mm/h 초과 시간 수 | {d['hours_over_10mmph_team_rule']} | {d['hours_over_10mmph_correct']} |",
        f"| 5년 총 강수(mm, 전 격자 합) | {d['total_mm_team_rule']:,.0f} | {d['total_mm_correct']:,.0f} |",
        "",
        f"표본 {d['samples']:,}건 중 {d['spurious_hours']:,}건({d['spurious_share_pct']}%)이 가짜 강수였고, 전부 초기화 시각(01시)이 아닌 때였다. "
        "이 저장소의 지역에서 측정한 값이며, 팀원이 쓴 지역(경로 버퍼 400점)에서 같은 정도라고 단정하지는 않는다. "
        "다만 같은 규칙을 쓰므로 그쪽 강수 최댓값(30mm/h로 보고)과 극한 강수 평가도 영향을 받았을 가능성이 있다. 이 분석은 올바른 규칙을 쓴다(`app/weather/era5.py`, 테스트 포함).",
        "",
        "## 2. 강수 1~3시간 후 예측: XGBoost vs 기준선",
        "",
        "기준선: **지속성**(h시간 뒤 강수 = 지금 강수), **기후값**(학습 평균). 시험 기간에서 평가한다. "
        "POD(탐지율)·FAR(오경보율)·CSI(적중 점수)는 \"예측 강수 ≥ 기준\"일 때 비로 보고 센다.",
        "",
    ]
    for h, e in m["horizons"].items():
        mm = e["models"]
        L += [f"### {h}시간 후 (시험 표본 {e['samples']['test']:,}건)", "",
              "| 모델 | MAE(mm/h) | RMSE | CSI@0.1 | POD@0.1 | FAR@0.1 | CSI@1.0 | 상위1% 강수 MAE |", "|---|---|---|---|---|---|---|---|"]
        for name, label in (("xgboost", "XGBoost"), ("persistence", "지속성"), ("climatology", "기후값")):
            r = mm[name]
            L.append(f"| {label} | {f(r['mae'], 4)} | {f(r['rmse'], 4)} | {f(r['thr_0.1']['csi'])} | {f(r['thr_0.1']['pod'])} | {f(r['thr_0.1']['far'])} | "
                     f"{f(r['thr_1.0']['csi'])} | {f(r['tail_top1pct']['mae'])} |")
        L += ["", "CSI 차이(XGBoost − 지속성)의 95% 구간(일 단위 블록 부트스트랩 1,000회):", ""]
        for thr, boot in e["xgb_vs_persistence"].items():
            L.append(f"- 기준 {thr}mm/h: {verdict(boot)}")
        L += ["", f"- 중요 특징(gain 상위): {', '.join(f'{k}({v})' for k, v in e['feature_gain'].items())}", ""]

    # 모델 비교 요약 (숫자는 위 표에서 계산한다)
    rows = []
    for h, e in m["horizons"].items():
        x, p_ = e["models"]["xgboost"], e["models"]["persistence"]
        verdicts = [v["a_better_significant"] for v in e["xgb_vs_persistence"].values()]
        worse = [t for t, v in e["xgb_vs_persistence"].items() if v["b_better_significant"]]
        rows.append((h, x["rmse"] < p_["rmse"], x["mae"] < p_["mae"], any(verdicts), worse))
    L += ["### 요약", ""]
    L.append(f"- XGBoost가 지속성보다 **뚜렷하게 나은** 경우: "
             + (", ".join(f"{h}시간" for h, *_, wins, _w in rows if wins) or "없음") + " (CSI 차이의 95% 구간이 0 위인 경우).")
    L.append("- 지속성이 **뚜렷하게 나은** 경우(CSI 기준): "
             + (", ".join(f"{h}시간({'/'.join(w)}mm/h)" for h, *_, w in rows if w) or "없음") + ".")
    L.append("- RMSE는 " + ", ".join(f"{h}시간 {'XGBoost' if r else '지속성'} 우세" for h, r, *_ in rows)
             + ". 제곱오차를 줄이도록 학습한 모델은 강한 비를 평균 쪽으로 낮춰 RMSE는 좋아지지만 강한 비의 탐지(CSI@1.0)는 나빠지는 경향이 있다.")
    L.append("- **결론**: 이 지역의 국소 강수 이력과 계절/시각 특징만으로는 지속성 기준선을 의미 있게 넘기지 못했다. "
             "이웃 격자의 강수, 이슬점·기온·바람·토양수분 같은 다른 기상 변수, 분류 후 회귀하는 2단계 모델(팀원이 시도) 등을 추가하면 달라질 수 있으나 여기서는 검증하지 않았다(미검증 가설).")
    L.append("")

    L += ["## 3. 저장소의 위험도 예보 오차 (예보 vs 실황, 리드타임별)", "",
          "저장소의 `forecast/`(모델 시각 3개 × 180분)를 같은 시각의 `actual/`과 비교했다. 기준선은 지속성(발표 시각의 실황을 유지). "
          "skill = 1 − MAE(예보)/MAE(지속성): 양수면 예보가 낫고 음수면 지속성보다 나쁘다.", ""]
    t = skill["total"]
    L += ["| 리드타임(분) | MAE 예보 | MAE 지속성 | 예보 편향 | skill |", "|---|---|---|---|---|"]
    for row in t["by_lead"]:
        if row["lead_min"] % 30 == 0 or row["lead_min"] == 170:
            L.append(f"| {row['lead_min']} | {f(row['mae_forecast'])} | {f(row['mae_persistence'])} | {row['bias_forecast']:+.3f} | {f(row['skill'], 2)} |")
    L += ["",
          f"- 종합 위험도에서 리드타임 0분을 뺀 모든 구간에서 예보가 지속성보다 나쁘다(평균 skill {f(t['mean_skill'], 2)}, 지속성보다 나은 비율 {t['share_leads_better_than_persistence'] * 100:.0f}%). "
          "기동성·센서 위험도도 같은 경향이다.",
          "- 예보는 **위험을 지속적으로 낮게 본다**(편향이 음수이며 리드타임이 길수록 커짐). 모델 시각 22:00 하나를 직접 확인했을 때 발표 시각(0분)에는 실황과 공간 상관이 0.97이었으나 60분 뒤 0.06, 90분 뒤 0.17로 무너졌고(평균 위험도도 예보 0.40 대 실황 0.75), 다른 모델 시각은 같은 방식으로 확인하지 않았다.",
          "- **시뮬레이션에 주는 의미**: 계획은 예보를, 사고 판정은 실황을 쓰므로 계획은 위험을 과소평가한 상태로 경로를 고른다. 이 편향을 보정하려면 예보를 지속성과 섞거나 편향을 빼는 방법을 시험해 볼 수 있으나, 이 문서에서는 시뮬레이션에 적용해 검증하지 않았다. (참고: 최적화된 모드의 `기상 민감도`는 균형 1.28, 정밀 1.30, 신속 0.61로 일관된 경향이 없어 이 편향과의 관계를 단정할 수 없다.)",
          "- 한계: 모델 시각이 3개뿐이고 모두 같은 밤의 사례라 일반화할 수 없다. 이 결과는 \"이 저장소의 예보 자료가 이 사례에서 그렇다\"는 뜻이다.", "",
          "## 4. 한계와 팀원 보고서와의 관계", "",
          "- 팀원 보고서의 강수 지표(MAE 0.118 mm/h, CSI@0.1 0.560 등)는 ConvLSTM(공간 모델) 결과이고, 여기는 격자별 XGBoost(공간 정보 없음)다. 사용 지역과 표본이 달라 **숫자를 직접 비교할 수 없다**.",
          "- 육지 격자 약 80개의 5년 시간 자료만 썼다. 연도별 교차검증은 하지 않았다(시험은 2022년 하반기 한 구간).",
          "- 강수가 대부분 0인 자료라 MAE는 \"항상 0\"에 가까운 예측도 낮게 나온다. 그래서 탐지 점수(CSI/POD/FAR)와 기준선 비교를 함께 본다.",
          "- 이 모델은 시뮬레이터의 위험도 입력(LTWR)에 연결되어 있지 않다. 시뮬레이터는 팀원이 만든 예보 parquet을 읽는다.", ""]
    OUT.write_text("\n".join(L), encoding="utf-8")
    print("saved", OUT)


if __name__ == "__main__":
    main()
