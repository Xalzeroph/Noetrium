from __future__ import annotations

import json
from pathlib import Path
import sqlite3

from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_connection,
    durable_sqlite_reader,
    immediate_sqlite_transaction,
)
from noetrium_platform.infrastructure.resources.compute.api import ComputeCluster, ComputeGPU, ComputeHost
from noetrium_platform.foundation.governance.api import (
    scope_from_data,
    scope_to_data,
)
from noetrium_platform.foundation.kernel.unit import NoetriumUnit


class ComputeInventory:
    """Restart-safe compute host/cluster catalog with atomic identity writes."""

    SCHEMA_VERSION = 1

    def __init__(self, path: str | Path, *, timeout_seconds: float = 30.0) -> None:
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS compute_meta(key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS compute_hosts(host_id TEXT PRIMARY KEY, payload TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS compute_clusters(cluster_id TEXT PRIMARY KEY, payload TEXT NOT NULL);"
            )
            conn.execute(
                "INSERT OR IGNORE INTO compute_meta(key,value) VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )
            row = conn.execute(
                "SELECT value FROM compute_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None or int(row[0]) != self.SCHEMA_VERSION:
                raise RuntimeError("unsupported ComputeInventory schema")

    def _connection(self):
        return durable_sqlite_connection(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    def _reader(self):
        return durable_sqlite_reader(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    @staticmethod
    def _scope(value: NoetriumUnit) -> dict[str, str]:
        return scope_to_data(value)

    @staticmethod
    def _decode_scope(value: dict[str, str]) -> NoetriumUnit:
        return scope_from_data(value)

    @classmethod
    def _host_payload(cls, host: ComputeHost) -> str:
        return json.dumps({
            "host_id": host.host_id,
            "scope": cls._scope(host.scope),
            "cpu_cores": host.cpu_cores,
            "memory_bytes": host.memory_bytes,
            "gpus": [
                {"gpu_id": gpu.gpu_id, "memory_bytes": gpu.memory_bytes,
                 "model": gpu.model, "labels": list(gpu.labels)}
                for gpu in host.gpus
            ],
            "labels": list(host.labels),
            "enabled": host.enabled,
        }, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _decode_host(cls, payload: str) -> ComputeHost:
        value = json.loads(payload)
        gpus = tuple(
            ComputeGPU(
                row["gpu_id"], int(row["memory_bytes"]), row["model"],
                tuple(tuple(item) for item in row["labels"]),
            )
            for row in value["gpus"]
        )
        return ComputeHost(
            value["host_id"], cls._decode_scope(value["scope"]),
            int(value["cpu_cores"]), int(value["memory_bytes"]), gpus,
            tuple(tuple(item) for item in value["labels"]), bool(value["enabled"]),
        )

    @classmethod
    def _cluster_payload(cls, cluster: ComputeCluster) -> str:
        return json.dumps({
            "cluster_id": cluster.cluster_id, "scope": cls._scope(cluster.scope),
            "host_ids": list(cluster.host_ids), "labels": list(cluster.labels),
        }, sort_keys=True, separators=(",", ":"))

    @classmethod
    def _decode_cluster(cls, payload: str) -> ComputeCluster:
        value = json.loads(payload)
        return ComputeCluster(
            value["cluster_id"], cls._decode_scope(value["scope"]),
            tuple(value["host_ids"]), tuple(tuple(item) for item in value["labels"]),
        )

    def _put(self, table: str, key: str, payload: str) -> None:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="compute inventory",
            ):
                conn.execute(
                    f"INSERT OR IGNORE INTO {table}({('host_id' if table == 'compute_hosts' else 'cluster_id')},payload) VALUES(?,?)",
                    (key, payload),
                )

    def register_host(self, host: ComputeHost) -> None:
        """Publish the latest observed facts for one stable compute-host identity.

        Host id plus scope is identity. CPU/RAM capacity, attached GPU set and
        GPU topology labels are inventory observations and may legitimately
        change across process restarts, cgroup reconfiguration or hardware
        maintenance. Exact warm re-registration stays read-only; changed facts
        are atomically refreshed after proving scope stability and global GPU
        UUID uniqueness.
        """
        if not isinstance(host, ComputeHost):
            raise TypeError("compute inventory requires ComputeHost")
        payload = self._host_payload(host)

        # Exact warm attachment avoids SQLite's writer lock/fsync path.
        with self._reader() as conn:
            row = conn.execute(
                "SELECT payload FROM compute_hosts WHERE host_id=?",
                (host.host_id,),
            ).fetchone()
        if row is not None and str(row[0]) == payload:
            return

        gpu_ids = frozenset(gpu.gpu_id for gpu in host.gpus)
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="compute host inventory refresh",
            ):
                current_row = conn.execute(
                    "SELECT payload FROM compute_hosts WHERE host_id=?",
                    (host.host_id,),
                ).fetchone()
                if current_row is not None:
                    current = self._decode_host(str(current_row[0]))
                    if current.scope != host.scope:
                        raise ValueError(
                            "compute host identity scope drifted: "
                            + host.host_id
                        )
                    if str(current_row[0]) == payload:
                        return

                rows = conn.execute(
                    "SELECT host_id,payload FROM compute_hosts "
                    "WHERE host_id<>? ORDER BY host_id",
                    (host.host_id,),
                ).fetchall()
                for _existing_id, existing_payload in rows:
                    existing = self._decode_host(str(existing_payload))
                    overlap = gpu_ids.intersection(
                        gpu.gpu_id for gpu in existing.gpus
                    )
                    if overlap:
                        raise ValueError(
                            "GPU identity registered by multiple compute hosts: "
                            + ",".join(sorted(overlap))
                        )

                conn.execute(
                    "INSERT INTO compute_hosts(host_id,payload) VALUES(?,?) "
                    "ON CONFLICT(host_id) DO UPDATE SET payload=excluded.payload",
                    (host.host_id, payload),
                )

    def host(self, host_id: str) -> ComputeHost:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT payload FROM compute_hosts WHERE host_id=?", (host_id,)
            ).fetchone()
        if row is None:
            raise KeyError(host_id)
        return self._decode_host(str(row[0]))

    def list_hosts(self, *, scope: NoetriumUnit | None = None) -> tuple[ComputeHost, ...]:
        with self._reader() as conn:
            rows = conn.execute(
                "SELECT payload FROM compute_hosts ORDER BY host_id"
            ).fetchall()
        hosts = tuple(self._decode_host(str(row[0])) for row in rows)
        return tuple(host for host in hosts if scope is None or host.scope == scope)

    def register_cluster(self, cluster: ComputeCluster) -> None:
        missing = [host_id for host_id in cluster.host_ids
                   if not self._exists("compute_hosts", "host_id", host_id)]
        if missing:
            raise KeyError(missing[0])
        payload = self._cluster_payload(cluster)
        self._put("compute_clusters", cluster.cluster_id, payload)
        if self.cluster(cluster.cluster_id) != cluster:
            raise ValueError(f"cluster identity already registered: {cluster.cluster_id}")

    def _exists(self, table: str, key_column: str, key: str) -> bool:
        with self._reader() as conn:
            return conn.execute(
                f"SELECT 1 FROM {table} WHERE {key_column}=?", (key,)
            ).fetchone() is not None

    def cluster(self, cluster_id: str) -> ComputeCluster:
        with self._reader() as conn:
            row = conn.execute(
                "SELECT payload FROM compute_clusters WHERE cluster_id=?", (cluster_id,)
            ).fetchone()
        if row is None:
            raise KeyError(cluster_id)
        return self._decode_cluster(str(row[0]))


__all__ = ["ComputeInventory"]
