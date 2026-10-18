"""Generate a SIMULATED fleet of GNSS trips for the Databricks pipeline.

    python scripts/make_fleet.py --trips 200 --out data/fleet

Each trip varies noise, number of multipath jumps and route shape. Output is
one CSV per trip: trip_id,timestamp,lat,lon,true_lat,true_lon.

Upload to the Unity Catalog volume created by notebook 00_setup:

    databricks fs cp -r data/fleet dbfs:/Volumes/<catalog>/gnss/raw/ --overwrite
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from geo.generate_trace import TIMESTAMP_FORMAT, generate_trace  # noqa: E402


def make_fleet(n_trips: int, out_dir: Path, seed: int = 2026) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    out_dir.mkdir(parents=True, exist_ok=True)
    meta = []
    start = pd.Timestamp("2026-10-01T06:00:00")
    for i in range(1, n_trips + 1):
        trip_id = f"trip_{i:03d}"
        noise_m = float(rng.uniform(2.0, 10.0))
        n_jumps = int(rng.integers(0, 13))
        jitter_m = float(rng.uniform(0.0, 60.0))
        t0 = start + pd.Timedelta(minutes=int(rng.integers(0, 60 * 24 * 14)))
        df = generate_trace(seed * 10_000 + i, noise_m=noise_m, n_jumps=n_jumps, route_jitter_m=jitter_m, start=t0)
        df.insert(0, "trip_id", trip_id)
        df.to_csv(out_dir / f"{trip_id}.csv", index=False, date_format=TIMESTAMP_FORMAT)
        meta.append({"trip_id": trip_id, "points": len(df), "noise_m": round(noise_m, 2),
                     "n_jumps": n_jumps, "route_jitter_m": round(jitter_m, 1)})
    return pd.DataFrame(meta)


def main() -> None:
    p = argparse.ArgumentParser(description="Generate a SIMULATED GNSS fleet (one CSV per trip).")
    p.add_argument("--trips", type=int, default=200)
    p.add_argument("--out", default="data/fleet")
    p.add_argument("--seed", type=int, default=2026)
    a = p.parse_args()
    out = Path(a.out)
    meta = make_fleet(a.trips, out, a.seed)
    meta.to_csv(out.parent / "fleet_manifest.csv", index=False)
    print(f"Wrote {len(meta)} simulated trips ({meta['points'].sum()} points) to {out}/")


if __name__ == "__main__":
    main()
