from __future__ import annotations

import json
from pathlib import Path

from noetrium_platform.capabilities.model.stack.api import ModelArtifactClosure
from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.kernel.durability import (
    sha256_bytes,
    sha256_file,
)


_WEIGHT_MANIFEST_CANDIDATES = (
    "model.safetensors.index.json",
    "pytorch_model.bin.index.json",
)
_WEIGHT_FILE_SUFFIXES = (".safetensors", ".bin")
_TOKENIZER_PRIMARY_CANDIDATES = (
    "tokenizer.json",
    "tokenizer.model",
    "spiece.model",
)
_CONFIG_FILE = "config.json"
_TOKENIZER_CONFIG_FILE = "tokenizer_config.json"
_CHAT_TEMPLATE_FILE = "chat_template.jinja"


class ModelArtifactClosureError(ValueError):
    pass


def _required_file(root: Path, relative: str) -> Path:
    path = root / relative
    if not path.is_file():
        raise ModelArtifactClosureError(
            f"model artifact closure missing required file: {relative}"
        )
    return path


def _single_file_digest(path: Path) -> str:
    digest, _size = sha256_file(path)
    return digest


def _weight_manifest_digest(root: Path) -> str:
    for relative in _WEIGHT_MANIFEST_CANDIDATES:
        path = root / relative
        if path.is_file():
            return _single_file_digest(path)

    weights = tuple(
        sorted(
            (
                path
                for path in root.iterdir()
                if path.is_file()
                and path.suffix.lower() in _WEIGHT_FILE_SUFFIXES
            ),
            key=lambda item: item.name,
        )
    )
    if not weights:
        raise ModelArtifactClosureError(
            "model artifact closure requires a weight manifest or weight file"
        )
    rows = []
    for path in weights:
        digest, size = sha256_file(path)
        rows.append(
            {
                "name": path.name,
                "sha256": digest,
                "bytes": size,
            }
        )
    return canonical_digest(
        {
            "schema": "noetrium.model-weight-manifest.v1",
            "files": rows,
        }
    )


def _tokenizer_digest(root: Path) -> str:
    for relative in _TOKENIZER_PRIMARY_CANDIDATES:
        path = root / relative
        if path.is_file():
            return _single_file_digest(path)
    raise ModelArtifactClosureError(
        "model artifact closure requires tokenizer.json, tokenizer.model, or spiece.model"
    )


def _chat_template_digest(root: Path) -> str | None:
    config_path = root / _TOKENIZER_CONFIG_FILE
    if config_path.is_file():
        try:
            value = json.loads(config_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ModelArtifactClosureError(
                "model tokenizer_config.json is unreadable"
            ) from exc
        template = value.get("chat_template") if isinstance(value, dict) else None
        if isinstance(template, str):
            return sha256_bytes(template.encode("utf-8"))
        if template is not None:
            raise ModelArtifactClosureError(
                "model tokenizer chat_template must be text when present"
            )

    template_path = root / _CHAT_TEMPLATE_FILE
    if template_path.is_file():
        return _single_file_digest(template_path)
    return None


def _model_code_digest(root: Path) -> str | None:
    files = tuple(
        sorted(
            (
                path
                for path in root.glob("*.py")
                if path.is_file()
            ),
            key=lambda item: item.name,
        )
    )
    if not files:
        return None
    rows = []
    for path in files:
        digest, size = sha256_file(path)
        rows.append(
            {
                "name": path.name,
                "sha256": digest,
                "bytes": size,
            }
        )
    return canonical_digest(
        {
            "schema": "noetrium.model-code-manifest.v1",
            "files": rows,
        }
    )


class ModelArtifactClosureAuthority:
    """Freeze immutable model artifacts into the serving-stack identity."""

    authority_id = "noetrium.model-artifact-closure.v1"

    def freeze(self, model_path: str | Path) -> ModelArtifactClosure:
        root = Path(model_path).expanduser().resolve(strict=True)
        if not root.is_dir():
            raise ModelArtifactClosureError(
                f"model artifact root is not a directory: {root}"
            )
        config_path = _required_file(root, _CONFIG_FILE)
        return ModelArtifactClosure(
            weights_manifest_sha256=_weight_manifest_digest(root),
            tokenizer_sha256=_tokenizer_digest(root),
            model_config_sha256=_single_file_digest(config_path),
            model_code_sha256=_model_code_digest(root),
            chat_template_sha256=_chat_template_digest(root),
        )


__all__ = [
    "ModelArtifactClosureAuthority",
    "ModelArtifactClosureError",
]
