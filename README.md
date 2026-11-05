# wave_lakehouse

A small medallion lakehouse (bronze, silver, gold) for ocean wave buoy data, built on
[Delta Lake](https://delta.io/) with Python. It ingests NOAA NDBC standard meteorological
files, validates and deduplicates them incrementally, and publishes daily statistics and
storm events ready for analysis or a BI tool.

The goal is to show the data engineering patterns I use, on a domain I know from coastal
engineering work: idempotent ingestion, schema evolution, incremental MERGE, explicit data
quality rules and tested transformations.

## Architecture

```
NDBC stdmet files ──► landing/ ──► bronze.stdmet ──► silver.observations ──► gold.daily_stats
 (historical .gz                    raw text +        typed, QC'd,             gold.storm_events
  or realtime)                      lineage           deduplicated
```

| Layer | Table | What it guarantees |
|---|---|---|
| Bronze | `stdmet` | Every value kept as text, plus `source_file`, `file_sha256`, `ingested_at`. Append only; re-ingesting the same file is a no-op. Schema grows when upstream adds columns. |
| Silver | `observations` | UTC timestamps, typed values, NDBC missing-value codes (99.0, 999, MM...) converted to null, out-of-range values nulled and recorded in `qc_flags`. One row per `(station_id, ts)`, updated with Delta MERGE. Only bronze rows newer than the last processed `ingested_at` are read. Partitioned by station. |
| Gold | `daily_stats` | Per station and day: observation counts, mean/max/p95 significant wave height, mean peak period, wind, water temperature. |
| Gold | `storm_events` | Peaks over threshold: Hs above the station's own 95th percentile for at least 3 h, gaps up to 2 h bridged. Start, end, duration, peak Hs and period. |

Quality rules live in `src/wavelake/quality.py`: physical ranges per variable and a gust vs
mean wind consistency check. Nothing is silently dropped; every correction leaves a flag.

## Usage

```bash
pip install -e ".[dev]"

# Download two buoys (historical 2023) and run the whole pipeline
wavelake run 41048 44025 --years 2023

# Or step by step
wavelake ingest 41048            # realtime file (last 45 days)
wavelake ingest-file my_file.txt --station 41048
wavelake build                   # silver MERGE + gold rebuild
wavelake report                  # completeness and QC flags per station
```

Tables are written under `./lake/` (change it with `--lake`) and can be read with any Delta
reader: `deltalake`, Spark, DuckDB, Polars or Microsoft Fabric.

## Tests and CI

- `pytest` covers parsing, missing-value handling, QC rules, storm detection and an end to
  end run that checks idempotency, incremental processing and deduplication of overlapping
  files. The tests use synthetic files in the exact NDBC layout, generated in `tests/conftest.py`.
- GitHub Actions runs lint (ruff) and tests on Python 3.11 and 3.12 for every push.
- A separate weekly workflow runs the pipeline against live NDBC data, so an upstream outage
  never blocks a merge.

## Limitations and next steps

- Gold tables are rebuilt in full on every run; fine at this scale, but they should become
  incremental per affected station and day.
- Storm thresholds are per station percentiles over the data loaded so far, so they shift as
  more years are ingested.
- Planned: spectral wave files, an orchestrator (Dagster or Fabric pipelines) and a small
  dashboard on top of `gold`.

Data source: [NOAA National Data Buoy Center](https://www.ndbc.noaa.gov/). MIT licensed.
