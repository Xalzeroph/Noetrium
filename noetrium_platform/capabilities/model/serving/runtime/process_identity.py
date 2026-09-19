from __future__ import annotations

from dataclasses import dataclass
import hashlib


@dataclass(frozen=True, slots=True)
class ProcessIdentity:
    pid: int
    start_marker: str
    argv_digest: str

    @classmethod
    def from_argv(cls, pid: int, start_marker: str, argv: tuple[str, ...]) -> "ProcessIdentity":
        raw = b"\0".join(x.encode("utf-8", "surrogateescape") for x in argv)
        return cls(pid=pid, start_marker=start_marker, argv_digest=hashlib.sha256(raw).hexdigest())


class ProcessIdentityReconciler:
    """Pure equality contract. OS-specific probes should produce ProcessIdentity outside this class."""

    def reconcile(self, recorded: ProcessIdentity, observed: ProcessIdentity | None) -> str:
        if observed is None:
            return "not_running"
        if recorded == observed:
            return "same_process"
        if recorded.pid == observed.pid:
            return "pid_reused_or_identity_drift"
        return "different_process"
