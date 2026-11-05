"""Data quality rules. Out-of-range values are set to null and recorded in qc_flags,
so nothing is silently dropped and every correction is traceable."""

from __future__ import annotations

import pandas as pd

# Physically plausible ranges for open-ocean buoys (inclusive).
RANGES = {
    "wave_height_m": (0.0, 25.0),
    "dominant_period_s": (1.0, 30.0),
    "avg_period_s": (1.0, 25.0),
    "mean_wave_dir_deg": (0.0, 360.0),
    "wind_dir_deg": (0.0, 360.0),
    "wind_speed_ms": (0.0, 80.0),
    "gust_ms": (0.0, 100.0),
    "pressure_hpa": (870.0, 1085.0),
    "air_temp_c": (-40.0, 50.0),
    "water_temp_c": (-3.0, 40.0),
}


def apply_range_checks(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    flags = pd.Series([""] * len(out), index=out.index, dtype="string")
    for col, (lo, hi) in RANGES.items():
        if col not in out:
            continue
        bad = out[col].notna() & ~out[col].between(lo, hi)
        flags = flags.where(~bad, flags + f"{col}_out_of_range;")
        out.loc[bad, col] = float("nan")
    # Gusts can't be weaker than the mean wind.
    bad_gust = out["gust_ms"].notna() & out["wind_speed_ms"].notna() & (out["gust_ms"] < out["wind_speed_ms"])
    flags = flags.where(~bad_gust, flags + "gust_below_wind;")
    out["qc_flags"] = flags.str.rstrip(";")
    return out


def summary(silver: pd.DataFrame) -> pd.DataFrame:
    """Completeness and flag counts per station, for the quality report."""
    measures = [c for c in RANGES if c in silver]
    g = silver.groupby("station_id")
    report = g[measures].apply(lambda x: x.notna().mean().round(3))
    report.columns = [f"{c}_completeness" for c in report.columns]
    report["rows"] = g.size()
    report["flagged_rows"] = g["qc_flags"].apply(lambda s: (s != "").sum())
    return report.reset_index()
