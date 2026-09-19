from __future__ import annotations

from collections.abc import Mapping

from noetrium_platform.capabilities.participant.method.api import (
    MethodIdentity,
    MethodProgramIdentity,
)
from noetrium_platform.foundation.kernel.kernel import (
    EffectClass,
    JsonObject,
    JsonValue,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

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


def _product_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "role": "ProductManager",
        "action": "WritePRD",
        "watch": "BossRequirement",
        "requirement": request.state["requirement"],
        "philosophy": METAGPT_SOFTWARE_COMPANY_FIDELITY.philosophy,
    }


def _record_prd(request: MethodNodeRequest) -> MethodNodeResult:
    prd = _agent_text(request.previous_value, "prd")
    return MethodNodeResult(
        value={
            "artifact_type": "software.prd",
            "media_type": "text/plain",
            "content": prd,
        },
        state_update={"prd": prd},
    )


def _architect_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "role": "Architect",
        "action": "WriteDesign",
        "watch": "WritePRD",
        "requirement": request.state["requirement"],
        "prd": request.state["prd"],
    }


def _record_design(request: MethodNodeRequest) -> MethodNodeResult:
    design = _agent_text(request.previous_value, "design")
    return MethodNodeResult(
        value={
            "artifact_type": "software.design",
            "media_type": "text/plain",
            "content": design,
        },
        state_update={"design": design},
    )


def _project_manager_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "role": "ProjectManager",
        "action": "WriteTasks",
        "watch": "WriteDesign",
        "requirement": request.state["requirement"],
        "prd": request.state["prd"],
        "design": request.state["design"],
    }


def _record_tasks(request: MethodNodeRequest) -> MethodNodeResult:
    tasks = _agent_text(request.previous_value, "tasks")
    return MethodNodeResult(
        value={
            "artifact_type": "software.tasks",
            "media_type": "text/plain",
            "content": tasks,
        },
        state_update={"tasks": tasks},
    )


def _engineer_view(request: MethodNodeRequest) -> JsonObject:
    return {
        "role": "Engineer",
        "action": "WriteCode",
        "watch": "WriteTasks",
        "requirement": request.state["requirement"],
        "design": request.state["design"],
        "tasks": request.state["tasks"],
        "existing_code": request.state.get("code", ""),
    }


def _record_code_to_publish(request: MethodNodeRequest) -> MethodNodeResult:
    code = _agent_text(request.previous_value, "code")
    return MethodNodeResult(
        value={"code": code},
        state_update={"code": code},
        next_node="prepare_code_publish",
    )


def _record_code_to_review(request: MethodNodeRequest) -> MethodNodeResult:
    code = _agent_text(request.previous_value, "code")
    return MethodNodeResult(
        value={"code": code},
        state_update={"code": code},
        next_node="review",
    )


def _review_view(request: MethodNodeRequest) -> JsonObject:
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


def _record_review(request: MethodNodeRequest) -> MethodNodeResult:
    code = _agent_text(request.previous_value, "code")
    return MethodNodeResult(
        value={"code": code},
        state_update={"code": code},
        next_node="prepare_code_publish",
    )


def _prepare_code_publish(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "artifact_type": "software.code",
            "media_type": "text/plain",
            "content": _text(request.state.get("code"), "code"),
        }
    )


def _record_artifact(request: MethodNodeRequest) -> MethodNodeResult:
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
    return MethodNodeResult(
        value=row,
        state_update={"artifacts": artifacts},
        checkpoint=True,
        checkpoint_value=row,
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    return MethodNodeResult(
        value={
            "task_id": request.state["task_id"],
            "code": request.state["code"],
            "artifact_receipts": request.state["artifacts"],
            "artifact_count": len(request.state["artifacts"]),
        }
    )


def build_metagpt_software_company_method_program(
    *,
    use_code_review: bool = False,
) -> MethodProgram:
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
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="metagpt",
            implementation_version=fidelity.audited_commit[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="metagpt.software-company.sop.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="product_manager")
    builder.agent(
        "product_manager",
        "metagpt.sop.write-prd",
        _PRODUCT_MANAGER,
        ("prepare_prd",),
        view_handler=_product_view,
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
        effect_class=EffectClass.IDEMPOTENT,
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
        view_handler=_architect_view,
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
        effect_class=EffectClass.IDEMPOTENT,
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
        view_handler=_project_manager_view,
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
        effect_class=EffectClass.IDEMPOTENT,
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
        view_handler=_engineer_view,
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
            view_handler=_review_view,
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
        effect_class=EffectClass.IDEMPOTENT,
    )
    builder.compute(
        "record_code_artifact",
        "metagpt.artifact.record-code",
        _record_artifact,
        ("return",),
    )
    builder.return_node("return", "metagpt.result", _return_result)
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ARTIFACT_CAPABILITY,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "metagpt.sop-trajectory",
            "metagpt.artifact-lineage",
        ),
        metric_names=("task_success", "artifact_count", "model_call_count"),
        artifact_kinds=(
            "software.prd",
            "software.design",
            "software.tasks",
            "software.code",
        ),
    )


__all__ = [
    "build_metagpt_software_company_method_program",
    "metagpt_initial_state",
]
