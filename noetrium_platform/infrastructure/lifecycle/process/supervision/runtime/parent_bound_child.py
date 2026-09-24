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
_owner_dead = False


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
    global _owner_dead
    _owner_dead = True
    # Keep the guardian itself alive as the physical ownership anchor until the
    # complete target process group has converged.
    _force_child(signal.SIGKILL, None)


def _linux_root_exited_without_reap(pid: int) -> bool:
    info = os.waitid(
        os.P_PID,
        pid,
        os.WEXITED | os.WNOHANG | os.WNOWAIT,
    )
    return info is not None and int(info.si_pid) == pid


def _linux_group_has_live_descendants(group_id: int, root_pid: int) -> bool:
    """Observe non-zombie group members while root still anchors its PGID."""

    try:
        entries = os.listdir("/proc")
    except OSError:
        # Linux without observable procfs cannot prove process-tree convergence.
        return True
    for name in entries:
        if not name.isdigit():
            continue
        pid = int(name)
        if pid == root_pid:
            continue
        try:
            with open(
                os.path.join("/proc", name, "stat"),
                "r",
                encoding="utf-8",
            ) as handle:
                stat = handle.read()
        except (FileNotFoundError, ProcessLookupError):
            continue
        except OSError:
            # A same-UID descendant should be observable. Unknown process facts
            # cannot prove the group has converged.
            return True
        close = stat.rfind(")")
        if close < 0:
            return True
        fields = stat[close + 2 :].split()
        if len(fields) < 3:
            return True
        state = fields[0]
        try:
            process_group = int(fields[2])
        except ValueError:
            return True
        if process_group == group_id and state != "Z":
            return True
    return False


def _exit_code(code: int) -> int:
    return int(code) if code >= 0 else 128 + abs(int(code))


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
        if sys.platform.startswith("linux"):
            # WNOWAIT deliberately leaves an exited root unreaped. Its PID/PGID
            # remains reserved while descendants are still live, so delayed TERM
            # or SIGUSR1 escalation cannot target a later group that reused the
            # same numeric identifier.
            if _linux_root_exited_without_reap(int(child.pid)):
                if not _linux_group_has_live_descendants(
                    int(child.pid),
                    int(child.pid),
                ):
                    code = int(child.wait())
                    return 125 if _owner_dead else _exit_code(code)
        else:
            # Linux is the production-qualified path. Other POSIX hosts retain
            # direct-child behavior until they gain an equivalent generation-
            # preserving process-group observation primitive.
            code = child.poll()
            if code is not None:
                return 125 if _owner_dead else _exit_code(int(code))

        if os.getppid() != ns.parent_pid and not _owner_dead:
            _owner_died()
        blocking_wait(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
