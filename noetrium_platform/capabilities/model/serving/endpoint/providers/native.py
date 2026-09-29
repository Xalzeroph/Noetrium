from __future__ import annotations

import json
import math
import time
from collections.abc import Callable, Mapping
from concurrent.futures import CancelledError
from threading import Lock

from noetrium_platform.capabilities.model.serving.api.admission import (
    ModelAdmissionClosed,
    ModelAdmissionLeasePort,
    ModelAdmissionPort,
    ModelAdmissionTimeout,
)
from noetrium_platform.capabilities.model.request.api import ModelOperationEnvelope
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
        return f"model-http:{request_id}:{sequence}"

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

    async def _post(
        self,
        context,
        request: ModelEndpointRequest,
        lease: ModelAdmissionLeasePort,
        wire,
    ) -> JsonHttpResponse:
        try:
            context.checkpoint()
            remaining=context.remaining_seconds
            timeout_s=self.route.timeout_s if remaining is None else min(self.route.timeout_s,remaining)
            if timeout_s <= 0:
                context.checkpoint()
                raise TimeoutError("model endpoint deadline expired before transport")
            response=await self.transport.post_json(
                self.route.completion_url,
                wire.wire_bytes,
                timeout_s=timeout_s,
                headers=wire.headers,
            )
            context.checkpoint()
            return response
        finally:
            lease.release()

    async def _post_stream(
        self,
        context,
        request: ModelEndpointRequest,
        lease: ModelAdmissionLeasePort,
        wire,
        decoder,
        accumulator: ModelStreamAccumulator,
        on_event: Callable[[ModelStreamEvent], None],
        idle_timeout_s: float,
    ) -> SseHttpResponse:
        try:
            context.checkpoint()
            remaining=context.remaining_seconds
            timeout_s=self.route.timeout_s if remaining is None else min(
                self.route.timeout_s,remaining
            )
            if timeout_s <= 0:
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
                idle_timeout_s=min(float(idle_timeout_s),timeout_s),
                on_event=on_raw,
                headers=wire.headers,
            )
            context.checkpoint()
            return response
        finally:
            lease.release()

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
        deadline=Deadline.after(max(1.0,min(self.route.timeout_s,30.0)))
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
            handle.result(timeout=max(0.001,deadline.remaining_seconds))
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
        stream_idle_timeout_s: float = 30.0,
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
        if (
            isinstance(stream_idle_timeout_s,bool)
            or not isinstance(stream_idle_timeout_s,(int,float))
            or not math.isfinite(float(stream_idle_timeout_s))
            or float(stream_idle_timeout_s) <= 0
        ):
            raise ValueError(
                "model stream idle timeout must be finite and positive"
            )
        started=time.perf_counter_ns()
        try:
            return self._stream(
                request,
                on_event,
                stream_idle_timeout_s=float(stream_idle_timeout_s),
                started_monotonic_ns=started,
            )
        except ModelEndpointError as exc:
            self._notify_failure(
                request,exc,started,time.perf_counter_ns()
            )
            raise

    def _stream(
        self,
        request: ModelEndpointRequest,
        on_event: Callable[[ModelStreamEvent], None],
        *,
        stream_idle_timeout_s: float,
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

        plan,wire=self._plan_stream(request)
        decoder=stream_decoder_for_protocol(
            plan.profile.protocol_id,
            provider_id=plan.profile.provider_id,
        )
        accumulator=ModelStreamAccumulator(plan)
        deadline=Deadline.after(self.route.timeout_s)
        try:
            owner_id=(
                request.request.context.study_id
                or request.request.context.run_id
            )
            lease=self._admission.acquire(
                timeout_seconds=max(0.0,deadline.remaining_seconds),
                owner_id=owner_id,
            )
        except ModelAdmissionTimeout as exc:
            raise ModelEndpointError(
                "model endpoint streaming admission timed out; "
                f"request_id={request.request.request_id}; "
                f"timeout_s={self.route.timeout_s:.3f}",
                failure_kind="capacity",
                retryable=True,
                affects_replica_health=False,
            ) from exc
        except ModelAdmissionClosed as exc:
            raise ModelEndpointError(
                "model endpoint streaming admission is closed",
                failure_kind="capacity",
                retryable=True,
                affects_replica_health=False,
            ) from exc

        try:
            handle=self._task_group.submit(
                ExecutionSpec(
                    task_id=self._next_task_id(
                        request.request.request_id + ":stream"
                    ),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                self._post_stream,
                request,
                lease,
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
            response=handle.result(
                timeout=max(0.001,deadline.remaining_seconds)
            )
        except (TimeoutError,TaskDeadlineExceeded) as exc:
            handle.cancel()
            raise ModelEndpointError(
                "model endpoint streaming transport timed out; "
                f"request_id={request.request.request_id}; "
                f"deployment_id={request.deployment_id}; "
                f"timeout_s={self.route.timeout_s:.3f}",
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
        input_tokens=(
            usage.get("prompt_tokens")
            if isinstance(usage,Mapping)
            else None
        )
        output_tokens=(
            usage.get("completion_tokens")
            if isinstance(usage,Mapping)
            else None
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
        )

    def _complete_operation(
        self,
        request: ModelEndpointRequest,
        started_monotonic_ns: int,
    ) -> ModelEndpointResponse:
        plan=self._operation_wire(request)
        deadline=Deadline.after(self.route.timeout_s)
        try:
            owner_id=request.request.context.study_id or request.request.context.run_id
            lease=self._admission.acquire(
                timeout_seconds=max(0.0,deadline.remaining_seconds),
                owner_id=owner_id,
            )
        except ModelAdmissionTimeout as exc:
            raise ModelEndpointError(
                "model operation admission timed out",
                failure_kind="capacity",
                retryable=True,
                affects_replica_health=False,
            ) from exc
        except ModelAdmissionClosed as exc:
            raise ModelEndpointError(
                "model operation admission is closed",
                failure_kind="capacity",
                retryable=True,
                affects_replica_health=False,
            ) from exc

        async def post_operation(context, lease):
            try:
                context.checkpoint()
                remaining=context.remaining_seconds
                timeout_s=self.route.timeout_s if remaining is None else min(self.route.timeout_s,remaining)
                if timeout_s <= 0:
                    context.checkpoint()
                    raise TimeoutError("model operation deadline expired before transport")
                return await self.transport.post_json(
                    self.route.base_url.rstrip("/") + plan.path,
                    plan.wire_bytes,
                    timeout_s=timeout_s,
                    headers=plan.headers,
                )
            finally:
                lease.release()

        try:
            handle=self._task_group.submit(
                ExecutionSpec(
                    task_id=self._next_task_id(request.request.request_id+":operation"),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                post_operation,
                lease,
                deadline=deadline,
            )
        except BaseException:
            lease.release()
            raise
        try:
            response=handle.result(timeout=max(0.001,deadline.remaining_seconds))
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

        plan,wire=self._plan(request)
        deadline=Deadline.after(self.route.timeout_s)
        try:
            owner_id=request.request.context.study_id or request.request.context.run_id
            lease=self._admission.acquire(
                timeout_seconds=max(0.0,deadline.remaining_seconds),
                owner_id=owner_id,
            )
        except ModelAdmissionTimeout as exc:
            raise ModelEndpointError(
                "model endpoint admission timed out; "
                f"request_id={request.request.request_id}; "
                f"timeout_s={self.route.timeout_s:.3f}"
            ) from exc
        except ModelAdmissionClosed as exc:
            raise ModelEndpointError("model endpoint admission is closed") from exc

        try:
            handle=self._task_group.submit(
                ExecutionSpec(
                    task_id=self._next_task_id(request.request.request_id),
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                self._post,
                request,
                lease,
                wire,
                deadline=deadline,
            )
        except BaseException:
            lease.release()
            raise

        try:
            response=handle.result(timeout=max(0.001,deadline.remaining_seconds))
        except (TimeoutError,TaskDeadlineExceeded) as exc:
            handle.cancel()
            raise ModelEndpointError(
                "model endpoint HTTP transport failed: TimeoutError; "
                f"request_id={request.request.request_id}; "
                f"deployment_id={request.deployment_id}; "
                f"timeout_s={self.route.timeout_s:.3f}",
                request_body=wire.wire_bytes,
            ) from exc
        except (TaskCancelled,CancelledError) as exc:
            raise ModelEndpointError(
                "model endpoint HTTP transport cancelled at deadline",
                request_body=wire.wire_bytes,
            ) from exc

        self._notify_exchange(
            request,response,started_monotonic_ns,time.perf_counter_ns()
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

        try:
            completion=self._protocols.decode(
                plan,response.body,raw_body=response.raw_body
            )
        except (ModelProviderRuntimeError,ValueError,TypeError) as exc:
            raise ModelEndpointError(
                f"model provider response normalization failed: "
                f"{type(exc).__name__}: {str(exc)[:1024]}",
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
                status_code=response.status_code,
                http_version=response.http_version,
                transport_digest=response.transport_digest,
            ) from exc

        usage=completion.usage
        input_tokens=usage.get("prompt_tokens") if isinstance(usage,Mapping) else None
        output_tokens=usage.get("completion_tokens") if isinstance(usage,Mapping) else None
        if input_tokens is not None and type(input_tokens) is not int:
            raise ModelEndpointError(
                "model provider prompt_tokens must be an integer",
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
            )
        if output_tokens is not None and type(output_tokens) is not int:
            raise ModelEndpointError(
                "model provider completion_tokens must be an integer",
                request_body=response.request_body or wire.wire_bytes,
                response_body=response.raw_body,
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
            usage=usage if isinstance(usage,Mapping) else None,
        )


__all__=["NativeModelProviderEndpoint"]
