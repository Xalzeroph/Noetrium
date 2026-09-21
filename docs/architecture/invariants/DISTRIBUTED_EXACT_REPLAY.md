# Distributed exact replay

Exact replay is independent of the original worker topology. Replay reconstructs execution from canonical journal facts, frozen bindings, receipts, and immutable artifacts; it must not require the same worker, endpoint, replica placement, or live provider.

If a required receipt or artifact is absent, exact replay fails closed. It must never silently issue a live effect and still claim exact replay.
