from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum

from noetrium_platform.capabilities.environment.api.semantics import (
    environment_capabilities,
    environment_unit,
    require_environment_unit,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue, freeze_json
from noetrium_platform.foundation.kernel.structure import NoetriumUnit


class SoftwareActionTimeoutError(RuntimeError):
    """Software action exceeded its declared execution budget."""


class SoftwareActionKind(StrEnum):
    LIST = "list"
    READ = "read"
    EDIT = "edit"
    EXECUTE = "execute"
    TEST = "test"
    BUILD = "build"


def software_context_policy(
    *,
    max_text_chars: int = 12_000,
    max_workspace_files: int = 512,
    max_list_files: int = 512,
) -> Mapping[str, JsonValue]:
    if (
        type(max_text_chars) is not int
        or max_text_chars < 1_000
        or type(max_workspace_files) is not int
        or max_workspace_files < 1
        or type(max_list_files) is not int
        or max_list_files < 1
    ):
        raise ValueError("software context policy bounds are invalid")
    return freeze_json({
        "max_text_chars": max_text_chars,
        "max_workspace_files": max_workspace_files,
        "max_list_files": max_list_files,
    })


def software_environment_unit(
    environment_id: str,
    revision: str,
    workspace_root: str,
    *,
    repository_digest: str = "",
    supported_actions: tuple[SoftwareActionKind, ...] = (),
    metadata: Mapping[str, JsonValue] | None = None,
    context_policy: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    if type(workspace_root) is not str or not workspace_root.strip():
        raise ValueError("software workspace_root is required")
    if type(supported_actions) is not tuple or any(
        not isinstance(item, SoftwareActionKind) for item in supported_actions
    ):
        raise TypeError("software actions must use SoftwareActionKind tuple")
    if len(supported_actions) != len(set(supported_actions)):
        raise ValueError("software actions must be unique")
    policy = (
        software_context_policy()
        if context_policy is None
        else freeze_json(context_policy)
    )
    return environment_unit(
        environment_id,
        category="software",
        revision=revision,
        capabilities=tuple(item.value for item in supported_actions) or ("observe",),
        parameters={
            "workspace_root": workspace_root,
            "repository_digest": repository_digest,
            "metadata": freeze_json({} if metadata is None else metadata),
            "context_policy": policy,
        },
    )


def require_software_environment(value: NoetriumUnit) -> NoetriumUnit:
    value = require_environment_unit(value)
    if value.parameters["category"] != "software":
        raise TypeError("software environment Unit must have category='software'")
    return value


def software_environment_id(value: NoetriumUnit) -> str:
    return require_software_environment(value).unit_id


def software_environment_revision(value: NoetriumUnit) -> str:
    return str(require_software_environment(value).parameters["revision"])


def software_environment_workspace_root(value: NoetriumUnit) -> str:
    return str(require_software_environment(value).parameters["workspace_root"])


def software_environment_repository_digest(value: NoetriumUnit) -> str:
    return str(require_software_environment(value).parameters["repository_digest"])


def software_environment_context_policy(
    value: NoetriumUnit,
) -> Mapping[str, JsonValue]:
    return require_software_environment(value).parameters["context_policy"]


def software_environment_supported_actions(
    value: NoetriumUnit,
) -> tuple[SoftwareActionKind, ...]:
    return tuple(
        SoftwareActionKind(item)
        for item in environment_capabilities(require_software_environment(value))
        if item in {kind.value for kind in SoftwareActionKind}
    )


__all__ = [
    "SoftwareActionKind",
    "SoftwareActionTimeoutError",
    "require_software_environment",
    "software_context_policy",
    "software_environment_context_policy",
    "software_environment_id",
    "software_environment_repository_digest",
    "software_environment_revision",
    "software_environment_supported_actions",
    "software_environment_unit",
    "software_environment_workspace_root",
]
