from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .contracts import CapabilityDescriptor, CapabilityRequest, CapabilityResult
from noetrium_platform.evidence.data.record.api import ExecutionRecordPlane
from noetrium_platform.foundation.kernel.kernel import require_sha256


class GuardVerdict(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    ABSTAIN = "abstain"


@dataclass(frozen=True, slots=True)
class GuardDecision:
    guard_id: str
    verdict: GuardVerdict
    reason_code: str = ""

    def __post_init__(self) -> None:
        if not self.guard_id.strip():
            raise ValueError("guard_id must be non-empty")
        if self.verdict is GuardVerdict.DENY and not self.reason_code.strip():
            raise ValueError("deny decision requires a stable reason_code")

    @property
    def record_plane(self) -> ExecutionRecordPlane:
        return ExecutionRecordPlane.LIVE_INTERCEPTION


@runtime_checkable
class CapabilityGuardPort(Protocol):
    guard_id: str
    implementation_digest: str
    def evaluate(self, descriptor: CapabilityDescriptor, request: CapabilityRequest) -> GuardDecision: ...


@runtime_checkable
class CapabilityApprovalPort(Protocol):
    approval_id: str
    implementation_digest: str
    def approve(self, descriptor: CapabilityDescriptor, request: CapabilityRequest) -> bool: ...


@runtime_checkable
class CapabilityPostPolicyPort(Protocol):
    policy_id: str
    implementation_digest: str
    def validate(
        self,
        descriptor: CapabilityDescriptor,
        request: CapabilityRequest,
        result: CapabilityResult,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class CapabilityPolicySet:
    guards: tuple[CapabilityGuardPort, ...] = ()
    approval: CapabilityApprovalPort | None = None
    post_policies: tuple[CapabilityPostPolicyPort, ...] = ()

    def __post_init__(self) -> None:
        if type(self.guards) is not tuple:
            raise TypeError("capability policy guards must be a tuple")
        guard_ids: list[str] = []
        for guard in self.guards:
            guard_id = getattr(guard, "guard_id", None)
            if type(guard_id) is not str or not guard_id.strip():
                raise ValueError("capability guard_id is required")
            require_sha256(
                getattr(guard, "implementation_digest", None),
                f"capability guard {guard_id} implementation_digest",
            )
            if not callable(getattr(guard, "evaluate", None)):
                raise TypeError(
                    f"capability guard {guard_id} evaluate must be callable"
                )
            guard_ids.append(guard_id.strip())
        if len(guard_ids) != len(set(guard_ids)):
            raise ValueError("capability guard ids must be unique")

        if self.approval is not None:
            approval_id = getattr(self.approval, "approval_id", None)
            if type(approval_id) is not str or not approval_id.strip():
                raise ValueError("capability approval_id is required")
            require_sha256(
                getattr(self.approval, "implementation_digest", None),
                f"capability approval {approval_id} implementation_digest",
            )
            if not callable(getattr(self.approval, "approve", None)):
                raise TypeError("capability approval approve must be callable")

        if type(self.post_policies) is not tuple:
            raise TypeError("capability post policies must be a tuple")
        policy_ids: list[str] = []
        for policy in self.post_policies:
            policy_id = getattr(policy, "policy_id", None)
            if type(policy_id) is not str or not policy_id.strip():
                raise ValueError("capability post policy_id is required")
            require_sha256(
                getattr(policy, "implementation_digest", None),
                f"capability post policy {policy_id} implementation_digest",
            )
            if not callable(getattr(policy, "validate", None)):
                raise TypeError(
                    f"capability post policy {policy_id} validate must be callable"
                )
            policy_ids.append(policy_id.strip())
        if len(policy_ids) != len(set(policy_ids)):
            raise ValueError("capability post policy ids must be unique")


class CapabilityPolicyDenied(PermissionError):
    def __init__(self, *, guard_id: str, reason_code: str) -> None:
        super().__init__(f"capability invocation denied by guard={guard_id} reason={reason_code}")
        self.guard_id = guard_id
        self.reason_code = reason_code


class CapabilityApprovalDenied(PermissionError):
    pass


class CapabilityPostPolicyViolation(RuntimeError):
    """Post-execution policy rejected an already completed invocation.

    ``execution_completed`` is deliberately explicit so recovery/failure code never
    mistakes a post-policy rejection for proof that the underlying capability did
    not run. The original exception remains available only through ``__cause__``.
    """

    execution_completed = True
    retry_safe = False

    def __init__(self, *, policy_id: str, result: CapabilityResult) -> None:
        super().__init__(f"capability post-policy rejected completed invocation: policy={policy_id}")
        self.policy_id = policy_id
        self.result = result


__all__ = [
    "CapabilityApprovalDenied",
    "CapabilityApprovalPort",
    "CapabilityGuardPort",
    "CapabilityPolicyDenied",
    "CapabilityPolicySet",
    "CapabilityPostPolicyPort",
    "CapabilityPostPolicyViolation",
    "GuardDecision",
    "GuardVerdict",
]
