from __future__ import annotations

from dataclasses import dataclass
import os

from noetrium.contracts.systems.participant__method import (
    MethodIdentity,
    MethodRuntimeIdentity,
)
from noetrium.platform import bind_method_endpoint, run_local_shell_command


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


def test_local_shell_command_returns_typed_result() -> None:
    if os.name == "nt":
        command = "echo public-facade"
        expected_prefix = (os.environ.get("COMSPEC", "cmd.exe"), "/d", "/s", "/c")
    else:
        command = "printf public-facade"
        expected_prefix = ("/bin/sh", "-lc")
    result = run_local_shell_command(command, timeout_seconds=5)

    assert result.argv == (*expected_prefix, command)
    assert result.returncode == 0
    assert result.stdout.strip() == "public-facade"
    assert result.stderr == ""
