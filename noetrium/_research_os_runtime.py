from __future__ import annotations

from pathlib import Path
from typing import Any

from noetrium_platform.product.research_os import ResearchPortfolio


class ResearchOS:
    """Highest-level live Research OS bound to one project workspace."""

    def __init__(self, loaded: object) -> None:
        required = ("portfolio", "revision", "research_os", "default_execution_id", "close")
        if any(not hasattr(loaded, name) for name in required):
            raise TypeError("ResearchOS requires a canonical loaded project composition")
        self._loaded = loaded

    @property
    def portfolio(self) -> ResearchPortfolio:
        return self._loaded.portfolio

    @property
    def revision(self) -> object:
        return self._loaded.revision

    @property
    def default_execution_id(self) -> str:
        return self._loaded.default_execution_id

    def __enter__(self) -> "ResearchOS":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()
    def close(self) -> None:
        self._loaded.close()

    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[object, ...] = (),
        message: str = "",
    ) -> object:
        revision = self._loaded.research_os.commit(
            portfolio,
            parents=parents,
            message=message,
        )
        self._loaded.portfolio = portfolio
        self._loaded.revision = revision
        return revision

    def diff(self, left: object, right: object) -> object:
        return self._loaded.research_os.diff(left, right)

    def branch(
        self,
        name: str,
        revision: object | None = None,
        *,
        expected: object | None = None,
    ) -> object:
        return self._loaded.research_os.branch(
            name,
            self.revision if revision is None else revision,
            expected=expected,
        )

    def tag(self, name: str, revision: object | None = None) -> object:
        return self._loaded.research_os.tag(
            name,
            self.revision if revision is None else revision,
        )
    def _target(
        self,
        *,
        revision: object | None = None,
        execution_id: str | None = None,
        node: tuple[str, str] | None = None,
    ) -> object:
        from noetrium_platform.product.research_os import (
            ResearchExecutionTarget,
            ResearchNodeRef,
        )
        selected_node = None if node is None else ResearchNodeRef(*node)
        return ResearchExecutionTarget(
            self.default_execution_id if execution_id is None else execution_id,
            self.revision if revision is None else revision,
            selected_node,
        )

    def _control(
        self,
        action: str,
        payload: object = None,
        *,
        revision: object | None = None,
        execution_id: str | None = None,
        node: tuple[str, str] | None = None,
    ) -> object:
        target = self._target(
            revision=revision,
            execution_id=execution_id,
            node=node,
        )
        return getattr(self._loaded.research_os, action)(target, payload)

    def run(self, payload: object = None, **scope: Any) -> object:
        return self._control("run", payload, **scope)

    def inspect(self, payload: object = None, **scope: Any) -> object:
        return self._control("inspect", payload, **scope)

    def pause(self, payload: object = None, **scope: Any) -> object:
        return self._control("pause", payload, **scope)

    def drain(self, payload: object = None, **scope: Any) -> object:
        return self._control("drain", payload, **scope)
    def interrupt(self, payload: object = None, **scope: Any) -> object:
        return self._control("interrupt", payload, **scope)

    def resume(self, payload: object = None, **scope: Any) -> object:
        return self._control("resume", payload, **scope)

    def retry(self, payload: object = None, **scope: Any) -> object:
        return self._control("retry", payload, **scope)

    def cancel(self, payload: object = None, **scope: Any) -> object:
        return self._control("cancel", payload, **scope)

    def checkpoint(self, payload: object = None, **scope: Any) -> object:
        return self._control("checkpoint", payload, **scope)

    def reconcile(self, payload: object = None, **scope: Any) -> object:
        return self._control("reconcile", payload, **scope)

    def migrate(self, payload: object = None, **scope: Any) -> object:
        return self._control("migrate", payload, **scope)


def open_project(
    project_root: str | Path = ".",
    *,
    config_path: str | Path | None = None,
) -> ResearchOS:
    """Open one canonical Noetrium project as the highest-level Research OS."""
    from noetrium_platform.composition.operator.project import load_project_research_os

    root = Path(project_root)
    config = None if config_path is None else Path(config_path)
    return ResearchOS(load_project_research_os(root, config_path=config))


__all__ = ("ResearchOS", "open_project")
