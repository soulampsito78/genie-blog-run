CREATE OR REPLACE VIEW `{{PROJECT_ID}}.{{DATASET_ID}}.v_genie_billing_usage_normalized` AS
SELECT
  billing_account_id,
  project.id AS project_id,
  project.name AS project_name,
  service.id AS service_id,
  service.description AS service_description,
  sku.id AS sku_id,
  sku.description AS sku_description,
  resource.name AS resource_name,
  location.location AS location,
  usage_start_time,
  usage_end_time,
  DATE(usage_start_time, 'Asia/Seoul') AS usage_date_kst,
  invoice.month AS invoice_month,
  usage.amount AS usage_amount,
  usage.unit AS usage_unit,
  CAST(cost AS NUMERIC) AS cost,
  IFNULL((SELECT SUM(CAST(c.amount AS NUMERIC)) FROM UNNEST(credits) c), 0) AS credits,
  CAST(cost AS NUMERIC) AS gross_cost,
  CAST(cost AS NUMERIC)
    + IFNULL((SELECT SUM(CAST(c.amount AS NUMERIC)) FROM UNNEST(credits) c), 0) AS net_cost,
  currency,
  CAST(currency_conversion_rate AS NUMERIC) AS currency_conversion_rate,
  TO_JSON_STRING(labels) AS labels,
  TO_JSON_STRING(system_labels) AS system_labels,
  '{{SOURCE_TABLE}}' AS export_source_table,
  _PARTITIONTIME AS exported_at
FROM `{{SOURCE_TABLE}}`
WHERE project.id = 'gen-lang-client-0667098249';
