from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import participant_component

from tests_support import environment_effect_intent

from noetrium_platform.infrastructure.reliability.effect.api import PreparedEffectHandle

from tests_support import context_action_spec

import hashlib
import json
from dataclasses import replace
from pathlib import Path
import tempfile

import pytest

from noetrium_platform.infrastructure.reliability.effect.api import EffectIntent, EffectIntentPhase

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
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot, MethodTaskCompletionReceipt, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryRunCheckpointStore


class MethodSession:
    task_completion_idempotency = "checkpoint-test.v1"

    def __init__(self, session_id: str):
        self.session_id = session_id
        self.completed = 0

    def ingest(self, evidence, context):
        pass

    def recall(self, request):
        return RecallResult(f"completed={self.completed}", f"mg{self.completed}")

    def task_completion_key(self, context):
        return f"cycle:{context.run_id}:{context.decision_cycle_id}"

    def task_completed(self, result, context):
        key = self.task_completion_key(context)
        # Idempotency is represented by restored method state + stable completion identity.
        self.completed += 1
        return MethodTaskCompletionReceipt(key, f"mg{self.completed}")

    def checkpoint(self):
        payload = json.dumps({"completed": self.completed}, sort_keys=True).encode()
        return MethodSnapshot(
            "m", "1", "1", "", self.session_id,
            hashlib.sha256(payload).hexdigest(), payload,
        )

    def restore(self, snapshot):
        self.completed = int(json.loads(snapshot.opaque_payload)["completed"])

    def close(self):
        pass


class Method:
    identity = MethodIdentity("m", "1", "1", "1")
    def __init__(self, sessions): self.sessions = sessions
    def open_session(self, *, session_id, services):
        session = MethodSession(session_id)
        self.sessions.append(session)
        return session


class ExternalWorld:
    def __init__(self):
        self.applied_action_ids: set[str] = set()
        self.raw_act_calls = 0
        self.reconcile_calls = 0
        self.crash_after_effect_for: set[str] = set()

    @property
    def generation(self) -> str:
        return f"world-{len(self.applied_action_ids)}"


def receipt(request: ActionRequest) -> EffectReceipt:
    return EffectReceipt(
        f"fx:{request.action_id}", action_request_digest(request),
        EffectClass.RECONCILABLE, EffectCertainty.EFFECT_CONFIRMED, "world",
    )


class EnvironmentSession:
    action_recovery_durability = "crash_durable"

    def __init__(self, world: ExternalWorld):
        self.world = world

    def observe(self, context):
        return Observation(
            f"obs:{len(self.world.applied_action_ids)}",
            self.world.generation,
            {"applied": sorted(self.world.applied_action_ids)},
        )

    def act(self, request):
        self.world.raw_act_calls += 1
        self.world.applied_action_ids.add(request.action_id)
        if request.action_id in self.world.crash_after_effect_for:
            self.world.crash_after_effect_for.remove(request.action_id)
            raise OSError("transport lost after external world committed action")
        return ActionResult(request.action_id, True, self.observe(request.context), receipt(request), {})

    def prepare_action_recovery(self, request, context):
        return PreparedEffectHandle.build(
            request_id=request.action_id, request_digest=action_request_digest(request),
            provider_schema="external-world.v1", opaque_payload=request.action_id.encode(),
            provider_instance_id="world",
        )

    def execute_prepared_action(self, request, handle):
        assert handle.request_id == request.action_id
        assert handle.request_digest == action_request_digest(request)
        return self.act(request)

    def reconcile_prepared_action(self, handle, context):
        self.world.reconcile_calls += 1
        if handle.request_id in self.world.applied_action_ids:
            effect = EffectReceipt(
                f"fx:{handle.request_id}", handle.request_digest, EffectClass.RECONCILABLE,
                EffectCertainty.EFFECT_CONFIRMED, "world",
            )
            result = ActionResult(
                handle.request_id, True, self.observe(context), effect, {"source": "world_reconcile"}
            )
            return ActionReconciliationResult(
                handle.request_id, ActionReconciliationDisposition.APPLIED, result, {}
            )
        no_effect = EffectReceipt(
            f"fx:{handle.request_id}:none", handle.request_digest, EffectClass.RECONCILABLE,
            EffectCertainty.NO_EFFECT, "world",
        )
        result = ActionResult(handle.request_id, False, self.observe(context), no_effect, {})
        return ActionReconciliationResult(
            handle.request_id, ActionReconciliationDisposition.NOT_APPLIED, result, {}
        )


    def reconcile(self, effect, context):
        return effect

    def checkpoint(self):
        # The real external world is intentionally not rollback-able by this session snapshot.
        return json.dumps({"observed_generation": self.world.generation}).encode()

    def restore(self, payload):
        # Restore local session state only. The external world remains authoritative.
        json.loads(payload)

    def close(self):
        pass


class Environment:
    identity = EnvironmentIdentity("e", "1", "1", "1")
    def __init__(self, world): self.world = world
    def open_session(self, *, session_id, services): return EnvironmentSession(self.world)


def spec() -> ExperimentSpec:
    return context_action_spec(study_id="study", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)


def registries(world: ExternalWorld, sessions: list[MethodSession]):
    mr = FakeParticipantResolver(); er = FakeParticipantResolver()
    mr.register("method", "m", lambda: Method(sessions))
    er.register("environment", "e", lambda: Environment(world))
    return mr, er


def test_checkpoint_restore_plus_action_wal_recovers_applied_effect_without_second_external_act():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        checkpoint_store = DirectoryRunCheckpointStore(root / "checkpoints")
        action_journal = SQLiteEffectIntentJournal(root / "actions.sqlite3")
        world = ExternalWorld()
        run_identity = RunIdentity("run", "session", "trace")
        c1 = run_identity.cycle(decision_cycle_id="dc1", task_id="t1")
        c2 = run_identity.cycle(decision_cycle_id="dc2", task_id="t2")

        sessions1: list[MethodSession] = []
        mr, er = registries(world, sessions1)
        runtime = context_action_runtime(
            mr, er, checkpoint_store=checkpoint_store, effect_journal=action_journal
        )
        run = runtime.open_run(spec(), run_identity=run_identity)
        run.execute(task="one", input_kind="move", input_payload={"n": 1}, cycle_identity=c1)
        checkpoint1 = run.latest_checkpoint_id
        assert checkpoint1 is not None
        assert sessions1[0].completed == 1
        assert world.raw_act_calls == 1

        world.crash_after_effect_for.add("action_dc2")
        with pytest.raises(Exception):
            run.execute(task="two", input_kind="move", input_payload={"n": 2}, cycle_identity=c2)
        assert run.requires_recovery is True
        assert world.raw_act_calls == 2
        assert "action_dc2" in world.applied_action_ids
        run.close()

        # PREPARED survived, but there is no returned EffectReceipt for dc2.
        # Construct the exact journal identity without relying on private runtime objects.
        # The action is authorized by the last verified joint checkpoint; environment
        # generation is deliberately not part of the stable action identity.
        from noetrium_platform.research.experimentation.run.runtime.decision_coordination import identity_context
        context = replace(identity_context(c2, spec()), checkpoint_id=checkpoint1)
        request = ActionRequest("action_dc2", "move", {"n": 2}, context)
        intent = environment_effect_intent(request, participant_component(next(row for row in spec().participants if row.role == "environment")), operation_id="dc2:environment.act")
        row = action_journal.load(intent.intent_id)
        assert row is not None and row.phase is EffectIntentPhase.PREPARED

        # Fresh process-equivalent method/environment sessions restore the pre-cycle scientific cut.
        sessions2: list[MethodSession] = []
        mr2, er2 = registries(world, sessions2)
        restored_runtime = context_action_runtime(
            mr2, er2, checkpoint_store=checkpoint_store, effect_journal=action_journal
        )
        restored = restored_runtime.open_run(
            spec(), run_identity=run_identity,
            restore_checkpoint_id=checkpoint1, restore_cycle_identity=c1,
        )
        assert restored.last_context is not None
        assert restored.last_context.checkpoint_id == checkpoint1
        assert sessions2[0].completed == 1

        replay = restored.execute(
            task="two", input_kind="move", input_payload={"n": 2}, cycle_identity=c2
        )
        assert replay.primary_result.diagnostics["source"] == "world_reconcile"
        assert world.raw_act_calls == 2, "recovery must not execute the external action again"
        assert world.reconcile_calls == 1
        assert sessions2[0].completed == 2
        row = action_journal.load(intent.intent_id)
        assert row is not None and row.phase is EffectIntentPhase.CONSUMED
        assert row.consumption is not None
        assert row.consumption.completion_key == "cycle:run:dc2"
        restored.close()
