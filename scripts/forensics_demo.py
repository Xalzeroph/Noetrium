from pathlib import Path
import tempfile

from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.composition import ForensicStore
from noetrium_platform.infrastructure.reliability.forensics.api import MutationRecord
from noetrium_platform.infrastructure.reliability.failure.api import RecoveryAction, build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext


def main() -> None:
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        store = ForensicStore(root)
        ctx = ExecutionContext(run_id="r1", trace_id="tr1", span_id="sp1", task_id="task1", decision_cycle_id="dc1", operation_id="op1")
        store.append_event(EventEnvelope("event1", "OPERATION_STARTED", 1, ctx, "agent.planner"))
        store.append_mutation(MutationRecord("mut1", "method.architecture_head", "method", 3, 4, "aaa", "bbb", "method.adoption", "op1", ctx))
        try:
            raise TimeoutError("model request exceeded deadline")
        except TimeoutError as exc:
            f = build_failure(component_id="platform.llm", failure_domain="MODEL_SERVING", failure_code="REQUEST_TIMEOUT", stage="http", context=ctx, exc=exc, operation_id="op1", recommended_recovery=RecoveryAction.RETRY_OPERATION)
            store.append_failure(f)
        print(store.verify_all())
        print("locate", store.index.locate("event1"))
        print("last_writer", store.index.last_writer("r1", "method.architecture_head"))


if __name__ == "__main__":
    main()
