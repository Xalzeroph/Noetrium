from __future__ import annotations

"""Linux exact-exec trampoline for platform-owned services.

The trampoline intentionally does not alter scheduler priority or OOM scoring.
Its only job is to preserve PID/session/process-group identity across exec so
the controller can publish ownership only after the exact executable/argv/cwd
has settled.
"""

import os
import sys


def main() -> int:
    if len(sys.argv) < 3:
        return 126
    executable = sys.argv[1]
    argv = tuple(sys.argv[2:])
    if not executable.startswith("/") or not argv or argv[0] != executable:
        return 126

    os.execve(executable, argv, dict(os.environ))
    return 127


if __name__ == "__main__":
    raise SystemExit(main())
