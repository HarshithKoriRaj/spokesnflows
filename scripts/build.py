"""Clean the raw Citi Bike trips and build the small tables the visualizations use.

Usage:
    python scripts/build.py                 # uses every trip zip in data/raw/trips
    python scripts/build.py --year 2025

Reads   data/raw/  (see scripts/download.py)
Writes  data/processed/*.csv     tables for the D3 views
        data/processed/data_quality.csv
        report/tables/*.tex      sample tables + numbers for the Milestone 2 report

All heavy work runs in DuckDB so the full year fits on a laptop.
"""
import argparse
import json
import math
import os
import shutil
import zipfile
from pathlib import Path

import duckdb
import numpy as np
import pandas as pd
from shapely.geometry import Point, shape
from shapely.strtree import STRtree

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
INTERIM = ROOT / "data" / "interim"
OUT = ROOT / "data" / "processed"
TEX = ROOT / "report" / "tables"

MAX_DURATION_MIN = 180      # longer trips are almost always bikes not docked properly
MIN_DURATION_MIN = 1        # the operator already drops trips under 60 s
NEAREST_MATCH_M = 75        # max distance when matching a station to GBFS by location

# US federal holidays observed in 2025 (used only to flag days in the daily table)
HOLIDAYS_2025 = ["2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26", "2025-06-19",
                 "2025-07-04", "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27",
                 "2025-12-25"]

TRIP_TYPES = {
    "ride_id": "VARCHAR", "rideable_type": "VARCHAR",
    "started_at": "TIMESTAMP", "ended_at": "TIMESTAMP",
    "start_station_name": "VARCHAR", "start_station_id": "VARCHAR",
    "end_station_name": "VARCHAR", "end_station_id": "VARCHAR",
    "start_lat": "DOUBLE", "start_lng": "DOUBLE", "end_lat": "DOUBLE", "end_lng": "DOUBLE",
    "member_casual": "VARCHAR",
}


# ---------------------------------------------------------------- helpers
def trips_to_parquet(con):
    """Convert each monthly zip's CSVs to Parquet once (typed, compressed).

    Returns the list of Parquet files. Already-converted files are reused, so
    adding a month only converts the new zip.
    """
    src, pq_dir, tmp = RAW / "trips", INTERIM / "parquet", INTERIM / "csv_tmp"
    pq_dir.mkdir(parents=True, exist_ok=True)
    zips = sorted(p for p in src.glob("*.zip") if not p.name.upper().startswith("JC"))
    if not zips and not any(pq_dir.glob("*.parquet")):
        raise SystemExit(f"No trip zips in {src}. Run scripts/download.py first.")
    types = "{" + ", ".join(f"'{k}': '{v}'" for k, v in TRIP_TYPES.items()) + "}"
    for z in zips:
        month = z.name[:6]
        if any(pq_dir.glob(f"{month}*.parquet")):
            continue
        print(f"  converting {z.name}")
        shutil.rmtree(tmp, ignore_errors=True)
        for csv in _unzip(z, tmp):
            out = pq_dir / (csv.stem + ".parquet")
            con.execute(f"""COPY (SELECT * FROM read_csv('{csv}', header=true, types={types}))
                            TO '{out}' (FORMAT parquet, COMPRESSION zstd)""")
            csv.unlink()
        shutil.rmtree(tmp, ignore_errors=True)
    files = sorted(str(p) for p in pq_dir.glob("*.parquet"))
    print(f"  {len(files)} Parquet files")
    return files


def _unzip(path, target):
    """Extract every CSV in a zip (zips can be nested). Returns the CSV paths."""
    target.mkdir(parents=True, exist_ok=True)
    found = []
    with zipfile.ZipFile(path) as zf:
        for m in zf.namelist():
            if "__MACOSX" in m or m.endswith("/"):
                continue
            if m.lower().endswith(".zip"):
                inner = target / Path(m).name
                with zf.open(m) as s, open(inner, "wb") as d:
                    shutil.copyfileobj(s, d)
                found += _unzip(inner, target / inner.stem)
                inner.unlink()
            elif m.lower().endswith(".csv"):
                dest = target / Path(m).name
                with zf.open(m) as s, open(dest, "wb") as d:
                    shutil.copyfileobj(s, d)
                found.append(dest)
    return found


def haversine_m(lat1, lng1, lat2, lng2):
    lat1, lng1, lat2, lng2 = map(np.radians, (lat1, lng1, lat2, lng2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lng2 - lng1) / 2) ** 2)
    return 6371000 * 2 * np.arcsin(np.sqrt(a))


def attach_capacity(stations):
    """Dock capacity from GBFS: match on short_name, then on nearest station."""
    path = RAW / "station_information.json"
    stations["capacity"] = np.nan
    stations["capacity_source"] = "missing"
    if not path.exists():
        print("  no station_information.json; capacity left empty")
        return stations
    info = pd.DataFrame(json.loads(path.read_text())["data"]["stations"])
    info = info.dropna(subset=["capacity"])
    info = info[info["capacity"] > 0]

    by_id = info.drop_duplicates("short_name").set_index("short_name")["capacity"]
    hit = stations["station_id"].map(by_id)
    stations.loc[hit.notna(), "capacity"] = hit[hit.notna()]
    stations.loc[hit.notna(), "capacity_source"] = "gbfs_id"

    todo = stations["capacity"].isna() & stations["lat"].notna()
    if todo.any():
        glat, glng = info["lat"].to_numpy(), info["lon"].to_numpy()
        for i in stations.index[todo]:
            d = haversine_m(stations.at[i, "lat"], stations.at[i, "lng"], glat, glng)
            j = int(np.argmin(d))
            if d[j] <= NEAREST_MATCH_M:
                stations.at[i, "capacity"] = info["capacity"].iloc[j]
                stations.at[i, "capacity_source"] = "gbfs_nearest"
    return stations


def attach_nta(stations):
    """Neighborhood (2020 NTA) and borough for each station via point-in-polygon."""
    path = RAW / "nta2020.geojson"
    for c in ("nta", "nta_name", "borough"):
        stations[c] = None
    if not path.exists():
        print("  no nta2020.geojson; neighborhoods left empty")
        return stations
    feats = json.loads(path.read_text())["features"]

    def prop(f, *names):
        p = {k.lower(): v for k, v in f["properties"].items()}
        return next((p[n] for n in names if n in p), None)

    polys = [shape(f["geometry"]) for f in feats]
    tree = STRtree(polys)
    for i, r in stations.iterrows():
        if pd.isna(r["lat"]):
            continue
        pt = Point(r["lng"], r["lat"])
        for k in tree.query(pt):
            if polys[k].contains(pt):
                f = feats[k]
                stations.at[i, "nta"] = prop(f, "nta2020", "ntacode")
                stations.at[i, "nta_name"] = prop(f, "ntaname")
                stations.at[i, "borough"] = prop(f, "boroname")
                break
    return stations


def tex_escape(s):
    s = str(s)
    for a, b in [("\\", r"\textbackslash{}"), ("&", r"\&"), ("%", r"\%"), ("$", r"\$"),
                 ("#", r"\#"), ("_", r"\_"), ("{", r"\{"), ("}", r"\}"),
                 ("~", r"\textasciitilde{}"), ("^", r"\textasciicircum{}")]:
        s = s.replace(a, b)
    return s


def fmt(v, digits=2):
    if v is None or (isinstance(v, float) and math.isnan(v)):
        return r"\textit{missing}"
    if isinstance(v, (int, np.integer)):
        return f"{v:,}"
    if isinstance(v, (float, np.floating)):
        return f"{v:,.{digits}f}"
    return tex_escape(v)


def write_tex_table(df, name, align=None, digits=None):
    """Write df as a booktabs tabular the report can \\input."""
    digits = digits or {}
    align = align or "l" * len(df.columns)
    lines = [rf"\begin{{tabular}}{{{align}}}", r"\toprule",
             " & ".join(rf"\textbf{{{tex_escape(c)}}}" for c in df.columns) + r" \\",
             r"\midrule"]
    for _, row in df.iterrows():
        lines.append(" & ".join(fmt(row[c], digits.get(c, 2)) for c in df.columns) + r" \\")
    lines += [r"\bottomrule", r"\end{tabular}"]
    (TEX / f"{name}.tex").write_text("\n".join(lines) + "\n")


# ---------------------------------------------------------------- main build
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--year", type=int, default=2025)
    year = ap.parse_args().year

    for d in (INTERIM, OUT, TEX):
        d.mkdir(parents=True, exist_ok=True)

    # In-memory database capped at half the machine's RAM; DuckDB spills to disk past that,
    # so the full pipeline also runs on small laptops.
    con = duckdb.connect()
    con.execute(f"SET temp_directory='{INTERIM / 'duckdb_tmp'}'")
    try:
        ram_gb = os.sysconf("SC_PAGE_SIZE") * os.sysconf("SC_PHYS_PAGES") / 1e9
        con.execute(f"SET memory_limit='{max(1.0, ram_gb / 2):.1f}GB'")
    except (ValueError, OSError, AttributeError):
        pass
    con.execute("SET preserve_insertion_order=false")

    print("1/7 Converting trip zips to Parquet (first run only)")
    files = trips_to_parquet(con)

    print("2/7 Loading trips into DuckDB")
    # A view, not a table: trips are read straight from the Parquet files when needed.
    con.execute(f"CREATE OR REPLACE VIEW raw AS SELECT * FROM read_parquet({files}, union_by_name=true)")

    print("3/7 Cleaning and counting problems")
    # Station IDs look like 7154.10, but some rows lose the trailing zero (7154.1) or gain a
    # trailing underscore (5303.06_). Normalize them so each dock has one ID.
    con.execute(r"""CREATE OR REPLACE MACRO norm_id(x) AS (
        CASE WHEN NULLIF(rtrim(trim(x), '_'), '') IS NULL THEN NULL
             WHEN regexp_matches(rtrim(trim(x), '_'), '^[0-9]+\.[0-9]$') THEN rtrim(trim(x), '_') || '0'
             ELSE rtrim(trim(x), '_') END)""")
    # Citi Bike's own depots, workshops and test docks are not public stations.
    con.execute(r"""CREATE OR REPLACE MACRO is_internal(id, nm) AS (
        coalesce(upper(id) LIKE 'SYS%' OR upper(nm) LIKE 'SYS%' OR lower(nm) LIKE '%charging%'
                 OR lower(nm) LIKE 'shop %' OR lower(nm) LIKE 'lab - %' OR lower(nm) LIKE '%demo%'
                 OR lower(nm) LIKE '%test%', false))""")
    hol_list = ", ".join(f"DATE '{h}'" for h in HOLIDAYS_2025) if year == 2025 else "NULL"
    con.execute(f"CREATE OR REPLACE MACRO is_holiday(dt) AS (coalesce(CAST(dt AS DATE) IN ({hol_list}), false))")
    # Only keep trips that start in a month we downloaded. Each monthly file also
    # holds a few trips that began the evening before the month started.
    file_months = sorted({Path(f).name[:6] for f in files if Path(f).name[:4] == str(year)})
    in_months = "strftime(started_at, '%Y%m') IN (" + ", ".join(f"'{m}'" for m in file_months) + ")"
    q = con.execute(f"""
        WITH r AS (
            SELECT *,
                   date_diff('second', started_at, ended_at) / 60.0 AS dur,
                   norm_id(start_station_id) AS sid,
                   norm_id(end_station_id)   AS eid,
                   NULLIF(trim(start_station_id), '') AS sid_raw,
                   NULLIF(trim(end_station_id), '')   AS eid_raw
            FROM raw)
        SELECT
          count(*)                                                      AS rows_raw,
          count(*) FILTER (NOT ({in_months}))                           AS outside_months,
          count(*) - count(DISTINCT ride_id)                            AS duplicate_ids,
          count(*) FILTER (dur < {MIN_DURATION_MIN})                    AS too_short,
          count(*) FILTER (dur > {MAX_DURATION_MIN})                    AS too_long,
          count(*) FILTER (sid IS NULL)                                 AS no_start_station,
          count(*) FILTER (eid IS NULL)                                 AS no_end_station,
          count(*) FILTER (eid IS NULL AND rideable_type = 'electric_bike') AS no_end_station_ebike,
          count(*) FILTER (eid IS NULL AND rideable_type = 'classic_bike')  AS no_end_station_classic,
          count(*) FILTER (end_lat IS NULL OR end_lng IS NULL)          AS no_end_coords,
          count(*) FILTER (eid IS NULL AND end_lat IS NOT NULL)         AS no_end_station_but_coords,
          count(*) FILTER (sid IS NOT NULL AND sid = eid)               AS round_trips,
          count(*) FILTER (sid IS DISTINCT FROM sid_raw OR eid IS DISTINCT FROM eid_raw) AS ids_normalized,
          count(*) FILTER (is_internal(sid, start_station_name) OR is_internal(eid, end_station_name)) AS internal_station,
          count(*) FILTER (eid IS NULL AND {in_months} AND dur BETWEEN {MIN_DURATION_MIN} AND {MAX_DURATION_MIN}) AS no_end_station_kept
        FROM r
    """).df().iloc[0]
    quality = {k: int(v) for k, v in q.items()}

    con.execute(f"""
        CREATE OR REPLACE TABLE trips_filtered AS
        SELECT ride_id, rideable_type, member_casual, started_at, ended_at,
               date_diff('second', started_at, ended_at) / 60.0          AS duration_min,
               norm_id(start_station_id) AS s_id, start_station_name AS s_name,
               norm_id(end_station_id)   AS e_id, end_station_name   AS e_name,
               start_lat AS s_lat, start_lng AS s_lng, end_lat AS e_lat, end_lng AS e_lng,
               CASE WHEN end_lat IS NULL THEN NULL ELSE
                 2 * 6371 * asin(sqrt(
                   pow(sin(radians(end_lat - start_lat) / 2), 2) +
                   cos(radians(start_lat)) * cos(radians(end_lat)) *
                   pow(sin(radians(end_lng - start_lng) / 2), 2))) END     AS dist_km,
               CAST(started_at AS DATE)                                   AS d,
               hour(started_at)                                           AS h,
               isodow(started_at)                                         AS dow,
               is_holiday(started_at)                                     AS holiday,
               -- public holidays behave like weekends, so they are grouped with them
               CASE WHEN isodow(started_at) >= 6 OR is_holiday(started_at) THEN 'weekend'
                    ELSE 'weekday' END                                    AS day_type,
               hour(ended_at)                                             AS e_h,
               CASE WHEN isodow(ended_at) >= 6 OR is_holiday(ended_at) THEN 'weekend'
                    ELSE 'weekday' END                                    AS e_day_type
        FROM raw
        WHERE {in_months}
          AND date_diff('second', started_at, ended_at) / 60.0
              BETWEEN {MIN_DURATION_MIN} AND {MAX_DURATION_MIN}
          AND NOT is_internal(norm_id(start_station_id), start_station_name)
          AND NOT is_internal(norm_id(end_station_id), end_station_name)
    """)
    con.execute("CREATE OR REPLACE TABLE trips AS SELECT * FROM trips_filtered")
    if quality["duplicate_ids"]:
        # Keep the first copy of a repeated ride ID. (DISTINCT ON rather than a window
        # filter, which trips an optimizer bug in some DuckDB 1.x releases.)
        con.execute("""CREATE OR REPLACE TABLE trips AS
                       SELECT DISTINCT ON (ride_id) * FROM trips ORDER BY ride_id, started_at""")
    con.execute("DROP TABLE trips_filtered")
    quality["rows_clean"] = con.execute("SELECT count(*) FROM trips").fetchone()[0]
    months = [r[0] for r in con.execute(
        "SELECT DISTINCT strftime(d, '%Y-%m') m FROM trips ORDER BY m").fetchall()]
    ndays = dict(con.execute(
        "SELECT day_type, count(DISTINCT d) FROM trips GROUP BY 1").fetchall())
    ndays.setdefault("weekday", 0)
    ndays.setdefault("weekend", 0)

    print("4/7 Building the station list (capacity + neighborhood)")
    stations = con.execute("""
        WITH ends AS (
          SELECT s_id AS station_id, s_name AS name, s_lat AS lat, s_lng AS lng,
                 rideable_type, d, 1 AS dep, 0 AS arr FROM trips WHERE s_id IS NOT NULL
          UNION ALL
          SELECT e_id, e_name, e_lat, e_lng, rideable_type, CAST(ended_at AS DATE), 0, 1
          FROM trips WHERE e_id IS NOT NULL)
        SELECT station_id,
               mode(name) AS name,
               median(lat) AS lat,
               median(lng) AS lng,
               min(d) AS first_seen,
               sum(dep)::BIGINT AS departures,
               sum(arr)::BIGINT AS arrivals
        FROM ends GROUP BY station_id ORDER BY station_id
    """).df()
    stations = attach_capacity(stations)
    stations = attach_nta(stations)
    quality["stations"] = len(stations)
    quality["stations_capacity_by_id"] = int((stations.capacity_source == "gbfs_id").sum())
    quality["stations_capacity_by_location"] = int((stations.capacity_source == "gbfs_nearest").sum())
    quality["stations_capacity_missing"] = int((stations.capacity_source == "missing").sum())
    quality["stations_no_nta"] = int(stations["nta"].isna().sum())
    gbfs_path = RAW / "station_information.json"
    if gbfs_path.exists():
        info = pd.DataFrame(json.loads(gbfs_path.read_text())["data"]["stations"])
        miss = stations[(stations.capacity_source == "missing") & stations.nta.notna()]
        zero = set(info.loc[info["capacity"].fillna(0) <= 0, "short_name"])
        quality["capacity_missing_in_nyc"] = len(miss)
        quality["capacity_missing_zero_docks_in_feed"] = int(miss.station_id.isin(zero).sum())
        quality["capacity_missing_not_in_feed"] = int((~miss.station_id.isin(info["short_name"])).sum())
    con.register("stations_df", stations)
    con.execute("CREATE OR REPLACE TABLE stations AS SELECT * FROM stations_df")
    stations.to_csv(OUT / "stations.csv", index=False)

    con.execute(f"""CREATE OR REPLACE TABLE ndays AS
        SELECT * FROM (VALUES ('weekday', {ndays['weekday']}), ('weekend', {ndays['weekend']}))
        t(day_type, n_days)""")

    print("5/7 Station x hour net flow (Q2)")
    station_hour = con.execute("""
        WITH dep AS (SELECT s_id AS station_id, day_type, h AS hour, count(*) AS n
                     FROM trips WHERE s_id IS NOT NULL GROUP BY ALL),
             arr AS (SELECT e_id AS station_id, e_day_type AS day_type, e_h AS hour, count(*) AS n
                     FROM trips WHERE e_id IS NOT NULL GROUP BY ALL),
             grid AS (SELECT s.station_id, t.day_type, h.hour, s.capacity, t.n_days
                      FROM stations s, ndays t, range(24) h(hour))
        SELECT g.station_id, g.day_type, g.hour,
               coalesce(dep.n, 0) / g.n_days                             AS departures_per_day,
               coalesce(arr.n, 0) / g.n_days                             AS arrivals_per_day,
               (coalesce(arr.n, 0) - coalesce(dep.n, 0)) / g.n_days      AS net_per_day,
               g.capacity,
               ((coalesce(arr.n, 0) - coalesce(dep.n, 0)) / g.n_days) / g.capacity AS net_per_dock,
               sum((coalesce(arr.n, 0) - coalesce(dep.n, 0)) / g.n_days)
                   OVER (PARTITION BY g.station_id, g.day_type ORDER BY g.hour) / g.capacity
                                                                         AS cum_net_per_dock
        FROM grid g
        LEFT JOIN dep USING (station_id, day_type, hour)
        LEFT JOIN arr USING (station_id, day_type, hour)
        WHERE g.n_days > 0
        ORDER BY g.station_id, g.day_type, g.hour
    """).df()
    station_hour.round(4).to_csv(OUT / "station_hour.csv", index=False)

    print("6/7 Hourly rhythm (Q1), neighborhood flows (Q3), daily + weather (Q4), bike types (Q5)")
    hourly = con.execute("""
        -- public holidays are left out so they don't pull down their weekday
        WITH days AS (SELECT dow, count(DISTINCT d) AS n_days FROM trips WHERE NOT holiday GROUP BY dow)
        SELECT t.dow, dayname(min(t.d)) AS day_name, t.h AS hour, t.member_casual AS rider_type,
               count(*) AS trips, count(*) / any_value(days.n_days) AS trips_per_day
        FROM trips t JOIN days USING (dow)
        WHERE NOT t.holiday
        GROUP BY t.dow, t.h, t.member_casual ORDER BY 1, 3, 4
    """).df()
    hourly.round(2).to_csv(OUT / "hourly_profile.csv", index=False)

    od = con.execute("""
        WITH t AS (
          SELECT s_id, e_id, day_type,
                 CASE WHEN day_type = 'weekend' THEN 'weekend'
                      WHEN h BETWEEN 7 AND 9   THEN 'weekday_am_peak'
                      WHEN h BETWEEN 16 AND 18 THEN 'weekday_pm_peak'
                      ELSE 'weekday_other' END AS period
          FROM trips WHERE s_id IS NOT NULL AND e_id IS NOT NULL)
        SELECT a.nta AS start_nta, a.nta_name AS start_nta_name, a.borough AS start_borough,
               b.nta AS end_nta,   b.nta_name AS end_nta_name,   b.borough AS end_borough,
               t.period, count(*) AS trips, count(*) / any_value(n.n_days) AS trips_per_day,
               a.borough <> b.borough AS crosses_borough,
               (a.borough = 'Manhattan' AND b.borough IN ('Brooklyn', 'Queens')) OR
               (b.borough = 'Manhattan' AND a.borough IN ('Brooklyn', 'Queens')) AS crosses_east_river
        FROM t JOIN stations a ON a.station_id = t.s_id
               JOIN stations b ON b.station_id = t.e_id
               JOIN ndays n ON n.day_type = t.day_type
        GROUP BY ALL ORDER BY trips DESC, start_nta, end_nta, period
    """).df()
    od.round(3).to_csv(OUT / "od_nta.csv", index=False)

    holidays = ", ".join(f"DATE '{h}'" for h in HOLIDAYS_2025) if year == 2025 else "NULL"
    weather_path = RAW / f"weather_central_park_{year}.csv"
    if weather_path.exists():
        con.execute(f"CREATE OR REPLACE TABLE weather AS SELECT * FROM read_csv('{weather_path}')")
        wcols = {c.upper(): c for c in con.execute("DESCRIBE weather").df()["column_name"]}
        sel = ", ".join(f"TRY_CAST(\"{wcols[c]}\" AS DOUBLE) AS {c.lower()}"
                        for c in ("TMAX", "TMIN", "PRCP", "SNOW") if c in wcols)
        con.execute(f"""CREATE OR REPLACE TABLE weather AS
                        SELECT CAST("{wcols['DATE']}" AS DATE) AS d, {sel} FROM weather""")
    else:
        print("  no weather file; weather columns left empty")
        con.execute("""CREATE OR REPLACE TABLE weather AS SELECT NULL::DATE d, NULL::DOUBLE tmax,
                       NULL::DOUBLE tmin, NULL::DOUBLE prcp, NULL::DOUBLE snow WHERE false""")
    daily = con.execute(f"""
        SELECT t.d AS date, dayname(t.d) AS day_name, any_value(t.day_type) AS day_type,
               t.d IN ({holidays}) AS holiday,
               count(*) AS trips,
               count(*) FILTER (member_casual = 'member') AS member_trips,
               count(*) FILTER (member_casual = 'casual') AS casual_trips,
               count(*) FILTER (rideable_type = 'electric_bike') AS ebike_trips,
               median(duration_min) AS median_duration_min,
               any_value(w.tmax) AS tmax_f, any_value(w.tmin) AS tmin_f,
               any_value(w.prcp) AS precip_in, any_value(w.snow) AS snow_in
        FROM trips t LEFT JOIN weather w ON w.d = t.d
        GROUP BY t.d ORDER BY t.d
    """).df()
    daily.round({c: 2 for c in daily.select_dtypes("number").columns}).to_csv(
        OUT / "daily.csv", index=False)

    bike = con.execute("""
        SELECT rideable_type, member_casual AS rider_type, count(*) AS trips,
               median(duration_min) AS median_min, median(dist_km) AS median_km,
               quantile_cont(dist_km, 0.9) AS p90_km,
               avg(CASE WHEN e_id IS NULL THEN 1 ELSE 0 END) AS share_no_end_station
        FROM trips GROUP BY ALL ORDER BY 1, 2
    """).df()
    bike.round(3).to_csv(OUT / "bike_type_summary.csv", index=False)
    con.execute("""
        COPY (SELECT rideable_type, least(floor(dist_km / 0.25) * 0.25, 8) AS dist_bin_km,
                     count(*) AS trips
              FROM trips WHERE dist_km IS NOT NULL GROUP BY ALL ORDER BY 1, 2)
        TO '""" + str(OUT / "distance_hist.csv") + "' (HEADER)")

    print("7/7 Writing report tables")
    pd.Series(quality).rename("count").to_csv(OUT / "data_quality.csv", header=True)
    write_report_tables(con, quality, months, ndays, stations, station_hour,
                        hourly, od, daily, bike)
    con.close()
    print("\nDone. Tables in data/processed/, report tables in report/tables/")


def write_report_tables(con, q, months, ndays, stations, sh, hourly, od, daily, bike):
    raw = q["rows_raw"]
    pct = lambda n: f"{100 * n / raw:.2f}" if raw else "0"
    macros = {
        "DataMonths": (", ".join(pd.to_datetime(m + "-01").strftime("%B %Y") for m in months)
                       + f" ({len(months)} months)") if months else "none",
        "TripsRaw": f"{raw:,}",
        "TripsClean": f"{q['rows_clean']:,}",
        "NoEndStationPct": pct(q["no_end_station"]),
        "NoEndStationEbikePct": (f"{100 * q['no_end_station_ebike'] / q['no_end_station']:.0f}"
                                 if q["no_end_station"] else "0"),
        "NStations": f"{q['stations']:,}",
        "NCapMissing": f"{q['stations_capacity_missing']:,}",
        "NWeekdays": str(ndays["weekday"]), "NWeekends": str(ndays["weekend"]),
        "NoEndStationN": f"{q['no_end_station']:,}",
        "NoEndNoCoordsN": f"{q['no_end_coords']:,}",
        "NoEndWithCoordsN": f"{q['no_end_station_but_coords']:,}",
        "NoStartStationN": f"{q['no_start_station']:,}",
        "NOutsideNYC": f"{q['stations_no_nta']:,}",
        "NoEndKeptN": f"{q['no_end_station_kept']:,}",
        "NoEndKeptPct": f"{100 * q['no_end_station_kept'] / q['rows_clean']:.2f}",
        "NoEndDroppedLongN": f"{q['no_end_station'] - q['no_end_station_kept']:,}",
        "NIdsFixed": f"{q['ids_normalized']:,}",
        "NInternal": f"{q['internal_station']:,}",
        "NCapMissingNYC": f"{q.get('capacity_missing_in_nyc', 0):,}",
        "NCapZero": f"{q.get('capacity_missing_zero_docks_in_feed', 0):,}",
        "NCapNotInFeed": f"{q.get('capacity_missing_not_in_feed', 0):,}",
    }
    (TEX / "meta.tex").write_text("".join(
        rf"\renewcommand{{\{k}}}{{{tex_escape(v)}}}" + "\n" for k, v in macros.items()))

    rows = [
        ("Trips in the downloaded files", q["rows_raw"], "--"),
        ("Started outside the downloaded months", q["outside_months"], "dropped"),
        ("Duplicate ride IDs", q["duplicate_ids"], "dropped (kept first)"),
        (f"Shorter than {MIN_DURATION_MIN} min", q["too_short"], "dropped"),
        (f"Longer than {MAX_DURATION_MIN} min", q["too_long"], "dropped"),
        ("Station ID written two ways (7154.1 / 7154.10)", q["ids_normalized"], "ID fixed"),
        ("To or from a Citi Bike depot or test dock", q["internal_station"], "dropped"),
        ("No start station ID", q["no_start_station"], "kept; not in station views"),
        ("No end station ID", q["no_end_station"], "see below"),
        ("\\quad of which e-bikes", q["no_end_station_ebike"], ""),
        ("\\quad of which classic bikes", q["no_end_station_classic"], ""),
        ("\\quad with end coordinates", q["no_end_station_but_coords"], ""),
        ("\\quad still in data after cleaning", q["no_end_station_kept"], "kept; not in station views"),
        ("Round trips (same start and end)", q["round_trips"], "kept"),
        ("Trips after cleaning", q["rows_clean"], "--"),
    ]
    lines = [r"\begin{tabular}{lrrl}", r"\toprule",
             r"\textbf{Check} & \textbf{Trips} & \textbf{\% of raw} & \textbf{What we do} \\",
             r"\midrule"]
    for label, n, action in rows:
        lines.append(f"{label} & {n:,} & {pct(n)} & {action} \\\\")
    lines += [r"\midrule",
              rf"Stations found in trips & {q['stations']:,} & & \\",
              rf"\quad capacity matched by ID & {q['stations_capacity_by_id']:,} & & \\",
              rf"\quad capacity matched by location & {q['stations_capacity_by_location']:,} & & within {NEAREST_MATCH_M} m \\",
              rf"\quad capacity missing & {q['stations_capacity_missing']:,} & & shown as ``no data'' \\",
              rf"\quad outside any NYC neighborhood & {q['stations_no_nta']:,} & & \\",
              r"\bottomrule", r"\end{tabular}"]
    (TEX / "quality.tex").write_text("\n".join(lines) + "\n")

    # Q1: a slice of the long table
    s = hourly[hourly["hour"].isin([8, 17]) & hourly["dow"].isin([3, 6])].copy()
    s = s[["day_name", "hour", "rider_type", "trips", "trips_per_day"]]
    s.columns = ["day", "hour", "rider type", "trips (study period)", "trips per day"]
    write_tex_table(s, "q1_sample", "lrlrr", {"trips per day": 0})

    # Q2: busiest station, weekday morning
    top = stations.sort_values("departures", ascending=False).iloc[0]
    s = sh[(sh.station_id == top.station_id) & (sh.day_type == "weekday") & sh.hour.between(6, 11)]
    s = s.assign(station=top["name"])[["station", "hour", "departures_per_day", "arrivals_per_day",
                                       "net_per_day", "capacity", "net_per_dock", "cum_net_per_dock"]]
    s.columns = ["station", "hour", "dep/day", "arr/day", "net/day", "docks", "net/dock",
                 "cum. net/dock"]
    write_tex_table(s, "q2_sample", "lrrrrrrr", {"dep/day": 1, "arr/day": 1, "net/day": 1,
                                                 "docks": 0})

    # Q2: which stations drift most by 10 am on weekdays (trip flow only)
    at10 = sh[(sh.day_type == "weekday") & (sh.hour == 9) & sh.capacity.ge(15)]
    at10 = at10.merge(stations[["station_id", "name", "borough"]], on="station_id")
    pick = pd.concat([at10.nsmallest(4, "cum_net_per_dock"), at10.nlargest(4, "cum_net_per_dock")])
    pick = pick[["name", "borough", "capacity", "cum_net_per_dock"]]
    pick.columns = ["station", "borough", "docks", "cum. net/dock by 10:00"]
    write_tex_table(pick, "q2_extremes", "llrr", {"docks": 0})

    # Q3: top cross-neighborhood pairs in the weekday morning peak
    s = od[(od.period == "weekday_am_peak") & (od.start_nta != od.end_nta)].nlargest(8, "trips_per_day")
    s = s[["start_nta_name", "end_nta_name", "trips_per_day", "crosses_east_river"]]
    s = s.assign(crosses_east_river=s.crosses_east_river.map({True: "yes", False: "no"}))
    s.columns = ["from neighborhood", "to neighborhood", "trips/day", "East River"]
    write_tex_table(s, "q3_sample", "llrl", {"trips/day": 1})

    rows = []
    for per, label in [("weekday_am_peak", "Weekday 7--10"), ("weekday_pm_peak", "Weekday 16--19"),
                       ("weekend", "Weekend (all day)")]:
        o = od[(od.period == per) & od.start_nta.notna() & od.end_nta.notna()]
        t = o.trips_per_day.sum()
        same = o[o.start_nta == o.end_nta].trips_per_day.sum()
        cross_b = o[o.crosses_borough == True].trips_per_day.sum()
        river = o[o.crosses_east_river == True].trips_per_day.sum()
        rows.append((label, t, 100 * same / t, 100 * (t - same - cross_b) / t, 100 * cross_b / t,
                     100 * river / t))
    sh_df = pd.DataFrame(rows, columns=["period", "trips/day", "same nbhd %", "same borough %",
                                        "other borough %", "East River %"])
    write_tex_table(sh_df, "q3_shares", "lrrrrr", {"trips/day": 0, "same nbhd %": 1,
                    "same borough %": 1, "other borough %": 1, "East River %": 1})

    b = (od[od.period == "weekday_am_peak"]
         .groupby(["start_borough", "end_borough"])["trips_per_day"].sum().unstack(fill_value=0))
    b = b.reset_index().rename(columns={"start_borough": "from / to"})
    write_tex_table(b, "q3_boroughs", "l" + "r" * (len(b.columns) - 1),
                    {c: 0 for c in b.columns})

    # Q4: first ten days of the period
    s = daily.head(10)[["date", "day_name", "trips", "member_trips", "casual_trips",
                        "tmax_f", "precip_in", "snow_in"]].copy()
    s["date"] = s["date"].astype(str)
    s.columns = ["date", "day", "trips", "members", "casual", "high (F)", "rain (in)", "snow (in)"]
    write_tex_table(s, "q4_sample", "llrrrrrr", {"high (F)": 0})

    # Q5: bike type summary
    s = bike.copy()
    s["rideable_type"] = s["rideable_type"].str.replace("_bike", "")
    s.columns = ["bike", "rider", "trips", "median min", "median km", "90th pct km",
                 "no end station"]
    s["no end station"] = 100 * s["no end station"]
    s = s.rename(columns={"no end station": "no end station %"})
    write_tex_table(s, "q5_sample", "llrrrrr")

    hist = con.execute("""
        SELECT rideable_type, least(floor(dist_km / 0.25) * 0.25, 8) AS bin, count(*) AS n
        FROM trips WHERE dist_km IS NOT NULL GROUP BY ALL ORDER BY 1, 2""").df()
    hist["share"] = 100 * hist.n / hist.groupby("rideable_type").n.transform("sum")
    hist["rideable_type"] = hist["rideable_type"].str.replace("_bike", "")
    hist["bin"] = hist["bin"].map(lambda b: "8+ km" if b >= 8 else f"{b:.2f}--{b + 0.25:.2f} km")
    h = hist[hist.groupby("rideable_type").cumcount() < 4][["rideable_type", "bin", "n", "share"]]
    h.columns = ["bike", "distance bin", "trips", "share of that bike's trips %"]
    write_tex_table(h, "q5_hist_sample", "llrr", {"share of that bike's trips %": 1})

    # Q4: rain effect on ordinary weekdays (no weekends, no holidays), against that month's
    # average ordinary weekday
    wd = daily[(daily.day_type == "weekday") & ~daily.holiday].copy()
    wd["month"] = pd.to_datetime(wd["date"]).dt.month
    wd["rain"] = wd.precip_in >= 0.1
    rain = {}
    for c in ("member_trips", "casual_trips"):
        pctv = 100 * wd[c] / wd.groupby("month")[c].transform("mean")
        rain[c] = (pctv[wd.rain].mean(), pctv[~wd.rain].mean())
    extra = {"NRainyWeekdays": str(int(wd.rain.sum())),
             "RainMemberPct": f"{rain['member_trips'][0]:.0f}", "DryMemberPct": f"{rain['member_trips'][1]:.0f}",
             "RainCasualPct": f"{rain['casual_trips'][0]:.0f}", "DryCasualPct": f"{rain['casual_trips'][1]:.0f}"}
    with open(TEX / "meta.tex", "a") as f:
        for k, v in extra.items():
            f.write(rf"\renewcommand{{\{k}}}{{{v}}}" + "\n")


if __name__ == "__main__":
    main()
