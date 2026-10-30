"""
backend/scripts/download_era5_scenario.py

시나리오 날짜의 ERA5-Land(시간별, 0.1°) 원시 기상을 내려받아 backend/data/weather/era5_scenario.nc 로 저장한다.
"기상 악영향" 지표(app/weather/scenario_index.py)가 이 파일을 읽는다. 저장소에는 ERA5 가 2018~2022년뿐이라 시나리오 날짜(2023-06-30 등)가 없다.

준비 (한 번): pip install cdsapi, 그리고 본인의 Copernicus CDS 계정 키를 ~/.cdsapirc 에 둔다.
키는 이 스크립트나 저장소에 쓰지 않는다 (cdsapi 가 그 파일을 읽는다). 계정과 데이터셋 이용 약관 동의가 필요하다.

    cd backend
    python scripts/download_era5_scenario.py --dates 2023-06-30 2023-07-01

- 첫 날의 앞날(전날)도 함께 받는다: 강수(tp)는 UTC 0시부터의 누적값이라 시간당 강수를 만들려면 앞 시각이 필요하다.
- 시나리오 날짜 표기가 2023-06-30(위험도 지도), 2023-07-26(사례 폴더명), 2024-07-03(노트북)로 엇갈린다. 어느 날이 맞는지 모르면 후보를 각각
  --out 으로 다른 파일에 받아 `check_weather_alignment.py --file ...` 로 위험도의 시간 변화와 맞는 쪽을 고른다.
- 작전 구역은 위도 54.30~54.52, 경도 18.27~18.64 이다. 0.1° 격자라 여유를 두고 받는다.
"""

from __future__ import annotations

import argparse
import shutil
import sys
import tempfile
from datetime import date, timedelta
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
DEFAULT_OUT = BACKEND / "data" / "weather" / "era5_scenario.nc"
VARIABLES = ["total_precipitation", "2m_temperature", "2m_dewpoint_temperature",
             "10m_u_component_of_wind", "10m_v_component_of_wind", "volumetric_soil_water_layer_1"]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dates", nargs="+", required=True, help="받을 날짜 (UTC, YYYY-MM-DD). 시나리오가 자정을 넘기면 둘 다 적는다")
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--area", nargs=4, type=float, default=[54.8, 18.0, 54.0, 19.0], metavar=("N", "W", "S", "E"))
    args = ap.parse_args()

    try:
        import cdsapi
        import xarray as xr
    except ImportError as exc:
        sys.exit(f"{exc.name} 가 필요합니다: pip install cdsapi")

    days = sorted({date.fromisoformat(d) for d in args.dates})
    days = [days[0] - timedelta(days=1)] + days                     # 강수 누적값을 풀기 위한 앞날
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    client = cdsapi.Client()
    work = Path(tempfile.mkdtemp(prefix="era5_dl_"))          # 한글이 든 경로에서는 netCDF4 가 파일을 못 연다(OSError 22). ASCII 임시 폴더에서 다룬다
    parts = []
    for d in days:
        part = work / f"part_{d:%Y%m%d}.nc"
        client.retrieve("reanalysis-era5-land", {
            "variable": VARIABLES, "year": [f"{d:%Y}"], "month": [f"{d:%m}"], "day": [f"{d:%d}"],
            "time": [f"{h:02d}:00" for h in range(24)], "area": args.area, "data_format": "netcdf", "download_format": "unarchived",
        }, str(part))
        parts.append(part)
        print(f"받음: {d}")
    ds = xr.concat([xr.open_dataset(p) for p in parts], dim="valid_time").sortby("valid_time").load()
    merged = work / "merged.nc"
    ds.to_netcdf(merged)
    ds.close()
    shutil.copy(merged, out)
    shutil.rmtree(work, ignore_errors=True)
    print(f"저장: {out}  ({ds.sizes['valid_time']}시간, {ds.sizes['latitude']}x{ds.sizes['longitude']}칸)")
    print("다음: python scripts/check_weather_alignment.py  (위험도의 시간 변화와 맞는지 확인)")


if __name__ == "__main__":
    main()
