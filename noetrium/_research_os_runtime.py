from __future__ import annotations

from pathlib import Path
from typing import Any

from noetrium_platform.product.research_os import ResearchPortfolio


class ResearchExecutionDSL:
    """Live execution-control system for one opened Research OS."""

    def __init__(self, owner: "ResearchOS") -> None:
        self._owner = owner

    def run(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("run", payload, **scope)

    def inspect(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("inspect", payload, **scope)

    def pause(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("pause", payload, **scope)

    def drain(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("drain", payload, **scope)

    def interrupt(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("interrupt", payload, **scope)

    def resume(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("resume", payload, **scope)

    def retry(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("retry", payload, **scope)

    def cancel(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("cancel", payload, **scope)

    def checkpoint(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("checkpoint", payload, **scope)

    def reconcile(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("reconcile", payload, **scope)

    def migrate(self, payload: object = None, **scope: Any) -> object:
        return self._owner._control("migrate", payload, **scope)


class ResearchRevisionDSL:
    """Version/branch/tag system over the canonical ResearchGraph history."""

    def __init__(self, owner: "ResearchOS") -> None:
        self._owner = owner

    def commit(
        self,
        portfolio: ResearchPortfolio,
        *,
        parents: tuple[object, ...] = (),
        message: str = "",
    ) -> object:
        revision = self._owner._loaded.research_os.commit(
            portfolio,
            parents=parents,
            message=message,
        )
        self._owner._loaded.portfolio = portfolio
        self._owner._loaded.revision = revision
        return revision

    def diff(self, left: object, right: object) -> object:
        return self._owner._loaded.research_os.diff(left, right)

    def branch(
        self,
        name: str,
        revision: object | None = None,
        *,
        expected: object | None = None,
    ) -> object:
        return self._owner._loaded.research_os.branch(
            name,
            self._owner.revision if revision is None else revision,
            expected=expected,
        )

    def tag(self, name: str, revision: object | None = None) -> object:
        return self._owner._loaded.research_os.tag(
            name,
            self._owner.revision if revision is None else revision,
        )


class ResearchOS:
    """Highest-level live Research OS bound to one project workspace."""

    def __init__(self, loaded: object) -> None:
        required = ("portfolio", "revision", "research_os", "default_execution_id", "close")
        if any(not hasattr(loaded, name) for name in required):
            raise TypeError("ResearchOS requires a canonical loaded project composition")
        self._loaded = loaded
        self._execution = ResearchExecutionDSL(self)
        self._revisions = ResearchRevisionDSL(self)

    @property
    def portfolio(self) -> ResearchPortfolio:
        return self._loaded.portfolio

    @property
    def revision(self) -> object:
        return self._loaded.revision

    @property
    def default_execution_id(self) -> str:
        return self._loaded.default_execution_id

    @property
    def execution(self) -> ResearchExecutionDSL:
        return self._execution

    @property
    def revisions(self) -> ResearchRevisionDSL:
        return self._revisions

    def __enter__(self) -> "ResearchOS":
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()

    def close(self) -> None:
        self._loaded.close()

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
        """One-command execution convenience; all other control lives under execution."""
        return self._execution.run(payload, **scope)


def open_project(project_root: str | Path = ".") -> ResearchOS:
    """Open one canonical project; physical runtime policy is platform-owned."""
    from noetrium_platform.composition.operator.project import load_project_research_os

    return ResearchOS(load_project_research_os(Path(project_root)))


__all__ = ("ResearchOS", "open_project")
