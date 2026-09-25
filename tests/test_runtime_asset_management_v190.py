from __future__ import annotations

import argparse
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Event, Thread
import unittest

import pytest
from unittest.mock import patch

from noetrium_platform.composition.operator.maintenance.management import (
    directories as directory_management,
)
from noetrium_platform.foundation.scope.api import PLATFORM_SCOPE
from noetrium_platform.foundation.kernel.kernel import (
    DurableCarrierClosureAuthority,
    DurableCarrierReferenceClosure,
)
from noetrium_platform.foundation.scope.runtime import InMemoryScopeRegistry
from noetrium_platform.infrastructure.resources.directory.api import (
    DirectoryLayout,
    ManagedDirectoryKind,
)
from noetrium_platform.infrastructure.resources.directory.runtime import build_local_directory_authorities
from noetrium_platform.capabilities.model.asset.api import (
    ModelAssetMode,
    ModelSourceSpec,
)
from noetrium_platform.capabilities.model.api import ModelAuthorities
from noetrium_platform.capabilities.model.deployment.api import ModelDeploymentLogs, ModelDeploymentSelector, ModelDeploymentSpec, ModelDesiredState, ModelRuntimeState
from noetrium_platform.infrastructure.resources.compute.api import GpuDeviceStatus, GpuProcessStatus, GpuRuntimeSnapshot
from noetrium_platform.capabilities.model.asset.providers import HuggingFaceCliModelSource
from noetrium_platform.capabilities.model.asset.runtime import LocalModelAssetStorage, ModelAssetManager, ModelAssetRegistry
from noetrium_platform.capabilities.model.composition import DeploymentModelAssetReferences
from noetrium_platform.capabilities.model.assignment.runtime import ModelAssignmentManager
from noetrium_platform.capabilities.model.deployment.runtime import (
    AppliedModelDeploymentStore,
    DurableModelAutoRecoveryAuthority,
    FileModelControllerStateStore,
    ModelDesiredStateController,
    ModelDeploymentCatalog,
    ModelDeploymentRegistry,
    ModelDeploymentLogReader,
    ModelDeploymentRuntime,
    ModelLaunchMaterializer,
    ModelFleetRuntime,
    ModelResourceView,
    sglang_deployment,
    vllm_deployment,
)
from noetrium_platform.infrastructure.resources.compute.providers import NvidiaSmiGpuRuntimeObserver
from noetrium_platform.infrastructure.lifecycle.python.api import EnvironmentCommandResult, PythonEnvironmentOwnership, PythonEnvironmentSpec
from noetrium_platform.infrastructure.lifecycle.python.runtime import CondaEnvironmentBackend, build_python_environment_authorities
from noetrium_platform.infrastructure.lifecycle.process.api import LocalCommandResult
from noetrium_platform.infrastructure.lifecycle.service.api import (
    ServiceProcessIdentity,
    ServiceReconcileObservation,
    ServiceStartOutcome,
    ServiceStopOutcome,
)


def layout(root: Path) -> DirectoryLayout:
    return DirectoryLayout(
        releases=root / "releases",
        runtime=root / "runtime",
        state=root / "state",
        logs=root / "logs",
        model_artifacts=root / "models",
        python_environments=root / "envs",
        cache=root / "cache",
        temp=root / "tmp",
        locks=root / "locks",
        workspaces=root / "workspaces",
    )


@pytest.mark.parametrize(
    "argv",
    (
        ("dirs", "entries", "cache", "--limit", "-1"),
        ("dirs", "clean", "cache", "--older-than-seconds", "-1"),
        ("dirs", "clean", "cache", "--older-than-seconds", "nan"),
        ("dirs", "clean", "cache", "--older-than-seconds", "inf"),
        ("dirs", "clean", "cache", "--older-than-seconds", "-inf"),
    ),
)
def test_directory_management_cli_rejects_unsafe_numeric_bounds(
    argv: tuple[str, ...],
) -> None:
    parser = argparse.ArgumentParser()
    groups = parser.add_subparsers(dest="group", required=True)
    directory_management.register(groups)

    with pytest.raises(SystemExit):
        parser.parse_args(argv)


@pytest.mark.parametrize("limit", (-1, True, 1.5))
def test_directory_inspector_rejects_invalid_limits(
    tmp_path: Path,
    limit: object,
) -> None:
    manager = build_local_directory_authorities(layout(tmp_path))

    with pytest.raises(ValueError, match="non-negative integer"):
        manager.inspection.entries(
            ManagedDirectoryKind.CACHE,
            limit=limit,  # type: ignore[arg-type]
        )


class FakeEnvBackend:
    backend_id = "fake"

    def create(self, root: Path, spec: PythonEnvironmentSpec) -> Path:
        python = root / "bin" / "python"
        python.parent.mkdir(parents=True, exist_ok=True)
        python.write_text("fake", encoding="utf-8")
        return python

    def python_path(self, root: Path) -> Path:
        return root / "bin" / "python"

    def install(self, root: Path, requirements: Path, *, extra_args=()):
        return EnvironmentCommandResult((str(self.python_path(root)), "pip"), 0, "installed", "")


class FakeCommandRunner:
    def __init__(self) -> None:
        self.calls = []

    def run(self, argv, *, cwd=None, environment=None):
        self.calls.append((tuple(argv), cwd, environment))
        tail = tuple(argv)
        if tail[-4:] == ("-m", "pip", "list", "--format=json"):
            stdout = '[{"name":"pip","version":"25.0"}]'
        elif tail[-3:] == ("-m", "pip", "freeze"):
            stdout = "pip==25.0\npytest==9.0\n"
        else:
            stdout = "ran"
        return EnvironmentCommandResult(tuple(argv), 0, stdout, "")


class RecordingCommandRunner(FakeCommandRunner):
    pass


class FakeGpuObserver:
    def __init__(self, snapshot=None):
        self._snapshot = snapshot or GpuRuntimeSnapshot(False, detail="test-no-gpu")

    def snapshot(self):
        return self._snapshot


class FakeRuntime:
    def __init__(self) -> None:
        self.live = False
        self.stop_succeeds = True
        self.start_calls = 0
        self.process: ServiceProcessIdentity | None = None

    def reconcile_exact(self, contract):
        return ServiceReconcileObservation(
            True,
            self.process if self.live else None,
        )

    def start_exact(self, contract):
        self.start_calls += 1
        self.live = True
        self.process = ServiceProcessIdentity(
            1233 + self.start_calls,
            f"start:{self.start_calls}",
        )
        return ServiceStartOutcome(
            contract.digest(),
            self.process,
            "ready:test",
            1234.5,
        )

    def verify_ready_exact(self, contract):
        raise NotImplementedError

    def stop_exact(self, contract, expected_process):
        if self.process is not None and self.process != expected_process:
            raise RuntimeError("test runtime process generation drifted")
        if not self.stop_succeeds:
            return ServiceStopOutcome(contract.digest(), False)
        self.live = False
        self.process = None
        return ServiceStopOutcome(contract.digest(), True)


class FakeFactory:
    def __init__(self, log_root: Path | None = None) -> None:
        self.runtime = FakeRuntime()
        self.contracts = []
        self.environments = []
        self.log_root = log_root or Path("/tmp")

    def open(self, contract, *, environment, readiness_url):
        self.contracts.append(contract)
        self.environments.append(environment)
        return self.runtime

    def logs(self, contract, *, deployment_id):
        return ModelDeploymentLogs(deployment_id, self.log_root / "stdout.log", self.log_root / "stderr.log")


def build_environments(directories, runner=None):
    command_runner = runner or FakeCommandRunner()
    return build_python_environment_authorities(directories.layout, (FakeEnvBackend(),), command_runner)


def build_models(directories, environments, factory, *, source_backends=(), gpu_observer=None):
    asset_registry = ModelAssetRegistry(directories.layout)
    deployment_registry = ModelDeploymentRegistry(directories.layout)
    applied_store = AppliedModelDeploymentStore(directories.layout)
    storage = LocalModelAssetStorage(directories.layout)
    catalog = ModelDeploymentCatalog(asset_registry, deployment_registry, environments.lifecycle)
    assets = ModelAssetManager(asset_registry, DeploymentModelAssetReferences(catalog), storage, source_backends)
    materializer = ModelLaunchMaterializer(assets, environments.lifecycle)
    runtime = ModelDeploymentRuntime(applied_store, catalog, materializer, factory)
    fleet = ModelFleetRuntime(
        catalog,
        runtime,
        DurableModelAutoRecoveryAuthority(directories.layout),
    )
    logs = ModelDeploymentLogReader(applied_store, catalog, materializer, factory)
    resources = ModelResourceView(assets, catalog, fleet, gpu_observer or FakeGpuObserver())
    controller = ModelDesiredStateController(
        fleet,
        FileModelControllerStateStore(directories.layout.layout.state / "model" / "deployments" / "controller.json"),
    )
    assignments = ModelAssignmentManager(InMemoryScopeRegistry())
    return ModelAuthorities(assets, assignments, catalog, runtime, fleet, logs, resources, controller)

def _closed_model_gc(models: ModelAuthorities, model_id: str):
    return models.assets.assess_model_gc(
        model_id,
        closures=(
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EVIDENCE,
                "1" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.EXECUTION,
                "2" * 64,
                (),
            ),
            DurableCarrierReferenceClosure(
                DurableCarrierClosureAuthority.RECOVERY,
                "3" * 64,
                (),
            ),
        ),
    )



class ManagementTests(unittest.TestCase):
    def test_directory_manager_allocates_and_removes_workspaces(self):
        with TemporaryDirectory() as td:
            manager = build_local_directory_authorities(layout(Path(td)))
            allocation = manager.workspaces.allocate_workspace("run-1", scope=PLATFORM_SCOPE, category="study", owner="paper-1")
            self.assertTrue(allocation.path.exists())
            self.assertEqual(manager.workspaces.list_workspaces(category="study")[0].owner, "paper-1")
            self.assertEqual(manager.layout.root(ManagedDirectoryKind.MODEL_ARTIFACTS), Path(td) / "models")
            (manager.layout.root(ManagedDirectoryKind.CACHE) / "large.bin").write_bytes(b"x" * 32)
            (manager.layout.root(ManagedDirectoryKind.CACHE) / "small.bin").write_bytes(b"x" * 4)
            overview = manager.inspection.overview(ManagedDirectoryKind.CACHE)
            self.assertEqual(overview.top_level_entries, 2)
            entries = manager.inspection.entries(ManagedDirectoryKind.CACHE, limit=1)
            self.assertEqual(entries[0].path.name, "large.bin")
            self.assertEqual(entries[0].bytes, 32)
            gc = manager.workspaces.assess_workspace_gc(
                "run-1",
                scope=PLATFORM_SCOPE,
                category="study",
                closures=(
                    DurableCarrierReferenceClosure(
                        DurableCarrierClosureAuthority.EVIDENCE,
                        "1" * 64,
                        (),
                    ),
                    DurableCarrierReferenceClosure(
                        DurableCarrierClosureAuthority.EXECUTION,
                        "2" * 64,
                        (),
                    ),
                    DurableCarrierReferenceClosure(
                        DurableCarrierClosureAuthority.RECOVERY,
                        "3" * 64,
                        (),
                    ),
                ),
            )
            self.assertTrue(
                manager.workspaces.remove_workspace(
                    "run-1",
                    scope=PLATFORM_SCOPE,
                    category="study",
                    gc=gc,
                )
            )

    def test_python_environment_manager_is_backend_driven(self):
        with TemporaryDirectory() as td:
            directories = build_local_directory_authorities(layout(Path(td)))
            manager = build_environments(directories)
            value = manager.lifecycle.create(PythonEnvironmentSpec("agent", PLATFORM_SCOPE, backend="fake"))
            self.assertTrue(value.python_path.exists())
            self.assertEqual(value.ownership, PythonEnvironmentOwnership.MANAGED)
            self.assertEqual(manager.execution.command("agent", "-m", "pytest")[1:], ("-m", "pytest"))
            req = Path(td) / "requirements.txt"
            req.write_text("x==1", encoding="utf-8")
            self.assertEqual(manager.packages.install("agent", req).returncode, 0)
            self.assertEqual(manager.packages.install_packages("agent", ("pytest==9.0",)).returncode, 0)
            self.assertEqual(manager.packages.packages("agent")[0].name, "pip")
            self.assertEqual(manager.packages.freeze("agent"), ("pip==25.0", "pytest==9.0"))
            self.assertEqual(manager.packages.check("agent").returncode, 0)
            self.assertEqual(manager.packages.uninstall_packages("agent", ("pytest",)).returncode, 0)
            self.assertEqual(manager.execution.run("agent", "-c", "print(1)").returncode, 0)
            self.assertEqual(len(manager.lifecycle.list()), 1)

    def test_registered_external_environment_remove_only_drops_metadata(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            manager = build_environments(directories)
            external = root / "external-env"
            python = external / "bin" / "python"
            python.parent.mkdir(parents=True)
            python.write_text("external", encoding="utf-8")
            value = manager.lifecycle.register_existing(PythonEnvironmentSpec("external", PLATFORM_SCOPE, backend="fake"), external)
            self.assertEqual(value.ownership, PythonEnvironmentOwnership.EXTERNAL)
            self.assertTrue(manager.lifecycle.remove("external"))
            self.assertTrue(external.exists())
            self.assertTrue(python.exists())

    def test_conda_and_mamba_backends_build_prefix_commands(self):
        with TemporaryDirectory() as td:
            root = Path(td) / "env"
            for executable, backend_id in (("conda", "conda"), ("mamba", "mamba")):
                runner = RecordingCommandRunner()
                backend = CondaEnvironmentBackend(runner, executable=executable, backend_id=backend_id)
                backend.create(root, PythonEnvironmentSpec("e", PLATFORM_SCOPE, backend=backend_id, python_version="3.11"))
                self.assertEqual(
                    runner.calls[-1][0],
                    (executable, "create", "-y", "-p", str(root), "python=3.11"),
                )

    def test_model_manager_handles_mutable_desired_state_without_qualification(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake"))
            model_dir = root / "external-model"
            model_dir.mkdir()
            (model_dir / "config.json").write_text(
                '{"model_type":"example_model","architectures":["ExampleForCausalLM"],"torch_dtype":"bfloat16","max_position_embeddings":32768,"quantization_config":{"quant_method":"awq","bits":4}}',
                encoding="utf-8",
            )
            factory = FakeFactory()
            models = build_models(directories, environments, factory)
            models.assets.register_model("example-model", PLATFORM_SCOPE, model_dir)
            spec = ModelDeploymentSpec(
                deployment_id="example-deployment",
                scope=PLATFORM_SCOPE,
                service_id="model:example-deployment",
                model_id="example-model",
                engine="custom",
                executable="{python}",
                argv=("{python}", "-m", "server", "--model", "{model_path}"),
                cwd=root,
                python_environment_id="serve",
                gpu_devices=("0", "1"),
            )
            models.deployment_catalog.put_deployment(spec)
            usage = models.assets.model_usage("example-model")
            self.assertEqual(usage.deployment_ids, ("example-deployment",))
            self.assertEqual(models.assets.model_stats("example-model").directories, 1)
            config = models.assets.model_config("example-model")
            self.assertEqual(config.model_type, "example_model")
            self.assertEqual(config.quantization_bits, 4)
            started = models.deployment_runtime.start(models.deployment_runtime.generation("example-deployment"))
            self.assertEqual(started.runtime_state, ModelRuntimeState.RUNNING)
            self.assertEqual(models.deployment_catalog.deployment("example-deployment").desired_state, ModelDesiredState.RUNNING)
            self.assertIn(("CUDA_VISIBLE_DEVICES", "0,1"), factory.environments[-1])
            self.assertIn(str(model_dir), factory.contracts[-1].argv)
            self.assertEqual(models.deployment_runtime.status("example-deployment").pid, 1234)
            stopped = models.deployment_runtime.stop(models.deployment_runtime.generation("example-deployment"))
            self.assertEqual(stopped.runtime_state, ModelRuntimeState.STOPPED)

    def test_running_deployment_can_be_reconfigured_then_reconciled(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake"))
            model_dir = root / "external-model"
            model_dir.mkdir()
            factory = FakeFactory()
            models = build_models(directories, environments, factory)
            models.assets.register_model("example-model", PLATFORM_SCOPE, model_dir)
            base = ModelDeploymentSpec(
                deployment_id="example-deployment",
                scope=PLATFORM_SCOPE,
                service_id="model:example-deployment",
                model_id="example-model",
                engine="custom",
                executable="{python}",
                argv=("{python}", "-m", "server", "--port", "8000"),
                cwd=root,
                python_environment_id="serve",
            )
            models.deployment_catalog.put_deployment(base)
            models.deployment_runtime.start(models.deployment_runtime.generation("example-deployment"))
            updated = ModelDeploymentSpec(
                deployment_id="example-deployment",
                scope=PLATFORM_SCOPE,
                service_id="model:example-deployment",
                model_id="example-model",
                engine="custom",
                executable="{python}",
                argv=("{python}", "-m", "server", "--port", "9000"),
                cwd=root,
                python_environment_id="serve",
                desired_state=ModelDesiredState.RUNNING,
            )
            models.deployment_catalog.put_deployment(updated)
            self.assertEqual(models.deployment_runtime.status("example-deployment").runtime_state, ModelRuntimeState.UPDATE_PENDING)
            reconciled = models.fleet.reconcile()[0]
            self.assertEqual(reconciled.runtime_state, ModelRuntimeState.RUNNING)
            self.assertIn("9000", factory.contracts[-1].argv)

    def test_applied_snapshot_survives_mutable_model_and_environment_registry_changes(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake"))
            old_model = root / "old-model"; old_model.mkdir()
            new_model = root / "new-model"; new_model.mkdir()
            factory = FakeFactory()
            models = build_models(directories, environments, factory)
            models.assets.register_model("m", PLATFORM_SCOPE, old_model)
            models.deployment_catalog.put_deployment(ModelDeploymentSpec(
                deployment_id="d", service_id="model:d", model_id="m", engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}", argv=("{python}", "-m", "server", "{model_path}"), cwd=root,
                python_environment_id="serve",
            ))
            models.deployment_runtime.start(models.deployment_runtime.generation("d"))
            applied_contract = factory.contracts[-1]
            models.assets.register_model("m", PLATFORM_SCOPE, new_model)
            self.assertEqual(models.deployment_runtime.status("d").runtime_state, ModelRuntimeState.UPDATE_PENDING)
            environments.lifecycle.remove("serve")
            pending = models.deployment_runtime.status("d")
            self.assertEqual(pending.runtime_state, ModelRuntimeState.UPDATE_PENDING)
            self.assertTrue(pending.detail.startswith("desired-resource-missing:"))
            models.deployment_runtime.stop(models.deployment_runtime.generation("d"))
            self.assertEqual(factory.contracts[-1].digest(), applied_contract.digest())

    def test_large_model_asset_modes_cover_reference_copy_move_and_symlink(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            models = build_models(directories, environments, FakeFactory())
            ref = root / "ref"; ref.mkdir(); (ref / "w").write_text("x")
            copied = root / "copied-source"; copied.mkdir(); (copied / "w").write_text("y")
            moved = root / "moved-source"; moved.mkdir(); (moved / "w").write_text("z")
            linked = root / "linked-source"; linked.mkdir()
            self.assertEqual(models.assets.register_model("ref", PLATFORM_SCOPE, ref).path, ref.resolve())
            copy_asset = models.assets.register_model("copy", PLATFORM_SCOPE, copied, mode="copy")
            self.assertTrue((copy_asset.path / "w").exists())
            move_asset = models.assets.register_model("move", PLATFORM_SCOPE, moved, mode="move")
            self.assertFalse(moved.exists())
            self.assertTrue((move_asset.path / "w").exists())
            try:
                link_asset = models.assets.register_model("link", PLATFORM_SCOPE, linked, mode="symlink")
            except OSError as exc:
                if getattr(exc, "winerror", None) == 1314:
                    self.skipTest("Windows symlink privilege is unavailable")
                raise
            self.assertTrue(link_asset.path.is_symlink())
            models.assets.unregister_model(
                "link",
                delete_managed_files=True,
                gc=_closed_model_gc(models, "link"),
            )
            self.assertTrue(linked.exists())

    def test_gpu_conflicts_are_visible_but_do_not_block_management(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake"))
            model_dir = root / "model"; model_dir.mkdir()
            models = build_models(directories, environments, FakeFactory())
            models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
            for name in ("a", "b"):
                models.deployment_catalog.put_deployment(ModelDeploymentSpec(
                    deployment_id=name, service_id=f"model:{name}", model_id="m", engine="custom",
                scope=PLATFORM_SCOPE,
                    executable="{python}", argv=("{python}", "-m", "server"), cwd=root,
                    python_environment_id="serve", gpu_devices=("0",), desired_state=ModelDesiredState.RUNNING,
                ))
            conflicts = models.resources.gpu_conflicts()
            self.assertEqual(conflicts[0].gpu_device, "0")
            self.assertFalse(models.resources.gpu_runtime().available)
            self.assertEqual(conflicts[0].deployment_ids, ("a", "b"))
            self.assertEqual(models.deployment_logs.logs("a").stdout_path, Path("/tmp/stdout.log"))

    def test_model_config_view_is_best_effort_for_malformed_config(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            model_dir = root / "broken-model"; model_dir.mkdir()
            (model_dir / "config.json").write_text("{broken", encoding="utf-8")
            models = build_models(directories, environments, FakeFactory())
            models.assets.register_model("broken", PLATFORM_SCOPE, model_dir)
            summary = models.assets.model_config("broken")
            self.assertTrue(summary.detail.startswith("config-unreadable:"))

    def test_log_tail_and_gpu_process_binding_are_operator_read_models(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake"))
            model_dir = root / "model"; model_dir.mkdir()
            log_root = root / "captured"; log_root.mkdir()
            (log_root / "stdout.log").write_text("hello\nworld\n", encoding="utf-8")
            (log_root / "stderr.log").write_text("warning\n", encoding="utf-8")
            gpu = GpuRuntimeSnapshot(True, processes=(GpuProcessStatus(1234, "GPU-1", 2048, "python"),))
            models = build_models(directories, environments, FakeFactory(log_root), gpu_observer=FakeGpuObserver(gpu))
            models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
            models.deployment_catalog.put_deployment(ModelDeploymentSpec(
                deployment_id="d", service_id="model:d", model_id="m", engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}", argv=("{python}", "-m", "server"), cwd=root, python_environment_id="serve",
            ))
            models.deployment_runtime.start(models.deployment_runtime.generation("d"))
            tail = models.deployment_logs.tail_logs("d", stream="stdout", max_bytes=6)
            self.assertEqual(tail.text, "world\n")
            bindings = models.resources.gpu_process_bindings()
            self.assertEqual(bindings[0].deployment_id, "d")
            self.assertEqual(bindings[0].used_memory_mb, 2048)

    def test_huggingface_source_backend_is_optional_management_acquisition(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            storage = LocalModelAssetStorage(directories.layout)
            seen = {}

            class FakeCommandRunner:
                def run(self, argv, **kwargs):
                    seen["argv"] = tuple(argv)
                    seen["env"] = kwargs.get("environment")
                    destination = Path(argv[argv.index("--local-dir") + 1])
                    destination.mkdir(parents=True)
                    (destination / "config.json").write_text("{}", encoding="utf-8")
                    return LocalCommandResult(tuple(argv), 0, "", "")

            source = HuggingFaceCliModelSource(
                storage,
                cache_root=directories.layout.layout.cache / "huggingface",
                environment={"HF_ENDPOINT": "https://hf-mirror.example"},
                command_runner=FakeCommandRunner(),
            )
            asset_registry = ModelAssetRegistry(directories.layout)
            deployment_registry = ModelDeploymentRegistry(directories.layout)
            applied_store = AppliedModelDeploymentStore(directories.layout)
            factory = FakeFactory()
            catalog = ModelDeploymentCatalog(asset_registry, deployment_registry, environments.lifecycle)
            assets = ModelAssetManager(asset_registry, DeploymentModelAssetReferences(catalog), storage, (source,))
            materializer = ModelLaunchMaterializer(assets, environments.lifecycle)
            runtime = ModelDeploymentRuntime(applied_store, catalog, materializer, factory)
            fleet = ModelFleetRuntime(
                catalog,
                runtime,
                DurableModelAutoRecoveryAuthority(directories.layout),
            )
            logs = ModelDeploymentLogReader(applied_store, catalog, materializer, factory)
            resources = ModelResourceView(assets, catalog, fleet, FakeGpuObserver())
            controller = ModelDesiredStateController(
                fleet,
                FileModelControllerStateStore(directories.layout.layout.state / "model" / "deployments" / "controller.json"),
            )
            assignments = ModelAssignmentManager(InMemoryScopeRegistry())
            models = ModelAuthorities(assets, assignments, catalog, runtime, fleet, logs, resources, controller)
            with patch("noetrium_platform.capabilities.model.asset.providers.huggingface_cli.shutil.which", return_value="/usr/bin/hf"):
                asset = models.assets.fetch_model(
                    "example-model",
                    PLATFORM_SCOPE,
                    ModelSourceSpec("huggingface", "example-org/example-model", revision="main", max_workers=24),
                )
            self.assertEqual(asset.mode, ModelAssetMode.FETCHED)
            self.assertEqual(asset.origin.backend, "huggingface")
            self.assertEqual(asset.origin.revision, "main")
            self.assertNotIn("--cache-dir", seen["argv"])
            self.assertEqual(seen["argv"][seen["argv"].index("--max-workers") + 1], "24")
            self.assertEqual(seen["env"]["HF_HOME"], str(directories.layout.layout.cache / "huggingface"))
            self.assertEqual(seen["env"]["HF_ENDPOINT"], "https://hf-mirror.example")
            self.assertTrue((asset.path / "config.json").exists())
            models.assets.unregister_model(
                "example-model",
                delete_managed_files=True,
                gc=_closed_model_gc(models, "example-model"),
            )
            self.assertFalse(asset.path.exists())

    def test_gpu_runtime_observer_is_best_effort_and_parses_nvidia_smi(self):
        class FakeCommandRunner:
            def __init__(self): self.outputs = [
                "0, GPU-1, H100, 81920, 1024, 80896, 12\n",
                "123, GPU-1, 512, python\n",
            ]
            def run(self, argv, **kwargs):
                return LocalCommandResult(tuple(argv), 0, self.outputs.pop(0), "")

        observer = NvidiaSmiGpuRuntimeObserver(FakeCommandRunner())
        with patch("noetrium_platform.infrastructure.resources.compute.providers.nvidia_smi.shutil.which", return_value=None):
            self.assertFalse(observer.snapshot().available)
        observer = NvidiaSmiGpuRuntimeObserver(FakeCommandRunner())
        with patch("noetrium_platform.infrastructure.resources.compute.providers.nvidia_smi.shutil.which", return_value="/usr/bin/nvidia-smi"):
            snapshot = observer.snapshot()
        self.assertTrue(snapshot.available)
        self.assertEqual(snapshot.devices[0].memory_free_mb, 80896)
        self.assertEqual(snapshot.processes[0].pid, 123)

    def test_fleet_reconcile_isolates_missing_desired_resources(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("good", PLATFORM_SCOPE, backend="fake"))
            environments.lifecycle.create(PythonEnvironmentSpec("gone", PLATFORM_SCOPE, backend="fake"))
            model_dir = root / "model"; model_dir.mkdir()
            models = build_models(directories, environments, FakeFactory())
            models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
            for deployment_id, env_id in (("good", "good"), ("bad", "gone")):
                models.deployment_catalog.put_deployment(ModelDeploymentSpec(
                    deployment_id=deployment_id, service_id=f"model:{deployment_id}", model_id="m", engine="custom",
                scope=PLATFORM_SCOPE,
                    executable="{python}", argv=("{python}", "-m", "server"), cwd=root, python_environment_id=env_id,
                    desired_state=ModelDesiredState.RUNNING,
                ))
            environments.lifecycle.remove("gone")
            states = {value.deployment_id: value.runtime_state for value in models.fleet.reconcile()}
            self.assertEqual(states["good"], ModelRuntimeState.RUNNING)
            self.assertEqual(states["bad"], ModelRuntimeState.MISSING)

    def test_optional_engine_templates_do_not_constrain_generic_launch_contract(self):
        root = Path("/srv/research")
        s = sglang_deployment(
            deployment_id="sg",
            scope=PLATFORM_SCOPE,
            model_id="m",
            python_environment_id="e",
            cwd=root,
            port=30001,
            tensor_parallel=4,
        )
        v = vllm_deployment(
            deployment_id="vl",
            scope=PLATFORM_SCOPE,
            model_id="m",
            python_environment_id="e",
            cwd=root,
            port=8001,
            tensor_parallel=4,
            gpu_devices=("GPU-0", "GPU-1", "GPU-2", "GPU-3"),
            extra_args=(
                "--gpu-memory-utilization",
                "0.97",
                "--max-num-seqs",
                "64",
            ),
        )
        self.assertEqual(s.engine, "sglang")
        self.assertEqual(v.engine, "vllm")
        self.assertIn("--tp-size", s.argv)
        self.assertIn("--tensor-parallel-size", v.argv)
        self.assertEqual(
            v.argv[v.argv.index("--gpu-memory-utilization") + 1],
            "0.97",
        )
        self.assertEqual(v.argv[v.argv.index("--max-num-seqs") + 1], "64")
        self.assertEqual(
            v.gpu_devices,
            ("GPU-0", "GPU-1", "GPU-2", "GPU-3"),
        )

        dp = vllm_deployment(
            deployment_id="vl-dp",
            scope=PLATFORM_SCOPE,
            model_id="m",
            python_environment_id="e",
            cwd=root,
            port=8002,
            tensor_parallel=2,
            data_parallel=2,
            data_parallel_rpc_port=18002,
            gpu_devices=("GPU-0", "GPU-1", "GPU-2", "GPU-3"),
        )
        self.assertEqual(
            dp.argv[dp.argv.index("--data-parallel-size") + 1],
            "2",
        )
        self.assertEqual(
            dp.argv[dp.argv.index("--data-parallel-rpc-port") + 1],
            "18002",
        )
        with self.assertRaisesRegex(ValueError, "platform-owned"):
            vllm_deployment(
                deployment_id="vl-escape",
                scope=PLATFORM_SCOPE,
                model_id="m",
                python_environment_id="e",
                cwd=root,
                port=8003,
                tensor_parallel=1,
                gpu_devices=("GPU-0",),
                extra_args=("--device-ids=7",),
            )


    def test_gpu_advisory_and_resource_changes_are_desired_only(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("env-a", PLATFORM_SCOPE, backend="fake"))
            environments.lifecycle.create(PythonEnvironmentSpec("env-b", PLATFORM_SCOPE, backend="fake"))
            model_dir = root / "model"; model_dir.mkdir()
            gpu_snapshot = GpuRuntimeSnapshot(
                True,
                devices=(
                    GpuDeviceStatus("0", "GPU-0", "A100", 81920, 12000, 69920, 30),
                    GpuDeviceStatus("1", "GPU-1", "A100", 81920, 2000, 79920, 5),
                    GpuDeviceStatus("2", "GPU-2", "A100", 81920, 1000, 80920, 80),
                ),
            )
            factory = FakeFactory()
            models = build_models(directories, environments, factory, gpu_observer=FakeGpuObserver(gpu_snapshot))
            models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
            models.deployment_catalog.put_deployment(ModelDeploymentSpec(
                deployment_id="d", service_id="model:d", model_id="m", engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}", argv=("{python}", "-V"), cwd=root,
                python_environment_id="env-a", desired_state=ModelDesiredState.RUNNING,
            ))
            candidates = models.resources.gpu_candidates(count=2, min_free_memory_mb=60000, max_utilization_percent=50)
            self.assertEqual(tuple(device.index for device in candidates), ("1", "0"))
            updated = models.deployment_catalog.set_gpu_devices("d", ("1", "0", "1"))
            self.assertEqual(updated.gpu_devices, ("1", "0"))
            updated = models.deployment_catalog.set_python_environment("d", "env-b")
            self.assertEqual(updated.python_environment_id, "env-b")
            self.assertFalse(factory.runtime.live)


    def test_named_model_storage_pools_keep_large_assets_on_selected_volume(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            storage = LocalModelAssetStorage(directories.layout, additional_pools={"nvme": root / "nvme-models"})
            environments = build_environments(directories)
            asset_registry = ModelAssetRegistry(directories.layout)
            deployment_registry = ModelDeploymentRegistry(directories.layout)
            catalog = ModelDeploymentCatalog(asset_registry, deployment_registry, environments.lifecycle)
            assets = ModelAssetManager(asset_registry, DeploymentModelAssetReferences(catalog), storage, ())
            source = root / "weights"; source.mkdir(); (source / "model.safetensors").write_bytes(b"weights")
            asset = assets.register_model("fast", PLATFORM_SCOPE, source, mode="copy", storage_pool="nvme")
            self.assertEqual(asset.storage_pool, "nvme")
            self.assertEqual(asset.path.parent, (root / "nvme-models").resolve())
            pools = {pool.pool_id: pool for pool in assets.storage_pools()}
            self.assertEqual(set(pools), {"default", "nvme"})
            self.assertEqual(pools["nvme"].path, (root / "nvme-models").resolve())


    def test_tags_and_selectors_support_group_management_without_starting_services(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("serve-a", PLATFORM_SCOPE, backend="fake", tags=("gpu", "online")))
            environments.lifecycle.create(PythonEnvironmentSpec("serve-b", PLATFORM_SCOPE, backend="fake", tags=("gpu", "batch")))
            self.assertEqual(tuple(value.environment_id for value in environments.lifecycle.list(tags=("online",))), ("serve-a",))

            model_a = root / "model-a"; model_a.mkdir()
            model_b = root / "model-b"; model_b.mkdir()
            factory = FakeFactory()
            models = build_models(directories, environments, factory)
            models.assets.register_model("a", PLATFORM_SCOPE, model_a, family="example-family", tags=("large", "chat"))
            models.assets.register_model("b", PLATFORM_SCOPE, model_b, family="example-family", tags=("small",))
            self.assertEqual(tuple(value.model_id for value in models.assets.models(tags=("large",))), ("a",))
            self.assertEqual(len(models.assets.models(family="example-family")), 2)

            for deployment_id, env_id, tags in (
                ("chat-a", "serve-a", ("online", "chat")),
                ("batch-b", "serve-b", ("batch",)),
            ):
                models.deployment_catalog.put_deployment(ModelDeploymentSpec(
                    deployment_id=deployment_id, service_id=f"model:{deployment_id}",
                scope=PLATFORM_SCOPE,
                    model_id="a" if deployment_id == "chat-a" else "b", engine="custom",
                    executable="{python}", argv=("{python}", "-V"), cwd=root,
                    python_environment_id=env_id, tags=tags,
                ))
            selected = models.deployment_catalog.select(ModelDeploymentSelector(tags=("online",)))
            self.assertEqual(tuple(value.deployment_id for value in selected), ("chat-a",))
            desired = models.deployment_catalog.set_desired_state_selected(
                ModelDeploymentSelector(tags=("online",)), ModelDesiredState.RUNNING
            )
            self.assertEqual(desired[0].desired_state, ModelDesiredState.RUNNING)
            self.assertFalse(factory.runtime.live)


    def test_desired_state_controller_runs_multiple_cycles_and_persists_status(self):
        class Stop:
            def __init__(self):
                self.waits = 0
            def wait(self, timeout=None):
                self.waits += 1
                return False

        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            environments = build_environments(directories)
            environments.lifecycle.create(PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake"))
            model_dir = root / "model"; model_dir.mkdir()
            models = build_models(directories, environments, FakeFactory())
            models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
            models.deployment_catalog.put_deployment(ModelDeploymentSpec(
                deployment_id="d", service_id="model:d", model_id="m", engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}", argv=("{python}", "-V"), cwd=root,
                python_environment_id="serve",
                desired_state=ModelDesiredState.RUNNING,
            ))
            state = models.controller.run(interval_seconds=0.01, stop=Stop(), max_cycles=2)
            self.assertEqual(state.phase.value, "stopped")
            self.assertEqual(state.cycle_count, 2)
            self.assertIsNone(state.pid)
            self.assertEqual(state.last_cycle.statuses[0].runtime_state, ModelRuntimeState.RUNNING)
            persisted = models.controller.snapshot()
            self.assertEqual(persisted.cycle_count, 2)
            self.assertEqual(persisted.last_cycle.cycle_index, 2)


    def test_python_environment_export_and_clone_are_management_operations(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            runner = FakeCommandRunner()
            environments = build_environments(directories, runner)
            environments.lifecycle.create(PythonEnvironmentSpec("source", PLATFORM_SCOPE, backend="fake"))
            exported = environments.packages.export_requirements("source", root / "exports" / "source.txt")
            self.assertIn("pytest==9.0", exported.read_text("utf-8"))
            cloned = environments.packages.clone(
                "source",
                PythonEnvironmentSpec("clone", PLATFORM_SCOPE, backend="fake", tags=("copy",)),
            )
            self.assertEqual(cloned.source_environment_id, "source")
            self.assertEqual(cloned.environment.environment_id, "clone")
            self.assertEqual(cloned.requirements_count, 2)
            self.assertEqual(cloned.install_result.returncode, 0)
            self.assertFalse((directories.layout.layout.temp / "python-env-clone" / "clone.requirements.txt").exists())

    def test_directory_cleanup_rejects_replaced_entry_from_stale_plan(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            candidate = (
                directories.layout.root(ManagedDirectoryKind.CACHE)
                / "download.partial"
            )
            candidate.mkdir()
            (candidate / "old.bin").write_bytes(b"old")
            stale = directories.cleanup.clean_plan(ManagedDirectoryKind.CACHE)[0]

            # Model another generation replacing the pathname after planning.
            candidate.rename(candidate.with_name("old-generation"))
            candidate.mkdir()
            (candidate / "new.bin").write_bytes(b"new")

            with patch.object(
                directories.cleanup,
                "clean_plan",
                return_value=(stale,),
            ):
                removed = directories.cleanup.clean(ManagedDirectoryKind.CACHE)

            self.assertEqual(removed, ())
            self.assertEqual((candidate / "new.bin").read_bytes(), b"new")

    def test_directory_cleanup_plan_is_non_destructive_until_clean_is_requested(self):
        with TemporaryDirectory() as td:
            root = Path(td)
            directories = build_local_directory_authorities(layout(root))
            candidate = directories.layout.root(ManagedDirectoryKind.CACHE) / "download.partial"
            candidate.mkdir()
            (candidate / "chunk.bin").write_bytes(b"1234")
            plan = directories.cleanup.clean_plan(ManagedDirectoryKind.CACHE)
            self.assertEqual(plan[0].path, candidate)
            self.assertEqual(plan[0].bytes, 4)
            self.assertTrue(candidate.exists())
            removed = directories.cleanup.clean(ManagedDirectoryKind.CACHE)
            self.assertEqual(removed, (candidate,))
            self.assertFalse(candidate.exists())


if __name__ == "__main__":
    unittest.main()


def test_model_runtime_shutdown_preserves_desired_state_for_restart() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        models.deployment_catalog.put_deployment(
            ModelDeploymentSpec(
                deployment_id="d",
                service_id="model:d",
                model_id="m",
                engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}",
                argv=("{python}", "-m", "server"),
                cwd=root,
                python_environment_id="serve",
            )
        )

        models.deployment_runtime.start(models.deployment_runtime.generation("d"))
        assert (
            models.deployment_catalog.deployment("d").desired_state
            is ModelDesiredState.RUNNING
        )
        assert factory.runtime.live is True

        stopped = models.fleet.shutdown_all()[0]
        assert stopped.runtime_state is ModelRuntimeState.STOPPED
        assert (
            models.deployment_catalog.deployment("d").desired_state
            is ModelDesiredState.RUNNING
        )
        assert factory.runtime.live is False

        restarted = models.fleet.reconcile()[0]
        assert restarted.runtime_state is ModelRuntimeState.RUNNING
        assert factory.runtime.live is True



def test_model_replacement_keeps_old_applied_generation_when_physical_stop_is_unproven() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        original = ModelDeploymentSpec(
            deployment_id="d",
            service_id="model:d",
            model_id="m",
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server", "--port", "8000"),
            cwd=root,
            python_environment_id="serve",
        )
        models.deployment_catalog.put_deployment(original)
        models.deployment_runtime.start(models.deployment_runtime.generation("d"))
        assert factory.runtime.start_calls == 1
        assert factory.runtime.live

        models.deployment_catalog.put_deployment(
            ModelDeploymentSpec(
                deployment_id="d",
                service_id="model:d",
                model_id="m",
                engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}",
                argv=("{python}", "-m", "server", "--port", "9000"),
                cwd=root,
                python_environment_id="serve",
                desired_state=ModelDesiredState.RUNNING,
            )
        )
        factory.runtime.stop_succeeds = False

        try:
            models.deployment_runtime.start(models.deployment_runtime.generation("d"))
        except RuntimeError as exc:
            assert "did not stop before deployment replacement" in str(exc)
        else:
            raise AssertionError("replacement must fail closed while the old process is live")

        assert factory.runtime.live
        assert factory.runtime.start_calls == 1
        assert (
            models.deployment_runtime.status("d").runtime_state
            is ModelRuntimeState.UPDATE_PENDING
        )


def test_model_remove_and_restart_require_physical_stop_convergence() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        models.deployment_catalog.put_deployment(
            ModelDeploymentSpec(
                deployment_id="d",
                service_id="model:d",
                model_id="m",
                engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}",
                argv=("{python}", "-m", "server"),
                cwd=root,
                python_environment_id="serve",
            )
        )
        models.deployment_runtime.start(models.deployment_runtime.generation("d"))
        factory.runtime.stop_succeeds = False

        try:
            models.deployment_runtime.remove_deployment(models.deployment_runtime.generation("d"))
        except RuntimeError as exc:
            assert "physical generation did not stop" in str(exc)
        else:
            raise AssertionError("remove must retain catalog state while the process is live")

        assert models.deployment_catalog.deployment("d").deployment_id == "d"
        assert factory.runtime.live
        assert factory.runtime.start_calls == 1

        try:
            models.deployment_runtime.restart(models.deployment_runtime.generation("d"))
        except RuntimeError as exc:
            assert "prior physical generation did not stop" in str(exc)
        else:
            raise AssertionError("restart must not start a second physical generation")

        assert factory.runtime.live
        assert factory.runtime.start_calls == 1
        assert (
            models.deployment_catalog.deployment("d").desired_state
            is ModelDesiredState.STOPPED
        )


def test_stale_model_generation_cannot_stop_or_remove_replacement_process() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)

        base = ModelDeploymentSpec(
            deployment_id="d",
            service_id="model:d",
            model_id="m",
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server", "--port", "8000"),
            cwd=root,
            python_environment_id="serve",
        )
        models.deployment_catalog.put_deployment(base)
        models.deployment_runtime.start(
            models.deployment_runtime.generation("d")
        )
        stale_running_generation = models.deployment_runtime.generation("d")

        replacement = ModelDeploymentSpec(
            deployment_id="d",
            service_id="model:d",
            model_id="m",
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server", "--port", "9000"),
            cwd=root,
            python_environment_id="serve",
            desired_state=ModelDesiredState.RUNNING,
        )
        models.deployment_catalog.put_deployment(replacement)
        reconciled = models.fleet.reconcile()[0]
        self_running = models.deployment_runtime.status("d")
        assert reconciled.runtime_state is ModelRuntimeState.RUNNING
        assert self_running.runtime_state is ModelRuntimeState.RUNNING
        replacement_generation = models.deployment_runtime.generation("d")
        assert replacement_generation != stale_running_generation

        with pytest.raises(RuntimeError, match="stale model deployment generation"):
            models.deployment_runtime.shutdown(stale_running_generation)
        with pytest.raises(RuntimeError, match="stale model deployment generation"):
            models.deployment_runtime.remove_deployment(stale_running_generation)

        assert models.deployment_runtime.generation("d") == replacement_generation
        assert models.deployment_runtime.status("d").runtime_state is ModelRuntimeState.RUNNING


def test_model_remove_retries_after_physical_stop_without_retargeting_generation() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model-remove-retry"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        spec = ModelDeploymentSpec(
            deployment_id="remove-retry",
            service_id="model:remove-retry",
            model_id="m",
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server"),
            cwd=root,
            python_environment_id="serve",
        )
        models.deployment_catalog.put_deployment(spec)
        models.deployment_runtime.start(
            models.deployment_runtime.generation("remove-retry")
        )
        owned_generation = models.deployment_runtime.generation("remove-retry")

        real_remove = models.deployment_catalog.remove
        remove_calls = 0

        def fail_once(deployment_id: str) -> bool:
            nonlocal remove_calls
            remove_calls += 1
            if remove_calls == 1:
                raise OSError("simulated desired retirement write failure")
            return real_remove(deployment_id)

        models.deployment_catalog.remove = fail_once

        with pytest.raises(OSError, match="retirement write failure"):
            models.deployment_runtime.remove_deployment(owned_generation)

        assert factory.runtime.live is False
        assert models.deployment_runtime.status("remove-retry").runtime_state is ModelRuntimeState.STOPPED

        assert models.deployment_runtime.remove_deployment(owned_generation) is True
        assert models.deployment_runtime.remove_deployment(owned_generation) is True
        assert remove_calls == 2

        with pytest.raises(RuntimeError, match="retired and cannot be reused"):
            models.deployment_catalog.put_deployment(spec)


def test_model_deployment_retirement_purges_obsolete_process_tombstones() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model-retirement-tombstone-gc"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        spec = ModelDeploymentSpec(
            deployment_id="retirement-tombstone-gc",
            service_id="model:retirement-tombstone-gc",
            model_id="m",
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server"),
            cwd=root,
            python_environment_id="serve",
            desired_state=ModelDesiredState.RUNNING,
        )
        models.deployment_catalog.put_deployment(spec)
        models.deployment_runtime.start(
            models.deployment_runtime.generation(spec.deployment_id)
        )
        owned = models.deployment_runtime.generation(spec.deployment_id)
        store = models.deployment_runtime._applied_store
        applied = store.read(spec.deployment_id)
        assert applied is not None
        marker = store._cleared_path(spec.deployment_id, applied.runtime_digest)

        assert (
            models.deployment_runtime.shutdown(owned).runtime_state
            is ModelRuntimeState.STOPPED
        )
        assert marker.exists()

        assert models.deployment_runtime.remove_deployment(owned) is True
        assert not marker.exists()
        assert tuple(
            store._cleared_root.glob(
                f"{store._key(spec.deployment_id)}.*.json"
            )
        ) == ()

        assert models.deployment_runtime.remove_deployment(owned) is True
        assert tuple(
            store._cleared_root.glob(
                f"{store._key(spec.deployment_id)}.*.json"
            )
        ) == ()




def test_model_asset_lifecycle_fence_orders_deployment_before_retirement() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        models = build_models(directories, environments, FakeFactory())
        source = root / "model-race-deployment-first"
        source.mkdir()
        (source / "weights.bin").write_bytes(b"weights")
        asset = models.assets.register_model(
            "race-deployment-first",
            PLATFORM_SCOPE,
            source,
            mode="copy",
        )
        gc = _closed_model_gc(models, asset.model_id)
        spec = ModelDeploymentSpec(
            deployment_id="race-deployment-first",
            service_id="model:race-deployment-first",
            model_id=asset.model_id,
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server"),
            cwd=root,
            python_environment_id="serve",
        )

        desired = models.deployment_catalog._deployment_registry
        real_put = desired.put
        deployment_inside_fence = Event()
        release_deployment = Event()

        def blocked_put(value):
            deployment_inside_fence.set()
            assert release_deployment.wait(5.0)
            return real_put(value)

        desired.put = blocked_put
        deployment_errors: list[BaseException] = []
        gc_errors: list[BaseException] = []

        def publish_deployment() -> None:
            try:
                models.deployment_catalog.put_deployment(spec)
            except BaseException as exc:
                deployment_errors.append(exc)

        def retire_asset() -> None:
            try:
                models.assets.unregister_model(
                    asset.model_id,
                    delete_managed_files=True,
                    gc=gc,
                )
            except BaseException as exc:
                gc_errors.append(exc)

        deployment_thread = Thread(target=publish_deployment)
        deployment_thread.start()
        assert deployment_inside_fence.wait(5.0)

        gc_thread = Thread(target=retire_asset)
        gc_thread.start()
        release_deployment.set()
        deployment_thread.join(5.0)
        gc_thread.join(5.0)
        assert not deployment_thread.is_alive()
        assert not gc_thread.is_alive()

        assert deployment_errors == []
        assert len(gc_errors) == 1
        assert "still referenced by a deployment" in str(gc_errors[0])
        assert models.deployment_catalog.deployment(spec.deployment_id) == spec
        assert models.assets.model(asset.model_id) == asset
        assert asset.path.exists()


def test_model_asset_lifecycle_fence_orders_retirement_before_deployment() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        models = build_models(directories, environments, FakeFactory())
        source = root / "model-race-retirement-first"
        source.mkdir()
        (source / "weights.bin").write_bytes(b"weights")
        asset = models.assets.register_model(
            "race-retirement-first",
            PLATFORM_SCOPE,
            source,
            mode="copy",
        )
        gc = _closed_model_gc(models, asset.model_id)
        spec = ModelDeploymentSpec(
            deployment_id="race-retirement-first",
            service_id="model:race-retirement-first",
            model_id=asset.model_id,
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server"),
            cwd=root,
            python_environment_id="serve",
        )

        storage = models.assets._storage
        real_remove = storage.remove
        gc_inside_fence = Event()
        release_gc = Event()

        def blocked_remove(value):
            gc_inside_fence.set()
            assert release_gc.wait(5.0)
            return real_remove(value)

        storage.remove = blocked_remove
        gc_errors: list[BaseException] = []
        deployment_errors: list[BaseException] = []

        def retire_asset() -> None:
            try:
                models.assets.unregister_model(
                    asset.model_id,
                    delete_managed_files=True,
                    gc=gc,
                )
            except BaseException as exc:
                gc_errors.append(exc)

        def publish_deployment() -> None:
            try:
                models.deployment_catalog.put_deployment(spec)
            except BaseException as exc:
                deployment_errors.append(exc)

        gc_thread = Thread(target=retire_asset)
        gc_thread.start()
        assert gc_inside_fence.wait(5.0)

        deployment_thread = Thread(target=publish_deployment)
        deployment_thread.start()
        release_gc.set()
        gc_thread.join(5.0)
        deployment_thread.join(5.0)
        assert not gc_thread.is_alive()
        assert not deployment_thread.is_alive()

        assert gc_errors == []
        assert len(deployment_errors) == 1
        assert "retiring or retired" in str(deployment_errors[0])
        assert not asset.path.exists()
        with pytest.raises(FileNotFoundError):
            models.deployment_catalog.deployment(spec.deployment_id)

def test_model_asset_physical_gc_requires_complete_external_closure() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        models = build_models(directories, environments, FakeFactory())
        source = root / "source-gc-gate"
        source.mkdir()
        (source / "weights.bin").write_bytes(b"weights")
        asset = models.assets.register_model(
            "gc-gate",
            PLATFORM_SCOPE,
            source,
            mode="copy",
        )

        with pytest.raises(RuntimeError, match="typed model asset GC assessment"):
            models.assets.unregister_model(
                "gc-gate",
                delete_managed_files=True,
            )
        assert asset.path.exists()
        assert models.assets.model("gc-gate") == asset

        partial = models.assets.assess_model_gc(
            "gc-gate",
            closures=(
                DurableCarrierReferenceClosure(
                    DurableCarrierClosureAuthority.EXECUTION,
                    "4" * 64,
                    (),
                ),
            ),
        )
        assert not partial.eligible
        with pytest.raises(RuntimeError, match="complete execution, evidence, and recovery"):
            models.assets.unregister_model(
                "gc-gate",
                delete_managed_files=True,
                gc=partial,
            )
        assert asset.path.exists()
        assert models.assets.model("gc-gate") == asset


@pytest.mark.parametrize(
    ("authority", "reference_id"),
    (
        (DurableCarrierClosureAuthority.EXECUTION, "run-resumable"),
        (DurableCarrierClosureAuthority.EVIDENCE, "evidence-retained"),
        (DurableCarrierClosureAuthority.RECOVERY, "checkpoint-retained"),
    ),
)
def test_model_asset_physical_gc_blocks_retained_external_reference(
    authority: DurableCarrierClosureAuthority,
    reference_id: str,
) -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        models = build_models(directories, environments, FakeFactory())
        source = root / f"source-{authority.value}"
        source.mkdir()
        (source / "weights.bin").write_bytes(b"weights")
        asset = models.assets.register_model(
            f"gc-{authority.value}",
            PLATFORM_SCOPE,
            source,
            mode="copy",
        )
        model_id = asset.model_id
        closures = tuple(
            DurableCarrierReferenceClosure(
                current,
                str(index) * 64,
                (reference_id,) if current is authority else (),
            )
            for index, current in enumerate(
                (
                    DurableCarrierClosureAuthority.EVIDENCE,
                    DurableCarrierClosureAuthority.EXECUTION,
                    DurableCarrierClosureAuthority.RECOVERY,
                ),
                start=5,
            )
        )
        gc = models.assets.assess_model_gc(model_id, closures=closures)
        assert gc.closure_complete
        assert not gc.eligible
        with pytest.raises(RuntimeError, match="zero retained references"):
            models.assets.unregister_model(
                model_id,
                delete_managed_files=True,
                gc=gc,
            )
        assert asset.path.exists()
        assert models.assets.model(model_id) == asset


def test_model_asset_physical_gc_retry_requires_same_durable_proof() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        models = build_models(directories, environments, FakeFactory())
        source = root / "source-proof-retry"
        source.mkdir()
        (source / "weights.bin").write_bytes(b"weights")
        asset = models.assets.register_model(
            "gc-proof-retry",
            PLATFORM_SCOPE,
            source,
            mode="copy",
        )
        storage = models.assets._storage
        real_remove = storage.remove

        def fail_remove(_asset):
            raise OSError("simulated destructive GC interruption")

        storage.remove = fail_remove
        original = _closed_model_gc(models, asset.model_id)
        with pytest.raises(OSError, match="destructive GC interruption"):
            models.assets.unregister_model(
                asset.model_id,
                delete_managed_files=True,
                gc=original,
            )

        changed = models.assets.assess_model_gc(
            asset.model_id,
            closures=(
                DurableCarrierReferenceClosure(
                    DurableCarrierClosureAuthority.EVIDENCE,
                    "a" * 64,
                    (),
                ),
                DurableCarrierReferenceClosure(
                    DurableCarrierClosureAuthority.EXECUTION,
                    "b" * 64,
                    (),
                ),
                DurableCarrierReferenceClosure(
                    DurableCarrierClosureAuthority.RECOVERY,
                    "c" * 64,
                    (),
                ),
            ),
        )
        storage.remove = real_remove
        with pytest.raises(RuntimeError, match="GC proof changed across retirement retry"):
            models.assets.unregister_model(
                asset.model_id,
                delete_managed_files=True,
                gc=changed,
            )
        assert asset.path.exists()

        assert models.assets.unregister_model(
            asset.model_id,
            delete_managed_files=True,
            gc=original,
        )
        assert not asset.path.exists()

def test_model_asset_retirement_retries_managed_delete_with_durable_original_policy() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        models = build_models(directories, environments, FakeFactory())
        source = root / "source-delete-retry"
        source.mkdir()
        (source / "weights.bin").write_bytes(b"weights")
        asset = models.assets.register_model(
            "retire-delete",
            PLATFORM_SCOPE,
            source,
            mode="copy",
        )

        storage = models.assets._storage
        real_remove = storage.remove
        calls = 0

        def fail_once(value):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated managed model delete interruption")
            return real_remove(value)

        storage.remove = fail_once
        gc = _closed_model_gc(models, "retire-delete")
        with pytest.raises(OSError, match="delete interruption"):
            models.assets.unregister_model(
                "retire-delete",
                delete_managed_files=True,
                gc=gc,
            )

        assert asset.path.exists()
        with pytest.raises(RuntimeError, match="retiring or retired"):
            models.assets.model("retire-delete")

        # Recovery follows the durable first intent, not this caller's false.
        assert models.assets.unregister_model(
            "retire-delete",
            delete_managed_files=False,
            gc=gc,
        )
        assert calls == 2
        assert not asset.path.exists()
        assert models.assets.unregister_model("retire-delete")
        with pytest.raises(RuntimeError, match="retired and cannot be reused"):
            models.assets.register_model(
                "retire-delete",
                PLATFORM_SCOPE,
                source,
                mode="reference",
            )


def test_model_asset_logical_retirement_can_later_gc_only_with_closure_proof() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        models = build_models(directories, environments, FakeFactory())
        source = root / "source-keep-retry"
        source.mkdir()
        (source / "weights.bin").write_bytes(b"weights")
        asset = models.assets.register_model(
            "retire-keep",
            PLATFORM_SCOPE,
            source,
            mode="copy",
        )

        registry = models.assets._asset_registry
        real_finish = registry.finish_retirement
        calls = 0

        def fail_once(value):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise OSError("simulated registry retirement finish failure")
            return real_finish(value)

        registry.finish_retirement = fail_once
        with pytest.raises(OSError, match="finish failure"):
            models.assets.unregister_model(
                "retire-keep",
                delete_managed_files=False,
            )

        assert asset.path.exists()
        with pytest.raises(RuntimeError, match="typed model asset GC assessment"):
            models.assets.unregister_model(
                "retire-keep",
                delete_managed_files=True,
            )
        assert calls == 1
        assert asset.path.exists()

        # Logical retirement retains exact managed-path metadata while fencing
        # new work. A later physical GC must bind a fresh complete closure proof
        # to that same asset digest before bytes can be removed.
        gc = _closed_model_gc(models, "retire-keep")
        assert models.assets.unregister_model(
            "retire-keep",
            delete_managed_files=True,
            gc=gc,
        )
        assert calls == 2
        assert not asset.path.exists()
        with pytest.raises(RuntimeError, match="retired and cannot be reused"):
            models.assets.register_model(
                "retire-keep",
                PLATFORM_SCOPE,
                source,
                mode="reference",
            )


def test_stale_same_config_generation_cannot_stop_restarted_process() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model-same-config-restart"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        spec = ModelDeploymentSpec(
            deployment_id="same-config",
            service_id="model:same-config",
            model_id="m",
            engine="custom",
            scope=PLATFORM_SCOPE,
            executable="{python}",
            argv=("{python}", "-m", "server"),
            cwd=root,
            python_environment_id="serve",
            desired_state=ModelDesiredState.RUNNING,
        )
        models.deployment_catalog.put_deployment(spec)

        first = models.deployment_runtime.start(
            models.deployment_runtime.generation("same-config")
        )
        assert first.runtime_state is ModelRuntimeState.RUNNING
        stale = models.deployment_runtime.generation("same-config")
        first_process = factory.runtime.process
        assert first_process is not None

        stopped = models.deployment_runtime.shutdown(stale)
        assert stopped.runtime_state is ModelRuntimeState.STOPPED
        restarted = models.fleet.reconcile()[0]
        assert restarted.runtime_state is ModelRuntimeState.RUNNING
        current = models.deployment_runtime.generation("same-config")
        second_process = factory.runtime.process
        assert second_process is not None
        assert second_process != first_process
        assert current != stale

        with pytest.raises(
            RuntimeError,
            match="stale model deployment generation",
        ):
            models.deployment_runtime.shutdown(stale)

        assert factory.runtime.live
        assert factory.runtime.process == second_process
        assert models.deployment_runtime.generation("same-config") == current


def test_model_stop_refuses_unowned_process_replacement() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model-process-drift"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        models.deployment_catalog.put_deployment(
            ModelDeploymentSpec(
                deployment_id="process-drift",
                service_id="model:process-drift",
                model_id="m",
                engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}",
                argv=("{python}", "-m", "server"),
                cwd=root,
                python_environment_id="serve",
            )
        )
        models.deployment_runtime.start(
            models.deployment_runtime.generation("process-drift")
        )
        owned = models.deployment_runtime.generation("process-drift")
        replacement = ServiceProcessIdentity(9999, "start:replacement")
        factory.runtime.process = replacement
        factory.runtime.live = True

        assert (
            models.deployment_runtime.status("process-drift").runtime_state
            is ModelRuntimeState.DRIFTED
        )
        with pytest.raises(
            RuntimeError,
            match="process generation drifted before physical stop",
        ):
            models.deployment_runtime.shutdown(owned)

        assert factory.runtime.live
        assert factory.runtime.process == replacement



def test_applied_clear_tombstone_survives_delete_commit_caller_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    import noetrium_platform.capabilities.model.deployment.runtime.applied_store as applied_store_module

    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model-clear-crash"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        models.deployment_catalog.put_deployment(
            ModelDeploymentSpec(
                deployment_id="clear-crash",
                service_id="model:clear-crash",
                model_id="m",
                engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}",
                argv=("{python}", "-m", "server"),
                cwd=root,
                python_environment_id="serve",
                desired_state=ModelDesiredState.RUNNING,
            )
        )
        models.deployment_runtime.start(
            models.deployment_runtime.generation("clear-crash")
        )
        generation = models.deployment_runtime.generation("clear-crash")
        store = models.deployment_runtime._applied_store
        applied = store.read("clear-crash")
        assert applied is not None
        active_path = store._path("clear-crash")
        active_bytes = active_path.read_bytes()
        marker_path = store._cleared_path(
            "clear-crash",
            applied.runtime_digest,
        )

        real_durable_unlink = applied_store_module.durable_unlink
        injected = False

        def delete_then_report_uncertain(path):
            nonlocal injected
            if path == active_path and not injected:
                injected = True
                path.unlink()
                raise OSError(
                    "simulated applied delete committed before durability acknowledgement"
                )
            return real_durable_unlink(path)

        monkeypatch.setattr(
            applied_store_module,
            "durable_unlink",
            delete_then_report_uncertain,
        )
        with pytest.raises(OSError, match="durability acknowledgement"):
            models.deployment_runtime.shutdown(generation)

        assert not factory.runtime.live
        assert marker_path.exists()
        assert store.read("clear-crash") is None

        # Model a reboot where the un-fsynced directory deletion rolls back and
        # the pre-clear active pathname becomes visible again.
        active_path.write_bytes(active_bytes)
        reopened = AppliedModelDeploymentStore(directories.layout)
        assert reopened.read("clear-crash") is None

        monkeypatch.setattr(
            applied_store_module,
            "durable_unlink",
            real_durable_unlink,
        )
        assert reopened.reconcile_cleared() == ("clear-crash",)
        assert not active_path.exists()
        assert marker_path.exists()


def test_cleared_applied_process_generation_cannot_be_resurrected() -> None:
    with TemporaryDirectory() as td:
        root = Path(td)
        directories = build_local_directory_authorities(layout(root))
        environments = build_environments(directories)
        environments.lifecycle.create(
            PythonEnvironmentSpec("serve", PLATFORM_SCOPE, backend="fake")
        )
        model_dir = root / "model-no-resurrection"
        model_dir.mkdir()
        factory = FakeFactory()
        models = build_models(directories, environments, factory)
        models.assets.register_model("m", PLATFORM_SCOPE, model_dir)
        models.deployment_catalog.put_deployment(
            ModelDeploymentSpec(
                deployment_id="no-resurrection",
                service_id="model:no-resurrection",
                model_id="m",
                engine="custom",
                scope=PLATFORM_SCOPE,
                executable="{python}",
                argv=("{python}", "-m", "server"),
                cwd=root,
                python_environment_id="serve",
                desired_state=ModelDesiredState.RUNNING,
            )
        )
        models.deployment_runtime.start(
            models.deployment_runtime.generation("no-resurrection")
        )
        store = models.deployment_runtime._applied_store
        old_applied = store.read("no-resurrection")
        assert old_applied is not None
        owned = models.deployment_runtime.generation("no-resurrection")
        assert (
            models.deployment_runtime.shutdown(owned).runtime_state
            is ModelRuntimeState.STOPPED
        )

        with pytest.raises(
            RuntimeError,
            match="cannot be resurrected",
        ):
            store.put(old_applied)

        assert store.read("no-resurrection") is None

        # A same-config restart gets a distinct OS process identity and is a new
        # applied runtime generation, so it remains admissible.
        restarted = models.fleet.reconcile()[0]
        assert restarted.runtime_state is ModelRuntimeState.RUNNING
        assert models.deployment_runtime.generation("no-resurrection") != owned
