from __future__ import annotations

from threading import Event, Lock
from time import sleep

from noetrium_platform.composition.method_agent_panel import (
    PooledMethodAgentPanelExecution,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.concurrency.api import (
    ConcurrencyBudget,
    ExecutionLaneKind,
    ExecutionSpec,
    TaskFailureScope,
)
from noetrium_platform.foundation.kernel.kernel import ExecutionContext
from noetrium_platform.research.execution.policy.api import AdmissionBudget
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
)
from noetrium_platform.research.execution.workflow.composition.model_agent import (
    MethodAgentPanelInvocation,
)


def _request(run_id: str = "run-panel") -> MethodAgentRequest:
    return MethodAgentRequest(
        agent_id="panel",
        goal={},
        view={},
        input_value=None,
        previous_value=None,
        context=ExecutionContext(
            run_id,
            f"trace-{run_id}",
            f"span-{run_id}",
            execution_tenant_id="paper-a",
        ),
    )


def test_pooled_method_panel_fans_out_and_reassembles_canonically() -> None:
    pool = ResearchExecutionPool()
    lock = Lock()
    entered: list[int] = []
    both = Event()
    try:
        def invocation(index: int) -> MethodAgentPanelInvocation:
            def invoke() -> MethodAgentResult:
                with lock:
                    entered.append(index)
                    if len(entered) == 2:
                        both.set()
                if not both.wait(2.0):
                    raise AssertionError("Method panel invocations executed serially")
                return MethodAgentResult(value={"member_index": index})

            return MethodAgentPanelInvocation(
                member_index=index,
                invoke=invoke,
                abort=lambda: None,
            )

        execution = PooledMethodAgentPanelExecution(
            pool,
            execution_tenant_id="paper-a",
        )
        rows = execution.execute(
            "panel",
            tuple(invocation(index) for index in range(2)),
            _request(),
        )

        assert set(entered) == {0, 1}
        assert tuple(index for index, _result in rows) == (0, 1)
        assert tuple(
            result.value["member_index"] for _index, result in rows
        ) == (0, 1)
        admission = pool.capability_io_admission_snapshot()
        assert admission.in_flight == 0
        assert admission.waiting == 0
    finally:
        pool.close()


def test_pooled_method_panel_uses_authority_bounded_rolling_window() -> None:
    capability_budget = ConcurrencyBudget(
        max_blocking_io_workers=2,
        max_serial_workers=2,
        max_cpu_workers=1,
        max_blocking_io_in_flight=2,
        max_async_io_in_flight=2,
        max_cpu_in_flight=1,
        default_queue_capacity=16,
    )
    admission_budget = AdmissionBudget(
        max_total_in_flight=2,
        max_in_flight_per_group=2,
        max_in_flight_per_tenant=2,
        max_in_flight_per_resource=2,
        max_blocking_io_in_flight=2,
        max_async_io_in_flight=2,
        max_cpu_in_flight=1,
        max_serial_in_flight=2,
        max_waiting=16,
    )
    pool = ResearchExecutionPool(
        capability_io_concurrency_budget=capability_budget,
        capability_io_admission_budget=admission_budget,
    )
    lock = Lock()
    current = 0
    maximum = 0
    aborts: list[int] = []
    try:
        def invocation(index: int) -> MethodAgentPanelInvocation:
            def invoke() -> MethodAgentResult:
                nonlocal current, maximum
                with lock:
                    current += 1
                    maximum = max(maximum, current)
                try:
                    sleep(0.03)
                    return MethodAgentResult(value={"member_index": index})
                finally:
                    with lock:
                        current -= 1

            return MethodAgentPanelInvocation(
                member_index=index,
                invoke=invoke,
                abort=lambda index=index: aborts.append(index),
            )

        execution = PooledMethodAgentPanelExecution(
            pool,
            execution_tenant_id="paper-b",
        )
        rows = execution.execute(
            "panel",
            tuple(invocation(index) for index in range(8)),
            _request("run-window"),
        )

        assert maximum == 2
        assert tuple(index for index, _result in rows) == tuple(range(8))
        assert aborts == []
        admission = pool.capability_io_admission_snapshot()
        assert admission.rejected_total == 0
        assert admission.in_flight == 0
        assert admission.waiting == 0
    finally:
        pool.close()


def test_method_panel_fanout_does_not_reenter_parent_machine_domain() -> None:
    machine_budget = ConcurrencyBudget(
        max_blocking_io_workers=1,
        max_serial_workers=1,
        max_cpu_workers=1,
        max_blocking_io_in_flight=1,
        max_async_io_in_flight=1,
        max_cpu_in_flight=1,
        default_queue_capacity=8,
    )
    capability_budget = ConcurrencyBudget(
        max_blocking_io_workers=2,
        max_serial_workers=2,
        max_cpu_workers=1,
        max_blocking_io_in_flight=2,
        max_async_io_in_flight=2,
        max_cpu_in_flight=1,
        default_queue_capacity=8,
    )
    pool = ResearchExecutionPool(
        machine_concurrency_budget=machine_budget,
        capability_io_concurrency_budget=capability_budget,
    )
    try:
        execution = PooledMethodAgentPanelExecution(
            pool,
            execution_tenant_id="paper-c",
        )
        invocations = tuple(
            MethodAgentPanelInvocation(
                member_index=index,
                invoke=lambda index=index: MethodAgentResult(
                    value={"member_index": index}
                ),
                abort=lambda: None,
            )
            for index in range(2)
        )
        parent = pool.open_machine_group(
            "parent-machine-domain-regression",
            tenant_id="paper-c",
        )

        def run_parent(context):
            context.checkpoint()
            rows = execution.execute(
                "panel",
                invocations,
                _request("run-parent"),
            )
            context.checkpoint()
            return rows

        handle = parent.submit(
            ExecutionSpec(
                task_id="parent-machine-task",
                lane_kind=ExecutionLaneKind.BLOCKING_IO,
                failure_scope=TaskFailureScope.CALLER,
            ),
            run_parent,
        )
        rows = handle.result(timeout=3.0)
        assert tuple(index for index, _result in rows) == (0, 1)
        pool.close_machine_group(parent)
    finally:
        pool.close()
