"""
backend/scripts/export_replay.py

팀원 시뮬레이션 결과(이동 기록 CSV) + 위험도 parquet 을 프론트 재생 화면용 데이터로 변환한다.

HTML 파일 안에 섞여 있던 "데이터"와 "화면"을 분리하기 위한 스크립트:
    입력  recommended_history_enriched_{balance,explore,rush}_2.csv   (모드별 이동/이벤트 로그)
          Min_000 ~ Min_170/sim_cost_map_*.parquet                    (턴별 위험도, 모드와 무관)
    출력  <out>/scenario.json            시나리오 메타 (출발지, 정찰지, 지도 경계, 턴 길이)
          <out>/{mode}.json              모드별 이동 기록 + 로그에서 집계한 KPI
          <out>/overlay/{total|mobility|sensor}/{turn}.png   위험도 오버레이 이미지

사용 예 (프로젝트 루트에서):
    python backend/scripts/export_replay.py \\
        --csv-dir  "<final_project>/html_code/enriched_csv_path" \\
        --case-dir "<final_project>/html_code/15_Fog-driven_20230726_0300/15_Fog-driven_20230726_0300" \\
        --out frontend_js/static/replay

이후 이 JSON 형식을 그대로 API 응답으로 옮기고 DB/시뮬레이션 엔진으로 교체한다.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))

from app.simulation.replay import GAR, MODES, OVERLAY_COLUMNS, build_mode, grid_bounds, overlay_png  # noqa: E402

STATIC_PARQUET = ROOT / "backend" / "data" / "map_20km" / "static" / "Test_sim_input_200m_bbox_20km.parquet"

START = (54.48, 18.32)                                    # (lat, lon)
POIS = [(54.40, 18.54), (54.33, 18.36), (54.37, 18.50)]   # POI-1, 2, 3
TURN_MINUTES = 10


def _static() -> pd.DataFrame:
    return pd.read_parquet(STATIC_PARQUET, columns=["row", "col", "lat", "lon"])


def nearest_cell(lat: float, lon: float) -> tuple[int, int]:
    """위경도에 가장 가까운 격자 셀 (row, col)."""
    df = _static()
    d = (df.lat - lat) ** 2 + ((df.lon - lon) * np.cos(np.radians(lat))) ** 2
    r = df.loc[d.idxmin()]
    return int(r.row), int(r.col)


def bounds() -> list[list[float]]:
    df = _static()
    ny, nx = int(df.row.max()) + 1, int(df.col.max()) + 1
    lat = np.full((ny, nx), np.nan)
    lon = np.full((ny, nx), np.nan)
    lat[df.row, df.col] = df.lat
    lon[df.row, df.col] = df.lon
    return grid_bounds(lat, lon)


def export_overlays(case_dir: Path, out: Path) -> int:
    """턴별 위험도 parquet → G/A/R PNG. 등급 기준은 전 턴 공통(30/70 분위수)이라 턴 간 비교가 가능하다."""
    mins = sorted(d for d in os.listdir(case_dir) if d.startswith("Min_"))
    frames = []
    for d in mins:
        pq = glob.glob(str(case_dir / d / "sim_cost_map_*.parquet"))
        if not pq:
            raise FileNotFoundError(f"{d} 에 sim_cost_map parquet 이 없습니다.")
        frames.append(pd.read_parquet(pq[0]))

    ny = int(max(f.row.max() for f in frames)) + 1
    nx = int(max(f.col.max() for f in frames)) + 1
    for kind, col in OVERLAY_COLUMNS.items():
        lo, hi = np.percentile(np.concatenate([f[col].to_numpy(dtype=np.float32) for f in frames]), [30, 70])
        (out / "overlay" / kind).mkdir(parents=True, exist_ok=True)
        for turn, f in enumerate(frames):
            grid = np.full((ny, nx), np.nan, dtype=np.float32)
            grid[f.row.to_numpy(int), f.col.to_numpy(int)] = f[col].to_numpy(dtype=np.float32)
            overlay_png(grid, lo, hi).save(out / "overlay" / kind / f"{turn}.png", optimize=True)
    return len(frames)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--csv-dir", required=True, type=Path)
    ap.add_argument("--case-dir", required=True, type=Path)
    ap.add_argument("--out", required=True, type=Path)
    args = ap.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)

    turns = export_overlays(args.case_dir, args.out)
    poi_cells = [nearest_cell(lat, lon) for lat, lon in POIS]
    for mode, label in MODES.items():
        df = pd.read_csv(args.csv_dir / f"recommended_history_enriched_{mode}_2.csv", encoding="utf-8-sig")
        data = build_mode(df, mode, label, poi_cells)
        (args.out / f"{mode}.json").write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        k = data["kpi"]
        print(f"{mode:8s} steps={len(data['steps']):5d} arrived={k['ugv_arrived']}/{k['ugv_total']} "
              f"sos={k['sos_events']} intervene={k['interventions']} wait={k['wait_turns_mean']}")

    scenario = {
        "case": "저시정(Fog-driven) 사례 · 팀원 시뮬레이션 기록",
        "turn_minutes": TURN_MINUTES,
        "turns": turns,
        "bounds": bounds(),
        "start": START,
        "pois": [{"id": i + 1, "lat": p[0], "lon": p[1]} for i, p in enumerate(POIS)],  # 어느 제대가 어느 POI 로 가는지는 모드마다 다르다 (kpi.per_team.poi)
        "modes": [{"key": k, "label": v} for k, v in MODES.items()],
        "overlays": [{"key": "total", "label": "종합 위험도"},
                     {"key": "mobility", "label": "기동성 위험도"},
                     {"key": "sensor", "label": "센서 위험도"}],
    }
    (args.out / "scenario.json").write_text(json.dumps(scenario, ensure_ascii=False, indent=1), encoding="utf-8")
    print("overlay turns:", turns, "→", args.out)


if __name__ == "__main__":
    main()
