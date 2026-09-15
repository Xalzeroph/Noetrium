from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import MachineKind

from .agent_turn import agent_turn_machine_family
from .reference import reference_machine_families as _legacy_reference_machine_families


def reference_machine_families():
    """Return the Research OS reference family set with Agent Turn v2 semantics.

    The generic reference module still supplies the other domain examples. The
    Agent family is replaced here so the package surface has one active Agent
    Turn descriptor and one Journal-preserving fact protocol.
    """

    rows = tuple(
        family
        for family in _legacy_reference_machine_families()
        if family.kind is not MachineKind.AGENT
    )
    return (*rows, agent_turn_machine_family())


__all__ = ["reference_machine_families"]
