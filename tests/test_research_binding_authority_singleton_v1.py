from __future__ import annotations

import ast
from pathlib import Path


_CANONICAL = Path(
    "noetrium_platform/composition/research_binding_authority.py"
)
_OWNED_NAMES = {
    "ResearchBindingAuthority",
    "ResearchBindingAuthorityError",
    "ResearchBindingResolutionContext",
    "ResearchCapabilityBindingResolverPort",
    "ResearchModelRoleBindingResolverPort",
    "ResearchParticipantBindingResolverPort",
    "ResearchProjectManifestResolverPort",
}


def test_research_binding_authority_has_one_platform_implementation() -> None:
    root = Path(__file__).resolve().parents[1]
    definitions: dict[str, list[str]] = {
        name: [] for name in sorted(_OWNED_NAMES)
    }

    for path in sorted((root / "noetrium_platform").rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        relative = path.relative_to(root).as_posix()
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name in definitions:
                definitions[node.name].append(relative)

    expected = _CANONICAL.as_posix()
    assert definitions == {
        name: [expected] for name in sorted(_OWNED_NAMES)
    }
