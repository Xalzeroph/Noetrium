from __future__ import annotations

from dataclasses import asdict
import hashlib
import json

from noetrium_platform.infrastructure.lifecycle.host.bootstrap.api import ServerBootstrapPhase, ServerBootstrapState

_SCHEMA = "server-bootstrap-state.v1"


class ServerBootstrapStateIntegrityError(RuntimeError):
    pass


class ServerBootstrapStateCodec:
    def encode(self, state: ServerBootstrapState) -> bytes:
        payload = asdict(state)
        payload["phase"] = state.phase.value
        body = {"schema": _SCHEMA, "payload": payload}
        canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        document = {**body, "sha256": hashlib.sha256(canonical).hexdigest()}
        return json.dumps(document, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8") + b"\n"

    def decode(self, raw: bytes) -> ServerBootstrapState:
        try:
            document = json.loads(raw)
            if document.get("schema") != _SCHEMA:
                raise ValueError("server bootstrap state schema mismatch")
            body = {"schema": document["schema"], "payload": document["payload"]}
            canonical = json.dumps(body, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
            if hashlib.sha256(canonical).hexdigest() != document.get("sha256"):
                raise ValueError("server bootstrap state checksum mismatch")
            payload = dict(document["payload"])
            payload["phase"] = ServerBootstrapPhase(payload["phase"])
            payload["evidence_refs"] = tuple(payload.get("evidence_refs", ()))
            return ServerBootstrapState(**payload)
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise ServerBootstrapStateIntegrityError(str(exc)) from exc


__all__ = ["ServerBootstrapStateCodec", "ServerBootstrapStateIntegrityError"]
