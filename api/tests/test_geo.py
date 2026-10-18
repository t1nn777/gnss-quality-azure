import numpy as np
import pandas as pd
import pytest

from geo import TraceError, clean_trace, default_odd_polygon, flag_anomalies, odd_check, trip_stats, validate_trace
from geo.generate_trace import generate_trace


@pytest.mark.parametrize("seed", [1, 2, 3, 4, 5])
def test_injected_jumps_are_flagged(seed):
    df = generate_trace(seed, noise_m=4.0, n_jumps=5)
    flags = flag_anomalies(validate_trace(df))
    jumps = df.attrs["jump_idx"]
    assert len(jumps) == 5
    assert flags[jumps].all()
    # and almost nothing else is flagged
    assert flags.sum() <= len(jumps) + 1


@pytest.mark.parametrize("seed", [1, 7, 42])
def test_smoothing_reduces_median_error(seed):
    stats = trip_stats(clean_trace(generate_trace(seed)))
    assert stats["median_err_smooth_m"] < stats["median_err_raw_m"]


def test_odd_check_full_coverage_polygon_is_100_percent():
    df = generate_trace(1)
    pad = 0.01
    lo0, lo1 = df["lon"].min() - pad, df["lon"].max() + pad
    la0, la1 = df["lat"].min() - pad, df["lat"].max() + pad
    poly = {"type": "Polygon", "coordinates": [[[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]]}
    res = odd_check(clean_trace(df), poly)
    assert res["pct_inside"] == 100.0
    assert res["events"] == []


def test_clean_trace_output_contract_and_extras():
    out = clean_trace(generate_trace(3), polygon=default_odd_polygon(10.7769, 106.7009))
    assert list(out.columns[:7]) == ["timestamp", "lat", "lon", "is_anomaly", "smooth_lat", "smooth_lon", "in_odd"]
    assert {"true_lat", "true_lon"} <= set(out.columns)
    assert out["in_odd"].notna().all()


def test_clean_trace_without_polygon_has_empty_in_odd():
    out = clean_trace(generate_trace(3))
    assert out["in_odd"].isna().all()
    assert "pct_in_odd" not in trip_stats(out)


def test_odd_events_report_exit_and_enter():
    df = clean_trace(generate_trace(1))
    first = df.iloc[0]
    # tiny polygon around the start only -> the trip exits once and never re-enters
    d = 0.0005
    poly = {"type": "Polygon", "coordinates": [[
        [first.smooth_lon - d, first.smooth_lat - d], [first.smooth_lon + d, first.smooth_lat - d],
        [first.smooth_lon + d, first.smooth_lat + d], [first.smooth_lon - d, first.smooth_lat + d],
        [first.smooth_lon - d, first.smooth_lat - d]]]}
    res = odd_check(df, poly)
    assert res["start_inside"] is True
    assert [e["type"] for e in res["events"]] == ["exit"]


@pytest.mark.parametrize(
    "frame, message",
    [
        (pd.DataFrame({"time": ["2026-01-01T00:00:00"], "lat": [1.0], "lon": [1.0]}), "Missing required column"),
        (pd.DataFrame({"timestamp": ["x", "y"], "lat": [1.0, 1.0], "lon": [1.0, 1.0]}), "ISO 8601"),
        (pd.DataFrame({"timestamp": ["2026-01-01T00:00:00", "2026-01-01T00:00:01"], "lat": [1.0, 95.0], "lon": [1.0, 1.0]}), "lat"),
    ],
)
def test_validate_trace_rejects_bad_input(frame, message):
    with pytest.raises(TraceError, match=message):
        validate_trace(frame)


def test_generator_is_deterministic_and_simulated_columns():
    a, b = generate_trace(9), generate_trace(9)
    pd.testing.assert_frame_equal(a, b)
    assert list(a.columns) == ["timestamp", "lat", "lon", "true_lat", "true_lon"]
    assert np.all(np.diff(a["timestamp"].astype("int64")) == 1_000_000_000)  # 1 Hz
