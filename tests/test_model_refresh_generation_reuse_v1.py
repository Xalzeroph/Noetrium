"""Avoid a second online canary only for an identical fenced physical generation."""
from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

from noetrium_platform.composition.model_runtime_refresh import (
    _can_reuse_generation_bound_qualification,
    _pair_qualified_replica_sources,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.capabilities.model.serving.endpoint.api import ModelEndpointRoute
from noetrium_platform.capabilities.model.serving.api import RoleModelAssignment
from noetrium_platform.capabilities.model.serving.composition import canonical_runtime_canary_probe


def _qualifications():
    applied = SimpleNamespace(
        pid=101, process_start_marker="boot:101",
        argv_digest="a" * 64,
    )
    deployed = SimpleNamespace(
        deployment_id="deployment-1",
        stack=SimpleNamespace(
            digest=lambda: "b" * 64,
            identity=SimpleNamespace(model_id="model-a"),
        ),
        certificate=SimpleNamespace(digest=lambda: "c" * 64),
        digest=lambda: "d" * 64,
    )
    route = ModelEndpointRoute(
        deployment_id="deployment-1",
        deployment_generation="d" * 64,
        base_url="http://127.0.0.1:39123",
    )
    assignment = RoleModelAssignment(
        role="agent", capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        deployment_id="deployment-1",
    )
    probe = canonical_runtime_canary_probe(
        assignment, deployed, required_capabilities=("generation",)
    )
    evidence = SimpleNamespace(
        role="agent",
        capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        verified_capabilities=("generation",),
        probe_digest=probe.digest(),
        deployment_id="deployment-1",
        passed=True,
        deployment_generation=deployed.digest(),
        route_digest=canonical_digest(route),
        process_pid=applied.pid,
        process_start_marker=applied.process_start_marker,
        argv_digest=applied.argv_digest,
        evidence_digest="e" * 64,
        observed_at=10.0,
    )
    receipt = SimpleNamespace(
        deployment_id="deployment-1",
        stack_digest=deployed.stack.digest(),
        qualification_certificate_digest=deployed.certificate.digest(),
        process_pid=applied.pid,
        process_start_marker=applied.process_start_marker,
        argv_digest=applied.argv_digest,
        heartbeat_timestamp=9.0,
        valid_until=100.0,
        evidence_refs=("canary:sha256:" + evidence.evidence_digest,),
        qualified_roles=("agent",),
    )
    closure = SimpleNamespace(
        deployments=(deployed,),
        routes=(route,),
        role_manifest=SimpleNamespace(assignments=(assignment,)),
        runtime_manifest_digest="f" * 64,
        runtime_canary_evidence=(evidence,),
        runtime_qualifications=SimpleNamespace(load=lambda *args: receipt),
    )
    kwargs = dict(
        closure=closure,
        deployments=(deployed,),
        routes=(route,),
        applied_identities={deployed.deployment_id: applied},
    )
    return kwargs, applied, deployed, route, evidence, receipt


def test_unmodified_live_generation_reuses_published_canary():
    kwargs, *_ = _qualifications()
    assert _can_reuse_generation_bound_qualification(**kwargs)


def test_runtime_canary_does_not_expire_merely_with_wall_clock():
    kwargs, _, _, _, _, receipt = _qualifications()
    # valid_until bounds when the proof was captured, not endpoint identity.
    kwargs["closure"].runtime_qualifications.load = lambda *a: SimpleNamespace(
        **{**vars(receipt), "valid_until": 11.0}
    )
    assert _can_reuse_generation_bound_qualification(**kwargs)


def test_process_generation_drift_requires_new_online_canary():
    kwargs, applied, *_ = _qualifications()
    kwargs["applied_identities"] = {
        "deployment-1": SimpleNamespace(**{
            **vars(applied), "process_start_marker": "boot:102"
        })
    }
    assert not _can_reuse_generation_bound_qualification(**kwargs)


def test_route_and_certificate_drift_require_new_canary():
    kwargs, *_ = _qualifications()
    kwargs["routes"] = (replace(kwargs["routes"][0], base_url="http://other"),)
    assert not _can_reuse_generation_bound_qualification(**kwargs)
    kwargs, _, deployed, *_ = _qualifications()
    kwargs["deployments"] = (SimpleNamespace(
        **{**vars(deployed), "digest": lambda: "0" * 64}
    ),)
    assert not _can_reuse_generation_bound_qualification(**kwargs)


def test_changed_or_missing_canary_proof_requires_requalification():
    kwargs, _, _, _, evidence, receipt = _qualifications()
    kwargs["closure"].runtime_canary_evidence = (
        SimpleNamespace(**{**vars(evidence), "passed": False}),
    )
    assert not _can_reuse_generation_bound_qualification(**kwargs)
    kwargs, *_ = _qualifications()
    kwargs["closure"].runtime_canary_evidence = ()
    assert not _can_reuse_generation_bound_qualification(**kwargs)
    kwargs, _, _, _, _, receipt = _qualifications()
    kwargs["closure"].runtime_qualifications.load = lambda *_: SimpleNamespace(
        **{**vars(receipt), "evidence_refs": ()}
    )
    assert not _can_reuse_generation_bound_qualification(**kwargs)


def test_replica_set_drift_requires_new_qualification():
    kwargs, *_ = _qualifications()
    kwargs["applied_identities"] = {}
    assert not _can_reuse_generation_bound_qualification(**kwargs)

def test_full_refresh_skips_second_canary_for_same_borrowed_generation(
    tmp_path, monkeypatch
):
    from noetrium_platform.composition import model_runtime_refresh as module
    from noetrium_platform.composition.model_runtime_bootstrap import (
        RequiredModelRuntime,
    )

    kwargs, applied, deployment, route, _, _ = _qualifications()
    closure = kwargs["closure"]
    deployment.stack.identity = SimpleNamespace(
        model_id="model-a", context_length=8192, engine="vllm",
    )
    deployment.stack.tensor_parallel = 1
    deployment.stack.engine_args = ()
    deployment.certificate.target_host_identity_digest = "host-a"
    root = tmp_path / "authority"
    path = root / "models" / "model-a" / "qualified-model-closure.json"
    path.parent.mkdir(parents=True)
    path.write_text("{}", encoding="utf-8")

    placements = (
        SimpleNamespace(
            replica_index=0, deployment_id=deployment.deployment_id,
            gpu_ids=("gpu-a",), endpoint_host="127.0.0.1",
            endpoint_port=39123,
        ),
    )
    calls = []

    class Pool:
        def borrow_existing(self, request, *, expected_replica_count):
            calls.append("borrow")
            assert expected_replica_count == 1
            return SimpleNamespace(report=SimpleNamespace(placements=placements))

        def reclaim_dominated_warm_realizations(self):
            return ()

    monkeypatch.setattr(module, "qualified_model_closure_path", lambda *a: path)
    monkeypatch.setattr(module, "_load_strict", lambda *a: closure)
    monkeypatch.setattr(module, "_uses_current_model_qualification_protocol", lambda *a: True)
    monkeypatch.setattr(module, "_closure_covers_required_model_rows", lambda *a, **kw: True)
    monkeypatch.setattr(module, "qualification_source_stack_digest", lambda x: x.digest())
    monkeypatch.setattr(module, "_desired_stack_materializations", lambda topologies, **kw: {
        key: SimpleNamespace(stack=deployment.stack, compute=object()) for key in topologies
    })
    monkeypatch.setattr(module, "ModelReplicaPoolRequest", lambda **kw: SimpleNamespace(**kw))
    monkeypatch.setattr(module, "QualifiedDeploymentManifest", lambda **kw: deployment)
    monkeypatch.setattr(module, "DeploymentPlacement", lambda ids: ids)
    monkeypatch.setattr(module, "decode_qualified_closure",
                        lambda document: SimpleNamespace(
                            closure_digest="f" * 64,
                            runtime_manifest_digest="f" * 64,
                            deployments=(deployment,),
                        ))
    monkeypatch.setattr(module, "qualify_and_publish_model_deployment_closure",
                        lambda *a, **kw: (_ for _ in ()).throw(AssertionError("duplicate canary")))
    physical = SimpleNamespace(applied_identity=lambda _: applied)
    inventory = SimpleNamespace(host=lambda _: object())
    pool = Pool()
    execution_pool = SimpleNamespace(
        open_model_io_group=lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("duplicate canary group")
        ),
    )
    result = module._refresh_required_qualified_model_runtimes_unfenced(
        authority_root=root,
        required_models=(RequiredModelRuntime(model_id="model-a", role="agent"),),
        assets=object(), resource_authority=object(), model_resources=object(),
        state_root=tmp_path / "model", runtime_workdir=tmp_path / "model-runtime",
        model_replica_pool=pool, deployment_runtime=physical,
        compute_inventory=inventory, gpu_runtime_observer=None,
        host_runtime_observer=None, execution_pool=execution_pool,
    )
    assert result == ("f" * 64,)
    assert calls == ["borrow"]

def test_replica_identity_pairing_preserves_canonical_role_with_permuted_ids():
    # The source closure was sorted by hashed deployment IDs, not the physical
    # replica index. Positional zip would swap role provenance.
    source_a = SimpleNamespace(deployment_id="a")
    source_z = SimpleNamespace(deployment_id="z")
    physical_z = SimpleNamespace(deployment_id="z", replica_index=0)
    physical_a = SimpleNamespace(deployment_id="a", replica_index=1)
    pairs = _pair_qualified_replica_sources(
        (source_a, source_z), (physical_z, physical_a)
    )
    assert pairs == ((source_z, physical_z), (source_a, physical_a))


def test_changed_physical_id_cannot_be_mistaken_for_existing_replica():
    source = SimpleNamespace(deployment_id="old")
    new_physical = SimpleNamespace(deployment_id="new", replica_index=0)
    assert _pair_qualified_replica_sources(
        (source,), (new_physical,)
    ) == ((source, new_physical),)

def test_changed_canonical_canary_contract_requires_live_requalification():
    kwargs, _, _, _, evidence, _ = _qualifications()
    kwargs["closure"].runtime_canary_evidence = (
        SimpleNamespace(**{**vars(evidence), "probe_digest": "0" * 64}),
    )
    assert not _can_reuse_generation_bound_qualification(**kwargs)


def test_role_not_covered_by_qualified_receipt_requires_live_requalification():
    kwargs, _, _, _, _, receipt = _qualifications()
    kwargs["closure"].runtime_qualifications.load = lambda *_: SimpleNamespace(
        **{**vars(receipt), "qualified_roles": ()}
    )
    assert not _can_reuse_generation_bound_qualification(**kwargs)
