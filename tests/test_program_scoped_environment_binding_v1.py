from __future__ import annotations

import pytest

from noetrium_platform.composition.environment_capability_runtime import (
    ProgramScopedEnvironmentCapabilityPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


class _Port:
    identity_digest = canonical_digest({"port": "single"})

    def invoke(self, request, control):
        raise AssertionError("unbound program-scoped port reached concrete provider")


def test_single_program_route_still_requires_unit_binding() -> None:
    port = ProgramScopedEnvironmentCapabilityPort((("paper.p0", _Port()),))

    with pytest.raises(RuntimeError, match="must be bound to NoetriumUnit"):
        port.invoke(object(), object())
