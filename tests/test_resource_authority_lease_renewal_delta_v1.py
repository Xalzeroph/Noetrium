from __future__ import annotations

from pathlib import Path
import sqlite3

from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE
from noetrium_platform.foundation.kernel.kernel import ManualLeaseClock
from noetrium_platform.infrastructure.resources.authority import (
    UniversalResourceAuthority,
    lease_field,
)


def test_lease_renewal_delta_rebuilds_exact_projection_and_is_compact(
    tmp_path: Path,
) -> None:
    clock = ManualLeaseClock()
    path = tmp_path / "authority.sqlite"
    authority = UniversalResourceAuthority(path, clock=clock)
    try:
        lease = authority.acquire_ttl_lease(
            lease_id="lease",
            resource_key="resource",
            holder_key="holder",
            owner_scope=PLATFORM_SCOPE,
            ttl_seconds=120.0,
            metadata={"kind": "delta-test", "payload": "x" * 256},
        )
        with sqlite3.connect(path) as conn:
            acquire_rowid, acquire_size = conn.execute(
                "SELECT rowid,length(payload) FROM resource_authority_events "
                "ORDER BY rowid DESC LIMIT 1"
            ).fetchone()
            acquire_rowid = int(acquire_rowid)
            acquire_size = int(acquire_size)

        for _ in range(3):
            clock.advance(10.0)
            (lease,) = authority.renew_leases(
                (lease,),
                ttl_seconds=120.0,
            )

        rebuilt = authority.verify_projection_rebuild()
        durable = authority.snapshot_for_resource_keys(
            frozenset({"resource"})
        )
        assert rebuilt.leases == authority.snapshot().leases
        assert durable.leases == (lease,)
        assert lease_field(lease, "expires_at_epoch_s") is not None

        with sqlite3.connect(path) as conn:
            renewal_sizes = tuple(
                int(row[0])
                for row in conn.execute(
                    "SELECT length(payload) FROM resource_authority_events "
                    "WHERE rowid>? ORDER BY rowid",
                    (acquire_rowid,),
                ).fetchall()
            )
        assert len(renewal_sizes) == 3
        assert max(renewal_sizes) < acquire_size * 0.70
    finally:
        authority.close()
