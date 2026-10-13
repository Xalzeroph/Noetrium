from __future__ import annotations

from noetrium_platform.capabilities.api import ArtifactContentIdentity
from noetrium_platform.foundation.kernel.kernel import JsonInput


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip() or value != value.strip():
        raise ValueError(f"{field} must be canonical non-empty text")
    return value


def _string_tuple(value: object, field: str) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, (str, bytes, bytearray)) or not isinstance(value, tuple):
        raise TypeError(f"{field} must be a tuple")
    rows = tuple(_text(item, field) for item in value)
    if len(rows) != len(set(rows)):
        raise ValueError(f"{field} must be unique")
    return rows


def program_execution_capability_payload(
    *,
    program_id: str,
    source_text: str,
    language: str,
    entrypoint: str,
    interface_schema_id: str,
    invocation: JsonInput,
    parent_program_digests: tuple[str, ...] = (),
    input_artifacts: tuple[ArtifactContentIdentity, ...] = (),
) -> dict[str, JsonInput]:
    """Build one immutable program-execution capability request payload."""

    _text(program_id, "program execution program_id")
    if type(source_text) is not str or not source_text:
        raise ValueError("program execution source_text must be non-empty text")
    _text(language, "program execution language")
    _text(entrypoint, "program execution entrypoint")
    _text(interface_schema_id, "program execution interface_schema_id")
    parents = _string_tuple(
        parent_program_digests,
        "program execution parent_program_digests",
    )
    if type(input_artifacts) is not tuple or any(
        type(row) is not ArtifactContentIdentity for row in input_artifacts
    ):
        raise TypeError(
            "program execution input_artifacts must be ArtifactContentIdentity tuple"
        )
    return {
        "program_id": program_id,
        "source_text": source_text,
        "language": language,
        "entrypoint": entrypoint,
        "interface_schema_id": interface_schema_id,
        "invocation": invocation,
        "parent_program_digests": parents,
        "input_artifacts": tuple(
            {
                "artifact_id": row.artifact_id,
                "content_sha256": row.content_sha256,
            }
            for row in input_artifacts
        ),
    }


__all__ = ["program_execution_capability_payload"]
