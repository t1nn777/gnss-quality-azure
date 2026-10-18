import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.patches import Polygon
from matplotlib.path import Path

rng = np.random.default_rng(7)
LAT0, LON0 = 10.7769, 106.7009
M_PER_DEG_LAT = 110540.0
M_PER_DEG_LON = 111320.0 * np.cos(np.radians(LAT0))

# ---- 1. Ground truth route (meters, local frame), 1 Hz, ~10 m/s ----
waypoints = np.array([[0, 0], [400, 0], [600, 150], [650, 450], [900, 600], [1200, 600]], float)
seg = np.diff(waypoints, axis=0)
seglen = np.hypot(seg[:, 0], seg[:, 1])
cum = np.concatenate([[0], np.cumsum(seglen)])
s = np.arange(0, cum[-1], 10.0)  # 10 m per second
truth = np.column_stack([np.interp(s, cum, waypoints[:, i]) for i in range(2)])
n = len(truth)

# ---- 2. Simulated GNSS: noise + multipath jumps ----
meas = truth + rng.normal(0, 4.0, truth.shape)
jump_idx = [25, 26, 70, 118, 150]
for i in jump_idx:
    ang = rng.uniform(0, 2 * np.pi)
    d = rng.uniform(80, 180)
    meas[i] += d * np.array([np.cos(ang), np.sin(ang)])

# ---- 3. Anomaly detection by implied speed ----
step = np.hypot(*np.diff(meas, axis=0).T)
speed_kmh = np.concatenate([[0], step * 3.6])
anom = np.zeros(n, bool)
anom[1:] = speed_kmh[1:] > 200
# a jump flags both entering and leaving; keep the point that is far from both neighbours
flag = np.zeros(n, bool)
for i in range(1, n - 1):
    if anom[i] and anom[i + 1]:
        flag[i] = True
for i in range(1, n - 1):  # consecutive jumps
    if anom[i] and not flag[i - 1] and not flag[i]:
        flag[i] = True

# ---- 4. Kalman filter (constant velocity) with gating ----
dt = 1.0
F = np.array([[1, 0, dt, 0], [0, 1, 0, dt], [0, 0, 1, 0], [0, 0, 0, 1]])
H = np.array([[1, 0, 0, 0], [0, 1, 0, 0]])
Q = np.diag([0.5, 0.5, 1.0, 1.0])
R = np.eye(2) * 4.0 ** 2
x = np.array([meas[0, 0], meas[0, 1], 0, 0], float)
P = np.diag([25, 25, 100, 100.0])
smooth = np.zeros_like(meas)
for k in range(n):
    x = F @ x
    P = F @ P @ F.T + Q
    z = meas[k]
    y = z - H @ x
    S = H @ P @ H.T + R
    if y @ np.linalg.solve(S, y) < 16 and not flag[k]:  # gating
        K = P @ H.T @ np.linalg.inv(S)
        x = x + K @ y
        P = (np.eye(4) - K @ H) @ P
    smooth[k] = x[:2]

# ---- 5. ODD polygon ----
odd = np.array([[-80, -80], [720, -80], [760, 520], [980, 520], [980, 700], [560, 700], [560, 250], [-80, 120]], float)
in_odd = Path(odd).contains_points(smooth)

err_raw = np.hypot(*(meas - truth).T)
err_sm = np.hypot(*(smooth - truth).T)
dist_km = np.sum(np.hypot(*np.diff(smooth, axis=0).T)) / 1000

def to_ll(xy):
    return LAT0 + xy[:, 1] / M_PER_DEG_LAT, LON0 + xy[:, 0] / M_PER_DEG_LON

lat, lon = to_ll(meas)
t0 = pd.Timestamp("2026-10-15 08:00:00")
df_in = pd.DataFrame({"timestamp": [t0 + pd.Timedelta(seconds=i) for i in range(n)],
                      "lat": lat.round(6), "lon": lon.round(6)})
slat, slon = to_ll(smooth)
df_out = df_in.assign(is_anomaly=flag, smooth_lat=slat.round(6), smooth_lon=slon.round(6), in_odd=in_odd)
df_in.to_csv("input_trace.csv", index=False)
df_out.to_csv("output_trace.csv", index=False)

stats = {
    "Quãng đường": f"{dist_km:.2f} km",
    "Thời lượng": f"{n/60:.1f} phút",
    "Tốc độ TB": f"{dist_km/(n/3600):.0f} km/h",
    "Điểm lỗi": f"{flag.sum()} / {n} ({flag.mean()*100:.1f}%)",
    "Trong ODD": f"{in_odd.mean()*100:.0f}% thời gian",
    "Sai số GPS gốc": f"{np.median(err_raw):.1f} m (trung vị)",
    "Sai số sau lọc": f"{np.median(err_sm):.1f} m (trung vị)",
}
print(stats)

# ---------------- FIGURE ----------------
plt.rcParams.update({"font.family": "DejaVu Sans", "font.size": 10})
fig = plt.figure(figsize=(15, 8.6), dpi=130)
fig.patch.set_facecolor("white")
gs = fig.add_gridspec(2, 2, width_ratios=[1, 1.25], height_ratios=[1, 1.15], hspace=0.28, wspace=0.12)

GREY, BLUE, RED, TEAL = "#888780", "#378ADD", "#E24B4A", "#1D9E75"

def style(ax):
    ax.set_aspect("equal")
    ax.set_xticks([]); ax.set_yticks([])
    for sp in ax.spines.values():
        sp.set_color("#D3D1C7")

# INPUT: CSV preview
ax0 = fig.add_subplot(gs[0, 0]); ax0.axis("off")
ax0.set_title("ĐẦU VÀO  ·  file CSV từ GPS của xe", loc="left", fontweight="bold", fontsize=12)
rows = df_in.iloc[[22, 23, 24, 25, 26, 27, 28]].copy()
rows["timestamp"] = rows["timestamp"].dt.strftime("%H:%M:%S")
tbl = ax0.table(cellText=rows.values, colLabels=rows.columns, loc="center", cellLoc="center")
tbl.auto_set_font_size(False); tbl.set_fontsize(10); tbl.scale(1, 1.55)
for (r, c), cell in tbl.get_celld().items():
    cell.set_edgecolor("#D3D1C7")
    if r == 0:
        cell.set_facecolor("#F1EFE8"); cell.set_text_props(fontweight="bold")
ax0.text(0.0, 0.0, f"Chỉ có thời gian + tọa độ.  {n} dòng (1 điểm/giây).\nNhìn bảng số không thể biết điểm nào sai.",
         transform=ax0.transAxes, fontsize=9.5, color="#5F5E5A", va="top")

# INPUT: raw map
ax1 = fig.add_subplot(gs[1, 0]); style(ax1)
ax1.set_title("ĐẦU VÀO  ·  vẽ thẳng các điểm GPS lên bản đồ", loc="left", fontweight="bold", fontsize=12)
ax1.plot(meas[:, 0], meas[:, 1], "-", color=GREY, lw=1)
ax1.scatter(meas[:, 0], meas[:, 1], s=9, color=BLUE, zorder=3)
ax1.text(0.02, 0.97, "Đường đi méo mó, có các 'gai' vô lý.\nKhông biết xe thật sự đi đâu.",
         transform=ax1.transAxes, va="top", fontsize=9.5, color="#5F5E5A")

# OUTPUT: cleaned map
ax2 = fig.add_subplot(gs[:, 1]); style(ax2)
ax2.set_title("ĐẦU RA  ·  app đã phân tích và làm sạch", loc="left", fontweight="bold", fontsize=12)
ax2.add_patch(Polygon(odd, closed=True, facecolor="#E1F5EE", edgecolor="#5DCAA5", lw=1, ls="--", label="Vùng cho phép (ODD)"))
ax2.plot(truth[:, 0], truth[:, 1], color="#B4B2A9", lw=9, alpha=0.45, solid_capstyle="round", label="Con đường thật (chỉ biết vì là mô phỏng)")
ax2.plot(meas[:, 0], meas[:, 1], "-", color=GREY, lw=0.7, alpha=0.6, label="GPS gốc")
ax2.plot(smooth[:, 0], smooth[:, 1], color=TEAL, lw=2.4, label="Quỹ đạo sau khi lọc")
ax2.scatter(meas[flag, 0], meas[flag, 1], s=60, color=RED, zorder=4, label="Điểm GPS lỗi (bị loại)")
out = ~in_odd
if out.any():
    ax2.scatter(smooth[out, 0], smooth[out, 1], s=14, color="#EF9F27", zorder=4, label="Xe ra ngoài vùng cho phép")
ax2.legend(loc="lower right", fontsize=9, frameon=True, framealpha=0.95)

st = ax2.table(cellText=[[k, v] for k, v in stats.items()], colLabels=["Thống kê", ""],
               cellLoc="left", colLoc="left", bbox=[0.01, 0.60, 0.46, 0.39], colWidths=[0.45, 0.55])
st.auto_set_font_size(False); st.set_fontsize(9.5); st.set_zorder(6)
for (r, c), cell in st.get_celld().items():
    cell.set_edgecolor("#D3D1C7"); cell.set_facecolor("white")
    if r == 0:
        cell.set_facecolor("#F1EFE8"); cell.set_text_props(fontweight="bold")
    elif c == 1:
        cell.set_text_props(fontweight="bold")
fig.savefig("gnss_input_output.png", bbox_inches="tight")

# output CSV preview image
fig2, ax = plt.subplots(figsize=(13, 2.6), dpi=130); ax.axis("off")
r2 = df_out.iloc[[23, 24, 25, 26, 27]].copy()
r2["timestamp"] = r2["timestamp"].dt.strftime("%H:%M:%S")
t2 = ax.table(cellText=r2.values, colLabels=r2.columns, loc="center", cellLoc="center")
t2.auto_set_font_size(False); t2.set_fontsize(10); t2.scale(1, 1.6)
for (r, c), cell in t2.get_celld().items():
    cell.set_edgecolor("#D3D1C7")
    if r == 0:
        cell.set_facecolor("#F1EFE8"); cell.set_text_props(fontweight="bold")
    elif c >= 3:
        cell.set_facecolor("#E1F5EE")
    if r > 0 and r2.iloc[r - 1]["is_anomaly"]:
        cell.set_facecolor("#FCEBEB")
ax.set_title("ĐẦU RA  ·  file CSV đã làm sạch (cột xanh = cột app thêm vào, dòng đỏ = điểm lỗi)", loc="left", fontweight="bold", fontsize=12)
fig2.savefig("gnss_output_csv.png", bbox_inches="tight")
