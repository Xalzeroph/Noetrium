from __future__ import annotations

from noetrium_platform.foundation.governance.release.api import (
    ActiveReleasePin,
    ReleaseConsumerQuiescenceProbe,
    ReleaseQuiescenceProof,
)


class ReleaseQuiescenceVerifier:
    """Join explicit consumer observations into one release proof."""

    def __init__(self, probes: tuple[ReleaseConsumerQuiescenceProbe, ...]) -> None:
        ids = [getattr(probe, "consumer_id", None) for probe in probes]
        non_empty = [item for item in ids if item is not None]
        if len(non_empty) != len(set(non_empty)):
            raise ValueError("duplicate release-consumer quiescence probe identity")
        self.probes = probes

    def prove(self, pin: ActiveReleasePin) -> ReleaseQuiescenceProof:
        blockers: list[str] = []
        refs: list[str] = []
        for probe in self.probes:
            observation = probe.observe(pin)
            refs.extend(observation.evidence_refs)
            refs.append(
                f"release-consumer:{observation.consumer_id}:{str(observation.quiescent).lower()}"
            )
            if not observation.quiescent:
                blockers.append(f"consumer {observation.consumer_id}: {observation.summary}")
        return ReleaseQuiescenceProof.create(
            pin,
            blockers=tuple(blockers),
            evidence_refs=tuple(refs),
        )


__all__ = ["ReleaseQuiescenceVerifier"]
