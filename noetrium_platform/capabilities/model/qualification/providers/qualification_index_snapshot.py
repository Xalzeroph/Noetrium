from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
from pathlib import Path
from typing import Any, Callable

from noetrium_platform.capabilities.model.qualification.api import (
    PackageArtifactFacts,
    PackageDependencyNodeFacts,
)


RunCommand = Callable[[tuple[str, ...], float], tuple[int, str, str]]
_WORKER_PATH = Path(__file__).with_name("qualification_index_worker.py")
_MAIN_FIELDS = frozenset({
    "selected_version",
    "artifacts",
    "dependency_nodes",
    "dependency_closure_complete",
    "dependency_closure_error",
    "error",
})
_ROOT_FIELDS = frozenset({"root_candidates"})
_ROOT_CANDIDATE_FIELDS = frozenset({"version", "compatible", "error"})
_ARTIFACT_REQUIRED = frozenset({"filename", "version", "kind"})
_ARTIFACT_OPTIONAL = frozenset({
    "sha256", "python_tags", "abi_tags", "platform_tags", "requires_python",
    "metadata_sha256", "dependency_requirements",
})


def _failure(detail: str) -> dict[str, object]:
    message = detail[:240]
    return {
        "selected_version": None,
        "artifacts": (),
        "dependency_nodes": (),
        "dependency_closure_complete": False,
        "dependency_closure_error": message,
        "error": message,
    }


def _sequence(value: Any, field: str) -> tuple[Any, ...]:
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, Sequence):
        raise ValueError(f"{field} must be a sequence")
    return tuple(value)


def _text(value: Any, field: str, *, optional: bool = False) -> str | None:
    if value is None and optional:
        return None
    if not isinstance(value, str) or (not optional and not value.strip()):
        raise ValueError(f"{field} must be text")
    return value


def _boolean(value: Any, field: str) -> bool:
    if not isinstance(value, bool):
        raise ValueError(f"{field} must be boolean")
    return value


def _strings(value: Any, field: str) -> tuple[str, ...]:
    rows = _sequence(value, field)
    if any(not isinstance(item, str) for item in rows):
        raise ValueError(f"{field} must contain only strings")
    return tuple(rows)


def _artifact(document: Any) -> PackageArtifactFacts:
    if not isinstance(document, Mapping):
        raise ValueError("artifact must be a mapping")
    fields = frozenset(document)
    if not _ARTIFACT_REQUIRED.issubset(fields) or not fields.issubset(_ARTIFACT_REQUIRED | _ARTIFACT_OPTIONAL):
        raise ValueError("artifact fields are invalid")
    return PackageArtifactFacts(
        filename=str(_text(document["filename"], "filename")),
        version=str(_text(document["version"], "version")),
        kind=str(_text(document["kind"], "kind")),
        sha256=_text(document.get("sha256"), "sha256", optional=True),
        python_tags=_strings(document.get("python_tags", ()), "python_tags"),
        abi_tags=_strings(document.get("abi_tags", ()), "abi_tags"),
        platform_tags=_strings(document.get("platform_tags", ()), "platform_tags"),
        requires_python=_text(document.get("requires_python"), "requires_python", optional=True),
        metadata_sha256=_text(document.get("metadata_sha256"), "metadata_sha256", optional=True),
        dependency_requirements=_strings(
            document.get("dependency_requirements", ()), "dependency_requirements"
        ),
    )


def _dependency_node(document: Any) -> PackageDependencyNodeFacts:
    if not isinstance(document, Mapping):
        raise ValueError("dependency node must be a mapping")
    if frozenset(document) != frozenset({"package", "version", "index_url", "artifact"}):
        raise ValueError("dependency node fields are invalid")
    return PackageDependencyNodeFacts(
        package=str(_text(document["package"], "package")),
        version=str(_text(document["version"], "version")),
        index_url=str(_text(document["index_url"], "index_url")),
        artifact=_artifact(document["artifact"]),
    )


def _decode_root_candidates(payload: Mapping[str, Any]) -> dict[str, object]:
    if frozenset(payload) != _ROOT_FIELDS:
        raise ValueError("root candidate payload fields are invalid")
    rows = []
    for item in _sequence(payload["root_candidates"], "root_candidates"):
        if not isinstance(item, Mapping) or frozenset(item) != _ROOT_CANDIDATE_FIELDS:
            raise ValueError("root candidate fields are invalid")
        rows.append({
            "version": str(_text(item["version"], "root candidate version")),
            "compatible": _boolean(item["compatible"], "root candidate compatible"),
            "error": _text(item["error"], "root candidate error", optional=True),
        })
    return {"root_candidates": tuple(rows)}


def _decode_main(payload: Mapping[str, Any]) -> dict[str, object]:
    if frozenset(payload) != _MAIN_FIELDS:
        raise ValueError("simple-index payload fields are invalid")
    error = _text(payload["error"], "error", optional=True)
    if error and not _sequence(payload["artifacts"], "artifacts"):
        return _failure(error)
    selected_version = _text(payload["selected_version"], "selected_version", optional=True)
    artifacts = tuple(_artifact(item) for item in _sequence(payload["artifacts"], "artifacts"))
    dependency_nodes = tuple(
        _dependency_node(item)
        for item in _sequence(payload["dependency_nodes"], "dependency_nodes")
    )
    return {
        "selected_version": selected_version,
        "artifacts": artifacts,
        "dependency_nodes": dependency_nodes,
        "dependency_closure_complete": _boolean(
            payload["dependency_closure_complete"], "dependency_closure_complete"
        ),
        "dependency_closure_error": _text(
            payload["dependency_closure_error"], "dependency_closure_error", optional=True
        ),
        "error": error,
    }


def decode_snapshot_output(output: str) -> dict[str, object]:
    try:
        payload = json.loads(output.strip().splitlines()[-1])
    except (json.JSONDecodeError, IndexError):
        detail = output.strip().splitlines()[-1] if output.strip() else "empty probe output"
        return _failure(f"target simple-index probe returned invalid JSON: {detail}")
    if not isinstance(payload, Mapping):
        return _failure("target simple-index probe returned a non-object payload")
    try:
        if "root_candidates" in payload:
            return _decode_root_candidates(payload)
        return _decode_main(payload)
    except (KeyError, TypeError, ValueError) as exc:
        return _failure(f"target simple-index probe returned invalid payload: {exc}")


class TargetPackageIndexSnapshotProbe:
    """Run the target-Python dependency worker and decode only typed observations."""

    def __init__(self, run: RunCommand) -> None:
        self._run = run

    def capture(
        self,
        python: Path,
        package: str,
        index_url: str,
        available_versions: tuple[str, ...],
        timeout: float,
        *,
        fallback_index: str,
        preferred_versions: dict[str, str | None] | None = None,
        root_version: str | None = None,
        root_candidates: tuple[str, ...] = (),
        cache_dir: Path | None = None,
    ) -> dict[str, object]:
        if not _WORKER_PATH.is_file():
            return _failure("target simple-index worker is missing from the installed package")
        preferred = {
            str(name).lower().replace("_", "-"): str(value)
            for name, value in (preferred_versions or {}).items()
            if value
        }
        argv = (
            str(python),
            str(_WORKER_PATH),
            index_url,
            package,
            json.dumps(available_versions),
            fallback_index,
            json.dumps(preferred),
            root_version or "",
            json.dumps(tuple(str(value) for value in root_candidates)),
            str(cache_dir) if cache_dir is not None else "",
        )
        code, out, err = self._run(argv, timeout)
        if code != 0:
            raw_detail = str(err or out or "")
            detail = raw_detail.strip().splitlines()[-1] if raw_detail.strip() else f"exit={code}"
            return _failure(f"target simple-index probe failed: {detail}")
        return decode_snapshot_output(str(out or ""))


__all__ = [
    "TargetPackageIndexSnapshotProbe",
    "decode_snapshot_output",
]
