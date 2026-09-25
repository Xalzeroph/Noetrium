from __future__ import annotations

import time

from .runtime_history_ports import RuntimeHistoryPort
from .runtime_state_contracts import RuntimeControlState, RuntimeTxnPhase
from .runtime_state_ports import RuntimeControlStateStorePort


class RuntimeControlStore:
    """Transaction coordinator joining authoritative state with an explicit history projection.

    The two durable stores are injected independently.  This class owns write ordering only:
    verify existing history -> publish authoritative state -> append history projection.
    """

    def __init__(self, state_store: RuntimeControlStateStorePort, history: RuntimeHistoryPort) -> None:
        self.state_store = state_store
        self.history = history

    def exists(self) -> bool:
        return self.state_store.exists()

    def create(self, control_id: str, manifest_digest: str) -> RuntimeControlState:
        if self.exists():
            raise RuntimeError("runtime control state already exists")
        state = RuntimeControlState(
            control_id,
            manifest_digest,
            RuntimeTxnPhase.PLANNED,
            (),
            None,
            False,
            (),
            None,
            None,
            None,
            time.time(),
        )
        self.write(state)
        return state

    def write(self, state: RuntimeControlState) -> None:
        # Fail before mutating authoritative state when the existing projection chain
        # is already corrupt.  The post-state/pre-history crash window remains explicitly
        # recoverable through reconcile_history().
        with self.history.verified_append_session() as history_tx:
            self.state_store.write(state)
            history_tx.append(state)

    def read(self) -> RuntimeControlState:
        return self.state_store.read()

    def verify_history(self) -> tuple[str, ...]:
        return self.history.verify()

    def reconcile_history(self) -> bool:
        if not self.exists():
            errors = self.history.verify()
            if errors:
                raise RuntimeError("runtime history integrity failure: " + "; ".join(errors))
            return False
        return self.history.reconcile_authoritative(self.read())

    def assert_history_tail_matches(self, state: RuntimeControlState) -> None:
        self.history.assert_tail_matches(state)


__all__ = ["RuntimeControlState", "RuntimeControlStore", "RuntimeTxnPhase"]
