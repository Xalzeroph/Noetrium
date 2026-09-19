from __future__ import annotations

import hashlib
from pathlib import Path

_DEFAULT_CHUNK_BYTES = 1024 * 1024


def sha256_file(path: Path, *, chunk_bytes: int = _DEFAULT_CHUNK_BYTES) -> tuple[str, int]:
    """Return the SHA-256 and byte length of *path* without materializing it in memory."""
    if chunk_bytes <= 0:
        raise ValueError("chunk_bytes must be positive")
    digest = hashlib.sha256()
    size = 0
    with Path(path).open("rb", buffering=chunk_bytes) as handle:
        for chunk in iter(lambda: handle.read(chunk_bytes), b""):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


__all__ = ["sha256_file"]
