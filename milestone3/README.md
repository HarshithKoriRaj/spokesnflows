# Milestone 3: D3 first draft

This folder contains the Milestone 3 write-up and a runnable first-draft D3 view set for the four core questions in the Citi Bike project.

## Files

- `index.html` – narrative page with the interactive D3 views
- `styles.css` – page styling
- `charts.js` – D3 rendering logic and data loading

## Open the milestone page

This write-up is intended to be viewed from the repository itself. After pushing to GitHub, open:

```text
https://github.com/<your-username>/<your-repo>/blob/main/milestone3/index.html
```

or, if you prefer to run it locally for testing:

```bash
cd /path/to/spokesnflows
python3 -m http.server 8000
```

Then visit:

```text
http://localhost:8000/milestone3/index.html
```

## Included questions

1. Q1 – when do riders travel, by member and casual rider type
2. Q2 – station net flow, with day type and hour controls
3. Q3 – busiest neighborhood-to-neighborhood flow ranking by period
4. Q4 – weather and seasonal association with ridership
5. Q5 (optional) – e-bike vs classic-bike distance comparison

## Data inputs

The views read the processed CSVs already generated in the project:

- `data/processed/hourly_profile.csv`
- `data/processed/station_hour.csv`
- `data/processed/daily.csv`
- `data/processed/od_nta.csv`
- `data/processed/distance_hist.csv`

## AI disclosure

The team used Claude for early exploratory chart mockups and data-cleaning scaffolding. Final chart choices, repo edits, and interpretation were reviewed and adjusted by the team before being included here.
