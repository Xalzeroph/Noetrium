from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model._persisted import (
    exact_fields,
    integer,
    optional_text,
    text,
    text_pairs,
    text_tuple,
)
from noetrium_platform.capabilities.model.request.api import (
    ModelEndpointEnvelope, ModelOperationEnvelope, ModelRequestEnvelope,
)
from noetrium_platform.substrate.api import ArtifactBlobRef
from noetrium_platform.foundation.kernel.kernel import (
    DurableSQLiteWriterOwner,
    ExecutionContext,
    ImmutableModelIdentity,
    canonical_bytes,
    execution_context_from_payload,
    immediate_sqlite_transaction,
)


_REQUEST_ENVELOPE_FIELDS = frozenset({
    "schema_version", "request_id", "context", "role", "model", "prompt_generation_id",
    "prompt_id", "prompt_digest", "request_body", "compiled_prompt", "tool_schema_bundle",
    "source_artifact_refs", "source_state_refs", "envelope_digest",
})

_OPERATION_ENVELOPE_FIELDS = frozenset({
    "schema_version", "request_id", "context", "role", "model", "capability_id",
    "input_schema_id", "output_schema_id", "request_body",
    "source_artifact_refs", "source_state_refs", "envelope_digest",
})
_CONTENT_REF_FIELDS = frozenset({"content_sha256", "size_bytes", "media_type"})
_MODEL_FIELDS = frozenset({
    "logical_name", "model_id", "revision", "engine", "engine_version", "dtype",
    "quantization", "context_length", "tokenizer_revision",
})


class SQLiteModelRequestLedger:
    """Crash-durable append-only model request ledger backed by SQLite WAL."""

    durability = "crash_durable"
    _BUSY_TIMEOUT_MS = 30_000

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._writer = DurableSQLiteWriterOwner(
            self.path,
            timeout_seconds=self._BUSY_TIMEOUT_MS / 1000.0,
        )
        with self._writer.session() as connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS model_requests (
                    request_id TEXT PRIMARY KEY NOT NULL,
                    envelope_digest TEXT NOT NULL,
                    payload BLOB NOT NULL
                ) WITHOUT ROWID
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS model_requests_envelope_digest "
                "ON model_requests(envelope_digest)"
            )

    @staticmethod
    def _encode(envelope: ModelEndpointEnvelope) -> bytes:
        return canonical_bytes(envelope)

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
        return execution_context_from_payload(value)  # type: ignore[arg-type]

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
    def _decode(cls, payload: bytes) -> ModelEndpointEnvelope:
        raw = json.loads(payload)
        if not isinstance(raw, dict):
            raise ValueError("model invocation envelope must be an object")
        schema = raw.get("schema_version")
        if schema in {"model-request.v1", "runtime-canary-request.v1"}:
            data = exact_fields(
                raw,
                field="model request envelope",
                fields=_REQUEST_ENVELOPE_FIELDS,
            )
            return ModelRequestEnvelope(
                schema_version=text(
                    data["schema_version"],
                    field="schema_version",
                    allow_empty=False,
                ),
                request_id=text(
                    data["request_id"],
                    field="request_id",
                    allow_empty=False,
                ),
                context=cls._context(data["context"]),
                role=text(data["role"], field="role", allow_empty=False),
                model=cls._model(data["model"]),
                prompt_generation_id=text(
                    data["prompt_generation_id"],
                    field="prompt_generation_id",
                    allow_empty=False,
                ),
                prompt_id=text(
                    data["prompt_id"],
                    field="prompt_id",
                    allow_empty=False,
                ),
                prompt_digest=text(
                    data["prompt_digest"],
                    field="prompt_digest",
                    allow_empty=False,
                ),
                request_body=cls._ref(
                    data["request_body"], field="request_body"
                ),
                compiled_prompt=cls._optional_ref(
                    data["compiled_prompt"], field="compiled_prompt"
                ),
                tool_schema_bundle=cls._optional_ref(
                    data["tool_schema_bundle"],
                    field="tool_schema_bundle",
                ),
                source_artifact_refs=text_tuple(
                    data["source_artifact_refs"],
                    field="source_artifact_refs",
                ),
                source_state_refs=text_tuple(
                    data["source_state_refs"],
                    field="source_state_refs",
                ),
                envelope_digest=text(
                    data["envelope_digest"],
                    field="envelope_digest",
                    allow_empty=False,
                ),
            )
        if schema in {"model-operation.v1", "runtime-canary-operation.v1"}:
            data = exact_fields(
                raw,
                field="model operation envelope",
                fields=_OPERATION_ENVELOPE_FIELDS,
            )
            return ModelOperationEnvelope(
                schema_version=text(
                    data["schema_version"],
                    field="schema_version",
                    allow_empty=False,
                ),
                request_id=text(
                    data["request_id"],
                    field="request_id",
                    allow_empty=False,
                ),
                context=cls._context(data["context"]),
                role=text(data["role"], field="role", allow_empty=False),
                model=cls._model(data["model"]),
                capability_id=text(
                    data["capability_id"],
                    field="capability_id",
                    allow_empty=False,
                ),
                input_schema_id=text(
                    data["input_schema_id"],
                    field="input_schema_id",
                    allow_empty=False,
                ),
                output_schema_id=text(
                    data["output_schema_id"],
                    field="output_schema_id",
                    allow_empty=False,
                ),
                request_body=cls._ref(
                    data["request_body"], field="request_body"
                ),
                source_artifact_refs=text_tuple(
                    data["source_artifact_refs"],
                    field="source_artifact_refs",
                ),
                source_state_refs=text_tuple(
                    data["source_state_refs"],
                    field="source_state_refs",
                ),
                envelope_digest=text(
                    data["envelope_digest"],
                    field="envelope_digest",
                    allow_empty=False,
                ),
            )
        raise ValueError(f"unsupported model invocation schema_version: {schema!r}")

    def append(self, envelope: ModelEndpointEnvelope) -> None:
        if not isinstance(
            envelope,
            (ModelRequestEnvelope, ModelOperationEnvelope),
        ):
            raise TypeError(
                "model invocation ledger requires request/operation envelope"
            )
        encoded = self._encode(envelope)
        request_id = envelope.request_id
        envelope_digest = envelope.envelope_digest

        with self._writer.session() as connection:
            row = connection.execute(
                "SELECT envelope_digest, payload FROM model_requests "
                "WHERE request_id = ?",
                (request_id,),
            ).fetchone()
            if row is not None:
                current = self._decode(bytes(row[1]))
                if row[0] != envelope_digest or current != envelope:
                    raise RuntimeError(
                        "model request id is already bound to a different envelope"
                    )
                return

            with immediate_sqlite_transaction(
                connection,
                timeout_seconds=self._BUSY_TIMEOUT_MS / 1000.0,
                label="model request ledger append",
            ):
                row = connection.execute(
                    "SELECT envelope_digest, payload FROM model_requests "
                    "WHERE request_id = ?",
                    (request_id,),
                ).fetchone()
                if row is not None:
                    current = self._decode(bytes(row[1]))
                    if row[0] != envelope_digest or current != envelope:
                        raise RuntimeError(
                            "model request id is already bound to a different envelope"
                        )
                else:
                    connection.execute(
                        "INSERT INTO model_requests"
                        "(request_id, envelope_digest, payload) VALUES (?, ?, ?)",
                        (request_id, envelope_digest, encoded),
                    )

    def get(self, request_id: str) -> ModelEndpointEnvelope:
        if type(request_id) is not str or not request_id:
            raise ValueError("model request ledger request_id is required")
        with self._writer.session() as connection:
            row = connection.execute(
                "SELECT envelope_digest, payload FROM model_requests "
                "WHERE request_id = ?",
                (request_id,),
            ).fetchone()
        if row is None:
            raise KeyError(f"model request ledger has no request: {request_id}")
        envelope = self._decode(bytes(row[1]))
        if envelope.request_id != request_id:
            raise RuntimeError("model request lookup identity mismatch")
        if envelope.envelope_digest != row[0]:
            raise RuntimeError("model request ledger indexed digest drift")
        return envelope

    def close(self) -> None:
        self._writer.close()



__all__ = ["SQLiteModelRequestLedger"]
