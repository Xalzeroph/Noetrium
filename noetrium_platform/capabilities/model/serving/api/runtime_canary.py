from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
import json
import math
from types import MappingProxyType

from noetrium_platform.foundation.kernel.kernel import JsonInput, JsonValue, canonical_digest


def _freeze_json(value: JsonInput, field: str) -> JsonValue:
    if value is None or type(value) in {str, int, bool}:
        return value
    if type(value) is float:
        if not math.isfinite(value):
            raise ValueError(f"{field} contains a non-finite float")
        return value
    if isinstance(value, Mapping):
        frozen: dict[str, JsonValue] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise TypeError(f"{field} requires string JSON object keys")
            frozen[key] = _freeze_json(item, field)
        return MappingProxyType(frozen)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_json(item, field) for item in value)
    raise TypeError(f"{field} contains unsupported JSON value: {type(value).__name__}")


def _digest(value: str, field: str) -> str:
    if type(value) is not str or len(value) != 64 or any(
        char not in "0123456789abcdef" for char in value
    ):
        raise ValueError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _text(value: str, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} is required")
    return value


@dataclass(frozen=True, slots=True)
class RuntimeCanaryContract:
    contract_id: str
    require_json_object: bool = False
    required_json_keys: tuple[str, ...] = ()
    allowed_finish_reasons: tuple[str, ...] = ()
    expected_json_digest: str | None = None

    def __post_init__(self) -> None:
        _text(self.contract_id, "runtime canary contract_id")
        if type(self.require_json_object) is not bool:
            raise TypeError("runtime canary require_json_object must be bool")
        for field, values in (
            ("required_json_keys", self.required_json_keys),
            ("allowed_finish_reasons", self.allowed_finish_reasons),
        ):
            if type(values) is not tuple:
                raise TypeError(f"runtime canary {field} must be tuple")
            if any(type(value) is not str or not value.strip() for value in values):
                raise TypeError(f"runtime canary {field} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"runtime canary {field} must be unique")
        if self.required_json_keys and not self.require_json_object:
            raise ValueError("runtime canary required_json_keys requires JSON object contract")
        if self.expected_json_digest is not None:
            _digest(self.expected_json_digest, "runtime canary expected_json_digest")
            if not self.require_json_object:
                raise ValueError("runtime canary expected_json_digest requires JSON object contract")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class RuntimeCanaryProbe:
    canary_id: str
    role: str
    suite_digest: str
    request_body: Mapping[str, JsonInput]
    contract: RuntimeCanaryContract

    def __post_init__(self) -> None:
        _text(self.canary_id, "runtime canary canary_id")
        _text(self.role, "runtime canary role")
        _digest(self.suite_digest, "runtime canary suite_digest")
        if not isinstance(self.request_body, Mapping) or not self.request_body:
            raise TypeError("runtime canary request_body must be a non-empty JSON object")
        frozen = _freeze_json(self.request_body, "runtime canary request_body")
        if not isinstance(frozen, Mapping):
            raise TypeError("runtime canary request_body must be a JSON object")
        object.__setattr__(self, "request_body", frozen)
        canonical_digest(self.request_body)

    @property
    def request_digest(self) -> str:
        return canonical_digest(self.request_body)

    def digest(self) -> str:
        return canonical_digest({
            "canary_id": self.canary_id,
            "role": self.role,
            "suite_digest": self.suite_digest,
            "request_digest": self.request_digest,
            "contract_digest": self.contract.digest(),
        })


@dataclass(frozen=True, slots=True)
class RuntimeCanaryEvidence:
    deployment_id: str
    deployment_generation: str
    route_digest: str
    role: str
    canary_id: str
    suite_digest: str
    process_pid: int
    process_start_marker: str
    argv_digest: str
    request_digest: str
    probe_digest: str
    response_digest: str
    contract_digest: str
    passed: bool
    observed_at: float
    evidence_digest: str = ""

    def __post_init__(self) -> None:
        _text(self.deployment_id, "runtime canary deployment_id")
        for field in ("deployment_generation", "route_digest", "suite_digest"):
            _digest(getattr(self, field), f"runtime canary {field}")
        _text(self.role, "runtime canary role")
        _text(self.canary_id, "runtime canary canary_id")
        if type(self.process_pid) is not int or self.process_pid <= 0:
            raise TypeError("runtime canary process_pid must be positive integer")
        _text(self.process_start_marker, "runtime canary process_start_marker")
        for field in ("argv_digest", "request_digest", "probe_digest", "response_digest", "contract_digest"):
            _digest(getattr(self, field), f"runtime canary {field}")
        if type(self.passed) is not bool:
            raise TypeError("runtime canary passed must be bool")
        if type(self.observed_at) is not float or not math.isfinite(self.observed_at):
            raise TypeError("runtime canary observed_at must be finite float")
        expected = canonical_digest({
            "deployment_id": self.deployment_id,
            "deployment_generation": self.deployment_generation,
            "route_digest": self.route_digest,
            "role": self.role,
            "canary_id": self.canary_id,
            "suite_digest": self.suite_digest,
            "process_pid": self.process_pid,
            "process_start_marker": self.process_start_marker,
            "argv_digest": self.argv_digest,
            "request_digest": self.request_digest,
            "probe_digest": self.probe_digest,
            "response_digest": self.response_digest,
            "contract_digest": self.contract_digest,
            "passed": self.passed,
            "observed_at": self.observed_at,
        })
        if self.evidence_digest and self.evidence_digest != expected:
            raise ValueError("runtime canary evidence digest mismatch")
        object.__setattr__(self, "evidence_digest", expected)


def evaluate_runtime_canary_contract(
    contract: RuntimeCanaryContract,
    *,
    text: str,
    finish_reason: str | None,
) -> bool:
    if type(text) is not str or not text.strip():
        return False
    if contract.allowed_finish_reasons and finish_reason not in contract.allowed_finish_reasons:
        return False
    if not contract.require_json_object:
        return True
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return False
    if type(payload) is not dict:
        return False
    if not all(key in payload for key in contract.required_json_keys):
        return False
    if contract.expected_json_digest is not None:
        return canonical_digest(payload) == contract.expected_json_digest
    return True


__all__ = [
    "RuntimeCanaryContract",
    "RuntimeCanaryEvidence",
    "RuntimeCanaryProbe",
    "evaluate_runtime_canary_contract",
]
