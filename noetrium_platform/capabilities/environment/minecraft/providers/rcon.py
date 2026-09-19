from __future__ import annotations

from collections.abc import Callable
import hashlib
import socket
import struct
import threading
from typing import Protocol

from noetrium_platform.foundation.kernel.kernel import canonical_digest

from ..api import MinecraftConsoleCommandResult, MinecraftRconEndpoint, MinecraftServerConsolePort


class MinecraftRconError(RuntimeError):
    """A Minecraft RCON operation failed with an actionable cause code."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"Minecraft RCON failed [{code}]: {message}")
        self.code = code


class _RconSocket(Protocol):
    def settimeout(self, value: float | None) -> None: ...

    def connect(self, address: tuple[str, int]) -> None: ...

    def sendall(self, data: bytes) -> None: ...

    def recv(self, size: int) -> bytes: ...

    def close(self) -> None: ...


def _default_socket() -> _RconSocket:
    return socket.socket(socket.AF_INET, socket.SOCK_STREAM)


def _read_exact(sock: _RconSocket, size: int) -> bytes:
    chunks: list[bytes] = []
    remaining = size
    while remaining:
        chunk = sock.recv(remaining)
        if not chunk:
            raise MinecraftRconError("RCON_EOF", f"expected {remaining} more bytes")
        chunks.append(chunk)
        remaining -= len(chunk)
    return b"".join(chunks)


def _read_packet(sock: _RconSocket, *, max_packet_bytes: int) -> tuple[int, int, str]:
    raw_length = _read_exact(sock, 4)
    (length,) = struct.unpack("<i", raw_length)
    if length < 10 or length > max_packet_bytes:
        raise MinecraftRconError("RCON_PACKET_INVALID", f"packet length={length}")
    body = _read_exact(sock, length)
    if len(body) < 10 or body[-2:] != b"\x00\x00":
        raise MinecraftRconError("RCON_PACKET_INVALID", "packet terminator or body is invalid")
    request_id, packet_type = struct.unpack("<ii", body[:8])
    try:
        payload = body[8:-2].decode("utf-8")
    except UnicodeDecodeError as exc:
        raise MinecraftRconError("RCON_RESPONSE_ENCODING", "response is not valid UTF-8") from exc
    return request_id, packet_type, payload


def _write_packet(sock: _RconSocket, request_id: int, packet_type: int, payload: str) -> None:
    encoded = payload.encode("utf-8")
    body = struct.pack("<ii", request_id, packet_type) + encoded + b"\x00\x00"
    sock.sendall(struct.pack("<i", len(body)) + body)


class MinecraftRconConsole(MinecraftServerConsolePort):
    """Dependency-free RCON implementation for MC server control.

    Authentication material is supplied by a callable and never enters an
    endpoint identity, diagnostic message or evidence reference.
    """

    def __init__(
        self,
        endpoint: MinecraftRconEndpoint,
        *,
        secret_provider: Callable[[], str],
        socket_factory: Callable[[], _RconSocket] | None = None,
        max_packet_bytes: int = 1024 * 1024,
    ) -> None:
        if max_packet_bytes < 10:
            raise ValueError("Minecraft RCON max_packet_bytes must be at least 10")
        self.endpoint = endpoint
        self._secret_provider = secret_provider
        self._socket_factory = socket_factory or _default_socket
        self._max_packet_bytes = max_packet_bytes
        self._lock = threading.Lock()
        self._next_request_id = 1

    def _request_id(self) -> int:
        with self._lock:
            request_id = self._next_request_id
            self._next_request_id = 1 if request_id >= 2_000_000_000 else request_id + 1
            return request_id

    def execute(self, command: str, *, timeout_s: float) -> MinecraftConsoleCommandResult:
        """Execute one RCON request on an independently owned socket.

        RCON request identifiers are synchronized, but network lifetime is not.
        Distinct calls therefore cannot block one another on a process-local lock.
        """
        if not command.strip() or "\x00" in command:
            raise MinecraftRconError("RCON_COMMAND_INVALID", "command is empty or contains NUL")
        if timeout_s <= 0:
            raise MinecraftRconError("RCON_TIMEOUT_INVALID", "timeout must be positive")
        try:
            password = self._secret_provider()
        except Exception as exc:
            raise MinecraftRconError(
                "RCON_SECRET_UNAVAILABLE",
                f"secret provider failed: {type(exc).__name__}",
            ) from exc
        if not isinstance(password, str) or not password:
            raise MinecraftRconError("RCON_SECRET_UNAVAILABLE", "secret provider returned no secret")

        sock: _RconSocket | None = None
        primary_error: BaseException | None = None
        result: MinecraftConsoleCommandResult | None = None
        stage = "connect"
        try:
            sock = self._socket_factory()
            sock.settimeout(timeout_s)
            sock.connect((self.endpoint.host, self.endpoint.port))

            auth_id = self._request_id()
            stage = "auth"
            _write_packet(sock, auth_id, 3, password)
            response_id, response_type, _response = _read_packet(
                sock,
                max_packet_bytes=self._max_packet_bytes,
            )
            if response_id == -1:
                raise MinecraftRconError("RCON_AUTH_FAILED", "server rejected authentication")
            if response_id != auth_id or response_type != 2:
                raise MinecraftRconError(
                    "RCON_AUTH_PROTOCOL",
                    f"unexpected auth response id={response_id} type={response_type}",
                )

            command_id = self._request_id()
            stage = "command"
            _write_packet(sock, command_id, 2, command)
            response_id, response_type, response = _read_packet(
                sock,
                max_packet_bytes=self._max_packet_bytes,
            )
            if response_id != command_id or response_type not in {0, 2}:
                raise MinecraftRconError(
                    "RCON_COMMAND_PROTOCOL",
                    f"unexpected command response id={response_id} type={response_type}",
                )
            evidence = "minecraft-rcon-command:" + canonical_digest(
                {
                    "host": self.endpoint.host,
                    "port": self.endpoint.port,
                    "command": command,
                    "response_sha256": hashlib.sha256(response.encode("utf-8")).hexdigest(),
                }
            )
            result = MinecraftConsoleCommandResult(command, response, evidence)
        except MinecraftRconError as exc:
            primary_error = exc
        except socket.timeout as exc:
            primary_error = MinecraftRconError("RCON_TIMEOUT", f"stage={stage}")
            primary_error.__cause__ = exc
        except OSError as exc:
            code = "RCON_CONNECT_FAILED" if stage == "connect" else "RCON_SOCKET_IO_FAILED"
            primary_error = MinecraftRconError(code, f"stage={stage}: {exc}")
            primary_error.__cause__ = exc
        except BaseException as exc:
            primary_error = exc
        finally:
            if sock is not None:
                try:
                    sock.close()
                except Exception as exc:
                    if primary_error is None:
                        primary_error = MinecraftRconError(
                            "RCON_SOCKET_CLOSE_FAILED",
                            f"{type(exc).__name__}: {exc}",
                        )
                    else:
                        primary_error = MinecraftRconError(
                            "RCON_OPERATION_AND_CLOSE_FAILED",
                            f"operation={primary_error}; close={type(exc).__name__}: {exc}",
                        )
        if primary_error is not None:
            raise primary_error
        assert result is not None
        return result


__all__ = ["MinecraftRconConsole", "MinecraftRconError"]
