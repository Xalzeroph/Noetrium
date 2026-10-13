from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from contextlib import ExitStack, contextmanager
from noetrium_platform.substrate.api import ResourceClaimConflict, claim_field
from dataclasses import dataclass, field, replace
from enum import StrEnum
import heapq
from threading import Condition, Lock
import math
import time
from uuid import uuid4

from noetrium_platform.capabilities.model.serving.api.admission import (
    ModelAdmissionLeasePort,
    ModelAdmissionPort,
)
from noetrium_platform.capabilities.model.request.api import (
    ModelEndpointEnvelope,
    ModelOperationEnvelope,
    ModelRequestEnvelope,
    model_request_flow_id,
    model_request_owner_id,
)
from noetrium_platform.foundation.kernel.kernel import (
    JsonInput,
    canonical_digest,
    ComplexityBound,
    ComplexityContract,
    current_runtime_cost_scope,
    thaw_json,
)
from noetrium_platform.foundation.kernel.concurrency.scheduling.api import (
    ExecutionPriority,
    SchedulingCandidate,
    SchedulingAuthorityPort,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    CancellationTokenPort,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
    wake_on_cancellation,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.contracts import (
    ModelEndpointError,
    ModelEndpointRequest,
    ModelEndpointRequestRejected,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.ports import ModelEndpointPort
from noetrium_platform.capabilities.model.serving.endpoint.api.qualification import (
    PREEMPTIVE_BORROWER_PRIORITY,
    PREEMPTIVE_PROTECTED_PRIORITY,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.pressure import (
    ModelRuntimePressureObserverPort,
    ModelRuntimePressureSnapshot,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.streaming import ModelStreamEvent
from noetrium_platform.capabilities.model.serving.endpoint.api.replica import (
    ModelEndpointDispatchAttempt,
    ModelEndpointDispatchResult,
    ModelEndpointPoolSnapshot,
    ModelEndpointReplicaSelectionCandidate,
    ModelEndpointReplicaSelectionPolicyPort,
    ModelEndpointReplicaSnapshot,
    ModelEndpointReplicaSet,
)
from noetrium_platform.foundation.kernel.kernel import (
    AdaptiveServiceWindow,
    AdaptiveServiceWindowPolicy,
)
from .request_retry import ModelRequestRetryPolicy
from .selection_policy import (
    DeficitPrefixPressureReplicaSelectionPolicy,
    PinnedReplicaSelectionPolicy,
)



class _StreamConsumerError(RuntimeError):
    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause=cause


class _FlowAdmissionClass(StrEnum):
    NORMAL = "normal"
    PROTECTED_RETURN = "protected-return"
    BORROWER = "borrower"


class ModelEndpointPoolUnavailable(ModelEndpointRequestRejected):
    def __init__(self, message: str) -> None:
        super().__init__(
            message,
            failure_kind="capacity",
            retryable=True,
            affects_replica_health=False,
        )


MODEL_TOKEN_PREFIX_LOOKUP_COMPLEXITY = ComplexityContract(
    algorithm_id="model.token-prefix-residency.lookup.v1",
    implementation_digest=canonical_digest(
        (
            "model.token-prefix-residency.lookup.v1",
            "exact-token-trie-single-pass",
        )
    ),
    time_upper_bound=ComplexityBound.linear("input_tokens"),
    space_upper_bound=ComplexityBound.constant(),
    assumptions=(
        "input token ids are already materialized by the qualified tokenizer",
        "dictionary child lookup is expected O(1)",
        "query returns the deepest historically resident token prefix and replica mask",
    ),
    time_lower_bound=ComplexityBound.linear("input_tokens"),
    space_lower_bound=ComplexityBound.constant(),
)


@dataclass(slots=True)
class _TokenPrefixTrieNode:
    children: dict[int, "_TokenPrefixTrieNode"] = field(
        default_factory=dict
    )
    replica_refcounts: dict[int, int] = field(default_factory=dict)
    replica_mask: int = 0


class _TokenPrefixResidencyIndex:
    """Exact token-prefix history with bounded per-replica metadata.

    This index owns logical locality evidence only. Physical KV-cache truth
    remains the provider's cached-token receipt (and, on newer runtimes,
    provider KV block events). Sequence LRU bounds metadata independently of
    the number of distinct token-prefix trie nodes shared across replicas.
    """

    def __init__(
        self,
        deployment_ids: tuple[str, ...],
        token_budget_by_deployment: Mapping[str, int],
    ) -> None:
        if not deployment_ids or len(set(deployment_ids)) != len(
            deployment_ids
        ):
            raise ValueError(
                "token-prefix index requires unique deployments"
            )
        self._deployment_ids = deployment_ids
        self._bit_by_deployment = {
            deployment_id: 1 << index
            for index, deployment_id in enumerate(deployment_ids)
        }
        self._index_by_deployment = {
            deployment_id: index
            for index, deployment_id in enumerate(deployment_ids)
        }
        self._all_replica_mask = (1 << len(deployment_ids)) - 1
        budgets: dict[str, int] = {}
        for deployment_id in deployment_ids:
            raw = token_budget_by_deployment.get(deployment_id, 0)
            if type(raw) is not int or raw < 0:
                raise ValueError(
                    "token-prefix metadata budgets must be non-negative"
                )
            budgets[deployment_id] = raw
        self._token_budgets = budgets
        self._resident_tokens = {
            deployment_id: 0 for deployment_id in deployment_ids
        }
        self._sequences = {
            deployment_id: OrderedDict()
            for deployment_id in deployment_ids
        }
        self._root = _TokenPrefixTrieNode()

    @staticmethod
    def _tokens(token_ids: tuple[int, ...]) -> tuple[int, ...]:
        if type(token_ids) is not tuple or any(
            type(token) is not int or token < 0
            for token in token_ids
        ):
            raise TypeError(
                "token-prefix identity requires non-negative integer tuple"
            )
        return token_ids

    def _add_sequence(
        self,
        deployment_id: str,
        token_ids: tuple[int, ...],
    ) -> None:
        replica_index = self._index_by_deployment[deployment_id]
        bit = self._bit_by_deployment[deployment_id]
        node = self._root
        for token in token_ids:
            node = node.children.setdefault(
                token,
                _TokenPrefixTrieNode(),
            )
            count = node.replica_refcounts.get(replica_index, 0) + 1
            node.replica_refcounts[replica_index] = count
            if count == 1:
                node.replica_mask |= bit

    def _remove_sequence(
        self,
        deployment_id: str,
        token_ids: tuple[int, ...],
    ) -> None:
        replica_index = self._index_by_deployment[deployment_id]
        bit = self._bit_by_deployment[deployment_id]
        node = self._root
        path: list[
            tuple[_TokenPrefixTrieNode, int, _TokenPrefixTrieNode]
        ] = []
        for token in token_ids:
            child = node.children.get(token)
            if child is None:
                raise RuntimeError(
                    "token-prefix residency index lost sequence path"
                )
            path.append((node, token, child))
            node = child

        for _parent, _token, child in path:
            count = child.replica_refcounts.get(replica_index, 0)
            if count <= 0:
                raise RuntimeError(
                    "token-prefix residency refcount underflow"
                )
            if count == 1:
                child.replica_refcounts.pop(replica_index, None)
                child.replica_mask &= ~bit
            else:
                child.replica_refcounts[replica_index] = count - 1

        for parent, token, child in reversed(path):
            if child.children or child.replica_refcounts:
                break
            del parent.children[token]

    def record(
        self,
        deployment_id: str,
        token_ids: tuple[int, ...],
    ) -> None:
        token_ids = self._tokens(token_ids)
        if deployment_id not in self._sequences:
            raise KeyError(deployment_id)
        budget = self._token_budgets[deployment_id]
        if budget <= 0 or not token_ids:
            return

        # Metadata has a strict token budget. A single prompt longer than the
        # budget contributes its exact leading budget-sized prefix rather than
        # disabling locality or violating the bound.
        retained = token_ids[:budget]
        rows: OrderedDict[tuple[int, ...], None] = self._sequences[
            deployment_id
        ]
        if retained in rows:
            rows.move_to_end(retained)
            return

        retained_tokens = len(retained)
        while (
            rows
            and self._resident_tokens[deployment_id]
            + retained_tokens
            > budget
        ):
            evicted, _ = rows.popitem(last=False)
            self._resident_tokens[deployment_id] -= len(evicted)
            self._remove_sequence(deployment_id, evicted)

        rows[retained] = None
        self._resident_tokens[deployment_id] += retained_tokens
        self._add_sequence(deployment_id, retained)

    def longest_prefix(
        self,
        token_ids: tuple[int, ...],
    ) -> tuple[int, int]:
        token_ids = self._tokens(token_ids)
        if not token_ids:
            return self._all_replica_mask, 0
        node = self._root
        best_mask = self._all_replica_mask
        best_depth = 0
        for depth, token in enumerate(token_ids, start=1):
            child = node.children.get(token)
            if child is None:
                break
            node = child
            if node.replica_mask:
                best_mask = node.replica_mask
                best_depth = depth
        return best_mask, best_depth

    def sequence_count(self, deployment_id: str) -> int:
        try:
            return len(self._sequences[deployment_id])
        except KeyError as exc:
            raise KeyError(deployment_id) from exc

    def resident_token_count(self, deployment_id: str) -> int:
        try:
            return self._resident_tokens[deployment_id]
        except KeyError as exc:
            raise KeyError(deployment_id) from exc


@dataclass(slots=True)
class _ReplicaRuntime:

    endpoint: ModelEndpointPort
    capacity: int
    isolation_limit: int
    preemptive_borrowing: bool
    adaptive_window: AdaptiveServiceWindow
    in_flight: int = 0
    borrowed_in_flight: int = 0
    completed: int = 0
    failures: int = 0
    request_rejections: int = 0
    selections: int = 0
    consecutive_failures: int = 0
    ewma_latency_seconds: float | None = None
    cooldown_until: float = 0.0
    last_selected_sequence: int = 0
    prefix_affinity_selections: int = 0
    pressure_snapshot: ModelRuntimePressureSnapshot | None = None
    pressure_probe_in_flight: bool = False
    pressure_probe_sequence: int = 0
    last_pressure_probe_at: float = -math.inf
    last_preemptions_total: int | None = None
    recovery_probe_in_flight: bool = False
    max_prefill_queued_tokens: int | None = None
    prefill_tokens_in_flight: int = 0
    token_reservation_in_flight: int = 0



@dataclass(slots=True)
class _PoolWaitDiagnostics:
    # Timed actual Condition waits, classified at the observed wait boundary.
    wait_reason_seconds: dict[str, float] = field(default_factory=dict)
    bypassed_ineligible_heads: int = 0
    physically_denied_epoch: int | None = None


@dataclass(frozen=True, slots=True)
class _PoolWaiter:
    ticket: int
    owner_id: str
    enqueued_monotonic: float
    flow_id: str | None = None
    persistent_flow: bool = False
    deadline_monotonic: float | None = None
    estimated_service_cost: float = 0.0
    # Dispatch feasibility is a projection of the existing waiting request.
    # Reservation waiters do not carry these fields.
    dispatch_input_token_ids: tuple[int, ...] | None = None
    dispatch_attempted_deployments: frozenset[str] = frozenset()
    dispatch_input_tokens: int = 0
    dispatch_output_tokens: int = 0
    dispatch_preemptive_eligible: bool = False
    diagnostics: _PoolWaitDiagnostics = field(
        default_factory=_PoolWaitDiagnostics, compare=False, repr=False,
    )

    @property
    def scheduling_flow_id(self) -> str:
        return self.owner_id if self.flow_id is None else self.flow_id

_SERVICE_QUANTA_PER_SECOND = 1_000_000_000


def _service_quanta_per_token(rate_tokens_per_second: float) -> int:
    if (
        isinstance(rate_tokens_per_second, bool)
        or not isinstance(rate_tokens_per_second, (int, float))
        or not math.isfinite(float(rate_tokens_per_second))
        or float(rate_tokens_per_second) <= 0.0
    ):
        raise ValueError("model service rate must be finite and positive")
    # Conservative fixed-point service time.  Ceil never understates the
    # measured cost and integer quanta make owner ordering deterministic.
    return max(
        1,
        math.ceil(_SERVICE_QUANTA_PER_SECOND / float(rate_tokens_per_second)),
    )


class AdaptiveModelEndpointPool:
    """Single adaptive dispatch machine for every frozen endpoint replica set."""

    def __init__(
        self,
        replica_set: ModelEndpointReplicaSet,
        endpoint_factory: Callable[[object], ModelEndpointPort],
        *,
        selection_policy: ModelEndpointReplicaSelectionPolicyPort | None = None,
        adaptive_window_policy: AdaptiveServiceWindowPolicy | None = None,
        retry_policy: ModelRequestRetryPolicy | None = None,
        scheduling_authority: SchedulingAuthorityPort,
        physical_continuity_controllers: Mapping[str, ModelAdmissionPort] | None = None,
        sleep: Callable[[float], None] = time.sleep,
        ewma_alpha: float = 0.2,
        failure_cooldown_seconds: float = 2.0,
        max_failure_cooldown_seconds: float = 30.0,
        pressure_observer: ModelRuntimePressureObserverPort | None = None,
        pressure_task_group: TaskGroupPort | None = None,
        owned_transport_close: Callable[[], None] | None = None,
        pressure_probe_interval_seconds: float = 1.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if not isinstance(replica_set, ModelEndpointReplicaSet):
            raise TypeError("adaptive model endpoint pool requires ModelEndpointReplicaSet")
        replicas = replica_set.members
        self._replica_set = replica_set
        replica_set_digest = replica_set.replica_set_digest
        if (
            type(replica_set_digest) is not str
            or len(replica_set_digest) != 64
            or any(char not in "0123456789abcdef" for char in replica_set_digest)
        ):
            raise ValueError("adaptive model endpoint pool requires replica set digest")
        if not callable(endpoint_factory):
            raise TypeError("adaptive model endpoint pool requires endpoint factory")
        if (
            not 0.0 < float(ewma_alpha) <= 1.0
            or not math.isfinite(float(ewma_alpha))
        ):
            raise ValueError("endpoint pool ewma_alpha must be finite in (0, 1]")
        for name, value in (
            ("failure_cooldown_seconds", failure_cooldown_seconds),
            ("max_failure_cooldown_seconds", max_failure_cooldown_seconds),
        ):
            if not math.isfinite(float(value)) or value <= 0:
                raise ValueError(f"endpoint pool {name} must be finite and positive")
        if max_failure_cooldown_seconds < failure_cooldown_seconds:
            raise ValueError("endpoint pool max cooldown cannot be shorter than base cooldown")
        self._replica_set_digest = replica_set_digest
        self._selection_policy = (
            DeficitPrefixPressureReplicaSelectionPolicy()
            if selection_policy is None
            else selection_policy
        )
        if not isinstance(self._selection_policy, ModelEndpointReplicaSelectionPolicyPort):
            raise TypeError("model endpoint selection_policy has invalid port type")
        self._scheduling_authority = scheduling_authority
        # A shared Scheduling Authority aggregates tenant fairness across pools,
        # but a flow's retirement belongs to its owning endpoint domain. Never
        # allow release in pool A to retire in-flight requests in pool B.
        self._scheduling_flow_namespace = "model-endpoint:" + uuid4().hex + ":"
        if not (
            callable(getattr(self._scheduling_authority, "ordering_keys_at_revision", None))
            and callable(getattr(self._scheduling_authority, "ordering_key", None))
            and callable(getattr(self._scheduling_authority, "select", None))
            and callable(getattr(self._scheduling_authority, "record_grant", None))
            and callable(getattr(self._scheduling_authority, "record_completion", None))
            and callable(getattr(self._scheduling_authority, "release_flow", None))
        ):
            raise TypeError("model endpoint scheduling_authority has invalid port type")
        self._selection_policy_digest = self._selection_policy.identity_digest
        if (
            type(self._selection_policy_digest) is not str
            or len(self._selection_policy_digest) != 64
            or any(char not in "0123456789abcdef" for char in self._selection_policy_digest)
        ):
            raise ValueError("model endpoint selection policy identity must be SHA-256")
        self._clock = clock
        self._adaptive_window_policy = (
            AdaptiveServiceWindowPolicy()
            if adaptive_window_policy is None
            else adaptive_window_policy
        )
        if not isinstance(self._adaptive_window_policy, AdaptiveServiceWindowPolicy):
            raise TypeError("adaptive_window_policy has invalid type")
        self._retry_policy = (
            ModelRequestRetryPolicy()
            if retry_policy is None
            else retry_policy
        )
        if not isinstance(self._retry_policy, ModelRequestRetryPolicy):
            raise TypeError("retry_policy has invalid type")
        if not callable(sleep):
            raise TypeError("model endpoint retry sleep must be callable")
        self._sleep = sleep
        self._ewma_alpha = float(ewma_alpha)
        self._failure_cooldown = float(failure_cooldown_seconds)
        self._max_failure_cooldown = float(max_failure_cooldown_seconds)
        if (pressure_observer is None) != (pressure_task_group is None):
            raise ValueError(
                "model pressure observer and task group must be supplied together"
            )
        if pressure_observer is not None and not isinstance(
            pressure_observer,
            ModelRuntimePressureObserverPort,
        ):
            raise TypeError("model pressure observer has invalid port type")
        if pressure_task_group is not None and not (
            callable(getattr(pressure_task_group, "submit", None))
            and callable(getattr(pressure_task_group, "close", None))
            and hasattr(pressure_task_group, "group_id")
        ):
            raise TypeError("model pressure task group has invalid port type")
        if (
            isinstance(pressure_probe_interval_seconds, bool)
            or not isinstance(pressure_probe_interval_seconds, (int, float))
            or not math.isfinite(float(pressure_probe_interval_seconds))
            or float(pressure_probe_interval_seconds) <= 0
        ):
            raise ValueError(
                "model pressure probe interval must be finite and positive"
            )
        if owned_transport_close is not None and not callable(owned_transport_close):
            raise TypeError("owned model transport close must be callable")
        self._owned_transport_close = owned_transport_close
        self._pressure_observer = pressure_observer
        self._pressure_task_group = pressure_task_group
        self._pressure_probe_interval = float(pressure_probe_interval_seconds)
        # Selection must never let an old high-pressure observation starve a
        # replica forever. Probes are completion-triggered, so a replica that
        # becomes less preferred also becomes less likely to refresh itself.
        # Three probe periods preserves short-term hysteresis while ensuring
        # stale telemetry ages out without another background controller.
        self._pressure_snapshot_max_age = 3.0 * self._pressure_probe_interval
        self._lock = Lock()
        self._cv = Condition(self._lock)
        # Only terminal close joins this mutex. Physical release may block
        # durably, but ordinary replica dispatch must never observe it.
        self._terminal_close_lock = Lock()
        self._terminal_close_complete = False
        self._physical_capacity_epoch = 0
        self._selection_sequence = 0
        self._closed = False
        self._next_waiter_ticket = 0
        # Per-owner FIFO queues plus a lazy owner-head heap preserve exact
        # fairness while making fair-head selection O(log owners), not a scan
        # of every owner after each grant/completion.
        self._waiters_by_owner: dict[
            str, OrderedDict[int, _PoolWaiter]
        ] = {}
        self._waiter_count = 0
        self._waiters_by_ticket: dict[int, _PoolWaiter] = {}
        self._waiter_conditions: dict[int, Condition] = {}
        self._waiter_selection_version = 0
        self._waiter_selection_cache_version = -1
        self._waiter_selection_cache_ticket: int | None = None
        # Ranking is a disposable projection of Scheduling Authority truth.
        # Cross-process fairness reads must never execute while holding the
        # replica-pool mutex: a slow durable cut would otherwise serialize
        # unrelated request encoding, completion and physical retirement.
        self._waiter_projection_revision: int | None = None
        self._waiter_projection_refreshing = False
        self._waiter_input_projection: tuple[
            tuple[_PoolWaiter, ...],
            tuple[SchedulingCandidate, ...],
            tuple[int, ...],
        ] | None = None
        self._waiter_owner_heap: list[tuple[tuple[int, ...], int]] = []
        self._waiter_flow_heaps_by_owner: dict[
            str, list[tuple[tuple[int | float, ...], int]]
        ] = {}
        self._active_by_owner: dict[str, int] = {}
        self._active_by_flow: dict[str, int] = {}
        # Admission grants are ordered without monopolizing the model pool
        # mutex across Scheduling Authority's durable SQLite transaction.
        self._global_grant_pending = False
        self._granting_flows: set[str] = set()
        self._flow_owner: dict[str, str] = {}
        self._reserved_flows: set[str] = set()
        # An external durable Claim acquisition must never hold the shared
        # scheduling lock. This per-flow pending set is only an ownership
        # handshake; Resource Authority remains the physical source of truth.
        self._claiming_flows: set[str] = set()
        # Resource Authority claims own the physical guarantee. These mappings
        # are only dispatch projections: where the lifetime has a claim and
        # which affine lease must be returned on completion.
        self._physical_continuity_controllers = physical_continuity_controllers
        self._physical_flow_claims: dict[
            str, tuple[str, ModelAdmissionLeasePort]
        ] = {}
        self._pending_flow_releases: set[str] = set()
        # Lifetime retirement is serialized per flow, not across the global
        # model-pool mutex. Its physical Authority commit happens outside cv.
        self._retiring_flow_releases: set[str] = set()
        self._latency_isolation_capacity = sum(
            (
                int(getattr(binding, "latency_isolation_concurrency"))
                if self._replica_set.qualified
                else 1
            )
            for binding in replicas
        )
        if self._latency_isolation_capacity <= 0:
            raise RuntimeError("model endpoint latency-isolation capacity must be positive")
        # Keep three distinct truths:
        #   strict isolation evidence, preferred operating prior, hard safe max.
        # A persistent flow is a lifetime ownership/affinity fact; reserving it
        # must not freeze active service concurrency at the preferred or isolated
        # operating point.  The hard flow ceiling follows measured qualification,
        # while AdaptiveServiceWindow governs how much work is active right now.
        self._persistent_flow_capacity = sum(
            (
                int(getattr(binding, "max_admitted_concurrency"))
                if self._replica_set.qualified
                else int(getattr(binding, "capacity"))
            )
            for binding in replicas
        )
        if self._persistent_flow_capacity <= 0:
            raise RuntimeError(
                "model endpoint persistent-flow capacity must be positive"
            )
        # VTC-style virtual service uses qualification-derived service-time
        # quanta, not raw token counts: prefill and decode tokens have materially
        # different costs.  The logical pool uses the slowest qualified member
        # in each dimension so owner fairness is independent of which physical
        # replica locality/load routing chooses afterward.
        qualified_prefill_rates = tuple(
            float(value)
            for binding in replicas
            for value in (
                getattr(binding, "prefill_input_tokens_per_second", None),
            )
            if value is not None
        )
        qualified_output_rates = tuple(
            float(value)
            for binding in replicas
            for value in (
                getattr(binding, "minimum_output_tokens_per_second", None),
            )
            if value is not None
        )
        if qualified_prefill_rates and len(qualified_prefill_rates) != len(replicas):
            raise ValueError(
                "model replica set cannot mix measured and unmeasured prefill service"
            )
        if qualified_output_rates and len(qualified_output_rates) != len(replicas):
            raise ValueError(
                "model replica set cannot mix measured and unmeasured output service"
            )
        self._prefill_service_quanta_per_token = (
            1
            if not qualified_prefill_rates
            else _service_quanta_per_token(min(qualified_prefill_rates))
        )
        self._output_service_quanta_per_token = (
            1
            if not qualified_output_rates
            else _service_quanta_per_token(min(qualified_output_rates))
        )
        self._runtimes: dict[str, _ReplicaRuntime] = {}
        self._bindings = {item.deployment_id: item for item in replicas}
        self._single_replica = len(replicas) == 1
        self._single_replica_default_policy = (
            self._single_replica
            and type(self._selection_policy)
            is DeficitPrefixPressureReplicaSelectionPolicy
        )
        if len(self._bindings) != len(replicas):
            raise ValueError("adaptive model endpoint pool deployments must be unique")
        # Exact prefix-residency index. The replica set is frozen, so one Python
        # integer can encode all owners of a prefix. This turns request affinity
        # matching from R*K per-replica membership probes into K bit lookups plus
        # at most R bit assignments.
        self._deployment_by_bit_index = tuple(
            binding.deployment_id for binding in replicas
        )
        self._replica_bit_by_deployment = {
            deployment_id: 1 << index
            for index, deployment_id in enumerate(self._deployment_by_bit_index)
        }
        self._worker_index_by_deployment = {
            deployment_id: index
            for index, deployment_id in enumerate(self._deployment_by_bit_index)
        }
        self._all_replica_mask = (1 << len(replicas)) - 1
        token_prefix_budgets = {
            binding.deployment_id: (
                max(
                    int(binding.model.context_length),
                    int(binding.max_prefill_queued_tokens)
                    * int(binding.max_admitted_concurrency),
                )
                if hasattr(binding, "model")
                and getattr(binding, "max_prefill_queued_tokens", None)
                is not None
                else 0
            )
            for binding in replicas
        }
        self._token_prefix_residency = _TokenPrefixResidencyIndex(
            self._deployment_by_bit_index,
            token_prefix_budgets,
        )

        qualified_prefill_windows = tuple(
            int(getattr(binding, "max_prefill_queued_tokens"))
            * self._prefill_service_quanta_per_token
            for binding in replicas
            if getattr(binding, "max_prefill_queued_tokens", None) is not None
        )
        self._worker_deficit_quantum_quanta = (
            1
            if not qualified_prefill_windows
            else min(qualified_prefill_windows)
        )
        if self._worker_deficit_quantum_quanta <= 0:
            raise RuntimeError("model worker deficit quantum must be positive")
        # D2LPM worker deficits are represented lazily as
        # q(owner,worker) = owner_credit - worker_debit. A refill is a uniform
        # translation of every q for one owner, so it updates only owner_credit
        # in O(1) rather than touching every replica.
        self._owner_worker_credit_quanta: dict[str, int] = {}
        self._owner_worker_debit_quanta: dict[str, dict[int, int]] = {}

        for binding in replicas:
            endpoint = endpoint_factory(binding)
            if endpoint.route.deployment_id != binding.deployment_id:
                raise ValueError("endpoint factory deployment identity drift")
            if endpoint.route.deployment_generation != binding.deployment_generation:
                raise ValueError("endpoint factory deployment generation drift")
            capacity = binding.max_admitted_concurrency
            isolation_limit = (
                int(getattr(binding, "latency_isolation_concurrency"))
                if self._replica_set.qualified
                else 1
            )
            preemptive_borrowing = bool(
                self._replica_set.qualified
                and getattr(binding, "preemptive_latency_isolation")
            )
            preferred = getattr(
                binding,
                "preferred_admitted_concurrency",
                None,
            )
            initial_limit = (
                None
                if preferred is None
                else min(capacity, int(preferred))
            )
            self._runtimes[binding.deployment_id] = _ReplicaRuntime(
                endpoint=endpoint,
                capacity=capacity,
                isolation_limit=isolation_limit,
                preemptive_borrowing=preemptive_borrowing,
                adaptive_window=AdaptiveServiceWindow(
                    max_limit=capacity,
                    policy=self._adaptive_window_policy,
                    initial_limit=initial_limit,
                    clock=self._clock,
                ),
                max_prefill_queued_tokens=getattr(
                    binding,
                    "max_prefill_queued_tokens",
                    None,
                ),
            )

        if self._physical_continuity_controllers is not None and (
            frozenset(self._physical_continuity_controllers)
            != frozenset(self._runtimes)
        ):
            raise RuntimeError(
                "physical model continuity requires one Resource Authority port per deployment"
            )

        self._preemptive_borrowing_enabled = any(
            runtime.preemptive_borrowing
            for runtime in self._runtimes.values()
        )

        if self._single_replica:
            single_id = self._deployment_by_bit_index[0]
            self._single_binding = self._bindings[single_id]
            self._single_runtime = self._runtimes[single_id]
        else:
            self._single_binding = None
            self._single_runtime = None

    @staticmethod
    def _provider_timeout_seconds(
        timeout_s: float | None,
    ) -> float | None:
        """Validate an optional caller-owned provider deadline.

        Queue/admission waits remain scheduling/resource-authority concerns and
        deliberately consume no provider time. A missing caller deadline is
        resolved *after* physical admission from frozen qualification evidence.
        """
        if timeout_s is None:
            return None
        if (
            isinstance(timeout_s, bool)
            or not isinstance(timeout_s, (int, float))
            or not math.isfinite(float(timeout_s))
            or float(timeout_s) <= 0
        ):
            raise ValueError(
                "model endpoint provider timeout must be finite and positive"
            )
        return float(timeout_s)

    @staticmethod
    def _qualified_transport_budget_seconds(
        binding,
        *,
        input_tokens: int,
        requested_output_tokens: int,
    ) -> tuple[float | None, float | None]:
        """Derive total/idle liveness cuts from qualification truth.

        The budget begins only after pool admission.  It is therefore not a
        scheduling deadline and cannot perturb VTC/fair-queue order.  The
        prefill cut covers one Authority-proven maximum queued-token window;
        the decode cut converts measured minimum aggregate throughput into a
        conservative per-flow service quantum at the qualified preferred
        concurrency.  Preemptive-return p99 evidence, when present, can only
        widen these cuts. No wall-clock constant is invented here.
        """
        try:
            max_prefill_tokens = int(binding.max_prefill_queued_tokens)
            prefill_rate = float(binding.prefill_input_tokens_per_second)
            output_rate = float(binding.minimum_output_tokens_per_second)
            preferred = getattr(binding, "preferred_admitted_concurrency", None)
            if preferred is None:
                preferred = int(binding.max_admitted_concurrency)
            preferred = int(preferred)
        except (AttributeError, TypeError, ValueError) as exc:
            raise RuntimeError(
                "qualified model endpoint lacks transport-liveness evidence"
            ) from exc
        if (
            max_prefill_tokens <= 0
            or preferred <= 0
            or not math.isfinite(prefill_rate)
            or prefill_rate <= 0.0
            or not math.isfinite(output_rate)
            or output_rate <= 0.0
        ):
            raise RuntimeError(
                "qualified model transport-liveness evidence must be positive and finite"
            )

        # Throughput proves service capacity, not tail wall-clock latency. Do
        # not manufacture a fail-close clock from throughput alone: a model
        # without measured return-latency evidence retains caller/route timeout
        # semantics. Production preemptive-qualified replicas carry both p99
        # measurements, which lets the platform derive a finite cut without a
        # hard-coded wall-clock constant.
        ttft = getattr(binding, "preemptive_return_ttft_p99_seconds", None)
        tpot = getattr(binding, "preemptive_return_tpot_p99_seconds", None)
        if ttft is None or tpot is None:
            return None, None

        prefill_seconds = max(
            max(max_prefill_tokens, max(1, int(input_tokens))) / prefill_rate,
            float(ttft),
        )
        per_output_token_seconds = max(
            preferred / output_rate,
            float(tpot),
        )
        output_tokens = int(requested_output_tokens)
        if output_tokens <= 0:
            context_length = int(binding.model.context_length)
            output_tokens = max(1, context_length - max(0, int(input_tokens)))
        total_seconds = (
            prefill_seconds + output_tokens * per_output_token_seconds
        )
        idle_seconds = prefill_seconds + per_output_token_seconds
        if (
            not math.isfinite(total_seconds)
            or total_seconds <= 0.0
            or not math.isfinite(idle_seconds)
            or idle_seconds <= 0.0
        ):
            raise RuntimeError(
                "qualified model transport liveness budget is invalid"
            )
        return total_seconds, idle_seconds

    def _apply_runtime_pressure_locked(
        self,
        runtime: _ReplicaRuntime,
        snapshot: ModelRuntimePressureSnapshot,
    ) -> None:
        """Apply provider pressure without confusing normal provider queueing.

        A vLLM waiting request is ordinary scheduler demand and may be required
        for batching. Only observed engine preemption proves that the current
        platform dispatch window exceeded the provider's effective service
        capacity. KV saturation suspends growth but does not invent a smaller
        capacity.
        """

        previous = runtime.last_preemptions_total
        runtime.last_preemptions_total = snapshot.preemptions_total
        runtime.pressure_snapshot = snapshot
        preemption_pressure = (
            previous is not None
            and snapshot.preemptions_total > previous
        )
        if preemption_pressure:
            runtime.adaptive_window.on_pressure(
                reason="engine_preemption",
                observed_capacity=snapshot.requests_running,
            )
        elif snapshot.gpu_kv_cache_usage >= 1.0:
            runtime.adaptive_window.on_saturation()

    def _schedule_pressure_probe(
        self,
        deployment_id: str,
        runtime: _ReplicaRuntime,
    ) -> None:
        observer = self._pressure_observer
        task_group = self._pressure_task_group
        if observer is None or task_group is None:
            return
        with self._cv:
            now = self._clock()
            if (
                self._closed
                or runtime.pressure_probe_in_flight
                or now - runtime.last_pressure_probe_at
                < self._pressure_probe_interval
            ):
                return
            runtime.pressure_probe_in_flight = True
            runtime.pressure_probe_sequence += 1
            probe_sequence = runtime.pressure_probe_sequence
            route = runtime.endpoint.route

        async def probe(context) -> None:
            snapshot = None
            try:
                context.checkpoint()
                snapshot = await observer.snapshot(route)
                context.checkpoint()
            except BaseException:
                snapshot = None
            with self._cv:
                runtime.pressure_probe_in_flight = False
                runtime.last_pressure_probe_at = self._clock()
                if (
                    snapshot is not None
                    and snapshot.deployment_id == deployment_id
                ):
                    self._apply_runtime_pressure_locked(
                        runtime,
                        snapshot,
                    )
                self._notify_selected_waiter_locked()

        try:
            task_group.submit(
                ExecutionSpec(
                    task_id=(
                        f"model-runtime-pressure:{deployment_id}:"
                        f"{probe_sequence}"
                    ),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                probe,
            )
        except BaseException:
            with self._cv:
                runtime.pressure_probe_in_flight = False
                runtime.last_pressure_probe_at = self._clock()
                self._notify_selected_waiter_locked()

    def _invalidate_waiter_selection_locked(self) -> None:
        self._waiter_selection_version += 1
        self._waiter_selection_cache_ticket = None
        self._waiter_input_projection = None

    def _prefill_service_quanta(self, input_tokens: int) -> int:
        return input_tokens * self._prefill_service_quanta_per_token

    def _output_service_quanta(self, output_tokens: int) -> int:
        return output_tokens * self._output_service_quanta_per_token

    def _flow_continuity_rank_locked(self, waiter: _PoolWaiter) -> int:
        flow_id = waiter.scheduling_flow_id
        if (
            waiter.persistent_flow
            and flow_id in self._reserved_flows
        ):
            # A live flow returning from environment/tool work owns one protected
            # service opportunity. Additional concurrent requests from the same
            # flow consume only genuinely spare isolation capacity.
            return 0 if self._active_by_flow.get(flow_id, 0) == 0 else 2
        return 1

    def _scheduling_flow_id(self, flow_id: str) -> str:
        return self._scheduling_flow_namespace + flow_id

    def _scheduling_candidate_locked(
        self,
        waiter: _PoolWaiter,
    ) -> SchedulingCandidate:
        flow_id = self._scheduling_flow_id(waiter.scheduling_flow_id)
        return SchedulingCandidate(
            ticket=waiter.ticket,
            group_id=flow_id,
            priority=ExecutionPriority.NORMAL,
            enqueued_monotonic=waiter.enqueued_monotonic,
            tenant_id=waiter.owner_id,
            flow_id=flow_id,
            continuity_rank=self._flow_continuity_rank_locked(waiter),
            deadline_monotonic=waiter.deadline_monotonic,
            estimated_service_cost=waiter.estimated_service_cost,
        )

    def _waiter_ordering_key_locked(
        self,
        waiter: _PoolWaiter,
    ) -> tuple[int | float, ...]:
        # Physical admission entitlement precedes *fair scheduling*. A flow
        # already holding idle continuity capacity is feasible even when a new
        # flow is blocked by that reservation. Sorting the blocked newcomer
        # first by VTC creates head-of-line deadlock: no request can finish to
        # release capacity. Within each entitlement class the one global
        # scheduling Authority still supplies the entire fairness order.
        protected_return = (
            waiter.persistent_flow
            and waiter.scheduling_flow_id in self._reserved_flows
            and self._active_by_flow.get(waiter.scheduling_flow_id, 0) == 0
        )
        return (
            0 if protected_return else 1,
            *self._scheduling_authority.ordering_key(
                self._scheduling_candidate_locked(waiter),
                now_monotonic=self._clock(),
            ),
        )

    def _flow_waiter_key_locked(
        self,
        waiter: _PoolWaiter,
    ) -> tuple[int | float, ...]:
        return self._waiter_ordering_key_locked(waiter)

    def _owner_waiter_key_locked(
        self,
        waiter: _PoolWaiter,
    ) -> tuple[int | float, ...]:
        return self._waiter_ordering_key_locked(waiter)

    def _owner_head_waiter_locked(
        self,
        owner_id: str,
    ) -> _PoolWaiter | None:
        queue = self._waiters_by_owner.get(owner_id)
        if not queue:
            self._waiter_flow_heaps_by_owner.pop(owner_id, None)
            return None
        heap = self._waiter_flow_heaps_by_owner.setdefault(owner_id, [])
        while heap:
            stored_key, ticket = heap[0]
            waiter = self._waiters_by_ticket.get(ticket)
            if waiter is None or waiter.owner_id != owner_id or ticket not in queue:
                heapq.heappop(heap)
                continue
            current_key = self._flow_waiter_key_locked(waiter)
            if current_key != stored_key:
                heapq.heapreplace(heap, (current_key, ticket))
                continue
            return waiter
        raise RuntimeError("model endpoint tenant flow heap lost queued waiters")

    def _compact_flow_heap_locked(self, owner_id: str) -> None:
        queue = self._waiters_by_owner.get(owner_id)
        if not queue:
            self._waiter_flow_heaps_by_owner.pop(owner_id, None)
            return
        heap = self._waiter_flow_heaps_by_owner.setdefault(owner_id, [])
        if len(heap) <= max(64, len(queue) * 4):
            return
        heap[:] = [
            (self._flow_waiter_key_locked(waiter), waiter.ticket)
            for waiter in queue.values()
        ]
        heapq.heapify(heap)

    def _compact_owner_heap_locked(self) -> None:
        owner_count = len(self._waiters_by_owner)
        if not owner_count:
            self._waiter_owner_heap.clear()
            return
        if len(self._waiter_owner_heap) <= max(64, owner_count * 4):
            return
        rows: list[tuple[tuple[int, ...], int]] = []
        for owner_id in tuple(self._waiters_by_owner):
            waiter = self._owner_head_waiter_locked(owner_id)
            if waiter is not None:
                rows.append((self._owner_waiter_key_locked(waiter), waiter.ticket))
        self._waiter_owner_heap = rows
        heapq.heapify(self._waiter_owner_heap)

    def _push_owner_head_locked(self, owner_id: str) -> None:
        # Historical callers use this hook after service/capacity transitions.
        # Do not synchronously re-rank one owner through durable Scheduling
        # Authority while holding the pool mutex. Mark the disposable projection
        # stale; _selected_waiter_locked rebuilds every live head coherently in
        # one lock-free authority batch.
        if owner_id not in self._waiters_by_owner:
            return
        self._waiter_flow_heaps_by_owner.pop(owner_id, None)
        self._waiter_owner_heap.clear()
        self._invalidate_waiter_selection_locked()

    def _enqueue_waiter_locked(self, waiter: _PoolWaiter) -> None:
        queue = self._waiters_by_owner.get(waiter.owner_id)
        if queue is None:
            queue = OrderedDict()
            self._waiters_by_owner[waiter.owner_id] = queue
        if waiter.ticket in queue:
            raise RuntimeError("duplicate model endpoint waiter ticket")
        queue[waiter.ticket] = waiter
        self._waiters_by_ticket[waiter.ticket] = waiter
        self._waiter_conditions[waiter.ticket] = Condition(self._lock)
        self._waiter_count += 1
        # Do not cross the durable Scheduling Authority boundary here. Ranking
        # is rebuilt lazily from one coherent batch outside the pool mutex.
        self._invalidate_waiter_selection_locked()

    def _remove_waiter_locked(self, waiter: _PoolWaiter) -> bool:
        queue = self._waiters_by_owner.get(waiter.owner_id)
        if queue is None:
            return False
        removed = queue.pop(waiter.ticket, None)
        if removed is None:
            return False
        self._waiters_by_ticket.pop(waiter.ticket, None)
        self._waiter_conditions.pop(waiter.ticket, None)
        self._waiter_count -= 1
        if self._waiter_count < 0:
            raise RuntimeError("model endpoint waiter accounting underflow")
        if not queue:
            self._waiters_by_owner.pop(waiter.owner_id, None)
            self._waiter_flow_heaps_by_owner.pop(waiter.owner_id, None)
        # Heaps are disposable projections and are rebuilt lazily. Avoid one
        # durable fairness read merely to discover which departing row was head.
        self._invalidate_waiter_selection_locked()
        return True

    def _dispatch_waiter_feasible_locked(self, waiter: _PoolWaiter) -> bool:
        """Read existing Authority/pool feasibility without granting a slot."""
        if waiter.dispatch_input_token_ids is None:
            flow_id = waiter.scheduling_flow_id
            if flow_id in self._claiming_flows:
                return False
            if flow_id in self._reserved_flows:
                return True
            # An actual Resource Authority refusal freezes only this waiter
            # until a committed capacity change. Other requests can continue.
            if waiter.diagnostics.physically_denied_epoch == self._physical_capacity_epoch:
                return False
            # The local case has an exact continuity capacity bound. A
            # full reservation domain cannot block unrelated dispatch.
            # Cross-process physical feasibility requires Resource Authority
            # evidence and must not be guessed from this local projection.
            if self._physical_continuity_controllers is None:
                return len(self._reserved_flows) < self._persistent_flow_capacity
            return True
        flow_id = waiter.scheduling_flow_id
        cls = self._flow_admission_class_locked(
            flow_id,
            persistent_flow=waiter.persistent_flow,
            preemptive_eligible=waiter.dispatch_preemptive_eligible,
        )
        if cls is None:
            return False
        physical = self._physical_flow_claims.get(flow_id)
        pinned_id = None if physical is None else physical[0]
        policy = self._selection_policy
        # For built-in policies, feasibility is the existential predicate
        # "is there at least one legally selectable physical replica?".
        # Prefix matching, GPU queue pressure and virtual service credit
        # determine *which* replica wins, never whether a legal slot exists.
        # Do not reconstruct candidate objects or traverse the prefix index
        # for every blocked owner under the scheduling Condition.
        if type(policy) in (
            DeficitPrefixPressureReplicaSelectionPolicy,
            PinnedReplicaSelectionPolicy,
        ):
            policy_pin = (
                policy.deployment_id
                if isinstance(policy, PinnedReplicaSelectionPolicy)
                else None
            )
            if pinned_id is not None and policy_pin is not None:
                if pinned_id != policy_pin:
                    raise RuntimeError(
                        "physical model continuation conflicts with pinned policy"
                    )
            required_id = pinned_id if pinned_id is not None else policy_pin
            candidates = (
                (self._runtimes[required_id],)
                if required_id is not None and required_id in self._runtimes
                else self._runtimes.values() if required_id is None else ()
            )
            now = self._clock()
            return any(
                runtime.cooldown_until <= now
                and not (
                    runtime.consecutive_failures > 0
                    and runtime.recovery_probe_in_flight
                )
                and self._runtime_request_available_locked(runtime, cls)
                and self._prefill_tokens_available(
                    runtime, waiter.dispatch_input_tokens,
                )
                and self._token_reservation_available(
                    runtime, waiter.dispatch_input_tokens,
                    waiter.dispatch_output_tokens,
                )
                for runtime in candidates
            )
        # An explicitly supplied nonstandard policy may reject a nonempty
        # candidate set. Preserve its full selection semantics rather than
        # guessing feasibility or declaring unavailable work runnable.
        (_now, binding, _runtime, _depth, _cooling) = (
            self._selection_candidate_locked(
                waiter.dispatch_input_token_ids,
                waiter.dispatch_attempted_deployments,
                waiter.dispatch_input_tokens,
                waiter.dispatch_output_tokens,
                owner_id=waiter.owner_id,
                admission_class=cls,
                physical_deployment_id=pinned_id,
                probe_only=True,
            )
        )
        return binding is not None

    def _waiter_block_reason_locked(self, waiter: _PoolWaiter) -> str:
        """Classify the authoritative state at one blocking-wait boundary.

        The reason applies to an observed Condition interval; it is never
        inferred from elapsed time after the fact. Mixed-replica failures
        remain explicitly mixed instead of inventing a single root cause.
        """
        if waiter.dispatch_input_token_ids is None:
            return "physical_continuity_wait"
        flow_id = waiter.scheduling_flow_id
        cls = self._flow_admission_class_locked(
            flow_id,
            persistent_flow=waiter.persistent_flow,
            preemptive_eligible=waiter.dispatch_preemptive_eligible,
        )
        if cls is None:
            return "flow_reservation_capacity"
        physical = self._physical_flow_claims.get(flow_id)
        pinned = None if physical is None else physical[0]
        if pinned is None:
            return "replica_or_token_capacity"
        runtime = self._runtimes.get(pinned)
        if runtime is None:
            return "pinned_replica_missing"
        if runtime.cooldown_until > self._clock():
            return "replica_cooldown"
        if runtime.consecutive_failures > 0 and runtime.recovery_probe_in_flight:
            return "replica_recovery_probe"
        if not self._runtime_request_available_locked(runtime, cls):
            return "pinned_replica_concurrency"
        if not self._prefill_tokens_available(
            runtime, waiter.dispatch_input_tokens,
        ):
            return "pinned_prefill_capacity"
        if not self._token_reservation_available(
            runtime, waiter.dispatch_input_tokens,
            waiter.dispatch_output_tokens,
        ):
            return "pinned_token_reservation"
        return "pinned_replica_policy_or_pressure"

    def _selected_waiter_locked(self) -> _PoolWaiter | None:
        """Select from one coherent Scheduling Authority cut without lock convoy.

        Durable VTC/LAS projection may wait behind a cross-process SQLite writer.
        Snapshot local waiter/capacity truth, release ``_cv`` for that read, then
        install the projection only if the local version is unchanged.  One
        refresher owns the authority boundary; peer callers wait on the actual
        projection transition rather than stampeding the reader.
        """
        while True:
            if self._waiter_count == 0:
                return None
            if self._waiter_projection_refreshing:
                self._cv.wait()
                continue

            local_version = self._waiter_selection_version
            known_revision = self._waiter_projection_revision
            cached = (
                self._waiter_selection_cache_version == local_version
                and known_revision is not None
            )
            projection = self._waiter_input_projection
            if projection is None:
                waiters = tuple(self._waiters_by_ticket.values())
                candidates = tuple(
                    self._scheduling_candidate_locked(waiter) for waiter in waiters
                )
                protected_prefix = tuple(
                    0
                    if (
                        waiter.persistent_flow
                        and waiter.scheduling_flow_id in self._reserved_flows
                        and self._active_by_flow.get(waiter.scheduling_flow_id, 0) == 0
                    )
                    else 1
                    for waiter in waiters
                )
                projection = (waiters, candidates, protected_prefix)
                self._waiter_input_projection = projection
            else:
                waiters, candidates, protected_prefix = projection
            now = self._clock()
            self._waiter_projection_refreshing = True
            self._cv.release()
            failure: BaseException | None = None
            revision = known_revision
            keys = None
            try:
                revision, keys = self._scheduling_authority.ordering_keys_at_revision(
                    candidates, now_monotonic=now,
                    known_revision=known_revision if cached else None,
                )
            except BaseException as exc:
                failure = exc
            finally:
                self._cv.acquire()
                self._waiter_projection_refreshing = False
                self._cv.notify_all()

            if failure is not None:
                raise failure
            if local_version != self._waiter_selection_version:
                # Local capacity/queue truth moved while the durable read was
                # outside the mutex. Discard the stale projection and retry.
                continue
            if self._waiter_count == 0:
                return None
            if keys is None:
                ticket = self._waiter_selection_cache_ticket
                return (
                    None if ticket is None
                    else self._waiters_by_ticket.get(ticket)
                )
            if len(keys) != len(waiters):
                raise RuntimeError(
                    "Scheduling Authority returned incomplete model ranking"
                )

            ranked = tuple(
                (waiter, (prefix, *key))
                for waiter, prefix, key in zip(
                    waiters, protected_prefix, keys, strict=True
                )
            )
            # Rebuild both disposable heaps from the same coherent batch cut.
            # This preserves observability/debug invariants while avoiding any
            # per-row durable authority calls during heap maintenance.
            flow_heaps: dict[str, list[tuple[tuple[int | float, ...], int]]] = {}
            for waiter, key in ranked:
                flow_heaps.setdefault(waiter.owner_id, []).append((key, waiter.ticket))
            for heap in flow_heaps.values():
                heapq.heapify(heap)
            self._waiter_flow_heaps_by_owner = flow_heaps
            owner_heads: dict[str, tuple[_PoolWaiter, tuple[int | float, ...]]] = {}
            owner_heap: list[tuple[tuple[int | float, ...], int]] = []
            for owner_id, heap in flow_heaps.items():
                key, ticket = heap[0]
                waiter = self._waiters_by_ticket[ticket]
                owner_heads[owner_id] = (waiter, key)
                owner_heap.append((key, ticket))
            heapq.heapify(owner_heap)
            self._waiter_owner_heap = owner_heap
            selected = min(
                owner_heads.values(),
                key=lambda row: row[1],
                default=None,
            )
            selected_waiter = None if selected is None else selected[0]
            if (
                selected_waiter is not None
                and not self._dispatch_waiter_feasible_locked(selected_waiter)
            ):
                blocked_head = selected_waiter
                feasible = (
                    (waiter, key)
                    for waiter, key in ranked
                    if self._dispatch_waiter_feasible_locked(waiter)
                )
                row = min(feasible, key=lambda item: item[1], default=None)
                selected_waiter = None if row is None else row[0]
                if selected_waiter is not None and selected_waiter is not blocked_head:
                    selected_waiter.diagnostics.bypassed_ineligible_heads += 1

            # Generation and keys come from the same authority read cut.
            # Local mutations invalidate input projections; remote service
            # transitions replace only the ranking of those immutable inputs.
            self._waiter_projection_revision = revision
            self._waiter_selection_cache_version = local_version
            self._waiter_selection_cache_ticket = (
                None if selected_waiter is None else selected_waiter.ticket
            )
            return selected_waiter

    def _wait_for_waiter_signal_locked(
        self,
        waiter: _PoolWaiter,
        *,
        timeout_seconds: float | None = None,
        reason: str = "physical_continuity_wait",
    ) -> None:
        condition = self._waiter_conditions.get(waiter.ticket)
        if condition is None:
            raise RuntimeError("model endpoint waiter condition disappeared")
        if timeout_seconds is not None and (
            isinstance(timeout_seconds, bool)
            or not isinstance(timeout_seconds, (int, float))
            or not math.isfinite(float(timeout_seconds))
            or float(timeout_seconds) < 0
        ):
            raise ValueError("model endpoint waiter timeout must be finite and non-negative")
        started = self._clock()
        try:
            condition.wait(
                None if timeout_seconds is None else float(timeout_seconds)
            )
        finally:
            duration = max(0.0, self._clock() - started)
            by_reason = waiter.diagnostics.wait_reason_seconds
            by_reason[reason] = by_reason.get(reason, 0.0) + duration

    def _notify_selected_waiter_locked(self) -> None:
        if self._waiter_count == 0:
            return
        # Grant/finish/prefill/cooldown/pressure are all capacity events.
        # Cached feasibility from the previous physical state is not truth.
        self._invalidate_waiter_selection_locked()
        selected = self._selected_waiter_locked()
        if selected is None:
            return
        condition = self._waiter_conditions.get(selected.ticket)
        if condition is None:
            raise RuntimeError("model endpoint selected waiter condition disappeared")
        condition.notify()

    def _notify_all_waiters_locked(self) -> None:
        # Capacity changes can turn an Authority-denied fair head into an
        # eligible one. Wake + cache invalidation form one atomic transition
        # under the same Condition lock; otherwise a stale None selection
        # will survive a committed capacity epoch and strand live requests.
        self._invalidate_waiter_selection_locked()
        for condition in tuple(self._waiter_conditions.values()):
            condition.notify()

    def _fresh_pressure_locked(
        self,
        runtime: _ReplicaRuntime,
        now: float,
    ) -> ModelRuntimePressureSnapshot | None:
        snapshot = runtime.pressure_snapshot
        if snapshot is None:
            return None
        age = max(0.0, float(now) - float(snapshot.observed_monotonic))
        if age > self._pressure_snapshot_max_age:
            return None
        return snapshot

    def _owner_worker_debits_locked(
        self,
        owner_id: str,
    ) -> dict[int, int]:
        debits = self._owner_worker_debit_quanta.get(owner_id)
        if debits is None:
            debits = {}
            self._owner_worker_debit_quanta[owner_id] = debits
        return debits

    def _owner_worker_deficit_locked(
        self,
        owner_id: str,
        worker_index: int,
    ) -> int:
        debits = self._owner_worker_debit_quanta.get(owner_id)
        debit = 0 if debits is None else debits.get(worker_index, 0)
        return self._owner_worker_credit_quanta.get(owner_id, 0) - debit

    def _owner_worker_deficit_snapshot_locked(
        self,
        owner_id: str,
    ) -> tuple[int, ...]:
        credit = self._owner_worker_credit_quanta.get(owner_id, 0)
        debits = self._owner_worker_debit_quanta.get(owner_id)
        if debits is None:
            return (credit,) * len(self._deployment_by_bit_index)
        return tuple(
            credit - debits.get(index, 0)
            for index in range(len(self._deployment_by_bit_index))
        )

    def _longest_prefix_workers_locked(
        self,
        input_token_ids: tuple[int, ...],
    ) -> tuple[int, int]:
        if self._single_replica:
            return self._all_replica_mask, 0
        return self._token_prefix_residency.longest_prefix(
            input_token_ids
        )

    def _refill_owner_worker_deficits_locked(
        self,
        owner_id: str,
        *,
        maximum_eligible_deficit: int | None = None,
    ) -> None:
        maximum = maximum_eligible_deficit
        if maximum is None:
            snapshot = self._owner_worker_deficit_snapshot_locked(owner_id)
            maximum = max(snapshot, default=0)
        if maximum > 0:
            return
        quantum = self._worker_deficit_quantum_quanta
        rounds = (-maximum // quantum) + 1
        self._owner_worker_credit_quanta[owner_id] = (
            self._owner_worker_credit_quanta.get(owner_id, 0)
            + rounds * quantum
        )

    def _charge_worker_deficit_locked(
        self,
        owner_id: str,
        deployment_id: str,
        *,
        input_tokens: int,
        requested_output_tokens: int,
    ) -> None:
        index = self._worker_index_by_deployment[deployment_id]
        debit = self._prefill_service_quanta(input_tokens)
        if requested_output_tokens:
            debit += self._output_service_quanta(
                requested_output_tokens
            )
        debits = self._owner_worker_debits_locked(owner_id)
        debits[index] = debits.get(index, 0) + debit

    def _reconcile_worker_service_deficit_locked(
        self,
        owner_id: str,
        deployment_id: str,
        *,
        charged_input_tokens: int,
        observed_input_tokens: int | None,
        cached_input_tokens: int | None,
        output_tokens: int | None,
        reserved_output_tokens: int,
    ) -> None:
        """Reconcile admission reservation to observed provider service.

        Admission debits are based on estimated/reserved input and output
        tokens. Provider receipts report the actual prompt token count and the
        subset served from prefix cache. These are intentionally different
        accounting domains and therefore must never be compared directly.

        Missing provider usage remains conservative: charged input is treated
        as observed input and missing output usage retains the full reserved
        output debit.
        """

        observed_input = (
            charged_input_tokens
            if observed_input_tokens is None
            else observed_input_tokens
        )
        cached_input = (
            0 if cached_input_tokens is None else cached_input_tokens
        )
        # Provider response contracts require cached tokens to be part of the
        # observed prompt. Keep this invariant local as a defensive boundary,
        # but do not compare cache hits with the admission estimate.
        if cached_input > observed_input:
            raise ValueError(
                "cached input tokens cannot exceed observed input tokens"
            )
        actual_prefill_tokens = max(0, observed_input - cached_input)
        actual_output_tokens = (
            reserved_output_tokens
            if output_tokens is None
            else output_tokens
        )

        reserved_service = (
            self._prefill_service_quanta(charged_input_tokens)
            + self._output_service_quanta(reserved_output_tokens)
        )
        actual_service = (
            self._prefill_service_quanta(actual_prefill_tokens)
            + self._output_service_quanta(actual_output_tokens)
        )
        delta = reserved_service - actual_service
        if delta == 0:
            return

        # q += delta is equivalent to debit -= delta while owner_credit stays
        # unchanged.
        index = self._worker_index_by_deployment[deployment_id]
        debits = self._owner_worker_debits_locked(owner_id)
        updated = debits.get(index, 0) - delta
        if updated:
            debits[index] = updated
        else:
            debits.pop(index, None)

    @staticmethod
    def _normalized_input_token_ids(
        input_token_ids: tuple[int, ...] | None,
        *,
        input_tokens: int,
    ) -> tuple[int, ...]:
        if input_token_ids is None:
            return ()
        if type(input_token_ids) is not tuple:
            raise TypeError(
                "model endpoint input_token_ids must be a tuple of "
                "non-negative integers or None"
            )
        for token in input_token_ids:
            if type(token) is not int or token < 0:
                raise TypeError(
                    "model endpoint input_token_ids must be a tuple of "
                    "non-negative integers or None"
                )
        if input_token_ids and len(input_token_ids) != input_tokens:
            raise ValueError(
                "model endpoint token IDs must exactly match input_tokens"
            )
        if not input_token_ids and input_tokens != 0:
            # Missing token provenance is allowed for operational/canary
            # traffic, but it carries no locality claim.
            return ()
        return input_token_ids

    @staticmethod
    def _normalized_input_tokens(input_tokens: int | None) -> int:
        if input_tokens is None:
            return 0
        if type(input_tokens) is not int or input_tokens <= 0:
            raise ValueError(
                "model endpoint input_tokens must be a positive integer or None"
            )
        return input_tokens

    @staticmethod
    def _normalized_requested_output_tokens(
        requested_output_tokens: int | None,
    ) -> int:
        if requested_output_tokens is None:
            return 0
        if (
            type(requested_output_tokens) is not int
            or requested_output_tokens <= 0
        ):
            raise ValueError(
                "model endpoint requested_output_tokens must be a positive "
                "integer or None"
            )
        return requested_output_tokens

    @staticmethod
    def _prefill_tokens_available(
        runtime: _ReplicaRuntime,
        input_tokens: int,
    ) -> bool:
        if input_tokens <= 0 or runtime.max_prefill_queued_tokens is None:
            return True
        if runtime.prefill_tokens_in_flight == 0:
            return True
        return (
            runtime.prefill_tokens_in_flight + input_tokens
            <= runtime.max_prefill_queued_tokens
        )

    @staticmethod
    def _token_reservation_available(
        runtime: _ReplicaRuntime,
        input_tokens: int,
        requested_output_tokens: int,
    ) -> bool:
        budget = runtime.max_prefill_queued_tokens
        if budget is None:
            return True
        requested = input_tokens + requested_output_tokens
        if requested <= 0:
            return True
        # A single request may consume the whole qualified window; admitting it
        # alone preserves progress while still preventing aggregate overcommit.
        if runtime.token_reservation_in_flight == 0:
            return True
        return runtime.token_reservation_in_flight + requested <= budget

    def _release_prefill_tokens(
        self,
        runtime: _ReplicaRuntime,
        input_tokens: int,
    ) -> None:
        if input_tokens <= 0:
            return
        with self._cv:
            if runtime.prefill_tokens_in_flight < input_tokens:
                raise RuntimeError(
                    "model endpoint prefill-token accounting underflow"
                )
            runtime.prefill_tokens_in_flight -= input_tokens
            self._notify_selected_waiter_locked()

    @staticmethod
    def _runtime_request_limit_locked(
        runtime: _ReplicaRuntime,
        admission_class: _FlowAdmissionClass,
    ) -> int:
        normal_limit = min(
            runtime.capacity,
            runtime.adaptive_window.limit,
        )
        if admission_class is _FlowAdmissionClass.BORROWER:
            return normal_limit if runtime.preemptive_borrowing else 0
        if (
            admission_class is _FlowAdmissionClass.PROTECTED_RETURN
            and runtime.preemptive_borrowing
        ):
            return normal_limit + runtime.isolation_limit
        return normal_limit

    @classmethod
    def _runtime_request_available_locked(
        cls,
        runtime: _ReplicaRuntime,
        admission_class: _FlowAdmissionClass,
    ) -> bool:
        return (
            runtime.in_flight
            < cls._runtime_request_limit_locked(
                runtime,
                admission_class,
            )
        )

    def _selection_candidate_locked(
        self,
        input_token_ids: tuple[int, ...],
        attempted_deployments: frozenset[str],
        input_tokens: int,
        requested_output_tokens: int = 0,
        *,
        owner_id: str,
        admission_class: _FlowAdmissionClass,
        physical_deployment_id: str | None = None,
        probe_only: bool = False,
    ) -> tuple[float, object | None, _ReplicaRuntime | None, int, float | None]:
        """Select one replica under the pool lock without changing admission state."""

        now = self._clock()
        if self._single_replica_default_policy:
            binding = self._single_binding
            runtime = self._single_runtime
            if binding is None or runtime is None:
                raise RuntimeError("single-replica endpoint pool lost its immutable member")
            if physical_deployment_id is not None and binding.deployment_id != physical_deployment_id:
                raise RuntimeError("physical model continuation route has drifted")
            if runtime.cooldown_until > now:
                return now, None, None, 0, runtime.cooldown_until
            if (
                runtime.consecutive_failures > 0
                and runtime.recovery_probe_in_flight
            ):
                return now, None, None, 0, None
            if not self._runtime_request_available_locked(
                runtime,
                admission_class,
            ):
                return now, None, None, 0, None
            if not self._prefill_tokens_available(runtime, input_tokens):
                return now, None, None, 0, None
            if not self._token_reservation_available(
                runtime,
                input_tokens,
                requested_output_tokens,
            ):
                return now, None, None, 0, None
            request_limit = self._runtime_request_limit_locked(
                runtime,
                admission_class,
            )
            if runtime.in_flight < request_limit and not probe_only:
                worker_deficit = self._owner_worker_deficit_locked(owner_id, 0)
                if worker_deficit <= 0:
                    self._refill_owner_worker_deficits_locked(
                        owner_id,
                        maximum_eligible_deficit=worker_deficit,
                    )
            cost_scope = current_runtime_cost_scope()
            if cost_scope is not None:
                cost_scope.set_scale("model_replica_candidates", 1)
                cost_scope.add_work("model_replica_candidates_examined", 1)
            return now, binding, runtime, 0, None

        next_cooling_until: float | None = None
        longest_prefix_mask, longest_prefix_depth = (
            self._longest_prefix_workers_locked(input_token_ids)
        )
        for selection_pass in range(2):
            candidate_count = 0
            maximum_dispatchable_deficit: int | None = None

            def candidate_stream():
                nonlocal next_cooling_until
                nonlocal candidate_count
                nonlocal maximum_dispatchable_deficit
                for deployment_id, runtime in self._runtimes.items():
                    if physical_deployment_id is not None and deployment_id != physical_deployment_id:
                        continue
                    if runtime.cooldown_until > now:
                        next_cooling_until = (
                            runtime.cooldown_until
                            if next_cooling_until is None
                            else min(
                                next_cooling_until,
                                runtime.cooldown_until,
                            )
                        )
                        continue
                    if (
                        runtime.consecutive_failures > 0
                        and runtime.recovery_probe_in_flight
                    ):
                        continue
                    if not self._runtime_request_available_locked(
                        runtime,
                        admission_class,
                    ):
                        continue
                    if not self._prefill_tokens_available(
                        runtime,
                        input_tokens,
                    ):
                        continue
                    if not self._token_reservation_available(
                        runtime,
                        input_tokens,
                        requested_output_tokens,
                    ):
                        continue

                    bit = self._replica_bit_by_deployment[deployment_id]
                    worker_index = bit.bit_length() - 1
                    worker_deficit = self._owner_worker_deficit_locked(
                        owner_id,
                        worker_index,
                    )
                    request_limit = self._runtime_request_limit_locked(
                        runtime,
                        admission_class,
                    )
                    if runtime.in_flight < request_limit:
                        maximum_dispatchable_deficit = (
                            worker_deficit
                            if maximum_dispatchable_deficit is None
                            else max(
                                maximum_dispatchable_deficit,
                                worker_deficit,
                            )
                        )

                    binding = self._bindings[deployment_id]
                    is_longest_prefix = bool(longest_prefix_mask & bit)
                    deepest = (
                        longest_prefix_depth
                        if is_longest_prefix
                        else 0
                    )
                    affinity_score = (
                        0.0
                        if not input_token_ids or deepest == 0
                        else deepest / len(input_token_ids)
                    )
                    pressure = self._fresh_pressure_locked(runtime, now)
                    candidate_count += 1
                    yield ModelEndpointReplicaSelectionCandidate(
                        deployment_id=binding.deployment_id,
                        capacity=request_limit,
                        in_flight=runtime.in_flight,
                        completed=runtime.completed,
                        failures=runtime.failures,
                        selections=runtime.selections,
                        consecutive_failures=(
                            runtime.consecutive_failures
                        ),
                        ewma_latency_seconds=(
                            runtime.ewma_latency_seconds
                        ),
                        last_selected_sequence=(
                            runtime.last_selected_sequence
                        ),
                        attempted_in_dispatch=(
                            binding.deployment_id
                            in attempted_deployments
                        ),
                        prefix_affinity_score=affinity_score,
                        prefix_affinity_depth=deepest,
                        runtime_requests_waiting=(
                            0
                            if pressure is None
                            else pressure.requests_waiting
                        ),
                        runtime_gpu_kv_cache_usage=(
                            0.0
                            if pressure is None
                            else pressure.gpu_kv_cache_usage
                        ),
                        runtime_pressure_observed=pressure is not None,
                        worker_deficit_positive=worker_deficit > 0,
                        global_longest_prefix_match=is_longest_prefix,
                    )

            try:
                selected_id = self._selection_policy.select(
                    candidate_stream()
                )
            except ValueError as exc:
                if candidate_count == 0:
                    return (
                        now,
                        None,
                        None,
                        0,
                        next_cooling_until,
                    )
                if isinstance(
                    self._selection_policy, PinnedReplicaSelectionPolicy
                ):
                    pinned_id = self._selection_policy.deployment_id
                    pinned_runtime = self._runtimes.get(pinned_id)
                    if (
                        pinned_runtime is not None
                        and pinned_runtime.cooldown_until <= now
                        and not (
                            pinned_runtime.consecutive_failures > 0
                            and pinned_runtime.recovery_probe_in_flight
                        )
                    ):
                        # The placement constraint is valid and healthy but is
                        # temporarily saturated. Preserve the pin and apply
                        # backpressure; never fall back to another replica.
                        return (
                            now,
                            None,
                            None,
                            0,
                            next_cooling_until,
                        )
                raise ModelEndpointPoolUnavailable(
                    "model endpoint selection policy chose an "
                    "unavailable replica"
                ) from exc

            binding = self._bindings.get(selected_id)
            runtime = self._runtimes.get(selected_id)
            if (
                binding is None
                or runtime is None
                or runtime.cooldown_until > now
                or (
                    runtime.consecutive_failures > 0
                    and runtime.recovery_probe_in_flight
                )
                or not self._runtime_request_available_locked(
                    runtime,
                    admission_class,
                )
                or not self._prefill_tokens_available(
                    runtime,
                    input_tokens,
                )
                or not self._token_reservation_available(
                    runtime,
                    input_tokens,
                    requested_output_tokens,
                )
            ):
                raise ModelEndpointPoolUnavailable(
                    "model endpoint selection policy chose an "
                    f"unavailable replica: {selected_id!r}"
                )

            bit = self._replica_bit_by_deployment[selected_id]
            worker_index = bit.bit_length() - 1
            if (
                runtime.in_flight < runtime.adaptive_window.limit
                and self._owner_worker_deficit_locked(
                    owner_id,
                    worker_index,
                ) <= 0
                and selection_pass == 0
                and not probe_only
            ):
                if maximum_dispatchable_deficit is None:
                    raise RuntimeError(
                        "dispatchable model replica deficit was not observed"
                    )
                self._refill_owner_worker_deficits_locked(
                    owner_id,
                    maximum_eligible_deficit=(
                        maximum_dispatchable_deficit
                    ),
                )
                continue

            return (
                now,
                binding,
                runtime,
                (
                    longest_prefix_depth
                    if longest_prefix_mask
                    & self._replica_bit_by_deployment[selected_id]
                    else 0
                ),
                None,
            )

        raise RuntimeError(
            "model worker deficit refill did not produce a selectable replica"
        )

    def _total_adaptive_capacity_locked(self) -> int:
        return sum(
            runtime.adaptive_window.limit
            for runtime in self._runtimes.values()
        )

    def _protected_flow_occupancy_locked(self) -> int:
        """Active protected service only; idle affinity claims consume no work slot."""

        protected_in_flight = 0
        for runtime in self._runtimes.values():
            if (
                runtime.borrowed_in_flight < 0
                or runtime.borrowed_in_flight > runtime.in_flight
            ):
                raise RuntimeError(
                    "model endpoint borrowed in-flight accounting drift"
                )
            protected_in_flight += (
                runtime.in_flight - runtime.borrowed_in_flight
            )
        return protected_in_flight

    def _idle_reserved_flow_count_locked(self) -> int:
        """Continuity owners awaiting work; affinity truth, not active capacity."""

        return sum(
            1
            for flow_id in self._reserved_flows
            if self._active_by_flow.get(flow_id, 0) == 0
        )

    def _flow_admission_class_locked(
        self,
        flow_id: str,
        *,
        persistent_flow: bool,
        preemptive_eligible: bool,
    ) -> _FlowAdmissionClass | None:
        # A caller that already relinquished its lifetime cannot reacquire
        # physical work while its last borrower or durable release converges.
        if flow_id in self._pending_flow_releases or flow_id in self._retiring_flow_releases:
            return None
        is_reserved_return = (
            persistent_flow
            and flow_id in self._reserved_flows
            and self._active_by_flow.get(flow_id, 0) == 0
        )
        if is_reserved_return:
            return _FlowAdmissionClass.PROTECTED_RETURN

        total_capacity = self._total_adaptive_capacity_locked()
        protected_occupancy = self._protected_flow_occupancy_locked()
        reservation_available = not (
            persistent_flow
            and flow_id not in self._reserved_flows
            and self._physical_continuity_controllers is None
            and len(self._reserved_flows)
            >= self._persistent_flow_capacity
        )
        physical_in_flight = sum(
            runtime.in_flight for runtime in self._runtimes.values()
        )
        # Borrowing is deliberately outside lifetime reservation capacity.
        # A non-persistent request, or a persistent request that cannot obtain a
        # new lifetime entitlement, may use service capacity left idle by an
        # already-reserved owner.  It remains lower priority so a measured-safe
        # protected return can reclaim the isolation headroom.
        if (
            preemptive_eligible
            and self._preemptive_borrowing_enabled
            and self._idle_reserved_flow_count_locked() > 0
            and physical_in_flight < total_capacity
            and (not persistent_flow or not reservation_available)
        ):
            return _FlowAdmissionClass.BORROWER

        if (
            protected_occupancy < total_capacity
            and reservation_available
        ):
            return _FlowAdmissionClass.NORMAL
        return None

    def _reserve_flow_for_admission_locked(
        self,
        *,
        owner_id: str,
        flow_id: str,
        persistent_flow: bool,
        admission_class: _FlowAdmissionClass,
    ) -> None:
        if not isinstance(admission_class, _FlowAdmissionClass):
            raise TypeError(
                "model flow admission requires internal admission class"
            )
        if (
            admission_class is _FlowAdmissionClass.BORROWER
            and not self._preemptive_borrowing_enabled
        ):
            raise RuntimeError(
                "model flow borrower admitted without preemptive qualification"
            )
        if (
            persistent_flow
            and self._physical_continuity_controllers is not None
            and flow_id not in self._physical_flow_claims
            and admission_class is not _FlowAdmissionClass.BORROWER
        ):
            raise RuntimeError(
                "model lifetime must obtain a Resource Authority continuity claim before dispatch"
            )
        if (
            persistent_flow
            and admission_class is not _FlowAdmissionClass.BORROWER
        ):
            existing_owner = self._flow_owner.get(flow_id)
            if existing_owner is not None and existing_owner != owner_id:
                raise RuntimeError(
                    "model flow changed execution owner while still reserved"
                )
            self._flow_owner[flow_id] = owner_id
            self._reserved_flows.add(flow_id)
            self._pending_flow_releases.discard(flow_id)
        self._active_by_flow[flow_id] = (
            self._active_by_flow.get(flow_id, 0) + 1
        )

    @contextmanager
    def _observe_physical_capacity(self, controllers):
        """Wake the selected physical waiter on committed Authority changes.

        Subscriptions precede the first authoritative attempt, preventing
        missed-release gaps between admission and Condition.wait. The durable
        feed retains bounded recovery if external notifications are lost.
        """
        unique = tuple(dict.fromkeys(controllers))

        def wake() -> None:
            with self._cv:
                self._physical_capacity_epoch += 1
                self._notify_all_waiters_locked()

        with ExitStack() as stack:
            event_driven = bool(unique)
            for controller in unique:
                unsubscribe = controller.subscribe_capacity_change(wake)
                if unsubscribe is None:
                    event_driven = False
                else:
                    stack.callback(unsubscribe)
            yield event_driven

    def _acquire_physical_flow_claim(
        self, *, owner_id: str, flow_id: str,
    ) -> tuple[str, ModelAdmissionLeasePort] | None:
        """Acquire an exact Resource Authority Claim with no local mutex held."""
        controllers = self._physical_continuity_controllers
        if not controllers:
            raise RuntimeError("physical continuity controllers unavailable")
        keys = frozenset(
            key
            for controller in controllers.values()
            for key in (
                controller.physical_continuity_resource_key,
                controller.physical_admission_resource_key,
            )
        )
        # Keep the uncontended path read-only. Only an advisory denial may pay
        # for one exact-resource orphan reconciliation; this closes the crash
        # liveness gap without placing normal admission on the Authority writer.
        for recovery_round in range(2):
            snapshot = next(iter(controllers.values())).physical_bundle_snapshot(
                keys
            )
            occupied = {deployment_id: 0 for deployment_id in controllers}
            reserved = {deployment_id: 0 for deployment_id in controllers}
            for row in snapshot.claims:
                attrs = dict(claim_field(row, "attributes") or {})
                deployment_id = attrs.get("deployment_id")
                if deployment_id not in controllers:
                    continue
                kind = attrs.get("kind")
                if kind == "model-continuity-slot":
                    reserved[deployment_id] += 1
                    occupied[deployment_id] += 1
                elif kind == "model-admission-slot":
                    occupied[deployment_id] += 1
                # A continuity borrow consumes its parent's reserved entitlement,
                # not an additional physical concurrency slot.
            pinned_id = (
                self._selection_policy.deployment_id
                if isinstance(self._selection_policy, PinnedReplicaSelectionPolicy)
                else None
            )
            eligible = (
                deployment_id
                for deployment_id, controller in controllers.items()
                if (pinned_id is None or deployment_id == pinned_id)
                and reserved[deployment_id] < controller.physical_continuity_capacity
                and occupied[deployment_id] < controller.capacity
            )
            ordered = sorted(
                eligible,
                key=lambda deployment_id: (
                    occupied[deployment_id] / controllers[deployment_id].capacity,
                    reserved[deployment_id]
                    / controllers[deployment_id].physical_continuity_capacity,
                    canonical_digest((flow_id, deployment_id)),
                ),
            )
            for deployment_id in ordered:
                claim = controllers[deployment_id].try_reserve_continuity(
                    owner_id=owner_id, flow_id=flow_id,
                )
                if claim is not None:
                    return deployment_id, claim
            if recovery_round == 0 and next(iter(controllers.values())).reconcile_physical_bundle_orphans(keys):
                continue
            break
        # The snapshot is advisory; the Authority's atomic commit is truth.
        return None

    def _retire_flow_outside_lock(self, flow_id: str) -> None:
        """Physical release outside the shared scheduling mutex, fail closed.

        The reserved-flow projection stays occupied until the Resource
        Authority has committed release. Concurrent retirement attempts join
        the same per-flow condition, never double-release the physical claim.
        """
        with self._cv:
            while flow_id in self._retiring_flow_releases:
                self._cv.wait()
            if flow_id not in self._reserved_flows:
                return
            if self._active_by_flow.get(flow_id, 0):
                self._pending_flow_releases.add(flow_id)
                return
            self._pending_flow_releases.add(flow_id)
            self._retiring_flow_releases.add(flow_id)
            physical = self._physical_flow_claims.get(flow_id)
        try:
            if physical is not None:
                physical[1].release()
        except BaseException:
            with self._cv:
                self._retiring_flow_releases.remove(flow_id)
                # Keep pending, reserved and affine Claim projections on
                # failure. A later explicit retirement can safely retry.
                self._cv.notify_all()
            raise
        with self._cv:
            if physical is not None:
                if self._physical_flow_claims.get(flow_id) is not physical:
                    raise RuntimeError("model physical retirement claim generation drift")
                del self._physical_flow_claims[flow_id]
            owner_id = self._flow_owner.pop(flow_id, None)
            self._reserved_flows.remove(flow_id)
            self._pending_flow_releases.discard(flow_id)
            self._retiring_flow_releases.remove(flow_id)
            # Per-flow duplicate retirement joins self._cv directly, whereas
            # model dispatch queues own ticket-specific Conditions. Wake both
            # populations in the same committed retirement cut.
            self._cv.notify_all()
            if owner_id is not None:
                self._push_owner_head_locked(owner_id)
            self._invalidate_waiter_selection_locked()
            self._notify_all_waiters_locked()

    @staticmethod
    def _atomic_flow_bundle_placement(pools, *, flow_id: str):
        """Exact physical cut plus load-aware augmenting-path assignment, no partial holds.

        The same flow has an exclusive continuity identity per deployment.
        Therefore its pools must claim distinct deployment identities even
        when a deployment has multiple free physical concurrency slots.
        """
        options = []
        controllers = {}
        keys = set()
        for pool in pools:
            entries = pool._physical_continuity_controllers
            if not entries:
                raise RuntimeError("atomic model flow requires physical Resource Authority")
            choices = tuple(sorted(entries))
            options.append(choices)
            for dep in choices:
                c = entries[dep]
                previous = controllers.setdefault(dep, c)
                if (
                    previous.physical_continuity_capacity != c.physical_continuity_capacity
                    or previous.capacity != c.capacity
                    or previous.physical_continuity_resource_key != c.physical_continuity_resource_key
                ):
                    raise RuntimeError("model continuity certification drift across pools")
                keys.add(c.physical_continuity_resource_key)
                keys.add(c.physical_admission_resource_key)
        snapshot = next(iter(controllers.values())).physical_bundle_snapshot(
            frozenset(keys)
        )
        occupied = {dep: 0 for dep in controllers}
        continuous = {dep: 0 for dep in controllers}
        for claim in snapshot.claims:
            attrs = dict(claim_field(claim, "attributes") or {})
            dep = attrs.get("deployment_id")
            kind = attrs.get("kind")
            if dep not in controllers:
                continue
            if kind == "model-continuity-slot":
                continuous[dep] += 1
                occupied[dep] += 1
            elif kind == "model-admission-slot":
                occupied[dep] += 1
        available = {
            dep: max(0, min(
                controller.physical_continuity_capacity - continuous[dep],
                controller.capacity - occupied[dep],
            ))
            for dep, controller in controllers.items()
        }
        # Integral maximum flow in a bipartite graph: role -> replica slots.
        # Preserve complete augmenting-path feasibility, but prefer the least
        # loaded *prospective* physical deployment on each search step. The
        # matched counts include earlier roles in this bundle, so one large
        # bundle cannot first-fit all of its roles onto the same idle GPU.
        # Tie identities are fixed per flow, independent of Python hash seeds.
        matched: dict[str, list[int]] = {}
        tie = {
            (index, dep): canonical_digest((flow_id, index, dep))
            for index, choices in enumerate(options)
            for dep in choices
        }

        def augment(index, seen):
            ordered = sorted(
                options[index],
                key=lambda dep: (
                    (occupied[dep] + len(matched.get(dep, ())))
                    / controllers[dep].capacity,
                    (continuous[dep] + len(matched.get(dep, ())))
                    / controllers[dep].physical_continuity_capacity,
                    tie[index, dep],
                ),
            )
            for dep in ordered:
                if available[dep] <= 0 or dep in seen:
                    continue
                seen.add(dep)
                members = matched.setdefault(dep, [])
                if len(members) < available[dep]:
                    members.append(index)
                    return True
                for position, displaced in enumerate(tuple(members)):
                    if augment(displaced, seen):
                        members[position] = index
                        return True
            return False

        for index in sorted(range(len(pools)), key=lambda i: (len(options[i]), i)):
            if not augment(index, set()):
                return None
        result = [None] * len(pools)
        for dep, indexes in matched.items():
            for index in indexes:
                result[index] = (
                    dep, pools[index]._physical_continuity_controllers[dep]
                )
        if any(item is None for item in result):
            raise RuntimeError("model physical bundle assignment incomplete")
        return tuple(result)

    def reserve_flow_bundle(
        self, pools, owner_id: str, flow_id: str, *,
        deadline: Deadline | None, cancellation: CancellationTokenPort | None,
    ) -> None:
        """Reserve every Method model role in one linearizable Authority cut.

        No flow can hold its first role while blocked acquiring a later role.
        Pool locks protect only ephemeral dispatch projections; Resource
        Authority alone decides physical feasibility and commits all grants.
        """
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError("bundle owner_id must be non-empty")
        if type(flow_id) is not str or not flow_id.strip():
            raise ValueError("bundle flow_id must be non-empty")
        if deadline is not None and not isinstance(deadline, Deadline):
            raise TypeError("bundle deadline must be Deadline")
        pools = tuple(dict.fromkeys(pools))
        if not pools or self not in pools:
            raise ValueError("bundle requires its coordinating pool")
        if any(not isinstance(pool, type(self)) for pool in pools):
            raise TypeError("bundle pools must share one physical model implementation")
        if len(pools) == 1:
            return self.reserve_flow(
                owner_id, flow_id, deadline=deadline, cancellation=cancellation,
            )
        for pool in pools:
            if not pool._physical_continuity_controllers:
                raise RuntimeError("model bundle requires qualified physical controllers")
        return self._reserve_flow_bundle_coordinated(
            pools, owner_id, flow_id, deadline=deadline,
            cancellation=cancellation,
        )

    def _reserve_flow_bundle_coordinated(
        self, pools, owner_id, flow_id, *, deadline, cancellation,
    ):
        # The unified pool waiter determines admission order. Physical
        # Resource Authority supplies feasibility, not a second FIFO.
        with self._cv:
            if self._closed:
                raise ModelEndpointPoolUnavailable("model bundle pool closed")
            waiter = _PoolWaiter(
                self._next_waiter_ticket,
                owner_id,
                self._clock(),
                flow_id,
                True,
                None,
                0.0,
            )
            self._next_waiter_ticket += 1
            self._enqueue_waiter_locked(waiter)
        controllers = tuple(
            controller
            for pool in pools
            for controller in pool._physical_continuity_controllers.values()
        )
        try:
            with self._observe_physical_capacity(controllers) as event_driven, wake_on_cancellation(
                cancellation, self._cv,
                notify_waiters=self._notify_all_waiters_locked,
            ):
                return self._reserve_flow_bundle_commit(
                    pools, owner_id, flow_id, waiter,
                    deadline=deadline, cancellation=cancellation,
                    event_driven=event_driven,
                )
        finally:
            with self._cv:
                self._remove_waiter_locked(waiter)
                self._notify_selected_waiter_locked()

    def _reserve_flow_bundle_commit(
        self, pools, owner_id, flow_id, waiter, *, deadline, cancellation,
        event_driven,
    ):
        """Two-phase exact bundle admission, never holding replica pool locks
        across cross-process Resource Authority commits or lease adoption.

        `_claiming_flows` is the provisional cut. It fences dispatch, terminal
        close and competing admission until the complete Authority-owned
        bundle can be published atomically to every participating replica.
        """
        ordered = tuple(sorted(pools, key=id))

        def acquire_all():
            stack = ExitStack()
            try:
                for pool in ordered:
                    stack.enter_context(pool._cv)
            except BaseException:
                stack.close()
                raise
            return stack

        while True:
            if cancellation is not None:
                cancellation.checkpoint()
            if deadline is not None and deadline.expired:
                raise TimeoutError("model atomic bundle admission deadline expired")
            with self._cv:
                if self._selected_waiter_locked() is not waiter:
                    self._wait_for_waiter_signal_locked(
                        waiter,
                        timeout_seconds=(
                            None if deadline is None else deadline.remaining_seconds
                        ),
                    )
                    continue
                selected_version = self._waiter_selection_version
                observed_capacity_epoch = self._physical_capacity_epoch
            # Advisory physical feasibility may touch SQLite; keep all model
            # pool locks free while the Resource Authority takes its snapshot.
            placement = self._atomic_flow_bundle_placement(
                pools, flow_id=flow_id,
            )
            orphan_expiry_recheck = None
            if placement is None:
                # The read-only placement cut deliberately stays off the
                # Authority writer fast path. If apparent capacity is exhausted,
                # recover dead owners for exactly the resources in this bundle
                # before sleeping for a future commit. Otherwise expired claims
                # can make the advisory cut permanently full while no writer is
                # left alive to emit the commit that would wake this waiter.
                controllers = tuple(
                    controller
                    for pool in pools
                    for controller in pool._physical_continuity_controllers.values()
                )
                keys = frozenset(
                    key
                    for controller in controllers
                    for key in (
                        controller.physical_continuity_resource_key,
                        controller.physical_admission_resource_key,
                    )
                )
                recovered = controllers[0].reconcile_physical_bundle_orphans(keys)
                if recovered:
                    placement = self._atomic_flow_bundle_placement(
                        pools, flow_id=flow_id,
                    )
                if placement is None:
                    orphan_expiry_recheck = (
                        controllers[0].physical_bundle_owner_expiry_recheck_seconds(
                            keys
                        )
                    )
            staged = False
            another_generation_claiming = False
            with acquire_all():
                if any(pool._closed for pool in pools):
                    raise ModelEndpointPoolUnavailable("model bundle pool closed")
                # Ranking releases its coordinator mutex for durable reads.
                # Never invoke it while holding peer mutexes: another bundle
                # can acquire the coordinator and wait for one of those peers.
                # Validate the prior single-pool projection in this atomic cut.
                if (
                    self._waiter_projection_refreshing
                    or self._waiter_selection_version != selected_version
                    or self._waiter_selection_cache_version != selected_version
                    or self._waiter_selection_cache_ticket != waiter.ticket
                ):
                    continue
                held = tuple(flow_id in pool._reserved_flows for pool in pools)
                if all(held):
                    if any(pool._flow_owner.get(flow_id) != owner_id for pool in pools):
                        raise RuntimeError("model bundle lifetime owner drift")
                    return
                if any(held):
                    raise RuntimeError("partial model lifetime reservation found")
                if any(flow_id in pool._claiming_flows for pool in pools):
                    # A provisional bundle owns all roles. Release EVERY pool
                    # lock before waiting on its lifecycle wake; Condition.wait
                    # on only the coordinator would otherwise strand peers.
                    another_generation_claiming = True
                elif placement is not None:
                    # Short, atomic provisional state; physical SQLite grant
                    # happens only after releasing *all* shared pool mutexes.
                    for pool in pools:
                        pool._claiming_flows.add(flow_id)
                    staged = True
            if another_generation_claiming:
                with self._cv:
                    self._wait_for_waiter_signal_locked(waiter)
                continue
            if staged:
                assert placement is not None
                granted = None
                claims = ()
                leases = []
                publication_succeeded = False
                try:
                    claims = tuple(
                        controller.declare_continuity_claim(
                            owner_id=owner_id,
                            flow_id=f"{flow_id}:role:{index}",
                        )
                        for index, (_dep, controller) in enumerate(placement)
                    )
                    try:
                        granted = placement[0][1].commit_continuity_bundle(claims)
                    except ResourceClaimConflict:
                        # Physical capacity changed after the advisory read;
                        # an epoch/commit-feed notification governs retry.
                        pass
                    if granted is not None:
                        if len(granted) != len(pools):
                            raise RuntimeError("model bundle grant cardinality drift")
                        for (_dep, controller), claim in zip(
                            placement, granted, strict=True,
                        ):
                            leases.append(controller.adopt_continuity_claim(claim))
                        if cancellation is not None:
                            cancellation.checkpoint()
                        if deadline is not None and deadline.expired:
                            raise TimeoutError(
                                "model atomic bundle committed after deadline"
                            )
                        with acquire_all():
                            # Fresh terminal checks cover the interval spent
                            # reacquiring multiple replica locks after the
                            # physical commit, with no premature publication.
                            if cancellation is not None:
                                cancellation.checkpoint()
                            if deadline is not None and deadline.expired:
                                raise TimeoutError(
                                    "model atomic bundle committed after deadline"
                                )
                            if any(pool._closed for pool in pools):
                                raise ModelEndpointPoolUnavailable(
                                    "model bundle pool closed during physical claim"
                                )
                            if any(
                                flow_id not in pool._claiming_flows
                                or flow_id in pool._reserved_flows
                                for pool in pools
                            ):
                                raise RuntimeError(
                                    "model bundle provisional ownership generation drift"
                                )
                            try:
                                for pool, (dep, _controller), lease in zip(
                                    pools, placement, leases, strict=True,
                                ):
                                    pool._physical_flow_claims[flow_id] = (dep, lease)
                                    pool._flow_owner[flow_id] = owner_id
                                    pool._reserved_flows.add(flow_id)
                                    pool._pending_flow_releases.discard(flow_id)
                                for pool in pools:
                                    pool._claiming_flows.remove(flow_id)
                                    pool._cv.notify_all()
                                    pool._notify_all_waiters_locked()
                            except BaseException:
                                for pool in pools:
                                    # Notifier failure must not expose an
                                    # unowned in-progress Authority rollback.
                                    # Re-establish the provisional fencing
                                    # before releasing any replica pool lock.
                                    pool._claiming_flows.add(flow_id)
                                    pool._physical_flow_claims.pop(flow_id, None)
                                    pool._flow_owner.pop(flow_id, None)
                                    pool._reserved_flows.discard(flow_id)
                                    pool._pending_flow_releases.discard(flow_id)
                                raise
                            publication_succeeded = True
                        return
                finally:
                    if not publication_succeeded:
                        cleanup = []
                        if granted is not None:
                            for (_dep, controller), claim in zip(
                                placement, granted, strict=True,
                            ):
                                try:
                                    controller.rollback_continuity_claim(claim)
                                except BaseException as exc:
                                    cleanup.append(exc)
                        if not cleanup:
                            with acquire_all():
                                for pool in pools:
                                    pool._claiming_flows.discard(flow_id)
                                    pool._cv.notify_all()
                                    pool._notify_all_waiters_locked()
                        if cleanup:
                            raise BaseExceptionGroup(
                                "model bundle rollback could not confirm physical release",
                                cleanup,
                            )
            # Either unavailable in the physical snapshot or a competing
            # process won before our atomic commit. Wait on the existing
            # Authority commit feed, not a polling loop or second queue.
            with self._cv:
                if self._physical_capacity_epoch != observed_capacity_epoch:
                    continue
                waiter.diagnostics.physically_denied_epoch = (
                    self._physical_capacity_epoch
                )
                self._notify_selected_waiter_locked()
                fallback = (
                    None if event_driven else min(
                        controller.contention_recheck_seconds
                        for pool in pools
                        for controller in pool._physical_continuity_controllers.values()
                    )
                )
                wake_after = orphan_expiry_recheck
                if fallback is not None:
                    wake_after = (
                        fallback if wake_after is None
                        else min(fallback, wake_after)
                    )
                remaining = (
                    None if deadline is None else deadline.remaining_seconds
                )
                self._wait_for_waiter_signal_locked(
                    waiter,
                    timeout_seconds=(
                        remaining if wake_after is None
                        else wake_after if remaining is None
                        else min(wake_after, remaining)
                    ),
                )
                if fallback is not None or orphan_expiry_recheck is not None:
                    # A timer at a relevant owner-lease boundary is itself a
                    # new physical liveness cut even though no Authority commit
                    # is emitted merely because wall clock passed the expiry.
                    waiter.diagnostics.physically_denied_epoch = None
                    self._notify_selected_waiter_locked()

    def reserve_flow(
        self,
        owner_id: str,
        flow_id: str,
        *,
        deadline: Deadline | None,
        cancellation: CancellationTokenPort | None,
    ) -> None:
        """Reserve one persistent continuity slot before the first request.

        This joins the same endpoint scheduling queue as dispatch, but does not
        create a synthetic request, occupy a replica in-flight slot, or advance
        service/VTC accounting. The first real request returns as a protected
        flow through the normal dispatch path.
        """

        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError(
                "model endpoint reserve_flow requires non-empty owner_id"
            )
        if type(flow_id) is not str or not flow_id.strip():
            raise ValueError(
                "model endpoint reserve_flow requires non-empty flow_id"
            )
        if deadline is not None and not isinstance(deadline, Deadline):
            raise TypeError(
                "model endpoint reserve_flow deadline must be Deadline"
            )
        if cancellation is not None and not (
            hasattr(cancellation, "cancelled")
            and hasattr(cancellation, "reason")
            and callable(getattr(cancellation, "wait", None))
            and callable(getattr(cancellation, "checkpoint", None))
        ):
            raise TypeError(
                "model endpoint reserve_flow cancellation must satisfy "
                "CancellationTokenPort"
            )
        owner_id = owner_id.strip()
        flow_id = flow_id.strip()
        if cancellation is not None:
            cancellation.checkpoint()

        physical_controllers = self._physical_continuity_controllers
        with self._observe_physical_capacity(
            () if physical_controllers is None
            else physical_controllers.values()
        ) as event_driven, wake_on_cancellation(
            cancellation, self._cv,
            notify_waiters=self._notify_all_waiters_locked,
        ), self._cv:
            if self._closed:
                raise ModelEndpointPoolUnavailable(
                    "model endpoint pool is closed"
                )
            while flow_id in self._granting_flows:
                self._cv.wait()
            existing_owner = self._flow_owner.get(flow_id)
            if flow_id in self._reserved_flows:
                if existing_owner != owner_id:
                    raise RuntimeError(
                        "model flow changed execution owner while still reserved"
                    )
                if flow_id in self._pending_flow_releases:
                    raise ModelEndpointPoolUnavailable(
                        "model flow reservation is physically retiring"
                    )
                return

            waiter = _PoolWaiter(
                self._next_waiter_ticket,
                owner_id,
                self._clock(),
                flow_id,
                True,
                # The deadline bounds waiting; it cannot make a physically
                # blocked reservation feasible or change scheduling priority.
                None,
                0.0,
            )
            self._next_waiter_ticket += 1
            self._enqueue_waiter_locked(waiter)
            admitted = False
            try:
                while True:
                    if cancellation is not None:
                        cancellation.checkpoint()
                    if self._closed:
                        raise ModelEndpointPoolUnavailable(
                            "model endpoint pool is closed"
                        )
                    if deadline is not None and deadline.expired:
                        raise TimeoutError(
                            "model persistent-flow reservation deadline expired"
                        )

                    existing_owner = self._flow_owner.get(flow_id)
                    if flow_id in self._reserved_flows:
                        if existing_owner != owner_id:
                            raise RuntimeError(
                                "model flow changed execution owner while reserved"
                            )
                        if flow_id in self._pending_flow_releases:
                            raise ModelEndpointPoolUnavailable(
                                "model flow reservation is physically retiring"
                            )
                        self._remove_waiter_locked(waiter)
                        admitted = True
                        self._notify_selected_waiter_locked()
                        return

                    if (
                        self._selected_waiter_locked() is waiter
                        and (
                            self._physical_continuity_controllers is not None
                            or len(self._reserved_flows) < self._persistent_flow_capacity
                        )
                    ):
                        if self._physical_continuity_controllers is not None:
                            if flow_id in self._claiming_flows:
                                raise RuntimeError(
                                    "concurrent physical Claim acquisition bypassed fair gate"
                                )
                            self._claiming_flows.add(flow_id)
                            observed_epoch = self._physical_capacity_epoch
                            # The selected request has secured the right to
                            # *attempt* admission, not yet a physical slot.
                            # Other independent requests may now use the pool.
                            self._notify_selected_waiter_locked()
                            physical = None
                            acquisition_error: BaseException | None = None
                            self._cv.release()
                            try:
                                physical = self._acquire_physical_flow_claim(
                                    owner_id=owner_id, flow_id=flow_id,
                                )
                            except BaseException as exc:
                                acquisition_error = exc
                            finally:
                                self._cv.acquire()

                            def resolve_claim_error(
                                original: BaseException,
                            ) -> None:
                                cleanup_error: BaseException | None = None
                                if physical is not None:
                                    self._cv.release()
                                    try:
                                        physical[1].release()
                                    except BaseException as exc:
                                        cleanup_error = exc
                                    finally:
                                        self._cv.acquire()
                                if cleanup_error is not None:
                                    # Failed cleanup cannot disappear from the
                                    # lifetime graph. Publish a still-live,
                                    # retiring affine Claim for explicit repair.
                                    self._physical_flow_claims[flow_id] = physical
                                    self._flow_owner[flow_id] = owner_id
                                    self._reserved_flows.add(flow_id)
                                    self._pending_flow_releases.add(flow_id)
                                self._claiming_flows.remove(flow_id)
                                self._cv.notify_all()
                                self._notify_all_waiters_locked()
                                if cleanup_error is not None:
                                    raise BaseExceptionGroup(
                                        "model Claim acquisition cleanup failed",
                                        [original, cleanup_error],
                                    )
                                raise original

                            if acquisition_error is not None:
                                resolve_claim_error(acquisition_error)
                            try:
                                if cancellation is not None:
                                    cancellation.checkpoint()
                                if self._closed:
                                    raise ModelEndpointPoolUnavailable(
                                        "pool closed during Resource Authority Claim"
                                    )
                                if deadline is not None and deadline.expired:
                                    raise TimeoutError(
                                        "model continuity Claim completed after deadline"
                                    )
                            except BaseException as exc:
                                resolve_claim_error(exc)
                            if physical is None:
                                self._claiming_flows.remove(flow_id)
                                self._cv.notify_all()
                                self._notify_all_waiters_locked()
                                # An Authority commit was observed during the
                                # external attempt; re-evaluate immediately.
                                if self._physical_capacity_epoch != observed_epoch:
                                    continue
                                waiter.diagnostics.physically_denied_epoch = (
                                    self._physical_capacity_epoch
                                )
                                self._notify_selected_waiter_locked()
                                controllers = self._physical_continuity_controllers
                                if not controllers:
                                    raise RuntimeError(
                                        "model continuity controllers disappeared"
                                    )
                                keys = frozenset(
                                    key
                                    for controller in controllers.values()
                                    for key in (
                                        controller.physical_continuity_resource_key,
                                        controller.physical_admission_resource_key,
                                    )
                                )
                                expiry_recheck = next(
                                    iter(controllers.values())
                                ).physical_bundle_owner_expiry_recheck_seconds(keys)
                                recheck = (
                                    None if event_driven else min(
                                        controller.contention_recheck_seconds
                                        for controller in controllers.values()
                                    )
                                )
                                wake_after = expiry_recheck
                                if recheck is not None:
                                    wake_after = (
                                        recheck if wake_after is None
                                        else min(recheck, wake_after)
                                    )
                                remaining = (
                                    None if deadline is None
                                    else deadline.remaining_seconds
                                )
                                self._wait_for_waiter_signal_locked(
                                    waiter,
                                    timeout_seconds=(
                                        remaining if wake_after is None
                                        else wake_after if remaining is None
                                        else min(wake_after, remaining)
                                    ),
                                )
                                if recheck is not None or expiry_recheck is not None:
                                    # Lease expiry does not increment the commit
                                    # epoch, so the advisory denial cache must be
                                    # retired when its ownership timer fires.
                                    waiter.diagnostics.physically_denied_epoch = None
                                    self._notify_selected_waiter_locked()
                                continue
                            self._physical_flow_claims[flow_id] = physical
                            self._claiming_flows.remove(flow_id)
                            self._cv.notify_all()
                        self._flow_owner[flow_id] = owner_id
                        self._reserved_flows.add(flow_id)
                        self._pending_flow_releases.discard(flow_id)
                        self._remove_waiter_locked(waiter)
                        admitted = True
                        self._push_owner_head_locked(owner_id)
                        self._invalidate_waiter_selection_locked()
                        self._notify_selected_waiter_locked()
                        return

                    self._wait_for_waiter_signal_locked(
                        waiter,
                        timeout_seconds=(
                            None
                            if deadline is None
                            else deadline.remaining_seconds
                        ),
                    )
            finally:
                if not admitted:
                    self._remove_waiter_locked(waiter)
                    self._notify_selected_waiter_locked()

    def release_flow(self, flow_id: str) -> None:
        """Release one lifetime continuity reservation without guessing by TTL."""

        if type(flow_id) is not str or not flow_id.strip():
            raise ValueError("model endpoint release_flow requires non-empty flow_id")
        flow_id = flow_id.strip()
        with self._cv:
            while flow_id in self._claiming_flows or flow_id in self._granting_flows:
                self._cv.wait()
            owner_id = self._flow_owner.get(flow_id)
        if owner_id is not None:
            self._scheduling_authority.release_flow(
                self._scheduling_flow_id(flow_id),
                tenant_id=owner_id,
            )
        self._retire_flow_outside_lock(flow_id)

    def _admit_selected_locked(
        self,
        *,
        owner_id: str,
        binding: object,
        runtime: _ReplicaRuntime,
        prefix_affinity_depth: int,
        input_tokens: int,
        requested_output_tokens: int = 0,
        flow_id: str | None = None,
        persistent_flow: bool = False,
        admission_class: _FlowAdmissionClass = _FlowAdmissionClass.NORMAL,
    ) -> tuple[int, object, _ReplicaRuntime]:
        resolved_flow_id = owner_id if flow_id is None else flow_id
        # Validate the local dispatch projection before the one scheduling
        # Authority linearizes the service grant.
        if not isinstance(admission_class, _FlowAdmissionClass):
            raise TypeError("model flow admission requires internal admission class")
        if admission_class is _FlowAdmissionClass.BORROWER and (
            not self._preemptive_borrowing_enabled or not runtime.preemptive_borrowing
        ):
            raise RuntimeError("model borrower has no qualified preemptive replica")
        if persistent_flow and admission_class is not _FlowAdmissionClass.BORROWER:
            if (
                self._physical_continuity_controllers is not None
                and resolved_flow_id not in self._physical_flow_claims
            ):
                raise RuntimeError(
                    "physical model continuation not reserved by Resource Authority"
                )
            existing_owner = self._flow_owner.get(resolved_flow_id)
            if existing_owner is not None and existing_owner != owner_id:
                raise RuntimeError("model flow changed execution owner while reserved")
        if runtime.consecutive_failures > 0 and runtime.recovery_probe_in_flight:
            raise RuntimeError("model endpoint recovery probe admission raced")
        if binding.deployment_id not in self._worker_index_by_deployment:
            raise RuntimeError("selected model deployment not in scheduling authority scope")
        reserved_service_quanta = (
            self._prefill_service_quanta(input_tokens)
            + self._output_service_quanta(requested_output_tokens)
        )
        if self._global_grant_pending:
            raise RuntimeError("overlapping global model admission settlement")
        self._global_grant_pending = True
        self._granting_flows.add(resolved_flow_id)
        # Only the durability transaction runs without the replica mutex.
        # A provisional global grant fences every other admission and exact
        # same-flow physical retirement until the authoritative sequence is
        # known. Independent completions and read-only snapshots remain live.
        self._cv.release()
        grant_committed = False
        try:
            sequence = self._scheduling_authority.record_grant(
                tenant_id=owner_id,
                flow_id=self._scheduling_flow_id(resolved_flow_id),
                permit_count=1,
                reserved_service_quanta=reserved_service_quanta,
            )
            grant_committed = True
        finally:
            self._cv.acquire()
            self._global_grant_pending = False
            self._granting_flows.remove(resolved_flow_id)
            self._cv.notify_all()
            # Successful grants publish local service accounting before waking
            # the next eligible head. Waking before that publication can throw
            # and strand a committed Authority permit without a local owner.
            if not grant_committed:
                self._notify_selected_waiter_locked()
        self._reserve_flow_for_admission_locked(
            owner_id=owner_id,
            flow_id=resolved_flow_id,
            persistent_flow=persistent_flow,
            admission_class=admission_class,
        )
        runtime.in_flight += 1
        if admission_class is _FlowAdmissionClass.BORROWER:
            if not runtime.preemptive_borrowing:
                raise RuntimeError(
                    "borrowed model request selected an unqualified replica"
                )
            runtime.borrowed_in_flight += 1
        runtime.prefill_tokens_in_flight += input_tokens
        runtime.token_reservation_in_flight += (
            input_tokens + requested_output_tokens
        )
        runtime.selections += 1
        if runtime.consecutive_failures > 0:
            if runtime.recovery_probe_in_flight:
                raise RuntimeError(
                    "model endpoint recovery probe admission raced"
                )
            runtime.recovery_probe_in_flight = True
        self._active_by_owner[owner_id] = (
            self._active_by_owner.get(owner_id, 0) + 1
        )
        self._charge_worker_deficit_locked(
            owner_id,
            binding.deployment_id,
            input_tokens=input_tokens,
            requested_output_tokens=requested_output_tokens,
        )
        self._selection_sequence = max(self._selection_sequence, sequence)
        runtime.last_selected_sequence = sequence
        self._push_owner_head_locked(owner_id)
        self._invalidate_waiter_selection_locked()
        if prefix_affinity_depth > 0:
            runtime.prefix_affinity_selections += 1
        self._notify_selected_waiter_locked()
        return sequence, binding, runtime

    def _select(
        self,
        input_token_ids: tuple[int, ...],
        attempted_deployments: frozenset[str],
        *,
        owner_id: str,
        input_tokens: int,
        requested_output_tokens: int = 0,
        flow_id: str | None = None,
        persistent_flow: bool = False,
        preemptive_eligible: bool = False,
    ) -> tuple[
        int,
        object,
        _ReplicaRuntime,
        _FlowAdmissionClass,
        float,
        tuple[tuple[str, float], ...],
        int,
        float,
    ]:
        queue_started = self._clock()
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError("model endpoint pool owner_id must be non-empty text")
        owner_id = owner_id.strip()
        resolved_flow_id = owner_id if flow_id is None else str(flow_id).strip()
        if not resolved_flow_id:
            raise ValueError("model endpoint pool flow_id must be non-empty text")
        pool_lock_entered = self._clock()
        with self._cv:
            pool_lock_wait_seconds = max(0.0, self._clock() - pool_lock_entered)
            lock_wait_evidence = (("pool_lock_acquisition", pool_lock_wait_seconds),)
            # A claimed replica generation can change during physical
            # retirement. Read its identity in the same ownership cut as
            # selection; never sample this mutable dictionary before the lock.
            physical_reservation = self._physical_flow_claims.get(resolved_flow_id)
            physical_deployment_id = (
                None if physical_reservation is None else physical_reservation[0]
            )
            if self._closed:
                raise ModelEndpointPoolUnavailable(
                    "model endpoint pool is closed"
                )

            # Uncontended admission pays no waiter/Condition/heap allocation.
            # Fairness is unaffected because this path is legal only when there
            # is no queued owner to preserve ahead of the arriving request.
            admission_class = self._flow_admission_class_locked(
                resolved_flow_id,
                persistent_flow=persistent_flow,
                preemptive_eligible=preemptive_eligible,
            )
            if (not self._global_grant_pending
                    and self._waiter_count == 0 and admission_class is not None):
                (
                    _now,
                    binding,
                    runtime,
                    affinity_depth,
                    _cooling_until,
                ) = self._selection_candidate_locked(
                    input_token_ids,
                    attempted_deployments,
                    input_tokens,
                    requested_output_tokens,
                    owner_id=owner_id,
                    admission_class=admission_class,
                    physical_deployment_id=physical_deployment_id,
                )
                if binding is not None and runtime is not None:
                    admission_started = self._clock()
                    admitted = self._admit_selected_locked(
                        owner_id=owner_id,
                        binding=binding,
                        runtime=runtime,
                        prefix_affinity_depth=affinity_depth,
                        input_tokens=input_tokens,
                        requested_output_tokens=requested_output_tokens,
                        flow_id=resolved_flow_id,
                        persistent_flow=persistent_flow,
                        admission_class=admission_class,
                    )
                    return (
                        *admitted,
                        admission_class,
                        max(0.0, self._clock() - queue_started),
                        lock_wait_evidence,
                        0,
                        max(0.0, self._clock() - admission_started),
                    )

            waiter = _PoolWaiter(
                self._next_waiter_ticket,
                owner_id,
                self._clock(),
                resolved_flow_id,
                persistent_flow,
                # dispatch_deadline is an operational fail-close bound, not a
                # semantic scheduling deadline.  Treating arrival-skewed
                # relative timeouts as EDF priority destroys tenant VTC
                # fairness. Scientific deadlines are admitted by the outer
                # execution/lifetime scheduler before this physical queue.
                None,
                (
                    self._prefill_service_quanta(input_tokens)
                    + self._output_service_quanta(requested_output_tokens)
                )
                / _SERVICE_QUANTA_PER_SECOND,
                dispatch_input_token_ids=input_token_ids,
                dispatch_attempted_deployments=attempted_deployments,
                dispatch_input_tokens=input_tokens,
                dispatch_output_tokens=requested_output_tokens,
                dispatch_preemptive_eligible=preemptive_eligible,
            )
            self._next_waiter_ticket += 1
            self._enqueue_waiter_locked(waiter)
            admitted = False
            try:
                while True:
                    if self._closed:
                        raise ModelEndpointPoolUnavailable(
                            "model endpoint pool is closed"
                        )
                    if self._global_grant_pending:
                        self._wait_for_waiter_signal_locked(
                            waiter, reason="global_scheduling_grant_commit",
                        )
                        continue
                    selected_waiter = self._selected_waiter_locked()
                    # Waiter selection may release the pool mutex while a durable
                    # Scheduling Authority projection is refreshed, or wait behind
                    # another refresher. Revalidate the grant fence after returning:
                    # another selected waiter may have started its durable Grant in
                    # that interval. The pre-selection check alone is a TOCTOU race.
                    if self._global_grant_pending:
                        self._wait_for_waiter_signal_locked(
                            waiter, reason="global_scheduling_grant_commit",
                        )
                        continue
                    if selected_waiter is not waiter:
                        self._wait_for_waiter_signal_locked(
                            waiter,
                            reason=(
                                "fair_queue_or_eligible_peer"
                                if selected_waiter is not None
                                else self._waiter_block_reason_locked(waiter)
                            ),
                        )
                        continue

                    admission_class = self._flow_admission_class_locked(
                        resolved_flow_id,
                        persistent_flow=persistent_flow,
                        preemptive_eligible=preemptive_eligible,
                    )
                    if admission_class is None:
                        self._wait_for_waiter_signal_locked(
                            waiter, reason="flow_reservation_capacity",
                        )
                        continue

                    (
                        now,
                        binding,
                        runtime,
                        affinity_depth,
                        cooling_until,
                    ) = self._selection_candidate_locked(
                        input_token_ids,
                        attempted_deployments,
                        input_tokens,
                        requested_output_tokens,
                        owner_id=owner_id,
                        admission_class=admission_class,
                        physical_deployment_id=physical_deployment_id,
                    )
                    if binding is None or runtime is None:
                        if cooling_until is not None:
                            self._wait_for_waiter_signal_locked(
                                waiter,
                                timeout_seconds=max(
                                    0.0, cooling_until - now
                                ),
                                reason="replica_cooldown",
                            )
                        else:
                            self._wait_for_waiter_signal_locked(
                                waiter,
                                reason=(
                                    "pinned_replica_unavailable"
                                    if physical_deployment_id is not None
                                    else "replica_or_token_capacity"
                                ),
                            )
                        continue

                    self._remove_waiter_locked(waiter)
                    admitted = True
                    admission_started = self._clock()
                    admitted_selection = self._admit_selected_locked(
                        owner_id=owner_id,
                        binding=binding,
                        runtime=runtime,
                        prefix_affinity_depth=affinity_depth,
                        input_tokens=input_tokens,
                        requested_output_tokens=requested_output_tokens,
                        flow_id=resolved_flow_id,
                        persistent_flow=persistent_flow,
                        admission_class=admission_class,
                    )
                    return (
                        *admitted_selection,
                        admission_class,
                        max(0.0, self._clock() - queue_started),
                        tuple(sorted((
                            *waiter.diagnostics.wait_reason_seconds.items(),
                            *lock_wait_evidence,
                        ))),
                        waiter.diagnostics.bypassed_ineligible_heads,
                        max(0.0, self._clock() - admission_started),
                    )
            finally:
                if not admitted:
                    self._remove_waiter_locked(waiter)
                    self._notify_selected_waiter_locked()

    def _finish(
        self,
        runtime: _ReplicaRuntime,
        *,
        owner_id: str,
        elapsed_seconds: float,
        flow_id: str | None = None,
        admission_class: _FlowAdmissionClass,
        outcome: str,
        input_token_ids: tuple[int, ...] = (),
        charged_input_tokens: int = 0,
        observed_input_tokens: int | None = None,
        cached_input_tokens: int | None = None,
        output_tokens: int | None = None,
        reserved_output_tokens: int = 0,
    ) -> float:
        settlement_started = self._clock()
        if outcome not in {"completed", "request_rejected", "replica_failed"}:
            raise ValueError(f"unknown model endpoint dispatch outcome: {outcome!r}")
        if type(charged_input_tokens) is not int or charged_input_tokens < 0:
            raise ValueError(
                "endpoint pool charged_input_tokens must be non-negative"
            )
        if observed_input_tokens is not None and (
            type(observed_input_tokens) is not int
            or observed_input_tokens < 0
        ):
            raise ValueError(
                "endpoint pool observed_input_tokens must be non-negative"
            )
        if cached_input_tokens is not None:
            if type(cached_input_tokens) is not int or cached_input_tokens < 0:
                raise ValueError(
                    "endpoint pool cached_input_tokens must be non-negative"
                )
            if outcome != "completed":
                raise ValueError(
                    "cached input service can only reconcile a completed request"
                )
        resolved_flow_id = owner_id if flow_id is None else flow_id
        if type(resolved_flow_id) is not str or not resolved_flow_id.strip():
            raise ValueError("endpoint pool flow_id must be non-empty text")
        resolved_flow_id = resolved_flow_id.strip()
        now = self._clock()
        deployment_id = runtime.endpoint.route.deployment_id
        reserved_tokens = charged_input_tokens + reserved_output_tokens
        retire_after_completion = False
        def active_snapshot_locked() -> tuple[bool, int, int, int]:
            """Check the current affine local cut, without releasing capacity.

            The first read validates before a durable side effect. Recheck
            after the scheduling commit because unrelated requests can finish
            while SQLite owns its cross-process writer transaction.
            """
            if runtime.in_flight <= 0:
                raise RuntimeError("endpoint pool in-flight accounting underflow")
            if not isinstance(admission_class, _FlowAdmissionClass):
                raise TypeError(
                    "model endpoint completion requires admission class"
                )
            if admission_class is _FlowAdmissionClass.BORROWER:
                if runtime.borrowed_in_flight <= 0:
                    raise RuntimeError(
                        "model endpoint borrowed in-flight accounting underflow"
                    )
            if runtime.token_reservation_in_flight < reserved_tokens:
                raise RuntimeError(
                    "endpoint pool token reservation accounting underflow"
                )
            active = self._active_by_owner.get(owner_id, 0)
            if active <= 0:
                raise RuntimeError("endpoint pool owner in-flight accounting underflow")
            flow_active = self._active_by_flow.get(resolved_flow_id, 0)
            if flow_active <= 0:
                raise RuntimeError("endpoint pool flow in-flight accounting underflow")
            # Retire affine physical/accounting ownership before any service
            # reconciliation that can reject malformed provider usage. A bad
            # receipt may fail the request, but it must never leak an in-flight
            # slot or borrowed-capacity token.
            demand_pressure = (
                self._waiter_count > 0
                or runtime.in_flight >= runtime.adaptive_window.limit
            )
            borrowed_after = runtime.borrowed_in_flight - (
                1 if admission_class is _FlowAdmissionClass.BORROWER else 0
            )
            if borrowed_after > runtime.in_flight - 1:
                raise RuntimeError(
                    "model endpoint borrowed in-flight accounting exceeded total"
                )
            return demand_pressure, borrowed_after, active, flow_active

        reserved_service_quanta = (
            self._prefill_service_quanta(charged_input_tokens)
            + self._output_service_quanta(reserved_output_tokens)
        )
        with self._cv:
            active_snapshot_locked()
        # A slow cross-process Scheduling Authority SQLite writer cannot hold
        # the replica pool mutex. The local in-flight slot remains occupied
        # until this authoritative completion is durable. Admission on free
        # slots is nevertheless work-conserving during the transaction.
        self._scheduling_authority.record_completion(
            tenant_id=owner_id,
            flow_id=self._scheduling_flow_id(resolved_flow_id),
            service_quanta=max(1, int(elapsed_seconds * _SERVICE_QUANTA_PER_SECOND)),
            permit_count=1,
            reserved_service_quanta=reserved_service_quanta,
        )
        with self._cv:
            demand_pressure, borrowed_after, active, flow_active = active_snapshot_locked()
            runtime.borrowed_in_flight = borrowed_after
            runtime.token_reservation_in_flight -= reserved_tokens
            if active == 1:
                self._active_by_owner.pop(owner_id, None)
            else:
                self._active_by_owner[owner_id] = active - 1
            if flow_active == 1:
                self._active_by_flow.pop(resolved_flow_id, None)
                if resolved_flow_id in self._pending_flow_releases:
                    retire_after_completion = True
            else:
                self._active_by_flow[resolved_flow_id] = flow_active - 1
            runtime.in_flight -= 1
            runtime.recovery_probe_in_flight = False

            self._reconcile_worker_service_deficit_locked(
                owner_id,
                deployment_id,
                charged_input_tokens=charged_input_tokens,
                observed_input_tokens=(
                    observed_input_tokens
                    if outcome == "completed"
                    else None
                ),
                cached_input_tokens=(
                    cached_input_tokens
                    if outcome == "completed"
                    else None
                ),
                output_tokens=(
                    output_tokens
                    if outcome == "completed"
                    else (0 if outcome == "request_rejected" else None)
                ),
                reserved_output_tokens=reserved_output_tokens,
            )
            if outcome == "request_rejected":
                runtime.request_rejections += 1
            elif outcome == "replica_failed":
                runtime.failures += 1
                runtime.consecutive_failures += 1
                cooldown = min(
                    self._max_failure_cooldown,
                    self._failure_cooldown
                    * (2 ** max(0, runtime.consecutive_failures - 1)),
                )
                runtime.cooldown_until = now + cooldown
            else:
                runtime.completed += 1
                service_seconds_per_item = (
                    None
                    if (
                        elapsed_seconds <= 0
                        or output_tokens is None
                        or output_tokens <= 0
                    )
                    else elapsed_seconds / output_tokens
                )
                runtime.adaptive_window.on_clean_completion(
                    service_seconds_per_item=(
                        service_seconds_per_item
                    ),
                    demand_pressure=demand_pressure,
                )
                runtime.consecutive_failures = 0
                runtime.cooldown_until = 0.0
                if not self._single_replica:
                    self._token_prefix_residency.record(
                        deployment_id,
                        input_token_ids,
                    )
                if runtime.ewma_latency_seconds is None:
                    runtime.ewma_latency_seconds = elapsed_seconds
                else:
                    runtime.ewma_latency_seconds = (
                        self._ewma_alpha * elapsed_seconds
                        + (1.0 - self._ewma_alpha)
                        * runtime.ewma_latency_seconds
                    )
            self._push_owner_head_locked(owner_id)
            self._invalidate_waiter_selection_locked()
            self._notify_selected_waiter_locked()
        # Physical SQLite release may block on unrelated Authority writers.
        # The just-finished request's local accounting has already converged;
        # keeping the pool mutex held would serialize every other tenant.
        if retire_after_completion:
            self._retire_flow_outside_lock(resolved_flow_id)
        self._schedule_pressure_probe(deployment_id, runtime)
        return max(0.0, self._clock() - settlement_started)

    @staticmethod
    def _platform_scheduled_body(
        binding: object,
        body: Mapping[str, JsonInput],
        admission_class: _FlowAdmissionClass,
    ) -> Mapping[str, JsonInput]:
        """Inject platform-owned physical scheduling metadata."""

        model = getattr(binding, "model", None)
        engine = str(
            getattr(model, "engine", "") or ""
        ).strip().lower()
        if (
            engine != "vllm"
            or not bool(
                getattr(binding, "preemptive_latency_isolation", False)
            )
        ):
            return body
        materialized = thaw_json(body)
        if not isinstance(materialized, dict):
            raise TypeError(
                "model endpoint body must materialize to an object"
            )
        if admission_class is _FlowAdmissionClass.PROTECTED_RETURN:
            priority = PREEMPTIVE_PROTECTED_PRIORITY
        elif admission_class is _FlowAdmissionClass.BORROWER:
            priority = PREEMPTIVE_BORROWER_PRIORITY
        else:
            priority = 0
        # Provider scheduling is platform truth. A downstream-supplied priority
        # cannot override continuity/fairness policy.
        materialized["priority"] = priority
        return materialized

    def complete(
        self,
        request: ModelEndpointEnvelope,
        body: Mapping[str, JsonInput],
        *,
        input_tokens: int | None = None,
        input_token_ids: tuple[int, ...] | None = None,
        requested_output_tokens: int | None = None,
        timeout_s: float | None = None,
    ) -> ModelEndpointDispatchResult:
        if not isinstance(
            request,
            (ModelRequestEnvelope, ModelOperationEnvelope),
        ):
            raise TypeError(
                "endpoint pool request must be a model request/operation envelope"
            )
        if not isinstance(body, Mapping):
            raise TypeError("endpoint pool body must be a mapping")

        normalized_input_tokens = self._normalized_input_tokens(input_tokens)
        normalized_input_token_ids = self._normalized_input_token_ids(
            input_token_ids,
            input_tokens=normalized_input_tokens,
        )
        normalized_output_reservation = (
            self._normalized_requested_output_tokens(
                requested_output_tokens
            )
        )
        requested_provider_timeout = self._provider_timeout_seconds(timeout_s)
        owner_id = model_request_owner_id(request)
        flow_id = model_request_flow_id(request)
        persistent_flow = bool(isinstance(request.context.lifetime_id, str) and request.context.lifetime_id.strip())
        attempts: list[ModelEndpointDispatchAttempt] = []
        attempted_deployments: set[str] = set()
        for attempt_number in range(1, self._retry_policy.max_attempts + 1):
            (
                sequence,
                binding,
                runtime,
                admission_class,
                queue_seconds,
                queue_wait_reason_seconds,
                queue_bypassed_ineligible_heads,
                queue_admission_wall_seconds,
            ) = self._select(
                normalized_input_token_ids,
                frozenset(attempted_deployments),
                owner_id=owner_id,
                input_tokens=normalized_input_tokens,
                requested_output_tokens=normalized_output_reservation,
                flow_id=flow_id,
                persistent_flow=persistent_flow,
                preemptive_eligible=isinstance(
                    request,
                    ModelRequestEnvelope,
                ),
            )
            attempted_deployments.add(binding.deployment_id)
            qualified_total_timeout = None
            if self._replica_set.qualified:
                qualified_total_timeout, _qualified_idle_timeout = (
                    self._qualified_transport_budget_seconds(
                        binding,
                        input_tokens=normalized_input_tokens,
                        requested_output_tokens=normalized_output_reservation,
                    )
                )
            provider_timeout = (
                requested_provider_timeout
                if requested_provider_timeout is not None
                else qualified_total_timeout
            )
            physical_body = self._platform_scheduled_body(
                binding,
                body,
                admission_class,
            )
            physical_request = ModelEndpointRequest(
                request=request,
                deployment_id=binding.deployment_id,
                deployment_generation=binding.deployment_generation,
                body=physical_body,
                timeout_s=provider_timeout,
                continuity_claim_id=(
                    self._physical_flow_claims[flow_id][1].claim_id
                    if flow_id in self._physical_flow_claims
                    and admission_class is not _FlowAdmissionClass.BORROWER
                    else None
                ),
            )
            started = self._clock()
            try:
                response = runtime.endpoint.complete(physical_request)
            except ModelEndpointError as exc:
                if exc.failure_kind == "rate_limit":
                    runtime.adaptive_window.on_pressure(reason="rate_limit")
                elif exc.failure_kind == "capacity":
                    runtime.adaptive_window.on_pressure(reason="capacity_pressure")
                elif exc.retryable:
                    runtime.adaptive_window.on_transient_failure()
                outcome = (
                    "replica_failed"
                    if exc.affects_replica_health
                    else "request_rejected"
                )
                elapsed = max(0.0, self._clock() - started)
                self._release_prefill_tokens(
                    runtime,
                    normalized_input_tokens,
                )
                completion_accounting_seconds = self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    flow_id=flow_id,
                    admission_class=admission_class,
                    outcome=outcome,
                    charged_input_tokens=normalized_input_tokens,
                    reserved_output_tokens=normalized_output_reservation,
                )
                can_retry = (
                    attempt_number < self._retry_policy.max_attempts
                    and exc.retryable
                    and exc.failure_kind
                    in self._retry_policy.retryable_failure_kinds
                )
                wait = (
                    max(
                        self._retry_policy.wait_seconds(
                            attempt_number=attempt_number,
                            retry_after_seconds=exc.retry_after_seconds,
                        ),
                        (
                            max(0.0, runtime.cooldown_until - self._clock())
                            if exc.affects_replica_health
                            else 0.0
                        ),
                    )
                    if can_retry
                    else 0.0
                )
                attempts.append(
                    ModelEndpointDispatchAttempt(
                        attempt_number=attempt_number,
                        deployment_id=binding.deployment_id,
                        selection_sequence=sequence,
                        elapsed_seconds=elapsed,
                        outcome=outcome,
                        queue_seconds=queue_seconds,
                        queue_wait_reason_seconds=queue_wait_reason_seconds,
                        queue_bypassed_ineligible_heads=queue_bypassed_ineligible_heads,
                        queue_admission_wall_seconds=queue_admission_wall_seconds,
                        completion_accounting_wall_seconds=completion_accounting_seconds,
                        failure_kind=exc.failure_kind,
                        retryable=exc.retryable,
                        retry_after_seconds=exc.retry_after_seconds,
                        wait_before_next_seconds=wait,
                    )
                )
                if not can_retry:
                    exc.dispatch_attempts = tuple(attempts)
                    exc.retry_policy_digest = self._retry_policy.policy_digest
                    raise
                if wait > 0:
                    self._sleep(wait)
                continue
            except BaseException as exc:
                elapsed = max(0.0, self._clock() - started)
                self._release_prefill_tokens(
                    runtime,
                    normalized_input_tokens,
                )
                completion_accounting_seconds = self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    flow_id=flow_id,
                    admission_class=admission_class,
                    outcome="replica_failed",
                    charged_input_tokens=normalized_input_tokens,
                    reserved_output_tokens=normalized_output_reservation,
                )
                attempts.append(
                    ModelEndpointDispatchAttempt(
                        attempt_number=attempt_number,
                        deployment_id=binding.deployment_id,
                        selection_sequence=sequence,
                        elapsed_seconds=elapsed,
                        outcome="replica_failed",
                        queue_seconds=queue_seconds,
                        queue_wait_reason_seconds=queue_wait_reason_seconds,
                        queue_bypassed_ineligible_heads=queue_bypassed_ineligible_heads,
                        queue_admission_wall_seconds=queue_admission_wall_seconds,
                        completion_accounting_wall_seconds=completion_accounting_seconds,
                        failure_kind=type(exc).__name__,
                        retryable=False,
                    )
                )
                try:
                    setattr(exc, "dispatch_attempts", tuple(attempts))
                    setattr(exc, "retry_policy_digest", self._retry_policy.policy_digest)
                except Exception:
                    pass
                raise

            elapsed = max(0.0, self._clock() - started)
            self._release_prefill_tokens(
                runtime,
                normalized_input_tokens,
            )
            completion_accounting_seconds = self._finish(
                runtime,
                owner_id=owner_id,
                elapsed_seconds=elapsed,
                flow_id=flow_id,
                admission_class=admission_class,
                outcome="completed",
                input_token_ids=normalized_input_token_ids,
                charged_input_tokens=normalized_input_tokens,
                observed_input_tokens=response.input_tokens,
                cached_input_tokens=response.cached_input_tokens,
                output_tokens=response.output_tokens,
                reserved_output_tokens=normalized_output_reservation,
            )
            attempts.append(
                ModelEndpointDispatchAttempt(
                    attempt_number=attempt_number,
                    deployment_id=binding.deployment_id,
                    selection_sequence=sequence,
                    elapsed_seconds=elapsed,
                    outcome="completed",
                    queue_seconds=queue_seconds,
                    queue_wait_reason_seconds=queue_wait_reason_seconds,
                    queue_bypassed_ineligible_heads=queue_bypassed_ineligible_heads,
                    queue_admission_wall_seconds=queue_admission_wall_seconds,
                    completion_accounting_wall_seconds=completion_accounting_seconds,
                )
            )
            return ModelEndpointDispatchResult(
                request=physical_request,
                response=response,
                replica_set_digest=self._replica_set_digest,
                selection_policy_digest=self._selection_policy_digest,
                selection_sequence=sequence,
                attempts=tuple(attempts),
                retry_policy_digest=self._retry_policy.policy_digest,
            )

        raise RuntimeError("model endpoint retry loop exhausted without terminal outcome")

    def stream(
        self,
        request: ModelRequestEnvelope,
        body: Mapping[str, JsonInput],
        on_event: Callable[[ModelStreamEvent], None],
        *,
        input_tokens: int | None = None,
        input_token_ids: tuple[int, ...] | None = None,
        requested_output_tokens: int | None = None,
        timeout_s: float | None = None,
        stream_idle_timeout_s: float | None = None,
    ) -> ModelEndpointDispatchResult:
        if not isinstance(request,ModelRequestEnvelope):
            raise TypeError("endpoint pool streaming requires ModelRequestEnvelope")
        if not isinstance(body,Mapping):
            raise TypeError("endpoint pool streaming body must be a mapping")
        if not callable(on_event):
            raise TypeError("endpoint pool streaming on_event must be callable")
        if stream_idle_timeout_s is not None and (
            isinstance(stream_idle_timeout_s,bool)
            or not isinstance(stream_idle_timeout_s,(int,float))
            or not math.isfinite(float(stream_idle_timeout_s))
            or float(stream_idle_timeout_s) <= 0
        ):
            raise ValueError(
                "endpoint pool stream idle timeout must be finite and positive when set"
            )

        normalized_input_tokens=self._normalized_input_tokens(input_tokens)
        normalized_input_token_ids=self._normalized_input_token_ids(
            input_token_ids,
            input_tokens=normalized_input_tokens,
        )
        normalized_output_reservation=(
            self._normalized_requested_output_tokens(requested_output_tokens)
        )
        requested_provider_timeout=self._provider_timeout_seconds(timeout_s)
        owner_id=model_request_owner_id(request)
        flow_id=model_request_flow_id(request)
        persistent_flow=bool(isinstance(request.context.lifetime_id,str) and request.context.lifetime_id.strip())
        attempts: list[ModelEndpointDispatchAttempt]=[]
        attempted_deployments: set[str]=set()
        for attempt_number in range(1,self._retry_policy.max_attempts+1):
            (
                sequence,
                binding,
                runtime,
                admission_class,
                queue_seconds,
                queue_wait_reason_seconds,
                queue_bypassed_ineligible_heads,
                queue_admission_wall_seconds,
            )=self._select(
                normalized_input_token_ids,
                frozenset(attempted_deployments),
                owner_id=owner_id,
                input_tokens=normalized_input_tokens,
                requested_output_tokens=normalized_output_reservation,
                flow_id=flow_id,
                persistent_flow=persistent_flow,
                preemptive_eligible=True,
            )
            attempted_deployments.add(binding.deployment_id)
            qualified_total_timeout = None
            qualified_idle_timeout = None
            if self._replica_set.qualified:
                qualified_total_timeout, qualified_idle_timeout = (
                    self._qualified_transport_budget_seconds(
                        binding,
                        input_tokens=normalized_input_tokens,
                        requested_output_tokens=normalized_output_reservation,
                    )
                )
            provider_timeout=(
                requested_provider_timeout
                if requested_provider_timeout is not None
                else qualified_total_timeout
            )
            physical_body=self._platform_scheduled_body(
                binding,
                body,
                admission_class,
            )
            physical_request=ModelEndpointRequest(
                request=request,
                deployment_id=binding.deployment_id,
                deployment_generation=binding.deployment_generation,
                body=physical_body,
                timeout_s=provider_timeout,
                continuity_claim_id=(
                    self._physical_flow_claims[flow_id][1].claim_id
                    if flow_id in self._physical_flow_claims
                    and admission_class is not _FlowAdmissionClass.BORROWER
                    else None
                ),
            )
            started=self._clock()
            emitted=0
            prefill_held=normalized_input_tokens > 0

            def release_prefill() -> None:
                nonlocal prefill_held
                if not prefill_held:
                    return
                self._release_prefill_tokens(
                    runtime,
                    normalized_input_tokens,
                )
                prefill_held=False

            def forward(event: ModelStreamEvent) -> None:
                nonlocal emitted
                if not isinstance(event,ModelStreamEvent):
                    raise TypeError("endpoint stream emitted untyped event")
                normalized=replace(event,attempt_number=attempt_number)
                release_prefill()
                emitted += 1
                try:
                    on_event(normalized)
                except BaseException as exc:
                    raise _StreamConsumerError(exc) from exc

            try:
                streamer=getattr(runtime.endpoint,"stream",None)
                if not callable(streamer):
                    raise ModelEndpointError(
                        "selected model endpoint does not support streaming",
                        failure_kind="invalid_request",
                        retryable=False,
                        affects_replica_health=False,
                    )
                response=streamer(
                    physical_request,
                    forward,
                    stream_idle_timeout_s=(
                        float(stream_idle_timeout_s)
                        if stream_idle_timeout_s is not None
                        else (
                            None
                            if qualified_idle_timeout is None
                            else (
                                float(qualified_idle_timeout)
                                if provider_timeout is None
                                else min(
                                    float(qualified_idle_timeout),
                                    float(provider_timeout),
                                )
                            )
                        )
                    ),
                )
            except _StreamConsumerError as exc:
                elapsed=max(0.0,self._clock()-started)
                release_prefill()
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    flow_id=flow_id,
                    admission_class=admission_class,
                    outcome="request_rejected",
                    charged_input_tokens=normalized_input_tokens,
                    reserved_output_tokens=normalized_output_reservation,
                )
                raise exc.cause
            except ModelEndpointError as exc:
                if exc.failure_kind == "rate_limit":
                    runtime.adaptive_window.on_pressure(reason="rate_limit")
                elif exc.failure_kind == "capacity":
                    runtime.adaptive_window.on_pressure(reason="capacity_pressure")
                elif exc.retryable:
                    runtime.adaptive_window.on_transient_failure()
                outcome=(
                    "replica_failed"
                    if exc.affects_replica_health
                    else "request_rejected"
                )
                elapsed=max(0.0,self._clock()-started)
                release_prefill()
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    flow_id=flow_id,
                    admission_class=admission_class,
                    outcome=outcome,
                    charged_input_tokens=normalized_input_tokens,
                    reserved_output_tokens=normalized_output_reservation,
                )
                can_retry=(
                    emitted == 0
                    and attempt_number < self._retry_policy.max_attempts
                    and exc.retryable
                    and exc.failure_kind
                    in self._retry_policy.retryable_failure_kinds
                )
                wait=(
                    max(
                        self._retry_policy.wait_seconds(
                            attempt_number=attempt_number,
                            retry_after_seconds=exc.retry_after_seconds,
                        ),
                        (
                            max(0.0, runtime.cooldown_until - self._clock())
                            if exc.affects_replica_health
                            else 0.0
                        ),
                    )
                    if can_retry
                    else 0.0
                )
                attempts.append(ModelEndpointDispatchAttempt(
                    attempt_number=attempt_number,
                    deployment_id=binding.deployment_id,
                    selection_sequence=sequence,
                    elapsed_seconds=elapsed,
                    outcome=outcome,
                    queue_seconds=queue_seconds,
                    queue_wait_reason_seconds=queue_wait_reason_seconds,
                    queue_bypassed_ineligible_heads=queue_bypassed_ineligible_heads,
                    queue_admission_wall_seconds=queue_admission_wall_seconds,
                    failure_kind=exc.failure_kind,
                    retryable=exc.retryable,
                    retry_after_seconds=exc.retry_after_seconds,
                    wait_before_next_seconds=wait,
                ))
                if not can_retry:
                    exc.dispatch_attempts=tuple(attempts)
                    exc.retry_policy_digest=self._retry_policy.policy_digest
                    raise
                if wait > 0:
                    self._sleep(wait)
                continue
            except BaseException as exc:
                elapsed=max(0.0,self._clock()-started)
                release_prefill()
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    flow_id=flow_id,
                    admission_class=admission_class,
                    outcome="replica_failed",
                    charged_input_tokens=normalized_input_tokens,
                    reserved_output_tokens=normalized_output_reservation,
                )
                attempts.append(ModelEndpointDispatchAttempt(
                    attempt_number=attempt_number,
                    deployment_id=binding.deployment_id,
                    selection_sequence=sequence,
                    elapsed_seconds=elapsed,
                    outcome="replica_failed",
                    queue_seconds=queue_seconds,
                    queue_wait_reason_seconds=queue_wait_reason_seconds,
                    queue_bypassed_ineligible_heads=queue_bypassed_ineligible_heads,
                    queue_admission_wall_seconds=queue_admission_wall_seconds,
                    failure_kind=type(exc).__name__,
                    retryable=False,
                ))
                try:
                    setattr(exc,"dispatch_attempts",tuple(attempts))
                    setattr(exc,"retry_policy_digest",self._retry_policy.policy_digest)
                except Exception:
                    pass
                raise

            elapsed=max(0.0,self._clock()-started)
            release_prefill()
            self._finish(
                runtime,
                owner_id=owner_id,
                elapsed_seconds=elapsed,
                flow_id=flow_id,
                admission_class=admission_class,
                outcome="completed",
                input_token_ids=normalized_input_token_ids,
                charged_input_tokens=normalized_input_tokens,
                observed_input_tokens=response.input_tokens,
                cached_input_tokens=response.cached_input_tokens,
                output_tokens=response.output_tokens,
                reserved_output_tokens=normalized_output_reservation,
            )
            attempts.append(ModelEndpointDispatchAttempt(
                attempt_number=attempt_number,
                deployment_id=binding.deployment_id,
                selection_sequence=sequence,
                elapsed_seconds=elapsed,
                outcome="completed",
                queue_seconds=queue_seconds,
                queue_wait_reason_seconds=queue_wait_reason_seconds,
                queue_bypassed_ineligible_heads=queue_bypassed_ineligible_heads,
                queue_admission_wall_seconds=queue_admission_wall_seconds,
            ))
            return ModelEndpointDispatchResult(
                request=physical_request,
                response=response,
                replica_set_digest=self._replica_set_digest,
                selection_policy_digest=self._selection_policy_digest,
                selection_sequence=sequence,
                attempts=tuple(attempts),
                retry_policy_digest=self._retry_policy.policy_digest,
            )

        raise RuntimeError("model endpoint streaming retry loop exhausted without terminal outcome")

    def close(self) -> None:
        # Closing may retire many independent physical claims. Serialize only
        # other close attempts; never hold the scheduling Condition over
        # Resource Authority I/O or external provider transport shutdown.
        with self._terminal_close_lock:
            if self._terminal_close_complete:
                return
            with self._cv:
                in_flight = {
                    dep: rt.in_flight
                    for dep, rt in self._runtimes.items()
                    if rt.in_flight
                }
                if in_flight:
                    raise RuntimeError(
                        "cannot close model endpoint pool with in-flight requests: "
                        f"{in_flight}"
                    )
                if self._claiming_flows:
                    raise RuntimeError(
                        "cannot close model pool during physical Claim admission"
                    )
                if self._global_grant_pending or self._granting_flows:
                    raise RuntimeError(
                        "cannot close model pool during durable scheduling Grant"
                    )
                # Publish terminal admission closure before releasing the mutex
                # so a waiting model caller cannot interleave a new grant.
                self._closed = True
                self._notify_all_waiters_locked()
                flows = tuple(self._reserved_flows)
                endpoints = tuple(
                    runtime.endpoint
                    for _dep, runtime in sorted(self._runtimes.items())
                )

            # Durable resource effects are not bounded by scheduling lock
            # latency, and each continuation retains its exact lease until
            # Resource Authority confirms physical retirement.
            release_failures = []
            for flow_id in flows:
                try:
                    self._retire_flow_outside_lock(flow_id)
                except BaseException as exc:
                    release_failures.append(exc)
            if release_failures:
                raise BaseExceptionGroup(
                    "model endpoint pool physical retirement failed",
                    release_failures,
                )
            with self._cv:
                if self._reserved_flows or self._physical_flow_claims:
                    raise RuntimeError(
                        "cannot close endpoint pool with outstanding physical claims"
                    )
                self._flow_owner.clear()
                self._pending_flow_releases.clear()

            errors = []
            for endpoint in reversed(endpoints):
                closer = getattr(endpoint, "close", None)
                if callable(closer):
                    try:
                        closer()
                    except BaseException as exc:
                        errors.append(exc)
            if self._owned_transport_close is not None:
                try:
                    self._owned_transport_close()
                except BaseException as exc:
                    errors.append(exc)
            if errors:
                raise BaseExceptionGroup(
                    "model endpoint pool transport shutdown failed",
                    errors,
                )
            self._terminal_close_complete = True

    def snapshot(self) -> ModelEndpointPoolSnapshot:
        now = self._clock()
        with self._lock:
            rows: list[ModelEndpointReplicaSnapshot] = []
            for deployment_id, runtime in sorted(self._runtimes.items()):
                adaptive = runtime.adaptive_window.snapshot()
                pressure = runtime.pressure_snapshot
                rows.append(
                    ModelEndpointReplicaSnapshot(
                        deployment_id=deployment_id,
                        deployment_generation=(
                            self._bindings[deployment_id].deployment_generation
                        ),
                        capacity=runtime.capacity,
                        in_flight=runtime.in_flight,
                        completed=runtime.completed,
                        failures=runtime.failures,
                        selections=runtime.selections,
                        consecutive_failures=runtime.consecutive_failures,
                        ewma_latency_seconds=runtime.ewma_latency_seconds,
                        cooling_down=runtime.cooldown_until > now,
                        request_rejections=runtime.request_rejections,
                        adaptive_limit=adaptive.current_limit,
                        adaptive_min_limit=adaptive.min_limit,
                        adaptive_max_limit=adaptive.max_limit,
                        adaptive_scale_up_suspended=adaptive.scale_up_suspended,
                        adaptive_window_policy_digest=adaptive.policy_digest,
                        adaptive_window_history=tuple(
                            (
                                event.sequence,
                                event.old_limit,
                                event.new_limit,
                                event.reason,
                                event.observed_at,
                            )
                            for event in adaptive.history
                        ),
                        token_prefix_sequences=(
                            self._token_prefix_residency.sequence_count(
                                deployment_id
                            )
                        ),
                        token_prefix_tokens=(
                            self._token_prefix_residency.resident_token_count(
                                deployment_id
                            )
                        ),
                        prefix_affinity_selections=(
                            runtime.prefix_affinity_selections
                        ),
                        runtime_requests_running=(
                            None if pressure is None else pressure.requests_running
                        ),
                        runtime_requests_waiting=(
                            None if pressure is None else pressure.requests_waiting
                        ),
                        runtime_gpu_kv_cache_usage=(
                            None if pressure is None else pressure.gpu_kv_cache_usage
                        ),
                        runtime_prefix_cache_hit_rate=(
                            None
                            if pressure is None
                            else pressure.prefix_cache_hit_rate
                        ),
                        runtime_preemptions_total=(
                            None if pressure is None else pressure.preemptions_total
                        ),
                        prefill_tokens_in_flight=(
                            runtime.prefill_tokens_in_flight
                        ),
                        token_reservation_in_flight=(
                            runtime.token_reservation_in_flight
                        ),
                        max_prefill_queued_tokens=(
                            runtime.max_prefill_queued_tokens
                        ),
                        latency_isolation_concurrency=(
                            int(getattr(
                                self._bindings[deployment_id],
                                "latency_isolation_concurrency",
                            ))
                            if self._replica_set.qualified
                            else None
                        ),
                    )
                )
            return ModelEndpointPoolSnapshot(
                replica_set_digest=self._replica_set_digest,
                selection_policy_digest=self._selection_policy_digest,
                selection_sequence=self._selection_sequence,
                replicas=tuple(rows),
                latency_isolation_capacity=self._latency_isolation_capacity,
                persistent_flow_capacity=self._persistent_flow_capacity,
                reserved_flow_count=len(self._reserved_flows),
                pending_flow_release_count=len(self._pending_flow_releases),
                active_flow_count=len(self._active_by_flow),
            )


    @property
    def latency_isolation_capacity(self) -> int:
        """Strict qualified single-flow latency-isolation evidence."""

        return self._latency_isolation_capacity

    @property
    def persistent_flow_capacity(self) -> int:
        """Measured preferred operating point for protected interactive flows."""

        return self._persistent_flow_capacity

    @property
    def replica_set(self) -> ModelEndpointReplicaSet:
        return self._replica_set


__all__ = [
    "AdaptiveModelEndpointPool",
    "ModelEndpointPoolUnavailable",
]
