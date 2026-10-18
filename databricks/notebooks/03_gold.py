# Databricks notebook source
# MAGIC %md
# MAGIC # 03 · Gold
# MAGIC One row per **simulated** trip → `gnss.gold_trip_quality`.
# MAGIC `usable` = anomaly_pct < 5 and pct_in_odd > 80. Stats come from `geo.trip_stats` (shared code).

# COMMAND ----------

import os
import sys

import pandas as pd
from pyspark.sql import functions as F
from pyspark.sql import types as T

dbutils.widgets.text("catalog", "main", "Unity Catalog catalog")
dbutils.widgets.text("repo_root", "", "Folder that contains geo/ (blank = search upwards)")
catalog = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG `{catalog}`")


def find_repo_root() -> str:
    candidates = [dbutils.widgets.get("repo_root")]
    p = os.getcwd()
    while p not in ("/", ""):
        candidates.append(p)
        p = os.path.dirname(p)
    for c in candidates:
        if c and os.path.isfile(os.path.join(c, "geo", "geo.py")):
            return c
    raise RuntimeError("geo/ package not found; set the repo_root widget to the folder that contains geo/")


REPO_ROOT = find_repo_root()

# COMMAND ----------

GOLD_SCHEMA = T.StructType([
    T.StructField("trip_id", T.StringType()),
    T.StructField("points", T.LongType()),
    T.StructField("start_time", T.TimestampType()),
    T.StructField("distance_km", T.DoubleType()),
    T.StructField("anomaly_pct", T.DoubleType()),
    T.StructField("pct_in_odd", T.DoubleType()),
    T.StructField("median_err_raw_m", T.DoubleType()),
    T.StructField("median_err_smooth_m", T.DoubleType()),
])


def trip_quality(pdf):
    if REPO_ROOT not in sys.path:
        sys.path.insert(0, REPO_ROOT)
    from geo import trip_stats

    s = trip_stats(pdf.sort_values("timestamp"))
    return pd.DataFrame([{
        "trip_id": pdf["trip_id"].iloc[0],
        "points": s["points"],
        "start_time": pd.Timestamp(s["start_time"]),
        "distance_km": s["distance_km"],
        "anomaly_pct": s["anomaly_pct"],
        "pct_in_odd": s["pct_in_odd"],
        "median_err_raw_m": s["median_err_raw_m"],
        "median_err_smooth_m": s["median_err_smooth_m"],
    }])


# COMMAND ----------

gold = (
    spark.table("gnss.silver_points")
    .groupBy("trip_id")
    .applyInPandas(trip_quality, schema=GOLD_SCHEMA)
    .withColumn("usable", (F.col("anomaly_pct") < 5) & (F.col("pct_in_odd") > 80))
)

(gold.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("gnss.gold_trip_quality"))

display(spark.sql("""
    SELECT count(*) AS trips,
           sum(CAST(usable AS INT)) AS usable_trips,
           round(percentile(median_err_raw_m, 0.5), 2) AS median_err_raw_m,
           round(percentile(median_err_smooth_m, 0.5), 2) AS median_err_smooth_m
    FROM gnss.gold_trip_quality
"""))
