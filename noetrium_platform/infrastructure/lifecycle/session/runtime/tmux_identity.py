from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path


class TmuxBinaryIdentityMismatch(RuntimeError):
    pass


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(frozen=True, slots=True)
class TmuxTransportIdentity:
    executable: str
    binary_sha256: str | None
    binary_verified: bool
    server_label: str
    config_file: str
    socket_directory: str

    @classmethod
    def resolve(
        cls,
        *,
        executable: str,
        expected_binary_sha256: str | None,
        server_label: str,
        config_file: str,
        socket_directory: str,
    ) -> "TmuxTransportIdentity":
        path = Path(executable)
        if expected_binary_sha256 is not None and len(expected_binary_sha256) != 64:
            raise ValueError("tmux binary identity must be SHA-256")
        actual = sha256_file(path) if path.is_file() else None
        frozen = actual if expected_binary_sha256 is None else expected_binary_sha256
        if actual is not None and frozen is not None and actual != frozen:
            raise TmuxBinaryIdentityMismatch("tmux binary bytes differ from frozen expected identity")
        return cls(
            executable,
            frozen,
            actual is not None and frozen is not None and actual == frozen,
            server_label,
            config_file,
            socket_directory,
        )

    @classmethod
    def from_remote_attestation(
        cls,
        *,
        executable: str,
        binary_sha256: str,
        server_label: str,
        config_file: str,
        socket_directory: str,
    ) -> "TmuxTransportIdentity":
        """Bind a tmux identity whose binary was attested on another host."""

        if len(binary_sha256) != 64 or any(char not in "0123456789abcdefABCDEF" for char in binary_sha256):
            raise ValueError("remote tmux binary identity must be a SHA-256 hex digest")
        return cls(
            executable,
            binary_sha256.lower(),
            True,
            server_label,
            config_file,
            socket_directory,
        )

    def digest(self) -> str:
        raw = json.dumps(
            {
                "backend_id": "tmux",
                "tmux_executable": self.executable,
                "tmux_binary_sha256": self.binary_sha256 or "UNVERIFIED",
                "server_label": self.server_label,
                "config_file": self.config_file,
                "socket_directory": self.socket_directory,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(raw).hexdigest()


__all__ = ["TmuxBinaryIdentityMismatch", "TmuxTransportIdentity", "sha256_file"]
