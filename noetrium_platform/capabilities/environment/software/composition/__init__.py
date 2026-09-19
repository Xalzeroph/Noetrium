from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandRunnerPort

from ..api import SoftwareEnvironmentSpec
from ..providers import LocalRepositorySoftwareProvider


def build_local_repository_software_provider(
    *,
    root: str | Path,
    spec: SoftwareEnvironmentSpec,
    command_runner: LocalCommandRunnerPort,
    command_runner_identity_digest: str,
) -> LocalRepositorySoftwareProvider:
    """Compose the software provider over the platform process authority."""

    return LocalRepositorySoftwareProvider(
        root=root,
        spec=spec,
        command_runner=command_runner,
        command_runner_identity_digest=command_runner_identity_digest,
    )


__all__ = ["build_local_repository_software_provider"]
