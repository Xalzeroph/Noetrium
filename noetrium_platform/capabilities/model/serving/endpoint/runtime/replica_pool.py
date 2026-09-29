from __future__ import annotations

from collections import OrderedDict
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field, replace
from hashlib import sha256
from threading import Condition, Lock
import math
import time

from noetrium_platform.capabilities.model.request.api import (
    ModelEndpointEnvelope, ModelOperationEnvelope, ModelRequestEnvelope,
)
from noetrium_platform.foundation.kernel.kernel import JsonInput, canonical_bytes
from noetrium_platform.capabilities.model.serving.endpoint.api.contracts import (
    ModelEndpointError,
    ModelEndpointRequest,
)
from noetrium_platform.capabilities.model.serving.endpoint.api.ports import ModelEndpointPort
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
                "tools": body.get("tools"),
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
        self._lock = Lock()
        self._cv = Condition(self._lock)
        self._selection_sequence = 0
        self._closed = False
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
            capacity = binding.max_admitted_concurrency
            self._runtimes[binding.deployment_id] = _ReplicaRuntime(
                endpoint=endpoint,
                capacity=capacity,
                adaptive_window=AdaptiveRequestWindow(
                    max_limit=capacity,
                    policy=self._adaptive_window_policy,
                    clock=self._clock,
                ),
            )

    def _select(
        self,
        affinity_keys: tuple[str, ...],
        attempted_deployments: frozenset[str],
    ) -> tuple[int, object, _ReplicaRuntime]:
        with self._cv:
            while True:
                if self._closed:
                    raise ModelEndpointPoolUnavailable(
                        "model endpoint pool is closed"
                    )
                now = self._clock()
                eligible = [
                    (self._bindings[deployment_id], runtime)
                    for deployment_id, runtime in self._runtimes.items()
                    if runtime.cooldown_until <= now
                ]
                if not eligible:
                    raise ModelEndpointPoolUnavailable(
                        "all model endpoint replicas are cooling down after failures"
                    )

                candidate_rows = []
                affinity_by_deployment: dict[str, tuple[float, int]] = {}
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
                    affinity_by_deployment[binding.deployment_id] = (
                        affinity_score,
                        deepest,
                    )
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
                        )
                    )
                candidates = tuple(candidate_rows)
                selected_id = self._selection_policy.select(candidates)
                selected = tuple(
                    row
                    for row in eligible
                    if row[0].deployment_id == selected_id
                )
                if len(selected) != 1:
                    raise ModelEndpointPoolUnavailable(
                        "model endpoint selection policy chose an unavailable replica: "
                        f"{selected_id!r}"
                    )
                binding, runtime = selected[0]

                # A healthy replica at its adaptive window is not a failure.
                # Wait until a completion changes pressure and then rerun the
                # complete selection policy against fresh health/load/locality.
                # This preserves the adaptive limit instead of bypassing it via
                # the lower deployment admission controller.
                if runtime.in_flight >= runtime.adaptive_window.limit:
                    self._cv.wait()
                    continue

                self._selection_sequence += 1
                sequence = self._selection_sequence
                runtime.in_flight += 1
                runtime.selections += 1
                runtime.last_selected_sequence = sequence
                if affinity_by_deployment[selected_id][1] > 0:
                    runtime.prefix_affinity_selections += 1
                return sequence, binding, runtime

    def _finish(
        self,
        runtime: _ReplicaRuntime,
        *,
        elapsed_seconds: float,
        outcome: str,
        affinity_keys: tuple[str, ...] = (),
    ) -> None:
        if outcome not in {"completed", "request_rejected", "replica_failed"}:
            raise ValueError(f"unknown model endpoint dispatch outcome: {outcome!r}")
        now = self._clock()
        with self._cv:
            if runtime.in_flight <= 0:
                raise RuntimeError("endpoint pool in-flight accounting underflow")
            runtime.in_flight -= 1
            if outcome == "request_rejected":
                runtime.request_rejections += 1
                self._cv.notify_all()
                return
            if outcome == "replica_failed":
                runtime.failures += 1
                runtime.consecutive_failures += 1
                cooldown = min(
                    self._max_failure_cooldown,
                    self._failure_cooldown
                    * (2 ** max(0, runtime.consecutive_failures - 1)),
                )
                runtime.cooldown_until = now + cooldown
                self._cv.notify_all()
                return
            runtime.completed += 1
            runtime.adaptive_window.on_clean_completion()
            runtime.consecutive_failures = 0
            runtime.cooldown_until = 0.0
            for key in affinity_keys:
                runtime.prefix_affinity[key] = None
                runtime.prefix_affinity.move_to_end(key)
            while (
                len(runtime.prefix_affinity)
                > self._max_prefix_affinity_entries
            ):
                runtime.prefix_affinity.popitem(last=False)
            if runtime.ewma_latency_seconds is None:
                runtime.ewma_latency_seconds = elapsed_seconds
            else:
                runtime.ewma_latency_seconds = (
                    self._ewma_alpha * elapsed_seconds
                    + (1.0 - self._ewma_alpha) * runtime.ewma_latency_seconds
                )
            self._cv.notify_all()

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

        affinity_keys = _request_prefix_affinity_keys(
            request,
            body,
            max_keys=self._max_prefix_affinity_keys,
        )
        attempts: list[ModelEndpointDispatchAttempt] = []
        attempted_deployments: set[str] = set()
        for attempt_number in range(1, self._retry_policy.max_attempts + 1):
            sequence, binding, runtime = self._select(
                affinity_keys,
                frozenset(attempted_deployments),
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
                    self._retry_policy.wait_seconds(
                        attempt_number=attempt_number,
                        retry_after_seconds=exc.retry_after_seconds,
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
                elapsed_seconds=elapsed,
                outcome="completed",
                affinity_keys=affinity_keys,
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

        affinity_keys=_request_prefix_affinity_keys(
            request,
            body,
            max_keys=self._max_prefix_affinity_keys,
        )
        attempts: list[ModelEndpointDispatchAttempt]=[]
        attempted_deployments: set[str]=set()
        for attempt_number in range(1,self._retry_policy.max_attempts+1):
            sequence,binding,runtime=self._select(
                affinity_keys,
                frozenset(attempted_deployments),
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
                    elapsed_seconds=elapsed,
                    outcome="request_rejected",
                )
                raise exc.cause
            except ModelEndpointError as exc:
                if exc.failure_kind == "rate_limit":
                    runtime.adaptive_window.on_rate_limit()
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
                    self._retry_policy.wait_seconds(
                        attempt_number=attempt_number,
                        retry_after_seconds=exc.retry_after_seconds,
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
                elapsed_seconds=elapsed,
                outcome="completed",
                affinity_keys=affinity_keys,
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
            self._cv.notify_all()
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
                    request_rejections=runtime.request_rejections,
                    adaptive_limit=runtime.adaptive_window.snapshot().current_limit,
                    adaptive_min_limit=runtime.adaptive_window.snapshot().min_limit,
                    adaptive_max_limit=runtime.adaptive_window.snapshot().max_limit,
                    adaptive_scale_up_suspended=(
                        runtime.adaptive_window.snapshot().scale_up_suspended
                    ),
                    adaptive_window_policy_digest=(
                        runtime.adaptive_window.snapshot().policy_digest
                    ),
                    adaptive_window_history=tuple(
                        (
                            event.sequence,
                            event.old_limit,
                            event.new_limit,
                            event.reason,
                            event.observed_at,
                        )
                        for event in runtime.adaptive_window.snapshot().history
                    ),
                    prefix_affinity_entries=len(runtime.prefix_affinity),
                    prefix_affinity_selections=runtime.prefix_affinity_selections,
                )
                for deployment_id, runtime in sorted(self._runtimes.items())
            )
            return ModelEndpointPoolSnapshot(
                replica_set_digest=self._replica_set_digest,
                selection_policy_digest=self._selection_policy_digest,
                selection_sequence=self._selection_sequence,
                replicas=rows,
            )


    @property
    def replica_set(self) -> ModelEndpointReplicaSet:
        return self._replica_set


__all__ = [
    "AdaptiveModelEndpointPool",
    "ModelEndpointPoolUnavailable",
]
