"""Single platform-level product composition owner for the public bindings."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import replace
from importlib import resources
import math
import os
from pathlib import Path
import shutil
import subprocess
import time
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
    ProjectModelBindingSet,
    ModelCapabilityRequirement,
    MultimodalRequest,
    MultimodalRequestCodecPort,
    ModelProviderProfile,
    ModelRequestTokenizationProviderPort,
    ProjectModelClientPort,
    ProjectModelProviderPort,
    ProjectModelRequest,
    ProjectModelResponse,
)
from noetrium_platform.capabilities.model.providers import QualifiedModelProjectProvider
from noetrium_platform.capabilities.model.request.api import ModelRequestRecorderPort
from noetrium_platform.evidence.artifact.content.api import ArtifactBlobStorePort
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
from noetrium_platform.capabilities.participant.method.api import (
    MethodEndpointPort,
    MethodImplementation,
    MethodSessionRuntime,
)
from noetrium_platform.capabilities.participant.method.runtime import (
    DefaultMethodEndpointFactory as _DefaultMethodEndpointFactory,
)
from noetrium_platform.capabilities.participant.agent.runtime import (
    AgentObservationPartSourcePort,
    MultimodalAgentObservationPort,
)
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonInput,
    JsonObject,
    DirectoryMachineJournal,
    MachineJournalPort,
    MachineSnapshotStorePort,
)
from noetrium_platform.infrastructure.lifecycle.process.api import (
    LocalCommandResult,
    LocalCommandStartError,
    LocalCommandTimeoutError,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodCheckpointStorePort,
    MethodMachinePort,
    MethodProgram,
    MethodRunResult,
    MethodRuntimeContext,
)
from noetrium_platform.foundation.kernel.concurrency.api import ConcurrencyBudget
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.research.execution.admission.api import AdmissionBudget
from noetrium_platform.research.execution.scheduling.api import ExecutionPriority
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.composition.research_campaign import ResearchCampaignBinding
from noetrium_platform.research.experimentation.api.campaign import (
    ResearchCampaignPlan,
    ResearchCampaignStudyBinding,
)
from noetrium_platform.research.experimentation.checkpoint.api import RunCheckpointStore
from noetrium_platform.research.experimentation.checkpoint.composition import (
    build_project_run_checkpoint_store as _build_project_run_checkpoint_store,
)
from noetrium_platform.research.experimentation.run.api import (
    RunArtifactKind,
    RunArtifactSnapshotReceipt,
    RunArtifactStorePort,
    RunArtifactVerificationPort,
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
from noetrium_platform.research.experimentation.experiment.api import ExperimentDefinition
from noetrium_platform.research.experimentation.resource.api import (
    ComputeDemand,
    ResourceAllocationLeasePort,
    ResourceAllocationReceipt,
    ResourcePolicy,
)
from noetrium_platform.research.experimentation.resource.composition import (
    build_experiment_resource_binder as _build_experiment_resource_binder,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeLeasePolicy,
    ComputeSchedulerPort,
    DEFAULT_COMPUTE_LEASE_POLICY,
)
from noetrium_platform.foundation.scope.api import ScopeIdentity
from noetrium_platform.research.experimentation.run.manifest.api import RunLaunchManifest
from noetrium_platform.research.experimentation.study.api import (
    BoundStudyExecutionPort,
    ExperimentPlan,
    StudyAssignmentPort,
    StudyMatrixExecutionReport,
    StudyMetricAggregationPort,
)
from noetrium_platform.research.experimentation.study.runtime import (
    BasicStudyMetricAggregator,
    DeterministicStudyAssignment,
)
from noetrium_platform.research.experimentation.api.program import (
    ExperimentProgramBinding,
    compile_experiment_program,
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
from noetrium_platform.infrastructure.lifecycle.host.composition.authorities import (
    local_operating_system_route,
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


def build_directory_machine_journal(
    root: str | Path,
) -> MachineJournalPort:
    """Build the standard crash-durable journal for universal research Machines."""

    return DirectoryMachineJournal(Path(root))


def build_project_run_checkpoint_store(project_state_root: str | Path) -> RunCheckpointStore:
    """Build the default durable project checkpoint store behind its public protocol."""

    return _build_project_run_checkpoint_store(project_state_root)


def bind_experiment_resources(
    definition: ExperimentDefinition,
    policy: ResourcePolicy,
    *,
    allocation_id: str,
    owner_scope: ScopeIdentity,
    placement_scope: ScopeIdentity | None = None,
    compute_scheduler: ComputeSchedulerPort | None = None,
    execution_pool: ResearchExecutionPool | None = None,
    compute_lease_policy: ComputeLeasePolicy = DEFAULT_COMPUTE_LEASE_POLICY,
) -> ResourceAllocationLeasePort:
    """Resolve a frozen resource policy through leased shared compute authority."""

    if not isinstance(definition, ExperimentDefinition):
        raise TypeError("resource binding requires ExperimentDefinition")
    if not isinstance(policy, ResourcePolicy):
        raise TypeError("resource binding requires ResourcePolicy")
    if definition.resource_policy_digest != policy.policy_digest:
        raise ValueError("experiment resource policy digest does not match frozen definition")
    guard_factory = None
    if policy.compute is not None:
        if compute_scheduler is None:
            raise RuntimeError("compute resource policy requires a compute scheduler")
        if execution_pool is None:
            raise RuntimeError(
                "compute resource policy requires a shared ResearchExecutionPool "
                "for structured lease renewal"
            )
        guard_factory = execution_pool.compute_lease_guard_factory(
            compute_scheduler, policy=compute_lease_policy
        )
    return _build_experiment_resource_binder(compute_scheduler, guard_factory).bind(
        definition,
        policy,
        allocation_id=allocation_id,
        owner_scope=owner_scope,
        placement_scope=placement_scope,
    )


def bind_durable_run_control(
    *,
    identity: RunIdentity,
    manifest: RunLaunchManifest,
    run_machine_journal: MachineJournalPort,
    lifecycle: RunControlLifecyclePort,
    checkpoint_store: RunControlCheckpointStorePort,
    reconciliation: RunControlReconciliationPort,
    evidence: RunControlEvidencePort,
    artifact_verifier: RunArtifactVerificationPort,
    run_machine_snapshot_store: MachineSnapshotStorePort | None = None,
) -> RunControlPort:
    """Bind operator control to the shared authoritative RunMachine journal."""

    return _build_durable_run_control(
        identity=identity,
        manifest=manifest,
        run_machine_journal=run_machine_journal,
        lifecycle=lifecycle,
        checkpoint_store=checkpoint_store,
        reconciliation=reconciliation,
        evidence=evidence,
        artifact_verifier=artifact_verifier,
        run_machine_snapshot_store=run_machine_snapshot_store,
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


def _host_shell_argv(command: str) -> tuple[str, ...]:
    if os.name == "nt":
        return (os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c", command)
    return ("/bin/sh", "-c", command)


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
    argv = _host_shell_argv(command)
    try:
        completed = subprocess.run(
            argv,
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
        argv=argv,
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


def run_local_command(
    argv: tuple[str, ...],
    *,
    timeout_seconds: float = 300.0,
    cwd: str | Path | None = None,
    environment: Mapping[str, str] | None = None,
) -> LocalCommandResult:
    """Execute an exact argv vector without shell interpretation."""

    if not isinstance(argv, tuple) or not argv or any(
        type(arg) is not str or not arg or "\x00" in arg for arg in argv
    ):
        raise ValueError("local command argv must be a non-empty tuple of safe strings")
    if not math.isfinite(float(timeout_seconds)) or timeout_seconds <= 0:
        raise ValueError("local command timeout must be finite and positive")
    if environment is not None and any(
        type(key) is not str or not key or "\x00" in key or type(value) is not str or "\x00" in value
        for key, value in environment.items()
    ):
        raise ValueError("local command environment must contain safe string pairs")
    try:
        completed = subprocess.run(
            list(argv),
            shell=False,
            text=True,
            capture_output=True,
            timeout=float(timeout_seconds),
            cwd=str(cwd) if cwd is not None else None,
            env=dict(environment) if environment is not None else None,
        )
    except subprocess.TimeoutExpired as exc:
        raise LocalCommandTimeoutError(
            "local-command", f"execution exceeded {float(timeout_seconds):g}s"
        ) from exc
    except OSError as exc:
        raise LocalCommandStartError("local-command", "could not start process") from exc
    return LocalCommandResult(
        argv=argv,
        returncode=int(completed.returncode),
        stdout=completed.stdout or "",
        stderr=completed.stderr or "",
    )


class ExperimentBinding:
    """ExperimentProgram execution over a resource-shared research pool."""

    def __init__(
        self,
        *,
        aggregation: StudyMetricAggregationPort | None = None,
        task_group_id: str | None = None,
        execution_pool: ResearchExecutionPool | None = None,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
    ) -> None:
        if tenant_id is not None and (
            not isinstance(tenant_id, str) or not tenant_id.strip()
        ):
            raise ValueError("experiment tenant_id must be non-empty when provided")
        if not isinstance(priority, ExecutionPriority):
            raise TypeError("experiment priority must be ExecutionPriority")
        self._pool = execution_pool or ResearchExecutionPool()
        self._owns_pool = execution_pool is None
        self._tenant_id = tenant_id
        self._priority = priority
        self._task_group_id = task_group_id
        self._task_group = None
        self._study_id: str | None = None
        self._aggregation: StudyMetricAggregationPort = (
            aggregation if aggregation is not None else BasicStudyMetricAggregator()
        )
        self._closed = False

    def _task_group_for(self, study_id: str):
        if self._closed:
            raise RuntimeError("experiment binding is closed")
        if type(study_id) is not str or not study_id.strip():
            raise ValueError("experiment study_id must be non-empty")
        if self._task_group is not None:
            if self._study_id != study_id:
                raise ValueError(
                    "one experiment binding cannot mix study identities; "
                    f"bound={self._study_id!r} requested={study_id!r}"
                )
            return self._task_group
        self._study_id = study_id
        group_id = self._task_group_id or f"experiment:{study_id}:{uuid4().hex}"
        self._task_group = self._pool.open_experiment_group(
            group_id,
            tenant_id=self._tenant_id,
            resource_id=f"study:{study_id}",
            priority=self._priority,
        )
        return self._task_group

    @property
    def aggregation(self) -> StudyMetricAggregationPort:
        return self._aggregation

    def execute(
        self,
        plan: ExperimentPlan,
        adapter: BoundStudyExecutionPort,
    ) -> StudyMatrixExecutionReport:
        if type(plan) is not ExperimentPlan:
            raise TypeError("experiment execution requires ExperimentPlan")
        if not isinstance(adapter, BoundStudyExecutionPort):
            raise TypeError("experiment execution requires BoundStudyExecutionPort")
        group = self._task_group_for(plan.protocol.study_id)
        return ExperimentProgramBinding(
            compile_experiment_program(plan),
            adapter,
            self._aggregation,
            task_group=group,
        ).execute(
            machine_id=f"experiment:{plan.protocol.study_id}:{plan.plan_digest[:16]}"
        )

    def close(self) -> None:
        if self._closed:
            return
        errors: list[BaseException] = []
        if self._task_group is not None:
            try:
                self._pool.close_experiment_group(self._task_group)
            except BaseException as exc:
                errors.append(exc)
        if self._owns_pool:
            try:
                self._pool.close()
            except BaseException as exc:
                errors.append(exc)
        self._closed = True
        if errors:
            raise ExceptionGroup("experiment binding close failed", errors)

    def __enter__(self) -> "ExperimentBinding":
        if self._closed:
            raise RuntimeError("experiment binding is closed")
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.close()


def bind_research_execution_pool(
    *,
    orchestration_concurrency_budget: ConcurrencyBudget | None = None,
    orchestration_admission_budget: AdmissionBudget | None = None,
    experiment_concurrency_budget: ConcurrencyBudget | None = None,
    experiment_admission_budget: AdmissionBudget | None = None,
    model_io_concurrency_budget: ConcurrencyBudget | None = None,
    model_io_admission_budget: AdmissionBudget | None = None,
    priority_aging_seconds: float = 1.0,
) -> ResearchExecutionPool:
    """Build one pool for orchestration -> study execution -> model-I/O nesting."""

    return ResearchExecutionPool(
        orchestration_concurrency_budget=orchestration_concurrency_budget,
        orchestration_admission_budget=orchestration_admission_budget,
        experiment_concurrency_budget=experiment_concurrency_budget,
        experiment_admission_budget=experiment_admission_budget,
        model_io_concurrency_budget=model_io_concurrency_budget,
        model_io_admission_budget=model_io_admission_budget,
        priority_aging_seconds=priority_aging_seconds,
    )


def bind_experiment_execution(
    *,
    aggregation: StudyMetricAggregationPort | None = None,
    task_group_id: str | None = None,
    execution_pool: ResearchExecutionPool | None = None,
    tenant_id: str | None = None,
    priority: ExecutionPriority = ExecutionPriority.NORMAL,
) -> ExperimentBinding:
    return ExperimentBinding(
        aggregation=aggregation,
        task_group_id=task_group_id,
        execution_pool=execution_pool,
        tenant_id=tenant_id,
        priority=priority,
    )


def bind_research_campaign(
    plan: ResearchCampaignPlan,
    bindings: tuple[ResearchCampaignStudyBinding, ...],
    *,
    execution_pool: ResearchExecutionPool | None = None,
    tenant_id: str | None = None,
    priority: ExecutionPriority = ExecutionPriority.NORMAL,
    task_group_id: str | None = None,
) -> ResearchCampaignBinding:
    """Bind independent frozen studies for failure-isolated parallel execution."""

    return ResearchCampaignBinding(
        plan,
        bindings,
        execution_pool=execution_pool,
        tenant_id=tenant_id,
        priority=priority,
        task_group_id=task_group_id,
    )


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
                operating_system=local_operating_system_route(),
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

    configured_bridge_root = os.environ.get("MC_BRIDGE_DIR", "").strip()
    if configured_bridge_root:
        bridge_root = Path(configured_bridge_root).expanduser().resolve()
    else:
        bridge_root = Path(
            str(
                resources.files("noetrium_platform.capabilities.environment.minecraft.providers")
                .joinpath("assets")
                .joinpath("mineflayer_bridge")
            )
        ).resolve()
    bridge_script = bridge_root / "bridge.js"
    if not bridge_script.is_file():
        raise RuntimeError(f"Noetrium Minecraft bridge asset is unavailable: bridge_root={bridge_root}")
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
    """Project model binding over shared model-I/O and admission authorities."""

    def __init__(
        self,
        profile: ModelProviderProfile,
        *,
        closure_path: str | Path,
        request_root: str | Path,
        tokenization_provider: ModelRequestTokenizationProviderPort,
        api_key: str = "",
        timeout_s: float | None = None,
        task_group_id: str | None = None,
        execution_pool: ResearchExecutionPool | None = None,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
    ) -> None:
        if not isinstance(profile, ModelProviderProfile):
            raise TypeError("profile must be ModelProviderProfile")
        if timeout_s is not None and timeout_s <= 0:
            raise ValueError("timeout_s must be positive when provided")
        if tenant_id is not None and (not isinstance(tenant_id, str) or not tenant_id.strip()):
            raise ValueError("project model tenant_id must be non-empty when provided")
        if not isinstance(priority, ExecutionPriority):
            raise TypeError("project model priority must be ExecutionPriority")
        self._profile = profile
        self._pool = execution_pool or ResearchExecutionPool()
        self._owns_pool = execution_pool is None
        self._task_group = None
        self._admission = self._pool.model_admission
        try:
            self._task_group = self._pool.open_model_io_group(
                task_group_id or f"project-model-{uuid4().hex}",
                tenant_id=tenant_id,
                priority=priority,
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
                profile,
                bindings,
                endpoint_factory,
                self._model_requests,
                tokenization_provider,
            )
        except BaseException:
            if self._task_group is not None:
                try:
                    self._pool.close_model_io_group(self._task_group)
                except BaseException:
                    pass
            if self._owns_pool:
                self._pool.close()
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
        if self._task_group is not None:
            try:
                self._pool.close_model_io_group(self._task_group)
            except BaseException as exc:
                errors.append(exc)
        if self._owns_pool:
            try:
                self._pool.close()
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
    tokenization_provider: ModelRequestTokenizationProviderPort,
    api_key: str = "",
    timeout_s: float | None = None,
    task_group_id: str | None = None,
    execution_pool: ResearchExecutionPool | None = None,
    tenant_id: str | None = None,
    priority: ExecutionPriority = ExecutionPriority.NORMAL,
) -> QualifiedProjectModelBinding:
    """Bind a qualified deployment, optionally sharing cross-study resources."""

    return QualifiedProjectModelBinding(
        profile,
        closure_path=closure_path,
        request_root=request_root,
        tokenization_provider=tokenization_provider,
        api_key=api_key,
        timeout_s=timeout_s,
        task_group_id=task_group_id,
        execution_pool=execution_pool,
        tenant_id=tenant_id,
        priority=priority,
    )


def complete_project_model(
    client: ProjectModelClientPort,
    recorder: ModelRequestRecorderPort,
    *,
    request_id: str,
    context: ExecutionContext,
    request_body: Mapping[str, JsonInput],
    compiled_prompt_text: str | None = None,
    tool_schema_bundle: JsonInput | None = None,
    source_artifact_refs: tuple[str, ...] = (),
    source_state_refs: tuple[str, ...] = (),
    binding_set: ProjectModelBindingSet | None = None,
    selection_attempt_index: int = 1,
    selection_reason_code: str = "primary",
    previous_selection_receipt_digest: str | None = None,
    selection_evidence_refs: tuple[str, ...] = (),
) -> ProjectModelResponse:
    """Record and execute one qualified project-model generation request.

    The request body remains method/provider-owned. Noetrium owns request
    identity, provenance recording, endpoint invocation, and response fencing.
    """

    if not isinstance(client, ProjectModelClientPort):
        raise TypeError("project model client must satisfy ProjectModelClientPort")
    if not isinstance(recorder, ModelRequestRecorderPort):
        raise TypeError("project model recorder must satisfy ModelRequestRecorderPort")
    if not isinstance(context, ExecutionContext):
        raise TypeError("project model request context must be an ExecutionContext")
    if not isinstance(request_body, Mapping):
        raise TypeError("project model request body must be a mapping")
    binding = client.binding
    prompt_fields = (
        binding.prompt_generation_id,
        binding.prompt_id,
        binding.prompt_digest,
    )
    if any(value is None for value in prompt_fields):
        raise ValueError(
            "complete_project_model requires a generation binding with prompt provenance"
        )
    envelope = recorder.record(
        request_id=request_id,
        context=context,
        role=binding.role,
        model=binding.model,
        prompt_generation_id=binding.prompt_generation_id,
        prompt_id=binding.prompt_id,
        prompt_digest=binding.prompt_digest,
        request_body=request_body,
        compiled_prompt_text=compiled_prompt_text,
        tool_schema_bundle=tool_schema_bundle,
        source_artifact_refs=source_artifact_refs,
        source_state_refs=source_state_refs,
    )
    request = ProjectModelRequest(
        requirement_digest=binding.requirement_digest,
        envelope=envelope,
        body=request_body,
    )
    response = client.complete(request)
    if response.request_digest != request.request_digest:
        raise RuntimeError("project model response request provenance drift")
    if response.binding_digest != binding.digest():
        raise RuntimeError("project model response binding provenance drift")
    if binding_set is None:
        if (
            selection_attempt_index != 1
            or selection_reason_code != "primary"
            or previous_selection_receipt_digest is not None
            or selection_evidence_refs
        ):
            raise ValueError(
                "model selection metadata requires an explicit frozen binding_set"
            )
        return response
    if binding_set.requirement_digest != binding.requirement_digest:
        raise ValueError("model binding set requirement does not match selected client")
    receipt = binding_set.selection_receipt(
        request_digest=request.request_digest,
        binding=binding,
        attempt_index=selection_attempt_index,
        reason_code=selection_reason_code,
        previous_selection_receipt_digest=previous_selection_receipt_digest,
        evidence_refs=selection_evidence_refs,
    )
    return replace(response, selection_receipt=receipt)


def bind_universal_method_machine(
    *,
    checkpoint_store: MethodCheckpointStorePort | None = None,
    max_steps: int = 10_000,
    checkpoint_interval: int = 1,
    max_seconds: float | None = None,
    clock: Callable[[], float] | None = None,
) -> MethodMachinePort:
    """Bind the platform-owned universal method runtime.

    Downstream methods receive only the public ``MethodMachinePort``. The
    concrete loop, operation routing, checkpoint semantics, and timeout policy
    remain platform-owned and are intentionally not imported by projects.
    """

    from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine

    machine_kwargs = {
        "checkpoint_store": checkpoint_store,
        "max_steps": max_steps,
        "checkpoint_interval": checkpoint_interval,
        "max_seconds": max_seconds,
    }
    if clock is not None:
        machine_kwargs["clock"] = clock
    return UniversalMethodMachine(**machine_kwargs)


def bind_method_checkpoint_store(root: str | Path) -> MethodCheckpointStorePort:
    """Bind the platform-owned crash-durable method checkpoint provider.

    Downstream methods can request durable checkpointing without importing a
    provider implementation from ``noetrium_platform``.  The returned port is
    compatible with :func:`bind_universal_method_machine` and preserves the
    platform's checkpoint digest and monotonicity rules.
    """

    from noetrium_platform.research.execution.workflow.providers import JsonMethodCheckpointStore

    return JsonMethodCheckpointStore(root)


def run_method_program(
    program: MethodProgram,
    *,
    runtime: MethodRuntimeContext,
    input_value: object = None,
    initial_state: JsonObject | None = None,
    resume: bool = False,
    machine: MethodMachinePort | None = None,
    state_root: str | Path | None = None,
) -> MethodRunResult:
    """Execute a MethodProgram through the Machine-backed universal host.

    Downstream code does not construct MachineExecutor. Supplying ``state_root``
    enables crash-durable journal/snapshot recovery; otherwise execution uses an
    embedded process-local Machine authority.
    """
    from noetrium_platform.research.execution.workflow.composition import bind_machine_method_runtime

    if runtime.transitions is None:
        if resume and state_root is None:
            raise ValueError("durable method resume requires state_root or a pre-bound transition authority")
        runtime = bind_machine_method_runtime(program, runtime, state_root=state_root)
    bound = machine or bind_universal_method_machine()
    return bound.run(program, runtime=runtime, input_value=input_value, initial_state=initial_state, resume=resume)


async def run_method_program_async(
    program: MethodProgram,
    *,
    runtime: MethodRuntimeContext,
    input_value: object = None,
    initial_state: JsonObject | None = None,
    resume: bool = False,
    machine: MethodMachinePort | None = None,
    state_root: str | Path | None = None,
) -> MethodRunResult:
    """Async Machine-backed sibling of :func:`run_method_program`."""
    from noetrium_platform.research.execution.workflow.composition import bind_machine_method_runtime

    if runtime.transitions is None:
        if resume and state_root is None:
            raise ValueError("durable method resume requires state_root or a pre-bound transition authority")
        runtime = bind_machine_method_runtime(program, runtime, state_root=state_root)
    bound = machine or bind_universal_method_machine()
    return await bound.run_async(program, runtime=runtime, input_value=input_value, initial_state=initial_state, resume=resume)


def invoke_multimodal_model(
    client: ProjectModelClientPort,
    recorder: ModelRequestRecorderPort,
    codec: MultimodalRequestCodecPort,
    content_store: ArtifactBlobStorePort,
    *,
    request_id: str,
    context: ExecutionContext,
    request: MultimodalRequest,
) -> ProjectModelResponse:
    """Invoke an arbitrary multimodal method through a provider-owned codec.

    Modality interpretation, serialization, and response decoding stay outside
    Noetrium. The platform only preserves typed request provenance and the
    content references used by the method.
    """

    if not isinstance(codec, MultimodalRequestCodecPort):
        raise TypeError("multimodal codec must satisfy MultimodalRequestCodecPort")
    if not isinstance(content_store, ArtifactBlobStorePort):
        raise TypeError("multimodal content store must satisfy ArtifactBlobStorePort")
    if not isinstance(request, MultimodalRequest):
        raise TypeError("multimodal request must be MultimodalRequest")
    body = codec.encode(request, content_store)
    if not isinstance(body, Mapping):
        raise TypeError("multimodal codec must return a mapping")
    source_refs = tuple(part.content.content_sha256 for part in request.parts)
    return complete_project_model(
        client,
        recorder,
        request_id=request_id,
        context=context,
        request_body=body,
        compiled_prompt_text=request.instruction,
        source_artifact_refs=source_refs,
    )




__all__ = [
    "AgentObservationPartSourcePort",
    "MultimodalAgentObservationPort",
    "ComputeDemand",
    "DirectoryRunArtifactBinding",
    "MinecraftEnvironmentBinding",
    "QualifiedProjectModelBinding",
    "ResearchCampaignBinding",
    "ResearchCampaignPlan",
    "ResearchCampaignStudyBinding",
    "ResearchWorkbenchBinding",
    "ResourceAllocationReceipt",
    "ResourcePolicy",
    "ExperimentBinding",
    "ProjectTestStage", "ProjectTestStageReceipt", "ResearchAction",
    "ResearchApplicationPort", "ResearchFacade", "ResearchOperationFailure",
    "ResearchRequest", "ResearchResult", "bind_bundled_minecraft_environment",
    "bind_directory_run_artifact_store", "bind_durable_run_control",
    "bind_experiment_resources",
    "bind_environment_category_catalog", "bind_minecraft_environment", "bind_qualified_project_model",
    "complete_project_model", "invoke_multimodal_model",
    "bind_universal_method_machine", "bind_method_checkpoint_store", "run_method_program", "run_method_program_async",
    "bind_method_endpoint", "run_local_command", "run_local_shell_command",
    "bind_research_campaign", "bind_research_execution_pool", "bind_research_workbench", "bind_run_control_application",
    "bind_experiment_execution", "build_basic_study_metric_aggregation",
    "build_project_run_checkpoint_store",
    "build_deterministic_study_assignment",
]
