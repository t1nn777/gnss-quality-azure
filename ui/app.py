"""Streamlit UI for the GNSS Trace Quality Checker. All processing happens in the API (env API_URL)."""
from __future__ import annotations

import io
import os

import pandas as pd
import pydeck as pdk
import requests
import streamlit as st

API_URL = os.getenv("API_URL", "http://localhost:8000").rstrip("/")
TIMEOUT_S = 60

GREY = [136, 135, 128]
TEAL = [29, 158, 117]
RED = [226, 75, 74]
ODD_FILL = [93, 202, 165, 50]
ODD_LINE = [93, 202, 165, 200]

st.set_page_config(page_title="GNSS Trace Quality Checker", page_icon="🛰️", layout="wide")


@st.cache_data(show_spinner=False)
def fetch_sample(seed: int, noise_m: float, n_jumps: int) -> bytes:
    r = requests.get(f"{API_URL}/trace/sample", params={"seed": seed, "noise_m": noise_m, "n_jumps": n_jumps}, timeout=TIMEOUT_S)
    r.raise_for_status()
    return r.content


@st.cache_data(show_spinner=False)
def clean_trace(csv_bytes: bytes, max_kmh: float, use_default_odd: bool) -> tuple[int, dict]:
    r = requests.post(
        f"{API_URL}/trace/clean",
        files={"file": ("trace.csv", csv_bytes, "text/csv")},
        data={"use_default_odd": str(use_default_odd).lower()},
        params={"max_kmh": max_kmh},
        timeout=TIMEOUT_S,
    )
    try:
        body = r.json()
    except ValueError:
        body = {"detail": r.text[:500]}
    return r.status_code, body


def fmt_duration(seconds: float) -> str:
    m, s = divmod(int(round(seconds)), 60)
    return f"{m}:{s:02d} min"


# --------------------------------------------------------------------------- #
# Sidebar
# --------------------------------------------------------------------------- #
with st.sidebar:
    st.header("Input")
    source = st.radio("Trace source", ["Generate sample", "Upload CSV"], horizontal=True)
    if source == "Generate sample":
        seed = st.slider("Seed", 1, 500, 1)
        noise = st.slider("GNSS noise σ (m)", 1.0, 15.0, 4.0, 0.5)
        jumps = st.slider("Number of multipath jumps", 0, 20, 5)
        if st.button("Generate sample", type="primary", use_container_width=True):
            try:
                st.session_state["csv"] = fetch_sample(seed, noise, jumps)
                st.session_state["csv_name"] = f"simulated_seed{seed}"
            except requests.RequestException as exc:
                st.error(f"Could not reach the API at {API_URL}: {exc}")
    else:
        up = st.file_uploader("CSV with columns timestamp,lat,lon (1 Hz)", type=["csv"])
        if up is not None:
            st.session_state["csv"] = up.getvalue()
            st.session_state["csv_name"] = up.name.rsplit(".", 1)[0]

    st.header("Settings")
    max_kmh = st.number_input("Anomaly speed threshold (km/h)", min_value=10.0, max_value=2000.0, value=200.0, step=10.0)
    use_odd = st.checkbox("Use default ODD polygon around the trace", value=True,
                          help="Demo operational design domain anchored at the first point of the trace.")
    st.caption(f"API: `{API_URL}`")

# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
st.title("GNSS Trace Quality Checker")
st.caption("Data is simulated for demonstration; not real vehicle data.")

csv_bytes = st.session_state.get("csv")
if not csv_bytes:
    st.info("Generate a simulated sample or upload a CSV in the sidebar to start.")
    st.stop()

with st.spinner("Cleaning trace…"):
    try:
        status, body = clean_trace(csv_bytes, max_kmh, use_odd)
    except requests.RequestException as exc:
        st.error(f"Could not reach the API at {API_URL}: {exc}")
        st.stop()

if status != 200:
    detail = body.get("detail", body)
    st.error(f"API returned {status}: {detail}")
    st.stop()

summary = body["summary"]
pts = pd.DataFrame(body["points"])

# ---- Metrics ----
row1, row2 = st.columns(4), st.columns(4)
row1[0].metric("Distance", f"{summary['distance_km']:.2f} km")
row1[1].metric("Duration", fmt_duration(summary["duration_s"]))
row1[2].metric("Avg speed", f"{summary['avg_speed_kmh']:.0f} km/h")
row1[3].metric("Anomalies", f"{summary['anomalies']} ({summary['anomaly_pct']:.1f}%)")
row2[0].metric("In ODD", f"{summary['pct_in_odd']:.0f}%" if "pct_in_odd" in summary else "—")
if "median_err_raw_m" in summary:  # only when the CSV has ground truth (simulated data)
    row2[1].metric("Median error raw", f"{summary['median_err_raw_m']:.1f} m")
    row2[2].metric("Median error smoothed", f"{summary['median_err_smooth_m']:.1f} m",
                   delta=f"{summary['median_err_smooth_m'] - summary['median_err_raw_m']:.1f} m", delta_color="inverse")

# ---- Map ----
layers = []
if summary.get("odd_polygon"):
    rings = summary["odd_polygon"]["coordinates"]
    polys = [rings] if summary["odd_polygon"]["type"] == "Polygon" else rings
    layers.append(pdk.Layer(
        "PolygonLayer", data=[{"polygon": p[0]} for p in polys], get_polygon="polygon",
        get_fill_color=ODD_FILL, get_line_color=ODD_LINE, line_width_min_pixels=1, stroked=True, filled=True,
    ))
layers += [
    pdk.Layer("PathLayer", data=[{"path": pts[["lon", "lat"]].values.tolist()}], get_path="path",
              get_color=GREY, width_min_pixels=1, opacity=0.7),
    pdk.Layer("PathLayer", data=[{"path": pts[["smooth_lon", "smooth_lat"]].values.tolist()}], get_path="path",
              get_color=TEAL, width_min_pixels=3),
    pdk.Layer("ScatterplotLayer", data=pts[pts["is_anomaly"]][["lon", "lat", "timestamp"]], get_position="[lon, lat]",
              get_fill_color=RED, get_radius=6, radius_min_pixels=4, pickable=True),
]
view = pdk.ViewState(latitude=float(pts["lat"].mean()), longitude=float(pts["lon"].mean()), zoom=15)
st.pydeck_chart(pdk.Deck(layers=layers, initial_view_state=view, map_provider="carto", map_style="light",
                         tooltip={"text": "Anomaly at {timestamp}"}))
st.caption("Grey = raw GNSS · Teal = smoothed · Red = anomalies (rejected) · Green fill = ODD")

# ---- Anomalies + ODD events + download ----
left, right = st.columns([3, 2])
with left:
    st.subheader("Anomalies")
    anom = pts[pts["is_anomaly"]][["timestamp", "lat", "lon", "smooth_lat", "smooth_lon"]]
    if anom.empty:
        st.write("No anomalies above the threshold.")
    else:
        st.dataframe(anom, use_container_width=True, hide_index=False)
with right:
    if summary.get("odd_events") is not None:
        st.subheader("ODD enter / exit")
        if summary["odd_events"]:
            st.dataframe(pd.DataFrame(summary["odd_events"])[["type", "timestamp"]], use_container_width=True, hide_index=True)
        else:
            st.write("Starts " + ("inside" if summary.get("odd_start_inside") else "outside") + " and never crosses the border.")

    buf = io.StringIO()
    pts.to_csv(buf, index=False)
    st.download_button("Download cleaned CSV", buf.getvalue(), file_name=f"{st.session_state.get('csv_name', 'trace')}_clean.csv",
                       mime="text/csv", type="primary")
    st.caption(f"Processed {summary['points']} points in {summary['processing_ms']:.0f} ms (API side).")
