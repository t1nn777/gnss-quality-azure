# Databricks notebook source
# MAGIC %md
# MAGIC # 01 · Bronze
# MAGIC Raw **simulated** CSVs from the volume → Delta table `gnss.bronze_points` (overwrite, idempotent).

# COMMAND ----------

from pyspark.sql import functions as F

dbutils.widgets.text("catalog", "main", "Unity Catalog catalog")
catalog = dbutils.widgets.get("catalog")
spark.sql(f"USE CATALOG `{catalog}`")

RAW_PATH = f"/Volumes/{catalog}/gnss/raw/"
SCHEMA = "trip_id STRING, timestamp TIMESTAMP, lat DOUBLE, lon DOUBLE, true_lat DOUBLE, true_lon DOUBLE"

# COMMAND ----------

bronze = (
    spark.read.csv(RAW_PATH, header=True, schema=SCHEMA, pathGlobFilter="*.csv", recursiveFileLookup=True)
    .withColumn("source_file", F.col("_metadata.file_path"))
    .withColumn("ingest_time", F.current_timestamp())
)

(bronze.write.format("delta").mode("overwrite").option("overwriteSchema", "true").saveAsTable("gnss.bronze_points"))

display(spark.sql("SELECT count(DISTINCT trip_id) AS trips, count(*) AS points FROM gnss.bronze_points"))
