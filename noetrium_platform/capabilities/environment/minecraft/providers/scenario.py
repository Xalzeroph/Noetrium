from __future__ import annotations

import re

from noetrium_platform.substrate.api import NoetriumUnit

from ..api import (
    MinecraftScenarioReceipt,
    MinecraftScenarioStepReceipt,
    MinecraftServerConsolePort,
    minecraft_response_sha256,
    minecraft_scenario_generation,
    minecraft_scenario_id,
    minecraft_scenario_step_command,
    minecraft_scenario_step_expected,
    minecraft_scenario_step_id,
    minecraft_scenario_step_timeout,
    minecraft_scenario_step_verification,
    minecraft_scenario_steps,
    require_minecraft_scenario,
)


_SCALAR = r"(?:true|false|[+-]?[0-9]+)"


def _scenario_response_matches(
    expected: str, response: str, verification_command: str | None
) -> bool:
    """Compare a gamerule readback by rule/value, retaining literal assertions elsewhere."""
    query = (verification_command or "").strip().lstrip("/").split()
    assignment = re.fullmatch(
        r"([A-Za-z][A-Za-z0-9_]*)\s*=\s*(" + _SCALAR + r")",
        expected.strip(),
        re.IGNORECASE,
    )
    if len(query) != 2 or query[0].casefold() != "gamerule" or assignment is None:
        return expected.casefold() in response.casefold()
    rule, wanted = assignment.groups()
    if rule.casefold() != query[1].casefold():
        return False
    observed = re.fullmatch(
        r"(?:Gamerule\s+"
        + re.escape(rule)
        + r"\s+is\s+(?:currently|now)\s+set\s+to:\s*|"
        + re.escape(rule)
        + r"\s*=\s*)("
        + _SCALAR
        + r")",
        response.strip(),
        re.IGNORECASE,
    )
    if observed is None:
        return False

    def scalar(value):
        return value.casefold() if value.casefold() in ("true", "false") else int(value)

    return scalar(wanted) == scalar(observed.group(1))


class MinecraftScenarioProvisioningError(RuntimeError):
    """A source-world scenario could not be proven exactly."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Minecraft scenario provisioning failed [{code}]: {message}")
        self.code = code


class RconMinecraftScenarioProvisioner:
    """Apply an immutable source-world scenario through the narrow RCON port."""

    def __init__(
        self,
        console: MinecraftServerConsolePort,
        scenario: NoetriumUnit,
    ) -> None:
        self.console = console
        self.scenario = require_minecraft_scenario(scenario)

    def apply(self) -> MinecraftScenarioReceipt:
        receipts: list[MinecraftScenarioStepReceipt] = []
        for step in minecraft_scenario_steps(self.scenario):
            step_id = minecraft_scenario_step_id(step)
            command = minecraft_scenario_step_command(step)
            expected_response = minecraft_scenario_step_expected(step)
            verification_command = minecraft_scenario_step_verification(step)
            timeout_s = minecraft_scenario_step_timeout(step)
            # A scenario mutation is issued exactly once. Even when a scenario
            # author believes a command is idempotent, the provider cannot infer
            # that safely for arbitrary RCON programs. Verification is a separate
            # read/assertion command and never triggers mutation replay.
            try:
                command_result = self.console.execute(command, timeout_s=timeout_s)
                verification_result = (
                    self.console.execute(verification_command, timeout_s=timeout_s)
                    if verification_command is not None
                    else command_result
                )
            except BaseException as exc:
                raise MinecraftScenarioProvisioningError(
                    "SCENARIO_COMMAND_FAILED",
                    f"step={step_id}: {type(exc).__name__}: {exc}",
                ) from exc
            if not _scenario_response_matches(
                expected_response, verification_result.response, verification_command
            ):
                raise MinecraftScenarioProvisioningError(
                    "SCENARIO_ASSERTION_FAILED",
                    (
                        f"step={step_id}: expected response fragment "
                        f"{expected_response!r} was not observed; "
                        f"actual_response={verification_result.response[:240]!r}; "
                        f"actual_response_sha256="
                        f"{minecraft_response_sha256(verification_result.response)}; "
                        f"verification_evidence_ref={verification_result.evidence_ref}"
                    ),
                )
            receipts.append(
                MinecraftScenarioStepReceipt(
                    step_id=step_id,
                    step_digest=step.unit_digest,
                    command_evidence_ref=command_result.evidence_ref,
                    command_response_sha256=minecraft_response_sha256(
                        command_result.response
                    ),
                    verification_evidence_ref=verification_result.evidence_ref,
                    verification_response_sha256=minecraft_response_sha256(
                        verification_result.response
                    ),
                )
            )
        return MinecraftScenarioReceipt(
            scenario_id=minecraft_scenario_id(self.scenario),
            generation=minecraft_scenario_generation(self.scenario),
            scenario_digest=self.scenario.unit_digest,
            steps=tuple(receipts),
        )


__all__ = ["MinecraftScenarioProvisioningError", "RconMinecraftScenarioProvisioner"]
