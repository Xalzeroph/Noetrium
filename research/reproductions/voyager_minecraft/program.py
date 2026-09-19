from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.machines.api import (
    ChildFailurePolicy,
    ChildResearchMachineExecution,
    ChildResearchMachineRequest,
)
from noetrium_platform.research.execution.runtime import (
    program_execution_capability_payload,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodEvent,
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .chest_memory import (
    VOYAGER_CHEST_MEMORY_PROGRAM,
    voyager_chest_memory_initial_data,
)
from .curriculum import (
    VOYAGER_CURRICULUM_DEFAULT_WARMUP,
    VOYAGER_CURRICULUM_OBSERVATION_ORDER,
    voyager_curriculum_always_sections,
    voyager_curriculum_compose_message,
    voyager_curriculum_context,
    voyager_curriculum_fixed_biome_questions,
    voyager_curriculum_randomizable_sections,
    voyager_curriculum_render_observation,
    voyager_curriculum_semantics_digest,
    voyager_parse_curriculum_questions,
)
from .curriculum_memory import (
    VOYAGER_QA_MEMORY_PROGRAM,
    voyager_qa_memory_initial_data,
)
from .fidelity import VOYAGER_AUDITED_COMMIT, VOYAGER_MINECRAFT_FIDELITY
from .skill_memory import (
    VOYAGER_SKILL_MEMORY_PROGRAM,
    voyager_skill_memory_initial_data,
)


_CURRICULUM_AGENT = "voyager.curriculum"
_ACTION_AGENT = "voyager.action"
_CRITIC_AGENT = "voyager.critic"
_QA_AGENT = "voyager.curriculum_qa"
_CURRICULUM_QA_QUESTION_AGENT = "voyager.curriculum_qa_questions"
_CURRICULUM_RANDOM_CAPABILITY = "research.random.bernoulli-mask"
_PROGRAM_EXECUTION_CAPABILITY = "execution.program.execute"
_SKILL_MEMORY_HOST = "voyager.skill-memory"
_CHEST_MEMORY_HOST = "voyager.chest-memory"
_QA_MEMORY_HOST = "voyager.curriculum-qa-memory"

_INITIAL_TASK = "Mine 1 wood log"
_INITIAL_CONTEXT = (
    "You can mine one of oak, birch, spruce, jungle, acacia, dark oak, "
    "or mangrove logs."
)
_DEPOSIT_TASK = "Place and deposit useless items into a chest"
_DEPOSIT_PREFIX = "Deposit useless items into the chest at"
_DEPOSIT_CONTEXT = (
    "Your inventory have {inventory_used} occupied slots before depositing. "
    "Place the chest in your inventory to the ground and choose some useless "
    "items to deposit. After depositing, your inventory should only have 20 "
    "occupied slots. You should deposit useless items such as andesite, dirt, "
    "cobblestone, etc. Also, you can deposit low-level tools. For example, if "
    "you have a stone pickaxe, you can deposit a wooden pickaxe. Make sure the "
    "list of useless items are in your inventory (do not list items already in "
    "the chest), You can use bot.inventoryUsed() to check how many inventory "
    "slots are used."
)


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _mapping(value: object, field_name: str) -> dict[str, JsonValue]:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be an object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    return decoded


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    rows = tuple(_text(row, field_name) for row in value)
    return rows


def _integer(value: object, field_name: str) -> int:
    if type(value) is not int or value < 0:
        raise ValueError(f"{field_name} must be a non-negative integer")
    return value


def _is_deposit_task(task: str) -> bool:
    return task == _DEPOSIT_TASK or task.startswith(_DEPOSIT_PREFIX)


def _inventory_used(observation: object) -> int:
    if not isinstance(observation, Mapping):
        return 0
    candidate: object = observation
    status = observation.get("status")
    if isinstance(status, Mapping):
        candidate = status
    if not isinstance(candidate, Mapping):
        return 0
    value = candidate.get("inventoryUsed", candidate.get("inventory_used", 0))
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    return max(0, int(value))


def voyager_minecraft_initial_state(
    *,
    initial_observation: JsonObject | None = None,
) -> JsonObject:
    observation = {} if initial_observation is None else dict(initial_observation)
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "completed_tasks": (),
        "failed_tasks": (),
        "action_iteration": 0,
        "current_task": "",
        "task_context": "",
        "pending_qa_question": "",
        "curriculum_sections": {},
        "curriculum_questions": (),
        "curriculum_answers": (),
        "curriculum_question_index": 0,
        "curriculum_human_message": "",
        "curriculum_random_receipt": None,
        "current_attempt": 0,
        "retrieved_skill_names": (),
        "retrieved_skill_codes": (),
        "retrieved_skill_digests": (),
        "program_name": "",
        "program_code": "",
        "exec_code": "",
        "critique": "",
        "chat_summary": "",
        "execution_errors": (),
        "world_observation": observation,
        "chest_observation": "Chests: None\n\n",
        "task_success": False,
        "last_execution": {},
        "last_skill_write": None,
        "learned_skill_count": 0,
    }


def _require_nested(request: MethodNodeRequest) -> None:
    if request.child_machines is None or request.parent_machine_id is None:
        raise RuntimeError(
            "Voyager requires nested journal-backed MemoryMachines"
        )


def _child_step(
    request: MethodNodeRequest,
    *,
    host_id: str,
    machine_suffix: str,
    program_digest: str,
    initial_data: JsonObject,
    event_kind: str,
    event_payload: JsonObject,
) -> ChildResearchMachineExecution:
    _require_nested(request)
    child_machine_id = f"{request.parent_machine_id}:{machine_suffix}"
    child = request.child_machines.step_once(
        ChildResearchMachineRequest(
            host_id=host_id,
            parent_machine_id=request.parent_machine_id,
            child_machine_id=child_machine_id,
            instance_identity={
                "source_commit": VOYAGER_AUDITED_COMMIT,
                "memory_role": machine_suffix,
                "program_digest": program_digest,
                "child_registry_identity_digest": (
                    request.child_machines.identity_digest
                ),
            },
            initial_data=initial_data,
            failure_policy=ChildFailurePolicy.FAIL_PARENT,
            payload={
                "event": {
                    "kind": event_kind,
                    "payload": event_payload,
                    "source": "voyager-method",
                }
            },
            command_id_prefix=(
                f"{child_machine_id}:{request.node_id}:{request.visit}"
            ),
        )
    )
    if not isinstance(child, ChildResearchMachineExecution):
        raise TypeError("Voyager child memory returned invalid execution")
    if child.status.value != "runnable":
        raise RuntimeError(
            f"Voyager persistent memory stopped unexpectedly: "
            f"{machine_suffix}:{child.status.value}"
        )
    return child


def _child_result(child: ChildResearchMachineExecution) -> JsonObject:
    return _mapping(child.result, "Voyager child memory result")


def _start_task(request: MethodNodeRequest) -> MethodNodeResult:
    action_iteration = _integer(
        request.state.get("action_iteration", 0),
        "Voyager action_iteration",
    )
    if action_iteration > VOYAGER_MINECRAFT_FIDELITY.max_learning_iterations:
        return MethodNodeResult(
            value={
                "reason": "iteration_limit",
                "action_iteration": action_iteration,
            },
            next_node="return",
        )

    completed = _strings(
        request.state.get("completed_tasks", ()),
        "Voyager completed_tasks",
    )
    if len(completed) == 0:
        return MethodNodeResult(
            value={"task": _INITIAL_TASK, "context": _INITIAL_CONTEXT},
            state_update={
                "current_task": _INITIAL_TASK,
                "task_context": _INITIAL_CONTEXT,
                "current_attempt": 0,
                "task_success": False,
                "critique": "",
                "chat_summary": "",
                "execution_errors": (),
            },
            next_node="retrieve_skills",
        )

    observation = request.state.get("world_observation", {})
    inventory_used = _inventory_used(observation)
    if inventory_used >= 33:
        context = _DEPOSIT_CONTEXT.format(inventory_used=inventory_used)
        return MethodNodeResult(
            value={"task": _DEPOSIT_TASK, "context": context},
            state_update={
                "current_task": _DEPOSIT_TASK,
                "task_context": context,
                "current_attempt": 0,
                "task_success": False,
                "critique": "",
                "chat_summary": "",
                "execution_errors": (),
            },
            next_node="retrieve_skills",
        )

    return MethodNodeResult(
        value={
            "completed_task_count": len(completed),
            "inventory_used": inventory_used,
        },
        next_node="prepare_curriculum",
    )


def _prepare_curriculum(request: MethodNodeRequest) -> MethodNodeResult:
    completed = _strings(
        request.state.get("completed_tasks", ()),
        "Voyager completed_tasks",
    )
    failed = _strings(
        request.state.get("failed_tasks", ()),
        "Voyager failed_tasks",
    )
    world = _mapping(
        request.state.get("world_observation", {}),
        "Voyager world_observation",
    )
    chest = _text(
        request.state.get("chest_observation", "Chests: None\n\n"),
        "Voyager chest_observation",
        allow_empty=True,
    )
    sections = voyager_curriculum_render_observation(
        world_observation=world,
        chest_observation=chest,
        completed_tasks=completed,
        failed_tasks=failed,
    )
    progress = len(completed)
    needs_qa = (
        progress >= VOYAGER_CURRICULUM_DEFAULT_WARMUP["context"]
    )
    return MethodNodeResult(
        value={
            "progress": progress,
            "needs_qa": needs_qa,
            "sections_digest": canonical_digest(sections),
        },
        state_update={
            "curriculum_sections": sections,
            "curriculum_questions": (),
            "curriculum_answers": (),
            "curriculum_question_index": 0,
            "curriculum_human_message": "",
            "curriculum_random_receipt": None,
            "pending_qa_question": "",
        },
        next_node=(
            "curriculum_qa_questions"
            if needs_qa
            else "prepare_curriculum_random"
        ),
    )


def _curriculum_qa_questions_view(
    request: MethodNodeRequest,
) -> JsonObject:
    sections = _mapping(
        request.state.get("curriculum_sections", {}),
        "Voyager curriculum sections",
    )
    full_observation = "".join(
        str(sections.get(key, ""))
        for key in VOYAGER_CURRICULUM_OBSERVATION_ORDER
    )
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "role": "curriculum_qa_step1_ask_questions",
        "observation": full_observation,
        "response_format": (
            "Question N: ...\nConcept N: ..."
        ),
        "minimum_questions": 5,
        "maximum_questions": 10,
    }


def _curriculum_question_text(value: JsonValue) -> str:
    if isinstance(value, str):
        return value
    decoded = _mapping(
        value,
        "Voyager curriculum QA question result",
    )
    return _text(
        decoded.get("text", decoded.get("response")),
        "Voyager curriculum QA question text",
    )


def _record_curriculum_qa_questions(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    world = _mapping(
        request.state.get("world_observation", {}),
        "Voyager world_observation",
    )
    fixed = voyager_curriculum_fixed_biome_questions(world)
    generated = voyager_parse_curriculum_questions(
        _curriculum_question_text(request.previous_value)
    )
    questions = (*fixed, *generated)
    return MethodNodeResult(
        value={
            "question_count": len(questions),
            "fixed_question_count": len(fixed),
            "questions_digest": canonical_digest(questions),
        },
        state_update={
            "curriculum_questions": questions,
            "curriculum_answers": (),
            "curriculum_question_index": 0,
            "pending_qa_question": "",
        },
        next_node="curriculum_qa_lookup",
    )


def _curriculum_qa_lookup(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    questions = _strings(
        request.state.get("curriculum_questions", ()),
        "Voyager curriculum questions",
    )
    answers = _strings(
        request.state.get("curriculum_answers", ()),
        "Voyager curriculum answers",
    )
    index = _integer(
        request.state.get("curriculum_question_index", 0),
        "Voyager curriculum question index",
    )
    if index >= len(questions):
        return MethodNodeResult(
            value={
                "question_count": len(questions),
                "answer_count": len(answers),
            },
            next_node="prepare_curriculum_random",
        )

    question = questions[index]
    child = _child_step(
        request,
        host_id=_QA_MEMORY_HOST,
        machine_suffix="voyager-curriculum-qa-memory",
        program_digest=VOYAGER_QA_MEMORY_PROGRAM.program_digest,
        initial_data=voyager_qa_memory_initial_data(),
        event_kind="voyager.qa.lookup",
        event_payload={
            "question": question,
            "allow_semantic": True,
        },
    )
    result = _child_result(child)
    if result.get("hit") is True:
        answer = _text(
            result.get("answer"),
            "Voyager curriculum cached QA answer",
        )
        return MethodNodeResult(
            value={
                "question": question,
                "answer": answer,
                "cache_hit": True,
                "semantic_distance": result.get("distance"),
            },
            state_update={
                "curriculum_answers": (*answers, answer),
                "curriculum_question_index": index + 1,
                "pending_qa_question": "",
            },
            next_node="curriculum_qa_lookup",
            child_links=(child.link,),
        )

    return MethodNodeResult(
        value={
            "question": question,
            "cache_hit": False,
        },
        state_update={"pending_qa_question": question},
        next_node="curriculum_qa_answer",
        child_links=(child.link,),
    )


def _record_curriculum_qa_answer(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    question = _text(
        request.state.get("pending_qa_question"),
        "Voyager pending curriculum QA question",
    )
    answer = _qa_answer_text(request.previous_value)
    child = _child_step(
        request,
        host_id=_QA_MEMORY_HOST,
        machine_suffix="voyager-curriculum-qa-memory",
        program_digest=VOYAGER_QA_MEMORY_PROGRAM.program_digest,
        initial_data=voyager_qa_memory_initial_data(),
        event_kind="voyager.qa.write",
        event_payload={
            "question": question,
            "answer": answer,
        },
    )
    result = _child_result(child)
    answers = _strings(
        request.state.get("curriculum_answers", ()),
        "Voyager curriculum answers",
    )
    index = _integer(
        request.state.get("curriculum_question_index", 0),
        "Voyager curriculum question index",
    )
    return MethodNodeResult(
        value={
            "question": question,
            "answer": answer,
            "entry_digest": result.get("entry_digest"),
        },
        state_update={
            "curriculum_answers": (*answers, answer),
            "curriculum_question_index": index + 1,
            "pending_qa_question": "",
        },
        next_node="curriculum_qa_lookup",
        child_links=(child.link,),
    )


def _prepare_curriculum_random(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    completed = _strings(
        request.state.get("completed_tasks", ()),
        "Voyager completed_tasks",
    )
    progress = len(completed)
    sections = _mapping(
        request.state.get("curriculum_sections", {}),
        "Voyager curriculum sections",
    )
    questions = _strings(
        request.state.get("curriculum_questions", ()),
        "Voyager curriculum questions",
    )
    answers = _strings(
        request.state.get("curriculum_answers", ()),
        "Voyager curriculum answers",
    )
    if questions:
        sections["context"] = voyager_curriculum_context(
            questions,
            answers,
        )
    eligible = voyager_curriculum_randomizable_sections(
        progress=progress,
    )
    return MethodNodeResult(
        value={
            "decision_id": (
                f"voyager.curriculum.sections:"
                f"{request.context.run_id}:{request.visit}"
            ),
            "items": eligible,
            "probability": 0.8,
            "mode": "independent_bernoulli",
            "source_semantics": "python.random.random<0.8",
        },
        state_update={"curriculum_sections": sections},
        next_node="curriculum_random",
    )


def _record_curriculum_random(
    request: MethodNodeRequest,
) -> MethodNodeResult:
    value = _mapping(
        request.previous_value,
        "Voyager curriculum random result",
    )
    included = _strings(
        value.get("included_items", ()),
        "Voyager included curriculum sections",
    )
    completed = _strings(
        request.state.get("completed_tasks", ()),
        "Voyager completed_tasks",
    )
    progress = len(completed)
    allowed = set(
        voyager_curriculum_randomizable_sections(progress=progress)
    )
    unknown = tuple(item for item in included if item not in allowed)
    if unknown:
        raise ValueError(
            "Voyager curriculum random capability returned "
            f"ineligible sections: {unknown}"
        )
    sections = _mapping(
        request.state.get("curriculum_sections", {}),
        "Voyager curriculum sections",
    )
    message = voyager_curriculum_compose_message(
        sections=sections,
        included_random_sections=included,
    )
    receipt = value.get("receipt")
    return MethodNodeResult(
        value={
            "included_random_sections": included,
            "always_sections": voyager_curriculum_always_sections(
                progress=progress
            ),
            "human_message_digest": canonical_digest(message),
            "random_receipt": receipt,
        },
        state_update={
            "curriculum_human_message": message,
            "curriculum_random_receipt": receipt,
        },
        next_node="curriculum",
        events=(
            MethodEvent(
                "voyager.curriculum.observation-mask",
                {
                    "progress": progress,
                    "included_random_sections": included,
                    "message_digest": canonical_digest(message),
                    "receipt_digest": canonical_digest(receipt),
                },
            ),
        ),
    )


def _curriculum_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "human_message": _text(
            request.state.get("curriculum_human_message", ""),
            "Voyager curriculum human message",
            allow_empty=True,
        ),
        "completed_tasks": request.state.get("completed_tasks", ()),
        "failed_tasks": request.state.get("failed_tasks", ()),
        "max_parse_retries": VOYAGER_MINECRAFT_FIDELITY.critic_parse_max_retries,
    }


def _record_curriculum(request: MethodNodeRequest) -> MethodNodeResult:
    value = _mapping(
        request.previous_value,
        "Voyager curriculum agent result",
    )
    task = _text(value.get("task", value.get("next_task")), "Voyager task")
    return MethodNodeResult(
        value={"task": task},
        state_update={
            "current_task": task,
            "task_context": "",
            "pending_qa_question": "",
            "curriculum_sections": {},
            "curriculum_questions": (),
            "curriculum_answers": (),
            "curriculum_question_index": 0,
            "curriculum_human_message": "",
            "curriculum_random_receipt": None,
            "current_attempt": 0,
            "task_success": False,
            "critique": "",
            "chat_summary": "",
            "execution_errors": (),
        },
        next_node="task_context_lookup",
    )


def _task_context_question(task: str) -> str:
    normalized = (
        task.replace("_", " ")
        .replace(" ore", "")
        .replace(" ores", "")
        .replace(".", "")
        .strip()
        .lower()
    )
    return f"How to {normalized} in Minecraft?"


def _task_context_lookup(request: MethodNodeRequest) -> MethodNodeResult:
    task = _text(request.state.get("current_task"), "Voyager current_task")
    question = _task_context_question(task)
    child = _child_step(
        request,
        host_id=_QA_MEMORY_HOST,
        machine_suffix="voyager-curriculum-qa-memory",
        program_digest=VOYAGER_QA_MEMORY_PROGRAM.program_digest,
        initial_data=voyager_qa_memory_initial_data(),
        event_kind="voyager.qa.lookup",
        event_payload={
            "question": question,
            "allow_semantic": False,
        },
    )
    result = _child_result(child)
    if result.get("hit") is True:
        answer = _text(result.get("answer"), "Voyager cached QA answer")
        context = f"Question: {question}\n{answer}"
        next_node = "retrieve_skills"
        update = {
            "task_context": context,
            "pending_qa_question": "",
        }
    else:
        context = ""
        next_node = "qa_answer"
        update = {
            "task_context": "",
            "pending_qa_question": question,
        }
    return MethodNodeResult(
        value={
            "question": question,
            "cache_hit": result.get("hit") is True,
            "context": context,
        },
        state_update=update,
        next_node=next_node,
        child_links=(child.link,),
    )


def _qa_answer_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "question": _text(
            request.state.get("pending_qa_question"),
            "Voyager pending QA question",
        ),
        "role": "curriculum_qa_step2_answer_questions",
    }


def _qa_answer_text(value: JsonValue) -> str:
    if isinstance(value, str):
        return _text(value, "Voyager QA answer")
    decoded = _mapping(value, "Voyager QA agent result")
    return _text(
        decoded.get("answer", decoded.get("text")),
        "Voyager QA answer",
    )


def _record_qa_answer(request: MethodNodeRequest) -> MethodNodeResult:
    question = _text(
        request.state.get("pending_qa_question"),
        "Voyager pending QA question",
    )
    answer = _qa_answer_text(request.previous_value)
    child = _child_step(
        request,
        host_id=_QA_MEMORY_HOST,
        machine_suffix="voyager-curriculum-qa-memory",
        program_digest=VOYAGER_QA_MEMORY_PROGRAM.program_digest,
        initial_data=voyager_qa_memory_initial_data(),
        event_kind="voyager.qa.write",
        event_payload={
            "question": question,
            "answer": answer,
        },
    )
    result = _child_result(child)
    context = f"Question: {question}\n{answer}"
    return MethodNodeResult(
        value={
            "question": question,
            "answer": answer,
            "entry_digest": result.get("entry_digest"),
        },
        state_update={
            "task_context": context,
            "pending_qa_question": "",
        },
        next_node="retrieve_skills",
        child_links=(child.link,),
    )


def _skill_query(request: MethodNodeRequest) -> str:
    context = _text(
        request.state.get("task_context", ""),
        "Voyager task context",
        allow_empty=True,
    )
    attempt = _integer(
        request.state.get("current_attempt", 0),
        "Voyager current_attempt",
    )
    if attempt == 0:
        return context or _text(
            request.state.get("current_task"),
            "Voyager current_task",
        )
    summary = _text(
        request.state.get("chat_summary", ""),
        "Voyager chat_summary",
        allow_empty=True,
    )
    return context + ("\n\n" + summary if summary else "")


def _retrieve_skills(request: MethodNodeRequest) -> MethodNodeResult:
    child = _child_step(
        request,
        host_id=_SKILL_MEMORY_HOST,
        machine_suffix="voyager-skill-memory",
        program_digest=VOYAGER_SKILL_MEMORY_PROGRAM.program_digest,
        initial_data=voyager_skill_memory_initial_data(),
        event_kind="voyager.skill.retrieve",
        event_payload={
            "query": _skill_query(request),
            "limit": VOYAGER_MINECRAFT_FIDELITY.skill_retrieval_top_k,
        },
    )
    result = _child_result(child)
    return MethodNodeResult(
        value=result,
        state_update={
            "retrieved_skill_names": result.get("program_names", ()),
            "retrieved_skill_codes": result.get("program_codes", ()),
            "retrieved_skill_digests": result.get("skill_digests", ()),
        },
        next_node="action",
        child_links=(child.link,),
        events=(
            MethodEvent(
                "voyager.skills.retrieved",
                {
                    "query_digest": canonical_digest(_skill_query(request)),
                    "program_names": result.get("program_names", ()),
                    "retrieval_digest": result.get("retrieval_digest"),
                },
            ),
        ),
    )


def _action_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "task": request.state.get("current_task"),
        "context": request.state.get("task_context"),
        "retrieved_skill_names": request.state.get(
            "retrieved_skill_names",
            (),
        ),
        "retrieved_skill_codes": request.state.get(
            "retrieved_skill_codes",
            (),
        ),
        "code_from_last_round": request.state.get("program_code", ""),
        "world_observation": request.state.get("world_observation", {}),
        "execution_errors": request.state.get("execution_errors", ()),
        "chat_summary": request.state.get("chat_summary", ""),
        "chest_observation": request.state.get(
            "chest_observation",
            "Chests: None\n\n",
        ),
        "critique": request.state.get("critique", ""),
        "attempt": request.state.get("current_attempt", 0),
        "max_attempts": (
            VOYAGER_MINECRAFT_FIDELITY.action_task_max_retries
        ),
        "parser_retries": 3,
    }


def _action_candidate(value: JsonValue) -> tuple[JsonObject | None, str | None]:
    if isinstance(value, str):
        return None, value
    if not isinstance(value, Mapping):
        raise TypeError("Voyager action agent result must be text or object")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError("Voyager action result must decode to object")
    if "parse_error" in decoded:
        return None, _text(
            decoded.get("parse_error"),
            "Voyager action parse_error",
        )
    required = ("program_name", "program_code", "exec_code")
    if any(type(decoded.get(name)) is not str or not decoded.get(name) for name in required):
        raise ValueError(
            "Voyager action candidate requires program_name/program_code/exec_code"
        )
    return decoded, None


def _record_action(request: MethodNodeRequest) -> MethodNodeResult:
    candidate, error = _action_candidate(request.previous_value)
    if candidate is not None:
        return MethodNodeResult(
            value=candidate,
            state_update={
                "program_name": candidate["program_name"],
                "program_code": candidate["program_code"],
                "exec_code": candidate["exec_code"],
            },
            next_node="prepare_execute",
        )

    attempt = _integer(
        request.state.get("current_attempt", 0),
        "Voyager current_attempt",
    ) + 1
    iteration = _integer(
        request.state.get("action_iteration", 0),
        "Voyager action_iteration",
    ) + 1
    exhausted = (
        attempt
        >= VOYAGER_MINECRAFT_FIDELITY.action_task_max_retries
    )
    return MethodNodeResult(
        value={
            "parsed": False,
            "error": error,
            "attempt": attempt,
            "action_iteration": iteration,
        },
        state_update={
            "current_attempt": attempt,
            "action_iteration": iteration,
            "execution_errors": (error or "action_parse_error",),
            "task_success": False,
        },
        next_node="progress" if exhausted else "action",
        checkpoint=True,
        checkpoint_value={
            "task": request.state.get("current_task"),
            "attempt": attempt,
            "action_iteration": iteration,
            "parse_error": error,
        },
    )


def _prepare_execute(request: MethodNodeRequest) -> MethodNodeResult:
    task = _text(request.state.get("current_task"), "Voyager current_task")
    program_name = _text(
        request.state.get("program_name"),
        "Voyager program_name",
    )
    program_code = _text(
        request.state.get("program_code"),
        "Voyager program_code",
    )
    exec_code = _text(
        request.state.get("exec_code"),
        "Voyager exec_code",
    )
    skill_programs = _strings(
        request.state.get("retrieved_skill_codes", ()),
        "Voyager retrieved skill code",
    )
    parent_program_digests = _strings(
        request.state.get("retrieved_skill_digests", ()),
        "Voyager retrieved skill digest",
    )
    source_text = "\n\n".join((*skill_programs, program_code))
    return MethodNodeResult(
        value=program_execution_capability_payload(
            program_id=f"voyager.skill.{program_name}",
            source_text=source_text,
            language="javascript",
            entrypoint=program_name,
            interface_schema_id="voyager.mineflayer-program.v1",
            invocation={
                "task": task,
                "context": request.state.get("task_context", ""),
                "expression": exec_code,
                "reset_placed_if_failed": False,
            },
            parent_program_digests=parent_program_digests,
        )
    )


def _execution_mapping(value: JsonValue) -> dict[str, JsonValue]:
    decoded = _mapping(value, "Voyager program execution result")
    structured = decoded.get("result")
    if isinstance(structured, Mapping):
        return _mapping(structured, "Voyager structured program return")
    payload = decoded.get("payload")
    if isinstance(payload, Mapping):
        nested = _mapping(payload, "Voyager program execution payload")
        structured = nested.get("result")
        if isinstance(structured, Mapping):
            return _mapping(
                structured,
                "Voyager structured program return",
            )
        return nested
    return decoded


def _record_execution(request: MethodNodeRequest) -> MethodNodeResult:
    execution = _execution_mapping(request.previous_value)
    attempt = _integer(
        request.state.get("current_attempt", 0),
        "Voyager current_attempt",
    ) + 1
    iteration = _integer(
        request.state.get("action_iteration", 0),
        "Voyager action_iteration",
    ) + 1
    observation = execution.get(
        "observation",
        execution.get("events", execution),
    )
    chat_summary = execution.get("chat_summary", "")
    if type(chat_summary) is not str:
        chat_summary = str(chat_summary)
    raw_errors = execution.get("execution_errors", ())
    if isinstance(raw_errors, str):
        errors = (raw_errors,)
    elif isinstance(raw_errors, Sequence):
        errors = tuple(str(row) for row in raw_errors)
    else:
        errors = ()

    child_links = ()
    chest_observation = request.state.get(
        "chest_observation",
        "Chests: None\n\n",
    )
    chests = execution.get("nearby_chests")
    if isinstance(chests, Mapping):
        child = _child_step(
            request,
            host_id=_CHEST_MEMORY_HOST,
            machine_suffix="voyager-chest-memory",
            program_digest=VOYAGER_CHEST_MEMORY_PROGRAM.program_digest,
            initial_data=voyager_chest_memory_initial_data(),
            event_kind="voyager.chest.update",
            event_payload={"chests": dict(chests)},
        )
        chest_result = _child_result(child)
        chest_observation = chest_result.get(
            "rendered",
            chest_observation,
        )
        child_links = (child.link,)

    return MethodNodeResult(
        value={
            "attempt": attempt,
            "action_iteration": iteration,
            "world_observation": observation,
            "chat_summary": chat_summary,
            "execution_errors": errors,
        },
        state_update={
            "current_attempt": attempt,
            "action_iteration": iteration,
            "world_observation": observation,
            "chat_summary": chat_summary,
            "execution_errors": errors,
            "chest_observation": chest_observation,
            "last_execution": execution,
        },
        next_node="critic",
        child_links=child_links,
        checkpoint=True,
        checkpoint_value={
            "task": request.state.get("current_task"),
            "attempt": attempt,
            "action_iteration": iteration,
        },
    )


def _critic_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "task": request.state.get("current_task"),
        "context": request.state.get("task_context"),
        "world_observation": request.state.get("world_observation", {}),
        "chest_observation": request.state.get(
            "chest_observation",
            "Chests: None\n\n",
        ),
        "max_parse_retries": (
            VOYAGER_MINECRAFT_FIDELITY.critic_parse_max_retries
        ),
    }


def _record_critic(request: MethodNodeRequest) -> MethodNodeResult:
    value = _mapping(
        request.previous_value,
        "Voyager critic result",
    )
    success = value.get("success")
    if type(success) is not bool:
        raise TypeError("Voyager critic success must be boolean")
    critique = value.get("critique", "")
    if type(critique) is not str:
        raise TypeError("Voyager critic critique must be text")

    task = _text(request.state.get("current_task"), "Voyager current_task")
    attempt = _integer(
        request.state.get("current_attempt", 0),
        "Voyager current_attempt",
    )
    if success:
        next_node = "progress" if _is_deposit_task(task) else "write_skill"
    else:
        next_node = (
            "progress"
            if attempt
            >= VOYAGER_MINECRAFT_FIDELITY.action_task_max_retries
            else "retrieve_skills"
        )
    return MethodNodeResult(
        value={
            "success": success,
            "critique": critique,
            "attempt": attempt,
        },
        state_update={
            "task_success": success,
            "critique": critique,
        },
        next_node=next_node,
    )


def _write_skill(request: MethodNodeRequest) -> MethodNodeResult:
    child = _child_step(
        request,
        host_id=_SKILL_MEMORY_HOST,
        machine_suffix="voyager-skill-memory",
        program_digest=VOYAGER_SKILL_MEMORY_PROGRAM.program_digest,
        initial_data=voyager_skill_memory_initial_data(),
        event_kind="voyager.skill.write",
        event_payload={
            "program_name": _text(
                request.state.get("program_name"),
                "Voyager program_name",
            ),
            "program_code": _text(
                request.state.get("program_code"),
                "Voyager program_code",
            ),
        },
    )
    result = _child_result(child)
    return MethodNodeResult(
        value=result,
        state_update={
            "last_skill_write": result,
            "learned_skill_count": result.get(
                "active_skill_count",
                request.state.get("learned_skill_count", 0),
            ),
        },
        next_node="progress",
        child_links=(child.link,),
        events=(
            MethodEvent(
                "voyager.skill.learned",
                {
                    "program_name": result.get("program_name"),
                    "skill_digest": result.get("skill_digest"),
                    "revision": result.get("revision"),
                },
            ),
        ),
    )


def _clean_progress(
    completed: tuple[str, ...],
    failed: tuple[str, ...],
) -> tuple[tuple[str, ...], tuple[str, ...]]:
    dedup_completed: list[str] = []
    for task in completed:
        if task not in dedup_completed:
            dedup_completed.append(task)
    completed_set = set(dedup_completed)
    retained_failed = tuple(task for task in failed if task not in completed_set)
    return tuple(dedup_completed), retained_failed


def _progress(request: MethodNodeRequest) -> MethodNodeResult:
    task = _text(request.state.get("current_task"), "Voyager current_task")
    success = request.state.get("task_success") is True
    completed = list(
        _strings(
            request.state.get("completed_tasks", ()),
            "Voyager completed_tasks",
        )
    )
    failed = list(
        _strings(
            request.state.get("failed_tasks", ()),
            "Voyager failed_tasks",
        )
    )

    housekeeping = _is_deposit_task(task)
    if not housekeeping:
        if success:
            completed.append(task)
        else:
            failed.append(task)
    completed_tuple, failed_tuple = _clean_progress(
        tuple(completed),
        tuple(failed),
    )
    return MethodNodeResult(
        value={
            "task": task,
            "success": success,
            "housekeeping": housekeeping,
            "completed_tasks": completed_tuple,
            "failed_tasks": failed_tuple,
        },
        state_update={
            "completed_tasks": completed_tuple,
            "failed_tasks": failed_tuple,
            "current_task": "",
            "task_context": "",
            "pending_qa_question": "",
            "current_attempt": 0,
            "retrieved_skill_names": (),
            "retrieved_skill_codes": (),
            "retrieved_skill_digests": (),
            "program_name": "",
            "program_code": "",
            "exec_code": "",
            "critique": "",
            "chat_summary": "",
            "execution_errors": (),
            "task_success": False,
            "last_execution": {},
        },
        next_node="start_task",
        events=(
            MethodEvent(
                "voyager.curriculum.progress",
                {
                    "task": task,
                    "success": success,
                    "housekeeping": housekeeping,
                    "completed_task_count": len(completed_tuple),
                    "failed_task_count": len(failed_tuple),
                },
            ),
        ),
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "source_commit": VOYAGER_AUDITED_COMMIT,
            "completed_tasks": request.state.get("completed_tasks", ()),
            "failed_tasks": request.state.get("failed_tasks", ()),
            "action_iteration": request.state.get("action_iteration", 0),
            "learned_skill_count": request.state.get("learned_skill_count", 0),
            "skill_memory_program_digest": (
                VOYAGER_SKILL_MEMORY_PROGRAM.program_digest
            ),
            "chest_memory_program_digest": (
                VOYAGER_CHEST_MEMORY_PROGRAM.program_digest
            ),
            "qa_memory_program_digest": (
                VOYAGER_QA_MEMORY_PROGRAM.program_digest
            ),
            "skill_memory_machine_id": (
                None
                if request.parent_machine_id is None
                else f"{request.parent_machine_id}:voyager-skill-memory"
            ),
            "chest_memory_machine_id": (
                None
                if request.parent_machine_id is None
                else f"{request.parent_machine_id}:voyager-chest-memory"
            ),
            "qa_memory_machine_id": (
                None
                if request.parent_machine_id is None
                else (
                    f"{request.parent_machine_id}:"
                    "voyager-curriculum-qa-memory"
                )
            ),
        }
    )


def build_voyager_minecraft_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "source_commit": VOYAGER_AUDITED_COMMIT,
        "max_learning_iterations": (
            VOYAGER_MINECRAFT_FIDELITY.max_learning_iterations
        ),
        "action_task_max_retries": (
            VOYAGER_MINECRAFT_FIDELITY.action_task_max_retries
        ),
        "critic_parse_max_retries": (
            VOYAGER_MINECRAFT_FIDELITY.critic_parse_max_retries
        ),
        "skill_retrieval_top_k": (
            VOYAGER_MINECRAFT_FIDELITY.skill_retrieval_top_k
        ),
        "first_task": _INITIAL_TASK,
        "inventory_housekeeping_threshold": 33,
        "skill_memory_program_digest": (
            VOYAGER_SKILL_MEMORY_PROGRAM.program_digest
        ),
        "chest_memory_program_digest": (
            VOYAGER_CHEST_MEMORY_PROGRAM.program_digest
        ),
        "qa_memory_program_digest": (
            VOYAGER_QA_MEMORY_PROGRAM.program_digest
        ),
        "program_execution_capability": _PROGRAM_EXECUTION_CAPABILITY,
        "curriculum_random_capability": _CURRICULUM_RANDOM_CAPABILITY,
        "curriculum_semantics_digest": (
            voyager_curriculum_semantics_digest()
        ),
        "curriculum_context_warmup": (
            VOYAGER_CURRICULUM_DEFAULT_WARMUP["context"]
        ),
        "curriculum_random_inclusion_probability": 0.8,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="voyager-minecraft",
            implementation_version=VOYAGER_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="voyager.minecraft.method.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="start_task")
    builder.route(
        "start_task",
        "voyager.curriculum.route",
        _start_task,
        (
            "prepare_curriculum",
            "retrieve_skills",
            "return",
        ),
        max_visits=512,
    )
    builder.route(
        "prepare_curriculum",
        "voyager.curriculum.prepare",
        _prepare_curriculum,
        (
            "curriculum_qa_questions",
            "prepare_curriculum_random",
        ),
        max_visits=512,
    )
    builder.agent(
        "curriculum_qa_questions",
        "voyager.curriculum.qa-questions",
        _CURRICULUM_QA_QUESTION_AGENT,
        ("record_curriculum_qa_questions",),
        view_handler=_curriculum_qa_questions_view,
        max_visits=512,
    )
    builder.compute(
        "record_curriculum_qa_questions",
        "voyager.curriculum.qa-questions-record",
        _record_curriculum_qa_questions,
        ("curriculum_qa_lookup",),
        max_visits=512,
    )
    builder.route(
        "curriculum_qa_lookup",
        "voyager.curriculum.qa-enrichment-cache",
        _curriculum_qa_lookup,
        (
            "curriculum_qa_lookup",
            "curriculum_qa_answer",
            "prepare_curriculum_random",
        ),
        max_visits=8192,
    )
    builder.agent(
        "curriculum_qa_answer",
        "voyager.curriculum.qa-enrichment-answer",
        _QA_AGENT,
        ("record_curriculum_qa_answer",),
        view_handler=_qa_answer_view,
        max_visits=8192,
    )
    builder.compute(
        "record_curriculum_qa_answer",
        "voyager.curriculum.qa-enrichment-record",
        _record_curriculum_qa_answer,
        ("curriculum_qa_lookup",),
        max_visits=8192,
    )
    builder.compute(
        "prepare_curriculum_random",
        "voyager.curriculum.random-mask-prepare",
        _prepare_curriculum_random,
        ("curriculum_random",),
        max_visits=512,
    )
    builder.capability(
        "curriculum_random",
        "voyager.curriculum.random-mask",
        _CURRICULUM_RANDOM_CAPABILITY,
        ("record_curriculum_random",),
        effect_class=EffectClass.PURE,
        max_visits=512,
        evidence_obligations=(
            "voyager.curriculum.random-receipt",
        ),
    )
    builder.compute(
        "record_curriculum_random",
        "voyager.curriculum.random-mask-record",
        _record_curriculum_random,
        ("curriculum",),
        max_visits=512,
    )
    builder.agent(
        "curriculum",
        "voyager.curriculum.propose",
        _CURRICULUM_AGENT,
        ("record_curriculum",),
        view_handler=_curriculum_view,
        max_visits=512,
    )
    builder.compute(
        "record_curriculum",
        "voyager.curriculum.record",
        _record_curriculum,
        ("task_context_lookup",),
        max_visits=512,
    )
    builder.route(
        "task_context_lookup",
        "voyager.curriculum.task-context-cache",
        _task_context_lookup,
        ("qa_answer", "retrieve_skills"),
        max_visits=512,
    )
    builder.agent(
        "qa_answer",
        "voyager.curriculum.qa-answer",
        _QA_AGENT,
        ("record_qa_answer",),
        view_handler=_qa_answer_view,
        max_visits=512,
    )
    builder.compute(
        "record_qa_answer",
        "voyager.curriculum.qa-record",
        _record_qa_answer,
        ("retrieve_skills",),
        max_visits=512,
    )
    builder.compute(
        "retrieve_skills",
        "voyager.skill-memory.retrieve",
        _retrieve_skills,
        ("action",),
        max_visits=1024,
    )
    builder.agent(
        "action",
        "voyager.action.generate",
        _ACTION_AGENT,
        ("record_action",),
        view_handler=_action_view,
        max_visits=1024,
    )
    builder.route(
        "record_action",
        "voyager.action.record",
        _record_action,
        ("action", "prepare_execute", "progress"),
        max_visits=1024,
    )
    builder.compute(
        "prepare_execute",
        "voyager.minecraft.prepare-program",
        _prepare_execute,
        ("execute_program",),
        max_visits=1024,
    )
    builder.capability(
        "execute_program",
        "voyager.minecraft.execute-program",
        _PROGRAM_EXECUTION_CAPABILITY,
        ("record_execution",),
        effect_class=EffectClass.RECONCILABLE,
        max_visits=1024,
        evidence_obligations=("minecraft.program-effect",),
    )
    builder.compute(
        "record_execution",
        "voyager.minecraft.record-program",
        _record_execution,
        ("critic",),
        max_visits=1024,
        evidence_obligations=("minecraft.observation",),
    )
    builder.agent(
        "critic",
        "voyager.critic.verify",
        _CRITIC_AGENT,
        ("record_critic",),
        view_handler=_critic_view,
        max_visits=1024,
    )
    builder.route(
        "record_critic",
        "voyager.critic.record",
        _record_critic,
        ("retrieve_skills", "write_skill", "progress"),
        max_visits=1024,
    )
    builder.compute(
        "write_skill",
        "voyager.skill-memory.write",
        _write_skill,
        ("progress",),
        max_visits=512,
    )
    builder.compute(
        "progress",
        "voyager.curriculum.progress",
        _progress,
        ("start_task",),
        max_visits=512,
    )
    builder.return_node(
        "return",
        "voyager.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(
            _CURRICULUM_RANDOM_CAPABILITY,
            _PROGRAM_EXECUTION_CAPABILITY,
        ),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "voyager.curriculum",
            "voyager.curriculum.random-receipt",
            "voyager.skill-memory.child-cuts",
            "voyager.chest-memory.child-cuts",
            "voyager.curriculum-qa-memory.child-cuts",
            "minecraft.program-effect",
            "minecraft.observation",
            "voyager.critic-verdict",
        ),
        metric_names=(
            "action_iteration",
            "completed_task_count",
            "failed_task_count",
            "learned_skill_count",
        ),
        artifact_kinds=(
            "voyager_skill_program",
            "voyager_minecraft_trajectory",
        ),
    )


VOYAGER_MINECRAFT_METHOD_PROGRAM = build_voyager_minecraft_method_program()


__all__ = [
    "VOYAGER_MINECRAFT_METHOD_PROGRAM",
    "build_voyager_minecraft_method_program",
    "voyager_minecraft_initial_state",
]
