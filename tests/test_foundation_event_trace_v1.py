import pytest

from noetrium_platform.foundation.kernel.event import (
    causal_event,
    causal_topological_order,
    event_field,
    event_ref,
    events_independent,
    reverse_causal_cone_from_traces,
    merge_causal_traces,
    reverse_causal_cone,
)
from noetrium_platform.foundation.kernel.truth import TruthModality
from noetrium_platform.foundation.kernel.unit import NoetriumUnit
from noetrium_platform.foundation.kernel.unit_codec import decode_unit, encode_unit


def _subject(name: str) -> NoetriumUnit:
    return NoetriumUnit(name, schemas=("test.subject",))


def test_unified_carrier_keeps_truth_modalities_distinct():
    subject = _subject("gpu")
    declared = causal_event(
        authority_domain="resource.gpu",
        generation=0,
        subject=subject,
        operation="claim",
        phase="requested",
        modality=TruthModality.DECLARED,
        writes=("gpu:0",),
    )
    authorized = causal_event(
        authority_domain="resource.gpu",
        generation=1,
        subject=subject,
        operation="claim",
        phase="granted",
        modality=TruthModality.AUTHORIZED,
        writes=("gpu:0",),
    )
    observed = causal_event(
        authority_domain="provider.nvidia",
        generation=1,
        subject=subject,
        operation="observe",
        phase="sampled",
        modality=TruthModality.OBSERVED,
        reads=("gpu:0",),
    )
    evidenced = causal_event(
        authority_domain="science.metric",
        generation=0,
        subject=subject,
        operation="measure",
        phase="recorded",
        modality=TruthModality.EVIDENCED,
        reads=("gpu:0",),
    )
    assert all(type(row) is NoetriumUnit for row in (declared, authorized, observed, evidenced))
    assert len({row.unit_digest for row in (declared, authorized, observed, evidenced)}) == 4
    assert event_field(authorized, "modality") is TruthModality.AUTHORIZED
    assert decode_unit(encode_unit(authorized)) == authorized


def test_authorized_event_requires_positive_generation():
    with pytest.raises(ValueError):
        causal_event(
            authority_domain="resource.gpu",
            generation=0,
            subject=_subject("gpu"),
            operation="claim",
            phase="granted",
            modality=TruthModality.AUTHORIZED,
        )


def test_trace_has_no_global_order_for_independent_events():
    left = causal_event(
        authority_domain="resource.gpu0",
        generation=1,
        subject=_subject("left"),
        operation="grant",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        writes=("gpu:0",),
    )
    right = causal_event(
        authority_domain="resource.gpu1",
        generation=1,
        subject=_subject("right"),
        operation="grant",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        writes=("gpu:1",),
    )
    conflict = causal_event(
        authority_domain="resource.other",
        generation=1,
        subject=_subject("conflict"),
        operation="grant",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        writes=("gpu:0",),
    )
    assert events_independent(left, right)
    assert not events_independent(left, conflict)


def test_causal_order_and_reverse_cone_are_derived_from_event_refs():
    root = causal_event(
        authority_domain="research.run",
        generation=1,
        subject=_subject("root"),
        operation="start",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        writes=("run:1",),
    )
    child = causal_event(
        authority_domain="resource.gpu",
        generation=1,
        subject=_subject("gpu"),
        operation="acquire",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        causal_parents=(event_ref(root),),
        reads=("run:1",),
        writes=("gpu:0",),
    )
    failure = causal_event(
        authority_domain="reliability.failure",
        generation=0,
        subject=_subject("failure"),
        operation="fail",
        phase="recorded",
        modality=TruthModality.EVIDENCED,
        causal_parents=(event_ref(child),),
        reads=("gpu:0",),
    )
    unrelated = causal_event(
        authority_domain="resource.cpu",
        generation=1,
        subject=_subject("cpu"),
        operation="acquire",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        writes=("cpu:0",),
    )
    trace = (failure, unrelated, child, root)
    ordered = causal_topological_order(trace)
    assert ordered.index(root) < ordered.index(child) < ordered.index(failure)
    assert {row.unit_digest for row in reverse_causal_cone(trace, failure)} == {
        root.unit_digest,
        child.unit_digest,
        failure.unit_digest,
    }


def test_cross_authority_trace_union_preserves_only_causal_order():
    resource = causal_event(
        authority_domain="resource.gpu0",
        generation=1,
        subject=_subject("resource"),
        operation="grant",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        writes=("gpu:0",),
    )
    effect = causal_event(
        authority_domain="effect.agent",
        generation=1,
        subject=_subject("effect"),
        operation="effect-transition",
        phase="result_recorded",
        modality=TruthModality.AUTHORIZED,
        causal_parents=(event_ref(resource),),
        reads=("gpu:0",),
        writes=("effect:e1",),
    )
    failure = causal_event(
        authority_domain="failure.run",
        generation=0,
        subject=_subject("failure-cross"),
        operation="record-failure",
        phase="invoke",
        modality=TruthModality.EVIDENCED,
        causal_parents=(event_ref(effect),),
        reads=("effect:e1",),
    )
    independent = causal_event(
        authority_domain="resource.cpu0",
        generation=1,
        subject=_subject("cpu"),
        operation="grant",
        phase="committed",
        modality=TruthModality.AUTHORIZED,
        writes=("cpu:0",),
    )
    merged = merge_causal_traces(
        (resource, independent),
        (effect,),
        (failure, resource),
    )
    assert len(merged) == 4
    cone = reverse_causal_cone_from_traces(
        ((resource, independent), (effect,), (failure,)),
        failure,
    )
    assert {event.unit_digest for event in cone} == {
        resource.unit_digest,
        effect.unit_digest,
        failure.unit_digest,
    }
