from __future__ import annotations

from dataclasses import replace

import pytest

from noetrium_platform.capabilities.environment.api import (
    ActionIdentityViolation,
    ActionRequest,
    EnvironmentCapability,
    EnvironmentCapabilityUnsupported,
    EnvironmentIdentity,
    EnvironmentConformanceProbe,
    ExecutionContext,
    EffectClass,
    EffectCertainty,
    EffectReceipt,
    EnvironmentProviderCapabilities,
    EnvironmentProviderConformanceReceipt,
    EnvironmentProviderPort,
    verify_environment_provider_conformance,
)
from noetrium_platform.capabilities.environment.composition import reference_counter_environment


def _context() -> ExecutionContext:
    return ExecutionContext("run-npe", "trace-npe", "span-npe", task_id="task-npe")


def test_reference_counter_satisfies_public_provider_conformance() -> None:
    provider = reference_counter_environment()
    context = _context()
    action = ActionRequest("action-1", "increment", {"amount": 2}, context)

    assert isinstance(provider, EnvironmentProviderPort)
    receipt = verify_environment_provider_conformance(
        provider,
        probe=EnvironmentConformanceProbe("session-npe", context, action),
        services=object(),
    )
    assert receipt.environment == provider.identity
    assert receipt.snapshot_sha256 is not None
    assert receipt.action_id == "action-1"
    assert receipt.diagnostics_generation == receipt.observation_generation
    assert receipt.checks == (
        "provider_identity",
        "open_session",
        "observe",
        "snapshot",
        "restore",
        "act",
        "reconcile",
        "diagnostics",
    )
    assert len(receipt.digest()) == 64


def test_reference_counter_snapshot_restore_and_typed_diagnostics() -> None:
    provider = reference_counter_environment()
    session = provider.open_session(session_id="session-npe", services=object())
    context = _context()

    before = session.diagnostics_snapshot()
    snapshot = session.checkpoint()
    session.act(ActionRequest("action-1", "increment", {"amount": 5}, context))
    assert session.observe(context).payload["state"]["value"] == 5
    session.restore(snapshot)
    assert session.observe(context).payload["state"]["value"] == 0
    assert before.environment == provider.identity
    assert before.ready is True and before.closed is False

    session.close()
    closed = session.diagnostics_snapshot()
    assert closed.ready is False and closed.closed is True
    assert closed.state_digest == before.state_digest


def test_capability_support_is_explicit_and_unsupported_is_typed() -> None:
    minimal = EnvironmentProviderCapabilities(
        (EnvironmentCapability.DIAGNOSTICS,)
    )
    assert minimal.supports(EnvironmentCapability.DIAGNOSTICS)
    assert not minimal.supports(EnvironmentCapability.SNAPSHOT)
    with pytest.raises(EnvironmentCapabilityUnsupported) as raised:
        minimal.require(EnvironmentCapability.SNAPSHOT)
    assert raised.value.capability == "snapshot"

    with pytest.raises(ValueError, match="restore capability requires snapshot"):
        EnvironmentProviderCapabilities((EnvironmentCapability.RESTORE,))


def test_conformance_rejects_provider_without_content_identity_before_open() -> None:
    class _IncompleteProvider:
        identity = EnvironmentIdentity("incomplete", "1", "1", "1", "")
        capabilities = EnvironmentProviderCapabilities()

        def open_session(self, *, session_id, services):
            raise AssertionError("identity must be rejected before provider open")

    with pytest.raises(ValueError, match="artifact_digest"):
        verify_environment_provider_conformance(
            _IncompleteProvider(),
            probe=EnvironmentConformanceProbe("session-npe", _context()),
            services=object(),
        )


def test_reconciliation_cannot_be_bypassed_with_forged_provider_receipt() -> None:
    provider = reference_counter_environment()
    session = provider.open_session(session_id="session-npe", services=object())
    context = _context()
    result = session.act(ActionRequest("action-1", "increment", {"amount": 1}, context))
    assert result.effect is not None

    forged = replace(result.effect, provider_receipt="action-not-applied")
    with pytest.raises(ActionIdentityViolation, match="does not identify"):
        session.reconcile(forged, context)

    session.close()


def test_reference_counter_rejected_action_is_non_mutating_and_evidence_bearing() -> None:
    provider = reference_counter_environment()
    session = provider.open_session(session_id="session-npe", services=object())
    context = _context()
    before = session.observe(context).payload["state_digest"]
    result = session.act(ActionRequest("action-reject", "reject", {}, context))

    assert result.accepted is False
    assert result.effect is not None
    assert session.reconcile(result.effect, context) == result.effect
    assert session.observe(context).payload["state_digest"] == before
    session.close()


def test_conformance_requires_typed_unsupported_optional_capabilities() -> None:
    from noetrium_platform.capabilities.environment.api import ActionResult, Observation
    from noetrium_platform.foundation.kernel.kernel import canonical_digest

    digest = canonical_digest({"provider": "unsupported-reference"})

    class _UnsupportedSession:
        def observe(self, context):
            del context
            return Observation("obs-1", digest, {"ready": True})

        def act(self, request):
            return ActionResult(request.action_id, False, None, None, {})

        def reconcile(self, effect, context):
            del effect, context
            raise EnvironmentCapabilityUnsupported("reconcile")

        def checkpoint(self):
            raise EnvironmentCapabilityUnsupported("snapshot")

        def restore(self, payload):
            del payload
            raise EnvironmentCapabilityUnsupported("restore")

        def close(self):
            return None

    class _UnsupportedProvider:
        identity = EnvironmentIdentity("unsupported-reference", "1", "1", "1", digest)
        capabilities = EnvironmentProviderCapabilities()

        def open_session(self, *, session_id, services):
            del session_id, services
            return _UnsupportedSession()

    receipt = verify_environment_provider_conformance(
        _UnsupportedProvider(),
        probe=EnvironmentConformanceProbe("unsupported-session", _context()),
        services=object(),
    )
    assert receipt.checks == (
        "provider_identity",
        "open_session",
        "observe",
        "snapshot_unsupported",
        "restore_unsupported",
    )
    assert receipt.snapshot_sha256 is None


def test_provider_author_effect_primitives_are_public_aliases() -> None:
    receipt = EffectReceipt(
        "effect-public",
        "a" * 64,
        EffectClass.RECONCILABLE,
        EffectCertainty.EFFECT_CONFIRMED,
    )
    assert receipt.certainty is EffectCertainty.EFFECT_CONFIRMED
    assert receipt.effect_class is EffectClass.RECONCILABLE
