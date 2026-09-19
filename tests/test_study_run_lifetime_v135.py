from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec

import hashlib
import json
from pathlib import Path
import tempfile

import pytest

from noetrium_platform.capabilities.environment.runtime.api import ActionRequest, ActionResult, EnvironmentIdentity, Observation, action_request_digest
from noetrium_platform.foundation.kernel.kernel import EffectCertainty, EffectClass, EffectReceipt
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, MethodSnapshot, MethodTaskCompletionReceipt, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.checkpoint.providers import DirectoryRunCheckpointStore
from noetrium_platform.research.execution.decision.cycle_identity import DecisionCycleIdentity
from noetrium_platform.research.experimentation.run.lifecycle.api import RunRecoveryRequired


class MethodSession:
    def __init__(self, owner, session_id):
        self.owner=owner; self.session_id=session_id; self.completed=0; self.closed=False
    def ingest(self,evidence,context): pass
    def recall(self,request): return RecallResult(f"completed={self.completed}",f"mg{self.completed}")
    def task_completed(self,result,context):
        self.completed += 1
        return MethodTaskCompletionReceipt(f"completion:{context.decision_cycle_id}",f"mg{self.completed}")
    def checkpoint(self):
        payload=json.dumps({"completed":self.completed}).encode()
        return MethodSnapshot("m","1","1","",self.session_id,hashlib.sha256(payload).hexdigest(),payload)
    def restore(self,snapshot): self.completed=json.loads(snapshot.opaque_payload)["completed"]
    def close(self): self.closed=True; self.owner.close_count += 1


class Method:
    identity=MethodIdentity("m","1","1","1")
    def __init__(self, owner): self.owner=owner
    def open_session(self,*,session_id,services):
        self.owner.open_count += 1
        session=MethodSession(self.owner,session_id); self.owner.sessions.append(session); return session


class MethodOwner:
    def __init__(self): self.open_count=0; self.close_count=0; self.sessions=[]


class EnvironmentSession:
    def __init__(self, owner): self.owner=owner; self.actions=0; self.closed=False
    def observe(self,context): return Observation(f"o{self.actions}",f"eg{self.actions}",{"actions":self.actions})
    def act(self,request):
        if self.owner.fail_next:
            self.owner.fail_next=False
            raise OSError("environment cut")
        self.actions += 1
        observation=Observation(f"o{self.actions}",f"eg{self.actions}",{"actions":self.actions})
        effect=EffectReceipt("fx",action_request_digest(request),EffectClass.RECONCILABLE,EffectCertainty.EFFECT_CONFIRMED,"env")
        return ActionResult(request.action_id,True,observation,effect,{})
    def checkpoint(self): return json.dumps({"actions":self.actions}).encode()
    def restore(self,payload): self.actions=json.loads(payload)["actions"]
    def close(self): self.closed=True; self.owner.close_count += 1


class Environment:
    identity=EnvironmentIdentity("e","1","1","1")
    def __init__(self,owner): self.owner=owner
    def open_session(self,*,session_id,services):
        self.owner.open_count += 1
        session=EnvironmentSession(self.owner); self.owner.sessions.append(session); return session


class EnvironmentOwner:
    def __init__(self): self.open_count=0; self.close_count=0; self.sessions=[]; self.fail_next=False


def registries(mo,eo):
    mr=FakeParticipantResolver(); er=FakeParticipantResolver()
    mr.register("method", "m",lambda:Method(mo)); er.register("environment", "e",lambda:Environment(eo))
    return mr,er


def spec(): return context_action_spec(study_id="study", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1)


def test_long_lived_run_opens_once_checkpoints_each_cycle_and_restores_exact_cut():
    with tempfile.TemporaryDirectory() as td:
        store=DirectoryRunCheckpointStore(Path(td)/"checkpoints")
        mo=MethodOwner(); eo=EnvironmentOwner(); mr,er=registries(mo,eo)
        runtime=context_action_runtime(mr,er,checkpoint_store=store)
        run_id=RunIdentity("run","session","trace")
        run=runtime.open_run(spec(),run_identity=run_id)
        c1=run_id.cycle(decision_cycle_id="dc1",task_id="t1")
        r1=run.execute(task="one",input_kind="move",input_payload={},cycle_identity=c1)
        cp1=run.latest_checkpoint_id
        assert cp1
        c2=run_id.cycle(decision_cycle_id="dc2",task_id="t2")
        r2=run.execute(task="two",input_kind="move",input_payload={},cycle_identity=c2)
        assert mo.open_count == eo.open_count == 1
        assert mo.sessions[0].completed == 2
        assert eo.sessions[0].actions == 2
        assert r1.context_text == "completed=0"
        assert r2.context_text == "completed=1"
        assert any(op.operation_id == "dc2:run.checkpoint.publish" for op in r2.operation_results)
        cp2=run.latest_checkpoint_id
        assert cp2 and cp2 != cp1
        assert run.last_context is not None and run.last_context.checkpoint_id == cp2
        run.close()
        assert mo.close_count == eo.close_count == 1

        # Fresh process-equivalent plugin sessions restore cycle-1 cut, then continue with cycle 2.
        mo2=MethodOwner(); eo2=EnvironmentOwner(); mr2,er2=registries(mo2,eo2)
        restored=context_action_runtime(mr2,er2,checkpoint_store=store).open_run(
            spec(),run_identity=run_id,restore_checkpoint_id=cp1,restore_cycle_identity=c1
        )
        assert mo2.sessions[0].completed == 1
        assert eo2.sessions[0].actions == 1
        assert restored.last_context is not None
        assert restored.last_context.checkpoint_id == cp1
        replay=restored.execute(task="two",input_kind="move",input_payload={},cycle_identity=c2)
        assert replay.context_text == "completed=1"
        assert mo2.sessions[0].completed == 2
        assert eo2.sessions[0].actions == 2
        assert any(op.operation_id == "dc1:method.restore:method" for op in restored.open_operations)
        restored.close()


def test_failed_live_cycle_marks_run_recovery_required_and_blocks_further_scientific_work():
    mo=MethodOwner(); eo=EnvironmentOwner(); mr,er=registries(mo,eo)
    run_id=RunIdentity("run","session","trace")
    run=context_action_runtime(mr,er).open_run(spec(),run_identity=run_id)
    eo.fail_next=True
    with pytest.raises(Exception):
        run.execute(task="bad",input_kind="move",input_payload={},cycle_identity=run_id.cycle(decision_cycle_id="dc1",task_id="t1"))
    assert run.requires_recovery is True
    action_count=eo.sessions[0].actions
    with pytest.raises(RunRecoveryRequired):
        run.execute(task="blocked",input_kind="move",input_payload={},cycle_identity=run_id.cycle(decision_cycle_id="dc2",task_id="t2"))
    assert eo.sessions[0].actions == action_count
    run.close()
