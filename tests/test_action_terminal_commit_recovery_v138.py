from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from tests_support import context_action_spec

import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntentPhase

from noetrium_platform.infrastructure.reliability.effect.runtime import SQLiteEffectIntentJournal
from noetrium_platform.capabilities.environment.runtime.api import (
    ActionReconciliationDisposition,
    ActionReconciliationResult,
    ActionRequest,
    ActionResult,
    EnvironmentIdentity,
    Observation,
    action_request_digest,
)
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt, OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot, MethodTaskCompletionReceipt, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryRunCheckpointStore


class FailOnceConsumedJournal:
    durability = "crash_durable"

    def __init__(self, path: Path) -> None:
        self.inner = SQLiteEffectIntentJournal(path)
        self.fail_next_consumed = False
        self.failures = 0

    def __getattr__(self, name):
        return getattr(self.inner, name)

    def record_consumed(self, intent_id, *, request_digest, consumption):
        if self.fail_next_consumed:
            self.fail_next_consumed = False
            self.failures += 1
            raise OSError("simulated durable CONSUMED commit failure")
        return self.inner.record_consumed(
            intent_id, request_digest=request_digest, consumption=consumption
        )


class MethodAuthority:
    def __init__(self) -> None:
        self.receipts: dict[str, MethodTaskCompletionReceipt] = {}
        self.task_completed_calls = 0
        self.reconcile_calls = 0


class MethodSession:
    task_completion_idempotency = "durable-authority.v1"

    def __init__(self, session_id: str, authority: MethodAuthority):
        self.session_id = session_id
        self.authority = authority
        self.local_completed: set[str] = set()
        self.ingest_calls = 0

    def ingest(self, evidence, context):
        self.ingest_calls += 1

    def recall(self, request):
        return RecallResult("ctx", f"mg{len(self.local_completed)}")

    def task_completion_key(self, context):
        return f"cycle:{context.run_id}:{context.decision_cycle_id}"

    def task_completed(self, result, context):
        key = self.task_completion_key(context)
        existing = self.authority.receipts.get(key)
        if existing is None:
            self.authority.task_completed_calls += 1
            receipt = MethodTaskCompletionReceipt(key, f"mg{len(self.authority.receipts) + 1}")
            self.authority.receipts[key] = receipt
        else:
            receipt = existing
        self.local_completed.add(key)
        return receipt

    def reconcile_task_completion(self, completion_key, context):
        self.authority.reconcile_calls += 1
        receipt = self.authority.receipts.get(completion_key)
        if receipt is not None:
            # Reconcile only local/session state from method authority; do not execute a new completion.
            self.local_completed.add(completion_key)
        return receipt

    def checkpoint(self):
        payload = json.dumps({"local_completed": sorted(self.local_completed)}).encode()
        return MethodSnapshot(
            "m", "1", "1", "", self.session_id,
            hashlib.sha256(payload).hexdigest(), payload,
        )

    def restore(self, snapshot):
        self.local_completed = set(json.loads(snapshot.opaque_payload)["local_completed"])

    def close(self):
        pass


class Method:
    identity = MethodIdentity("m", "1", "1", "1")

    def __init__(self, authority: MethodAuthority, sessions: list[MethodSession]):
        self.authority = authority
        self.sessions = sessions

    def open_session(self, *, session_id, services):
        session = MethodSession(session_id, self.authority)
        self.sessions.append(session)
        return session


class World:
    def __init__(self) -> None:
        self.actions: set[str] = set()
        self.act_calls = 0
        self.reconcile_calls = 0

    @property
    def generation(self) -> str:
        return f"world-{len(self.actions)}"


def _effect(request: ActionRequest) -> EffectReceipt:
    return EffectReceipt(
        f"fx:{request.action_id}", action_request_digest(request),
        EffectClass.RECONCILABLE, EffectCertainty.EFFECT_CONFIRMED, "world",
    )


class EnvironmentSession:
    action_recovery_durability = "crash_durable"

    def __init__(self, world: World):
        self.world = world

    def observe(self, context):
        return Observation("obs", self.world.generation, {"actions": sorted(self.world.actions)})

    def act(self, request):
        self.world.act_calls += 1
        self.world.actions.add(request.action_id)
        return ActionResult(request.action_id, True, self.observe(request.context), _effect(request), {})

    def prepare_action_recovery(self, request, context):
        payload = json.dumps(
            {"action_id": request.action_id, "action_type": request.action_type, "payload": request.payload},
            sort_keys=True, separators=(",", ":"),
        ).encode()
        return PreparedEffectHandle.build(
            request_id=request.action_id,
            request_digest=action_request_digest(request),
            provider_schema="test-world.v1",
            opaque_payload=payload,
            provider_instance_id="world",
        )

    def execute_prepared_action(self, request, handle):
        assert handle.request_id == request.action_id
        assert handle.request_digest == action_request_digest(request)
        return self.act(request)

    def reconcile_prepared_action(self, handle, context):
        self.world.reconcile_calls += 1
        if handle.request_id not in self.world.actions:
            raise AssertionError("test world lost an already-committed external action")
        effect = EffectReceipt(
            f"fx:{handle.request_id}", handle.request_digest, EffectClass.RECONCILABLE,
            EffectCertainty.EFFECT_CONFIRMED, "world",
        )
        result = ActionResult(
            handle.request_id, True, self.observe(context), effect, {"source": "reconcile"}
        )
        return ActionReconciliationResult(
            handle.request_id, ActionReconciliationDisposition.APPLIED, result, {}
        )


    def reconcile(self, effect, context):
        return effect

    def checkpoint(self):
        return json.dumps({"observed": self.world.generation}).encode()

    def restore(self, payload):
        json.loads(payload)

    def close(self):
        pass


class Environment:
    identity = EnvironmentIdentity("e", "1", "1", "1")

    def __init__(self, world: World):
        self.world = world

    def open_session(self, *, session_id, services):
        return EnvironmentSession(self.world)


def _spec() -> ExperimentSpec:
    return context_action_spec(study_id="study", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)


def _registries(authority: MethodAuthority, world: World, sessions: list[MethodSession]):
    mr = FakeParticipantResolver(); er = FakeParticipantResolver()
    mr.register("method", "m", lambda: Method(authority, sessions))
    er.register("environment", "e", lambda: Environment(world))
    return mr, er


def test_consumed_write_failure_recovers_without_second_task_completion_or_external_act():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        checkpoints = DirectoryRunCheckpointStore(root / "checkpoints")
        journal = FailOnceConsumedJournal(root / "actions.sqlite3")
        authority = MethodAuthority()
        world = World()
        identity = RunIdentity("run", "session", "trace")
        c1 = identity.cycle(decision_cycle_id="dc1", task_id="t1")
        c2 = identity.cycle(decision_cycle_id="dc2", task_id="t2")

        sessions1: list[MethodSession] = []
        mr, er = _registries(authority, world, sessions1)
        run = context_action_runtime(mr, er, checkpoint_store=checkpoints, effect_journal=journal).open_run(
            _spec(), run_identity=identity
        )
        run.execute(task="one", input_kind="move", input_payload={"n": 1}, cycle_identity=c1)
        checkpoint1 = run.latest_checkpoint_id
        assert checkpoint1 is not None
        assert authority.task_completed_calls == 1

        journal.fail_next_consumed = True
        with pytest.raises(OperationFailure) as failed:
            run.execute(task="two", input_kind="move", input_payload={"n": 2}, cycle_identity=c2)
        assert isinstance(failed.value.__cause__, OSError)
        assert "CONSUMED commit failure" in str(failed.value.__cause__)
        assert authority.task_completed_calls == 2
        assert world.act_calls == 2
        assert journal.failures == 1
        run.close()

        # The external effect and Method completion are durable, but the journal is not terminal yet.
        rows = journal.unresolved_for_scope(run_id="run", lifetime_id=None)
        assert len(rows) == 1
        assert rows[0].phase is EffectIntentPhase.RESULT_RECORDED
        assert rows[0].intent.decision_cycle_id == "dc2"

        sessions2: list[MethodSession] = []
        mr2, er2 = _registries(authority, world, sessions2)
        restored = context_action_runtime(
            mr2, er2, checkpoint_store=checkpoints, effect_journal=journal
        ).open_run(
            _spec(), run_identity=identity,
            restore_checkpoint_id=checkpoint1, restore_cycle_identity=c1,
        )
        assert "cycle:run:dc2" not in sessions2[0].local_completed

        recovered = restored.execute(
            task="caller-no-longer-authoritative", input_kind="wrong-on-purpose",
            input_payload={"different": True}, cycle_identity=c2
        )
        assert recovered.context_text == "", "recovery must not fabricate/re-run recall context"
        assert recovered.primary_result.diagnostics["study_recovery"] == "method_completion_already_committed"
        assert recovered.primary_result.diagnostics["action_recovery_source"] == "durable_provider_handle"
        assert authority.task_completed_calls == 2, "Method.task_completed must not run again"
        assert authority.reconcile_calls >= 1
        assert world.act_calls == 2, "Environment.act must not run again"
        assert world.reconcile_calls == 1
        assert sessions2[0].ingest_calls == 0, "recovery must bypass observe→ingest scientific workflow"
        assert "cycle:run:dc2" in sessions2[0].local_completed
        assert journal.unresolved_for_scope(run_id="run", lifetime_id=None) == ()
        restored.close()
