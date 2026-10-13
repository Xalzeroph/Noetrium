from __future__ import annotations

"""Neutral typed contract for generated platform leaf ownership seams.

Generic catalog leaves are topology/dispatch seams only. They deliberately do
not own persistence, checkpointing or recovery state. Durable mutation belongs
to an explicitly declared canonical authority (Machine, Operation, Effect,
Scope, Resource lease, Artifact/content, etc.), never to a generated leaf
wrapper merely because the package has a runtime plane.
"""

from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Protocol

from .json_value import JsonValue
from .canonical import canonical_digest
from .errors import describe_exception
from .leaf_failure import LeafFailureClass, LeafFailureReceipt, receipt


class LeafExecutionError(RuntimeError):
    """A leaf cannot execute and carries a machine-diagnosable receipt."""

    def __init__(self, message: str, *, failure_receipt: LeafFailureReceipt | None = None):
        super().__init__(message)
        self.receipt = failure_receipt


class LeafHandler(Protocol):
    def __call__(self, operation: str, payload: Mapping[str, JsonValue]) -> JsonValue: ...


@dataclass(frozen=True, slots=True)
class LeafExecutionResult:
    operation: str
    output: JsonValue
    contract_digest: str
    handler_id: str
    output_digest: str
    handler_bound: bool


@dataclass(frozen=True, slots=True)
class BoundSystemLeafRuntime:
    """Bound behavior for a catalog leaf without an independent state store.

    The runtime can translate/execute behavior, but it cannot checkpoint or
    restore arbitrary leaf-local truth. Stateful behavior must call the port of
    the canonical authority named by the system registry instead.
    """

    contract: "SystemLeafContract"
    handler: LeafHandler

    @property
    def handler_id(self) -> str:
        handler_type = type(self.handler)
        return f"{handler_type.__module__}.{handler_type.__qualname__}"

    def execute(self, operation: str, payload: Mapping[str, JsonValue]) -> LeafExecutionResult:
        if not operation.strip():
            raise ValueError("leaf operation must be non-empty")
        if not isinstance(payload, Mapping):
            raise TypeError("leaf payload must be a mapping")
        try:
            output = self.handler(operation, payload)
        except LeafExecutionError:
            raise
        except (TimeoutError, ConnectionError) as exc:
            detail = describe_exception(exc).safe_message
            raise LeafExecutionError(
                detail,
                failure_receipt=receipt(
                    exc,
                    code="LEAF_EXTERNAL_UNCERTAIN",
                    classification=LeafFailureClass.EXTERNAL_EFFECT_UNCERTAIN,
                    retryable=False,
                    effect_certainty="unknown",
                    contract_digest=self.contract.digest,
                ),
            ) from exc
        except (OSError, PermissionError) as exc:
            detail = describe_exception(exc).safe_message
            raise LeafExecutionError(
                detail,
                failure_receipt=receipt(
                    exc,
                    code="LEAF_PERSISTENCE_FAILURE",
                    classification=LeafFailureClass.PERSISTENCE,
                    retryable=True,
                    effect_certainty="not_applicable",
                    contract_digest=self.contract.digest,
                ),
            ) from exc
        except (ValueError, TypeError, KeyError) as exc:
            detail = describe_exception(exc).safe_message
            raise LeafExecutionError(
                detail,
                failure_receipt=receipt(
                    exc,
                    code="LEAF_INVALID_INPUT",
                    classification=LeafFailureClass.BUSINESS,
                    retryable=False,
                    effect_certainty="not_applied",
                    contract_digest=self.contract.digest,
                ),
            ) from exc
        except Exception as exc:
            detail = describe_exception(exc).safe_message
            raise LeafExecutionError(
                detail,
                failure_receipt=receipt(
                    exc,
                    code="LEAF_PROGRAMMING_FAILURE",
                    classification=LeafFailureClass.PROGRAMMING,
                    retryable=False,
                    effect_certainty="unknown",
                    contract_digest=self.contract.digest,
                ),
            ) from exc
        return LeafExecutionResult(
            operation=operation,
            output=output,
            contract_digest=self.contract.digest,
            handler_id=self.handler_id,
            output_digest=canonical_digest(output),
            handler_bound=True,
        )


@dataclass(frozen=True, slots=True)
class SystemLeafContract:
    """Executable topology contract for one catalog leaf.

    ``authority_id`` is retained as declaration metadata while the vNext
    catalog is being consolidated. It does not grant this generic wrapper a
    durable write path. Direct authority is decided only by the canonical
    System Registry ``node_kind=authority`` contract.
    """

    system_id: str
    node: str
    package_prefix: str
    authority_id: str
    owns: str
    must_not_own: str
    api_module: str
    runtime_module: str
    provider_module: str
    composition_module: str

    def __post_init__(self) -> None:
        text_fields = (
            self.system_id,
            self.node,
            self.package_prefix,
            self.authority_id,
            self.owns,
            self.must_not_own,
            self.api_module,
            self.runtime_module,
            self.provider_module,
            self.composition_module,
        )
        if any(not value.strip() for value in text_fields):
            raise ValueError("system leaf contract fields must be non-empty")
        if not self.node.startswith(self.system_id + "/") and self.node != self.system_id:
            raise ValueError("system leaf node must be rooted at system_id")
        if not self.package_prefix.startswith("noetrium_platform."):
            raise ValueError("system leaf package must be inside noetrium_platform")
        expected = (
            ("api_module", self.package_prefix + ".api", self.api_module),
            ("runtime_module", self.package_prefix + ".runtime", self.runtime_module),
            ("provider_module", self.package_prefix + ".providers", self.provider_module),
            ("composition_module", self.package_prefix + ".composition", self.composition_module),
        )
        for field, expected_value, actual in expected:
            if actual != expected_value:
                raise ValueError(f"system leaf {field} drift")

    @property
    def digest(self) -> str:
        return canonical_digest(
            {
                "system_id": self.system_id,
                "node": self.node,
                "package_prefix": self.package_prefix,
                "authority_id": self.authority_id,
                "owns": self.owns,
                "must_not_own": self.must_not_own,
                "api_module": self.api_module,
                "runtime_module": self.runtime_module,
                "provider_module": self.provider_module,
                "composition_module": self.composition_module,
            }
        )


@dataclass(frozen=True, slots=True)
class SystemLeafRuntimeOwner:
    """Side-effect-free runtime binder for one leaf contract.

    ``state_path`` is accepted only to fail closed for stale generated wrappers.
    Passing one can no longer manufacture an implicit state authority.
    """

    contract: SystemLeafContract

    def __post_init__(self) -> None:
        if not isinstance(self.contract, SystemLeafContract):
            raise TypeError("runtime owner requires a SystemLeafContract")

    @property
    def owner_id(self) -> str:
        return self.contract.authority_id

    def describe(self) -> dict[str, str]:
        return {
            "node": self.contract.node,
            "package_prefix": self.contract.package_prefix,
            "authority_id": self.contract.authority_id,
            "contract_digest": self.contract.digest,
        }

    def bind(
        self,
        handler: LeafHandler,
        state_path: str | Path | None = None,
    ) -> BoundSystemLeafRuntime:
        if not callable(handler):
            raise TypeError("leaf runtime handler must be callable")
        if state_path is not None:
            raise LeafExecutionError(
                "generic leaf-local state is forbidden; bind the canonical authority port instead"
            )
        return BoundSystemLeafRuntime(self.contract, handler)


@dataclass(frozen=True, slots=True)
class SystemLeafProvider:
    """Provider seam: domain behavior is injected without acquiring truth ownership."""

    contract: SystemLeafContract

    def describe(self) -> dict[str, str]:
        return {
            "provider_module": self.contract.provider_module,
            "contract_digest": self.contract.digest,
        }

    def bind(
        self,
        handler: LeafHandler,
        state_path: str | Path | None = None,
    ) -> BoundSystemLeafRuntime:
        return SystemLeafRuntimeOwner(self.contract).bind(handler, state_path)


__all__ = [
    "BoundSystemLeafRuntime",
    "LeafExecutionError",
    "LeafExecutionResult",
    "LeafFailureClass",
    "LeafFailureReceipt",
    "LeafHandler",
    "SystemLeafContract",
    "SystemLeafProvider",
    "SystemLeafRuntimeOwner",
]
