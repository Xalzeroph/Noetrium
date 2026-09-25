from __future__ import annotations

from pathlib import Path
import re


class ControllerEnvironmentFileError(ValueError):
    """A controller environment file is malformed or unsafe."""


_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def load_controller_environment(
    path: str | Path | None,
) -> tuple[tuple[str, str], ...]:
    """Load exact non-shell controller environment data for a run session."""

    values: dict[str, str] = {}
    if path is not None:
        source_path = Path(path).expanduser().resolve()
        if not source_path.is_file():
            raise ControllerEnvironmentFileError(
                f"controller environment file is not a regular file: {source_path}"
            )
        try:
            lines = source_path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            raise ControllerEnvironmentFileError(
                f"controller environment file cannot be read: {source_path}"
            ) from exc
    else:
        lines = ()
    seen: set[str] = set()
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ControllerEnvironmentFileError(
                f"controller environment line {line_number} must be KEY=value"
            )
        key, value = (part.strip() for part in line.split("=", 1))
        if _KEY_RE.fullmatch(key) is None or key in seen:
            raise ControllerEnvironmentFileError(
                f"controller environment line {line_number} has an invalid or duplicate key"
            )
        value = value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise ControllerEnvironmentFileError(
                    f"controller environment line {line_number} has an unterminated quoted value"
                )
            value = value[1:-1]
        elif any(char.isspace() for char in value):
            raise ControllerEnvironmentFileError(
                f"controller environment line {line_number} contains unquoted whitespace"
            )
        if any(char in key + value for char in "\x00\r\n"):
            raise ControllerEnvironmentFileError(
                f"controller environment line {line_number} contains unsafe characters"
            )
        seen.add(key)
        values[key] = value
    return tuple(sorted(values.items()))


__all__ = ["ControllerEnvironmentFileError", "load_controller_environment"]
