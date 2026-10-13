from __future__ import annotations

from ..api import ServerTransportFailureKind


def bounded_output_text(
    value: str | bytes | None,
    *,
    limit: int,
    total_bytes: int | None = None,
    truncated: bool = False,
) -> tuple[str, int]:
    if value is None:
        raw = b""
    else:
        raw = value if isinstance(value, bytes) else value.encode("utf-8", errors="replace")
    size = len(raw) if total_bytes is None else int(total_bytes)
    if size < len(raw):
        raise ValueError("reported output byte count is smaller than captured output")
    was_truncated = truncated or size > len(raw) or len(raw) > limit
    if not was_truncated and len(raw) <= limit:
        return raw.decode("utf-8", errors="replace"), size
    marker = f"\n[output truncated after {limit} bytes; total={size}]\n".encode("utf-8")
    bounded = raw[: max(0, limit - len(marker))] + marker
    return bounded.decode("utf-8", errors="replace"), size


def classify_transport_failure(return_code: int, stderr: str) -> ServerTransportFailureKind:
    if return_code == 0:
        return ServerTransportFailureKind.NONE
    lowered = stderr.lower()
    if return_code == 255:
        if "banner exchange:" in lowered or "connection to unknown port" in lowered:
            return ServerTransportFailureKind.NETWORK
        if any(marker in lowered for marker in (
            "permission denied",
            "authentication that can continue",
            "too many authentication failures",
            "no supported authentication methods",
        )):
            return ServerTransportFailureKind.AUTHENTICATION
        return ServerTransportFailureKind.NETWORK
    return ServerTransportFailureKind.REMOTE_EXIT


__all__ = ["bounded_output_text", "classify_transport_failure"]
