from __future__ import annotations

from typing import Iterable

from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.evidence.observability.status.api import HealthState, PlatformStatus, SubsystemSnapshot, SubsystemStatusProbePort


class PlatformStatusService:
    """Read-only join of independent subsystem status projections."""

    def __init__(self, probes: Iterable[SubsystemStatusProbePort] = ()) -> None:
        self._probes = tuple(probes)

    def snapshot(self) -> PlatformStatus:
        out: list[SubsystemSnapshot] = []
        for probe in self._probes:
            try:
                snap = probe.snapshot()
            except Exception as exc:
                descriptor = describe_exception(exc)
                name = type(probe).__name__
                snap = SubsystemSnapshot(
                    subsystem=f"probe:{name}",
                    state=HealthState.FAILED,
                    summary=(
                        f"status probe failed: {descriptor.error_type}: {descriptor.safe_message}; "
                        f"error_digest={descriptor.error_digest}"
                    ),
                    next_commands=("inspect the probe failure; status probes must remain read-only",),
                    reason_codes=("status_probe_failed",),
                )
            out.append(snap)
        return PlatformStatus(tuple(out))


__all__ = ["PlatformStatusService"]
