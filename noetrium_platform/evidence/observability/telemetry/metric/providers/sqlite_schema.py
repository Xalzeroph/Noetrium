from __future__ import annotations

import sqlite3


SCHEMA_SQL = """CREATE TABLE IF NOT EXISTS metric_observations(
  sequence INTEGER PRIMARY KEY AUTOINCREMENT,
  metric TEXT NOT NULL,
  value REAL NOT NULL,
  timestamp REAL NOT NULL,
  run_id TEXT NOT NULL,
  study_id TEXT,
  condition_id TEXT,
  task_id TEXT,
  decision_cycle_id TEXT,
  trace_id TEXT NOT NULL,
  span_id TEXT NOT NULL,
  operation_id TEXT,
  component_id TEXT,
  participant_generations_json TEXT NOT NULL,
  dimensions_json TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS idx_metric_name_time ON metric_observations(metric,timestamp);
CREATE INDEX IF NOT EXISTS idx_metric_run_time ON metric_observations(run_id,timestamp);
CREATE INDEX IF NOT EXISTS idx_metric_dc ON metric_observations(decision_cycle_id,timestamp);
CREATE INDEX IF NOT EXISTS idx_metric_component ON metric_observations(component_id,timestamp);
CREATE INDEX IF NOT EXISTS idx_metric_run_sequence ON metric_observations(run_id,sequence);
CREATE INDEX IF NOT EXISTS idx_metric_run_name_sequence ON metric_observations(run_id,metric,sequence);
CREATE INDEX IF NOT EXISTS idx_metric_run_name_value ON metric_observations(run_id,metric,value);
CREATE INDEX IF NOT EXISTS idx_metric_run_dc_sequence ON metric_observations(run_id,decision_cycle_id,sequence);"""


def initialize_telemetry_schema(db: sqlite3.Connection) -> None:
    with db:
        db.executescript(SCHEMA_SQL)
