from pathlib import Path

from noetrium_platform.composition.experiment_runtime import build_experiment_runtime_components
from noetrium_platform.foundation.kernel.kernel import DirectoryMachineJournal, DirectoryMachineSnapshotStore
from tests_support import EmptyWorkflowSurfaceFactory, NoOpTrialProtocol


def test_state_root_wires_durable_experiment_authorities(tmp_path: Path) -> None:
    components = build_experiment_runtime_components(
        participant_adapters=(),
        trial_protocol=NoOpTrialProtocol(),
        workflow_surface_factories=(EmptyWorkflowSurfaceFactory(),),
        state_root=tmp_path,
    )

    run_runtime = components.run_runtime
    assert isinstance(run_runtime._machine_journal, DirectoryMachineJournal)
    assert isinstance(run_runtime._machine_snapshot_store, DirectoryMachineSnapshotStore)
    assert (tmp_path / "machine-journal").exists()
    assert (tmp_path / "machine-snapshots").exists()
    assert (tmp_path / "run-checkpoints").exists()
