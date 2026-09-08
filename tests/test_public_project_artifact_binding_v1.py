from __future__ import annotations

import json
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from noetrium.contracts.systems.experimentation__run import (
    RunArtifactKind,
    RunArtifactSnapshotReceipt,
)
from noetrium.platform import (
    DirectoryRunArtifactStoreBinding,
    bind_directory_run_artifact_store,
)


class PublicProjectArtifactBindingTests(TestCase):
    def test_binding_is_direct_artifact_port_and_preserves_compatibility_view(self) -> None:
        with TemporaryDirectory() as root:
            with bind_directory_run_artifact_store(
                root,
                run_id="sem-run-1",
                task_group_id="project:run-artifacts:test",
            ) as binding:
                self.assertIsInstance(binding, DirectoryRunArtifactStoreBinding)
                self.assertIs(binding.store, binding.store)
                published = binding.publish_json(
                    "results/task.json",
                    {"task_id": "task-1", "success": True},
                    kind=RunArtifactKind.RESULT,
                )
                self.assertEqual(
                    json.loads(Path(published).read_text(encoding="utf-8")),
                    {"task_id": "task-1", "success": True},
                )
                receipt = binding.finalize(
                    "results/task.json",
                    kind=RunArtifactKind.RESULT,
                    record_stream=False,
                )
                self.assertIsInstance(receipt, RunArtifactSnapshotReceipt)
                self.assertEqual(receipt.run_id, "sem-run-1")
                self.assertEqual(receipt.artifact_ref, "results/task.json")
                self.assertEqual(binding.verify_finalized(receipt), receipt)

            with self.assertRaisesRegex(RuntimeError, "closed"):
                _ = binding.store
            with self.assertRaisesRegex(RuntimeError, "closed"):
                binding.publish_text(
                    "results/after-close.txt",
                    "forbidden",
                    kind=RunArtifactKind.RESULT,
                )

    def test_binding_preserves_record_stream_count(self) -> None:
        with TemporaryDirectory() as root, bind_directory_run_artifact_store(
            root,
            run_id="sem-run-2",
        ) as binding:
            binding.append_json(
                "audit/events.jsonl",
                {"sequence": 1},
                kind=RunArtifactKind.EVIDENCE,
            )
            binding.append_json(
                "audit/events.jsonl",
                {"sequence": 2},
                kind=RunArtifactKind.EVIDENCE,
            )
            receipt = binding.finalize(
                "audit/events.jsonl",
                kind=RunArtifactKind.EVIDENCE,
                record_stream=True,
            )
            self.assertEqual(receipt.record_count, 2)
            self.assertEqual(binding.verify_finalized(receipt), receipt)

    def test_empty_task_group_id_is_rejected_before_composition(self) -> None:
        with TemporaryDirectory() as root:
            with self.assertRaisesRegex(ValueError, "task_group_id"):
                bind_directory_run_artifact_store(
                    root,
                    run_id="sem-run-3",
                    task_group_id=" ",
                )
