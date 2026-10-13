from __future__ import annotations

import contextlib
import io
import os
from pathlib import Path
import signal
from tempfile import TemporaryDirectory
import time
import unittest
from unittest import mock

from scripts import control_worker


class ControlWorkerTerminalFrameTests(unittest.TestCase):
    def _serve(self, root: Path, dispatch):
        socket_path = root / "control.sock"
        patches = (
            mock.patch.object(control_worker, "_preload_runtime", lambda: ((), "gpu")),
            mock.patch.object(control_worker, "_source_drift", lambda _baseline: None),
            mock.patch.object(
                control_worker,
                "_runtime_is_fresh",
                lambda _argv, _gpu: True,
            ),
            mock.patch.object(control_worker, "_dispatch", dispatch),
            mock.patch.dict(
                os.environ,
                {
                    "NOETRIUM_CONTROL_STATE_ROOT": str(root),
                    "NOETRIUM_BOOTSTRAP_OWNER_PID": "",
                    "NOETRIUM_BOOTSTRAP_OWNER_BOOT": "",
                    "NOETRIUM_BOOTSTRAP_OWNER_START": "",
                    "NOETRIUM_CONTROL_REQUEST_LEASE": "",
                    "NOETRIUM_CONTROL_WORKER_USE_LOCK": "",
                },
                clear=False,
            ),
        )
        for patch in patches:
            patch.start()

        server_pid = os.fork()
        if server_pid == 0:
            raise SystemExit(control_worker.serve(socket_path))

        deadline = time.monotonic() + 3.0
        while not socket_path.exists():
            if time.monotonic() >= deadline:
                os.kill(server_pid, signal.SIGKILL)
                os.waitpid(server_pid, 0)
                raise AssertionError("resident control socket was not created")
            time.sleep(0.01)
        return socket_path, server_pid, patches

    @staticmethod
    def _stop(server_pid: int, patches) -> None:
        try:
            os.kill(server_pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        os.waitpid(server_pid, 0)
        for patch in reversed(patches):
            patch.stop()

    def test_signal_killed_child_gets_supervisor_terminal_frame(self) -> None:
        def dispatch(argv: tuple[str, ...]) -> int:
            if argv != ("die",):
                raise AssertionError(argv)
            os.kill(os.getpid(), signal.SIGKILL)
            raise AssertionError("SIGKILL returned")

        with TemporaryDirectory() as temporary:
            socket_path, server_pid, patches = self._serve(
                Path(temporary),
                dispatch,
            )
            stderr = io.StringIO()
            try:
                with contextlib.redirect_stderr(stderr):
                    result = control_worker.request(socket_path, ("die",))
            finally:
                self._stop(server_pid, patches)

        self.assertEqual(result, 1)
        self.assertNotEqual(result, control_worker._UNAVAILABLE_EXIT)
        self.assertIn("SIGKILL", stderr.getvalue())
        self.assertNotIn("without a terminal frame", stderr.getvalue())

    def test_normal_request_terminal_round_trip(self) -> None:
        def dispatch(argv: tuple[str, ...]) -> int:
            if argv != ("ok",):
                raise AssertionError(argv)
            return 0

        with TemporaryDirectory() as temporary:
            socket_path, server_pid, patches = self._serve(
                Path(temporary),
                dispatch,
            )
            try:
                result = control_worker.request(socket_path, ("ok",))
            finally:
                self._stop(server_pid, patches)

        self.assertEqual(result, 0)


if __name__ == "__main__":
    unittest.main()
