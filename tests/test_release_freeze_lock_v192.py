from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from noetrium_platform.foundation.governance.release.runtime.freeze_lock import ReleaseFreezeBusy, ReleaseFreezeLock


class ReleaseFreezeLockV192Tests(unittest.TestCase):
    def test_lock_lives_outside_source_root(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            lock = ReleaseFreezeLock(root)
            self.assertEqual(lock.path.parent, root.parent)
            self.assertFalse(lock.path.is_relative_to(root))

    def test_second_release_process_fails_closed_while_freeze_is_active(self):
        project_root = Path(__file__).resolve().parents[1]
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "source"
            root.mkdir()
            env = os.environ.copy()
            env["PYTHONPATH"] = str(project_root)
            code = (
                f"import sys; sys.path.insert(0, {str(project_root)!r}); "
                "from pathlib import Path; "
                "from noetrium_platform.foundation.governance.release.runtime.freeze_lock import ReleaseFreezeBusy, ReleaseFreezeLock; "
                f"root=Path({str(root)!r}); "
                "\ntry:\n"
                "    with ReleaseFreezeLock(root):\n"
                "        raise SystemExit(0)\n"
                "except ReleaseFreezeBusy:\n"
                "    raise SystemExit(23)\n"
            )
            with ReleaseFreezeLock(root):
                result = subprocess.run(
                    [sys.executable, "-c", code],
                    cwd=project_root,
                    env=env,
                    check=False,
                    timeout=10,
                )
            self.assertEqual(result.returncode, 23)


if __name__ == "__main__":
    unittest.main()
