from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel.durability.sqlite import (
    durable_sqlite_connection,
    immediate_sqlite_transaction,
)
from noetrium_platform.foundation.kernel.structure import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit
from noetrium_platform.research.experimentation.lifecycle.experiment.api.unit_semantics import (
    experiment_id,
    experiment_project_id,
    experiment_study_id,
    require_experiment_unit,
)
from noetrium_platform.research.experimentation.lifecycle.run.api import RunIdentity
from noetrium_platform.research.experimentation.lifecycle.study.api.unit_semantics import (
    require_study_unit,
    study_experiment_id,
    study_id,
    study_project_id,
)
from noetrium_platform.research.execution.api import (
    ScopeIndexPort,
    ScopeKind,
    scope_key,
    scope_unit,
)


class ExperimentationCatalogConflict(RuntimeError):
    pass


class ExperimentationCatalogNotFound(KeyError):
    pass


def _study_scope(value: NoetriumUnit) -> NoetriumUnit:
    return scope_unit(ScopeKind.STUDY, study_id(require_study_unit(value)))


def _experiment_scope(value: NoetriumUnit) -> NoetriumUnit:
    return scope_unit(ScopeKind.EXPERIMENT, experiment_id(require_experiment_unit(value)))


def _unit_payload(value: NoetriumUnit) -> bytes:
    if type(value) is not NoetriumUnit:
        raise TypeError("experimentation catalog static value must be NoetriumUnit")
    return encode_unit(value)


def _unit_from_payload(value: object) -> NoetriumUnit:
    if isinstance(value, memoryview):
        value = value.tobytes()
    if type(value) is not bytes:
        raise TypeError("experimentation catalog Unit payload must be bytes")
    return decode_unit(value)


class InMemoryExperimentationCatalog:
    """Rebuildable Study/Experiment/Run hierarchy projection over Unit truth."""

    def __init__(self, scopes: ScopeIndexPort) -> None:
        self._scopes = scopes
        self._studies: dict[str, NoetriumUnit] = {}
        self._experiments: dict[str, NoetriumUnit] = {}
        self._runs: dict[str, tuple[str, RunIdentity]] = {}

    @staticmethod
    def _put(store: dict[str, object], key: str, value: object) -> None:
        current = store.get(key)
        if current is not None and current != value:
            raise ExperimentationCatalogConflict(key)
        store[key] = value

    def register_study(self, spec: NoetriumUnit) -> None:
        spec = require_study_unit(spec)
        parent = scope_unit(ScopeKind.PROJECT, study_project_id(spec))
        if not self._scopes.contains(parent):
            raise ExperimentationCatalogNotFound(scope_key(parent))
        key = study_id(spec)
        self._put(self._studies, key, spec)
        self._scopes.register(_study_scope(spec), parent)

    def register_experiment(self, spec: NoetriumUnit) -> None:
        spec = require_experiment_unit(spec)
        parent_id = experiment_study_id(spec)
        try:
            study = self._studies[parent_id]
        except KeyError as exc:
            raise ExperimentationCatalogNotFound(parent_id) from exc
        if study_project_id(study) != experiment_project_id(spec):
            raise ExperimentationCatalogConflict(
                "experiment project_id does not match its Study"
            )
        if study_experiment_id(study) != experiment_id(spec):
            raise ExperimentationCatalogConflict(
                "experiment is not declared by its Study"
            )
        key = experiment_id(spec)
        self._put(self._experiments, key, spec)
        self._scopes.register(_experiment_scope(spec), _study_scope(study))

    def register_run(self, experiment_id_value: str, identity: RunIdentity) -> None:
        try:
            experiment = self._experiments[experiment_id_value]
        except KeyError as exc:
            raise ExperimentationCatalogNotFound(experiment_id_value) from exc
        value = (experiment_id_value, identity)
        self._put(self._runs, identity.run_id, value)
        self._scopes.register(identity.scope, _experiment_scope(experiment))

    def study(self, study_id_value: str) -> NoetriumUnit:
        try:
            return self._studies[study_id_value]
        except KeyError as exc:
            raise ExperimentationCatalogNotFound(study_id_value) from exc

    def experiment(self, experiment_id_value: str) -> NoetriumUnit:
        try:
            return self._experiments[experiment_id_value]
        except KeyError as exc:
            raise ExperimentationCatalogNotFound(experiment_id_value) from exc

    def experiments(
        self,
        *,
        study_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        rows = self._experiments.values()
        if study_id is not None:
            rows = (
                row
                for row in rows
                if experiment_study_id(row) == study_id
            )
        return tuple(sorted(rows, key=experiment_id))


class SQLiteExperimentationCatalog:
    """Crash-durable rebuildable hierarchy projection over exact Unit documents."""

    SCHEMA_VERSION = 3

    def __init__(
        self,
        path: str | Path,
        scopes: ScopeIndexPort,
        *,
        timeout_seconds: float = 30.0,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("experimentation SQLite timeout must be positive")
        self.path = Path(path).absolute()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._scopes = scopes
        self.timeout_seconds = float(timeout_seconds)
        with self._connection() as conn:
            conn.executescript(
                "CREATE TABLE IF NOT EXISTS experimentation_meta("
                "key TEXT PRIMARY KEY, value TEXT NOT NULL);"
                "CREATE TABLE IF NOT EXISTS studies("
                "study_id TEXT PRIMARY KEY, project_id TEXT NOT NULL, payload BLOB NOT NULL);"
                "CREATE TABLE IF NOT EXISTS experiments("
                "experiment_id TEXT PRIMARY KEY, study_id TEXT NOT NULL,"
                "project_id TEXT NOT NULL, payload BLOB NOT NULL);"
                "CREATE TABLE IF NOT EXISTS runs("
                "run_id TEXT PRIMARY KEY, experiment_id TEXT NOT NULL, payload TEXT NOT NULL);"
            )
            conn.execute(
                "INSERT OR IGNORE INTO experimentation_meta(key,value) "
                "VALUES('schema_version',?)",
                (str(self.SCHEMA_VERSION),),
            )
            row = conn.execute(
                "SELECT value FROM experimentation_meta WHERE key='schema_version'"
            ).fetchone()
            if row is None or int(row[0]) != self.SCHEMA_VERSION:
                raise RuntimeError(
                    "unsupported SQLiteExperimentationCatalog schema; "
                    "retired static-carrier catalogs are not compatible"
                )
        self.rebuild_scope_index()

    def _connection(self):
        return durable_sqlite_connection(
            self.path,
            timeout_seconds=self.timeout_seconds,
        )

    @staticmethod
    def _decode_run(payload: str) -> RunIdentity:
        value = json.loads(payload)
        return RunIdentity(
            str(value["run_id"]),
            str(value["session_id"]),
            str(value["trace_id"]),
        )

    @staticmethod
    def _run_payload(identity: RunIdentity) -> str:
        return json.dumps(
            asdict(identity),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )

    def _insert(self, statement: str, values: tuple[object, ...]) -> None:
        with self._connection() as conn:
            with immediate_sqlite_transaction(
                conn,
                timeout_seconds=self.timeout_seconds,
                label="experimentation catalog",
            ):
                conn.execute(statement, values)

    def rebuild_scope_index(self) -> None:
        with self._connection() as conn:
            studies = conn.execute(
                "SELECT payload FROM studies ORDER BY study_id"
            ).fetchall()
            experiments = conn.execute(
                "SELECT payload FROM experiments ORDER BY experiment_id"
            ).fetchall()
            runs = conn.execute(
                "SELECT experiment_id,payload FROM runs ORDER BY run_id"
            ).fetchall()

        study_by_id: dict[str, NoetriumUnit] = {}
        experiment_by_id: dict[str, NoetriumUnit] = {}
        for (payload,) in studies:
            spec = require_study_unit(_unit_from_payload(payload))
            study_by_id[study_id(spec)] = spec
            self._scopes.register(
                _study_scope(spec),
                scope_unit(ScopeKind.PROJECT, study_project_id(spec)),
            )
        for (payload,) in experiments:
            spec = require_experiment_unit(_unit_from_payload(payload))
            parent_id = experiment_study_id(spec)
            study = study_by_id.get(parent_id)
            if study is None:
                raise RuntimeError(
                    f"experiment scope parent is missing: {parent_id}"
                )
            experiment_by_id[experiment_id(spec)] = spec
            self._scopes.register(_experiment_scope(spec), _study_scope(study))
        for experiment_id_value, payload in runs:
            identity = self._decode_run(str(payload))
            experiment = experiment_by_id.get(str(experiment_id_value))
            if experiment is None:
                raise RuntimeError(
                    f"run scope parent is missing: {experiment_id_value}"
                )
            self._scopes.register(identity.scope, _experiment_scope(experiment))

    def register_study(self, spec: NoetriumUnit) -> None:
        spec = require_study_unit(spec)
        project_id = study_project_id(spec)
        sid = study_id(spec)
        parent = scope_unit(ScopeKind.PROJECT, project_id)
        if not self._scopes.contains(parent):
            raise ExperimentationCatalogNotFound(scope_key(parent))
        payload = _unit_payload(spec)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM studies WHERE study_id=?",
                (sid,),
            ).fetchone()
        if row is not None:
            if _unit_from_payload(row[0]) != spec:
                raise ExperimentationCatalogConflict(sid)
            return
        self._scopes.register(_study_scope(spec), parent)
        self._insert(
            "INSERT OR IGNORE INTO studies(study_id,project_id,payload) "
            "VALUES(?,?,?)",
            (sid, project_id, payload),
        )
        if self.study(sid) != spec:
            raise ExperimentationCatalogConflict(sid)

    def register_experiment(self, spec: NoetriumUnit) -> None:
        spec = require_experiment_unit(spec)
        sid = experiment_study_id(spec)
        eid = experiment_id(spec)
        project_id = experiment_project_id(spec)
        study = self.study(sid)
        if study_project_id(study) != project_id:
            raise ExperimentationCatalogConflict(
                "experiment project_id does not match its Study"
            )
        if study_experiment_id(study) != eid:
            raise ExperimentationCatalogConflict(
                "experiment is not declared by its Study"
            )
        payload = _unit_payload(spec)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM experiments WHERE experiment_id=?",
                (eid,),
            ).fetchone()
        if row is not None:
            if _unit_from_payload(row[0]) != spec:
                raise ExperimentationCatalogConflict(eid)
            return
        self._scopes.register(_experiment_scope(spec), _study_scope(study))
        self._insert(
            "INSERT OR IGNORE INTO experiments("
            "experiment_id,study_id,project_id,payload) VALUES(?,?,?,?)",
            (eid, sid, project_id, payload),
        )
        if self.experiment(eid) != spec:
            raise ExperimentationCatalogConflict(eid)

    def register_run(
        self,
        experiment_id_value: str,
        identity: RunIdentity,
    ) -> None:
        experiment = self.experiment(experiment_id_value)
        payload = self._run_payload(identity)
        with self._connection() as conn:
            row = conn.execute(
                "SELECT experiment_id,payload FROM runs WHERE run_id=?",
                (identity.run_id,),
            ).fetchone()
        if row is not None:
            if str(row[0]) != experiment_id_value or str(row[1]) != payload:
                raise ExperimentationCatalogConflict(identity.run_id)
            return
        self._scopes.register(identity.scope, _experiment_scope(experiment))
        self._insert(
            "INSERT OR IGNORE INTO runs(run_id,experiment_id,payload) "
            "VALUES(?,?,?)",
            (identity.run_id, experiment_id_value, payload),
        )

    def study(self, study_id_value: str) -> NoetriumUnit:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM studies WHERE study_id=?",
                (study_id_value,),
            ).fetchone()
        if row is None:
            raise ExperimentationCatalogNotFound(study_id_value)
        return require_study_unit(_unit_from_payload(row[0]))

    def experiment(self, experiment_id_value: str) -> NoetriumUnit:
        with self._connection() as conn:
            row = conn.execute(
                "SELECT payload FROM experiments WHERE experiment_id=?",
                (experiment_id_value,),
            ).fetchone()
        if row is None:
            raise ExperimentationCatalogNotFound(experiment_id_value)
        return require_experiment_unit(_unit_from_payload(row[0]))

    def experiments(
        self,
        *,
        study_id: str | None = None,
    ) -> tuple[NoetriumUnit, ...]:
        query = "SELECT payload FROM experiments"
        values: tuple[object, ...] = ()
        if study_id is not None:
            query += " WHERE study_id=?"
            values = (study_id,)
        with self._connection() as conn:
            rows = conn.execute(
                query + " ORDER BY experiment_id",
                values,
            ).fetchall()
        return tuple(
            require_experiment_unit(_unit_from_payload(row[0]))
            for row in rows
        )


__all__ = [
    "ExperimentationCatalogConflict",
    "ExperimentationCatalogNotFound",
    "InMemoryExperimentationCatalog",
    "SQLiteExperimentationCatalog",
]
