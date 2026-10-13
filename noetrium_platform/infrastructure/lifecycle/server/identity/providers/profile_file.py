from __future__ import annotations

from collections.abc import Mapping
import os
from pathlib import Path
import re


class ServerProfileFileError(ValueError):
    """A managed server profile file is malformed or unsafe to load."""


_KEY_RE = re.compile(r"^[A-Z][A-Z0-9_]*$")


def load_server_profile_environment(
    path: str | Path,
    *,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Load one literal, non-shell server profile into an environment mapping.

    The profile format intentionally accepts only ``KEY=value`` records,
    comments, blank lines, and fully single/double-quoted values.  It does not
    expand variables, execute shell syntax, or silently accept duplicate keys.
    This keeps the profile a data boundary shared by health, release, and
    session operations instead of making every caller hand-copy a large set of
    exports.
    """

    profile_path = Path(path).expanduser().resolve()
    if not profile_path.is_file():
        raise ServerProfileFileError(f"server profile file is not a regular file: {profile_path}")
    source = os.environ if base is None else base
    # A profile file is the single authority for server bindings.  Remove
    # inherited RP_SERVER_* values before applying it so a stale exported
    # field cannot silently fill a missing field or override a deliberate edit.
    values = {key: value for key, value in source.items() if not key.startswith("RP_SERVER_")}
    seen: set[str] = set()
    try:
        lines = profile_path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise ServerProfileFileError(f"server profile file cannot be read: {profile_path}") from exc
    for line_number, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if line.startswith("export "):
            line = line[7:].lstrip()
        if "=" not in line:
            raise ServerProfileFileError(f"profile line {line_number} must be KEY=value")
        key, value = line.split("=", 1)
        key = key.strip()
        if _KEY_RE.fullmatch(key) is None:
            raise ServerProfileFileError(f"profile line {line_number} has an unsafe key")
        if key in seen:
            raise ServerProfileFileError(f"profile line {line_number} duplicates {key}")
        seen.add(key)
        value = value.strip()
        if value.startswith(("'", '"')):
            quote = value[0]
            if len(value) < 2 or value[-1] != quote:
                raise ServerProfileFileError(f"profile line {line_number} has an unterminated quoted value")
            value = value[1:-1]
            if quote == '"' and '\\"' in value:
                value = value.replace('\\"', '"')
        elif any(char.isspace() for char in value):
            raise ServerProfileFileError(
                f"profile line {line_number} contains unquoted whitespace; quote the value"
            )
        if "\x00" in key or "\x00" in value or "\r" in value or "\n" in value:
            raise ServerProfileFileError(f"profile line {line_number} contains unsafe characters")
        values[key] = value
    return values


__all__ = ["ServerProfileFileError", "load_server_profile_environment"]
