import io
import json
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from api.main import app
from geo.generate_trace import generate_trace, to_csv_text

client = TestClient(app)
SAMPLES = Path(__file__).resolve().parents[2] / "samples"


def _upload(csv_text: str):
    return {"file": ("trace.csv", csv_text.encode(), "text/csv")}


@pytest.fixture(scope="module")
def sample_csv() -> str:
    return to_csv_text(generate_trace(1))


def test_health():
    assert client.get("/health").json() == {"status": "ok"}


def test_root_redirects_to_docs():
    r = client.get("/", follow_redirects=False)
    assert r.status_code in (302, 307)
    assert r.headers["location"] == "/docs"


def test_sample_returns_simulated_csv():
    r = client.get("/trace/sample", params={"seed": 2, "n_jumps": 3})
    assert r.status_code == 200
    df = pd.read_csv(io.StringIO(r.text))
    assert list(df.columns) == ["timestamp", "lat", "lon", "true_lat", "true_lon"]


def test_stats(sample_csv):
    r = client.post("/trace/stats", files=_upload(sample_csv))
    assert r.status_code == 200
    body = r.json()
    assert body["points"] == 200
    assert body["anomalies"] == 5
    assert body["median_err_smooth_m"] < body["median_err_raw_m"]


def test_anomalies_threshold(sample_csv):
    strict = client.post("/trace/anomalies", files=_upload(sample_csv), params={"max_kmh": 200}).json()
    assert strict["count"] == 5
    assert {"index", "timestamp", "lat", "lon", "speed_kmh"} <= set(strict["points"][0])
    loose = client.post("/trace/anomalies", files=_upload(sample_csv), params={"max_kmh": 2000}).json()
    assert loose["count"] == 0


def test_smooth_returns_csv(sample_csv):
    r = client.post("/trace/smooth", files=_upload(sample_csv))
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/csv")
    df = pd.read_csv(io.StringIO(r.text))
    assert {"smooth_lat", "smooth_lon", "is_anomaly"} <= set(df.columns)


def test_odd_check(sample_csv):
    df = pd.read_csv(io.StringIO(sample_csv))
    lo0, lo1, la0, la1 = df.lon.min() - 1, df.lon.max() + 1, df.lat.min() - 1, df.lat.max() + 1
    poly = {"type": "Polygon", "coordinates": [[[lo0, la0], [lo1, la0], [lo1, la1], [lo0, la1], [lo0, la0]]]}
    r = client.post("/trace/odd-check", files=_upload(sample_csv), data={"polygon": json.dumps(poly)})
    assert r.status_code == 200
    assert r.json()["pct_inside"] == 100.0


def test_clean_with_default_odd(sample_csv):
    r = client.post("/trace/clean", files=_upload(sample_csv), data={"use_default_odd": "true"})
    assert r.status_code == 200
    body = r.json()
    assert 0 < body["summary"]["pct_in_odd"] <= 100
    assert body["summary"]["odd_polygon"]["type"] == "Polygon"
    assert len(body["points"]) == body["summary"]["points"]
    assert {"is_anomaly", "smooth_lat", "smooth_lon", "in_odd", "true_lat"} <= set(body["points"][0])


def test_default_odd_is_fixed_in_place(sample_csv):
    # A trace elsewhere must not drag the demo ODD along with its first point.
    df = pd.read_csv(io.StringIO(sample_csv))
    moved = df.assign(lat=df.lat + 0.05, lon=df.lon + 0.05)
    home = client.post("/trace/clean", files=_upload(sample_csv), data={"use_default_odd": "true"}).json()["summary"]
    away = client.post("/trace/clean", files=_upload(to_csv_text(moved)), data={"use_default_odd": "true"}).json()["summary"]
    assert away["odd_polygon"] == home["odd_polygon"]
    assert away["pct_in_odd"] == 0.0


def test_clean_with_uploaded_sample_files():
    csv_text = (SAMPLES / "trip_tan_binh_simulated.csv").read_text(encoding="utf-8")
    polygon = (SAMPLES / "odd_cong_hoa_only.geojson").read_text(encoding="utf-8")
    r = client.post("/trace/clean", files=_upload(csv_text), data={"polygon": polygon, "use_default_odd": "true"})
    assert r.status_code == 200
    summary = r.json()["summary"]
    assert summary["odd_polygon"]["type"] == "Polygon"  # uploaded FeatureCollection, normalised; it wins over the default
    assert 0 < summary["pct_in_odd"] < 100
    assert [e["type"] for e in summary["odd_events"]] == ["exit"]


def test_clean_without_odd_has_null_in_odd(sample_csv):
    body = client.post("/trace/clean", files=_upload(sample_csv)).json()
    assert body["summary"]["odd_polygon"] is None
    assert body["points"][0]["in_odd"] is None


@pytest.mark.parametrize(
    "csv_text, fragment",
    [
        ("time,lat,lon\n2026-01-01T00:00:00,1,1\n", "Missing required column"),
        ("timestamp,lat,lon\nnot-a-date,1,1\nnope,1,1\n", "ISO 8601"),
        ("timestamp,lat,lon\n2026-01-01T00:00:00,abc,1\n2026-01-01T00:00:01,1,1\n", "'lat'"),
        ("", "empty"),
    ],
)
def test_bad_csv_returns_422(csv_text, fragment):
    r = client.post("/trace/clean", files=_upload(csv_text))
    assert r.status_code == 422
    assert fragment in r.json()["detail"]


def test_bad_polygon_returns_422(sample_csv):
    r = client.post("/trace/odd-check", files=_upload(sample_csv), data={"polygon": "{not json"})
    assert r.status_code == 422
    assert "GeoJSON" in r.json()["detail"]
