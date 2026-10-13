from __future__ import annotations

from noetrium_platform.composition.method_telemetry_sink import RawLakeMethodObservationSink
from noetrium_platform.composition.diagnostic_degradation import (
    ForensicDiagnosticDegradationSink,
)
from noetrium_platform.composition.research_execution_costs import (
    ForensicTelemetryCostObservationSink,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime import (
    ForensicFailureMaterializer,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime.recorder import (
    FailureRecorder,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime.run_trace import (
    RunCausalTrace,
)
from noetrium_platform.infrastructure.reliability.forensics.composition import (
    ForensicStore,
)
from noetrium_platform.infrastructure.reliability.forensics.runtime.paths import (
    run_trace_forensics_root,
)

from dataclasses import dataclass, field
import hashlib
import importlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time
from threading import RLock

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_runtime_local import (
    LocalResearchComposition,
    compose_local_research_runtime,
)
from noetrium_platform.infrastructure.resources.directory.runtime import (
    standard_local_directory_layout,
)
from noetrium_platform.composition.runtime_coordination import runtime_fabric_root
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.kernel import (
    InterprocessLockBusy,
    materialize_staged_bytes,
)
from noetrium_platform.foundation.portfolio.api import (
    decode_project_manifest_bytes,
    project_manifest_project_id,
    project_manifest_template_revision,
)
from noetrium_platform.product.operator.api import project_template_revision
from noetrium_platform.product.research_unit import require_research_root
from noetrium_platform.product.research_control import (
    ResearchControlAction,
    ResearchControlReceipt,
    ResearchExecutionTarget,
    ResearchGraphRevision,
    BoundResearchControl,
)

from .project_execution_authority import (
    materialize_project_execution_authorities,
)
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionAuthorities,
    ResearchExecutionContext,
    compose_research_portfolio_roots,
)
from .project_layout import project_package_name


_STATE_DIRECTORY = ".noetrium/research"
_SOURCE_SNAPSHOT_DIRECTORY = "source-snapshots"
_SOURCE_SNAPSHOT_MESSAGE_PREFIX = "project source snapshot:"
_SOURCE_SNAPSHOT_ATTEMPTS = 4


_PROJECT_STATE_ROOT_ENV = "NOETRIUM_PROJECT_STATE_ROOT"
_ACTIVE_PROJECT_SOURCE_LOCK = RLock()
_ACTIVE_PROJECT_SOURCES: dict[str, tuple[str, int]] = {}



def _normalize_project_roots(
    project_roots: Path | tuple[Path, ...],
) -> tuple[Path, ...]:
    roots = (project_roots,) if isinstance(project_roots, Path) else project_roots
    if type(roots) is not tuple or not roots or any(not isinstance(row, Path) for row in roots):
        raise TypeError("Research execution roots must be pathlib.Path or non-empty Path tuple")
    resolved = tuple(row.expanduser().absolute() for row in roots)
    if len(resolved) != len(set(resolved)):
        raise ValueError("Research execution project roots must be unique")
    for root in resolved:
        if root.is_symlink() or not root.is_dir():
            raise ValueError(f"Research execution root must be a real directory: {root}")
    return tuple(sorted(resolved, key=str))


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
            materialize_staged_bytes(destination, payload)
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


def _run_bound_control(
    owner,
    control: BoundResearchControl,
    target: ResearchExecutionTarget,
    payload=None,
):
    """Run through the one loaded-root control authority."""
    trace = getattr(owner, "_run_trace", None)
    phase = (
        None
        if trace is None
        else trace.start_phase(
            "research.run",
            component_id="research.control",
            attributes={
                "execution_id": target.execution_id,
                "revision_digest": target.revision.revision_digest,
            },
        )
    )
    try:
        owner.ensure_execution_plane()
        receipt = owner._control.run(target, payload)
        if trace is not None and phase is not None:
            trace_attributes = {"receipt_state": receipt.state}
            if receipt.state in {"failed", "blocked", "cancelled"}:
                # A scientific/control terminal failure is authoritative in the
                # returned receipt and ResearchGraph failure provenance. Mark
                # the causal phase failed without manufacturing a second
                # operational Failure node or changing receipt-return semantics.
                trace.fail_phase(
                    phase,
                    RuntimeError(
                        "Research control receipt terminal state: " + receipt.state
                    ),
                    attributes=trace_attributes,
                    record_failure=False,
                )
            else:
                trace.complete_phase(phase, attributes=trace_attributes)
        return receipt
    except InterprocessLockBusy as exc:
        active_revision = owner.active_revision
        if (
            active_revision is None
            or active_revision.revision_digest != target.revision.revision_digest
        ):
            if trace is not None and phase is not None:
                trace.fail_phase(phase, exc)
            raise
        inspect_target = ResearchExecutionTarget(target.execution_id, active_revision)
        if target.graph is not None:
            inspect_target = inspect_target.for_graph(target.graph.path)
        inspected = control.inspect(inspect_target)
        payload_row = dict(inspected.payload or {})
        states = payload_row.get("states") or {}
        live = tuple(states.get("claimed", ())) + tuple(states.get("running", ()))
        if not live:
            if trace is not None and phase is not None:
                trace.fail_phase(phase, exc)
            raise
        payload_row["attached_to_existing_owner"] = True
        payload_row["owner_fence"] = "managed-research-runtime"
        state = "already_running"
        digest = canonical_digest(
            {
                "action": ResearchControlAction.RUN.value,
                "target_digest": target.target_digest,
                "state": state,
                "payload": payload_row,
            }
        )
        receipt = ResearchControlReceipt(
            ResearchControlAction.RUN,
            target,
            state,
            digest,
            payload_row,
        )
        if trace is not None and phase is not None:
            trace.complete_phase(phase, attributes={"receipt_state": receipt.state})
        return receipt
    except BaseException as exc:
        if trace is not None and phase is not None:
            trace.fail_phase(phase, exc)
        raise


@dataclass(slots=True)
class LoadedResearchRoot:
    """One Research over a recursive root set of one or many projects."""

    project_roots: tuple[Path, ...]
    state_root: Path
    sources: tuple[LoadedProjectSource, ...]
    portfolio: NoetriumUnit
    revision: ResearchGraphRevision
    active_revision: ResearchGraphRevision | None
    _control: BoundResearchControl
    execution_pool: ResearchExecutionPool | None
    _composition: LocalResearchComposition
    _shared_runtime: ManagedResearchRuntime | None = None
    _managed_runtime: ManagedResearchRuntime | None = None
    _owns_managed_runtime: bool = False
    _execution_authorities: ResearchExecutionAuthorities | None = None
    _run_trace: RunCausalTrace | None = None
    _run_forensics: ForensicStore | None = None
    _closed: bool = False
    _execution_lock: RLock = field(default_factory=RLock, repr=False)

    @property
    def default_execution_id(self) -> str:
        return self.revision.portfolio_id

    @property
    def execution_plane_ready(self) -> bool:
        return self._managed_runtime is not None

    @property
    def manifests(self) -> tuple[NoetriumUnit, ...]:
        return tuple(source.manifest for source in self.sources)

    @property
    def authority_manifest_digest(self) -> str | None:
        authorities = self._execution_authorities
        return None if authorities is None else authorities.authority_manifest_digest

    def default_target(self) -> ResearchExecutionTarget:
        return ResearchExecutionTarget(self.default_execution_id, self.revision)

    def run(
        self,
        target: ResearchExecutionTarget | None = None,
        payload=None,
    ):
        return _run_bound_control(
            self,
            self._control,
            self.default_target() if target is None else target,
            payload,
        )

    def inspect(self, target: ResearchExecutionTarget, payload=None):
        return self._control.inspect(target, payload)

    def pause(self, target: ResearchExecutionTarget, payload=None):
        return self._control.pause(target, payload)

    def drain(self, target: ResearchExecutionTarget, payload=None):
        return self._control.drain(target, payload)

    def interrupt(self, target: ResearchExecutionTarget, payload=None):
        return self._control.interrupt(target, payload)

    def resume(self, target: ResearchExecutionTarget, payload=None):
        self.ensure_execution_plane()
        return self._control.resume(target, payload)

    def retry(self, target: ResearchExecutionTarget, payload=None):
        self.ensure_execution_plane()
        return self._control.retry(target, payload)

    def cancel(self, target: ResearchExecutionTarget, payload=None):
        return self._control.cancel(target, payload)

    def checkpoint(self, target: ResearchExecutionTarget, payload=None):
        self.ensure_execution_plane()
        return self._control.checkpoint(target, payload)

    def reconcile(self, target: ResearchExecutionTarget, payload=None):
        self.ensure_execution_plane()
        return self._control.reconcile(target, payload)

    def migrate(self, target: ResearchExecutionTarget, payload=None):
        self.ensure_execution_plane()
        return self._control.migrate(target, payload)

    def ensure_execution_plane(self) -> None:
        if self._closed:
            raise RuntimeError("Research execution is closed")
        if self._managed_runtime is not None:
            return
        with self._execution_lock:
            if self._managed_runtime is not None:
                return
            trace = self._run_trace
            runtime_phase = (
                None
                if trace is None
                else trace.start_phase(
                    "execution-runtime.materialize",
                    component_id="runtime.fabric",
                )
            )
            owns_runtime = self._shared_runtime is None
            runtime = self._shared_runtime
            try:
                if runtime is None:
                    runtime = build_local_managed_research_runtime(
                        standard_local_directory_layout(
                            self.state_root / "platform-runtime"
                        ),
                    )
                else:
                    runtime.assert_healthy()
            except BaseException as primary:
                if trace is not None and runtime_phase is not None:
                    trace.fail_phase(runtime_phase, primary)
                raise
            if trace is not None and runtime_phase is not None:
                trace.complete_phase(
                    runtime_phase,
                    attributes={"owns_runtime": owns_runtime},
                )

            replacement = None
            authorities = None
            try:
                authority_phase = (
                    None
                    if trace is None
                    else trace.start_phase(
                        "execution-authority.materialize",
                        component_id="research.execution.authority",
                    )
                )
                try:
                    context = ResearchExecutionContext(
                        self.state_root,
                        runtime,
                        content=self._composition.content,
                        execution_tenant_id=self.portfolio.unit_id,
                        causal_context=(None if trace is None else trace.context),
                        causal_event_refs=(
                            () if trace is None else (trace.head_event.unit_digest,)
                        ),
                    )
                    authorities = materialize_project_execution_authorities(
                        context,
                        self.portfolio,
                        self.manifests,
                    )
                except BaseException as exc:
                    if trace is not None and authority_phase is not None:
                        trace.fail_phase(authority_phase, exc)
                    raise
                else:
                    if trace is not None and authority_phase is not None:
                        trace.complete_phase(
                            authority_phase,
                            attributes={
                                "authority_manifest_digest": (
                                    authorities.authority_manifest_digest
                                )
                            },
                        )

                compose_phase = (
                    None
                    if trace is None
                    else trace.start_phase(
                        "execution-plane.compose",
                        component_id="research.composition",
                    )
                )
                try:
                    replacement = compose_local_research_runtime(
                        self.state_root,
                        experiment_compilation=authorities.experiment_compilation,
                        experiment_runtime_binding=authorities.experiment_runtime_binding,
                        symbol_bindings=authorities.symbol_bindings,
                        execution_pool=runtime.execution_pool,
                        method_runtime_inventory=authorities.method_runtime_inventory,
                        operation_dispatcher=runtime.operation_runtime.dispatcher,
                        method_observation=RawLakeMethodObservationSink(
                            runtime.observability.raw
                        ),
                        content_authorities=context.content,
                        cost_observation=ForensicTelemetryCostObservationSink(
                            runtime.operation_runtime.forensics,
                            runtime.observability.telemetry,
                        ),
                        diagnostic_degradation=ForensicDiagnosticDegradationSink(
                            runtime.operation_runtime.forensics
                        ),
                        failure_materializer=ForensicFailureMaterializer(
                            FailureRecorder(runtime.operation_runtime.forensics)
                        ),
                        lifetime_controller=authorities.lifetime_controller,
                        causal_event_refs=(
                            ()
                            if trace is None
                            else (trace.head_event.unit_digest,)
                        ),
                    )
                except BaseException as exc:
                    if trace is not None and compose_phase is not None:
                        trace.fail_phase(compose_phase, exc)
                    raise
                else:
                    if trace is not None and compose_phase is not None:
                        trace.complete_phase(compose_phase)
            except BaseException as primary:
                cleanup=[]
                if replacement is not None:
                    try: replacement.close()
                    except BaseException as exc: cleanup.append(exc)
                if authorities is not None:
                    try: authorities.retire()
                    except BaseException as exc: cleanup.append(exc)
                if owns_runtime:
                    try: runtime.close()
                    except BaseException as exc: cleanup.append(exc)
                if cleanup:
                    raise BaseExceptionGroup(
                        "Research execution execution-plane materialization failed",
                        [primary, *cleanup],
                    ) from primary
                raise

            previous=self._composition
            handoff_phase = (
                None
                if trace is None
                else trace.start_phase(
                    "control-plane.handoff",
                    component_id="research.control_plane",
                )
            )
            previous.handoff_content_ownership(replacement)
            try:
                previous.close()
            except BaseException as primary:
                if trace is not None and handoff_phase is not None:
                    trace.fail_phase(handoff_phase, primary)
                cleanup=[]
                try: replacement.close()
                except BaseException as exc: cleanup.append(exc)
                try: authorities.retire()
                except BaseException as exc: cleanup.append(exc)
                if owns_runtime:
                    try: runtime.close()
                    except BaseException as exc: cleanup.append(exc)
                if cleanup:
                    raise BaseExceptionGroup(
                        "Research execution control-plane replacement failed",
                        [primary,*cleanup],
                    ) from primary
                raise
            else:
                if trace is not None and handoff_phase is not None:
                    trace.complete_phase(handoff_phase)

            self._composition=replacement
            self.execution_pool=replacement.execution_pool
            self._managed_runtime=runtime
            self._owns_managed_runtime=owns_runtime
            self._execution_authorities=authorities
            self._control = replacement.control

    def retire_runtime_fabric(self) -> None:
        if self._closed:
            raise RuntimeError("Research execution is closed")
        if self._shared_runtime is not None:
            raise RuntimeError("Research execution cannot retire a borrowed Runtime Fabric")
        with self._execution_lock:
            if self._execution_authorities is not None:
                raise RuntimeError("terminal Runtime Fabric retirement requires a fresh control handle")
            runtime=self._managed_runtime
            if runtime is None:
                runtime=build_local_managed_research_runtime(
                    standard_local_directory_layout(self.state_root / "platform-runtime"),
                )
                self._managed_runtime=runtime
                self._owns_managed_runtime=True
            runtime.retire_runtime_fabric()

    def close(self) -> None:
        if self._closed:
            return

        trace = self._run_trace
        retire_phase = (
            None
            if trace is None
            else trace.start_phase(
                "lifecycle.retire",
                component_id="research.lifecycle",
            )
        )
        runtime = self._managed_runtime
        errors: list[BaseException] = []

        def attempt(stage: str, action) -> bool:
            try:
                action()
            except BaseException as exc:
                try:
                    exc.add_note("Research execution close stage failed: " + stage)
                except BaseException:
                    pass
                errors.append(exc)
                return False
            return True

        # Stop admitting/dispatching workload first. Physical session/provider
        # cleanup remains live on lifecycle groups, so authority retirement can
        # safely drain those owners after workload quiescence.
        if runtime is not None and self._owns_managed_runtime:
            attempt("runtime workload quiescence", lambda: runtime.quiesce_workloads())

        if self._execution_authorities is not None:
            authorities = self._execution_authorities
            if attempt("execution authority retirement", lambda: authorities.retire()):
                self._execution_authorities = None

        attempt("research composition close", lambda: self._composition.close())

        if runtime is not None and self._owns_managed_runtime:
            if attempt("managed runtime close", runtime.close):
                self._managed_runtime = None

        for source in reversed(self.sources):
            attempt("research source close", source.close)

        close_error: BaseException | None = None
        if errors:
            close_error = BaseExceptionGroup(
                "Research execution close failed",
                errors,
            )

        if trace is not None and retire_phase is not None:
            try:
                if close_error is None:
                    trace.complete_phase(retire_phase)
                else:
                    trace.fail_phase(retire_phase, close_error)
                trace.finish(
                    attributes={
                        "revision_digest": self.revision.revision_digest,
                        "root_unit_digest": self.portfolio.unit_digest,
                    }
                )
            except BaseException as exc:
                errors.append(exc)
                close_error = BaseExceptionGroup(
                    "Research execution close failed",
                    errors,
                )

        if self._run_forensics is not None:
            try:
                self._run_forensics.close()
            except BaseException as exc:
                errors.append(exc)
                close_error = BaseExceptionGroup(
                    "Research execution close failed",
                    errors,
                )
            finally:
                self._run_forensics = None

        if close_error is not None:
            raise close_error
        self._closed = True


def _project_manifest(root: Path) -> NoetriumUnit:
    path = root / "project.manifest.json"
    if not path.is_file() or path.is_symlink():
        raise ValueError("project Research execution requires canonical project.manifest.json")
    manifest = decode_project_manifest_bytes(path.read_bytes())
    if project_manifest_template_revision(manifest) != project_template_revision():
        raise ValueError(
            "project template revision is unsupported for Research execution composition"
        )
    return manifest

_SOURCE_SET_MESSAGE_PREFIX = "research source set:"

def _root_set_identity(project_roots: tuple[Path, ...]) -> tuple[str, str]:
    digest = canonical_digest(
        {
            "schema": "noetrium.project-root-set.v1",
            "roots": tuple(str(row) for row in project_roots),
        }
    )
    return f"research-root-{digest[:24]}", digest

def _root_set_state_root(project_roots: tuple[Path, ...]) -> Path:
    explicit = os.environ.get(_PROJECT_STATE_ROOT_ENV, "").strip()
    if explicit:
        root = Path(explicit).expanduser()
        if not root.is_absolute():
            raise ValueError(f"{_PROJECT_STATE_ROOT_ENV} must be an absolute path")
        return root
    _root_id, digest = _root_set_identity(project_roots)
    return runtime_fabric_root() / "research" / digest

def _write_source_set(state_root: Path, sources: tuple[LoadedProjectSource, ...]) -> str:
    payload = _source_set_payload(sources)
    digest = canonical_digest(payload)
    path = state_root / _SOURCE_SET_DIRECTORY / f"{digest}.json"
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8") + b"\n"
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != raw:
            raise RuntimeError("durable research source-set identity drifted")
    else:
        materialize_staged_bytes(path, raw)
    return digest

def _source_set_digest_from_message(message: str) -> str:
    if type(message) is not str or not message.startswith(_SOURCE_SET_MESSAGE_PREFIX):
        raise RuntimeError("Research execution revision has no durable source-set identity")
    digest = message[len(_SOURCE_SET_MESSAGE_PREFIX):]
    if len(digest) != 64 or any(ch not in "0123456789abcdef" for ch in digest):
        raise RuntimeError("Research execution source-set identity is invalid")
    return digest

def _load_durable_source_set(state_root: Path, digest: str) -> tuple[LoadedProjectSource, ...]:
    path = state_root / _SOURCE_SET_DIRECTORY / f"{digest}.json"
    if path.is_symlink() or not path.is_file():
        raise RuntimeError("durable research source-set record is missing")
    try:
        payload = json.loads(path.read_text("utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RuntimeError("durable research source-set record is invalid") from exc
    if not isinstance(payload, dict) or payload.get("schema") != "noetrium.research-source-set.v1":
        raise RuntimeError("durable research source-set schema is invalid")
    if canonical_digest(payload) != digest:
        raise RuntimeError("durable research source-set digest drifted")
    rows = payload.get("sources")
    if not isinstance(rows, list) or not rows:
        raise RuntimeError("durable research source-set is empty")
    sources: list[LoadedProjectSource] = []
    try:
        for row in rows:
            if not isinstance(row, dict):
                raise RuntimeError("durable research source-set row is invalid")
            project_root = Path(str(row["project_root"]))
            project_id = str(row["project_id"])
            state_key = str(row["source_state_key"])
            snapshot_digest = str(row["snapshot_digest"])
            source_state = state_root / "sources" / state_key
            snapshot_root = source_state / _SOURCE_SNAPSHOT_DIRECTORY / snapshot_digest
            if snapshot_root.is_symlink() or not snapshot_root.is_dir():
                raise RuntimeError("durable research source snapshot is missing")
            manifest = _project_manifest(snapshot_root)
            if project_manifest_project_id(manifest) != project_id:
                raise RuntimeError("durable research source project identity drifted")
            snapshot_src = snapshot_root / "src"
            package = project_package_name(project_id)
            _retain_project_source(package, snapshot_src)
            try:
                portfolio = _load_project_portfolio_unit(snapshot_root, manifest)
            except BaseException:
                _release_project_source(package, snapshot_src)
                raise
            sources.append(
                LoadedProjectSource(
                    project_root,
                    source_state,
                    manifest,
                    portfolio,
                    snapshot_digest,
                    snapshot_src,
                    package,
                )
            )
        return tuple(sources)
    except BaseException:
        for source in reversed(sources):
            try:
                source.close()
            except BaseException:
                pass
        raise

def _compose_root_set_portfolio(
    sources: tuple[LoadedProjectSource, ...],
    *,
    root_id: str,
) -> NoetriumUnit:
    ids = tuple(project_manifest_project_id(source.manifest) for source in sources)
    if len(ids) != len(set(ids)):
        raise ValueError("Research execution source-set project identities must be unique")
    if len(sources) == 1:
        return sources[0].portfolio
    return compose_research_portfolio_roots(
        tuple(source.portfolio for source in sources),
        root_id=root_id,
    )


_SOURCE_SET_DIRECTORY = "source-sets"

def _source_set_payload(sources: tuple[LoadedProjectSource, ...]) -> dict[str, object]:
    rows = tuple(
        {
            "project_root": str(source.project_root),
            "project_id": project_manifest_project_id(source.manifest),
            "source_state_key": canonical_digest(str(source.project_root))[:24],
            "snapshot_digest": source.source_snapshot_digest,
        }
        for source in sources
    )
    return {"schema": "noetrium.research-source-set.v1", "sources": rows}


@dataclass(slots=True)
class LoadedProjectSource:
    """Immutable project source/manifest/portfolio ownership without runtime."""

    project_root: Path
    state_root: Path
    manifest: NoetriumUnit
    portfolio: NoetriumUnit
    source_snapshot_digest: str
    _source_snapshot_src: Path
    _project_package: str
    _closed: bool = False

    def close(self) -> None:
        if self._closed:
            return
        _release_project_source(
            self._project_package,
            self._source_snapshot_src,
        )
        self._closed = True

def load_project_source_snapshot(
    project_root: Path,
    *,
    state_root: Path,
) -> LoadedProjectSource:
    """Freeze one downstream source tree without composing Research/runtime."""

    root = project_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project source root must be a real directory")
    resolved_state = state_root.expanduser().absolute()
    if resolved_state.is_symlink():
        raise ValueError("project source state root must not be a symlink")
    resolved_state.mkdir(parents=True, exist_ok=True)
    manifest = _project_manifest(root)
    snapshot_root, snapshot_digest = _materialize_project_source_snapshot(
        root,
        resolved_state,
    )
    snapshot_src = snapshot_root / "src"
    package = project_package_name(project_manifest_project_id(manifest))
    _retain_project_source(package, snapshot_src)
    try:
        portfolio = _load_project_portfolio_unit(snapshot_root, manifest)
    except BaseException:
        _release_project_source(package, snapshot_src)
        raise
    return LoadedProjectSource(
        root,
        resolved_state,
        manifest,
        portfolio,
        snapshot_digest,
        snapshot_src,
        package,
    )


def _load_research_root(
    project_roots: Path | tuple[Path, ...],
    *,
    root_unit: NoetriumUnit | None = None,
    shared_runtime: ManagedResearchRuntime | None = None,
    state_root: Path | None = None,
    revision_intent: str = "working",
) -> LoadedResearchRoot:
    """Canonical loader for both source-authored and direct-Unit research roots."""
    if root_unit is not None and type(root_unit) is not NoetriumUnit:
        raise TypeError("direct research root must be NoetriumUnit")
    if root_unit is not None and revision_intent != "working":
        raise ValueError("direct NoetriumUnit loading only supports working revision")
    if shared_runtime is not None and not isinstance(shared_runtime,ManagedResearchRuntime):
        raise TypeError("shared runtime must be ManagedResearchRuntime")
    if revision_intent not in {"working","active"}:
        raise ValueError("revision_intent must be 'working' or 'active'")
    roots=_normalize_project_roots(project_roots)
    root_id,_root_digest=_root_set_identity(roots)
    direct_portfolio = None if root_unit is None else require_research_root(root_unit)
    if direct_portfolio is not None:
        authority_root_id = direct_portfolio.unit_id
    elif len(roots) == 1:
        authority_root_id = project_manifest_project_id(_project_manifest(roots[0]))
    else:
        authority_root_id = root_id
    resolved_state=(
        _root_set_state_root(roots)
        if state_root is None
        else state_root.expanduser().absolute()
    )
    if resolved_state.is_symlink():
        raise ValueError("Research execution state root must not be a symlink")
    resolved_state.mkdir(parents=True,exist_ok=True)
    source_identity = tuple(str(root) for root in roots)
    trace_partition_id = canonical_digest(
        {
            "schema": "noetrium.run-trace-partition.v1",
            "source_identity": source_identity,
            "state_root": str(resolved_state),
            "pid": os.getpid(),
            "started_ns": time.time_ns(),
        }
    )
    run_forensics = ForensicStore(
        run_trace_forensics_root(resolved_state, trace_partition_id),
        read_only=False,
        task_group=None,
    )
    parent_digest = os.environ.get(
        "NOETRIUM_CONTROL_PARENT_EVENT_DIGEST",
        "",
    ).strip()
    try:
        run_trace = RunCausalTrace(
            run_forensics,
            source_identity=source_identity,
            execution_tenant_id=authority_root_id,
            causal_parent_digests=(
                () if not parent_digest else (parent_digest,)
            ),
        )
    except BaseException:
        run_forensics.close()
        raise
    load_phase = run_trace.start_phase(
        "research.load",
        component_id="project.loader",
        attributes={"revision_intent": revision_intent},
    )
    composition=None
    sources=()
    try:
        composition_phase = run_trace.start_phase(
            "control-plane.compose",
            component_id="research.control_plane",
        )
        try:
            composition=compose_local_research_runtime(resolved_state)
        except BaseException as exc:
            run_trace.fail_phase(composition_phase, exc)
            raise
        else:
            run_trace.complete_phase(composition_phase)
        control=composition.control
        active=composition.graph_store.active_cut(authority_root_id)
        active_revision=None
        if active is not None:
            stored=composition.revision_store.revision(
                authority_root_id,
                active.research_revision_digest,
            )
            active_revision=_public_revision(stored)
        if revision_intent == "active":
            if active_revision is None:
                raise RuntimeError("active Research execution control requires an existing durable cut")
            source_set_digest=_source_set_digest_from_message(active_revision.message)
            sources=_load_durable_source_set(resolved_state,source_set_digest)
            portfolio=_compose_root_set_portfolio(sources,root_id=root_id)
            if portfolio.unit_digest != active_revision.portfolio_digest:
                raise RuntimeError("active Research execution source-set drifted from durable revision")
            revision=active_revision
        else:
            loaded=[]
            try:
                for root in roots:
                    state_key=canonical_digest(str(root))[:24]
                    loaded.append(load_project_source_snapshot(root,state_root=resolved_state / "sources" / state_key))
                sources=tuple(loaded)
            except BaseException:
                for source in reversed(loaded):
                    try: source.close()
                    except BaseException: pass
                raise
            portfolio=(
                _compose_root_set_portfolio(sources,root_id=root_id)
                if direct_portfolio is None
                else direct_portfolio
            )
            source_set_digest=_write_source_set(resolved_state,sources)
            message=_SOURCE_SET_MESSAGE_PREFIX+source_set_digest
            if active_revision is None:
                revision=control.commit(portfolio,message=message)
            elif active_revision.portfolio_digest == portfolio.unit_digest and active_revision.message == message:
                revision=active_revision
            else:
                revision=control.commit(portfolio,parents=(active_revision,),message=message)
        run_trace.complete_phase(
            load_phase,
            attributes={
                "root_unit_id": portfolio.unit_id,
                "root_unit_digest": portfolio.unit_digest,
                "revision_digest": revision.revision_digest,
            },
        )
        return LoadedResearchRoot(
            roots,resolved_state,sources,portfolio,revision,active_revision,
            control,composition.execution_pool,composition,
            _shared_runtime=shared_runtime,
            _run_trace=run_trace,
            _run_forensics=run_forensics,
        )
    except BaseException as primary:
        try:
            run_trace.fail_phase(load_phase, primary)
        except BaseException:
            pass
        cleanup=[]
        if composition is not None:
            try: composition.close()
            except BaseException as exc: cleanup.append(exc)
        for source in reversed(sources):
            try: source.close()
            except BaseException as exc: cleanup.append(exc)
        try:
            run_forensics.close()
        except BaseException as exc:
            cleanup.append(exc)
        if cleanup:
            raise BaseExceptionGroup("Research execution load failed with cleanup errors",[primary,*cleanup]) from primary
        raise


def load_research_root(
    source: NoetriumUnit | Path | tuple[Path, ...],
    *,
    project_roots: Path | tuple[Path, ...] | None = None,
    shared_runtime: ManagedResearchRuntime | None = None,
    state_root: Path | None = None,
    revision_intent: str = "working",
) -> LoadedResearchRoot:
    """Load one canonical research root from a Unit or filesystem source."""
    if type(source) is NoetriumUnit:
        if revision_intent != "working":
            raise ValueError("direct NoetriumUnit loading only supports working revision")
        roots = Path(".") if project_roots is None else project_roots
        return _load_research_root(
            roots,
            root_unit=source,
            shared_runtime=shared_runtime,
            state_root=state_root,
            revision_intent="working",
        )
    if project_roots is not None:
        raise ValueError("project_roots is only valid when source is NoetriumUnit")
    if not isinstance(source, Path) and type(source) is not tuple:
        raise TypeError("research root source must be NoetriumUnit, Path, or Path tuple")
    return _load_research_root(
        source,
        shared_runtime=shared_runtime,
        state_root=state_root,
        revision_intent=revision_intent,
    )


def _load_project_portfolio_unit(
    root: Path,
    manifest: NoetriumUnit,
) -> NoetriumUnit:
    project_id = project_manifest_project_id(manifest)
    package = project_package_name(project_id)
    src = (root / "src").resolve()
    research_path = src / package / "research.py"
    if not research_path.is_file() or research_path.is_symlink():
        raise ValueError("project is missing user-owned research.py")

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
            f"cannot import project research module: {module_name}"
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
            "project research module resolved outside the explicit project root"
        )
    root_unit = getattr(module, "ROOT", None)
    if type(root_unit) is not NoetriumUnit:
        raise TypeError("project research module did not expose ROOT NoetriumUnit")
    if root_unit.unit_id != project_id:
        raise ValueError("project ROOT Unit identity drifted from manifest")
    return require_research_root(root_unit)


def _public_revision(value) -> ResearchGraphRevision:
    revision = ResearchGraphRevision(
        value.subject_id,
        value.semantic_digest,
        value.parent_revision_digests,
        value.message,
    )
    if revision.revision_digest != value.revision_digest:
        raise RuntimeError("Research execution revision identity drifted")
    return revision


def _load_project_source(
    project_root: Path,
) -> tuple[Path, NoetriumUnit, NoetriumUnit]:
    root = project_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project Research execution root must be a real directory")
    manifest = _project_manifest(root)
    return root, manifest, _load_project_portfolio_unit(root, manifest)


def load_project_portfolio(project_root: Path) -> NoetriumUnit:
    """Load the frozen research.portfolio Unit without attaching runtime state."""

    _root, _manifest, portfolio = _load_project_source(project_root)
    return portfolio




__all__ = ["LoadedProjectSource", "LoadedResearchRoot", "load_project_portfolio", "load_project_source_snapshot", "load_research_root"]
