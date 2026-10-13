from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    exception_reference_projection,
)
from noetrium_platform.infrastructure.reliability.failure.api import (
    FailureReference,
    FailureSpec,
    failure_reference,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime.recorder import (
    FailureRecorder,
)


class ForensicFailureMaterializer:
    """Adjacent-layer projection from one exception chain to one Failure Unit ref."""

    def __init__(self, recorder: FailureRecorder) -> None:
        if not isinstance(recorder, FailureRecorder):
            raise TypeError(
                "forensic failure materializer requires FailureRecorder"
            )
        self._recorder = recorder

    def materialize(
        self,
        *,
        spec: FailureSpec,
        component_id: str,
        context: ExecutionContext,
        exc: BaseException,
        correlation_refs: tuple[str, ...] = (),
    ) -> FailureReference:
        refs = exception_reference_projection(exc)
        outcome = self._recorder.record(
            spec=spec,
            component_id=component_id,
            context=context,
            exc=exc,
            request_refs=refs.request_refs,
            effect_refs=refs.effect_refs,
            state_refs=refs.state_refs,
            evidence_refs=refs.evidence_refs,
            artifact_refs=refs.artifact_refs,
            correlation_refs=tuple(
                dict.fromkeys((*correlation_refs, *refs.correlation_refs))
            ),
        )
        return failure_reference(outcome.failure)


__all__ = ["ForensicFailureMaterializer"]
