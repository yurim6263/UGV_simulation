"""
backend/scripts/extract_era5_scenario.py

ERA5-Land 월별 파일(2018~2022)에서 시나리오 날짜 조각을 잘라 backend/data/weather/era5_scenario.nc 로 저장한다.
"기상 악영향" 지표(app/weather/scenario_index.py)가 이 파일을 읽는다. 작아서(약 100KB) git 에 둔다.

    cd backend
    python scripts/extract_era5_scenario.py [--start 2022-08-19T00:00] [--end 2022-08-21T06:00]

앞날부터 자르는 이유: 강수 tp 는 UTC 0시부터의 누적값(01시 초기화)이라 시간당 강수를 만들려면 앞 시각이 필요하고, 안개 식은 최근 3시간 강수를 쓴다.
원본(WEATHER_ERA5_DIR, 기본 final_project/ERA5_기상데이터_자료/ERA5_land)은 저장소에 없다.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    import numpy as np

    from app.weather.dataset import LAT_RANGE, LON_RANGE, era5_dir
    from app.weather.era5 import open_month

    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default="2022-08-19T00:00")
    ap.add_argument("--end", default="2022-08-21T06:00")
    ap.add_argument("--out", default=str(BACKEND / "data" / "weather" / "era5_scenario.nc"))
    args = ap.parse_args()
    t0, t1 = np.datetime64(args.start), np.datetime64(args.end)
    months = sorted({str(t0)[:7], str(t1)[:7]})
    import xarray as xr

    parts = []
    for ym in months:
        y, m = ym.split("-")
        parts.append(open_month(era5_dir() / f"ERA5_land_{y}_{m}.nc", ("tp", "t2m", "d2m", "u10", "v10", "swvl1"), LAT_RANGE, LON_RANGE))
    ds = xr.concat(parts, dim="valid_time").sortby("valid_time").sel(valid_time=slice(t0, t1))
    work = Path(tempfile.mkdtemp(prefix="era5_x_"))              # 한글 경로에서는 netCDF4 가 못 쓴다
    ds.to_netcdf(work / "x.nc")
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy(work / "x.nc", out)
    shutil.rmtree(work, ignore_errors=True)
    print(f"저장: {out}  ({ds.sizes['valid_time']}시간 {args.start} ~ {args.end}, {ds.sizes['latitude']}x{ds.sizes['longitude']}칸)")


if __name__ == "__main__":
    main()
