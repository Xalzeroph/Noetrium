from __future__ import annotations

from resource_test_support import build_test_directory_authorities

from pathlib import Path

import pytest

from noetrium_platform.infrastructure.lifecycle.python.api import (
    EnvironmentCommandResult,
    PythonEnvironmentOwnership,
    PythonEnvironmentSpec,
)
from noetrium_platform.infrastructure.lifecycle.python.runtime import build_python_environment_authorities
from noetrium_platform.infrastructure.lifecycle.python.runtime.lifecycle_transaction import (
    PythonEnvironmentLifecycleTransaction,
    PythonEnvironmentLifecycleTransactionStore,
)
from noetrium_platform.infrastructure.lifecycle.python.runtime.registry import PythonEnvironmentRegistry
from noetrium_platform.infrastructure.resources.directory.api import DirectoryLayout, ManagedDirectoryKind
from noetrium_platform.infrastructure.resources.directory.composition import build_local_directory_authorities
from noetrium_platform.infrastructure.resources.authority.runtime.authority import UniversalResourceAuthority
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


def _layout(root: Path) -> DirectoryLayout:
    return DirectoryLayout(
        releases=root / "releases",
        runtime=root / "runtime",
        state=root / "state",
        logs=root / "logs",
        model_artifacts=root / "models",
        python_environments=root / "envs",
        cache=root / "cache",
        temp=root / "tmp",
        locks=root / "locks",
        workspaces=root / "workspaces",
    )


class _Runner:
    def run(self, argv, *, cwd=None, environment=None):
        return EnvironmentCommandResult(tuple(argv), 0, "", "")


class _Backend:
    backend_id = "fake"

    def __init__(self, *, fail_after_partial: bool = False) -> None:
        self.fail_after_partial = fail_after_partial

    def create(self, root: Path, spec: PythonEnvironmentSpec) -> Path:
        del spec
        path = self.python_path(root)
        path.parent.mkdir(parents=True, exist_ok=True)
        if self.fail_after_partial:
            (root / "partial.txt").write_text("partial", encoding="utf-8")
            raise RuntimeError("backend create failed")
        path.write_text("python", encoding="utf-8")
        return path

    def python_path(self, root: Path) -> Path:
        return root / "bin" / "python"

    def install(self, root: Path, requirements: Path, *, extra_args: tuple[str, ...] = ()) -> EnvironmentCommandResult:
        del root, requirements, extra_args
        return EnvironmentCommandResult(("pip",), 0, "", "")


def _directories(root: Path):
    return build_test_directory_authorities(_layout(root))


def _authorities(root: Path, backend: _Backend | None = None):
    directories = _directories(root)
    resource_authority = UniversalResourceAuthority(
        root / "resource-authority.sqlite3"
    )
    authorities = build_python_environment_authorities(
        directories.layout,
        (backend or _Backend(),),
        _Runner(),
        resource_authority,
    )
    return directories, authorities


def _spec(environment_id: str = "managed") -> PythonEnvironmentSpec:
    return PythonEnvironmentSpec(
        environment_id,
        PLATFORM_SCOPE,
        backend="fake",
        description="managed test env",
        tags=("test",),
    )


def _transaction(root: Path, *, operation: str, phase: str, environment_id: str = "managed"):
    directories = _directories(root)
    spec = _spec(environment_id)
    env_root = directories.layout.root(ManagedDirectoryKind.PYTHON_ENVIRONMENTS) / environment_id
    resource_authority = UniversalResourceAuthority(
        root / "resource-authority.sqlite3"
    )
    generation = resource_authority.ensure_generation(
        "python-environment:" + environment_id
    ).generation
    txn = PythonEnvironmentLifecycleTransaction(
        operation,
        phase,
        environment_id,
        spec.scope,
        spec.backend,
        env_root,
        env_root / "bin" / "python",
        PythonEnvironmentOwnership.MANAGED,
        spec.description,
        tuple(sorted(set(spec.tags))),
        spec.specification_digest,
        generation,
    )
    return directories, spec, txn


def _materialize(txn: PythonEnvironmentLifecycleTransaction, payload: bytes = b"python") -> None:
    txn.python_path.parent.mkdir(parents=True, exist_ok=True)
    txn.python_path.write_bytes(payload)


def test_create_failure_rolls_back_partial_managed_root_and_journal(tmp_path) -> None:
    directories, authorities = _authorities(tmp_path, _Backend(fail_after_partial=True))
    with pytest.raises(RuntimeError, match="backend create failed"):
        authorities.lifecycle.create(_spec())
    env_root = directories.layout.root(ManagedDirectoryKind.PYTHON_ENVIRONMENTS) / "managed"
    assert not env_root.exists()
    with pytest.raises(KeyError):
        authorities.lifecycle.get("managed")
    assert PythonEnvironmentLifecycleTransactionStore(directories.layout).get("managed") is None


def test_constructor_completes_materialized_create_after_crash(tmp_path) -> None:
    directories, _spec_value, txn = _transaction(tmp_path, operation="create", phase="materialized")
    _materialize(txn)
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    store.put(txn)

    _directories_again, authorities = _authorities(tmp_path)

    loaded = authorities.lifecycle.get("managed")
    assert loaded.specification_digest == txn.specification_digest
    assert loaded.root == txn.root
    assert store.get("managed") is None


def test_constructor_finishes_create_when_registry_was_published_before_phase_commit(tmp_path) -> None:
    directories, _spec_value, txn = _transaction(tmp_path, operation="create", phase="materialized")
    _materialize(txn)
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    store.put(txn)
    PythonEnvironmentRegistry(directories.layout).put(txn.environment())

    _directories_again, authorities = _authorities(tmp_path)

    assert authorities.lifecycle.get("managed").identity_digest == txn.environment().identity_digest
    assert store.get("managed") is None


def test_prepared_create_crash_rolls_back_partial_root_on_constructor(tmp_path) -> None:
    directories, _spec_value, txn = _transaction(tmp_path, operation="create", phase="prepared")
    _materialize(txn, b"partial")
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    store.put(txn)

    _authorities(tmp_path)

    assert not txn.root.exists()
    assert store.get("managed") is None


def test_remove_crash_after_registry_delete_continues_root_cleanup(tmp_path) -> None:
    directories, authorities = _authorities(tmp_path)
    created = authorities.lifecycle.create(_spec())
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    txn = PythonEnvironmentLifecycleTransaction(
        "remove", "prepared", created.environment_id, created.scope, created.backend,
        created.root, created.python_path, created.ownership, created.description,
        created.tags, created.specification_digest, created.resource_generation,
    )
    store.put(txn)
    authority = UniversalResourceAuthority(tmp_path / "resource-authority.sqlite3")
    authority.fence_if_no_live_leases(
        "python-environment:managed",
        holder_key="python-environment-retire:managed:1",
    )
    PythonEnvironmentRegistry(directories.layout).retire(created)

    _authorities(tmp_path)

    assert not created.root.exists()
    assert store.get("managed") is None


def test_remove_crash_after_root_delete_clears_unregistered_transaction(tmp_path) -> None:
    directories, authorities = _authorities(tmp_path)
    created = authorities.lifecycle.create(_spec())
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    txn = PythonEnvironmentLifecycleTransaction(
        "remove", "unregistered", created.environment_id, created.scope, created.backend,
        created.root, created.python_path, created.ownership, created.description,
        created.tags, created.specification_digest, created.resource_generation,
    )
    store.put(txn)
    authority = UniversalResourceAuthority(tmp_path / "resource-authority.sqlite3")
    authority.fence_if_no_live_leases(
        "python-environment:managed",
        holder_key="python-environment-retire:managed:1",
    )
    PythonEnvironmentRegistry(directories.layout).retire(created)
    import shutil
    shutil.rmtree(created.root)

    _authorities(tmp_path)

    assert store.get("managed") is None


def test_transaction_event_tampering_fails_closed_before_mutation(tmp_path) -> None:
    directories, _spec_value, txn = _transaction(
        tmp_path, operation="create", phase="prepared"
    )
    _materialize(txn, b"partial")
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    store.put(txn)
    projection = (
        directories.layout.root(ManagedDirectoryKind.STATE)
        / "python-environment-lifecycle"
        / "managed.json"
    )
    event_path = next(projection.with_name(projection.name + ".events").glob("*.unit"))
    event_path.write_bytes(b"corrupt-unit")

    with pytest.raises(RuntimeError, match="causal Event Unit is corrupt"):
        _authorities(tmp_path)

    assert txn.root.exists()
    assert event_path.exists()


def test_committed_create_missing_root_fails_closed_and_preserves_journal(tmp_path) -> None:
    directories, _spec_value, txn = _transaction(tmp_path, operation="create", phase="committed")
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    store.put(txn)

    with pytest.raises(RuntimeError, match="Committed Python environment is missing"):
        _authorities(tmp_path)

    assert store.get("managed") is not None


def test_create_is_idempotent_only_for_same_managed_specification(tmp_path) -> None:
    _directories_value, authorities = _authorities(tmp_path)
    first = authorities.lifecycle.create(_spec())
    second = authorities.lifecycle.create(_spec())
    assert second.identity_digest == first.identity_digest

    changed = PythonEnvironmentSpec("managed", PLATFORM_SCOPE, backend="fake", description="changed")
    with pytest.raises(FileExistsError, match="already registered"):
        authorities.lifecycle.create(changed)


class _CountingBackend(_Backend):
    def __init__(self) -> None:
        super().__init__()
        self.create_count = 0

    def create(self, root: Path, spec: PythonEnvironmentSpec) -> Path:
        import time
        self.create_count += 1
        time.sleep(0.05)
        return super().create(root, spec)


def test_concurrent_same_spec_create_materializes_backend_once(tmp_path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    backend = _CountingBackend()
    _directories_value, authorities = _authorities(tmp_path, backend)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = tuple(pool.map(lambda _item: authorities.lifecycle.create(_spec()), range(2)))

    assert backend.create_count == 1
    assert results[0].identity_digest == results[1].identity_digest


def test_same_spec_create_does_not_hide_missing_registered_interpreter(tmp_path) -> None:
    _directories_value, authorities = _authorities(tmp_path)
    created = authorities.lifecycle.create(_spec())
    created.python_path.unlink()

    with pytest.raises(FileExistsError, match="already registered"):
        authorities.lifecycle.create(_spec())

    assert authorities.lifecycle.get("managed").state.value == "missing"


class _CrossProcessBackend(_Backend):
    def __init__(self, marker: Path) -> None:
        super().__init__()
        self.marker = marker

    def create(self, root: Path, spec: PythonEnvironmentSpec) -> Path:
        import os
        import time

        self.marker.parent.mkdir(parents=True, exist_ok=True)
        try:
            fd = os.open(self.marker, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        except FileExistsError as exc:
            raise RuntimeError("backend materialized more than once across processes") from exc
        try:
            os.write(fd, b"materialized\n")
            os.fsync(fd)
        finally:
            os.close(fd)
        time.sleep(0.25)
        return super().create(root, spec)


def _cross_process_create_worker(
    root_value: str,
    marker_value: str,
    start_event,
    ready_queue,
    result_queue,
) -> None:
    try:
        root = Path(root_value)
        _directories_value, authorities = _authorities(
            root,
            _CrossProcessBackend(Path(marker_value)),
        )
        ready_queue.put("ready")
        if not start_event.wait(10):
            raise TimeoutError("cross-process create start barrier timed out")
        value = authorities.lifecycle.create(_spec())
        result_queue.put(("ok", value.identity_digest))
    except BaseException as exc:
        result_queue.put(("error", type(exc).__name__, str(exc)))


def test_concurrent_same_spec_create_is_serialized_across_processes(tmp_path) -> None:
    import multiprocessing

    context = multiprocessing.get_context("spawn")
    start_event = context.Event()
    ready_queue = context.Queue()
    result_queue = context.Queue()
    marker = tmp_path / "backend-materialized.marker"
    args = (str(tmp_path), str(marker), start_event, ready_queue, result_queue)
    processes = [context.Process(target=_cross_process_create_worker, args=args) for _ in range(2)]
    for process in processes:
        process.start()
    assert [ready_queue.get(timeout=15) for _ in processes] == ["ready", "ready"]
    start_event.set()
    results = [result_queue.get(timeout=20) for _ in processes]
    for process in processes:
        process.join(timeout=20)
        assert process.exitcode == 0
    assert all(result[0] == "ok" for result in results), results
    assert results[0][1] == results[1][1]
    assert marker.read_text(encoding="utf-8") == "materialized\n"


def test_process_lock_is_shared_per_authority_path_only(tmp_path) -> None:
    _directories_a1, authorities_a1 = _authorities(tmp_path / "a")
    _directories_a2, authorities_a2 = _authorities(tmp_path / "a")
    _directories_b, authorities_b = _authorities(tmp_path / "b")

    assert authorities_a1.lifecycle._lock is authorities_a2.lifecycle._lock
    assert authorities_a1.lifecycle._lock is not authorities_b.lifecycle._lock


def test_failed_create_rollback_keeps_same_resource_generation(tmp_path) -> None:
    _directories_value, broken = _authorities(
        tmp_path, _Backend(fail_after_partial=True)
    )
    with pytest.raises(RuntimeError, match="backend create failed"):
        broken.lifecycle.create(_spec())

    authority = UniversalResourceAuthority(tmp_path / "resource-authority.sqlite3")
    generation = authority.generation("python-environment:managed")
    assert generation is not None and generation.generation == 1

    _directories_value, recovered = _authorities(tmp_path, _Backend())
    created = recovered.lifecycle.create(_spec())
    assert created.resource_generation == 1
    assert created.python_path.exists()
    authority.verify_projection_rebuild()


def test_explicit_managed_remove_advances_generation_and_allows_new_generation(
    tmp_path,
) -> None:
    _directories_value, authorities = _authorities(tmp_path)
    created = authorities.lifecycle.create(_spec())
    assert created.resource_generation == 1
    assert authorities.lifecycle.remove("managed")
    assert not created.root.exists()

    authority = UniversalResourceAuthority(tmp_path / "resource-authority.sqlite3")
    generation = authority.generation("python-environment:managed")
    assert generation is not None and generation.generation == 2

    replacement = authorities.lifecycle.create(_spec())
    assert replacement.resource_generation == 2
    assert replacement.root.exists()
    authority.verify_projection_rebuild()


def test_external_remove_preserves_physical_root_and_advances_logical_generation(
    tmp_path,
) -> None:
    _directories_value, authorities = _authorities(tmp_path)
    external = tmp_path / "external-runtime"
    python_path = external / "bin" / "python"
    python_path.parent.mkdir(parents=True)
    python_path.write_bytes(b"python")
    spec = PythonEnvironmentSpec(
        "external-retired",
        PLATFORM_SCOPE,
        backend="fake",
    )
    registered = authorities.lifecycle.register_existing(spec, external)
    assert registered.resource_generation == 1

    assert authorities.lifecycle.remove("external-retired")
    assert external.exists()
    assert python_path.exists()

    authority = UniversalResourceAuthority(tmp_path / "resource-authority.sqlite3")
    generation = authority.generation("python-environment:external-retired")
    assert generation is not None and generation.generation == 2

    replacement = authorities.lifecycle.register_existing(spec, external)
    assert replacement.resource_generation == 2
    assert replacement.root == external.resolve()
    authority.verify_projection_rebuild()



def test_active_borrow_blocks_remove_until_lease_released(tmp_path) -> None:
    _directories_value, authorities = _authorities(tmp_path)
    created = authorities.lifecycle.create(_spec())
    borrow = authorities.lifecycle.borrow(
        "managed", holder_key="test-consumer"
    )
    observed = borrow.__enter__()
    assert observed.identity_digest == created.identity_digest
    try:
        with pytest.raises(RuntimeError, match="live consumers"):
            authorities.lifecycle.remove("managed")
        assert created.root.exists()
    finally:
        borrow.__exit__(None, None, None)

    # The pending remove transaction is recovered after the final consumer
    # lease is released; it fences generation 1 and retires physical state.
    assert authorities.lifecycle.remove("managed") is True
    assert not created.root.exists()
    authority = UniversalResourceAuthority(tmp_path / "resource-authority.sqlite3")
    generation = authority.generation("python-environment:managed")
    assert generation is not None and generation.generation == 2
    authority.verify_projection_rebuild()


def test_python_environment_projections_rebuild_from_causal_events(tmp_path) -> None:
    directories, authorities = _authorities(tmp_path)
    created = authorities.lifecycle.create(_spec())
    state_root = directories.layout.root(ManagedDirectoryKind.STATE)
    registry_projection = state_root / "python-environments" / "managed.json"
    transaction_projection = (
        state_root / "python-environment-lifecycle" / "managed.json"
    )
    assert registry_projection.exists()
    assert transaction_projection.exists()
    registry_projection.unlink()
    transaction_projection.unlink()

    # Event directories are the truth; both disposable latest projections are
    # reconstructed on demand without changing resource generation.
    reopened_directories, reopened = _authorities(tmp_path)
    loaded = reopened.lifecycle.get("managed")
    assert loaded.identity_digest == created.identity_digest
    assert registry_projection.exists()
    assert transaction_projection.exists()
    PythonEnvironmentRegistry(reopened_directories.layout).verify_projection_rebuild()
    PythonEnvironmentLifecycleTransactionStore(
        reopened_directories.layout
    ).verify_projection_rebuild()
    UniversalResourceAuthority(
        tmp_path / "resource-authority.sqlite3"
    ).verify_projection_rebuild()


def test_python_lifecycle_transaction_rejects_phase_skip(tmp_path) -> None:
    directories, _spec_value, prepared = _transaction(
        tmp_path, operation="create", phase="prepared"
    )
    store = PythonEnvironmentLifecycleTransactionStore(directories.layout)
    store.put(prepared)
    with pytest.raises(RuntimeError, match="illegal Python environment lifecycle transition"):
        store.put(prepared.with_phase("committed"))
    assert store.get("managed") == prepared
