# Databricks notebook source
# MAGIC %md
# MAGIC # 00 · Setup
# MAGIC Creates the `gnss` schema and the `raw` volume that receives the **simulated** fleet CSVs.
# MAGIC Idempotent.

# COMMAND ----------

dbutils.widgets.text("catalog", "main", "Unity Catalog catalog")
catalog = dbutils.widgets.get("catalog")

spark.sql(f"USE CATALOG `{catalog}`")
spark.sql("CREATE SCHEMA IF NOT EXISTS gnss COMMENT 'GNSS trace quality (simulated data)'")
spark.sql("CREATE VOLUME IF NOT EXISTS gnss.raw COMMENT 'Simulated GNSS trip CSVs'")

print(f"Ready. Upload CSVs to /Volumes/{catalog}/gnss/raw/")
