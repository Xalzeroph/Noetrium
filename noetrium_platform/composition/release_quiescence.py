from __future__ import annotations

from noetrium_platform.foundation.governance.release.api import ActiveReleasePin, ReleaseConsumerQuiescence
from noetrium_platform.infrastructure.reliability.recovery.api.ports import RecoveryLeaseReadPort
from noetrium_platform.infrastructure.lifecycle.session.api import (
    PersistentSessionObservationState,
    PersistentSessionStatusProbePort,
)
from noetrium_platform.infrastructure.lifecycle.service.runtime.quiescence import ExactServiceQuiescenceProbe


class PersistentSessionReleaseConsumerProbe:
    consumer_id = "persistent-controller"

    def __init__(self, source: PersistentSessionStatusProbePort) -> None:
        self.source = source

    def observe(self, pin: ActiveReleasePin) -> ReleaseConsumerQuiescence:
        del pin
        session = self.source.observe()
        quiescent = session.state is PersistentSessionObservationState.MISSING
        return ReleaseConsumerQuiescence(
            self.consumer_id,
            quiescent,
            "controller session is proven absent"
            if quiescent
            else f"controller session is not proven absent: {session.state.value}",
            tuple(session.evidence_refs)
            + (f"server-session:{session.state.value}:{session.session_name}",),
        )


class RecoveryLeaseReleaseConsumerProbe:
    consumer_id = "runtime-recovery-lease"

    def __init__(self, source: RecoveryLeaseReadPort) -> None:
        self.source = source

    def observe(self, pin: ActiveReleasePin) -> ReleaseConsumerQuiescence:
        lease = self.source.read()
        relevant = lease is not None and lease.manifest_digest == pin.runtime_manifest_digest
        refs = () if lease is None else (f"recovery-lease:{lease.owner_id}:{lease.expires_at}",)
        return ReleaseConsumerQuiescence(
            self.consumer_id,
            not relevant,
            "no recovery lease references this runtime manifest"
            if not relevant
            else "runtime recovery lease still references this manifest",
            refs,
        )


class ServiceReleaseConsumerProbe:
    def __init__(self, source: ExactServiceQuiescenceProbe) -> None:
        self.source = source
        self.consumer_id = f"service:{source.contract.service_id}"

    def observe(self, pin: ActiveReleasePin) -> ReleaseConsumerQuiescence:
        del pin
        observation = self.source.observe()
        return ReleaseConsumerQuiescence(
            self.consumer_id,
            observation.quiescent,
            observation.summary,
            observation.evidence_refs,
        )


__all__ = [
    "PersistentSessionReleaseConsumerProbe",
    "RecoveryLeaseReleaseConsumerProbe",
    "ServiceReleaseConsumerProbe",
]
