from __future__ import annotations

from typing import Protocol


class OperatorRoutePort(Protocol):
    """One operator command-family route. None means the route does not own the command."""

    def __call__(self, args: object) -> object | None: ...


class OperatorHandlerPort(Protocol):
    """Stable command dispatch surface used by CLI/application hosts."""

    def handle(self, args: object) -> object: ...


__all__ = ["OperatorHandlerPort", "OperatorRoutePort"]
