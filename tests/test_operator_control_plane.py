from pathlib import Path
import tempfile
import unittest

from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.infrastructure.reliability.failure.api import RecoveryAction

from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.infrastructure.reliability.forensics.runtime.diagnostic_adapter import ForensicDiagnosticEvidence
from noetrium_platform.infrastructure.reliability.forensics.api import MutationRecord
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api import ModelPhase, ModelRunState
from noetrium_platform.capabilities.model.serving.runtime import RecoveryPlanner, ExactRecoveryCoordinator, RecoveryExecutionError
from noetrium_platform.infrastructure.reliability.diagnostics.runtime import EvidenceVerifier, FailureDiagnosisService
from noetrium_platform.infrastructure.reliability.diagnostics.runtime.status_projection import ForensicStatusProbe
from noetrium_platform.evidence.observability.status.runtime import PlatformStatusService


class _Executor:
    def __init__(self, fail_at=None):
        self.fail_at = fail_at
        self.calls = []
    def run_step(self, step, plan):
        self.calls.append(step)
        if step == self.fail_at:
            raise OSError("injected recovery defect")
        return (f"evidence:{step.value}",)


class OperatorControlPlaneTests(unittest.TestCase):
    def _ctx(self):
        return ExecutionContext(run_id="run_x", trace_id="trace_x", span_id="span_x", task_id="task_x", decision_cycle_id="dc_x", operation_id="op_x")

    def test_why_joins_failure_timeline_and_recent_writer(self):
        with tempfile.TemporaryDirectory() as td:
            store = ForensicStore(Path(td))
            ctx = self._ctx()
            store.append_event(EventEnvelope("event_before", "stage.started", ctx, "agent.planner"))
            store.append_mutation(MutationRecord("mut_1", "method.architecture_head", "agg", 1, 2, "old", "new", "method.adoption", "op_a", ctx))
            failure = build_failure(
                component_id="agent.planner", failure_domain="LLM", failure_code="OUTPUT_CONTRACT",
                stage="decode", context=ctx, exc=ValueError("bad json"), operation_id="op_x",
                recommended_recovery=RecoveryAction.RETRY_OPERATION,
            )
            store.append_failure(failure)
            diag = FailureDiagnosisService(ForensicDiagnosticEvidence(store)).why(failure.failure_id)
            self.assertEqual(diag.failure_id, failure.failure_id)
            self.assertIn("agent.planner/decode", diag.exact_location)
            self.assertTrue(any(r.get("event_id") == "event_before" for r in diag.related_objects))
            self.assertEqual(diag.recent_state_writers[0]["mutation_id"], "mut_1")
            self.assertIn("retry_operation", diag.recovery)

    def test_related_query_uses_context_not_payload_grep(self):
        with tempfile.TemporaryDirectory() as td:
            store=ForensicStore(Path(td)); ctx=self._ctx()
            store.append_event(EventEnvelope("e1", "A", ctx, "c"))
            store.append_event(EventEnvelope("e2", "B", ctx, "c"))
            related=store.index.related_to("e1")
            self.assertEqual({x.to_payload()["event_id"] for x in related},{"e1","e2"})

    def test_evidence_verifier_and_status_are_read_only_views(self):
        with tempfile.TemporaryDirectory() as td:
            store=ForensicStore(Path(td)); store.append_event(EventEnvelope("e1", "X", self._ctx(), "c"))
            report=EvidenceVerifier(ForensicDiagnosticEvidence(store)).verify()
            self.assertTrue(report.valid); self.assertEqual(report.rows["events"],1)
            status=PlatformStatusService((ForensicStatusProbe(ForensicDiagnosticEvidence(store)),)).snapshot()
            self.assertFalse(status.failed); self.assertEqual(status.snapshots[0].subsystem,"forensics")

    def test_exact_recovery_executes_every_step_once_in_order(self):
        ident=ImmutableModelIdentity("m","id","rev","sglang","v","bfloat16",None,262144)
        state=ModelRunState.initial("r", ident, "d"*64).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
        plan=RecoveryPlanner().plan(state,ident,state.deployment_digest)
        ex=_Executor(); report=ExactRecoveryCoordinator(ex).run(plan)
        self.assertEqual(tuple(ex.calls),plan.steps)
        self.assertEqual(report.state.value,"succeeded")
        self.assertEqual(len(report.completed),len(plan.steps))

    def test_exact_recovery_stops_at_first_failure_without_fallback(self):
        ident=ImmutableModelIdentity("m","id","rev","sglang","v","bfloat16",None,262144)
        state=ModelRunState.initial("r", ident, "d"*64).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
        plan=RecoveryPlanner().plan(state,ident,state.deployment_digest); fail=plan.steps[3]
        ex=_Executor(fail)
        with self.assertRaises(RecoveryExecutionError) as cm:
            ExactRecoveryCoordinator(ex).run(plan)
        self.assertEqual(cm.exception.step,fail)
        self.assertEqual(tuple(ex.calls),plan.steps[:4])
        self.assertEqual(cm.exception.completed,plan.steps[:3])


if __name__ == "__main__":
    unittest.main()
