from __future__ import annotations

import threading
import time

import pytest

from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    Deadline,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskCancelled,
    TaskDeadlineExceeded,
    TaskFailurePolicy,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.concurrency.composition import build_concurrency_runtime
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessTerminationPolicy
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_supervisor


class _FakeProcess:
    def __init__(self, pid: int, *, exit_after: float | None = None, terminate_exits: bool = True) -> None:
        self.pid = pid
        self._exit_at = None if exit_after is None else time.monotonic() + exit_after
        self._terminate_exits = terminate_exits
        self._code: int | None = None
        self.terminate_calls = 0
        self.kill_calls = 0

    def poll(self) -> int | None:
        if self._code is None and self._exit_at is not None and time.monotonic() >= self._exit_at:
            self._code = 0
        return self._code

    def terminate(self) -> None:
        self.terminate_calls += 1
        if self._terminate_exits:
            self._code = 0

    def kill(self) -> None:
        self.kill_calls += 1
        self._code = -9


def _runtime():
    return build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            max_async_io_in_flight=64,
            default_queue_capacity=8,
        )
    )


def test_async_process_supervisor_watches_many_processes_on_one_async_owner_thread() -> None:
    before = {thread.ident for thread in threading.enumerate()}
    runtime = _runtime()
    group = runtime.open_task_group("process-supervision", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    supervisor = build_process_supervisor(
        group,
        policy=ProcessTerminationPolicy(poll_interval_seconds=0.005),
    )
    owned_ident: int | None = None
    try:
        handles = [
            supervisor.await_exit(
                f"proc-{index}",
                _FakeProcess(1000 + index, exit_after=0.02),
                deadline=Deadline.after(1.0),
            )
            for index in range(32)
        ]
        receipts = [handle.result(1) for handle in handles]
        assert [receipt.exit_code for receipt in receipts] == [0] * 32
        async_threads = [thread for thread in threading.enumerate() if thread.name == "platform-async-io"]
        owned_threads = [thread for thread in async_threads if thread.ident not in before]
        assert len(owned_threads) == 1
        owned_ident = owned_threads[0].ident
    finally:
        group.close()
        runtime.close()
    if owned_ident is not None:
        deadline = time.monotonic() + 1.0
        while time.monotonic() < deadline and any(
            thread.ident == owned_ident for thread in threading.enumerate()
        ):
            time.sleep(0.01)
        assert not any(thread.ident == owned_ident for thread in threading.enumerate())


def test_process_supervisors_have_distinct_task_identity_namespaces_in_one_group() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("process-supervision-shared", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    first = build_process_supervisor(group, policy=ProcessTerminationPolicy(poll_interval_seconds=0.005))
    second = build_process_supervisor(group, policy=ProcessTerminationPolicy(poll_interval_seconds=0.005))
    try:
        left = first.await_exit(
            "same-process-role", _FakeProcess(2001, exit_after=0.01), deadline=Deadline.after(1.0)
        )
        right = second.await_exit(
            "same-process-role", _FakeProcess(2002, exit_after=0.01), deadline=Deadline.after(1.0)
        )
        assert left.task_id != right.task_id
        assert left.result(1).exit_code == 0
        assert right.result(1).exit_code == 0
    finally:
        group.close()
        runtime.close()


def test_async_process_supervisor_escalates_terminate_to_kill_without_blocking_wait() -> None:
    runtime = _runtime()
    group = runtime.open_task_group("process-termination", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    supervisor = build_process_supervisor(
        group,
        policy=ProcessTerminationPolicy(
            poll_interval_seconds=0.005,
            graceful_timeout_seconds=0.02,
            kill_timeout_seconds=0.05,
        ),
    )
    process = _FakeProcess(4242, terminate_exits=False)
    try:
        receipt = supervisor.terminate(
            "stubborn",
            process,
            deadline=Deadline.after(0.5),
        ).result(1)
        assert receipt.exit_code == -9
        assert receipt.escalated_to_kill
        assert process.terminate_calls == 1
        assert process.kill_calls == 1
    finally:
        group.close()
        runtime.close()



def test_process_command_admission_deadline_prevents_late_spawn(tmp_path) -> None:
    import asyncio
    import sys
    from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime import AsyncProcessCommandRunner

    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_cpu_workers=1,
            max_async_io_in_flight=1,
            default_queue_capacity=1,
        )
    )
    group = runtime.open_task_group(
        "process-command-admission-deadline",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )

    async def occupy_async_lane(context):
        context.checkpoint()
        await asyncio.sleep(30)

    blocker = group.submit(
        ExecutionSpec(
            task_id="process-command-admission-blocker",
            lane_kind=ExecutionLaneKind.ASYNC_IO,
            failure_scope=TaskFailureScope.CALLER,
        ),
        occupy_async_lane,
    )
    marker = tmp_path / "late-spawn.txt"
    runner = AsyncProcessCommandRunner(
        group,
        cleanup_timeout_seconds=0.02,
    )
    started = time.monotonic()
    try:
        with pytest.raises(TaskDeadlineExceeded):
            runner.execute(
                (sys.executable, "-c", f"from pathlib import Path; Path({str(marker)!r}).write_text('spawned')"),
                timeout_seconds=0.05,
            )
        assert time.monotonic() - started < 0.75
        time.sleep(0.1)
        assert not marker.exists(), "deadline-expired command spawned after caller failure"
    finally:
        blocker.cancel()
        group.close(cancel_pending=True)
        runtime.close()


def test_process_command_rejects_non_finite_or_unbounded_timeouts() -> None:
    from noetrium_platform.infrastructure.lifecycle.process.supervision.runtime import AsyncProcessCommandRunner

    runtime = _runtime()
    group = runtime.open_task_group(
        "process-command-finite-timeout",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    runner = AsyncProcessCommandRunner(group)
    try:
        for timeout in (None, float("inf"), float("nan"), 0.0, -1.0):
            with pytest.raises(ValueError, match="finite and positive"):
                runner.execute(("not-spawned",), timeout_seconds=timeout)  # type: ignore[arg-type]
    finally:
        group.close()
        runtime.close()

def test_async_process_command_runner_executes_and_captures_without_blocking_worker() -> None:
    import sys
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner

    runtime = _runtime()
    group = runtime.open_task_group("process-command", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    runner = build_process_command_runner(group)
    try:
        result = runner.execute(
            (sys.executable, "-c", "import sys; print('out'); print('err', file=sys.stderr)"),
            timeout_seconds=5.0,
        ).result(7)
        assert result.return_code == 0
        assert result.stdout.strip() == b"out"
        assert result.stderr.strip() == b"err"
        assert not result.timed_out
        assert result.spawn_error is None
    finally:
        group.close()
        runtime.close()


def test_async_process_command_runner_timeout_terminates_and_reaps_child() -> None:
    import sys
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner

    runtime = _runtime()
    group = runtime.open_task_group("process-command-timeout", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    runner = build_process_command_runner(group)
    try:
        result = runner.execute(
            (sys.executable, "-c", "import time; print('started', flush=True); time.sleep(30)"),
            timeout_seconds=0.05,
        ).result(2)
        assert result.return_code == 124
        assert result.timed_out
    finally:
        group.close()
        runtime.close()


def test_async_process_command_runner_timeout_reaps_spawned_process_group(tmp_path) -> None:
    import os
    import sys
    from pathlib import Path
    import pytest
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner

    if os.name != "posix":
        pytest.skip("process-group cleanup proof is POSIX-specific")

    runtime = _runtime()
    group = runtime.open_task_group("process-command-group-timeout", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    runner = build_process_command_runner(group)
    pid_file = Path(tmp_path) / "grandchild.pid"
    child_code = (
        "import pathlib,subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    try:
        result = runner.execute(
            (sys.executable, "-c", child_code),
            timeout_seconds=3.0,
        ).result(6)
        assert result.timed_out
        deadline = time.monotonic() + 2.0
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_file.exists()
        grandchild_pid = int(pid_file.read_text())
        while time.monotonic() < deadline:
            try:
                os.kill(grandchild_pid, 0)
            except ProcessLookupError:
                break
            # A killed orphan may briefly remain as a zombie until adopted/reaped.
            stat_path = Path("/proc") / str(grandchild_pid) / "stat"
            if stat_path.exists():
                fields = stat_path.read_text().split()
                if len(fields) > 2 and fields[2] == "Z":
                    break
            time.sleep(0.02)
        else:
            raise AssertionError("grandchild survived process-group timeout cleanup")
    finally:
        group.close()
        runtime.close()


def test_process_command_cancellation_reaps_descendant_tree(tmp_path) -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner

    runtime = _runtime()
    group = runtime.open_task_group("process-command-cancel-tree", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    runner = build_process_command_runner(group)
    pid_file = Path(tmp_path) / "cancel-grandchild.pid"
    child_code = (
        "import pathlib,subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    handle = runner.execute((sys.executable, "-c", child_code), timeout_seconds=30.0)
    try:
        deadline = time.monotonic() + 3.0
        while not pid_file.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        assert pid_file.exists()
        grandchild_pid = int(pid_file.read_text())
        assert handle.cancel()
        with pytest.raises(TaskCancelled):
            handle.result(5)

        deadline = time.monotonic() + 3.0
        while time.monotonic() < deadline:
            if os.name == "nt":
                listed = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {grandchild_pid}", "/NH"],
                    capture_output=True, text=True, check=False,
                ).stdout
                if str(grandchild_pid) not in listed:
                    break
            else:
                try:
                    os.kill(grandchild_pid, 0)
                except ProcessLookupError:
                    break
                stat_path = Path("/proc") / str(grandchild_pid) / "stat"
                if stat_path.exists():
                    fields = stat_path.read_text().split()
                    if len(fields) > 2 and fields[2] == "Z":
                        break
            time.sleep(0.02)
        else:
            raise AssertionError("grandchild survived structured cancellation cleanup")
    finally:
        group.close()
        runtime.close()


def test_async_process_command_runner_bounds_retained_pipe_memory_but_counts_all_bytes() -> None:
    import sys
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner

    runtime = _runtime()
    group = runtime.open_task_group("process-command-output-budget", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    runner = build_process_command_runner(group)
    payload_size = 512 * 1024
    retained_limit = 4096
    code = (
        "import os; "
        f"payload=b'x'*{payload_size}; "
        "os.write(1,payload); os.write(2,payload)"
    )
    try:
        result = runner.execute(
            (sys.executable, "-c", code),
            timeout_seconds=3.0,
            output_limit_bytes=retained_limit,
        ).result(5)
        assert result.return_code == 0
        assert len(result.stdout) == retained_limit
        assert len(result.stderr) == retained_limit
        assert result.stdout_bytes == payload_size
        assert result.stderr_bytes == payload_size
        assert result.stdout_truncated
        assert result.stderr_truncated
    finally:
        group.close()
        runtime.close()


def test_async_process_command_runner_timeout_drains_chatty_child_without_pipe_deadlock() -> None:
    import sys
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner

    runtime = _runtime()
    group = runtime.open_task_group("process-command-chatty-timeout", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    runner = build_process_command_runner(group)
    code = (
        "import os,time; "
        "payload=b'z'*65536; "
        "[(os.write(1,payload),os.write(2,payload)) for _ in range(32)]; "
        "time.sleep(30)"
    )
    try:
        result = runner.execute(
            (sys.executable, "-c", code),
            timeout_seconds=0.15,
            output_limit_bytes=2048,
        ).result(4)
        assert result.timed_out
        assert result.return_code == 124
        assert len(result.stdout) <= 2048
        assert len(result.stderr) <= 2048
        assert result.stdout_bytes >= len(result.stdout)
        assert result.stderr_bytes >= len(result.stderr)
    finally:
        group.close()
        runtime.close()


def test_windows_process_command_timeout_reaps_descendant_tree(tmp_path) -> None:
    import os
    import subprocess
    import sys
    from pathlib import Path
    import pytest
    from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import build_process_command_runner

    if os.name != "nt":
        pytest.skip("Windows Job Object proof is Windows-specific")

    runtime = _runtime()
    group = runtime.open_task_group("process-command-win-tree", failure_policy=TaskFailurePolicy.COLLECT_ALL)
    runner = build_process_command_runner(group)
    pid_file = Path(tmp_path) / "grandchild.pid"
    child_code = (
        "import pathlib,subprocess,sys,time; "
        "p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); "
        f"pathlib.Path({str(pid_file)!r}).write_text(str(p.pid)); "
        "time.sleep(30)"
    )
    try:
        result = runner.execute(
            (sys.executable, "-c", child_code), timeout_seconds=1.0
        ).result(6)
        assert result.timed_out and result.return_code == 124
        assert pid_file.exists()
        grandchild_pid = int(pid_file.read_text())
        listed = subprocess.run(
            ["tasklist", "/FI", f"PID eq {grandchild_pid}", "/NH"],
            capture_output=True,
            text=True,
            check=False,
        ).stdout
        assert str(grandchild_pid) not in listed
    finally:
        group.close()
        runtime.close()
