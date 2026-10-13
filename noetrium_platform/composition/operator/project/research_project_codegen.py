def render_research_module(project_id: str) -> str:
    """Render the initial user-owned scientific Unit module."""
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("research module project_id must be non-empty")
    return f'''"""USER-OWNED scientific semantics.

NoetriumUnit is the complete scientific language. Paper-specific concepts are
open schemas and roles; Noetrium does not require Method/Study/Experiment
carrier classes.
"""
from noetrium import NoetriumUnit


def _bootstrap():
    """Minimal executable used only until the author replaces this root."""
    return None


def build_research() -> NoetriumUnit:
    implementation = NoetriumUnit.from_python_callable(
        "root.implementation",
        _bootstrap,
    )
    implementation_symbol = NoetriumUnit.make_symbol(
        "root.implementation",
        traits=("noetrium.implementation", "research.runtime"),
        implementation=implementation,
    )
    executable = NoetriumUnit.make_structure(
        "root",
        traits=("research.runtime",),
        symbols=(implementation_symbol,),
    )
    return NoetriumUnit.make_structure(
        {project_id!r},
        traits=("research.portfolio",),
        members=(executable,),
    )


ROOT = build_research()
if type(ROOT) is not NoetriumUnit:
    raise TypeError("build_research() must return noetrium.NoetriumUnit")
if ROOT.unit_id != {project_id!r}:
    raise ValueError("build_research() root Unit id must match project identity")


__all__ = ["ROOT", "build_research"]
'''


def render_generated_test_module(package: str, project_id: str) -> str:
    if type(package) is not str or not package.strip():
        raise ValueError("generated test package must be non-empty")
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("generated test project_id must be non-empty")
    return f'''import unittest

from noetrium import NoetriumUnit
from {package}.research import ROOT


class GeneratedProjectTests(unittest.TestCase):
    def test_user_research_exports_root_unit(self):
        self.assertIsInstance(ROOT, NoetriumUnit)
        self.assertEqual(ROOT.unit_id, {project_id!r})
        self.assertTrue(ROOT.has_schema("research.portfolio"))

    def test_scaffold_does_not_impose_scientific_topology(self):
        self.assertTrue(ROOT.members)
        unit_ids = tuple(unit.unit_id for unit in ROOT.members)
        self.assertEqual(len(unit_ids), len(set(unit_ids)))


if __name__ == "__main__":
    unittest.main()
'''


__all__ = [
    "render_generated_test_module",
    "render_research_module",
]
