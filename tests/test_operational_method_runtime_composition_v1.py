from __future__ import annotations

from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointRoute,
    OperationalModelEndpointReplica,
    OperationalModelEndpointReplicaSet,
    OperationalModelServingInventory,
)
from noetrium_platform.capabilities.model.serving.endpoint.composition import (
    build_adaptive_operational_endpoint_pool,
)
from noetrium_platform.composition.method_model_runtime import (
    compose_operational_model_method_runtime,
)
from noetrium_platform.composition.model_requests import (
    build_directory_model_request_recorder,
)
from noetrium_platform.composition.research_execution_pool import ResearchExecutionPool
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodNodeResult,
    MethodProgramBuilder,
)
from noetrium_platform.research.execution.workflow.composition import (
    plan_method_runtime_binding,
)


def _program(agent_id: str):
    identity = MethodProgramIdentity(
        MethodIdentity(f"runtime.{agent_id}", "1", "1", "1")
    )

    def done(request):
        return MethodNodeResult(value=request.previous_value)

    return (
        MethodProgramBuilder(identity, entrypoint="agent")
        .agent(
            "agent",
            "runtime.agent",
            agent_id,
            ("done",),
            view_handler=lambda request: {"prompt": "respond"},
        )
        .return_node("done", "runtime.done", done)
        .build()
    )


def _serving() -> OperationalModelServingInventory:
    model = ImmutableModelIdentity(
        logical_name="runtime-model",
        model_id="Qwen/Test",
        revision="checkpoint",
        engine="vllm",
        engine_version="test",
        dtype="bfloat16",
        quantization=None,
        context_length=4096,
        tokenizer_revision="checkpoint",
    )
    replica = OperationalModelEndpointReplica(
        ModelEndpointRoute(
            "runtime-deployment",
            "a" * 64,
            "http://127.0.0.1:18080",
        ),
        2,
    )
    return OperationalModelServingInventory(
        model,
        "runtime-served-model",
        OperationalModelEndpointReplicaSet((replica,)),
    )


def test_operational_model_composition_binds_union_of_method_agent_requirements(
    tmp_path,
) -> None:
    programs = (_program("agent-b"), _program("agent-a"))
    pool = ResearchExecutionPool()
    group = pool.open_model_io_group("operational-method-runtime-test")
    try:
        serving = _serving()
        dispatch = build_adaptive_operational_endpoint_pool(
            serving.replica_set,
            task_group=group,
            admission_registry=pool.model_admission,
        )
        inventory = compose_operational_model_method_runtime(
            programs,
            serving,
            pool=dispatch,
            recorder=build_directory_model_request_recorder(tmp_path / "requests"),
            generation_options={"max_tokens": 32},
        )
        assert inventory.agent_loop is not None
        assert inventory.agent_loop.agent_ids == ("agent-a", "agent-b")
        for program in programs:
            plan = plan_method_runtime_binding(program, inventory)
            assert plan.complete is True
            assert plan.missing_agent_ids == ()
    finally:
        pool.close_model_io_group(group, cancel_pending=True)
        pool.close()


def test_operational_model_composition_does_not_invent_agent_port_when_unused(
    tmp_path,
) -> None:
    identity = MethodProgramIdentity(MethodIdentity("runtime.no-agent", "1", "1", "1"))

    def done(request):
        return MethodNodeResult(value=request.input_value)

    program = MethodProgramBuilder(identity, entrypoint="done").return_node(
        "done", "runtime.done", done
    ).build()
    pool = ResearchExecutionPool()
    group = pool.open_model_io_group("operational-method-runtime-no-agent-test")
    try:
        serving = _serving()
        dispatch = build_adaptive_operational_endpoint_pool(
            serving.replica_set,
            task_group=group,
            admission_registry=pool.model_admission,
        )
        inventory = compose_operational_model_method_runtime(
            (program,),
            serving,
            pool=dispatch,
            recorder=build_directory_model_request_recorder(tmp_path / "requests"),
        )
        assert inventory.agent_loop is None
    finally:
        pool.close_model_io_group(group, cancel_pending=True)
        pool.close()
