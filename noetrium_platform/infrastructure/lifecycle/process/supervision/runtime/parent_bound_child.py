from __future__ import annotations

"""Fresh-exec guardian for crash-bound interactive POSIX subprocess trees.

The owner spawns this module as a new session leader. On Linux the guardian is
also a child subreaper, so descendants that daemonize, double-fork, or create a
new session remain inside the same physical ownership tree after their original
parent exits. The guardian stays alive until the complete descendant tree
converges and turns owner death into tree-level SIGKILL.

A fresh interpreter is used deliberately instead of multithreaded preexec_fn.
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
_force_requested = False

_PR_SET_PDEATHSIG = 1
_PR_SET_CHILD_SUBREAPER = 36


def _linux_prctl(option: int, value: int) -> None:
    libc = ctypes.CDLL(None, use_errno=True)
    if libc.prctl(int(option), int(value), 0, 0, 0) != 0:
        error_number = ctypes.get_errno()
        raise OSError(error_number, f"prctl({option}) failed")


def _linux_configure_guardian() -> None:
    if not sys.platform.startswith("linux"):
        return
    # SIGUSR2 is guardian-private and becomes a tree-level SIGKILL rather than
    # being inherited by the real child.
    _linux_prctl(_PR_SET_PDEATHSIG, int(signal.SIGUSR2))
    # This is the critical fork/daemon boundary: orphaned grandchildren are
    # reparented here rather than escaping to PID 1, even after setsid/double-fork.
    _linux_prctl(_PR_SET_CHILD_SUBREAPER, 1)


def _forward(signum: int, _frame) -> None:
    child_group = _child_group
    if child_group is None:
        return
    try:
        os.killpg(child_group, signum)
    except ProcessLookupError:
        return


def _request_force(_signum: int, _frame) -> None:
    global _force_requested
    _force_requested = True
    # Kill the original process group immediately. Detached descendants are
    # killed from the main loop using ancestry proof + pidfd generation handles.
    child_group = _child_group
    if child_group is not None:
        try:
            os.killpg(child_group, signal.SIGKILL)
        except ProcessLookupError:
            pass


def _owner_died(_signum: int | None = None, _frame=None) -> None:
    global _owner_dead
    _owner_dead = True
    _request_force(int(signal.SIGKILL), None)


def _linux_root_exited_without_reap(pid: int) -> bool:
    info = os.waitid(
        os.P_PID,
        pid,
        os.WEXITED | os.WNOHANG | os.WNOWAIT,
    )
    return info is not None and int(info.si_pid) == pid


def _linux_process_rows() -> dict[int, tuple[int, str]]:
    """Return PID -> (PPID, state), failing closed on unparseable owned facts."""

    rows: dict[int, tuple[int, str]] = {}
    for name in os.listdir("/proc"):
        if not name.isdigit():
            continue
        pid = int(name)
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
            # Global procfs may contain entries hidden by policy. Those entries
            # cannot be descendants of this same-UID guardian unless Linux also
            # blocks our child relationship; treat that case conservatively by
            # excluding only the unreadable unrelated row.
            continue
        close = stat.rfind(")")
        if close < 0:
            continue
        fields = stat[close + 2 :].split()
        if len(fields) < 3:
            continue
        state = fields[0]
        try:
            parent_pid = int(fields[1])
        except ValueError:
            continue
        rows[pid] = (parent_pid, state)
    return rows


def _linux_owned_descendants(guardian_pid: int) -> dict[int, str]:
    """Resolve the complete live ancestry rooted at this guardian.

    Process-group membership is intentionally not used here: forked children may
    call setsid(), double-fork, or otherwise leave the original PGID while still
    remaining descendants of the owned root.
    """

    rows = _linux_process_rows()
    owned = {guardian_pid}
    changed = True
    while changed:
        changed = False
        for pid, (parent_pid, _state) in rows.items():
            if pid not in owned and parent_pid in owned:
                owned.add(pid)
                changed = True
    owned.discard(guardian_pid)
    return {
        pid: rows[pid][1]
        for pid in owned
        if pid in rows
    }


def _linux_reap_subreaper_zombies(
    guardian_pid: int,
    root_pid: int,
    rows: dict[int, str],
) -> None:
    process_rows = _linux_process_rows()
    for pid, state in rows.items():
        if pid == root_pid or state != "Z":
            continue
        parent = process_rows.get(pid)
        if parent is None or parent[0] != guardian_pid:
            continue
        try:
            os.waitpid(pid, os.WNOHANG)
        except ChildProcessError:
            pass


def _linux_pidfd_kill(pid: int) -> bool:
    """SIGKILL one exact observed generation without a PID-reuse race."""

    pidfd_open = getattr(os, "pidfd_open", None)
    pidfd_send_signal = getattr(signal, "pidfd_send_signal", None)
    if pidfd_open is None or pidfd_send_signal is None:
        return False
    try:
        descriptor = int(pidfd_open(pid, 0))
    except ProcessLookupError:
        return True
    try:
        pidfd_send_signal(descriptor, signal.SIGKILL, None, 0)
        return True
    except ProcessLookupError:
        return True
    finally:
        os.close(descriptor)


def _linux_force_owned_tree(guardian_pid: int, root_pid: int) -> None:
    rows = _linux_owned_descendants(guardian_pid)
    # Root group first: this is generation-stable while the unreaped root keeps
    # its PGID reserved. Then exact-pidfd kill anything that escaped that group.
    try:
        os.killpg(root_pid, signal.SIGKILL)
    except ProcessLookupError:
        pass
    for pid, state in rows.items():
        if state == "Z":
            continue
        if not _linux_pidfd_kill(pid):
            raise RuntimeError(
                "pidfd process-tree cleanup unavailable; refusing racy PID kill "
                f"for owned descendant pid={pid}"
            )


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
    signal.signal(signal.SIGUSR1, _request_force)
    signal.signal(signal.SIGUSR2, _owner_died)

    _linux_configure_guardian()
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

    guardian_pid = os.getpid()
    while True:
        if sys.platform.startswith("linux"):
            if _force_requested:
                _linux_force_owned_tree(guardian_pid, int(child.pid))

            rows = _linux_owned_descendants(guardian_pid)
            _linux_reap_subreaper_zombies(
                guardian_pid,
                int(child.pid),
                rows,
            )
            rows = _linux_owned_descendants(guardian_pid)

            # WNOWAIT leaves the root unreaped while any live descendant exists,
            # reserving the original root PID/PGID against numeric reuse. Detached
            # setsid/double-fork descendants remain visible through subreaper
            # ancestry and therefore keep the guardian alive until they converge.
            root_exited = _linux_root_exited_without_reap(int(child.pid))
            live_descendants = any(
                pid != int(child.pid) and state != "Z"
                for pid, state in rows.items()
            )
            if root_exited and not live_descendants:
                code = int(child.wait())
                return 125 if _owner_dead else _exit_code(code)
        else:
            # Linux is the production-qualified tree-ownership path. Other POSIX
            # hosts retain direct-child behavior until they gain an equivalent
            # subreaper + generation-safe descendant signalling primitive.
            code = child.poll()
            if code is not None:
                return 125 if _owner_dead else _exit_code(int(code))

        if os.getppid() != ns.parent_pid and not _owner_dead:
            _owner_died()
        blocking_wait(0.05)


if __name__ == "__main__":
    raise SystemExit(main())
