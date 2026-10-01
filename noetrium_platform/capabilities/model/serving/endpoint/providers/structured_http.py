from __future__ import annotations

from threading import Lock

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    AsyncJsonHttpTransportPort,
    JsonHttpResponse,
    ModelEndpointError,
    ModelJsonHttpClientPort,
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
        timeout_s: float,
        headers: tuple[tuple[str, str], ...] = (),
    ) -> JsonHttpResponse:
        task_id = self._next_task_id()
        deadline = Deadline.after(timeout_s)

        async def invoke(context):
            context.checkpoint()
            remaining = context.remaining_seconds
            resolved = timeout_s if remaining is None else min(timeout_s, remaining)
            if resolved <= 0:
                context.checkpoint()
                raise TimeoutError("model JSON HTTP deadline expired before transport")
            response = await self._transport.post_json(
                url,
                body,
                timeout_s=resolved,
                headers=headers,
            )
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
        try:
            return handle.result(timeout=max(0.001, deadline.remaining_seconds))
        except (TimeoutError, TaskDeadlineExceeded) as exc:
            handle.cancel()
            raise ModelEndpointError(
                "model JSON HTTP request timed out",
                request_body=body,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
            ) from exc
        except TaskCancelled as exc:
            raise ModelEndpointError(
                "model JSON HTTP request was cancelled",
                request_body=body,
                failure_kind="timeout",
                retryable=True,
                affects_replica_health=True,
            ) from exc

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
