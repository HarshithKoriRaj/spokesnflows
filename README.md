# Spokes & Flows: How New York Moves on Citi Bike

Team 2, CS-GY 6313 B Information Visualization (Fall 2026, NYU Tandon)
Harshith Kori Raj (hk4488) · Lakshmi Hukunda Raju (lh4140)

We look at 11.8 million Citi Bike trips from January, July and October 2025 and ask one main question:
**where does the system struggle, and when?** The views show when people ride, which stations lose or gain
bikes through riders' trips at each hour, where those trips come from, and how much the weather matters.
The intended reader is someone planning the network (for example NYC DOT or a community board deciding
where to add docks).

## Questions

| # | Question | Status |
|---|----------|--------|
| Q1 | When do people ride, and how do members and casual riders differ? | core |
| Q2 | Where and when do stations gain or lose bikes through trips (net trips per dock)? | core |
| Q3 | Where do the trips behind that imbalance come from (neighborhood-to-neighborhood flows)? | core |
| Q4 | How much do weather and season change ridership? | core |
| Q5 | Do e-bike trips differ from classic-bike trips? | optional |

Net flow is a **trip** measure (arrivals minus departures). It does not show whether a station was actually
empty or full, because staff rebalancing trips are not in the public data.

## Repository layout

```
scripts/download.py     downloads every dataset into data/raw/
scripts/build.py        converts trips to Parquet, cleans them in DuckDB, writes the processed tables
data/raw/               downloaded files (not committed, ~2.3 GB)
data/interim/           Parquet copies of the trips + DuckDB working file (not committed)
data/processed/         small CSV tables the visualizations read (committed, ~10 MB)
report/milestone2.tex   Milestone 2 report; tables and numbers come from report/tables/
report/milestone2.pdf   compiled report
report/tables/          LaTeX tables + numbers written by build.py
sketches/               our hand-drawn sketches (q1 ... q5) and the brief we drew them from
```

## How to run

Needs Python 3.10+, about 8 GB of RAM and 4 GB of free disk space. Tested with DuckDB 1.5.6 and 2.0.

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

python scripts/download.py     # January, July, October 2025 + station, neighborhood and weather files
python scripts/build.py        # about a minute; writes data/processed/ and report/tables/
```

To build the report PDF (needs a LaTeX install, or upload `report/` to Overleaf together with `sketches/`):

```bash
cd report && latexmk -pdf milestone2.tex
```

`build.py` converts each trip zip in `data/raw/trips/` to Parquet once (cached in `data/interim/parquet/`) and then
uses every Parquet file there. To use different months, run `python scripts/download.py --months ...` and rerun
`build.py`; for a year other than 2025, pass `--year` to both scripts. Rerunning on the same files gives identical
output.

## Data access

| Dataset | Published by | Link | File we use |
|---------|--------------|------|-------------|
| Citi Bike trip histories, Jan / Jul / Oct 2025 (NYC) | Lyft / Citi Bike | [System data page](https://citibikenyc.com/system-data) · [file index](https://s3.amazonaws.com/tripdata/index.html) | `202501-citibike-tripdata.zip`, `202507-…zip`, `202510-…zip` → `data/raw/trips/` |
| Station capacity (GBFS `station_information`) | Lyft / Citi Bike | [GBFS feed index](https://gbfs.citibikenyc.com/gbfs/2.3/gbfs.json) | `data/raw/station_information.json` (current snapshot, downloaded Nov 2026) |
| 2020 Neighborhood Tabulation Areas | NYC Dept. of City Planning, via NYC Open Data | [NYC Open Data](https://data.cityofnewyork.us/d/9nt8-h7nd) | `data/raw/nta2020.geojson` (Export → GeoJSON) |
| Daily weather, Central Park (GHCND:USW00094728) | NOAA NCEI | [Station page](https://www.ncei.noaa.gov/cdo-web/datasets/GHCND/stations/GHCND:USW00094728/detail) · [CSV for 2025](https://www.ncei.noaa.gov/access/services/data/v1?dataset=daily-summaries&stations=USW00094728&startDate=2025-01-01&endDate=2025-12-31&dataTypes=TMAX,TMIN,PRCP,SNOW&units=standard&format=csv) | `data/raw/weather_central_park_2025.csv` |

`download.py` fetches all of these. If a download is blocked on your network, open the links above in a
browser and save each file under the name in the last column. Citi Bike data is used under the
[NYCBS Data Use Policy](https://www.citibikenyc.com/data-sharing-policy).

## Processed tables (`data/processed/`)

| File | One row is | Rows | Used by |
|------|------------|------|---------|
| `hourly_profile.csv` | day of week × hour × rider type | 336 | Q1 |
| `station_hour.csv` | station × weekday/weekend × hour: departures, arrivals and net per day, net per dock, cumulative net per dock | 109,056 | Q2 |
| `stations.csv` | station: name, location, docks, neighborhood, borough, first seen | 2,272 | Q2, Q3 |
| `od_nta.csv` | start neighborhood × end neighborhood × period, with borough and East River flags | 32,019 | Q3 |
| `daily.csv` | day: trips by rider and bike type, weather, holiday flag | 93 | Q4 |
| `bike_type_summary.csv`, `distance_hist.csv` | bike type × rider type; distance histogram | 4 / 66 | Q5 |
| `data_quality.csv` | counts for every cleaning check | 24 | report |

**Cleaning rules:**

- Keep trips that start in the downloaded months.
- Drop trips longer than 3 hours. The operator already removes trips under 60 seconds.
- Drop trips to or from Citi Bike's own depots, workshops and test docks (about 2,800 trips).
- Fix station IDs written two ways (e.g. `7154.1` and `7154.10`, or a trailing `_`) so each dock has one ID.
- Group public holidays with weekends.
- Trips with no end station (0.26% of cleaned trips, almost none with end coordinates) are kept for Q1 and Q4 and
  left out of the station and neighborhood views.
- 66 Jersey City / Hoboken stations reached from NYC are left off the map.
- Stations with no dock data (59 in NYC) are kept and shown as "no data".
- In `distance_hist.csv` the last bin, 8, means 8 km or more.

## Observable notebooks

None yet. Links will be added here for Milestone 3, along with what each notebook is for.

## AI use

We used Claude (Anthropic) to help write `scripts/download.py` and `scripts/build.py`, to run the first data checks,
and to draft parts of the report text. We reviewed and ran the code, checked the outputs against the raw files, and
edited the text, and we can explain every step. Claude also made reference mockups of each view from our processed
data; the sketches in `sketches/` are drawn by hand by us, using those mockups as a guide.

## Course staff access

This repository is private and shared with GitHub users `ctsilva` and `kimryan0416`.
