from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.capabilities.model.api import (
    ProjectModelBinding,
    ProjectModelBindingSet,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    QualifiedModelEndpointBinding,
)
from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    canonical_digest,
)
from noetrium_platform.research.experimentation.api import compile_experiment_program
from noetrium_platform.research.experimentation.composition import (
    compile_model_replica_shard_plan,
    qualified_replica_capacity_units,
)
from noetrium_platform.research.experimentation.lifecycle.api import (
    AssignmentWorkload,
    StudyExecutionPlan,
    StudyAssignment,
    StudyProtocol,
    StudyVariantSpec,
    VariantBinding,
    VariantKind,
)


MODEL = ImmutableModelIdentity(
    "qwen3-8b",
    "Qwen/Qwen3-8B",
    "revision-qwen3-8b",
    "vllm",
    "0.8.5",
    "bfloat16",
    None,
    8192,
    "tokenizer-qwen3-8b",
)


def _binding(index: int) -> ProjectModelBinding:
    digit = f"{index + 3:x}"
    return ProjectModelBinding(
        requirement_digest="1" * 64,
        provider_id="provider-qwen",
        provider_profile_digest="2" * 64,
        role="policy",
        model=MODEL,
        deployment_id=f"qwen-replica-{index}",
        deployment_generation=digit * 64,
        model_stack_digest="a" * 64,
        qualification_certificate_digest="b" * 64,
        runtime_qualification_digest="c" * 64,
        host_identity_digest="d" * 64,
        prompt_generation_id="prompt-generation",
        prompt_id="policy-prompt",
        prompt_digest="e" * 64,
        capabilities=("generation",),
        runtime_canary_evidence_digests=(f"{index + 6:x}" * 64,),
        request_tokenization_digest="f" * 64,
    )


def _qualified(binding: ProjectModelBinding, capacity: int) -> QualifiedModelEndpointBinding:
    return QualifiedModelEndpointBinding(
        role=binding.role,
        capability_id="generation",
        input_schema_id="model.generation.request.v1",
        output_schema_id="model.generation.response.v1",
        deployment_id=binding.deployment_id,
        deployment_generation=binding.deployment_generation,
        base_url=f"http://127.0.0.1:{18000 + capacity}",
        model=binding.model,
        model_stack_digest=binding.model_stack_digest,
        qualification_certificate_digest=binding.qualification_certificate_digest,
        runtime_qualification_digest=binding.runtime_qualification_digest,
        host_identity_digest=binding.host_identity_digest,
        prompt_generation=binding.prompt_generation_id or "",
        max_admitted_concurrency=capacity,
        runtime_canary_evidence_digests=binding.runtime_canary_evidence_digests,
        tokenizer_sha256="9" * 64,
        chat_template_sha256=None,
    )


def _compiled():
    variant = StudyVariantSpec(
        variant_id="treatment",
        kind=VariantKind.TREATMENT,
        implementation_id="impl:treatment",
        configuration_digest=canonical_digest({"variant": "treatment"}),
        budget_tier="standard",
    )
    protocol = StudyProtocol(
        study_id="replica-sharding",
        workload_id="benchmark:test",
        variants=(variant,),
        repetitions=6,
        seed_schedule_digest=canonical_digest(tuple(str(i) for i in range(6))),
        metric_names=("success",),
        task_manifest_digest=canonical_digest(tuple(f"task-{i}" for i in range(6))),
        assignment_workloads=tuple(
            AssignmentWorkload((f"task-{i}",))
            for i in range(6)
        ),
        budget_tiers=("standard",),
    )
    binding = VariantBinding(
        variant=variant,
        intervention_digest=canonical_digest({"variant": "treatment"}),
        provider_id="provider:treatment",
        ablation_policy_id="none",
        comparator_role="treatment",
    )
    assignments = tuple(
        StudyAssignment(
            study_id=protocol.study_id,
            variant_id=variant.variant_id,
            repetition=repetition,
            seed=str(repetition),
            workload=workload,
        )
        for repetition in range(6)
        for workload in protocol.assignment_workloads
    )
    return compile_experiment_program(
        StudyExecutionPlan.compile(protocol, (binding,), assignments)
    )


def test_qualified_replica_capacity_drives_exact_worker_sharding() -> None:
    bindings = tuple(_binding(index) for index in range(3))
    binding_set = ProjectModelBindingSet(bindings)
    qualified = tuple(
        _qualified(binding, capacity)
        for binding, capacity in zip(bindings, (1, 2, 3), strict=True)
    )

    capacities = qualified_replica_capacity_units(binding_set, qualified)
    plan = compile_model_replica_shard_plan(
        _compiled(),
        binding_set=binding_set,
        capacity_units=capacities,
    )

    assert tuple(row.capacity_units for row in plan.workers) == (1, 2, 3)
    assert tuple(len(row.assignment_digests) for row in plan.shard_plan.shards) == (
        6,
        12,
        18,
    )
    assert tuple(row.worker_scope_id for row in plan.workers) == tuple(
        row.worker_scope_id for row in plan.shard_plan.shards
    )
    plan.shard_plan.assert_complete_for(_compiled())


def test_replica_sharding_rejects_scientific_model_drift() -> None:
    first = _binding(0)
    second = replace(_binding(1), provider_id="different-provider")
    binding_set = ProjectModelBindingSet((first, second))

    with pytest.raises(ValueError, match="scientifically equivalent"):
        compile_model_replica_shard_plan(
            _compiled(),
            binding_set=binding_set,
            capacity_units={first.digest(): 1, second.digest(): 1},
        )


def test_qualified_capacity_must_cover_every_frozen_replica() -> None:
    first, second = _binding(0), _binding(1)
    binding_set = ProjectModelBindingSet((first, second))

    with pytest.raises(ValueError, match="no qualified replica capacity"):
        qualified_replica_capacity_units(
            binding_set,
            (_qualified(first, 4),),
        )
