from __future__ import annotations

import os
from pathlib import Path
from tempfile import gettempdir

from noetrium_platform.foundation.kernel.kernel import canonical_digest, LocalLeaseClock


_RUNTIME_COORDINATION_ROOT_ENV = "NOETRIUM_RUNTIME_COORDINATION_ROOT"
_RUNTIME_FABRIC_ROOT_ENV = "NOETRIUM_RUNTIME_FABRIC_ROOT"
_RUNTIME_CACHE_ROOT_ENV = "NOETRIUM_RUNTIME_CACHE_ROOT"


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



def _canonical_user_home() -> Path:
    """Resolve the OS-account home independently of mutable session HOME/XDG state."""

    getuid = getattr(os, "getuid", None)
    if callable(getuid) and os.name != "nt":
        import pwd

        record = pwd.getpwuid(int(getuid()))
        home = Path(record.pw_dir)
        if not home.is_absolute():
            raise RuntimeError("OS account home must be absolute")
        return home
    home = Path.home()
    if not home.is_absolute():
        raise RuntimeError("OS account home must be absolute")
    return home


def runtime_cache_root() -> Path:
    """Return the disposable host-local acceleration cache root."""

    explicit = os.environ.get(_RUNTIME_CACHE_ROOT_ENV, "").strip()
    if explicit:
        base = Path(explicit)
        if not base.is_absolute():
            raise ValueError(
                f"{_RUNTIME_CACHE_ROOT_ENV} must be an absolute path"
            )
    else:
        base = _canonical_user_home() / ".cache" / "noetrium" / "runtime-cache"
    reading = LocalLeaseClock().read()
    return (
        base
        / runtime_coordination_user_namespace()
        / reading.host_identity_digest
    )


def runtime_fabric_root() -> Path:
    """Return the durable host-scoped Runtime Fabric authority root."""

    explicit = os.environ.get(_RUNTIME_FABRIC_ROOT_ENV, "").strip()
    if explicit:
        base = Path(explicit)
        if not base.is_absolute():
            raise ValueError(
                f"{_RUNTIME_FABRIC_ROOT_ENV} must be an absolute path"
            )
    else:
        # Runtime Fabric is a host-user authority.  Shell/IDE/Remote wrappers
        # may intentionally rewrite HOME or XDG_STATE_HOME while preserving the
        # same OS uid; those session-local variables must not fork durable
        # authority state.  Users needing a non-default root have the explicit
        # NOETRIUM_RUNTIME_FABRIC_ROOT authority above.
        base = (
            _canonical_user_home()
            / ".local"
            / "state"
            / "noetrium"
            / "runtime-fabric"
        )

    reading = LocalLeaseClock().read()
    return (
        base
        / runtime_coordination_user_namespace()
        / reading.host_identity_digest
    )


__all__ = [
    "runtime_cache_root",
    "runtime_coordination_root",
    "runtime_coordination_user_namespace",
    "runtime_fabric_root",
]
