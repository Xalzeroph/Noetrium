from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from noetrium_platform.foundation.kernel.kernel import (
    CanonicalDecodingError, CanonicalEncodingError, strict_finite_json_bytes, strict_json_loads,
)

from noetrium_platform.capabilities.participant.api.revision import (
    ParticipantRevisionAuthoritySnapshot,
    ParticipantRevisionCommit,
    ParticipantRevisionConflictError,
    ParticipantRevisionEvidence,
    ParticipantRevisionEvidenceKind,
    ParticipantRevisionIntegrityError,
    ParticipantRevisionProposal,
    ParticipantRevisionStateError,
    ParticipantRevisionValue,
    ParticipantStateCompatibility,
    ParticipantStateRevision,
    ParticipantStateTransition,
    ParticipantTransitionValue,
    PreparedParticipantRevision,
)
from noetrium_platform.capabilities.participant.api.topology import (
    ArchitectureChangeKind,
    ParticipantArchitectureChange,
    ParticipantArchitectureComponent,
    ParticipantArchitectureRevision,
    ParticipantArchitectureTransition,
    ParticipantTopology,
    ParticipantTopologyChange,
    ParticipantTopologyMember,
    ParticipantTopologyTransition,
    TopologyChangeKind,
)

_SCHEMA_VERSION = "participant-revision-authority.sqlite.v1"
_TABLES = frozenset({"authority_meta", "revisions", "proposals", "transitions", "prepared", "commits"})
JsonNode = str | int | None | list["JsonNode"] | tuple["JsonNode", ...] | dict[str, "JsonNode"]



def _loads(raw: bytes, *, field: str) -> dict[str, JsonNode]:
    try:
        value = strict_json_loads(raw)
    except CanonicalDecodingError as exc:
        raise ParticipantRevisionIntegrityError(f"{field} is not strict finite JSON") from exc
    if not isinstance(value, dict):
        raise ParticipantRevisionIntegrityError(f"{field} must decode to an object")
    return value



def _bytes(value: dict[str, JsonNode]) -> bytes:
    try:
        return strict_finite_json_bytes(value)
    except (CanonicalEncodingError, UnicodeEncodeError) as exc:
        raise ParticipantRevisionIntegrityError("participant revision payload cannot be encoded as strict finite JSON") from exc



def _expect(value: dict[str, JsonNode], fields: frozenset[str], *, field: str) -> None:
    if frozenset(value) != fields:
        raise ParticipantRevisionIntegrityError(f"{field} fields are invalid")


def _object(value: JsonNode, *, field: str) -> dict[str, JsonNode]:
    if not isinstance(value, dict):
        raise ParticipantRevisionIntegrityError(f"{field} must be an object")
    return value


def _list(value: JsonNode, *, field: str) -> list[JsonNode]:
    if not isinstance(value, list):
        raise ParticipantRevisionIntegrityError(f"{field} must be an array")
    return value


def _string(value: JsonNode, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ParticipantRevisionIntegrityError(f"{field} must be canonical non-empty text")
    return value


def _integer(value: JsonNode, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ParticipantRevisionIntegrityError(f"{field} must be a positive integer")
    return value


def _strings(value: JsonNode, *, field: str) -> tuple[str, ...]:
    rows = _list(value, field=field)
    result = tuple(_string(item, field=field) for item in rows)
    if len(set(result)) != len(result):
        raise ParticipantRevisionIntegrityError(f"{field} must be unique")
    return result


def _encode_revision(value: ParticipantRevisionValue) -> bytes:
    if isinstance(value, ParticipantTopology):
        return _bytes({
            "kind": "topology",
            "members": [
                {
                    "architecture_revision_digest": member.architecture_revision_digest,
                    "binding_digest": member.binding_digest,
                    "participant_id": member.participant_id,
                    "requirement_digest": member.requirement_digest,
                    "role": member.role,
                }
                for member in value.members
            ],
            "predecessor_digest": value.predecessor_digest,
            "revision": value.revision,
            "topology_id": value.topology_id,
        })
    if isinstance(value, ParticipantArchitectureRevision):
        return _bytes({
            "components": [
                {
                    "capability_id": component.capability_id,
                    "component_id": component.component_id,
                    "configuration_digest": component.configuration_digest,
                    "implementation_digest": component.implementation_digest,
                    "state_schema_id": component.state_schema_id,
                }
                for component in value.components
            ],
            "kind": "architecture",
            "participant_id": value.participant_id,
            "predecessor_digest": value.predecessor_digest,
            "revision_id": value.revision_id,
        })
    return _bytes({
        "compatibility": {
            "codec_contract_id": value.compatibility.codec_contract_id,
            "codec_implementation_digest": value.compatibility.codec_implementation_digest,
            "state_contract_id": value.compatibility.state_contract_id,
            "state_schema_digest": value.compatibility.state_schema_digest,
        },
        "configuration_digest": value.configuration_digest,
        "implementation_digest": value.implementation_digest,
        "kind": "state",
        "participant_id": value.participant_id,
        "predecessor_digest": value.predecessor_digest,
        "revision_id": value.revision_id,
        "state_artifact_digest": value.state_artifact_digest,
    })


def _decode_revision(raw: bytes) -> ParticipantRevisionValue:
    root = _loads(raw, field="participant revision")
    kind = _string(root.get("kind"), field="participant revision kind")
    try:
        if kind == "topology":
            return _decode_topology(root)
        if kind == "architecture":
            return _decode_architecture(root)
        if kind == "state":
            return _decode_state(root)
    except (TypeError, ValueError) as exc:
        raise ParticipantRevisionIntegrityError("participant revision payload is invalid") from exc
    raise ParticipantRevisionIntegrityError("participant revision kind is unsupported")


def _decode_topology(root: dict[str, JsonNode]) -> ParticipantTopology:
    _expect(root, frozenset({
        "kind", "members", "predecessor_digest", "revision", "topology_id",
    }), field="participant topology")
    members: list[ParticipantTopologyMember] = []
    for index, item in enumerate(_list(root["members"], field="participant topology members")):
        row = _object(item, field=f"participant topology members[{index}]")
        _expect(row, frozenset({
            "architecture_revision_digest", "binding_digest", "participant_id",
            "requirement_digest", "role",
        }), field=f"participant topology members[{index}]")
        members.append(ParticipantTopologyMember(
            participant_id=_string(row["participant_id"], field="participant_id"),
            role=_string(row["role"], field="role"),
            requirement_digest=_string(row["requirement_digest"], field="requirement_digest"),
            binding_digest=_string(row["binding_digest"], field="binding_digest"),
            architecture_revision_digest=_string(
                row["architecture_revision_digest"], field="architecture_revision_digest"
            ),
        ))
    return ParticipantTopology(
        topology_id=_string(root["topology_id"], field="topology_id"),
        members=tuple(members),
        revision=_integer(root["revision"], field="revision"),
        predecessor_digest=_string(
            root["predecessor_digest"], field="predecessor_digest", optional=True
        ),
    )


def _decode_architecture(root: dict[str, JsonNode]) -> ParticipantArchitectureRevision:
    _expect(root, frozenset({
        "components", "kind", "participant_id", "predecessor_digest", "revision_id",
    }), field="participant architecture")
    components: list[ParticipantArchitectureComponent] = []
    for index, item in enumerate(_list(root["components"], field="participant architecture components")):
        row = _object(item, field=f"participant architecture components[{index}]")
        _expect(row, frozenset({
            "capability_id", "component_id", "configuration_digest", "implementation_digest",
            "state_schema_id",
        }), field=f"participant architecture components[{index}]")
        components.append(ParticipantArchitectureComponent(
            component_id=_string(row["component_id"], field="component_id"),
            capability_id=_string(row["capability_id"], field="capability_id"),
            implementation_digest=_string(
                row["implementation_digest"], field="implementation_digest"
            ),
            configuration_digest=_string(
                row["configuration_digest"], field="configuration_digest"
            ),
            state_schema_id=_string(row["state_schema_id"], field="state_schema_id"),
        ))
    return ParticipantArchitectureRevision(
        participant_id=_string(root["participant_id"], field="participant_id"),
        revision_id=_string(root["revision_id"], field="revision_id"),
        components=tuple(components),
        predecessor_digest=_string(
            root["predecessor_digest"], field="predecessor_digest", optional=True
        ),
    )


def _decode_state(root: dict[str, JsonNode]) -> ParticipantStateRevision:
    _expect(root, frozenset({
        "compatibility", "configuration_digest", "implementation_digest", "kind",
        "participant_id", "predecessor_digest", "revision_id", "state_artifact_digest",
    }), field="participant state revision")
    compatibility = _object(root["compatibility"], field="participant state compatibility")
    _expect(compatibility, frozenset({
        "codec_contract_id", "codec_implementation_digest", "state_contract_id",
        "state_schema_digest",
    }), field="participant state compatibility")
    return ParticipantStateRevision(
        participant_id=_string(root["participant_id"], field="participant_id"),
        revision_id=_string(root["revision_id"], field="revision_id"),
        compatibility=ParticipantStateCompatibility(
            state_contract_id=_string(compatibility["state_contract_id"], field="state_contract_id"),
            state_schema_digest=_string(compatibility["state_schema_digest"], field="state_schema_digest"),
            codec_contract_id=_string(compatibility["codec_contract_id"], field="codec_contract_id"),
            codec_implementation_digest=_string(
                compatibility["codec_implementation_digest"], field="codec_implementation_digest"
            ),
        ),
        implementation_digest=_string(root["implementation_digest"], field="implementation_digest"),
        configuration_digest=_string(root["configuration_digest"], field="configuration_digest"),
        state_artifact_digest=_string(root["state_artifact_digest"], field="state_artifact_digest"),
        predecessor_digest=_string(
            root["predecessor_digest"], field="predecessor_digest", optional=True
        ),
    )


def _encode_proposal(value: ParticipantRevisionProposal) -> bytes:
    return _bytes({
        "evidence_refs": list(value.evidence_refs),
        "migration_adapter_digest": value.migration_adapter_digest,
        "predecessor_revision_digest": value.predecessor_revision_digest,
        "proposal_id": value.proposal_id,
        "reason_digest": value.reason_digest,
        "update_contract_id": value.update_contract_id,
    })


def _decode_proposal(raw: bytes) -> ParticipantRevisionProposal:
    root = _loads(raw, field="participant revision proposal")
    _expect(root, frozenset({
        "evidence_refs", "migration_adapter_digest", "predecessor_revision_digest",
        "proposal_id", "reason_digest", "update_contract_id",
    }), field="participant revision proposal")
    try:
        return ParticipantRevisionProposal(
            proposal_id=_string(root["proposal_id"], field="proposal_id"),
            predecessor_revision_digest=_string(
                root["predecessor_revision_digest"], field="predecessor_revision_digest"
            ),
            update_contract_id=_string(root["update_contract_id"], field="update_contract_id"),
            reason_digest=_string(root["reason_digest"], field="reason_digest"),
            migration_adapter_digest=_string(
                root["migration_adapter_digest"], field="migration_adapter_digest", optional=True
            ),
            evidence_refs=_strings(root["evidence_refs"], field="evidence_refs"),
        )
    except (TypeError, ValueError) as exc:
        raise ParticipantRevisionIntegrityError("participant revision proposal is invalid") from exc


def _encode_transition(value: ParticipantTransitionValue) -> bytes:
    if isinstance(value, ParticipantTopologyTransition):
        return _bytes({
            "changes": [
                {
                    "after": change.after_member_digest,
                    "before": change.before_member_digest,
                    "kind": change.kind.value,
                    "participant_id": change.participant_id,
                }
                for change in value.changes
            ],
            "evidence_refs": list(value.evidence_refs),
            "from": value.from_topology_digest,
            "kind": "topology",
            "to": value.to_topology_digest,
            "transition_id": value.transition_id,
        })
    if isinstance(value, ParticipantArchitectureTransition):
        return _bytes({
            "changes": [
                {
                    "after": change.after_component_digest,
                    "before": change.before_component_digest,
                    "component_id": change.component_id,
                    "kind": change.kind.value,
                }
                for change in value.changes
            ],
            "evidence_refs": list(value.evidence_refs),
            "from": value.from_revision_digest,
            "kind": "architecture",
            "participant_id": value.participant_id,
            "to": value.to_revision_digest,
            "transition_id": value.transition_id,
        })
    return _bytes({
        "evidence_refs": list(value.evidence_refs),
        "from": value.from_revision_digest,
        "kind": "state",
        "migration_adapter_digest": value.migration_adapter_digest,
        "to": value.to_revision_digest,
        "transition_id": value.transition_id,
        "update_contract_id": value.update_contract_id,
    })


def _decode_transition(raw: bytes) -> ParticipantTransitionValue:
    root = _loads(raw, field="participant revision transition")
    kind = _string(root.get("kind"), field="participant transition kind")
    try:
        if kind == "topology":
            return _decode_topology_transition(root)
        if kind == "architecture":
            return _decode_architecture_transition(root)
        if kind == "state":
            return _decode_state_transition(root)
    except (TypeError, ValueError) as exc:
        raise ParticipantRevisionIntegrityError("participant revision transition is invalid") from exc
    raise ParticipantRevisionIntegrityError("participant revision transition kind is unsupported")


def _decode_topology_transition(root: dict[str, JsonNode]) -> ParticipantTopologyTransition:
    _expect(root, frozenset({
        "changes", "evidence_refs", "from", "kind", "to", "transition_id",
    }), field="participant topology transition")
    changes: list[ParticipantTopologyChange] = []
    for index, item in enumerate(_list(root["changes"], field="topology transition changes")):
        row = _object(item, field=f"topology transition changes[{index}]")
        _expect(row, frozenset({"after", "before", "kind", "participant_id"}), field=f"topology transition changes[{index}]")
        changes.append(ParticipantTopologyChange(
            kind=TopologyChangeKind(_string(row["kind"], field="topology change kind")),
            participant_id=_string(row["participant_id"], field="participant_id"),
            before_member_digest=_string(row["before"], field="before", optional=True),
            after_member_digest=_string(row["after"], field="after", optional=True),
        ))
    return ParticipantTopologyTransition(
        transition_id=_string(root["transition_id"], field="transition_id"),
        from_topology_digest=_string(root["from"], field="from"),
        to_topology_digest=_string(root["to"], field="to"),
        changes=tuple(changes),
        evidence_refs=_strings(root["evidence_refs"], field="evidence_refs"),
    )


def _decode_architecture_transition(root: dict[str, JsonNode]) -> ParticipantArchitectureTransition:
    _expect(root, frozenset({
        "changes", "evidence_refs", "from", "kind", "participant_id", "to", "transition_id",
    }), field="participant architecture transition")
    changes: list[ParticipantArchitectureChange] = []
    for index, item in enumerate(_list(root["changes"], field="architecture transition changes")):
        row = _object(item, field=f"architecture transition changes[{index}]")
        _expect(row, frozenset({"after", "before", "component_id", "kind"}), field=f"architecture transition changes[{index}]")
        changes.append(ParticipantArchitectureChange(
            kind=ArchitectureChangeKind(_string(row["kind"], field="architecture change kind")),
            component_id=_string(row["component_id"], field="component_id"),
            before_component_digest=_string(row["before"], field="before", optional=True),
            after_component_digest=_string(row["after"], field="after", optional=True),
        ))
    return ParticipantArchitectureTransition(
        transition_id=_string(root["transition_id"], field="transition_id"),
        participant_id=_string(root["participant_id"], field="participant_id"),
        from_revision_digest=_string(root["from"], field="from"),
        to_revision_digest=_string(root["to"], field="to"),
        changes=tuple(changes),
        evidence_refs=_strings(root["evidence_refs"], field="evidence_refs"),
    )


def _decode_state_transition(root: dict[str, JsonNode]) -> ParticipantStateTransition:
    _expect(root, frozenset({
        "evidence_refs", "from", "kind", "migration_adapter_digest", "to",
        "transition_id", "update_contract_id",
    }), field="participant state transition")
    return ParticipantStateTransition(
        transition_id=_string(root["transition_id"], field="transition_id"),
        from_revision_digest=_string(root["from"], field="from"),
        to_revision_digest=_string(root["to"], field="to"),
        update_contract_id=_string(root["update_contract_id"], field="update_contract_id"),
        migration_adapter_digest=_string(
            root["migration_adapter_digest"], field="migration_adapter_digest", optional=True
        ),
        evidence_refs=_strings(root["evidence_refs"], field="evidence_refs"),
    )


def _encode_evidence(values: tuple[ParticipantRevisionEvidence, ...]) -> bytes:
    return _bytes({"evidence": [
        {
            "evidence_digest": value.evidence_digest,
            "kind": value.kind.value,
            "producer_contract_id": value.producer_contract_id,
            "revision_digest": value.revision_digest,
        }
        for value in values
    ]})


def _decode_evidence(raw: bytes) -> tuple[ParticipantRevisionEvidence, ...]:
    root = _loads(raw, field="participant revision evidence")
    _expect(root, frozenset({"evidence"}), field="participant revision evidence")
    rows = _list(root["evidence"], field="participant revision evidence")
    if not rows:
        raise ParticipantRevisionIntegrityError("participant revision evidence must be non-empty")
    result: list[ParticipantRevisionEvidence] = []
    for index, item in enumerate(rows):
        row = _object(item, field=f"participant revision evidence[{index}]")
        _expect(row, frozenset({
            "evidence_digest", "kind", "producer_contract_id", "revision_digest",
        }), field=f"participant revision evidence[{index}]")
        try:
            result.append(ParticipantRevisionEvidence(
                kind=ParticipantRevisionEvidenceKind(_string(row["kind"], field="kind")),
                revision_digest=_string(row["revision_digest"], field="revision_digest"),
                evidence_digest=_string(row["evidence_digest"], field="evidence_digest"),
                producer_contract_id=_string(
                    row["producer_contract_id"], field="producer_contract_id"
                ),
            ))
        except (TypeError, ValueError) as exc:
            raise ParticipantRevisionIntegrityError(
                f"participant revision evidence[{index}] is invalid"
            ) from exc
    return tuple(result)


class SQLiteParticipantRevisionAuthority:
    """Crash-durable participant revision authority with generation-fenced CAS."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._bootstrap_or_verify()

    def _connect(self) -> sqlite3.Connection:
        try:
            connection = sqlite3.connect(self._path, timeout=30.0, isolation_level=None)
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys=ON")
            connection.execute("PRAGMA synchronous=FULL")
            connection.execute("PRAGMA journal_mode=WAL")
            return connection
        except sqlite3.DatabaseError as exc:
            raise ParticipantRevisionIntegrityError("participant revision database cannot be opened") from exc

    @contextmanager
    def _transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self._connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.execute("COMMIT")
        except sqlite3.DatabaseError as exc:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.DatabaseError:
                pass
            raise ParticipantRevisionIntegrityError("participant revision transaction failed") from exc
        except BaseException:
            try:
                connection.execute("ROLLBACK")
            except sqlite3.DatabaseError:
                pass
            raise
        finally:
            connection.close()

    def _bootstrap_or_verify(self) -> None:
        is_new = not self._path.exists()
        if is_new:
            with self._transaction() as connection:
                self._create_schema(connection)
            return
        if self._path.stat().st_size == 0:
            raise ParticipantRevisionIntegrityError("existing participant revision database is empty")
        connection = self._connect()
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise ParticipantRevisionIntegrityError("participant revision database integrity failed")
            tables = frozenset(row[0] for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ))
            if tables != _TABLES:
                raise ParticipantRevisionIntegrityError("participant revision database table set is invalid")
            row = connection.execute(
                "SELECT schema_version FROM authority_meta WHERE singleton=1"
            ).fetchone()
            if row is None or row[0] != _SCHEMA_VERSION:
                raise ParticipantRevisionIntegrityError("participant revision schema version is invalid")
        except sqlite3.DatabaseError as exc:
            raise ParticipantRevisionIntegrityError("participant revision database schema is unreadable") from exc
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE authority_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version TEXT NOT NULL, generation INTEGER, current_digest TEXT, initial_digest TEXT, revision_kind TEXT)")
        connection.execute("CREATE TABLE revisions (digest TEXT PRIMARY KEY, parent_digest TEXT, kind TEXT NOT NULL, payload BLOB NOT NULL, committed INTEGER NOT NULL CHECK(committed IN (0,1)))")
        connection.execute("CREATE TABLE proposals (digest TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        connection.execute("CREATE TABLE transitions (digest TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        connection.execute("CREATE TABLE prepared (proposal_digest TEXT PRIMARY KEY, prepared_digest TEXT NOT NULL UNIQUE, predecessor_digest TEXT NOT NULL, candidate_digest TEXT NOT NULL UNIQUE, transition_digest TEXT NOT NULL, generation INTEGER NOT NULL, recovery_anchor_digest TEXT NOT NULL, validation_plan_digest TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('prepared','committed')), FOREIGN KEY(proposal_digest) REFERENCES proposals(digest), FOREIGN KEY(predecessor_digest) REFERENCES revisions(digest), FOREIGN KEY(candidate_digest) REFERENCES revisions(digest), FOREIGN KEY(transition_digest) REFERENCES transitions(digest))")
        connection.execute("CREATE TABLE commits (candidate_digest TEXT PRIMARY KEY, prepared_digest TEXT NOT NULL UNIQUE, evidence BLOB NOT NULL, generation INTEGER NOT NULL, commit_digest TEXT NOT NULL UNIQUE, FOREIGN KEY(candidate_digest) REFERENCES revisions(digest))")
        connection.execute(
            "INSERT INTO authority_meta(singleton,schema_version) VALUES(1,?)",
            (_SCHEMA_VERSION,),
        )

    @staticmethod
    def _meta(connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(
            "SELECT generation,current_digest,initial_digest,revision_kind FROM authority_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise ParticipantRevisionIntegrityError("participant revision authority metadata is missing")
        return row

    @staticmethod
    def _require_initialized(row: sqlite3.Row) -> tuple[int, str, str, str]:
        generation = row["generation"]
        current = row["current_digest"]
        initial = row["initial_digest"]
        kind = row["revision_kind"]
        if type(generation) is not int or generation <= 0:
            raise ParticipantRevisionStateError("participant revision authority is not initialized")
        if not all(isinstance(value, str) and value for value in (current, initial, kind)):
            raise ParticipantRevisionIntegrityError("participant revision metadata is invalid")
        return generation, current, initial, kind

    @staticmethod
    def _revision_kind(value: ParticipantRevisionValue) -> str:
        if isinstance(value, ParticipantTopology):
            return "topology"
        if isinstance(value, ParticipantArchitectureRevision):
            return "architecture"
        return "state"

    @staticmethod
    def _expect_generation(current: int, expected: int) -> None:
        if type(expected) is not int or expected <= 0:
            raise ValueError("expected_generation must be positive")
        if current != expected:
            raise ParticipantRevisionConflictError(
                f"stale participant revision generation: expected {expected}, current {current}"
            )

    @staticmethod
    def _load_revision(connection: sqlite3.Connection, digest: str) -> ParticipantRevisionValue:
        row = connection.execute(
            "SELECT payload FROM revisions WHERE digest=?", (digest,)
        ).fetchone()
        if row is None:
            raise ParticipantRevisionIntegrityError("referenced participant revision is missing")
        revision = _decode_revision(bytes(row["payload"]))
        if revision.digest() != digest:
            raise ParticipantRevisionIntegrityError("stored participant revision digest mismatch")
        return revision

    @staticmethod
    def _load_proposal(connection: sqlite3.Connection, digest: str) -> ParticipantRevisionProposal:
        row = connection.execute(
            "SELECT payload FROM proposals WHERE digest=?", (digest,)
        ).fetchone()
        if row is None:
            raise ParticipantRevisionIntegrityError("referenced participant proposal is missing")
        proposal = _decode_proposal(bytes(row["payload"]))
        if proposal.digest() != digest:
            raise ParticipantRevisionIntegrityError("stored participant proposal digest mismatch")
        return proposal

    @staticmethod
    def _load_transition(connection: sqlite3.Connection, digest: str) -> ParticipantTransitionValue:
        row = connection.execute(
            "SELECT payload FROM transitions WHERE digest=?", (digest,)
        ).fetchone()
        if row is None:
            raise ParticipantRevisionIntegrityError("referenced participant transition is missing")
        transition = _decode_transition(bytes(row["payload"]))
        if transition.digest() != digest:
            raise ParticipantRevisionIntegrityError("stored participant transition digest mismatch")
        return transition

    @classmethod
    def _prepared_from_row(
        cls, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> PreparedParticipantRevision:
        proposal = cls._load_proposal(connection, row["proposal_digest"])
        predecessor = cls._load_revision(connection, row["predecessor_digest"])
        candidate = cls._load_revision(connection, row["candidate_digest"])
        transition = cls._load_transition(connection, row["transition_digest"])
        try:
            prepared = PreparedParticipantRevision(
                proposal=proposal,
                predecessor=predecessor,
                candidate=candidate,
                transition=transition,
                preparation_generation=row["generation"],
                recovery_anchor_digest=row["recovery_anchor_digest"],
                validation_plan_digest=row["validation_plan_digest"],
            )
        except (TypeError, ValueError) as exc:
            raise ParticipantRevisionIntegrityError("stored prepared participant revision is invalid") from exc
        if prepared.digest() != row["prepared_digest"]:
            raise ParticipantRevisionIntegrityError("stored prepared participant revision digest mismatch")
        return prepared

    def initialize(
        self, initial: ParticipantRevisionValue
    ) -> ParticipantRevisionAuthoritySnapshot:
        if not isinstance(initial, (ParticipantTopology, ParticipantArchitectureRevision, ParticipantStateRevision)):
            raise TypeError("initial participant revision must be typed")
        digest = initial.digest()
        kind = self._revision_kind(initial)
        with self._transaction() as connection:
            meta = self._meta(connection)
            if meta["generation"] is not None:
                current = self._require_initialized(meta)
                if current[2] != digest or current[3] != kind:
                    raise ParticipantRevisionStateError(
                        "participant revision authority already has another initial revision"
                    )
                return self._snapshot(connection)
            connection.execute(
                "INSERT INTO revisions(digest,parent_digest,kind,payload,committed) VALUES(?,?,?,?,1)",
                (digest, initial.predecessor_digest, kind, _encode_revision(initial)),
            )
            connection.execute(
                "UPDATE authority_meta SET generation=1,current_digest=?,initial_digest=?,revision_kind=? WHERE singleton=1",
                (digest, digest, kind),
            )
            return self._snapshot(connection)

    @classmethod
    def _snapshot(cls, connection: sqlite3.Connection) -> ParticipantRevisionAuthoritySnapshot:
        generation, current_digest, _, kind = cls._require_initialized(cls._meta(connection))
        current = cls._load_revision(connection, current_digest)
        if cls._revision_kind(current) != kind:
            raise ParticipantRevisionIntegrityError("participant revision kind metadata drift")
        committed = tuple(row[0] for row in connection.execute(
            "SELECT digest FROM revisions WHERE committed=1 ORDER BY digest"
        ))
        prepared = tuple(row[0] for row in connection.execute(
            "SELECT prepared_digest FROM prepared WHERE status='prepared' ORDER BY prepared_digest"
        ))
        try:
            return ParticipantRevisionAuthoritySnapshot(generation, current, committed, prepared)
        except (TypeError, ValueError) as exc:
            raise ParticipantRevisionIntegrityError("participant revision snapshot is invalid") from exc

    def snapshot(self) -> ParticipantRevisionAuthoritySnapshot:
        connection = self._connect()
        try:
            return self._snapshot(connection)
        finally:
            connection.close()

    def load_prepared(self, proposal_digest: str) -> PreparedParticipantRevision:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM prepared WHERE proposal_digest=?", (proposal_digest,)
            ).fetchone()
            if row is None:
                raise KeyError(proposal_digest)
            return self._prepared_from_row(connection, row)
        except sqlite3.DatabaseError as exc:
            raise ParticipantRevisionIntegrityError("prepared participant revision cannot be read") from exc
        finally:
            connection.close()

    def prepare_successor(
        self,
        proposal: ParticipantRevisionProposal,
        predecessor: ParticipantRevisionValue,
        candidate: ParticipantRevisionValue,
        transition: ParticipantTransitionValue,
        *,
        expected_generation: int,
        recovery_anchor_digest: str,
        validation_plan_digest: str,
    ) -> PreparedParticipantRevision:
        if not isinstance(proposal, ParticipantRevisionProposal):
            raise TypeError("participant revision prepare requires typed proposal")
        if type(predecessor) is not type(candidate):
            raise TypeError("participant revision predecessor/candidate kinds must match")
        proposal_digest = proposal.digest()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM prepared WHERE proposal_digest=?", (proposal_digest,)
            ).fetchone()
            if existing is not None:
                prepared = self._prepared_from_row(connection, existing)
                if (
                    prepared.proposal != proposal
                    or prepared.predecessor != predecessor
                    or prepared.candidate != candidate
                    or prepared.transition != transition
                    or prepared.recovery_anchor_digest != recovery_anchor_digest
                    or prepared.validation_plan_digest != validation_plan_digest
                ):
                    raise ParticipantRevisionStateError(
                        "participant proposal identity was reused with different prepare facts"
                    )
                return prepared
            generation, current_digest, _, kind = self._require_initialized(self._meta(connection))
            self._expect_generation(generation, expected_generation)
            predecessor_digest = predecessor.digest()
            if current_digest != predecessor_digest:
                raise ParticipantRevisionConflictError(
                    "participant revision predecessor is not current durable revision"
                )
            if self._revision_kind(predecessor) != kind or self._revision_kind(candidate) != kind:
                raise ParticipantRevisionStateError("participant revision kind cannot change in one authority")
            if self._load_revision(connection, predecessor_digest) != predecessor:
                raise ParticipantRevisionIntegrityError("participant predecessor payload drift")
            next_generation = generation + 1
            prepared = PreparedParticipantRevision(
                proposal, predecessor, candidate, transition, next_generation,
                recovery_anchor_digest, validation_plan_digest,
            )
            candidate_digest = candidate.digest()
            transition_digest = transition.digest()
            collision = connection.execute(
                "SELECT payload FROM revisions WHERE digest=?", (candidate_digest,)
            ).fetchone()
            if collision is not None:
                if _decode_revision(bytes(collision["payload"])) != candidate:
                    raise ParticipantRevisionIntegrityError("participant candidate digest collision")
                raise ParticipantRevisionStateError("participant candidate already belongs to another transition")
            connection.execute(
                "INSERT INTO proposals(digest,payload) VALUES(?,?)",
                (proposal_digest, _encode_proposal(proposal)),
            )
            connection.execute(
                "INSERT INTO transitions(digest,payload) VALUES(?,?)",
                (transition_digest, _encode_transition(transition)),
            )
            connection.execute(
                "INSERT INTO revisions(digest,parent_digest,kind,payload,committed) VALUES(?,?,?,?,0)",
                (candidate_digest, candidate.predecessor_digest, kind, _encode_revision(candidate)),
            )
            connection.execute(
                "INSERT INTO prepared(proposal_digest,prepared_digest,predecessor_digest,candidate_digest,transition_digest,generation,recovery_anchor_digest,validation_plan_digest,status) VALUES(?,?,?,?,?,?,?,?,'prepared')",
                (
                    proposal_digest, prepared.digest(), predecessor_digest, candidate_digest,
                    transition_digest, next_generation, recovery_anchor_digest, validation_plan_digest,
                ),
            )
            connection.execute("UPDATE authority_meta SET generation=? WHERE singleton=1", (next_generation,))
            return prepared

    def commit_successor(
        self,
        prepared: PreparedParticipantRevision,
        validation_evidence: tuple[ParticipantRevisionEvidence, ...],
        *,
        expected_generation: int,
    ) -> ParticipantRevisionCommit:
        if not isinstance(prepared, PreparedParticipantRevision):
            raise TypeError("participant revision commit requires PreparedParticipantRevision")
        candidate_digest = prepared.candidate.digest()
        probe = ParticipantRevisionCommit(prepared, validation_evidence, 1)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM commits WHERE candidate_digest=?", (candidate_digest,)
            ).fetchone()
            if existing is not None:
                prepared_row = connection.execute(
                    "SELECT * FROM prepared WHERE prepared_digest=?", (existing["prepared_digest"],)
                ).fetchone()
                if prepared_row is None:
                    raise ParticipantRevisionIntegrityError("participant commit lost prepared state")
                stored_prepared = self._prepared_from_row(connection, prepared_row)
                stored_evidence = _decode_evidence(bytes(existing["evidence"]))
                stored = ParticipantRevisionCommit(
                    stored_prepared, stored_evidence, existing["generation"]
                )
                if stored.prepared != prepared or stored.validation_evidence != probe.validation_evidence:
                    raise ParticipantRevisionStateError(
                        "participant revision commit was retried with different facts"
                    )
                if stored.digest() != existing["commit_digest"]:
                    raise ParticipantRevisionIntegrityError("stored participant commit digest mismatch")
                return stored
            generation, current_digest, _, _ = self._require_initialized(self._meta(connection))
            self._expect_generation(generation, expected_generation)
            if current_digest != prepared.predecessor.digest():
                raise ParticipantRevisionConflictError(
                    "prepared participant predecessor is no longer current"
                )
            prepared_row = connection.execute(
                "SELECT * FROM prepared WHERE prepared_digest=?", (prepared.digest(),)
            ).fetchone()
            if prepared_row is None:
                raise ParticipantRevisionStateError(
                    "participant revision was not prepared by this authority"
                )
            stored_prepared = self._prepared_from_row(connection, prepared_row)
            if stored_prepared != prepared:
                raise ParticipantRevisionIntegrityError("prepared participant revision payload drift")
            if prepared_row["status"] != "prepared":
                raise ParticipantRevisionStateError("prepared participant revision is not pending")
            next_generation = generation + 1
            commit = ParticipantRevisionCommit(prepared, validation_evidence, next_generation)
            connection.execute(
                "INSERT INTO commits(candidate_digest,prepared_digest,evidence,generation,commit_digest) VALUES(?,?,?,?,?)",
                (
                    candidate_digest, prepared.digest(), _encode_evidence(commit.validation_evidence),
                    next_generation, commit.digest(),
                ),
            )
            connection.execute(
                "UPDATE revisions SET committed=1 WHERE digest=? AND committed=0", (candidate_digest,)
            )
            connection.execute(
                "UPDATE prepared SET status='committed' WHERE prepared_digest=?", (prepared.digest(),)
            )
            connection.execute(
                "UPDATE authority_meta SET generation=?,current_digest=? WHERE singleton=1",
                (next_generation, candidate_digest),
            )
            return commit


__all__ = ["SQLiteParticipantRevisionAuthority"]
