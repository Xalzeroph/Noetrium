from __future__ import annotations

from pathlib import Path
import sys

from noetrium_platform.capabilities.model.qualification.api import (
    BackendCandidatePlan,
    DeploymentQualificationPlan,
    DeploymentQualificationApplicationRequest,
    DeploymentQualificationRequest,
    DeploymentQualificationRuntimeRequest,
)

from .context import ManagementCommandContext


def qualification_python_path(path: Path) -> Path:
    """Keep a virtual-environment entrypoint instead of resolving its symlink."""

    return path.expanduser()


def _candidate_summary(candidate: BackendCandidatePlan) -> dict[str, object]:
    packages = candidate.packages
    return {
        "backend": candidate.backend,
        "decision": candidate.decision,
        "version": candidate.version,
        "package_count": len(packages),
        "package_head": tuple(
            {"name": item.name, "version": item.version} for item in packages[:8]
        ),
        "package_tail": tuple(
            {"name": item.name, "version": item.version} for item in packages[-8:]
        ),
        "native_packages": tuple(
            {"name": item.name, "version": item.version}
            for item in packages
            if any(
                token in item.name.lower().replace("_", "-")
                for token in (
                    "nvidia",
                    "cuda",
                    "nccl",
                    "cudnn",
                    "cublas",
                    "nvrtc",
                    "torch",
                )
            )
        ),
        "reasons": candidate.reasons,
        "evidence_refs": candidate.evidence_refs,
    }


def qualification_summary(plan: DeploymentQualificationPlan) -> dict[str, object]:
    return {
        "request_digest": plan.request_digest,
        "facts_digest": plan.facts_digest,
        "plan_digest": plan.plan_digest,
        "selected_backend": plan.selected_backend,
        "candidates": tuple(_candidate_summary(candidate) for candidate in plan.candidates),
    }


def dispatch_qualification_action(
    args: object,
    context: ManagementCommandContext,
) -> tuple[bool, object]:
    action = getattr(args, "action")
    if action == "qualify":
        if args.environment_id and args.python:
            raise ValueError(
                "deployment qualification accepts either --environment-id or --python, not both"
            )
        environment_id = args.environment_id
        if environment_id:
            python_path = context.environments.lifecycle.get(environment_id).python_path
        else:
            python_path = args.python or Path(sys.executable)
        plan = context.deployment_qualification.qualification.qualify(
            DeploymentQualificationRequest(
                model_id=args.model_id,
                model_path=args.model_path.expanduser().resolve(),
                python_executable=qualification_python_path(python_path),
                python_environment_id=environment_id,
                backends=tuple(args.backends) if args.backends else ("sglang", "vllm"),
                tensor_parallel=args.tensor_parallel,
                package_index_urls=tuple(args.index_urls),
                probe_timeout_seconds=args.timeout_seconds,
            )
        )
        return True, qualification_summary(plan) if args.summary else plan
    if action == "qualification":
        return True, context.deployment_qualification.evidence.get(args.plan_digest)
    if action == "apply-qualification":
        return True, context.deployment_qualification.application.apply(
            DeploymentQualificationApplicationRequest(
                plan_digest=args.plan_digest,
                environment_id=args.environment_id,
            )
        )
    if action == "runtime-qualify":
        return True, context.deployment_qualification.runtime.qualify(
            DeploymentQualificationRuntimeRequest(args.application_digest)
        )
    return False, None


__all__ = [
    "dispatch_qualification_action",
    "qualification_python_path",
    "qualification_summary",
]
