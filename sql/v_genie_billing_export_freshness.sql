CREATE OR REPLACE VIEW `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_billing_export_freshness` AS
SELECT MAX(usage_end_time) AS billing_export_last_usage_time,
       MAX(exported_at) AS billing_export_last_load_time,
       COUNT(*) AS billing_row_count
FROM `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_billing_usage_normalized`;
