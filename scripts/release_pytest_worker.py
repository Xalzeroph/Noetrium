from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path


def _fallback_without_pytest(arguments: list[str]) -> int:
    """Run one dependency-free fixture module for runner lifecycle tests only."""

    import inspect
    from pathlib import Path
    import runpy
    import signal

    # Keep the fixture alive until the release runner's force phase so the
    # process-group reaper is exercised under the same failure timing as the
    # real pytest worker.
    signal.signal(signal.SIGTERM, signal.SIG_IGN)

    paths = [Path(item) for item in arguments if not item.startswith("-")]
    if not paths:
        paths = sorted(Path.cwd().glob("test_*.py"))
    if len(paths) != 1 or not paths[0].is_file():
        print("PYTEST_UNAVAILABLE: full release regression requires pytest", file=sys.stderr)
        return 2
    namespace = runpy.run_path(str(paths[0]))
    tests = [
        value
        for name, value in namespace.items()
        if name.startswith("test") and callable(value) and not inspect.signature(value).parameters
    ]
    if "--collect-only" in arguments:
        print(f"{len(tests)} test collected")
        return 0
    for test in tests:
        test()
    print(f"{len(tests)} passed")
    return 0


def main() -> int:
    """Replace the worker with pytest instead of embedding ``pytest.main``.

    A release shard owns one OS process group.  ``exec`` preserves that group
    while making pytest itself the process leader, so plugin threads, atexit
    handlers, and child-process lifecycle are governed by normal interpreter
    shutdown rather than by an embedded pytest call returning into a long-lived
    wrapper interpreter.
    """

    if importlib.util.find_spec("pytest") is None:
        return _fallback_without_pytest(sys.argv[1:])

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
