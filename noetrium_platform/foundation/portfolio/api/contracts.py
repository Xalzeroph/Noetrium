from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import re
from typing import cast

from noetrium_platform.foundation.kernel.kernel import (
    CanonicalDecodingError,
    CanonicalDecodingFailureKind,
    CanonicalEncodingError,
    JsonDocument,
    JsonInput,
    require_sha256,
    strict_finite_json_bytes,
    strict_finite_json_digest,
    strict_json_loads,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


PROJECT_MANIFEST_SCHEMA = "noetrium.project-manifest.v2"
_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*")


class ProjectManifestDecodeError(ValueError):
    """A project manifest is malformed, non-canonical, or digest-inconsistent."""


_PROJECT_JSON_DECODE_MESSAGES = {
    CanonicalDecodingFailureKind.BOM: "project manifest JSON contains forbidden UTF-8 BOM",
    CanonicalDecodingFailureKind.DUPLICATE_KEY: "project manifest JSON contains duplicate JSON key",
    CanonicalDecodingFailureKind.NON_FINITE: "project manifest JSON contains forbidden non-finite value",
    CanonicalDecodingFailureKind.SYNTAX: "project manifest JSON cannot be decoded",
    CanonicalDecodingFailureKind.DOMAIN: "project manifest JSON violates strict finite JSON domain",
}


def _require_token(value: str, field: str) -> None:
    if not _TOKEN.fullmatch(value):
        raise ValueError(f"{field} must be a canonical lowercase token")


def _require_text(value: str, field: str) -> None:
    if not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be non-empty canonical text")


def _require_sha256(value: str, field: str) -> None:
    require_sha256(value, field)


@dataclass(frozen=True, slots=True, order=True)
class ProjectIdentity:
    """Stable project identity reused by Portfolio, Scope, and composition inputs."""

    project_id: str
    version: str

    def __post_init__(self) -> None:
        _require_token(self.project_id, "project_id")
        if not _VERSION.fullmatch(self.version):
            raise ValueError("project version is not canonical")

    @property
    def key(self) -> str:
        return f"{self.project_id}@{self.version}"

    @property
    def scope(self) -> ScopeIdentity:
        return ScopeIdentity(ScopeKind.PROJECT, self.project_id)


@dataclass(frozen=True, slots=True)
class WorkspaceSpec:
    workspace_id: str
    name: str
    description: str = ""

    def __post_init__(self) -> None:
        _require_token(self.workspace_id, "workspace_id")
        _require_text(self.name, "workspace name")

    @property
    def scope(self) -> ScopeIdentity:
        return ScopeIdentity(ScopeKind.WORKSPACE, self.workspace_id)


@dataclass(frozen=True, slots=True)
class ProgramSpec:
    program_id: str
    workspace_id: str
    name: str
    description: str = ""

    def __post_init__(self) -> None:
        _require_token(self.program_id, "program_id")
        _require_token(self.workspace_id, "workspace_id")
        _require_text(self.name, "program name")

    @property
    def scope(self) -> ScopeIdentity:
        return ScopeIdentity(ScopeKind.PROGRAM, self.program_id)


@dataclass(frozen=True, slots=True)
class ProjectSpec:
    identity: ProjectIdentity
    program_id: str
    name: str
    description: str = ""
    tags: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_token(self.program_id, "program_id")
        _require_text(self.name, "project name")
        if len(self.tags) != len(set(self.tags)):
            raise ValueError("project tags must be unique")
        for tag in self.tags:
            _require_token(tag, "project tag")

    @property
    def project_id(self) -> str:
        return self.identity.project_id

    @property
    def scope(self) -> ScopeIdentity:
        return self.identity.scope


class ProjectRequirementCardinality(StrEnum):
    EXACTLY_ONE = "exactly_one"
    ONE_OR_MORE = "one_or_more"


class ProjectManifestFacet(StrEnum):
    """Explicit ProjectManifest identity/equality dimensions; none is Run/scientific validity."""

    PROJECT_SPEC = "project_spec"
    AUTHOR_REQUIREMENTS = "author_requirements"
    PROVIDER_BINDINGS = "provider_bindings"
    SCAFFOLD_PLATFORM_PROVENANCE = "scaffold_platform_provenance"
    TOTAL_CLOSURE = "total_closure"


@dataclass(frozen=True, slots=True)
class ProjectManifestIdentityFacets:
    project_spec_digest: str
    author_requirements_digest: str
    provider_bindings_digest: str
    scaffold_platform_provenance_digest: str
    total_closure_digest: str

    def __post_init__(self) -> None:
        for field, value in (
            ("project_spec_digest", self.project_spec_digest),
            ("author_requirements_digest", self.author_requirements_digest),
            ("provider_bindings_digest", self.provider_bindings_digest),
            ("scaffold_platform_provenance_digest", self.scaffold_platform_provenance_digest),
            ("total_closure_digest", self.total_closure_digest),
        ):
            require_sha256(value, field)

    def digest_for(self, facet: ProjectManifestFacet) -> str:
        if facet is ProjectManifestFacet.PROJECT_SPEC:
            return self.project_spec_digest
        if facet is ProjectManifestFacet.AUTHOR_REQUIREMENTS:
            return self.author_requirements_digest
        if facet is ProjectManifestFacet.PROVIDER_BINDINGS:
            return self.provider_bindings_digest
        if facet is ProjectManifestFacet.SCAFFOLD_PLATFORM_PROVENANCE:
            return self.scaffold_platform_provenance_digest
        if facet is ProjectManifestFacet.TOTAL_CLOSURE:
            return self.total_closure_digest
        raise ValueError(f"unsupported ProjectManifest facet: {facet!r}")


@dataclass(frozen=True, slots=True)
class ProjectManifestFacetChange:
    facet: ProjectManifestFacet
    before_digest: str
    after_digest: str

    def __post_init__(self) -> None:
        require_sha256(self.before_digest, "before_digest")
        require_sha256(self.after_digest, "after_digest")
        if self.before_digest == self.after_digest:
            raise ValueError("facet change requires distinct digests")


@dataclass(frozen=True, slots=True)
class ProjectManifestFacetDiff:
    before_total_closure_digest: str
    after_total_closure_digest: str
    changes: tuple[ProjectManifestFacetChange, ...]

    def __post_init__(self) -> None:
        require_sha256(self.before_total_closure_digest, "before_total_closure_digest")
        require_sha256(self.after_total_closure_digest, "after_total_closure_digest")
        facets = tuple(change.facet for change in self.changes)
        if len(facets) != len(set(facets)):
            raise ValueError("ProjectManifest facet diff contains duplicate facets")
        expected = tuple(facet for facet in ProjectManifestFacet if facet in set(facets))
        if facets != expected:
            raise ValueError("ProjectManifest facet changes must be in canonical facet order")
        closure_changed = self.before_total_closure_digest != self.after_total_closure_digest
        closure_reported = ProjectManifestFacet.TOTAL_CLOSURE in facets
        if closure_changed != closure_reported:
            raise ValueError("ProjectManifest total-closure change must match the TOTAL_CLOSURE facet")
        if not closure_changed and facets:
            raise ValueError("ProjectManifest local facet changes require a changed total closure")

    @property
    def changed_facets(self) -> tuple[ProjectManifestFacet, ...]:
        return tuple(change.facet for change in self.changes)


@dataclass(frozen=True, slots=True, order=True)
class ProjectCapabilityRequirement:
    """Platform capability binding input declared by a project, not a provider choice."""

    requirement_id: str
    namespace: str
    name: str
    major_version: int
    interface_digest: str
    cardinality: ProjectRequirementCardinality = ProjectRequirementCardinality.EXACTLY_ONE
    optional: bool = False

    def __post_init__(self) -> None:
        _require_token(self.requirement_id, "requirement_id")
        _require_token(self.namespace, "capability namespace")
        _require_token(self.name, "capability name")
        if type(self.major_version) is not int or self.major_version <= 0:
            raise ValueError("capability major_version must be a positive integer")
        _require_sha256(self.interface_digest, "capability interface_digest")
        if type(self.optional) is not bool:
            raise ValueError("capability optional must be boolean")

    @property
    def capability_key(self) -> str:
        return f"{self.namespace}.{self.name}.v{self.major_version}"


@dataclass(frozen=True, slots=True, order=True)
class ProjectMethodRequirement:
    """Project-owned scientific/method requirement, separate from Platform capability truth."""

    method_id: str
    treatment_id: str
    implementation_digest: str

    def __post_init__(self) -> None:
        _require_token(self.method_id, "method_id")
        _require_token(self.treatment_id, "treatment_id")
        _require_sha256(self.implementation_digest, "method implementation_digest")


@dataclass(frozen=True, slots=True, order=True)
class ProjectConfigurationReference:
    """Content-addressed project-owned configuration fact."""

    configuration_id: str
    artifact_ref: str
    content_sha256: str

    def __post_init__(self) -> None:
        _require_token(self.configuration_id, "configuration_id")
        _require_text(self.artifact_ref, "configuration artifact_ref")
        _require_sha256(self.content_sha256, "configuration content_sha256")


@dataclass(frozen=True, slots=True, order=True)
class ProjectToolProvenance:
    """Installed Platform/tool identity that created or last rewrote the manifest."""

    tool_id: str
    tool_version: str
    platform_artifact_sha256: str

    def __post_init__(self) -> None:
        _require_token(self.tool_id, "tool_id")
        if not _VERSION.fullmatch(self.tool_version):
            raise ValueError("tool_version is not canonical")
        _require_sha256(self.platform_artifact_sha256, "platform_artifact_sha256")


@dataclass(frozen=True, slots=True, order=True)
class ProjectProviderBinding:
    """Explicit provider choice bound to one declared capability requirement."""

    binding_id: str
    requirement_id: str
    provider_identity: str
    provider_version: str
    configuration_digest: str

    def __post_init__(self) -> None:
        _require_token(self.binding_id, "binding_id")
        _require_token(self.requirement_id, "binding requirement_id")
        _require_text(self.provider_identity, "provider_identity")
        if not _VERSION.fullmatch(self.provider_version):
            raise ValueError("provider_version is not canonical")
        _require_sha256(self.configuration_digest, "provider configuration_digest")


@dataclass(frozen=True, slots=True)
class ProjectManifest:
    """Canonical project manifest authority for Portfolio and downstream onboarding."""

    project: ProjectSpec
    template_revision: str
    provenance: ProjectToolProvenance
    capability_requirements: tuple[ProjectCapabilityRequirement, ...] = ()
    provider_bindings: tuple[ProjectProviderBinding, ...] = ()
    method_requirements: tuple[ProjectMethodRequirement, ...] = ()
    configuration_refs: tuple[ProjectConfigurationReference, ...] = ()
    study_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        _require_text(self.template_revision, "template_revision")
        requirement_ids = tuple(row.requirement_id for row in self.capability_requirements)
        if len(requirement_ids) != len(set(requirement_ids)):
            raise ValueError("project capability requirement ids must be unique")
        requirement_by_id = {row.requirement_id: row for row in self.capability_requirements}
        binding_ids = tuple(row.binding_id for row in self.provider_bindings)
        if len(binding_ids) != len(set(binding_ids)):
            raise ValueError("project provider binding ids must be unique")
        binding_keys = tuple((row.requirement_id, row.provider_identity) for row in self.provider_bindings)
        if len(binding_keys) != len(set(binding_keys)):
            raise ValueError("project provider bindings must be unique")
        binding_counts: dict[str, int] = {}
        for binding in self.provider_bindings:
            requirement = requirement_by_id.get(binding.requirement_id)
            if requirement is None:
                raise ValueError("project provider binding names an unknown requirement")
            binding_counts[binding.requirement_id] = binding_counts.get(binding.requirement_id, 0) + 1
            if (
                requirement.cardinality is ProjectRequirementCardinality.EXACTLY_ONE
                and binding_counts[binding.requirement_id] > 1
            ):
                raise ValueError("exactly-one capability has multiple provider bindings")
        method_keys = tuple((row.method_id, row.treatment_id) for row in self.method_requirements)
        if len(method_keys) != len(set(method_keys)):
            raise ValueError("project method requirements must be unique")
        config_ids = tuple(row.configuration_id for row in self.configuration_refs)
        if len(config_ids) != len(set(config_ids)):
            raise ValueError("project configuration ids must be unique")
        if len(self.study_ids) != len(set(self.study_ids)):
            raise ValueError("project study ids must be unique")
        for study_id in self.study_ids:
            _require_token(study_id, "study_id")

    @property
    def identity(self) -> ProjectIdentity:
        return self.project.identity

    @property
    def binding_inputs(self) -> tuple[ProjectCapabilityRequirement, ...]:
        """Explicit capability inputs consumed by composition/doctor; no ambient lookup."""
        return self.capability_requirements

    @property
    def identity_facets(self) -> "ProjectManifestIdentityFacets":
        return project_manifest_identity_facets(self)

    @property
    def semantic_digest(self) -> str:
        """Complete manifest closure digest; not a Study/Run/scientific-equivalence identity."""
        return self.identity_facets.total_closure_digest


def _project_spec_payload(manifest: ProjectManifest) -> dict[str, JsonInput]:
    project = manifest.project
    return {
        "identity": {"project_id": project.identity.project_id, "version": project.identity.version},
        "program_id": project.program_id,
        "name": project.name,
        "description": project.description,
        "tags": project.tags,
    }


def _author_requirements_payload(manifest: ProjectManifest) -> dict[str, JsonInput]:
    return {
        "capability_requirements": tuple(
            {
                "requirement_id": row.requirement_id, "namespace": row.namespace, "name": row.name,
                "major_version": row.major_version, "interface_digest": row.interface_digest,
                "cardinality": row.cardinality.value, "optional": row.optional,
            }
            for row in manifest.capability_requirements
        ),
        "method_requirements": tuple(
            {
                "method_id": row.method_id,
                "treatment_id": row.treatment_id,
                "implementation_digest": row.implementation_digest,
            }
            for row in manifest.method_requirements
        ),
        "configuration_refs": tuple(
            {
                "configuration_id": row.configuration_id, "artifact_ref": row.artifact_ref,
                "content_sha256": row.content_sha256,
            }
            for row in manifest.configuration_refs
        ),
        "study_ids": manifest.study_ids,
    }


def _provider_bindings_payload(manifest: ProjectManifest) -> dict[str, JsonInput]:
    return {
        "provider_bindings": tuple(
            {
                "binding_id": row.binding_id, "requirement_id": row.requirement_id,
                "provider_identity": row.provider_identity, "provider_version": row.provider_version,
                "configuration_digest": row.configuration_digest,
            }
            for row in manifest.provider_bindings
        )
    }


def _scaffold_platform_provenance_payload(manifest: ProjectManifest) -> dict[str, JsonInput]:
    return {
        "template_revision": manifest.template_revision,
        "provenance": {
            "tool_id": manifest.provenance.tool_id,
            "tool_version": manifest.provenance.tool_version,
            "platform_artifact_sha256": manifest.provenance.platform_artifact_sha256,
        },
    }


def _project_manifest_payload(manifest: ProjectManifest) -> dict[str, JsonInput]:
    return {
        **_scaffold_platform_provenance_payload(manifest),
        "project": _project_spec_payload(manifest),
        **_author_requirements_payload(manifest),
        **_provider_bindings_payload(manifest),
    }


def project_manifest_identity_facets(manifest: ProjectManifest) -> ProjectManifestIdentityFacets:
    return ProjectManifestIdentityFacets(
        project_spec_digest=strict_finite_json_digest(_project_spec_payload(manifest)),
        author_requirements_digest=strict_finite_json_digest(_author_requirements_payload(manifest)),
        provider_bindings_digest=strict_finite_json_digest(_provider_bindings_payload(manifest)),
        scaffold_platform_provenance_digest=strict_finite_json_digest(
            _scaffold_platform_provenance_payload(manifest)
        ),
        total_closure_digest=strict_finite_json_digest(_project_manifest_payload(manifest)),
    )


def diff_project_manifest_facets(
    before: ProjectManifest, after: ProjectManifest
) -> ProjectManifestFacetDiff:
    left = project_manifest_identity_facets(before)
    right = project_manifest_identity_facets(after)
    changes = tuple(
        ProjectManifestFacetChange(facet, left.digest_for(facet), right.digest_for(facet))
        for facet in ProjectManifestFacet
        if left.digest_for(facet) != right.digest_for(facet)
    )
    return ProjectManifestFacetDiff(left.total_closure_digest, right.total_closure_digest, changes)


def project_manifest_document(manifest: ProjectManifest) -> JsonDocument:
    payload = _project_manifest_payload(manifest)
    return {
        "schema": PROJECT_MANIFEST_SCHEMA,
        "semantic_digest": strict_finite_json_digest(payload),
        **payload,
    }


def encode_project_manifest(manifest: ProjectManifest) -> bytes:
    """Encode canonical finite JSON bytes including a semantic digest binding."""
    return strict_finite_json_bytes(project_manifest_document(manifest))


def decode_project_manifest_bytes(raw: bytes) -> ProjectManifest:
    """Decode strict UTF-8 JSON and verify exact schema plus semantic digest."""
    if not isinstance(raw, bytes):
        raise ProjectManifestDecodeError("project manifest input must be bytes")
    try:
        value = strict_json_loads(raw)
    except CanonicalDecodingError as exc:
        raise ProjectManifestDecodeError(_PROJECT_JSON_DECODE_MESSAGES[exc.kind]) from exc
    if not isinstance(value, dict):
        raise ProjectManifestDecodeError("project manifest root must be an object")
    document = cast(JsonDocument, value)
    try:
        if raw != strict_finite_json_bytes(document):
            raise ProjectManifestDecodeError("project manifest bytes are not canonical JSON")
    except CanonicalEncodingError as exc:
        raise ProjectManifestDecodeError(str(exc)) from exc
    return decode_project_manifest_document(document)


def _object(value: JsonInput, field: str) -> dict[str, JsonInput]:
    if not isinstance(value, dict):
        raise ProjectManifestDecodeError(f"{field} must be an object")
    return value


def _array(value: JsonInput, field: str) -> tuple[JsonInput, ...]:
    if not isinstance(value, (list, tuple)):
        raise ProjectManifestDecodeError(f"{field} must be an array")
    return tuple(value)


def _text(value: JsonInput, field: str) -> str:
    if type(value) is not str:
        raise ProjectManifestDecodeError(f"{field} must be a string")
    return value


def _bool(value: JsonInput, field: str) -> bool:
    if type(value) is not bool:
        raise ProjectManifestDecodeError(f"{field} must be boolean")
    return value


def _int(value: JsonInput, field: str) -> int:
    if type(value) is not int:
        raise ProjectManifestDecodeError(f"{field} must be an integer")
    return value


def _exact_fields(value: dict[str, JsonInput], expected: frozenset[str], field: str) -> None:
    if frozenset(value) != expected:
        raise ProjectManifestDecodeError(f"{field} fields are not exact")


def _decode_project_manifest_document(document: JsonDocument) -> ProjectManifest:
    """Decode an already parsed manifest while preserving finite/canonical semantics."""
    try:
        strict_finite_json_bytes(document)
    except CanonicalEncodingError as exc:
        raise ProjectManifestDecodeError(str(exc)) from exc
    if not isinstance(document, dict):
        document = dict(document)
    root = cast(dict[str, JsonInput], document)
    _exact_fields(
        root,
        frozenset({
            "schema", "semantic_digest", "template_revision", "provenance", "project",
            "capability_requirements", "provider_bindings", "method_requirements",
            "configuration_refs", "study_ids",
        }),
        "project manifest",
    )
    if _text(root["schema"], "schema") != PROJECT_MANIFEST_SCHEMA:
        raise ProjectManifestDecodeError("unsupported project manifest schema")
    expected_digest = _text(root["semantic_digest"], "semantic_digest")
    try:
        require_sha256(expected_digest, "semantic_digest")
    except ValueError as exc:
        raise ProjectManifestDecodeError(str(exc)) from exc
    template_revision = _text(root["template_revision"], "template_revision")
    provenance_raw = _object(root["provenance"], "provenance")
    _exact_fields(
        provenance_raw,
        frozenset({"tool_id", "tool_version", "platform_artifact_sha256"}),
        "provenance",
    )
    provenance = ProjectToolProvenance(
        _text(provenance_raw["tool_id"], "provenance.tool_id"),
        _text(provenance_raw["tool_version"], "provenance.tool_version"),
        _text(provenance_raw["platform_artifact_sha256"], "provenance.platform_artifact_sha256"),
    )

    project_raw = _object(root["project"], "project")
    _exact_fields(project_raw, frozenset({"identity", "program_id", "name", "description", "tags"}), "project")
    identity_raw = _object(project_raw["identity"], "project.identity")
    _exact_fields(identity_raw, frozenset({"project_id", "version"}), "project.identity")
    identity = ProjectIdentity(
        _text(identity_raw["project_id"], "project.identity.project_id"),
        _text(identity_raw["version"], "project.identity.version"),
    )
    tags = tuple(_text(item, "project.tags[]") for item in _array(project_raw["tags"], "project.tags"))
    project = ProjectSpec(
        identity,
        _text(project_raw["program_id"], "project.program_id"),
        _text(project_raw["name"], "project.name"),
        _text(project_raw["description"], "project.description"),
        tags,
    )

    capabilities: list[ProjectCapabilityRequirement] = []
    cap_fields = frozenset({
        "requirement_id", "namespace", "name", "major_version", "interface_digest", "cardinality", "optional",
    })
    for item in _array(root["capability_requirements"], "capability_requirements"):
        row = _object(item, "capability_requirements[]")
        _exact_fields(row, cap_fields, "capability_requirements[]")
        try:
            cardinality = ProjectRequirementCardinality(_text(row["cardinality"], "capability cardinality"))
        except ValueError as exc:
            raise ProjectManifestDecodeError("invalid capability cardinality") from exc
        capabilities.append(ProjectCapabilityRequirement(
            _text(row["requirement_id"], "capability requirement_id"),
            _text(row["namespace"], "capability namespace"),
            _text(row["name"], "capability name"),
            _int(row["major_version"], "capability major_version"),
            _text(row["interface_digest"], "capability interface_digest"),
            cardinality,
            _bool(row["optional"], "capability optional"),
        ))

    provider_bindings: list[ProjectProviderBinding] = []
    binding_fields = frozenset({
        "binding_id", "requirement_id", "provider_identity", "provider_version", "configuration_digest",
    })
    for item in _array(root["provider_bindings"], "provider_bindings"):
        row = _object(item, "provider_bindings[]")
        _exact_fields(row, binding_fields, "provider_bindings[]")
        provider_bindings.append(ProjectProviderBinding(
            _text(row["binding_id"], "binding_id"),
            _text(row["requirement_id"], "binding requirement_id"),
            _text(row["provider_identity"], "provider_identity"),
            _text(row["provider_version"], "provider_version"),
            _text(row["configuration_digest"], "provider configuration_digest"),
        ))

    methods: list[ProjectMethodRequirement] = []
    for item in _array(root["method_requirements"], "method_requirements"):
        row = _object(item, "method_requirements[]")
        _exact_fields(
            row,
            frozenset({"method_id", "treatment_id", "implementation_digest"}),
            "method_requirements[]",
        )
        methods.append(ProjectMethodRequirement(
            _text(row["method_id"], "method_id"),
            _text(row["treatment_id"], "treatment_id"),
            _text(row["implementation_digest"], "method implementation_digest"),
        ))

    configs: list[ProjectConfigurationReference] = []
    for item in _array(root["configuration_refs"], "configuration_refs"):
        row = _object(item, "configuration_refs[]")
        _exact_fields(row, frozenset({"configuration_id", "artifact_ref", "content_sha256"}), "configuration_refs[]")
        configs.append(ProjectConfigurationReference(
            _text(row["configuration_id"], "configuration_id"),
            _text(row["artifact_ref"], "artifact_ref"),
            _text(row["content_sha256"], "content_sha256"),
        ))

    studies = tuple(_text(item, "study_ids[]") for item in _array(root["study_ids"], "study_ids"))
    manifest = ProjectManifest(
        project, template_revision, provenance, tuple(capabilities), tuple(provider_bindings),
        tuple(methods), tuple(configs), studies,
    )
    if manifest.semantic_digest != expected_digest:
        raise ProjectManifestDecodeError("project manifest semantic digest mismatch")
    return manifest


def decode_project_manifest_document(document: JsonDocument) -> ProjectManifest:
    """Fail-closed public decoder with one typed error surface."""
    try:
        return _decode_project_manifest_document(document)
    except ProjectManifestDecodeError:
        raise
    except (KeyError, TypeError, ValueError) as exc:
        raise ProjectManifestDecodeError(str(exc)) from exc


__all__ = [
    "PROJECT_MANIFEST_SCHEMA",
    "ProgramSpec",
    "ProjectCapabilityRequirement",
    "ProjectConfigurationReference",
    "ProjectIdentity",
    "ProjectManifest",
    "ProjectManifestDecodeError",
    "ProjectManifestFacet",
    "ProjectManifestFacetChange",
    "ProjectManifestFacetDiff",
    "ProjectManifestIdentityFacets",
    "ProjectProviderBinding",
    "ProjectMethodRequirement",
    "ProjectRequirementCardinality",
    "ProjectSpec",
    "ProjectToolProvenance",
    "WorkspaceSpec",
    "decode_project_manifest_bytes",
    "decode_project_manifest_document",
    "diff_project_manifest_facets",
    "encode_project_manifest",
    "project_manifest_document",
    "project_manifest_identity_facets",
]
