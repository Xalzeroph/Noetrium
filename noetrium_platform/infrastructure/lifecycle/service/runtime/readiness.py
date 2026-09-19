from __future__ import annotations

import asyncio
import hashlib
import math
import ssl
from threading import Lock
from urllib.parse import urlsplit

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
    TaskGroupPort,
)
from noetrium_platform.infrastructure.lifecycle.service.api import ServiceLaunchContract, ServiceProcessIdentity

from .process_contracts import ExactProcessBackend


class ProcessAliveReadinessProbe:
    """Generic service liveness readiness owned by the ASYNC_IO timer lane."""

    def __init__(self, task_group: TaskGroupPort, *, poll_interval_s: float = 0.05) -> None:
        if not math.isfinite(float(poll_interval_s)) or poll_interval_s <= 0:
            raise ValueError("poll interval must be finite and positive")
        self._task_group = task_group
        self.poll_interval_s = float(poll_interval_s)
        self._sequence_lock = Lock()
        self._sequence = 0

    async def _wait_ready_async(
        self,
        context,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        backend: ExactProcessBackend,
    ) -> str:
        while True:
            context.checkpoint()
            if backend.alive(process):
                payload = f"{contract.digest()}:{process.pid}:{process.start_identity}:alive"
                return "process-alive:" + hashlib.sha256(payload.encode()).hexdigest()
            remaining = context.remaining_seconds
            delay = self.poll_interval_s if remaining is None else min(self.poll_interval_s, remaining)
            if delay <= 0:
                context.checkpoint()
            await asyncio.sleep(delay)

    def wait_ready(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        backend: ExactProcessBackend,
    ) -> str:
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        deadline = Deadline.after(contract.readiness_timeout_s)
        handle = self._task_group.submit(
            ExecutionSpec(
                task_id=f"service-process-readiness:{contract.service_id}:{sequence}",
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            self._wait_ready_async,
            process,
            contract,
            backend,
            deadline=deadline,
        )
        try:
            return handle.result(timeout=max(0.001, deadline.remaining_seconds))
        except TimeoutError as exc:
            handle.cancel()
            raise TimeoutError(
                f"service {contract.service_id} did not remain alive before readiness timeout"
            ) from exc


class HttpEndpointReadinessProbe:
    """Operational HTTP readiness using the process-wide ASYNC_IO network lane."""

    def __init__(
        self,
        task_group: TaskGroupPort,
        url: str,
        *,
        poll_interval_s: float = 0.25,
        request_timeout_s: float = 2.0,
    ) -> None:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            raise ValueError("readiness URL must use http or https")
        if parsed.username is not None or parsed.password is not None:
            raise ValueError("readiness URL must not embed credentials")
        if (
            not math.isfinite(float(poll_interval_s))
            or not math.isfinite(float(request_timeout_s))
            or poll_interval_s <= 0
            or request_timeout_s <= 0
        ):
            raise ValueError("readiness polling values must be finite and positive")
        self._task_group = task_group
        self.url = url
        self.poll_interval_s = float(poll_interval_s)
        self.request_timeout_s = float(request_timeout_s)
        self._parsed = parsed
        self._sequence_lock = Lock()
        self._sequence = 0

    async def _status(self) -> int:
        parsed = self._parsed
        host = parsed.hostname
        assert host is not None
        secure = parsed.scheme == "https"
        port = parsed.port or (443 if secure else 80)
        ssl_context = ssl.create_default_context() if secure else None
        path = parsed.path or "/"
        if parsed.query:
            path += "?" + parsed.query
        host_header = host
        default_port = 443 if secure else 80
        if port != default_port:
            host_header = f"{host}:{port}"
        writer = None
        try:
            async with asyncio.timeout(self.request_timeout_s):
                reader, writer = await asyncio.open_connection(
                    host,
                    port,
                    ssl=ssl_context,
                    server_hostname=host if secure else None,
                )
                request = (
                    f"GET {path} HTTP/1.1\r\n"
                    f"Host: {host_header}\r\n"
                    "Connection: close\r\n"
                    "User-Agent: noetrium-readiness/1\r\n\r\n"
                ).encode("ascii", errors="strict")
                writer.write(request)
                await writer.drain()
                status_line = await reader.readline()
            try:
                text = status_line.decode("ascii", errors="strict").strip()
                protocol, status, _reason = text.split(" ", 2)
                if not protocol.startswith("HTTP/"):
                    raise ValueError("invalid HTTP status line")
                return int(status)
            except (UnicodeDecodeError, ValueError) as exc:
                raise OSError("readiness endpoint returned an invalid HTTP status line") from exc
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except OSError:
                    pass

    async def _wait_ready_async(
        self,
        context,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        backend: ExactProcessBackend,
    ) -> str:
        last_error = "not-ready"
        while True:
            context.checkpoint()
            if not backend.alive(process):
                raise RuntimeError(f"service {contract.service_id} exited before HTTP readiness")
            try:
                status = await self._status()
                if 200 <= status < 400:
                    payload = f"{contract.digest()}:{process.pid}:{self.url}:{status}"
                    return "http-ready:" + hashlib.sha256(payload.encode()).hexdigest()
                last_error = f"http-{status}"
            except (OSError, TimeoutError, ssl.SSLError) as exc:
                last_error = type(exc).__name__
            remaining = context.remaining_seconds
            delay = self.poll_interval_s if remaining is None else min(self.poll_interval_s, remaining)
            if delay <= 0:
                context.checkpoint()
            await asyncio.sleep(delay)

    def wait_ready(
        self,
        process: ServiceProcessIdentity,
        contract: ServiceLaunchContract,
        backend: ExactProcessBackend,
    ) -> str:
        with self._sequence_lock:
            self._sequence += 1
            sequence = self._sequence
        deadline = Deadline.after(contract.readiness_timeout_s)
        handle = self._task_group.submit(
            ExecutionSpec(
                task_id=f"service-http-readiness:{contract.service_id}:{sequence}",
                lane_kind=ExecutionLaneKind.ASYNC_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            self._wait_ready_async,
            process,
            contract,
            backend,
            deadline=deadline,
        )
        try:
            return handle.result(timeout=max(0.001, deadline.remaining_seconds))
        except TimeoutError as exc:
            handle.cancel()
            raise TimeoutError(
                f"service {contract.service_id} readiness timed out"
            ) from exc


__all__ = ["HttpEndpointReadinessProbe", "ProcessAliveReadinessProbe"]
