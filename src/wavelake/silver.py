"""Silver layer: typed, validated, deduplicated observations. Incremental MERGE on (station_id, ts)."""

from __future__ import annotations

from pathlib import Path

import pandas as pd
import pyarrow as pa
from deltalake import DeltaTable, write_deltalake

from wavelake.ndbc import MISSING
from wavelake.quality import apply_range_checks

RENAME = {
    "WDIR": "wind_dir_deg",
    "WSPD": "wind_speed_ms",
    "GST": "gust_ms",
    "WVHT": "wave_height_m",
    "DPD": "dominant_period_s",
    "APD": "avg_period_s",
    "MWD": "mean_wave_dir_deg",
    "PRES": "pressure_hpa",
    "ATMP": "air_temp_c",
    "WTMP": "water_temp_c",
}

SILVER_COLUMNS = ["station_id", "ts", *RENAME.values(), "qc_flags", "_bronze_ingested_at"]


def _new_bronze_rows(lake: Path) -> pd.DataFrame:
    bronze = DeltaTable(str(lake / "bronze" / "stdmet")).to_pandas()
    silver_path = lake / "silver" / "observations"
    if DeltaTable.is_deltatable(str(silver_path)):
        watermark = (
            DeltaTable(str(silver_path))
            .to_pyarrow_table(columns=["_bronze_ingested_at"])
            .column("_bronze_ingested_at")
            .to_pandas()
            .max()
        )
        bronze = bronze[bronze["ingested_at"] > watermark]
    return bronze


def transform(bronze: pd.DataFrame) -> pd.DataFrame:
    """Bronze strings -> typed silver rows. Pure function, unit tested."""
    df = bronze.copy()
    for col, sentinels in MISSING.items():
        if col in df:
            df[col] = df[col].where(~df[col].isin(sentinels))

    year = df["year"].astype(int)
    year = year.where(year > 99, year + 1900)  # pre-1999 files use 2-digit years
    minute = df["minute"].fillna("0") if "minute" in df else pd.Series("0", index=df.index)
    df["ts"] = pd.to_datetime(
        dict(year=year, month=df["month"].astype(int), day=df["day"].astype(int),
             hour=df["hour"].astype(int), minute=minute.astype(int)),
        utc=True,
    )

    out = pd.DataFrame({"station_id": df["station_id"].astype(str), "ts": df["ts"]})
    for src, dst in RENAME.items():
        out[dst] = pd.to_numeric(df[src], errors="coerce") if src in df else float("nan")
    out = apply_range_checks(out)
    out["_bronze_ingested_at"] = df["ingested_at"]

    # Same timestamp landed twice (e.g. realtime then historical): keep the latest ingestion.
    out = out.sort_values("_bronze_ingested_at").drop_duplicates(["station_id", "ts"], keep="last")
    return out[SILVER_COLUMNS].reset_index(drop=True)


def build(lake: Path) -> int:
    """Merge new bronze rows into silver. Returns rows processed."""
    new = _new_bronze_rows(lake)
    if new.empty:
        return 0
    rows = transform(new)
    table = pa.Table.from_pandas(rows, preserve_index=False)
    silver_path = lake / "silver" / "observations"
    if not DeltaTable.is_deltatable(str(silver_path)):
        write_deltalake(str(silver_path), table, partition_by=["station_id"])
    else:
        (
            DeltaTable(str(silver_path))
            .merge(table, "t.station_id = s.station_id AND t.ts = s.ts",
                   source_alias="s", target_alias="t")
            .when_matched_update_all()
            .when_not_matched_insert_all()
            .execute()
        )
    return len(rows)
