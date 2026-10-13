from __future__ import annotations

from .context import ManagementCommandContext
from .deployment_actions import dispatch_deployment_action
from .deployment_parser import GROUP, register
from .deployment_qualification import (
    dispatch_qualification_action,
    qualification_python_path,
)
from .deployment_spec import deployment_from_json, deployment_selector

# Preserve the narrow helper imports used by existing tests/callers while the
# implementation lives in single-purpose modules.
_qualification_python_path = qualification_python_path
_deployment_from_json = deployment_from_json
_selector = deployment_selector


def dispatch(args: object, context: ManagementCommandContext) -> object:
    handled, result = dispatch_deployment_action(args, context)
    if handled:
        return result
    handled, result = dispatch_qualification_action(args, context)
    if handled:
        return result
    raise ValueError(f"unsupported deployment management action: {args.action}")


__all__ = ["GROUP", "dispatch", "register"]
