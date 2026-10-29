-- ===========================================================================
-- Insurer Monitor — BigQuery Schema
-- Tables for validated KPIs, quarantined rows, and run logs.
-- ===========================================================================

-- Validated KPI rows (clean data warehouse)
CREATE TABLE IF NOT EXISTS `insurer_monitor.kpi_validated` (
    row_id              STRING       NOT NULL,
    insurer             STRING       NOT NULL,
    period              STRING       NOT NULL,
    section             STRING       NOT NULL,
    metric_name         STRING       NOT NULL,
    metric_value        FLOAT64,
    null_reason         STRING,
    unit                STRING       NOT NULL,
    is_total            BOOL         DEFAULT FALSE,
    source_doc_id       STRING       NOT NULL,
    source_page         INT64        NOT NULL,
    validation_status   STRING       DEFAULT 'validated',
    extracted_at        TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    run_id              STRING       NOT NULL,
)
PARTITION BY DATE(extracted_at)
CLUSTER BY insurer, period;

-- Quarantined rows (pending human review)
CREATE TABLE IF NOT EXISTS `insurer_monitor.kpi_quarantined` (
    row_id              STRING       NOT NULL,
    insurer             STRING       NOT NULL,
    period              STRING       NOT NULL,
    section             STRING       NOT NULL,
    metric_name         STRING       NOT NULL,
    metric_value        FLOAT64,
    null_reason         STRING,
    unit                STRING       NOT NULL,
    is_total            BOOL         DEFAULT FALSE,
    source_doc_id       STRING       NOT NULL,
    source_page         INT64        NOT NULL,
    validation_status   STRING       DEFAULT 'quarantined',
    quarantine_reason   STRING       NOT NULL,
    quarantined_at      TIMESTAMP    DEFAULT CURRENT_TIMESTAMP,
    run_id              STRING       NOT NULL,
);

-- Agent run logs (execution trace)
CREATE TABLE IF NOT EXISTS `insurer_monitor.run_logs` (
    run_id              STRING       NOT NULL,
    doc_id              STRING       NOT NULL,
    step_number         INT64        NOT NULL,
    tool_name           STRING       NOT NULL,
    tool_args           JSON,
    result_summary      STRING,
    tokens_used         INT64        DEFAULT 0,
    duration_seconds    FLOAT64      DEFAULT 0.0,
    step_timestamp      TIMESTAMP    NOT NULL,
);

-- Run summary (one row per agent run)
CREATE TABLE IF NOT EXISTS `insurer_monitor.run_summary` (
    run_id              STRING       NOT NULL,
    doc_id              STRING       NOT NULL,
    insurer             STRING,
    period              STRING,
    started_at          TIMESTAMP    NOT NULL,
    finished_at         TIMESTAMP,
    pages_processed     INT64,
    rows_validated      INT64        DEFAULT 0,
    rows_quarantined    INT64        DEFAULT 0,
    total_tokens        INT64        DEFAULT 0,
    total_cost_usd      FLOAT64      DEFAULT 0.0,
    outcome             STRING,      -- 'success', 'partial', 'failed'
);
