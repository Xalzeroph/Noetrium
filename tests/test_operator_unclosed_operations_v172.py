from __future__ import annotations

from pathlib import Path
import tempfile

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.product.operator.runtime.parser import build_parser
from noetrium_platform.product.operator.query.runtime.route_diagnostics import route_diagnostics


def test_operator_exposes_unclosed_operation_query_without_mutating_forensics() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ctx = ExecutionContext(run_id="run-op", trace_id="trace", span_id="span")
        with ForensicStore(root) as store:
            store.append_event(EventEnvelope(
                "started-1",
                "OPERATION_STARTED",
                ctx,
                "target",
                payload={
                    "operation_id": "op",
                    "operation_invocation_id": "inv",
                    "operation_type": "capability.invoke",
                    "caller_component_id": "caller",
                    "target_component_id": "target",
                },
            ))
        args = build_parser().parse_args([
            "unclosed-operations",
            str(root),
            "--run-id",
            "run-op",
        ])
        rows = route_diagnostics(args)
        assert len(rows) == 1
        assert rows[0]["invocation_id"] == "inv"
        assert rows[0]["operation_type"] == "capability.invoke"
