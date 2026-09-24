from __future__ import annotations

import pytest

import research.reproductions.authority_requirements as requirements_module
import research.reproductions.execution_authority as authority_module
import research.reproductions.fleet as fleet_module

from noetrium_platform.composition.research_binding_authority import (
    ResearchCapabilityBindingRegistry,
    ResearchModelRoleBindingRegistry,
    ResearchParticipantBindingRegistry,
    ResearchProjectManifestRegistry,
)
from noetrium_platform.composition.research_os_experiment_runtime_binding import (
    ResearchOSExperimentReconciliationRegistration,
    ResearchOSExperimentReconciliationRegistry,
)
from noetrium_platform.composition.research_os_experiment_trial_execution import (
    ResearchOSExperimentTrialProviderRegistration,
    ResearchOSExperimentTrialProviderRegistry,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectConfigurationReference,
    ProjectIdentity,
    ProjectManifest,
    ProjectMethodRequirement,
    ProjectProviderBinding,
    ProjectSpec,
    ProjectToolProvenance,
)
from noetrium_platform.research.experimentation.api import (
    research_manifest_requirement_keys,
)
from noetrium_platform.research.experimentation.lifecycle.study.api import (
    BenchmarkResolutionRegistry,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)
from research.reproductions.adaptagent_acl2025.definition import (
    REPRODUCTION as ADAPTAGENT,
)
from research.reproductions.execution_authority import (
    MaterializedReproductionFleetExecutionAuthorities,
    ReproductionFleetAuthorityMaterializationError,
    ReproductionFleetAuthorityMaterializerPort,
    ReproductionFleetOwnerAuthorities,
    ReproductionFleetPrerequisiteAuthorities,
    materialize_repository_fleet_execution_authorities,
)
from research.reproductions.fleet import ReproductionBenchmarkSelection


class _AdaptAgentBenchmarkAuthority:
    authority_digest = canonical_digest(
        {"authority": "test.two-stage-materializer.benchmark.v1"}
    )

    @staticmethod
    def _benchmark(benchmark_id: str) -> BenchmarkTaskSet:
        revision = "two-stage-materializer"
        task_id = benchmark_id + ".task"
        task = TaskDefinition(
            task_id,
            revision,
            "fixture",
            benchmark_id + ".task.v1",
            canonical_digest(
                {
                    "benchmark_id": benchmark_id,
                    "revision": revision,
                    "task_id": task_id,
                }
            ),
        )
        return BenchmarkTaskSet(
            benchmark_id=benchmark_id,
            revision_id=revision,
            source_digest=canonical_digest(
                {"benchmark_id": benchmark_id, "revision": revision}
            ),
            task_schema_id=benchmark_id + ".task.v1",
            tasks=(task,),
            splits=(TaskSetSplit("test", (task_id,)),),
        )

    def resolve(self, definition, study_factory):
        assert definition.package == "adaptagent_acl2025"
        assert study_factory.qualname == "build_adaptagent_study"
        return tuple(
            ReproductionBenchmarkSelection(
                self._benchmark(benchmark_id),
                ("test",),
                canonical_digest(
                    {
                        "authority_digest": self.authority_digest,
                        "benchmark_id": benchmark_id,
                    }
                ),
            )
            for benchmark_id in definition.catalog.benchmark_ids
        )


class _TrialProvider:
    def __init__(self, protocol_identity) -> None:
        self.protocol_identity = protocol_identity

    def run_trial(self, request):
        raise AssertionError(
            "two-stage authority materialization must not execute Trial providers"
        )


class _Reconciliation:
    def __init__(self, protocol_digest: str) -> None:
        self._identity_digest = canonical_digest(
            {
                "authority": "test.two-stage-materializer.reconciliation.v1",
                "protocol_digest": protocol_digest,
            }
        )

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def reconcile(
        self,
        closure,
        *,
        machine_id,
        execution_cut_id,
        graph_node_id,
        semantic_digest,
        lowering_digest,
        attempt_id,
    ):
        raise AssertionError(
            "two-stage authority materialization must not reconcile executions"
        )


class _Materializer:
    def __init__(self) -> None:
        self.prerequisite_manifest_digest = None
        self.owner_manifest_digest = None
        self.capability_manifest_digest = None
        self.owner_fleet_digest = None

    def materialize_prerequisites(self, requirements):
        self.prerequisite_manifest_digest = requirements.manifest_digest
        return ReproductionFleetPrerequisiteAuthorities(
            BenchmarkResolutionRegistry(),
        )

    def materialize_manifests(self, requirements, fleet):
        self.owner_manifest_digest = requirements.manifest_digest
        self.owner_fleet_digest = fleet.materialization_digest

        manifests = []
        for lane in fleet.lanes:
            keys = research_manifest_requirement_keys(lane.study)
            capabilities = tuple(
                ProjectCapabilityRequirement(
                    requirement_id,
                    "test",
                    f"capability-{index}",
                    1,
                    canonical_digest(
                        {
                            "requirement_id": requirement_id,
                            "study_id": lane.study.study_id,
                        }
                    ),
                )
                for index, requirement_id in enumerate(
                    keys.capability_requirement_ids
                )
            )
            provider_bindings = tuple(
                ProjectProviderBinding(
                    f"binding-{index}",
                    requirement.requirement_id,
                    f"provider.{index}",
                    "1",
                    canonical_digest(
                        {
                            "provider": f"provider.{index}",
                            "requirement_id": requirement.requirement_id,
                        }
                    ),
                )
                for index, requirement in enumerate(capabilities)
            )
            method_requirements = tuple(
                ProjectMethodRequirement(
                    method_id,
                    treatment_id,
                    canonical_digest(
                        {
                            "method_id": method_id,
                            "treatment_id": treatment_id,
                        }
                    ),
                )
                for method_id, treatment_id in keys.method_requirement_keys
            )
            configuration_refs = tuple(
                ProjectConfigurationReference(
                    configuration_id,
                    f"artifact://fixture/{configuration_id}",
                    canonical_digest(
                        {
                            "configuration_id": configuration_id,
                            "study_id": lane.study.study_id,
                        }
                    ),
                )
                for configuration_id in keys.configuration_ref_ids
            )
            manifests.append(
                ProjectManifest(
                    ProjectSpec(
                        ProjectIdentity(lane.study.project_id, "1"),
                        lane.program.program_id,
                        "Three-stage materializer fixture",
                    ),
                    "fixture-v1",
                    ProjectToolProvenance(
                        "noetrium-test",
                        "1",
                        canonical_digest(
                            {
                                "program_id": lane.program.program_id,
                                "study_id": lane.study.study_id,
                            }
                        ),
                    ),
                    capability_requirements=capabilities,
                    provider_bindings=provider_bindings,
                    method_requirements=method_requirements,
                    configuration_refs=configuration_refs,
                    study_ids=(lane.study.study_id,),
                )
            )
        return ResearchProjectManifestRegistry(tuple(manifests))

    def materialize_execution_owners(
        self,
        requirements,
        capability_requirements,
        fleet,
        manifests,
    ):
        self.capability_manifest_digest = capability_requirements.manifest_digest
        self.owner_fleet_digest = fleet.materialization_digest
        assert capability_requirements.project_manifest_registry_digest == (
            manifests.identity_digest
        )

        protocol_by_digest = {
            lane.study.trial_protocol_identity.digest():
                lane.study.trial_protocol_identity
            for lane in fleet.lanes
        }
        trial_registrations = tuple(
            ResearchOSExperimentTrialProviderRegistration(
                "trial.provider.fixture",
                _TrialProvider(protocol),
                canonical_digest(
                    {
                        "provider": "trial.provider.fixture",
                        "protocol_digest": protocol_digest,
                    }
                ),
            )
            for protocol_digest, protocol in sorted(protocol_by_digest.items())
        )
        reconciliation_registrations = tuple(
            ResearchOSExperimentReconciliationRegistration(
                "trial.provider.fixture",
                protocol_digest,
                _Reconciliation(protocol_digest),
            )
            for protocol_digest in sorted(protocol_by_digest)
        )

        return ReproductionFleetOwnerAuthorities(
            research_capabilities=ResearchCapabilityBindingRegistry(()),
            participants=ResearchParticipantBindingRegistry(()),
            models=ResearchModelRoleBindingRegistry(()),
            trial_providers=ResearchOSExperimentTrialProviderRegistry(
                trial_registrations
            ),
            reconciliation=ResearchOSExperimentReconciliationRegistry(
                reconciliation_registrations
            ),
        )


def test_two_stage_materializer_is_the_single_zero_glue_authority_pipeline(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        requirements_module,
        "executable_reproduction_definitions",
        lambda: (ADAPTAGENT,),
    )
    monkeypatch.setattr(
        fleet_module,
        "executable_reproduction_definitions",
        lambda: (ADAPTAGENT,),
    )

    benchmark_authority = _AdaptAgentBenchmarkAuthority()

    class _RepositoryBenchmarkAuthority:
        @staticmethod
        def discover(registry):
            assert type(registry) is BenchmarkResolutionRegistry
            return benchmark_authority

    monkeypatch.setattr(
        authority_module,
        "RepositoryBenchmarkAuthority",
        _RepositoryBenchmarkAuthority,
    )

    class _ClosedAudit:
        blocker_count = 0
        gap_count = 0

    monkeypatch.setattr(
        authority_module,
        "audit_materialized_reproduction_fleet_authorities",
        lambda *args, **kwargs: _ClosedAudit(),
    )

    materializer = _Materializer()
    assert isinstance(materializer, ReproductionFleetAuthorityMaterializerPort)

    result = materialize_repository_fleet_execution_authorities(materializer)

    assert type(result) is MaterializedReproductionFleetExecutionAuthorities
    assert materializer.prerequisite_manifest_digest == (
        result.prerequisites.manifest_digest
    )
    assert materializer.owner_manifest_digest == (
        result.owner_requirements.manifest_digest
    )
    assert materializer.owner_fleet_digest == result.fleet.materialization_digest
    assert materializer.capability_manifest_digest == (
        result.capability_requirements.manifest_digest
    )
    assert result.owner_requirements.materialization_digest == (
        result.fleet.materialization_digest
    )
    assert result.execution_authorities.benchmark_resolver is benchmark_authority
    assert result.execution_authorities.authority_manifest_digest
    assert len(result.execution_authorities.authority_manifest_digest) == 64
    assert len(result.materialization_digest) == 64
    assert result.materialization_digest not in {
        result.prerequisites.manifest_digest,
        result.fleet.materialization_digest,
        result.owner_requirements.manifest_digest,
        result.capability_requirements.manifest_digest,
        result.execution_authorities.authority_manifest_digest,
    }
    assert result.capability_requirements.requirements
    assert all(
        row.project_manifest_digest
        for row in result.capability_requirements.requirements
    )
    assert {row.stage for row in result.owner_requirements.requirements} == {
        "project_manifest",
        "participant",
        "model",
        "trial_provider",
        "aggregation",
        "reconciliation",
    }


def test_two_stage_materializer_fails_closed_on_incomplete_owner_registries(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        requirements_module,
        "executable_reproduction_definitions",
        lambda: (ADAPTAGENT,),
    )
    monkeypatch.setattr(
        fleet_module,
        "executable_reproduction_definitions",
        lambda: (ADAPTAGENT,),
    )

    benchmark_authority = _AdaptAgentBenchmarkAuthority()

    class _RepositoryBenchmarkAuthority:
        @staticmethod
        def discover(registry):
            assert type(registry) is BenchmarkResolutionRegistry
            return benchmark_authority

    monkeypatch.setattr(
        authority_module,
        "RepositoryBenchmarkAuthority",
        _RepositoryBenchmarkAuthority,
    )

    with pytest.raises(
        ReproductionFleetAuthorityMaterializationError
    ) as captured:
        materialize_repository_fleet_execution_authorities(_Materializer())

    error = captured.value
    assert error.audit.blocker_count > 0
    assert error.audit.gap_count > 0
    assert len(error.prerequisite_manifest_digest) == 64
    assert len(error.owner_requirement_manifest_digest) == 64
    assert len(error.capability_requirement_manifest_digest) == 64
    assert len(error.error_digest) == 64
