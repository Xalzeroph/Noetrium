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
            self.assertEqual(findings[0].authority, "lifecycle.process_spawn")
            self.assertEqual(findings[0].line, 4)

    def test_indirect_process_spawn_reference_is_rejected(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "runtime_manager"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "import subprocess\n\ndef build():\n    factory = subprocess.Popen\n    return factory\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "lifecycle.process_spawn")

    def test_protected_primitive_alias_capture_is_rejected_across_authorities(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "runtime_manager"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "sqlite_ref.py").write_text(
                "import sqlite3\n\ndef build():\n    factory = sqlite3.connect\n    return factory\n",
                encoding="utf-8",
            )
            (target / "thread_ref.py").write_text(
                "from concurrent.futures import ThreadPoolExecutor\n\ndef build():\n"
                "    factory = ThreadPoolExecutor\n    return factory\n",
                encoding="utf-8",
            )
            (target / "spawn_alias.py").write_text(
                "from subprocess import Popen as Spawn\n\ndef build():\n"
                "    factory = Spawn\n    return factory\n",
                encoding="utf-8",
            )

            findings = audit_source_authorities(root)
            by_authority = {row.authority: row for row in findings}

            self.assertEqual(
                set(by_authority),
                {
                    "storage.sqlite_connection",
                    "concurrency.thread_pool",
                    "lifecycle.process_spawn",
                },
            )
            self.assertEqual(by_authority["storage.sqlite_connection"].line, 4)
            self.assertEqual(by_authority["concurrency.thread_pool"].line, 4)
            self.assertEqual(by_authority["lifecycle.process_spawn"].line, 4)

    def test_type_annotation_reference_does_not_claim_spawn_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "runtime_manager"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "from __future__ import annotations\n"
                "import subprocess\n\n"
                "def keep(child: subprocess.Popen[bytes]) -> subprocess.Popen[bytes]:\n"
                "    return child\n",
                encoding="utf-8",
            )
            self.assertEqual(audit_source_authorities(root), ())

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



    def test_reference_component_cannot_bypass_platform_durability(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "components" / "reference"
            target.mkdir(parents=True)
            (target / "rogue.py").write_text(
                "import sqlite3\\n\\ndef connect(path):\\n    return sqlite3.connect(path)\\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "storage.sqlite_connection")
            self.assertEqual(findings[0].module, "components.reference.rogue")

    def test_platform_research_runtime_cannot_bypass_concurrency_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "research" / "runtime"
            target.mkdir(parents=True)
            (target / "rogue.py").write_text(
                "from concurrent.futures import ThreadPoolExecutor\n\n"
                "def build():\n    return ThreadPoolExecutor(max_workers=2)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "concurrency.thread_pool")
            self.assertEqual(findings[0].module, "research.runtime.rogue")

    def test_public_noetrium_package_cannot_bypass_kernel_authority(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium"
            target.mkdir(parents=True)
            (target / "__init__.py").write_text("", encoding="utf-8")
            (target / "rogue.py").write_text(
                "import sqlite3\n\ndef connect(path):\n    return sqlite3.connect(path)\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "storage.sqlite_connection")
            self.assertEqual(findings[0].module, "noetrium.rogue")

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

    def test_raw_fork_is_rejected_everywhere_in_platform_source(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_runtime"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "import os\n\ndef split():\n    return os.fork()\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].authority, "process.raw_fork")

    def test_multiprocessing_context_is_owned_by_executor_provider(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            target = root / "noetrium_platform" / "rogue_runtime"
            target.mkdir(parents=True)
            (root / "noetrium_platform" / "__init__.py").write_text("", encoding="utf-8")
            (target / "x.py").write_text(
                "import multiprocessing as mp\n\ndef context():\n"
                "    return mp.get_context('fork')\n",
                encoding="utf-8",
            )
            findings = audit_source_authorities(root)
            self.assertEqual(len(findings), 1)
            self.assertEqual(
                findings[0].authority,
                "concurrency.multiprocessing_context",
            )

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
