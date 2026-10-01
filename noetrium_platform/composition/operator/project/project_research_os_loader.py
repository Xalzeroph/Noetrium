from __future__ import annotations

from noetrium_platform.composition.method_telemetry_sink import RawLakeMethodObservationSink

from dataclasses import dataclass, field
import hashlib
import importlib
import os
from pathlib import Path
import shutil
import sys
import tempfile
from threading import RLock

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os_local import (
    LocalResearchOSComposition,
    compose_local_research_os,
)
from noetrium_platform.infrastructure.resources.directory.runtime import (
    standard_local_directory_layout,
)
from noetrium_platform.foundation.portfolio.project.api import (
    ProjectManifest,
    decode_project_manifest_bytes,
)
from noetrium_platform.product.operator.api import project_template_revision
from noetrium_platform.product.research_os import (
    ResearchGraphRevision,
    ResearchOS,
    ResearchPortfolio,
)

from .project_execution_authority import (
    materialize_project_execution_authorities,
)
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
)
from .project_layout import project_package_name


_STATE_DIRECTORY = ".noetrium/research-os"
_SOURCE_SNAPSHOT_DIRECTORY = "source-snapshots"
_SOURCE_SNAPSHOT_MESSAGE_PREFIX = "project source snapshot:"
_SOURCE_SNAPSHOT_ATTEMPTS = 4


_PROJECT_STATE_ROOT_ENV = "NOETRIUM_PROJECT_STATE_ROOT"
_ACTIVE_PROJECT_SOURCE_LOCK = RLock()
_ACTIVE_PROJECT_SOURCES: dict[str, tuple[str, int]] = {}


def _project_state_root(project_root: Path) -> Path:
    explicit = os.environ.get(_PROJECT_STATE_ROOT_ENV, "").strip()
    if not explicit:
        return project_root / _STATE_DIRECTORY
    root = Path(explicit)
    if not root.is_absolute():
        raise ValueError(f"{_PROJECT_STATE_ROOT_ENV} must be an absolute path")
    root.mkdir(parents=True, exist_ok=True)
    return root


def _snapshot_digest(records: tuple[tuple[str, bytes], ...]) -> str:
    digest = hashlib.sha256()
    for relative, payload in records:
        encoded = relative.encode("utf-8")
        digest.update(len(encoded).to_bytes(8, "big"))
        digest.update(encoded)
        digest.update(len(payload).to_bytes(8, "big"))
        digest.update(payload)
    return digest.hexdigest()


def _read_project_source_records(root: Path) -> tuple[tuple[str, bytes], ...]:
    manifest_path = root / "project.manifest.json"
    src = root / "src"
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("project source snapshot requires canonical project.manifest.json")
    if src.is_symlink() or not src.is_dir():
        raise ValueError("project source snapshot requires a real src directory")

    records: list[tuple[str, bytes]] = [
        ("project.manifest.json", manifest_path.read_bytes())
    ]
    for current, directory_names, file_names in os.walk(
        src,
        topdown=True,
        followlinks=False,
    ):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in sorted(directory_names):
            path = current_path / name
            if path.is_symlink():
                raise ValueError(
                    f"project source snapshot refuses symlink directory: "
                    f"{path.relative_to(root).as_posix()}"
                )
            if name == "__pycache__":
                continue
            kept_directories.append(name)
        directory_names[:] = kept_directories
        for name in sorted(file_names):
            if name.endswith(".pyc"):
                continue
            path = current_path / name
            relative = path.relative_to(root).as_posix()
            if path.is_symlink() or not path.is_file():
                raise ValueError(
                    f"project source snapshot requires regular files: {relative}"
                )
            before = path.stat()
            payload = path.read_bytes()
            after = path.stat()
            if (
                before.st_dev != after.st_dev
                or before.st_ino != after.st_ino
                or before.st_size != after.st_size
                or before.st_mtime_ns != after.st_mtime_ns
            ):
                raise RuntimeError(
                    f"project source changed while snapshotting: {relative}"
                )
            records.append((relative, payload))
    return tuple(records)


def _stable_project_source_records(
    root: Path,
) -> tuple[tuple[tuple[str, bytes], ...], str]:
    previous: tuple[tuple[str, bytes], ...] | None = None
    for _attempt in range(_SOURCE_SNAPSHOT_ATTEMPTS):
        observed = _read_project_source_records(root)
        if previous is not None and observed == previous:
            return observed, _snapshot_digest(observed)
        previous = observed
    raise RuntimeError(
        "project source remained mutable while an immutable revision snapshot "
        "was being captured"
    )


def _verify_source_snapshot(snapshot_root: Path, expected_digest: str) -> None:
    observed = _read_project_source_records(snapshot_root)
    if _snapshot_digest(observed) != expected_digest:
        raise RuntimeError("project source snapshot content-address identity drifted")


def _materialize_project_source_snapshot(
    project_root: Path,
    state_root: Path,
) -> tuple[Path, str]:
    records, digest = _stable_project_source_records(project_root)
    snapshots = state_root / _SOURCE_SNAPSHOT_DIRECTORY
    if snapshots.is_symlink():
        raise ValueError("project source snapshot root must not be a symlink")
    snapshots.mkdir(parents=True, exist_ok=True)
    target = snapshots / digest
    if target.exists():
        if target.is_symlink() or not target.is_dir():
            raise RuntimeError("project source snapshot target has invalid identity")
        _verify_source_snapshot(target, digest)
        return target, digest

    temporary = Path(
        tempfile.mkdtemp(
            prefix=f".{digest[:16]}-",
            dir=snapshots,
        )
    )
    try:
        for relative, payload in records:
            destination = temporary / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_bytes(payload)
        _verify_source_snapshot(temporary, digest)
        try:
            temporary.rename(target)
        except OSError:
            if not target.is_dir() or target.is_symlink():
                raise
            _verify_source_snapshot(target, digest)
        else:
            temporary = target
    finally:
        if temporary != target and temporary.exists():
            shutil.rmtree(temporary)
    return target, digest


def _source_revision_message(snapshot_digest: str) -> str:
    if (
        type(snapshot_digest) is not str
        or len(snapshot_digest) != 64
        or any(ch not in "0123456789abcdef" for ch in snapshot_digest)
    ):
        raise ValueError("project source snapshot digest must be SHA-256")
    return f"{_SOURCE_SNAPSHOT_MESSAGE_PREFIX}{snapshot_digest}"


def _source_snapshot_digest_from_message(message: str) -> str:
    if type(message) is not str or not message.startswith(_SOURCE_SNAPSHOT_MESSAGE_PREFIX):
        raise RuntimeError("active project revision has no immutable source snapshot identity")
    digest = message[len(_SOURCE_SNAPSHOT_MESSAGE_PREFIX):]
    if (
        len(digest) != 64
        or any(ch not in "0123456789abcdef" for ch in digest)
        or message != _source_revision_message(digest)
    ):
        raise RuntimeError("active project revision source snapshot identity is invalid")
    return digest


def _retain_project_source(package: str, source_root: Path) -> None:
    resolved = str(source_root.resolve())
    with _ACTIVE_PROJECT_SOURCE_LOCK:
        current = _ACTIVE_PROJECT_SOURCES.get(package)
        if current is not None:
            current_root, count = current
            if current_root != resolved:
                raise RuntimeError(
                    "one process cannot bind two immutable source snapshots for "
                    f"the same project package: {package}"
                )
            _ACTIVE_PROJECT_SOURCES[package] = (current_root, count + 1)
            return
        sys.path.insert(0, resolved)
        _ACTIVE_PROJECT_SOURCES[package] = (resolved, 1)


def _release_project_source(package: str, source_root: Path) -> None:
    resolved = str(source_root.resolve())
    with _ACTIVE_PROJECT_SOURCE_LOCK:
        current = _ACTIVE_PROJECT_SOURCES.get(package)
        if current is None or current[0] != resolved:
            raise RuntimeError("project source snapshot retain/release ownership drifted")
        if current[1] > 1:
            _ACTIVE_PROJECT_SOURCES[package] = (resolved, current[1] - 1)
            return
        _ACTIVE_PROJECT_SOURCES.pop(package, None)
        try:
            sys.path.remove(resolved)
        except ValueError as exc:
            raise RuntimeError(
                "project source snapshot disappeared from import authority"
            ) from exc


class _LazyProjectResearchOS:
    """ResearchOS proxy that attaches the physical execution plane on demand."""

    __slots__ = ("_owner", "_delegate")

    def __init__(self, owner: "LoadedProjectResearchOS", delegate: ResearchOS) -> None:
        self._owner = owner
        self._delegate = delegate

    def _replace_delegate(self, delegate: ResearchOS) -> None:
        self._delegate = delegate

    def _execution_delegate(self) -> ResearchOS:
        self._owner.ensure_execution_plane()
        return self._delegate

    def __getattr__(self, name: str):
        return getattr(self._delegate, name)

    def run(self, target, payload=None):
        return self._execution_delegate().run(target, payload)

    def inspect(self, target, payload=None):
        return self._delegate.inspect(target, payload)

    def pause(self, target, payload=None):
        # PAUSE is durable ResearchGraph control.  A second operator process
        # must never materialize or contend for the physical execution plane
        # merely to fence new claims in an already-running project.
        return self._delegate.pause(target, payload)

    def drain(self, target, payload=None):
        # DRAIN publishes admission intent into the durable graph; the live
        # scheduler observes that intent and converges to PAUSED itself.
        return self._delegate.drain(target, payload)

    def interrupt(self, target, payload=None):
        # INTERRUPT fences the selected graph/node generation durably.  Lower
        # execution is stopped by the process that already owns it.
        return self._delegate.interrupt(target, payload)

    def resume(self, target, payload=None):
        # RESUME can produce new execution, so it must attach an execution
        # plane when no live owner remains.
        return self._execution_delegate().resume(target, payload)

    def retry(self, target, payload=None):
        return self._execution_delegate().retry(target, payload)

    def cancel(self, target, payload=None):
        # CANCEL is a durable graph/subgraph terminal transition and releases
        # only Research-OS-owned value pins; it requires no provider runtime.
        return self._delegate.cancel(target, payload)

    def checkpoint(self, target, payload=None):
        return self._execution_delegate().checkpoint(target, payload)

    def reconcile(self, target, payload=None):
        # Reconciliation is a control-plane proof operation.  It may consume
        # durable graph/Machine/effect evidence, but it must never bootstrap
        # model/environment/resource realizations merely to inspect recovery.
        return self._delegate.reconcile(target, payload)

    def migrate(self, target, payload=None):
        return self._execution_delegate().migrate(target, payload)


@dataclass(slots=True)
class LoadedProjectResearchOS:
    """Project control plane with one lazily-owned physical execution plane."""

    project_root: Path
    state_root: Path
    manifest: ProjectManifest
    _portfolio: ResearchPortfolio | None
    revision: ResearchGraphRevision
    active_revision: ResearchGraphRevision | None
    research_os: ResearchOS
    execution_pool: ResearchExecutionPool
    _composition: LocalResearchOSComposition
    source_snapshot_digest: str
    _source_snapshot_src: Path
    _project_package: str
    _source_retained: bool = True
    _shared_runtime: ManagedResearchRuntime | None = None
    _managed_runtime: ManagedResearchRuntime | None = None
    _owns_managed_runtime: bool = False
    _execution_authorities: ResearchExecutionAuthorities | None = None
    _closed: bool = False
    _execution_lock: RLock = field(default_factory=RLock, repr=False)

    @property
    def default_execution_id(self) -> str:
        return self.manifest.project.identity.project_id

    def _materialize_portfolio(self) -> ResearchPortfolio:
        portfolio = self._portfolio
        if portfolio is not None:
            return portfolio
        snapshot_root = self._source_snapshot_src.parent
        _verify_source_snapshot(snapshot_root, self.source_snapshot_digest)
        _retain_project_source(self._project_package, self._source_snapshot_src)
        self._source_retained = True
        try:
            portfolio = _load_generated_portfolio(snapshot_root, self.manifest)
        except BaseException:
            _release_project_source(self._project_package, self._source_snapshot_src)
            self._source_retained = False
            raise
        if portfolio.portfolio_digest != self.revision.portfolio_digest:
            _release_project_source(self._project_package, self._source_snapshot_src)
            self._source_retained = False
            raise RuntimeError(
                "active project source snapshot drifted from durable revision"
            )
        self._portfolio = portfolio
        return portfolio

    @property
    def portfolio(self) -> ResearchPortfolio:
        return self._materialize_portfolio()

    @property
    def execution_plane_ready(self) -> bool:
        return self._managed_runtime is not None

    def ensure_execution_plane(self) -> None:
        """Materialize the one physical execution plane at first execution intent."""
        if self._closed:
            raise RuntimeError("project Research OS is closed")
        if self._managed_runtime is not None:
            return
        with self._execution_lock:
            if self._managed_runtime is not None:
                return
            state_root = self.state_root
            owns_managed_runtime = self._shared_runtime is None
            managed_runtime = self._shared_runtime
            if managed_runtime is None:
                managed_runtime = build_local_managed_research_runtime(
                    standard_local_directory_layout(state_root / "platform-runtime"),
                    # Initial execution-authority materialization is the sole owner
                    # of model/resource convergence. Background reconcilers attach
                    # only after that synchronous closure is complete, otherwise
                    # they can race the bootstrap fleet over the same desired
                    # deployment generation.
                    start_background_controllers=False,
                    runtime_consumer_scope=self.manifest.project.identity.scope,
                )
            else:
                managed_runtime.assert_healthy()
            replacement: LocalResearchOSComposition | None = None
            authorities: ResearchExecutionAuthorities | None = None
            try:
                context = ResearchExecutionContext(
                    state_root,
                    managed_runtime,
                    content=self._composition.content,
                    execution_tenant_id=self.portfolio.portfolio_id,
                )
                authorities = materialize_project_execution_authorities(
                    context,
                    self.portfolio,
                    self.manifest,
                )
                replacement = compose_local_research_os(
                    state_root,
                    experiment_closures=authorities.experiment_closures,
                    experiment_runtime_components=(
                        authorities.experiment_runtime_components
                    ),
                    execution_pool=managed_runtime.execution_pool,
                    method_runtime_inventory=authorities.method_runtime_inventory,
                    operation_dispatcher=managed_runtime.operation_runtime.dispatcher,
                    method_observation=RawLakeMethodObservationSink(
                        managed_runtime.observability.raw
                    ),
                    content_authorities=context.content,
                )
                # Background reconcilers attach only after the synchronous
                # execution-authority closure is complete. This ordering is
                # platform-owned and cannot be disabled by downstream code.
                managed_runtime.start_background_controllers()
            except BaseException as primary:
                cleanup_errors: list[BaseException] = []
                if authorities is not None:
                    try:
                        authorities.close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                if owns_managed_runtime:
                    try:
                        managed_runtime.close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                if cleanup_errors:
                    raise ExceptionGroup(
                        "project execution-plane materialization failed with cleanup error",
                        [primary, *cleanup_errors],
                    ) from primary
                raise
            previous = self._composition
            previous.handoff_content_ownership(replacement)
            try:
                previous.close()
            except BaseException as primary:
                cleanup_errors: list[BaseException] = []
                try:
                    replacement.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
                if authorities is not None:
                    try:
                        authorities.close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                if owns_managed_runtime:
                    try:
                        managed_runtime.close()
                    except BaseException as exc:
                        cleanup_errors.append(exc)
                if cleanup_errors:
                    raise ExceptionGroup(
                        "project control-plane replacement failed with cleanup errors",
                        [primary, *cleanup_errors],
                    ) from primary
                raise

            self._composition = replacement
            self.execution_pool = replacement.execution_pool
            self._managed_runtime = managed_runtime
            self._owns_managed_runtime = owns_managed_runtime
            self._execution_authorities = authorities
            proxy = self.research_os
            if isinstance(proxy, _LazyProjectResearchOS):
                proxy._replace_delegate(replacement.research_os)
            else:
                self.research_os = replacement.research_os

    def retire_runtime_fabric(self) -> None:
        """Terminally retire the host Runtime Fabric for this project state root.

        Normal project close only detaches consumers so exact model/environment
        realizations stay warm across runs. This explicit operator action is the
        terminal lifecycle boundary: it reuses ManagedResearchRuntime's single
        retirement authority and never materializes project execution
        authorities merely to clean physical state.
        """

        if self._closed:
            raise RuntimeError("project Research OS is closed")
        if self._shared_runtime is not None:
            raise RuntimeError(
                "project cannot terminally retire a shared ManagedResearchRuntime"
            )
        with self._execution_lock:
            if self._execution_authorities is not None:
                raise RuntimeError(
                    "terminal Runtime Fabric retirement requires a fresh "
                    "control-plane project handle"
                )
            runtime = self._managed_runtime
            if runtime is None:
                runtime = build_local_managed_research_runtime(
                    standard_local_directory_layout(
                        self.state_root / "platform-runtime"
                    ),
                    start_background_controllers=False,
                )
                self._managed_runtime = runtime
                self._owns_managed_runtime = True
            elif not self._owns_managed_runtime:
                raise RuntimeError(
                    "project does not own the ManagedResearchRuntime"
                )
            runtime.retire_runtime_fabric()

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        try:
            self._composition.close()
        except BaseException as exc:
            errors.append(exc)
        if self._execution_authorities is not None:
            try:
                self._execution_authorities.close()
            except BaseException as exc:
                errors.append(exc)
        if self._managed_runtime is not None and self._owns_managed_runtime:
            try:
                self._managed_runtime.close()
            except BaseException as exc:
                errors.append(exc)
        if self._source_retained:
            try:
                _release_project_source(
                    self._project_package,
                    self._source_snapshot_src,
                )
            except BaseException as exc:
                errors.append(exc)
            else:
                self._source_retained = False
        self._closed = True
        if errors:
            raise ExceptionGroup(
                "project Research OS close failed",
                errors,
            )

def _project_manifest(root: Path) -> ProjectManifest:
    path = root / "project.manifest.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("project Research OS requires canonical project.manifest.json")
    manifest = decode_project_manifest_bytes(path.read_bytes())
    if manifest.template_revision != project_template_revision():
        raise ValueError(
            "project template revision is unsupported for Research OS composition"
        )
    return manifest


def _load_generated_portfolio(
    root: Path,
    manifest: ProjectManifest,
) -> ResearchPortfolio:
    project_id = manifest.project.identity.project_id
    package = project_package_name(project_id)
    src = (root / "src").resolve()
    research_path = src / package / "research.py"
    if not research_path.is_file() or research_path.is_symlink():
        raise ValueError("project is missing generated Research OS shell")

    module_name = f"{package}.research"
    stale_names = tuple(
        name
        for name in sys.modules
        if name == package or name.startswith(package + ".")
    )
    for name in stale_names:
        sys.modules.pop(name, None)

    importlib.invalidate_caches()
    sys.path.insert(0, str(src))
    try:
        module = importlib.import_module(module_name)
    except ImportError as exc:
        raise ValueError(
            f"cannot import generated Research OS module: {module_name}"
        ) from exc
    finally:
        if sys.path and sys.path[0] == str(src):
            sys.path.pop(0)

    module_file = getattr(module, "__file__", None)
    if (
        not isinstance(module_file, str)
        or Path(module_file).resolve() != research_path.resolve()
    ):
        raise ValueError(
            "generated Research OS module resolved outside the explicit project root"
        )
    portfolio = getattr(module, "PORTFOLIO", None)
    if type(portfolio) is not ResearchPortfolio:
        raise TypeError("generated Research OS shell did not expose ResearchPortfolio")
    if portfolio.portfolio_id != project_id:
        raise ValueError("project ResearchPortfolio identity drifted from manifest")
    return portfolio


def _public_revision(value) -> ResearchGraphRevision:
    revision = ResearchGraphRevision(
        value.subject_id,
        value.payload_digest,
        value.parent_revision_digests,
        value.message,
    )
    if revision.revision_digest != value.revision_digest:
        raise RuntimeError("project Research OS revision identity drifted")
    return revision


def _load_project_source(
    project_root: Path,
) -> tuple[Path, ProjectManifest, ResearchPortfolio]:
    root = project_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project Research OS root must be a real directory")
    manifest = _project_manifest(root)
    return root, manifest, _load_generated_portfolio(root, manifest)


def load_project_portfolio(project_root: Path) -> ResearchPortfolio:
    """Load the frozen portfolio without attaching control or runtime state."""

    _root, _manifest, portfolio = _load_project_source(project_root)
    return portfolio


def load_project_research_os(
    project_root: Path,
    *,
    shared_runtime: ManagedResearchRuntime | None = None,
    state_root: Path | None = None,
    revision_intent: str = "working",
) -> LoadedProjectResearchOS:
    """Load one project directly into the canonical Research OS.

    Downstream scientific code remains provider-free. Project opening loads
    only the durable Research OS control plane. The canonical ManagedResearchRuntime
    and owner-system execution authorities are materialized exactly once, lazily,
    when execution intent first reaches the control boundary.
    """

    if shared_runtime is not None and not isinstance(
        shared_runtime,
        ManagedResearchRuntime,
    ):
        raise TypeError("shared project runtime must be ManagedResearchRuntime")
    if revision_intent not in {"working", "active"}:
        raise ValueError("project revision_intent must be 'working' or 'active'")

    root = project_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project Research OS root must be a real directory")
    manifest = _project_manifest(root)
    resolved_state_root = (
        _project_state_root(root)
        if state_root is None
        else state_root.expanduser().absolute()
    )
    if resolved_state_root.is_symlink():
        raise ValueError("project Research OS state root must not be a symlink")
    resolved_state_root.mkdir(parents=True, exist_ok=True)

    package = project_package_name(manifest.project.identity.project_id)
    composition: LocalResearchOSComposition | None = None
    snapshot_src: Path | None = None
    source_snapshot_digest: str | None = None
    source_retained = False
    try:
        # Compose durable control state first.  ACTIVE intent intentionally does
        # not read the mutable worktree at all: it discovers the exact source
        # snapshot from the already-active durable ResearchGraph cut.
        composition = compose_local_research_os(resolved_state_root)
        research_os = composition.research_os
        revisions = composition.revision_store
        graph = composition.graph_store
        pool = composition.execution_pool
        execution_id = manifest.project.identity.project_id
        active = graph.active_cut(execution_id)
        active_revision: ResearchGraphRevision | None = None

        if active is not None:
            stored = revisions.revision(
                manifest.project.identity.project_id,
                active.research_revision_digest,
            )
            active_revision = _public_revision(stored)

        if revision_intent == "active":
            if active_revision is None:
                raise RuntimeError(
                    "active project control requires an existing durable Research OS cut"
                )
            source_snapshot_digest = _source_snapshot_digest_from_message(
                active_revision.message
            )
            snapshot_root = (
                resolved_state_root
                / _SOURCE_SNAPSHOT_DIRECTORY
                / source_snapshot_digest
            )
            if snapshot_root.is_symlink() or not snapshot_root.is_dir():
                raise RuntimeError(
                    "active project immutable source snapshot is missing"
                )
            snapshot_src = snapshot_root / "src"
            # ACTIVE control is durable-state only.  Import the immutable paper
            # source lazily if and only if an execution-producing action later
            # needs to reattach execution authorities.
            portfolio = None
            revision = active_revision
        else:
            snapshot_root, source_snapshot_digest = (
                _materialize_project_source_snapshot(
                    root,
                    resolved_state_root,
                )
            )
            snapshot_src = snapshot_root / "src"
            _retain_project_source(package, snapshot_src)
            source_retained = True
            portfolio = _load_generated_portfolio(snapshot_root, manifest)
            revision_message = _source_revision_message(source_snapshot_digest)
            if active_revision is None:
                revision = research_os.commit(
                    portfolio,
                    message=revision_message,
                )
            elif (
                active_revision.portfolio_digest == portfolio.portfolio_digest
                and active_revision.message == revision_message
            ):
                revision = active_revision
            else:
                revision = research_os.commit(
                    portfolio,
                    parents=(active_revision,),
                    message=revision_message,
                )

        assert source_snapshot_digest is not None
        assert snapshot_src is not None
        loaded = LoadedProjectResearchOS(
            root,
            resolved_state_root,
            manifest,
            portfolio,
            revision,
            active_revision,
            research_os,
            pool,
            composition,
            source_snapshot_digest,
            snapshot_src,
            package,
            _source_retained=source_retained,
            _shared_runtime=shared_runtime,
        )
        loaded.research_os = _LazyProjectResearchOS(loaded, research_os)
        return loaded
    except BaseException as primary:
        cleanup_errors: list[BaseException] = []
        if composition is not None:
            try:
                composition.close()
            except BaseException as exc:
                cleanup_errors.append(exc)
        if source_retained and snapshot_src is not None:
            try:
                _release_project_source(package, snapshot_src)
            except BaseException as exc:
                cleanup_errors.append(exc)
        if cleanup_errors:
            raise ExceptionGroup(
                "project Research OS open failed with cleanup errors",
                [primary, *cleanup_errors],
            ) from primary
        raise


__all__ = ["LoadedProjectResearchOS", "load_project_portfolio", "load_project_research_os"]
