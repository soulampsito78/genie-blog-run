CREATE OR REPLACE VIEW `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_non_ai_infra_monthly` AS
SELECT FORMAT_DATE('%Y-%m', usage_date_kst) AS usage_month, invoice_month,
       service_id, service_description, sku_id, sku_description, currency,
       SUM(gross_cost) AS gross_cost, SUM(credits) AS credits, SUM(net_cost) AS net_cost
FROM `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_billing_usage_normalized`
WHERE service_description != 'Vertex AI'
GROUP BY usage_month, invoice_month, service_id, service_description, sku_id, sku_description, currency;
