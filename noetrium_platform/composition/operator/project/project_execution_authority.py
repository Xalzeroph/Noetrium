from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
    load_research_execution_authority_materializer,
)
from noetrium_platform.product.research_os import ResearchPortfolio


_SCHEMA = "noetrium.project-execution-config.v1"


@dataclass(frozen=True, slots=True)
class ProjectExecutionAuthorityConfig:
    authority_factory: str
    start_background_controllers: bool = True
    authority_inputs: tuple[tuple[str, str], ...] = ()

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
        if type(self.authority_inputs) is not tuple:
            raise TypeError("project execution authority_inputs must be a tuple")
        normalized: list[tuple[str, str]] = []
        for row in self.authority_inputs:
            if type(row) is not tuple or len(row) != 2:
                raise TypeError(
                    "project execution authority_inputs must contain text pairs"
                )
            key, value = row
            if (
                type(key) is not str
                or not key.strip()
                or key != key.strip()
                or type(value) is not str
                or not value.strip()
                or value != value.strip()
            ):
                raise ValueError(
                    "project execution authority_inputs require canonical non-empty text"
                )
            normalized.append((key, value))
        normalized.sort(key=lambda row: row[0])
        if len({key for key, _value in normalized}) != len(normalized):
            raise ValueError("project execution authority_inputs keys must be unique")
        object.__setattr__(self, "authority_inputs", tuple(normalized))


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
        "authority_inputs",
    }
    unknown = tuple(sorted(set(document) - allowed))
    if unknown:
        raise ValueError(
            f"project execution config contains unknown fields: {unknown}"
        )
    authority_inputs = document.get("authority_inputs", {})
    if type(authority_inputs) is not dict:
        raise TypeError("project execution authority_inputs must be a JSON object")
    return ProjectExecutionAuthorityConfig(
        authority_factory=document.get("authority_factory", ""),
        start_background_controllers=document.get(
            "start_background_controllers",
            True,
        ),
        authority_inputs=tuple(authority_inputs.items()),
    )


def materialize_project_execution_authorities(
    spec: str,
    context: ResearchExecutionContext,
    portfolio: ResearchPortfolio,
) -> ResearchExecutionAuthorities:
    """Resolve project input through the cardinality-agnostic execution seam."""

    if type(portfolio) is not ResearchPortfolio:
        raise TypeError(
            "project authority materialization requires ResearchPortfolio"
        )
    materializer = load_research_execution_authority_materializer(
        spec,
        context,
    )
    authorities = materializer.materialize(portfolio)
    if type(authorities) is not ResearchExecutionAuthorities:
        raise TypeError(
            "research execution authority materializer must return "
            "ResearchExecutionAuthorities"
        )
    return authorities


__all__ = [
    "ProjectExecutionAuthorityConfig",
    "load_project_execution_authority_config",
    "materialize_project_execution_authorities",
]
