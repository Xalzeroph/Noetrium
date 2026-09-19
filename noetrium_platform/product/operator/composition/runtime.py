from __future__ import annotations

from noetrium_platform.product.operator.audit.runtime.route_architecture import route_architecture
from noetrium_platform.product.operator.audit.runtime.route_release import route_release
from noetrium_platform.product.operator.query.runtime.route_diagnostics import route_diagnostics
from noetrium_platform.product.operator.query.runtime.route_runtime import route_runtime
from noetrium_platform.product.operator.query.runtime.route_telemetry import route_telemetry
from noetrium_platform.product.operator.runtime import OperatorHandler


def build_operator_handler() -> OperatorHandler:
    return OperatorHandler(
        (
            route_architecture,
            route_release,
            route_runtime,
            route_telemetry,
            route_diagnostics,
        )
    )


__all__ = ["build_operator_handler"]
