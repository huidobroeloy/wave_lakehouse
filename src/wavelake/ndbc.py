"""Download and parse NOAA NDBC standard meteorological (stdmet) buoy files.

Format reference: https://www.ndbc.noaa.gov/faq/measdes.shtml
Historical files mark missing values with 9s (99.0, 999, 9999.0); realtime files use "MM".
"""

from __future__ import annotations

import gzip
import io
import urllib.request
from pathlib import Path

import pandas as pd

HISTORICAL_URL = "https://www.ndbc.noaa.gov/data/historical/stdmet/{station}h{year}.txt.gz"
REALTIME_URL = "https://www.ndbc.noaa.gov/data/realtime2/{station}.txt"

# Column name in the NDBC header -> sentinel values meaning "missing".
MISSING = {
    "WDIR": {"999", "MM"},
    "WSPD": {"99.0", "MM"},
    "GST": {"99.0", "MM"},
    "WVHT": {"99.00", "99.0", "MM"},
    "DPD": {"99.00", "99.0", "MM"},
    "APD": {"99.00", "99.0", "MM"},
    "MWD": {"999", "MM"},
    "PRES": {"9999.0", "MM"},
    "ATMP": {"999.0", "MM"},
    "WTMP": {"999.0", "MM"},
    "DEWP": {"999.0", "MM"},
    "VIS": {"99.0", "MM"},
    "PTDY": {"99.0", "MM"},
    "TIDE": {"99.00", "99.0", "MM"},
}


def download(station: str, year: int | None, landing_dir: Path) -> Path:
    """Fetch one station file into the landing zone and return its path.

    year=None downloads the realtime file (last 45 days).
    """
    landing_dir.mkdir(parents=True, exist_ok=True)
    if year is None:
        url = REALTIME_URL.format(station=station)
        target = landing_dir / f"{station}_realtime.txt"
    else:
        url = HISTORICAL_URL.format(station=station, year=year)
        target = landing_dir / f"{station}h{year}.txt"
    req = urllib.request.Request(url, headers={"User-Agent": "wave-lakehouse"})
    with urllib.request.urlopen(req, timeout=60) as resp:
        payload = resp.read()
    if url.endswith(".gz"):
        payload = gzip.decompress(payload)
    target.write_bytes(payload)
    return target


def parse_stdmet(text: str) -> pd.DataFrame:
    """Parse a stdmet file into a DataFrame of strings (no type casting).

    Keeping everything as text in bronze means a format change upstream never
    breaks ingestion; typing and validation happen in silver.
    """
    lines = [ln for ln in text.splitlines() if ln.strip()]
    if not lines or not lines[0].startswith("#"):
        raise ValueError("Not an NDBC stdmet file: missing '#' header line")
    header = lines[0].lstrip("#").split()
    # Date columns: 'MM' (month) and 'mm' (minute) differ only by case, which Delta Lake
    # rejects, so they get explicit names. Older files use 'YYYY' and have no minute column.
    dates = {"YY": "year", "YYYY": "year", "MM": "month", "DD": "day", "hh": "hour", "mm": "minute"}
    header = [dates.get(h, h) for h in header]
    rows = [ln.split() for ln in lines[1:] if not ln.startswith("#")]
    bad = [r for r in rows if len(r) != len(header)]
    if bad:
        raise ValueError(f"{len(bad)} rows do not match the {len(header)} header columns")
    return pd.DataFrame(rows, columns=header, dtype="string")


def read_file(path: Path) -> str:
    raw = path.read_bytes()
    if raw[:2] == b"\x1f\x8b":
        raw = gzip.decompress(raw)
    return io.TextIOWrapper(io.BytesIO(raw), encoding="utf-8").read()
