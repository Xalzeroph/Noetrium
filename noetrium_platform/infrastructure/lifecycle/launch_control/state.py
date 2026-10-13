from __future__ import annotations

import time

from .runtime_history_ports import RuntimeHistoryPort
from .runtime_state_contracts import RuntimeControlState, RuntimeTxnPhase
from .runtime_state_ports import RuntimeControlStateStorePort


class RuntimeControlStore:
    """Coordinator joining one causal state journal with a disposable history projection.

    RuntimeControlStateStorePort commits Event truth first. RuntimeHistoryPort is only
    a diagnostic projection that may lag and can be reconciled from current Event state.
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
        # A corrupt diagnostic projection fails closed before new publication. The
        # Event-backed state write is the only truth mutation; history append is derived.
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
        return self.history.reconcile_projection(self.read())

    def assert_history_tail_matches(self, state: RuntimeControlState) -> None:
        self.history.assert_tail_matches(state)


__all__ = ["RuntimeControlState", "RuntimeControlStore", "RuntimeTxnPhase"]
