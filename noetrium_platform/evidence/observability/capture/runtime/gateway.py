from __future__ import annotations

import base64
from threading import RLock
import time

from noetrium_platform.foundation.governance.api import SystemRegistryPort
from noetrium_platform.foundation.kernel.kernel import JsonObject, thaw_json
from noetrium_platform.foundation.kernel.record import record_document

from ..api.contracts import RawCaptureHealth, RecordCapture, RawObservationReceipt
from .lake import RawObservationLake


class RegistryBoundRawObservationGateway:
    """Single capture gateway joining lossless facts to system topology."""

    def __init__(self, lake: RawObservationLake, systems: SystemRegistryPort) -> None:
        self._lake = lake
        self._systems = systems
        self._lock = RLock()
        self._accepted = 0
        self._duplicates = 0
        self._rejected = 0
        self._seen: set[str] = set()
        self._registered: dict[str, str] = {}
        self._observed: set[str] = set()

    def register_producer(self, producer_id: str, system: object) -> None:
        if not producer_id.strip():
            raise ValueError("producer_id must be non-empty")
        identity = self._systems.validate(system)
        with self._lock:
            self._registered[producer_id] = identity.identity.key

    def capture(self, envelope: RecordCapture) -> RawObservationReceipt:
        return self.capture_many((envelope,))[0]

    def capture_many(
        self, envelopes: tuple[RecordCapture, ...],
    ) -> tuple[RawObservationReceipt, ...]:
        """One validated capture boundary, independent durable family actors.

        No observation is acknowledged before all admitted writers have
        committed. Other appenders preserve per-family serial ordering and
        restart-safe idempotency. Any failure propagates after all joins.
        """
        pending = []
        try:
            for envelope in envelopes:
                identity = self._systems.validate(envelope.system)
                payload = self._payload(envelope, identity.identity.key)
                pending.append((
                    envelope.context, envelope.family, payload,
                    envelope.event_id, envelope.recorded_at,
                ))
            with self._lock:
                self._duplicates += sum(
                    envelope.event_id in self._seen for envelope in envelopes
                )
                self._observed.update(
                    envelope.producer_id for envelope in envelopes
                )
            receipts = self._lake.append_many_once(tuple(pending))
            if len(receipts) != len(envelopes):
                raise RuntimeError("raw observation receipt cardinality drift")
            with self._lock:
                self._seen.update(envelope.event_id for envelope in envelopes)
                self._accepted += len(receipts)
            return receipts
        except BaseException:
            with self._lock:
                self._rejected += len(envelopes)
            raise

    def append(self, envelope: RecordCapture) -> RawObservationReceipt:
        return self.capture(envelope)

    def _payload(self, envelope: RecordCapture, system_key: str) -> JsonObject:
        payload=dict(thaw_json(envelope.payload))
        if "__record" in payload or "__content_b64" in payload: raise ValueError("record storage keys are reserved by capture")
        payload["__record"]=record_document(envelope.record)
        payload["__content_b64"]=base64.b64encode(envelope.raw_payload).decode("ascii")
        return payload

    def health(self) -> RawCaptureHealth:
        with self._lock:
            missing = tuple(sorted(set(self._registered) - self._observed))
            return RawCaptureHealth(
                self._accepted,
                self._duplicates,
                self._rejected,
                self._systems.generation,
                self._systems.topology_digest,
                tuple(sorted(self._registered)),
                tuple(sorted(self._observed)),
                missing,
            )

    def release_run(self, run_id: str) -> None:
        self._lake.release_run(run_id)

    def close(self) -> None:
        self._lake.close()


__all__ = ["RegistryBoundRawObservationGateway"]
