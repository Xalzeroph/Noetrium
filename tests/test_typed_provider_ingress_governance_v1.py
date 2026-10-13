from __future__ import annotations

import hashlib

import pytest

from noetrium_platform.foundation.governance.api import RepositorySourceBlob, RepositorySourceSnapshot
from noetrium_platform.foundation.governance.architecture.api import (
    BindingProof,
    CompositionSubject,
    ProviderIngressBoundary,
    ProviderIngressContractError,
    ProviderIngressProtocol,
    ProviderQualificationIdentity,
    ProviderImplementationIdentity,
    ProviderRevision,
    ProviderRevisionKind,
    provider_implementation_from_repository_source,
)
from noetrium_platform.foundation.governance.architecture import audit_provider_ingress_boundaries
from noetrium_platform.foundation.kernel.kernel import Sha256Digest


def _digest(ch: str) -> Sha256Digest:
    return Sha256Digest(ch * 64)


def _blob(path: str, text: str) -> RepositorySourceBlob:
    return RepositorySourceBlob(
        relative_path=path,
        suffix=".py",
        sha256=hashlib.sha256(text.encode("utf-8")).hexdigest(),
        text=text,
    )


def test_provider_revision_requires_immutable_exact_identity() -> None:
    commit = ProviderRevision(ProviderRevisionKind.GIT_COMMIT, "a" * 40)
    content = ProviderRevision(ProviderRevisionKind.CONTENT_SHA256, "b" * 64)
    image = ProviderRevision(ProviderRevisionKind.OCI_SHA256, "sha256:" + "c" * 64)
    package = ProviderRevision(ProviderRevisionKind.PACKAGE_VERSION, "4.37.1")
    service = ProviderRevision(ProviderRevisionKind.SERVICE_REVISION, "2026-08-31.r7")
    assert (commit.value, content.value, image.value, package.value, service.value) == (
        "a" * 40, "b" * 64, "sha256:" + "c" * 64, "4.37.1", "2026-08-31.r7"
    )
    for value in ("main", "master", "latest", "a" * 39, "A" * 40):
        with pytest.raises(ProviderIngressContractError):
            ProviderRevision(ProviderRevisionKind.GIT_COMMIT, value)
    for kind in (ProviderRevisionKind.PACKAGE_VERSION, ProviderRevisionKind.SERVICE_REVISION):
        for value in ("latest", "main", " current ", ""):
            with pytest.raises(ProviderIngressContractError):
                ProviderRevision(kind, value)



class _FrozenSourceIndex:
    def __init__(self, revision: str | None) -> None:
        self.source_revision = revision
        self.source_digest = "d" * 64
        self.source_authority = "git"

    def documents(self, *, suffixes):
        return ()

    def text(self, relative_path: str, *, sha256: str | None = None) -> str:
        raise KeyError(relative_path)

    def python_tree(self, relative_path: str, *, sha256: str | None = None):
        raise KeyError(relative_path)


def test_provider_repository_factory_requires_resolved_git_commit() -> None:
    implementation = provider_implementation_from_repository_source(
        "github.example.provider", _FrozenSourceIndex("e" * 40)
    )
    assert implementation.revision.kind is ProviderRevisionKind.GIT_COMMIT
    assert implementation.revision.value == "e" * 40
    assert implementation.provenance_digest == Sha256Digest("d" * 64)
    with pytest.raises(ProviderIngressContractError):
        provider_implementation_from_repository_source(
            "github.example.provider", _FrozenSourceIndex(None)
        )
    with pytest.raises(ProviderIngressContractError):
        provider_implementation_from_repository_source(
            "github.example.provider", _FrozenSourceIndex("main")
        )

def test_provider_qualification_profile_binds_source_adapter_contract_and_evidence() -> None:
    implementation = ProviderImplementationIdentity(
        implementation_id="github.example.provider",
        revision=ProviderRevision(ProviderRevisionKind.GIT_COMMIT, "a" * 40),
        provenance_digest=_digest("1"),
    )
    profile = ProviderQualificationIdentity(
        provider_identity="provider.example/v1",
        implementation=implementation,
        ingress=ProviderIngressProtocol("mcp"),
        capability_contract_digest=_digest("2"),
        adapter_contract_digest=_digest("3"),
        qualification_evidence_digest=_digest("4"),
    )
    changed = ProviderQualificationIdentity(
        provider_identity=profile.provider_identity,
        implementation=implementation,
        ingress=profile.ingress,
        capability_contract_digest=profile.capability_contract_digest,
        adapter_contract_digest=profile.adapter_contract_digest,
        qualification_evidence_digest=_digest("5"),
    )
    assert isinstance(profile.profile_digest, Sha256Digest)
    assert profile.profile_digest != changed.profile_digest
    assert implementation.digest != _digest("1")
    subject = CompositionSubject.project_subject("demo", "v1")
    proof = BindingProof(
        owner=subject,
        subject=subject,
        requirement_digest=_digest("6"),
        provider_identity=profile.provider_identity,
        provider_profile_digest=profile.profile_digest,
        binding_generation="generation-1",
    )
    assert proof.provider_profile_digest == profile.profile_digest


def test_provider_native_imports_are_confined_to_declared_adapter_boundary() -> None:
    source = RepositorySourceSnapshot(tuple(sorted((
        _blob("noetrium_platform/capabilities/environment/providers/example/adapter.py", "import vendor_mcp.client\n"),
        _blob("noetrium_platform/capabilities/environment/providers/example/runtime.py", "from .adapter import object\n"),
        _blob("noetrium_platform/capabilities/environment/api/contracts.py", "from vendor_mcp import types\n"),
        _blob("noetrium_platform/capabilities/environment/composition/example.py", "import vendor_sdk.session\n"),
    ), key=lambda item: item.relative_path)))
    boundary = ProviderIngressBoundary(
        provider_identity="provider.example/v1",
        ingress=ProviderIngressProtocol("mcp"),
        adapter_module_prefix="noetrium_platform.capabilities.environment.providers.example",
        implementation_import_prefixes=("vendor_mcp", "vendor_sdk"),
    )
    violations = audit_provider_ingress_boundaries(source, (boundary,))
    assert [(row.path, row.imported_module) for row in violations] == [
        ("noetrium_platform/capabilities/environment/api/contracts.py", "vendor_mcp"),
        ("noetrium_platform/capabilities/environment/composition/example.py", "vendor_sdk.session"),
    ]
    assert all(row.code == "provider_native_import_escaped_adapter" for row in violations)


def test_provider_ingress_audit_fails_closed_on_unparseable_source() -> None:
    source = RepositorySourceSnapshot((
        _blob("noetrium_platform/capabilities/environment/providers/example/adapter.py", "def broken(:\n"),
    ))
    boundary = ProviderIngressBoundary(
        provider_identity="provider.example/v1",
        ingress=ProviderIngressProtocol("sdk.python"),
        adapter_module_prefix="noetrium_platform.capabilities.environment.providers.example",
        implementation_import_prefixes=("vendor_sdk",),
    )
    violations = audit_provider_ingress_boundaries(source, (boundary,))
    assert len(violations) == 1
    assert violations[0].code == "source_parse_failed"


def test_provider_ingress_boundaries_reject_ambiguous_or_invalid_declarations() -> None:
    with pytest.raises(ProviderIngressContractError):
        ProviderIngressProtocol("MCP")
    with pytest.raises(ProviderIngressContractError):
        ProviderIngressBoundary(
            provider_identity="provider.example/v1",
            ingress=ProviderIngressProtocol("mcp"),
            adapter_module_prefix="not/a/module",
            implementation_import_prefixes=("vendor",),
        )
    with pytest.raises(ProviderIngressContractError):
        ProviderIngressBoundary(
            provider_identity="provider.example/v1",
            ingress=ProviderIngressProtocol("mcp"),
            adapter_module_prefix="noetrium_platform.capabilities.environment.providers.example",
            implementation_import_prefixes=("vendor", "vendor.client"),
        )
