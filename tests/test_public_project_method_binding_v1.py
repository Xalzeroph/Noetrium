from __future__ import annotations

from dataclasses import dataclass
import os
import sys

from noetrium.contracts.systems.participant__method import (
    MethodIdentity,
    MethodRuntimeIdentity,
)
from noetrium.platform import bind_method_endpoint, run_local_command, run_local_shell_command


@dataclass(frozen=True)
class _Implementation:
    identity: MethodIdentity


@dataclass
class _Runtime:
    runtime_identity: MethodRuntimeIdentity

    def open_session(self, implementation, *, binding, session_id, services):
        raise AssertionError("the binding test must not open a session")


def test_method_endpoint_is_bound_through_public_facade() -> None:
    implementation = _Implementation(
        MethodIdentity("test.method", "v1", "abi1", "schema1")
    )
    runtime = _Runtime(
        MethodRuntimeIdentity("test.runtime", "v1", "abi1", "0" * 64)
    )

    endpoint = bind_method_endpoint(implementation, runtime)

    assert endpoint.identity == implementation.identity
    assert endpoint.runtime_identity == runtime.runtime_identity
    assert endpoint.binding.implementation == implementation.identity
    assert endpoint.binding.runtime == runtime.runtime_identity


def test_local_shell_command_returns_host_typed_result() -> None:
    command = "echo public-facade" if os.name == "nt" else "printf public-facade"
    result = run_local_shell_command(command, timeout_seconds=5)

    expected_argv = (
        ("cmd.exe", "/d", "/s", "/c", command)
        if os.name == "nt"
        else ("/bin/sh", "-c", command)
    )
    assert result.argv == expected_argv
    assert result.returncode == 0
    assert result.stdout.strip() == "public-facade"
    assert result.stderr == ""


def test_local_command_uses_exact_argv_without_shell_interpretation() -> None:
    result = run_local_command((sys.executable, "-c", "print('public-argv')"), timeout_seconds=5)

    assert result.returncode == 0
    assert result.argv[0] == sys.executable
    assert result.stdout.strip() == "public-argv"
    assert result.stderr == ""
