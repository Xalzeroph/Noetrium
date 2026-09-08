import json
from pathlib import Path

import pytest

import noetrium_platform.capabilities.model.qualification.providers.qualification_host_probe as host_module
from noetrium_platform.capabilities.model.qualification.providers.qualification_accelerator_probe import AcceleratorFactsProbe
from noetrium_platform.capabilities.model.qualification.providers.qualification_host_probe import HostFactsProbe
from noetrium_platform.capabilities.model.qualification.providers.qualification_model_artifact_probe import ModelArtifactProbe
from noetrium_platform.capabilities.model.qualification.providers.qualification_python_facts_probe import PythonFactsProbe


def test_host_probe_captures_resource_values_without_controller(monkeypatch) -> None:
    monkeypatch.setattr(host_module.os, "cpu_count", lambda: 12)
    monkeypatch.setattr(host_module.platform, "node", lambda: "qual-host")
    monkeypatch.setattr(host_module.platform, "machine", lambda: "x86_64")
    monkeypatch.setattr(host_module.platform, "libc_ver", lambda: ("glibc", "2.39"))
    monkeypatch.setattr(
        HostFactsProbe,
        "_meminfo_bytes",
        staticmethod(lambda key: {"MemTotal": 128 << 30, "MemAvailable": 96 << 30}[key]),
    )
    monkeypatch.setattr(
        HostFactsProbe,
        "_integer_file",
        staticmethod(lambda path: {"memory.max": 64 << 30, "memory.current": 8 << 30, "pids.max": 4096}.get(path.name)),
    )

    facts, errors = HostFactsProbe().host(2.0)

    assert facts.hostname == "qual-host"
    assert facts.logical_cpu_count == 12
    assert facts.physical_memory_bytes == 128 << 30
    assert facts.available_memory_bytes == 96 << 30
    assert facts.cgroup_memory_limit_bytes == 64 << 30
    assert facts.cgroup_memory_current_bytes == 8 << 30
    assert facts.pids_limit == 4096
    assert facts.libc == "glibc"
    assert tuple(errors) == facts.errors


def test_accelerator_probe_captures_cuda_and_gpu_facts() -> None:
    def run(argv, timeout):
        del timeout
        if argv[:2] == ("nvidia-smi", "--query-gpu=driver_version"):
            return 0, "580.173.02\n", ""
        if argv == ("nvidia-smi",):
            return 0, "CUDA Version: 13.0 NVIDIA Management Library Version: 580.173.02", ""
        if argv[:2] == ("nvcc", "--version"):
            return 0, "Cuda compilation tools, release 12.4, V12.4.131", ""
        if argv[:2] == ("ldconfig", "-p"):
            return 0, "libcudart.so.13.0 => /usr/lib/libcudart.so.13.0\nlibcuda.so.1 => /usr/lib/libcuda.so.1", ""
        if argv[0] == "nvidia-smi" and any("pci.bus_id" in item for item in argv):
            return 0, "0, GPU-0, RTX 3090, 24576, 24000, 00000000:01:00.0, 8.6, 350.0", ""
        if argv[0] == str(Path("/opt/python/bin/python")):
            return 0, "8.6\n", ""
        raise AssertionError(argv)

    probe = AcceleratorFactsProbe(run)
    cuda, cuda_errors = probe.cuda(2.0)

    assert cuda.driver_version == "580.173.02"
    assert cuda.driver_cuda_version == "13.0"
    assert cuda.toolkit_version == "12.4"
    assert cuda.runtime_library_versions == ("1", "13.0")
    assert cuda_errors == []


def test_accelerator_probe_parses_extended_gpu_row() -> None:
    from noetrium_platform.capabilities.model.qualification.api import DeploymentQualificationRequest, PythonRuntimeFacts

    def run(argv, timeout):
        del timeout
        if argv[0] == "nvidia-smi" and any("pci.bus_id" in item for item in argv):
            return 0, "0, GPU-0, RTX 3090, 24576, 24000, 00000000:01:00.0, 8.6, 350.0", ""
        if argv[0] == str(Path("/opt/python/bin/python")):
            return 0, "8.6\n", ""
        raise AssertionError(argv)

    request = DeploymentQualificationRequest(
        "model", Path("/models/model"), Path("/opt/python/bin/python")
    )
    python = PythonRuntimeFacts("/opt/python/bin/python", "3.11.0", None, False, False, None, None, None)
    gpus, errors = AcceleratorFactsProbe(run).gpus(request, python, 2.0)

    assert errors == []
    assert len(gpus) == 1
    assert gpus[0].uuid == "GPU-0"
    assert gpus[0].compute_capability == "8.6"
    assert gpus[0].pci_bus_id == "00000000:01:00.0"
    assert gpus[0].power_limit_watts == 350.0



def test_local_capability_probe_composes_split_fact_probes(tmp_path) -> None:
    import json
    from noetrium_platform.capabilities.model.qualification.api import DeploymentQualificationRequest
    from noetrium_platform.capabilities.model.qualification.providers.qualification_probe import LocalDeploymentCapabilityProbe
    from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult

    model_path = tmp_path / "model"
    model_path.mkdir()
    (model_path / "config.json").write_text(json.dumps({"model_type": "test", "architectures": ["TestModel"]}), encoding="utf-8")
    python_executable = Path("/opt/python/bin/python")

    class Runner:
        def run(self, argv, *, cwd=None, environment=None, timeout_seconds=None):
            del cwd, environment, timeout_seconds
            argv = tuple(argv)
            if len(argv) >= 3 and argv[1] == "-c" and "sysconfig.get_paths" in argv[2]:
                payload = {"version": "3.11.0", "site_packages": None, "torch_version": None, "kernel_architectures": [], "native_library_names": [], "python_abi": "cpython-311", "platform_tag": "test"}
                return LocalCommandResult(argv, 0, json.dumps(payload), "")
            if argv[1:4] == ("-m", "pip", "--version"):
                return LocalCommandResult(argv, 0, "pip 26.0", "")
            if argv[1:4] == ("-m", "ensurepip", "--version"):
                return LocalCommandResult(argv, 0, "pip 26.0", "")
            if len(argv) >= 3 and argv[1] == "-c" and "import venv" in argv[2]:
                return LocalCommandResult(argv, 0, "ok", "")
            return LocalCommandResult(argv, 1, "", "unavailable")

    facts = LocalDeploymentCapabilityProbe(Runner()).capture(
        DeploymentQualificationRequest("model", model_path, python_executable, backends=("dummy",), package_index_urls=("https://example.invalid/simple",), probe_timeout_seconds=1.0)
    )

    assert facts.model.config_present is True
    assert facts.python.version == "3.11.0"
    assert facts.host.logical_cpu_count >= 1
    assert facts.package_indexes[0].package == "dummy"


def _capture_model_artifact(tmp_path: Path, payload: object):
    model_path = tmp_path / "strict-model"
    model_path.mkdir()
    (model_path / "config.json").write_text(json.dumps(payload), encoding="utf-8")
    from noetrium_platform.capabilities.model.qualification.api import DeploymentQualificationRequest

    request = DeploymentQualificationRequest(
        "strict-model",
        model_path,
        Path("/opt/python/bin/python"),
    )
    return ModelArtifactProbe.capture(request)


def test_model_artifact_probe_preserves_exact_typed_config_facts(tmp_path: Path) -> None:
    facts, error = _capture_model_artifact(
        tmp_path,
        {
            "model_type": "qwen3",
            "architectures": ["Qwen3ForCausalLM"],
            "torch_dtype": "bfloat16",
            "max_position_embeddings": 32768,
        },
    )

    assert error is None
    assert facts.config_present is True
    assert facts.model_type == "qwen3"
    assert facts.architectures == ("Qwen3ForCausalLM",)
    assert facts.torch_dtype == "bfloat16"
    assert facts.context_length == 32768


def test_model_artifact_probe_rejects_non_object_config_without_throwing(tmp_path: Path) -> None:
    facts, error = _capture_model_artifact(tmp_path, ["not", "an", "object"])

    assert facts.config_present is False
    assert facts.model_type is None
    assert facts.architectures == ()
    assert facts.context_length is None
    assert error == "model config.json root must be a JSON object"
    assert facts.error == error


@pytest.mark.parametrize(
    "payload, expected_detail",
    [
        ({"model_type": 123}, "model_type must be non-empty text"),
        ({"architectures": "Qwen3ForCausalLM"}, "architectures must be a JSON list"),
        ({"architectures": ["Qwen3ForCausalLM", 7]}, "architectures must contain only non-empty strings"),
        ({"torch_dtype": 16}, "torch_dtype must be non-empty text"),
        ({"max_position_embeddings": "32768"}, "max_position_embeddings must be a positive integer"),
        ({"max_position_embeddings": True}, "max_position_embeddings must be a positive integer"),
        ({"max_position_embeddings": 0}, "max_position_embeddings must be a positive integer"),
    ],
)
def test_model_artifact_probe_fails_closed_on_malformed_typed_facts(
    tmp_path: Path,
    payload: object,
    expected_detail: str,
) -> None:
    facts, error = _capture_model_artifact(tmp_path, payload)

    assert facts.config_present is False
    assert error is not None
    assert expected_detail in error
    assert facts.error == error


_VALID_PYTHON_INFO = {
    "version": "3.12.10",
    "site_packages": "/opt/python/lib/python3.12/site-packages",
    "torch_version": "2.8.0",
    "kernel_architectures": ["sm86"],
    "native_library_names": ["libcudart.so.13"],
    "python_abi": "cpython-312",
    "platform_tag": "linux-x86_64",
}


def _capture_python_info(payload: object):
    def run(argv: tuple[str, ...], timeout: float):
        del timeout
        if len(argv) >= 3 and argv[1] == "-c" and "sysconfig.get_paths" in argv[2]:
            return 0, json.dumps(payload), ""
        if len(argv) >= 3 and argv[1] == "-c" and "import torch" in argv[2]:
            return 1, "", "torch unavailable"
        if argv[1:4] == ("-m", "pip", "--version"):
            return 0, "pip 26.0", ""
        if argv[1:4] == ("-m", "ensurepip", "--version"):
            return 0, "pip 26.0", ""
        if len(argv) >= 3 and argv[1] == "-c" and "import venv" in argv[2]:
            return 0, "ok", ""
        raise AssertionError(argv)

    return PythonFactsProbe(run).capture(Path("/opt/python/bin/python"), 1.0)


def test_python_facts_probe_preserves_exact_typed_observation() -> None:
    facts, errors = _capture_python_info(dict(_VALID_PYTHON_INFO))

    assert errors == []
    assert facts.version == "3.12.10"
    assert facts.kernel_architectures == ("sm86",)
    assert facts.native_library_names == ("libcudart.so.13",)
    assert facts.python_abi == "cpython-312"
    assert facts.platform_tag == "linux-x86_64"


@pytest.mark.parametrize(
    "payload, expected_detail",
    [
        (["not", "an", "object"], "root must be a JSON object"),
        ({key: value for key, value in _VALID_PYTHON_INFO.items() if key != "version"}, "field set mismatch"),
        ({**_VALID_PYTHON_INFO, "unexpected": "field"}, "field set mismatch"),
        ({**_VALID_PYTHON_INFO, "version": 312}, "version must be non-empty text"),
        ({**_VALID_PYTHON_INFO, "site_packages": 12}, "site_packages must be non-empty text"),
        ({**_VALID_PYTHON_INFO, "kernel_architectures": "sm86"}, "kernel_architectures must be a JSON list"),
        ({**_VALID_PYTHON_INFO, "native_library_names": ["libcudart.so.13", 7]}, "native_library_names must contain only non-empty strings"),
    ],
)
def test_python_facts_probe_fails_closed_on_malformed_typed_observation(
    payload: object,
    expected_detail: str,
) -> None:
    facts, errors = _capture_python_info(payload)

    assert facts.version == "unknown"
    assert facts.site_packages is None
    assert facts.torch_version is None
    assert facts.kernel_architectures == ()
    assert facts.native_library_names == ()
    assert facts.python_abi is None
    assert facts.platform_tag is None
    assert len(errors) == 1
    assert "invalid typed facts" in errors[0]
    assert expected_detail in errors[0]
    assert facts.errors == tuple(errors)
