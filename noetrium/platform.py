"""Stable product facade for applications built on Noetrium."""

from __future__ import annotations

from importlib import resources
from pathlib import Path
import math
import shutil
import subprocess
from uuid import uuid4

from noetrium_platform.api import (
    ProjectTestStage,
    ProjectTestStageReceipt,
    ResearchAction,
    ResearchApplicationPort,
    ResearchFacade,
    ResearchOperationFailure,
    ResearchRequest,
    ResearchResult,
)
from noetrium_platform.capabilities.environment.category.api import EnvironmentCategoryCatalogPort
from noetrium_platform.capabilities.environment.category.composition import (
    default_environment_category_catalog,
)
from noetrium_platform.capabilities.environment.api import (
    EnvironmentCapability,
    EnvironmentIdentity,
    EnvironmentProviderCapabilities,
    EnvironmentSession,
    EnvironmentSessionServices,
)
from noetrium_platform.capabilities.environment.minecraft.api import (
    MinecraftAgentSpec,
    MinecraftBridgeSpec,
    MinecraftCheckpointPort,
    MinecraftDiagnosticsPort,
    MinecraftEndpointSpec,
    MinecraftEnvironmentSpec,
)
from noetrium_platform.capabilities.environment.minecraft.composition.environment import (
    compose_minecraft_environment,
)
from noetrium_platform.capabilities.model.api import (
    ModelBindingDiagnostic,
    ModelCapabilityRequirement,
    ModelProviderProfile,
    ProjectModelClientPort,
    ProjectModelProviderPort,
)
from noetrium_platform.capabilities.model.providers import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.request.composition.recorder import (
    build_directory_model_request_recorder,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    PersistedQualifiedModelEndpointBinding,
    build_openai_compatible_qualified_endpoint,
    load_qualified_model_deployment_closure,
)
from noetrium_platform.capabilities.model.serving.providers import (
    DirectoryRuntimeCanaryEvidenceStore,
    DirectoryRuntimeQualificationEvidenceStore,
)
from noetrium_platform.capabilities.model.serving.runtime.admission import ModelAdmissionRegistry
from noetrium_platform.capabilities.participant.method.api import (
    MethodEndpointPort,
    MethodImplementation,
    MethodSessionRuntime,
)
from noetrium_platform.capabilities.participant.method.runtime import (
    DefaultMethodEndpointFactory as _DefaultMethodEndpointFactory,
)
from noetrium.contracts.systems.runtime__process import (
    LocalCommandResult,
    LocalCommandStartError,
    LocalCommandTimeoutError,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.lifecycle.host.providers import LocalOperatingSystemRoute
from noetrium_platform.research.experimentation.checkpoint.api import (
    RunCheckpointStore,
    WorkloadCheckpointCoordinatorPort,
    WorkloadCheckpointPublicationPort,
    WorkloadCheckpointedBatchExecutorPort,
)
from noetrium_platform.research.experimentation.checkpoint.composition import (
    build_checkpointed_workload_batch_executor as _build_checkpointed_workload_batch_executor,
    build_project_run_checkpoint_store as _build_project_run_checkpoint_store,
)
from noetrium_platform.research.experimentation.run.api import (
    RunArtifactKind,
    RunArtifactSnapshotReceipt,
    RunArtifactStorePort,
    RunArtifactVerificationPort,
    RunArtifactWriteActorPort,
)
from noetrium_platform.research.experimentation.run.composition.artifacts import (
    build_directory_run_artifact_store as _build_directory_run_artifact_store,
)
from noetrium_platform.research.experimentation.run.control.api import (
    RunControlCheckpointStorePort,
    RunControlEvidencePort,
    RunControlLifecyclePort,
    RunControlPort,
    RunControlReconciliationPort,
)
from noetrium_platform.research.experimentation.run.control.composition.factory import (
    build_durable_run_control as _build_durable_run_control,
)
from noetrium_platform.research.experimentation.run.identity.api import RunIdentity
from noetrium_platform.research.experimentation.run.manifest.api import RunLaunchManifest
from noetrium_platform.research.experimentation.study.api import (
    BoundStudyUnitExecutionPort,
    ExperimentPlan,
    StudyAssignment,
    StudyAssignmentPort,
    StudyMatrixExecutionPort,
    StudyMatrixExecutionReport,
    StudyMetricAggregationPort,
    StudyProtocol,
    StudyUnitExecutionPort,
)
from noetrium_platform.research.experimentation.study.runtime import (
    BasicStudyMetricAggregator,
    DeterministicStudyAssignment,
    StudyMatrixExecutor,
)
from noetrium_platform.research.experimentation.workbench.api import (
    FigureRendererPort,
    ReportTableRendererPort,
    ResearchFigureFactoryPort,
    ResearchLifecyclePort,
    ResearchStatisticsPort,
    ResearchTablePipelinePort,
    TableReaderPort,
)
from noetrium_platform.research.experimentation.workbench.composition import (
    compose_standard_research_workbench,
)
from noetrium_platform.product.operator.runtime.run_control_application import (
    bind_run_control_application,
)


class DirectoryRunArtifactBinding:
    """Own a directory run-artifact store and its serial-write concurrency runtime."""

    def __init__(
        self,
        root: str | Path,
        *,
        run_id: str,
        queue_capacity: int | None = None,
        task_group_id: str | None = None,
    ) -> None:
        self._concurrency = build_concurrency_runtime()
        try:
            self._task_group = self._concurrency.open_task_group(
                task_group_id or f"run-artifacts-{uuid4().hex}"
            )
            self._store: RunArtifactStorePort = _build_directory_run_artifact_store(
                root,
                run_id=run_id,
                task_group=self._task_group,
                queue_capacity=queue_capacity,
            )
        except BaseException:
            self._concurrency.close()
            raise
        self._closed = False

    @property
    def store(self) -> RunArtifactStorePort:
        if self._closed:
            raise RuntimeError("directory run artifact binding is closed")
        return self._store

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._concurrency.close()

    def __enter__(self) -> "DirectoryRunArtifactBinding":
        if self._closed:
            raise RuntimeError("directory run artifact binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def bind_directory_run_artifact_store(
    root: str | Path,
    *,
    run_id: str,
    queue_capacity: int | None = None,
    task_group_id: str | None = None,
) -> DirectoryRunArtifactBinding:
    """Bind the default durable run-artifact store without exposing actor internals."""

    return DirectoryRunArtifactBinding(
        root,
        run_id=run_id,
        queue_capacity=queue_capacity,
        task_group_id=task_group_id,
    )


def build_project_run_checkpoint_store(project_state_root: str | Path) -> RunCheckpointStore:
    """Build the default durable project checkpoint store behind its public protocol."""

    return _build_project_run_checkpoint_store(project_state_root)


def build_checkpointed_workload_batch_executor(
    coordinator: WorkloadCheckpointCoordinatorPort,
    *,
    publication: WorkloadCheckpointPublicationPort | None = None,
) -> WorkloadCheckpointedBatchExecutorPort:
    """Compose checkpoint semantics with Noetrium's generic workload executor."""

    return _build_checkpointed_workload_batch_executor(
        coordinator, publication=publication
    )


def bind_durable_run_control(
    root: str | Path,
    *,
    identity: RunIdentity,
    manifest: RunLaunchManifest,
    writer_actor: RunArtifactWriteActorPort,
    lifecycle: RunControlLifecyclePort,
    checkpoint_store: RunControlCheckpointStorePort,
    reconciliation: RunControlReconciliationPort,
    evidence: RunControlEvidencePort,
    artifact_verifier: RunArtifactVerificationPort,
) -> RunControlPort:
    """Compose durable run control from explicit producer-owned public authorities."""

    return _build_durable_run_control(
        root,
        identity=identity,
        manifest=manifest,
        writer_actor=writer_actor,
        lifecycle=lifecycle,
        checkpoint_store=checkpoint_store,
        reconciliation=reconciliation,
        evidence=evidence,
        artifact_verifier=artifact_verifier,
    )


def bind_environment_category_catalog() -> EnvironmentCategoryCatalogPort:
    """Return Noetrium's registry-aligned environment category catalog."""

    return default_environment_category_catalog()


def bind_method_endpoint(
    implementation: MethodImplementation,
    runtime: MethodSessionRuntime,
) -> MethodEndpointPort:
    """Bind a downstream method through Noetrium's public product facade.

    Downstream projects must not import the platform's internal method runtime
    namespace merely to compose an implementation with its generic runtime.
    The concrete factory remains an upstream implementation detail.
    """

    if not isinstance(implementation, MethodImplementation):
        raise TypeError("method implementation must satisfy MethodImplementation")
    if not isinstance(runtime, MethodSessionRuntime):
        raise TypeError("method runtime must satisfy MethodSessionRuntime")
    return _DefaultMethodEndpointFactory().bind(implementation, runtime)


def run_local_shell_command(
    command: str,
    *,
    timeout_seconds: float = 300.0,
    cwd: str | Path | None = None,
) -> LocalCommandResult:
    """Execute one explicitly supplied host command behind the Noe facade.

    This is intended for project composition actions such as an externally
    managed assignment/world reset. The command remains deployment-owned; SEM
    does not own a process authority or call subprocess directly.
    """

    if type(command) is not str or not command.strip():
        raise ValueError("local shell command must be non-empty")
    if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
        raise ValueError("local shell command timeout must be finite and positive")
    try:
        completed = subprocess.run(
            command,
            shell=True,
            text=True,
            capture_output=True,
            timeout=float(timeout_seconds),
            cwd=str(cwd) if cwd is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalCommandTimeoutError(
            "local-shell-command", f"execution exceeded {float(timeout_seconds):g}s"
        ) from exc
    except OSError as exc:
        raise LocalCommandStartError(
            "local-shell-command", "could not start process"
        ) from exc
    return LocalCommandResult(
        argv=("/bin/sh", "-lc", command),
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


class StudyMatrixBinding:
    """Ready study-matrix execution bound to Noetrium structured concurrency."""

    def __init__(
        self,
        *,
        aggregation: StudyMetricAggregationPort | None = None,
        task_group_id: str | None = None,
    ) -> None:
        self._concurrency = build_concurrency_runtime()
        try:
            self._task_group = self._concurrency.open_task_group(
                task_group_id or f"study-matrix-{uuid4().hex}"
            )
            self._assignment: StudyAssignmentPort = DeterministicStudyAssignment()
            self._aggregation: StudyMetricAggregationPort = (
                aggregation if aggregation is not None else BasicStudyMetricAggregator()
            )
            self._executor: StudyMatrixExecutionPort = StudyMatrixExecutor(
                self._aggregation,
                assignment_expander=self._assignment,
                task_group=self._task_group,
            )
        except BaseException:
            self._concurrency.close()
            raise
        self._closed = False

    @property
    def assignments(self) -> StudyAssignmentPort:
        return self._assignment

    @property
    def aggregation(self) -> StudyMetricAggregationPort:
        return self._aggregation

    def execute(
        self,
        protocol: StudyProtocol,
        assignments: tuple[StudyAssignment, ...],
        adapter: StudyUnitExecutionPort,
    ) -> StudyMatrixExecutionReport:
        if self._closed:
            raise RuntimeError("study matrix binding is closed")
        return self._executor.execute(protocol, assignments, adapter)

    def execute_plan(
        self,
        plan: ExperimentPlan,
        assignments: tuple[StudyAssignment, ...],
        adapter: BoundStudyUnitExecutionPort,
    ) -> StudyMatrixExecutionReport:
        if self._closed:
            raise RuntimeError("study matrix binding is closed")
        return self._executor.execute_plan(plan, assignments, adapter)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self._concurrency.close()

    def __enter__(self) -> "StudyMatrixBinding":
        if self._closed:
            raise RuntimeError("study matrix binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def bind_study_matrix_execution(
    *,
    aggregation: StudyMetricAggregationPort | None = None,
    task_group_id: str | None = None,
) -> StudyMatrixBinding:
    return StudyMatrixBinding(aggregation=aggregation, task_group_id=task_group_id)


def build_deterministic_study_assignment() -> StudyAssignmentPort:
    return DeterministicStudyAssignment()


def build_basic_study_metric_aggregation() -> StudyMetricAggregationPort:
    return BasicStudyMetricAggregator()


class ResearchWorkbenchBinding:
    """Curated standard-library workbench with only public protocol-typed properties."""

    def __init__(self) -> None:
        self._assembly = compose_standard_research_workbench()

    @property
    def lifecycle(self) -> ResearchLifecyclePort:
        return self._assembly.lifecycle

    @property
    def pipeline(self) -> ResearchTablePipelinePort:
        return self._assembly.pipeline

    @property
    def statistics(self) -> ResearchStatisticsPort:
        return self._assembly.statistics

    @property
    def figures(self) -> ResearchFigureFactoryPort:
        return self._assembly.figures

    @property
    def csv_reader(self) -> TableReaderPort:
        return self._assembly.csv_reader

    @property
    def jsonl_reader(self) -> TableReaderPort:
        return self._assembly.jsonl_reader

    @property
    def table_renderer(self) -> ReportTableRendererPort:
        return self._assembly.table_renderer

    @property
    def figure_renderer(self) -> FigureRendererPort:
        return self._assembly.figure_renderer

    @property
    def svg_renderer(self) -> FigureRendererPort:
        return self._assembly.svg_renderer


def bind_research_workbench() -> ResearchWorkbenchBinding:
    """Build Noetrium's deterministic standard-library research workbench."""

    return ResearchWorkbenchBinding()


class MinecraftEnvironmentBinding:
    """Project-owned Minecraft provider binding over Noetrium runtime authorities."""

    def __init__(
        self,
        spec: MinecraftEnvironmentSpec,
        *,
        diagnostics: MinecraftDiagnosticsPort | None = None,
        checkpoint: MinecraftCheckpointPort | None = None,
        task_group_id: str | None = None,
    ) -> None:
        if not isinstance(spec, MinecraftEnvironmentSpec):
            raise TypeError("Minecraft environment binding requires MinecraftEnvironmentSpec")
        self._concurrency = build_concurrency_runtime()
        self._task_group = self._concurrency.open_task_group(
            task_group_id or f"project-minecraft-{uuid4().hex}"
        )
        try:
            self._assembly = compose_minecraft_environment(
                spec,
                operating_system=LocalOperatingSystemRoute(),
                diagnostics=diagnostics,
                checkpoint=checkpoint,
                task_group=self._task_group,
            )
        except BaseException:
            self._concurrency.close()
            raise
        self._sessions: list[EnvironmentSession] = []
        self._closed = False
        supported = [
            EnvironmentCapability.RECONCILE,
            EnvironmentCapability.DIAGNOSTICS,
            EnvironmentCapability.QUERY,
        ]
        if checkpoint is not None:
            supported.extend((EnvironmentCapability.SNAPSHOT, EnvironmentCapability.RESTORE))
        self._capabilities = EnvironmentProviderCapabilities(tuple(supported))

    @property
    def spec(self) -> MinecraftEnvironmentSpec:
        return self._assembly.implementation.spec

    @property
    def identity(self) -> EnvironmentIdentity:
        return self._assembly.implementation.identity

    @property
    def capabilities(self) -> EnvironmentProviderCapabilities:
        return self._capabilities

    def open_session(
        self,
        *,
        session_id: str,
        services: EnvironmentSessionServices,
    ) -> EnvironmentSession:
        if self._closed:
            raise RuntimeError("Minecraft environment binding is closed")
        session = self._assembly.runtime.open_session(
            self._assembly.implementation,
            session_id=session_id,
            services=services,
        )
        self._sessions.append(session)
        return session

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        for session in reversed(self._sessions):
            try:
                session.close()
            except BaseException as exc:
                errors.append(exc)
        try:
            self._concurrency.close()
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        if errors:
            raise ExceptionGroup("Minecraft environment binding close failed", errors)

    def __enter__(self) -> "MinecraftEnvironmentBinding":
        if self._closed:
            raise RuntimeError("Minecraft environment binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def bind_minecraft_environment(
    spec: MinecraftEnvironmentSpec,
    *,
    diagnostics: MinecraftDiagnosticsPort | None = None,
    checkpoint: MinecraftCheckpointPort | None = None,
    task_group_id: str | None = None,
) -> MinecraftEnvironmentBinding:
    """Bind an explicit Minecraft spec to Noetrium-owned local runtime authorities."""

    return MinecraftEnvironmentBinding(
        spec,
        diagnostics=diagnostics,
        checkpoint=checkpoint,
        task_group_id=task_group_id,
    )


def bind_bundled_minecraft_environment(
    *,
    host: str = "127.0.0.1",
    port: int = 25565,
    username: str = "ResearchBot",
    auth: str = "offline",
    version: str = "",
    node_executable: str | None = None,
    action_recovery_root: str | None = None,
    connect_timeout_s: float = 45.0,
    command_timeout_s: float = 45.0,
    diagnostics: MinecraftDiagnosticsPort | None = None,
    checkpoint: MinecraftCheckpointPort | None = None,
    task_group_id: str | None = None,
) -> MinecraftEnvironmentBinding:
    """Bind Noetrium's packaged Mineflayer bridge without exposing provider paths."""

    bridge_root = Path(
        str(
            resources.files("noetrium_platform.capabilities.environment.minecraft.providers")
            .joinpath("assets")
            .joinpath("mineflayer_bridge")
        )
    ).resolve()
    bridge_script = bridge_root / "bridge.js"
    if not bridge_script.is_file():
        raise RuntimeError("Noetrium bundled Minecraft bridge asset is unavailable")
    executable = node_executable or shutil.which("node")
    if not executable:
        raise RuntimeError("Node.js executable is required for the bundled Minecraft bridge")
    spec = MinecraftEnvironmentSpec(
        endpoint=MinecraftEndpointSpec(host=host, port=port),
        bridge=MinecraftBridgeSpec(
            command=(executable, str(bridge_script)),
            cwd=str(bridge_root),
            action_recovery_root=action_recovery_root,
            connect_timeout_s=connect_timeout_s,
            command_timeout_s=command_timeout_s,
        ),
        agent=MinecraftAgentSpec(username=username, auth=auth, version=version),
    )
    return bind_minecraft_environment(
        spec,
        diagnostics=diagnostics,
        checkpoint=checkpoint,
        task_group_id=task_group_id,
    )


class QualifiedProjectModelBinding:
    """Own one project-facing binding over a persisted qualified deployment closure."""

    def __init__(
        self,
        profile: ModelProviderProfile,
        *,
        closure_path: str | Path,
        request_root: str | Path,
        api_key: str = "",
        timeout_s: float | None = None,
        task_group_id: str | None = None,
    ) -> None:
        if not isinstance(profile, ModelProviderProfile):
            raise TypeError("profile must be ModelProviderProfile")
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be positive when provided")
        self._profile = profile
        self._concurrency = build_concurrency_runtime()
        self._admission = ModelAdmissionRegistry()
        try:
            self._task_group = self._concurrency.open_task_group(
                task_group_id or f"project-model-{uuid4().hex}"
            )
            closure = load_qualified_model_deployment_closure(
                closure_path,
                runtime_qualification_store_factory=DirectoryRuntimeQualificationEvidenceStore,
                runtime_canary_store_factory=DirectoryRuntimeCanaryEvidenceStore,
            )
            bindings = PersistedQualifiedModelEndpointBinding(closure)
            self._model_requests = build_directory_model_request_recorder(
                Path(request_root).expanduser().resolve(strict=False)
            )

            def endpoint_factory(binding):
                return build_openai_compatible_qualified_endpoint(
                    binding,
                    api_key=api_key,
                    timeout_s=timeout_s,
                    task_group=self._task_group,
                    admission_registry=self._admission,
                )

            self._provider: ProjectModelProviderPort = QualifiedModelProjectProvider(
                profile, bindings, endpoint_factory, self._model_requests
            )
        except BaseException:
            self._admission.close()
            self._concurrency.close()
            raise
        self._closed = False

    @property
    def profile(self) -> ModelProviderProfile:
        return self._profile

    @property
    def provider(self) -> ProjectModelProviderPort:
        return self._provider

    @property
    def model_requests(self) -> ModelRequestRecorderPort:
        return self._model_requests

    def bind(self, requirement: ModelCapabilityRequirement) -> ProjectModelClientPort:
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self._provider.bind(requirement)

    def diagnose(
        self, requirement: ModelCapabilityRequirement
    ) -> tuple[ModelBindingDiagnostic, ...]:
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self._provider.diagnose(requirement)

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        try:
            self._admission.close()
        except BaseException as exc:
            errors.append(exc)
        try:
            self._concurrency.close()
        except BaseException as exc:
            errors.append(exc)
        self._closed = True
        if errors:
            raise ExceptionGroup("qualified project model binding close failed", errors)

    def __enter__(self) -> "QualifiedProjectModelBinding":
        if self._closed:
            raise RuntimeError("qualified project model binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def bind_qualified_project_model(
    profile: ModelProviderProfile,
    *,
    closure_path: str | Path,
    request_root: str | Path,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group_id: str | None = None,
) -> QualifiedProjectModelBinding:
    """Bind a persisted qualified model deployment through Noetrium authorities."""

    return QualifiedProjectModelBinding(
        profile,
        closure_path=closure_path,
        request_root=request_root,
        api_key=api_key,
        timeout_s=timeout_s,
        task_group_id=task_group_id,
    )


__all__ = [
    "DirectoryRunArtifactBinding",
    "MinecraftEnvironmentBinding",
    "QualifiedProjectModelBinding",
    "ResearchWorkbenchBinding",
    "StudyMatrixBinding",
    "ProjectTestStage", "ProjectTestStageReceipt", "ResearchAction",
    "ResearchApplicationPort", "ResearchFacade", "ResearchOperationFailure",
    "ResearchRequest", "ResearchResult", "bind_bundled_minecraft_environment",
    "bind_directory_run_artifact_store", "bind_durable_run_control",
    "bind_environment_category_catalog", "bind_minecraft_environment", "bind_qualified_project_model",
    "bind_method_endpoint", "run_local_shell_command",
    "bind_research_workbench", "bind_run_control_application",
    "bind_study_matrix_execution", "build_basic_study_metric_aggregation",
    "build_checkpointed_workload_batch_executor", "build_project_run_checkpoint_store",
    "build_deterministic_study_assignment",
]
