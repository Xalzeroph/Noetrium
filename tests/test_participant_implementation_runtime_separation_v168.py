from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.capabilities.participant.binding.runtime.configuration import ParticipantConfigurationCatalog
from noetrium_platform.capabilities.participant.core.api import (
    participant_implementation_unit,
    participant_implementation_digest,
    participant_implementation_artifact,
    ParticipantConfigurationArtifact,
        ParticipantRuntimeBinding,
    ParticipantSessionRuntimeIdentity,
)
from noetrium_platform.capabilities.participant.definition.runtime.catalog import ParticipantImplementationCatalog
from noetrium_platform.capabilities.participant.binding.runtime import LocalParticipantResolver
from noetrium_platform.capabilities.participant.session.runtime.runtime_catalog import ParticipantSessionRuntimeCatalog
from noetrium_platform.capabilities.participant.session.runtime.runtime_endpoint import LocalParticipantRuntimeEndpoint
from tests_support import runtime_identity_for_test




class Runtime:
    def __init__(self, identity): self._identity = identity
    @property
    def runtime_identity(self): return self._identity
    def open_session(self, implementation, *, session_id, services):
        raise AssertionError("runtime open is not part of resolver-only test")


@dataclass
class Built:
    config_payload: bytes


def test_one_implementation_can_back_multiple_runtime_configurations_without_new_factory_registration():
    impl = participant_implementation_unit("robot", "arm", "7", "abi1", "schema3", "a" * 64)
    implementations = ParticipantImplementationCatalog()
    calls=[]
    implementations.register(impl, lambda config: calls.append(config.configuration_digest) or Built(config.opaque_payload))

    runtime_identity = runtime_identity_for_test("robot")
    runtimes = ParticipantSessionRuntimeCatalog()
    runtimes.register(runtime_identity, lambda: Runtime(runtime_identity))
    configurations = ParticipantConfigurationCatalog()
    configurations.register(ParticipantConfigurationArtifact("cfg-a", b"speed=1"))
    configurations.register(ParticipantConfigurationArtifact("cfg-b", b"speed=2"))
    resolver = LocalParticipantResolver(
        implementations,
        runtimes,
        configurations,
        LocalParticipantRuntimeEndpoint,
    )

    a = resolver.resolve(ParticipantRuntimeBinding("arm_a", impl, runtime_identity, "cfg-a"))
    b = resolver.resolve(ParticipantRuntimeBinding("arm_b", impl, runtime_identity, "cfg-b"))

    assert a.binding.implementation.unit_digest == b.binding.implementation.unit_digest
    assert a.binding.configuration_digest != b.binding.configuration_digest
    assert a.endpoint.implementation.config_payload == b"speed=1"
    assert b.endpoint.implementation.config_payload == b"speed=2"
    assert calls == ["cfg-a", "cfg-b"]
    assert implementations.identities() == (impl,)


def test_runtime_binding_digest_changes_for_role_or_config_but_not_implementation_digest():
    impl = participant_implementation_unit("agent", "generic", "1", "abi", "schema", "b" * 64)
    a = ParticipantRuntimeBinding("agent", impl, runtime_identity_for_test("agent"), "cfg-a")
    b = ParticipantRuntimeBinding("agent", impl, runtime_identity_for_test("agent"), "cfg-b")
    c = ParticipantRuntimeBinding("planner", impl, runtime_identity_for_test("agent"), "cfg-a")
    assert a.implementation.unit_digest == b.implementation.unit_digest == c.implementation.unit_digest
    assert len({a.digest(), b.digest(), c.digest()}) == 3


def test_resolver_uses_typed_empty_configuration_when_binding_has_no_configuration_digest():
    impl = participant_implementation_unit("robot", "arm", "7", "abi1", "schema3")
    implementations = ParticipantImplementationCatalog()
    seen = []
    implementations.register(
        impl,
        lambda config: seen.append((config.configuration_digest, config.opaque_payload)) or Built(config.opaque_payload),
    )
    runtime_identity = runtime_identity_for_test("robot")
    runtimes = ParticipantSessionRuntimeCatalog()
    runtimes.register(runtime_identity, lambda: Runtime(runtime_identity))
    resolver = LocalParticipantResolver(
        implementations,
        runtimes,
        ParticipantConfigurationCatalog(),
        LocalParticipantRuntimeEndpoint,
    )

    handle = resolver.resolve(ParticipantRuntimeBinding("arm", impl, runtime_identity, None))

    assert handle.binding.configuration_digest is None
    assert seen == [(None, b"")]

@pytest.mark.parametrize(
    "artifact_digest",
    ("bogus", "a" * 63, "g" * 64, "A" * 64),
)
def test_core_participant_implementation_identity_rejects_noncanonical_artifact_digest(artifact_digest: str):
    with pytest.raises(ValueError, match="artifact_digest"):
        participant_implementation_unit("agent", "probe", "1", "abi", "schema", artifact_digest)


def test_core_participant_implementation_identity_accepts_typed_absence_or_canonical_sha256():
    absent = participant_implementation_unit("agent", "probe", "1", "abi", "schema", None)
    exact = participant_implementation_unit("agent", "probe", "1", "abi", "schema", "c" * 64)
    assert participant_implementation_artifact(absent) is None
    assert participant_implementation_artifact(exact) == "c" * 64

@pytest.mark.parametrize(
    "artifact_digest",
    ("bogus", "a" * 63, "g" * 64, "A" * 64),
)
def test_core_participant_session_runtime_identity_rejects_noncanonical_artifact_digest(artifact_digest: str):
    with pytest.raises(ValueError, match="artifact_digest"):
        ParticipantSessionRuntimeIdentity("runtime", "1", "abi", artifact_digest)


def test_core_participant_session_runtime_identity_accepts_canonical_sha256():
    identity = ParticipantSessionRuntimeIdentity("runtime", "1", "abi", "d" * 64)
    assert identity.artifact_digest == "d" * 64
