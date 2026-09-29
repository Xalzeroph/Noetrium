from __future__ import annotations

from noetrium_platform.capabilities.model.serving.api import (
    QualifiedDeploymentManifest,
    RoleModelAssignment,
    RuntimeCanaryContract,
    RuntimeCanaryProbe,
)
from noetrium_platform.foundation.kernel.kernel import canonical_digest


_STANDARD_GENERATION_KEY = (
    "generation",
    "model.generation.request.v1",
    "model.generation.response.v1",
)


def canonical_runtime_canary_probe(
    assignment: RoleModelAssignment,
    deployment: QualifiedDeploymentManifest,
    *,
    required_capabilities: tuple[str, ...] = ("generation",),
) -> RuntimeCanaryProbe:
    """Materialize a strict live canary without weakening capability proof."""

    protocol = (
        assignment.capability_id,
        assignment.input_schema_id,
        assignment.output_schema_id,
    )
    if protocol != _STANDARD_GENERATION_KEY:
        raise KeyError(
            "no canonical runtime canary is registered for model protocol: "
            + repr(assignment.protocol_key)
        )
    capabilities = tuple(sorted(set(required_capabilities)))
    if not capabilities or "generation" not in capabilities:
        raise ValueError(
            "canonical generation canary must verify generation capability"
        )
    unsupported = set(capabilities) - {"generation", "structured_output"}
    if unsupported:
        raise KeyError(
            "canonical generation canary cannot prove capabilities: "
            + ",".join(sorted(unsupported))
        )

    structured = "structured_output" in capabilities
    expected_json = {"ok": True}
    if structured:
        request_body = {
            "model": deployment.stack.identity.model_id,
            "messages": (
                {
                    "role": "user",
                    "content": "Return exactly one JSON object with ok set to true.",
                },
            ),
            "temperature": 0,
            "max_tokens": 16,
            "chat_template_kwargs": {"enable_thinking": False},
            "response_format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "noetrium_runtime_canary",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "properties": {"ok": {"const": True}},
                        "required": ["ok"],
                        "additionalProperties": False,
                    },
                },
            },
        }
        contract = RuntimeCanaryContract(
            contract_id="standard-generation-structured-json.v1",
            require_non_empty_text=True,
            require_json_object=True,
            required_json_keys=("ok",),
            allowed_finish_reasons=("stop", "length"),
            expected_json_digest=canonical_digest(expected_json),
            verified_capabilities=capabilities,
        )
        suite_schema = (
            "noetrium.runtime-canary-suite.standard-generation-structured.v1"
        )
    else:
        request_body = {
            "model": deployment.stack.identity.model_id,
            "messages": (
                {
                    "role": "user",
                    "content": "Reply with one short plain-text token.",
                },
            ),
            "temperature": 0,
            "max_tokens": 8,
        }
        contract = RuntimeCanaryContract(
            contract_id="standard-generation-nonempty.v1",
            require_non_empty_text=True,
            allowed_finish_reasons=("stop", "length"),
            verified_capabilities=capabilities,
        )
        suite_schema = "noetrium.runtime-canary-suite.standard-generation.v1"

    suite_digest = canonical_digest(
        {
            "schema": suite_schema,
            "protocol": assignment.protocol_key,
            "stack_digest": deployment.stack.digest(),
            "verified_capabilities": capabilities,
        }
    )
    return RuntimeCanaryProbe(
        canary_id=(
            "standard-generation:"
            + canonical_digest(
                {
                    "role": assignment.role,
                    "stack_digest": deployment.stack.digest(),
                    "verified_capabilities": capabilities,
                }
            )[:24]
        ),
        role=assignment.role,
        suite_digest=suite_digest,
        request_body=request_body,
        contract=contract,
        capability_id=assignment.capability_id,
        input_schema_id=assignment.input_schema_id,
        output_schema_id=assignment.output_schema_id,
    )


__all__ = ["canonical_runtime_canary_probe"]
