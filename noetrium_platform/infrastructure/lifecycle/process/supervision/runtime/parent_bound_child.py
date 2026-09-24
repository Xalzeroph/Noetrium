from __future__ import annotations

"""Fresh-exec guardian for crash-bound interactive POSIX subprocess trees.

The owner spawns this module as a new session leader. The guardian starts the
real command in a distinct child process group, remains alive until that group
converges, and turns owner death into a tree-level SIGKILL. A fresh interpreter
is used deliberately instead of multithreaded preexec_fn.
"""

import argparse
import ctypes
import os
import signal
import subprocess
import sys

from noetrium_platform.foundation.kernel.kernel.retry import blocking_wait


_child_group: int | None = None


def _linux_parent_death_signal() -> None:
    if not sys.platform.startswith("linux"):
        return
    libc = ctypes.CDLL(None, use_errno=True)
    # PR_SET_PDEATHSIG = 1. SIGUSR2 is guardian-private and is converted below
    # into a tree-level SIGKILL rather than being inherited by the real child.
    if libc.prctl(1, int(signal.SIGUSR2), 0, 0, 0) != 0:
        errno = ctypes.get_errno()
        raise OSError(errno, "prctl(PR_SET_PDEATHSIG) failed")


def _forward(signum: int, _frame) -> None:
    child_group = _child_group
    if child_group is None:
        return
    try:
        os.killpg(child_group, signum)
    except ProcessLookupError:
        return


def _force_child(_signum: int, _frame) -> None:
    child_group = _child_group
    if child_group is not None:
        try:
            os.killpg(child_group, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _owner_died(_signum: int | None = None, _frame=None) -> None:
    _force_child(signal.SIGKILL, None)
    os._exit(125)


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

    signal.signal(signal.SIGTERM, _forward)
    signal.signal(signal.SIGHUP, _forward)
    signal.signal(signal.SIGINT, _forward)
    signal.signal(signal.SIGUSR1, _force_child)
    signal.signal(signal.SIGUSR2, _owner_died)

    _linux_parent_death_signal()
    if os.getppid() != ns.parent_pid:
        _owner_died()

    global _child_group
    try:
        child = subprocess.Popen(command, process_group=0)
    except BaseException:
        return 127
    _child_group = int(child.pid)

    # Close the tiny race between child creation and publishing its group into
    # the owner-death handler.
    if os.getppid() != ns.parent_pid:
        _owner_died()

    while True:
        code = child.poll()
        if code is not None:
            return int(code) if code >= 0 else 128 + abs(int(code))
        if os.getppid() != ns.parent_pid:
            _owner_died()
        blocking_wait(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
