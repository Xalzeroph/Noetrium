from __future__ import annotations

import hashlib
import shutil
from pathlib import Path

from noetrium_platform.product.operator.api import (
    ProjectCreateReceipt,
    ProjectCreateRequest,
    ProjectTemplateProfile,
    project_template_revision,
)
from noetrium_platform.product.operator.runtime.project_layout import project_package_name
from noetrium_platform.product.operator.runtime.project_platform_identity import installed_platform_identity
from noetrium_platform.foundation.kernel.kernel.durability import InterprocessFileLock, atomic_replace_bytes
from noetrium_platform.foundation.portfolio.api import (
    ProjectIdentity,
    ProjectManifest,
    ProjectSpec,
    ProjectToolProvenance,
    encode_project_manifest,
    project_manifest_document,
)

_MANIFEST_PATH = "project.manifest.json"


def _manifest(request: ProjectCreateRequest, platform_version: str, artifact_digest: str) -> ProjectManifest:
    return ProjectManifest(
        project=ProjectSpec(
            identity=ProjectIdentity(request.project_id, request.version),
            program_id=request.program_id,
            name=request.project_id,
        ),
        template_revision=project_template_revision(request.template_profile),
        provenance=ProjectToolProvenance(
            tool_id="noetrium-cli",
            tool_version=platform_version,
            platform_artifact_sha256=artifact_digest,
        ),
    )


def _pyproject(request: ProjectCreateRequest, package: str, platform_version: str) -> str:
    return f'''[build-system]\nrequires = ["setuptools>=69"]\nbuild-backend = "setuptools.build_meta"\n\n[project]\nname = "{request.project_id}"\nversion = "{request.version}"\nrequires-python = ">=3.11"\ndependencies = ["noetrium=={platform_version}"]\n\n[tool.setuptools.packages.find]\nwhere = ["src"]\ninclude = ["{package}*"]\n'''


def _project_module(request: ProjectCreateRequest) -> str:
    return f'''from noetrium.contracts.project import ProjectIdentity\n\nPROJECT_IDENTITY = ProjectIdentity({request.project_id!r}, {request.version!r})\n\n__all__ = ["PROJECT_IDENTITY"]\n'''


def _author_module(kind: str) -> str:
    return f'''"""Paper-author {kind} definitions.\n\nKeep paper-specific semantics here. The Platform compiler/binding layer consumes\nauthor definitions through public contracts once the producer handoff is available.\nDo not import Platform runtime/provider implementation modules from this file.\n"""\n\n__all__: tuple[str, ...] = ()\n'''


def _author_research_module() -> str:
    return '''from noetrium.contracts.project import ProjectManifest
from noetrium.contracts.research import (
    ResearchBindingContribution,
    ResearchMethodHost,
    ResearchMethodHostPort,
    ResearchStudyDefinition,
)

METHOD_HOST: ResearchMethodHostPort = ResearchMethodHost()


def compile_method(
    definition: ResearchStudyDefinition,
    project_manifest: ProjectManifest,
    binding: ResearchBindingContribution,
):
    return METHOD_HOST.compile_method(definition, project_manifest, binding)


__all__ = ["METHOD_HOST", "compile_method"]
'''


def _requirements_module(request: ProjectCreateRequest) -> str:
    agent_digest = hashlib.sha256(
        f"{request.project_id}:{request.version}:agent".encode("utf-8")
    ).hexdigest()
    prompt_digest = hashlib.sha256(
        f"{request.project_id}:{request.version}:prompt".encode("utf-8")
    ).hexdigest()
    return f'''from noetrium.contracts.agent import AgentIdentity\nfrom noetrium.contracts.model import ModelCapabilityRequirement\nfrom noetrium.contracts.participant import AgentProjectDefinition\n\nAGENT_DEFINITION = AgentProjectDefinition(\n    role="agent",\n    identity=AgentIdentity(\n        agent_id={request.project_id!r},\n        implementation_version={request.version!r},\n        abi_version="1",\n        schema_version="1",\n        artifact_digest={agent_digest!r},\n    ),\n)\nPARTICIPANT_REQUIREMENT = AGENT_DEFINITION.requirement()\nMODEL_REQUIREMENT = ModelCapabilityRequirement(\n    role="agent",\n    prompt_generation_id="generation-1",\n    prompt_id="default",\n    prompt_digest={prompt_digest!r},\n)\n\n__all__ = ["AGENT_DEFINITION", "MODEL_REQUIREMENT", "PARTICIPANT_REQUIREMENT"]\n'''


def _participant_provider_module() -> str:
    return '''from noetrium.contracts.participant import (\n    ParticipantBindingDiagnostic,\n    ParticipantBindingDiagnosticCode,\n    ParticipantBindingDiagnosticSeverity,\n    ParticipantProjectBindingError,\n    ParticipantProviderProfile,\n    ParticipantRequirement,\n    ProjectParticipantBinding,\n    ProjectParticipantProviderPort,\n)\n\n\nclass ProjectParticipantProvider:\n    @property\n    def profile(self) -> ParticipantProviderProfile:\n        return ParticipantProviderProfile(provider_id="project-participant", supported_kinds=("agent",))\n\n    def diagnose(self, requirement: ParticipantRequirement) -> tuple[ParticipantBindingDiagnostic, ...]:\n        return (ParticipantBindingDiagnostic(\n            ParticipantBindingDiagnosticCode.RUNTIME_UNAVAILABLE,\n            ParticipantBindingDiagnosticSeverity.ERROR,\n            "configure a project Participant runtime binding",\n            requirement.digest(),\n            self.profile.provider_id,\n        ),)\n\n    def bind(self, requirement: ParticipantRequirement) -> ProjectParticipantBinding:\n        raise ParticipantProjectBindingError(self.diagnose(requirement))\n\n\nPARTICIPANT_PROVIDER: ProjectParticipantProviderPort = ProjectParticipantProvider()\n'''


def _model_provider_module() -> str:
    return '''from noetrium.contracts.model import (\n    ModelBindingDiagnostic,\n    ModelBindingDiagnosticCode,\n    ModelBindingDiagnosticSeverity,\n    ModelCapabilityRequirement,\n    ModelProjectBindingError,\n    ModelProviderProfile,\n    ProjectModelClientPort,\n    ProjectModelProviderPort,\n)\n\n\nclass ProjectModelProvider:\n    @property\n    def profile(self) -> ModelProviderProfile:\n        return ModelProviderProfile(provider_id="project-model", capabilities=())\n\n    def diagnose(self, requirement: ModelCapabilityRequirement) -> tuple[ModelBindingDiagnostic, ...]:\n        return (ModelBindingDiagnostic(\n            ModelBindingDiagnosticCode.QUALIFIED_BINDING_UNAVAILABLE,\n            ModelBindingDiagnosticSeverity.ERROR,\n            "configure a qualified project Model binding",\n            requirement.digest(),\n            self.profile.provider_id,\n        ),)\n\n    def bind(self, requirement: ModelCapabilityRequirement) -> ProjectModelClientPort:\n        raise ModelProjectBindingError(self.diagnose(requirement))\n\n\nMODEL_PROVIDER: ProjectModelProviderPort = ProjectModelProvider()\n'''


def _environment_provider_module(request: ProjectCreateRequest) -> str:
    digest = hashlib.sha256(
        f"{request.project_id}:{request.version}:environment".encode("utf-8")
    ).hexdigest()
    return f'''from noetrium.contracts.environment import (\n    EnvironmentIdentity,\n    EnvironmentProviderCapabilities,\n    EnvironmentProviderPort,\n    EnvironmentSession,\n    EnvironmentSessionServices,\n)\n\n\nclass ProjectEnvironmentProvider:\n    @property\n    def identity(self) -> EnvironmentIdentity:\n        return EnvironmentIdentity(\n            environment_id={request.project_id!r},\n            implementation_version={request.version!r},\n            abi_version="1",\n            schema_version="1",\n            artifact_digest={digest!r},\n        )\n\n    @property\n    def capabilities(self) -> EnvironmentProviderCapabilities:\n        return EnvironmentProviderCapabilities()\n\n    def open_session(self, *, session_id: str, services: EnvironmentSessionServices) -> EnvironmentSession:\n        del session_id, services\n        raise NotImplementedError("configure a project EnvironmentSession implementation")\n\n\nclass ProjectEnvironmentServices:\n    pass\n\n\nENVIRONMENT_SERVICES: EnvironmentSessionServices = ProjectEnvironmentServices()\nENVIRONMENT_PROVIDER: EnvironmentProviderPort = ProjectEnvironmentProvider()\n'''


def _application_module() -> str:
    return '''from pathlib import Path\n\nfrom noetrium.platform import ResearchApplicationPort, bind_run_control_application\nfrom noetrium.contracts.research import RunControlPort\n\n\ndef build_application(config_path: Path | None) -> ResearchApplicationPort:\n    del config_path\n    raise NotImplementedError("bind the project RunControlPort explicitly")\n\n\ndef bind_control(control: RunControlPort, *, run_id: str, run_manifest_digest: str) -> ResearchApplicationPort:\n    return bind_run_control_application(control, run_id=run_id, run_manifest_digest=run_manifest_digest)\n'''


def _author_test_module(package: str) -> str:
    return f'''import unittest\nfrom pathlib import Path\n\nfrom noetrium.contracts.project import ProjectIdentity, decode_project_manifest_bytes\nfrom {package}.project import PROJECT_IDENTITY\nfrom {package}.research import METHOD_HOST, compile_method\nimport {package}.methods\nimport {package}.tasks\nimport {package}.measurements\nimport {package}.studies\n\nROOT = Path(__file__).resolve().parents[1]\n\n\nclass GeneratedAuthorProjectTests(unittest.TestCase):\n    def test_manifest_identity_matches_public_project_identity(self):\n        manifest = decode_project_manifest_bytes((ROOT / {_MANIFEST_PATH!r}).read_bytes())\n        self.assertIsInstance(PROJECT_IDENTITY, ProjectIdentity)\n        self.assertEqual(manifest.project.identity, PROJECT_IDENTITY)\n\n    def test_author_modules_import_without_provider_plumbing(self):\n        self.assertFalse((ROOT / "src" / {package!r} / "participant_provider.py").exists())\n        self.assertFalse((ROOT / "src" / {package!r} / "model_provider.py").exists())\n        self.assertFalse((ROOT / "src" / {package!r} / "environment_provider.py").exists())\n        self.assertFalse((ROOT / "src" / {package!r} / "application.py").exists())\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''


def _provider_test_module(package: str) -> str:
    return f'''import unittest\nfrom pathlib import Path\n\nfrom noetrium.contracts.environment import EnvironmentProviderPort\nfrom noetrium.contracts.model import ModelProjectBindingError, ProjectModelProviderPort\nfrom noetrium.contracts.participant import ParticipantProjectBindingError, ProjectParticipantProviderPort\nfrom noetrium.contracts.project import ProjectIdentity, decode_project_manifest_bytes\nfrom {package}.environment_provider import ENVIRONMENT_PROVIDER, ENVIRONMENT_SERVICES\nfrom {package}.model_provider import MODEL_PROVIDER\nfrom {package}.participant_provider import PARTICIPANT_PROVIDER\nfrom {package}.project import PROJECT_IDENTITY\nfrom {package}.requirements import MODEL_REQUIREMENT, PARTICIPANT_REQUIREMENT\n\nROOT = Path(__file__).resolve().parents[1]\n\n\nclass GeneratedProviderProjectTests(unittest.TestCase):\n    def test_manifest_identity_matches_public_project_identity(self):\n        manifest = decode_project_manifest_bytes((ROOT / {_MANIFEST_PATH!r}).read_bytes())\n        self.assertIsInstance(PROJECT_IDENTITY, ProjectIdentity)\n        self.assertEqual(manifest.project.identity, PROJECT_IDENTITY)\n\n    def test_provider_templates_use_public_seams_and_fail_closed(self):\n        self.assertIsInstance(PARTICIPANT_PROVIDER, ProjectParticipantProviderPort)\n        with self.assertRaises(ParticipantProjectBindingError):\n            PARTICIPANT_PROVIDER.bind(PARTICIPANT_REQUIREMENT)\n        self.assertIsInstance(MODEL_PROVIDER, ProjectModelProviderPort)\n        with self.assertRaises(ModelProjectBindingError):\n            MODEL_PROVIDER.bind(MODEL_REQUIREMENT)\n        self.assertIsInstance(ENVIRONMENT_PROVIDER, EnvironmentProviderPort)\n        with self.assertRaises(NotImplementedError):\n            ENVIRONMENT_PROVIDER.open_session(session_id="generated-test", services=ENVIRONMENT_SERVICES)\n\n\nif __name__ == "__main__":\n    unittest.main()\n'''


def _readme(project_id: str, profile: ProjectTemplateProfile) -> str:
    if profile is ProjectTemplateProfile.AUTHOR:
        return f'''# {project_id}\n\nThis is the Level-0 paper-author scaffold.\n\nEdit `methods.py`, `tasks.py`, `measurements.py`, and `studies.py`. Use `research.py` as the public Method Host entry point: it compiles typed author facts with an injected ProjectManifest and BindingContribution. Provider, runtime, checkpoint, resource, and evidence authorities remain outside the author project.\n\nRun `noetrium project doctor --project .` to verify the public compiler/binding seam and `noetrium project test --project .` for structural/public-boundary conformance.\n'''
    return f'''# {project_id}\n\nThis is the explicit Level-2 provider-author scaffold.\n\nIt exposes Participant/Model/Environment provider stubs and direct RunControl application binding through public Platform contracts. Every stub fails closed until implemented.\n\nNormal paper authors should use the default `author` template instead.\n'''


def _scaffold_files(request: ProjectCreateRequest) -> tuple[dict[str, bytes], str]:
    platform = installed_platform_identity()
    manifest = _manifest(request, platform.version, platform.artifact_sha256)
    semantic_digest = str(project_manifest_document(manifest)["semantic_digest"])
    package = project_package_name(request.project_id)
    revision = project_template_revision(request.template_profile)
    text_files = {
        ".noetrium-template": revision + "\n",
        "README.md": _readme(request.project_id, request.template_profile),
        "pyproject.toml": _pyproject(request, package, platform.version),
        f"src/{package}/__init__.py": "from .project import PROJECT_IDENTITY\n\n__all__ = [\"PROJECT_IDENTITY\"]\n",
        f"src/{package}/project.py": _project_module(request),
    }
    if request.template_profile is ProjectTemplateProfile.AUTHOR:
        for kind in ("methods", "tasks", "measurements", "studies"):
            text_files[f"src/{package}/{kind}.py"] = _author_module(kind)
        text_files[f"src/{package}/research.py"] = _author_research_module()
        text_files["tests/test_generated_author_project.py"] = _author_test_module(package)
    else:
        text_files[f"src/{package}/requirements.py"] = _requirements_module(request)
        text_files[f"src/{package}/participant_provider.py"] = _participant_provider_module()
        text_files[f"src/{package}/model_provider.py"] = _model_provider_module()
        text_files[f"src/{package}/environment_provider.py"] = _environment_provider_module(request)
        text_files[f"src/{package}/application.py"] = _application_module()
        text_files["tests/test_generated_provider_project.py"] = _provider_test_module(package)
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
        program_id=request.program_id,
        destination=str(root),
        template_profile=request.template_profile,
        template_revision=project_template_revision(request.template_profile),
        manifest_path=_MANIFEST_PATH,
        manifest_semantic_digest=semantic_digest,
        generated_files=tuple(sorted(files)),
    )


__all__ = ["create_project"]
