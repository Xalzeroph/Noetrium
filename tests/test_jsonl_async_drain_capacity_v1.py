from __future__ import annotations

import sys

from noetrium_platform.capabilities.environment.providers import (
    JsonlProcessSpec,
    JsonlProcessTransport,
)
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailurePolicy,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.concurrency.composition import (
    build_concurrency_runtime,
)
from noetrium_platform.infrastructure.lifecycle.host.providers import (
    LocalOperatingSystemRoute,
)
from noetrium_platform.infrastructure.lifecycle.process.supervision.composition import (
    build_process_supervisor,
)


def test_long_lived_jsonl_drains_do_not_consume_blocking_worker_capacity(tmp_path) -> None:
    runtime = build_concurrency_runtime(
        budget=ConcurrencyBudget(
            max_blocking_io_workers=1,
            max_serial_workers=1,
            max_cpu_workers=1,
            max_blocking_io_in_flight=1,
            max_async_io_in_flight=16,
            max_cpu_in_flight=1,
            default_queue_capacity=32,
        )
    )
    group = runtime.open_task_group(
        "jsonl-async-drain-capacity",
        failure_policy=TaskFailurePolicy.COLLECT_ALL,
    )
    supervisor = build_process_supervisor(group)
    transports: list[JsonlProcessTransport] = []
    try:
        for index in range(5):
            transport = JsonlProcessTransport(
                spec=JsonlProcessSpec(
                    (
                        sys.executable,
                        "-u",
                        "-c",
                        "import sys; sys.stdin.read()",
                    ),
                    str(tmp_path),
                ),
                operating_system=LocalOperatingSystemRoute(),
                task_group=group,
                process_supervisor=supervisor,
                transport_identity=f"long-lived-{index}",
            )
            transport.start()
            transports.append(transport)

        cleanup = group.submit(
            ExecutionSpec(
                task_id="blocking-cleanup-proof",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            lambda context: (
                context.checkpoint(),
                "cleanup-ran",
            )[1],
        )
        assert cleanup.result(1.0) == "cleanup-ran"
    finally:
        errors: list[BaseException] = []
        for transport in reversed(transports):
            try:
                transport.close()
            except BaseException as exc:
                errors.append(exc)
        try:
            group.close(cancel_pending=True)
        except BaseException as exc:
            errors.append(exc)
        try:
            runtime.close()
        except BaseException as exc:
            errors.append(exc)
        if errors:
            raise ExceptionGroup("JSONL async drain capacity cleanup failed", errors)
