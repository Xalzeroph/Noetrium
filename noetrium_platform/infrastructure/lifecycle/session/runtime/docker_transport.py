from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
import shutil

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.lifecycle.process.api import (
    ProcessCommandResult,
    ProcessCommandRunnerPort,
)
from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionDrift,
    PersistentSessionEffectUncertain,
    PersistentSessionReasonCode,
    PersistentSessionSnapshot,
    PersistentSessionSpec,
)

_LABEL_MANAGED = "io.noetrium.persistent-session"
_LABEL_SESSION = "io.noetrium.persistent-session-name"
_LABEL_SPEC = "io.noetrium.persistent-session-spec"
_LABEL_TRANSPORT = "io.noetrium.persistent-session-transport"


class DockerPersistentSessionControl:
    """Docker transport for the generic persistent-session authority."""
    backend_id = "docker"
    def __init__(
        self,
        *,
        process_runner: ProcessCommandRunnerPort,
        image: str,
        docker_executable: str = "docker",
        command_timeout_s: float = 10.0,
        user: str | None = None,
        network_host: bool = True,
        gpus: str | None = None,
        mounts: tuple[str, ...] = (),
        group_add: tuple[str, ...] = (),
        restart_policy: str = "unless-stopped",
        binary_identity_digest: str | None = None,
        image_identity: str | None = None,
        daemon_identity: str | None = None,
    ) -> None:
        if not image.strip():
            raise ValueError("Docker persistent-session image required")
        if not math.isfinite(float(command_timeout_s)) or command_timeout_s <= 0:
            raise ValueError("Docker persistent-session timeout must be finite and positive")
        if restart_policy not in {"no", "unless-stopped", "always"}:
            raise ValueError("unsupported Docker persistent-session restart policy")
        self._runner = process_runner
        self._docker = docker_executable
        self._image = image
        self._timeout = float(command_timeout_s)
        self._user = user
        self._network_host = bool(network_host)
        self._gpus = gpus
        self._mounts = tuple(mounts)
        self._group_add = tuple(group_add)
        self._restart_policy = restart_policy
        binary_digest = binary_identity_digest or self._binary_digest(docker_executable)
        image_id = image_identity or self._read_text(
            (docker_executable, "image", "inspect", "--format", "{{.Id}}", image),
            "image identity",
        )
        daemon_id = daemon_identity or self._read_text(
            (docker_executable, "info", "--format", "{{.ID}}"),
            "daemon identity",
        )
        if not image_id or not daemon_id:
            raise RuntimeError("Docker persistent-session transport identity incomplete")
        self._identity_verified = binary_digest is not None
        self._identity_digest = canonical_digest({
            "schema": "noetrium.persistent-session.docker-transport.v1",
            "docker_binary_sha256": binary_digest,
            "image_identity": image_id,
            "daemon_identity": daemon_id,
            "network_host": self._network_host,
            "user": self._user,
            "gpus": self._gpus,
            "mounts": self._mounts,
            "group_add": self._group_add,
            "restart_policy": self._restart_policy,
        })
    @staticmethod
    def _binary_digest(executable: str) -> str | None:
        resolved = shutil.which(executable)
        if resolved is None:
            candidate = Path(executable)
            if candidate.is_file():
                resolved = str(candidate)
        if resolved is None:
            return None
        return hashlib.sha256(Path(resolved).read_bytes()).hexdigest()

    @property
    def identity_verified(self) -> bool:
        return self._identity_verified

    @property
    def identity_digest(self) -> str:
        return self._identity_digest

    def _execute(self, argv: tuple[str, ...]) -> ProcessCommandResult:
        result = self._runner.execute(
            argv,
            timeout_seconds=self._timeout,
            environment=None,
            cwd=None,
            output_limit_bytes=2 * 1024 * 1024,
        ).result()
        if result.timed_out:
            raise RuntimeError("Docker persistent-session command timed out")
        if result.spawn_error is not None:
            raise RuntimeError(f"Docker command spawn failed: {result.spawn_error}")
        return result
    def _read_text(self, argv: tuple[str, ...], operation: str) -> str:
        result = self._execute(argv)
        if result.return_code != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Docker persistent-session {operation} failed: {detail}")
        return result.stdout.decode("utf-8", errors="replace").strip()

    @staticmethod
    def _is_missing(result: ProcessCommandResult) -> bool:
        if result.return_code == 0:
            return False
        detail = result.stderr.decode("utf-8", errors="replace").lower()
        return "no such object" in detail or "no such container" in detail

    def _inspect(self, target: str) -> dict[str, object] | None:
        result = self._execute((self._docker, "inspect", target))
        if self._is_missing(result):
            return None
        if result.return_code != 0:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            raise RuntimeError(f"Docker persistent-session inspect failed: {detail}")
        payload = json.loads(result.stdout.decode("utf-8"))
        if not isinstance(payload, list) or len(payload) != 1:
            raise RuntimeError("Docker persistent-session inspect payload invalid")
        row = payload[0]
        if not isinstance(row, dict):
            raise RuntimeError("Docker persistent-session inspect row invalid")
        return row
    @staticmethod
    def _snapshot(session_name: str, row: dict[str, object]) -> PersistentSessionSnapshot:
        state = row.get("State")
        config = row.get("Config")
        container_id = row.get("Id")
        if not isinstance(state, dict) or not isinstance(config, dict):
            raise RuntimeError("Docker persistent-session inspect payload incomplete")
        if not isinstance(container_id, str) or not container_id:
            raise RuntimeError("Docker persistent-session container ID missing")
        pid = state.get("Pid")
        working_dir = config.get("WorkingDir")
        return PersistentSessionSnapshot(
            session_name=session_name,
            exists=True,
            controller_pid=int(pid) if isinstance(pid, int) and pid > 0 else None,
            controller_dead=not bool(state.get("Running")),
            start_command=json.dumps(
                {"entrypoint": config.get("Entrypoint"), "cmd": config.get("Cmd")},
                sort_keys=True,
                separators=(",", ":"),
            ),
            current_path=working_dir if isinstance(working_dir, str) else None,
            evidence_refs=(f"docker-container:{container_id}",),
            session_generation=container_id,
        )

    def inspect(self, session_name: str) -> PersistentSessionSnapshot:
        row = self._inspect(session_name)
        if row is None:
            return PersistentSessionSnapshot(
                session_name,
                False,
                evidence_refs=(f"docker-session-missing:{session_name}",),
            )
        return self._snapshot(session_name, row)
    def _verify_row(
        self,
        spec: PersistentSessionSpec,
        row: dict[str, object],
        *,
        expected_generation: str | None = None,
    ) -> tuple[str, ...]:
        container_id = row.get("Id")
        config = row.get("Config")
        state = row.get("State")
        if not isinstance(container_id, str) or not isinstance(config, dict):
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.SESSION_IDENTITY_DRIFT,
                "Docker persistent-session identity missing",
            )
        if expected_generation is not None and container_id != expected_generation:
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.SESSION_IDENTITY_DRIFT,
                "Docker persistent-session generation drifted",
            )
        labels = config.get("Labels")
        if not isinstance(labels, dict):
            labels = {}
        expected = {
            _LABEL_MANAGED: "true",
            _LABEL_SESSION: spec.session_name,
            _LABEL_SPEC: spec.digest(),
            _LABEL_TRANSPORT: self.identity_digest,
        }
        if any(labels.get(key) != value for key, value in expected.items()):
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.SESSION_IDENTITY_DRIFT,
                "Docker persistent-session labels drifted",
            )
        if config.get("WorkingDir") != spec.cwd:
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.CONTROLLER_CWD_DRIFT,
                "Docker persistent-session working directory drifted",
            )
        if not isinstance(state, dict) or not bool(state.get("Running")):
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.CONTROLLER_NOT_LIVE,
                "Docker persistent-session controller is not running",
            )
        pid = state.get("Pid")
        if not isinstance(pid, int) or pid <= 0:
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.CONTROLLER_NOT_LIVE,
                "Docker persistent-session controller PID missing",
            )
        return (
            f"docker-session-exact:{spec.session_name}:{container_id}:"
            f"{spec.digest()}:{self.identity_digest}",
        )

    def verify_snapshot(
        self,
        spec: PersistentSessionSpec,
        snapshot: PersistentSessionSnapshot,
    ) -> tuple[str, ...]:
        if not snapshot.exists or not snapshot.session_generation:
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.SESSION_MISSING,
                "Docker persistent-session container is absent",
            )
        row = self._inspect(snapshot.session_generation)
        if row is None:
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.SESSION_MISSING,
                "Docker persistent-session exact generation is absent",
            )
        return self._verify_row(spec, row, expected_generation=snapshot.session_generation)
    def create_detached(self, spec: PersistentSessionSpec) -> PersistentSessionSnapshot:
        argv: list[str] = [
            self._docker,
            "run",
            "-d",
            "--init",
            "--restart",
            self._restart_policy,
            "--name",
            spec.session_name,
            "--label",
            f"{_LABEL_MANAGED}=true",
            "--label",
            f"{_LABEL_SESSION}={spec.session_name}",
            "--label",
            f"{_LABEL_SPEC}={spec.digest()}",
            "--label",
            f"{_LABEL_TRANSPORT}={self.identity_digest}",
            "--workdir",
            spec.cwd,
        ]
        if self._network_host:
            argv.extend(("--network", "host"))
        if self._user:
            argv.extend(("--user", self._user))
        if self._gpus:
            argv.extend(("--gpus", self._gpus))
        for group in self._group_add:
            argv.extend(("--group-add", group))
        for mount in self._mounts:
            argv.extend(("-v", mount))
        for key, value in spec.process_environment:
            argv.extend(("-e", f"{key}={value}"))
        argv.append(self._image)
        argv.extend(spec.command_argv)
        try:
            result = self._execute(tuple(argv))
            if result.return_code != 0:
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Docker persistent-session create failed: {detail}")
            container_id = result.stdout.decode("utf-8", errors="replace").strip()
            if not container_id:
                raise RuntimeError("Docker persistent-session create returned no container ID")
            row = self._inspect(container_id)
            if row is None:
                raise RuntimeError("Docker persistent-session container disappeared after create")
            self._verify_row(spec, row, expected_generation=container_id)
            return self._snapshot(spec.session_name, row)
        except PersistentSessionEffectUncertain:
            raise
        except Exception as exc:
            raise PersistentSessionEffectUncertain(
                "create",
                spec.session_name,
                cause=exc,
            ) from exc

    def terminate(self, snapshot: PersistentSessionSnapshot) -> tuple[str, ...]:
        if not snapshot.exists or not snapshot.session_generation:
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.SESSION_IDENTITY_DRIFT,
                "refusing to terminate Docker session without exact generation",
            )
        generation = snapshot.session_generation
        row = self._inspect(generation)
        if row is None:
            return (f"docker-session-kill-missing:{snapshot.session_name}:{generation}",)
        config = row.get("Config")
        labels = config.get("Labels") if isinstance(config, dict) else None
        if (
            row.get("Id") != generation
            or not isinstance(labels, dict)
            or labels.get(_LABEL_MANAGED) != "true"
            or labels.get(_LABEL_SESSION) != snapshot.session_name
            or labels.get(_LABEL_TRANSPORT) != self.identity_digest
        ):
            raise PersistentSessionDrift(
                PersistentSessionReasonCode.SESSION_IDENTITY_DRIFT,
                "refusing to terminate drifted Docker persistent-session generation",
            )
        try:
            result = self._execute((self._docker, "rm", "-f", generation))
            if result.return_code != 0 and not self._is_missing(result):
                detail = result.stderr.decode("utf-8", errors="replace").strip()
                raise RuntimeError(f"Docker persistent-session terminate failed: {detail}")
            return (f"docker-session-killed:{snapshot.session_name}:{generation}",)
        except PersistentSessionEffectUncertain:
            raise
        except Exception as exc:
            raise PersistentSessionEffectUncertain(
                "terminate",
                snapshot.session_name,
                cause=exc,
            ) from exc

    def attach_argv(self, session_name: str) -> tuple[str, ...]:
        return (self._docker, "logs", "-f", session_name)


__all__ = ["DockerPersistentSessionControl"]
