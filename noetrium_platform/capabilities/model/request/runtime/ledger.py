from __future__ import annotations

import hashlib
import json
from contextlib import contextmanager
from dataclasses import asdict
from pathlib import Path

from noetrium_platform.capabilities.model._persisted import (
    exact_fields,
    integer,
    optional_text,
    text,
    text_pairs,
    text_tuple,
)
from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import ExecutionContext, ImmutableModelIdentity
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import InterprocessFileLock


_ENVELOPE_FIELDS = frozenset({
    "schema_version", "request_id", "context", "role", "model", "prompt_generation_id",
    "prompt_id", "prompt_digest", "request_body", "compiled_prompt", "tool_schema_bundle",
    "source_artifact_refs", "source_state_refs", "envelope_digest",
})
_CONTENT_REF_FIELDS = frozenset({"content_sha256", "size_bytes", "media_type"})
_CONTEXT_FIELDS = frozenset({
    "run_id", "trace_id", "span_id", "parent_span_id", "study_id", "condition_id",
    "lifetime_id", "branch_id", "task_id", "decision_cycle_id", "checkpoint_id",
    "operation_id", "component_id", "participant_generations", "platform_generation",
})
_MODEL_FIELDS = frozenset({
    "logical_name", "model_id", "revision", "engine", "engine_version", "dtype",
    "quantization", "context_length", "tokenizer_revision",
})


@contextmanager
def _exclusive_lock(path: Path):
    """Hold the platform-owned cross-process lock without duplicate OS code."""

    with InterprocessFileLock(path, blocking=True):
        yield


class DirectoryModelRequestLedger:
    """Append-only-by-identity request ledger: request_id may bind exactly one envelope."""

    durability = "crash_durable"

    def __init__(self, root: Path) -> None:
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe(request_id: str) -> str:
        return hashlib.sha256(request_id.encode("utf-8")).hexdigest()

    def _path(self, request_id: str) -> Path:
        return self.root / f"{self._safe(request_id)}.json"

    def _lock_path(self, request_id: str) -> Path:
        return self.root / f"{self._safe(request_id)}.lock"

    @staticmethod
    def _encode(envelope: ModelRequestEnvelope) -> bytes:
        return json.dumps(
            asdict(envelope), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")

    @staticmethod
    def _ref(value: object, *, field: str) -> ArtifactBlobRef:
        if value is None:
            raise ValueError(f"{field} is required")
        data = exact_fields(value, field=field, fields=_CONTENT_REF_FIELDS)
        return ArtifactBlobRef(
            content_sha256=text(data["content_sha256"], field=f"{field}.content_sha256", allow_empty=False),
            size_bytes=integer(data["size_bytes"], field=f"{field}.size_bytes", minimum=0),
            media_type=text(data["media_type"], field=f"{field}.media_type", allow_empty=False),
        )

    @classmethod
    def _optional_ref(cls, value: object, *, field: str) -> ArtifactBlobRef | None:
        return None if value is None else cls._ref(value, field=field)

    @staticmethod
    def _context(value: object) -> ExecutionContext:
        data = exact_fields(value, field="model request context", fields=_CONTEXT_FIELDS)
        return ExecutionContext(
            run_id=text(data["run_id"], field="context.run_id", allow_empty=False),
            trace_id=text(data["trace_id"], field="context.trace_id", allow_empty=False),
            span_id=text(data["span_id"], field="context.span_id", allow_empty=False),
            parent_span_id=optional_text(data["parent_span_id"], field="context.parent_span_id"),
            study_id=optional_text(data["study_id"], field="context.study_id"),
            condition_id=optional_text(data["condition_id"], field="context.condition_id"),
            lifetime_id=optional_text(data["lifetime_id"], field="context.lifetime_id"),
            branch_id=optional_text(data["branch_id"], field="context.branch_id"),
            task_id=optional_text(data["task_id"], field="context.task_id"),
            decision_cycle_id=optional_text(data["decision_cycle_id"], field="context.decision_cycle_id"),
            checkpoint_id=optional_text(data["checkpoint_id"], field="context.checkpoint_id"),
            operation_id=optional_text(data["operation_id"], field="context.operation_id"),
            component_id=optional_text(data["component_id"], field="context.component_id"),
            participant_generations=text_pairs(
                data["participant_generations"], field="context.participant_generations"
            ),
            platform_generation=optional_text(
                data["platform_generation"], field="context.platform_generation"
            ),
        )

    @staticmethod
    def _model(value: object) -> ImmutableModelIdentity:
        data = exact_fields(value, field="model identity", fields=_MODEL_FIELDS)
        return ImmutableModelIdentity(
            logical_name=text(data["logical_name"], field="model.logical_name", allow_empty=False),
            model_id=text(data["model_id"], field="model.model_id", allow_empty=False),
            revision=text(data["revision"], field="model.revision", allow_empty=False),
            engine=text(data["engine"], field="model.engine", allow_empty=False),
            engine_version=text(data["engine_version"], field="model.engine_version", allow_empty=False),
            dtype=text(data["dtype"], field="model.dtype", allow_empty=False),
            quantization=optional_text(data["quantization"], field="model.quantization"),
            context_length=integer(data["context_length"], field="model.context_length", minimum=1),
            tokenizer_revision=optional_text(
                data["tokenizer_revision"], field="model.tokenizer_revision"
            ),
        )

    @classmethod
    def _decode(cls, payload: bytes) -> ModelRequestEnvelope:
        data = exact_fields(
            json.loads(payload), field="model request envelope", fields=_ENVELOPE_FIELDS
        )
        return ModelRequestEnvelope(
            schema_version=text(data["schema_version"], field="schema_version", allow_empty=False),
            request_id=text(data["request_id"], field="request_id", allow_empty=False),
            context=cls._context(data["context"]),
            role=text(data["role"], field="role", allow_empty=False),
            model=cls._model(data["model"]),
            prompt_generation_id=text(
                data["prompt_generation_id"], field="prompt_generation_id", allow_empty=False
            ),
            prompt_id=text(data["prompt_id"], field="prompt_id", allow_empty=False),
            prompt_digest=text(data["prompt_digest"], field="prompt_digest", allow_empty=False),
            request_body=cls._ref(data["request_body"], field="request_body"),
            compiled_prompt=cls._optional_ref(
                data["compiled_prompt"], field="compiled_prompt"
            ),
            tool_schema_bundle=cls._optional_ref(
                data["tool_schema_bundle"], field="tool_schema_bundle"
            ),
            source_artifact_refs=text_tuple(
                data["source_artifact_refs"], field="source_artifact_refs"
            ),
            source_state_refs=text_tuple(data["source_state_refs"], field="source_state_refs"),
            envelope_digest=text(
                data["envelope_digest"], field="envelope_digest", allow_empty=False
            ),
        )

    def append(self, envelope: ModelRequestEnvelope) -> None:
        path = self._path(envelope.request_id)
        encoded = self._encode(envelope)
        lock_path = self._lock_path(envelope.request_id)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(lock_path):
            if path.exists():
                current = self._decode(path.read_bytes())
                if current != envelope:
                    raise RuntimeError("model request id is already bound to a different envelope")
                return
            atomic_replace_bytes(path, encoded)

    def get(self, request_id: str) -> ModelRequestEnvelope:
        envelope = self._decode(self._path(request_id).read_bytes())
        if envelope.request_id != request_id:
            raise RuntimeError("model request lookup identity mismatch")
        return envelope


__all__ = ["DirectoryModelRequestLedger"]
