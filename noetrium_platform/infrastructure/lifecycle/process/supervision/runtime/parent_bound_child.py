from __future__ import annotations

"""Fresh-exec guardian for crash-bound interactive POSIX subprocess trees.

This module is executed in a new Python interpreter, never through preexec_fn.
The guardian is the session/process-group leader created by the owner process.
It starts the real command in the same process group and remains alive until
that command exits.  Parent death or owner-directed termination therefore
converges the complete inherited process group rather than only one PID.
"""

import argparse
import ctypes
import os
import signal
import subprocess
import sys
import time


def _linux_parent_death_signal() -> None:
    if not sys.platform.startswith("linux"):
        return
    libc = ctypes.CDLL(None, use_errno=True)
    pr_set_pdeathsig = 1
    if libc.prctl(pr_set_pdeathsig, int(signal.SIGTERM), 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, "prctl(PR_SET_PDEATHSIG) failed")


def _forward_to_owned_group(signum: int, _frame) -> None:
    # Reset this signal first so the group delivery terminates the guardian
    # instead of recursively invoking the handler.
    signal.signal(signum, signal.SIG_DFL)
    os.killpg(os.getpgrp(), signum)


def _kill_owned_group() -> None:
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGHUP, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_DFL)
    os.killpg(os.getpgrp(), signal.SIGKILL)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--parent-pid", type=int, required=True)
    parser.add_argument("command", nargs=argparse.REMAINDER)
    ns = parser.parse_args(argv)
    command = list(ns.command)
    if command and command[0] == "--":
        command = command[1:]
    if ns.parent_pid <= 0 or not command:
        return 126

    for sig in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(sig, _forward_to_owned_group)

    _linux_parent_death_signal()
    if os.getppid() != ns.parent_pid:
        _kill_owned_group()
        return 125

    try:
        child = subprocess.Popen(command)
    except BaseException:
        return 127

    while True:
        code = child.poll()
        if code is not None:
            return int(code) if code >= 0 else 128 + abs(int(code))
        if os.getppid() != ns.parent_pid:
            _kill_owned_group()
            return 125
        time.sleep(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
