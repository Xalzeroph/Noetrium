from __future__ import annotations

from dataclasses import dataclass

import pytest

from noetrium_platform.evidence.artifact.api import ArtifactContentIdentity
from noetrium_platform.evidence.artifact.catalog.api import ArtifactNotFound
from noetrium_platform.evidence.artifact.content.api import (
    ArtifactContentIdentityVerificationError,
    ArtifactStorageBinding,
    ArtifactStorageBindingNotFound,
    ArtifactStorageVerificationError,
    VerifiedArtifactStoragePlacement,
)
from noetrium_platform.evidence.artifact.content.api import ArtifactContentIdentityResolverPort
from noetrium_platform.evidence.artifact.content.composition import compose_artifact_content_identity_resolver
from noetrium_platform.evidence.artifact.reference.api import ArtifactReference, ArtifactReferenceNotFound
from noetrium_platform.foundation.scope.api import ScopeIdentity, ScopeKind


DIGEST = "a" * 64
OTHER_DIGEST = "b" * 64


@dataclass(frozen=True)
class _Record:
    artifact_id: str
    digest: str


class _Artifacts:
    def __init__(self, digest: str | None, artifact_id: str = "artifact-1") -> None:
        self.digest = digest
        self.artifact_id = artifact_id

    def get(self, artifact_id: str) -> _Record:
        if self.digest is None:
            raise ArtifactNotFound(artifact_id)
        return _Record(self.artifact_id, self.digest)




class _References:
    def __init__(self, reference: ArtifactReference | None) -> None:
        self.reference = reference

    def resolve(self, reference_id: str, scope: ScopeIdentity) -> ArtifactReference:
        if self.reference is None:
            raise ArtifactReferenceNotFound(reference_id)
        return self.reference


class _Storage:
    def __init__(self, binding: ArtifactStorageBinding | None) -> None:
        self.binding = binding

    def resolve(self, artifact_id: str) -> ArtifactStorageBinding:
        if self.binding is None:
            raise ArtifactStorageBindingNotFound(artifact_id)
        return self.binding



def _resolver(*, artifacts, storage, placement_verifier=None, references=None):
    return compose_artifact_content_identity_resolver(
        artifacts=artifacts,
        storage=storage,
        placement_verifier=placement_verifier or _PlacementVerifier(),
        references=references or _References(None),
    )


def verify_artifact_content_identity(identity, *, artifacts, storage, placement_verifier=None):
    return _resolver(
        artifacts=artifacts, storage=storage, placement_verifier=placement_verifier
    ).verify(identity)


class _PlacementVerifier:
    def __init__(self, *, error_code: str | None = None, foreign: bool = False) -> None:
        self.error_code = error_code
        self.foreign = foreign

    def verify(
        self, *, artifact_id: str, content_sha256: str, storage_provider_id: str, location: str
    ) -> VerifiedArtifactStoragePlacement:
        if self.error_code is not None:
            raise ArtifactStorageVerificationError(self.error_code, "test placement failure")
        return VerifiedArtifactStoragePlacement(
            artifact_id="artifact-foreign" if self.foreign else artifact_id,
            content_sha256=content_sha256,
            storage_provider_id=storage_provider_id,
            location=location,
            size_bytes=1,
        )


def load_verified_artifact_content_identity(artifact_id, *, artifacts, storage, placement_verifier=None):
    return _resolver(
        artifacts=artifacts, storage=storage, placement_verifier=placement_verifier
    ).load(artifact_id)


def resolve_artifact_reference_content_identity(
    reference_id, scope, *, references, artifacts, storage, placement_verifier=None
):
    return _resolver(
        artifacts=artifacts,
        storage=storage,
        placement_verifier=placement_verifier,
        references=references,
    ).snapshot_reference(reference_id, scope)


def _verify(identity, *, artifacts, storage, placement_verifier=None):
    return verify_artifact_content_identity(
        identity,
        artifacts=artifacts,
        storage=storage,
        placement_verifier=placement_verifier or _PlacementVerifier(),
    )

def _binding(
    *,
    artifact_id: str = "artifact-1",
    digest: str = DIGEST,
    location: str = "A:/artifact.bin",
    generation: int = 1,
) -> ArtifactStorageBinding:
    return ArtifactStorageBinding(
        artifact_id=artifact_id,
        content_sha256=digest,
        storage_provider_id="artifact.filesystem",
        location=location,
        generation=generation,
    )


def test_artifact_content_identity_is_portable_and_minimal() -> None:
    identity = ArtifactContentIdentity("artifact-1", DIGEST)
    assert identity.artifact_id == "artifact-1"
    assert identity.content_sha256 == DIGEST
    assert not hasattr(identity, "location")
    assert not hasattr(identity, "reference_id")
    assert not hasattr(identity, "generation")

    with pytest.raises(ValueError):
        ArtifactContentIdentity("", DIGEST)
    with pytest.raises(ValueError):
        ArtifactContentIdentity("artifact-1", "A" * 64)


def test_artifact_content_identity_survives_storage_relocation() -> None:
    identity = ArtifactContentIdentity("artifact-1", DIGEST)
    artifacts = _Artifacts(DIGEST)

    first = _verify(
        identity,
        artifacts=artifacts,
        storage=_Storage(_binding(location="A:/artifact.bin", generation=1)),
    )
    relocated = _verify(
        identity,
        artifacts=artifacts,
        storage=_Storage(_binding(location="B:/archive/artifact.bin", generation=2)),
    )

    assert first is identity
    assert relocated is identity


def test_artifact_content_identity_fails_closed_on_catalog_or_storage_drift() -> None:
    identity = ArtifactContentIdentity("artifact-1", DIGEST)

    with pytest.raises(ArtifactContentIdentityVerificationError) as missing_artifact:
        _verify(identity, artifacts=_Artifacts(None), storage=_Storage(_binding()))
    assert missing_artifact.value.code == "ARTIFACT_NOT_FOUND"

    with pytest.raises(ArtifactContentIdentityVerificationError) as catalog_drift:
        _verify(identity, artifacts=_Artifacts(OTHER_DIGEST), storage=_Storage(_binding()))
    assert catalog_drift.value.code == "CATALOG_DIGEST_MISMATCH"


    with pytest.raises(ArtifactContentIdentityVerificationError) as missing_storage:
        _verify(identity, artifacts=_Artifacts(DIGEST), storage=_Storage(None))
    assert missing_storage.value.code == "STORAGE_BINDING_NOT_FOUND"

    with pytest.raises(ArtifactContentIdentityVerificationError) as storage_drift:
        _verify(
            identity,
            artifacts=_Artifacts(DIGEST),
            storage=_Storage(_binding(digest=OTHER_DIGEST)),
        )
    assert storage_drift.value.code == "STORAGE_DIGEST_MISMATCH"


class _ForeignArtifacts(_Artifacts):
    def get(self, artifact_id: str) -> _Record:
        return _Record("artifact-foreign", DIGEST)


def test_artifact_content_identity_rejects_foreign_identity_impostors() -> None:
    identity = ArtifactContentIdentity("artifact-1", DIGEST)

    with pytest.raises(ArtifactContentIdentityVerificationError) as catalog_impostor:
        _verify(identity, artifacts=_ForeignArtifacts(DIGEST), storage=_Storage(_binding()))
    assert catalog_impostor.value.code == "CATALOG_IDENTITY_MISMATCH"

    foreign_binding = ArtifactStorageBinding(
        artifact_id="artifact-foreign",
        content_sha256=DIGEST,
        storage_provider_id="artifact.filesystem",
        location="A:/artifact.bin",
        generation=1,
    )
    with pytest.raises(ArtifactContentIdentityVerificationError) as storage_impostor:
        _verify(identity, artifacts=_Artifacts(DIGEST), storage=_Storage(foreign_binding))
    assert storage_impostor.value.code == "STORAGE_IDENTITY_MISMATCH"


def test_artifact_content_identity_requires_provider_owned_placement_proof() -> None:
    identity = ArtifactContentIdentity("artifact-1", DIGEST)
    with pytest.raises(ArtifactContentIdentityVerificationError) as error:
        _verify(
            identity,
            artifacts=_Artifacts(DIGEST),
            storage=_Storage(_binding()),
            placement_verifier=_PlacementVerifier(error_code="CONTENT_SHA256_MISMATCH"),
        )
    assert error.value.code == "STORAGE_PLACEMENT_UNVERIFIED"
    assert isinstance(error.value.__cause__, ArtifactStorageVerificationError)


def test_artifact_content_identity_rejects_foreign_placement_proof() -> None:
    identity = ArtifactContentIdentity("artifact-1", DIGEST)
    with pytest.raises(ArtifactContentIdentityVerificationError) as error:
        _verify(
            identity,
            artifacts=_Artifacts(DIGEST),
            storage=_Storage(_binding()),
            placement_verifier=_PlacementVerifier(foreign=True),
        )
    assert error.value.code == "STORAGE_PLACEMENT_MISMATCH"


def test_load_verified_artifact_content_identity_builds_from_artifact_authority() -> None:
    identity = load_verified_artifact_content_identity(
        "artifact-1",
        artifacts=_Artifacts(DIGEST),
        storage=_Storage(_binding()),
        placement_verifier=_PlacementVerifier(),
    )
    assert identity == ArtifactContentIdentity("artifact-1", DIGEST)


def test_mutable_reference_is_snapshotted_to_immutable_content_identity() -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "project-1")
    first_reference = ArtifactReference("latest", scope, "artifact-1", 1)
    first = resolve_artifact_reference_content_identity(
        "latest",
        scope,
        references=_References(first_reference),
        artifacts=_Artifacts(DIGEST),
        storage=_Storage(_binding()),
        placement_verifier=_PlacementVerifier(),
    )
    assert first == ArtifactContentIdentity("artifact-1", DIGEST)
    assert not hasattr(first, "generation")
    assert not hasattr(first, "reference_id")


def test_reference_snapshot_rejects_missing_or_foreign_reference_facts() -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "project-1")
    with pytest.raises(ArtifactContentIdentityVerificationError) as missing:
        resolve_artifact_reference_content_identity(
            "latest",
            scope,
            references=_References(None),
            artifacts=_Artifacts(DIGEST),
            storage=_Storage(_binding()),
            placement_verifier=_PlacementVerifier(),
        )
    assert missing.value.code == "ARTIFACT_REFERENCE_NOT_FOUND"

    foreign = ArtifactReference("other", scope, "artifact-1", 1)
    with pytest.raises(ArtifactContentIdentityVerificationError) as mismatch:
        resolve_artifact_reference_content_identity(
            "latest",
            scope,
            references=_References(foreign),
            artifacts=_Artifacts(DIGEST),
            storage=_Storage(_binding()),
            placement_verifier=_PlacementVerifier(),
        )
    assert mismatch.value.code == "ARTIFACT_REFERENCE_IDENTITY_MISMATCH"


def test_reference_retarget_creates_new_snapshot_without_mutating_old_identity() -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "project-1")
    first = resolve_artifact_reference_content_identity(
        "latest",
        scope,
        references=_References(ArtifactReference("latest", scope, "artifact-1", 1)),
        artifacts=_Artifacts(DIGEST, "artifact-1"),
        storage=_Storage(_binding(artifact_id="artifact-1", digest=DIGEST)),
        placement_verifier=_PlacementVerifier(),
    )
    second = resolve_artifact_reference_content_identity(
        "latest",
        scope,
        references=_References(ArtifactReference("latest", scope, "artifact-2", 2)),
        artifacts=_Artifacts(OTHER_DIGEST, "artifact-2"),
        storage=_Storage(_binding(artifact_id="artifact-2", digest=OTHER_DIGEST)),
        placement_verifier=_PlacementVerifier(),
    )
    assert first == ArtifactContentIdentity("artifact-1", DIGEST)
    assert second == ArtifactContentIdentity("artifact-2", OTHER_DIGEST)
    assert first != second


def test_reference_snapshot_rejects_runtime_reference_impostor() -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "project-1")

    class _Impostor:
        reference_id = "latest"
        artifact_id = "artifact-1"
        generation = 1

        def __init__(self, resolved_scope: ScopeIdentity) -> None:
            self.scope = resolved_scope

    with pytest.raises(ArtifactContentIdentityVerificationError) as error:
        resolve_artifact_reference_content_identity(
            "latest",
            scope,
            references=_References(_Impostor(scope)),
            artifacts=_Artifacts(DIGEST),
            storage=_Storage(_binding()),
            placement_verifier=_PlacementVerifier(),
        )
    assert error.value.code == "ARTIFACT_REFERENCE_TYPE_MISMATCH"


def test_composed_resolver_exposes_one_typed_fail_closed_surface() -> None:
    scope = ScopeIdentity(ScopeKind.PROJECT, "project-1")
    resolver = _resolver(
        artifacts=_Artifacts(DIGEST),
        storage=_Storage(_binding()),
        references=_References(ArtifactReference("latest", scope, "artifact-1", 1)),
    )
    assert isinstance(resolver, ArtifactContentIdentityResolverPort)
    assert resolver.verify(ArtifactContentIdentity("artifact-1", DIGEST)) == ArtifactContentIdentity(
        "artifact-1", DIGEST
    )
    assert resolver.load("artifact-1") == ArtifactContentIdentity("artifact-1", DIGEST)
    assert resolver.snapshot_reference("latest", scope) == ArtifactContentIdentity("artifact-1", DIGEST)

    with pytest.raises(ValueError):
        resolver.load("")
    with pytest.raises(ValueError):
        resolver.snapshot_reference("", scope)
    with pytest.raises(TypeError):
        resolver.snapshot_reference("latest", object())  # type: ignore[arg-type]


def test_removed_function_style_identity_entrypoints_are_not_public() -> None:
    import noetrium_platform.evidence.artifact.content.composition as composition

    for old_name in (
        "verify_artifact_content_identity",
        "load_verified_artifact_content_identity",
        "resolve_artifact_reference_content_identity",
    ):
        assert not hasattr(composition, old_name)


def test_content_identity_is_owned_only_by_top_level_artifact_api() -> None:
    import noetrium_platform.evidence.artifact.content.api as content_api

    assert ArtifactContentIdentity("artifact-1", DIGEST).artifact_id == "artifact-1"
    assert not hasattr(content_api, "ArtifactContentIdentity")