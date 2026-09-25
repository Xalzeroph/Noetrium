from __future__ import annotations


def render_research_core(project_id: str) -> str:
    'Render the default Program-first downstream surface.'
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("research core project_id must be non-empty")
    return f'''# USER-OWNED executable semantics.
#
# Implement the actual paper/method/agent semantics here or import arbitrary
# package-local modules. The normal downstream contract is one MethodProgram.
# No ResearchPortfolio, Study, ProjectManifest, provider wiring, scheduler,
# Docker, resource, checkpoint, evidence, or recovery declaration is required.
from noetrium import api


def _return_input(request):
    return api.MethodNodeResult(value=request.input_value)


def build_program() -> api.MethodProgram:
    identity = api.MethodProgramIdentity(
        api.MethodIdentity(
            {project_id!r},
            "1",
            "noetrium.method-machine.v1",
            "1",
        )
    )
    return (
        api.MethodProgramBuilder(identity, entrypoint="return")
        .return_node("return", {project_id!r} + ".return", _return_input)
        .build()
    )


__all__ = ["build_program"]
'''


def render_research_module(project_id: str) -> str:
    'Render the platform-owned lift from Program to internal Research OS IR.'
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("research module project_id must be non-empty")
    return f'''# AUTO-GENERATED Noetrium execution shell. Do not edit.
from noetrium import api
from .core import build_program as _build_program


PROGRAM = _build_program()
if not isinstance(PROGRAM, api.MethodProgram):
    raise TypeError("build_program() must return noetrium.api.MethodProgram")

_research = api.ResearchProgramBuilder({project_id!r})
_research.method_program_factory(
    "method",
    module=__package__ + ".core",
    qualname="build_program",
)
_research.node(
    "run",
    kind=api.ResearchNodeKind.METHOD,
    definitions=("method",),
)
RESEARCH_PROGRAM = _research.freeze()
PORTFOLIO = api.ResearchPortfolio({project_id!r}, (RESEARCH_PROGRAM,))
PROGRAMS = PORTFOLIO.programs

__all__ = ["PROGRAM", "RESEARCH_PROGRAM", "PORTFOLIO", "PROGRAMS"]
'''


def render_generated_test_module(package: str, project_id: str) -> str:
    if type(package) is not str or not package.strip():
        raise ValueError("generated test package must be non-empty")
    if type(project_id) is not str or not project_id.strip():
        raise ValueError("generated test project_id must be non-empty")
    return f'''import unittest

from noetrium import api
from {package}.research import PROGRAM, PORTFOLIO, PROGRAMS, RESEARCH_PROGRAM


class GeneratedProjectTests(unittest.TestCase):
    def test_user_core_builds_executable_program(self):
        self.assertIsInstance(PROGRAM, api.MethodProgram)

    def test_platform_shell_lifts_program_into_research_os(self):
        self.assertIsInstance(RESEARCH_PROGRAM, api.ResearchProgram)
        self.assertIsInstance(PORTFOLIO, api.ResearchPortfolio)
        self.assertEqual(PORTFOLIO.portfolio_id, {project_id!r})
        self.assertEqual(PROGRAMS, (RESEARCH_PROGRAM,))


if __name__ == "__main__":
    unittest.main()
'''


__all__ = [
    "render_generated_test_module",
    "render_research_core",
    "render_research_module",
]
