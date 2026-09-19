from __future__ import annotations

import hashlib
import json
from pathlib import Path
from dataclasses import replace
from threading import Event, Thread
import tempfile
import time
import unittest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityPolicySet,
    CapabilityRequest,
    CapabilityResult,
    GuardDecision,
    GuardVerdict,
)
from noetrium_platform.research.execution.capability.runtime import CapabilityInvocationPipelineFactory
from noetrium_platform.research.execution.machines import (
    CapabilityMediationDenied,
    capability_mediator_binding_digest,
    capability_program_from_policy,
)
from noetrium_platform.evidence.data.fact.api import DurableFact, FactCriticality, UnknownRequiredFact
from noetrium_platform.evidence.observability.api import EventEnvelope
from noetrium_platform.evidence.data.record.api import ExecutionRecordPlane
from noetrium_platform.evidence.data.fact.runtime import FactDecoderRegistry
from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal, canonical_bytes, EffectClass, ExecutionContext, ImmutableModelIdentity, canonical_digest
from noetrium_platform.evidence.artifact.content.providers import DirectoryArtifactBlobStore
from noetrium_platform.capabilities.model.request.runtime import (
    DirectoryModelRequestLedger,
    ReconstructableModelRequestRecorder,
)
from noetrium_platform.evidence.data.projection.api import ProjectionCursor, ProjectionTail
from noetrium_platform.evidence.data.projection.runtime import IncrementalProjectionRuntime, InMemoryProjectionCheckpointStore, ProjectionSourceDrift
from noetrium_platform.research.execution.capability.api import RegistrationKey, ScopeDisposed
from noetrium_platform.research.execution.capability.runtime import ScopedRegistrationRuntime


class _Deny:
    guard_id = "deny.secret"
    implementation_digest = canonical_digest({
        "guard": guard_id,
        "implementation_revision": 1,
    })
    def evaluate(self, descriptor, request):
        return GuardDecision(self.guard_id, GuardVerdict.DENY, "policy.blocked")


class _Allow:
    guard_id = "allow.after"
    implementation_digest = canonical_digest({
        "guard": guard_id,
        "implementation_revision": 1,
    })
    def evaluate(self, descriptor, request):
        return GuardDecision(self.guard_id, GuardVerdict.ALLOW)


class _AllowV2:
    guard_id = "allow.after"
    implementation_digest = canonical_digest({
        "guard": guard_id,
        "implementation_revision": 2,
    })
    def evaluate(self, descriptor, request):
        return GuardDecision(self.guard_id, GuardVerdict.ALLOW)


class _RejectPost:
    policy_id = "post.reject"
    implementation_digest = canonical_digest({
        "post_policy": policy_id,
        "implementation_revision": 1,
    })
    def validate(self, descriptor, request, result):
        raise RuntimeError("token=POST_POLICY_SECRET")


class _Reducer:
    projector_id = "sum"
    projector_version = "v1"
    def initial(self): return 0
    def apply(self, state, item): return state + item
    def digest(self, state): return canonical_digest(state)


class HarnessPatternsV190Tests(unittest.TestCase):
    def test_capability_policy_binding_changes_with_implementation_identity(self):
        first_program, first_mediators = capability_program_from_policy(
            CapabilityPolicySet(guards=(_Allow(),))
        )
        second_program, second_mediators = capability_program_from_policy(
            CapabilityPolicySet(guards=(_AllowV2(),))
        )
        self.assertEqual(first_program.program_digest, second_program.program_digest)
        self.assertNotEqual(
            capability_mediator_binding_digest(first_program, first_mediators),
            capability_mediator_binding_digest(second_program, second_mediators),
        )

    def test_capability_policy_requires_explicit_implementation_identity(self):
        class MissingIdentity:
            guard_id = "missing.identity"
            def evaluate(self, descriptor, request):
                return GuardDecision(self.guard_id, GuardVerdict.ALLOW)

        with self.assertRaises((TypeError, ValueError)):
            CapabilityPolicySet(guards=(MissingIdentity(),))

    def context(self):
        return ExecutionContext(run_id="r190", trace_id="tr190", span_id="sp190", decision_cycle_id="dc190")

    def test_model_visible_request_is_reconstructable_and_drift_fails(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            content=DirectoryArtifactBlobStore(root/"blobs")
            ledger=DirectoryModelRequestLedger(root/"ledger")
            recorder=ReconstructableModelRequestRecorder(content,ledger)
            body={"messages":[{"role":"system","content":"hello"}],"tools":[{"name":"x"}]}
            env=recorder.record(
                request_id="rq190", context=self.context(), role="planner",
                model=ImmutableModelIdentity("planner","m","rev","engine","1","bf16",None,4096), prompt_generation_id="g1",
                prompt_id="planner.v1", prompt_digest="a"*64, request_body=body,
                compiled_prompt_text="hello", tool_schema_bundle=body["tools"],
                source_artifact_refs=("artifact:1",), source_state_refs=("state:1",),
            )
            self.assertEqual(env.model.model_id,"m")
            self.assertEqual(env.model.engine,"engine")
            reconstructed_full=recorder.reconstruct(env)
            reconstructed=reconstructed_full.request_body
            self.assertEqual(canonical_bytes(reconstructed),canonical_bytes(body))
            with self.assertRaises(TypeError): reconstructed_full.tool_schema_bundle[0]["name"]="tampered"
            self.assertFalse(isinstance(reconstructed, dict))
            with self.assertRaises(TypeError): reconstructed["messages"]=[]
            with self.assertRaises(TypeError): dict.__setitem__(reconstructed,"bypass",True)
            with self.assertRaises(TypeError): reconstructed["messages"][0]["content"]="tampered"
            recorder.verify_visible_request(env,body)
            body["messages"][0]["content"]="caller-mutated"
            self.assertEqual(reconstructed["messages"][0]["content"],"hello")
            self.assertEqual(ledger.get("rq190"),env)
            with self.assertRaises(RuntimeError): recorder.verify_visible_request(env,body)
            with self.assertRaises(RuntimeError): recorder.verify_visible_request(env,{"messages":[]})
            other_ref=content.put(b'{"x":1}',media_type="application/json")
            with self.assertRaises(RuntimeError):
                ledger.append(replace(env,request_body=other_ref,envelope_digest=""))

    def test_model_request_recorder_rejects_non_json_visible_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root=Path(td)
            recorder=ReconstructableModelRequestRecorder(
                DirectoryArtifactBlobStore(root/"blobs"),
                DirectoryModelRequestLedger(root/"ledger"),
            )
            common=dict(
                request_id="rq-bad-json", context=self.context(), role="planner",
                model=ImmutableModelIdentity("planner","m","rev","engine","1","bf16",None,4096),
                prompt_generation_id="g1", prompt_id="planner.v1", prompt_digest="a"*64,
            )
            with self.assertRaises(TypeError):
                recorder.record(**common, request_body={"bad": object()})
            with self.assertRaises(TypeError):
                recorder.record(**common, request_body={"messages": []}, tool_schema_bundle={"bad": object()})

    def test_scope_disposal_waits_for_active_lease_and_then_rejects_new_use(self):
        scope=ScopedRegistrationRuntime("root")
        key=RegistrationKey("capability","x")
        scope.register(key,object())
        entered=Event(); release=Event(); disposed=Event()
        def reader():
            with scope.acquire(key):
                entered.set(); release.wait(2)
        def disposer():
            scope.dispose(timeout_s=2); disposed.set()
        t=Thread(target=reader); t.start(); self.assertTrue(entered.wait(1))
        d=Thread(target=disposer); d.start(); time.sleep(.05); self.assertFalse(disposed.is_set())
        release.set(); t.join(1); d.join(1); self.assertTrue(disposed.is_set())
        with self.assertRaises(ScopeDisposed): scope.register(RegistrationKey("x","y"),1)

    def test_monotonic_guard_denial_prevents_execute_and_later_allow(self):
        descriptor=CapabilityDescriptor("capability.test","v1","req","res",EffectClass.PURE)
        request=CapabilityRequest("capability.test",{},self.context())
        called=[]
        journal=InMemoryMachineJournal()
        pipeline=CapabilityInvocationPipelineFactory(journal).create(
            CapabilityPolicySet(guards=(_Deny(),_Allow()))
        )
        with self.assertRaises(CapabilityMediationDenied) as caught:
            pipeline.invoke(
                invocation_id="dc190:capability.test:0",
                descriptor=descriptor,
                request=request,
                execute=lambda mediated: (
                    called.append(1)
                    or CapabilityResult(mediated.capability_id,{})
                ),
            )
        self.assertEqual(called,[])
        self.assertEqual(caught.exception.stage.value,"pre")
        self.assertFalse(caught.exception.execution_completed)
        commits=journal.commits("runtime-capability:r190:" + canonical_digest({
            "invocation_id":"dc190:capability.test:0",
            "run_id":"r190",
            "capability_id":"capability.test",
            "program_digest":pipeline._program.program_digest,
        })[:24])
        self.assertGreaterEqual(len(commits),2)
        self.assertEqual(commits[-1].accepted_status.value,"failed")

    def test_projection_runtime_replays_only_tail_and_rejects_rewind(self):
        store=InMemoryProjectionCheckpointStore(); runtime=IncrementalProjectionRuntime(); reducer=_Reducer()
        cp=runtime.advance(reducer=reducer,store=store,tail=ProjectionTail(ProjectionCursor("ledger",0,"0"*64),ProjectionCursor("ledger",2,"a"*64),(1,2)))
        self.assertEqual(cp.payload,3)
        cp=runtime.advance(reducer=reducer,store=store,tail=ProjectionTail(cp.cursor,ProjectionCursor("ledger",3,"b"*64),(3,)))
        self.assertEqual(cp.payload,6)
        with self.assertRaises(ProjectionSourceDrift):
            runtime.advance(reducer=reducer,store=store,tail=ProjectionTail(ProjectionCursor("ledger",2,"a"*64),ProjectionCursor("ledger",2,"a"*64),()))

    def test_unknown_required_fact_fails_closed_but_ignorable_can_be_skipped(self):
        registry=FactDecoderRegistry()
        required=DurableFact("f1","plugin.state","v9",FactCriticality.REQUIRED,{})
        with self.assertRaises(UnknownRequiredFact): registry.decode(required)
        ignorable=DurableFact("f2","plugin.note","v9",FactCriticality.IGNORABLE,{})
        self.assertIsNone(registry.decode(ignorable))

    def test_scope_registration_handle_quiesces_one_key_without_disposing_scope(self):
        scope=ScopedRegistrationRuntime("root")
        key=RegistrationKey("capability","temporary")
        handle=scope.register(key,object())
        entered=Event(); release=Event(); closed=Event()
        def reader():
            with scope.acquire(key):
                entered.set(); release.wait(2)
        def closer():
            handle.close(timeout_s=2); closed.set()
        t=Thread(target=reader); t.start(); self.assertTrue(entered.wait(1))
        c=Thread(target=closer); c.start(); time.sleep(.05); self.assertFalse(closed.is_set())
        release.set(); t.join(1); c.join(1); self.assertTrue(closed.is_set())
        with self.assertRaises(KeyError):
            with scope.acquire(key): pass
        other=RegistrationKey("capability","other")
        scope.register(other,1)
        with scope.acquire(other) as value: self.assertEqual(value,1)
        scope.dispose()

    def test_disposed_child_cannot_acquire_inherited_parent_registration(self):
        parent=ScopedRegistrationRuntime("parent")
        key=RegistrationKey("capability","shared")
        parent.register(key,object())
        child=parent.child("child")
        child.dispose()
        with self.assertRaises(ScopeDisposed):
            with child.acquire(key): pass
        with parent.acquire(key): pass
        parent.dispose()

    def test_concurrent_scope_dispose_callers_share_quiescence_boundary(self):
        scope=ScopedRegistrationRuntime("root")
        key=RegistrationKey("capability","x")
        scope.register(key,object())
        entered=Event(); release=Event(); done=[]; errors=[]
        def reader():
            with scope.acquire(key): entered.set(); release.wait(2)
        def disposer():
            try:
                scope.dispose(timeout_s=2); done.append(1)
            except BaseException as exc:
                errors.append(exc)
        t=Thread(target=reader); t.start(); self.assertTrue(entered.wait(1))
        d1=Thread(target=disposer); d2=Thread(target=disposer); d1.start(); d2.start()
        time.sleep(.05); self.assertEqual(done,[])
        release.set(); t.join(1); d1.join(1); d2.join(1)
        self.assertEqual(errors,[]); self.assertEqual(len(done),2)

    def test_post_policy_rejection_preserves_completed_execution_truth(self):
        descriptor=CapabilityDescriptor("capability.test","v1","req","res",EffectClass.RECONCILABLE)
        request=CapabilityRequest("capability.test",{},self.context())
        result=CapabilityResult("capability.test",{"ok":True})
        pipeline=CapabilityInvocationPipelineFactory(
            InMemoryMachineJournal()
        ).create(CapabilityPolicySet(post_policies=(_RejectPost(),)))
        with self.assertRaises(CapabilityMediationDenied) as caught:
            pipeline.invoke(
                invocation_id="dc190:capability.test:post",
                descriptor=descriptor,
                request=request,
                execute=lambda mediated: result,
            )
        exc=caught.exception
        self.assertTrue(exc.execution_completed)
        self.assertFalse(exc.retry_safe)
        self.assertEqual(exc.stage.value,"post")
        self.assertEqual(exc.reason_code,"post_policy:post.reject")

    def test_projection_rejects_same_watermark_with_changed_source_digest(self):
        store=InMemoryProjectionCheckpointStore(); runtime=IncrementalProjectionRuntime(); reducer=_Reducer()
        cp=runtime.advance(reducer=reducer,store=store,tail=ProjectionTail(ProjectionCursor("ledger",0,"0"*64),ProjectionCursor("ledger",1,"a"*64),(1,)))
        with self.assertRaises(RuntimeError):
            runtime.advance(reducer=reducer,store=store,tail=ProjectionTail(cp.cursor,ProjectionCursor("ledger",1,"b"*64),()))

    def test_record_planes_are_explicit_and_non_interchangeable(self):
        fact=DurableFact("f-plane","session.state","v1",FactCriticality.REQUIRED,{})
        self.assertIs(fact.record_plane,ExecutionRecordPlane.DURABLE_FACT)
        decision=GuardDecision("guard.live",GuardVerdict.ABSTAIN)
        self.assertIs(decision.record_plane,ExecutionRecordPlane.LIVE_INTERCEPTION)
        event=EventEnvelope("e-plane","TRACE",self.context(),"component.test")
        self.assertIs(event.record_plane,ExecutionRecordPlane.SIDE_PLANE_OBSERVATION)
        self.assertNotIn("record_plane",event.to_dict())


if __name__ == "__main__": unittest.main()
