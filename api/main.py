"""GNSS Trace Quality Checker API (FastAPI). Processes one SIMULATED trip per request.

Run locally (from api/):  uvicorn main:app --reload
On App Service:           gunicorn -w 2 -k uvicorn.workers.UvicornWorker main:app

How `geo` is found: in the repo, geo/ sits next to api/, so we add the repo root
to sys.path. On App Service the deploy workflow copies geo/ into the api package,
so it is importable from the app folder directly. One source of truth, no pip
package to publish.
"""
from __future__ import annotations

import io
import json
import logging
import os
import sys
import time
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent
if (_REPO_ROOT / "geo").is_dir() and str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

# Must run before FastAPI is imported so the FastAPI instrumentation can patch it.
if os.getenv("APPLICATIONINSIGHTS_CONNECTION_STRING"):
    from azure.monitor.opentelemetry import configure_azure_monitor

    configure_azure_monitor()

import pandas as pd  # noqa: E402
from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile  # noqa: E402
from fastapi.responses import Response  # noqa: E402

import geo  # noqa: E402
from geo.generate_trace import generate_trace, to_csv_text  # noqa: E402

logger = logging.getLogger("gnss.api")
logger.setLevel(logging.INFO)

MAX_UPLOAD_BYTES = 20 * 1024 * 1024
CSV_DATE_FORMAT = "%Y-%m-%dT%H:%M:%S"

app = FastAPI(
    title="GNSS Trace Quality Checker",
    version="1.0.0",
    description="Flags anomalies, smooths and ODD-checks GNSS traces. Demo data is simulated, not real vehicle data.",
)

MaxKmh = Query(200.0, gt=0, le=2000, description="Implied-speed threshold for anomalies (km/h)")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
async def _read_trace(file: UploadFile) -> pd.DataFrame:
    content = await file.read()
    if not content:
        raise HTTPException(422, "Uploaded file is empty. Expected a CSV with header timestamp,lat,lon.")
    if len(content) > MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"File too large (max {MAX_UPLOAD_BYTES // (1024 * 1024)} MB).")
    try:
        df = pd.read_csv(io.BytesIO(content))
    except (pd.errors.ParserError, pd.errors.EmptyDataError, UnicodeDecodeError) as exc:
        raise HTTPException(422, f"Could not parse CSV: {exc}") from exc
    try:
        return geo.validate_trace(df)
    except geo.TraceError as exc:
        raise HTTPException(422, str(exc)) from exc


def _clean(df: pd.DataFrame, polygon=None, max_kmh: float = 200.0) -> pd.DataFrame:
    try:
        return geo.clean_trace(df, polygon=polygon, max_kmh=max_kmh)
    except geo.TraceError as exc:
        raise HTTPException(422, str(exc)) from exc


def _parse_polygon_field(polygon: str | None):
    if polygon is None or not polygon.strip():
        return None
    try:
        geo.parse_polygon(polygon)
    except geo.TraceError as exc:
        raise HTTPException(422, str(exc)) from exc
    return json.loads(polygon)


def _records(df: pd.DataFrame) -> list[dict]:
    # to_json turns NaN / <NA> into null and timestamps into ISO strings
    return json.loads(df.to_json(orient="records", date_format="iso"))


def _csv_response(df: pd.DataFrame, filename: str) -> Response:
    return Response(
        content=df.to_csv(index=False, date_format=CSV_DATE_FORMAT),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# --------------------------------------------------------------------------- #
# Endpoints
# --------------------------------------------------------------------------- #
@app.get("/health")
def health() -> dict:
    return {"status": "ok"}


@app.get("/trace/sample", response_class=Response)
def sample(
    seed: int = Query(1, ge=0, le=1_000_000),
    noise_m: float = Query(4.0, ge=0, le=50),
    n_jumps: int = Query(5, ge=0, le=50),
) -> Response:
    """A SIMULATED trace (with ground truth columns true_lat/true_lon)."""
    df = generate_trace(seed, noise_m=noise_m, n_jumps=n_jumps)
    return Response(
        content=to_csv_text(df),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="simulated_trace_seed{seed}.csv"'},
    )


@app.post("/trace/stats")
async def stats(file: UploadFile = File(...), max_kmh: float = MaxKmh) -> dict:
    df = await _read_trace(file)
    return geo.trip_stats(_clean(df, max_kmh=max_kmh))


@app.post("/trace/anomalies")
async def anomalies(file: UploadFile = File(...), max_kmh: float = MaxKmh) -> dict:
    df = await _read_trace(file)
    flags = geo.flag_anomalies(df, max_kmh=max_kmh)
    speed = geo.implied_speed_kmh(df)
    points = [
        {
            "index": int(i),
            "timestamp": df["timestamp"].iloc[i].isoformat(),
            "lat": float(df["lat"].iloc[i]),
            "lon": float(df["lon"].iloc[i]),
            "speed_kmh": round(float(speed[i]), 1),
        }
        for i in flags.nonzero()[0]
    ]
    return {"max_kmh": max_kmh, "count": len(points), "points": points}


@app.post("/trace/smooth", response_class=Response)
async def smooth(file: UploadFile = File(...), max_kmh: float = MaxKmh) -> Response:
    df = await _read_trace(file)
    out = _clean(df, max_kmh=max_kmh).drop(columns=["in_odd"])
    return _csv_response(out, "smoothed_trace.csv")


@app.post("/trace/odd-check")
async def odd_check(
    file: UploadFile = File(...),
    polygon: str = Form(..., description="GeoJSON Polygon/MultiPolygon/Feature, coordinates [lon, lat]"),
    max_kmh: float = MaxKmh,
) -> dict:
    df = await _read_trace(file)
    poly = _parse_polygon_field(polygon)
    if poly is None:
        raise HTTPException(422, "Form field 'polygon' (GeoJSON) is required.")
    res = geo.odd_check(_clean(df, max_kmh=max_kmh), poly)
    return {"pct_inside": res["pct_inside"], "start_inside": res["start_inside"], "events": res["events"]}


@app.post("/trace/clean")
async def clean(
    file: UploadFile = File(...),
    polygon: str | None = Form(None, description="Optional GeoJSON ODD polygon, coordinates [lon, lat]"),
    use_default_odd: bool = Form(False, description="Use the demo ODD polygon anchored at the first point"),
    max_kmh: float = MaxKmh,
) -> dict:
    """Everything the UI needs: summary + per-point output."""
    t_start = time.perf_counter()
    df = await _read_trace(file)
    poly = _parse_polygon_field(polygon)
    if poly is None and use_default_odd:
        poly = geo.default_odd_polygon(float(df["lat"].iloc[0]), float(df["lon"].iloc[0]))

    out = _clean(df, polygon=poly, max_kmh=max_kmh)
    summary = geo.trip_stats(out)
    summary["max_kmh"] = max_kmh
    summary["odd_polygon"] = poly
    if poly is not None:
        res = geo.odd_check(out, poly)
        summary["odd_events"] = res["events"]
        summary["odd_start_inside"] = res["start_inside"]

    elapsed_ms = round((time.perf_counter() - t_start) * 1000, 1)
    summary["processing_ms"] = elapsed_ms
    logger.info(
        "trace cleaned: %d points, %d anomalies, %.1f ms",
        summary["points"], summary["anomalies"], elapsed_ms,
        extra={"trip_points": summary["points"], "anomalies": summary["anomalies"], "processing_ms": elapsed_ms},
    )
    return {"summary": summary, "points": _records(out)}
