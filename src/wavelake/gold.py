"""Gold layer: analysis-ready tables, rebuilt from silver on every run."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from deltalake import DeltaTable, write_deltalake


def daily_stats(silver: pd.DataFrame) -> pd.DataFrame:
    df = silver.assign(date=silver["ts"].dt.tz_convert("UTC").dt.date)
    g = df.groupby(["station_id", "date"])
    out = pd.DataFrame({
        "n_obs": g.size(),
        "n_wave_obs": g["wave_height_m"].count(),
        "hs_mean_m": g["wave_height_m"].mean(),
        "hs_max_m": g["wave_height_m"].max(),
        "hs_p95_m": g["wave_height_m"].quantile(0.95),
        "tp_mean_s": g["dominant_period_s"].mean(),
        "wind_speed_mean_ms": g["wind_speed_ms"].mean(),
        "water_temp_mean_c": g["water_temp_c"].mean(),
    }).reset_index()
    numeric = out.select_dtypes("number").columns
    out[numeric] = out[numeric].round(3)
    out["date"] = pd.to_datetime(out["date"])
    return out


def storm_events(silver: pd.DataFrame, quantile: float = 0.95, min_hours: float = 3.0,
                 max_gap_hours: float = 2.0) -> pd.DataFrame:
    """Peaks-over-threshold events: Hs above the station's own quantile for at least min_hours.

    Gaps up to max_gap_hours inside an event are bridged (missing data, short dips).
    """
    events = []
    for station, df in silver.dropna(subset=["wave_height_m"]).groupby("station_id"):
        df = df.sort_values("ts")
        threshold = df["wave_height_m"].quantile(quantile)
        above = df[df["wave_height_m"] > threshold]
        if above.empty:
            continue
        gap = above["ts"].diff() > pd.Timedelta(hours=max_gap_hours)
        for _, ev in above.groupby(gap.cumsum()):
            duration = (ev["ts"].iloc[-1] - ev["ts"].iloc[0]) / pd.Timedelta(hours=1)
            if duration < min_hours:
                continue
            peak = ev.loc[ev["wave_height_m"].idxmax()]
            events.append({
                "station_id": station,
                "start": ev["ts"].iloc[0],
                "end": ev["ts"].iloc[-1],
                "duration_h": round(duration, 2),
                "hs_peak_m": peak["wave_height_m"],
                "tp_at_peak_s": peak["dominant_period_s"],
                "threshold_m": round(threshold, 3),
            })
    cols = ["station_id", "start", "end", "duration_h", "hs_peak_m", "tp_at_peak_s", "threshold_m"]
    return pd.DataFrame(events, columns=cols)


def build(lake: Path) -> dict[str, int]:
    silver = DeltaTable(str(lake / "silver" / "observations")).to_pandas()
    tables = {"daily_stats": daily_stats(silver), "storm_events": storm_events(silver)}
    for name, df in tables.items():
        write_deltalake(str(lake / "gold" / name), df, mode="overwrite", schema_mode="overwrite")
    return {name: len(df) for name, df in tables.items()}
