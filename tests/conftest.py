"""Synthetic stdmet files in the exact NDBC layout. Values are generated, not real buoy data."""

from __future__ import annotations

import math

import pytest

HEADER = (
    "#YY  MM DD hh mm WDIR WSPD GST  WVHT   DPD   APD MWD   PRES  ATMP  WTMP  DEWP  VIS  TIDE\n"
    "#yr  mo dy hr mn degT m/s  m/s     m   sec   sec degT   hPa  degC  degC  degC  mi    ft\n"
)


def make_stdmet(hours: int = 72, start_day: int = 1, storm_at: int | None = 30,
                missing_every: int = 0, bad_rows: dict[int, str] | None = None) -> str:
    lines = [HEADER.rstrip("\n")]
    for h in range(hours):
        day, hour = start_day + h // 24, h % 24
        hs = 1.5 + 0.3 * math.sin(h / 6)
        if storm_at is not None and storm_at <= h < storm_at + 6:
            hs = 5.0 + 0.2 * (h - storm_at)
        wvht = f"{hs:5.2f}"
        if missing_every and h % missing_every == 0:
            wvht = "99.00"
        row = (f"2023 01 {day:02d} {hour:02d} 00 270  8.0 10.0 {wvht} 11.00  7.20 280 "
               f"1012.0  14.0  15.5 999.0 99.0 99.00")
        if bad_rows and h in bad_rows:
            row = bad_rows[h]
        lines.append(row)
    return "\n".join(lines) + "\n"


@pytest.fixture
def stdmet_file(tmp_path):
    path = tmp_path / "TEST1h2023.txt"
    path.write_text(make_stdmet())
    return path
