from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class FailureCorrelationSource(Protocol):
    @property
    def failure_correlation_refs(self) -> tuple[str, ...]: ...


def exception_correlation_refs(exc: BaseException) -> tuple[str, ...]:
    """Collect safe, explicit correlation refs from an exception cause chain.

    Domain exceptions opt in by exposing ``failure_correlation_refs``.  The failure
    platform never imports domain exception classes and never serializes arbitrary
    exception attributes.
    """

    refs: list[str] = []
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, FailureCorrelationSource):
            values = current.failure_correlation_refs
            if not isinstance(values, tuple) or any(not isinstance(value, str) for value in values):
                raise TypeError("failure_correlation_refs must be tuple[str, ...]")
            refs.extend(value for value in values if value)
        current = current.__cause__ if current.__cause__ is not None else current.__context__
    return tuple(dict.fromkeys(refs))


__all__ = ["FailureCorrelationSource", "exception_correlation_refs"]
