from __future__ import annotations

from dataclasses import dataclass
import json
import math
from uuid import uuid4

from noetrium_platform.infrastructure.lifecycle.service.api import (
    MaterializedServiceEnvironment,
    ServiceLaunchContract,
)
from .prepared_start import ServiceStartRecoveryHandle


LINUX_PREPARED_START_SCHEMA = "noetrium.linux-prepared-start.v1"
LINUX_PREPARED_START_ENV = "NOETRIUM_INTERNAL_SERVICE_START_TOKEN"


@dataclass(frozen=True, slots=True)
class LinuxPreparedStartToken:
    token: str
    intent_id: str
    attempt: int
    contract_digest: str
    environment_digest: str

    def __post_init__(self) -> None:
        if (
            len(self.token) != 32
            or any(character not in "0123456789abcdef" for character in self.token)
        ):
            raise ValueError("Linux prepared-start token must be uuid4 hex")
        if not self.intent_id:
            raise ValueError("Linux prepared-start intent id is required")
        if type(self.attempt) is not int or self.attempt <= 0:
            raise ValueError("Linux prepared-start attempt must be positive")
        for value, label in (
            (self.contract_digest, "contract"),
            (self.environment_digest, "environment"),
        ):
            if (
                len(value) != 64
                or any(character not in "0123456789abcdef" for character in value)
            ):
                raise ValueError(
                    f"Linux prepared-start {label} digest must be lowercase sha256"
                )

    def encode(self) -> bytes:
        return json.dumps(
            {
                "token": self.token,
                "intent_id": self.intent_id,
                "attempt": self.attempt,
                "contract_digest": self.contract_digest,
                "environment_digest": self.environment_digest,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")

    @classmethod
    def decode(cls, payload: bytes) -> "LinuxPreparedStartToken":
        try:
            raw = json.loads(payload.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ValueError("Linux prepared-start recovery payload is invalid") from exc
        if not isinstance(raw, dict) or set(raw) != {
            "token",
            "intent_id",
            "attempt",
            "contract_digest",
            "environment_digest",
        }:
            raise ValueError("Linux prepared-start recovery payload fields are invalid")
        return cls(
            str(raw["token"]),
            str(raw["intent_id"]),
            int(raw["attempt"]),
            str(raw["contract_digest"]),
            str(raw["environment_digest"]),
        )


def prepare_linux_start_handle(
    contract: ServiceLaunchContract,
    environment: MaterializedServiceEnvironment,
    *,
    intent_id: str,
    attempt: int,
) -> ServiceStartRecoveryHandle:
    if LINUX_PREPARED_START_ENV in environment.as_dict():
        raise ValueError(
            f"{LINUX_PREPARED_START_ENV} is reserved for lifecycle recovery"
        )
    token = LinuxPreparedStartToken(
        uuid4().hex,
        intent_id,
        attempt,
        contract.digest(),
        environment.digest,
    )
    return ServiceStartRecoveryHandle.from_payload(
        LINUX_PREPARED_START_SCHEMA,
        token.encode(),
    )


def decode_linux_start_handle(
    handle: ServiceStartRecoveryHandle,
    contract: ServiceLaunchContract,
    environment: MaterializedServiceEnvironment,
) -> LinuxPreparedStartToken:
    if handle.provider_schema != LINUX_PREPARED_START_SCHEMA:
        raise ValueError(
            "Linux prepared-start recovery handle belongs to a different provider"
        )
    token = LinuxPreparedStartToken.decode(handle.opaque_payload)
    if token.contract_digest != contract.digest():
        raise ValueError("Linux prepared-start recovery contract digest drift")
    if token.environment_digest != environment.digest:
        raise ValueError("Linux prepared-start recovery environment digest drift")
    return token


def process_environment_without_start_marker(
    environment: dict[str, str],
) -> tuple[dict[str, str], str | None]:
    observed = dict(environment)
    marker = observed.pop(LINUX_PREPARED_START_ENV, None)
    return observed, marker


__all__ = [
    "LINUX_PREPARED_START_ENV",
    "LINUX_PREPARED_START_SCHEMA",
    "LinuxPreparedStartToken",
    "decode_linux_start_handle",
    "prepare_linux_start_handle",
    "process_environment_without_start_marker",
]
