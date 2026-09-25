from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
LINEAGE_PACKAGES = (
    "react_alfworld",
    "reflexion_alfworld",
    "tree_of_thoughts",
    "rap_reasoning",
    "lats_webshop",
    "tree_search_language_model_agents",
    "exact_vwa",
    "qlass_alfworld",
    "lits_math500",
    "agent_q_surrogate",
    "mars_automated_ai_research",
    "gats",
)


def _tree(path: Path) -> ast.Module:
    return ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def _calls_method_source_lane(tree: ast.AST) -> bool:
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        if isinstance(node.func, ast.Name) and node.func.id == "MethodSourceLane":
            return True
        if isinstance(node.func, ast.Attribute) and node.func.attr == "MethodSourceLane":
            return True
    return False


def _imports_canonical_source(tree: ast.AST) -> bool:
    return any(
        isinstance(node, ast.ImportFrom)
        and node.level == 1
        and node.module == "source"
        and bool(node.names)
        for node in ast.walk(tree)
    )


def test_lineage_fidelity_has_one_source_provenance_authority() -> None:
    base = ROOT / "research" / "reproductions"
    for package in LINEAGE_PACKAGES:
        package_root = base / package
        source = package_root / "source.py"
        fidelity = package_root / "fidelity.py"
        assert source.is_file(), package
        assert fidelity.is_file(), package

        fidelity_tree = _tree(fidelity)
        assert _imports_canonical_source(fidelity_tree), package
        assert not _calls_method_source_lane(fidelity_tree), package


def test_lineage_package_root_does_not_reexport_source_authority() -> None:
    base = ROOT / "research" / "reproductions"
    for package in LINEAGE_PACKAGES:
        package_init = base / package / "__init__.py"
        tree = _tree(package_init)
        source_imports = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.ImportFrom)
            and node.level == 1
            and node.module == "source"
        ]
        assert source_imports == [], package
