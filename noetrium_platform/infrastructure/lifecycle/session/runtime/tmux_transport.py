from __future__ import annotations

import math

from noetrium_platform.foundation.scope.path.api import is_absolute_target_path
from noetrium_platform.infrastructure.lifecycle.process.supervision.api import ProcessCommandRunnerPort

from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionDrift,
    PersistentSessionReasonCode,
    PersistentSessionEffectUncertain,
    PersistentSessionSnapshot,
    PersistentSessionSpec,
)

from .tmux_commands import TmuxCommandCodec
from .tmux_contracts import TmuxCommandResult, TmuxCommandRunner
from .tmux_evidence import tmux_evidence_ref
from .tmux_identity import TmuxBinaryIdentityMismatch, TmuxTransportIdentity
from .tmux_parser import parse_tmux_snapshot
from .tmux_result_policy import TmuxCommandFailed, require_success, session_is_absent
from .tmux_subprocess import SubprocessTmuxCommandRunner


class TmuxPersistentSessionControl:
    """tmux implementation of the generic persistent-session control port."""

    backend_id = "tmux"

    def __init__(
        self,
        *,
        tmux_executable: str = "/usr/bin/tmux",
        server_label: str = "noetrium",
        config_file: str = "/dev/null",
        environment_executable: str = "/usr/bin/env",
        socket_directory: str = "/tmp",
        binary_identity_digest: str | None = None,
        command_timeout_s: float = 5.0,
        runner: TmuxCommandRunner | None = None,
        process_runner: ProcessCommandRunnerPort | None = None,
        transport_identity: TmuxTransportIdentity | None = None,
    ) -> None:
        if not math.isfinite(float(command_timeout_s)) or command_timeout_s <= 0:
            raise ValueError("tmux command timeout must be finite and positive")
        if not is_absolute_target_path(socket_directory):
            raise ValueError("tmux socket directory must be absolute")
        self.commands = TmuxCommandCodec(
            tmux_executable,
            server_label,
            config_file,
            environment_executable,
        )
        self.transport_identity = transport_identity or TmuxTransportIdentity.resolve(
            executable=self.commands.executable,
            expected_binary_sha256=binary_identity_digest,
            server_label=self.commands.server_label,
            config_file=self.commands.config_file,
            # Preserve the target host's path flavor. Path(...) would reinterpret
            # a valid POSIX server path as a Windows path on the controller.
            socket_directory=socket_directory,
        )
        self.command_timeout_s = float(command_timeout_s)
        if runner is None:
            if process_runner is None:
                raise RuntimeError(
                    "tmux execution requires an injected async process command runner"
                )
            runner = SubprocessTmuxCommandRunner(process_runner, self.command_timeout_s)
        self.runner = runner

    @property
    def tmux_executable(self) -> str:
        return self.commands.executable

    @property
    def server_label(self) -> str:
        return self.commands.server_label

    @property
    def socket_directory(self) -> str:
        return self.transport_identity.socket_directory

    @property
    def binary_identity_digest(self) -> str | None:
        return self.transport_identity.binary_sha256

    @property
    def identity_verified(self) -> bool:
        return self.transport_identity.binary_verified

    @property
    def identity_digest(self) -> str:
        return self.transport_identity.digest()

    def _run(self, argv: tuple[str, ...], *, effect: str) -> TmuxCommandResult:
        return self.runner.run(
            argv,
            environment={"TMPDIR": self.socket_directory, "LC_ALL": "C"},
            effect=effect,
        )

    def inspect(self, session_name: str) -> PersistentSessionSnapshot:
        result = self._run(self.commands.inspect_argv(session_name), effect="observation")
        if result.returncode != 0:
            if not session_is_absent(result):
                raise TmuxCommandFailed("inspect", result)
            return PersistentSessionSnapshot(
                session_name,
                False,
                evidence_refs=(tmux_evidence_ref("missing", session_name),),
            )
        parsed = parse_tmux_snapshot(session_name, result.stdout)
        return PersistentSessionSnapshot(
            parsed.session_name,
            parsed.exists,
            parsed.controller_pid,
            parsed.controller_dead,
            parsed.start_command,
            parsed.current_path,
            (
                tmux_evidence_ref(
                    "snapshot",
                    (
                        parsed.session_name,
                        parsed.controller_pid,
                        parsed.controller_dead,
                        parsed.start_command,
                        parsed.current_path,
                    ),
                ),
            ),
        )

    def verify_snapshot(
        self,
        spec: PersistentSessionSpec,
        snapshot: PersistentSessionSnapshot,
    ) -> tuple[str, ...]:
        if not snapshot.exists:
            raise PersistentSessionDrift(PersistentSessionReasonCode.SESSION_MISSING, "tmux session is absent")
        if snapshot.session_name != spec.session_name:
            raise PersistentSessionDrift(PersistentSessionReasonCode.SESSION_IDENTITY_DRIFT, "tmux session name differs from frozen binding")
        if snapshot.controller_pid is None or snapshot.controller_pid <= 0:
            raise PersistentSessionDrift(PersistentSessionReasonCode.CONTROLLER_NOT_LIVE, "tmux controller PID missing")
        if snapshot.controller_dead:
            raise PersistentSessionDrift(PersistentSessionReasonCode.CONTROLLER_NOT_LIVE, "tmux controller pane is dead")
        expected = self.commands.pane_command(spec)
        if snapshot.start_command != expected:
            raise PersistentSessionDrift(PersistentSessionReasonCode.CONTROLLER_COMMAND_DRIFT, "tmux pane command differs from frozen controller argv/environment")
        if snapshot.current_path != spec.cwd:
            raise PersistentSessionDrift(PersistentSessionReasonCode.CONTROLLER_CWD_DRIFT, "tmux controller cwd differs from frozen release directory")
        return (
            tmux_evidence_ref(
                "exact",
                (spec.session_name, snapshot.controller_pid, expected, spec.cwd, self.identity_digest),
            ),
        )

    def create_detached(self, spec: PersistentSessionSpec) -> PersistentSessionSnapshot:
        # Build/validate the command before entering the side-effect window.  Once
        # the runner is invoked, any ordinary failure is conservatively treated as
        # uncertain: tmux may have created the session before the client observed
        # the error.  The caller must inspect/reconcile before another create.
        argv = self.commands.create_argv(spec)
        try:
            result = self._run(argv, effect="mutation")
            require_success("create", result)
            snapshot = self.inspect(spec.session_name)
            self.verify_snapshot(spec, snapshot)
            return snapshot
        except Exception as exc:
            raise PersistentSessionEffectUncertain("create", spec.session_name, cause=exc) from exc

    def terminate(self, session_name: str) -> tuple[str, ...]:
        # As with create, command construction is outside the external-effect
        # window.  A definitive "session absent" response proves no live target;
        # every other ordinary failure after submission is effect-uncertain.
        argv = self.commands.terminate_argv(session_name)
        try:
            result = self._run(argv, effect="mutation")
            if result.returncode != 0:
                if session_is_absent(result):
                    return (tmux_evidence_ref("kill-missing", session_name),)
                raise TmuxCommandFailed("terminate", result)
            return (tmux_evidence_ref("killed", session_name),)
        except PersistentSessionEffectUncertain:
            raise
        except Exception as exc:
            raise PersistentSessionEffectUncertain("terminate", session_name, cause=exc) from exc

    def attach_argv(self, session_name: str) -> tuple[str, ...]:
        return self.commands.attach_argv(session_name)


__all__ = ["TmuxBinaryIdentityMismatch", "TmuxPersistentSessionControl"]
