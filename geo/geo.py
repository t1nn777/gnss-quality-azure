"""GNSS trace cleaning algorithms, ported from reference/demo.py.

Pure functions only: no plotting, no file I/O. Every function takes / returns
pandas DataFrames or numpy arrays so the same code runs in the API, the UI
backend and Databricks (applyInPandas).

CSV contract
    input : timestamp,lat,lon            (ISO timestamps, 1 Hz)
    output: + is_anomaly,smooth_lat,smooth_lon,in_odd
"""
from __future__ import annotations

import json
from typing import Any

import numpy as np
import pandas as pd
import shapely
from shapely.geometry import MultiPolygon, Polygon, shape

M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON_EQUATOR = 111320.0
EARTH_RADIUS_M = 6371008.8

REQUIRED_COLUMNS = ("timestamp", "lat", "lon")
OUTPUT_COLUMNS = REQUIRED_COLUMNS + ("is_anomaly", "smooth_lat", "smooth_lon", "in_odd")
TRUTH_COLUMNS = ("true_lat", "true_lon")

# Demo ODD polygon in local metres (x east, y north) around DEMO_ODD_ANCHOR, the start
# of the simulated route (Cong Hoa, Tan Binh, HCMC). A ~45 m corridor along Cong Hoa and
# Hoang Hoa Tham that ends partway down Truong Chinh, so the simulated trip exits it once
# (~80% inside). It is fixed in place: uploaded traces elsewhere are simply outside it.
DEMO_ODD_ANCHOR = (10.802419, 106.640461)
DEMO_ODD_LOCAL_M = np.array(
    [[-30, -40], [-20, 50], [820, -25], [805, -95], [750, -740], [495, -605], [540, -525], [670, -595],
     [715, -105]],
    dtype=float,
)


class TraceError(ValueError):
    """Raised when an input trace does not follow the CSV contract."""


# --------------------------------------------------------------------------- #
# Validation
# --------------------------------------------------------------------------- #
def validate_trace(df: pd.DataFrame) -> pd.DataFrame:
    """Check the input contract and return a normalised copy sorted by time."""
    missing = [c for c in REQUIRED_COLUMNS if c not in df.columns]
    if missing:
        raise TraceError(
            f"Missing required column(s): {', '.join(missing)}. "
            f"Expected header: {','.join(REQUIRED_COLUMNS)}"
        )
    if len(df) < 2:
        raise TraceError("Trace must contain at least 2 points.")

    out = df.copy()
    try:
        out["timestamp"] = pd.to_datetime(out["timestamp"], format="ISO8601")
    except (ValueError, TypeError) as exc:
        raise TraceError("Column 'timestamp' must contain ISO 8601 timestamps.") from exc

    for col, lo, hi in (("lat", -90.0, 90.0), ("lon", -180.0, 180.0)):
        values = pd.to_numeric(out[col], errors="coerce")
        bad = values.isna() | (values < lo) | (values > hi)
        if bad.any():
            rows = ", ".join(str(i + 2) for i in np.flatnonzero(bad.to_numpy())[:5])
            raise TraceError(f"Column '{col}' must be a number in [{lo:g}, {hi:g}] (bad CSV line(s): {rows}).")
        out[col] = values.astype(float)

    out = out.sort_values("timestamp", kind="stable").reset_index(drop=True)
    if out["timestamp"].duplicated().any():
        raise TraceError("Timestamps must be unique.")
    return out


# --------------------------------------------------------------------------- #
# Geometry helpers
# --------------------------------------------------------------------------- #
def to_local_xy(lat, lon, lat0: float | None = None, lon0: float | None = None):
    """Equirectangular projection to metres around (lat0, lon0) (default: first point)."""
    lat = np.asarray(lat, dtype=float)
    lon = np.asarray(lon, dtype=float)
    lat0 = float(lat[0]) if lat0 is None else lat0
    lon0 = float(lon[0]) if lon0 is None else lon0
    m_per_deg_lon = M_PER_DEG_LON_EQUATOR * np.cos(np.radians(lat0))
    return (lon - lon0) * m_per_deg_lon, (lat - lat0) * M_PER_DEG_LAT


def from_local_xy(x, y, lat0: float, lon0: float):
    """Inverse of to_local_xy. Returns (lat, lon)."""
    m_per_deg_lon = M_PER_DEG_LON_EQUATOR * np.cos(np.radians(lat0))
    return lat0 + np.asarray(y, dtype=float) / M_PER_DEG_LAT, lon0 + np.asarray(x, dtype=float) / m_per_deg_lon


def haversine_m(lat1, lon1, lat2, lon2):
    """Great-circle distance in metres (vectorised)."""
    p1, p2 = np.radians(lat1), np.radians(lat2)
    dphi = p2 - p1
    dlmb = np.radians(np.asarray(lon2, dtype=float) - np.asarray(lon1, dtype=float))
    a = np.sin(dphi / 2) ** 2 + np.cos(p1) * np.cos(p2) * np.sin(dlmb / 2) ** 2
    return 2 * EARTH_RADIUS_M * np.arcsin(np.sqrt(a))


def _seconds(ts: pd.Series) -> np.ndarray:
    return (ts - ts.iloc[0]).dt.total_seconds().to_numpy()


# --------------------------------------------------------------------------- #
# 1. Anomaly detection by implied speed
# --------------------------------------------------------------------------- #
def implied_speed_kmh(df: pd.DataFrame) -> np.ndarray:
    """Speed from the previous point to each point (km/h). First point is 0."""
    x, y = to_local_xy(df["lat"], df["lon"])
    dt = np.diff(_seconds(df["timestamp"]))
    dt = np.where(dt > 0, dt, 1.0)
    speed = np.zeros(len(df))
    speed[1:] = np.hypot(np.diff(x), np.diff(y)) / dt * 3.6
    return speed


def flag_anomalies(df: pd.DataFrame, max_kmh: float = 200.0) -> np.ndarray:
    """Flag the jumped points (bool array).

    A jump makes both the step into and out of the bad point too fast; we keep
    the point that is far from both neighbours. Lone fast steps (e.g. two
    consecutive jumps) flag the entering point.
    """
    n = len(df)
    anom = np.zeros(n, dtype=bool)
    anom[1:] = implied_speed_kmh(df)[1:] > max_kmh

    flag = np.zeros(n, dtype=bool)
    for i in range(1, n - 1):
        if anom[i] and anom[i + 1]:
            flag[i] = True
    for i in range(1, n):  # consecutive jumps (and a jump on the last point)
        if anom[i] and not flag[i - 1] and not flag[i]:
            flag[i] = True
    return flag


# --------------------------------------------------------------------------- #
# 2. Kalman filter (constant velocity) with gating
# --------------------------------------------------------------------------- #
def kalman_smooth(
    df: pd.DataFrame, flags=None, meas_sigma_m: float = 4.0, gate: float = 16.0, max_gated: int = 3
) -> pd.DataFrame:
    """Return a DataFrame with smooth_lat / smooth_lon (same index as df).

    State [x, y, vx, vy], dt = 1 s, R = (4 m)^2 I. The update step is skipped
    when the point is flagged or its innovation Mahalanobis^2 exceeds `gate`.
    After `max_gated` consecutive unflagged points fail the gate, the model is
    assumed wrong (e.g. a sharp turn, which a constant-velocity model cannot
    follow), so the covariance is reset and the point is used again.
    """
    n = len(df)
    flags = np.zeros(n, dtype=bool) if flags is None else np.asarray(flags, dtype=bool)
    lat0, lon0 = float(df["lat"].iloc[0]), float(df["lon"].iloc[0])
    mx, my = to_local_xy(df["lat"], df["lon"], lat0, lon0)
    meas = np.column_stack([mx, my])

    dt = 1.0
    F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]], dtype=float)
    H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]], dtype=float)
    Q = np.diag([0.5, 0.5, 1.0, 1.0])
    R = np.eye(2) * meas_sigma_m**2
    x = np.array([meas[0, 0], meas[0, 1], 0.0, 0.0])
    P0 = np.diag([25.0, 25.0, 100.0, 100.0])
    P = P0.copy()

    smooth = np.zeros_like(meas)
    gated_run = 0
    for k in range(n):
        x = F @ x
        P = F @ P @ F.T + Q
        y = meas[k] - H @ x
        S = H @ P @ H.T + R
        accept = not flags[k] and y @ np.linalg.solve(S, y) < gate  # gating
        if not flags[k] and not accept:
            gated_run += 1
            if gated_run >= max_gated:  # filter lost track: re-anchor on the measurement
                P = P0.copy()
                S = H @ P @ H.T + R
                accept = True
        if accept:
            gated_run = 0
            K = P @ H.T @ np.linalg.inv(S)
            x = x + K @ y
            P = (np.eye(4) - K @ H) @ P
        smooth[k] = x[:2]

    slat, slon = from_local_xy(smooth[:, 0], smooth[:, 1], lat0, lon0)
    return pd.DataFrame({"smooth_lat": slat.round(6), "smooth_lon": slon.round(6)}, index=df.index)


# --------------------------------------------------------------------------- #
# 3. ODD (operational design domain) check
# --------------------------------------------------------------------------- #
def parse_polygon(polygon: Any) -> Polygon | MultiPolygon:
    """Accept a shapely (Multi)Polygon or GeoJSON (str/dict: geometry, Feature, FeatureCollection).

    GeoJSON coordinates are [lon, lat].
    """
    if isinstance(polygon, (Polygon, MultiPolygon)):
        geom = polygon
    else:
        try:
            obj = json.loads(polygon) if isinstance(polygon, (str, bytes)) else dict(polygon)
            if obj.get("type") == "FeatureCollection":
                obj = obj["features"][0]
            if obj.get("type") == "Feature":
                obj = obj["geometry"]
            geom = shape(obj)
        except Exception as exc:  # noqa: BLE001 - any parse problem is a user error
            raise TraceError(f"Invalid GeoJSON polygon: {exc}") from exc
    if not isinstance(geom, (Polygon, MultiPolygon)) or geom.is_empty:
        raise TraceError("ODD polygon must be a non-empty GeoJSON Polygon or MultiPolygon.")
    if not geom.is_valid:
        raise TraceError("ODD polygon is not valid (self-intersecting?).")
    return geom


def default_odd_polygon(lat0: float = DEMO_ODD_ANCHOR[0], lon0: float = DEMO_ODD_ANCHOR[1]) -> dict:
    """Demo ODD polygon as a GeoJSON Polygon dict (fixed in Tan Binh unless re-anchored)."""
    plat, plon = from_local_xy(DEMO_ODD_LOCAL_M[:, 0], DEMO_ODD_LOCAL_M[:, 1], lat0, lon0)
    ring = [[round(float(lo), 7), round(float(la), 7)] for la, lo in zip(plat, plon)]
    ring.append(ring[0])
    return {"type": "Polygon", "coordinates": [ring]}


def odd_check(df: pd.DataFrame, polygon: Any) -> dict:
    """Point-in-polygon per point (smoothed position if available).

    Returns {"in_odd": bool array, "pct_inside": float, "start_inside": bool,
             "events": [{"type": "exit"|"enter", "index": i, "timestamp": iso}]}.
    """
    geom = parse_polygon(polygon)
    shapely.prepare(geom)
    lat_col, lon_col = ("smooth_lat", "smooth_lon") if "smooth_lat" in df.columns else ("lat", "lon")
    inside = np.asarray(shapely.contains_xy(geom, df[lon_col].to_numpy(), df[lat_col].to_numpy()), dtype=bool)

    events = []
    for i in np.flatnonzero(inside[1:] != inside[:-1]) + 1:
        events.append({
            "type": "enter" if inside[i] else "exit",
            "index": int(i),
            "timestamp": pd.Timestamp(df["timestamp"].iloc[i]).isoformat(),
        })
    return {
        "in_odd": inside,
        "pct_inside": round(float(inside.mean() * 100), 2),
        "start_inside": bool(inside[0]),
        "events": events,
    }


# --------------------------------------------------------------------------- #
# 4. Stats + full pipeline
# --------------------------------------------------------------------------- #
def trip_stats(df: pd.DataFrame) -> dict:
    """Summary of a (raw or cleaned) trace. Optional columns add optional keys."""
    lat_col, lon_col = ("smooth_lat", "smooth_lon") if "smooth_lat" in df.columns else ("lat", "lon")
    lat, lon = df[lat_col].to_numpy(dtype=float), df[lon_col].to_numpy(dtype=float)
    dist_m = float(np.sum(haversine_m(lat[:-1], lon[:-1], lat[1:], lon[1:])))
    ts = pd.to_datetime(df["timestamp"])
    duration_s = float((ts.iloc[-1] - ts.iloc[0]).total_seconds())

    stats: dict[str, Any] = {
        "points": int(len(df)),
        "start_time": ts.iloc[0].isoformat(),
        "end_time": ts.iloc[-1].isoformat(),
        "duration_s": duration_s,
        "distance_km": round(dist_m / 1000, 3),
        "avg_speed_kmh": round(dist_m / duration_s * 3.6, 2) if duration_s > 0 else 0.0,
    }
    if "is_anomaly" in df.columns:
        flags = df["is_anomaly"].astype(bool).to_numpy()
        stats["anomalies"] = int(flags.sum())
        stats["anomaly_pct"] = round(float(flags.mean() * 100), 2)
    if "in_odd" in df.columns and df["in_odd"].notna().all():
        stats["pct_in_odd"] = round(float(df["in_odd"].astype(bool).mean() * 100), 2)
    if all(c in df.columns for c in TRUTH_COLUMNS) and df[list(TRUTH_COLUMNS)].notna().all().all():
        err_raw = haversine_m(df["lat"], df["lon"], df["true_lat"], df["true_lon"])
        stats["median_err_raw_m"] = round(float(np.median(err_raw)), 2)
        if "smooth_lat" in df.columns:
            err_sm = haversine_m(df["smooth_lat"], df["smooth_lon"], df["true_lat"], df["true_lon"])
            stats["median_err_smooth_m"] = round(float(np.median(err_sm)), 2)
    return stats


def clean_trace(df: pd.DataFrame, polygon: Any = None, max_kmh: float = 200.0) -> pd.DataFrame:
    """Validate, flag anomalies, smooth and (optionally) ODD-check a trace.

    Returns the output CSV contract columns first, then any extra input
    columns (e.g. true_lat/true_lon, trip_id) unchanged. `in_odd` is <NA>
    when no polygon is given.
    """
    trace = validate_trace(df)
    flags = flag_anomalies(trace, max_kmh=max_kmh)
    smooth = kalman_smooth(trace, flags)
    out = trace.assign(is_anomaly=flags, smooth_lat=smooth["smooth_lat"], smooth_lon=smooth["smooth_lon"])
    if polygon is None:
        out["in_odd"] = pd.array([pd.NA] * len(out), dtype="boolean")
    else:
        out["in_odd"] = pd.array(odd_check(out, polygon)["in_odd"], dtype="boolean")
    extras = [c for c in out.columns if c not in OUTPUT_COLUMNS]
    return out[list(OUTPUT_COLUMNS) + extras]
