from __future__ import annotations

import shlex

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerConnectionPort
from noetrium_platform.infrastructure.lifecycle.server.api import ServerOperationEffect

from ..api import ServerHealthProbePort, ServerHealthReport, ServerRuntimeHealthSpec


def _line_command(executable: str, *arguments: str) -> str:
    return shlex.join((executable, *arguments))


def _inotify_probe_script() -> str:
    return """import ctypes, os, sys
status = 'not_required'
if sys.platform.startswith('linux'):
    status = 'unavailable'
    try:
        libc = ctypes.CDLL(None, use_errno=True)
        init = libc.inotify_init1
        add_watch = libc.inotify_add_watch
        init.argtypes = [ctypes.c_int]
        init.restype = ctypes.c_int
        add_watch.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_uint32]
        add_watch.restype = ctypes.c_int
        fd = int(init(os.O_NONBLOCK | getattr(os, 'O_CLOEXEC', 0)))
        if fd >= 0:
            try:
                watch = int(add_watch(fd, os.fsencode('/tmp'), 0x00000FC0))
                if watch >= 0:
                    status = 'available'
            finally:
                os.close(fd)
    except (AttributeError, OSError, TypeError):
        pass
print(status)"""


class SSHServerHealthProbe(ServerHealthProbePort):
    """Collect connectivity and managed-runtime facts through SSH."""

    BASIC_COMMAND = (
        "printf 'host='; hostname; "
        "printf 'python='; python3 --version 2>&1; "
        "printf 'git='; git --version 2>&1; "
        "printf 'tmux='; tmux -V 2>&1; "
        "printf 'disk='; df -h / /data 2>&1"
    )

    @staticmethod
    def _managed_command(specification: ServerRuntimeHealthSpec) -> str:
        checks = (
            ("remote_home", "directory", specification.remote_home),
            ("platform_root", "directory", specification.platform_root),
            ("release_root", "directory", specification.release_root),
            ("repository_root", "directory", specification.repository_root),
            ("python_executable", "executable", specification.python_executable),
            ("node_executable", "executable", specification.node_executable),
            ("java_executable", "executable", specification.java_executable),
            ("platform_management_executable", "executable", specification.platform_management_executable),
            ("tmux_executable", "executable", specification.tmux_executable),
            ("sha256sum_executable", "executable", specification.sha256sum_executable),
        )
        parts = [
            "set +e",
            "printf 'host='; hostname 2>&1",
            f"python_version=$({_line_command(specification.python_executable, '--version')} 2>&1); printf 'python_version=%s\\n' \"$python_version\"",
            f"inotify_watch_authority=$({_line_command(specification.python_executable, '-c', _inotify_probe_script())} 2>/dev/null); printf 'inotify_watch_authority=%s\\n' \"$inotify_watch_authority\"",
            "python_packages_probe=$(mktemp); "
            f"{_line_command(specification.python_executable, '-m', 'pip', 'freeze', '--all')} >\"$python_packages_probe\" 2>&1; "
            "python_packages_status=$?; "
            f"if test \"$python_packages_status\" -eq 0; then python_packages_digest=$(LC_ALL=C sort \"$python_packages_probe\" | {_line_command(specification.sha256sum_executable)}); else python_packages_digest=UNAVAILABLE; fi; "
            "rm -f -- \"$python_packages_probe\"; "
            "printf 'python_packages_status=%s\\n' \"$python_packages_status\"; "
            "printf 'python_packages_digest=%s\\n' \"$python_packages_digest\"",
            f"node_version=$({_line_command(specification.node_executable, '--version')} 2>&1); printf 'node_version=%s\\n' \"$node_version\"",
            f"java_version=$({_line_command(specification.java_executable, '-version')} 2>&1); printf 'java_version=%s\\n' \"$java_version\"",
            f"printf 'python_binary_digest='; {_line_command(specification.sha256sum_executable, '--', specification.python_executable)} 2>&1",
            f"printf 'node_binary_digest='; {_line_command(specification.sha256sum_executable, '--', specification.node_executable)} 2>&1",
            f"printf 'java_binary_digest='; {_line_command(specification.sha256sum_executable, '--', specification.java_executable)} 2>&1",
            f"printf 'platform_management_binary_digest='; {_line_command(specification.sha256sum_executable, '--', specification.platform_management_executable)} 2>&1",
            f"printf 'tmux_digest='; {_line_command(specification.sha256sum_executable, '--', specification.tmux_executable)} 2>&1",
        ]
        for key, kind, path in checks:
            quoted = shlex.quote(path)
            test = "-d" if kind == "directory" else "-x"
            parts.append(f"if test {test} {quoted}; then printf '{key}=present\\n'; else printf '{key}=missing\\n'; fi")
        return "; ".join(parts)

    @staticmethod
    def _parse(stdout: str) -> dict[str, str]:
        values: dict[str, str] = {}
        for line in stdout.splitlines():
            if "=" not in line:
                continue
            key, value = line.split("=", 1)
            values[key.strip()] = value.strip()
        return values

    @staticmethod
    def _managed_result(
        values: dict[str, str],
        result,
        specification: ServerRuntimeHealthSpec,
    ) -> tuple[bool, tuple[tuple[str, str], ...], tuple[str, ...]]:
        checks = {
            key: values.get(key, "missing")
            for key in (
                "remote_home",
                "platform_root",
                "release_root",
                "repository_root",
                "python_executable",
                "node_executable",
                "java_executable",
                "platform_management_executable",
                "tmux_executable",
                "sha256sum_executable",
            )
        }
        issues = [key for key, value in checks.items() if value != "present"]
        inotify_status = values.get("inotify_watch_authority", "unavailable")
        checks["inotify_watch_authority"] = (
            inotify_status if inotify_status in {"available", "not_required"} else "unavailable"
        )
        if checks["inotify_watch_authority"] == "unavailable":
            issues.append("inotify_watch_authority")
        digest_line = values.get("tmux_digest", "")
        actual_digest = digest_line.split(maxsplit=1)[0].lower() if digest_line.strip() else ""
        checks["tmux_binary_identity"] = "verified" if actual_digest == specification.tmux_binary_sha256.lower() else "mismatch"
        if checks["tmux_binary_identity"] != "verified":
            issues.append("tmux_binary_identity")
        package_status = values.get("python_packages_status", "1")
        package_digest_value = values.get("python_packages_digest", "")
        package_digest = package_digest_value.split(maxsplit=1)[0].lower() if package_digest_value.strip() else ""
        checks["python_packages_identity"] = (
            "verified"
            if package_status == "0" and package_digest == specification.python_packages_sha256.lower()
            else "mismatch"
        )
        if checks["python_packages_identity"] != "verified":
            issues.append("python_packages_identity")
        for check_name, digest_key, expected in (
            ("python_binary_identity", "python_binary_digest", specification.python_binary_sha256),
            ("node_binary_identity", "node_binary_digest", specification.node_binary_sha256),
            ("java_binary_identity", "java_binary_digest", specification.java_binary_sha256),
            (
                "platform_management_binary_identity",
                "platform_management_binary_digest",
                specification.platform_management_binary_sha256,
            ),
        ):
            actual_value = values.get(digest_key, "")
            actual = actual_value.split(maxsplit=1)[0].lower() if actual_value.strip() else ""
            checks[check_name] = "verified" if actual == expected.lower() else "mismatch"
            if checks[check_name] != "verified":
                issues.append(check_name)
        checks_tuple = tuple(sorted(checks.items()))
        return result.succeeded and not issues, checks_tuple, tuple(issues)

    def probe(
        self,
        connection: ServerConnectionPort,
        *,
        interactive: bool = False,
        specification: ServerRuntimeHealthSpec | None = None,
    ) -> ServerHealthReport:
        if specification is None:
            result = connection.execute(
                self.BASIC_COMMAND,
                interactive=interactive,
                effect=ServerOperationEffect.OBSERVATION,
            )
            values = self._parse(result.stdout)
            return ServerHealthReport(
                server_id=result.server_id,
                reachable=result.succeeded,
                host_name=values.get("host"),
                python_version=values.get("python"),
                git_version=values.get("git"),
                tmux_version=values.get("tmux"),
                raw=result,
                platform_ready=result.succeeded,
            )
        result = connection.execute(
            self._managed_command(specification),
            interactive=interactive,
            effect=ServerOperationEffect.OBSERVATION,
        )
        values = self._parse(result.stdout)
        ready, checks, issues = self._managed_result(values, result, specification)
        return ServerHealthReport(
            server_id=result.server_id,
            reachable=result.succeeded,
            host_name=values.get("host"),
            python_version=values.get("python_version"),
            git_version=None,
            tmux_version=None,
            raw=result,
            platform_ready=ready,
            checks=checks,
            issues=issues,
        )


__all__ = ["SSHServerHealthProbe"]
