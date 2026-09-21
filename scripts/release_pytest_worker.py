from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def main() -> int:
    """Replace the worker with pytest instead of embedding ``pytest.main``.

    A release shard owns one OS process group.  ``exec`` preserves that group
    while making pytest itself the process leader, so plugin threads, atexit
    handlers, and child-process lifecycle are governed by normal interpreter
    shutdown rather than by an embedded pytest call returning into a long-lived
    wrapper interpreter.
    """

    if importlib.util.find_spec("pytest") is None:
        print("PYTEST_UNAVAILABLE: release regression requires pytest", file=sys.stderr)
        return 2

    arguments = list(sys.argv[1:])
    env = os.environ.copy()
    if env.get("RELEASE_PYTEST_RESULT_PATH"):
        # The worker may run with a temporary checkout/fixture as cwd.  Keep the
        # release plugin import rooted at this platform source tree rather than
        # relying on cwd or an ambient PYTHONPATH.
        project_root = str(Path(__file__).resolve().parents[1])
        current = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = project_root if not current else project_root + os.pathsep + current
        arguments = ["-p", "scripts.release_pytest_plugin", *arguments]
    if os.name == "nt":
        # Windows has no POSIX exec process-image replacement semantics.
        # This worker is one-shot, so running pytest in-process preserves the
        # worker as the process-group leader without creating a wrapper child.
        os.environ.clear()
        os.environ.update(env)
        project_root = str(Path(__file__).resolve().parents[1])
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        import pytest
        return int(pytest.main(arguments))
    os.execve(sys.executable, [sys.executable, "-m", "pytest", *arguments], env)
    raise RuntimeError("os.execve unexpectedly returned")


if __name__ == "__main__":
    raise SystemExit(main())
