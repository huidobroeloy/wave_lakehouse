from __future__ import annotations

import pandas as pd
import pytest
from conftest import make_stdmet
from deltalake import DeltaTable

from wavelake import bronze, gold, ndbc, quality, silver


def test_parse_keeps_everything_as_text():
    df = ndbc.parse_stdmet(make_stdmet(hours=5))
    assert len(df) == 5
    assert "WVHT" in df and str(df["WVHT"].dtype) == "string"


def test_parse_rejects_non_ndbc_text():
    with pytest.raises(ValueError):
        ndbc.parse_stdmet("hello\nworld\n")


def test_sentinels_become_null():
    raw = ndbc.parse_stdmet(make_stdmet(hours=6, missing_every=2))
    raw["station_id"] = "TEST1"
    raw["ingested_at"] = pd.Timestamp.now(tz="UTC")
    out = silver.transform(raw)
    assert out["wave_height_m"].isna().sum() == 3
    assert out["air_temp_c"].notna().all()
    assert out["ts"].dt.tz is not None


def test_range_checks_null_and_flag():
    df = pd.DataFrame({"wave_height_m": [2.0, 40.0], "wind_speed_ms": [5.0, 5.0], "gust_ms": [7.0, 3.0]})
    out = quality.apply_range_checks(df)
    assert pd.isna(out.loc[1, "wave_height_m"])
    assert "wave_height_m_out_of_range" in out.loc[1, "qc_flags"]
    assert "gust_below_wind" in out.loc[1, "qc_flags"]
    assert out.loc[0, "qc_flags"] == ""


def test_storm_event_detected():
    raw = ndbc.parse_stdmet(make_stdmet(hours=72, storm_at=30))
    raw["station_id"] = "TEST1"
    raw["ingested_at"] = pd.Timestamp.now(tz="UTC")
    events = gold.storm_events(silver.transform(raw))
    assert len(events) == 1
    ev = events.iloc[0]
    assert ev["duration_h"] >= 3
    assert ev["hs_peak_m"] == pytest.approx(6.0)


def test_end_to_end_is_idempotent_and_incremental(tmp_path, stdmet_file):
    lake = tmp_path / "lake"
    assert bronze.ingest_file(stdmet_file, "TEST1", lake) == 72
    assert bronze.ingest_file(stdmet_file, "TEST1", lake) == 0  # same file twice: skipped

    assert silver.build(lake) == 72
    assert silver.build(lake) == 0  # nothing new since last run

    # A later file overlapping one day: overlapping timestamps are updated, not duplicated.
    later = tmp_path / "TEST1_realtime.txt"
    later.write_text(make_stdmet(hours=48, start_day=3, storm_at=None))
    bronze.ingest_file(later, "TEST1", lake)
    silver.build(lake)

    obs = DeltaTable(str(lake / "silver" / "observations")).to_pandas()
    assert len(obs) == 72 + 24
    assert not obs.duplicated(["station_id", "ts"]).any()

    counts = gold.build(lake)
    assert counts["daily_stats"] == 4
    daily = DeltaTable(str(lake / "gold" / "daily_stats")).to_pandas()
    assert daily["n_obs"].eq(24).all()
