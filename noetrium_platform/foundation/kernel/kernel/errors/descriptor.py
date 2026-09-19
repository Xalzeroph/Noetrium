from __future__ import annotations

import hashlib

from .contracts import SafeExceptionDescriptor
from .redaction import redact_text


def describe_exception(exc: BaseException) -> SafeExceptionDescriptor:
    kind = type(exc)
    qualified = f"{kind.__module__}.{kind.__qualname__}"
    safe_message = redact_text(str(exc))
    canonical = f"{qualified}:{safe_message}"
    return SafeExceptionDescriptor(
        error_type=kind.__qualname__,
        qualified_type=qualified,
        safe_message=safe_message,
        error_digest=hashlib.sha256(canonical.encode("utf-8", "replace")).hexdigest(),
    )


__all__ = ["describe_exception"]
