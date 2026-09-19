from __future__ import annotations

from collections.abc import Callable
import threading
import time
from pathlib import Path

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.errors import describe_exception
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path

from ..api import (
    MinecraftServerConsolePort,
    MinecraftWorldQuiescence,
    MinecraftWorldQuiescencePort,
)


def _is_sha256(value: str) -> bool:
    return len(value) == 64 and all(char in "0123456789abcdef" for char in value.lower())


class MinecraftWorldQuiescenceError(RuntimeError):
    """A save barrier could not prove a safe world cut."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Minecraft world quiescence failed [{code}]: {message}")
        self.code = code


def _safe_exception_message(exc: BaseException) -> str:
    descriptor = describe_exception(exc)
    return f"{descriptor.error_type}[{descriptor.error_digest[:16]}]"


class MinecraftSaveQuiescenceProvider(MinecraftWorldQuiescencePort):
    """Hold a provider-owned save barrier around a world-cut operation."""

    def __init__(
        self,
        *,
        console: MinecraftServerConsolePort,
        source_workdir: str,
        level_name: str,
        server_contract_digest: str,
        process_identity_digest: Callable[[], str],
        command_timeout_s: float = 10.0,
        settle_after_flush_s: float = 0.0,
    ) -> None:
        source = Path(source_workdir).expanduser().resolve(strict=False)
        if not is_absolute_target_path(source):
            raise ValueError("Minecraft quiescence source_workdir must be absolute")
        if (
            not level_name.strip()
            or "/" in level_name
            or "\\" in level_name
            or level_name in {".", ".."}
        ):
            raise ValueError("Minecraft quiescence level_name is invalid")
        if not _is_sha256(server_contract_digest):
            raise ValueError("Minecraft quiescence server_contract_digest must be SHA-256")
        if command_timeout_s <= 0 or settle_after_flush_s < 0:
            raise ValueError("Minecraft quiescence timing values are invalid")
        self.console = console
        self.source_workdir = str(source)
        self.level_name = level_name
        self.server_contract_digest = server_contract_digest.lower()
        self._process_identity_digest = process_identity_digest
        self.command_timeout_s = command_timeout_s
        self.settle_after_flush_s = settle_after_flush_s
        self._lock = threading.RLock()
        self._active: tuple[str, MinecraftWorldQuiescence] | None = None
        self._transition_session: str | None = None

    def _identity(self) -> str:
        try:
            value = self._process_identity_digest()
        except Exception as exc:
            raise MinecraftWorldQuiescenceError(
                "PROCESS_IDENTITY_UNAVAILABLE",
                f"{type(exc).__name__}: {exc}",
            ) from exc
        if not isinstance(value, str) or not _is_sha256(value):
            raise MinecraftWorldQuiescenceError(
                "PROCESS_IDENTITY_INVALID",
                "process identity provider did not return SHA-256",
            )
        return value.lower()

    def _command(self, command: str):
        try:
            return self.console.execute(command, timeout_s=self.command_timeout_s)
        except Exception as exc:
            raise MinecraftWorldQuiescenceError(
                f"CONSOLE_{command.upper().replace(' ', '_').replace('-', '_')}_FAILED",
                f"{type(exc).__name__}: {exc}",
            ) from exc

    def save_and_quiesce(self, *, session_id: str, context: object) -> MinecraftWorldQuiescence:
        del context
        if not session_id.strip():
            raise MinecraftWorldQuiescenceError("SESSION_ID_REQUIRED", "session_id is empty")
        with self._lock:
            if self._active is not None or self._transition_session is not None:
                active = self._active[0] if self._active is not None else self._transition_session
                raise MinecraftWorldQuiescenceError("QUIESCENCE_ALREADY_ACTIVE", f"session={active}")
            self._transition_session = session_id

        process_identity = self._identity()
        save_off_attempted = False
        try:
            save_off_attempted = True
            save_off = self._command("save-off")
            save_flush = self._command("save-all flush")
            if self.settle_after_flush_s:
                time.sleep(self.settle_after_flush_s)
            if self._identity() != process_identity:
                raise MinecraftWorldQuiescenceError(
                    "PROCESS_IDENTITY_CHANGED",
                    "server process changed during save barrier",
                )
            save_evidence_ref = "minecraft-save-barrier:" + canonical_digest(
                {
                    "level_name": self.level_name,
                    "server_contract_digest": self.server_contract_digest,
                    "process_identity_digest": process_identity,
                    "save_off_evidence_ref": save_off.evidence_ref,
                    "save_flush_evidence_ref": save_flush.evidence_ref,
                }
            )
            quiescence = MinecraftWorldQuiescence(
                source_workdir=self.source_workdir,
                level_name=self.level_name,
                server_contract_digest=self.server_contract_digest,
                process_identity_digest=process_identity,
                save_evidence_ref=save_evidence_ref,
            )
            with self._lock:
                if self._transition_session != session_id or self._active is not None:
                    raise MinecraftWorldQuiescenceError(
                        "QUIESCENCE_STATE_DRIFT",
                        "save barrier reservation changed before commit",
                    )
                self._active = (session_id, quiescence)
                self._transition_session = None
            return quiescence
        except MinecraftWorldQuiescenceError as exc:
            if save_off_attempted:
                self._recover_save_on(process_identity, exc)
            raise
        except Exception as exc:
            wrapped = MinecraftWorldQuiescenceError("SAVE_BARRIER_FAILED", f"{type(exc).__name__}: {exc}")
            if save_off_attempted:
                self._recover_save_on(process_identity, wrapped)
            raise wrapped from exc
        finally:
            with self._lock:
                if self._transition_session == session_id:
                    self._transition_session = None

    def _recover_save_on(self, expected_identity: str, primary: MinecraftWorldQuiescenceError) -> None:
        try:
            if self._identity() != expected_identity:
                raise MinecraftWorldQuiescenceError(
                    "PROCESS_IDENTITY_CHANGED",
                    "cannot issue recovery save-on to a different server process",
                )
            self._command("save-on")
        except Exception as recovery:
            if isinstance(recovery, MinecraftWorldQuiescenceError):
                detail = str(recovery)
            else:
                detail = f"{type(recovery).__name__}: {recovery}"
            raise MinecraftWorldQuiescenceError(
                "SAVE_BARRIER_RECOVERY_FAILED",
                f"primary={primary}; recovery={detail}",
            ) from recovery

    def resume(self, quiescence: MinecraftWorldQuiescence, *, session_id: str, context: object) -> None:
        del context
        if not session_id.strip():
            raise MinecraftWorldQuiescenceError("SESSION_ID_REQUIRED", "session_id is empty")
        with self._lock:
            if self._transition_session is not None:
                raise MinecraftWorldQuiescenceError(
                    "QUIESCENCE_TRANSITION_ACTIVE",
                    f"session={self._transition_session}",
                )
            if self._active is None:
                raise MinecraftWorldQuiescenceError("QUIESCENCE_NOT_ACTIVE", session_id)
            active_session, active = self._active
            if active_session != session_id or active != quiescence:
                raise MinecraftWorldQuiescenceError(
                    "QUIESCENCE_IDENTITY_MISMATCH",
                    f"active_session={active_session}; requested_session={session_id}",
                )
            self._transition_session = session_id

        try:
            if self._identity() != quiescence.process_identity_digest:
                raise MinecraftWorldQuiescenceError(
                    "PROCESS_IDENTITY_CHANGED",
                    "server process changed before save-on",
                )
            try:
                self._command("save-on")
            except MinecraftWorldQuiescenceError as exc:
                raise MinecraftWorldQuiescenceError(
                    "RESUME_SAVE_ON_FAILED",
                    _safe_exception_message(exc),
                ) from exc
            with self._lock:
                if self._transition_session != session_id or self._active != (session_id, quiescence):
                    raise MinecraftWorldQuiescenceError(
                        "QUIESCENCE_STATE_DRIFT",
                        "resume reservation changed before commit",
                    )
                self._active = None
                self._transition_session = None
        finally:
            with self._lock:
                if self._transition_session == session_id:
                    self._transition_session = None


__all__ = ["MinecraftSaveQuiescenceProvider", "MinecraftWorldQuiescenceError"]
