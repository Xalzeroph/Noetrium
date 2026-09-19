from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory
import time
import unittest
from unittest.mock import patch

from noetrium_platform.foundation.kernel.kernel.durability.durable_file import atomic_replace_bytes
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_contracts import ServiceStartIntent, ServiceStartIntentPhase
from noetrium_platform.infrastructure.lifecycle.service.runtime.start_intent_store import DirectoryServiceStartIntentStore


def intent(*, phase: ServiceStartIntentPhase = ServiceStartIntentPhase.PREPARED) -> ServiceStartIntent:
    now = time.time()
    return ServiceStartIntent(
        "intent-1",
        "svc",
        "d" * 64,
        1,
        phase,
        None,
        None,
        now,
        now,
    )


class ServiceStartIntentIndexPerformanceV172Tests(unittest.TestCase):
    def test_active_lookup_never_scans_completed_history(self) -> None:
        with TemporaryDirectory() as td:
            store = DirectoryServiceStartIntentStore(Path(td))
            active = store.create_once(intent())
            with patch.object(store, "all", side_effect=AssertionError("slow scan used")):
                self.assertEqual(store.unresolved(active.service_id, active.contract_digest), (active,))

    def test_missing_active_pointer_is_rebuilt_from_authoritative_intent(self) -> None:
        with TemporaryDirectory() as td:
            store = DirectoryServiceStartIntentStore(Path(td))
            row = intent()
            # Simulate crash after authoritative document publication and before pointer publish.
            atomic_replace_bytes(store._path(row.intent_id), store.codec.encode(row))
            self.assertEqual(store.unresolved(row.service_id, row.contract_digest), (row,))
            with patch.object(store, "all", side_effect=AssertionError("rebuild did not persist")):
                self.assertEqual(store.unresolved(row.service_id, row.contract_digest), (row,))

    def test_stale_pointer_after_complete_publication_self_heals(self) -> None:
        with TemporaryDirectory() as td:
            store = DirectoryServiceStartIntentStore(Path(td))
            row = store.create_once(intent())
            complete = replace(row, phase=ServiceStartIntentPhase.COMPLETE, updated_at=time.time())
            # Simulate crash after COMPLETE document publication and before pointer clear.
            atomic_replace_bytes(store._path(row.intent_id), store.codec.encode(complete))
            self.assertEqual(store.unresolved(row.service_id, row.contract_digest), ())
            with patch.object(store, "all", side_effect=AssertionError("unexpected slow scan")):
                self.assertEqual(store.unresolved(row.service_id, row.contract_digest), ())


if __name__ == "__main__":
    unittest.main()
