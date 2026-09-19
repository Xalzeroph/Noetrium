from __future__ import annotations

from . import controller, deployments, directories, environments, models, summary
from .context import ManagementCommandContext

_ROUTES = (summary, controller, directories, environments, models, deployments)
DISPATCH = {route.GROUP: route.dispatch for route in _ROUTES}


def register_all(groups) -> None:
    for route in _ROUTES:
        route.register(groups)


__all__ = ["DISPATCH", "ManagementCommandContext", "register_all"]
