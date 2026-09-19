from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    capability_request_digest,
)
from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.foundation.kernel.kernel import EffectClass, require_sha256
from noetrium_platform.research.experimentation.workbench.api import (
    CandidateProgramExecutionPort,
    CandidateProgramExecutionReceipt,
    CandidateProgramExecutionRequest,
    CandidateProgramIdentity,
    CandidateProgramMeasurementProjection,
    CandidateProgramMeasurementProjectionPort,
    CandidateProgramSourcePublicationPort,
)

_REQUEST_SCHEMA = "noetrium.candidate-program-capability.request.v1"
_RESULT_SCHEMA = "noetrium.candidate-program-capability.result.v1"


def candidate_program_capability_payload(
    *,
    candidate_id: str,
    generation: int,
    source_text: str,
    language: str,
    entrypoint: str,
    interface_schema_id: str,
    parent_candidate_digests: tuple[str, ...] = (),
) -> dict[str, object]:
    if not isinstance(candidate_id, str) or not candidate_id.strip():
        raise ValueError("candidate program candidate_id must be non-empty")
    if type(generation) is not int or generation < 0:
        raise ValueError("candidate program generation must be non-negative")
    for name, value in (
        ("source_text", source_text),
        ("language", language),
        ("entrypoint", entrypoint),
        ("interface_schema_id", interface_schema_id),
    ):
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"candidate program {name} must be non-empty")
    if type(parent_candidate_digests) is not tuple:
        raise TypeError("candidate program parent digests must be a tuple")
    for digest in parent_candidate_digests:
        require_sha256(digest, "candidate program parent digest")
    return {
        "candidate_id": candidate_id,
        "generation": generation,
        "source_text": source_text,
        "language": language,
        "entrypoint": entrypoint,
        "interface_schema_id": interface_schema_id,
        "parent_candidate_digests": parent_candidate_digests,
    }


class CandidateProgramCapabilityBinding:
    """Bind immutable source publication + isolated execution to MethodProgram.

    Benchmark/evaluator/isolation identities are fixed at composition time rather
    than supplied by the evolving method. This prevents a candidate-search method
    from changing its own scientific evaluation cut.

    Measurement values are read-only projections whose record digests must be
    present in the authoritative execution receipt.
    """

    def __init__(
        self,
        *,
        source_publisher: CandidateProgramSourcePublicationPort,
        executor: CandidateProgramExecutionPort,
        measurement_projection: CandidateProgramMeasurementProjectionPort,
        benchmark_cut_digest: str,
        evaluator_digest: str,
        isolation_requirement_id: str,
        measurement_ids: tuple[str, ...],
        resource_requirement_digest: str | None = None,
        capability_id: str = "workbench.candidate-program.execute",
    ) -> None:
        for name, value in (
            ("source_publisher.publish_source", getattr(source_publisher, "publish_source", None)),
            ("executor.execute", getattr(executor, "execute", None)),
            ("measurement_projection.project", getattr(measurement_projection, "project", None)),
        ):
            if not callable(value):
                raise TypeError(f"candidate program binding requires {name}")
        require_sha256(benchmark_cut_digest, "candidate program benchmark_cut_digest")
        require_sha256(evaluator_digest, "candidate program evaluator_digest")
        if resource_requirement_digest is not None:
            require_sha256(
                resource_requirement_digest,
                "candidate program resource_requirement_digest",
            )
        if not isinstance(isolation_requirement_id, str) or not isolation_requirement_id.strip():
            raise ValueError("candidate program isolation_requirement_id must be non-empty")
        if (
            type(measurement_ids) is not tuple
            or not measurement_ids
            or any(not isinstance(row, str) or not row.strip() for row in measurement_ids)
            or len(measurement_ids) != len(set(measurement_ids))
        ):
            raise ValueError("candidate program measurement_ids must be unique non-empty tuple")
        if not isinstance(capability_id, str) or not capability_id.strip():
            raise ValueError("candidate program capability_id must be non-empty")

        self._source_publisher = source_publisher
        self._executor = executor
        self._measurement_projection = measurement_projection
        self._benchmark_cut_digest = benchmark_cut_digest
        self._evaluator_digest = evaluator_digest
        self._isolation_requirement_id = isolation_requirement_id
        self._measurement_ids = measurement_ids
        self._resource_requirement_digest = resource_requirement_digest
        self._cache: dict[str, CapabilityResult] = {}
        self._descriptor = CapabilityDescriptor(
            capability_id=capability_id,
            interface_version="1",
            request_schema=_REQUEST_SCHEMA,
            result_schema=_RESULT_SCHEMA,
            effect_class=EffectClass.IDEMPOTENT,
            deterministic=False,
        )

    @property
    def capabilities(self) -> tuple[CapabilityDescriptor, ...]:
        return (self._descriptor,)

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        if capability_id != self._descriptor.capability_id:
            raise KeyError(capability_id)
        return self._descriptor

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        if request.capability_id != self._descriptor.capability_id:
            raise KeyError(request.capability_id)
        if not isinstance(request.payload, Mapping):
            raise TypeError("candidate program capability payload must be a mapping")
        request_digest = capability_request_digest(request)
        cached = self._cache.get(request_digest)
        if cached is not None:
            return cached

        candidate_id = self._text(request.payload.get("candidate_id"), "candidate_id")
        generation = request.payload.get("generation")
        if type(generation) is not int or generation < 0:
            raise ValueError("candidate program generation must be non-negative")
        source_text = self._text(request.payload.get("source_text"), "source_text")
        language = self._text(request.payload.get("language"), "language")
        entrypoint = self._text(request.payload.get("entrypoint"), "entrypoint")
        interface_schema_id = self._text(
            request.payload.get("interface_schema_id"),
            "interface_schema_id",
        )
        raw_parents = request.payload.get("parent_candidate_digests", ())
        if not isinstance(raw_parents, Sequence) or isinstance(
            raw_parents, (str, bytes, bytearray)
        ):
            raise TypeError("candidate program parent digests must be a sequence")
        parents = tuple(raw_parents)
        if any(not isinstance(row, str) for row in parents):
            raise TypeError("candidate program parent digests must contain strings")
        for digest in parents:
            require_sha256(digest, "candidate program parent digest")

        source = self._source_publisher.publish_source(
            candidate_id=candidate_id,
            generation=generation,
            language=language,
            source_text=source_text,
        )
        if not isinstance(source, ArtifactContentIdentity):
            raise TypeError("candidate source publisher must return ArtifactContentIdentity")

        candidate = CandidateProgramIdentity(
            candidate_id=candidate_id,
            generation=generation,
            source=source,
            language=language,
            entrypoint=entrypoint,
            interface_schema_id=interface_schema_id,
            parent_candidate_digests=parents,
        )
        execution_request = CandidateProgramExecutionRequest(
            candidate=candidate,
            benchmark_cut_digest=self._benchmark_cut_digest,
            evaluator_digest=self._evaluator_digest,
            isolation_requirement_id=self._isolation_requirement_id,
            resource_requirement_digest=self._resource_requirement_digest,
        )
        receipt = self._executor.execute(execution_request)
        if not isinstance(receipt, CandidateProgramExecutionReceipt):
            raise TypeError("candidate executor must return CandidateProgramExecutionReceipt")
        if receipt.request_digest != execution_request.request_digest:
            raise ValueError("candidate execution receipt request identity mismatch")

        projections = self._measurement_projection.project(
            receipt,
            measurement_ids=self._measurement_ids,
        )
        if type(projections) is not tuple or any(
            not isinstance(row, CandidateProgramMeasurementProjection)
            for row in projections
        ):
            raise TypeError("candidate measurement projection returned invalid rows")
        by_id = {row.measurement_id: row for row in projections}
        if len(by_id) != len(projections):
            raise ValueError("candidate measurement projections contain duplicate ids")
        if receipt.status.value == "succeeded":
            if set(by_id) != set(self._measurement_ids):
                raise ValueError("successful candidate execution is missing requested measurements")
        elif projections:
            raise ValueError("failed/rejected candidate execution cannot project measurements")
        allowed_records = set(receipt.measurement_record_digests)
        if any(row.record_digest not in allowed_records for row in projections):
            raise ValueError("candidate measurement projection references foreign record digest")

        result = CapabilityResult(
            capability_id=self._descriptor.capability_id,
            payload={
                "candidate_id": candidate.candidate_id,
                "candidate_digest": candidate.candidate_digest,
                "source_artifact_id": source.artifact_id,
                "source_content_sha256": source.content_sha256,
                "execution_request_digest": execution_request.request_digest,
                "execution_receipt_digest": receipt.receipt_digest,
                "status": receipt.status.value,
                "failure_code": receipt.failure_code,
                "measurements": tuple(
                    {
                        "measurement_id": row.measurement_id,
                        "record_digest": row.record_digest,
                        "scalar": float(row.scalar),
                    }
                    for row in projections
                ),
                "measurement_record_digests": receipt.measurement_record_digests,
                "evidence_digests": receipt.evidence_digests,
                "isolation_evidence_digests": receipt.isolation_evidence_digests,
            },
            artifacts=tuple(row.artifact_id for row in receipt.output_artifacts),
            diagnostics={
                "benchmark_cut_digest": self._benchmark_cut_digest,
                "evaluator_digest": self._evaluator_digest,
                "isolation_requirement_id": self._isolation_requirement_id,
            },
            request_digest=request_digest,
        )
        self._cache[request_digest] = result
        return result

    @staticmethod
    def _text(value: object, field: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"candidate program {field} must be non-empty text")
        return value


__all__ = [
    "CandidateProgramCapabilityBinding",
    "candidate_program_capability_payload",
]
