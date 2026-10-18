"""Simulated GNSS trace generator (ported from reference/demo.py).

The output is SIMULATED data, not real vehicle data. It keeps the ground truth
(true_lat, true_lon) so smoothing error can be measured.

CLI:
    python -m geo.generate_trace --seed 1 --out sample.csv
"""
from __future__ import annotations

import argparse

import numpy as np
import pandas as pd

from geo.geo import from_local_xy, to_local_xy

# Simulated route on real streets around E-Town, 364 Cong Hoa, Tan Binh, Ho Chi Minh City:
# Cong Hoa (east) -> Hoang Hoa Tham (south) -> Truong Chinh (west), ~2 km.
# Road geometry from OpenStreetMap (ODbL) via OSRM; the trace itself is simulated.
ROUTE_LATLON = np.array([
    (10.802419, 106.640461),  # Cong Hoa, in front of E-Town
    (10.801826, 106.647469),  # Cong Hoa x Hoang Hoa Tham
    (10.796367, 106.646964),  # Hoang Hoa Tham x Truong Chinh
    (10.799041, 106.641960),  # Truong Chinh
])
LAT0, LON0 = float(ROUTE_LATLON[0, 0]), float(ROUTE_LATLON[0, 1])
WAYPOINTS_M = np.column_stack(to_local_xy(ROUTE_LATLON[:, 0], ROUTE_LATLON[:, 1], LAT0, LON0))
TIMESTAMP_FORMAT = "%Y-%m-%dT%H:%M:%S"


def _pick_jump_indices(rng: np.random.Generator, n: int, n_jumps: int, min_gap: int = 3) -> list[int]:
    """Random jump positions, at least `min_gap` points apart, away from the ends."""
    picked: list[int] = []
    for i in rng.permutation(np.arange(2, max(n - 2, 2))):
        if len(picked) >= n_jumps:
            break
        if all(abs(int(i) - j) >= min_gap for j in picked):
            picked.append(int(i))
    return sorted(picked)


def generate_trace(
    seed: int = 1,
    noise_m: float = 4.0,
    n_jumps: int = 5,
    *,
    speed_mps: float = 10.0,
    route_jitter_m: float = 0.0,
    lat0: float = LAT0,
    lon0: float = LON0,
    start: str | pd.Timestamp = "2026-10-15T08:00:00",
) -> pd.DataFrame:
    """Simulate a 1 Hz trace: waypoints -> ~10 m/s, Gaussian noise, multipath jumps of 80-180 m.

    Columns: timestamp, lat, lon, true_lat, true_lon. The injected jump indices
    are stored in df.attrs["jump_idx"].
    """
    rng = np.random.default_rng(seed)
    waypoints = WAYPOINTS_M.copy()
    if route_jitter_m > 0:  # vary the route between trips; the start stays at the origin
        waypoints[1:] += rng.normal(0, route_jitter_m, waypoints[1:].shape)

    seg = np.diff(waypoints, axis=0)
    cum = np.concatenate([[0], np.cumsum(np.hypot(seg[:, 0], seg[:, 1]))])
    s = np.arange(0, cum[-1], speed_mps)  # one point per second
    truth = np.column_stack([np.interp(s, cum, waypoints[:, i]) for i in range(2)])
    n = len(truth)

    meas = truth + rng.normal(0, noise_m, truth.shape)
    jump_idx = _pick_jump_indices(rng, n, n_jumps)
    for i in jump_idx:
        ang = rng.uniform(0, 2 * np.pi)
        d = rng.uniform(80, 180)
        meas[i] += d * np.array([np.cos(ang), np.sin(ang)])

    lat, lon = from_local_xy(meas[:, 0], meas[:, 1], lat0, lon0)
    tlat, tlon = from_local_xy(truth[:, 0], truth[:, 1], lat0, lon0)
    t0 = pd.Timestamp(start)
    df = pd.DataFrame({
        "timestamp": t0 + pd.to_timedelta(np.arange(n), unit="s"),
        "lat": lat.round(6),
        "lon": lon.round(6),
        "true_lat": tlat.round(6),
        "true_lon": tlon.round(6),
    })
    df.attrs["jump_idx"] = jump_idx
    return df


def to_csv_text(df: pd.DataFrame) -> str:
    return df.to_csv(index=False, date_format=TIMESTAMP_FORMAT)


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Generate a SIMULATED GNSS trace CSV.")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--noise", type=float, default=4.0, help="Gaussian noise sigma in metres")
    p.add_argument("--jumps", type=int, default=5, help="number of multipath jumps")
    p.add_argument("--jitter", type=float, default=0.0, help="route waypoint jitter in metres")
    p.add_argument("--out", default="sample.csv")
    a = p.parse_args(argv)
    df = generate_trace(a.seed, noise_m=a.noise, n_jumps=a.jumps, route_jitter_m=a.jitter)
    with open(a.out, "w", newline="", encoding="utf-8") as f:
        f.write(to_csv_text(df))
    print(f"Wrote {len(df)} simulated points to {a.out} (jumps at {df.attrs['jump_idx']})")


if __name__ == "__main__":
    main()
