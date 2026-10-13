from __future__ import annotations

from threading import Lock
import time
from uuid import uuid4

from noetrium_platform.capabilities.model.serving.api import ModelAdmissionRegistryPort
from noetrium_platform.capabilities.model.serving.runtime.admission import ModelAdmissionRegistry
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AdaptiveModelEndpointPoolPort,
    ModelEndpointReplicaSet,
    ModelJsonHttpClientPort,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_adaptive_model_endpoint_pool,
)
from noetrium_platform.capabilities.model.serving.endpoint.providers import (
    PooledModelHttpTransport,
    PooledModelHttpTransportOwner,
    StructuredModelJsonHttpClient,
)
from noetrium_platform.infrastructure.resources.authority.runtime.commit_feed import (
    SQLiteAuthorityCommitFeed,
)
from noetrium_platform.infrastructure.resources.authority import (
    AuthorityLeasePolicy,
    DEFAULT_AUTHORITY_LEASE_POLICY,
    LeaseHeartbeatFactory,
    UniversalResourceAuthority,
    lease_field,
)
from noetrium_platform.infrastructure.resources.compute.api import (
    HostRuntimeObserverPort,
)
from noetrium_platform.infrastructure.resources.compute.providers import (
    LocalHostRuntimeObserver,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest, retry_until_deadline
from noetrium_platform.foundation.kernel.kernel.durability import is_sqlite_lock_contention
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
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

from .concurrency import (
    build_execution_concurrency_runtime,
    build_scheduling_authority,
    retire_scheduling_authority,
)
from .shared_host_pressure import (
    ResourceCompetitionDemand,
    ResourceCompetitionPolicy,
    ResourceCompetitionReservations,
    SharedNetworkPressureObserverPort,
    SharedStoragePressureObserverPort,
)


def _renew_resource_authority_leases(
    authority: UniversalResourceAuthority,
    rows,
    policy: AuthorityLeasePolicy,
):
    """Renew one authority batch until its actual lease safety horizon.

    SQLite contention is scheduling noise, not evidence that ownership was
    lost. Retry transient contention until the earliest authoritative lease
    expiry in this batch. Generation fences, release, expiry, and all other
    non-contention Authority failures remain fail-close immediately.
    """
    lease_rows = tuple(rows)
    expiries = tuple(
        float(expiry)
        for row in lease_rows
        if (expiry := lease_field(row, "expires_at_epoch_s")) is not None
    )
    retry_budget = (
        max(0.0, min(expiries) - time.time())
        if expiries
        else float(policy.ttl_seconds)
    )
    retry_interval = max(
        0.001,
        min(
            float(policy.renewal_interval_seconds) / 100.0,
            max(retry_budget / 100.0, 0.001),
        ),
    )
    return retry_until_deadline(
        lambda: authority.renew_leases(
            lease_rows,
            ttl_seconds=policy.ttl_seconds,
        ),
        should_retry=is_sqlite_lock_contention,
        timeout_seconds=retry_budget,
        interval_seconds=retry_interval,
    )


def _default_control_concurrency_budget() -> ConcurrencyBudget:
    """Expose the same physical ceiling to control work as the host authority.

    Control-plane work is already isolated by its own admission/scheduling
    domain and priority. Dividing host capacity by fixed fractions creates an
    arbitrary concurrency policy and can strand otherwise idle capacity.
    Runtime admission remains responsible for the live window.
    """

    return ConcurrencyBudget()


def _default_experiment_concurrency_budget() -> ConcurrencyBudget:
    """Bound speculative blocking work by physical experiment workers.

    A blocking provider with W workers has service-capacity upper bound W.
    Admitting Q>W blocking experiment children cannot raise that bound; it only
    creates queued reservations, authority writes, memory pressure and recovery
    debt.  The rolling frontier refills immediately when a worker completes, so
    Q=W is the work-conserving optimum for this domain.  Async/model I/O keeps
    its independent capacity because its service model is not thread-worker
    bounded.
    """

    base = ConcurrencyBudget()
    return ConcurrencyBudget(
        max_blocking_io_workers=base.max_blocking_io_workers,
        max_serial_workers=base.max_serial_workers,
        max_cpu_workers=base.max_cpu_workers,
        max_blocking_io_in_flight=base.max_blocking_io_workers,
        max_async_io_in_flight=base.max_async_io_in_flight,
        max_cpu_in_flight=base.max_cpu_in_flight,
        default_queue_capacity=base.default_queue_capacity,
        shutdown_timeout_seconds=base.shutdown_timeout_seconds,
    )


def _default_model_io_concurrency_budget() -> ConcurrencyBudget:
    """Use kernel-derived physical ceilings; endpoint dispatch owns live concurrency.

    The global model-I/O runtime must not reserve a fixed fraction of file
    descriptors. Qualified endpoint capacity, adaptive request windows and the
    shared resource authority determine actual model concurrency.
    """

    return ConcurrencyBudget()


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

        fleet -> orchestration -> experiment scheduling -> workload execution
              -> machine execution -> {model I/O, capability I/O}

    A synchronous parent may wait only on work in a downstream domain. Keeping
    the workload admission/concurrency domains independent prevents nested-admission
    deadlock while preserving one composition owner and bounded resources.
    Exact model-serving capacity is a Resource Authority capacity dimension;
    no independent admission truth exists outside the platform Authority.
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
        resource_authority: UniversalResourceAuthority,
        host_runtime_observer: HostRuntimeObserverPort | None = None,
        storage_pressure_observer: SharedStoragePressureObserverPort | None = None,
        network_pressure_observer: SharedNetworkPressureObserverPort | None = None,
        resource_competition_policy: ResourceCompetitionPolicy | None = None,
        exclusive_owner_generation: bool = False,
    ) -> None:
        if type(exclusive_owner_generation) is not bool:
            raise TypeError("exclusive_owner_generation must be boolean")
        if not isinstance(resource_authority, UniversalResourceAuthority):
            raise TypeError(
                "ResearchExecutionPool requires the platform UniversalResourceAuthority"
            )
        self._resource_authority = resource_authority
        self._owner_generation_id = uuid4().hex
        self._resource_competition_owner_resource_key = (
            "research-execution-pool:" + self._owner_generation_id
        )
        self._resource_competition_owner_lease = resource_authority.acquire_ttl_lease(
            lease_id="resource-competition-owner:" + self._owner_generation_id,
            resource_key=self._resource_competition_owner_resource_key,
            holder_key="research-execution-pool:" + self._owner_generation_id,
            owner_scope=PLATFORM_SCOPE,
            ttl_seconds=DEFAULT_AUTHORITY_LEASE_POLICY.ttl_seconds,
            metadata={
                "kind": "resource-competition-owner",
                "owner_generation_id": self._owner_generation_id,
            },
        )
        self._resource_competition_owner_guard = None

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
        # Terminal convergence is one end-to-end operation.  A fresh timeout
        # per logical domain makes the global bound additive in the number of
        # domains; one shared absolute deadline makes it independent of domain
        # count while preserving dependency-ordered close semantics.
        self._shutdown_timeout_seconds = max(
            budget.shutdown_timeout_seconds
            for budget in (
                resolved_control_budget,
                resolved_orchestration_budget,
                resolved_fleet_budget,
                resolved_experiment_budget,
                resolved_machine_budget,
                resolved_capability_io_budget,
                resolved_model_io_budget,
            )
        )
        self._scheduling_authority = build_scheduling_authority(
            resource_authority=resource_authority,
        )
        # Control-plane liveness must not depend on the workload-global durable
        # scheduling ledger that it exists to keep alive. A stalled scheduler
        # writer would otherwise delay heartbeat dispatch before it even reaches
        # the physically isolated control timer/serial lanes, allowing graph and
        # resource leases to expire. Control work retains the identical VTC/LAS
        # scheduling semantics locally; only cross-workload durable fairness is
        # intentionally out of its liveness path.
        self._control_scheduling_authority = build_scheduling_authority()
        resolved_host_runtime_observer = (
            host_runtime_observer or LocalHostRuntimeObserver()
        )
        self._host_runtime_observer = resolved_host_runtime_observer
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
            scheduling_authority=self._control_scheduling_authority,
            blocking_io_thread_name_prefix="research-control-io",
            timer_name="research-control-timer",
        )
        self._shared_workload_cpu = None
        self._shared_workload_cpu_closed = False
        self._resource_competition_reservations = ResourceCompetitionReservations(
            resource_authority,
            self._resource_competition_owner_lease,
        )
        try:
            self._shared_workload_cpu = build_cpu_worker_pool_provider(
                shared_cpu_budget
            )
            self._fleet = build_execution_concurrency_runtime(
                concurrency_budget=resolved_fleet_budget,
                admission_budget=fleet_admission_budget,
                    scheduling_authority=self._scheduling_authority,
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
                    scheduling_authority=self._scheduling_authority,
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
                    scheduling_authority=self._scheduling_authority,
                host_runtime_observer=resolved_host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-experiment-io",
                timer_name="research-experiment-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._workloads = build_execution_concurrency_runtime(
                concurrency_budget=resolved_machine_budget,
                admission_budget=machine_admission_budget,
                    scheduling_authority=self._scheduling_authority,
                host_runtime_observer=resolved_host_runtime_observer,
                storage_pressure_observer=storage_pressure_observer,
                network_pressure_observer=network_pressure_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-workload-io",
                timer_name="research-workload-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._machines = build_execution_concurrency_runtime(
                concurrency_budget=resolved_machine_budget,
                admission_budget=machine_admission_budget,
                    scheduling_authority=self._scheduling_authority,
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
                    scheduling_authority=self._scheduling_authority,
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
                    scheduling_authority=self._scheduling_authority,
                host_runtime_observer=resolved_host_runtime_observer,
                resource_competition_policy=resolved_resource_competition_policy,
                resource_competition_reservations=self._resource_competition_reservations,
                blocking_io_thread_name_prefix="research-model-io",
                timer_name="research-model-timer",
                cpu_provider=self._shared_workload_cpu,
            )
            self._model_admission: ModelAdmissionRegistryPort = (
                ModelAdmissionRegistry(
                    resource_authority,
                    self._resource_competition_owner_lease,
                    change_feed=SQLiteAuthorityCommitFeed(
                        resource_authority.path,
                        task_group=self._control.open_task_group(
                            "resource-authority-commit-feed:"
                            + self._owner_generation_id,
                        ),
                        close_group=self._control.close_task_group,
                    ),
                )
            )
            self._model_io_resource_lock = Lock()
            self._model_io_resources: list[object] = []
            self._model_io_resource_ids: set[int] = set()
            self._model_io_resources_closed = False
            self._lifecycle_resource_lock = Lock()
            self._lifecycle_resources: list[object] = []
            self._lifecycle_resource_ids: set[int] = set()
            self._lifecycle_resources_closed = False
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
            for name in ("_model_io", "_capability_io", "_machines", "_workloads", "_experiments", "_orchestration", "_fleet"):
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
            try:
                self._resource_competition_reservations.close()
            except BaseException as cleanup_exc:
                errors.append(cleanup_exc)
            try:
                self._resource_authority.release_lease(
                    self._resource_competition_owner_lease
                )
            except BaseException as cleanup_exc:
                errors.append(cleanup_exc)
            if len(errors) == 1:
                raise
            raise BaseExceptionGroup(
                "research execution pool construction failed",
                errors,
            ) from exc
        self._workload_cpu_workers = shared_cpu_budget.max_cpu_workers
        self._exclusive_owner_generation = exclusive_owner_generation
        self._resource_lease_group: TaskGroupPort | None = None
        self._resource_lease_factory_lock = Lock()
        self._resource_lease_factory_binding: tuple[
            UniversalResourceAuthority,
            AuthorityLeasePolicy,
            int | None,
            LeaseHeartbeatFactory,
        ] | None = None
        self._resource_lease_factory_closed = False
        self._workloads_quiescing = False
        self._workloads_quiesced = False
        self._closing = False
        self._closed = False
        self._resource_competition_owner_guard = None
        self._owner_heartbeat_bootstrapping = True
        try:
            owner_factory = self.resource_lease_guard_factory(resource_authority)
            owner_guard = owner_factory.create(
                (self._resource_competition_owner_lease,)
            )
            owner_guard.start()
        except BaseException as primary:
            cleanup: list[BaseException] = []
            try:
                self._resource_competition_reservations.close()
            except BaseException as exc:
                cleanup.append(exc)
            try:
                resource_authority.release_lease(
                    self._resource_competition_owner_lease
                )
            except BaseException as exc:
                cleanup.append(exc)
            if cleanup:
                raise BaseExceptionGroup(
                    "research execution pool owner heartbeat construction failed",
                    [primary, *cleanup],
                ) from primary
            raise
        self._resource_competition_owner_guard = owner_guard
        self._owner_heartbeat_bootstrapping = False

    def _assert_owner_lease_healthy(self) -> None:
        guard = self._resource_competition_owner_guard
        if guard is None:
            raise RuntimeError("research execution pool has no live owner heartbeat")
        try:
            guard.assert_healthy()
        except BaseException as exc:
            raise RuntimeError(
                "research execution pool lost Universal Resource Authority ownership: "
                f"{type(exc).__name__}: {exc}"
            ) from exc

    def _require_workloads_open(self) -> None:
        if self._closed:
            raise RuntimeError("research execution pool is closed")
        if self._closing:
            raise RuntimeError("research execution pool is closing")
        if self._workloads_quiescing or self._workloads_quiesced:
            raise RuntimeError("research execution pool workloads are quiescing")
        self._assert_owner_lease_healthy()

    @property
    def model_http_max_connections(self) -> int:
        """Maximum concurrent model HTTP requests owned by this execution pool."""
        return self._model_http_max_connections

    @property
    def scheduling_authority(self):
        """Durable fairness authority shared by workload-bearing domains."""

        return self._scheduling_authority

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
            self._workloads.resource_competition is not None,
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
    def workload_cpu_workers(self) -> int:
        """Physical CPU workers shared by all workload execution domains."""

        return self._workload_cpu_workers

    @property
    def workloads_quiescent(self) -> bool:
        """Whether every workload-bearing domain has physically converged.

        Control/heartbeat domains are intentionally excluded: they remain live
        until shared owner retirement completes.
        """
        if self._closed or self._workloads_quiesced:
            return True
        runtimes = (
            self._fleet,
            self._experiments,
            self._workloads,
            self._machines,
            self._capability_io,
            self._model_io,
            self._orchestration,
        )
        return all(runtime.topology_snapshot().converged for runtime in runtimes)

    @property
    def owner_generation_id(self) -> str:
        """Process-generation fence shared by all schedulers in this pool."""

        return self._owner_generation_id

    def _owned_flow_id(self, group_id: str) -> str:
        """Fence each scheduling flow to this physical execution generation.

        Logical tenant/resource fairness identities remain unchanged. A
        durable retiring flow of an earlier generation must never reject a
        new generation's admissible task or be silently reactivated.
        """
        if type(group_id) is not str or not group_id:
            raise ValueError("execution group identity must be non-empty text")
        return group_id + ":generation:" + self._owner_generation_id

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
                health_check=self._assert_owner_lease_healthy,
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
            client = StructuredModelJsonHttpClient(
                transport,
                group,
            )
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
                    scheduling_authority=self._scheduling_authority,
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
            self._owned_flow_id(group_id),
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
            self._owned_flow_id(group_id),
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
            self._owned_flow_id(group_id),
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
            self._owned_flow_id(group_id),
            tenant_id=tenant_id,
            resource_id=resource_id,
            priority=priority,
            admission_queue_wait_timeout_seconds=admission_queue_wait_timeout_seconds,
            resource_demand=resource_demand,
            deadline=deadline,
            failure_policy=failure_policy,
        )

    def open_workload_group(
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
        return self._workloads.open_task_group(
            self._owned_flow_id(group_id),
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
            self._owned_flow_id(group_id),
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
        authority: UniversalResourceAuthority,
        *,
        policy: AuthorityLeasePolicy = DEFAULT_AUTHORITY_LEASE_POLICY,
        lane_capacity: int | None = None,
    ) -> LeaseHeartbeatFactory:
        """Return the one aggregate renewal authority for Resource leases."""

        if not self._owner_heartbeat_bootstrapping:
            self._require_workloads_open()
        elif self._closed or self._closing:
            raise RuntimeError(
                "research execution pool is closing during owner bootstrap"
            )
        if not isinstance(authority, UniversalResourceAuthority):
            raise TypeError(
                "resource lease heartbeat requires UniversalResourceAuthority"
            )
        if not isinstance(policy, AuthorityLeasePolicy):
            raise TypeError(
                "resource lease heartbeat requires AuthorityLeasePolicy"
            )

        with self._resource_lease_factory_lock:
            existing = self._resource_lease_factory_binding
            if existing is not None:
                bound_authority, bound_policy, bound_capacity, factory = existing
                if bound_authority is not authority:
                    raise RuntimeError(
                        "resource lease heartbeat authority drifted within one "
                        "execution pool"
                    )
                if bound_policy != policy or bound_capacity != lane_capacity:
                    raise RuntimeError(
                        "resource lease heartbeat policy drifted within one "
                        "execution pool"
                    )
                return factory

            group = self._resource_lease_group
            if group is None:
                group = self._control.open_task_group(
                    "research-resource-leases:" + uuid4().hex,
                    resource_id="generic-resource-lease-heartbeats",
                    priority=ExecutionPriority.CRITICAL,
                    failure_policy=TaskFailurePolicy.FAIL_FAST,
                )
                self._resource_lease_group = group

            factory = LeaseHeartbeatFactory(
                renew=lambda rows: _renew_resource_authority_leases(
                    authority,
                    rows,
                    policy,
                ),
                row_identity=lambda row: str(lease_field(row, "lease_id")),
                row_expiry_epoch_s=lambda row: (
                    None
                    if lease_field(row, "expires_at_epoch_s") is None
                    else float(lease_field(row, "expires_at_epoch_s"))
                ),
                heartbeat_namespace="resource-lease",
                task_group=group,
                heartbeat_scheduler=self._control.heartbeats,
                lane_id="research-generic-resource-lease-renewal",
                interval_seconds=policy.renewal_interval_seconds,
                lane_capacity=lane_capacity,
                policy=policy,
            )
            self._resource_lease_factory_binding = (
                authority,
                policy,
                lane_capacity,
                factory,
            )
            return factory

    def _close_resource_lease_heartbeat_factory(
        self,
    ) -> BaseException | None:
        with self._resource_lease_factory_lock:
            if self._resource_lease_factory_closed:
                return None
            binding = self._resource_lease_factory_binding
        if binding is None:
            with self._resource_lease_factory_lock:
                self._resource_lease_factory_closed = True
            return None
        factory = binding[3]
        try:
            factory.close()
        except BaseException as exc:
            exc.add_note(
                "resource lease heartbeat active_members="
                + repr(factory.active_member_identities)
            )
            return exc
        with self._resource_lease_factory_lock:
            self._resource_lease_factory_closed = True
        return None

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

    def register_lifecycle_resource(self, resource: object) -> None:
        """Register one physical lifecycle owner with the sole pool registry.

        Model services, Environment realizations and future physical runtimes
        share this exact registry.  Callers may request early retirement, but
        they never own an independent close ledger.
        """
        self._require_workloads_open()
        closer = getattr(resource, "close", None)
        if not callable(closer):
            raise TypeError("physical lifecycle resource must expose close()")
        identity = id(resource)
        with self._lifecycle_resource_lock:
            if self._lifecycle_resources_closed:
                raise RuntimeError("physical lifecycle resources are already closed")
            if identity in self._lifecycle_resource_ids:
                return
            self._lifecycle_resources.append(resource)
            self._lifecycle_resource_ids.add(identity)

    def retire_lifecycle_resource(self, resource: object) -> None:
        """Converge one registered physical owner and forget it only on success.

        Failed retirement remains registered so terminal pool close retries the
        same exact owner.  This prevents local routing/runtime objects from
        creating a second lifecycle truth.
        """
        identity = id(resource)
        with self._lifecycle_resource_lock:
            if identity not in self._lifecycle_resource_ids:
                if self._lifecycle_resources_closed:
                    return
                raise KeyError("physical lifecycle resource is not registered")
        resource.close()
        with self._lifecycle_resource_lock:
            if identity not in self._lifecycle_resource_ids:
                return
            self._lifecycle_resource_ids.remove(identity)
            self._lifecycle_resources = [
                row for row in self._lifecycle_resources if id(row) != identity
            ]

    def _close_lifecycle_resources(self) -> BaseException | None:
        with self._lifecycle_resource_lock:
            if self._lifecycle_resources_closed:
                return None
            resources = tuple(reversed(self._lifecycle_resources))
        errors: list[BaseException] = []
        retired_ids: set[int] = set()
        for resource in resources:
            try:
                resource.close()
            except BaseException as exc:
                errors.append(exc)
            else:
                retired_ids.add(id(resource))
        with self._lifecycle_resource_lock:
            if retired_ids:
                self._lifecycle_resource_ids.difference_update(retired_ids)
                self._lifecycle_resources = [
                    row
                    for row in self._lifecycle_resources
                    if id(row) not in retired_ids
                ]
            if not self._lifecycle_resources:
                self._lifecycle_resources_closed = True
        if errors:
            return BaseExceptionGroup(
                "physical lifecycle resource shutdown failed",
                errors,
            )
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
            self._owned_flow_id(group_id),
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
            self._owned_flow_id(group_id),
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

    def close_workload_group(
        self,
        group: TaskGroupPort,
        *,
        cancel_pending: bool = False,
        deadline: Deadline | None = None,
    ) -> None:
        self._workloads.close_task_group(
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
        Research execution orchestration. Experiment scheduling is closed next because it may synchronously wait
        on Machine execution; Machine execution is closed next because it may
        synchronously wait on model-I/O or capability-I/O. Resource and
        durable-ownership heartbeats live in the
        independent control domain and intentionally survive workload quiescence;
        each physical owner stops its own guard only after dependent work has
        converged and the physical effect is safe to release.
        """

        if self._closed or self._workloads_quiesced:
            return
        # The research execution deadline may already be exhausted when its
        # last Task finishes or cancellation is observed. Physical retirement
        # is a separate bounded obligation: passing an expired work deadline
        # into the kernel join would make every idle serial/timer thread report
        # spurious non-convergence without even one scheduling opportunity.
        # Use the existing authority-owned shutdown budget, never an arbitrary
        # new timeout or the original experiment's spent execution budget.
        effective = (
            deadline
            if deadline is not None and not deadline.expired
            else Deadline.after(self._shutdown_timeout_seconds)
        )
        self._workloads_quiescing = True
        errors: list[BaseException] = []
        fleet_error = self._close_domain_for_physical_convergence(
            self._fleet,
            deadline=effective,
        )
        if fleet_error is not None:
            errors.append(fleet_error)
        experiment_error = self._close_domain_for_physical_convergence(
            self._experiments,
            deadline=effective,
        )
        if experiment_error is not None:
            errors.append(experiment_error)
        workload_error = self._close_domain_for_physical_convergence(
            self._workloads,
            deadline=effective,
        )
        if workload_error is not None:
            errors.append(workload_error)
        machine_error = self._close_domain_for_physical_convergence(
            self._machines,
            deadline=effective,
        )
        if machine_error is not None:
            errors.append(machine_error)
        # Even when upstream convergence is unproven, downstream I/O domains
        # still receive bounded close attempts so shutdown does not strand workers.
        capability_io_error = self._close_domain_for_physical_convergence(
            self._capability_io,
            deadline=effective,
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
                deadline=effective,
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

    def workload_admission_snapshot(self):
        return self._workloads.admission_snapshot()

    def machine_admission_snapshot(self):
        return self._machines.admission_snapshot()

    def capability_io_admission_snapshot(self):
        return self._capability_io.admission_snapshot()

    def model_io_admission_snapshot(self):
        return self._model_io.admission_snapshot()

    def close(self, *, deadline: Deadline | None = None) -> None:
        if self._closed:
            return
        # The research execution deadline may already be exhausted when its
        # last Task finishes or cancellation is observed. Physical retirement
        # is a separate bounded obligation: passing an expired work deadline
        # into the kernel join would make every idle serial/timer thread report
        # spurious non-convergence without even one scheduling opportunity.
        # Use the existing authority-owned shutdown budget, never an arbitrary
        # new timeout or the original experiment's spent execution budget.
        effective = (
            deadline
            if deadline is not None and not deadline.expired
            else Deadline.after(self._shutdown_timeout_seconds)
        )
        # Seal every workload submission path immediately. Control-plane
        # ownership remains alive until every workload domain and its shared
        # physical CPU provider have converged, so lease/fencing/recovery can
        # still make progress after a bounded close failure.
        self._closing = True
        errors: list[BaseException] = []
        fleet_error = self._close_domain_for_physical_convergence(
            self._fleet,
            deadline=effective,
        )
        if fleet_error is not None:
            errors.append(fleet_error)
        pre_model_runtimes = (
            self._experiments,
            self._workloads,
            self._machines,
            self._capability_io,
        )
        for runtime in pre_model_runtimes:
            error = self._close_domain_for_physical_convergence(
                runtime,
                deadline=effective,
            )
            if error is not None:
                errors.append(error)

        model_resource_error = self._close_model_io_resources()
        if model_resource_error is not None:
            errors.append(model_resource_error)
        else:
            model_io_error = self._close_domain_for_physical_convergence(
                self._model_io,
                deadline=effective,
            )
            if model_io_error is not None:
                errors.append(model_io_error)

        lifecycle_error = self._close_lifecycle_resources()
        if lifecycle_error is not None:
            errors.append(lifecycle_error)
        lifecycle_converged = self._lifecycle_resources_closed

        # A physical lifecycle closer may fail and still leave no executing
        # workload. Preserve that error for retry/forensics, but never strand the
        # orchestration/control runtimes as non-daemon process owners. Terminal
        # convergence is best-effort across every independent owner boundary.
        orchestration_error = self._close_domain_for_physical_convergence(
            self._orchestration,
            deadline=effective,
        )
        if orchestration_error is not None:
            errors.append(orchestration_error)

        workload_runtimes = (
            self._fleet,
            self._experiments,
            self._workloads,
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
            try:
                self._resource_competition_reservations.close()
            except BaseException as exc:
                errors.append(exc)
            owner_guard = self._resource_competition_owner_guard
            if owner_guard is not None:
                try:
                    current_owner_lease = owner_guard.handles[0]
                    owner_guard.close()
                    self._resource_authority.release_lease(current_owner_lease)
                except BaseException as exc:
                    errors.append(exc)
                else:
                    self._resource_competition_owner_guard = None

            # Control owns lease-renewal execution.  It may converge only after
            # the single physical-lifecycle registry is empty; TaskGroup
            # convergence alone is not sufficient proof of Resource ownership
            # convergence.
            if lifecycle_converged:
                heartbeat_error = self._close_resource_lease_heartbeat_factory()
                if heartbeat_error is not None:
                    errors.append(heartbeat_error)
                else:
                    control_error = self._close_domain_for_physical_convergence(
                        self._control,
                        deadline=effective,
                    )
                    if control_error is not None:
                        errors.append(control_error)

        if errors:
            raise BaseExceptionGroup("research execution pool close failed", errors)
        if not workloads_converged or not self._shared_workload_cpu_closed:
            raise RuntimeError(
                "research execution pool close did not converge workload CPU ownership"
            )
        if not lifecycle_converged:
            raise RuntimeError(
                "research execution pool close did not converge physical lifecycle ownership"
            )
        if not self._control.topology_snapshot().converged:
            raise RuntimeError(
                "research execution pool close did not converge control ownership"
            )
        # The scheduler owns one protected SQLite writer for its process
        # lifetime. Close it only after every control/workload domain has
        # reached terminal convergence; failed shutdown remains retryable.
        retire_scheduling_authority(self._scheduling_authority)
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
