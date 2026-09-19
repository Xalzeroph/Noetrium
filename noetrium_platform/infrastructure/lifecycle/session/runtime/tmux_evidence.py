from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import JsonValue, canonical_digest


def tmux_evidence_ref(kind: str, payload: JsonValue) -> str:
    return f"tmux-{kind}:" + canonical_digest(payload)


__all__ = ["tmux_evidence_ref"]
