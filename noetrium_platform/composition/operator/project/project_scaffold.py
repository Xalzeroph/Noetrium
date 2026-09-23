from __future__ import annotations

import shutil
from pathlib import Path

from noetrium_platform.product.operator.api import (
    ProjectCreateReceipt,
    ProjectCreateRequest,
    project_template_revision,
)
from noetrium_platform.composition.operator.project.project_layout import project_package_name
from noetrium_platform.composition.operator.project.project_platform_identity import installed_platform_identity
from noetrium_platform.foundation.kernel.kernel.durability import (
    InterprocessFileLock,
    atomic_replace_bytes,
)
from noetrium_platform.foundation.portfolio.api import (
    ProjectManifest,
    ProjectSpec,
    ProjectToolProvenance,
    ProjectIdentity,
    encode_project_manifest,
    project_manifest_document,
)

_MANIFEST_PATH = "project.manifest.json"


def _manifest(
    request: ProjectCreateRequest,
    platform_version: str,
    artifact_digest: str,
) -> ProjectManifest:
    return ProjectManifest(
        project=ProjectSpec(
            identity=ProjectIdentity(request.project_id, request.version),
            program_id=request.project_id,
            name=request.project_id,
        ),
        template_revision=project_template_revision(),
        provenance=ProjectToolProvenance(
            tool_id="noetrium-cli",
            tool_version=platform_version,
            platform_artifact_sha256=artifact_digest,
        ),
    )


def _pyproject(
    request: ProjectCreateRequest,
    package: str,
    platform_version: str,
) -> str:
    return f'''[build-system]
requires = ["setuptools>=69"]
build-backend = "setuptools.build_meta"

[project]
name = "{request.project_id}"
version = "{request.version}"
requires-python = ">=3.11"
dependencies = ["noetrium=={platform_version}"]

[tool.setuptools.packages.find]
where = ["src"]
include = ["{package}*"]
'''


def _research_module(request: ProjectCreateRequest) -> str:
    return f'''"""Whole-project scientific authoring through the unified Research OS."""
from noetrium import api


def paper_method(payload=None):
    """Implement the paper-specific method semantics here."""
    return payload


def benchmark():
    """Return or resolve the benchmark/task semantics for this project."""
    return ()


def primary_metric(value):
    """Implement the primary metric semantics here."""
    return 0.0 if value is None else 1.0


_builder = api.ResearchProgramBuilder({request.project_id!r})
_builder.method("method", implementation=paper_method)
_builder.benchmark("benchmark", implementation=benchmark)
_builder.metric("primary-metric", implementation=primary_metric)
_builder.experiment(
    "main",
    definitions=("method", "benchmark"),
    outputs=(
        api.ResearchOutputSpec("trajectory", api.ResearchValueKind.ARTIFACT),
    ),
)
_builder.evaluation(
    "evaluate",
    definitions=("primary-metric",),
    outputs=(
        api.ResearchOutputSpec("score", api.ResearchValueKind.METRIC),
    ),
)
_builder.depends(
    "evaluate",
    "main",
    bindings=(
        api.ResearchInputBinding(
            "trajectory",
            "trajectory",
            api.ResearchValueKind.ARTIFACT,
        ),
    ),
)
_builder.analysis(
    "analysis",
    depends_on=("evaluate",),
    outputs=(
        api.ResearchOutputSpec("claim-evidence", api.ResearchValueKind.EVIDENCE),
    ),
)

PROGRAM = _builder.freeze()
PORTFOLIO = api.ResearchPortfolio({request.project_id!r}, (PROGRAM,))

__all__ = ["PORTFOLIO", "PROGRAM"]
'''



def _generated_test_module(package: str) -> str:
    return f'''import unittest

from noetrium import api
from {package}.research import PORTFOLIO, PROGRAM


class GeneratedProjectTests(unittest.TestCase):
    def test_project_authors_one_top_level_research_program(self):
        self.assertIsInstance(PROGRAM, api.ResearchProgram)
        self.assertIsInstance(PORTFOLIO, api.ResearchPortfolio)
        self.assertEqual(PORTFOLIO.programs, (PROGRAM,))

    def test_program_contains_scientific_pipeline(self):
        self.assertEqual(
            tuple(node.node_id for node in PROGRAM.nodes),
            ("analysis", "evaluate", "main"),
        )
        self.assertEqual(
            tuple(definition.definition_id for definition in PROGRAM.definitions),
            ("benchmark", "method", "primary-metric"),
        )
        self.assertTrue(all(
            len(definition.implementation_digest) == 64
            for definition in PROGRAM.definitions
        ))


if __name__ == "__main__":
    unittest.main()
'''



def _readme(project_id: str) -> str:
    return f'''# {project_id}

This is a unified Noetrium Research OS project.

Edit `research.py` to describe the complete scientific program: methods,
benchmarks, metrics, experiments, evaluations, analyses, dependencies, and
outputs. Use `from noetrium import api` as the only platform import.

Model/environment/resource binding, scheduling, checkpointing, evidence,
recovery, and operator plumbing are platform-owned and are not project files.

Run `noetrium project doctor --project .` and
`noetrium project test --project .`.
'''


def _scaffold_files(
    request: ProjectCreateRequest,
) -> tuple[dict[str, bytes], str]:
    platform = installed_platform_identity()
    manifest = _manifest(request, platform.version, platform.artifact_sha256)
    semantic_digest = str(project_manifest_document(manifest)["semantic_digest"])
    package = project_package_name(request.project_id)
    revision = project_template_revision()
    text_files = {
        ".noetrium-template": revision + "\n",
        "README.md": _readme(request.project_id),
        "pyproject.toml": _pyproject(request, package, platform.version),
        f"src/{package}/__init__.py": '"""Unified Noetrium downstream project."""\n',
        f"src/{package}/research.py": _research_module(request),
        "tests/test_generated_project.py": _generated_test_module(package),
    }
    files = {name: text.encode("utf-8") for name, text in text_files.items()}
    files[_MANIFEST_PATH] = encode_project_manifest(manifest)
    return files, semantic_digest


def _verify_existing(root: Path, files: dict[str, bytes]) -> None:
    actual_files: set[str] = set()
    for target in root.rglob("*"):
        if target.is_symlink():
            raise ValueError("project destination contains a symlink")
        if target.is_file():
            actual_files.add(target.relative_to(root).as_posix())
    expected_files = set(files)
    if actual_files != expected_files:
        unexpected = sorted(actual_files - expected_files)
        missing = sorted(expected_files - actual_files)
        raise ValueError(
            "project destination is not the identical generated scaffold: "
            f"unexpected={unexpected!r} missing={missing!r}"
        )
    for relative, expected in sorted(files.items()):
        target = root / relative
        if target.read_bytes() != expected:
            raise ValueError(
                f"project destination is not the identical generated scaffold: {relative}"
            )


def _write_new_project(root: Path, files: dict[str, bytes]) -> None:
    root.mkdir(parents=False, exist_ok=False)
    marker = ".noetrium-template"
    ordered = [name for name in sorted(files) if name != marker]
    if marker in files:
        ordered.append(marker)
    try:
        for relative in ordered:
            target = root / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            atomic_replace_bytes(target, files[relative])
    except BaseException:
        shutil.rmtree(root, ignore_errors=True)
        raise


def create_project(request: ProjectCreateRequest) -> ProjectCreateReceipt:
    files, semantic_digest = _scaffold_files(request)
    root = request.destination.expanduser().absolute()
    if root.is_symlink():
        raise ValueError("project destination must not be a symlink")
    root.parent.mkdir(parents=True, exist_ok=True)
    lock_path = root.parent / f".{root.name}.noetrium-create.lock"
    with InterprocessFileLock(lock_path):
        if root.exists():
            if not root.is_dir():
                raise ValueError("project destination exists and is not a directory")
            _verify_existing(root, files)
        else:
            _write_new_project(root, files)
    return ProjectCreateReceipt(
        project_id=request.project_id,
        version=request.version,
        destination=str(root),
        template_revision=project_template_revision(),
        manifest_path=_MANIFEST_PATH,
        manifest_semantic_digest=semantic_digest,
        generated_files=tuple(sorted(files)),
    )


__all__ = ["create_project"]
