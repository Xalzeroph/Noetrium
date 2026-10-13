from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.api import ModelRequestRecorderPort, ModelRequestTokenizationPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointDispatchPoolPort,
    OperationalModelServingInventory,
)
from noetrium_platform.foundation.kernel.kernel import JsonInput
from noetrium_platform.research.execution.policy.api import ExecutionBudgetAuthorityPort
from noetrium_platform.research.execution.workflow.api import (
    NoetriumUnit,
    analyze_method_runtime_requirements,
)
from noetrium_platform.research.execution.workflow.composition import (
    MethodModelAgentLoop,
    MethodAgentLoopRouter,
    MethodModelEndpointBinding,
    MethodRuntimePortInventory,
    MethodViewChatRequestFactory,
)


def compose_operational_model_method_runtime(
    programs: tuple[NoetriumUnit, ...],
    serving: OperationalModelServingInventory,
    *,
    pool: ModelEndpointDispatchPoolPort,
    recorder: ModelRequestRecorderPort,
    generation_options: Mapping[str, JsonInput] | None = None,
    tokenization: ModelRequestTokenizationPort | None = None,
    execution_budget: ExecutionBudgetAuthorityPort | None = None,
    base: MethodRuntimePortInventory | None = None,
) -> MethodRuntimePortInventory:
    """Bind one operational model fleet to all model-agent needs in MethodPrograms.

    This does not assert scientific equivalence with any Study model role. It only
    binds the actual immutable serving identity used for execution. Claim/assurance
    remains owned by Research binding evidence.
    """

    if type(programs) is not tuple or any(
        not isinstance(program, NoetriumUnit) for program in programs
    ):
        raise TypeError("operational Method runtime programs must be NoetriumUnit tuple")
    if not isinstance(serving, OperationalModelServingInventory):
        raise TypeError(
            "operational Method runtime serving must be OperationalModelServingInventory"
        )
    if not isinstance(pool, ModelEndpointDispatchPoolPort):
        raise TypeError(
            "operational Method runtime pool must satisfy ModelEndpointDispatchPoolPort"
        )
    if not all(
        callable(getattr(recorder, name, None))
        for name in ("record", "reconstruct", "verify_visible_request")
    ):
        raise TypeError(
            "operational Method runtime recorder must provide model request recording"
        )
    if base is not None and not isinstance(base, MethodRuntimePortInventory):
        raise TypeError("operational Method runtime base must be MethodRuntimePortInventory")
    if base is not None and base.agent_loop is not None:
        raise ValueError(
            "operational Method runtime cannot replace an existing agent-loop authority"
        )

    agent_ids = tuple(
        sorted(
            {
                agent_id
                for program in programs
                for agent_id in analyze_method_runtime_requirements(program).agent_ids
            }
        )
    )
    if agent_ids:
        if tokenization is None or not isinstance(tokenization, ModelRequestTokenizationPort):
            raise TypeError("operational Method model runtime requires exact tokenization authority")
        if execution_budget is None or not isinstance(execution_budget, ExecutionBudgetAuthorityPort):
            raise TypeError("operational Method model runtime requires execution budget authority")

    if not agent_ids:
        return MethodRuntimePortInventory(
            capabilities=None if base is None else base.capabilities,
            unit_activation=None if base is None else base.unit_activation,
            schemas=None if base is None else base.schemas,
        )

    factory = MethodViewChatRequestFactory(
        serving.served_model_name,
        {} if generation_options is None else generation_options,
    )
    loops = {
        agent_id: MethodModelAgentLoop(
            binding=MethodModelEndpointBinding(
                agent_id=agent_id,
                role=agent_id,
                model=serving.model,
                request_factory_digest=factory.digest,
            ),
            pool=pool,
            recorder=recorder,
            request_factory=factory,
            tokenization=tokenization,
            execution_budget=execution_budget,
        )
        for agent_id in agent_ids
    }
    return MethodRuntimePortInventory(
        agent_loop=MethodAgentLoopRouter(loops),
        capabilities=None if base is None else base.capabilities,
        unit_activation=None if base is None else base.unit_activation,
        schemas=None if base is None else base.schemas,
    )


__all__ = ["compose_operational_model_method_runtime"]
