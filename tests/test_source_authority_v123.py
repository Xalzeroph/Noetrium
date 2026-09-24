from pathlib import Path
import tempfile
import unittest

from noetrium_platform.foundation.governance.architecture import audit_source_authorities
from tests_support import repository_architecture_report


class SourceAuthorityV123Tests(unittest.TestCase):
    def test_current_tree_has_no_source_authority_violation(self):
        root = Path(__file__).resolve().parents[1]
        self.assertEqual(audit_source_authorities(root), ())
        self.assertEqual(repository_architecture_report().source_authority_violations, ())

    def test_process_spawn_outside_backend_is_rejected_even_when_import_is_legal(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "runtime_manager"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "import subprocess\n\ndef start():\n    return subprocess.Popen(['x'])\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "service.process_spawn")
            self.assertEqual(findings[0].line, 4)

    def test_raw_file_replace_outside_durable_filesystem_authority_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "runtime_manager"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "rogue.py").write_text(
                "import os\n\ndef publish(tmp, target):\n    os.replace(tmp, target)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "filesystem.atomic_replace")

    def test_checkpoint_publish_cannot_escape_checkpoint_coordinator(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "study"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "rogue.py").write_text(
                "def publish(store, manifest, method, env):\n    return store.publish(manifest, method, env)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "study.checkpoint_publish")

    def test_prepared_capability_effect_calls_cannot_bypass_effect_executor(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "study"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "rogue_workflow.py").write_text(
                "def run(session, request, handle, ctx):\n"
                "    session.prepare_capability_effect(request)\n"
                "    session.execute_prepared_capability(request, handle)\n"
                "    return session.reconcile_prepared_capability(handle, ctx)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            authorities = {row.authority for row in findings}
            self.assertEqual(
                authorities,
                {"capability.effect_prepare", "capability.effect_execute", "capability.effect_reconcile"},
            )



    def test_sqlite_connection_outside_platform_durability_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_storage"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "import sqlite3\n\ndef connect(path):\n    return sqlite3.connect(path)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "storage.sqlite_connection")

    def test_thread_pool_outside_concurrency_provider_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_runtime"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "from concurrent.futures import ThreadPoolExecutor\n\n"
                "def build():\n    return ThreadPoolExecutor(max_workers=2)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "concurrency.thread_pool")

    def test_raw_thread_outside_concurrency_provider_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_runtime"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "from threading import Thread\n\n"
                "def build(fn):\n    return Thread(target=fn)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "concurrency.thread")


    def test_raw_fd_open_outside_durability_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_storage"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "import os\n\ndef open_raw(path):\n"
                "    return os.open(path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o644)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "filesystem.raw_fd_open")

    def test_raw_fd_write_outside_durability_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_storage"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "import os\n\ndef write_raw(fd, payload):\n"
                "    return os.write(fd, payload)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "filesystem.raw_fd_write")

    def test_write_mode_path_open_outside_durability_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_storage"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "from pathlib import Path\n\n"
                "def append(path):\n"
                "    return Path(path).open('ab')\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "filesystem.write_mode_open")


if __name__ == "__main__":
    unittest.main()
