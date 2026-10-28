-- Looker Studio / BI views over the demand_events table that the app streams to when BIGQUERY_DATASET is set.
CREATE OR REPLACE VIEW `PROJECT.shelfsense.unmet_demand_weekly` AS
SELECT
  DATE_TRUNC(DATE(ts), WEEK(MONDAY)) AS week,
  need_key,
  APPROX_TOP_COUNT(need_text, 1)[OFFSET(0)].value AS label,
  COUNTIF(outcome = 'not_carried')  AS not_carried,
  COUNTIF(outcome = 'partial')      AS substitute_only,
  COUNTIF(outcome = 'out_of_stock') AS out_of_stock,
  COUNTIF(outcome = 'over_budget')  AS over_budget,
  COUNT(DISTINCT customer_id)       AS shoppers,
  SUM(est_value)                    AS est_value_inr
FROM `PROJECT.shelfsense.demand_events`
WHERE outcome != 'in_stock'
GROUP BY week, need_key;

CREATE OR REPLACE VIEW `PROJECT.shelfsense.fulfilment_rate_daily` AS
SELECT DATE(ts) AS day, language,
       COUNT(*) AS requests,
       SAFE_DIVIDE(COUNTIF(outcome = 'in_stock'), COUNT(*)) AS fulfilment_rate
FROM `PROJECT.shelfsense.demand_events`
GROUP BY day, language;
