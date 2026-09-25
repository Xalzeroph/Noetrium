from __future__ import annotations

"""Linux-only self-prioritizing exec trampoline for platform-owned services.

The trampoline mutates only its own process before exec, eliminating PID-reuse
races that would exist if a multithreaded controller tried to renice a child by
PID after spawn. The PID/session/process-group survive exec unchanged.
"""

import os
from pathlib import Path
import sys


_TARGET_NICE = 5
_TARGET_OOM_SCORE_ADJ = 500


def _apply_self_competition_policy() -> tuple[str, ...]:
    warnings: list[str] = []

    try:
        current = os.getpriority(os.PRIO_PROCESS, 0)
        if current < _TARGET_NICE:
            os.setpriority(os.PRIO_PROCESS, 0, _TARGET_NICE)
    except (AttributeError, OSError) as exc:
        warnings.append(f"nice:{type(exc).__name__}:{exc}")

    oom_path = Path("/proc/self/oom_score_adj")
    try:
        current_oom = int(oom_path.read_text("utf-8").strip())
        if current_oom < _TARGET_OOM_SCORE_ADJ:
            oom_path.write_text(str(_TARGET_OOM_SCORE_ADJ), encoding="utf-8")
    except (OSError, ValueError) as exc:
        warnings.append(f"oom-score:{type(exc).__name__}:{exc}")

    return tuple(warnings)


def main() -> int:
    if len(sys.argv) < 3:
        return 126
    executable = sys.argv[1]
    argv = tuple(sys.argv[2:])
    if not executable.startswith("/") or not argv or argv[0] != executable:
        return 126

    warnings = _apply_self_competition_policy()
    if warnings:
        os.write(
            2,
            (
                "noetrium opportunistic process policy degraded: "
                + ";".join(warnings)
                + "\n"
            ).encode("utf-8", errors="replace"),
        )
    os.execve(executable, argv, dict(os.environ))
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
