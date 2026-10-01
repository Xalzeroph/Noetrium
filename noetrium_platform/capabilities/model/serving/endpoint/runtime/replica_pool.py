from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
import heapq
from threading import Condition, Lock
import math
import time

from noetrium_platform.capabilities.model.request.api import (
    ModelEndpointEnvelope,
    ModelOperationEnvelope,
    ModelRequestEnvelope,
    model_request_owner_id,
)
from noetrium_platform.foundation.kernel.kernel import JsonInput, canonical_bytes
from noetrium_platform.foundation.kernel.concurrency.api import (
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.contracts import (
    ModelEndpointError,
    ModelEndpointRequest,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.ports import ModelEndpointPort
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
from .adaptive_window import (
    AdaptiveRequestWindow,
    AdaptiveRequestWindowPolicy,
)
from .request_retry import ModelRequestRetryPolicy
from .selection_policy import AdaptiveLeastPressureReplicaSelectionPolicy



class _StreamConsumerError(RuntimeError):
    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause=cause


class ModelEndpointPoolUnavailable(RuntimeError):
    pass


def _request_prefix_affinity_keys(
    request: ModelEndpointEnvelope,
    body: Mapping[str, JsonInput],
    *,
    max_keys: int,
) -> tuple[str, ...]:
    """Derive bounded, provider-neutral locality keys without tokenizing twice.

    Generation requests expose immutable prompt provenance plus the visible
    structured request. The first keys describe the stable prompt/tool prefix;
    subsequent keys extend through only the leading messages, and an exact
    compiled-prompt key is appended when available. This keeps routing work
    bounded while still capturing the prefixes that inference engines can
    reuse through automatic prefix/KV caching.
    """

    if not isinstance(request, ModelRequestEnvelope):
        return ()
    seed = sha256(
        canonical_bytes(
            {
                "schema": "noetrium.model-prefix-affinity.v1",
                "prompt_generation_id": request.prompt_generation_id,
                "prompt_id": request.prompt_id,
                "prompt_digest": request.prompt_digest,
                "tool_schema_sha256": (
                    None
                    if request.tool_schema_bundle is None
                    else request.tool_schema_bundle.content_sha256
                ),
                "chat_template_kwargs": body.get("chat_template_kwargs"),
                # An immutable tool-schema bundle is the authoritative content
                # address for this prefix. Re-encoding the full structured tool
                # list on every request is redundant and can dominate routing
                # CPU for large agent tool surfaces. Preserve the full fallback
                # only when no content-addressed bundle exists.
                "tools": (
                    body.get("tools")
                    if request.tool_schema_bundle is None
                    else None
                ),
            }
        )
    )
    keys: list[str] = [seed.hexdigest()]

    messages = body.get("messages")
    if isinstance(messages, (tuple, list)):
        # Reserve one slot for an exact compiled-prompt key when available.
        message_budget = max(0, max_keys - len(keys) - 1)
        for message in messages[:message_budget]:
            seed.update(b"\x00message\x00")
            seed.update(canonical_bytes(message))
            keys.append(seed.hexdigest())

    exact_material = None
    if request.compiled_prompt is not None:
        exact_material = {
            "kind": "compiled-prompt",
            "content_sha256": request.compiled_prompt.content_sha256,
        }
    elif isinstance(body.get("prompt"), str):
        exact_material = {"kind": "prompt", "value": body.get("prompt")}
    elif body.get("input") is not None:
        exact_material = {"kind": "input", "value": body.get("input")}
    if exact_material is not None and len(keys) < max_keys:
        keys.append(
            sha256(canonical_bytes(exact_material)).hexdigest()
        )
    return tuple(dict.fromkeys(keys[:max_keys]))


@dataclass(slots=True)
class _ReplicaRuntime:
    endpoint: ModelEndpointPort
    capacity: int
    adaptive_window: AdaptiveRequestWindow
    in_flight: int = 0
    completed: int = 0
    failures: int = 0
    request_rejections: int = 0
    selections: int = 0
    consecutive_failures: int = 0
    ewma_latency_seconds: float | None = None
    cooldown_until: float = 0.0
    last_selected_sequence: int = 0
    prefix_affinity: OrderedDict[str, None] = field(default_factory=OrderedDict)
    prefix_affinity_selections: int = 0
    pressure_snapshot: ModelRuntimePressureSnapshot | None = None
    pressure_probe_in_flight: bool = False
    pressure_probe_sequence: int = 0
    last_pressure_probe_at: float = -math.inf
    last_preemptions_total: int | None = None
    recovery_probe_in_flight: bool = False



@dataclass(frozen=True, slots=True)
class _PoolWaiter:
    ticket: int
    owner_id: str

class AdaptiveModelEndpointPool:
    """Single adaptive dispatch machine for every frozen endpoint replica set."""

    def __init__(
        self,
        replica_set: ModelEndpointReplicaSet,
        endpoint_factory: Callable[[object], ModelEndpointPort],
        *,
        selection_policy: ModelEndpointReplicaSelectionPolicyPort | None = None,
        adaptive_window_policy: AdaptiveRequestWindowPolicy | None = None,
        retry_policy: ModelRequestRetryPolicy | None = None,
        sleep: Callable[[float], None] = time.sleep,
        ewma_alpha: float = 0.2,
        failure_cooldown_seconds: float = 2.0,
        max_failure_cooldown_seconds: float = 30.0,
        max_prefix_affinity_entries_per_replica: int = 4096,
        max_prefix_affinity_keys_per_request: int = 32,
        pressure_observer: ModelRuntimePressureObserverPort | None = None,
        pressure_task_group: TaskGroupPort | None = None,
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
        for name, value in (
            (
                "max_prefix_affinity_entries_per_replica",
                max_prefix_affinity_entries_per_replica,
            ),
            (
                "max_prefix_affinity_keys_per_request",
                max_prefix_affinity_keys_per_request,
            ),
        ):
            if type(value) is not int or value <= 0:
                raise ValueError(f"endpoint pool {name} must be a positive integer")
        self._replica_set_digest = replica_set_digest
        self._selection_policy = (
            AdaptiveLeastPressureReplicaSelectionPolicy()
            if selection_policy is None
            else selection_policy
        )
        if not isinstance(self._selection_policy, ModelEndpointReplicaSelectionPolicyPort):
            raise TypeError("model endpoint selection_policy has invalid port type")
        self._selection_policy_digest = self._selection_policy.identity_digest
        if (
            type(self._selection_policy_digest) is not str
            or len(self._selection_policy_digest) != 64
            or any(char not in "0123456789abcdef" for char in self._selection_policy_digest)
        ):
            raise ValueError("model endpoint selection policy identity must be SHA-256")
        self._clock = clock
        self._adaptive_window_policy = (
            AdaptiveRequestWindowPolicy()
            if adaptive_window_policy is None
            else adaptive_window_policy
        )
        if not isinstance(self._adaptive_window_policy, AdaptiveRequestWindowPolicy):
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
        self._max_prefix_affinity_entries = max_prefix_affinity_entries_per_replica
        self._max_prefix_affinity_keys = max_prefix_affinity_keys_per_request
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
        self._waiter_owner_heap: list[tuple[tuple[int, int, int], int]] = []
        self._active_by_owner: dict[str, int] = {}
        self._owner_last_grant: dict[str, int] = {}
        self._runtimes: dict[str, _ReplicaRuntime] = {}
        self._bindings = {item.deployment_id: item for item in replicas}
        self._single_replica = len(replicas) == 1
        if len(self._bindings) != len(replicas):
            raise ValueError("adaptive model endpoint pool deployments must be unique")
        for binding in replicas:
            endpoint = endpoint_factory(binding)
            if endpoint.route.deployment_id != binding.deployment_id:
                raise ValueError("endpoint factory deployment identity drift")
            if endpoint.route.deployment_generation != binding.deployment_generation:
                raise ValueError("endpoint factory deployment generation drift")
            capacity = binding.max_admitted_concurrency
            preferred = getattr(
                binding,
                "preferred_admitted_concurrency",
                None,
            )
            self._runtimes[binding.deployment_id] = _ReplicaRuntime(
                endpoint=endpoint,
                capacity=capacity,
                adaptive_window=AdaptiveRequestWindow(
                    max_limit=capacity,
                    policy=self._adaptive_window_policy,
                    initial_limit=preferred,
                    clock=self._clock,
                ),
            )

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
                    previous = runtime.last_preemptions_total
                    runtime.last_preemptions_total = (
                        snapshot.preemptions_total
                    )
                    runtime.pressure_snapshot = snapshot
                    runtime.adaptive_window.on_runtime_pressure(
                        snapshot,
                        previous_preemptions_total=previous,
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

    def _owner_waiter_key_locked(
        self,
        waiter: _PoolWaiter,
    ) -> tuple[int, int, int]:
        return (
            self._active_by_owner.get(waiter.owner_id, 0),
            self._owner_last_grant.get(waiter.owner_id, -1),
            waiter.ticket,
        )

    def _compact_owner_heap_locked(self) -> None:
        owner_count = len(self._waiters_by_owner)
        if not owner_count:
            self._waiter_owner_heap.clear()
            return
        # Lazy decrease-key avoids an indexed-heap implementation on every
        # grant/release. Periodic rebuild bounds stale nodes to O(owners), so a
        # long-lived shared model pool cannot accumulate one heap row per
        # historical request.
        if len(self._waiter_owner_heap) <= max(64, owner_count * 4):
            return
        self._waiter_owner_heap = [
            (
                self._owner_waiter_key_locked(next(iter(queue.values()))),
                next(iter(queue.values())).ticket,
            )
            for queue in self._waiters_by_owner.values()
            if queue
        ]
        heapq.heapify(self._waiter_owner_heap)

    def _push_owner_head_locked(self, owner_id: str) -> None:
        queue = self._waiters_by_owner.get(owner_id)
        if not queue:
            return
        waiter = next(iter(queue.values()))
        heapq.heappush(
            self._waiter_owner_heap,
            (self._owner_waiter_key_locked(waiter), waiter.ticket),
        )
        self._compact_owner_heap_locked()

    def _enqueue_waiter_locked(self, waiter: _PoolWaiter) -> None:
        queue = self._waiters_by_owner.get(waiter.owner_id)
        new_head = queue is None or not queue
        if queue is None:
            queue = OrderedDict()
            self._waiters_by_owner[waiter.owner_id] = queue
        if waiter.ticket in queue:
            raise RuntimeError("duplicate model endpoint waiter ticket")
        queue[waiter.ticket] = waiter
        self._waiters_by_ticket[waiter.ticket] = waiter
        self._waiter_conditions[waiter.ticket] = Condition(self._lock)
        self._waiter_count += 1
        if new_head:
            self._push_owner_head_locked(waiter.owner_id)
        self._invalidate_waiter_selection_locked()

    def _remove_waiter_locked(self, waiter: _PoolWaiter) -> bool:
        queue = self._waiters_by_owner.get(waiter.owner_id)
        if queue is None:
            return False
        was_head = next(iter(queue.values()), None) is waiter
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
        elif was_head:
            self._push_owner_head_locked(waiter.owner_id)
        self._invalidate_waiter_selection_locked()
        return True

    def _selected_waiter_locked(self) -> _PoolWaiter | None:
        if self._waiter_count == 0:
            return None
        if self._waiter_selection_cache_version == self._waiter_selection_version:
            ticket = self._waiter_selection_cache_ticket
            return None if ticket is None else self._waiters_by_ticket.get(ticket)

        selected: _PoolWaiter | None = None
        while self._waiter_owner_heap:
            stored_key, ticket = self._waiter_owner_heap[0]
            waiter = self._waiters_by_ticket.get(ticket)
            if waiter is None:
                heapq.heappop(self._waiter_owner_heap)
                continue
            queue = self._waiters_by_owner.get(waiter.owner_id)
            if not queue or next(iter(queue.values())) is not waiter:
                heapq.heappop(self._waiter_owner_heap)
                continue
            current_key = self._owner_waiter_key_locked(waiter)
            if current_key != stored_key:
                heapq.heapreplace(
                    self._waiter_owner_heap,
                    (current_key, waiter.ticket),
                )
                continue
            selected = waiter
            break

        if selected is None and self._waiter_count:
            raise RuntimeError("model endpoint owner-head heap lost queued waiters")
        self._waiter_selection_cache_version = self._waiter_selection_version
        self._waiter_selection_cache_ticket = (
            None if selected is None else selected.ticket
        )
        return selected

    def _wait_for_waiter_signal_locked(
        self,
        waiter: _PoolWaiter,
        *,
        timeout_seconds: float | None = None,
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
        condition.wait(
            None if timeout_seconds is None else float(timeout_seconds)
        )

    def _notify_selected_waiter_locked(self) -> None:
        if self._waiter_count == 0:
            return
        selected = self._selected_waiter_locked()
        if selected is None:
            return
        condition = self._waiter_conditions.get(selected.ticket)
        if condition is None:
            raise RuntimeError("model endpoint selected waiter condition disappeared")
        condition.notify()

    def _notify_all_waiters_locked(self) -> None:
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

    def _selection_candidate_locked(
        self,
        affinity_keys: tuple[str, ...],
        attempted_deployments: frozenset[str],
    ) -> tuple[float, object | None, _ReplicaRuntime | None, int, float | None]:
        """Select one replica under the pool lock without changing admission state."""

        now = self._clock()
        eligible = [
            (self._bindings[deployment_id], runtime)
            for deployment_id, runtime in self._runtimes.items()
            if (
                runtime.cooldown_until <= now
                and not (
                    runtime.consecutive_failures > 0
                    and runtime.recovery_probe_in_flight
                )
            )
        ]
        if not eligible:
            cooling_until = tuple(
                runtime.cooldown_until
                for runtime in self._runtimes.values()
                if runtime.cooldown_until > now
            )
            return (
                now,
                None,
                None,
                0,
                None if not cooling_until else min(cooling_until),
            )

        candidate_rows = []
        affinity_depth_by_deployment: dict[str, int] = {}
        for binding, runtime in eligible:
            deepest = 0
            for index, key in enumerate(affinity_keys, start=1):
                if key in runtime.prefix_affinity:
                    deepest = index
            affinity_score = (
                0.0
                if not affinity_keys or deepest == 0
                else deepest / len(affinity_keys)
            )
            affinity_depth_by_deployment[binding.deployment_id] = deepest
            pressure = self._fresh_pressure_locked(runtime, now)
            candidate_rows.append(
                ModelEndpointReplicaSelectionCandidate(
                    deployment_id=binding.deployment_id,
                    capacity=runtime.adaptive_window.limit,
                    in_flight=runtime.in_flight,
                    completed=runtime.completed,
                    failures=runtime.failures,
                    selections=runtime.selections,
                    consecutive_failures=runtime.consecutive_failures,
                    ewma_latency_seconds=runtime.ewma_latency_seconds,
                    last_selected_sequence=runtime.last_selected_sequence,
                    attempted_in_dispatch=(
                        binding.deployment_id in attempted_deployments
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
                )
            )
        selected_id = self._selection_policy.select(tuple(candidate_rows))
        binding = self._bindings.get(selected_id)
        runtime = self._runtimes.get(selected_id)
        if (
            binding is None
            or runtime is None
            or runtime.cooldown_until > now
        ):
            raise ModelEndpointPoolUnavailable(
                "model endpoint selection policy chose an unavailable replica: "
                f"{selected_id!r}"
            )
        return (
            now,
            binding,
            runtime,
            affinity_depth_by_deployment[selected_id],
            None,
        )

    def _admit_selected_locked(
        self,
        *,
        owner_id: str,
        binding: object,
        runtime: _ReplicaRuntime,
        prefix_affinity_depth: int,
    ) -> tuple[int, object, _ReplicaRuntime]:
        self._selection_sequence += 1
        sequence = self._selection_sequence
        runtime.in_flight += 1
        runtime.selections += 1
        runtime.last_selected_sequence = sequence
        if runtime.consecutive_failures > 0:
            if runtime.recovery_probe_in_flight:
                raise RuntimeError(
                    "model endpoint recovery probe admission raced"
                )
            runtime.recovery_probe_in_flight = True
        self._active_by_owner[owner_id] = (
            self._active_by_owner.get(owner_id, 0) + 1
        )
        self._owner_last_grant[owner_id] = sequence
        self._push_owner_head_locked(owner_id)
        self._invalidate_waiter_selection_locked()
        if prefix_affinity_depth > 0:
            runtime.prefix_affinity_selections += 1
        self._notify_selected_waiter_locked()
        return sequence, binding, runtime

    def _select(
        self,
        affinity_keys: tuple[str, ...],
        attempted_deployments: frozenset[str],
        *,
        owner_id: str,
    ) -> tuple[int, object, _ReplicaRuntime]:
        if type(owner_id) is not str or not owner_id.strip():
            raise ValueError("model endpoint pool owner_id must be non-empty text")
        owner_id = owner_id.strip()
        with self._cv:
            if self._closed:
                raise ModelEndpointPoolUnavailable(
                    "model endpoint pool is closed"
                )

            # Uncontended admission pays no waiter/Condition/heap allocation.
            # Fairness is unaffected because this path is legal only when there
            # is no queued owner to preserve ahead of the arriving request.
            if self._waiter_count == 0:
                (
                    _now,
                    binding,
                    runtime,
                    affinity_depth,
                    _cooling_until,
                ) = self._selection_candidate_locked(
                    affinity_keys,
                    attempted_deployments,
                )
                if (
                    binding is not None
                    and runtime is not None
                    and runtime.in_flight < runtime.adaptive_window.limit
                ):
                    return self._admit_selected_locked(
                        owner_id=owner_id,
                        binding=binding,
                        runtime=runtime,
                        prefix_affinity_depth=affinity_depth,
                    )

            waiter = _PoolWaiter(self._next_waiter_ticket, owner_id)
            self._next_waiter_ticket += 1
            self._enqueue_waiter_locked(waiter)
            admitted = False
            try:
                while True:
                    if self._closed:
                        raise ModelEndpointPoolUnavailable(
                            "model endpoint pool is closed"
                        )
                    if self._selected_waiter_locked() is not waiter:
                        self._wait_for_waiter_signal_locked(waiter)
                        continue

                    (
                        now,
                        binding,
                        runtime,
                        affinity_depth,
                        cooling_until,
                    ) = self._selection_candidate_locked(
                        affinity_keys,
                        attempted_deployments,
                    )
                    if binding is None or runtime is None:
                        if cooling_until is not None:
                            self._wait_for_waiter_signal_locked(
                                waiter,
                                timeout_seconds=max(
                                    0.0,
                                    cooling_until - now,
                                ),
                            )
                        else:
                            self._wait_for_waiter_signal_locked(waiter)
                        continue

                    if runtime.in_flight >= runtime.adaptive_window.limit:
                        self._wait_for_waiter_signal_locked(waiter)
                        continue

                    self._remove_waiter_locked(waiter)
                    admitted = True
                    return self._admit_selected_locked(
                        owner_id=owner_id,
                        binding=binding,
                        runtime=runtime,
                        prefix_affinity_depth=affinity_depth,
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
        outcome: str,
        affinity_keys: tuple[str, ...] = (),
        output_tokens: int | None = None,
    ) -> None:
        if outcome not in {"completed", "request_rejected", "replica_failed"}:
            raise ValueError(f"unknown model endpoint dispatch outcome: {outcome!r}")
        now = self._clock()
        deployment_id = runtime.endpoint.route.deployment_id
        with self._cv:
            if runtime.in_flight <= 0:
                raise RuntimeError("endpoint pool in-flight accounting underflow")
            active = self._active_by_owner.get(owner_id, 0)
            if active <= 0:
                raise RuntimeError("endpoint pool owner in-flight accounting underflow")
            if active == 1:
                self._active_by_owner.pop(owner_id, None)
            else:
                self._active_by_owner[owner_id] = active - 1
            self._push_owner_head_locked(owner_id)
            self._invalidate_waiter_selection_locked()
            demand_pressure = (
                self._waiter_count > 0
                or runtime.in_flight >= runtime.adaptive_window.limit
            )
            runtime.in_flight -= 1
            runtime.recovery_probe_in_flight = False
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
                service_seconds_per_output_token = (
                    None
                    if (
                        elapsed_seconds <= 0
                        or output_tokens is None
                        or output_tokens <= 0
                    )
                    else elapsed_seconds / output_tokens
                )
                runtime.adaptive_window.on_clean_completion(
                    service_seconds_per_output_token=(
                        service_seconds_per_output_token
                    ),
                    demand_pressure=demand_pressure,
                )
                runtime.consecutive_failures = 0
                runtime.cooldown_until = 0.0
                for key in affinity_keys:
                    runtime.prefix_affinity[key] = None
                    runtime.prefix_affinity.move_to_end(key)
                while len(runtime.prefix_affinity) > self._max_prefix_affinity_entries:
                    runtime.prefix_affinity.popitem(last=False)
                if runtime.ewma_latency_seconds is None:
                    runtime.ewma_latency_seconds = elapsed_seconds
                else:
                    runtime.ewma_latency_seconds = (
                        self._ewma_alpha * elapsed_seconds
                        + (1.0 - self._ewma_alpha)
                        * runtime.ewma_latency_seconds
                    )
            self._notify_selected_waiter_locked()
        self._schedule_pressure_probe(deployment_id, runtime)

    def _affinity_keys_for_request(
        self,
        request: ModelEndpointEnvelope,
        body: Mapping[str, JsonInput],
    ) -> tuple[str, ...]:
        # Prefix affinity exists only to choose among interchangeable physical
        # replicas. A single-replica pool has no routing decision to improve,
        # so hashing prompt/tool/message prefixes is pure per-request latency.
        if self._single_replica:
            return ()
        return _request_prefix_affinity_keys(
            request,
            body,
            max_keys=self._max_prefix_affinity_keys,
        )

    def complete(
        self,
        request: ModelEndpointEnvelope,
        body: Mapping[str, JsonInput],
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

        affinity_keys = self._affinity_keys_for_request(request, body)
        owner_id = model_request_owner_id(request)
        attempts: list[ModelEndpointDispatchAttempt] = []
        attempted_deployments: set[str] = set()
        for attempt_number in range(1, self._retry_policy.max_attempts + 1):
            sequence, binding, runtime = self._select(
                affinity_keys,
                frozenset(attempted_deployments),
                owner_id=owner_id,
            )
            attempted_deployments.add(binding.deployment_id)
            physical_request = ModelEndpointRequest(
                request=request,
                deployment_id=binding.deployment_id,
                deployment_generation=binding.deployment_generation,
                body=body,
            )
            started = self._clock()
            try:
                response = runtime.endpoint.complete(physical_request)
            except ModelEndpointError as exc:
                if exc.failure_kind == "rate_limit":
                    runtime.adaptive_window.on_rate_limit()
                elif exc.failure_kind == "capacity":
                    runtime.adaptive_window.on_capacity_pressure()
                elif exc.retryable:
                    runtime.adaptive_window.on_transient_failure()
                outcome = (
                    "replica_failed"
                    if exc.affects_replica_health
                    else "request_rejected"
                )
                elapsed = max(0.0, self._clock() - started)
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    outcome=outcome,
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
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    outcome="replica_failed",
                )
                attempts.append(
                    ModelEndpointDispatchAttempt(
                        attempt_number=attempt_number,
                        deployment_id=binding.deployment_id,
                        selection_sequence=sequence,
                        elapsed_seconds=elapsed,
                        outcome="replica_failed",
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
            self._finish(
                runtime,
                owner_id=owner_id,
                elapsed_seconds=elapsed,
                outcome="completed",
                affinity_keys=affinity_keys,
                output_tokens=response.output_tokens,
            )
            attempts.append(
                ModelEndpointDispatchAttempt(
                    attempt_number=attempt_number,
                    deployment_id=binding.deployment_id,
                    selection_sequence=sequence,
                    elapsed_seconds=elapsed,
                    outcome="completed",
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
        stream_idle_timeout_s: float = 30.0,
    ) -> ModelEndpointDispatchResult:
        if not isinstance(request,ModelRequestEnvelope):
            raise TypeError("endpoint pool streaming requires ModelRequestEnvelope")
        if not isinstance(body,Mapping):
            raise TypeError("endpoint pool streaming body must be a mapping")
        if not callable(on_event):
            raise TypeError("endpoint pool streaming on_event must be callable")
        if (
            isinstance(stream_idle_timeout_s,bool)
            or not isinstance(stream_idle_timeout_s,(int,float))
            or not math.isfinite(float(stream_idle_timeout_s))
            or float(stream_idle_timeout_s) <= 0
        ):
            raise ValueError("endpoint pool stream idle timeout must be finite and positive")

        affinity_keys=self._affinity_keys_for_request(request, body)
        owner_id=model_request_owner_id(request)
        attempts: list[ModelEndpointDispatchAttempt]=[]
        attempted_deployments: set[str]=set()
        for attempt_number in range(1,self._retry_policy.max_attempts+1):
            sequence,binding,runtime=self._select(
                affinity_keys,
                frozenset(attempted_deployments),
                owner_id=owner_id,
            )
            attempted_deployments.add(binding.deployment_id)
            physical_request=ModelEndpointRequest(
                request=request,
                deployment_id=binding.deployment_id,
                deployment_generation=binding.deployment_generation,
                body=body,
            )
            started=self._clock()
            emitted=0

            def forward(event: ModelStreamEvent) -> None:
                nonlocal emitted
                if not isinstance(event,ModelStreamEvent):
                    raise TypeError("endpoint stream emitted untyped event")
                normalized=replace(event,attempt_number=attempt_number)
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
                    stream_idle_timeout_s=float(stream_idle_timeout_s),
                )
            except _StreamConsumerError as exc:
                elapsed=max(0.0,self._clock()-started)
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    outcome="request_rejected",
                )
                raise exc.cause
            except ModelEndpointError as exc:
                if exc.failure_kind == "rate_limit":
                    runtime.adaptive_window.on_rate_limit()
                elif exc.failure_kind == "capacity":
                    runtime.adaptive_window.on_capacity_pressure()
                elif exc.retryable:
                    runtime.adaptive_window.on_transient_failure()
                outcome=(
                    "replica_failed"
                    if exc.affects_replica_health
                    else "request_rejected"
                )
                elapsed=max(0.0,self._clock()-started)
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    outcome=outcome,
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
                self._finish(
                    runtime,
                    owner_id=owner_id,
                    elapsed_seconds=elapsed,
                    outcome="replica_failed",
                )
                attempts.append(ModelEndpointDispatchAttempt(
                    attempt_number=attempt_number,
                    deployment_id=binding.deployment_id,
                    selection_sequence=sequence,
                    elapsed_seconds=elapsed,
                    outcome="replica_failed",
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
            self._finish(
                runtime,
                owner_id=owner_id,
                elapsed_seconds=elapsed,
                outcome="completed",
                affinity_keys=affinity_keys,
                output_tokens=response.output_tokens,
            )
            attempts.append(ModelEndpointDispatchAttempt(
                attempt_number=attempt_number,
                deployment_id=binding.deployment_id,
                selection_sequence=sequence,
                elapsed_seconds=elapsed,
                outcome="completed",
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
        with self._cv:
            if self._closed:
                return
            in_flight={
                deployment_id: runtime.in_flight
                for deployment_id,runtime in self._runtimes.items()
                if runtime.in_flight
            }
            if in_flight:
                raise RuntimeError(
                    "cannot close model endpoint pool with in-flight requests: "
                    f"{in_flight}"
                )
            self._closed=True
            self._notify_all_waiters_locked()
            endpoints=tuple(
                runtime.endpoint
                for _deployment_id,runtime in sorted(self._runtimes.items())
            )
        errors=[]
        for endpoint in reversed(endpoints):
            closer=getattr(endpoint,"close",None)
            if callable(closer):
                try:
                    closer()
                except BaseException as exc:
                    errors.append(exc)
        if errors:
            raise ExceptionGroup(
                "model endpoint pool transport shutdown failed",
                errors,
            )

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
                        prefix_affinity_entries=len(runtime.prefix_affinity),
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
                    )
                )
            return ModelEndpointPoolSnapshot(
                replica_set_digest=self._replica_set_digest,
                selection_policy_digest=self._selection_policy_digest,
                selection_sequence=self._selection_sequence,
                replicas=tuple(rows),
            )


    @property
    def replica_set(self) -> ModelEndpointReplicaSet:
        return self._replica_set


__all__ = [
    "AdaptiveModelEndpointPool",
    "ModelEndpointPoolUnavailable",
]
