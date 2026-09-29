from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path

from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
)
from noetrium_platform.composition.local_research_execution_authority import (
    build_local_research_execution_authority_materializer,
)
from noetrium_platform.product.research_os import ResearchPortfolio


_SCHEMA = "noetrium.project-execution-config.v1"


@dataclass(frozen=True, slots=True)
class ProjectExecutionAuthorityConfig:
    start_background_controllers: bool = True

    def __post_init__(self) -> None:
        if type(self.start_background_controllers) is not bool:
            raise TypeError(
                "project execution start_background_controllers must be boolean"
            )



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
        "start_background_controllers",
    }
    unknown = tuple(sorted(set(document) - allowed))
    if unknown:
        raise ValueError(
            f"project execution config contains unknown fields: {unknown}"
        )
    return ProjectExecutionAuthorityConfig(
        start_background_controllers=document.get(
            "start_background_controllers",
            True,
        ),
    )


def materialize_project_execution_authorities(
    context: ResearchExecutionContext,
    portfolio: ResearchPortfolio,
    project_manifest,
) -> ResearchExecutionAuthorities:
    """Resolve every project through the one platform-owned execution seam."""

    if type(portfolio) is not ResearchPortfolio:
        raise TypeError(
            "project authority materialization requires ResearchPortfolio"
        )
    materializer = build_local_research_execution_authority_materializer(
        context,
        project_manifest,
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
