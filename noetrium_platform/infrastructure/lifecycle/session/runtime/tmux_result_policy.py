from __future__ import annotations

import hashlib

from noetrium_platform.foundation.kernel.kernel.errors import redact_text

from .tmux_contracts import TmuxCommandResult


class TmuxCommandFailed(RuntimeError):
    """Safe transport failure. Raw stderr is never stored on the exception."""

    def __init__(self, operation: str, result: TmuxCommandResult) -> None:
        safe = redact_text(result.stderr.strip() or result.stdout.strip() or "tmux command failed")
        digest = hashlib.sha256(safe.encode("utf-8", "replace")).hexdigest()
        self.operation = operation
        self.returncode = int(result.returncode)
        self.stderr_digest = digest
        super().__init__(
            f"tmux {operation} failed rc={self.returncode}: {safe}; stderr_digest={digest}"
        )


_MISSING_MARKERS = (
    "can't find session",
    "can't find pane",
    "no server running on",
    "no sessions",
)


def session_is_absent(result: TmuxCommandResult) -> bool:
    if result.returncode == 0:
        return False
    text = f"{result.stderr}\n{result.stdout}".strip().lower()
    # Literal "missing" is accepted for deterministic fake transports used by
    # tests and adapters, while partial matches are intentionally rejected.
    if text == "missing":
        return True
    if any(marker in text for marker in _MISSING_MARKERS):
        return True
    # A freshly selected tmux server label has no socket yet. tmux reports
    # that state as a connection error rather than "no server running"; it is
    # an absent session only when both parts of this exact diagnostic occur.
    return "error connecting to " in text and "no such file or directory" in text


def require_success(operation: str, result: TmuxCommandResult) -> None:
    if result.returncode != 0:
        raise TmuxCommandFailed(operation, result)


__all__ = ["TmuxCommandFailed", "require_success", "session_is_absent"]
