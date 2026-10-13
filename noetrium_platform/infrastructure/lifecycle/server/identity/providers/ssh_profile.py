from __future__ import annotations

from collections.abc import Mapping
import shutil
from pathlib import Path

from ..api import ServerConnectionProfile, ServerIdentityConfigurationError, server_environment_prefix


def materialize_ssh_profile(
    server_id: str,
    values: Mapping[str, str],
    *,
    ssh_executable: str | None,
) -> ServerConnectionProfile:
    prefix = server_environment_prefix(server_id)

    def required(name: str) -> str:
        value = values.get(f"{prefix}_{name}", "").strip()
        if not value:
            raise ServerIdentityConfigurationError(f"missing environment variable {prefix}_{name}")
        return value

    port_text = required("PORT")
    try:
        port = int(port_text)
    except ValueError as exc:
        raise ServerIdentityConfigurationError(f"{prefix}_PORT must be an integer") from exc

    def optional_local_file(name: str) -> Path | None:
        raw = values.get(f"{prefix}_{name}", "").strip()
        if not raw:
            return None
        path = Path(raw).expanduser()
        if not path.is_absolute():
            raise ServerIdentityConfigurationError(f"{prefix}_{name} must be an absolute local path")
        try:
            resolved = path.resolve(strict=True)
            if not resolved.is_file():
                raise OSError("not a regular file")
            with resolved.open("rb"):
                pass
        except OSError as exc:
            raise ServerIdentityConfigurationError(
                f"{prefix}_{name} must be a readable regular local file"
            ) from exc
        return resolved

    key_path = optional_local_file("KEY_PATH")
    known_hosts_path = optional_local_file("KNOWN_HOSTS")
    ssh_config_path = optional_local_file("SSH_CONFIG")
    control_path_text = values.get(f"{prefix}_SSH_CONTROL_PATH", "").strip()
    control_persist_text = values.get(f"{prefix}_SSH_CONTROL_PERSIST_SECONDS", "600").strip() or "600"
    timeout_text = values.get(f"{prefix}_SSH_COMMAND_TIMEOUT_SECONDS", "120").strip() or "120"
    interactive_timeout_text = values.get(f"{prefix}_SSH_INTERACTIVE_TIMEOUT_SECONDS", str(8 * 60 * 60)).strip() or str(8 * 60 * 60)
    transfer_timeout_text = values.get(f"{prefix}_SSH_TRANSFER_TIMEOUT_SECONDS", "1800").strip() or "1800"
    repository_timeout_text = values.get(f"{prefix}_SSH_REPOSITORY_TIMEOUT_SECONDS", "1800").strip() or "1800"
    git_transport_timeout_text = values.get(f"{prefix}_SSH_GIT_TIMEOUT_SECONDS", "120").strip() or "120"
    output_limit_text = values.get(f"{prefix}_SSH_OUTPUT_LIMIT_BYTES", str(8 * 1024 * 1024)).strip() or str(8 * 1024 * 1024)
    try:
        control_persist_seconds = int(control_persist_text)
        command_timeout_seconds = float(timeout_text)
        interactive_timeout_seconds = float(interactive_timeout_text)
        transfer_timeout_seconds = float(transfer_timeout_text)
        repository_timeout_seconds = float(repository_timeout_text)
        git_transport_timeout_seconds = float(git_transport_timeout_text)
        output_limit_bytes = int(output_limit_text)
    except ValueError as exc:
        raise ServerIdentityConfigurationError(
            f"{prefix}_SSH_CONTROL_PERSIST_SECONDS must be an integer and SSH timeout/output fields must be numeric"
        ) from exc
    selected_executable = ssh_executable or values.get(f"{prefix}_SSH", "").strip() or shutil.which("ssh") or "ssh"
    return ServerConnectionProfile(
        server_id=server_id,
        host=required("HOST"),
        port=port,
        username=required("USER"),
        key_path=key_path,
        known_hosts_path=known_hosts_path,
        ssh_config_path=ssh_config_path,
        ssh_executable=selected_executable,
        control_path=(Path(control_path_text).expanduser() if control_path_text else None),
        control_persist_seconds=control_persist_seconds,
        command_timeout_seconds=command_timeout_seconds,
        interactive_timeout_seconds=interactive_timeout_seconds,
        transfer_timeout_seconds=transfer_timeout_seconds,
        repository_timeout_seconds=repository_timeout_seconds,
        git_transport_timeout_seconds=git_transport_timeout_seconds,
        output_limit_bytes=output_limit_bytes,
    )


__all__ = ["materialize_ssh_profile"]
