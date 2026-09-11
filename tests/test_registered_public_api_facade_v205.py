from pathlib import Path

from noetrium_platform.foundation.governance.architecture import public_api_invariants
from noetrium_platform.foundation.governance.architecture.public_api_invariants import audit_registered_public_facades
from noetrium_platform.foundation.governance.architecture.source_index import architecture_source_index
from noetrium_platform.foundation.governance.system_registry.api import (
    DownstreamSurfaceMode,
    SystemDescriptor,
    SystemIdentity,
    SystemLayer,
)


def test_registered_boundaries_do_not_reexport_concrete_layers():
    root = Path(__file__).resolve().parents[1]
    assert audit_registered_public_facades(root) == []


def test_nested_api_facade_cannot_reexport_its_runtime_layer(tmp_path, monkeypatch):
    package = tmp_path / "noetrium_platform" / "sample"
    (package / "api").mkdir(parents=True)
    (package / "providers").mkdir()
    (package / "__init__.py").write_text("", encoding="utf-8")
    (package / "api" / "__init__.py").write_text(
        "from ..providers import SampleProvider\n",
        encoding="utf-8",
    )
    (package / "providers" / "__init__.py").write_text("", encoding="utf-8")
    descriptor = SystemDescriptor(
        identity=SystemIdentity("sample"),
        layer=SystemLayer.RUNTIME,
        package_prefix="noetrium_platform.sample",
        downstream_surface=DownstreamSurfaceMode.PUBLIC,
    )
    monkeypatch.setattr(public_api_invariants, "system_catalog", lambda: (descriptor,))
    with architecture_source_index(tmp_path):
        violations = audit_registered_public_facades(tmp_path)
    assert len(violations) == 1
    assert violations[0].invariant == "registered_public_api_facade"
