from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DOWNSTREAM_RESEARCH_ROOTS = (
    ROOT / "research" / "authoring",
    ROOT / "research" / "benchmarks",
    ROOT / "research" / "reproductions",
)
FORBIDDEN_IMPORT_MARKERS = (
    "from noetrium_platform",
    "import noetrium_platform",
    "from noetrium.contracts",
    "import noetrium.contracts",
    "from noetrium.platform",
    "import noetrium.platform",
    "from components.api",
    "import components.api",
    "from orchestration",
    "import orchestration",
)


def test_research_workspace_uses_one_downstream_api() -> None:
    violations: list[str] = []
    for root in DOWNSTREAM_RESEARCH_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for marker in FORBIDDEN_IMPORT_MARKERS:
                if marker in text:
                    violations.append(f"{path.relative_to(ROOT)}: {marker}")
    assert violations == []


def test_unified_api_is_the_declared_catalog_entrypoint() -> None:
    from noetrium import api

    assert api.catalog().entrypoint == "noetrium.api"
