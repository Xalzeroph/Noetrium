from __future__ import annotations

import json
from pathlib import Path

import pytest

from noetrium_platform.capabilities.environment.minecraft.composition.server_service import (
    MinecraftServerServiceError,
)
from noetrium_platform.capabilities.environment.minecraft.runtime.errors import (
    MinecraftEnvironmentFailure,
)
from noetrium_platform.composition.environment_capabilities.minecraft_local import (
    LocalMinecraftLifetimeSessionController,
    _is_pre_agent_infrastructure_failure,
    _pre_agent_failure_evidence,
    _pre_agent_recovery_decision,
)
from noetrium_platform.infrastructure.resources.authority import (
    ResourceObservationNotReady,
)


def test_pre_agent_recovery_accepts_only_typed_infrastructure_failures() -> None:
    assert _is_pre_agent_infrastructure_failure(
        MinecraftServerServiceError("RCON readiness deadline expired")
    )
    assert _is_pre_agent_infrastructure_failure(
        ResourceObservationNotReady("not ready")
    )
    assert _is_pre_agent_infrastructure_failure(
        MinecraftEnvironmentFailure(
            "setup.verify",
            "physical postconditions did not converge",
            cause_code="MINECRAFT_SETUP_POSTCONDITION_FAILED",
        )
    )
    assert not _is_pre_agent_infrastructure_failure(ValueError("invalid task spec"))
    assert not _is_pre_agent_infrastructure_failure(
        MinecraftEnvironmentFailure(
            "act.validate",
            "invalid action",
            cause_code="MINECRAFT_ACTION_INVALID",
        )
    )


def test_pre_agent_recovery_rejects_mixed_exception_group() -> None:
    mixed = ExceptionGroup(
        "mixed",
        [
            MinecraftServerServiceError("transient"),
            ValueError("deterministic"),
        ],
    )
    assert not _is_pre_agent_infrastructure_failure(mixed)


def test_pre_agent_recovery_is_bounded_without_delay_policy() -> None:
    error = MinecraftServerServiceError("transient")
    assert _pre_agent_recovery_decision(error, attempt=1, max_attempts=3) == "retry"
    assert _pre_agent_recovery_decision(error, attempt=2, max_attempts=3) == "retry"
    assert _pre_agent_recovery_decision(error, attempt=3, max_attempts=3) == "exhausted"
    assert _pre_agent_recovery_decision(
        ValueError("bad config"), attempt=1, max_attempts=3
    ) == "fatal"
    with pytest.raises(ValueError):
        _pre_agent_recovery_decision(error, attempt=4, max_attempts=3)


def test_pre_agent_failure_evidence_preserves_typed_phase_and_code() -> None:
    error = MinecraftEnvironmentFailure(
        "setup.control.verify",
        "biome authority did not converge",
        cause_code="MINECRAFT_SETUP_CONTROL_POSTCONDITION_FAILED",
    )
    assert _pre_agent_failure_evidence(error) == ({
        "type": "MinecraftEnvironmentFailure",
        "message": str(error),
        "phase": "setup.control.verify",
        "cause_code": "MINECRAFT_SETUP_CONTROL_POSTCONDITION_FAILED",
    },)


def test_pre_agent_recovery_evidence_is_durable_and_bounded(tmp_path: Path) -> None:
    controller = LocalMinecraftLifetimeSessionController.__new__(
        LocalMinecraftLifetimeSessionController
    )
    controller.state_root = tmp_path
    controller.pre_agent_infrastructure_attempts = 3
    error = MinecraftServerServiceError("RCON readiness deadline expired")
    controller._record_pre_agent_recovery(
        lifetime_key="lifetime-key",
        attempt=1,
        status="retrying",
        scope_generation=7,
        resource_generations={"server": 4, "game-endpoint": 4},
        failure=error,
    )
    files = tuple(
        (tmp_path / "pre-agent-infrastructure-recovery" / "lifetime-key").glob(
            "*.json"
        )
    )
    assert len(files) == 1
    row = json.loads(files[0].read_text())
    assert row["schema"] == "noetrium.minecraft-pre-agent-infrastructure-recovery.v1"
    assert row["attempt"] == 1
    assert row["max_attempts"] == 3
    assert row["scope_generation"] == 7
    assert row["resource_generations"] == {"game-endpoint": 4, "server": 4}
    assert row["status"] == "retrying"
    assert row["failure"][0]["type"] == "MinecraftServerServiceError"
