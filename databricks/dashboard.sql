-- Dashboard queries for Databricks SQL / AI-BI dashboards (simulated data).
-- Run with the catalog that holds the gnss schema selected (USE CATALOG <catalog>;).

-- 1. Usable vs not usable trips (counter / pie)
SELECT CASE WHEN usable THEN 'usable' ELSE 'not usable' END AS status,
       count(*) AS trips
FROM gnss.gold_trip_quality
GROUP BY 1
ORDER BY 1;

-- 2. Anomaly % per trip (bar), with the 5 % usability line as a reference
SELECT trip_id, anomaly_pct, pct_in_odd, usable
FROM gnss.gold_trip_quality
ORDER BY trip_id;

-- 3. Worst 10 trips (table)
SELECT trip_id, points, distance_km, anomaly_pct, pct_in_odd,
       median_err_raw_m, median_err_smooth_m, usable
FROM gnss.gold_trip_quality
ORDER BY anomaly_pct DESC, pct_in_odd ASC
LIMIT 10;

-- 4. Anomaly points on a map (map / point map visual: latitude = lat, longitude = lon)
SELECT trip_id, timestamp, lat, lon
FROM gnss.silver_points
WHERE is_anomaly;

-- 5. Headline numbers for the README Results section
SELECT count(*)                                         AS trips,
       sum(CAST(usable AS INT))                         AS usable_trips,
       round(avg(anomaly_pct), 2)                       AS avg_anomaly_pct,
       round(percentile(median_err_raw_m, 0.5), 2)      AS median_err_raw_m,
       round(percentile(median_err_smooth_m, 0.5), 2)   AS median_err_smooth_m
FROM gnss.gold_trip_quality;
