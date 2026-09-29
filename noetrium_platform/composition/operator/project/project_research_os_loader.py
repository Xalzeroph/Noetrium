from __future__ import annotations

from noetrium_platform.composition.method_telemetry_sink import RawLakeMethodObservationSink

from dataclasses import dataclass, field
import importlib
from pathlib import Path
import sys
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
    ProjectExecutionAuthorityConfig,
    load_project_execution_authority_config,
    materialize_project_execution_authorities,
)
from noetrium_platform.composition.research_portfolio_execution import (
    ResearchExecutionContext,
)
from .project_layout import project_package_name


_STATE_DIRECTORY = ".noetrium/research-os"
_REVISION_MESSAGE_INITIAL = "project source"
_REVISION_MESSAGE_UPDATE = "project source update"


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
        return self._execution_delegate().pause(target, payload)

    def drain(self, target, payload=None):
        return self._execution_delegate().drain(target, payload)

    def interrupt(self, target, payload=None):
        return self._execution_delegate().interrupt(target, payload)

    def resume(self, target, payload=None):
        return self._execution_delegate().resume(target, payload)

    def retry(self, target, payload=None):
        return self._execution_delegate().retry(target, payload)

    def cancel(self, target, payload=None):
        return self._execution_delegate().cancel(target, payload)

    def checkpoint(self, target, payload=None):
        return self._execution_delegate().checkpoint(target, payload)

    def reconcile(self, target, payload=None):
        return self._execution_delegate().reconcile(target, payload)

    def migrate(self, target, payload=None):
        return self._execution_delegate().migrate(target, payload)


@dataclass(slots=True)
class LoadedProjectResearchOS:
    """Project control plane with one lazily-owned physical execution plane."""

    project_root: Path
    manifest: ProjectManifest
    portfolio: ResearchPortfolio
    revision: ResearchGraphRevision
    active_revision: ResearchGraphRevision | None
    research_os: ResearchOS
    execution_pool: ResearchExecutionPool
    _composition: LocalResearchOSComposition
    _execution_config: ProjectExecutionAuthorityConfig
    _managed_runtime: ManagedResearchRuntime | None = None
    _closed: bool = False
    _execution_lock: RLock = field(default_factory=RLock, repr=False)

    @property
    def default_execution_id(self) -> str:
        return self.manifest.project.identity.project_id

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
            state_root = self.project_root / _STATE_DIRECTORY
            managed_runtime = build_local_managed_research_runtime(
                standard_local_directory_layout(state_root / "platform-runtime"),
                # Initial execution-authority materialization is the sole owner
                # of model/resource convergence. Background reconcilers attach
                # only after that synchronous closure is complete, otherwise
                # they can race the bootstrap fleet over the same desired
                # deployment generation.
                start_background_controllers=False,
            )
            replacement: LocalResearchOSComposition | None = None
            try:
                context = ResearchExecutionContext(
                    state_root,
                    managed_runtime,
                    content=self._composition.content,
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
                if self._execution_config.start_background_controllers:
                    managed_runtime.start_background_controllers()
            except BaseException as primary:
                try:
                    managed_runtime.close()
                except BaseException as cleanup:
                    raise ExceptionGroup(
                        "project execution-plane materialization failed with cleanup error",
                        [primary, cleanup],
                    ) from primary
                raise
            previous = self._composition
            try:
                previous.close()
            except BaseException as primary:
                cleanup_errors: list[BaseException] = []
                try:
                    replacement.close()
                except BaseException as exc:
                    cleanup_errors.append(exc)
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
            proxy = self.research_os
            if isinstance(proxy, _LazyProjectResearchOS):
                proxy._replace_delegate(replacement.research_os)
            else:
                self.research_os = replacement.research_os

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        try:
            self._composition.close()
        except BaseException as exc:
            errors.append(exc)
        if self._managed_runtime is not None:
            try:
                self._managed_runtime.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            raise ExceptionGroup(
                "project Research OS close failed",
                errors,
            )
        self._closed = True

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


def load_project_research_os(
    project_root: Path,
    *,
    config_path: Path | None = None,
) -> LoadedProjectResearchOS:
    """Load one project directly into the canonical Research OS.

    Downstream scientific code remains provider-free. Project opening loads
    only the durable Research OS control plane. The canonical ManagedResearchRuntime
    and owner-system execution authorities are materialized exactly once, lazily,
    when execution intent first reaches the control boundary.
    """

    root = project_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project Research OS root must be a real directory")

    manifest = _project_manifest(root)
    portfolio = _load_generated_portfolio(root, manifest)
    state_root = root / _STATE_DIRECTORY
    state_root.mkdir(parents=True, exist_ok=True)

    config = (
        ProjectExecutionAuthorityConfig()
        if config_path is None
        else load_project_execution_authority_config(config_path)
    )

    # Project opening is control-plane only. Physical runtime ownership,
    # Docker/model/resource reconciliation and execution authorities attach at
    # the first execution intent.
    composition = compose_local_research_os(state_root)
    research_os = composition.research_os
    revisions = composition.revision_store
    graph = composition.graph_store
    pool = composition.execution_pool

    execution_id = manifest.project.identity.project_id
    active = graph.active_cut(execution_id)
    active_revision = None
    if active is None:
        revision = research_os.commit(
            portfolio,
            message=_REVISION_MESSAGE_INITIAL,
        )
    else:
        stored = revisions.revision(
            portfolio.portfolio_id,
            active.research_revision_digest,
        )
        active_revision = _public_revision(stored)
        if active_revision.portfolio_digest == portfolio.portfolio_digest:
            revision = active_revision
        else:
            revision = research_os.commit(
                portfolio,
                parents=(active_revision,),
                message=_REVISION_MESSAGE_UPDATE,
            )

    loaded = LoadedProjectResearchOS(
        root,
        manifest,
        portfolio,
        revision,
        active_revision,
        research_os,
        pool,
        composition,
        config,
    )
    loaded.research_os = _LazyProjectResearchOS(loaded, research_os)
    return loaded


__all__ = ["LoadedProjectResearchOS", "load_project_research_os"]
