from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import require_sha256
from noetrium_platform.foundation.kernel.unit import NoetriumUnit

from .failure_units import failure_field, is_failure_record


def _refs(failure: NoetriumUnit, name: str) -> tuple[str, ...]:
    value = failure_field(failure, name)
    if type(value) is not tuple or any(
        type(item) is not str or not item.strip() for item in value
    ):
        raise TypeError(f"failure {name} projection must be tuple[str, ...]")
    return tuple(dict.fromkeys(item.strip() for item in value))


@dataclass(frozen=True, slots=True)
class FailureReference:
    failure_id: str
    failure_unit_digest: str
    request_refs: tuple[str, ...] = ()
    effect_refs: tuple[str, ...] = ()
    state_refs: tuple[str, ...] = ()
    evidence_refs: tuple[str, ...] = ()
    artifact_refs: tuple[str, ...] = ()
    correlation_refs: tuple[str, ...] = ()
    causal_event_refs: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if type(self.failure_id) is not str or not self.failure_id.strip():
            raise ValueError("FailureReference failure_id is required")
        require_sha256(
            self.failure_unit_digest,
            "FailureReference failure_unit_digest",
        )
        for name in (
            "request_refs",
            "effect_refs",
            "state_refs",
            "evidence_refs",
            "artifact_refs",
            "correlation_refs",
            "causal_event_refs",
        ):
            values = getattr(self, name)
            if type(values) is not tuple or any(
                type(item) is not str or not item.strip() for item in values
            ):
                raise TypeError(f"FailureReference {name} must be tuple[str, ...]")
            if len(values) != len(set(values)):
                raise ValueError(f"FailureReference {name} must be unique")

    @property
    def lower_refs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((
            *(f"request:{value}" for value in self.request_refs),
            *(f"effect:{value}" for value in self.effect_refs),
            *(f"state:{value}" for value in self.state_refs),
            *(f"correlation:{value}" for value in self.correlation_refs),
            *(f"causal-event:{value}" for value in self.causal_event_refs),
        )))

    @property
    def graph_evidence_refs(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((
            "failure-unit:" + self.failure_unit_digest,
            *(f"evidence:{value}" for value in self.evidence_refs),
            *(f"artifact:{value}" for value in self.artifact_refs),
        )))


def failure_reference(failure: NoetriumUnit) -> FailureReference:
    if not is_failure_record(failure):
        raise TypeError("failure_reference requires reliability.failure Event Unit")
    return FailureReference(
        failure_id=str(failure_field(failure, "failure_id")),
        failure_unit_digest=failure.unit_digest,
        request_refs=_refs(failure, "request_refs"),
        effect_refs=_refs(failure, "effect_refs"),
        state_refs=_refs(failure, "state_refs"),
        evidence_refs=_refs(failure, "evidence_refs"),
        artifact_refs=_refs(failure, "artifact_refs"),
        correlation_refs=_refs(failure, "correlation_refs"),
        causal_event_refs=_refs(failure, "causal_event_refs"),
    )


__all__ = ["FailureReference", "failure_reference"]
