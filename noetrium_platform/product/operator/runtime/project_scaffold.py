from __future__ import annotations

import shutil
from pathlib import Path

from noetrium_platform.product.operator.api import (
    ProjectCreateReceipt,
    ProjectCreateRequest,
    project_template_revision,
)
from noetrium_platform.product.operator.runtime.project_layout import project_package_name
from noetrium_platform.product.operator.runtime.project_platform_identity import installed_platform_identity
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


def _method_module(request: ProjectCreateRequest) -> str:
    return f'''"""Paper-specific method semantics."""
from noetrium.api import AgentMethodSpec, AgentPhaseSpec

METHOD_SPEC = AgentMethodSpec(
    method_id={request.project_id!r},
    phases=(
        AgentPhaseSpec(
            "solve",
            "agent.solve",
            "Implement the paper-specific method semantics here.",
        ),
    ),
)
METHOD_PROGRAM = METHOD_SPEC.compile()

__all__ = ["METHOD_PROGRAM", "METHOD_SPEC"]
'''


def _study_module() -> str:
    return '''"""Paper experiment declaration."""
from noetrium.api import AgentStudySpec

from .method import METHOD_SPEC

STUDY_SPEC = AgentStudySpec(
    project_id=METHOD_SPEC.method_id,
    study_id=f"{METHOD_SPEC.method_id}.study",
    method_id=METHOD_SPEC.method_id,
)

build_study = STUDY_SPEC.build

__all__ = ["STUDY_SPEC", "build_study"]
'''


def _generated_test_module(package: str) -> str:
    return f'''import unittest
from pathlib import Path

from noetrium.api import (
    AgentMethodSpec,
    AgentStudySpec,
    MethodProgram,
    compile_research_method,
    decode_project_manifest_bytes,
)
from {package}.method import METHOD_PROGRAM, METHOD_SPEC
from {package}.study import STUDY_SPEC, build_study

ROOT = Path(__file__).resolve().parents[1]


class GeneratedProjectTests(unittest.TestCase):
    def test_manifest_identity_matches_method_identity(self):
        manifest = decode_project_manifest_bytes(
            (ROOT / {_MANIFEST_PATH!r}).read_bytes()
        )
        self.assertEqual(
            manifest.project.identity.project_id,
            METHOD_SPEC.method_id,
        )

    def test_method_and_study_use_unified_public_contracts(self):
        self.assertIsInstance(METHOD_SPEC, AgentMethodSpec)
        self.assertIsInstance(METHOD_PROGRAM, MethodProgram)
        self.assertIsInstance(STUDY_SPEC, AgentStudySpec)
        self.assertTrue(callable(build_study))
        self.assertTrue(callable(compile_research_method))


if __name__ == "__main__":
    unittest.main()
'''


def _readme(project_id: str) -> str:
    return f'''# {project_id}

This is a unified Noetrium downstream project.

Edit `method.py` for paper-specific method semantics and `study.py` for the
scientific experiment declaration. Import platform capabilities only from
`noetrium.api`.

Runtime/provider/application code is optional project-owned extension code; it
is not generated as a separate project type.

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
        f"src/{package}/method.py": _method_module(request),
        f"src/{package}/study.py": _study_module(),
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
