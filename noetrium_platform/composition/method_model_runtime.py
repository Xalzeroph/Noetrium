from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.api import ModelRequestRecorderPort
from noetrium_platform.capabilities.model.serving.endpoint.api import (
    ModelEndpointDispatchPoolPort,
    OperationalModelServingInventory,
)
from noetrium_platform.foundation.kernel.kernel import JsonInput
from noetrium_platform.research.execution.workflow.api import (
    MethodProgram,
    analyze_method_runtime_requirements,
)
from noetrium_platform.research.execution.workflow.composition import (
    DispatchPoolBackedMethodAgentLoop,
    MethodAgentLoopRouter,
    MethodModelEndpointBinding,
    MethodRuntimePortInventory,
    MethodViewChatRequestFactory,
)


def compose_operational_model_method_runtime(
    programs: tuple[MethodProgram, ...],
    serving: OperationalModelServingInventory,
    *,
    pool: ModelEndpointDispatchPoolPort,
    recorder: ModelRequestRecorderPort,
    generation_options: Mapping[str, JsonInput] | None = None,
    base: MethodRuntimePortInventory | None = None,
) -> MethodRuntimePortInventory:
    """Bind one operational model fleet to all model-agent needs in MethodPrograms.

    This does not assert scientific equivalence with any Study model role. It only
    binds the actual immutable serving identity used for execution. Claim/assurance
    remains owned by Research binding evidence.
    """

    if type(programs) is not tuple or any(
        not isinstance(program, MethodProgram) for program in programs
    ):
        raise TypeError("operational Method runtime programs must be MethodProgram tuple")
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
    if not agent_ids:
        return MethodRuntimePortInventory(
            capabilities=None if base is None else base.capabilities,
            child_machines=None if base is None else base.child_machines,
            schemas=None if base is None else base.schemas,
        )

    factory = MethodViewChatRequestFactory(
        serving.served_model_name,
        {} if generation_options is None else generation_options,
    )
    loops = {
        agent_id: DispatchPoolBackedMethodAgentLoop(
            binding=MethodModelEndpointBinding(
                agent_id=agent_id,
                role=agent_id,
                model=serving.model,
                request_factory_digest=factory.digest,
            ),
            pool=pool,
            recorder=recorder,
            request_factory=factory,
        )
        for agent_id in agent_ids
    }
    return MethodRuntimePortInventory(
        agent_loop=MethodAgentLoopRouter(loops),
        capabilities=None if base is None else base.capabilities,
        child_machines=None if base is None else base.child_machines,
        schemas=None if base is None else base.schemas,
    )


__all__ = ["compose_operational_model_method_runtime"]
