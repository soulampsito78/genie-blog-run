CREATE OR REPLACE VIEW `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_vertex_ai_reconciliation` AS
SELECT FORMAT_DATE('%Y-%m', usage_date_kst) AS usage_month, invoice_month, currency,
       SUM(gross_cost) AS vertex_ai_billed_gross,
       SUM(credits) AS vertex_ai_credits,
       SUM(net_cost) AS vertex_ai_billed_net
FROM `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_billing_usage_normalized`
WHERE service_description = 'Vertex AI'
GROUP BY usage_month, invoice_month, currency;
