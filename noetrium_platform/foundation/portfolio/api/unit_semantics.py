"""Unit-native project manifest semantics.

All frozen project declarations share the same NoetriumUnit carrier. Runtime
catalogs, bindings, revisions and receipts may reference these Units but never
re-materialize parallel static dataclasses.
"""
from __future__ import annotations

from enum import StrEnum
import re

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.foundation.api import ScopeKind, scope_unit


_TOKEN = re.compile(r"[a-z][a-z0-9_.-]*")
_VERSION = re.compile(r"[0-9A-Za-z][0-9A-Za-z._+-]*")

PROJECT_MANIFEST_TRAIT = "noetrium.project-manifest"
PROJECT_PROVENANCE_TRAIT = "noetrium.project-provenance"
PROJECT_CAPABILITY_REQUIREMENT_TRAIT = "noetrium.project-capability-requirement"
PROJECT_METHOD_REQUIREMENT_TRAIT = "noetrium.project-method-requirement"
PROJECT_CONFIGURATION_REFERENCE_TRAIT = "noetrium.project-configuration-reference"
PROJECT_PROVIDER_BINDING_TRAIT = "noetrium.project-provider-binding"


class ProjectManifestDecodeError(ValueError):
    pass


class ProjectRequirementCardinality(StrEnum):
    EXACTLY_ONE = "exactly_one"
    ONE_OR_MORE = "one_or_more"


def _token(value: object, field: str) -> str:
    if type(value) is not str or _TOKEN.fullmatch(value) is None:
        raise ValueError(f"{field} must be a canonical lowercase token")
    return value


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _version(value: object, field: str) -> str:
    if type(value) is not str or _VERSION.fullmatch(value) is None:
        raise ValueError(f"{field} must be canonical version text")
    return value


def _tokens(values: object, field: str) -> tuple[str, ...]:
    if type(values) is not tuple:
        raise TypeError(f"{field} must be a tuple")
    rows = tuple(_token(row, field) for row in values)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return rows


def _trait(value: NoetriumUnit, trait: str, field: str) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(trait):
        raise TypeError(f"{field} must be {trait} NoetriumUnit")
    return value


def project_provenance_unit(
    tool_id: str,
    tool_version: str,
    platform_artifact_sha256: str,
) -> NoetriumUnit:
    tool_id = _token(tool_id, "project provenance tool_id")
    tool_version = _version(tool_version, "project provenance tool_version")
    require_sha256(platform_artifact_sha256, "project provenance platform artifact")
    return structure_unit(
        tool_id,
        traits=(PROJECT_PROVENANCE_TRAIT,),
        parameters={
            "tool_version": tool_version,
            "platform_artifact_sha256": platform_artifact_sha256,
        },
    )


def require_project_provenance(value: NoetriumUnit) -> NoetriumUnit:
    return _trait(value, PROJECT_PROVENANCE_TRAIT, "project provenance")


def project_provenance_tool_id(value: NoetriumUnit) -> str:
    return require_project_provenance(value).unit_id


def project_provenance_tool_version(value: NoetriumUnit) -> str:
    return str(require_project_provenance(value).parameters["tool_version"])


def project_provenance_platform_artifact(value: NoetriumUnit) -> str:
    return str(
        require_project_provenance(value).parameters["platform_artifact_sha256"]
    )


def project_capability_requirement_unit(
    requirement_id: str,
    namespace: str,
    name: str,
    major_version: int,
    interface_digest: str,
    cardinality: ProjectRequirementCardinality = ProjectRequirementCardinality.EXACTLY_ONE,
    optional: bool = False,
) -> NoetriumUnit:
    requirement_id = _token(requirement_id, "project capability requirement_id")
    namespace = _token(namespace, "project capability namespace")
    name = _token(name, "project capability name")
    if type(major_version) is not int or major_version <= 0:
        raise ValueError("project capability major_version must be positive")
    require_sha256(interface_digest, "project capability interface_digest")
    if not isinstance(cardinality, ProjectRequirementCardinality):
        raise TypeError("project capability cardinality must be typed")
    if type(optional) is not bool:
        raise TypeError("project capability optional must be boolean")
    return structure_unit(
        requirement_id,
        traits=(PROJECT_CAPABILITY_REQUIREMENT_TRAIT,),
        parameters={
            "namespace": namespace,
            "name": name,
            "major_version": major_version,
            "interface_digest": interface_digest,
            "cardinality": cardinality.value,
            "optional": optional,
        },
    )


def require_project_capability_requirement(value: NoetriumUnit) -> NoetriumUnit:
    return _trait(
        value,
        PROJECT_CAPABILITY_REQUIREMENT_TRAIT,
        "project capability requirement",
    )


def project_capability_requirement_id(value: NoetriumUnit) -> str:
    return require_project_capability_requirement(value).unit_id


def project_capability_requirement_namespace(value: NoetriumUnit) -> str:
    return str(require_project_capability_requirement(value).parameters["namespace"])


def project_capability_requirement_name(value: NoetriumUnit) -> str:
    return str(require_project_capability_requirement(value).parameters["name"])


def project_capability_requirement_major_version(value: NoetriumUnit) -> int:
    return int(require_project_capability_requirement(value).parameters["major_version"])


def project_capability_requirement_interface_digest(value: NoetriumUnit) -> str:
    return str(require_project_capability_requirement(value).parameters["interface_digest"])


def project_capability_requirement_cardinality(
    value: NoetriumUnit,
) -> ProjectRequirementCardinality:
    return ProjectRequirementCardinality(
        str(require_project_capability_requirement(value).parameters["cardinality"])
    )


def project_capability_requirement_optional(value: NoetriumUnit) -> bool:
    return bool(require_project_capability_requirement(value).parameters["optional"])


def project_capability_key(value: NoetriumUnit) -> str:
    return (
        f"{project_capability_requirement_namespace(value)}."
        f"{project_capability_requirement_name(value)}."
        f"v{project_capability_requirement_major_version(value)}"
    )


def project_method_requirement_unit(
    method_id: str,
    treatment_id: str,
    implementation_digest: str,
) -> NoetriumUnit:
    method_id = _token(method_id, "project method_id")
    treatment_id = _token(treatment_id, "project treatment_id")
    require_sha256(implementation_digest, "project method implementation_digest")
    local_id = "method-requirement:" + canonical_digest(
        {"method_id": method_id, "treatment_id": treatment_id}
    )
    return structure_unit(
        local_id,
        traits=(PROJECT_METHOD_REQUIREMENT_TRAIT,),
        parameters={
            "method_id": method_id,
            "treatment_id": treatment_id,
            "implementation_digest": implementation_digest,
        },
    )


def require_project_method_requirement(value: NoetriumUnit) -> NoetriumUnit:
    return _trait(value, PROJECT_METHOD_REQUIREMENT_TRAIT, "project method requirement")


def project_method_requirement_method_id(value: NoetriumUnit) -> str:
    return str(require_project_method_requirement(value).parameters["method_id"])


def project_method_requirement_treatment_id(value: NoetriumUnit) -> str:
    return str(require_project_method_requirement(value).parameters["treatment_id"])


def project_method_requirement_implementation_digest(value: NoetriumUnit) -> str:
    return str(
        require_project_method_requirement(value).parameters["implementation_digest"]
    )


def project_configuration_reference_unit(
    configuration_id: str,
    artifact_ref: str,
    content_sha256: str,
) -> NoetriumUnit:
    configuration_id = _token(configuration_id, "project configuration_id")
    artifact_ref = _text(artifact_ref, "project configuration artifact_ref")
    require_sha256(content_sha256, "project configuration content_sha256")
    return structure_unit(
        configuration_id,
        traits=(PROJECT_CONFIGURATION_REFERENCE_TRAIT,),
        parameters={
            "artifact_ref": artifact_ref,
            "content_sha256": content_sha256,
        },
    )


def require_project_configuration_reference(value: NoetriumUnit) -> NoetriumUnit:
    return _trait(
        value,
        PROJECT_CONFIGURATION_REFERENCE_TRAIT,
        "project configuration reference",
    )


def project_configuration_reference_id(value: NoetriumUnit) -> str:
    return require_project_configuration_reference(value).unit_id


def project_configuration_reference_artifact(value: NoetriumUnit) -> str:
    return str(require_project_configuration_reference(value).parameters["artifact_ref"])


def project_configuration_reference_content_sha256(value: NoetriumUnit) -> str:
    return str(
        require_project_configuration_reference(value).parameters["content_sha256"]
    )


def project_provider_binding_unit(
    binding_id: str,
    requirement_id: str,
    provider_identity: str,
    provider_version: str,
    configuration_digest: str,
) -> NoetriumUnit:
    binding_id = _token(binding_id, "project provider binding_id")
    requirement_id = _token(requirement_id, "project provider requirement_id")
    provider_identity = _text(provider_identity, "project provider identity")
    provider_version = _version(provider_version, "project provider version")
    require_sha256(configuration_digest, "project provider configuration_digest")
    return structure_unit(
        binding_id,
        traits=(PROJECT_PROVIDER_BINDING_TRAIT,),
        parameters={
            "requirement_id": requirement_id,
            "provider_identity": provider_identity,
            "provider_version": provider_version,
            "configuration_digest": configuration_digest,
        },
    )


def require_project_provider_binding(value: NoetriumUnit) -> NoetriumUnit:
    return _trait(value, PROJECT_PROVIDER_BINDING_TRAIT, "project provider binding")


def project_provider_binding_id(value: NoetriumUnit) -> str:
    return require_project_provider_binding(value).unit_id


def project_provider_binding_requirement_id(value: NoetriumUnit) -> str:
    return str(require_project_provider_binding(value).parameters["requirement_id"])


def project_provider_binding_identity(value: NoetriumUnit) -> str:
    return str(require_project_provider_binding(value).parameters["provider_identity"])


def project_provider_binding_version(value: NoetriumUnit) -> str:
    return str(require_project_provider_binding(value).parameters["provider_version"])


def project_provider_binding_configuration_digest(value: NoetriumUnit) -> str:
    return str(
        require_project_provider_binding(value).parameters["configuration_digest"]
    )


def project_manifest_unit(
    project_id: str,
    version: str,
    program_id: str,
    name: str,
    *,
    template_revision: str,
    provenance: NoetriumUnit,
    description: str = "",
    tags: tuple[str, ...] = (),
    capability_requirements: tuple[NoetriumUnit, ...] = (),
    provider_bindings: tuple[NoetriumUnit, ...] = (),
    method_requirements: tuple[NoetriumUnit, ...] = (),
    configuration_refs: tuple[NoetriumUnit, ...] = (),
    study_ids: tuple[str, ...] = (),
) -> NoetriumUnit:
    project_id = _token(project_id, "project_id")
    version = _version(version, "project version")
    program_id = _token(program_id, "project program_id")
    name = _text(name, "project name")
    if type(description) is not str:
        raise TypeError("project description must be text")
    tags = _tokens(tags, "project tags")
    template_revision = _text(template_revision, "project template_revision")
    require_project_provenance(provenance)
    if type(study_ids) is not tuple:
        raise TypeError("project study_ids must be tuple")
    study_ids = tuple(_token(row, "project study_id") for row in study_ids)
    if len(study_ids) != len(set(study_ids)):
        raise ValueError("project study ids must be unique")

    groups = (
        (
            capability_requirements,
            require_project_capability_requirement,
            project_capability_requirement_id,
            "capability requirements",
        ),
        (
            provider_bindings,
            require_project_provider_binding,
            project_provider_binding_id,
            "provider bindings",
        ),
        (
            method_requirements,
            require_project_method_requirement,
            lambda row: (
                project_method_requirement_method_id(row),
                project_method_requirement_treatment_id(row),
            ),
            "method requirements",
        ),
        (
            configuration_refs,
            require_project_configuration_reference,
            project_configuration_reference_id,
            "configuration refs",
        ),
    )
    normalized: list[tuple[NoetriumUnit, ...]] = []
    for rows, validator, key, field in groups:
        if type(rows) is not tuple:
            raise TypeError(f"project {field} must be tuple")
        for row in rows:
            validator(row)
        keys = tuple(key(row) for row in rows)
        if len(keys) != len(set(keys)):
            raise ValueError(f"project {field} must be unique")
        normalized.append(tuple(sorted(rows, key=lambda row: row.unit_digest)))

    capability_requirements, provider_bindings, method_requirements, configuration_refs = normalized

    known_requirements = {
        project_capability_requirement_id(row) for row in capability_requirements
    }
    counts: dict[str, int] = {}
    for binding in provider_bindings:
        requirement_id = project_provider_binding_requirement_id(binding)
        if requirement_id not in known_requirements:
            raise ValueError("project provider binding names unknown requirement")
        counts[requirement_id] = counts.get(requirement_id, 0) + 1
    for requirement in capability_requirements:
        requirement_id = project_capability_requirement_id(requirement)
        if (
            project_capability_requirement_cardinality(requirement)
            is ProjectRequirementCardinality.EXACTLY_ONE
            and counts.get(requirement_id, 0) > 1
        ):
            raise ValueError("exactly-one capability has multiple provider bindings")

    return structure_unit(
        project_id,
        traits=(PROJECT_MANIFEST_TRAIT,),
        parameters={
            "version": version,
            "program_id": program_id,
            "name": name,
            "description": description,
            "tags": tags,
            "template_revision": template_revision,
            "study_ids": tuple(sorted(study_ids)),
        },
        members=(
            (provenance,)
            + capability_requirements
            + provider_bindings
            + method_requirements
            + configuration_refs
        ),
    )


def require_project_manifest(value: NoetriumUnit) -> NoetriumUnit:
    return _trait(value, PROJECT_MANIFEST_TRAIT, "project manifest")


def project_manifest_project_id(value: NoetriumUnit) -> str:
    return require_project_manifest(value).unit_id


def project_manifest_version(value: NoetriumUnit) -> str:
    return str(require_project_manifest(value).parameters["version"])


def project_manifest_program_id(value: NoetriumUnit) -> str:
    return str(require_project_manifest(value).parameters["program_id"])


def project_manifest_name(value: NoetriumUnit) -> str:
    return str(require_project_manifest(value).parameters["name"])


def project_manifest_description(value: NoetriumUnit) -> str:
    return str(require_project_manifest(value).parameters["description"])


def project_manifest_tags(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(require_project_manifest(value).parameters["tags"])


def project_manifest_template_revision(value: NoetriumUnit) -> str:
    return str(require_project_manifest(value).parameters["template_revision"])


def project_manifest_study_ids(value: NoetriumUnit) -> tuple[str, ...]:
    return tuple(require_project_manifest(value).parameters["study_ids"])


def project_manifest_scope(value: NoetriumUnit) -> NoetriumUnit:
    return scope_unit(ScopeKind.PROJECT, project_manifest_project_id(value))


def _members_with_trait(value: NoetriumUnit, trait: str) -> tuple[NoetriumUnit, ...]:
    require_project_manifest(value)
    return tuple(row for row in value.members if row.has_trait(trait))


def project_manifest_provenance(value: NoetriumUnit) -> NoetriumUnit:
    rows = _members_with_trait(value, PROJECT_PROVENANCE_TRAIT)
    if len(rows) != 1:
        raise ValueError("project manifest requires exactly one provenance Unit")
    return rows[0]


def project_manifest_capability_requirements(
    value: NoetriumUnit,
) -> tuple[NoetriumUnit, ...]:
    return _members_with_trait(value, PROJECT_CAPABILITY_REQUIREMENT_TRAIT)


def project_manifest_provider_bindings(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return _members_with_trait(value, PROJECT_PROVIDER_BINDING_TRAIT)


def project_manifest_method_requirements(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return _members_with_trait(value, PROJECT_METHOD_REQUIREMENT_TRAIT)


def project_manifest_configuration_refs(value: NoetriumUnit) -> tuple[NoetriumUnit, ...]:
    return _members_with_trait(value, PROJECT_CONFIGURATION_REFERENCE_TRAIT)


def project_manifest_digest(value: NoetriumUnit) -> str:
    return require_project_manifest(value).unit_digest


def encode_project_manifest(value: NoetriumUnit) -> bytes:
    return encode_unit(require_project_manifest(value))


def decode_project_manifest_bytes(raw: bytes) -> NoetriumUnit:
    if type(raw) is not bytes:
        raise ProjectManifestDecodeError("project manifest input must be bytes")
    try:
        return require_project_manifest(decode_unit(raw))
    except (TypeError, ValueError, KeyError) as exc:
        raise ProjectManifestDecodeError(str(exc)) from exc


__all__ = [name for name in globals() if name.startswith(("PROJECT_", "project_", "require_", "encode_", "decode_"))] + [
    "ProjectManifestDecodeError",
    "ProjectRequirementCardinality",
]
