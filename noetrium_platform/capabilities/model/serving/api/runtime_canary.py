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
    verified_capabilities: tuple[str, ...] = ()
    require_non_empty_text: bool = True
    required_tool_names: tuple[str, ...] = ()
    minimum_tool_calls: int = 0
    required_content_block_kinds: tuple[str, ...] = ()
    required_stream_event_kinds: tuple[str, ...] = ()
    require_payload: bool = False
    required_payload_keys: tuple[str, ...] = ()
    expected_payload_digest: str | None = None

    def __post_init__(self) -> None:
        _text(self.contract_id, "runtime canary contract_id")
        if type(self.require_json_object) is not bool:
            raise TypeError("runtime canary require_json_object must be bool")
        if type(self.require_non_empty_text) is not bool:
            raise TypeError("runtime canary require_non_empty_text must be bool")
        if type(self.require_payload) is not bool:
            raise TypeError("runtime canary require_payload must be bool")
        if type(self.minimum_tool_calls) is not int or self.minimum_tool_calls < 0:
            raise ValueError("runtime canary minimum_tool_calls must be non-negative integer")
        for field, values in (
            ("required_json_keys", self.required_json_keys),
            ("allowed_finish_reasons", self.allowed_finish_reasons),
            ("verified_capabilities", self.verified_capabilities),
            ("required_tool_names", self.required_tool_names),
            ("required_content_block_kinds", self.required_content_block_kinds),
            ("required_stream_event_kinds", self.required_stream_event_kinds),
            ("required_payload_keys", self.required_payload_keys),
        ):
            if type(values) is not tuple:
                raise TypeError(f"runtime canary {field} must be tuple")
            if any(type(value) is not str or not value.strip() for value in values):
                raise TypeError(f"runtime canary {field} must contain non-empty strings")
            if len(set(values)) != len(values):
                raise ValueError(f"runtime canary {field} must be unique")
        object.__setattr__(
            self,
            "verified_capabilities",
            tuple(sorted(self.verified_capabilities)),
        )
        if self.required_json_keys and not self.require_json_object:
            raise ValueError("runtime canary required_json_keys requires JSON object contract")
        if self.expected_json_digest is not None:
            _digest(self.expected_json_digest, "runtime canary expected_json_digest")
            if not self.require_json_object:
                raise ValueError("runtime canary expected_json_digest requires JSON object contract")
        capabilities=set(self.verified_capabilities)
        if "structured_output" in capabilities and not self.require_json_object:
            raise ValueError(
                "structured_output capability requires JSON object proof"
            )
        if capabilities & {"tools","parallel_tools"}:
            if not self.required_tool_names and self.minimum_tool_calls <= 0:
                raise ValueError(
                    "tool capability requires tool-call proof conditions"
                )
        if "parallel_tools" in capabilities and self.minimum_tool_calls < 2:
            raise ValueError(
                "parallel_tools capability requires at least two tool calls"
            )
        if "reasoning" in capabilities and "reasoning" not in self.required_content_block_kinds:
            raise ValueError(
                "reasoning capability requires reasoning content-block proof"
            )
        if "streaming" in capabilities and "completed" not in self.required_stream_event_kinds:
            raise ValueError(
                "streaming capability requires completed stream-event proof"
            )
        if self.required_payload_keys and not self.require_payload:
            raise ValueError(
                "runtime canary required_payload_keys requires payload proof"
            )
        if self.expected_payload_digest is not None:
            _digest(
                self.expected_payload_digest,
                "runtime canary expected_payload_digest",
            )
            if not self.require_payload:
                raise ValueError(
                    "runtime canary expected_payload_digest requires payload proof"
                )

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class RuntimeCanaryProbe:
    canary_id: str
    role: str
    suite_digest: str
    request_body: Mapping[str, JsonInput]
    contract: RuntimeCanaryContract
    execution_mode: str = "complete"
    capability_id: str = "generation"
    input_schema_id: str = "model.generation.request.v1"
    output_schema_id: str = "model.generation.response.v1"

    def __post_init__(self) -> None:
        _text(self.canary_id, "runtime canary canary_id")
        _text(self.role, "runtime canary role")
        _digest(self.suite_digest, "runtime canary suite_digest")
        _text(self.capability_id, "runtime canary capability_id")
        _text(self.input_schema_id, "runtime canary input_schema_id")
        _text(self.output_schema_id, "runtime canary output_schema_id")
        if self.execution_mode not in {"complete","stream"}:
            raise ValueError(
                "runtime canary execution_mode must be complete or stream"
            )
        if self.execution_mode == "stream" and self.capability_id != "generation":
            raise ValueError(
                "stream runtime canary is only defined for generation"
            )
        if (
            "streaming" in self.contract.verified_capabilities
            and self.execution_mode != "stream"
        ):
            raise ValueError(
                "streaming capability requires stream execution mode"
            )
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
            "execution_mode": self.execution_mode,
            "capability_id": self.capability_id,
            "input_schema_id": self.input_schema_id,
            "output_schema_id": self.output_schema_id,
        })


@dataclass(frozen=True, slots=True)
class RuntimeCanaryEvidence:
    deployment_id: str
    deployment_generation: str
    route_digest: str
    role: str
    capability_id: str
    input_schema_id: str
    output_schema_id: str
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
    verified_capabilities: tuple[str, ...] = ()
    execution_mode: str = "complete"
    stream_digest: str | None = None
    evidence_digest: str = ""

    def __post_init__(self) -> None:
        _text(self.deployment_id, "runtime canary deployment_id")
        for field in ("deployment_generation", "route_digest", "suite_digest"):
            _digest(getattr(self, field), f"runtime canary {field}")
        _text(self.role, "runtime canary role")
        _text(self.capability_id, "runtime canary capability_id")
        _text(self.input_schema_id, "runtime canary input_schema_id")
        _text(self.output_schema_id, "runtime canary output_schema_id")
        _text(self.canary_id, "runtime canary canary_id")
        if type(self.process_pid) is not int or self.process_pid <= 0:
            raise TypeError("runtime canary process_pid must be positive integer")
        _text(self.process_start_marker, "runtime canary process_start_marker")
        for field in ("argv_digest", "request_digest", "probe_digest", "response_digest", "contract_digest"):
            _digest(getattr(self, field), f"runtime canary {field}")
        if type(self.passed) is not bool:
            raise TypeError("runtime canary passed must be bool")
        if self.execution_mode not in {"complete","stream"}:
            raise ValueError(
                "runtime canary evidence execution_mode must be complete or stream"
            )
        if self.execution_mode == "stream":
            if self.stream_digest is None:
                raise ValueError(
                    "stream runtime canary evidence requires stream_digest"
                )
            _digest(self.stream_digest,"runtime canary stream_digest")
        elif self.stream_digest is not None:
            raise ValueError(
                "complete runtime canary evidence cannot carry stream_digest"
            )
        if type(self.verified_capabilities) is not tuple or any(
            type(value) is not str or not value.strip()
            for value in self.verified_capabilities
        ):
            raise TypeError("runtime canary verified_capabilities must contain non-empty strings")
        normalized_capabilities = tuple(sorted(set(self.verified_capabilities)))
        if len(normalized_capabilities) != len(self.verified_capabilities):
            raise ValueError("runtime canary verified_capabilities must be unique")
        if not self.passed and normalized_capabilities:
            raise ValueError("failed runtime canary cannot verify capabilities")
        object.__setattr__(self, "verified_capabilities", normalized_capabilities)
        if type(self.observed_at) is not float or not math.isfinite(self.observed_at):
            raise TypeError("runtime canary observed_at must be finite float")
        expected = canonical_digest({
            "deployment_id": self.deployment_id,
            "deployment_generation": self.deployment_generation,
            "route_digest": self.route_digest,
            "role": self.role,
            "capability_id": self.capability_id,
            "input_schema_id": self.input_schema_id,
            "output_schema_id": self.output_schema_id,
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
            "verified_capabilities": self.verified_capabilities,
            "execution_mode": self.execution_mode,
            "stream_digest": self.stream_digest,
        })
        if self.evidence_digest and self.evidence_digest != expected:
            raise ValueError("runtime canary evidence digest mismatch")
        object.__setattr__(self, "evidence_digest", expected)


def evaluate_runtime_canary_contract(
    contract: RuntimeCanaryContract,
    *,
    text: str,
    finish_reason: str | None,
    tool_calls: JsonValue = (),
    content_blocks: JsonValue = (),
    stream_event_kinds: tuple[str, ...] = (),
    payload: JsonValue | None = None,
) -> bool:
    if type(text) is not str:
        return False
    if contract.require_non_empty_text and not text.strip():
        return False
    if contract.allowed_finish_reasons and finish_reason not in contract.allowed_finish_reasons:
        return False

    if not isinstance(tool_calls, tuple):
        return False
    tool_names: list[str] = []
    for call in tool_calls:
        if not isinstance(call, Mapping):
            return False
        function=call.get("function")
        if not isinstance(function, Mapping):
            return False
        name=function.get("name")
        if isinstance(name,str) and name:
            tool_names.append(name)
    if len(tool_calls) < contract.minimum_tool_calls:
        return False
    if any(name not in tool_names for name in contract.required_tool_names):
        return False

    if not isinstance(content_blocks, tuple):
        return False
    content_kinds = {
        block.get("kind")
        for block in content_blocks
        if isinstance(block, Mapping) and isinstance(block.get("kind"), str)
    }
    if any(
        kind not in content_kinds
        for kind in contract.required_content_block_kinds
    ):
        return False

    observed_stream_kinds=set(stream_event_kinds)
    if any(
        kind not in observed_stream_kinds
        for kind in contract.required_stream_event_kinds
    ):
        return False

    if contract.require_payload and payload is None:
        return False
    if contract.required_payload_keys:
        if not isinstance(payload, Mapping):
            return False
        if any(key not in payload for key in contract.required_payload_keys):
            return False
    if (
        contract.expected_payload_digest is not None
        and canonical_digest(payload) != contract.expected_payload_digest
    ):
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
