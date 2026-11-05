"""Bronze layer: raw records as text, plus lineage columns. Append-only and idempotent."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path

import pandas as pd
from deltalake import DeltaTable, write_deltalake

from wavelake.ndbc import parse_stdmet, read_file


def _already_ingested(table_path: Path, file_hash: str) -> bool:
    if not DeltaTable.is_deltatable(str(table_path)):
        return False
    dt = DeltaTable(str(table_path))
    hashes = dt.to_pyarrow_table(columns=["file_sha256"]).column("file_sha256").to_pylist()
    return file_hash in set(hashes)


def ingest_file(path: Path, station: str, lake: Path) -> int:
    """Append one landed file to bronze. Returns rows written (0 if already ingested)."""
    table_path = lake / "bronze" / "stdmet"
    text = read_file(path)
    file_hash = hashlib.sha256(text.encode()).hexdigest()
    if _already_ingested(table_path, file_hash):
        return 0

    df = parse_stdmet(text)
    df.insert(0, "station_id", pd.array([station] * len(df), dtype="string"))
    df["source_file"] = path.name
    df["file_sha256"] = file_hash
    df["ingested_at"] = datetime.now(UTC)
    # Realtime files have PTDY and historical ones may not: let the schema grow.
    write_deltalake(str(table_path), df, mode="append", schema_mode="merge")
    return len(df)
