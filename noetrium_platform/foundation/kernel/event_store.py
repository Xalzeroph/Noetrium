"""One file-backed causal Event-Unit persistence primitive for all platform domains."""
from __future__ import annotations

import base64
import hashlib
from pathlib import Path

from noetrium_platform.foundation.kernel.event import (
    causal_event,
    event_field,
    event_ref,
)
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.foundation.kernel.kernel.durability.durable_file import (
    atomic_replace_bytes,
)
from noetrium_platform.foundation.kernel.kernel.durability.file_lock import (
    InterprocessFileLock,
)


class FileCausalEventStore:
    """Append-only causal truth plus a disposable latest-state file projection.

    The projection path is never authoritative.  Every transition is first
    committed as a content-addressed system.event Unit.  A missing or divergent
    projection is rebuilt from the causal trace on read.
    """

    def __init__(
        self,
        projection_path: Path,
        *,
        state_schema: str,
        authority_domain: str | None = None,
    ) -> None:
        if type(state_schema) is not str or not state_schema.strip():
            raise ValueError("causal state schema must be non-empty")
        self.projection_path = projection_path.resolve()
        self.state_schema = state_schema.strip()
        identity = hashlib.sha256(
            str(self.projection_path).encode("utf-8")
        ).hexdigest()
        self.authority_domain = (
            f"lifecycle.state.{identity}"
            if authority_domain is None
            else authority_domain.strip()
        )
        if not self.authority_domain:
            raise ValueError("causal state authority_domain must be non-empty")
        self.event_root = self.projection_path.with_name(
            self.projection_path.name + ".events"
        )
        self.event_root.mkdir(parents=True, exist_ok=True)
        self.lock_path = self.projection_path.with_name(
            self.projection_path.name + ".causal.lock"
        )
        # Disposable, process-local proof of an already validated prefix.
        # Never used by read(), events(), or integrity verification.
        self._append_tail: tuple[int, NoetriumUnit | None, tuple[int, ...], bytes | None] | None = None

    def _directory_stamp(self) -> tuple[int, ...]:
        stat = self.event_root.stat()
        return (stat.st_dev, stat.st_ino, stat.st_mtime_ns, stat.st_ctime_ns, stat.st_size)

    def mutation(self) -> InterprocessFileLock:
        return InterprocessFileLock(self.lock_path)

    def _event_paths(self) -> tuple[Path, ...]:
        """Index a linear causal chain in expected O(N), not O(N log N).

        The writer assigns dense generations. Filename generation and digest
        remain untrusted until verified against the decoded Event Unit.
        Missing, malformed, or duplicate generations fail closed.
        """
        by_generation: dict[int, Path] = {}
        for path in self.event_root.glob("*.unit"):
            name = path.name
            generation_text, separator, digest_with_suffix = name.partition("-")
            digest = digest_with_suffix.removesuffix(".unit")
            if (
                separator != "-"
                or len(generation_text) != 20
                or not generation_text.isdecimal()
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
                or name != generation_text + "-" + digest + ".unit"
            ):
                raise RuntimeError("lifecycle causal Event filename is malformed: " + name)
            generation = int(generation_text)
            if generation == 0 or generation in by_generation:
                raise RuntimeError("lifecycle causal Event generation is repeated or zero")
            by_generation[generation] = path
        if by_generation and max(by_generation) != len(by_generation):
            raise RuntimeError("lifecycle causal Event generation is not contiguous")
        return tuple(by_generation[generation] for generation in range(1, len(by_generation) + 1))

    def _scan_events_unlocked(
        self, *, collect: bool,
    ) -> tuple[NoetriumUnit, ...]:
        """Validate every durable Event with O(1) retained Unit history when
        only the last state is required. Full events() still returns the chain.
        """
        # An integrity failure must revoke a previously cached append proof.
        # Only a fully successful scan may publish a new validated tail.
        self._append_tail = None
        events_list: list[NoetriumUnit] = []
        previous: NoetriumUnit | None = None
        last_encoded: bytes | None = None
        expected_generation = 1
        for path in self._event_paths():
            try:
                encoded = path.read_bytes()
                event = decode_unit(encoded)
                generation = int(event_field(event, "generation"))
                if path.name != f"{generation:020d}-{event.unit_digest}.unit":
                    raise RuntimeError("causal Event filename does not match event identity")
            except Exception as exc:
                raise RuntimeError(
                    "lifecycle causal Event Unit is corrupt: " + path.name
                ) from exc
            if event_field(event, "authority_domain") != self.authority_domain:
                raise RuntimeError("lifecycle causal journal crossed authority domain")
            if generation != expected_generation:
                raise RuntimeError(
                    "lifecycle causal journal generation is not contiguous: "
                    f"expected={expected_generation} actual={generation}"
                )
            parents = tuple(event.refs("causal-parent"))
            if previous is None:
                if parents:
                    raise RuntimeError("lifecycle causal journal genesis has parent")
            elif parents != (event_ref(previous),):
                raise RuntimeError("lifecycle causal journal is not one exact domain chain")
            if collect:
                events_list.append(event)
            previous = event
            last_encoded = encoded
            expected_generation += 1
        if previous is None and self.projection_path.exists():
            raise RuntimeError(
                "lifecycle projection exists without causal Event truth: "
                + str(self.projection_path)
            )
        self._append_tail = (
            expected_generation - 1, previous, self._directory_stamp(), last_encoded
        )
        return tuple(events_list) if collect else (() if previous is None else (previous,))

    def _events_unlocked(self) -> tuple[NoetriumUnit, ...]:
        return self._scan_events_unlocked(collect=True)

    def _tail_unlocked(self) -> tuple[NoetriumUnit, ...]:
        return self._scan_events_unlocked(collect=False)

    def _append_predecessor_unlocked(self) -> tuple[int, NoetriumUnit | None]:
        """Reuse one validated prefix only while this process owns its cut.

        A new process or an observed directory-entry mutation must replay the
        full journal. Read/recovery always verify the complete chain regardless
        of this optimization. The lock serializes legitimate concurrent writers.
        """
        cached = self._append_tail
        if cached is not None and cached[2] == self._directory_stamp():
            generation, predecessor, _stamp, encoded = cached
            if predecessor is None:
                return generation, None
            path = self.event_root / f"{generation:020d}-{predecessor.unit_digest}.unit"
            if encoded is not None and path.is_file() and path.read_bytes() == encoded:
                return generation, predecessor
        tail = self._tail_unlocked()
        return (int(event_field(tail[-1], "generation")), tail[-1]) if tail else (0, None)

    def events(self) -> tuple[NoetriumUnit, ...]:
        with self.mutation():
            return self._events_unlocked()

    def _subject_payload(self, event: NoetriumUnit) -> bytes:
        subject = event_field(event, "subject")
        if (
            type(subject) is not NoetriumUnit
            or not subject.has_schema("lifecycle.state")
            or subject.attribute("state_schema") != self.state_schema
        ):
            raise RuntimeError("lifecycle state Event contains invalid subject")
        payload = base64.b64decode(
            str(subject.attribute("payload_b64")).encode("ascii")
        )
        if hashlib.sha256(payload).hexdigest() != subject.attribute("payload_sha256"):
            raise RuntimeError("lifecycle state Event payload digest drifted")
        return payload

    def exists(self) -> bool:
        with self.mutation():
            return bool(self._tail_unlocked())

    def read(self) -> bytes:
        with self.mutation():
            tail = self._tail_unlocked()
            if not tail:
                raise FileNotFoundError(self.projection_path)
            payload = self._subject_payload(tail[-1])
            if (
                not self.projection_path.exists()
                or self.projection_path.read_bytes() != payload
            ):
                atomic_replace_bytes(self.projection_path, payload)
            return payload

    def append(
        self,
        payload: bytes,
        *,
        phase: str = "observed",
        modality: TruthModality = TruthModality.OBSERVED,
        operation: str = "state-transition",
    ) -> NoetriumUnit:
        raw = bytes(payload)
        with self.mutation():
            committed_generation, previous = self._append_predecessor_unlocked()
            generation = committed_generation + 1
            digest = hashlib.sha256(raw).hexdigest()
            subject = NoetriumUnit(
                "lifecycle.state:" + digest,
                schemas=("lifecycle.state", self.state_schema),
                attributes={
                    "kind": "lifecycle.state",
                    "state_schema": self.state_schema,
                    "payload_b64": base64.b64encode(raw).decode("ascii"),
                    "payload_sha256": digest,
                },
                semantic_projection_digest=digest,
            )
            event = causal_event(
                authority_domain=self.authority_domain,
                generation=generation,
                subject=subject,
                operation=operation,
                phase=phase,
                modality=TruthModality(modality),
                causal_parents=(
                    () if previous is None else (event_ref(previous),)
                ),
                reads=(f"state:{self.state_schema}",),
                writes=(f"state:{self.state_schema}",),
                event_kind="lifecycle.state-transition",
            )
            path = self.event_root / f"{generation:020d}-{event.unit_digest}.unit"
            encoded = encode_unit(event)
            if path.exists():
                if path.read_bytes() != encoded:
                    raise RuntimeError("lifecycle Event content-address collision")
            else:
                atomic_replace_bytes(path, encoded)
            # The durable Event is authoritative. Cache only the prefix proof;
            # the latest-state file remains a disposable projection.
            self._append_tail = (generation, event, self._directory_stamp(), encoded)
            atomic_replace_bytes(self.projection_path, raw)
            return event

    def verify_projection_rebuild(self) -> bytes:
        with self.mutation():
            tail = self._tail_unlocked()
            if not tail:
                if self.projection_path.exists():
                    raise RuntimeError(
                        "lifecycle projection exists without causal Event truth"
                    )
                return b""
            expected = self._subject_payload(tail[-1])
            if (
                not self.projection_path.exists()
                or self.projection_path.read_bytes() != expected
            ):
                raise RuntimeError(
                    "lifecycle latest-state projection diverged from causal Event Journal"
                )
            return expected


__all__ = ["FileCausalEventStore"]
