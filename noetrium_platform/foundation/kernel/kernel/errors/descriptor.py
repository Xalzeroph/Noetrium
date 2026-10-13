from __future__ import annotations

import hashlib
from pathlib import Path
import traceback

from .contracts import SafeExceptionDescriptor
from .redaction import redact_text


_MAX_GROUP_LEAF_KINDS = 16


def exception_leaves(exc: BaseException) -> tuple[BaseException, ...]:
    """Flatten one exception tree into deterministic left-to-right leaves."""

    if not isinstance(exc, BaseExceptionGroup):
        return (exc,)
    rows: list[BaseException] = []
    stack: list[BaseException] = list(reversed(exc.exceptions))
    while stack:
        current = stack.pop()
        if isinstance(current, BaseExceptionGroup):
            stack.extend(reversed(current.exceptions))
        else:
            rows.append(current)
    return tuple(rows)


def _cause_summary(exc: BaseException, *, max_depth: int = 4) -> str:
    rows: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    depth = 0
    while current is not None and id(current) not in seen and depth < max_depth:
        seen.add(id(current))
        if depth:
            kind = type(current)
            rows.append(
                f"{kind.__module__}.{kind.__qualname__}: "
                f"{redact_text(str(current), max_chars=512)}"
            )
        if current.__cause__ is not None:
            current = current.__cause__
        elif not current.__suppress_context__:
            current = current.__context__
        else:
            current = None
        depth += 1
    return " <- ".join(rows)


def _terminal_frame(exc: BaseException) -> str:
    frames = traceback.extract_tb(exc.__traceback__)
    if not frames:
        return ""
    frame = frames[-1]
    return (
        f"{Path(frame.filename).name}:{frame.lineno}:"
        f"{redact_text(frame.name, max_chars=128)}"
    )


def _leaf_descriptor(exc: BaseException) -> SafeExceptionDescriptor:
    kind = type(exc)
    qualified = f"{kind.__module__}.{kind.__qualname__}"
    safe_message = redact_text(str(exc))
    notes = tuple(
        redact_text(note, max_chars=512)
        for note in getattr(exc, "__notes__", ())
        if str(note).strip()
    )
    if notes:
        safe_message = redact_text(
            safe_message + " | notes: " + " ; ".join(notes)
        )
    canonical = f"{qualified}:{safe_message}"
    return SafeExceptionDescriptor(
        error_type=kind.__qualname__,
        qualified_type=qualified,
        safe_message=safe_message,
        error_digest=hashlib.sha256(
            canonical.encode("utf-8", "replace")
        ).hexdigest(),
    )


def _group_leaf_summary(exc: BaseException) -> str:
    descriptor = _leaf_descriptor(exc)
    parts = [f"{descriptor.qualified_type}: {descriptor.safe_message}"]
    frame = _terminal_frame(exc)
    if frame:
        parts.append(f"at {frame}")
    cause = _cause_summary(exc)
    if cause:
        parts.append(f"caused by {cause}")
    return " | ".join(parts)


def describe_exception(exc: BaseException) -> SafeExceptionDescriptor:
    """Return one safe deterministic descriptor, including ExceptionGroup leaves."""

    if not isinstance(exc, BaseExceptionGroup):
        return _leaf_descriptor(exc)

    kind = type(exc)
    qualified = f"{kind.__module__}.{kind.__qualname__}"
    leaves = exception_leaves(exc)
    grouped: dict[str, int] = {}
    for leaf in leaves:
        key = _group_leaf_summary(leaf)
        grouped[key] = grouped.get(key, 0) + 1

    parts = [
        redact_text(str(exc), max_chars=512),
        f"exception_group_leaves={len(leaves)}",
        f"exception_group_leaf_kinds={len(grouped)}",
    ]
    ordered = sorted(
        grouped.items(),
        key=lambda item: (-item[1], item[0]),
    )
    for leaf_summary, count in ordered[:_MAX_GROUP_LEAF_KINDS]:
        parts.append(f"x{count} {leaf_summary}")
    omitted = len(ordered) - _MAX_GROUP_LEAF_KINDS
    if omitted > 0:
        parts.append(f"leaf_kinds_omitted={omitted}")

    safe_message = redact_text(" | ".join(parts))
    canonical = f"{qualified}:{safe_message}"
    return SafeExceptionDescriptor(
        error_type=kind.__qualname__,
        qualified_type=qualified,
        safe_message=safe_message,
        error_digest=hashlib.sha256(
            canonical.encode("utf-8", "replace")
        ).hexdigest(),
    )


__all__ = ["describe_exception", "exception_leaves"]
