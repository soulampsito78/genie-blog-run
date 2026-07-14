CREATE OR REPLACE VIEW `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_billing_monthly_by_service` AS
SELECT FORMAT_DATE('%Y-%m', usage_date_kst) AS usage_month, invoice_month,
       service_id, service_description, currency,
       SUM(gross_cost) AS gross_cost, SUM(credits) AS credits, SUM(net_cost) AS net_cost,
       MAX(usage_end_time) AS last_usage_time, MAX(exported_at) AS last_load_time
FROM `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_billing_usage_normalized`
GROUP BY usage_month, invoice_month, service_id, service_description, currency;
