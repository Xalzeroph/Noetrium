from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.infrastructure.reliability.forensics.api.runtime_parts import ForensicRuntimeParts


@dataclass(slots=True)
class ForensicRuntimeLifecycle:
    """Owns close ordering and lease release; resources themselves live in runtime parts."""

    parts: ForensicRuntimeParts
    closed: bool = False

    def close(self,flush_projections)->None:
        if self.closed:
            return
        error=None
        if self.parts.writer_lease is not None:
            try:
                flush_projections()
            except Exception as exc:
                error=exc

        # Release every owned resource, including segmented ledgers that keep
        # process-wide filesystem watches alive. Continue cleanup after the
        # first failure so one resource cannot leak the rest of the bundle.
        for resource in (
            self.parts.events,
            self.parts.failures,
            self.parts.mutations,
            self.parts.index,
        ):
            close=getattr(resource,"close",None)
            if close is None:
                continue
            try:
                close()
            except Exception as exc:
                if error is None:
                    error=exc

        if self.parts.writer_lease is not None:
            try:
                self.parts.writer_lease.release()
            except Exception as exc:
                if error is None:
                    error=exc
        self.closed=True
        if error is not None:
            raise error
