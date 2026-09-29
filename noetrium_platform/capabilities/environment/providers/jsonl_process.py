from __future__ import annotations

from collections import deque
from collections.abc import AsyncIterator
from dataclasses import dataclass
import asyncio
import codecs
import json
import os
import queue
import subprocess
import threading
from typing import Callable, Mapping, Protocol, TextIO, cast
from uuid import uuid4

from noetrium_platform.foundation.kernel.concurrency.api import (
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskContextPort,
    TaskFailureScope,
    TaskGroupPort,
    TaskHandlePort,
)
from noetrium_platform.foundation.kernel.kernel import JsonValue
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.substrate.api import OperatingSystemRoute
from noetrium_platform.substrate.api import ProcessSupervisorPort



_STDOUT_EOF = object()


def safe_exception_message(exc: BaseException) -> str:
    descriptor = describe_exception(exc)
    return f"{descriptor.error_type}[{descriptor.error_digest[:16]}]"


class JsonlProcessError(RuntimeError):
    """Transport/protocol failure with a stable phase and cause code."""

    error_prefix = "JSONL process"

    def __init__(self, phase: str, cause_code: str, message: str) -> None:
        super().__init__(f"{self.error_prefix} {phase} failed [{cause_code}]: {message}")
        self.phase = phase
        self.cause_code = cause_code


@dataclass(frozen=True, slots=True)
class JsonlProcessSpec:
    command: tuple[str, ...]
    cwd: str
    stdout_queue_capacity: int = 4096

    def __post_init__(self) -> None:
        if not self.command or any(type(item) is not str or not item.strip() for item in self.command):
            raise ValueError("JSONL process command must be non-empty")
        if type(self.cwd) is not str or not self.cwd.strip():
            raise ValueError("JSONL process cwd must be non-empty")
        if type(self.stdout_queue_capacity) is not int or self.stdout_queue_capacity <= 0:
            raise ValueError("JSONL process stdout_queue_capacity must be positive")


class JsonlProcess(Protocol):
    stdin: TextIO | None
    stdout: TextIO | None
    stderr: TextIO | None
    pid: int

    def poll(self) -> int | None: ...
    def wait(self, timeout: float | None = None) -> int: ...
    def terminate(self) -> None: ...
    def kill(self) -> None: ...


class ProcessFactory(Protocol):
    def __call__(
        self,
        command: list[str],
        **process_options: object,
    ) -> JsonlProcess: ...


class FailureReporter(Protocol):
    def __call__(
        self,
        *,
        phase: str,
        code: str,
        message: str,
        exception: BaseException | None = None,
        attributes: Mapping[str, JsonValue] | None = None,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class JsonlProcessMessage:
    kind: str
    value: Mapping[str, JsonValue]


class JsonlProcessTransport:
    """Provider-neutral supervised subprocess transport with JSONL framing."""

    def __init__(
        self,
        *,
        spec: JsonlProcessSpec,
        operating_system: OperatingSystemRoute,
        task_group: TaskGroupPort,
        transport_identity: str,
        process_factory: ProcessFactory | None = None,
        process_supervisor: ProcessSupervisorPort,
        failure_reporter: FailureReporter | None = None,
        stderr_tail_lines: int = 300,
        environment_overrides: Mapping[str, str] | None = None,
        task_namespace: str = "environment-jsonl",
        error_type: type[JsonlProcessError] = JsonlProcessError,
    ) -> None:
        if not isinstance(spec, JsonlProcessSpec):
            raise TypeError("JSONL process transport requires JsonlProcessSpec")
        if type(transport_identity) is not str or not transport_identity.strip():
            raise ValueError("JSONL process transport_identity must be non-empty")
        if type(task_namespace) is not str or not task_namespace.strip():
            raise ValueError("JSONL process task_namespace must be non-empty")
        if not issubclass(error_type, JsonlProcessError):
            raise TypeError("JSONL process error_type must derive from JsonlProcessError")
        self.spec = spec
        self._operating_system = operating_system
        self._task_group = task_group
        self._transport_identity = transport_identity
        self._task_namespace = task_namespace
        self._error_type = error_type
        self._environment_overrides = dict(environment_overrides or {})
        if any(
            type(key) is not str or not key or type(value) is not str
            for key, value in self._environment_overrides.items()
        ):
            raise ValueError("JSONL process environment overrides must be text pairs")
        self._process_factory = process_factory
        self._failure_reporter = failure_reporter
        self._stderr_tail: deque[str] = deque(maxlen=max(20, stderr_tail_lines))
        self._stdout_queue: queue.Queue[str | object] = queue.Queue(
            maxsize=self.spec.stdout_queue_capacity
        )
        self._stdout_stop = threading.Event()
        self._process: JsonlProcess | None = None
        self._stdout_task: TaskHandlePort[None] | None = None
        self._stderr_task: TaskHandlePort[None] | None = None
        self._process_supervisor = process_supervisor

    @property
    def started(self) -> bool:
        return self._process is not None

    @property
    def process_id(self) -> int | None:
        return self._process.pid if self._process is not None else None

    @property
    def stderr_tail(self) -> tuple[str, ...]:
        return tuple(self._stderr_tail)

    def stderr_tail_text(self) -> str:
        return " | ".join(self.stderr_tail[-20:])[-6000:]

    def _failure(
        self,
        *,
        phase: str,
        code: str,
        message: str,
        exception: BaseException | None = None,
        attributes: Mapping[str, JsonValue] | None = None,
    ) -> None:
        if self._failure_reporter is None:
            return
        self._failure_reporter(
            phase=phase,
            code=code,
            message=message,
            exception=exception,
            attributes=attributes,
        )

    async def _put_stdout_async(
        self,
        context: TaskContextPort,
        item: str | object,
    ) -> bool:
        while not self._stdout_stop.is_set():
            context.checkpoint()
            try:
                self._stdout_queue.put_nowait(item)
                return True
            except queue.Full:
                await asyncio.sleep(0.01)
        return False

    async def _stream_lines(
        self,
        context: TaskContextPort,
        stream: TextIO,
    ) -> AsyncIterator[str]:
        """Drain one text pipe without occupying a BLOCKING_IO worker.

        Real subprocess pipes are switched to non-blocking descriptor reads and
        cooperatively multiplexed by the platform ASYNC_IO loop. In-memory test
        streams have no file descriptor and are already non-blocking.
        """
        try:
            fd = stream.fileno()
        except (AttributeError, OSError, ValueError):
            while not self._stdout_stop.is_set():
                context.checkpoint()
                line = stream.readline()
                if line == "":
                    return
                yield line
                await asyncio.sleep(0)
            return

        was_blocking = os.get_blocking(fd)
        if was_blocking:
            os.set_blocking(fd, False)
        encoding = getattr(stream, "encoding", None) or "utf-8"
        decoder = codecs.getincrementaldecoder(encoding)(errors="replace")
        pending = ""
        try:
            while not self._stdout_stop.is_set():
                context.checkpoint()
                try:
                    chunk = os.read(fd, 65536)
                except BlockingIOError:
                    await asyncio.sleep(0.01)
                    continue
                except (OSError, ValueError):
                    if self._stdout_stop.is_set():
                        return
                    raise
                if not chunk:
                    pending += decoder.decode(b"", final=True)
                    if pending:
                        yield pending
                    return
                pending += decoder.decode(chunk)
                while True:
                    end = pending.find("\n")
                    if end < 0:
                        break
                    end += 1
                    line, pending = pending[:end], pending[end:]
                    yield line
                await asyncio.sleep(0)
        finally:
            if was_blocking and not getattr(stream, "closed", False):
                try:
                    os.set_blocking(fd, True)
                except (OSError, ValueError):
                    pass

    async def _drain_stdout_task(self, context: TaskContextPort) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            async for line in self._stream_lines(context, process.stdout):
                if not await self._put_stdout_async(context, line):
                    return
        finally:
            try:
                self._stdout_queue.put_nowait(_STDOUT_EOF)
            except queue.Full:
                pass

    async def _drain_stderr_task(self, context: TaskContextPort) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        async for line in self._stream_lines(context, process.stderr):
            self._stderr_tail.append(line.rstrip("\r\n"))

    @staticmethod
    def _has_file_descriptor(stream: TextIO | None) -> bool:
        if stream is None:
            return False
        try:
            stream.fileno()
        except (AttributeError, OSError, ValueError):
            return False
        return True

    def _put_stdout_blocking(self, context: TaskContextPort, item: str | object) -> bool:
        while not self._stdout_stop.is_set():
            context.checkpoint()
            try:
                self._stdout_queue.put_nowait(item)
                return True
            except queue.Full:
                context.wait(0.01)
        return False

    def _drain_stdout_blocking_task(self, context: TaskContextPort) -> None:
        process = self._process
        if process is None or process.stdout is None:
            return
        try:
            while not self._stdout_stop.is_set():
                context.checkpoint()
                line = process.stdout.readline()
                if line == "":
                    return
                if not self._put_stdout_blocking(context, line):
                    return
        finally:
            try:
                self._stdout_queue.put_nowait(_STDOUT_EOF)
            except queue.Full:
                pass

    def _drain_stderr_blocking_task(self, context: TaskContextPort) -> None:
        process = self._process
        if process is None or process.stderr is None:
            return
        while not self._stdout_stop.is_set():
            context.checkpoint()
            line = process.stderr.readline()
            if line == "":
                return
            self._stderr_tail.append(line.rstrip("\r\n"))

    def start(self) -> None:
        if self._process is not None:
            raise self._error_type(
                "start", "BRIDGE_ALREADY_STARTED", "bridge transport already started"
            )
        self._stdout_stop.clear()
        self._stdout_queue = queue.Queue(maxsize=self.spec.stdout_queue_capacity)
        process_options: dict[str, object] = {
            "cwd": self.spec.cwd,
            "stdin": subprocess.PIPE,
            "stdout": subprocess.PIPE,
            "stderr": subprocess.PIPE,
            "text": True,
            "bufsize": 1,
            "start_new_session": self._operating_system.is_posix,
        }
        if self._operating_system.is_windows:
            process_options["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP
        process_environment = os.environ.copy()
        process_environment.update(self._environment_overrides)
        process_options["env"] = process_environment
        try:
            if self._process_factory is None:
                self._process = cast(
                    JsonlProcess,
                    self._process_supervisor.spawn_interactive(
                        self.spec.command,
                        cwd=self.spec.cwd,
                        environment=process_environment,
                        start_new_session=self._operating_system.is_posix,
                        creationflags=(
                            subprocess.CREATE_NEW_PROCESS_GROUP
                            if self._operating_system.is_windows
                            else 0
                        ),
                    ),
                )
            else:
                self._process = self._process_factory(
                    list(self.spec.command), **process_options
                )
            # OS subprocess pipes expose file descriptors and are cooperatively
            # drained on the shared ASYNC_IO loop. File-like process factories may
            # expose genuinely blocking streams without fileno(); those must never
            # block the event loop, so they use the bounded BLOCKING_IO provider.
            fd_backed = self._has_file_descriptor(self._process.stdout) and self._has_file_descriptor(
                self._process.stderr
            )
            lane_kind = ExecutionLaneKind.ASYNC_IO if fd_backed else ExecutionLaneKind.BLOCKING_IO
            stdout_drain = self._drain_stdout_task if fd_backed else self._drain_stdout_blocking_task
            stderr_drain = self._drain_stderr_task if fd_backed else self._drain_stderr_blocking_task
            self._stdout_task, self._stderr_task = self._task_group.submit_atomic_batch(
                (
                    (
                        ExecutionSpec(
                            task_id=f"{self._task_namespace}:{self._transport_identity}:stdout:{uuid4().hex}",
                            lane_kind=lane_kind,
                            failure_scope=TaskFailureScope.CALLER,
                        ),
                        stdout_drain,
                    ),
                    (
                        ExecutionSpec(
                            task_id=f"{self._task_namespace}:{self._transport_identity}:stderr:{uuid4().hex}",
                            lane_kind=lane_kind,
                            failure_scope=TaskFailureScope.CALLER,
                        ),
                        stderr_drain,
                    ),
                )
            )
        except BaseException as primary:
            # A physical child may already exist even though transport startup
            # never reached the logical "ready" point. Converge that child here
            # instead of requiring every environment adapter to remember a
            # compensating close. If cleanup is transiently unproven, close()
            # retains the exact process/task handles so a later retry can finish.
            try:
                self.close()
            except BaseException as cleanup:
                raise BaseExceptionGroup(
                    f"{self._task_namespace} start failed with cleanup error",
                    [primary, cleanup],
                ) from primary
            raise

    def send(
        self,
        command: str,
        payload: Mapping[str, JsonValue],
        *,
        request_id: str,
    ) -> None:
        process = self._process
        if process is None or process.stdin is None:
            raise self._error_type(
                "transport", "BRIDGE_NOT_STARTED", "bridge process is not running"
            )
        message = {"cmd": command, "request_id": request_id, **dict(payload)}
        try:
            process.stdin.write(
                json.dumps(message, ensure_ascii=False, separators=(",", ":")) + "\n"
            )
            process.stdin.flush()
        except Exception as exc:
            detail = safe_exception_message(exc)
            self._failure(
                phase="send",
                code="BRIDGE_STDIN_WRITE_FAILED",
                message=detail,
                exception=exc,
            )
            raise self._error_type("send", "BRIDGE_STDIN_WRITE_FAILED", detail) from exc

    def read(self, *, timeout_s: float) -> JsonlProcessMessage:
        process = self._process
        if process is None:
            raise self._error_type(
                "read", "BRIDGE_NOT_STARTED", "bridge process is not running"
            )
        try:
            item = self._stdout_queue.get(timeout=timeout_s)
        except queue.Empty as exc:
            code = process.poll()
            if code is not None:
                self._failure(
                    phase="read",
                    code="BRIDGE_EXITED",
                    message=f"exit_code={code}",
                    attributes={"stderr_tail": self.stderr_tail_text()},
                )
                raise self._error_type(
                    "read",
                    "BRIDGE_EXITED",
                    f"exit_code={code}; stderr_tail={self.stderr_tail_text()}",
                ) from exc
            raise self._error_type(
                "read",
                "BRIDGE_READ_TIMEOUT",
                f"no complete JSONL message within {timeout_s:.3f}s",
            ) from exc
        if item is _STDOUT_EOF:
            self._failure(
                phase="read",
                code="BRIDGE_STDOUT_EOF",
                message=f"exit_code={process.poll()}",
                attributes={"stderr_tail": self.stderr_tail_text()},
            )
            raise self._error_type(
                "read",
                "BRIDGE_STDOUT_EOF",
                f"exit_code={process.poll()}; stderr_tail={self.stderr_tail_text()}",
            )
        line = str(item).strip()
        try:
            value = json.loads(line)
        except json.JSONDecodeError as exc:
            detail = f"invalid-json[{safe_exception_message(exc)}]"
            self._failure(
                phase="decode",
                code="BRIDGE_INVALID_JSON",
                message=detail,
                exception=exc,
                attributes={
                    "raw_line": line[:512],
                    "raw_line_truncated": len(line) > 512,
                    "stderr_tail": self.stderr_tail_text(),
                },
            )
            raise self._error_type("decode", "BRIDGE_INVALID_JSON", detail) from exc
        if not isinstance(value, Mapping):
            self._failure(
                phase="decode",
                code="BRIDGE_MESSAGE_NOT_OBJECT",
                message=line[:512],
            )
            raise self._error_type("decode", "BRIDGE_MESSAGE_NOT_OBJECT", line[:512])
        return JsonlProcessMessage(
            str(value.get("type", "")),
            dict(cast(Mapping[str, JsonValue], value)),
        )

    def close(self) -> None:
        process = self._process
        if process is None:
            return
        stdout_task = self._stdout_task
        stderr_task = self._stderr_task
        try:
            try:
                if process.poll() is None:
                    try:
                        self._process_supervisor.await_exit(
                            f"{self._task_namespace}:{self._transport_identity}:graceful-close",
                            process,
                            deadline=Deadline.after(3.0),
                        ).result(timeout=4.0)
                    except TimeoutError:
                        self._terminate_process(process)
            finally:
                if process.poll() is None:
                    self._terminate_process(process)
                self._stdout_stop.set()
                drain_errors: list[BaseException] = []
                pending: list[TaskHandlePort[None]] = []
                for handle in (stdout_task, stderr_task):
                    if handle is None:
                        continue
                    try:
                        handle.result(timeout=0.25)
                    except TimeoutError:
                        pending.append(handle)
                    except BaseException as exc:
                        drain_errors.append(exc)
                for stream in (process.stdout, process.stderr):
                    if stream is not None:
                        try:
                            stream.close()
                        except (OSError, ValueError):
                            pass
                for handle in pending:
                    try:
                        handle.result(timeout=2.0)
                    except BaseException as exc:
                        drain_errors.append(exc)
                if drain_errors:
                    raise ExceptionGroup(
                        f"{self._task_namespace} drain tasks failed to converge", drain_errors
                    )
        finally:
            # Never discard the exact physical process identity while the child
            # may still be alive.  Termination can fail transiently; retaining
            # the process and drain-task handles makes close() retryable and
            # prevents a later caller from treating a surviving child as gone.
            if process.poll() is not None:
                self._stdout_task = None
                self._stderr_task = None
                self._process = None

    def _terminate_process(self, process: JsonlProcess) -> None:
        if process.poll() is not None:
            return
        self._process_supervisor.terminate(
            f"{self._task_namespace}:{self._transport_identity}:terminate",
            process,
            deadline=Deadline.after(6.0),
        ).result(timeout=7.0)


__all__ = [
    "FailureReporter",
    "JsonlProcess",
    "JsonlProcessError",
    "JsonlProcessMessage",
    "JsonlProcessSpec",
    "JsonlProcessTransport",
    "ProcessFactory",
    "safe_exception_message",
]
