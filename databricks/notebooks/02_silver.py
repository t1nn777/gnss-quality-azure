# Databricks notebook source
# MAGIC %md
# MAGIC # 02 · Silver
# MAGIC Runs the repo's shared `geo/` package (same code as the API) on every trip with
# MAGIC `groupBy("trip_id").applyInPandas(...)` → `gnss.silver_points`. No algorithm code lives here.

# COMMAND ----------

import os
import sys

from pyspark.sql import types as T

dbutils.widgets.text("catalog", "main", "Unity Catalog catalog")
dbutils.widgets.text("repo_root", "", "Folder that contains geo/ (blank = search upwards)")
catalog = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG `{catalog}`")


def find_repo_root() -> str:
    """The folder holding geo/: the bundle files root, or a Git folder checkout."""
    candidates = [dbutils.widgets.get("repo_root")]
    p = os.getcwd()  # the notebook's folder for workspace files
    while p not in ("/", ""):
        candidates.append(p)
        p = os.path.dirname(p)
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "geo", "geo.py")):
            return c
    raise RuntimeError("geo/ package not found; set the repo_root widget to the folder that contains geo/")


REPO_ROOT = find_repo_root()
sys.path.insert(0, REPO_ROOT)
print("Using geo/ from", REPO_ROOT)

# COMMAND ----------

SILVER_SCHEMA = T.StructType([
    T.StructField("trip_id", T.StringType()),
    T.StructField("timestamp", T.TimestampType()),
    T.StructField("lat", T.DoubleType()),
    T.StructField("lon", T.DoubleType()),
    T.StructField("is_anomaly", T.BooleanType()),
    T.StructField("smooth_lat", T.DoubleType()),
    T.StructField("smooth_lon", T.DoubleType()),
    T.StructField("in_odd", T.BooleanType()),
    T.StructField("true_lat", T.DoubleType()),
    T.StructField("true_lon", T.DoubleType()),
])


def clean_trip(pdf):
    # Runs in the Python workers: make geo importable there too.
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from geo import clean_trace, default_odd_polygon

    pdf = pdf.sort_values("timestamp")
    odd = default_odd_polygon(float(pdf["lat"].iloc[0]), float(pdf["lon"].iloc[0]))
    out = clean_trace(pdf, polygon=odd)
    out["in_odd"] = out["in_odd"].astype(bool)
    return out[[f.name for f in SILVER_SCHEMA]]


# COMMAND ----------

bronze = spark.table("gnss.bronze_points").select("trip_id", "timestamp", "lat", "lon", "true_lat", "true_lon")
silver = bronze.groupBy("trip_id").applyInPandas(clean_trip, schema=SILVER_SCHEMA)

(silver.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("gnss.silver_points"))

display(spark.sql("""
    SELECT count(DISTINCT trip_id) AS trips, count(*) AS points, sum(CAST(is_anomaly AS INT)) AS anomalies
    FROM gnss.silver_points
"""))
