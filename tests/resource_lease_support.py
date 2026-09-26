from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

from noetrium_platform.infrastructure.resources.lease.api import LeaseClockPort
from noetrium_platform.infrastructure.resources.lease.runtime import ResourceLeaseRegistry


class TestResourceLeaseRegistry(ResourceLeaseRegistry):
    """Test-only path convenience over the sole production lease machine."""

    __test__ = False

    def __init__(
        self,
        *,
        clock: LeaseClockPort | None = None,
        state_path: str | Path | None = None,
    ) -> None:
        self._temporary_directory: TemporaryDirectory[str] | None = None
        if state_path is None:
            temporary_directory = TemporaryDirectory(prefix="noetrium-lease-test-")
            self._temporary_directory = temporary_directory
            path = Path(temporary_directory.name) / "resources.sqlite"
        else:
            path = Path(state_path)
        super().__init__(path, clock=clock)

    @property
    def clock(self) -> LeaseClockPort:
        return self._clock


__all__ = ["TestResourceLeaseRegistry"]
