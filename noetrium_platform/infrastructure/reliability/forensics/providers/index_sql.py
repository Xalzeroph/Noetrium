OBJECT_UPSERT_SQL = "INSERT OR REPLACE INTO object_index VALUES(?,?,?,?,?,?,?,?,?,?)"
STATE_UPSERT_SQL = "INSERT OR REPLACE INTO state_writers VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)"
FRESHNESS_UPSERT_SQL = "INSERT OR REPLACE INTO ledger_freshness(ledger,rows,tail_hash) VALUES(?,?,?)"

OPERATION_INVOCATION_UPSERT_SQL = """
INSERT INTO operation_invocations VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
ON CONFLICT(invocation_id) DO UPDATE SET
    operation_id=excluded.operation_id,
    operation_type=excluded.operation_type,
    run_id=COALESCE(excluded.run_id, operation_invocations.run_id),
    task_id=COALESCE(excluded.task_id, operation_invocations.task_id),
    decision_cycle_id=COALESCE(excluded.decision_cycle_id, operation_invocations.decision_cycle_id),
    trace_id=COALESCE(excluded.trace_id, operation_invocations.trace_id),
    span_id=COALESCE(excluded.span_id, operation_invocations.span_id),
    caller_component_id=COALESCE(excluded.caller_component_id, operation_invocations.caller_component_id),
    target_component_id=COALESCE(excluded.target_component_id, operation_invocations.target_component_id),
    started_event_id=COALESCE(excluded.started_event_id, operation_invocations.started_event_id),
    started_at=COALESCE(excluded.started_at, operation_invocations.started_at),
    terminal_event_id=COALESCE(excluded.terminal_event_id, operation_invocations.terminal_event_id),
    terminal_event_type=COALESCE(excluded.terminal_event_type, operation_invocations.terminal_event_type),
    terminal_at=COALESCE(excluded.terminal_at, operation_invocations.terminal_at),
    status=COALESCE(excluded.status, operation_invocations.status),
    failure_id=COALESCE(excluded.failure_id, operation_invocations.failure_id),
    latest_payload_json=CASE
        WHEN excluded.terminal_event_id IS NOT NULL THEN excluded.latest_payload_json
        WHEN operation_invocations.terminal_event_id IS NULL THEN excluded.latest_payload_json
        ELSE operation_invocations.latest_payload_json
    END
"""
