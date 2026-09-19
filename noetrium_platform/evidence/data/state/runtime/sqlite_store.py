from __future__ import annotations

from pathlib import Path

from noetrium_platform.evidence.data._canonical import DataCanonicalDecodingError
from noetrium_platform.evidence.data.state.api import AggregateValue, AtomicMutation, StateCorruptionError, StateVersionConflict
from .sqlite_backend import EncodedAggregate, SQLiteStateBackend
from .sqlite_codec import StatePayloadCodec, StrictJsonStatePayloadCodec, payload_sha256


class SQLiteAtomicStateStore:
    """Crash-durable AtomicStateStore over an isolated SQLite persistence backend."""

    def __init__(
        self,
        path: Path,
        initial: tuple[AggregateValue, ...] = (),
        *,
        codec: StatePayloadCodec | None = None,
        timeout_seconds: float = 30.0,
    ) -> None:
        if len({value.aggregate_id for value in initial}) != len(initial):
            raise ValueError("duplicate initial aggregate")
        self.codec = codec or StrictJsonStatePayloadCodec()
        self.backend = SQLiteStateBackend(path, timeout_seconds=timeout_seconds)
        self.backend.initialize(tuple(self._encode_value(value) for value in initial))

    def _encode_value(self, value: AggregateValue) -> EncodedAggregate:
        raw = self.codec.encode(value.payload)
        return EncodedAggregate(
            value.aggregate_id,
            value.version,
            value.generation,
            value.digest,
            raw,
            payload_sha256(raw),
        )

    def _decode_value(self, value: EncodedAggregate) -> AggregateValue:
        if payload_sha256(value.payload) != value.payload_sha256:
            raise StateCorruptionError(f"aggregate payload checksum mismatch: {value.aggregate_id}")
        try:
            payload = self.codec.decode(value.payload)
        except DataCanonicalDecodingError as exc:
            raise StateCorruptionError(
                f"aggregate payload cannot be decoded: {value.aggregate_id}"
            ) from exc
        return AggregateValue(
            value.aggregate_id,
            value.version,
            value.generation,
            value.digest,
            payload,
        )

    def read(self, aggregate_id: str) -> AggregateValue:
        row = self.backend.read(aggregate_id)
        if row is None:
            raise KeyError(f"unknown aggregate: {aggregate_id}")
        return self._decode_value(row)

    @staticmethod
    def _assert_precondition(current: AggregateValue, mutation: AtomicMutation) -> None:
        if current.version != mutation.expected_version or current.generation != mutation.expected_generation:
            raise StateVersionConflict(
                f"aggregate {mutation.aggregate_id} expected "
                f"v{mutation.expected_version}/{mutation.expected_generation}, "
                f"found v{current.version}/{current.generation}"
            )

    def _prepare(self, current: AggregateValue, mutation: AtomicMutation) -> AggregateValue:
        return AggregateValue(
            mutation.aggregate_id,
            current.version + 1,
            mutation.new_generation,
            mutation.new_digest,
            mutation.new_payload,
        )

    def commit_batch(self, mutations: tuple[AtomicMutation, ...]) -> tuple[AggregateValue, ...]:
        if not mutations:
            return ()
        if len({m.aggregate_id for m in mutations}) != len(mutations):
            raise ValueError("duplicate aggregate mutation in one atomic batch")
        with self.backend.write_session() as tx:
            current = self._load_current(tx, mutations)
            prepared = tuple(
                AggregateValue(
                    mutation.aggregate_id,
                    current[mutation.aggregate_id].version + 1,
                    mutation.new_generation,
                    mutation.new_digest,
                    mutation.new_payload,
                )
                for mutation in mutations
            )
            encoded_rows = tuple(
                (self._encode_value(value), mutation.expected_version, mutation.expected_generation)
                for mutation, value in zip(mutations, prepared, strict=True)
            )
            if not tx.update_many(encoded_rows):
                raise StateVersionConflict("aggregate changed during atomic batch commit")
            tx.commit()
            return prepared

    def _load_current(self, tx, mutations: tuple[AtomicMutation, ...]) -> dict[str, EncodedAggregate]:
        rows = tx.read_many(tuple(m.aggregate_id for m in mutations))
        current = {row.aggregate_id: row for row in rows}
        for mutation in mutations:
            row = current.get(mutation.aggregate_id)
            if row is None:
                raise KeyError(f"unknown aggregate: {mutation.aggregate_id}")
            if payload_sha256(row.payload) != row.payload_sha256:
                raise StateCorruptionError(f"aggregate payload checksum mismatch: {row.aggregate_id}")
            if row.version != mutation.expected_version or row.generation != mutation.expected_generation:
                raise StateVersionConflict(
                    f"aggregate {mutation.aggregate_id} expected "
                    f"v{mutation.expected_version}/{mutation.expected_generation}, "
                    f"found v{row.version}/{row.generation}"
                )
        return current
