from __future__ import annotations

from noetrium_platform.product.operator.api import OperatorRoutePort


class OperatorHandler:
    """Route dispatcher; concrete child routes are injected by the operator composition root."""

    def __init__(self, routes: tuple[OperatorRoutePort, ...]) -> None:
        self._routes = routes

    def handle(self, args: object) -> object:
        for route in self._routes:
            result = route(args)
            if result is not None:
                return result
        raise AssertionError(f"unhandled operator command: {getattr(args, 'command', None)}")


__all__ = ["OperatorHandler"]
