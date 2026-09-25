from __future__ import annotations

import hashlib

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
)
from noetrium_platform.foundation.kernel.kernel import EffectClass, ExecutionContext
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
    MethodRuntimeContext,
    MethodRunStatus,
)
from noetrium_platform.research.execution.workflow.runtime import UniversalMethodMachine
from research.reproductions.metagpt_software_company import (
    build_metagpt_software_company_method_program,
    metagpt_initial_state,
)


class _Artifacts:
    def __init__(self) -> None:
        self.published = []

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        assert capability_id == "artifact.publish"
        return CapabilityDescriptor(
            capability_id, "1", "json", "json", EffectClass.IDEMPOTENT, True
        )

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        assert request.capability_id == "artifact.publish"
        artifact_type = request.payload["artifact_type"]
        content = request.payload["content"]
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        row = {
            "artifact_type": artifact_type,
            "artifact_ref": f"method-artifacts/{artifact_type}/{digest}.txt",
            "generation": hashlib.sha256(
                f"{artifact_type}:{digest}".encode("utf-8")
            ).hexdigest(),
            "content_sha256": digest,
            "byte_size": len(content.encode("utf-8")),
        }
        self.published.append((artifact_type, content))
        return CapabilityResult(
            request.capability_id,
            row,
            generation=row["generation"],
            artifacts=(row["artifact_ref"],),
        )


class _SoftwareCompany:
    def __init__(self, *, review: bool) -> None:
        self.review = review
        self.calls = []

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        self.calls.append((request.agent_id, request.view["action"]))
        action = request.view["action"]
        if action == "WritePRD":
            assert request.view["watch"] == "BossRequirement"
            return MethodAgentResult(value={"prd": "PRD: calculator"})
        if action == "WriteDesign":
            assert request.view["prd"] == "PRD: calculator"
            return MethodAgentResult(value={"design": "Design: one function"})
        if action == "WriteTasks":
            assert request.view["design"] == "Design: one function"
            return MethodAgentResult(value={"tasks": "Tasks: implement add"})
        if action == "WriteCode":
            assert request.view["tasks"] == "Tasks: implement add"
            return MethodAgentResult(value={"code": "def add(a, b): return a - b"})
        assert action == "WriteCodeReview"
        assert self.review is True
        assert request.view["code"] == "def add(a, b): return a - b"
        return MethodAgentResult(value={"code": "def add(a, b): return a + b"})


def _run(*, review: bool):
    capabilities = _Artifacts()
    agents = _SoftwareCompany(review=review)
    program = build_metagpt_software_company_method_program(use_code_review=review)
    result = UniversalMethodMachine(max_steps=64).run(
        program,
        runtime=MethodRuntimeContext(
            ExecutionContext("metagpt-run", "trace", "span", task_id="HumanEval/0"),
            capabilities=capabilities,
            agent_loop=agents,
        ),
        initial_state=metagpt_initial_state(
            task_id="HumanEval/0",
            requirement="Implement add(a, b).",
        ),
    )
    return program, result, capabilities, agents


def test_metagpt_core_sop_publishes_role_artifacts_in_dependency_order() -> None:
    program, result, capabilities, agents = _run(review=False)
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["code"] == "def add(a, b): return a - b"
    assert result.value["artifact_count"] == 4
    assert [row[0] for row in capabilities.published] == [
        "software.prd",
        "software.design",
        "software.tasks",
        "software.code",
    ]
    assert agents.calls == [
        ("metagpt.product-manager", "WritePRD"),
        ("metagpt.architect", "WriteDesign"),
        ("metagpt.project-manager", "WriteTasks"),
        ("metagpt.engineer", "WriteCode"),
    ]
    assert program.required_capabilities == ("artifact.publish",)


def test_metagpt_code_review_is_same_engineer_role_and_changes_program_identity() -> None:
    core, _, _, _ = _run(review=False)
    reviewed, result, capabilities, agents = _run(review=True)
    assert reviewed.program_digest != core.program_digest
    assert result.status is MethodRunStatus.SUCCEEDED
    assert result.value["code"] == "def add(a, b): return a + b"
    assert capabilities.published[-1] == (
        "software.code",
        "def add(a, b): return a + b",
    )
    assert agents.calls[-2:] == [
        ("metagpt.engineer", "WriteCode"),
        ("metagpt.engineer", "WriteCodeReview"),
    ]
