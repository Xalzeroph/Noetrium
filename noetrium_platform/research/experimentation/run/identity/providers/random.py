from __future__ import annotations

import uuid

from ..api.contracts import RunIdentity


class RandomRunIdentityProvider:
    def allocate(self) -> RunIdentity:
        run_id = f"run_{uuid.uuid4().hex[:12]}"
        return RunIdentity(
            run_id,
            f"session_{uuid.uuid4().hex[:12]}",
            run_id,
        )


__all__ = ["RandomRunIdentityProvider"]
