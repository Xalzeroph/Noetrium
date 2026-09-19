from __future__ import annotations

from collections.abc import Mapping, Sequence

from noetrium_platform.capabilities.environment.composition import (
    environment_action_capability_payload,
)
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
from noetrium_platform.research.execution.workflow.api import (
    MethodExecutionClass,
    MethodNodeRequest,
    MethodNodeResult,
    MethodProgram,
    MethodProgramBuilder,
)

from .fidelity import CODE_AS_POLICIES_FIDELITY
from .hierarchy import SYNTHESIS_AGENT_ID
from .source import CODE_AS_POLICIES_AUDITED_COMMIT


_ENVIRONMENT_CAPABILITY_ID = "environment.act"
_POLICY_PROGRAM_ACTION = "embodied_policy_program"


def _text(value: object, field_name: str, *, allow_empty: bool = False) -> str:
    if type(value) is not str:
        raise TypeError(f"{field_name} must be text")
    if not allow_empty and not value.strip():
        raise ValueError(f"{field_name} must be non-empty")
    return value


def _strings(value: object, field_name: str) -> tuple[str, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a sequence")
    rows = tuple(_text(item, field_name) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field_name} must contain unique values")
    return rows


def code_as_policies_initial_state(
    *,
    query: str,
    context: str = "",
    known_names: tuple[str, ...] = (),
    api_bindings: tuple[str, ...] = (),
) -> JsonObject:
    return {
        "source_commit": CODE_AS_POLICIES_AUDITED_COMMIT,
        "query": _text(query, "Code as Policies query"),
        "context": _text(
            context,
            "Code as Policies context",
            allow_empty=True,
        ),
        "known_names": _strings(
            known_names,
            "Code as Policies known_names",
        ),
        "api_bindings": _strings(
            api_bindings,
            "Code as Policies api_bindings",
        ),
        "policy_source": "",
        "helper_sources": (),
        "generation_receipts": (),
        "synthesis_bundle_digest": None,
        "synthesis_complete": False,
        "execution_result": None,
    }


def _synthesis_view(request: MethodNodeRequest) -> JsonObject:
    if request.state.get("source_commit") != CODE_AS_POLICIES_AUDITED_COMMIT:
        raise ValueError("Code as Policies source identity drifted")
    return {
        "query": _text(
            request.state.get("query"),
            "Code as Policies query",
        ),
        "context": _text(
            request.state.get("context", ""),
            "Code as Policies context",
            allow_empty=True,
        ),
        "known_names": _strings(
            request.state.get("known_names", ()),
            "Code as Policies known_names",
        ),
    }


def _helper_rows(value: object) -> tuple[JsonObject, ...]:
    decoded = thaw_json(value)
    if not isinstance(decoded, (tuple, list)):
        raise TypeError("Code as Policies helper_sources must be a sequence")
    rows: list[JsonObject] = []
    for item in decoded:
        if not isinstance(item, dict):
            raise TypeError("Code as Policies helper source row must be object")
        rows.append(item)
    return tuple(rows)


def _prepare_execution(request: MethodNodeRequest) -> MethodNodeResult:
    if request.state.get("synthesis_complete") is not True:
        raise RuntimeError(
            "Code as Policies cannot execute before synthesis completes"
        )
    policy_source = _text(
        request.state.get("policy_source"),
        "Code as Policies policy source",
    )
    helpers = _helper_rows(request.state.get("helper_sources", ()))
    bundle_digest = request.state.get("synthesis_bundle_digest")
    if type(bundle_digest) is not str or len(bundle_digest) != 64:
        raise ValueError(
            "Code as Policies synthesis bundle identity is missing"
        )
    api_bindings = _strings(
        request.state.get("api_bindings", ()),
        "Code as Policies api_bindings",
    )
    envelope = environment_action_capability_payload(
        _POLICY_PROGRAM_ACTION,
        {
            "language": "python",
            "query": request.state.get("query"),
            "context": request.state.get("context", ""),
            "policy_source": policy_source,
            "helper_sources": helpers,
            "bundle_digest": bundle_digest,
            "api_bindings": api_bindings,
            "execution_contract": {
                "isolation_required": True,
                "host_exec_forbidden": True,
                "effect_reconciliation_required": True,
                "historical_exec_filter": {
                    "banned_phrases": (
                        CODE_AS_POLICIES_FIDELITY.original_exec_banned_phrases
                    ),
                    "shadowed_names": (
                        CODE_AS_POLICIES_FIDELITY.original_exec_shadows
                    ),
                    "qualified_sandbox": False,
                },
            },
        },
    )
    return MethodNodeResult(
        value=envelope,
        state_update={
            "execution_request_digest": canonical_digest(envelope),
        },
    )


def _record_execution(request: MethodNodeRequest) -> MethodNodeResult:
    result = thaw_json(request.previous_value)
    if not isinstance(result, dict):
        raise TypeError(
            "Code as Policies environment execution result must be object"
        )
    accepted = result.get("accepted")
    if type(accepted) is not bool:
        raise TypeError(
            "Code as Policies environment result requires accepted boolean"
        )
    return MethodNodeResult(
        value=result,
        state_update={"execution_result": result},
        next_node="return",
    )


def _return_result(request: MethodNodeRequest) -> MethodNodeResult:
    result = request.state.get("execution_result")
    return MethodNodeResult(
        value={
            "source_commit": CODE_AS_POLICIES_AUDITED_COMMIT,
            "query": request.state.get("query"),
            "synthesis_bundle_digest": request.state.get(
                "synthesis_bundle_digest"
            ),
            "helper_count": len(
                _helper_rows(request.state.get("helper_sources", ()))
            ),
            "execution_result": result,
        }
    )


def build_code_as_policies_method_program() -> MethodProgram:
    configuration: JsonObject = {
        "source_commit": CODE_AS_POLICIES_AUDITED_COMMIT,
        "hierarchical_code_generation": True,
        "undefined_function_recursion": True,
        "environment_capability": _ENVIRONMENT_CAPABILITY_ID,
        "policy_program_action": _POLICY_PROGRAM_ACTION,
        "qualified_sandbox_required": True,
        "host_exec_forbidden": True,
    }
    identity = MethodProgramIdentity(
        MethodIdentity(
            method_id="code-as-policies",
            implementation_version=CODE_AS_POLICIES_AUDITED_COMMIT[:12],
            abi_version="noetrium.method-machine.v1",
            schema_version="code-as-policies.hierarchical-lmp.v1",
        ),
        configuration_digest=canonical_digest(configuration),
    )
    builder = MethodProgramBuilder(identity, entrypoint="synthesize")
    builder.agent(
        "synthesize",
        "code-as-policies.hierarchical-synthesis",
        SYNTHESIS_AGENT_ID,
        ("prepare_execute",),
        view_handler=_synthesis_view,
    )
    builder.compute(
        "prepare_execute",
        "code-as-policies.prepare-policy-program",
        _prepare_execution,
        ("execute_policy",),
    )
    builder.capability(
        "execute_policy",
        "code-as-policies.execute-policy-program",
        _ENVIRONMENT_CAPABILITY_ID,
        ("record_execution",),
        effect_class=EffectClass.RECONCILABLE,
        evidence_obligations=(
            "code-as-policies.program-effect",
            "environment.effect",
        ),
    )
    builder.compute(
        "record_execution",
        "code-as-policies.record-policy-program",
        _record_execution,
        ("return",),
    )
    builder.return_node(
        "return",
        "code-as-policies.result",
        _return_result,
    )
    return builder.build(
        configuration=configuration,
        required_capabilities=(_ENVIRONMENT_CAPABILITY_ID,),
        execution_class=MethodExecutionClass.EFFECT_RECORDED,
        evidence_obligations=(
            "code-as-policies.generation-receipts",
            "code-as-policies.helper-source-lineage",
            "code-as-policies.program-effect",
            "environment.effect",
        ),
        metric_names=(
            "helper_count",
            "generation_calls",
            "execution_success",
        ),
        artifact_kinds=(
            "code_as_policies_policy_source",
            "code_as_policies_helper_source",
            "code_as_policies_execution_trajectory",
        ),
    )


CODE_AS_POLICIES_METHOD_PROGRAM = build_code_as_policies_method_program()

__all__ = [
    "CODE_AS_POLICIES_METHOD_PROGRAM",
    "build_code_as_policies_method_program",
    "code_as_policies_initial_state",
]
