from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
import math
from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.content.api import TensorContentRef
from noetrium_platform.foundation.kernel.kernel import (
    ExecutionContext,
    JsonObject,
    canonical_digest,
    thaw_json,
)
from noetrium_platform.research.execution.workflow.api import (
    MethodAgentRequest,
    MethodAgentResult,
)

from .fidelity import VIMA_REFERENCE_FIDELITY
from .source import VIMA_POLICY_AUDITED_COMMIT


VIMA_POLICY_AGENT_ID = "vima.policy"
_PROMPT_TOKEN_SCHEMA = "vima.prompt-token.tensor.v1"
_PROMPT_MASK_SCHEMA = "vima.prompt-mask.tensor.v1"
_OBSERVATION_TOKEN_SCHEMA = "vima.observation-token.tensor.v1"
_OBSERVATION_MASK_SCHEMA = "vima.observation-mask.tensor.v1"
_ACTION_TOKEN_SCHEMA = "vima.action-token.tensor.v1"


def _finite(value: object, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise TypeError(f"{field_name} must be numeric")
    parsed = float(value)
    if not math.isfinite(parsed):
        raise ValueError(f"{field_name} must be finite")
    return parsed


def _int_tuple(
    value: object,
    *,
    length: int,
    field_name: str,
) -> tuple[int, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be an integer sequence")
    row = tuple(value)
    if len(row) != length or any(type(item) is not int for item in row):
        raise TypeError(
            f"{field_name} must contain exactly {length} integers"
        )
    return row


def _float_tuple(
    value: object,
    *,
    length: int,
    field_name: str,
) -> tuple[float, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a numeric sequence")
    row = tuple(
        _finite(item, f"{field_name} component")
        for item in value
    )
    if len(row) != length:
        raise ValueError(
            f"{field_name} must contain exactly {length} values"
        )
    return row


def _tensor_ref(
    value: object,
    *,
    schema_id: str,
    field_name: str,
) -> TensorContentRef:
    if not isinstance(value, Mapping):
        raise TypeError(f"{field_name} must be a tensor reference")
    decoded = thaw_json(value)
    if not isinstance(decoded, dict):
        raise TypeError(f"{field_name} must decode to an object")
    ref = TensorContentRef.from_payload(decoded)
    if ref.schema_id != schema_id:
        raise ValueError(f"{field_name} tensor schema drifted")
    return ref


def _tensor_refs(
    value: object,
    *,
    schema_id: str,
    field_name: str,
) -> tuple[TensorContentRef, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(
        value,
        Sequence,
    ):
        raise TypeError(f"{field_name} must be a tensor-ref sequence")
    return tuple(
        _tensor_ref(
            item,
            schema_id=schema_id,
            field_name=field_name,
        )
        for item in value
    )


@dataclass(frozen=True, slots=True)
class VimaActionBounds:
    low: tuple[float, float]
    high: tuple[float, float]

    def __post_init__(self) -> None:
        low = _float_tuple(
            self.low,
            length=2,
            field_name="VIMA action bounds low",
        )
        high = _float_tuple(
            self.high,
            length=2,
            field_name="VIMA action bounds high",
        )
        if any(lower > upper for lower, upper in zip(low, high)):
            raise ValueError("VIMA action bounds must be ordered")
        object.__setattr__(self, "low", low)
        object.__setattr__(self, "high", high)

    def payload(self) -> JsonObject:
        return {"low": self.low, "high": self.high}

    @classmethod
    def from_payload(cls, value: object) -> "VimaActionBounds":
        if not isinstance(value, Mapping):
            raise TypeError("VIMA action bounds must be an object")
        return cls(
            low=_float_tuple(
                value.get("low"),
                length=2,
                field_name="VIMA action bounds low",
            ),
            high=_float_tuple(
                value.get("high"),
                length=2,
                field_name="VIMA action bounds high",
            ),
        )


@dataclass(frozen=True, slots=True)
class VimaDiscreteAction:
    pose0_position: tuple[int, int]
    pose0_rotation: tuple[int, int, int, int]
    pose1_position: tuple[int, int]
    pose1_rotation: tuple[int, int, int, int]

    def __post_init__(self) -> None:
        position_bins = VIMA_REFERENCE_FIDELITY.pose_position_bins
        rotation_bins = VIMA_REFERENCE_FIDELITY.pose_rotation_bins
        for name in ("pose0_position", "pose1_position"):
            value = _int_tuple(
                getattr(self, name),
                length=2,
                field_name=f"VIMA {name}",
            )
            if any(
                item < 0 or item >= limit
                for item, limit in zip(value, position_bins)
            ):
                raise ValueError(f"VIMA {name} index is outside decoder bins")
            object.__setattr__(self, name, value)
        for name in ("pose0_rotation", "pose1_rotation"):
            value = _int_tuple(
                getattr(self, name),
                length=4,
                field_name=f"VIMA {name}",
            )
            if any(
                item < 0 or item >= limit
                for item, limit in zip(value, rotation_bins)
            ):
                raise ValueError(f"VIMA {name} index is outside decoder bins")
            object.__setattr__(self, name, value)

    def payload(self) -> JsonObject:
        return {
            "pose0_position": self.pose0_position,
            "pose0_rotation": self.pose0_rotation,
            "pose1_position": self.pose1_position,
            "pose1_rotation": self.pose1_rotation,
        }

    @classmethod
    def from_payload(cls, value: object) -> "VimaDiscreteAction":
        if not isinstance(value, Mapping):
            raise TypeError("VIMA discrete action must be an object")
        return cls(
            pose0_position=_int_tuple(
                value.get("pose0_position"),
                length=2,
                field_name="VIMA pose0_position",
            ),
            pose0_rotation=_int_tuple(
                value.get("pose0_rotation"),
                length=4,
                field_name="VIMA pose0_rotation",
            ),
            pose1_position=_int_tuple(
                value.get("pose1_position"),
                length=2,
                field_name="VIMA pose1_position",
            ),
            pose1_rotation=_int_tuple(
                value.get("pose1_rotation"),
                length=4,
                field_name="VIMA pose1_rotation",
            ),
        )


@dataclass(frozen=True, slots=True)
class VimaContinuousAction:
    pose0_position: tuple[float, float]
    pose0_rotation: tuple[float, float, float, float]
    pose1_position: tuple[float, float]
    pose1_rotation: tuple[float, float, float, float]

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "pose0_position",
            _float_tuple(
                self.pose0_position,
                length=2,
                field_name="VIMA continuous pose0_position",
            ),
        )
        object.__setattr__(
            self,
            "pose1_position",
            _float_tuple(
                self.pose1_position,
                length=2,
                field_name="VIMA continuous pose1_position",
            ),
        )
        object.__setattr__(
            self,
            "pose0_rotation",
            _float_tuple(
                self.pose0_rotation,
                length=4,
                field_name="VIMA continuous pose0_rotation",
            ),
        )
        object.__setattr__(
            self,
            "pose1_rotation",
            _float_tuple(
                self.pose1_rotation,
                length=4,
                field_name="VIMA continuous pose1_rotation",
            ),
        )

    def payload(self) -> JsonObject:
        return {
            "pose0_position": self.pose0_position,
            "pose0_rotation": self.pose0_rotation,
            "pose1_position": self.pose1_position,
            "pose1_rotation": self.pose1_rotation,
        }


def de_discretize_vima_action(
    action: VimaDiscreteAction,
    bounds: VimaActionBounds,
) -> VimaContinuousAction:
    """Reproduce the camera-ready inference post-processing exactly."""

    if not isinstance(action, VimaDiscreteAction):
        raise TypeError("VIMA action must be VimaDiscreteAction")
    if not isinstance(bounds, VimaActionBounds):
        raise TypeError("VIMA bounds must be VimaActionBounds")

    position_bins = VIMA_REFERENCE_FIDELITY.pose_position_bins
    rotation_bins = VIMA_REFERENCE_FIDELITY.pose_rotation_bins

    def position(row: tuple[int, int]) -> tuple[float, float]:
        normalized = tuple(
            value / bins
            for value, bins in zip(row, position_bins)
        )
        scaled = tuple(
            value * (upper - lower) + lower
            for value, lower, upper in zip(
                normalized,
                bounds.low,
                bounds.high,
            )
        )
        return tuple(
            min(max(value, lower), upper)
            for value, lower, upper in zip(
                scaled,
                bounds.low,
                bounds.high,
            )
        )

    def rotation(
        row: tuple[int, int, int, int],
    ) -> tuple[float, float, float, float]:
        normalized = tuple(
            value / bins
            for value, bins in zip(row, rotation_bins)
        )
        scaled = tuple(value * 2.0 - 1.0 for value in normalized)
        return tuple(min(max(value, -1.0), 1.0) for value in scaled)

    return VimaContinuousAction(
        pose0_position=position(action.pose0_position),
        pose0_rotation=rotation(action.pose0_rotation),
        pose1_position=position(action.pose1_position),
        pose1_rotation=rotation(action.pose1_rotation),
    )


@dataclass(frozen=True, slots=True)
class VimaPolicyRequest:
    prompt_token_ref: TensorContentRef
    prompt_mask_ref: TensorContentRef
    observation_token_refs: tuple[TensorContentRef, ...]
    observation_mask_refs: tuple[TensorContentRef, ...]
    action_token_refs: tuple[TensorContentRef, ...]
    step_index: int

    def __post_init__(self) -> None:
        if self.prompt_token_ref.schema_id != _PROMPT_TOKEN_SCHEMA:
            raise ValueError("VIMA prompt token schema drifted")
        if self.prompt_mask_ref.schema_id != _PROMPT_MASK_SCHEMA:
            raise ValueError("VIMA prompt mask schema drifted")
        if any(
            ref.schema_id != _OBSERVATION_TOKEN_SCHEMA
            for ref in self.observation_token_refs
        ):
            raise ValueError("VIMA observation token schema drifted")
        if any(
            ref.schema_id != _OBSERVATION_MASK_SCHEMA
            for ref in self.observation_mask_refs
        ):
            raise ValueError("VIMA observation mask schema drifted")
        if any(
            ref.schema_id != _ACTION_TOKEN_SCHEMA
            for ref in self.action_token_refs
        ):
            raise ValueError("VIMA action token schema drifted")
        if (
            len(self.observation_token_refs)
            != len(self.observation_mask_refs)
        ):
            raise ValueError(
                "VIMA observation tokens and masks must align"
            )
        if (
            len(self.observation_token_refs)
            != len(self.action_token_refs) + 1
        ):
            raise ValueError(
                "VIMA policy requires one more observation than "
                "historical action tokens"
            )
        if type(self.step_index) is not int or self.step_index < 0:
            raise ValueError("VIMA step_index must be non-negative")
        if self.step_index != len(self.action_token_refs):
            raise ValueError(
                "VIMA step_index must equal action-history length"
            )

    @property
    def request_digest(self) -> str:
        return canonical_digest({
            "prompt_token_digest": self.prompt_token_ref.tensor_digest,
            "prompt_mask_digest": self.prompt_mask_ref.tensor_digest,
            "observation_token_digests": tuple(
                ref.tensor_digest for ref in self.observation_token_refs
            ),
            "observation_mask_digests": tuple(
                ref.tensor_digest for ref in self.observation_mask_refs
            ),
            "action_token_digests": tuple(
                ref.tensor_digest for ref in self.action_token_refs
            ),
            "step_index": self.step_index,
        })


@dataclass(frozen=True, slots=True)
class VimaPolicyPrediction:
    action: VimaDiscreteAction
    action_token_ref: TensorContentRef
    model_receipt: JsonObject

    def __post_init__(self) -> None:
        if not isinstance(self.action, VimaDiscreteAction):
            raise TypeError(
                "VIMA prediction action must be VimaDiscreteAction"
            )
        if (
            not isinstance(self.action_token_ref, TensorContentRef)
            or self.action_token_ref.schema_id != _ACTION_TOKEN_SCHEMA
        ):
            raise ValueError(
                "VIMA prediction requires action-token tensor ref"
            )
        if not isinstance(self.model_receipt, Mapping):
            raise TypeError("VIMA model_receipt must be an object")


@runtime_checkable
class VimaPolicyModelPort(Protocol):
    @property
    def identity_digest(self) -> str: ...

    def predict(
        self,
        request: VimaPolicyRequest,
        context: ExecutionContext,
    ) -> VimaPolicyPrediction: ...


class VimaPolicyAgentLoop:
    """Paper-owned VIMA autoregressive policy seam.

    Model weights/device execution and tensor materialization live behind
    VimaPolicyModelPort. This loop owns only the released sequence/history and
    action post-processing semantics.
    """

    def __init__(self, model: VimaPolicyModelPort) -> None:
        if not isinstance(model, VimaPolicyModelPort):
            raise TypeError("VIMA agent loop requires VimaPolicyModelPort")
        self._model = model

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "source_commit": VIMA_POLICY_AUDITED_COMMIT,
            "model_identity_digest": self._model.identity_digest,
            "history": "prompt+(obs,action)* autoregressive",
            "action_postprocess": "camera-ready-example",
            "implementation_revision": 1,
        })

    def run(self, request: MethodAgentRequest) -> MethodAgentResult:
        if request.agent_id != VIMA_POLICY_AGENT_ID:
            raise ValueError(
                f"unexpected VIMA agent id: {request.agent_id}"
            )
        view = thaw_json(request.view)
        if not isinstance(view, dict):
            raise TypeError("VIMA agent view must be an object")

        policy_request = VimaPolicyRequest(
            prompt_token_ref=_tensor_ref(
                view.get("prompt_token_ref"),
                schema_id=_PROMPT_TOKEN_SCHEMA,
                field_name="VIMA prompt_token_ref",
            ),
            prompt_mask_ref=_tensor_ref(
                view.get("prompt_mask_ref"),
                schema_id=_PROMPT_MASK_SCHEMA,
                field_name="VIMA prompt_mask_ref",
            ),
            observation_token_refs=_tensor_refs(
                view.get("observation_token_refs", ()),
                schema_id=_OBSERVATION_TOKEN_SCHEMA,
                field_name="VIMA observation_token_refs",
            ),
            observation_mask_refs=_tensor_refs(
                view.get("observation_mask_refs", ()),
                schema_id=_OBSERVATION_MASK_SCHEMA,
                field_name="VIMA observation_mask_refs",
            ),
            action_token_refs=_tensor_refs(
                view.get("action_token_refs", ()),
                schema_id=_ACTION_TOKEN_SCHEMA,
                field_name="VIMA action_token_refs",
            ),
            step_index=int(view.get("step_index", 0)),
        )
        prediction = self._model.predict(
            policy_request,
            request.context,
        )
        if not isinstance(prediction, VimaPolicyPrediction):
            raise TypeError(
                "VIMA model must return VimaPolicyPrediction"
            )

        bounds = VimaActionBounds.from_payload(
            view.get("action_bounds")
        )
        continuous = de_discretize_vima_action(
            prediction.action,
            bounds,
        )
        prior_action_refs = tuple(
            ref.payload()
            for ref in policy_request.action_token_refs
        )
        action_refs = (
            *prior_action_refs,
            prediction.action_token_ref.payload(),
        )
        return MethodAgentResult(
            value={
                "step_index": policy_request.step_index,
                "policy_request_digest": (
                    policy_request.request_digest
                ),
                "discrete_action": prediction.action.payload(),
                "action": continuous.payload(),
                "action_token_ref": (
                    prediction.action_token_ref.payload()
                ),
                "model_receipt": prediction.model_receipt,
            },
            state_update={
                "pending_action": continuous.payload(),
                "pending_discrete_action": (
                    prediction.action.payload()
                ),
                "action_token_refs": action_refs,
                "last_policy_request_digest": (
                    policy_request.request_digest
                ),
                "last_model_receipt": prediction.model_receipt,
            },
        )


__all__ = [
    "VIMA_POLICY_AGENT_ID",
    "VimaActionBounds",
    "VimaContinuousAction",
    "VimaDiscreteAction",
    "VimaPolicyAgentLoop",
    "VimaPolicyModelPort",
    "VimaPolicyPrediction",
    "VimaPolicyRequest",
    "de_discretize_vima_action",
]
