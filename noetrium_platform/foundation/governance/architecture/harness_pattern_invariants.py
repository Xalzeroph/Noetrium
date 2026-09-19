from __future__ import annotations

from pathlib import Path

from .source_index import source_text
from .source_scan import SourceInvariantViolation, imports, violation


def _require_tokens(root: Path, path: Path, invariant: str, tokens: tuple[str, ...]) -> list[SourceInvariantViolation]:
    if not path.parent.exists():
        return []
    if not path.exists():
        return [violation(root, path, invariant, 1, "required module missing")]
    text = source_text(path)
    return [
        violation(root, path, invariant, 1, f"missing required boundary token: {token}")
        for token in tokens
        if token not in text
    ]


def _audit_api_dependency_direction(root: Path) -> list[SourceInvariantViolation]:
    rows: list[SourceInvariantViolation] = []
    rules = (
        (root / "noetrium_platform" / "capabilities" / "model" / "request" / "api", ("noetrium_platform.capabilities.model.request.runtime", "noetrium_platform.capabilities.model.request.prompt.runtime", "noetrium_platform.capabilities.model.serving")),
        (root / "noetrium_platform" / "research" / "execution" / "capability" / "api", ("noetrium_platform.research.execution.capability.runtime", "noetrium_platform.research.execution.workflow.implementations", "noetrium_platform.research.experimentation")),
        (root / "noetrium_platform" / "evidence" / "data" / "projection" / "api", ("noetrium_platform.evidence.data.projection.runtime", "noetrium_platform.infrastructure.reliability.forensics")),
        (root / "noetrium_platform" / "evidence" / "data" / "fact" / "api", ("noetrium_platform.evidence.data.fact.runtime",)),
        (root / "noetrium_platform" / "capabilities" / "participant" / "capability" / "api", ("noetrium_platform.research.execution.capability.runtime",)),
        (root / "noetrium_platform" / "evidence" / "data" / "record" / "api", ("noetrium_platform.evidence.data.fact.api", "noetrium_platform.evidence.observability.api", "noetrium_platform.capabilities.participant.capability.api")),
    )
    for base, forbidden in rules:
        if not base.exists():
            continue
        for path in sorted(base.rglob("*.py")):
            for module, line in imports(path):
                if module.startswith(forbidden):
                    rows.append(violation(root, path, "harness_api_dependency_direction", line, f"API package {base.relative_to(root)} imports runtime/upper implementation {module}"))
    return rows


def audit_harness_pattern_invariants(root: Path) -> list[SourceInvariantViolation]:
    rows = _audit_api_dependency_direction(root)
    rows += _require_tokens(
        root,
        root / "noetrium_platform" / "capabilities" / "model" / "request" / "prompt" / "runtime" / "request_build.py",
        "model_visible_request_reconstructability",
        ("ModelRequestRecorderPort", "model_requests.record", "model_requests.verify_visible_request"),
    )
    rows += _require_tokens(
        root,
        root / "noetrium_platform" / "research" / "execution" / "workflow" / "implementations" / "agent_turn" / "capability_routing.py",
        "scoped_capability_pipeline",
        ("RegistrationScopePort", "CapabilityInvocationPipelinePort", "self._scope.acquire", "self._scope.dispose"),
    )
    rows += _require_tokens(
        root,
        root / "noetrium_platform" / "research" / "execution" / "workflow" / "implementations" / "agent_turn" / "agent_turn_operations.py",
        "scoped_capability_lifecycle",
        ("finally:", "router.close()"),
    )
    rows += _require_tokens(
        root,
        root / "noetrium_platform" / "evidence" / "data" / "record" / "api" / "contracts.py",
        "execution_record_planes",
        ("DURABLE_FACT", "LIVE_INTERCEPTION", "SIDE_PLANE_OBSERVATION"),
    )
    rows += _require_tokens(
        root,
        root / "noetrium_platform" / "evidence" / "data" / "fact" / "runtime" / "decoder_registry.py",
        "unknown_required_fact_fail_closed",
        ("FactCriticality.IGNORABLE", "raise UnknownRequiredFact"),
    )
    return rows


__all__ = ["audit_harness_pattern_invariants"]
