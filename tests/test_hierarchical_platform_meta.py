from dataclasses import replace

from tests_support import model_role_for_test
import pytest

from noetrium_platform.research.experimentation.catalog.runtime import InMemoryExperimentationCatalog
from noetrium_platform.research.experimentation.experiment.api import ExperimentSpec
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.study import StudySpec
from noetrium_platform.foundation.portfolio.api import (
    ProgramSpec,
    ProjectCapabilityRequirement,
    ProjectConfigurationReference,
    ProjectIdentity,
    ProjectManifest,
    ProjectManifestDecodeError,
    ProjectManifestFacet,
    ProjectMethodRequirement,
    ProjectProviderBinding,
    ProjectSpec,
    ProjectToolProvenance,
    WorkspaceSpec,
    decode_project_manifest_bytes,
    decode_project_manifest_document,
    diff_project_manifest_facets,
    encode_project_manifest,
    project_manifest_document,
)
from noetrium_platform.foundation.portfolio.runtime import InMemoryPortfolioCatalog
from noetrium_platform.capabilities.environment.catalog.api import (
    EnvironmentAssignment,
    EnvironmentOverlay,
    EnvironmentSpec,
    ExecutionEnvironmentKind,
)
from noetrium_platform.capabilities.environment.catalog.runtime import ExecutionEnvironmentCatalog
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry


EXAMPLE_TEMPLATE_REVISION = "research-project-template.v1"


def _project_tool_provenance() -> ProjectToolProvenance:
    return ProjectToolProvenance("research", "1.0.0", "a" * 64)


def test_scope_portfolio_experiment_run_hierarchy_is_explicit():
    scopes = InMemoryScopeRegistry()
    portfolio = InMemoryPortfolioCatalog(scopes)
    portfolio.register_workspace(WorkspaceSpec("ws", "Workspace"))
    portfolio.register_program(ProgramSpec("prog", "ws", "Program"))
    portfolio.register_project(ProjectManifest(
        ProjectSpec(ProjectIdentity("paper", "1.0.0"), "prog", "Paper"),
        EXAMPLE_TEMPLATE_REVISION,
        _project_tool_provenance(),
        study_ids=("main",),
    ))

    experiments = InMemoryExperimentationCatalog(scopes)
    study = StudySpec("main", "paper", "Main", ("exp",))
    experiments.register_study(study)
    experiment = ExperimentSpec(
        experiment_id="exp",
        study_id="main",
        project_id="paper",
        participants=(),
        model_roles=(model_role_for_test(),),
        workload_digest="b" * 64,
        seed_digest="c" * 64,
        repetitions=1,
        trial_protocol_id="trial",
        trial_protocol_configuration_digest="a" * 64,
    )
    experiments.register_experiment(experiment)
    run = RunIdentity("run-1", "session-1", "trace-1")
    experiments.register_run("exp", run)

    assert [item.kind for item in scopes.ancestry(run.scope)] == [
        ScopeKind.RUN,
        ScopeKind.EXPERIMENT,
        ScopeKind.STUDY,
        ScopeKind.PROJECT,
        ScopeKind.PROGRAM,
        ScopeKind.WORKSPACE,
        ScopeKind.PLATFORM,
    ]


def test_environment_assignment_inherits_and_overlay_merges_without_copying_envs():
    scopes = InMemoryScopeRegistry()
    ws = ScopeIdentity(ScopeKind.WORKSPACE, "ws")
    project = ScopeIdentity(ScopeKind.PROJECT, "paper")
    study = ScopeIdentity(ScopeKind.STUDY, "study")
    scopes.register(ws, ScopeIdentity(ScopeKind.PLATFORM, "default"))
    program = ScopeIdentity(ScopeKind.PROGRAM, "prog")
    scopes.register(program, ws)
    scopes.register(project, program)
    scopes.register(study, project)

    catalog = ExecutionEnvironmentCatalog(scopes)
    base = EnvironmentSpec(
        "base",
        ExecutionEnvironmentKind.PYTHON,
        ws,
        requirements=(("python", "3.12"), ("torch", "2.6")),
    )
    sem = EnvironmentSpec(
        "sem",
        ExecutionEnvironmentKind.PYTHON,
        project,
        parent_spec_id="base",
        requirements=(("faiss", "1"),),
    )
    catalog.register_spec(base)
    catalog.register_spec(sem)
    catalog.assign(EnvironmentAssignment("method", "sem", project))
    catalog.register_overlay(EnvironmentOverlay("study-debug", "sem", study, requirements=(("debugpy", "1"),)))

    resolved = catalog.resolve("method", study)
    assert resolved.source_spec_ids == ("base", "sem")
    assert dict(resolved.requirements) == {"python": "3.12", "torch": "2.6", "faiss": "1", "debugpy": "1"}
    assert resolved.applied_overlay_ids == ("study-debug",)

def _project_manifest_fixture() -> ProjectManifest:
    return ProjectManifest(
        ProjectSpec(
            ProjectIdentity("example-project", "1.2.0"),
            "prog",
            "Example Project",
            tags=("example",),
        ),
        EXAMPLE_TEMPLATE_REVISION,
        _project_tool_provenance(),
        capability_requirements=(
            ProjectCapabilityRequirement(
                "logging",
                "observability.logging",
                "system",
                1,
                "1" * 64,
            ),
        ),
        provider_bindings=(
            ProjectProviderBinding(
                "logging-default", "logging", "reference.logging", "1.0.0", "3" * 64
            ),
        ),
        method_requirements=(ProjectMethodRequirement("baseline", "control", "4" * 64),),
        configuration_refs=(
            ProjectConfigurationReference("main-config", "configs/main.json", "2" * 64),
        ),
        study_ids=("main",),
    )


def test_project_manifest_is_strict_canonical_digest_bound_and_single_authority() -> None:
    from noetrium_platform.foundation.portfolio.project.api import ProjectIdentity as LeafProjectIdentity
    from noetrium_platform.foundation.portfolio.project.api import ProjectManifest as LeafProjectManifest

    manifest = _project_manifest_fixture()
    raw = encode_project_manifest(manifest)
    decoded = decode_project_manifest_bytes(raw)
    assert decoded == manifest
    assert decoded.semantic_digest == manifest.semantic_digest
    assert project_manifest_document(decoded)["semantic_digest"] == manifest.semantic_digest
    assert LeafProjectManifest is ProjectManifest
    assert LeafProjectIdentity is ProjectIdentity
    assert manifest.binding_inputs == manifest.capability_requirements


def test_project_manifest_digest_changes_with_project_configuration_truth() -> None:
    manifest = _project_manifest_fixture()
    changed = ProjectManifest(
        project=manifest.project,
        template_revision=manifest.template_revision,
        provenance=manifest.provenance,
        capability_requirements=manifest.capability_requirements,
        provider_bindings=manifest.provider_bindings,
        method_requirements=manifest.method_requirements,
        configuration_refs=(
            ProjectConfigurationReference("main-config", "configs/main.json", "3" * 64),
        ),
        study_ids=manifest.study_ids,
    )
    assert changed.semantic_digest != manifest.semantic_digest


def test_project_manifest_decoder_rejects_unknown_nonfinite_and_digest_drift() -> None:
    manifest = _project_manifest_fixture()
    document = dict(project_manifest_document(manifest))
    document["unknown"] = "value"
    with pytest.raises(ProjectManifestDecodeError, match="fields are not exact"):
        decode_project_manifest_document(document)

    for nonfinite in (float("nan"), float("inf"), float("-inf")):
        document = dict(project_manifest_document(manifest))
        document["unknown"] = nonfinite
        with pytest.raises(ProjectManifestDecodeError, match="non-finite"):
            decode_project_manifest_document(document)

    document = dict(project_manifest_document(manifest))
    document["schema"] = "noetrium.project-manifest.v999"
    with pytest.raises(ProjectManifestDecodeError, match="unsupported project manifest schema"):
        decode_project_manifest_document(document)

    document = dict(project_manifest_document(manifest))
    project = dict(document["project"])
    project["name"] = "Tampered"
    document["project"] = project
    with pytest.raises(ProjectManifestDecodeError, match="semantic digest mismatch"):
        decode_project_manifest_document(document)


def test_project_manifest_bytes_reject_duplicate_keys_and_noncanonical_identity() -> None:
    with pytest.raises(ProjectManifestDecodeError, match="duplicate JSON key"):
        decode_project_manifest_bytes(b'{"schema":"x","schema":"y"}')
    document = dict(project_manifest_document(_project_manifest_fixture()))
    project = dict(document["project"])
    identity = dict(project["identity"])
    identity["project_id"] = "Bad Project"
    project["identity"] = identity
    document["project"] = project
    with pytest.raises(ProjectManifestDecodeError, match="project_id"):
        decode_project_manifest_document(document)

def test_project_manifest_binds_template_tool_provenance_and_provider_choices() -> None:
    manifest = _project_manifest_fixture()
    document = project_manifest_document(manifest)
    assert document["template_revision"] == EXAMPLE_TEMPLATE_REVISION
    assert document["provenance"]["tool_id"] == "research"
    assert document["provenance"]["platform_artifact_sha256"] == "a" * 64
    assert document["provider_bindings"][0]["binding_id"] == "logging-default"
    assert document["schema"] == "noetrium.project-manifest.v2"
    assert document["method_requirements"][0]["implementation_digest"] == "4" * 64

    changed = ProjectManifest(
        project=manifest.project,
        template_revision=manifest.template_revision,
        provenance=ProjectToolProvenance("research", "1.0.0", "b" * 64),
        capability_requirements=manifest.capability_requirements,
        provider_bindings=manifest.provider_bindings,
        method_requirements=manifest.method_requirements,
        configuration_refs=manifest.configuration_refs,
        study_ids=manifest.study_ids,
    )
    assert changed.semantic_digest != manifest.semantic_digest


def test_project_manifest_records_product_owned_template_revision_without_owning_compatibility() -> None:
    manifest = _project_manifest_fixture()
    future_revision = "research-project-template.v999"
    future = ProjectManifest(
        project=manifest.project,
        template_revision=future_revision,
        provenance=manifest.provenance,
        capability_requirements=manifest.capability_requirements,
        provider_bindings=manifest.provider_bindings,
        method_requirements=manifest.method_requirements,
        configuration_refs=manifest.configuration_refs,
        study_ids=manifest.study_ids,
    )
    decoded = decode_project_manifest_bytes(encode_project_manifest(future))
    assert decoded.template_revision == future_revision
    assert decoded.semantic_digest == future.semantic_digest

    for invalid in ("", " research-project-template.v1", "research-project-template.v1 "):
        with pytest.raises(ValueError, match="template_revision"):
            ProjectManifest(
                project=manifest.project,
                template_revision=invalid,
                provenance=manifest.provenance,
            )


def test_project_manifest_rejects_duplicate_provider_binding_identity() -> None:
    manifest = _project_manifest_fixture()
    duplicate = ProjectProviderBinding(
        "logging-default", "logging", "another.logging", "1.0.0", "4" * 64
    )
    with pytest.raises(ValueError, match="provider binding ids must be unique"):
        ProjectManifest(
            project=manifest.project,
            template_revision=manifest.template_revision,
            provenance=manifest.provenance,
            capability_requirements=manifest.capability_requirements,
            provider_bindings=(*manifest.provider_bindings, duplicate),
        )


def test_project_manifest_bytes_require_exact_canonical_encoding() -> None:
    raw = encode_project_manifest(_project_manifest_fixture())
    assert decode_project_manifest_bytes(raw) == _project_manifest_fixture()
    with pytest.raises(ProjectManifestDecodeError, match="bytes are not canonical JSON"):
        decode_project_manifest_bytes(b" " + raw)

def test_project_manifest_identity_facets_expose_total_closure_without_claiming_scientific_equivalence() -> None:
    manifest = _project_manifest_fixture()
    facets = manifest.identity_facets
    assert manifest.semantic_digest == facets.total_closure_digest
    assert project_manifest_document(manifest)["semantic_digest"] == facets.total_closure_digest
    assert len({
        facets.project_spec_digest,
        facets.author_requirements_digest,
        facets.provider_bindings_digest,
        facets.scaffold_platform_provenance_digest,
        facets.total_closure_digest,
    }) == 5


def test_project_manifest_facet_diff_localizes_provider_binding_change() -> None:
    manifest = _project_manifest_fixture()
    binding = manifest.provider_bindings[0]
    changed = replace(
        manifest,
        provider_bindings=(replace(binding, configuration_digest="4" * 64),),
    )
    diff = diff_project_manifest_facets(manifest, changed)
    assert diff.changed_facets == (
        ProjectManifestFacet.PROVIDER_BINDINGS,
        ProjectManifestFacet.TOTAL_CLOSURE,
    )
    left, right = manifest.identity_facets, changed.identity_facets
    assert left.project_spec_digest == right.project_spec_digest
    assert left.author_requirements_digest == right.author_requirements_digest
    assert left.scaffold_platform_provenance_digest == right.scaffold_platform_provenance_digest


def test_project_manifest_facet_diff_localizes_author_provenance_and_project_changes() -> None:
    manifest = _project_manifest_fixture()

    author_changed = replace(
        manifest,
        configuration_refs=(
            replace(manifest.configuration_refs[0], content_sha256="4" * 64),
        ),
    )
    assert diff_project_manifest_facets(manifest, author_changed).changed_facets == (
        ProjectManifestFacet.AUTHOR_REQUIREMENTS,
        ProjectManifestFacet.TOTAL_CLOSURE,
    )

    provenance_changed = replace(
        manifest,
        provenance=ProjectToolProvenance("research", "1.0.0", "b" * 64),
    )
    assert diff_project_manifest_facets(manifest, provenance_changed).changed_facets == (
        ProjectManifestFacet.SCAFFOLD_PLATFORM_PROVENANCE,
        ProjectManifestFacet.TOTAL_CLOSURE,
    )

    project_changed = replace(manifest, project=replace(manifest.project, name="Renamed Project"))
    assert diff_project_manifest_facets(manifest, project_changed).changed_facets == (
        ProjectManifestFacet.PROJECT_SPEC,
        ProjectManifestFacet.TOTAL_CLOSURE,
    )

    assert diff_project_manifest_facets(manifest, manifest).changes == ()
