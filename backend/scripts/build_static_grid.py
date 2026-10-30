"""
backend/scripts/build_static_grid.py

정적 지형 격자(토지 피복, 품질 마스크, 도로 거리)를 원자료에서 만들고 기존(팀원) 파일과 대조한다. 방법과 한계는 app/geo/static_grid.py 참고.

    cd backend
    python scripts/build_static_grid.py [--out data/map_20km_rebuilt/static/Test_sim_input_200m_bbox_20km.parquet]

필요: ESA WorldCover 2021 N54E018 타일(WORLDCOVER_DIR), 인터넷(첫 실행에 OSM 도로를 Overpass 로 받는다, 약 1분. 캐시 data/osm/roads_raw.json).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    import pandas as pd

    from app.geo import static_grid as sg

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default=str(BACKEND / "data" / "map_20km_rebuilt" / "static" / "Test_sim_input_200m_bbox_20km.parquet"))
    ap.add_argument("--reference", default=str(BACKEND / "data" / "map_20km" / "static" / "Test_sim_input_200m_bbox_20km.parquet"))
    args = ap.parse_args()

    df = sg.build_static_grid()
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    df.to_parquet(out, index=False)
    print(f"저장: {out}  ({len(df)}칸)")
    print("토지 코드 분포:", df.lc_code.value_counts().sort_index().to_dict(), " mask_good", round(float(df.mask_good.mean()), 3), " 도로 있음", round(float(df.roads_has_drivable_road.mean()), 3))
    ref = Path(args.reference)
    if ref.exists():
        print("팀 원본과 대조:", json.dumps(sg.compare_with(df, pd.read_parquet(ref)), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
