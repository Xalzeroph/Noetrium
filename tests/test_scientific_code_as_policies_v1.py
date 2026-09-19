from __future__ import annotations

import pytest

from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    canonical_digest,
)
from noetrium_platform.research.execution.workflow.api import MethodAgentRequest
from noetrium_platform.research.reproduction import ReproductionAssetKind

from research.reproductions.code_as_policies import (
    CODE_AS_POLICIES_FIDELITY,
    CODE_AS_POLICIES_METHOD_PROGRAM,
    CodeAsPoliciesGeneration,
    CodeAsPoliciesGenerationKind,
    CodeAsPoliciesHierarchicalSynthesisAgentLoop,
    REPRODUCTION,
    SYNTHESIS_AGENT_ID,
    discover_function_calls,
)


class _Generator:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "generator": "code-as-policies-test",
            "implementation_revision": 1,
        })

    def generate(self, request, context):
        del context
        if request.kind is CodeAsPoliciesGenerationKind.POLICY:
            return CodeAsPoliciesGeneration(
                "result = outer(x)",
                {"kind": "policy"},
            )
        if request.function_name == "outer":
            return CodeAsPoliciesGeneration(
                "def outer(x):\n"
                "    return inner(x) + api(x)",
                {"kind": "function", "name": "outer"},
            )
        if request.function_name == "inner":
            return CodeAsPoliciesGeneration(
                "def inner(x):\n"
                "    return x * 2",
                {"kind": "function", "name": "inner"},
            )
        raise AssertionError(request.function_name)


class _CycleGenerator:
    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "generator": "code-as-policies-cycle-test",
            "implementation_revision": 1,
        })

    def generate(self, request, context):
        del context
        if request.kind is CodeAsPoliciesGenerationKind.POLICY:
            return CodeAsPoliciesGeneration("outer(x)")
        return CodeAsPoliciesGeneration(
            "def outer(x):\n"
            "    return outer(x - 1)"
        )


def _context() -> ExecutionContext:
    return ExecutionContext(
        run_id="cap-test-run",
        trace_id="cap-test-trace",
        span_id="cap-test-span",
        task_id="cap-test-task",
    )


def test_function_parser_preserves_assignment_signature_override() -> None:
    calls = discover_function_calls(
        "plain(x)\n"
        "value = assigned(x, y=2)\n"
        "obj.method(x)\n"
    )
    assert tuple(item.function_name for item in calls) == (
        "plain",
        "assigned",
    )
    assert calls[0].signature == "plain(x)"
    assert calls[0].assignment_signature is False
    assert calls[1].signature == "value = assigned(x, y=2)"
    assert calls[1].assignment_signature is True


def test_hierarchical_synthesis_generates_children_before_parent_bundle() -> None:
    loop = CodeAsPoliciesHierarchicalSynthesisAgentLoop(_Generator())
    result = loop.run(MethodAgentRequest(
        agent_id=SYNTHESIS_AGENT_ID,
        goal=None,
        view={
            "query": "do the task",
            "context": "x = 3",
            "known_names": ("api",),
        },
        input_value=None,
        previous_value=None,
        context=_context(),
    ))

    helpers = result.state_update["helper_sources"]
    assert tuple(row["function_name"] for row in helpers) == (
        "inner",
        "outer",
    )
    assert helpers[0]["parent_function"] == "outer"
    assert helpers[1]["parent_function"] is None

    receipts = result.state_update["generation_receipts"]
    assert tuple(row["function_name"] for row in receipts) == (
        None,
        "outer",
        "inner",
    )
    assert result.state_update["synthesis_complete"] is True
    assert len(result.state_update["synthesis_bundle_digest"]) == 64


def test_hierarchical_synthesis_fails_closed_on_recursive_cycle() -> None:
    loop = CodeAsPoliciesHierarchicalSynthesisAgentLoop(_CycleGenerator())
    with pytest.raises(RuntimeError, match="cyclic helper dependency"):
        loop.run(MethodAgentRequest(
            agent_id=SYNTHESIS_AGENT_ID,
            goal=None,
            view={
                "query": "recursive task",
                "context": "",
                "known_names": (),
            },
            input_value=None,
            previous_value=None,
            context=_context(),
        ))


def test_code_as_policies_fidelity_does_not_call_exec_safe_a_sandbox() -> None:
    fidelity = CODE_AS_POLICIES_FIDELITY
    assert fidelity.hierarchical_code_generation is True
    assert fidelity.direct_name_calls_only is True
    assert fidelity.assignment_overrides_call_signature is True
    assert fidelity.original_exec_banned_phrases == ("import", "__")
    assert fidelity.original_exec_shadows == ("exec", "eval")
    assert fidelity.original_exec_is_qualified_sandbox is False
    assert fidelity.post_paper_chain_of_code_included is False
    assert fidelity.post_paper_lmpc_included is False


def test_code_as_policies_method_program_uses_environment_effect_authority() -> None:
    program = CODE_AS_POLICIES_METHOD_PROGRAM
    node_ids = tuple(node.node_id for node in program.nodes)
    assert node_ids == (
        "synthesize",
        "prepare_execute",
        "execute_policy",
        "record_execution",
        "return",
    )
    assert program.required_capabilities == ("environment.act",)
    assert "code-as-policies.generation-receipts" in program.evidence_obligations
    assert "environment.effect" in program.evidence_obligations


def test_code_as_policies_reproduction_records_sandbox_gap_explicitly() -> None:
    assert REPRODUCTION.lifecycle.value == "protocol_bound"
    kinds = tuple(asset.kind for asset in REPRODUCTION.assets)
    assert ReproductionAssetKind("method_program") in kinds
    assert ReproductionAssetKind("semantics") in kinds
    assert any(
        "exec_safe" in delta.description
        and "qualified isolated environment provider" in delta.description
        for delta in REPRODUCTION.deltas
    )
