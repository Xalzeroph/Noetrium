from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceLaunchContract,
    ServiceLaunchPreflightReport,
)
from .environment import MaterializedServiceEnvironment


class ServiceLaunchPreflightError(RuntimeError):
    def __init__(self, report: ServiceLaunchPreflightReport) -> None:
        self.report = report
        super().__init__("service launch preflight failed: " + "; ".join(report.errors))


class LocalServiceLaunchPreflight:
    """Pure, side-effect-free launch validation for an exact service contract."""

    def __init__(self, *, required_paths: tuple[str, ...] = ()) -> None:
        self.required_paths = tuple(str(path) for path in required_paths)
        if any(not path for path in self.required_paths):
            raise ValueError("required service paths must be non-empty")
        if any(not Path(path).is_absolute() for path in self.required_paths):
            raise ValueError("required service paths must be absolute")
        if len(set(self.required_paths)) != len(self.required_paths):
            raise ValueError("required service paths must be unique")

    def inspect(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
    ) -> ServiceLaunchPreflightReport:
        if not isinstance(contract, ServiceLaunchContract):
            raise TypeError("service preflight contract must be typed")
        if not isinstance(environment, MaterializedServiceEnvironment):
            raise TypeError("service preflight environment must be typed")
        checks: list[tuple[str, bool]] = []
        errors: list[str] = []

        def check(name: str, passed: bool, error: str) -> None:
            checks.append((name, passed))
            if not passed:
                errors.append(error)

        executable = Path(contract.executable)
        cwd = Path(contract.cwd)
        check("executable", executable.is_file(), f"executable is not a file: {contract.executable}")
        check("cwd", cwd.is_dir(), f"service cwd is not a directory: {contract.cwd}")
        check(
            "environment_digest",
            environment.digest == contract.environment_digest,
            "materialized environment digest does not match launch contract",
        )
        for required_path in self.required_paths:
            path = Path(required_path)
            check("required:" + required_path, path.exists(), f"required service resource is missing: {required_path}")
        for index, arg in enumerate(contract.argv):
            check(
                f"argv[{index}]",
                "\x00" not in arg and bool(arg),
                f"service argv[{index}] is empty or contains NUL",
            )
        return ServiceLaunchPreflightReport(contract.digest(), tuple(checks), tuple(errors))

    def validate(
        self,
        contract: ServiceLaunchContract,
        environment: MaterializedServiceEnvironment,
    ) -> ServiceLaunchPreflightReport:
        report = self.inspect(contract, environment)
        if not report.ready:
            raise ServiceLaunchPreflightError(report)
        return report


__all__ = [
    "LocalServiceLaunchPreflight",
    "ServiceLaunchPreflightError",
    "ServiceLaunchPreflightReport",
]
