from __future__ import annotations

from threading import Lock
from uuid import uuid4

from noetrium_platform.capabilities.model.serving.api import ModelAdmissionRegistryPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AdaptiveModelEndpointPoolPort,
    ModelEndpointReplicaSet,
    ModelJsonHttpClientPort,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_adaptive_model_endpoint_pool,
)
from noetrium_platform.capabilities.model.serving.runtime import ModelAdmissionRegistry
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PooledModelHttpTransport,
    PooledModelHttpTransportOwner,
    StructuredModelJsonHttpClient,
)
from noetrium_platform.infrastructure.resources.container.api import (
    DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
    DockerContainerLeasePolicy,
)
from noetrium_platform.infrastructure.resources.container.runtime import DockerContainerLeaseAuthority
from noetrium_platform.composition.environment_instance_leases import (
    DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
    EnvironmentInstanceLeaseAuthority,
    EnvironmentInstanceLeasePolicy,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    ComputeLeaseGuardFactoryPort,
    ComputeLeasePolicy,
    ComputeSchedulerPort,
    DEFAULT_COMPUTE_LEASE_POLICY,
    HostRuntimeObserverPort,
)
from noetrium_platform.infrastructure.resources.compute.providers import (
    LocalHostRuntimeObserver,
)
from noetrium_platform.infrastructure.resources.allocation.api import (
    DEFAULT_ENDPOINT_LEASE_POLICY,
    EndpointAllocationPort,
    EndpointLeaseGuardFactoryPort,
    EndpointLeasePolicy,
)
from noetrium_platform.infrastructure.resources.lease.api import (
    DEFAULT_RESOURCE_LEASE_POLICY,
    ResourceLease,
    ResourceLeasePolicy,
    ResourceLeasePort,
)
from noetrium_platform.infrastructure.resources.lease.runtime import LeaseHeartbeatFactory
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    Deadline,
    TaskFailurePolicy,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_cpu_worker_pool_provider,
)
from noetrium_platform.foundation.kernel.concurrency.api import SingleFlightCache
from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.research.execution.policy.api import ExecutionPriority

from .concurrency import build_execution_concurrency_runtime
from .shared_host_pressure import (
    ResourceCompetitionDemand,
    ResourceCompetitionPolicy,
    ResourceCompetitionReservationLedger,
    SharedNetworkPressureObserverPort,
    SharedStoragePressureObserverPort,
)


def _default_control_concurrency_budget() -> ConcurrencyBudget:
    """Keep lifecycle/recovery control isolated with a minimal CPU reserve."""

    return ConcurrencyBudget(
        max_blocking_io_workers=2,
        max_serial_workers=2,
        max_cpu_workers=1,
        max_blocking_io_in_flight=8,
        max_async_io_in_flight=16,
        max_cpu_in_flight=1,
        default_queue_capacity=256,
    )


def _default_experiment_concurrency_budget() -> ConcurrencyBudget:
    """Keep physical workers bounded while allowing experiment batches to queue."""

    base = ConcurrencyBudget()
    return ConcurrencyBudget(
        max_blocking_io_workers=base.max_blocking_io_workers,
        max_serial_workers=base.max_serial_workers,
        max_cpu_workers=base.max_cpu_workers,
        max_blocking_io_in_flight=base.default_queue_capacity,
        max_async_io_in_flight=base.max_async_io_in_flight,
        max_cpu_in_flight=base.max_cpu_in_flight,
        default_queue_capacity=base.default_queue_capacity,
        shutdown_timeout_seconds=base.shutdown_timeout_seconds,
    )


def _default_model_io_concurrency_budget() -> ConcurrencyBudget:
    """Size async model I/O from the process file-descriptor budget."""

    base = ConcurrencyBudget()
    async_limit = base.max_async_io_in_flight
    try:
        import resource

        soft_limit, _hard_limit = resource.getrlimit(resource.RLIMIT_NOFILE)
        if soft_limit == resource.RLIM_INFINITY:
            fd_budget = base.default_queue_capacity
        else:
            fd_budget = max(1, int(soft_limit) // 2)
        # Model HTTP sockets are the scarce physical resource here.  Do not
        # re-cap the FD-derived authority at the generic task-queue default;
        # that silently serialized capable inference servers at 256 requests.
        async_limit = max(async_limit, fd_budget)
    except (ImportError, OSError, ValueError):
        pass

    return ConcurrencyBudget(
        max_blocking_io_workers=base.max_blocking_io_workers,
        max_serial_workers=base.max_serial_workers,
        max_cpu_workers=base.max_cpu_workers,
        max_blocking_io_in_flight=base.max_blocking_io_in_flight,
        max_async_io_in_flight=async_limit,
        max_cpu_in_flight=base.max_cpu_in_flight,
        default_queue_capacity=max(
            base.default_queue_capacity,
            async_limit,
        ),
        shutdown_timeout_seconds=base.shutdown_timeout_seconds,
    )


def _shared_workload_cpu_budget(
    budgets: tuple[ConcurrencyBudget, ...],
) -> ConcurrencyBudget:
    if not budgets:
        raise ValueError("shared workload CPU budget requires logical domains")
    return ConcurrencyBudget(
        max_cpu_workers=max(item.max_cpu_workers for item in budgets),
        max_cpu_in_flight=max(int(item.max_cpu_in_flight) for item in budgets),
    )


class ResearchExecutionPool:
    """Shared execution authorities for nested concurrent research workloads.

    The dependency order is explicit:

        fleet -> orchestration -> experiment scheduling -> machine execution -> {model I/O, capability I/O}

    A synchronous parent may wait only on work in a downstream domain. Keeping
    the workload admission/concurrency domains independent prevents nested-admission
    deadlock while preserving one composition owner and bounded resources.
    Exact model-serving capacity is shared separately through one admission
    registry per deployment generation.
    """

    def __init__(
        self,
        *,
        fleet_concurrency_budget: ConcurrencyBudget | None = None,
        fleet_admission_budget: AdmissionBudget | None = None,
        orchestration_concurrency_budget: ConcurrencyBudget | None = None,
        orchestration_admission_budget: AdmissionBudget | None = None,
        control_concurrency_budget: ConcurrencyBudget | None = None,
        control_admission_budget: AdmissionBudget | None = None,
        experiment_concurrency_budget: ConcurrencyBudget | None = None,
        experiment_admission_budget: AdmissionBudget | None = None,
        machine_concurrency_budget: ConcurrencyBudget | None = None,
        machine_admission_budget: AdmissionBudget | None = None,
        capability_io_concurrency_budget: ConcurrencyBudget | None = None,
        capability_io_admission_budget: AdmissionBudget | None = None,
        model_io_concurrency_budget: ConcurrencyBudget | None = None,
        model_io_admission_budget: AdmissionBudget | None = None,
        model_admission_registry: ModelAdmissionRegistryPort | None = None,
        priority_aging_seconds: float = 1.0,
        host_runtime_observer: HostRuntimeObserverPort | None = None,
        storage_pressure_observer: SharedStoragePressureObserverPort | None = None,
        network_pressure_observer: SharedNetworkPressureObserverPort | None = None,
        resource_competition_policy: ResourceCompetitionPolicy | None = None,
        exclusive_owner_generation: bool = False,
    ) -> None:
        if type(exclusive_owner_generation) is not bool:
            raise TypeError("exclusive_owner_generation must be boolean")

        resolved_control_budget = (
            control_concurrency_budget or _default_control_concurrency_budget()
        )
        resolved_orchestration_budget = (
            orchestration_concurrency_budget or ConcurrencyBudget()
        )
        resolved_fleet_budget = (
            fleet_concurrency_budget or resolved_orchestration_budget
        )
        resolved_experiment_budget = (
            experiment_concurrency_budget or _default_experiment_concurrency_budget()
        )
        resolved_machine_budget = (
            machine_concurrency_budget or ConcurrencyBudget()
        )
        resolved_capability_io_budget = (
            capability_io_concurrency_budget or ConcurrencyBudget()
        )
        resolved_model_io_budget = (
            model_io_concurrency_budget
            or _default_model_io_concurrency_budget()
        )
        resolved_resource_competition_policy = (
            resource_competition_policy or ResourceCompetitionPolicy()
        )
        resolved_host_runtime_observer = (
            host_runtime_observer or LocalHostRuntimeObserver()
        )
        self._resource_competition_policy = resolved_resource_competition_policy
        shared_cpu_budget = _shared_workload_cpu_budget(
            (
                resolved_fleet_budget,
                resolved_orchestration_budget,
                resolved_experiment_budget,
                resolved_machine_budget,
                resolved_capability_io_budget,
                resolved_model_io_budget,
            )
        )

        self._control = build_execution_concurrency_runtime(
            concurrency_budget=resolved_control_budget,
            admission_budget=control_admission_budget,
            priority_aging_seconds=priority_aging_seconds,
            blocking_io_thread_name_prefix="research-control-io",
            timer_name="research-control-timer",
        )
        self._shared_workload_cpu = None
        self._shared_workload_cpu_closed = False
        self._resource_competition_reservations = (
            ResourceCompetitionReservationLedger()
        )
        try:
            self._shared_workload_cpu = build_cpu_worker_pool_provider(
                shared_cpu_budget
            )
            self._fleet = build_execution_concurrency_runtime(
                concurrency_budget=resolved_fleet_budget,
                admission_budget=fleet_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=resolved_host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-fleet-io",
                timer_name="research-fleet-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._orchestration = build_execution_concurrency_runtime(
                concurrency_budget=resolved_orchestration_budget,
                admission_budget=orchestration_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=resolved_host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-orchestration-io",
                timer_name="research-orchestration-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._experiments = build_execution_concurrency_runtime(
                concurrency_budget=resolved_experiment_budget,
                admission_budget=experiment_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=resolved_host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-experiment-io",
                timer_name="research-experiment-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._machines = build_execution_concurrency_runtime(
                concurrency_budget=resolved_machine_budget,
                admission_budget=machine_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=resolved_host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-machine-io",
                timer_name="research-machine-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._capability_io = build_execution_concurrency_runtime(
                concurrency_budget=resolved_capability_io_budget,
                admission_budget=capability_io_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=resolved_host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-capability-io",
                timer_name="research-capability-io-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._model_io = build_execution_concurrency_runtime(
                concurrency_budget=resolved_model_io_budget,
                admission_budget=model_io_admission_budget,
                priority_aging_seconds=priority_aging_seconds,
                host_runtime_observer=resolved_host_runtime_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-model-io",
                timer_name="research-model-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            if model_admission_registry is not None and (
                not callable(getattr(model_admission_registry, "controller_for", None))
                or not callable(getattr(model_admission_registry, "close", None))
            ):
                raise TypeError(
                    "model_admission_registry must satisfy ModelAdmissionRegistryPort"
                )
            self._model_admission: ModelAdmissionRegistryPort = (
                ModelAdmissionRegistry()
                if model_admission_registry is None
                else model_admission_registry
            )
            self._model_io_resource_lock = Lock()
            self._model_io_resources: list[object] = []
            self._model_io_resource_ids: set[int] = set()
            self._model_io_resources_closed = False
            self._model_lifecycle_resource_lock = Lock()
            self._model_lifecycle_resources: list[object] = []
            self._model_lifecycle_resource_ids: set[int] = set()
            self._model_lifecycle_resources_closed = False
            self._model_http_transport_lock = Lock()
            self._model_http_transport_owner: PooledModelHttpTransportOwner | None = None
            self._model_json_http_client_lock = Lock()
            self._model_json_http_client: ModelJsonHttpClientPort | None = None
            self._model_endpoint_pools: SingleFlightCache[
                AdaptiveModelEndpointPoolPort
            ] = SingleFlightCache()
            self._model_http_max_connections = max(
                1,
                resolved_model_io_budget.max_async_io_in_flight,
            )
            self._model_http_close_timeout_s = float(
                resolved_model_io_budget.shutdown_timeout_seconds
            )
        except BaseException as exc:
            errors: list[BaseException] = [exc]
            for name in ("_model_io", "_capability_io", "_machines", "_experiments", "_orchestration", "_fleet"):
                runtime = getattr(self, name, None)
                if runtime is None:
                    continue
                try:
                    runtime.close()
                except BaseException as cleanup_exc:
                    errors.append(cleanup_exc)
            if self._shared_workload_cpu is not None:
                try:
                    self._shared_workload_cpu.close(
                        wait=True,
                        cancel_pending=True,
                    )
                except BaseException as cleanup_exc:
                    errors.append(cleanup_exc)
            try:
                self._control.close()
            except BaseException as cleanup_exc:
                errors.append(cleanup_exc)
            if len(errors) == 1:
                raise
            raise BaseExceptionGroup(
                "research execution pool construction failed",
                errors,
            ) from exc
        self._workload_cpu_workers = shared_cpu_budget.max_cpu_workers
        self._experiment_frontier_capacity = int(
            resolved_experiment_budget.max_blocking_io_workers
        )
        # Mechanical submission window for one workload DAG. This is not a
        # scientific concurrency policy: admission/fairness/resource gates
        # remain authoritative. It prevents one ready set from pre-queuing
        # more blocking work than the Machine provider can execute at once.
        self._workload_frontier_capacity = int(
            resolved_machine_budget.max_blocking_io_workers
        )
        self._owner_generation_id = uuid4().hex
        self._exclusive_owner_generation = exclusive_owner_generation
        self._resource_lease_group: TaskGroupPort | None = None
        self._compute_lease_group: TaskGroupPort | None = None
        self._endpoint_lease_group: TaskGroupPort | None = None
        self._environment_lease_group: TaskGroupPort | None = None
        self._container_lease_group: TaskGroupPort | None = None
        self._workloads_quiescing = False
        self._workloads_quiesced = False
        self._closing = False
        self._closed = False

    def _require_workloads_open(self) -> None:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        if self._workloads_quiescing or self._workloads_quiesced:
            raise RuntimeError("research execution pool workloads are quiescing")

    @property
    def model_http_max_connections(self) -> int:
        """Maximum concurrent model HTTP requests owned by this execution pool."""
        return self._model_http_max_connections

    @property
    def resource_competition_policy(self) -> ResourceCompetitionPolicy:
        return self._resource_competition_policy

    @property
    def resource_competition_policy_digest(self) -> str:
        return canonical_digest(self._resource_competition_policy)

    @property
    def resource_competition_enabled(self) -> bool:
        """Whether all workload domains are bound to physical competition facts."""

        states = (
            self._orchestration.resource_competition is not None,
            self._experiments.resource_competition is not None,
            self._machines.resource_competition is not None,
            self._capability_io.resource_competition is not None,
            self._model_io.resource_competition is not None,
        )
        if len(set(states)) != 1:
            raise RuntimeError(
                "research execution pool resource competition wiring is split"
            )
        return states[0]

    @property
    def experiment_frontier_capacity(self) -> int:
        """Mechanical experiment frontier computed by the platform runtime."""

        return self._experiment_frontier_capacity

    @property
    def workload_cpu_workers(self) -> int:
        """Physical CPU workers shared by all workload execution domains."""

        return self._workload_cpu_workers

    @property
    def workload_frontier_capacity(self) -> int:
        return self._workload_frontier_capacity

    @property
    def owner_generation_id(self) -> str:
        """Process-generation fence shared by all schedulers in this pool."""

        return self._owner_generation_id

    @property
    def can_recover_abandoned_owner_generations(self) -> bool:
        """Whether composition proved this pool is the only live local generation."""

        return self._exclusive_owner_generation

    @property
    def model_admission(self) -> ModelAdmissionRegistryPort:
        self._require_workloads_open()
        return self._model_admission


    @property
    def model_http_transport(self) -> PooledModelHttpTransport:
        """Shared model HTTP/2 transport for this execution-pool generation.

        Scientific endpoint pools retain independent routing/provenance state.
        Only generic connection management is shared across exact model
        deployments so role/prompt differences do not duplicate TCP/HTTP2 pools.
        """
        self._require_workloads_open()
        with self._model_http_transport_lock:
            owner = self._model_http_transport_owner
            if owner is not None:
                return owner.transport

            # HTTPX async connection pools are event-loop owned.  Bind both
            # requests and transport teardown to the model-I/O runtime; workload
            # quiescence closes registered request resources before sealing this
            # domain, while physical model-service owners survive separately.
            group = self._model_io.open_task_group(
                f"research-model-http-transport:{self._owner_generation_id}",
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
            transport = PooledModelHttpTransport(
                max_connections=self._model_http_max_connections,
                max_keepalive_connections=self._model_http_max_connections,
            )
            owner = PooledModelHttpTransportOwner(
                transport,
                group,
                close_timeout_s=self._model_http_close_timeout_s,
            )
            try:
                # Register the shared transport before any pool borrowing it.
                # Resource shutdown is reverse-registration order, so endpoint
                # pools close first and the shared transport closes last.
                self.register_model_io_resource(owner)
            except BaseException:
                try:
                    owner.close()
                finally:
                    try:
                        group.close(cancel_pending=True)
                    except BaseException:
                        pass
                raise
            self._model_http_transport_owner = owner
            return owner.transport

    @property
    def model_json_http_client(self) -> ModelJsonHttpClientPort:
        """Shared synchronous bridge onto the execution pool HTTP/2 transport."""

        self._require_workloads_open()
        with self._model_json_http_client_lock:
            current = self._model_json_http_client
            if current is not None:
                return current
            transport = self.model_http_transport
            group = self.open_model_io_group(
                f"research-model-json-http:{self._owner_generation_id}",
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
            client = StructuredModelJsonHttpClient(transport, group)
            try:
                self.register_model_io_resource(client)
            except BaseException:
                try:
                    client.close()
                except BaseException:
                    pass
                raise
            self._model_json_http_client = client
            return client

    def model_endpoint_pool(
        self,
        replica_set: ModelEndpointReplicaSet,
        *,
        observers: tuple[object, ...] = (),
    ) -> AdaptiveModelEndpointPoolPort:
        """Reuse one physical dispatch runtime for one exact frozen replica set.

        Scientific identity remains in each request/binding. This cache owns
        only operational state: health, adaptive admission, retry history and
        prefix/KV locality. Observer identity participates in the key so
        lossless evidence capture is never silently changed by reuse.
        """

        self._require_workloads_open()
        if not isinstance(replica_set, ModelEndpointReplicaSet):
            raise TypeError(
                "research model endpoint pool requires ModelEndpointReplicaSet"
            )
        if type(observers) is not tuple:
            raise TypeError("research model endpoint observers must be a tuple")
        cache_key = canonical_digest(
            {
                "schema": "research-model-endpoint-pool-cache.v1",
                "replica_set_digest": replica_set.replica_set_digest,
                "observer_runtime_ids": tuple(id(observer) for observer in observers),
            }
        )

        def build() -> AdaptiveModelEndpointPoolPort:
            group = self.open_model_io_group(
                "research-model-endpoint-pool:"
                + cache_key[:24],
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
            pool = None
            try:
                pool = build_adaptive_model_endpoint_pool(
                    replica_set,
                    task_group=group,
                    admission_registry=self._model_admission,
                    observers=observers,
                    transport=self.model_http_transport,
                )
                self.register_model_io_resource(pool)
                return pool
            except BaseException:
                if pool is not None:
                    try:
                        pool.close()
                    except BaseException:
                        pass
                try:
                    self.close_model_io_group(
                        group,
                        cancel_pending=True,
                    )
                except BaseException:
                    pass
                raise

        return self._model_endpoint_pools.get_or_create(cache_key, build)

    def open_orchestration_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_queue_wait_timeout_seconds: float | None = None,
        resource_demand: ResourceCompetitionDemand | None = None,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self._orchestration.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            resource_demand=resource_demand,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    @property
    def control_heartbeats(self):
        """Maintenance heartbeat scheduler isolated from workload admission."""
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self._control.heartbeats

    def open_fleet_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_queue_wait_timeout_seconds: float | None = None,
        resource_demand: ResourceCompetitionDemand | None = None,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        self._require_workloads_open()
        return self._fleet.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            resource_demand=resource_demand,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def open_control_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.CRITICAL,
        admission_queue_wait_timeout_seconds: float | None = None,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        """Open control-plane work that must not be starved by workload capacity."""
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self._control.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def open_experiment_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_queue_wait_timeout_seconds: float | None = None,
        resource_demand: ResourceCompetitionDemand | None = None,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        self._require_workloads_open()
        return self._experiments.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            resource_demand=resource_demand,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def open_machine_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_queue_wait_timeout_seconds: float | None = None,
        resource_demand: ResourceCompetitionDemand | None = None,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        """Open generic Research Machine work below experiment scheduling.

        This domain is physically independent from the experiment scheduler so a
        synchronous experiment task may wait on child Machine execution without
        occupying the workers needed by those children.
        """
        self._require_workloads_open()
        return self._machines.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            resource_demand=resource_demand,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def resource_lease_guard_factory(
        self,
        leases: ResourceLeasePort,
        *,
        policy: ResourceLeasePolicy = DEFAULT_RESOURCE_LEASE_POLICY,
        lane_capacity: int | None = None,
    ) -> LeaseHeartbeatFactory:
        """Bind generic durable resource leases to the universal heartbeat machine."""
        self._require_workloads_open()
        if not isinstance(policy, ResourceLeasePolicy):
            raise TypeError("generic resource lease heartbeat requires ResourceLeasePolicy")

        if self._resource_lease_group is None:
            self._resource_lease_group = self._control.open_task_group(
                f"research-resource-leases:{uuid4().hex}",
                resource_id="generic-resource-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )

        def renew(rows: tuple[ResourceLease, ...]) -> tuple[ResourceLease, ...]:
            return tuple(
                leases.renew(
                    row.lease_id,
                    fencing_token=row.fencing_token,
                    ttl_seconds=policy.ttl_seconds,
                )
                for row in rows
            )

        return LeaseHeartbeatFactory(
            renew=renew,
            row_identity=lambda row: row.lease_id,
            heartbeat_namespace="resource-lease",
            task_group=self._resource_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-generic-resource-lease-renewal",
            interval_seconds=policy.renewal_interval_seconds,
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def compute_lease_guard_factory(
        self,
        scheduler: ComputeSchedulerPort,
        *,
        policy: ComputeLeasePolicy = DEFAULT_COMPUTE_LEASE_POLICY,
        lane_capacity: int | None = None,
    ) -> ComputeLeaseGuardFactoryPort:
        """Share one structured heartbeat authority across all compute leases."""
        self._require_workloads_open()

        if self._compute_lease_group is None:
            self._compute_lease_group = self._control.open_task_group(
                f"research-compute-leases:{uuid4().hex}",
                resource_id="compute-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return LeaseHeartbeatFactory(
            renew=lambda rows: scheduler.renew_many(rows, ttl_seconds=policy.ttl_seconds),
            row_identity=lambda row: row.allocation_id,
            heartbeat_namespace="compute-lease",
            task_group=self._compute_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-compute-lease-renewal",
            interval_seconds=policy.renewal_interval_seconds,
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def endpoint_lease_guard_factory(
        self,
        allocations: EndpointAllocationPort,
        *,
        policy: EndpointLeasePolicy = DEFAULT_ENDPOINT_LEASE_POLICY,
        lane_capacity: int | None = None,
    ) -> EndpointLeaseGuardFactoryPort:
        """Share one structured heartbeat authority across endpoint leases."""
        self._require_workloads_open()

        if self._endpoint_lease_group is None:
            self._endpoint_lease_group = self._control.open_task_group(
                f"research-endpoint-leases:{uuid4().hex}",
                resource_id="endpoint-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return LeaseHeartbeatFactory(
            renew=lambda rows: allocations.renew_many(rows, ttl_seconds=policy.ttl_seconds),
            row_identity=lambda row: row.allocation_id,
            heartbeat_namespace="endpoint-lease",
            task_group=self._endpoint_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-endpoint-lease-renewal",
            interval_seconds=policy.renewal_interval_seconds,
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def environment_instance_lease_guard_factory(
        self,
        authority: EnvironmentInstanceLeaseAuthority,
        *,
        policy: EnvironmentInstanceLeasePolicy = DEFAULT_ENVIRONMENT_INSTANCE_LEASE_POLICY,
        lane_capacity: int | None = None,
    ) -> LeaseHeartbeatFactory:
        """Share one structured heartbeat authority across environment checkouts."""
        self._require_workloads_open()

        if self._environment_lease_group is None:
            self._environment_lease_group = self._control.open_task_group(
                f"research-environment-leases:{uuid4().hex}",
                resource_id="environment-instance-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return LeaseHeartbeatFactory(
            renew=authority.renew_many,
            row_identity=lambda row: row.instance.instance_id,
            heartbeat_namespace="environment-instance-lease",
            task_group=self._environment_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-environment-instance-lease-renewal",
            interval_seconds=policy.renewal_interval_seconds,
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def docker_container_lease_guard_factory(
        self,
        authority: DockerContainerLeaseAuthority,
        *,
        policy: DockerContainerLeasePolicy = DEFAULT_DOCKER_CONTAINER_LEASE_POLICY,
        lane_capacity: int | None = None,
    ) -> LeaseHeartbeatFactory:
        """Share one structured heartbeat authority across managed Docker containers."""
        self._require_workloads_open()

        if self._container_lease_group is None:
            self._container_lease_group = self._control.open_task_group(
                f"research-container-leases:{uuid4().hex}",
                resource_id="docker-container-lease-heartbeats",
                priority=ExecutionPriority.CRITICAL,
                failure_policy=TaskFailurePolicy.FAIL_FAST,
            )
        return LeaseHeartbeatFactory(
            renew=authority.renew_many,
            row_identity=lambda row: row.allocation_id,
            heartbeat_namespace="docker-container-lease",
            task_group=self._container_lease_group,
            heartbeat_scheduler=self._control.heartbeats,
            lane_id="research-docker-container-lease-renewal",
            interval_seconds=policy.renewal_interval_seconds,
            lane_capacity=lane_capacity,
            policy=policy,
        )

    def register_model_io_resource(self, resource: object) -> None:
        """Bind one closeable long-lived resource to the model-I/O domain."""
        self._require_workloads_open()
        closer=getattr(resource,"close",None)
        if not callable(closer):
            raise TypeError("model-I/O resource must expose close()")
        identity=id(resource)
        with self._model_io_resource_lock:
            if self._model_io_resources_closed:
                raise RuntimeError("model-I/O resources are already closed")
            if identity in self._model_io_resource_ids:
                return
            self._model_io_resources.append(resource)
            self._model_io_resource_ids.add(identity)

    def _close_model_io_resources(self) -> BaseException | None:
        with self._model_io_resource_lock:
            if self._model_io_resources_closed:
                return None
            resources=tuple(reversed(self._model_io_resources))
        errors: list[BaseException] = []
        for resource in resources:
            try:
                resource.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            return BaseExceptionGroup(
                "model-I/O owned resource shutdown failed",
                errors,
            )
        with self._model_io_resource_lock:
            self._model_io_resources_closed=True
        return None

    def register_model_lifecycle_resource(self, resource: object) -> None:
        """Bind a physical model owner that must survive workload I/O quiescence."""
        self._require_workloads_open()
        closer = getattr(resource, "close", None)
        if not callable(closer):
            raise TypeError("model lifecycle resource must expose close()")
        identity = id(resource)
        with self._model_lifecycle_resource_lock:
            if self._model_lifecycle_resources_closed:
                raise RuntimeError("model lifecycle resources are already closed")
            if identity in self._model_lifecycle_resource_ids:
                return
            self._model_lifecycle_resources.append(resource)
            self._model_lifecycle_resource_ids.add(identity)

    def _close_model_lifecycle_resources(self) -> BaseException | None:
        with self._model_lifecycle_resource_lock:
            if self._model_lifecycle_resources_closed:
                return None
            resources = tuple(reversed(self._model_lifecycle_resources))
        errors: list[BaseException] = []
        for resource in resources:
            try:
                resource.close()
            except BaseException as exc:
                errors.append(exc)
        if errors:
            return BaseExceptionGroup(
                "model physical lifecycle resource shutdown failed",
                errors,
            )
        with self._model_lifecycle_resource_lock:
            self._model_lifecycle_resources_closed = True
        return None

    def open_capability_io_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        resource_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_queue_wait_timeout_seconds: float | None = None,
        resource_demand: ResourceCompetitionDemand | None = None,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        self._require_workloads_open()
        return self._capability_io.open_task_group(
            group_id,
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            resource_demand=resource_demand,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def open_model_io_group(
        self,
        group_id: str,
        *,
        tenant_id: str | None = None,
        priority: ExecutionPriority = ExecutionPriority.NORMAL,
        admission_queue_wait_timeout_seconds: float | None = None,
        resource_demand: ResourceCompetitionDemand | None = None,
        deadline: Deadline | None = None,
        failure_policy: TaskFailurePolicy = TaskFailurePolicy.FAIL_FAST,
    ) -> TaskGroupPort:
        self._require_workloads_open()
        return self._model_io.open_task_group(
            group_id,
            tenant_id=tenant_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            resource_demand=resource_demand,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def close_fleet_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._fleet.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_orchestration_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._orchestration.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_control_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._control.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_experiment_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._experiments.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_machine_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._machines.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_capability_io_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._capability_io.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    def close_model_io_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._model_io.close_task_group(
            group,
            cancel_pending=cancel_pending,
            deadline=deadline,
        )

    @staticmethod
    def _close_domain_for_physical_convergence(
        runtime,
        *,
        deadline: Deadline | None,
    ) -> BaseException | None:
        """Close one execution domain and classify only physical non-convergence.

        The concurrency runtime intentionally reports historical logical child
        failures from close() even after every owned task/lane/provider has
        physically joined. Those failures remain visible in topology/evidence
        and through normal task health checks, but they must not pin physical
        resources forever during terminal teardown.
        """

        try:
            runtime.close(deadline=deadline)
        except BaseException as exc:
            snapshot = runtime.topology_snapshot()
            if snapshot.converged:
                return None
            return exc
        return None

    def quiesce_workloads(
        self,
        *,
        deadline: Deadline | None = None,
    ) -> None:
        """Seal and physically join fleet/downstream work, keeping control alive.

        Fleet dispatch is closed first because it may synchronously wait on
        Research OS orchestration. Experiment scheduling is closed next because it may synchronously wait
        on Machine execution; Machine execution is closed next because it may
        synchronously wait on model-I/O or capability-I/O. Resource and
        durable-ownership heartbeats live in the
        independent control domain and intentionally survive workload quiescence;
        each physical owner stops its own guard only after dependent work has
        converged and the physical effect is safe to release.
        """

        if self._closed or self._workloads_quiesced:
            return
        self._workloads_quiescing = True
        errors: list[BaseException] = []
        fleet_error = self._close_domain_for_physical_convergence(
            self._fleet,
            deadline=deadline,
        )
        if fleet_error is not None:
            errors.append(fleet_error)
        experiment_error = self._close_domain_for_physical_convergence(
            self._experiments,
            deadline=deadline,
        )
        if experiment_error is not None:
            errors.append(experiment_error)
        machine_error = self._close_domain_for_physical_convergence(
            self._machines,
            deadline=deadline,
        )
        if machine_error is not None:
            errors.append(machine_error)
        # Even when upstream convergence is unproven, downstream I/O domains
        # still receive bounded close attempts so shutdown does not strand workers.
        capability_io_error = self._close_domain_for_physical_convergence(
            self._capability_io,
            deadline=deadline,
        )
        if capability_io_error is not None:
            errors.append(capability_io_error)
        # Request-side HTTP/client/recorder resources are event-loop owned and
        # must close while model-I/O is still alive.  Physical model-service
        # lifecycle owners are registered separately and intentionally survive
        # quiescence until terminal runtime teardown.
        model_resource_error = self._close_model_io_resources()
        if model_resource_error is not None:
            errors.append(model_resource_error)
        else:
            model_io_error = self._close_domain_for_physical_convergence(
                self._model_io,
                deadline=deadline,
            )
            if model_io_error is not None:
                errors.append(model_io_error)
        if errors:
            raise BaseExceptionGroup(
                "research execution workload quiesce failed",
                errors,
            )
        self._workloads_quiesced = True

    def fleet_admission_snapshot(self):
        return self._fleet.admission_snapshot()

    def orchestration_admission_snapshot(self):
        return self._orchestration.admission_snapshot()

    def control_admission_snapshot(self):
        return self._control.admission_snapshot()

    def experiment_admission_snapshot(self):
        return self._experiments.admission_snapshot()

    def machine_admission_snapshot(self):
        return self._machines.admission_snapshot()

    def capability_io_admission_snapshot(self):
        return self._capability_io.admission_snapshot()

    def model_io_admission_snapshot(self):
        return self._model_io.admission_snapshot()

    def close(self, *, deadline: Deadline | None = None) -> None:
        if self._closed:
            return
        # Seal every workload submission path immediately. Control-plane
        # ownership remains alive until every workload domain and its shared
        # physical CPU provider have converged, so lease/fencing/recovery can
        # still make progress after a bounded close failure.
        self._closing = True
        errors: list[BaseException] = []
        fleet_error = self._close_domain_for_physical_convergence(
            self._fleet,
            deadline=deadline,
        )
        if fleet_error is not None:
            errors.append(fleet_error)
        pre_model_runtimes = (
            self._experiments,
            self._machines,
            self._capability_io,
        )
        for runtime in pre_model_runtimes:
            error = self._close_domain_for_physical_convergence(
                runtime,
                deadline=deadline,
            )
            if error is not None:
                errors.append(error)

        model_resource_error = self._close_model_io_resources()
        if model_resource_error is not None:
            errors.append(model_resource_error)
        else:
            model_io_error = self._close_domain_for_physical_convergence(
                self._model_io,
                deadline=deadline,
            )
            if model_io_error is not None:
                errors.append(model_io_error)

        lifecycle_error = self._close_model_lifecycle_resources()
        if lifecycle_error is not None:
            errors.append(lifecycle_error)

        # A physical lifecycle closer may fail and still leave no executing
        # workload. Preserve that error for retry/forensics, but never strand the
        # orchestration/control runtimes as non-daemon process owners. Terminal
        # convergence is best-effort across every independent owner boundary.
        orchestration_error = self._close_domain_for_physical_convergence(
            self._orchestration,
            deadline=deadline,
        )
        if orchestration_error is not None:
            errors.append(orchestration_error)

        workload_runtimes = (
            self._fleet,
            self._experiments,
            self._machines,
            self._capability_io,
            self._model_io,
            self._orchestration,
        )
        workloads_converged = all(
            runtime.topology_snapshot().converged
            for runtime in workload_runtimes
        )
        if workloads_converged and not self._shared_workload_cpu_closed:
            try:
                assert self._shared_workload_cpu is not None
                self._shared_workload_cpu.close(
                    wait=True,
                    cancel_pending=True,
                )
            except BaseException as exc:
                errors.append(exc)
            else:
                self._shared_workload_cpu_closed = True

        if workloads_converged and self._shared_workload_cpu_closed:
            try:
                self._model_admission.close()
            except BaseException as exc:
                errors.append(exc)
            control_error = self._close_domain_for_physical_convergence(
                self._control,
                deadline=deadline,
            )
            if control_error is not None:
                errors.append(control_error)

        if errors:
            raise BaseExceptionGroup("research execution pool close failed", errors)
        if not workloads_converged or not self._shared_workload_cpu_closed:
            raise RuntimeError(
                "research execution pool close did not converge workload CPU ownership"
            )
        if not self._control.topology_snapshot().converged:
            raise RuntimeError(
                "research execution pool close did not converge control ownership"
            )
        self._closed = True

    def __enter__(self) -> "ResearchExecutionPool":
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        return self

    def __exit__(self, exc_type, exc, traceback) -> bool:
        self.close()
        return False


__all__ = ["ResearchExecutionPool"]
