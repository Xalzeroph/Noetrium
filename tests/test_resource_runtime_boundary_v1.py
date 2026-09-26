from pathlib import Path
import ast

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "noetrium_platform" / "infrastructure" / "resources"


def test_resource_authority_never_depends_on_runtime_lifecycle() -> None:
    violations = []
    for path in RESOURCE.rglob("*.py"):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.ImportFrom) and node.module:
                names.append(node.module)
            elif isinstance(node, ast.Import):
                names.extend(alias.name for alias in node.names)
            for name in names:
                if name.startswith("noetrium_platform.infrastructure.lifecycle"):
                    violations.append((str(path.relative_to(ROOT)), node.lineno, name))
    assert violations == []


def test_resource_lease_and_endpoint_expose_one_production_authority_each() -> None:
    from noetrium_platform.infrastructure.resources.allocation import runtime as allocation_runtime
    from noetrium_platform.infrastructure.resources.lease import runtime as lease_runtime

    assert "ResourceLeaseRegistry" in lease_runtime.__all__
    assert "AtomicEndpointAllocator" in allocation_runtime.__all__
    for retired in (
        "InMemoryResourceLeaseRegistry",
        "SQLiteResourceLeaseRegistry",
    ):
        assert not hasattr(lease_runtime, retired)
    for retired in (
        "InMemoryEndpointAllocator",
        "SQLiteEndpointAllocator",
    ):
        assert not hasattr(allocation_runtime, retired)


def test_resource_product_code_contains_no_second_lease_or_endpoint_authority() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(RESOURCE.rglob("*.py"))
    )
    for forbidden in (
        "InMemoryResourceLeaseRegistry",
        "SQLiteResourceLeaseRegistry",
        "InMemoryEndpointAllocator",
        "SQLiteEndpointAllocator",
    ):
        assert forbidden not in text
