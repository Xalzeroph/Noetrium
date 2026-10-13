from __future__ import annotations

import hashlib
from pathlib import Path
from threading import Lock, Event
from dataclasses import dataclass, field
import time

from noetrium_platform.foundation.kernel.concurrency.api import Deadline, SerialActorPort, TaskGroupPort, TaskHandlePort
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    canonical_bytes,
    strict_json_loads,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception

from ..api.contracts import RawObservationReceipt, RawObservationSchema
from .segment_codec import RawSegmentCodecError, canonical_record_bytes, decode_record_json, encode_record
from .segment_pool import RawSegmentPool
from .segment_recovery import scan_raw_segment
from .segment_writer import RawSegmentWriter


@dataclass(slots=True)
class _RawCommitBatch:
    """One actor-owned group commit; callers join before the actor starts."""

    schema_version: str
    records: list[dict[str, object]] = field(default_factory=list)
    handle: TaskHandlePort[tuple[RawObservationReceipt, ...]] | None = None
    ready: Event = field(default_factory=Event)
    submission_error: BaseException | None = None


class FileRawObservationPersistence:
    """Filesystem-backed raw observation persistence with actor-owned writers."""

    def __init__(self, root: Path, *, task_group: TaskGroupPort) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self._pool = RawSegmentPool(root)
        self._task_group = task_group
        self._actors_lock = Lock()
        self._close_lock = Lock()
        self._actors: dict[tuple[str, str], SerialActorPort] = {}
        self._close_pending: dict[tuple[str, str], RawSegmentWriter] = {}
        self._closed = False
        self._commit_lock = Lock()
        self._pending_commits: dict[tuple[str, str], _RawCommitBatch] = {}
        self._max_commit_records = 64

    @staticmethod
    def _context_payload(context: ExecutionContext) -> JsonObject:
        if not isinstance(context, ExecutionContext):
            raise TypeError("raw observation context must be ExecutionContext")
        payload = strict_json_loads(canonical_bytes(context))
        if type(payload) is not dict:
            raise TypeError("canonical ExecutionContext projection must be an object")
        return payload

    @staticmethod
    def _actor_suffix(run_id: str, family: str) -> str:
        return hashlib.sha256(f"{run_id}\x00{family}".encode("utf-8")).hexdigest()

    def _actor_for(self, run_id: str, family: str) -> SerialActorPort:
        key = (run_id, family)
        with self._actors_lock:
            if self._closed:
                raise RuntimeError("raw observation persistence is closed")
            actor = self._actors.get(key)
            if actor is None:
                suffix = self._actor_suffix(run_id, family)
                actor = self._task_group.open_serial_actor(
                    f"raw-segment:{suffix}",
                    lane_id=f"raw-segment:{suffix}",
                )
                self._actors[key] = actor
            return actor

    def append(
        self,
        context: ExecutionContext,
        schema: RawObservationSchema,
        payload: JsonObject,
        *,
        timestamp: float | None,
        idempotency_key: str | None,
    ) -> RawObservationReceipt:
        return self.append_many(((
            context, schema, payload, timestamp, idempotency_key,
        ),))[0]

    def append_many(
        self,
        records: tuple[tuple[
            ExecutionContext, RawObservationSchema, JsonObject,
            float | None, str | None,
        ], ...],
    ) -> tuple[RawObservationReceipt, ...]:
        """Submit independent segment writers before joining durable receipts.

        Durable Actor fsync guarantees and per-family idempotence are retained.
        A failed submission still joins all previously admitted side effects
        before propagating an error; no receipt is returned before fsync.
        """
        pending: list[tuple[_RawCommitBatch, int]] = []
        failures: list[BaseException] = []
        for context, schema, payload, timestamp, idempotency_key in records:
            try:
                pending.append(self._submit_append(
                    context, schema, payload,
                    timestamp=timestamp, idempotency_key=idempotency_key,
                ))
            except BaseException as exc:
                failures.append(exc)
                break
        receipts: list[RawObservationReceipt] = []
        for batch, position in pending:
            try:
                batch.ready.wait()
                if batch.submission_error is not None:
                    raise batch.submission_error
                handle = batch.handle
                if handle is None:
                    raise RuntimeError("raw observation group commit has no owned task")
                receipts.append(handle.result()[position])
            except BaseException as exc:
                failures.append(exc)
        if failures:
            if len(failures) == 1:
                raise failures[0]
            raise BaseExceptionGroup("raw observation group commit failed", failures)
        return tuple(receipts)

    def _submit_append(
        self,
        context: ExecutionContext,
        schema: RawObservationSchema,
        payload: JsonObject,
        *,
        timestamp: float | None,
        idempotency_key: str | None,
    ) -> tuple[_RawCommitBatch, int]:
        resolved_timestamp = time.time() if timestamp is None else float(timestamp)
        context_payload = self._context_payload(context)
        preflight: dict[str, object] = {
            "sequence": 0,
            "timestamp": resolved_timestamp,
            "family": schema.family,
            "schema_version": schema.schema_version,
            "retention": schema.retention.value,
            "context": context_payload,
            "payload": dict(payload),
        }
        if idempotency_key is not None:
            preflight["idempotency_key"] = idempotency_key
        canonical_record_bytes(preflight)
        actor = self._actor_for(context.run_id, schema.family)
        key = (context.run_id, schema.family)

        def commit_owned(batch: _RawCommitBatch) -> tuple[RawObservationReceipt, ...]:
            # The serial actor owns the committed cut and exact segment writer.
            # Once it starts, new callers must join the next batch.
            with self._commit_lock:
                if self._pending_commits.get(key) is batch:
                    del self._pending_commits[key]
                entries = tuple(batch.records)
            segment = self._pool.get(context.run_id, schema.family, schema.schema_version)
            new_rows: list[tuple[bytes, RawObservationReceipt, str | None]] = []
            intra_batch: dict[str, RawObservationReceipt] = {}
            receipts: list[RawObservationReceipt] = []
            for preflight_record in entries:
                idem = preflight_record.get("idempotency_key")
                idempotency = str(idem) if idem is not None else None
                previous = None if idempotency is None else (
                    intra_batch.get(idempotency) or segment.previous(idempotency)
                )
                if previous is not None:
                    receipts.append(previous)
                    continue
                sequence = segment.sequence + len(new_rows) + 1
                record = dict(preflight_record)
                record["sequence"] = sequence
                encoded, digest = encode_record(record)
                receipt = RawObservationReceipt(
                    schema.family,
                    schema.schema_version,
                    context.run_id,
                    str(segment.target),
                    sequence,
                    digest,
                    len(encoded),
                )
                new_rows.append((encoded, receipt, idempotency))
                receipts.append(receipt)
                if idempotency is not None:
                    intra_batch[idempotency] = receipt
            segment.append_batch(tuple(new_rows))
            return tuple(receipts)

        with self._commit_lock:
            batch = self._pending_commits.get(key)
            if (
                batch is None
                or batch.schema_version != schema.schema_version
                or len(batch.records) >= self._max_commit_records
            ):
                batch = _RawCommitBatch(schema.schema_version)
                self._pending_commits[key] = batch
                created = True
            else:
                created = False
            position = len(batch.records)
            batch.records.append(preflight)
        # Never submit to a possibly bounded scheduler while holding the queue
        # lock needed by the actor's drain; this avoids a lock inversion when
        # the serial mailbox is saturated by many concurrent producers.
        if created:
            try:
                batch.handle = actor.submit("append-group-commit", commit_owned, batch)
            except BaseException as exc:
                with self._commit_lock:
                    if self._pending_commits.get(key) is batch:
                        del self._pending_commits[key]
                batch.submission_error = exc
                raise
            finally:
                batch.ready.set()
        # The owning Actor's completion is joined after independent writers
        # have been submitted; no per-record physical worker is created.
        return batch, position

    def verify(self, run_id: str, family: str) -> tuple[str, ...]:
        target = RawSegmentPool.target(self.root, run_id, family)
        actor = self._actor_for(run_id, family)

        def freeze_prefix_owned() -> tuple[int, str] | None:
            if not target.exists():
                return None
            schema_version = self._schema_version_for(target, run_id, family)
            return target.stat().st_size, schema_version

        try:
            snapshot = actor.call("freeze-verify-prefix", freeze_prefix_owned)
            if snapshot is None:
                return (f"missing segment: {target}",)
            snapshot_size, schema_version = snapshot
            scan_raw_segment(
                target,
                family=family,
                schema_version=schema_version,
                run_id=run_id,
                limit_bytes=snapshot_size,
                repair_partial_tail=False,
            )
        except Exception as exc:
            descriptor = describe_exception(exc)
            return (
                f"{descriptor.error_type}: {descriptor.safe_message}; "
                f"error_digest={descriptor.error_digest}",
            )
        return ()

    def read(self, run_id: str, family: str, *, limit: int = 10000) -> tuple[JsonObject, ...]:
        if limit <= 0:
            return ()
        target = RawSegmentPool.target(self.root, run_id, family)
        actor = self._actor_for(run_id, family)

        def freeze_committed_prefix() -> tuple[int, str] | None:
            # The only actor-owned operation is selecting a completed append
            # cut. Expensive hash verification and JSON decoding must never
            # occupy the unique family writer or hold up future fsyncs.
            if not target.exists():
                return None
            return target.stat().st_size, self._schema_version_for(
                target, run_id, family,
            )

        frozen = actor.call("freeze-read-prefix", freeze_committed_prefix)
        if frozen is None:
            return ()
        snapshot_size, schema_version = frozen
        # Append-only files keep all bytes preceding the frozen cut immutable.
        # Verify the *entire* prefix, then read only that prefix: concurrent
        # actor commits cannot slip extra records into this reader's result.
        # The single immutable-prefix scan verifies all records (including
        # those beyond the requested limit), while retaining only the small
        # caller-visible leading slice. No second open/read/JSON parse is needed.
        verified = scan_raw_segment(
            target,
            family=family,
            schema_version=schema_version,
            run_id=run_id,
            limit_bytes=snapshot_size,
            repair_partial_tail=False,
            read_rows_limit=limit,
        )
        return verified.read_rows

    @staticmethod
    def _schema_version_for(target: Path, run_id: str, family: str) -> str:
        if not target.exists():
            raise FileNotFoundError(target)
        with target.open("rb") as handle:
            raw = handle.readline()
        if not raw.endswith(b"\n"):
            raise RuntimeError(f"{target}: incomplete first record")
        try:
            row = decode_record_json(raw)
        except RawSegmentCodecError as exc:
            raise RuntimeError(f"{target}: invalid first record") from exc
        if not isinstance(row, dict) or row.get("family") != family:
            raise RuntimeError(f"{target}: family identity mismatch for run {run_id!r}")
        schema_version = row.get("schema_version")
        if not isinstance(schema_version, str) or not schema_version:
            raise RuntimeError(f"{target}: invalid schema_version")
        return schema_version

    def release_run(self, run_id: str) -> None:
        if type(run_id) is not str or not run_id.strip():
            raise ValueError("raw observation release run_id must be non-empty text")
        with self._actors_lock:
            if self._closed:
                return
            rows = tuple(
                (key, actor)
                for key, actor in self._actors.items()
                if key[0] == run_id
            )
        errors: list[BaseException] = []
        deadline = Deadline.after(30.0)
        for (owned_run_id, family), actor in rows:
            try:
                actor.call(
                    "release-writer",
                    self._pool.release,
                    owned_run_id,
                    family,
                    deadline=deadline,
                )
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup(
                f"raw observation run release failed: {run_id}",
                errors,
            )

    def close(self) -> None:
        """Seal writers once and retry only incomplete actor-owned cleanup."""

        with self._close_lock:
            with self._actors_lock:
                if self._closed and not self._close_pending:
                    return
                if not self._closed:
                    self._closed = True
                    self._close_pending = dict(self._pool.seal())
                actors = dict(self._actors)
                pending = dict(self._close_pending)

            errors: list[BaseException] = []
            failed: dict[tuple[str, str], RawSegmentWriter] = {}
            deadline = Deadline.after(30.0)
            for key, writer in pending.items():
                actor = actors.get(key)
                if actor is None:
                    errors.append(RuntimeError(f"raw segment writer has no actor owner: {key}"))
                    failed[key] = writer
                    continue
                try:
                    actor.call("close-writer", writer.close, deadline=deadline)
                except BaseException as exc:
                    errors.append(exc)
                    failed[key] = writer

            with self._actors_lock:
                self._close_pending = failed
            if errors:
                raise ExceptionGroup("raw observation persistence close failed", errors)
