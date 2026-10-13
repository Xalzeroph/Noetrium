from pathlib import Path
import ast

from noetrium_platform.infrastructure.resources.authority import UniversalResourceAuthority

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / "noetrium_platform" / "infrastructure" / "resources"


def test_resource_authority_never_depends_on_runtime_lifecycle() -> None:
    violations = []
    authority_root = RESOURCE / "authority"
    for path in authority_root.rglob("*.py"):
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


def test_resource_lifecycle_has_one_universal_authority() -> None:
    assert UniversalResourceAuthority.__name__ == "UniversalResourceAuthority"
    assert not (RESOURCE / "lease" / "runtime" / "registry.py").exists()
    assert not (RESOURCE / "allocation" / "runtime" / "endpoint_allocator.py").exists()
    assert not (RESOURCE / "compute" / "runtime" / "scheduler.py").exists()
    assert not (RESOURCE / "container" / "runtime" / "lease_authority.py").exists()


def test_resource_product_code_contains_no_parallel_resource_authority() -> None:
    text = "\n".join(
        path.read_text(encoding="utf-8")
        for path in sorted(RESOURCE.rglob("*.py"))
    )
    for forbidden in (
        "class ResourceLeaseRegistry",
        "class AtomicEndpointAllocator",
        "class ComputeScheduler",
        "class DockerContainerLeaseAuthority",
        "class EnvironmentInstanceLeaseAuthority",
    ):
        assert forbidden not in text
