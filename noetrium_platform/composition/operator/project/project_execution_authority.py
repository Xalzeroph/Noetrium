from __future__ import annotations

from dataclasses import dataclass
import importlib
import json
from pathlib import Path

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
)
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
)
from noetrium_platform.foundation.portfolio.project.api import ProjectManifest
from noetrium_platform.product.research_os import ResearchPortfolio


_SCHEMA = "noetrium.project-execution-config.v1"


@dataclass(frozen=True, slots=True)
class ProjectExecutionAuthorityConfig:
    authority_factory: str
    start_background_controllers: bool = True

    def __post_init__(self) -> None:
        if (
            type(self.authority_factory) is not str
            or not self.authority_factory.strip()
            or self.authority_factory != self.authority_factory.strip()
        ):
            raise ValueError(
                "project execution authority_factory must be canonical text"
            )
        module, separator, qualname = self.authority_factory.partition(":")
        if (
            separator != ":"
            or not module
            or not qualname
            or ":" in qualname
            or any(
                not part or part.startswith("_")
                for part in qualname.split(".")
            )
        ):
            raise ValueError(
                "project execution authority_factory must use public "
                "module:factory format"
            )
        if type(self.start_background_controllers) is not bool:
            raise TypeError(
                "project execution start_background_controllers must be boolean"
            )


@dataclass(frozen=True, slots=True)
class ProjectExecutionContext:
    project_root: Path
    state_root: Path
    manifest: ProjectManifest
    portfolio: ResearchPortfolio
    runtime: ManagedResearchRuntime

    def __post_init__(self) -> None:
        if not isinstance(self.project_root, Path):
            raise TypeError("project execution project_root must be pathlib.Path")
        if not isinstance(self.state_root, Path):
            raise TypeError("project execution state_root must be pathlib.Path")
        if type(self.manifest) is not ProjectManifest:
            raise TypeError("project execution manifest must be ProjectManifest")
        if type(self.portfolio) is not ResearchPortfolio:
            raise TypeError("project execution portfolio must be ResearchPortfolio")
        if not isinstance(self.runtime, ManagedResearchRuntime):
            raise TypeError(
                "project execution runtime must be ManagedResearchRuntime"
            )

    @property
    def execution_pool(self):
        return self.runtime.execution_pool

    @property
    def management(self):
        return self.runtime.management

    @property
    def resources(self):
        return self.runtime.resources

    @property
    def model_replica_pool(self):
        return self.runtime.model_replica_pool


def load_project_execution_authority_config(
    path: Path,
) -> ProjectExecutionAuthorityConfig:
    if not isinstance(path, Path):
        raise TypeError("project execution config path must be pathlib.Path")
    resolved = path.expanduser().absolute()
    if not resolved.is_file() or resolved.is_symlink():
        raise ValueError(
            "project execution config must be a real JSON file"
        )
    try:
        document = json.loads(resolved.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("project execution config is not valid JSON") from exc
    if type(document) is not dict:
        raise TypeError("project execution config must be a JSON object")
    if document.get("schema") != _SCHEMA:
        raise ValueError(
            "project execution config schema must be "
            f"{_SCHEMA!r}"
        )
    allowed = {
        "schema",
        "authority_factory",
        "start_background_controllers",
    }
    unknown = tuple(sorted(set(document) - allowed))
    if unknown:
        raise ValueError(
            f"project execution config contains unknown fields: {unknown}"
        )
    return ProjectExecutionAuthorityConfig(
        authority_factory=document.get("authority_factory", ""),
        start_background_controllers=document.get(
            "start_background_controllers",
            True,
        ),
    )


def materialize_project_execution_authorities(
    spec: str,
    context: ProjectExecutionContext,
) -> ProjectExecutionAuthorities:
    if type(context) is not ProjectExecutionContext:
        raise TypeError(
            "project authority materialization requires ProjectExecutionContext"
        )
    config = ProjectExecutionAuthorityConfig(spec)
    module_name, _separator, qualname = config.authority_factory.partition(":")
    try:
        value: object = importlib.import_module(module_name)
        for part in qualname.split("."):
            value = getattr(value, part)
    except (ImportError, AttributeError) as exc:
        raise ValueError(
            "project execution authority factory cannot be imported: "
            f"{config.authority_factory}"
        ) from exc
    if not callable(value):
        raise TypeError(
            "project execution authority factory target must be callable"
        )
    authorities = value(context)
    if type(authorities) is not ResearchExecutionAuthorities:
        raise TypeError(
            "project execution authority factory must return "
            "ResearchExecutionAuthorities"
        )
    return authorities


__all__ = [
    "ProjectExecutionAuthorityConfig",
    "ProjectExecutionContext",
    "load_project_execution_authority_config",
    "materialize_project_execution_authorities",
]
