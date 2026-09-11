from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_root_product_entrypoint_only_forwards_the_single_composition_owner() -> None:
    path = ROOT / "noetrium/platform.py"
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    assert not any(
        isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
        for node in ast.walk(tree)
    )
    imports = {
        (node.module, tuple(alias.name for alias in node.names))
        for node in tree.body
        if isinstance(node, ast.ImportFrom)
    }
    owner = "noetrium_platform.platform"
    assert (owner, ("*",)) in imports
    assert (owner, ("__all__",)) in imports


def test_public_platform_bindings_have_one_runtime_owner() -> None:
    import noetrium.platform as root_platform
    import noetrium_platform.platform as public_platform

    assert root_platform.__all__ == public_platform.__all__
    for name in root_platform.__all__:
        assert getattr(root_platform, name) is getattr(public_platform, name)
