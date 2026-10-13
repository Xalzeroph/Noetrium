from __future__ import annotations

import asyncio
import json
import math
import time
from collections.abc import Callable, Mapping
from dataclasses import replace
from concurrent.futures import CancelledError
from threading import Event, Lock

from noetrium_platform.capabilities.model.serving.api.admission import (
    ModelAdmissionClosed,
    ModelAdmissionLeasePort,
    ModelAdmissionPort,
    ModelAdmissionTimeout,
)
from noetrium_platform.capabilities.model.request.api import (
    ModelOperationEnvelope,
    model_request_owner_id,
)
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AsyncJsonHttpTransportPort,
    JsonHttpResponse,
    ModelStreamEvent,
    SseHttpResponse,
    ModelEndpointError,
    ModelEndpointObserverPort,
    ModelEndpointPort,
    ModelEndpointRequest,
    ModelEndpointRequestRejected,
    ModelEndpointResponse,
    ModelEndpointRoute,
)
from noetrium_platform.capabilities.model.serving.provider import (
    ModelProviderOperationPlan,
    ModelProviderRequestPlanner,
    ModelProviderRequestUnsupported,
    ModelProviderRuntimeError,
    NativeModelOperationProtocolRegistry,
    NativeModelProviderProfileResolver,
    NativeModelProviderProtocolRegistry,
    ModelStreamAccumulator,
    classify_provider_failure,
    provider_error_detail,
    provider_profile_for_protocol,
    stream_decoder_for_protocol,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskCancelled,
    TaskDeadlineExceeded,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.foundation.kernel.kernel import canonical_bytes, thaw_json
from noetrium_platform.capabilities.model.serving.provider.structured_schema import (
    xgrammar_wire_projection, validate_original_structured_response,
)


class _PhysicalRetirementGate:
    """One parent-owned HTTP task held live until its exact Claim is retired.

    The gate is a rendezvous only, not a new task, permit, queue or authority.
    The ASYNC_IO task supplies the physical-completion boundary; its original
    synchronous caller performs the blocking Authority transaction.
    """

    def __init__(self) -> None:
        self.ready = Event()
        self._lock = Lock()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._release: asyncio.Future[None] | None = None
        self._fallback_retire: Callable[[], None] | None = None
        self._physically_completed = False

    async def finish_transport(self) -> None:
        loop = asyncio.get_running_loop()
        future = loop.create_future()
        with self._lock:
            self._loop = loop
            self._release = future
            fallback_retire = self._fallback_retire
            self._fallback_retire = None
            self.ready.set()
        # If the synchronous owner hit its physical deadline before transport
        # convergence, retirement ownership was transferred to this exact
        # physical task.  The Claim remains fenced while HTTP may still run,
        # but the logical caller is free to fail over instead of blocking the
        # whole graph behind an unbounded terminal rendezvous.
        if fallback_retire is not None:
            fallback_retire()
            if not future.done():
                future.set_result(None)
            return
        # Healthy requests retain the zero-secondary-admission fast path: the
        # original synchronous caller commits retirement and then wakes this
        # exact task. Cancellation cannot tear down the task before its Claim.
        while not future.done():
            try:
                await asyncio.shield(future)
            except asyncio.CancelledError:
                task = asyncio.current_task()
                if task is not None:
                    task.uncancel()

    def transfer_retirement(self, retire: Callable[[], None]) -> bool:
        """Transfer Claim retirement iff transport has not reached its fence."""
        if not callable(retire):
            raise TypeError("physical retirement callback must be callable")
        with self._lock:
            if self._release is not None or self._physically_completed:
                return False
            if self._fallback_retire is not None:
                raise RuntimeError("physical Claim retirement already transferred")
            self._fallback_retire = retire
            return True

    def signal_retired(self) -> None:
        with self._lock:
            loop, future = self._loop, self._release
        if loop is not None and future is not None:
            loop.call_soon_threadsafe(
                lambda: future.set_result(None) if not future.done() else None
            )

    def signal_if_never_started(self) -> None:
        # Kernel physical completion may happen before coroutine entry
        # (e.g. task canceled in the provider queue). If timeout ownership was
        # transferred, this callback is the only physical completion boundary
        # and therefore retires the still-fenced Claim exactly once.
        fallback_retire = None
        with self._lock:
            self._physically_completed = True
            if self._release is None and self._fallback_retire is not None:
                fallback_retire = self._fallback_retire
                self._fallback_retire = None
            self.ready.set()
        if fallback_retire is not None:
            fallback_retire()


async def _transport_with_physical_retirement(
    context, gate: _PhysicalRetirementGate, transport_fn, *args,
):
    try:
        return await transport_fn(context, *args)
    finally:
        await gate.finish_transport()


def _usage_token_observation(
    usage: object,
) -> tuple[int | None, int | None, int | None]:
    """Normalize provider token usage without inventing cache observations."""

    if not isinstance(usage, Mapping):
        return None, None, None

    def optional_count(*keys: str) -> int | None:
        for key in keys:
            if key not in usage:
                continue
            value = usage.get(key)
            if value is None:
                continue
            if type(value) is not int or value < 0:
                raise ValueError(
                    f"model provider usage {key} must be a non-negative integer"
                )
            return value
        return None

    input_tokens = optional_count("prompt_tokens", "input_tokens")
    output_tokens = optional_count("completion_tokens", "output_tokens")

    details = usage.get("prompt_tokens_details")
    if details is None:
        details = usage.get("input_tokens_details")
    cached_input_tokens: int | None = None
    if details is not None:
        if not isinstance(details, Mapping):
            raise ValueError(
                "model provider token details must be an object"
            )
        cached = details.get("cached_tokens")
        if cached is not None:
            if type(cached) is not int or cached < 0:
                raise ValueError(
                    "model provider cached_tokens must be a non-negative integer"
                )
            cached_input_tokens = cached

    if cached_input_tokens is not None:
        if input_tokens is None:
            raise ValueError(
                "model provider cached_tokens requires input token usage"
            )
        if cached_input_tokens > input_tokens:
            raise ValueError(
                "model provider cached_tokens exceeds input token usage"
            )
    return input_tokens, output_tokens, cached_input_tokens


_ENDPOINT_INSTANCE_LOCK = Lock()
_ENDPOINT_INSTANCE_SEQUENCE = 0


def _next_endpoint_instance_sequence() -> int:
    global _ENDPOINT_INSTANCE_SEQUENCE
    with _ENDPOINT_INSTANCE_LOCK:
        _ENDPOINT_INSTANCE_SEQUENCE += 1
        return _ENDPOINT_INSTANCE_SEQUENCE


class NativeModelProviderEndpoint(ModelEndpointPort):
    """Single provider-neutral endpoint backed by Noetrium-native protocol codecs."""

    def __init__(
        self,
        *,
        route: ModelEndpointRoute,
        transport: AsyncJsonHttpTransportPort,
        task_group: TaskGroupPort,
        admission: ModelAdmissionPort,
        api_key: str = "",
        profile_resolver: NativeModelProviderProfileResolver | None = None,
        protocols: NativeModelProviderProtocolRegistry | None = None,
        operation_protocols: NativeModelOperationProtocolRegistry | None = None,
        planner: ModelProviderRequestPlanner | None = None,
        observers: tuple[ModelEndpointObserverPort, ...] = (),
        owns_transport: bool = True,
    ) -> None:
        if not isinstance(route, ModelEndpointRoute):
            raise TypeError("native model endpoint requires ModelEndpointRoute")
        if type(api_key) is not str:
            raise TypeError("native model endpoint api_key must be text")
        if type(owns_transport) is not bool:
            raise TypeError("native model endpoint owns_transport must be bool")
        self._route=route
        self.transport=transport
        self._task_group=task_group
        self._admission=admission
        self._api_key=api_key
        self._profiles=profile_resolver or NativeModelProviderProfileResolver()
        self._protocols=protocols or NativeModelProviderProtocolRegistry()
        self._operation_protocols=(
            operation_protocols or NativeModelOperationProtocolRegistry()
        )
        self._planner=planner or ModelProviderRequestPlanner()
        self._observers=tuple(observers)
        self._sequence_lock=Lock()
        self._sequence=0
        self._instance_sequence=_next_endpoint_instance_sequence()
        self._task_namespace=(
            f"{self.route.deployment_generation}:"
            f"{self._instance_sequence}"
        )
        self._owns_transport=owns_transport
        self._closed=False
        self._close_lock=Lock()

    @property
    def route(self) -> ModelEndpointRoute:
        return self._route

    def _next_task_id(self, request_id: str) -> str:
        with self._sequence_lock:
            self._sequence += 1
            sequence=self._sequence
        return (
            f"model-http:{self._task_namespace}:"
            f"{request_id}:{sequence}"
        )

    def _notify_exchange(
        self,
        request: ModelEndpointRequest,
        response: JsonHttpResponse,
        started_monotonic_ns: int,
        completed_monotonic_ns: int,
    ) -> None:
        for observer in self._observers:
            try:
                observer.on_exchange(
                    request,response,started_monotonic_ns,completed_monotonic_ns
                )
            except Exception as exc:
                observer_id=getattr(observer,"observer_id",type(observer).__qualname__)
                raise ModelEndpointError(
                    f"lossless model exchange capture failed: {observer_id}"
                ) from exc

    def _notify_failure(
        self,
        request: ModelEndpointRequest,
        exc: BaseException,
        started_monotonic_ns: int,
        completed_monotonic_ns: int,
    ) -> None:
        for observer in self._observers:
            callback=getattr(observer,"on_failure",None)
            if callable(callback):
                if not isinstance(exc, ModelEndpointError):
                    exc = ModelEndpointError(
                        f"{type(exc).__name__}: {str(exc)[:2048]}",
                        failure_kind="internal",
                        retryable=False,
                        affects_replica_health=False,
                    )
                callback(
                    request,
                    exc,
                    started_monotonic_ns,
                    completed_monotonic_ns,
                )

    def _provider_profile(self, request: ModelEndpointRequest):
        body_model=request.body.get("model")
        if not isinstance(body_model,str) or not body_model.strip():
            raise ModelEndpointRequestRejected(
                "model provider request requires canonical model name",
                request_body=canonical_bytes(request.body),
                status_code=400,
            )
        model=request.request.model
        profile=self._profiles.resolve(
            logical_model_name=body_model,
            provider_model_name=model.model_id,
            model_engine=model.engine,
        )
        if self.route.completion_path.rstrip("/").endswith("/responses"):
            profile = provider_profile_for_protocol(
                profile,
                "openai.responses",
            )
        return profile

    def _plan(self, request: ModelEndpointRequest):
        try:
            profile=self._provider_profile(request)
            plan=self._planner.plan(profile,request.body)
            wire=self._protocols.encode(plan,api_key=self._api_key)
            if plan.profile.provider_id == "vllm":
                projected = xgrammar_wire_projection(wire.body)
                if projected is not None:
                    # Only the provider wire grammar is relaxed. Plan, durable
                    # request and original semantics retain the full schema.
                    wire = replace(
                        wire, body=projected, wire_bytes=canonical_bytes(projected),
                    )
        except ModelProviderRequestUnsupported as exc:
            raise ModelEndpointRequestRejected(
                f"model provider request unsupported: {exc}",
                request_body=canonical_bytes(request.body),
                status_code=400,
            ) from exc
        return plan,wire

    def _plan_stream(self, request: ModelEndpointRequest):
        try:
            profile=self._provider_profile(request)
            body=thaw_json(request.body)
            if not isinstance(body,dict):
                raise ModelProviderRequestUnsupported(
                    "streaming provider request body materialization drift"
                )
            body["stream"]=True
            plan=self._planner.plan_stream(profile,body)
            wire=self._protocols.encode(plan,api_key=self._api_key)
        except ModelProviderRequestUnsupported as exc:
            raise ModelEndpointRequestRejected(
                f"streaming model provider request unsupported: {exc}",
                request_body=canonical_bytes(request.body),
                status_code=400,
            ) from exc
        return plan,wire

    @staticmethod
    def _await_and_retire(
        handle, lease: ModelAdmissionLeasePort,
        *, gate: _PhysicalRetirementGate,
        timeout_seconds: float | None,
        timings_ns: dict[str, int] | None = None,
    ):
        """Synchronous parent finalizer; Kernel task remains live until release."""
        handle.add_done_callback(
            lambda _task: gate.signal_if_never_started()
        )
        ready = gate.ready.wait(timeout_seconds)
        if not ready:
            # Do not wait indefinitely for a transport that has already missed
            # its physical deadline. Transfer retirement to that exact physical
            # task before cancellation so the Claim cannot be reused early.
            # If transport crossed its terminal fence concurrently, ownership
            # stays here and the normal retirement path below remains exact.
            transferred = gate.transfer_retirement(lease.release)
            handle.cancel()
            if transferred:
                raise TimeoutError("model transport physical deadline expired")
            ready = True
        started_ns = time.perf_counter_ns()
        release_failure: BaseException | None = None
        try:
            lease.release()
        except BaseException as exc:
            release_failure = exc
        finally:
            if timings_ns is not None:
                duration_ns = max(0, time.perf_counter_ns() - started_ns)
                timings_ns["authority_release"] = duration_ns
                timings_ns["authority_release_commit"] = duration_ns
            # Always unblock the *same* Kernel task, even on Authority
            # failure, so its existing lifecycle/failure owner can converge.
            gate.signal_retired()
        result = None
        execution_failure: BaseException | None = None
        try:
            result = handle.result(timeout=timeout_seconds)
        except BaseException as exc:
            execution_failure = exc
        if execution_failure is not None:
            if release_failure is not None:
                raise BaseExceptionGroup(
                    "model execution and Resource Authority retirement both failed",
                    [execution_failure, release_failure],
                )
            raise execution_failure
        if release_failure is not None:
            raise release_failure
        return result

    async def _post(
        self,
        context,
        wire,
        timings_ns: dict[str, int] | None = None,
        submitted_ns: int | None = None,
    ) -> JsonHttpResponse:
        entered_ns = time.perf_counter_ns()
        if timings_ns is not None and submitted_ns is not None:
            timings_ns["async_io_dispatch_wait"] = max(0, entered_ns - submitted_ns)
        context.checkpoint()
        remaining=context.remaining_seconds
        timeout_s=(self.route.timeout_s if remaining is None else remaining)
        if timeout_s is not None and timeout_s <= 0:
            context.checkpoint()
            raise TimeoutError("model endpoint deadline expired before transport")
        before_http_ns = time.perf_counter_ns()
        try:
            response=await self.transport.post_json(
                self.route.completion_url,
                wire.wire_bytes,
                timeout_s=timeout_s,
                headers=wire.headers,
            )
        finally:
            if timings_ns is not None:
                timings_ns["http_transport"] = max(0, time.perf_counter_ns() - before_http_ns)
        context.checkpoint()
        return response

    async def _post_stream(
        self,
        context,
        wire,
        decoder,
        accumulator: ModelStreamAccumulator,
        on_event: Callable[[ModelStreamEvent], None],
        idle_timeout_s: float,
    ) -> SseHttpResponse:
        context.checkpoint()
        remaining=context.remaining_seconds
        timeout_s=(self.route.timeout_s if remaining is None else remaining)
        if timeout_s is not None and timeout_s <= 0:
            context.checkpoint()
            raise TimeoutError(
                "model endpoint deadline expired before streaming transport"
            )
        post_sse=getattr(self.transport,"post_sse",None)
        if not callable(post_sse):
            raise ModelEndpointError(
                "configured model transport does not implement SSE streaming",
                request_body=wire.wire_bytes,
                failure_kind="invalid_request",
                retryable=False,
                affects_replica_health=False,
            )

        def on_raw(raw_event) -> None:
            for event in decoder.decode(raw_event):
                accumulator.add(event)
                on_event(event)

        response=await post_sse(
            self.route.completion_url,
            wire.wire_bytes,
            timeout_s=timeout_s,
            idle_timeout_s=(
                None
                if idle_timeout_s is None
                else (
                    float(idle_timeout_s)
                    if timeout_s is None
                    else min(float(idle_timeout_s), timeout_s)
                )
            ),
            on_event=on_raw,
            headers=wire.headers,
        )
        context.checkpoint()
        return response


    def _notify_stream_exchange(
        self,
        request: ModelEndpointRequest,
        response: SseHttpResponse,
        started_monotonic_ns: int,
        completed_monotonic_ns: int,
    ) -> None:
        for observer in self._observers:
            callback=getattr(observer,"on_stream_exchange",None)
            if not callable(callback):
                observer_id=getattr(
                    observer,"observer_id",type(observer).__qualname__
                )
                raise ModelEndpointError(
                    "lossless streaming model exchange capture is unavailable: "
                    f"{observer_id}",
                    request_body=response.request_body,
                    response_body=response.raw_body,
                    status_code=response.status_code,
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                )
            try:
                callback(
                    request,
                    response,
                    started_monotonic_ns,
                    completed_monotonic_ns,
                )
            except Exception as exc:
                observer_id=getattr(
                    observer,"observer_id",type(observer).__qualname__
                )
                raise ModelEndpointError(
                    f"lossless streaming model exchange capture failed: {observer_id}",
                    request_body=response.request_body,
                    response_body=response.raw_body,
                    status_code=response.status_code,
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                ) from exc

    async def _close_owned_transport(self, context) -> None:
        context.checkpoint()
        closer=getattr(self.transport,"aclose",None)
        if callable(closer):
            value=closer()
            if hasattr(value,"__await__"):
                await value
            elif value is not None:
                raise TypeError(
                    "model transport aclose must return awaitable or None"
                )
        else:
            closer=getattr(self.transport,"close",None)
            if callable(closer):
                value=closer()
                if hasattr(value,"__await__"):
                    await value
                elif value is not None:
                    raise TypeError(
                        "model transport close must return awaitable or None"
                    )
        context.checkpoint()

    def close(self) -> None:
        with self._close_lock:
            if self._closed:
                return
            self._closed=True
        if not self._owns_transport:
            return
        closer=getattr(self.transport,"aclose",None)
        sync_closer=getattr(self.transport,"close",None)
        if not callable(closer) and not callable(sync_closer):
            return
        deadline=(
            None
            if self.route.timeout_s is None
            else Deadline.after(self.route.timeout_s)
        )
        handle=self._task_group.submit(
            ExecutionSpec(
                task_id=self._next_task_id("transport-close"),
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            self._close_owned_transport,
            deadline=deadline,
        )
        try:
            handle.result(
                timeout=(
                    None
                    if deadline is None
                    else deadline.remaining_seconds
                )
            )
        except BaseException:
            # Closed is terminal even if physical transport convergence failed;
            # callers must not race new work against uncertain teardown.
            raise

    def complete(self, request: ModelEndpointRequest) -> ModelEndpointResponse:
        with self._close_lock:
            if self._closed:
                raise ModelEndpointError(
                    "model endpoint is closed",
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                )
        started=time.perf_counter_ns()
        try:
            return self._complete(request,started)
        except ModelEndpointError as exc:
            self._notify_failure(request,exc,started,time.perf_counter_ns())
            raise

    def stream(
        self,
        request: ModelEndpointRequest,
        on_event: Callable[[ModelStreamEvent], None],
        *,
        stream_idle_timeout_s: float | None = None,
    ) -> ModelEndpointResponse:
        with self._close_lock:
            if self._closed:
                raise ModelEndpointError(
                    "model endpoint is closed",
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                )
        if not callable(on_event):
            raise TypeError("model stream on_event must be callable")
        if stream_idle_timeout_s is not None and (
            isinstance(stream_idle_timeout_s,bool)
            or not isinstance(stream_idle_timeout_s,(int,float))
            or not math.isfinite(float(stream_idle_timeout_s))
            or float(stream_idle_timeout_s) <= 0
        ):
            raise ValueError(
                "model stream idle timeout must be finite and positive when set"
            )
        started=time.perf_counter_ns()
        try:
            return self._stream(
                request,
                on_event,
                stream_idle_timeout_s=(
                    None
                    if stream_idle_timeout_s is None
                    else float(stream_idle_timeout_s)
                ),
                started_monotonic_ns=started,
            )
        except ModelEndpointError as exc:
            self._notify_failure(
                request,exc,started,time.perf_counter_ns()
            )
            raise

    def _admit_physical_request(
        self,
        request: ModelEndpointRequest,
        *,
        deadline: Deadline | None,
    ) -> ModelAdmissionLeasePort:
        """One Authority admission and one deadline across all provider stages."""
        if deadline is not None and deadline.expired:
            raise ModelEndpointError(
                "model request deadline expired before physical admission",
                failure_kind="timeout", retryable=False,
                affects_replica_health=False,
            )
        try:
            return self._admission.acquire(
                timeout_seconds=(
                    None if deadline is None else deadline.remaining_seconds
                ),
                owner_id=model_request_owner_id(request.request),
                **({} if request.continuity_claim_id is None else {
                    "continuity_claim_id": request.continuity_claim_id,
                }),
            )
        except ModelAdmissionTimeout as exc:
            raise ModelEndpointError(
                "model physical admission exhausted the request deadline",
                failure_kind="timeout", retryable=False,
                affects_replica_health=False,
            ) from exc
        except ModelAdmissionClosed as exc:
            raise ModelEndpointError(
                "model physical admission is closed",
                failure_kind="capacity", retryable=False,
                affects_replica_health=False,
            ) from exc

    def _stream(
        self,
        request: ModelEndpointRequest,
        on_event: Callable[[ModelStreamEvent], None],
        *,
        stream_idle_timeout_s: float | None,
        started_monotonic_ns: int,
    ) -> ModelEndpointResponse:
        if request.deployment_id != self.route.deployment_id:
            raise ModelEndpointError(
                "endpoint stream request deployment does not match route"
            )
        if request.deployment_generation != self.route.deployment_generation:
            raise ModelEndpointError(
                "endpoint stream request deployment generation does not match route"
            )

        request_timeout_s = (
            self.route.timeout_s
            if request.timeout_s is None
            else float(request.timeout_s)
        )
        plan,wire=self._plan_stream(request)
        decoder=stream_decoder_for_protocol(
            plan.profile.protocol_id,
            provider_id=plan.profile.provider_id,
        )
        accumulator=ModelStreamAccumulator(plan)
        lease = self._admit_physical_request(request, deadline=None)
        deadline = (
            None if request_timeout_s is None
            else Deadline.after(request_timeout_s)
        )
        gate = _PhysicalRetirementGate()
        try:
            handle=self._task_group.submit(
                ExecutionSpec(
                    task_id=self._next_task_id(
                        request.request.request_id + ":stream"
                    ),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                _transport_with_physical_retirement,
                gate,
                self._post_stream,
                wire,
                decoder,
                accumulator,
                on_event,
                stream_idle_timeout_s,
                deadline=deadline,
            )
        except BaseException:
            lease.release()
            raise

        try:
            response=self._await_and_retire(
                handle, lease, gate=gate, timeout_seconds=(
                    None if deadline is None else deadline.remaining_seconds
                ),
            )
        except (TimeoutError,TaskDeadlineExceeded) as exc:
            handle.cancel()
            raise ModelEndpointError(
                "model endpoint streaming transport timed out; "
                f"request_id={request.request.request_id}; "
                f"deployment_id={request.deployment_id}; "
                f"timeout_s={request_timeout_s!r}",
                request_body=wire.wire_bytes,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
            ) from exc
        except (TaskCancelled,CancelledError) as exc:
            raise ModelEndpointError(
                "model endpoint streaming transport cancelled at deadline",
                request_body=wire.wire_bytes,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
            ) from exc

        completed_ns=time.perf_counter_ns()
        self._notify_stream_exchange(
            request,response,started_monotonic_ns,completed_ns
        )
        if not 200 <= response.status_code < 300:
            try:
                payload=json.loads(response.raw_body.decode("utf-8"))
            except (UnicodeDecodeError,json.JSONDecodeError):
                payload={
                    "detail":response.raw_body.decode(
                        "utf-8",errors="replace"
                    )[:2048]
                }
            failure=classify_provider_failure(
                status_code=response.status_code,
                payload=payload,
                response_headers=response.response_headers,
            )
            rejected=(
                not failure.retryable
                and not failure.affects_replica_health
            )
            error_type=(
                ModelEndpointRequestRejected
                if rejected
                else ModelEndpointError
            )
            detail=(
                failure.provider_message
                or provider_error_detail(payload)
            )
            raise error_type(
                f"model streaming endpoint returned HTTP "
                f"{response.status_code} [{failure.kind.value}]: {detail}",
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                response_headers=response.response_headers,
                failure_kind=failure.kind.value,
                retryable=failure.retryable,
                retry_after_seconds=failure.retry_after_seconds,
                provider_code=failure.provider_code,
                affects_replica_health=failure.affects_replica_health,
                http_version=response.http_version,
                transport_digest=response.transport_digest,
            )

        try:
            completion=accumulator.completion(
                response_bytes=response.raw_body
            )
        except (ModelProviderRuntimeError,ValueError,TypeError) as exc:
            raise ModelEndpointError(
                "model provider streaming normalization failed: "
                f"{type(exc).__name__}: {str(exc)[:1024]}",
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                failure_kind="invalid_request",
                retryable=False,
                affects_replica_health=False,
            ) from exc

        usage=completion.usage
        try:
            (
                input_tokens,
                output_tokens,
                cached_input_tokens,
            ) = _usage_token_observation(usage)
        except ValueError as exc:
            raise ModelEndpointError(
                "model provider usage normalization failed: "
                + str(exc),
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                failure_kind="invalid_response",
                retryable=False,
                affects_replica_health=False,
            ) from exc
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text=completion.text,
            payload={
                "text":completion.text,
                "tool_calls":completion.tool_calls,
                "content_blocks":completion.content_blocks,
                "finish_reason":completion.finish_reason,
            },
            tool_calls=completion.tool_calls,
            content_blocks=completion.content_blocks,
            finish_reason=completion.finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            usage=usage if isinstance(usage,Mapping) else None,
        )



    def _operation_wire(
        self,
        request: ModelEndpointRequest,
    ) -> ModelProviderOperationPlan:
        envelope=request.request
        if not isinstance(envelope,ModelOperationEnvelope):
            raise TypeError("model operation wire requires ModelOperationEnvelope")
        body=request.body
        if not isinstance(body,Mapping):
            raise ModelEndpointRequestRejected(
                "model operation body materialization drift",
                request_body=canonical_bytes(request.body),
                status_code=400,
            )
        try:
            profile=self._profiles.resolve(
                logical_model_name=envelope.model.logical_name,
                provider_model_name=envelope.model.model_id,
                model_engine=envelope.model.engine,
            )
            return self._operation_protocols.plan(
                envelope,
                body,
                default_path=self.route.completion_path,
                provider_id=profile.provider_id,
                auth_kind=profile.auth_kind,
                api_key=self._api_key,
            )
        except ModelProviderRequestUnsupported as exc:
            raise ModelEndpointRequestRejected(
                f"model operation request unsupported: {exc}",
                request_body=canonical_bytes(request.body),
                status_code=400,
                failure_kind="invalid_request",
                retryable=False,
                affects_replica_health=False,
            ) from exc

    def _decode_operation_response(
        self,
        request: ModelEndpointRequest,
        response: JsonHttpResponse,
        *,
        plan: ModelProviderOperationPlan,
    ) -> ModelEndpointResponse:
        envelope=request.request
        if not isinstance(envelope,ModelOperationEnvelope):
            raise TypeError("model operation decode requires ModelOperationEnvelope")
        try:
            canonical=self._operation_protocols.decode(plan,response.body)
        except (ModelProviderRuntimeError,ValueError,TypeError) as exc:
            raise ModelEndpointError(
                "model operation response normalization failed: "
                f"{type(exc).__name__}: {str(exc)[:1024]}",
                request_body=response.request_body or plan.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                failure_kind="invalid_response",
                retryable=False,
                affects_replica_health=False,
                http_version=response.http_version,
                transport_digest=response.transport_digest,
            ) from exc
        payload=response.body
        usage=payload.get("usage") if isinstance(payload,Mapping) else None
        return ModelEndpointResponse(
            request_id=envelope.request_id,
            deployment_id=request.deployment_id,
            payload=canonical,
            usage=usage if isinstance(usage,Mapping) else None,
            stage_timings_ns=response.stage_timings_ns,
        )

    def _complete_operation(
        self,
        request: ModelEndpointRequest,
        started_monotonic_ns: int,
    ) -> ModelEndpointResponse:
        request_timeout_s = (
            self.route.timeout_s
            if request.timeout_s is None
            else float(request.timeout_s)
        )
        plan=self._operation_wire(request)
        lease = self._admit_physical_request(request, deadline=None)
        deadline = (
            None if request_timeout_s is None
            else Deadline.after(request_timeout_s)
        )

        async def post_operation(context):
            context.checkpoint()
            remaining=context.remaining_seconds
            timeout_s=(self.route.timeout_s if remaining is None else remaining)
            if timeout_s is not None and timeout_s <= 0:
                context.checkpoint()
                raise TimeoutError("model operation deadline expired before transport")
            return await self.transport.post_json(
                self.route.base_url.rstrip("/") + plan.path,
                plan.wire_bytes,
                timeout_s=timeout_s,
                headers=plan.headers,
            )
        gate = _PhysicalRetirementGate()
        try:
            handle=self._task_group.submit(
                ExecutionSpec(
                    task_id=self._next_task_id(request.request.request_id+":operation"),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                _transport_with_physical_retirement,
                gate,
                post_operation,
                deadline=deadline,
            )
        except BaseException:
            lease.release()
            raise
        try:
            response=self._await_and_retire(
                handle, lease, gate=gate, timeout_seconds=(
                    None if deadline is None else deadline.remaining_seconds
                ),
            )
        except (TimeoutError,TaskDeadlineExceeded) as exc:
            handle.cancel()
            raise ModelEndpointError(
                "model operation transport timed out",
                request_body=plan.wire_bytes,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
            ) from exc
        except (TaskCancelled,CancelledError) as exc:
            raise ModelEndpointError(
                "model operation transport cancelled at deadline",
                request_body=plan.wire_bytes,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
            ) from exc

        self._notify_exchange(request,response,started_monotonic_ns,time.perf_counter_ns())
        if not 200 <= response.status_code < 300:
            failure=classify_provider_failure(
                status_code=response.status_code,
                payload=response.body,
                response_headers=response.response_headers,
            )
            rejected=not failure.retryable and not failure.affects_replica_health
            error_type=ModelEndpointRequestRejected if rejected else ModelEndpointError
            raise error_type(
                f"model operation returned HTTP {response.status_code} [{failure.kind.value}]: "
                f"{failure.provider_message or provider_error_detail(response.body)}",
                request_body=response.request_body or plan.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                response_headers=response.response_headers,
                failure_kind=failure.kind.value,
                retryable=failure.retryable,
                retry_after_seconds=failure.retry_after_seconds,
                provider_code=failure.provider_code,
                affects_replica_health=failure.affects_replica_health,
                http_version=response.http_version,
                transport_digest=response.transport_digest,
            )
        return self._decode_operation_response(
            request,response,plan=plan
        )

    def _complete(
        self,
        request: ModelEndpointRequest,
        started_monotonic_ns: int,
    ) -> ModelEndpointResponse:
        if request.deployment_id != self.route.deployment_id:
            raise ModelEndpointError("endpoint request deployment does not match route")
        if request.deployment_generation != self.route.deployment_generation:
            raise ModelEndpointError("endpoint request deployment generation does not match route")
        if isinstance(request.request, ModelOperationEnvelope):
            return self._complete_operation(request, started_monotonic_ns)

        request_timeout_s = (
            self.route.timeout_s
            if request.timeout_s is None
            else float(request.timeout_s)
        )
        timings_ns: dict[str, int] = {}
        before_plan_ns = time.perf_counter_ns()
        try:
            plan,wire=self._plan(request)
        except ModelEndpointError as exc:
            timings_ns["request_encode"] = max(0, time.perf_counter_ns() - before_plan_ns)
            exc.stage_timings_ns = tuple(sorted(timings_ns.items()))
            raise
        timings_ns["request_encode"] = max(0, time.perf_counter_ns() - before_plan_ns)
        before_admit_ns = time.perf_counter_ns()
        try:
            lease = self._admit_physical_request(request, deadline=None)
        except ModelEndpointError as exc:
            timings_ns["authority_admission"] = max(0, time.perf_counter_ns() - before_admit_ns)
            exc.stage_timings_ns = tuple(sorted(timings_ns.items()))
            raise
        timings_ns["authority_admission"] = max(0, time.perf_counter_ns() - before_admit_ns)
        deadline = (
            None if request_timeout_s is None
            else Deadline.after(request_timeout_s)
        )
        submitted_ns = time.perf_counter_ns()
        gate = _PhysicalRetirementGate()
        try:
            handle=self._task_group.submit(
                ExecutionSpec(
                    task_id=self._next_task_id(request.request.request_id),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                _transport_with_physical_retirement,
                gate,
                self._post,
                wire,
                timings_ns,
                submitted_ns,
                deadline=deadline,
            )
        except BaseException:
            lease.release()
            raise

        try:
            response=self._await_and_retire(
                handle, lease, gate=gate, timeout_seconds=(
                    None if deadline is None else deadline.remaining_seconds
                ), timings_ns=timings_ns,
            )
        except ModelEndpointError as exc:
            timings_ns["submit_and_completion_wait"] = max(0, time.perf_counter_ns() - submitted_ns)
            exc.stage_timings_ns = tuple(sorted(timings_ns.items()))
            raise
        except (TimeoutError,TaskDeadlineExceeded) as exc:
            handle.cancel()
            timings_ns["submit_and_completion_wait"] = max(0, time.perf_counter_ns() - submitted_ns)
            raise ModelEndpointError(
                "model endpoint HTTP transport failed: TimeoutError; "
                f"request_id={request.request.request_id}; "
                f"deployment_id={request.deployment_id}; "
                f"timeout_s={request_timeout_s!r}",
                request_body=wire.wire_bytes,
                stage_timings_ns=tuple(sorted(timings_ns.items())),
            ) from exc
        except (TaskCancelled,CancelledError) as exc:
            timings_ns["submit_and_completion_wait"] = max(0, time.perf_counter_ns() - submitted_ns)
            raise ModelEndpointError(
                "model endpoint HTTP transport cancelled at deadline",
                request_body=wire.wire_bytes,
                stage_timings_ns=tuple(sorted(timings_ns.items())),
            ) from exc

        timings_ns["submit_and_completion_wait"] = max(
            0, time.perf_counter_ns() - submitted_ns
        )
        response = replace(
            response,
            stage_timings_ns=tuple(sorted({
                **dict(response.stage_timings_ns), **timings_ns,
            }.items())),
        )
        capture_started_ns = time.perf_counter_ns()
        try:
            self._notify_exchange(
                request,response,started_monotonic_ns,time.perf_counter_ns()
            )
        finally:
            # Two distinct raw-lake families are presently committed
            # synchronously before method continuation. This elapsed stage
            # isolates their real durability cost from Qwen HTTP and the
            # GPU time; it is not assumed to be CPU or model inference.
            timings_ns["raw_exchange_capture"] = max(
                0, time.perf_counter_ns() - capture_started_ns,
            )
        if not 200 <= response.status_code < 300:
            failure = classify_provider_failure(
                status_code=response.status_code,
                payload=response.body,
                response_headers=response.response_headers,
            )
            rejected = not failure.retryable and not failure.affects_replica_health
            error_type = ModelEndpointRequestRejected if rejected else ModelEndpointError
            detail = failure.provider_message or provider_error_detail(response.body)
            raise error_type(
                f"model endpoint returned HTTP {response.status_code} "
                f"[{failure.kind.value}]: {detail}",
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                response_headers=response.response_headers,
                failure_kind=failure.kind.value,
                retryable=failure.retryable,
                retry_after_seconds=failure.retry_after_seconds,
                provider_code=failure.provider_code,
                affects_replica_health=failure.affects_replica_health,
                http_version=response.http_version,
                transport_digest=response.transport_digest,
            )

        normalization_started_ns = time.perf_counter_ns()
        try:
            completion=self._protocols.decode(
                plan,response.body,raw_body=response.raw_body
            )
            if plan.profile.provider_id == "vllm":
                # Never accept faster grammar output unless the complete
                # declared schema, including all physical bounds, validates.
                validate_original_structured_response(completion.text, request.body)
        except (ModelProviderRuntimeError,ValueError,TypeError) as exc:
            raise ModelEndpointError(
                f"model provider response normalization failed: "
                f"{type(exc).__name__}: {str(exc)[:1024]}",
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                http_version=response.http_version,
                transport_digest=response.transport_digest,
                failure_kind="invalid_response",
                retryable=False,
                affects_replica_health=False,
            ) from exc

        usage=completion.usage
        try:
            (
                input_tokens,
                output_tokens,
                cached_input_tokens,
            ) = _usage_token_observation(usage)
        except ValueError as exc:
            raise ModelEndpointError(
                "model provider usage normalization failed: "
                + str(exc),
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                failure_kind="invalid_response",
                retryable=False,
                affects_replica_health=False,
            ) from exc
        timings_ns["provider_response_normalization"] = max(
            0, time.perf_counter_ns() - normalization_started_ns,
        )
        return ModelEndpointResponse(
            request_id=request.request.request_id,
            deployment_id=request.deployment_id,
            text=completion.text,
            payload={
                "text":completion.text,
                "tool_calls":completion.tool_calls,
                "content_blocks":completion.content_blocks,
                "finish_reason":completion.finish_reason,
            },
            tool_calls=completion.tool_calls,
            content_blocks=completion.content_blocks,
            finish_reason=completion.finish_reason,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            cached_input_tokens=cached_input_tokens,
            usage=usage if isinstance(usage,Mapping) else None,
            stage_timings_ns=tuple(sorted({
                **dict(response.stage_timings_ns), **timings_ns,
            }.items())),
        )


__all__=["NativeModelProviderEndpoint"]
