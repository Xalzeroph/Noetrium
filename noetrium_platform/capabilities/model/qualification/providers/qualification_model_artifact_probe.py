"""Model artifact facts for deployment qualification."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from noetrium_platform.capabilities.model.qualification.api import DeploymentQualificationRequest, ModelArtifactFacts


_CONTEXT_FIELDS = ("max_position_embeddings", "max_sequence_length", "max_seq_len")


def _optional_text(document: dict[str, object], field: str) -> str | None:
    value = document.get(field)
    if value is None:
        return None
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text when present")
    return value


def _architectures(document: dict[str, object]) -> tuple[str, ...]:
    value = document.get("architectures")
    if value is None:
        return ()
    if type(value) is not list:
        raise ValueError("architectures must be a JSON list when present")
    if any(type(item) is not str or not item.strip() for item in value):
        raise ValueError("architectures must contain only non-empty strings")
    return tuple(value)


def _context_length(document: dict[str, object]) -> int | None:
    for field in _CONTEXT_FIELDS:
        value = document.get(field)
        if value is None:
            continue
        if type(value) is not int or value <= 0:
            raise ValueError(f"{field} must be a positive integer when present")
        return value
    return None


class ModelArtifactProbe:
    """Inspect local model artifacts without loading model weights."""

    @staticmethod
    def _artifact_stats(path: Path) -> tuple[int | None, int | None, int | None]:
        if not path.is_dir():
            return None, None, None
        total = 0
        files = 0
        shards = 0
        try:
            for item in path.rglob("*"):
                if not item.is_file():
                    continue
                files += 1
                total += item.stat().st_size
                if item.suffix.lower() in {".safetensors", ".bin", ".pt", ".pth"}:
                    shards += 1
        except OSError:
            return None, None, None
        return total, files, shards

    @staticmethod
    def _failure(
        request: DeploymentQualificationRequest,
        message: str,
        artifact_bytes: int | None,
        file_count: int | None,
        shard_count: int | None,
    ) -> tuple[ModelArtifactFacts, str]:
        return ModelArtifactFacts(
            request.model_id,
            str(request.model_path),
            None,
            (),
            None,
            None,
            False,
            message,
            artifact_bytes,
            file_count,
            shard_count,
            artifact_bytes,
        ), message

    @classmethod
    def capture(cls, request: DeploymentQualificationRequest) -> tuple[ModelArtifactFacts, str | None]:
        path = request.model_path
        artifact_bytes, file_count, shard_count = cls._artifact_stats(path)
        config = path / "config.json"
        if not config.is_file():
            return cls._failure(
                request,
                "model config.json is missing",
                artifact_bytes,
                file_count,
                shard_count,
            )
        try:
            data = json.loads(config.read_text("utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            return cls._failure(
                request,
                f"model config.json could not be parsed: {type(exc).__name__}",
                artifact_bytes,
                file_count,
                shard_count,
            )
        if type(data) is not dict:
            return cls._failure(
                request,
                "model config.json root must be a JSON object",
                artifact_bytes,
                file_count,
                shard_count,
            )
        try:
            model_type = _optional_text(data, "model_type")
            architectures = _architectures(data)
            torch_dtype = _optional_text(data, "torch_dtype")
            context_length = _context_length(data)
        except ValueError as exc:
            return cls._failure(
                request,
                f"model config.json has invalid typed facts: {exc}",
                artifact_bytes,
                file_count,
                shard_count,
            )
        return ModelArtifactFacts(
            request.model_id,
            str(path),
            model_type,
            architectures,
            torch_dtype,
            context_length,
            True,
            None,
            artifact_bytes,
            file_count,
            shard_count,
            artifact_bytes,
        ), None


__all__ = ["ModelArtifactProbe"]
