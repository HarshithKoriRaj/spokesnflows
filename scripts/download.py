"""Download every dataset the project uses into data/raw/.

Usage:
    python scripts/download.py                 # Jan, Jul, Oct 2025 (the months we use) + supporting data
    python scripts/download.py --months 1 2 3  # any other set of 2025 months
    python scripts/download.py --skip-trips    # supporting data only

Files that already exist are skipped, so the script is safe to re-run.
"""
import argparse
import json
import sys
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"

TRIP_BUCKET = "https://s3.amazonaws.com/tripdata/"
GBFS_INDEX = "https://gbfs.citibikenyc.com/gbfs/2.3/gbfs.json"
NTA_GEOJSON = ("https://data.cityofnewyork.us/api/v3/views/9nt8-h7nd/"
               "query.geojson?accessType=DOWNLOAD")
NOAA_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
CENTRAL_PARK = "USW00094728"


def fetch(url, dest, params=None, stream=False):
    """Download url to dest unless dest already exists. Returns True on success."""
    if dest.exists() and dest.stat().st_size > 0:
        print(f"  exists, skipping: {dest.relative_to(ROOT)}")
        return True
    dest.parent.mkdir(parents=True, exist_ok=True)
    try:
        r = requests.get(url, params=params, stream=stream, timeout=120)
    except requests.RequestException as e:
        print(f"  failed: {url} ({e})")
        return False
    if r.status_code != 200:
        print(f"  HTTP {r.status_code}: {r.url}")
        return False
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as f:
        if stream:
            done = 0
            for chunk in r.iter_content(chunk_size=1 << 20):
                f.write(chunk)
                done += len(chunk)
                print(f"\r  {dest.name}: {done / 1e6:,.0f} MB", end="", flush=True)
            print()
        else:
            f.write(r.content)
    tmp.rename(dest)
    print(f"  saved {dest.relative_to(ROOT)}")
    return True


def download_trips(year, months):
    print(f"Citi Bike trips, {year}, months {months}")
    out = RAW / "trips"
    missing = []
    for m in months:
        ym = f"{year}{m:02d}"
        # 2025 files are named YYYYMM-citibike-tripdata.zip; older years used .csv.zip
        candidates = [f"{ym}-citibike-tripdata.zip", f"{ym}-citibike-tripdata.csv.zip"]
        if any((out / c).exists() for c in candidates):
            print(f"  exists, skipping: {ym}")
            continue
        if not any(fetch(TRIP_BUCKET + c, out / c, stream=True) for c in candidates):
            missing.append(ym)
    if missing:
        print("\nCould not download:", ", ".join(missing))
        print("Download them by hand from https://s3.amazonaws.com/tripdata/index.html")
        print(f"(NYC files, not the JC- ones) and put the .zip files in {out}")


def download_gbfs():
    print("Citi Bike station information (GBFS)")
    try:
        feeds = requests.get(GBFS_INDEX, timeout=60).json()["data"]["en"]["feeds"]
        url = next(f["url"] for f in feeds if f["name"] == "station_information")
    except Exception as e:  # fall back to the usual location
        print(f"  could not read feed index ({e}); using default URL")
        url = "https://gbfs.lyft.com/gbfs/2.3/bkn/en/station_information.json"
    fetch(url, RAW / "station_information.json")


def download_nta():
    print("2020 Neighborhood Tabulation Areas (NYC Open Data)")
    fetch(NTA_GEOJSON, RAW / "nta2020.geojson")


def download_weather(year):
    print("NOAA daily weather, Central Park")
    params = {
        "dataset": "daily-summaries",
        "stations": CENTRAL_PARK,
        "startDate": f"{year}-01-01",
        "endDate": f"{year}-12-31",
        "dataTypes": "TMAX,TMIN,PRCP,SNOW",
        "units": "standard",
        "format": "csv",
    }
    fetch(NOAA_URL, RAW / f"weather_central_park_{year}.csv", params=params)


def main():
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--year", type=int, default=2025)
    p.add_argument("--months", type=int, nargs="+", default=[1, 7, 10])
    p.add_argument("--skip-trips", action="store_true")
    a = p.parse_args()

    if not a.skip_trips:
        download_trips(a.year, a.months)
    download_gbfs()
    download_nta()
    download_weather(a.year)

    meta = {"year": a.year, "months": a.months}
    (RAW / "download_meta.json").write_text(json.dumps(meta))
    print("\nDone. Next: python scripts/build.py")


if __name__ == "__main__":
    sys.exit(main())
