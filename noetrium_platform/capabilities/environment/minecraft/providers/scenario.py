from __future__ import annotations

from ..api import (
    MinecraftScenarioReceipt,
    MinecraftScenarioSpec,
    MinecraftScenarioStepReceipt,
    MinecraftServerConsolePort,
    minecraft_response_sha256,
)


class MinecraftScenarioProvisioningError(RuntimeError):
    """A source-world scenario could not be proven exactly."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Minecraft scenario provisioning failed [{code}]: {message}")
        self.code = code


class RconMinecraftScenarioProvisioner:
    """Apply an immutable source-world scenario through the narrow RCON port."""

    def __init__(self, console: MinecraftServerConsolePort, scenario: MinecraftScenarioSpec) -> None:
        self.console = console
        self.scenario = scenario

    def apply(self) -> MinecraftScenarioReceipt:
        receipts: list[MinecraftScenarioStepReceipt] = []
        for step in self.scenario.steps:
            try:
                command_result = self.console.execute(step.command, timeout_s=step.timeout_s)
                verification_result = (
                    self.console.execute(step.verification_command, timeout_s=step.timeout_s)
                    if step.verification_command is not None
                    else command_result
                )
            except BaseException as exc:
                raise MinecraftScenarioProvisioningError(
                    "SCENARIO_COMMAND_FAILED",
                    f"step={step.step_id}: {type(exc).__name__}: {exc}",
                ) from exc
            expected = step.expected_response_contains.casefold()
            if expected not in verification_result.response.casefold():
                raise MinecraftScenarioProvisioningError(
                    "SCENARIO_ASSERTION_FAILED",
                    (
                        f"step={step.step_id}: expected response fragment "
                        f"{step.expected_response_contains!r} was not observed"
                    ),
                )
            receipts.append(
                MinecraftScenarioStepReceipt(
                    step_id=step.step_id,
                    step_digest=step.digest(),
                    command_evidence_ref=command_result.evidence_ref,
                    command_response_sha256=minecraft_response_sha256(command_result.response),
                    verification_evidence_ref=verification_result.evidence_ref,
                    verification_response_sha256=minecraft_response_sha256(
                        verification_result.response
                    ),
                )
            )
        return MinecraftScenarioReceipt(
            scenario_id=self.scenario.scenario_id,
            generation=self.scenario.generation,
            scenario_digest=self.scenario.digest(),
            steps=tuple(receipts),
        )


__all__ = ["MinecraftScenarioProvisioningError", "RconMinecraftScenarioProvisioner"]
