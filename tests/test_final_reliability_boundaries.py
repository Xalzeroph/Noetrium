from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from noetrium_platform.evidence.observability.logging.context.api import DiagnosticAddress
from noetrium_platform.evidence.observability.logging.record.api import LogLevel, LogRecord
from tests._concurrency_support import jsonl_log_store as JsonlLogStore
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE


class FinalReliabilityBoundaryTests(unittest.TestCase):
    def test_jsonl_log_store_round_trip_survives_new_reader(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "events.jsonl"
            record = LogRecord(
                "log-1",
                1.0,
                LogLevel.ERROR,
                "test",
                "failure",
                "safe message",
                DiagnosticAddress((PLATFORM_SCOPE,)),
            )
            JsonlLogStore(path).append(record)
            self.assertEqual(JsonlLogStore(path).query(limit=1), (record,))



if __name__ == "__main__":
    unittest.main()
