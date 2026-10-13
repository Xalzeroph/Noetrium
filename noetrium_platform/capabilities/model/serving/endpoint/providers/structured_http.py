from __future__ import annotations

from threading import Lock
import time

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AsyncJsonHttpTransportPort,
    JsonHttpResponse,
    ModelEndpointError,
    ModelJsonHttpClientPort,
)
from noetrium_platform.capabilities.model.serving.endpoint.runtime.request_retry import ModelRequestRetryPolicy
from noetrium_platform.foundation.kernel.kernel import blocking_wait
from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskCancelled,
    TaskDeadlineExceeded,
    TaskFailureScope,
    TaskGroupPort,
)


class StructuredModelJsonHttpClient(ModelJsonHttpClientPort):
    """Synchronous Model HTTP seam over the shared async HTTP/2 transport.

    The client owns only its structured-concurrency task group. The underlying
    transport is borrowed so generation, tokenization and typed operations can
    share one connection pool and event-loop authority.
    """

    def __init__(
        self,
        transport: AsyncJsonHttpTransportPort,
        task_group: TaskGroupPort,
        retry_policy: ModelRequestRetryPolicy | None = None,
    ) -> None:
        if not isinstance(transport, AsyncJsonHttpTransportPort):
            raise TypeError("structured model HTTP client requires async transport")
        if (
            not callable(getattr(task_group, "submit", None))
            or not callable(getattr(task_group, "close", None))
        ):
            raise TypeError("structured model HTTP client requires TaskGroupPort")
        self._transport = transport
        self._task_group = task_group
        self._retry_policy = (
            ModelRequestRetryPolicy()
            if retry_policy is None
            else retry_policy
        )
        if not isinstance(self._retry_policy, ModelRequestRetryPolicy):
            raise TypeError(
                "structured model HTTP retry_policy must be ModelRequestRetryPolicy"
            )
        self._lock = Lock()
        self._sequence = 0
        self._closed = False

    def _next_task_id(self) -> str:
        with self._lock:
            if self._closed:
                raise ModelEndpointError(
                    "structured model HTTP client is closed",
                    failure_kind="internal",
                    retryable=False,
                    affects_replica_health=False,
                )
            self._sequence += 1
            return f"model-json-http:{self._sequence}"

    def post_json(
        self,
        url: str,
        body: bytes,
        *,
        timeout_s: float | None,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> JsonHttpResponse:
        deadline = None if timeout_s is None else Deadline.after(timeout_s)
        policy = self._retry_policy
        last_error: ModelEndpointError | None = None

        for attempt_number in range(1, policy.max_attempts + 1):
            task_id = self._next_task_id()
            submit_started = time.monotonic()
            invoke_started: float | None = None
            transport_completed: float | None = None

            async def invoke(context):
                nonlocal invoke_started, transport_completed
                context.checkpoint()
                invoke_started = time.monotonic()
                remaining = context.remaining_seconds
                resolved = (
                    timeout_s
                    if remaining is None
                    else (
                        remaining
                        if timeout_s is None
                        else min(timeout_s, remaining)
                    )
                )
                if resolved is not None and resolved <= 0:
                    context.checkpoint()
                    raise TimeoutError("model JSON HTTP deadline expired before transport")
                response = await self._transport.post_json(
                    url,
                    body,
                    timeout_s=resolved,
                    headers=headers,
                )
                transport_completed = time.monotonic()
                context.checkpoint()
                return response

            handle = self._task_group.submit(
                ExecutionSpec(
                    task_id=task_id,
                    lane_kind=ExecutionLaneKind.ASYNC_IO,
                    failure_scope=TaskFailureScope.CALLER,
                ),
                invoke,
                deadline=deadline,
            )
            submitted_at = time.monotonic()
            try:
                return handle.result(
                    timeout=(
                        None
                        if deadline is None
                        else max(0.001, deadline.remaining_seconds)
                    )
                )
            except (TimeoutError, TaskDeadlineExceeded) as exc:
                failed_at = time.monotonic()
                handle.cancel()
                invoke_delay = (
                    None
                    if invoke_started is None
                    else max(0.0, invoke_started - submitted_at)
                )
                transport_elapsed = (
                    None
                    if invoke_started is None
                    else max(
                        0.0,
                        (transport_completed or failed_at) - invoke_started,
                    )
                )
                error = ModelEndpointError(
                    "model JSON HTTP request timed out; "
                    f"submit_s={max(0.0, submitted_at - submit_started):.6f}; "
                    f"invoke_delay_s={invoke_delay}; "
                    f"transport_s={transport_elapsed}",
                    request_body=body,
                    failure_kind="timeout",
                    retryable=True,
                    affects_replica_health=True,
                )
                error.__cause__ = exc
            except TaskCancelled as exc:
                error = ModelEndpointError(
                    "model JSON HTTP request was cancelled",
                    request_body=body,
                    failure_kind="timeout",
                    retryable=True,
                    affects_replica_health=True,
                )
                error.__cause__ = exc
            except ModelEndpointError as exc:
                error = exc

            last_error = error
            if (
                not error.retryable
                or error.failure_kind not in policy.retryable_failure_kinds
                or attempt_number >= policy.max_attempts
            ):
                raise error

            delay = policy.wait_seconds(
                attempt_number=attempt_number,
                retry_after_seconds=error.retry_after_seconds,
            )
            if deadline is not None:
                remaining = deadline.remaining_seconds
                if remaining <= 0 or delay >= remaining:
                    raise error
            if delay > 0:
                blocking_wait(delay)

        if last_error is None:
            raise RuntimeError("structured model HTTP retry loop produced no result")
        raise last_error

    def close(self) -> None:
        with self._lock:
            if self._closed:
                return
            self._closed = True
        self._task_group.close(
            cancel_pending=True,
            deadline=Deadline.after(30.0),
        )


__all__ = ["StructuredModelJsonHttpClient"]
