from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import (
    ImmutableModelIdentity,
    canonical_digest,
)

from .replica import OperationalModelEndpointReplicaSet


@dataclass(frozen=True, slots=True)
class OperationalModelServingInventory:
    """Frozen non-claim serving inventory for one immutable model identity.

    Discovery is deliberately outside this value object. A local management plane,
    cluster scheduler, service registry, or downstream deployment file may all
    materialize the same contract. No host, port, GPU, replica count, or capacity
    is assumed by the platform.
    """

    model: ImmutableModelIdentity
    served_model_name: str
    replica_set: OperationalModelEndpointReplicaSet

    def __post_init__(self) -> None:
        if not isinstance(self.model, ImmutableModelIdentity):
            raise TypeError("operational model serving inventory requires ImmutableModelIdentity")
        if type(self.served_model_name) is not str or not self.served_model_name.strip():
            raise ValueError("operational model serving inventory served_model_name is required")
        if not isinstance(self.replica_set, OperationalModelEndpointReplicaSet):
            raise TypeError("operational model serving inventory requires replica set")

    @property
    def capacity(self) -> int:
        return sum(replica.capacity for replica in self.replica_set.replicas)

    @property
    def identity_digest(self) -> str:
        return canonical_digest({
            "schema": "operational-model-serving-inventory.v1",
            "model": self.model,
            "served_model_name": self.served_model_name,
            "replica_set_digest": self.replica_set.replica_set_digest,
        })


__all__ = ["OperationalModelServingInventory"]
