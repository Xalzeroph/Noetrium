from __future__ import annotations

from tests_support import model_role_for_test

from tests_support import FakeParticipantResolver, participant
from tests_support import agent_turn_runtime

import hashlib
import multiprocessing as mp
import os
from pathlib import Path
import tempfile

from noetrium_platform.capabilities.participant.agent.api import AgentIdentity, AgentSnapshot, AgentTurnResult
from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityEffectReconciliationResult,
    CapabilityProviderIdentity,
    CapabilityRequest,
    CapabilityResult,
    capability_effect_request_id,
    capability_request_digest,
)
from noetrium_platform.infrastructure.reliability.effect.api import EffectReconciliationDisposition, PreparedEffectHandle
from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentPhase
from noetrium_platform.infrastructure.reliability.effect.runtime import SQLiteEffectIntentJournal
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, canonical_digest
from noetrium_platform.research.execution.workflow.implementations.agent_turn import AGENT_TURN_TRIAL_CONFIGURATION_DIGEST
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentParticipantSpec, ExperimentSpec


class _CrashBeforeConsumeJournal:
    """Fault injector: RESULT_RECORDED is durable, consumer terminalization never returns."""

    durability = "crash_durable"

    def __init__(self, inner: SQLiteEffectIntentJournal) -> None:
        self._inner = inner

    def prepare(self, intent): return self._inner.prepare(intent)
    def load(self, intent_id): return self._inner.load(intent_id)
    def record_result(self, intent_id, *, request_digest, effect):
        return self._inner.record_result(intent_id, request_digest=request_digest, effect=effect)
    def record_reconciled(self, intent_id, *, request_digest, effect):
        return self._inner.record_reconciled(intent_id, request_digest=request_digest, effect=effect)
    def record_not_applied(self, intent_id, *, request_digest, effect):
        return self._inner.record_not_applied(intent_id, request_digest=request_digest, effect=effect)
    def unresolved_for_scope(self, *, run_id, lifetime_id, exclude_intent_id=None):
        return self._inner.unresolved_for_scope(
            run_id=run_id, lifetime_id=lifetime_id, exclude_intent_id=exclude_intent_id
        )

    def record_consumed(self, intent_id, *, request_digest, consumption):
        # Abrupt process death models controller/runtime loss after the external effect and
        # RESULT_RECORDED are durable, but before consumer completion is terminalized.
        os._exit(73)


class _ExternalWriteSession:
    effect_recovery_durability = "crash_durable"

    def __init__(self, external_effect_path: Path) -> None:
        self._external_effect_path = external_effect_path

    @property
    def capabilities(self):
        return (
            CapabilityDescriptor(
                "tool.write",
                "1",
                "tool.write.req.v1",
                "tool.write.res.v1",
                EffectClass.NON_IDEMPOTENT,
            ),
        )

    def prepare_capability_effect(self, request):
        return PreparedEffectHandle.build(
            request_id=capability_effect_request_id(request),
            request_digest=capability_request_digest(request),
            provider_schema="external-write.recovery.v1",
            opaque_payload=b"provider-transaction-42",
            provider_instance_id="external-write-instance",
        )

    @staticmethod
    def _result(request_digest: str) -> CapabilityResult:
        return CapabilityResult(
            "tool.write",
            {"ok": True},
            effect=EffectReceipt(
                "effect:external-write-42",
                request_digest,
                EffectClass.NON_IDEMPOTENT,
                EffectCertainty.EFFECT_CONFIRMED,
                "external-write-instance",
            ),
        )

    def execute_prepared_capability(self, request, handle):
        # This file is the simulated external system. Each physical execution appends one
        # durable line, allowing the parent process to prove exactly-once behavior.
        with self._external_effect_path.open("ab") as fh:
            fh.write(b"EXECUTED\n")
            fh.flush()
            os.fsync(fh.fileno())
        return self._result(handle.request_digest)

    def reconcile_prepared_capability(self, handle, context):
        del context
        if not self._external_effect_path.exists():
            raise AssertionError("provider cannot prove the prepared external effect")
        return CapabilityEffectReconciliationResult(
            "tool.write",
            EffectReconciliationDisposition.APPLIED,
            self._result(handle.request_digest),
        )

    def invoke(self, request):
        raise AssertionError("raw invoke must never execute a non-idempotent capability")

    def checkpoint(self): return b"provider"
    def restore(self, payload): del payload
    def close(self): pass


class _ExternalWriteProvider:
    identity = CapabilityProviderIdentity("external-write", "1", "1", "1", "f" * 64)

    def __init__(self, external_effect_path: Path) -> None:
        self._external_effect_path = external_effect_path

    def open_session(self, *, session_id: str, services: object):
        del session_id, services
        return _ExternalWriteSession(self._external_effect_path)


class _RestartAgentSession:
    def __init__(self, session_id: str) -> None:
        self.session_id = session_id
        self.generation = 0

    def run_turn(self, request, capabilities):
        result = capabilities.invoke(
            CapabilityRequest(
                "tool.write",
                {"task": request.task, "payload": request.input_payload},
                request.context,
                "stable-write-slot",
            )
        )
        self.generation += 1
        return AgentTurnResult(result.payload, f"agent-g{self.generation}")

    def checkpoint(self):
        payload = str(self.generation).encode()
        return AgentSnapshot(
            "restart-agent",
            "1",
            "1",
            self.session_id,
            hashlib.sha256(payload).hexdigest(),
            payload,
        )

    def restore(self, snapshot): self.generation = int(snapshot.opaque_payload.decode())
    def diagnostics(self): return {"generation": self.generation}
    def close(self): pass


class _RestartAgent:
    identity = AgentIdentity("restart-agent", "1", "1", "1", "a" * 64)

    def open_session(self, *, session_id: str, services: object):
        del services
        return _RestartAgentSession(session_id)


def _spec() -> ExperimentSpec:
    return ExperimentSpec(
        experiment_id="agent-effect-sqlite-restart",
        study_id="default-study",
        project_id="default-project",
        participants=(
            participant("capability_provider", "external-write", "external-write", implementation_version="1", abi_version="1", schema_version="1", artifact_digest="f" * 64),
            participant("agent", "agent", "restart-agent", implementation_version="1", abi_version="1", schema_version="1", artifact_digest="a" * 64, depends_on_roles=("external-write",)),
        ),
        model_roles=(model_role_for_test(),), workload_digest="b" * 64,
        seed_digest="c" * 64, repetitions=1, trial_protocol_id="agent_turn.v2",
        trial_protocol_configuration_digest=AGENT_TURN_TRIAL_CONFIGURATION_DIGEST,
    )


def _runtime(db_path: Path, external_effect_path: Path, *, crash_before_consume: bool) -> ExperimentRuntime:
    agents = FakeParticipantResolver()
    agents.register("agent", "restart-agent", _RestartAgent)
    providers = FakeParticipantResolver()
    providers.register("capability_provider", "external-write", lambda: _ExternalWriteProvider(external_effect_path))
    base_journal = SQLiteEffectIntentJournal(db_path)
    journal = _CrashBeforeConsumeJournal(base_journal) if crash_before_consume else base_journal
    return agent_turn_runtime(
        agents,
        capability_plugins=providers,
        effect_journal=journal,
    )


def _first_process(db_path: str, external_effect_path: str) -> None:
    runtime = _runtime(Path(db_path), Path(external_effect_path), crash_before_consume=True)
    runtime.execute_cycle(
        _spec(),
        task="write",
        input_payload={"value": 1},
        cycle_identity=DecisionCycleIdentity("run", "dc", "session", "task", "trace"),
    )
    raise AssertionError("fault injector should terminate the process before execute_cycle returns")


def _recovery_process(db_path: str, external_effect_path: str, result_path: str) -> None:
    runtime = _runtime(Path(db_path), Path(external_effect_path), crash_before_consume=False)
    result = runtime.execute_cycle(
        _spec(),
        task="write",
        input_payload={"value": 1},
        cycle_identity=DecisionCycleIdentity("run", "dc", "session", "task", "trace"),
    )
    Path(result_path).write_text(str(result.primary_result.output), encoding="utf-8")


def test_agent_only_non_idempotent_capability_recovers_across_real_process_restart():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        db_path = root / "effects.sqlite3"
        external_effect = root / "external-system.log"
        recovery_result = root / "recovery-result.txt"
        ctx = mp.get_context("spawn")

        first = ctx.Process(target=_first_process, args=(str(db_path), str(external_effect)))
        first.start(); first.join(20)
        assert first.exitcode == 73
        assert external_effect.read_bytes().splitlines() == [b"EXECUTED"]

        # The crash happened after RESULT_RECORDED but before CONSUMED.
        journal = SQLiteEffectIntentJournal(db_path)
        pending = journal.unresolved_for_scope(run_id="run", lifetime_id=None)
        assert len(pending) == 1
        assert pending[0].phase is EffectIntentPhase.RESULT_RECORDED
        assert pending[0].intent.recovery_handle is not None
        assert pending[0].intent.recovery_handle.opaque_payload == b"provider-transaction-42"

        recovered = ctx.Process(
            target=_recovery_process,
            args=(str(db_path), str(external_effect), str(recovery_result)),
        )
        recovered.start(); recovered.join(20)
        assert recovered.exitcode == 0
        assert recovery_result.read_text(encoding="utf-8") == "{'ok': True}"

        # A brand-new OS process consumed the durable intent by provider reconciliation.
        # The physical external write never happened twice.
        assert external_effect.read_bytes().splitlines() == [b"EXECUTED"]
        final = SQLiteEffectIntentJournal(db_path).unresolved_for_scope(run_id="run", lifetime_id=None)
        assert final == ()
