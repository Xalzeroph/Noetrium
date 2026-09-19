from __future__ import annotations

from tests_support import FakeParticipantResolver
from tests_support import context_action_runtime

from tests_support import context_action_spec
from pathlib import Path
import tempfile
import pytest
from tests._concurrency_support import OwnedForensicStore as ForensicStore
from noetrium_platform.composition.operation_forensics import OperationForensicFailureSink
from noetrium_platform.composition.context_action import context_action_failure_classifier_chain
from noetrium_platform.infrastructure.reliability.effect.runtime import SQLiteEffectIntentJournal
from noetrium_platform.capabilities.environment.runtime.api import EnvironmentIdentity, Observation
from noetrium_platform.foundation.kernel.kernel import OperationExecutor, OperationFailure
from noetrium_platform.capabilities.participant.method.api import MethodIdentity, RecallResult
from noetrium_platform.research.experimentation.experiment.runtime import ExperimentRuntime
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec

class MS:
    def ingest(self,e,c): pass
    def recall(self,r): return RecallResult("ctx","g")
    def task_completed(self,r,c): pass
    def close(self): pass
class M:
    identity=MethodIdentity("m","1","1","1")
    def open_session(self,*,session_id,services): return MS()
class ES:
    act_calls=0
    def observe(self,c): return Observation("o","eg",{})
    def act(self,r): type(self).act_calls += 1; raise AssertionError("must not execute")
    def close(self): pass
class E:
    identity=EnvironmentIdentity("e","1","1","1")
    def open_session(self,*,session_id,services): return ES()

def test_crash_durable_journal_requires_reconcile_capability_before_any_external_action():
    with tempfile.TemporaryDirectory() as td:
        mr=FakeParticipantResolver(); mr.register("method", "m",M); er=FakeParticipantResolver(); er.register("environment", "e",E)
        with ForensicStore(Path(td)/"forensics") as store:
            executor=OperationExecutor(OperationForensicFailureSink(store, classifier=context_action_failure_classifier_chain()))
            rt=context_action_runtime(mr,er,operation_executor=executor,effect_journal=SQLiteEffectIntentJournal(Path(td)/"actions.sqlite3"))
            ES.act_calls=0
            with pytest.raises(OperationFailure) as exc:
                rt.execute_cycle(context_action_spec(study_id="s", method_id="m", environment_id="e", workload_digest="b" * 64, seed_digest="c" * 64, repetitions=1),task="t",input_kind="move",input_payload={})
            assert exc.value.result.operation_id.endswith("environment.action_safety_preflight")
            assert ES.act_calls == 0
            failure=store.failures.verified_payloads_after(0).payloads[0]
            assert failure["failure_code"] == "ACTION_SAFETY_CAPABILITY_MISSING"
            assert failure["recommended_recovery"] == "block_scientific_use"
