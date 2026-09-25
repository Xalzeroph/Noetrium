from __future__ import annotations

from dataclasses import dataclass
import importlib
from pathlib import Path
import sys

from noetrium_platform.composition.managed_research_runtime import (
    ManagedResearchRuntime,
    build_local_managed_research_runtime,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_os_local import (
    LocalResearchOSComposition,
    compose_local_research_os,
)
from noetrium_platform.composition.research_os_study_closure import (
    ResearchStudyProtocolClosureProvider,
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
    ProjectExecutionContext,
    load_project_execution_authority_config,
    materialize_project_execution_authorities,
)
from .project_layout import project_package_name


_STATE_DIRECTORY = ".noetrium/research-os"
_REVISION_MESSAGE_INITIAL = "project source"
_REVISION_MESSAGE_UPDATE = "project source update"


@dataclass(slots=True)
class LoadedProjectResearchOS:
    """Platform-owned canonical Research OS composition for one generated project."""

    project_root: Path
    manifest: ProjectManifest
    portfolio: ResearchPortfolio
    revision: ResearchGraphRevision
    active_revision: ResearchGraphRevision | None
    research_os: ResearchOS
    execution_pool: ResearchExecutionPool
    _composition: LocalResearchOSComposition
    _managed_runtime: ManagedResearchRuntime | None = None
    _closed: bool = False

    @property
    def default_execution_id(self) -> str:
        return self.manifest.project.identity.project_id

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

    Downstream scientific code remains provider-free. Optional machine-local
    provider composition is loaded from one typed authority factory and receives
    the canonical ManagedResearchRuntime rather than constructing shadow Docker,
    endpoint, compute, environment, model or execution-pool authorities.
    """

    root = project_root.expanduser().absolute()
    if root.is_symlink() or not root.is_dir():
        raise ValueError("project Research OS root must be a real directory")

    manifest = _project_manifest(root)
    portfolio = _load_generated_portfolio(root, manifest)
    state_root = root / _STATE_DIRECTORY
    state_root.mkdir(parents=True, exist_ok=True)

    managed_runtime: ManagedResearchRuntime | None = None
    if config_path is None:
        composition = compose_local_research_os(state_root)
    else:
        config = load_project_execution_authority_config(config_path)
        managed_runtime = build_local_managed_research_runtime(
            standard_local_directory_layout(
                state_root / "platform-runtime"
            ),
            start_background_controllers=(
                config.start_background_controllers
            ),
        )
        try:
            context = ProjectExecutionContext(
                root,
                state_root,
                manifest,
                portfolio,
                managed_runtime,
            )
            authorities = materialize_project_execution_authorities(
                config.authority_factory,
                context,
            )
            closures = (
                None
                if authorities.research_bindings is None
                else ResearchStudyProtocolClosureProvider(
                    authorities.research_bindings
                )
            )
            composition = compose_local_research_os(
                state_root,
                experiment_closures=closures,
                experiment_runtime_components=(
                    authorities.experiment_runtime_components
                ),
                execution_pool=managed_runtime.execution_pool,
                method_runtime_inventory=(
                    authorities.method_runtime_inventory
                ),
            )
        except BaseException as primary:
            try:
                managed_runtime.close()
            except BaseException as cleanup:
                raise ExceptionGroup(
                    "project authority composition failed with runtime cleanup error",
                    [primary, cleanup],
                ) from primary
            raise
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

    return LoadedProjectResearchOS(
        root,
        manifest,
        portfolio,
        revision,
        active_revision,
        research_os,
        pool,
        composition,
        managed_runtime,
    )


__all__ = ["LoadedProjectResearchOS", "load_project_research_os"]
