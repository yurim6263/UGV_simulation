"""
backend/scripts/forecast_skill_report.py

위험도 예보(forecast/)가 같은 시각의 실황(actual/)과 얼마나 맞는지(리드타임별 MAE, 지속성 기준선 대비 skill)를 계산해
backend/data/weather/forecast_skill_<데이터셋 폴더>.json 으로 저장한다. AI 어시스턴트의 get_forecast_quality 도구가 활성 데이터셋의 이 파일을 읽는다.

    cd backend
    python scripts/forecast_skill_report.py [--dataset map_20km_rebuilt]

팀 원본 데이터(map_20km)의 분석과 해석 문서는 scripts/make_weather_report.py 가 만든다 (docs/weather_model_report.md).
우리가 직접 만든 데이터(map_20km_rebuilt)에서 실황은 ERA5 값으로, 예보는 ConvLSTM 예측으로 만든 레이어이므로, 이 skill 은
"위험도 레이어 수준에서 ConvLSTM 예보가 지속성보다 나은가"를 보여 준다 (날씨 변수 수준의 평가는 docs/weather_convlstm.md).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("JWT_SECRET_KEY", "script-only")


def main() -> None:
    from app.weather.forecast_skill import skill_by_lead

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", default="map_20km_rebuilt")
    args = ap.parse_args()
    dynamic = BACKEND / "data" / args.dataset / "dynamic"
    skill = {k: skill_by_lead(dynamic, k) for k in ("total", "mobility", "sensor")}
    out = BACKEND / "data" / "weather" / (f"forecast_skill_{args.dataset}.json" if args.dataset != "map_20km" else "forecast_skill.json")
    out.write_text(json.dumps(skill, ensure_ascii=False, indent=1), encoding="utf-8")
    for kind, t in skill.items():
        print(f"{kind}: 평균 skill {t['mean_skill']:.2f}, 지속성보다 나은 리드타임 비율 {t['share_leads_better_than_persistence']:.2f}, 모델 시각 {t['models']}")
    print("저장:", out)


if __name__ == "__main__":
    main()
