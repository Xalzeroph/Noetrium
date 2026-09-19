from pathlib import Path
import json
from dataclasses import replace

from noetrium_platform.capabilities.model.qualification.api import (
    CudaFacts,
    DeploymentCapabilityFacts,
    DeploymentQualificationRequest,
    GpuCapabilityFacts,
    GpuFabricFacts,
    HostExecutionFacts,
    ModelArtifactFacts,
    OperatingSystemFacts,
    PackageArtifactFacts,
    PackageDependencyNodeFacts,
    PackageIndexFacts,
    PythonRuntimeFacts,
    StorageCapabilityFacts,
    CandidateDecision,
    native_cuda_runtime_package_names,
)
from noetrium_platform.capabilities.model.qualification.runtime.qualification import (
    DeploymentQualificationResolver,
    _QualificationFactView,
)
from noetrium_platform.product.operator.maintenance.runtime.management.deployments import _qualification_python_path
from noetrium_platform.capabilities.model.qualification.providers.qualification_probe import LocalDeploymentCapabilityProbe
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult


def _facts(*, kernel_architectures: tuple[str, ...] = ("sm100",)) -> DeploymentCapabilityFacts:
    return DeploymentCapabilityFacts(
        captured_at_unix=1.0,
        operating_system=OperatingSystemFacts("Linux", "Ubuntu", "22.04", "6.8", "x86_64"),
        cuda=CudaFacts("580.173.02", "13.0", "12.4", ("12",)),
        gpus=(GpuCapabilityFacts("0", "GPU-0", "RTX 3090", 24576, 24000, "8.6"),),
        python=PythonRuntimeFacts(
            "/opt/python/bin/python",
            "3.11.0",
            "pip 26.0",
            True,
            True,
            "/opt/python/lib/python3.11/site-packages",
            "2.11.0",
            "13.0",
            kernel_architectures,
            native_library_names=("libcudart.so.13",),
        ),
        model=ModelArtifactFacts(
            "example-model",
            "/models/example-model",
            "example_decoder",
            ("ExampleForConditionalGeneration",),
            "bfloat16",
            262144,
            True,
        ),
        package_indexes=(
            PackageIndexFacts(
                "sglang", "https://pypi.org/simple", ("0.5.17",),
                selected_version="0.5.17", dependency_closure_complete=True,
            ),
            PackageIndexFacts(
                "vllm", "https://pypi.org/simple", ("0.27.1",),
                selected_version="0.27.1", dependency_closure_complete=True,
            ),
            PackageIndexFacts(
                "sglang-kernel",
                "https://docs.sglang.io/whl/cu130/",
                ("0.4.6.post1+cu130",),
                selected_version="0.4.6.post1+cu130",
                dependency_closure_complete=True,
            ),
        ),
        host=HostExecutionFacts("test-host", "x86_64", 16, 128 << 30, 96 << 30),
        fabric=GpuFabricFacts(("GPU0 GPU1 NV1",), "2.18", "/usr/lib/libnccl.so.2"),
        storage=StorageCapabilityFacts("/models/example-model", 1 << 40, 512 << 30, 1_000_000, "xfs", "dev0", True, True),
    )



def test_qualification_fact_view_indexes_are_structurally_immutable() -> None:
    view = _QualificationFactView.build(_facts())
    assert not isinstance(view.by_package, dict)
    assert not isinstance(view.by_identity, dict)
    assert view.by_package["vllm"][0].selected_version == "0.27.1"

    import pytest
    with pytest.raises(TypeError):
        dict.__setitem__(view.by_package, "forged", ())
    with pytest.raises(TypeError):
        dict.__setitem__(view.by_identity, ("vllm", "forged"), view.by_package["vllm"][0])


def test_resolver_rejects_observed_sglang_architecture_mismatch_and_selects_vllm() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        tensor_parallel=1,
    )

    plan = DeploymentQualificationResolver().resolve(request, _facts())

    sglang, vllm = plan.candidates
    assert sglang.decision is CandidateDecision.REJECTED
    assert "sm86" in " ".join(sglang.reasons)
    assert sglang.packages[0].version == "0.5.17"
    assert vllm.decision is CandidateDecision.ACCEPTED
    assert vllm.packages[0].name == "vllm"
    assert vllm.packages[0].version == "0.27.1"
    assert plan.selected_backend == "vllm"
    assert len(plan.plan_digest) == 64


def test_resolver_does_not_call_unobserved_kernel_support_qualified() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
    )

    plan = DeploymentQualificationResolver().resolve(request, _facts(kernel_architectures=()))

    sglang = plan.candidates[0]
    assert sglang.decision is CandidateDecision.REJECTED
    assert "not observable yet" in " ".join(sglang.reasons)


def test_resolver_rejects_candidate_with_incomplete_dependency_closure() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        backends=("vllm",),
    )
    facts = _facts()
    facts = DeploymentCapabilityFacts(
        captured_at_unix=facts.captured_at_unix,
        operating_system=facts.operating_system,
        cuda=facts.cuda,
        gpus=facts.gpus,
        python=facts.python,
        model=facts.model,
        package_indexes=(
            PackageIndexFacts(
                "vllm", "https://pypi.org/simple", ("0.27.1",),
                selected_version="0.27.1",
                dependency_closure_error="metadata request failed",
            ),
        ),
        host=facts.host,
        fabric=facts.fabric,
        storage=facts.storage,
    )

    plan = DeploymentQualificationResolver().resolve(request, facts)

    assert plan.selected_backend is None
    assert "dependency closure is incomplete" in " ".join(plan.candidates[0].reasons)


def test_resolver_freezes_observed_dependency_nodes_into_install_plan() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        backends=("vllm",),
    )
    facts = _facts()
    root_artifact = PackageArtifactFacts(
        "vllm-0.27.1-cp38-abi3-manylinux_2_28_x86_64.whl",
        "0.27.1",
        "wheel",
        sha256="1" * 64,
    )
    dependency_artifact = PackageArtifactFacts(
        "torch-2.11.0-cp311-cp311-manylinux_2_28_x86_64.whl",
        "2.11.0",
        "wheel",
        sha256="2" * 64,
    )
    facts = DeploymentCapabilityFacts(
        captured_at_unix=facts.captured_at_unix,
        operating_system=facts.operating_system,
        cuda=facts.cuda,
        gpus=facts.gpus,
        python=facts.python,
        model=facts.model,
        package_indexes=(
            PackageIndexFacts(
                "vllm",
                "https://pypi.org/simple",
                ("0.27.1",),
                selected_version="0.27.1",
                artifacts=(root_artifact,),
                dependency_nodes=(
                    PackageDependencyNodeFacts(
                        "vllm",
                        "0.27.1",
                        "https://pypi.org/simple",
                        root_artifact,
                    ),
                    PackageDependencyNodeFacts(
                        "torch",
                        "2.11.0",
                        "https://pypi.org/simple",
                        dependency_artifact,
                    ),
                ),
                dependency_closure_complete=True,
            ),
        ),
        host=facts.host,
        fabric=facts.fabric,
        storage=facts.storage,
    )

    plan = DeploymentQualificationResolver().resolve(request, facts)

    candidate = plan.candidates[0]
    assert candidate.decision is CandidateDecision.ACCEPTED
    assert [(item.name, item.version) for item in candidate.packages] == [
        ("vllm", "0.27.1"),
        ("torch", "2.11.0"),
    ]
    assert "dependency-package-plan:vllm:1-package(s)" in candidate.evidence_refs


def test_resolver_uses_first_observed_configured_index() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        backends=("vllm",),
    )
    facts = _facts()
    facts = DeploymentCapabilityFacts(
        captured_at_unix=facts.captured_at_unix,
        operating_system=facts.operating_system,
        cuda=facts.cuda,
        gpus=facts.gpus,
        python=facts.python,
        model=facts.model,
        package_indexes=(
            PackageIndexFacts(
                "vllm", "https://mirror.example/simple", ("0.27.1",),
                selected_version="0.27.1", dependency_closure_complete=True,
            ),
            PackageIndexFacts(
                "vllm", "https://pypi.org/simple", ("0.27.1",),
                selected_version="0.27.1", dependency_closure_complete=True,
            ),
        ),
        host=facts.host,
        fabric=facts.fabric,
        storage=facts.storage,
    )

    plan = DeploymentQualificationResolver().resolve(request, facts)

    assert plan.selected_backend == "vllm"
    assert plan.candidates[0].packages[0].index_url == "https://mirror.example/simple"


def test_resolver_freezes_missing_native_cuda_runtime_package() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        backends=("vllm",),
    )
    facts = _facts()
    facts = replace(
        facts,
        python=replace(facts.python, native_library_names=()),
        package_indexes=(
            *facts.package_indexes,
            PackageIndexFacts(
                "nvidia-cuda-runtime-cu13",
                "https://pypi.org/simple",
                ("13.0.3.0",),
                selected_version="13.0.3.0",
                artifacts=(
                    PackageArtifactFacts(
                        "nvidia_cuda_runtime_cu13-13.0.3.0-cp311-cp311-manylinux_2_28_x86_64.whl",
                        "13.0.3.0",
                        "wheel",
                        platform_tags=("manylinux_2_28_x86_64",),
                    ),
                ),
                dependency_closure_complete=True,
            ),
        ),
    )

    plan = DeploymentQualificationResolver().resolve(request, facts)

    candidate = plan.candidates[0]
    assert candidate.decision is CandidateDecision.ACCEPTED
    assert ("nvidia-cuda-runtime-cu13", "13.0.3.0") in {
        (item.name, item.version) for item in candidate.packages
    }
    assert any(
        ref.startswith("native-cuda-runtime:libcudart.so.13:planned:")
        for ref in candidate.evidence_refs
    )


def test_native_cuda_runtime_replaces_conflicting_closure_provider() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        backends=("vllm",),
    )
    facts = replace(
        _facts(),
        python=replace(_facts().python, native_library_names=()),
        package_indexes=(
            PackageIndexFacts(
                "vllm",
                "https://pypi.org/simple",
                ("0.27.1",),
                selected_version="0.27.1",
                dependency_nodes=(
                    PackageDependencyNodeFacts(
                        "vllm",
                        "0.27.1",
                        "https://pypi.org/simple",
                        PackageArtifactFacts("vllm.whl", "0.27.1", "wheel"),
                    ),
                    PackageDependencyNodeFacts(
                        "nvidia-cuda-runtime",
                        "13.0.96",
                        "https://pypi.org/simple",
                        PackageArtifactFacts(
                            "nvidia_cuda_runtime-13.0.96.whl",
                            "13.0.96",
                            "wheel",
                        ),
                    ),
                ),
                dependency_closure_complete=True,
            ),
            PackageIndexFacts(
                "nvidia-cuda-runtime",
                "https://pypi.org/simple",
                ("13.3.29",),
                selected_version="13.3.29",
                artifacts=(
                    PackageArtifactFacts(
                        "nvidia_cuda_runtime-13.3.29-py3-none-manylinux2014_x86_64.whl",
                        "13.3.29",
                        "wheel",
                        platform_tags=("manylinux2014_x86_64",),
                    ),
                ),
                dependency_closure_complete=True,
            ),
        ),
    )

    candidate = DeploymentQualificationResolver().resolve(request, facts).candidates[0]

    assert candidate.decision is CandidateDecision.ACCEPTED
    providers = [
        item
        for item in candidate.packages
        if item.name.lower().replace("_", "-") == "nvidia-cuda-runtime"
    ]
    assert [(item.name, item.version) for item in providers] == [
        ("nvidia-cuda-runtime", "13.3.29")
    ]
    assert "native-cuda-runtime:libcudart.so.13:single-provider:nvidia-cuda-runtime" in candidate.evidence_refs


def test_cuda13_runtime_provider_prefers_observed_unsuffixed_nvidia_package() -> None:
    assert native_cuda_runtime_package_names("13.0") == (
        "nvidia-cuda-runtime",
        "nvidia-cuda-runtime-cu13",
    )


def test_resolver_rejects_native_runtime_placeholder_wheel() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        backends=("vllm",),
    )
    facts = _facts()
    facts = replace(
        facts,
        python=replace(facts.python, native_library_names=()),
        package_indexes=(
            *facts.package_indexes,
            PackageIndexFacts(
                "nvidia-cuda-runtime-cu13",
                "https://pypi.org/simple",
                ("0.0.0a0",),
                selected_version="0.0.0a0",
                artifacts=(
                    PackageArtifactFacts(
                        "nvidia_cuda_runtime_cu13-0.0.0a0-py3-none-any.whl",
                        "0.0.0a0",
                        "wheel",
                        platform_tags=("any",),
                    ),
                ),
                dependency_closure_complete=True,
            ),
        ),
    )

    candidate = DeploymentQualificationResolver().resolve(request, facts).candidates[0]

    assert candidate.decision is CandidateDecision.REJECTED
    assert "does not provide a platform-specific binary artifact" in " ".join(candidate.reasons)
    assert not any(item.name == "nvidia-cuda-runtime-cu13" for item in candidate.packages)


def test_probe_parses_primary_and_extra_pip_indexes() -> None:
    assert LocalDeploymentCapabilityProbe._parse_package_index_urls(
        "global.index-url='https://mirror.example/simple'\n"
        "global.extra-index-url='https://extra.example/simple https://third.example/simple'\n"
    ) == (
        "https://mirror.example/simple",
        "https://extra.example/simple",
        "https://third.example/simple",
    )


def test_qualification_request_keeps_venv_interpreter_path_unresolved() -> None:
    # Resolving this path would erase the environment prefix when bin/python
    # is a symlink to the system interpreter.
    selected = _qualification_python_path(Path("/opt/envs/serving/bin/python"))
    assert selected.as_posix().endswith("/opt/envs/serving/bin/python")


def test_package_index_qualification_consumes_artifact_metadata_without_install() -> None:
    class Runner:
        def __init__(self) -> None:
            self.calls: list[tuple[str, ...]] = []

        def run(self, argv, *, cwd=None, environment=None, timeout_seconds=None):
            self.calls.append(tuple(argv))
            if len(argv) >= 4 and argv[1:4] == ("-m", "pip", "index"):
                return LocalCommandResult(tuple(argv), 0, "Available versions: 1.2.3", "")
            return LocalCommandResult(
                tuple(argv),
                0,
                json.dumps(
                    {
                        "selected_version": "1.2.3",
                        "artifacts": [
                            {
                                "filename": "vllm-1.2.3-cp311-cp311-manylinux_2_28_x86_64.whl",
                                "version": "1.2.3",
                                "kind": "wheel",
                                "sha256": "a" * 64,
                                "python_tags": ["cp311"],
                                "abi_tags": ["cp311"],
                                "platform_tags": ["manylinux_2_28_x86_64"],
                                "requires_python": ">=3.11",
                            }
                        ],
                        "dependency_nodes": [],
                        "dependency_closure_complete": True,
                        "dependency_closure_error": None,
                        "error": None,
                    }
                ),
                "",
            )

    runner = Runner()
    item = LocalDeploymentCapabilityProbe(runner)._index(
        Path("/opt/env/bin/python"), "vllm", "https://pypi.org/simple", 3.0
    )

    assert item.selected_version == "1.2.3"
    assert item.artifacts[0].sha256 == "a" * 64
    assert not any("install" in call for call in runner.calls)


def test_package_index_probe_preserves_target_stderr_on_failure() -> None:
    class Runner:
        def run(self, argv, *, cwd=None, environment=None, timeout_seconds=None):
            if len(argv) >= 4 and argv[1:4] == ("-m", "pip", "index"):
                return LocalCommandResult(tuple(argv), 0, "Available versions: 1.2.3", "")
            return LocalCommandResult(tuple(argv), 17, "", "metadata endpoint failed")

    item = LocalDeploymentCapabilityProbe(Runner())._index(
        Path("/opt/env/bin/python"), "vllm", "https://pypi.org/simple", 3.0
    )

    assert item.selected_version is None
    assert "metadata endpoint failed" in (item.dependency_closure_error or "")


def test_resolver_rejects_incomplete_python_capability_facts() -> None:
    request = DeploymentQualificationRequest(
        "example-model",
        Path("/models/example-model"),
        Path("/opt/python/bin/python"),
        backends=("vllm",),
    )
    facts = _facts()
    facts = replace(
        facts,
        python=replace(
            facts.python,
            errors=("Python capability probe returned invalid typed facts: field set mismatch",),
        ),
    )

    plan = DeploymentQualificationResolver().resolve(request, facts)

    candidate = plan.candidates[0]
    assert candidate.decision is CandidateDecision.REJECTED
    assert "target Python capability facts are incomplete" in " ".join(candidate.reasons)
    assert plan.selected_backend is None
