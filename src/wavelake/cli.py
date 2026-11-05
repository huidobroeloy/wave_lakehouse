"""Command line entry point: wavelake {ingest,build,report,run}."""

from __future__ import annotations

import argparse
from pathlib import Path

from deltalake import DeltaTable

from wavelake import bronze, gold, ndbc, quality, silver


def _ingest(args: argparse.Namespace) -> None:
    lake = Path(args.lake)
    for station in args.stations:
        years = args.years or [None]
        for year in years:
            path = ndbc.download(station, year, lake / "landing")
            n = bronze.ingest_file(path, station, lake)
            label = year or "realtime"
            print(f"bronze  {station} {label}: {n} rows" + ("" if n else " (already ingested)"))


def _ingest_file(args: argparse.Namespace) -> None:
    n = bronze.ingest_file(Path(args.path), args.station, Path(args.lake))
    print(f"bronze  {args.station} {Path(args.path).name}: {n} rows")


def _build(args: argparse.Namespace) -> None:
    lake = Path(args.lake)
    print(f"silver  {silver.build(lake)} rows merged")
    for name, n in gold.build(lake).items():
        print(f"gold    {name}: {n} rows")


def _report(args: argparse.Namespace) -> None:
    df = DeltaTable(str(Path(args.lake) / "silver" / "observations")).to_pandas()
    print(quality.summary(df).to_string(index=False))


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="wavelake", description=__doc__)
    p.add_argument("--lake", default="lake", help="lake root directory (default: ./lake)")
    sub = p.add_subparsers(required=True)

    ing = sub.add_parser("ingest", help="download NDBC files and append them to bronze")
    ing.add_argument("stations", nargs="+")
    ing.add_argument("--years", nargs="*", type=int, help="historical years; omit for realtime")
    ing.set_defaults(func=_ingest)

    f = sub.add_parser("ingest-file", help="append a local stdmet file to bronze")
    f.add_argument("path")
    f.add_argument("--station", required=True)
    f.set_defaults(func=_ingest_file)

    sub.add_parser("build", help="update silver and rebuild gold").set_defaults(func=_build)
    sub.add_parser("report", help="data quality summary").set_defaults(func=_report)

    run = sub.add_parser("run", help="ingest + build")
    run.add_argument("stations", nargs="+")
    run.add_argument("--years", nargs="*", type=int)
    run.set_defaults(func=lambda a: (_ingest(a), _build(a)))

    args = p.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
