from __future__ import annotations

from .contracts import RunCleanupReport


def attach_cleanup_note(exc: BaseException, report: RunCleanupReport) -> None:
    """Attach stable cleanup diagnostics without exposing Lifecycle runtime internals."""
    if not report.failures:
        return
    details = "; ".join(
        f"{x.operation_id}:{x.failure_id or x.diagnostics.get('exception_type','unrecorded')}"
        for x in report.failures
    )
    try:
        exc.add_note(f"additional cleanup failures: {details}")
    except AttributeError:
        pass


__all__ = ["attach_cleanup_note"]
