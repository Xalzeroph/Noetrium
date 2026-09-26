from __future__ import annotations

from research.reproductions._support import (
    JsonObject,
    JsonValue,
    MethodCall,
    canonical_digest,
    freeze_json,
    method_event,
    require_sha256,
    thaw_json,
)
from research.reproductions._support import JsonObject, JsonValue, canonical_digest

from collections.abc import Mapping





from .fidelity import METAGPT_SOFTWARE_COMPANY_FIDELITY

_ARTIFACT_CAPABILITY = "artifact.publish"
_PRODUCT_MANAGER = "metagpt.product-manager"
_ARCHITECT = "metagpt.architect"
_PROJECT_MANAGER = "metagpt.project-manager"
_ENGINEER = "metagpt.engineer"


def _text(value: object, field: str, *, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or (not allow_empty and not value.strip()):
        raise ValueError(f"MetaGPT {field} must be text")
    return value


def metagpt_initial_state(*, task_id: str, requirement: str) -> JsonObject:
    return {
        "task_id": _text(task_id, "task_id"),
        "requirement": _text(requirement, "requirement"),
        "prd": "",
        "design": "",
        "tasks": "",
        "code": "",
        "artifacts": (),
    }


def _agent_text(value: JsonValue, field: str) -> str:
    if isinstance(value, str):
        return _text(value, field)
    if isinstance(value, Mapping):
        for key in (field, "content", "text", "output"):
            candidate = value.get(key)
            if isinstance(candidate, str) and candidate.strip():
                return candidate
    raise TypeError(f"MetaGPT agent result must contain {field} text")


def _product_view(request: MethodCall) -> JsonObject:
    return {
        "role": "ProductManager",
        "action": "WritePRD",
        "watch": "BossRequirement",
        "requirement": request.state["requirement"],
        "philosophy": METAGPT_SOFTWARE_COMPANY_FIDELITY.philosophy,
    }


def _record_prd(request: MethodCall) -> MethodNodeResult:
    prd = _agent_text(request.previous_value, "prd")
    return dict(
        value={
            "artifact_type": "software.prd",
            "media_type": "text/plain",
            "content": prd,
        },
        state_update={"prd": prd},
    )


def _architect_view(request: MethodCall) -> JsonObject:
    return {
        "role": "Architect",
        "action": "WriteDesign",
        "watch": "WritePRD",
        "requirement": request.state["requirement"],
        "prd": request.state["prd"],
    }


def _record_design(request: MethodCall) -> MethodNodeResult:
    design = _agent_text(request.previous_value, "design")
    return dict(
        value={
            "artifact_type": "software.design",
            "media_type": "text/plain",
            "content": design,
        },
        state_update={"design": design},
    )


def _project_manager_view(request: MethodCall) -> JsonObject:
    return {
        "role": "ProjectManager",
        "action": "WriteTasks",
        "watch": "WriteDesign",
        "requirement": request.state["requirement"],
        "prd": request.state["prd"],
        "design": request.state["design"],
    }


def _record_tasks(request: MethodCall) -> MethodNodeResult:
    tasks = _agent_text(request.previous_value, "tasks")
    return dict(
        value={
            "artifact_type": "software.tasks",
            "media_type": "text/plain",
            "content": tasks,
        },
        state_update={"tasks": tasks},
    )


def _engineer_view(request: MethodCall) -> JsonObject:
    return {
        "role": "Engineer",
        "action": "WriteCode",
        "watch": "WriteTasks",
        "requirement": request.state["requirement"],
        "design": request.state["design"],
        "tasks": request.state["tasks"],
        "existing_code": request.state.get("code", ""),
    }


def _record_code_to_publish(request: MethodCall) -> MethodNodeResult:
    code = _agent_text(request.previous_value, "code")
    return dict(
        value={"code": code},
        state_update={"code": code},
        next_node="prepare_code_publish",
    )


def _record_code_to_review(request: MethodCall) -> MethodNodeResult:
    code = _agent_text(request.previous_value, "code")
    return dict(
        value={"code": code},
        state_update={"code": code},
        next_node="review",
    )


def _review_view(request: MethodCall) -> JsonObject:
    return {
        "role": "Engineer",
        "action": "WriteCodeReview",
        "requirement": request.state["requirement"],
        "design": request.state["design"],
        "tasks": request.state["tasks"],
        "code": request.state["code"],
        "review_checks": (
            "requirements",
            "logic",
            "design-conformance",
            "omissions",
            "dependencies",
        ),
    }


def _record_review(request: MethodCall) -> MethodNodeResult:
    code = _agent_text(request.previous_value, "code")
    return dict(
        value={"code": code},
        state_update={"code": code},
        next_node="prepare_code_publish",
    )


def _prepare_code_publish(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "artifact_type": "software.code",
            "media_type": "text/plain",
            "content": _text(request.state.get("code"), "code"),
        }
    )


def _record_artifact(request: MethodCall) -> MethodNodeResult:
    value = request.previous_value
    if not isinstance(value, Mapping):
        raise TypeError("MetaGPT artifact publication receipt must be a mapping")
    artifact_ref = _text(value.get("artifact_ref"), "artifact_ref")
    generation = _text(value.get("generation"), "artifact generation")
    content_sha256 = _text(value.get("content_sha256"), "artifact content digest")
    artifact_type = _text(value.get("artifact_type"), "artifact_type")
    row = {
        "artifact_type": artifact_type,
        "artifact_ref": artifact_ref,
        "generation": generation,
        "content_sha256": content_sha256,
    }
    artifacts = (*request.state.get("artifacts", ()), row)
    return dict(
        value=row,
        state_update={"artifacts": artifacts},
        checkpoint=True,
        checkpoint_value=row,
    )


def _return_result(request: MethodCall) -> MethodNodeResult:
    return dict(
        value={
            "task_id": request.state["task_id"],
            "code": request.state["code"],
            "artifact_receipts": request.state["artifacts"],
            "artifact_count": len(request.state["artifacts"]),
        }
    )


def build_metagpt_software_company_method_program(method,
    *,
    use_code_review: bool = False,
) -> None:
    if type(use_code_review) is not bool:
        raise TypeError("MetaGPT use_code_review must be boolean")
    fidelity = METAGPT_SOFTWARE_COMPANY_FIDELITY
    configuration: JsonObject = {
        "source_commit": fidelity.audited_commit,
        "philosophy": fidelity.philosophy,
        "core_roles": fidelity.core_roles,
        "sop_edges": fidelity.sop_edges,
        "default_round_budget": fidelity.default_round_budget,
        "use_code_review": use_code_review,
    }

    builder = method
    builder.agent(
        "product_manager",
        "metagpt.sop.write-prd",
        _PRODUCT_MANAGER,
        ("prepare_prd",),
        view=_product_view,
    )
    builder.compute(
        "prepare_prd",
        "metagpt.artifact.prepare-prd",
        _record_prd,
        ("publish_prd",),
    )
    builder.capability(
        "publish_prd",
        "metagpt.artifact.publish-prd",
        _ARTIFACT_CAPABILITY,
        ("record_prd_artifact",),
        effect='idempotent',
    )
    builder.compute(
        "record_prd_artifact",
        "metagpt.artifact.record-prd",
        _record_artifact,
        ("architect",),
    )
    builder.agent(
        "architect",
        "metagpt.sop.write-design",
        _ARCHITECT,
        ("prepare_design",),
        view=_architect_view,
    )
    builder.compute(
        "prepare_design",
        "metagpt.artifact.prepare-design",
        _record_design,
        ("publish_design",),
    )
    builder.capability(
        "publish_design",
        "metagpt.artifact.publish-design",
        _ARTIFACT_CAPABILITY,
        ("record_design_artifact",),
        effect='idempotent',
    )
    builder.compute(
        "record_design_artifact",
        "metagpt.artifact.record-design",
        _record_artifact,
        ("project_manager",),
    )
    builder.agent(
        "project_manager",
        "metagpt.sop.write-tasks",
        _PROJECT_MANAGER,
        ("prepare_tasks",),
        view=_project_manager_view,
    )
    builder.compute(
        "prepare_tasks",
        "metagpt.artifact.prepare-tasks",
        _record_tasks,
        ("publish_tasks",),
    )
    builder.capability(
        "publish_tasks",
        "metagpt.artifact.publish-tasks",
        _ARTIFACT_CAPABILITY,
        ("record_tasks_artifact",),
        effect='idempotent',
    )
    builder.compute(
        "record_tasks_artifact",
        "metagpt.artifact.record-tasks",
        _record_artifact,
        ("engineer",),
    )
    builder.agent(
        "engineer",
        "metagpt.sop.write-code",
        _ENGINEER,
        ("record_code",),
        view=_engineer_view,
    )
    if use_code_review:
        builder.route(
            "record_code",
            "metagpt.code.record",
            _record_code_to_review,
            ("review",),
        )
        # Same Engineer role, matching paper-era source where WriteCodeReview is
        # an optional second Engineer action rather than a fifth collaboration role.
        builder.agent(
            "review",
            "metagpt.sop.write-code-review",
            _ENGINEER,
            ("record_review",),
            view=_review_view,
        )
        builder.route(
            "record_review",
            "metagpt.code.record-review",
            _record_review,
            ("prepare_code_publish",),
        )
    else:
        builder.route(
            "record_code",
            "metagpt.code.record",
            _record_code_to_publish,
            ("prepare_code_publish",),
        )

    builder.compute(
        "prepare_code_publish",
        "metagpt.artifact.prepare-code",
        _prepare_code_publish,
        ("publish_code",),
    )
    builder.capability(
        "publish_code",
        "metagpt.artifact.publish-code",
        _ARTIFACT_CAPABILITY,
        ("record_code_artifact",),
        effect='idempotent',
    )
    builder.compute(
        "record_code_artifact",
        "metagpt.artifact.record-code",
        _record_artifact,
        ("return",),
    )
    builder.return_node("return", "metagpt.result", _return_result)
    builder.configure(configuration)
    builder.requires(*(_ARTIFACT_CAPABILITY,))
    builder.policy(
        execution='effect_recorded',
        evidence=(
            "metagpt.sop-trajectory",
            "metagpt.artifact-lineage",
        ),
        metrics=("task_success", "artifact_count", "model_call_count"),
        artifacts=(
            "software.prd",
            "software.design",
            "software.tasks",
            "software.code",
        ),
    )
    return builder


METHOD_CONFIGURER = build_metagpt_software_company_method_program
METHOD_ENTRYPOINT = "product_manager"
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = [
    'build_metagpt_software_company_method_program',
    'metagpt_initial_state',
    'METHOD_CONFIGURER',
    'METHOD_ENTRYPOINT',
    'METHOD_CONFIGURER_ARGS',
    'METHOD_CONFIGURER_KWARGS',
]
