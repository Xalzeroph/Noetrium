from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
import sqlite3
from typing import Iterator

from noetrium_platform.foundation.kernel.kernel import (
    CanonicalDecodingError, CanonicalEncodingError, ImmutableModelIdentity, canonical_digest,
    strict_finite_json_bytes, strict_json_loads,
)
from noetrium_platform.capabilities.model.catalog.revision.api.contracts import (
    ModelPromotionDecision,
    ModelPromotionReceipt,
    ModelRevisionAuthoritySnapshot,
    ModelRevisionCommit,
    ModelRevisionConflictError,
    ModelRevisionEvidence,
    ModelRevisionEvidenceKind,
    ModelRevisionIdentity,
    ModelRevisionIntegrityError,
    ModelRevisionStateError,
    ModelRollbackReceipt,
    ModelUpdateProposal,
    PreparedModelRevision,
)
from noetrium_platform.capabilities.model.catalog.revision.api.update import (
    ModelUpdateBuildEvidence,
    ModelUpdateBuildReceipt,
    ModelUpdatePlan,
    ModelUpdateSource,
)

_SCHEMA_VERSION = "model-revision-authority.sqlite.v2"
_TABLES = frozenset({"authority_meta", "revisions", "proposals", "prepared", "commits", "promotions", "rollbacks"})
JsonNode = str | int | None | list["JsonNode"] | tuple["JsonNode", ...] | dict[str, "JsonNode"]



def _loads(raw: bytes, *, field: str) -> dict[str, JsonNode]:
    try:
        value = strict_json_loads(raw)
    except CanonicalDecodingError as exc:
        raise ModelRevisionIntegrityError(f"{field} is not strict finite JSON") from exc
    if not isinstance(value, dict):
        raise ModelRevisionIntegrityError(f"{field} must decode to an object")
    return value



def _bytes(value: dict[str, JsonNode]) -> bytes:
    try:
        return strict_finite_json_bytes(value)
    except (CanonicalEncodingError, UnicodeEncodeError) as exc:
        raise ModelRevisionIntegrityError("revision payload cannot be encoded as strict finite JSON") from exc



def _expect(raw: dict[str, JsonNode], fields: frozenset[str], *, field: str) -> None:
    if frozenset(raw) != fields:
        raise ModelRevisionIntegrityError(f"{field} fields are invalid")


def _string(value: JsonNode, *, field: str, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value.strip() or value != value.strip():
        raise ModelRevisionIntegrityError(f"{field} must be canonical non-empty text")
    return value


def _integer(value: JsonNode, *, field: str) -> int:
    if type(value) is not int or value <= 0:
        raise ModelRevisionIntegrityError(f"{field} must be a positive integer")
    return value


def _encode_revision(value: ModelRevisionIdentity) -> bytes:
    model = value.model
    return _bytes({
        "lineage_contract_id": value.lineage_contract_id,
        "model": {
            "context_length": model.context_length,
            "dtype": model.dtype,
            "engine": model.engine,
            "engine_version": model.engine_version,
            "logical_name": model.logical_name,
            "model_id": model.model_id,
            "quantization": model.quantization,
            "revision": model.revision,
            "tokenizer_revision": model.tokenizer_revision,
        },
        "parent_revision_digest": value.parent_revision_digest,
        "revision_artifact_digest": value.revision_artifact_digest,
    })


def _decode_revision(raw: bytes) -> ModelRevisionIdentity:
    root = _loads(raw, field="model revision")
    _expect(root, frozenset({
        "lineage_contract_id", "model", "parent_revision_digest", "revision_artifact_digest",
    }), field="model revision")
    model_raw = root["model"]
    if not isinstance(model_raw, dict):
        raise ModelRevisionIntegrityError("model revision model must be an object")
    _expect(model_raw, frozenset({
        "context_length", "dtype", "engine", "engine_version", "logical_name", "model_id",
        "quantization", "revision", "tokenizer_revision",
    }), field="model revision model")
    try:
        model = ImmutableModelIdentity(
            logical_name=_string(model_raw["logical_name"], field="logical_name"),
            model_id=_string(model_raw["model_id"], field="model_id"),
            revision=_string(model_raw["revision"], field="revision"),
            engine=_string(model_raw["engine"], field="engine"),
            engine_version=_string(model_raw["engine_version"], field="engine_version"),
            dtype=_string(model_raw["dtype"], field="dtype"),
            quantization=_string(model_raw["quantization"], field="quantization", optional=True),
            context_length=_integer(model_raw["context_length"], field="context_length"),
            tokenizer_revision=_string(
                model_raw["tokenizer_revision"], field="tokenizer_revision", optional=True
            ),
        )
        return ModelRevisionIdentity(
            model=model,
            revision_artifact_digest=_string(
                root["revision_artifact_digest"], field="revision_artifact_digest"
            ),
            parent_revision_digest=_string(
                root["parent_revision_digest"], field="parent_revision_digest", optional=True
            ),
            lineage_contract_id=_string(root["lineage_contract_id"], field="lineage_contract_id"),
        )
    except (TypeError, ValueError) as exc:
        raise ModelRevisionIntegrityError("model revision payload is invalid") from exc


def _encode_proposal(value: ModelUpdateProposal) -> bytes:
    return _bytes({
        "configuration_digest": value.configuration_digest,
        "evidence_refs": list(value.evidence_refs),
        "implementation_digest": value.implementation_digest,
        "predecessor_revision_digest": value.predecessor_revision_digest,
        "proposal_id": value.proposal_id,
        "randomness_digest": value.randomness_digest,
        "training_input_digest": value.training_input_digest,
        "update_contract_id": value.update_contract_id,
    })


def _decode_proposal(raw: bytes) -> ModelUpdateProposal:
    root = _loads(raw, field="model update proposal")
    _expect(root, frozenset({
        "configuration_digest", "evidence_refs", "implementation_digest",
        "predecessor_revision_digest", "proposal_id", "randomness_digest",
        "training_input_digest", "update_contract_id",
    }), field="model update proposal")
    refs = root["evidence_refs"]
    if not isinstance(refs, list) or any(not isinstance(item, str) for item in refs):
        raise ModelRevisionIntegrityError("model update proposal evidence_refs are invalid")
    try:
        return ModelUpdateProposal(
            proposal_id=_string(root["proposal_id"], field="proposal_id"),
            predecessor_revision_digest=_string(
                root["predecessor_revision_digest"], field="predecessor_revision_digest"
            ),
            update_contract_id=_string(root["update_contract_id"], field="update_contract_id"),
            implementation_digest=_string(
                root["implementation_digest"], field="implementation_digest"
            ),
            configuration_digest=_string(
                root["configuration_digest"], field="configuration_digest"
            ),
            training_input_digest=_string(
                root["training_input_digest"], field="training_input_digest"
            ),
            randomness_digest=_string(
                root["randomness_digest"], field="randomness_digest", optional=True
            ),
            evidence_refs=tuple(refs),
        )
    except (TypeError, ValueError) as exc:
        raise ModelRevisionIntegrityError("model update proposal payload is invalid") from exc



def _encode_build_receipt(value: ModelUpdateBuildReceipt) -> bytes:
    plan = value.plan
    return _bytes({
        "build_evidence": [
            {
                "candidate_revision_digest": row.candidate_revision_digest,
                "evidence_digest": row.evidence_digest,
                "plan_digest": row.plan_digest,
                "producer_contract_id": row.producer_contract_id,
            }
            for row in value.build_evidence
        ],
        "plan": {
            "configuration_digest": plan.configuration_digest,
            "implementation_digest": plan.implementation_digest,
            "output_lineage_contract_id": plan.output_lineage_contract_id,
            "plan_id": plan.plan_id,
            "predecessor_revision_digest": plan.predecessor_revision_digest,
            "randomness_digest": plan.randomness_digest,
            "source_revisions": [
                {
                    "revision_digest": source.revision_digest,
                    "role": source.role,
                    "source_id": source.source_id,
                }
                for source in plan.source_revisions
            ],
            "training_input_digest": plan.training_input_digest,
            "update_contract_id": plan.update_contract_id,
        },
        "producer_contract_id": value.producer_contract_id,
        "producer_implementation_digest": value.producer_implementation_digest,
    })


def _decode_build_receipt(
    raw: bytes,
    *,
    proposal: ModelUpdateProposal,
    predecessor: ModelRevisionIdentity,
    candidate: ModelRevisionIdentity,
) -> ModelUpdateBuildReceipt:
    root = _loads(raw, field="model update build receipt")
    _expect(root, frozenset({
        "build_evidence", "plan", "producer_contract_id", "producer_implementation_digest",
    }), field="model update build receipt")
    plan_raw = root["plan"]
    if not isinstance(plan_raw, dict):
        raise ModelRevisionIntegrityError("model update build plan must be an object")
    _expect(plan_raw, frozenset({
        "configuration_digest", "implementation_digest", "output_lineage_contract_id", "plan_id",
        "predecessor_revision_digest", "randomness_digest", "source_revisions",
        "training_input_digest", "update_contract_id",
    }), field="model update build plan")
    sources_raw = plan_raw["source_revisions"]
    if not isinstance(sources_raw, list):
        raise ModelRevisionIntegrityError("model update build sources must be a list")
    sources: list[ModelUpdateSource] = []
    for index, source_raw in enumerate(sources_raw):
        if not isinstance(source_raw, dict):
            raise ModelRevisionIntegrityError(f"model update source[{index}] must be an object")
        _expect(source_raw, frozenset({"revision_digest", "role", "source_id"}), field=f"model update source[{index}]")
        try:
            sources.append(ModelUpdateSource(
                source_id=_string(source_raw["source_id"], field="source_id"),
                role=_string(source_raw["role"], field="source role"),
                revision_digest=_string(source_raw["revision_digest"], field="source revision digest"),
            ))
        except (TypeError, ValueError) as exc:
            raise ModelRevisionIntegrityError(f"model update source[{index}] is invalid") from exc
    evidence_raw = root["build_evidence"]
    if not isinstance(evidence_raw, list) or not evidence_raw:
        raise ModelRevisionIntegrityError("model update build evidence must be a non-empty list")
    evidence: list[ModelUpdateBuildEvidence] = []
    for index, row in enumerate(evidence_raw):
        if not isinstance(row, dict):
            raise ModelRevisionIntegrityError(f"model update build evidence[{index}] must be an object")
        _expect(row, frozenset({
            "candidate_revision_digest", "evidence_digest", "plan_digest", "producer_contract_id",
        }), field=f"model update build evidence[{index}]")
        try:
            evidence.append(ModelUpdateBuildEvidence(
                plan_digest=_string(row["plan_digest"], field="build evidence plan digest"),
                candidate_revision_digest=_string(row["candidate_revision_digest"], field="build evidence candidate digest"),
                evidence_digest=_string(row["evidence_digest"], field="build evidence digest"),
                producer_contract_id=_string(row["producer_contract_id"], field="build evidence producer contract"),
            ))
        except (TypeError, ValueError) as exc:
            raise ModelRevisionIntegrityError(f"model update build evidence[{index}] is invalid") from exc
    try:
        plan = ModelUpdatePlan(
            plan_id=_string(plan_raw["plan_id"], field="plan_id"),
            predecessor_revision_digest=_string(plan_raw["predecessor_revision_digest"], field="plan predecessor"),
            update_contract_id=_string(plan_raw["update_contract_id"], field="update contract"),
            implementation_digest=_string(plan_raw["implementation_digest"], field="update implementation"),
            configuration_digest=_string(plan_raw["configuration_digest"], field="update configuration"),
            training_input_digest=_string(plan_raw["training_input_digest"], field="training input"),
            randomness_digest=_string(plan_raw["randomness_digest"], field="randomness", optional=True),
            source_revisions=tuple(sources),
            output_lineage_contract_id=_string(plan_raw["output_lineage_contract_id"], field="output lineage contract"),
        )
        return ModelUpdateBuildReceipt(
            plan=plan,
            proposal=proposal,
            predecessor=predecessor,
            candidate=candidate,
            producer_contract_id=_string(root["producer_contract_id"], field="build producer contract"),
            producer_implementation_digest=_string(root["producer_implementation_digest"], field="build producer implementation"),
            build_evidence=tuple(evidence),
        )
    except (TypeError, ValueError) as exc:
        raise ModelRevisionIntegrityError("model update build receipt is invalid") from exc


def _encode_evidence(values: tuple[ModelRevisionEvidence, ...]) -> bytes:
    return _bytes({"evidence": [
        {
            "evidence_digest": value.evidence_digest,
            "kind": value.kind.value,
            "producer_contract_id": value.producer_contract_id,
            "revision_digest": value.revision_digest,
        }
        for value in values
    ]})


def _decode_evidence(raw: bytes) -> tuple[ModelRevisionEvidence, ...]:
    root = _loads(raw, field="model revision evidence")
    _expect(root, frozenset({"evidence"}), field="model revision evidence")
    rows = root["evidence"]
    if not isinstance(rows, list) or not rows:
        raise ModelRevisionIntegrityError("model revision evidence must be a non-empty list")
    result: list[ModelRevisionEvidence] = []
    for index, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ModelRevisionIntegrityError(f"model revision evidence[{index}] must be an object")
        _expect(row, frozenset({
            "evidence_digest", "kind", "producer_contract_id", "revision_digest",
        }), field=f"model revision evidence[{index}]")
        try:
            result.append(ModelRevisionEvidence(
                kind=ModelRevisionEvidenceKind(_string(row["kind"], field="kind")),
                revision_digest=_string(row["revision_digest"], field="revision_digest"),
                evidence_digest=_string(row["evidence_digest"], field="evidence_digest"),
                producer_contract_id=_string(
                    row["producer_contract_id"], field="producer_contract_id"
                ),
            ))
        except (TypeError, ValueError) as exc:
            raise ModelRevisionIntegrityError(
                f"model revision evidence[{index}] is invalid"
            ) from exc
    return tuple(result)


def _operation_digest(*, kind: str, fields: dict[str, JsonNode]) -> str:
    return canonical_digest({"kind": kind, **fields})


class SQLiteModelRevisionAuthority:
    """Crash-durable model revision authority with generation-fenced CAS transitions."""

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
            raise ModelRevisionIntegrityError("model revision database cannot be opened") from exc

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
            raise ModelRevisionIntegrityError("model revision transaction failed") from exc
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
            raise ModelRevisionIntegrityError("existing model revision database is empty")
        connection = self._connect()
        try:
            integrity = connection.execute("PRAGMA integrity_check").fetchone()
            if integrity is None or integrity[0] != "ok":
                raise ModelRevisionIntegrityError("model revision database integrity check failed")
            tables = frozenset(
                row[0] for row in connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                )
            )
            if tables != _TABLES:
                raise ModelRevisionIntegrityError("model revision database table set is invalid")
            row = connection.execute(
                "SELECT schema_version FROM authority_meta WHERE singleton=1"
            ).fetchone()
            if row is None or row[0] != _SCHEMA_VERSION:
                raise ModelRevisionIntegrityError("model revision database schema version is invalid")
        except sqlite3.DatabaseError as exc:
            raise ModelRevisionIntegrityError("model revision database schema is unreadable") from exc
        finally:
            connection.close()

    @staticmethod
    def _create_schema(connection: sqlite3.Connection) -> None:
        connection.execute("CREATE TABLE authority_meta (singleton INTEGER PRIMARY KEY CHECK(singleton=1), schema_version TEXT NOT NULL, generation INTEGER, active_digest TEXT, initial_digest TEXT)")
        connection.execute("CREATE TABLE revisions (digest TEXT PRIMARY KEY, parent_digest TEXT, payload BLOB NOT NULL, committed INTEGER NOT NULL CHECK(committed IN (0,1)))")
        connection.execute("CREATE TABLE proposals (digest TEXT PRIMARY KEY, payload BLOB NOT NULL)")
        connection.execute("CREATE TABLE prepared (proposal_digest TEXT PRIMARY KEY, prepared_digest TEXT NOT NULL UNIQUE, predecessor_digest TEXT NOT NULL, candidate_digest TEXT NOT NULL UNIQUE, generation INTEGER NOT NULL, recovery_anchor_digest TEXT NOT NULL, validation_plan_digest TEXT NOT NULL, build_receipt BLOB NOT NULL, status TEXT NOT NULL CHECK(status IN ('prepared','committed')), FOREIGN KEY(proposal_digest) REFERENCES proposals(digest), FOREIGN KEY(predecessor_digest) REFERENCES revisions(digest), FOREIGN KEY(candidate_digest) REFERENCES revisions(digest))")
        connection.execute("CREATE TABLE commits (candidate_digest TEXT PRIMARY KEY, prepared_digest TEXT NOT NULL UNIQUE, evidence BLOB NOT NULL, generation INTEGER NOT NULL, commit_digest TEXT NOT NULL UNIQUE, FOREIGN KEY(candidate_digest) REFERENCES revisions(digest))")
        connection.execute("CREATE TABLE promotions (decision_digest TEXT PRIMARY KEY, candidate_digest TEXT NOT NULL, predecessor_digest TEXT NOT NULL, generation INTEGER NOT NULL, receipt_digest TEXT NOT NULL UNIQUE)")
        connection.execute("CREATE TABLE rollbacks (operation_digest TEXT PRIMARY KEY, failed_digest TEXT NOT NULL, target_digest TEXT NOT NULL, evidence BLOB NOT NULL, recovery_anchor_digest TEXT NOT NULL, generation INTEGER NOT NULL, receipt_digest TEXT NOT NULL UNIQUE)")
        connection.execute(
            "INSERT INTO authority_meta(singleton,schema_version) VALUES(1,?)",
            (_SCHEMA_VERSION,),
        )

    @staticmethod
    def _meta(connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(
            "SELECT generation, active_digest, initial_digest FROM authority_meta WHERE singleton=1"
        ).fetchone()
        if row is None:
            raise ModelRevisionIntegrityError("model revision authority metadata is missing")
        return row

    @staticmethod
    def _require_initialized(row: sqlite3.Row) -> tuple[int, str, str]:
        generation, active, initial = row["generation"], row["active_digest"], row["initial_digest"]
        if type(generation) is not int or generation <= 0:
            raise ModelRevisionStateError("model revision authority is not initialized")
        if not isinstance(active, str) or not isinstance(initial, str):
            raise ModelRevisionIntegrityError("initialized model revision metadata is invalid")
        return generation, active, initial

    @staticmethod
    def _expect_generation(current: int, expected: int) -> None:
        if type(expected) is not int or expected <= 0:
            raise ValueError("expected_generation must be a positive integer")
        if current != expected:
            raise ModelRevisionConflictError(
                f"stale model revision generation: expected {expected}, current {current}"
            )

    @staticmethod
    def _next_generation(current: int) -> int:
        return current + 1

    @staticmethod
    def _load_revision(connection: sqlite3.Connection, digest: str) -> ModelRevisionIdentity:
        row = connection.execute(
            "SELECT payload FROM revisions WHERE digest=?", (digest,)
        ).fetchone()
        if row is None:
            raise ModelRevisionIntegrityError("referenced model revision is missing")
        revision = _decode_revision(bytes(row["payload"]))
        if revision.digest() != digest:
            raise ModelRevisionIntegrityError("stored model revision digest mismatch")
        return revision

    @staticmethod
    def _load_proposal(connection: sqlite3.Connection, digest: str) -> ModelUpdateProposal:
        row = connection.execute(
            "SELECT payload FROM proposals WHERE digest=?", (digest,)
        ).fetchone()
        if row is None:
            raise ModelRevisionIntegrityError("referenced model update proposal is missing")
        proposal = _decode_proposal(bytes(row["payload"]))
        if proposal.digest() != digest:
            raise ModelRevisionIntegrityError("stored model update proposal digest mismatch")
        return proposal

    @classmethod
    def _prepared_from_row(
        cls, connection: sqlite3.Connection, row: sqlite3.Row
    ) -> PreparedModelRevision:
        proposal = cls._load_proposal(connection, row["proposal_digest"])
        predecessor = cls._load_revision(connection, row["predecessor_digest"])
        candidate = cls._load_revision(connection, row["candidate_digest"])
        try:
            build_receipt = _decode_build_receipt(
                bytes(row["build_receipt"]),
                proposal=proposal, predecessor=predecessor, candidate=candidate,
            )
            prepared = PreparedModelRevision(
                proposal=proposal,
                predecessor=predecessor,
                candidate=candidate,
                build_receipt_digest=build_receipt.digest(),
                preparation_generation=row["generation"],
                recovery_anchor_digest=row["recovery_anchor_digest"],
                validation_plan_digest=row["validation_plan_digest"],
            )
        except (TypeError, ValueError) as exc:
            raise ModelRevisionIntegrityError("stored prepared model revision is invalid") from exc
        if prepared.digest() != row["prepared_digest"]:
            raise ModelRevisionIntegrityError("stored prepared model revision digest mismatch")
        return prepared

    def initialize(self, initial: ModelRevisionIdentity) -> ModelRevisionAuthoritySnapshot:
        if not isinstance(initial, ModelRevisionIdentity):
            raise TypeError("initial model revision must be ModelRevisionIdentity")
        digest = initial.digest()
        with self._transaction() as connection:
            meta = self._meta(connection)
            if meta["generation"] is not None:
                current = self._require_initialized(meta)
                if current[2] != digest:
                    raise ModelRevisionStateError("model revision authority already has another initial revision")
                return self._snapshot(connection)
            connection.execute(
                "INSERT INTO revisions(digest,parent_digest,payload,committed) VALUES(?,?,?,1)",
                (digest, initial.parent_revision_digest, _encode_revision(initial)),
            )
            connection.execute(
                "UPDATE authority_meta SET generation=1,active_digest=?,initial_digest=? WHERE singleton=1",
                (digest, digest),
            )
            return self._snapshot(connection)

    @classmethod
    def _snapshot(cls, connection: sqlite3.Connection) -> ModelRevisionAuthoritySnapshot:
        generation, active_digest, _ = cls._require_initialized(cls._meta(connection))
        active = cls._load_revision(connection, active_digest)
        committed = tuple(row[0] for row in connection.execute(
            "SELECT digest FROM revisions WHERE committed=1 ORDER BY digest"
        ))
        prepared = tuple(row[0] for row in connection.execute(
            "SELECT prepared_digest FROM prepared WHERE status='prepared' ORDER BY prepared_digest"
        ))
        try:
            return ModelRevisionAuthoritySnapshot(generation, active, committed, prepared)
        except (TypeError, ValueError) as exc:
            raise ModelRevisionIntegrityError("model revision snapshot is invalid") from exc

    def snapshot(self) -> ModelRevisionAuthoritySnapshot:
        connection = self._connect()
        try:
            return self._snapshot(connection)
        finally:
            connection.close()

    def load_prepared(self, proposal_digest: str) -> PreparedModelRevision:
        connection = self._connect()
        try:
            row = connection.execute(
                "SELECT * FROM prepared WHERE proposal_digest=?", (proposal_digest,)
            ).fetchone()
            if row is None:
                raise KeyError(proposal_digest)
            return self._prepared_from_row(connection, row)
        except sqlite3.DatabaseError as exc:
            raise ModelRevisionIntegrityError("prepared model revision cannot be read") from exc
        finally:
            connection.close()

    def prepare_successor(
        self,
        build_receipt: ModelUpdateBuildReceipt,
        *,
        expected_generation: int,
        recovery_anchor_digest: str,
        validation_plan_digest: str,
    ) -> PreparedModelRevision:
        if not isinstance(build_receipt, ModelUpdateBuildReceipt):
            raise TypeError("model revision prepare requires ModelUpdateBuildReceipt")
        proposal = build_receipt.proposal
        predecessor = build_receipt.predecessor
        candidate = build_receipt.candidate
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
                    or prepared.build_receipt_digest != build_receipt.digest()
                    or prepared.recovery_anchor_digest != recovery_anchor_digest
                    or prepared.validation_plan_digest != validation_plan_digest
                ):
                    raise ModelRevisionStateError("model update proposal identity was reused with different prepare facts")
                return prepared
            generation, active_digest, _ = self._require_initialized(self._meta(connection))
            self._expect_generation(generation, expected_generation)
            predecessor_digest = predecessor.digest()
            if active_digest != predecessor_digest:
                raise ModelRevisionConflictError("model update predecessor is not the current active revision")
            stored_predecessor = self._load_revision(connection, predecessor_digest)
            if stored_predecessor != predecessor:
                raise ModelRevisionIntegrityError("model update predecessor payload drift")
            next_generation = self._next_generation(generation)
            prepared = PreparedModelRevision(
                proposal, predecessor, candidate, build_receipt.digest(), next_generation,
                recovery_anchor_digest, validation_plan_digest,
            )
            candidate_digest = candidate.digest()
            collision = connection.execute(
                "SELECT payload FROM revisions WHERE digest=?", (candidate_digest,)
            ).fetchone()
            if collision is not None:
                stored_candidate = _decode_revision(bytes(collision["payload"]))
                if stored_candidate != candidate:
                    raise ModelRevisionIntegrityError("model candidate digest collision")
                raise ModelRevisionStateError("model candidate is already registered by another transition")
            connection.execute(
                "INSERT INTO proposals(digest,payload) VALUES(?,?)",
                (proposal_digest, _encode_proposal(proposal)),
            )
            connection.execute(
                "INSERT INTO revisions(digest,parent_digest,payload,committed) VALUES(?,?,?,0)",
                (candidate_digest, candidate.parent_revision_digest, _encode_revision(candidate)),
            )
            connection.execute(
                "INSERT INTO prepared(proposal_digest,prepared_digest,predecessor_digest,candidate_digest,generation,recovery_anchor_digest,validation_plan_digest,build_receipt,status) VALUES(?,?,?,?,?,?,?,?,'prepared')",
                (
                    proposal_digest, prepared.digest(), predecessor_digest, candidate_digest,
                    next_generation, recovery_anchor_digest, validation_plan_digest,
                    _encode_build_receipt(build_receipt),
                ),
            )
            connection.execute(
                "UPDATE authority_meta SET generation=? WHERE singleton=1", (next_generation,)
            )
            return prepared

    def commit_successor(
        self,
        prepared: PreparedModelRevision,
        validation_evidence: tuple[ModelRevisionEvidence, ...],
        *,
        expected_generation: int,
    ) -> ModelRevisionCommit:
        if not isinstance(prepared, PreparedModelRevision):
            raise TypeError("model revision commit requires PreparedModelRevision")
        candidate_digest = prepared.candidate.digest()
        candidate_commit = ModelRevisionCommit(prepared, validation_evidence, 1)
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM commits WHERE candidate_digest=?", (candidate_digest,)
            ).fetchone()
            if existing is not None:
                stored_prepared_row = connection.execute(
                    "SELECT * FROM prepared WHERE prepared_digest=?", (existing["prepared_digest"],)
                ).fetchone()
                if stored_prepared_row is None:
                    raise ModelRevisionIntegrityError("committed model revision lost prepared state")
                stored_prepared = self._prepared_from_row(connection, stored_prepared_row)
                stored_evidence = _decode_evidence(bytes(existing["evidence"]))
                stored = ModelRevisionCommit(stored_prepared, stored_evidence, existing["generation"])
                if stored.prepared != prepared or stored.validation_evidence != candidate_commit.validation_evidence:
                    raise ModelRevisionStateError("model candidate commit was retried with different facts")
                if stored.digest() != existing["commit_digest"]:
                    raise ModelRevisionIntegrityError("stored model revision commit digest mismatch")
                return stored
            generation, active_digest, _ = self._require_initialized(self._meta(connection))
            self._expect_generation(generation, expected_generation)
            if active_digest != prepared.predecessor.digest():
                raise ModelRevisionConflictError("prepared model predecessor is no longer active")
            prepared_row = connection.execute(
                "SELECT * FROM prepared WHERE prepared_digest=?", (prepared.digest(),)
            ).fetchone()
            if prepared_row is None:
                raise ModelRevisionStateError("model revision was not prepared by this authority")
            stored_prepared = self._prepared_from_row(connection, prepared_row)
            if stored_prepared != prepared:
                raise ModelRevisionIntegrityError("prepared model revision payload drift")
            if prepared_row["status"] != "prepared":
                raise ModelRevisionStateError("prepared model revision is not pending commit")
            next_generation = self._next_generation(generation)
            commit = ModelRevisionCommit(prepared, validation_evidence, next_generation)
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
            connection.execute("UPDATE authority_meta SET generation=? WHERE singleton=1", (next_generation,))
            return commit

    def promote(
        self,
        decision: ModelPromotionDecision,
        *,
        expected_generation: int,
    ) -> ModelPromotionReceipt:
        if not isinstance(decision, ModelPromotionDecision):
            raise TypeError("model promotion requires ModelPromotionDecision")
        probe = ModelPromotionReceipt(decision, 1)
        decision_digest = decision.digest()
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM promotions WHERE decision_digest=?", (decision_digest,)
            ).fetchone()
            if existing is not None:
                _, active_digest, _ = self._require_initialized(self._meta(connection))
                if active_digest != existing["candidate_digest"]:
                    raise ModelRevisionConflictError(
                        "historical model promotion is no longer the active transition"
                    )
                stored = ModelPromotionReceipt(decision, existing["generation"])
                if stored.digest() != existing["receipt_digest"]:
                    raise ModelRevisionIntegrityError("stored model promotion receipt digest mismatch")
                return stored
            generation, active_digest, _ = self._require_initialized(self._meta(connection))
            self._expect_generation(generation, expected_generation)
            if active_digest != decision.predecessor_active_revision_digest:
                raise ModelRevisionConflictError("model promotion predecessor is not current active revision")
            commit_row = connection.execute(
                "SELECT c.commit_digest,p.predecessor_digest FROM commits c "
                "JOIN prepared p ON p.prepared_digest=c.prepared_digest "
                "WHERE c.candidate_digest=?",
                (decision.candidate_revision_digest,),
            ).fetchone()
            if commit_row is None:
                raise ModelRevisionStateError("model promotion candidate is not committed")
            if commit_row["predecessor_digest"] != active_digest:
                raise ModelRevisionStateError("model promotion candidate is not the exact committed successor")
            candidate = self._load_revision(connection, decision.candidate_revision_digest)
            if candidate.parent_revision_digest != active_digest:
                raise ModelRevisionIntegrityError("committed model candidate lineage is invalid")
            next_generation = self._next_generation(generation)
            receipt = ModelPromotionReceipt(decision, next_generation)
            connection.execute(
                "INSERT INTO promotions(decision_digest,candidate_digest,predecessor_digest,generation,receipt_digest) VALUES(?,?,?,?,?)",
                (
                    decision_digest, decision.candidate_revision_digest,
                    decision.predecessor_active_revision_digest, next_generation, receipt.digest(),
                ),
            )
            connection.execute(
                "UPDATE authority_meta SET generation=?,active_digest=? WHERE singleton=1",
                (next_generation, decision.candidate_revision_digest),
            )
            return receipt

    @staticmethod
    def _is_committed_ancestor(
        connection: sqlite3.Connection, *, descendant: str, ancestor: str
    ) -> bool:
        """Resolve strict committed ancestry with one recursive database query.

        Algorithm-Complexity: O(D)
        Algorithm-Rationale: D is lineage depth; one recursive CTE loads the lineage once, then validation walks the returned rows without database I/O inside the loop.
        """
        rows = connection.execute(
            "WITH RECURSIVE lineage(digest,parent_digest,committed,path,cycle) AS ("
            " SELECT digest,parent_digest,committed,',' || digest || ',',0"
            " FROM revisions WHERE digest=?"
            " UNION ALL"
            " SELECT r.digest,r.parent_digest,r.committed,lineage.path || r.digest || ',',"
            " instr(lineage.path, ',' || r.digest || ',') > 0"
            " FROM lineage JOIN revisions r ON r.digest=lineage.parent_digest"
            " WHERE lineage.parent_digest IS NOT NULL AND lineage.cycle=0"
            ") SELECT digest,parent_digest,committed,cycle FROM lineage",
            (descendant,),
        ).fetchall()
        if not rows:
            raise ModelRevisionIntegrityError("model revision lineage references a missing revision")
        digests: list[str] = []
        for row in rows:
            digest = row["digest"]
            parent = row["parent_digest"]
            if not isinstance(digest, str) or (parent is not None and not isinstance(parent, str)):
                raise ModelRevisionIntegrityError("model revision lineage contains an invalid digest")
            if row["committed"] != 1:
                raise ModelRevisionIntegrityError("model revision lineage references an uncommitted revision")
            if row["cycle"]:
                raise ModelRevisionIntegrityError("model revision lineage contains a cycle")
            digests.append(digest)
        if rows[-1]["parent_digest"] is not None:
            raise ModelRevisionIntegrityError("model revision lineage references a missing parent")
        return ancestor in digests[1:]

    def rollback(
        self,
        failed_active_revision_digest: str,
        rollback_target_revision_digest: str,
        triggering_evidence: tuple[ModelRevisionEvidence, ...],
        *,
        recovery_anchor_digest: str,
        expected_generation: int,
    ) -> ModelRollbackReceipt:
        probe = ModelRollbackReceipt(
            failed_active_revision_digest,
            rollback_target_revision_digest,
            triggering_evidence,
            recovery_anchor_digest,
            1,
        )
        operation_digest = _operation_digest(
            kind="rollback",
            fields={
                "evidence": tuple(item.digest() for item in probe.triggering_evidence),
                "failed": failed_active_revision_digest,
                "recovery_anchor": recovery_anchor_digest,
                "target": rollback_target_revision_digest,
            },
        )
        with self._transaction() as connection:
            existing = connection.execute(
                "SELECT * FROM rollbacks WHERE operation_digest=?", (operation_digest,)
            ).fetchone()
            if existing is not None:
                _, active_digest, _ = self._require_initialized(self._meta(connection))
                if active_digest != existing["target_digest"]:
                    raise ModelRevisionConflictError(
                        "historical model rollback is no longer the active transition"
                    )
                stored_evidence = _decode_evidence(bytes(existing["evidence"]))
                stored = ModelRollbackReceipt(
                    existing["failed_digest"], existing["target_digest"], stored_evidence,
                    existing["recovery_anchor_digest"], existing["generation"],
                )
                if stored.triggering_evidence != probe.triggering_evidence:
                    raise ModelRevisionIntegrityError("stored model rollback evidence drift")
                if stored.digest() != existing["receipt_digest"]:
                    raise ModelRevisionIntegrityError("stored model rollback receipt digest mismatch")
                return stored
            generation, active_digest, _ = self._require_initialized(self._meta(connection))
            self._expect_generation(generation, expected_generation)
            if active_digest != failed_active_revision_digest:
                raise ModelRevisionConflictError("rollback failed revision is not current active revision")
            if not self._is_committed_ancestor(
                connection,
                descendant=failed_active_revision_digest,
                ancestor=rollback_target_revision_digest,
            ):
                raise ModelRevisionStateError("model rollback target is not a committed ancestor")
            next_generation = self._next_generation(generation)
            receipt = ModelRollbackReceipt(
                failed_active_revision_digest,
                rollback_target_revision_digest,
                triggering_evidence,
                recovery_anchor_digest,
                next_generation,
            )
            connection.execute(
                "INSERT INTO rollbacks(operation_digest,failed_digest,target_digest,evidence,recovery_anchor_digest,generation,receipt_digest) VALUES(?,?,?,?,?,?,?)",
                (
                    operation_digest, failed_active_revision_digest, rollback_target_revision_digest,
                    _encode_evidence(receipt.triggering_evidence), recovery_anchor_digest,
                    next_generation, receipt.digest(),
                ),
            )
            connection.execute(
                "UPDATE authority_meta SET generation=?,active_digest=? WHERE singleton=1",
                (next_generation, rollback_target_revision_digest),
            )
            return receipt


__all__ = ["SQLiteModelRevisionAuthority"]
