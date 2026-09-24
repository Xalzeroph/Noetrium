from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel.durability import atomic_replace_bytes

import hashlib
from pathlib import Path
import socket
from typing import Mapping

from noetrium_platform.foundation.kernel.kernel import JsonValue
from ..api import MinecraftServerPreparedFiles, MinecraftServerSpec


class MinecraftServerPreparationError(RuntimeError):
    """Server files are not safe or complete enough for a managed launch."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Minecraft server preparation failed [{code}]: {message}")
        self.code = code


def render_server_properties(spec: MinecraftServerSpec, *, rcon_password: str | None = None) -> str:
    if spec.rcon_endpoint is None and rcon_password is not None:
        raise ValueError("rcon_password requires MinecraftServerSpec.rcon_endpoint")
    if spec.rcon_endpoint is not None and not rcon_password:
        raise MinecraftServerPreparationError(
            "RCON_PASSWORD_REQUIRED",
            "an explicit RCON secret is required when the server control endpoint is enabled",
        )
    values: Mapping[str, JsonValue] = {
        "allow-flight": True,
        "enable-command-block": False,
        "enforce-secure-profile": False,
        "force-gamemode": True,
        "gamemode": "survival",
        "generate-structures": True,
        "level-name": spec.level_name,
        "level-seed": spec.level_seed,
        "max-players": 4,
        "motd": "Noetrium Minecraft Environment",
        "online-mode": spec.online_mode,
        "pvp": False,
        "simulation-distance": 6,
        "sync-chunk-writes": False,
        "max-tick-time": -1,
        "enable-status": False,
        "server-ip": spec.host if spec.host not in {"127.0.0.1", "localhost"} else "",
        "server-port": spec.bound_port,
        "spawn-protection": 0,
        "view-distance": 6,
    }
    if spec.rcon_endpoint is not None:
        values = {
            **values,
            "enable-rcon": True,
            "rcon.password": rcon_password,
            "rcon.port": spec.rcon_endpoint.bound_port,
        }
    lines = []
    for key in sorted(values):
        value = values[key]
        rendered = str(value).lower() if isinstance(value, bool) else str(value)
        lines.append(f"{key}={rendered}")
    return "\n".join(lines) + "\n"


def prepare_server_files(
    spec: MinecraftServerSpec,
    *,
    accept_eula: bool,
    rcon_password: str | None = None,
) -> MinecraftServerPreparedFiles:
    jar = Path(spec.jar_path)
    if not jar.is_file():
        raise MinecraftServerPreparationError("SERVER_JAR_MISSING", str(jar))
    # Validate all secret-dependent rendering before mutating the workdir.
    properties = render_server_properties(spec, rcon_password=rcon_password)

    workdir = Path(spec.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    eula_path = workdir / "eula.txt"
    existing_eula = eula_path.read_text(encoding="utf-8", errors="replace").strip().lower() if eula_path.exists() else ""
    eula_accepted = "eula=true" in existing_eula
    if not eula_accepted:
        if not accept_eula:
            raise MinecraftServerPreparationError(
                "EULA_ACCEPTANCE_REQUIRED",
                "pass the explicit operator/experiment policy accept_eula=True",
            )
        atomic_replace_bytes(eula_path, b"eula=true\n")
        eula_accepted = True

    properties_path = workdir / "server.properties"
    atomic_replace_bytes(properties_path, properties.encode("utf-8"))
    return MinecraftServerPreparedFiles(
        eula_path=str(eula_path),
        properties_path=str(properties_path),
        eula_accepted=eula_accepted,
        properties_digest=hashlib.sha256(properties.encode("utf-8")).hexdigest(),
    )


def ensure_port_available(host: str, port: int) -> None:
    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        probe.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        probe.bind((host, port))
    except OSError as exc:
        raise MinecraftServerPreparationError("SERVER_PORT_COLLISION", f"{host}:{port}: {exc}") from exc
    finally:
        probe.close()


__all__ = [
    "MinecraftServerPreparationError",
    "ensure_port_available",
    "prepare_server_files",
    "render_server_properties",
]
