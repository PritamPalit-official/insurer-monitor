-- ===========================================================================
-- Insurer Monitor — BigQuery Views
-- Analytical views for the Power BI dashboard.
-- ===========================================================================

-- Latest validated KPIs per insurer (deduplicated)
CREATE OR REPLACE VIEW `insurer_monitor.v_latest_kpis` AS
SELECT
    insurer,
    period,
    section,
    metric_name,
    metric_value,
    unit,
    is_total,
    extracted_at,
FROM (
    SELECT
        *,
        ROW_NUMBER() OVER (
            PARTITION BY insurer, metric_name, period
            ORDER BY extracted_at DESC
        ) AS rn
    FROM `insurer_monitor.kpi_validated`
)
WHERE rn = 1;


-- Period-over-period changes
CREATE OR REPLACE VIEW `insurer_monitor.v_period_changes` AS
WITH ranked AS (
    SELECT
        insurer,
        metric_name,
        period,
        metric_value,
        unit,
        ROW_NUMBER() OVER (
            PARTITION BY insurer, metric_name
            ORDER BY period DESC
        ) AS period_rank
    FROM `insurer_monitor.v_latest_kpis`
    WHERE metric_value IS NOT NULL
      AND is_total = FALSE
)
SELECT
    curr.insurer,
    curr.metric_name,
    curr.period              AS current_period,
    prev.period              AS prior_period,
    curr.metric_value        AS current_value,
    prev.metric_value        AS prior_value,
    curr.metric_value - prev.metric_value AS absolute_change,
    SAFE_DIVIDE(
        curr.metric_value - prev.metric_value,
        prev.metric_value
    ) * 100                   AS percent_change,
    curr.unit,
FROM ranked curr
JOIN ranked prev
  ON curr.insurer    = prev.insurer
 AND curr.metric_name = prev.metric_name
 AND curr.period_rank = 1
 AND prev.period_rank = 2;


-- Quarantine summary (for human review queue)
CREATE OR REPLACE VIEW `insurer_monitor.v_quarantine_queue` AS
SELECT
    insurer,
    period,
    section,
    metric_name,
    quarantine_reason,
    quarantined_at,
    source_doc_id,
    source_page,
FROM `insurer_monitor.kpi_quarantined`
ORDER BY quarantined_at DESC;


-- Run performance summary
CREATE OR REPLACE VIEW `insurer_monitor.v_run_performance` AS
SELECT
    run_id,
    doc_id,
    insurer,
    period,
    outcome,
    pages_processed,
    rows_validated,
    rows_quarantined,
    total_tokens,
    total_cost_usd,
    TIMESTAMP_DIFF(finished_at, started_at, SECOND) AS duration_seconds,
FROM `insurer_monitor.run_summary`
ORDER BY started_at DESC;
