from __future__ import annotations

from dataclasses import dataclass, field
import math
from typing import Protocol, runtime_checkable

from noetrium_platform.evidence.artifact.content.api import TensorContentRef
from noetrium_platform.foundation.kernel.kernel import (
    JsonObject,
    JsonValue,
    canonical_digest,
    freeze_json,
    require_sha256,
)

from .fidelity import (
    MINECLIP_VARIANTS,
    MINEDOJO_REFERENCE_FIDELITY,
)
from .source import MINECLIP_AUDITED_COMMIT


MINECLIP_VIDEO_SCHEMA_ID = "minedojo.mineclip.video-clip.tensor.v1"


def _text(value: object, field_name: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field_name} must be non-empty text")
    return value.strip()


@dataclass(frozen=True, slots=True)
class MineClipRewardRequest:
    """One paper-semantics video-language reward query."""

    video: TensorContentRef
    task_prompt: str
    variant: str
    request_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.video, TensorContentRef):
            raise TypeError(
                "MineCLIP reward request video must be TensorContentRef"
            )
        if self.video.schema_id != MINECLIP_VIDEO_SCHEMA_ID:
            raise ValueError("MineCLIP video tensor schema drifted")
        if len(self.video.shape) != 4:
            raise ValueError(
                "MineCLIP video tensor must have [T,C,H,W] shape"
            )
        frames, channels, height, width = self.video.shape
        if not (
            1
            <= frames
            <= MINEDOJO_REFERENCE_FIDELITY.mineclip_temporal_max_sequence_length
        ):
            raise ValueError(
                "MineCLIP video length exceeds paper-release temporal bound"
            )
        if channels != 3:
            raise ValueError("MineCLIP video must contain RGB frames")
        if (
            height,
            width,
        ) != MINEDOJO_REFERENCE_FIDELITY.mineclip_input_resolution:
            raise ValueError("MineCLIP input resolution drifted")
        object.__setattr__(
            self,
            "task_prompt",
            _text(self.task_prompt, "MineCLIP task_prompt"),
        )
        if self.variant not in MINECLIP_VARIANTS:
            raise ValueError("MineCLIP variant must be attn or avg")
        object.__setattr__(
            self,
            "request_digest",
            canonical_digest({
                "video_tensor_digest": self.video.tensor_digest,
                "task_prompt": self.task_prompt,
                "variant": self.variant,
                "source_commit": MINECLIP_AUDITED_COMMIT,
            }),
        )


@dataclass(frozen=True, slots=True)
class MineClipRewardPrediction:
    """Provider result without inventing a normalized reward transformation.

    The released model API exposes video/text similarity logits. Any later
    shaping/normalization belongs to the paper-specific training/evaluation
    protocol rather than this model seam.
    """

    request_digest: str
    similarity_logit: float
    model_identity_digest: str
    receipt: JsonValue = None
    prediction_digest: str = field(init=False)

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "request_digest",
            require_sha256(
                self.request_digest,
                "MineCLIP reward request_digest",
            ),
        )
        if (
            isinstance(self.similarity_logit, bool)
            or not isinstance(self.similarity_logit, (int, float))
            or not math.isfinite(float(self.similarity_logit))
        ):
            raise ValueError(
                "MineCLIP similarity_logit must be finite numeric"
            )
        object.__setattr__(
            self,
            "similarity_logit",
            float(self.similarity_logit),
        )
        object.__setattr__(
            self,
            "model_identity_digest",
            require_sha256(
                self.model_identity_digest,
                "MineCLIP model_identity_digest",
            ),
        )
        object.__setattr__(self, "receipt", freeze_json(self.receipt))
        object.__setattr__(
            self,
            "prediction_digest",
            canonical_digest({
                "request_digest": self.request_digest,
                "similarity_logit": self.similarity_logit,
                "model_identity_digest": self.model_identity_digest,
                "receipt": self.receipt,
            }),
        )

    def payload(self) -> JsonObject:
        return {
            "request_digest": self.request_digest,
            "similarity_logit": self.similarity_logit,
            "model_identity_digest": self.model_identity_digest,
            "receipt": self.receipt,
            "prediction_digest": self.prediction_digest,
        }


@runtime_checkable
class MineClipRewardModelPort(Protocol):
    """Deployment-neutral MineCLIP inference seam."""

    @property
    def identity_digest(self) -> str: ...

    def score(
        self,
        request: MineClipRewardRequest,
    ) -> MineClipRewardPrediction: ...


@dataclass(frozen=True, slots=True)
class MineClipRewardBinding:
    model: MineClipRewardModelPort
    binding_digest: str = field(init=False)

    def __post_init__(self) -> None:
        if not isinstance(self.model, MineClipRewardModelPort):
            raise TypeError(
                "MineCLIP reward binding requires MineClipRewardModelPort"
            )
        require_sha256(
            self.model.identity_digest,
            "MineCLIP reward model identity_digest",
        )
        object.__setattr__(
            self,
            "binding_digest",
            canonical_digest({
                "source_commit": MINECLIP_AUDITED_COMMIT,
                "model_identity_digest": self.model.identity_digest,
                "video_schema_id": MINECLIP_VIDEO_SCHEMA_ID,
                "max_temporal_length": (
                    MINEDOJO_REFERENCE_FIDELITY
                    .mineclip_temporal_max_sequence_length
                ),
            }),
        )

    def score(
        self,
        request: MineClipRewardRequest,
    ) -> MineClipRewardPrediction:
        prediction = self.model.score(request)
        if not isinstance(prediction, MineClipRewardPrediction):
            raise TypeError(
                "MineCLIP model must return MineClipRewardPrediction"
            )
        if prediction.request_digest != request.request_digest:
            raise ValueError(
                "MineCLIP model response request identity drifted"
            )
        if prediction.model_identity_digest != self.model.identity_digest:
            raise ValueError(
                "MineCLIP model response implementation identity drifted"
            )
        return prediction


__all__ = [
    "MINECLIP_VIDEO_SCHEMA_ID",
    "MineClipRewardBinding",
    "MineClipRewardModelPort",
    "MineClipRewardPrediction",
    "MineClipRewardRequest",
]
