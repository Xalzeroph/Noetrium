from __future__ import annotations

from contextlib import closing
from pathlib import Path
import sqlite3

from noetrium_platform.evidence.artifact._sqlite_connection import (
    connect_artifact_reader,
    connect_artifact_writer,
    rollback_artifact_writer,
)
from noetrium_platform.evidence.artifact._sqlite_types import require_text
from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.lineage.relation.api import (
    ArtifactLineageConflict,
    ArtifactLineageCorruptionError,
    ArtifactLineageCycle,
    ArtifactLineageEdge,
)
from noetrium_platform.foundation.kernel.kernel import strict_finite_json_text, strict_json_loads


class SQLiteArtifactLineageStore:
    """Append-only DAG over immutable Artifact content identities."""

    _COLUMNS = (
        "edge_id", "parent_artifact_id", "parent_content_sha256",
        "child_artifact_id", "child_content_sha256", "relation_type",
        "evidence_refs_json",
    )
    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path).expanduser().resolve()
        self.timeout_seconds = timeout_seconds
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with closing(self._connect_writer()) as db:
            self._ensure_schema(db)

    def _connect_writer(self) -> sqlite3.Connection:
        return connect_artifact_writer(self.path, timeout_seconds=self.timeout_seconds)

    def _connect_reader(self) -> sqlite3.Connection:
        return connect_artifact_reader(self.path, timeout_seconds=self.timeout_seconds)

    @classmethod
    def _ensure_schema(cls, db: sqlite3.Connection) -> None:
        db.executescript(
            """
            CREATE TABLE IF NOT EXISTS artifact_lineage_edges(
                edge_id TEXT PRIMARY KEY,
                parent_artifact_id TEXT NOT NULL,
                parent_content_sha256 TEXT NOT NULL,
                child_artifact_id TEXT NOT NULL,
                child_content_sha256 TEXT NOT NULL,
                relation_type TEXT NOT NULL,
                evidence_refs_json TEXT NOT NULL
            );
            """
        )
        columns = tuple(row[1] for row in db.execute("PRAGMA table_info(artifact_lineage_edges)"))
        if columns != cls._COLUMNS:
            raise ArtifactLineageCorruptionError(
                f"unsupported artifact lineage schema columns: {columns!r}"
            )
        db.executescript(
            """
            CREATE INDEX IF NOT EXISTS idx_lineage_parent
                ON artifact_lineage_edges(
                    parent_artifact_id,parent_content_sha256,
                    child_artifact_id,child_content_sha256,edge_id
                );
            CREATE INDEX IF NOT EXISTS idx_lineage_child
                ON artifact_lineage_edges(
                    child_artifact_id,child_content_sha256,
                    parent_artifact_id,parent_content_sha256,edge_id
                );
            """
        )

    @staticmethod
    def _content_document(value: ArtifactContentIdentity) -> dict[str, str]:
        return {
            "artifact_id": value.artifact_id,
            "content_sha256": value.content_sha256,
        }

    @classmethod
    def _evidence_text(cls, edge: ArtifactLineageEdge) -> str:
        return strict_finite_json_text(
            tuple(cls._content_document(ref) for ref in edge.evidence_refs)
        )

    @staticmethod
    def _decode_content(value: object, *, label: str) -> ArtifactContentIdentity:
        if not isinstance(value, dict) or set(value) != {"artifact_id", "content_sha256"}:
            raise TypeError(f"{label} must contain exact content identity fields")
        artifact_id = value.get("artifact_id")
        content_sha256 = value.get("content_sha256")
        if not isinstance(artifact_id, str) or not isinstance(content_sha256, str):
            raise TypeError(f"{label} content identity fields must be strings")
        return ArtifactContentIdentity(artifact_id, content_sha256)

    @classmethod
    def _decode(cls, row: tuple[object, ...]) -> ArtifactLineageEdge:
        try:
            evidence_raw = strict_json_loads(
                require_text(row[6], label="lineage evidence_refs_json")
            )
            if not isinstance(evidence_raw, list):
                raise TypeError("lineage evidence_refs_json must decode to a list")
            evidence = tuple(
                cls._decode_content(value, label="lineage evidence ref")
                for value in evidence_raw
            )
            edge = ArtifactLineageEdge(
                parent=ArtifactContentIdentity(
                    require_text(row[1], label="lineage parent_artifact_id"),
                    require_text(row[2], label="lineage parent_content_sha256"),
                ),
                child=ArtifactContentIdentity(
                    require_text(row[3], label="lineage child_artifact_id"),
                    require_text(row[4], label="lineage child_content_sha256"),
                ),
                relation_type=require_text(row[5], label="lineage relation_type"),
                evidence_refs=evidence,
            )
            stored_edge_id = require_text(row[0], label="lineage edge_id")
        except (IndexError, TypeError, ValueError) as exc:
            raise ArtifactLineageCorruptionError(
                "stored lineage edge cannot be decoded"
            ) from exc
        if edge.edge_id != stored_edge_id:
            raise ArtifactLineageCorruptionError(
                f"stored lineage edge identity mismatch: {row[0]}"
            )
        return edge

    @staticmethod
    def _would_cycle(db: sqlite3.Connection, edge: ArtifactLineageEdge) -> bool:
        row = db.execute(
            """
            WITH RECURSIVE descendants(artifact_id,content_sha256) AS (
                SELECT child_artifact_id,child_content_sha256
                FROM artifact_lineage_edges
                WHERE parent_artifact_id=? AND parent_content_sha256=?
                UNION
                SELECT e.child_artifact_id,e.child_content_sha256
                FROM artifact_lineage_edges e
                JOIN descendants d
                  ON e.parent_artifact_id=d.artifact_id
                 AND e.parent_content_sha256=d.content_sha256
            )
            SELECT 1 FROM descendants
            WHERE artifact_id=? AND content_sha256=? LIMIT 1
            """,
            (
                edge.child.artifact_id,
                edge.child.content_sha256,
                edge.parent.artifact_id,
                edge.parent.content_sha256,
            ),
        ).fetchone()
        return row is not None

    def add(self, edge: ArtifactLineageEdge) -> ArtifactLineageEdge:
        if type(edge) is not ArtifactLineageEdge:
            raise TypeError("edge must be ArtifactLineageEdge")
        with closing(self._connect_writer()) as db:
            db.execute("BEGIN IMMEDIATE")
            try:
                columns = ",".join(self._COLUMNS)
                row = db.execute(
                    f"SELECT {columns} FROM artifact_lineage_edges WHERE edge_id=?",
                    (edge.edge_id,),
                ).fetchone()
                if row is not None:
                    current = self._decode(row)
                    if current != edge:
                        raise ArtifactLineageConflict(edge.edge_id)
                    db.execute("COMMIT")
                    return current
                if self._would_cycle(db, edge):
                    raise ArtifactLineageCycle(
                        "lineage edge would create a cycle: "
                        f"{edge.parent.artifact_id} -> {edge.child.artifact_id}"
                    )
                db.execute(
                    "INSERT INTO artifact_lineage_edges VALUES(?,?,?,?,?,?,?)",
                    (
                        edge.edge_id,
                        edge.parent.artifact_id,
                        edge.parent.content_sha256,
                        edge.child.artifact_id,
                        edge.child.content_sha256,
                        edge.relation_type,
                        self._evidence_text(edge),
                    ),
                )
                db.execute("COMMIT")
            except BaseException as primary:
                rollback_artifact_writer(db, primary)
                raise
        return edge

    def _query(
        self,
        prefix: str,
        identity: ArtifactContentIdentity,
    ) -> tuple[ArtifactLineageEdge, ...]:
        if type(identity) is not ArtifactContentIdentity:
            raise TypeError("artifact lineage lookup identity must be ArtifactContentIdentity")
        if prefix not in {"parent", "child"}:
            raise ValueError("invalid lineage query prefix")
        columns = ",".join(self._COLUMNS)
        with closing(self._connect_reader()) as db:
            rows = db.execute(
                f"SELECT {columns} FROM artifact_lineage_edges "
                f"WHERE {prefix}_artifact_id=? AND {prefix}_content_sha256=? "
                "ORDER BY edge_id",
                (identity.artifact_id, identity.content_sha256),
            ).fetchall()
        return tuple(self._decode(row) for row in rows)

    def parents(
        self,
        child: ArtifactContentIdentity,
    ) -> tuple[ArtifactLineageEdge, ...]:
        return self._query("child", child)

    def children(
        self,
        parent: ArtifactContentIdentity,
    ) -> tuple[ArtifactLineageEdge, ...]:
        return self._query("parent", parent)


__all__ = ["SQLiteArtifactLineageStore"]
