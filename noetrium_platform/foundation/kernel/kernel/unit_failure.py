from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


def _text_tuple(value: object, name: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if not isinstance(value, (tuple, list)):
        raise TypeError(f"{name} must be a sequence")
    rows = tuple(str(item).strip() for item in value)
    if any(not item for item in rows):
        raise ValueError(f"{name} cannot contain blank refs")
    return tuple(dict.fromkeys(rows))


@dataclass(frozen=True, slots=True)
class ExceptionReferenceProjection:
    request_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    state_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()

    def merged(self, other: "ExceptionReferenceProjection") -> "ExceptionReferenceProjection":
        if not isinstance(other, ExceptionReferenceProjection):
            raise TypeError("exception reference merge requires typed projection")
        return ExceptionReferenceProjection(
            request_refs=tuple(dict.fromkeys((*self.request_refs, *other.request_refs))),
            effect_refs=tuple(dict.fromkeys((*self.effect_refs, *other.effect_refs))),
            state_refs=tuple(dict.fromkeys((*self.state_refs, *other.state_refs))),
            evidence_refs=tuple(dict.fromkeys((*self.evidence_refs, *other.evidence_refs))),
            artifact_refs=tuple(dict.fromkeys((*self.artifact_refs, *other.artifact_refs))),
            correlation_refs=tuple(dict.fromkeys((*self.correlation_refs, *other.correlation_refs))),
        )


def exception_reference_projection(exc: BaseException) -> ExceptionReferenceProjection:
    """Project explicit structured refs from a complete exception causal graph."""

    if not isinstance(exc, BaseException):
        raise TypeError("exception reference projection requires BaseException")
    result = ExceptionReferenceProjection()
    seen: set[int] = set()
    pending: list[BaseException] = [exc]
    while pending:
        current = pending.pop()
        if id(current) in seen:
            continue
        seen.add(id(current))
        reference = getattr(current, "failure_reference", None)

        def values(name: str, *aliases: str) -> tuple[str, ...]:
            for candidate in (name, *aliases):
                raw = getattr(current, candidate, None)
                if raw is not None:
                    return _text_tuple(raw, f"exception {candidate}")
                if reference is not None:
                    raw = getattr(reference, candidate, None)
                    if raw is not None:
                        return _text_tuple(raw, f"failure reference {candidate}")
            return ()

        result = result.merged(
            ExceptionReferenceProjection(
                request_refs=values("request_refs"),
                effect_refs=values("effect_refs", "effect_intent_refs"),
                state_refs=values("state_refs"),
                evidence_refs=values("evidence_refs"),
                artifact_refs=values("artifact_refs"),
                correlation_refs=values(
                    "correlation_refs",
                    "failure_correlation_refs",
                ),
            )
        )
        if isinstance(current, BaseExceptionGroup):
            pending.extend(reversed(current.exceptions))
        cause = (
            current.__cause__
            if current.__cause__ is not None
            else (None if current.__suppress_context__ else current.__context__)
        )
        if cause is not None:
            pending.append(cause)
    return result


class UnitExecutionFailure(RuntimeError):
    """Typed projection of one durable Universal Unit terminal failure."""

    def __init__(
        self,
        surface: str,
        *,
        code: str,
        message: str,
        error_digest: str | None = None,
        cursor: str | None = None,
        visit: int | None = None,
        traceback_tail: tuple[str, ...] = (),
        request_refs: tuple[str, ...] = (),
        effect_refs: tuple[str, ...] = (),
        state_refs: tuple[str, ...] = (),
        evidence_refs: tuple[str, ...] = (),
        artifact_refs: tuple[str, ...] = (),
        correlation_refs: tuple[str, ...] = (),
        child_link_refs: tuple[str, ...] = (),
    ) -> None:
        if type(surface) is not str or not surface.strip():
            raise ValueError("UnitExecutionFailure surface is required")
        if type(code) is not str or not code.strip():
            raise ValueError("UnitExecutionFailure code is required")
        if type(message) is not str:
            raise TypeError("UnitExecutionFailure message must be text")
        self.surface = surface.strip()
        self.code = code.strip()
        self.error_digest = None if error_digest is None else str(error_digest)
        self.cursor = None if cursor is None else str(cursor)
        self.visit = visit
        self.traceback_tail = tuple(traceback_tail)
        self.request_refs = tuple(request_refs)
        self.effect_refs = tuple(effect_refs)
        self.state_refs = tuple(state_refs)
        self.evidence_refs = tuple(evidence_refs)
        self.artifact_refs = tuple(artifact_refs)
        self.correlation_refs = tuple(
            dict.fromkeys((*correlation_refs, *child_link_refs))
        )
        self.child_link_refs = tuple(child_link_refs)
        detail = f"{self.surface} failed code={self.code}"
        if self.cursor is not None:
            detail += f" cursor={self.cursor}"
        if message:
            detail += f": {message}"
        if self.error_digest is not None:
            detail += f" [error_digest={self.error_digest}]"
        super().__init__(detail)

    @property
    def failure_correlation_refs(self) -> tuple[str, ...]:
        return self.correlation_refs


def unit_execution_failure(
    semantic_state: Mapping[str, object],
    *,
    surface: str,
) -> UnitExecutionFailure:
    """Decode the sole durable Universal Unit failure carrier."""

    if not isinstance(semantic_state, Mapping):
        raise TypeError("unit failure semantic state must be a mapping")
    raw = semantic_state.get("unit_failure")
    if not isinstance(raw, Mapping):
        raise RuntimeError(
            f"{surface} entered FAILED state without durable unit_failure"
        )
    code = raw.get("code")
    message = raw.get("message")
    if type(code) is not str or type(message) is not str:
        raise TypeError("durable unit_failure lost code/message")
    visit = raw.get("visit")
    if visit is not None and type(visit) is not int:
        raise TypeError("durable unit_failure visit must be integer or null")
    return UnitExecutionFailure(
        surface,
        code=code,
        message=message,
        error_digest=(
            None
            if raw.get("error_digest") is None
            else str(raw["error_digest"])
        ),
        cursor=None if raw.get("cursor") is None else str(raw["cursor"]),
        visit=visit,
        traceback_tail=_text_tuple(raw.get("traceback_tail", ()), "traceback_tail"),
        request_refs=_text_tuple(raw.get("request_refs", ()), "request_refs"),
        effect_refs=_text_tuple(raw.get("effect_refs", ()), "effect_refs"),
        state_refs=_text_tuple(raw.get("state_refs", ()), "state_refs"),
        evidence_refs=_text_tuple(raw.get("evidence_refs", ()), "evidence_refs"),
        artifact_refs=_text_tuple(raw.get("artifact_refs", ()), "artifact_refs"),
        correlation_refs=_text_tuple(raw.get("correlation_refs", ()), "correlation_refs"),
        child_link_refs=_text_tuple(raw.get("child_link_refs", ()), "child_link_refs"),
    )


__all__ = [
    "ExceptionReferenceProjection",
    "UnitExecutionFailure",
    "exception_reference_projection",
    "unit_execution_failure",
]
