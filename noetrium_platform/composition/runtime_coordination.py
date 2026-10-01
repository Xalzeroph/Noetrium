from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.lease.runtime import LocalLeaseClock


_RUNTIME_COORDINATION_ROOT_ENV = "NOETRIUM_RUNTIME_COORDINATION_ROOT"
_RUNTIME_FABRIC_ROOT_ENV = "NOETRIUM_RUNTIME_FABRIC_ROOT"


def runtime_coordination_root() -> Path:
    """Resolve the single host-visible coordination root for all Noetrium processes."""

    explicit = os.environ.get(_RUNTIME_COORDINATION_ROOT_ENV, "").strip()
    if explicit:
        root = Path(explicit)
        if not root.is_absolute():
            raise ValueError(
                f"{_RUNTIME_COORDINATION_ROOT_ENV} must be an absolute path"
            )
        return root

    xdg_runtime = os.environ.get("XDG_RUNTIME_DIR", "").strip()
    if xdg_runtime:
        candidate = Path(xdg_runtime).absolute()
        if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK):
            return candidate / "noetrium"

    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        uid = int(getuid())
        candidate = Path("/run/user") / str(uid)
        if candidate.is_dir() and os.access(candidate, os.W_OK | os.X_OK):
            return candidate / "noetrium"
        shared_memory = Path("/dev/shm")
        if shared_memory.is_dir() and os.access(
            shared_memory, os.W_OK | os.X_OK
        ):
            return shared_memory / f"noetrium-uid-{uid}"

    if os.name != "nt":
        raise RuntimeError(
            "no writable host runtime coordination filesystem is available"
        )
    return Path(gettempdir()).absolute() / "noetrium"


def runtime_coordination_user_namespace() -> str:
    getuid = getattr(os, "getuid", None)
    if callable(getuid):
        return f"uid-{int(getuid())}"
    raw = (
        os.environ.get("USERNAME")
        or os.environ.get("USER")
        or os.environ.get("LOGNAME")
        or "unknown-user"
    )
    return "user-" + canonical_digest(raw)[:16]



def runtime_fabric_root() -> Path:
    """Return the durable host-scoped Runtime Fabric authority root."""

    explicit = os.environ.get(_RUNTIME_FABRIC_ROOT_ENV, "").strip()
    if explicit:
        base = Path(explicit).expanduser()
        if not base.is_absolute():
            raise ValueError(
                f"{_RUNTIME_FABRIC_ROOT_ENV} must be an absolute path"
            )
    else:
        xdg_state = os.environ.get("XDG_STATE_HOME", "").strip()
        if xdg_state:
            base = Path(xdg_state).expanduser()
            if not base.is_absolute():
                raise ValueError("XDG_STATE_HOME must be an absolute path")
            base = base / "noetrium" / "runtime-fabric"
        else:
            base = Path.home() / ".local" / "state" / "noetrium" / "runtime-fabric"

    reading = LocalLeaseClock().read()
    return (
        base
        / runtime_coordination_user_namespace()
        / reading.host_identity_digest
    )


__all__ = [
    "runtime_coordination_root",
    "runtime_coordination_user_namespace",
    "runtime_fabric_root",
]
