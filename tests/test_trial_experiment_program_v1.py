import pytest

from noetrium_platform.evidence.artifact.reference.api import ArtifactReference
from noetrium_platform.research.experimentation.api import (
    ResearchBindingContribution,
    ResearchBindingRequirements,
    ResearchCapabilityBinding,
    ResearchParticipantBinding,
    ResearchParticipantRequirement,
    compile_research_plan,
    resolve_research_requirements,
)
from noetrium_platform.research.experimentation.experiment.api import (
    ExperimentParticipantSpec,
    ExperimentTrialProtocolIdentity,
)
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkTaskSet,
    FactorLevelSpec,
    MeasurementDefinition,
    MeasurementProtocol,
    MeasurementRecord,
    MeasurementValue,
    MeasurementValueKind,
    ResearchRevision,
    ReplayLevel,
    ResearchStudyDefinition,
    StudyExecutionPolicy,
    StudyFactorSpec,
    TaskDefinition,
    TrialBudget,
    TrialExecutionReceipt,
)
from noetrium_platform.research.experimentation.study.runtime import (
    TrialExperimentProgramBinding,
    compile_trial_experiment_program,
)
from noetrium_platform.foundation.governance.architecture.api import BindingProof, CompositionSubject
from noetrium_platform.foundation.governance.system_registry.api import SystemIdentity
from noetrium_platform.capabilities.participant.api.project import (
    ParticipantProviderProfile,
    ParticipantRequirement,
    ProjectParticipantBinding,
)
from noetrium_platform.capabilities.participant.core.api.contracts import (
    ParticipantImplementationIdentity,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.foundation.kernel.kernel import InMemoryMachineJournal, Sha256Digest, canonical_digest
from noetrium_platform.foundation.portfolio.api import (
    ProjectCapabilityRequirement,
    ProjectIdentity,
    ProjectManifest,
    ProjectMethodRequirement,
    ProjectProviderBinding,
    ProjectSpec,
    ProjectToolProvenance,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


AGENT_CFG = "1" * 64
OFFLINE_CFG = "2" * 64
CUSTOM_CFG = "3" * 64

def _participant(role: str, kind: str, *, depends_on_roles: tuple[str, ...] = ()) -> ExperimentParticipantSpec:
    participant_id = role if kind == "method" else f"{kind}-impl"
    return ExperimentParticipantSpec(
        role,
        ParticipantImplementationIdentity(kind, participant_id, "1", "1", "1", "a" * 64),
        ParticipantSessionRuntimeIdentity(f"runtime.{kind}", "1", "1", "b" * 64),
        "d" * 64,
        depends_on_roles,
    )


def _benchmark() -> BenchmarkTaskSet:
    task = TaskDefinition("task-1", "1", "generic", "task.v1", "a" * 64)
    return BenchmarkTaskSet("benchmark", "1", "b" * 64, "task.v1", (task,))


def _measurements() -> MeasurementProtocol:
    return MeasurementProtocol(
        "trial-measurements",
        (
            MeasurementDefinition("score", "scalar-v1", MeasurementValueKind.SCALAR),
            MeasurementDefinition("trace", "trace-v1", MeasurementValueKind.STRUCTURED),
        ),
    )


def _manifest(protocol_identity, participants) -> ProjectManifest:
    requirement = ProjectCapabilityRequirement(
        "trial-provider", "experimentation", "trial", 1, "4" * 64
    )
    provider_id = f"{protocol_identity.protocol_id}.provider"
    return ProjectManifest(
        ProjectSpec(ProjectIdentity("project", "1"), "program", "Project"),
        "template-1",
        ProjectToolProvenance("tool", "1", "5" * 64),
        capability_requirements=(requirement,),
        provider_bindings=(
            ProjectProviderBinding(
                "trial-binding", "trial-provider", provider_id, "1", "6" * 64
            ),
        ),
        method_requirements=tuple(
            ProjectMethodRequirement("method", row.role, row.implementation.digest())
            for row in participants
        ),
        study_ids=("study",),
    )


def _subject(manifest: ProjectManifest) -> CompositionSubject:
    return CompositionSubject.project_subject(
        manifest.identity.project_id, manifest.identity.version
    )


def _trial_capability_binding(manifest, resolution) -> ResearchCapabilityBinding:
    requirement = resolution.capability_requirement("trial-provider")
    provider = manifest.provider_bindings[0]
    proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("experimentation")),
        subject=_subject(manifest),
        requirement_digest=Sha256Digest(canonical_digest(requirement)),
        provider_identity=provider.provider_identity,
        provider_profile_digest=Sha256Digest("7" * 64),
        binding_generation="generation-1",
    )
    return ResearchCapabilityBinding("trial-provider", proof)


def _participant_proof_binding(manifest, row) -> ResearchParticipantBinding:
    requirement = ParticipantRequirement(
        row.role, row.implementation, row.configuration_digest
    )
    profile = ParticipantProviderProfile(
        f"participant.{row.role}", (row.implementation.kind,)
    )
    domain = ProjectParticipantBinding.from_runtime(
        requirement, profile, row.runtime_binding()
    )
    proof = BindingProof(
        owner=CompositionSubject.system_subject(SystemIdentity("participant")),
        subject=_subject(manifest),
        requirement_digest=Sha256Digest(domain.requirement_digest),
        provider_identity=profile.provider_id,
        provider_profile_digest=Sha256Digest(profile.digest()),
        binding_generation=f"participant-{row.runtime.digest()}",
    )
    return ResearchParticipantBinding(row.role, domain, proof)


def _plan(protocol_identity, participants, revision):
    requirements = ResearchBindingRequirements(
        "trial-provider",
        participants=tuple(
            ResearchParticipantRequirement(
                row.role, row.implementation.kind, "method", row.role,
                depends_on_roles=row.depends_on_roles,
            )
            for row in participants
        ),
    )
    definition = ResearchStudyDefinition(
        "project", "experiment", "study", "workload",
        (
            StudyFactorSpec(
                "mode",
                (
                    FactorLevelSpec("control", "control", control=True),
                    FactorLevelSpec("candidate", "candidate"),
                ),
            ),
        ),
        ("seed-1",), 1, _measurements(), _benchmark(), None,
        requirements, protocol_identity, revision,
        StudyExecutionPolicy.serial_shared_v1(
            trial_budget=TrialBudget("standard", max_steps=12, max_seconds=180.0),
            replay_level=ReplayLevel.EXACT,
            repetition_timeout_seconds=3600.0,
        ),
    )
    manifest = _manifest(protocol_identity, participants)
    resolution = resolve_research_requirements(definition, manifest)
    binding = ResearchBindingContribution(
        resolution.resolution_digest,
        (_trial_capability_binding(manifest, resolution),),
        tuple(_participant_proof_binding(manifest, row) for row in participants),
    )
    return compile_research_plan(definition, resolution, binding)

def _record(request, measurement_id: str, value: MeasurementValue, *, producer: str) -> MeasurementRecord:
    definition = request.measurement_protocol.definition(measurement_id)
    return MeasurementRecord(
        request.project_id,
        request.assignment.study_id,
        request.run_id,
        request.assignment.assignment_digest,
        request.assignment.variant_id,
        producer,
        "e" * 64,
        measurement_id,
        definition.schema_id,
        definition.semantic_contract_digest,
        request.measurement_protocol.semantic_digest,
        value,
        "t0",
        request.intervention,
        request.revision,
    )


class AgentProvider:
    protocol_identity = ExperimentTrialProtocolIdentity("trial.agent", AGENT_CFG)

    def run_trial(self, request):
        return _receipt(request, "agent", 1.0)


class OfflineProvider:
    protocol_identity = ExperimentTrialProtocolIdentity("trial.offline", OFFLINE_CFG)

    def run_trial(self, request):
        assert request.participant_schedule.applicable is False
        assert request.revision.applicable is False
        return _receipt(request, "offline", 0.5)


class CustomProvider:
    protocol_identity = ExperimentTrialProtocolIdentity("trial.custom", CUSTOM_CFG)

    def run_trial(self, request):
        return _receipt(request, "custom", 0.75)


def _receipt(request, label: str, score: float) -> TrialExecutionReceipt:
    records = (
        _record(request, "score", MeasurementValue(MeasurementValueKind.SCALAR, scalar=score), producer=label),
        _record(request, "trace", MeasurementValue(MeasurementValueKind.STRUCTURED, structured={"loop": label}), producer=label),
    )
    evidence = ArtifactReference(
        f"evidence-{label}",
        ScopeIdentity(ScopeKind.RUN, request.run_id),
        f"artifact-{label}",
        1,
    )
    return TrialExecutionReceipt(
        request.request_digest,
        request.assignment.assignment_digest,
        records,
        (evidence,),
    )


@pytest.mark.parametrize(
    ("provider", "participants", "revision"),
    (
        (AgentProvider(), (_participant("method", "method"),), ResearchRevision("r", "c" * 64)),
        (OfflineProvider(), (), None),
        (
            CustomProvider(),
            (
                _participant("actor", "actor"),
                _participant("judge", "evaluator", depends_on_roles=("actor",)),
            ),
            ResearchRevision("r", "d" * 64),
        ),
    ),
)
def test_structurally_distinct_trials_share_one_neutral_lifecycle(provider, participants, revision) -> None:
    plan = _plan(provider.protocol_identity, participants, revision)
    report = TrialExperimentProgramBinding(compile_trial_experiment_program(plan), provider).execute(run_id="run-1")
    assert len(report.trial_receipt_digests) == len(plan.experiment_plan.assignments)
    assert len(report.records) == len(plan.experiment_plan.assignments) * 2
    assert {row.measurement_id for row in report.records} == {"score", "trace"}


def test_trial_experiment_program_rejects_provider_protocol_drift() -> None:
    plan = _plan(AgentProvider.protocol_identity, (), None)
    with pytest.raises(ValueError, match="protocol identity"):
        TrialExperimentProgramBinding(compile_trial_experiment_program(plan), OfflineProvider()).execute(run_id="run-1")


class LooseEvidenceProvider:
    protocol_identity = ExperimentTrialProtocolIdentity("trial.loose", "4" * 64)

    def run_trial(self, request):
        record = _record(
            request, "score",
            MeasurementValue(MeasurementValueKind.SCALAR, scalar=0.5),
            producer="loose",
        )
        trace = _record(
            request, "trace",
            MeasurementValue(MeasurementValueKind.STRUCTURED, structured={"loop": "loose"}),
            producer="loose",
        )
        return TrialExecutionReceipt(
            request.request_digest,
            request.assignment.assignment_digest,
            (record, trace),
            ("evidence:loose",),
        )


def test_trial_receipt_rejects_loose_string_evidence() -> None:
    plan = _plan(LooseEvidenceProvider.protocol_identity, (), None)
    with pytest.raises(TypeError, match="ArtifactReference"):
        TrialExperimentProgramBinding(compile_trial_experiment_program(plan), LooseEvidenceProvider()).execute(run_id="run-1")

def test_trial_experiment_program_resumes_from_machine_journal() -> None:
    provider = AgentProvider()
    plan = _plan(
        provider.protocol_identity,
        (_participant("method", "method"),),
        ResearchRevision("r", "c" * 64),
    )
    compiled = compile_trial_experiment_program(plan)
    binding = TrialExperimentProgramBinding(compiled, provider)
    journal = InMemoryMachineJournal()

    first = binding.open_session(run_id="run-resume", journal=journal)
    first.start(
        compiled.initial_data("run-resume"),
        command_id=f"{first.machine_id}:start",
    )
    first.step(
        {"source": "partial-test"},
        command_id=f"{first.machine_id}:one-assignment",
    )
    assert first.data["assignment_cursor"] == 1

    report = binding.execute(run_id="run-resume", journal=journal)
    assert len(report.trial_receipt_digests) == len(
        plan.experiment_plan.assignments
    )
    assert len(report.records) == (
        len(plan.experiment_plan.assignments)
        * len(plan.measurement_protocol.definitions)
    )
