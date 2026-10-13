from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, runtime_checkable

from .contracts import CapabilityDescriptor, CapabilityRequest, CapabilityResult
from noetrium_platform.foundation.kernel.record_plane import ExecutionRecordPlane
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
    "CapabilityPostPolicyPort",
    "CapabilityPostPolicyViolation",
    "GuardDecision",
    "GuardVerdict",
]
