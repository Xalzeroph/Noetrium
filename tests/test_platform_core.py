from pathlib import Path
import tempfile
import unittest

from noetrium_platform.foundation.governance.architecture import ArchitectureAudit, ComponentDescriptor
from noetrium_platform.infrastructure.reliability.failure.api import RecoveryAction, RiskLevel
from noetrium_platform.infrastructure.reliability.forensics.runtime import triage
from noetrium_platform.infrastructure.reliability.failure.api import build_failure
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.capabilities.participant.method.api import MethodIdentity
from noetrium_platform.capabilities.model.serving.api import ModelPhase, ModelRunState
from noetrium_platform.capabilities.model.serving.runtime import RecoveryPlanner
from noetrium_platform.capabilities.model.request.prompt.runtime import PromptRegistry, default_prompt_specs
from noetrium_platform.evidence.observability.telemetry.metric.composition import build_default_registry
from noetrium_platform.evidence.observability.telemetry.metric.runtime import InMemoryMetricRecorder


class PlatformCoreTests(unittest.TestCase):
    def test_failure_is_precisely_locatable(self):
        ctx = ExecutionContext(run_id="r1", trace_id="t1", span_id="s1", task_id="task7", decision_cycle_id="dc9", operation_id="op3")
        try:
            raise RuntimeError("boom")
        except RuntimeError as exc:
            f = build_failure(component_id="method.evolution", failure_domain="METHOD_EVOLUTION", failure_code="SYNTHESIS_FAILED", stage="synthesis", context=ctx, exc=exc, operation_id="op3", recommended_recovery=RecoveryAction.MANUAL_DIAGNOSIS, scientific_validity_risk=RiskLevel.HIGH)
        r = triage(f)
        self.assertIn("task7", r.exact_location)
        self.assertIn("dc9", r.exact_location)
        self.assertEqual(r.scientific_risk, "high")

    def test_metrics_reject_unknown_dimensions(self):
        registry = build_default_registry()
        rec = InMemoryMetricRecorder(registry)
        rec.observe("model.ttft", 0.2, model="m", engine="e", replica="0")
        with self.assertRaises(ValueError):
            rec.observe("model.ttft", 0.2, model="m", engine="e", replica="0", surprise="x")

    def test_prompt_generation_is_atomic(self):
        reg = PromptRegistry()
        specs = default_prompt_specs()
        reg.publish("g1", specs)
        self.assertEqual(reg.generation, "g1")
        self.assertTrue(reg.get("planner.v6").digest)
        self.assertIn("Verified current state", reg.get("planner.v6").text)

    def test_recovery_refuses_quality_or_identity_drift(self):
        base = ImmutableModelIdentity("m", "example/model", "abc", "example-engine", "1.0.0", "bfloat16", None, 262144)
        changed = ImmutableModelIdentity("m", "example/model", "abc", "example-engine", "1.0.0", "float16", None, 262144)
        state = ModelRunState.initial("run", base, "d"*64).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
        with self.assertRaises(ValueError):
            RecoveryPlanner().plan(state,changed,state.deployment_digest)

    def test_recovery_refuses_deployment_stack_drift_even_when_logical_model_identity_matches(self):
        base = ImmutableModelIdentity("m", "example/model", "abc", "example-engine", "1.0.0", "bfloat16", None, 262144)
        state = ModelRunState.initial("run", base, "a"*64).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
        with self.assertRaises(ValueError):
            RecoveryPlanner().plan(state, base, "b"*64)

    def test_recovery_is_exact_and_complete(self):
        base = ImmutableModelIdentity("m", "example/model", "abc", "example-engine", "1.0.0", "bfloat16", None, 262144)
        state = ModelRunState.initial("run", base, "d"*64).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
        plan = RecoveryPlanner().plan(state,base,state.deployment_digest)
        self.assertEqual(plan.frozen_identity, base)
        self.assertEqual(plan.steps[-1].value, "resume_run_exact")

    def test_architecture_firewall_catches_audit_to_method(self):
        d = (ComponentDescriptor("bad", data_domains_read=("j_audit",), data_domains_write=("method_memory",)),)
        v = ArchitectureAudit(d, state_owners={}, side_effect_owners={}, forbidden_dataflows={("j_audit", "method_memory")}).run()
        self.assertEqual(v[0].kind, "forbidden_dataflow")

    def test_method_api_contains_no_minecraft_semantics(self):
        fields = MethodIdentity.__dataclass_fields__
        self.assertNotIn("minecraft", " ".join(fields).lower())


if __name__ == "__main__":
    unittest.main()


def test_retry_until_deadline_retries_only_classified_transient_errors() -> None:
    from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline

    attempts = 0

    def operation() -> str:
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            raise RuntimeError("transient")
        return "ok"

    assert retry_until_deadline(
        operation,
        should_retry=lambda exc: isinstance(exc, RuntimeError),
        timeout_seconds=1.0,
        interval_seconds=0.001,
    ) == "ok"
    assert attempts == 3


def test_retry_until_deadline_fails_closed_for_unclassified_error() -> None:
    import pytest
    from noetrium_platform.foundation.kernel.kernel.retry import retry_until_deadline

    with pytest.raises(ValueError, match="fatal"):
        retry_until_deadline(
            lambda: (_ for _ in ()).throw(ValueError("fatal")),
            should_retry=lambda exc: isinstance(exc, RuntimeError),
            timeout_seconds=1.0,
        )
