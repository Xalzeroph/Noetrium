from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.capabilities.participant.capability.api import (
    CapabilityDescriptor,
    CapabilityRequest,
    CapabilityResult,
    CapabilitySelectionReference,
    materialize_capability_selection_view,
)


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _descriptor(capability_id: str, version: str = "1") -> CapabilityDescriptor:
    return CapabilityDescriptor(
        capability_id=capability_id,
        interface_version=version,
        request_schema=f"schema://{capability_id}/{version}/request",
        result_schema=f"schema://{capability_id}/{version}/result",
    )


class _Catalog:
    def __init__(self, descriptors: tuple[CapabilityDescriptor, ...]) -> None:
        self._descriptors = {row.capability_id: row for row in descriptors}

    def describe(self, capability_id: str) -> CapabilityDescriptor:
        return self._descriptors[capability_id]

    def invoke(self, request: CapabilityRequest) -> CapabilityResult:
        raise AssertionError("selection view materialization must not invoke capabilities")


def test_selection_view_freezes_authoritative_descriptors_without_owning_selector_policy() -> None:
    weather = _descriptor("weather.current")
    calendar = _descriptor("calendar.create")
    view = materialize_capability_selection_view(
        (
            CapabilitySelectionReference(weather.capability_id, weather.digest()),
            CapabilitySelectionReference(calendar.capability_id, calendar.digest()),
        ),
        source_cut_digest=_digest("catalog-cut"),
        selection_provenance_digest=_digest("selector-output"),
        capability_port=_Catalog((weather, calendar)),
    )

    assert view.descriptors == (weather, calendar)
    assert view.source_cut_digest == _digest("catalog-cut")
    assert view.selection_provenance_digest == _digest("selector-output")
    assert len(view.view_digest) == 64
    assert not hasattr(view, "retrieval_metric")
    assert not hasattr(view, "query_vector")


def test_selection_view_materialization_fails_closed_when_authoritative_descriptor_drifted() -> None:
    selected = _descriptor("weather.current", "1")
    drifted = _descriptor("weather.current", "2")

    with pytest.raises(ValueError, match="descriptor drifted"):
        materialize_capability_selection_view(
            (CapabilitySelectionReference(selected.capability_id, selected.digest()),),
            source_cut_digest=_digest("catalog-cut"),
            selection_provenance_digest=_digest("selector-output"),
            capability_port=_Catalog((drifted,)),
        )


def test_selection_view_rejects_duplicate_selected_capabilities() -> None:
    weather = _descriptor("weather.current")
    reference = CapabilitySelectionReference(weather.capability_id, weather.digest())

    with pytest.raises(ValueError, match="must be unique"):
        materialize_capability_selection_view(
            (reference, reference),
            source_cut_digest=_digest("catalog-cut"),
            selection_provenance_digest=_digest("selector-output"),
            capability_port=_Catalog((weather,)),
        )
