from __future__ import annotations

import hashlib

from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSnapshot


class TmuxSnapshotParseError(RuntimeError):
    pass


def parse_tmux_snapshot(session_name: str, stdout: str) -> PersistentSessionSnapshot:
    line = stdout.rstrip("\r\n")
    # tmux 3.0a emits the format escape ``\\t`` literally, while newer
    # versions may emit an actual tab. Accept only these two exact encodings;
    # do not fall back to whitespace splitting because command/cwd identity is
    # part of the frozen session proof.
    literal_separator = "\\t"
    candidates = (line.split("\t", 5), line.split(literal_separator, 5))
    parts = next(
        (candidate for candidate in candidates if len(candidate) == 6 and candidate[0] == session_name),
        (),
    )
    if len(parts) != 6:
        actual = line.split("\t", 5)
        literal = line.split(literal_separator, 5)
        digest = hashlib.sha256(stdout.encode("utf-8", "replace")).hexdigest()
        raise TmuxSnapshotParseError(
            "tmux returned malformed or non-exact session snapshot"
            f"; stdout_len={len(stdout)}; digest={digest}"
            f"; actual_tab_fields={len(actual)}; literal_tab_fields={len(literal)}"
            f"; first_field_matches={line.split(chr(9), 1)[0] == session_name or line.split(literal_separator, 1)[0] == session_name}"
        )
    session_generation = parts[1]
    if not session_generation:
        raise TmuxSnapshotParseError("tmux returned missing session generation")
    try:
        controller_pid = int(parts[2])
    except ValueError as exc:
        raise TmuxSnapshotParseError("tmux returned invalid controller PID") from exc
    return PersistentSessionSnapshot(
        session_name=session_name,
        exists=True,
        controller_pid=controller_pid,
        controller_dead=parts[3] == "1",
        start_command=parts[4],
        current_path=parts[5],
        session_generation=session_generation,
    )


__all__ = ["TmuxSnapshotParseError", "parse_tmux_snapshot"]
