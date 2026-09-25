from __future__ import annotations

from dataclasses import dataclass


PI05_OPENPI_REPOSITORY = "Physical-Intelligence/openpi"
PI05_OPENPI_SOURCE_COMMIT = "8999e55c55ad43b976fa71949ec070ee0128a8bc"


@dataclass(frozen=True, slots=True)
class Pi05OpenPIFidelity:
    """OpenPI π0.5 source semantics pinned near the public 2025 release."""

    repository: str = PI05_OPENPI_REPOSITORY
    source_commit: str = PI05_OPENPI_SOURCE_COMMIT
    config_source: str = "src/openpi/models/pi0_config.py"
    model_contract_source: str = "src/openpi/models/model.py"
    model_type: str = "pi05"
    image_keys: tuple[str, ...] = (
        "base_0_rgb",
        "left_wrist_0_rgb",
        "right_wrist_0_rgb",
    )
    image_resolution: tuple[int, int] = (224, 224)
    action_dim: int = 32
    action_horizon: int = 50
    max_token_len: int = 200
    state_representation: str = "discrete_language_tokens"
    flow_timestep_injection: str = "action_expert_adaRMSNorm"
    action_representation: str = "continuous_float32_chunk"

    def __post_init__(self) -> None:
        if len(self.source_commit) != 40:
            raise ValueError("π0.5 source commit must be a full git SHA")
        if self.model_type != "pi05":
            raise ValueError("π0.5 model type drifted")
        if self.image_keys != ("base_0_rgb", "left_wrist_0_rgb", "right_wrist_0_rgb"):
            raise ValueError("π0.5 image-key contract drifted")
        if self.image_resolution != (224, 224):
            raise ValueError("π0.5 image resolution drifted")
        if (self.action_dim, self.action_horizon, self.max_token_len) != (32, 50, 200):
            raise ValueError("π0.5 action/token dimensions drifted")
        if self.state_representation != "discrete_language_tokens":
            raise ValueError("π0.5 discrete state representation drifted")
        if self.flow_timestep_injection != "action_expert_adaRMSNorm":
            raise ValueError("π0.5 flow-timestep injection drifted")
        if self.action_representation != "continuous_float32_chunk":
            raise ValueError("π0.5 action representation drifted")


PI05_OPENPI_FIDELITY = Pi05OpenPIFidelity()


__all__ = [
    "PI05_OPENPI_FIDELITY",
    "PI05_OPENPI_REPOSITORY",
    "PI05_OPENPI_SOURCE_COMMIT",
    "Pi05OpenPIFidelity",
]
