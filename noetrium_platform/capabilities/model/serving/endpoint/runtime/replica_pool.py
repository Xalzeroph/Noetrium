from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from threading import Lock
import math
import time

from noetrium_platform.capabilities.model.request.api import ModelRequestEnvelope
from noetrium_platform.foundation.kernel.kernel import JsonInput
from noetrium_platform.capabilities.model.serving.endpoint.api.contracts import (
    ModelEndpointRequest,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.ports import ModelEndpointPort
from noetrium_platform.capabilities.model.serving.endpoint.api.replica import (
    ModelEndpointDispatchResult,
    ModelEndpointPoolSnapshot,
    ModelEndpointReplicaSnapshot,
    OperationalModelEndpointReplicaSet,
    QualifiedModelEndpointReplicaSet,
)


class ModelEndpointPoolUnavailable(RuntimeError):
    pass


@dataclass(slots=True)
class _ReplicaRuntime:
    endpoint: ModelEndpointPort
    capacity: int
    in_flight: int = 0
    completed: int = 0
    failures: int = 0
    selections: int = 0
    consecutive_failures: int = 0
    ewma_latency_seconds: float | None = None
    cooldown_until: float = 0.0
    last_selected_sequence: int = 0


class _AdaptiveModelEndpointPoolCore:
    """Work-conserving routing shared by operational and qualified pools."""

    def __init__(
        self,
        replicas: tuple[object, ...],
        replica_set_digest: str,
        endpoint_factory: Callable[[object], ModelEndpointPort],
        *,
        ewma_alpha: float = 0.2,
        failure_cooldown_seconds: float = 2.0,
        max_failure_cooldown_seconds: float = 30.0,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        if type(replicas) is not tuple or not replicas:
            raise ValueError("adaptive model endpoint pool requires at least one replica")
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
        self._clock = clock
        self._ewma_alpha = float(ewma_alpha)
        self._failure_cooldown = float(failure_cooldown_seconds)
        self._max_failure_cooldown = float(max_failure_cooldown_seconds)
        self._lock = Lock()
        self._selection_sequence = 0
        self._runtimes: dict[str, _ReplicaRuntime] = {}
        self._bindings = {item.deployment_id: item for item in replicas}
        if len(self._bindings) != len(replicas):
            raise ValueError("adaptive model endpoint pool deployments must be unique")
        for binding in replicas:
            endpoint = endpoint_factory(binding)
            if endpoint.route.deployment_id != binding.deployment_id:
                raise ValueError("endpoint factory deployment identity drift")
            if endpoint.route.deployment_generation != binding.deployment_generation:
                raise ValueError("endpoint factory deployment generation drift")
            self._runtimes[binding.deployment_id] = _ReplicaRuntime(
                endpoint=endpoint,
                capacity=binding.max_admitted_concurrency,
            )

    def _select(self) -> tuple[int, object, _ReplicaRuntime]:
        now = self._clock()
        with self._lock:
            available = [
                (self._bindings[deployment_id], runtime)
                for deployment_id, runtime in self._runtimes.items()
                if runtime.cooldown_until <= now
            ]
            if not available:
                raise ModelEndpointPoolUnavailable(
                    "all model endpoint replicas are cooling down after failures"
                )

            def score(row):
                binding, runtime = row
                saturated = 1 if runtime.in_flight >= runtime.capacity else 0
                normalized_load = runtime.in_flight / runtime.capacity
                latency = runtime.ewma_latency_seconds
                # Unmeasured replicas are intentionally preferred over already
                # measured replicas at equal pressure so cold replicas receive work.
                latency_rank = -1.0 if latency is None else latency
                return (
                    saturated,
                    normalized_load,
                    runtime.consecutive_failures,
                    latency_rank,
                    runtime.last_selected_sequence,
                    binding.deployment_id,
                )

            binding, runtime = min(available, key=score)
            self._selection_sequence += 1
            sequence = self._selection_sequence
            runtime.in_flight += 1
            runtime.selections += 1
            runtime.last_selected_sequence = sequence
            return sequence, binding, runtime

    def _finish(
        self,
        runtime: _ReplicaRuntime,
        *,
        elapsed_seconds: float,
        failed: bool,
    ) -> None:
        now = self._clock()
        with self._lock:
            if runtime.in_flight <= 0:
                raise RuntimeError("endpoint pool in-flight accounting underflow")
            runtime.in_flight -= 1
            if failed:
                runtime.failures += 1
                runtime.consecutive_failures += 1
                cooldown = min(
                    self._max_failure_cooldown,
                    self._failure_cooldown
                    * (2 ** max(0, runtime.consecutive_failures - 1)),
                )
                runtime.cooldown_until = now + cooldown
                return
            runtime.completed += 1
            runtime.consecutive_failures = 0
            runtime.cooldown_until = 0.0
            if runtime.ewma_latency_seconds is None:
                runtime.ewma_latency_seconds = elapsed_seconds
            else:
                runtime.ewma_latency_seconds = (
                    self._ewma_alpha * elapsed_seconds
                    + (1.0 - self._ewma_alpha) * runtime.ewma_latency_seconds
                )

    def complete(
        self,
        request: ModelRequestEnvelope,
        body: Mapping[str, JsonInput],
    ) -> ModelEndpointDispatchResult:
        if not isinstance(request, ModelRequestEnvelope):
            raise TypeError("endpoint pool request must be ModelRequestEnvelope")
        if not isinstance(body, Mapping):
            raise TypeError("endpoint pool body must be a mapping")
        sequence, binding, runtime = self._select()
        physical_request = ModelEndpointRequest(
            request=request,
            deployment_id=binding.deployment_id,
            deployment_generation=binding.deployment_generation,
            body=body,
        )
        started = self._clock()
        try:
            response = runtime.endpoint.complete(physical_request)
        except BaseException:
            self._finish(
                runtime,
                elapsed_seconds=max(0.0, self._clock() - started),
                failed=True,
            )
            raise
        self._finish(
            runtime,
            elapsed_seconds=max(0.0, self._clock() - started),
            failed=False,
        )
        return ModelEndpointDispatchResult(
            request=physical_request,
            response=response,
            replica_set_digest=self._replica_set_digest,
            selection_sequence=sequence,
        )

    def snapshot(self) -> ModelEndpointPoolSnapshot:
        now = self._clock()
        with self._lock:
            rows = tuple(
                ModelEndpointReplicaSnapshot(
                    deployment_id=deployment_id,
                    deployment_generation=self._bindings[deployment_id].deployment_generation,
                    capacity=runtime.capacity,
                    in_flight=runtime.in_flight,
                    completed=runtime.completed,
                    failures=runtime.failures,
                    selections=runtime.selections,
                    consecutive_failures=runtime.consecutive_failures,
                    ewma_latency_seconds=runtime.ewma_latency_seconds,
                    cooling_down=runtime.cooldown_until > now,
                )
                for deployment_id, runtime in sorted(self._runtimes.items())
            )
            return ModelEndpointPoolSnapshot(
                replica_set_digest=self._replica_set_digest,
                selection_sequence=self._selection_sequence,
                replicas=rows,
            )


class AdaptiveOperationalModelEndpointPool(_AdaptiveModelEndpointPoolCore):
    """Adaptive dispatch across frozen routes without qualification claims."""

    def __init__(
        self,
        replica_set: OperationalModelEndpointReplicaSet,
        endpoint_factory: Callable[[object], ModelEndpointPort],
        **kwargs,
    ) -> None:
        if not isinstance(replica_set, OperationalModelEndpointReplicaSet):
            raise TypeError("operational endpoint pool requires operational replica set")
        self._operational_replica_set = replica_set
        super().__init__(
            replica_set.replicas,
            replica_set.replica_set_digest,
            endpoint_factory,
            **kwargs,
        )

    @property
    def replica_set(self) -> OperationalModelEndpointReplicaSet:
        return self._operational_replica_set


class AdaptiveQualifiedModelEndpointPool(_AdaptiveModelEndpointPoolCore):
    """Adaptive dispatch across replicas proven scientifically interchangeable.

    Every replica must already prove the same immutable model, stack, tokenizer,
    chat template, role and prompt generation. Requests are never transparently
    replayed after an endpoint failure because the failed invocation may have an
    uncertain external effect/cost.
    """

    def __init__(
        self,
        replica_set: QualifiedModelEndpointReplicaSet,
        endpoint_factory: Callable[[object], ModelEndpointPort],
        **kwargs,
    ) -> None:
        if not isinstance(replica_set, QualifiedModelEndpointReplicaSet):
            raise TypeError("qualified endpoint pool requires qualified replica set")
        self._qualified_replica_set = replica_set
        super().__init__(
            replica_set.bindings,
            replica_set.replica_set_digest,
            endpoint_factory,
            **kwargs,
        )

    @property
    def replica_set(self) -> QualifiedModelEndpointReplicaSet:
        return self._qualified_replica_set


__all__ = [
    "AdaptiveOperationalModelEndpointPool",
    "AdaptiveQualifiedModelEndpointPool",
    "ModelEndpointPoolUnavailable",
]
