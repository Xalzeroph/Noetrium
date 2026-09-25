from __future__ import annotations


class OperationSemanticPolicyViolation(RuntimeError):
    """A component boundary request violates a mechanical execution-safety contract."""


__all__ = ["OperationSemanticPolicyViolation"]
