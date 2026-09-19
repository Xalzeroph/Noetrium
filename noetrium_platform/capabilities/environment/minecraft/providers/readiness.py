from __future__ import annotations

import json
import re
import socket
import subprocess
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Protocol

from noetrium_platform.infrastructure.lifecycle.toolchain.api import (
    RuntimeToolchainError,
    parse_java_major as parse_runtime_java_major,
)
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception


@dataclass(frozen=True, slots=True)
class MinecraftReadinessProbe:
    """One reproducible readiness observation with an actionable cause code."""

    name: str
    ok: bool
    phase: str
    cause_code: str
    detail: str
    command: tuple[str, ...] = ()

    def as_dict(self) -> dict[str, object]:
        return asdict(self)


class MinecraftReadinessError(RuntimeError):
    """Raised only when a readiness input is malformed, not when a probe fails."""


class MinecraftReadinessCommandRunner(Protocol):
    def __call__(
        self,
        command: list[str],
        *,
        cwd: str | None,
        check: bool,
        capture_output: bool,
        text: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[str]: ...


@dataclass(frozen=True, slots=True)
class _CommandAttempt:
    result: subprocess.CompletedProcess[str] | None
    failure: str | None = None


def _safe_exception_message(exc: BaseException) -> str:
    descriptor = describe_exception(exc)
    return f"{descriptor.error_type}[{descriptor.error_digest[:16]}]"


def parse_node_major(version_text: str) -> int:
    match = re.fullmatch(r"v?(\d+)(?:\.\d+){0,2}", version_text.strip())
    if not match:
        raise MinecraftReadinessError(f"unrecognized Node version: {version_text!r}")
    return int(match.group(1))


def parse_java_major(version_text: str) -> int:
    try:
        return parse_runtime_java_major(version_text)
    except RuntimeToolchainError as exc:
        raise MinecraftReadinessError(_safe_exception_message(exc)) from exc


def _run(
    command: Sequence[str],
    *,
    cwd: str | Path | None = None,
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> _CommandAttempt:
    try:
        return _CommandAttempt(
            runner(
                list(command),
                cwd=str(cwd) if cwd is not None else None,
                check=False,
                capture_output=True,
                text=True,
                timeout=10,
            )
        )
    except Exception as exc:
        return _CommandAttempt(None, _safe_exception_message(exc))


def probe_node(
    *,
    minimum_major: int = 22,
    command: Sequence[str] = ("node", "--version"),
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> MinecraftReadinessProbe:
    command_tuple = tuple(command)
    attempt = _run(command_tuple, runner=runner)
    result = attempt.result
    if result is None:
        return MinecraftReadinessProbe(
            "node", False, "runtime", "NODE_NOT_EXECUTABLE", f"Node command could not be executed; failure={attempt.failure}", command_tuple
        )
    text = (result.stdout or result.stderr).strip()
    if result.returncode != 0:
        return MinecraftReadinessProbe(
            "node", False, "runtime", "NODE_COMMAND_FAILED", f"rc={result.returncode}: {text}", command_tuple
        )
    try:
        major = parse_node_major(text)
    except MinecraftReadinessError as exc:
        return MinecraftReadinessProbe("node", False, "runtime", "NODE_VERSION_INVALID", _safe_exception_message(exc), command_tuple)
    ok = major >= minimum_major
    return MinecraftReadinessProbe(
        "node",
        ok,
        "runtime",
        "OK" if ok else "NODE_VERSION_TOO_OLD",
        f"{text}; required >= v{minimum_major}",
        command_tuple,
    )


def probe_java(
    *,
    minimum_major: int = 21,
    command: Sequence[str] = ("java", "-version"),
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> MinecraftReadinessProbe:
    command_tuple = tuple(command)
    attempt = _run(command_tuple, runner=runner)
    result = attempt.result
    if result is None:
        return MinecraftReadinessProbe(
            "java", False, "runtime", "JAVA_NOT_EXECUTABLE", f"Java command could not be executed; failure={attempt.failure}", command_tuple
        )
    text = (result.stderr or result.stdout).strip()
    try:
        major = parse_java_major(text)
    except MinecraftReadinessError as exc:
        return MinecraftReadinessProbe("java", False, "runtime", "JAVA_VERSION_INVALID", _safe_exception_message(exc), command_tuple)
    ok = result.returncode == 0 and major >= minimum_major
    code = "OK" if ok else "JAVA_VERSION_TOO_OLD" if major < minimum_major else "JAVA_COMMAND_FAILED"
    return MinecraftReadinessProbe(
        "java", ok, "runtime", code, f"{text.splitlines()[0] if text else '<empty>'}; required >= {minimum_major}", command_tuple
    )


def probe_node_package(
    bridge_dir: str | Path,
    *,
    package_name: str,
    expected_version: str | None = None,
    node_command: str = "node",
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> MinecraftReadinessProbe:
    package_literal = json.dumps(package_name)
    script = (
        "const fs=require('fs'),path=require('path');"
        f"const expected={package_literal};"
        "let current=path.dirname(require.resolve(expected)),found=null;"
        "while(true){const candidate=path.join(current,'package.json');"
        "if(fs.existsSync(candidate)){const value=JSON.parse(fs.readFileSync(candidate,'utf8'));"
        "if(value.name===expected){found=value;break;}}"
        "const parent=path.dirname(current);if(parent===current)break;current=parent;}"
        "if(!found)throw new Error('package metadata not found for '+expected);"
        "process.stdout.write(String(found.version||''));"
    )
    command = (node_command, "-e", script)
    attempt = _run(command, cwd=bridge_dir, runner=runner)
    result = attempt.result
    if result is None:
        return MinecraftReadinessProbe(
            package_name, False, "dependencies", "PACKAGE_PROBE_FAILED", f"dependency probe could not execute; failure={attempt.failure}", command
        )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        return MinecraftReadinessProbe(
            package_name,
            False,
            "dependencies",
            "PACKAGE_NOT_RESOLVABLE",
            detail[0] if detail else "module resolution failed",
            command,
        )
    version = result.stdout.strip()
    ok = bool(version) and (expected_version is None or version == expected_version)
    code = "OK" if ok else "PACKAGE_VERSION_MISMATCH" if version else "PACKAGE_VERSION_EMPTY"
    return MinecraftReadinessProbe(
        package_name,
        ok,
        "dependencies",
        code,
        f"resolved {version or '<empty>'}" + (f"; expected {expected_version}" if expected_version else ""),
        command,
    )


def probe_pathfinder(
    bridge_dir: str | Path,
    *,
    expected_version: str = "2.4.5",
    node_command: str = "node",
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> MinecraftReadinessProbe:
    result = probe_node_package(
        bridge_dir,
        package_name="mineflayer-pathfinder",
        expected_version=expected_version,
        node_command=node_command,
        runner=runner,
    )
    return MinecraftReadinessProbe(
        "mineflayer_pathfinder", result.ok, result.phase, result.cause_code, result.detail, result.command
    )


def probe_minecraft_protocol_version(
    bridge_dir: str | Path,
    *,
    minecraft_version: str,
    node_command: str = "node",
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> MinecraftReadinessProbe:
    if not minecraft_version.strip() or len(minecraft_version) > 64:
        raise MinecraftReadinessError("Minecraft version probe requires a bounded version")
    script = (
        "const p=require('minecraft-protocol');"
        "const versions=Array.isArray(p.supportedVersions)?p.supportedVersions:[];"
        f"process.stdout.write(JSON.stringify({{requested:{minecraft_version!r},versions}}));"
    )
    command = (node_command, "-e", script)
    attempt = _run(command, cwd=bridge_dir, runner=runner)
    result = attempt.result
    if result is None or result.returncode != 0:
        detail = (f"probe could not execute; failure={attempt.failure}" if result is None else (result.stderr or result.stdout).strip())
        return MinecraftReadinessProbe(
            "minecraft_protocol_version",
            False,
            "dependencies",
            "PROTOCOL_VERSION_PROBE_FAILED",
            detail or "minecraft-protocol module resolution failed",
            command,
        )
    try:
        payload = json.loads(result.stdout)
        versions = payload["versions"]
        ok = isinstance(versions, list) and minecraft_version in versions
    except (json.JSONDecodeError, KeyError, TypeError):
        return MinecraftReadinessProbe(
            "minecraft_protocol_version",
            False,
            "dependencies",
            "PROTOCOL_VERSION_OUTPUT_INVALID",
            "minecraft-protocol support probe returned invalid JSON",
            command,
        )
    return MinecraftReadinessProbe(
        "minecraft_protocol_version",
        ok,
        "dependencies",
        "OK" if ok else "MINECRAFT_VERSION_UNSUPPORTED",
        f"requested {minecraft_version}; supported={','.join(str(value) for value in versions)}",
        command,
    )


def probe_tcp(host: str, port: int, *, timeout_s: float = 2.0) -> MinecraftReadinessProbe:
    try:
        with socket.create_connection((host, port), timeout=timeout_s):
            pass
    except OSError as exc:
        return MinecraftReadinessProbe(
            "minecraft_server", False, "server", "SERVER_TCP_UNREACHABLE", f"{host}:{port}: {exc}"
        )
    return MinecraftReadinessProbe(
        "minecraft_server", True, "server", "OK", f"{host}:{port} accepted TCP connection"
    )


def minecraft_preflight(
    bridge_dir: str | Path,
    *,
    host: str,
    port: int,
    check_server: bool = True,
    node_command: str = "node",
    java_command: str = "java",
    check_java: bool = True,
    minecraft_version: str | None = None,
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> tuple[MinecraftReadinessProbe, ...]:
    results = [
        probe_node(command=(node_command, "--version"), runner=runner),
    ]
    if check_java:
        results.append(probe_java(command=(java_command, "-version"), runner=runner))
    results.extend(
        [
            probe_node_package(
                bridge_dir,
                package_name="mineflayer",
                expected_version="4.37.1",
                node_command=node_command,
                runner=runner,
            ),
            probe_pathfinder(bridge_dir, node_command=node_command, runner=runner),
            probe_node_package(
                bridge_dir,
                package_name="mineflayer-pvp",
                expected_version="1.3.2",
                node_command=node_command,
                runner=runner,
            ),
            probe_node_package(
                bridge_dir,
                package_name="vec3",
                expected_version="0.1.8",
                node_command=node_command,
                runner=runner,
            ),
        ]
    )
    if minecraft_version is not None:
        results.append(
            probe_minecraft_protocol_version(
                bridge_dir,
                minecraft_version=minecraft_version,
                node_command=node_command,
                runner=runner,
            )
        )
    if check_server:
        results.append(probe_tcp(host, port))
    return tuple(results)


def report_json(results: Sequence[MinecraftReadinessProbe]) -> str:
    return json.dumps(
        {"ok": all(result.ok for result in results), "results": [result.as_dict() for result in results]},
        ensure_ascii=False,
        indent=2,
    )


__all__ = [
    "MinecraftReadinessError",
    "MinecraftReadinessProbe",
    "minecraft_preflight",
    "parse_java_major",
    "parse_node_major",
    "probe_java",
    "probe_minecraft_protocol_version",
    "probe_mineflayer",
    "probe_node",
    "probe_node_package",
    "probe_pathfinder",
    "probe_tcp",
    "report_json",
]


def probe_mineflayer(
    bridge_dir: str | Path,
    *,
    expected_version: str = "4.37.1",
    node_command: str = "node",
    runner: MinecraftReadinessCommandRunner = subprocess.run,
) -> MinecraftReadinessProbe:
    return probe_node_package(
        bridge_dir,
        package_name="mineflayer",
        expected_version=expected_version,
        node_command=node_command,
        runner=runner,
    )
