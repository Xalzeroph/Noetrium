from __future__ import annotations

from dataclasses import dataclass, field

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256

from .contracts import CapabilityDescriptor, CapabilityPort


@dataclass(frozen=True, slots=True)
class CapabilitySelectionReference:
    """One selected capability bound to the descriptor digest seen by selection."""

    capability_id: str
    descriptor_digest: str

    def __post_init__(self) -> None:
        if not isinstance(self.capability_id, str) or not self.capability_id.strip() or self.capability_id != self.capability_id.strip():
            raise ValueError("capability selection reference id must be canonical non-empty text")
        require_sha256(self.descriptor_digest, "capability selection descriptor_digest")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class CapabilitySelectionView:
    """Immutable exact capability surface exposed after a method-owned selection step.

    The view owns no retrieval/ranking policy and no capability definitions. It binds
    an opaque source cut plus selection provenance to authoritative descriptors
    re-materialized from CapabilityPort.
    """

    source_cut_digest: str
    selection_provenance_digest: str
    descriptors: tuple[CapabilityDescriptor, ...]
    view_digest: str = field(init=False)

    def __post_init__(self) -> None:
        require_sha256(self.source_cut_digest, "capability selection source_cut_digest")
        require_sha256(
            self.selection_provenance_digest,
            "capability selection selection_provenance_digest",
        )
        if not isinstance(self.descriptors, tuple) or any(
            not isinstance(descriptor, CapabilityDescriptor) for descriptor in self.descriptors
        ):
            raise TypeError("capability selection view requires CapabilityDescriptor values")
        capability_ids = tuple(descriptor.capability_id for descriptor in self.descriptors)
        if len(set(capability_ids)) != len(capability_ids):
            raise ValueError("capability selection view cannot contain duplicate capabilities")
        object.__setattr__(
            self,
            "view_digest",
            canonical_digest(
                {
                    "source_cut_digest": self.source_cut_digest,
                    "selection_provenance_digest": self.selection_provenance_digest,
                    "descriptor_digests": [descriptor.digest() for descriptor in self.descriptors],
                }
            ),
        )


def materialize_capability_selection_view(
    references: tuple[CapabilitySelectionReference, ...],
    *,
    source_cut_digest: str,
    selection_provenance_digest: str,
    capability_port: CapabilityPort,
) -> CapabilitySelectionView:
    """Resolve selected refs against the capability authority and fail closed on drift."""

    if not isinstance(references, tuple) or any(
        not isinstance(reference, CapabilitySelectionReference) for reference in references
    ):
        raise TypeError("capability selection references must be a tuple of typed references")
    capability_ids = tuple(reference.capability_id for reference in references)
    if len(set(capability_ids)) != len(capability_ids):
        raise ValueError("capability selection references must be unique")

    descriptors: list[CapabilityDescriptor] = []
    for reference in references:
        descriptor = capability_port.describe(reference.capability_id)
        if not isinstance(descriptor, CapabilityDescriptor):
            raise TypeError("CapabilityPort.describe must return CapabilityDescriptor")
        if descriptor.capability_id != reference.capability_id:
            raise ValueError("selected capability reference resolved to another capability")
        if descriptor.digest() != reference.descriptor_digest:
            raise ValueError("selected capability descriptor drifted from the pinned selection source")
        descriptors.append(descriptor)

    return CapabilitySelectionView(
        source_cut_digest=source_cut_digest,
        selection_provenance_digest=selection_provenance_digest,
        descriptors=tuple(descriptors),
    )


__all__ = [
    "CapabilitySelectionReference",
    "CapabilitySelectionView",
    "materialize_capability_selection_view",
]
