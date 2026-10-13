from __future__ import annotations

import sqlite3
import tempfile
import unittest
from pathlib import Path

from noetrium_platform.infrastructure.resources.authority.runtime.authority import _SCHEMA


class ResourceAuthorityClaimKindIndexTests(unittest.TestCase):
    def test_multi_kind_projection_uses_live_kind_resource_index(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "authority.sqlite"
            db = sqlite3.connect(path)
            try:
                db.executescript(_SCHEMA)
                plan = " ".join(
                    str(row[3])
                    for row in db.execute(
                        """
                        EXPLAIN QUERY PLAN
                        SELECT resource_key,
                               json_extract(
                                   attributes_json,
                                   '$.attributes.consumer_resource_key'
                               )
                        FROM resource_authority_claims
                        INDEXED BY idx_resource_authority_claims_live_kind_resource
                        WHERE released=0
                          AND json_extract(
                              attributes_json,
                              '$.attributes.kind'
                          ) IN (?, ?)
                        """,
                        ("compute", "minecraft-server"),
                    ).fetchall()
                )
            finally:
                db.close()

        self.assertIn(
            "idx_resource_authority_claims_live_kind_resource",
            plan,
        )


if __name__ == "__main__":
    unittest.main()
