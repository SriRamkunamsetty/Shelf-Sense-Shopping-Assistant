-- Fleet-scale alternative to the in-process forecaster: BigQuery ML ARIMA_PLUS.
-- Replace PROJECT with your project id. Load data first: python scripts/load_bigquery.py --project PROJECT
-- Training only on in-stock days leaves gaps on stock-out days; ARIMA_PLUS interpolates missing points,
-- which is the BigQuery equivalent of the stock-out correction in services/forecast.py.
CREATE OR REPLACE MODEL `PROJECT.shelfsense.sales_forecast`
OPTIONS (
  model_type = 'ARIMA_PLUS',
  time_series_timestamp_col = 'day',
  time_series_data_col = 'units',
  time_series_id_col = 'sku',
  data_frequency = 'DAILY',
  holiday_region = 'IN',
  auto_arima = TRUE
) AS
SELECT day, sku, units
FROM `PROJECT.shelfsense.sales_daily`
WHERE in_stock;

-- 14-day forecast with an 80% interval
SELECT sku, forecast_timestamp AS day, forecast_value AS mean,
       prediction_interval_lower_bound AS lo, prediction_interval_upper_bound AS hi
FROM ML.FORECAST(MODEL `PROJECT.shelfsense.sales_forecast`, STRUCT(14 AS horizon, 0.8 AS confidence_level))
ORDER BY sku, day;
