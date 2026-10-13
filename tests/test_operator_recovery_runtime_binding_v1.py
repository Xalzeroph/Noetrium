from pathlib import Path
import json
from types import SimpleNamespace
import pytest
from tests.test_operator_paper_lifecycle_v1 import recorded
from tests.test_unified_operator_entrypoint_v1 import (
    platform,
    git_repository,
    GitRunner,
)
from noetrium_platform.composition.operator.cli_context import (
    execution_record,
    observed_source_revision,
    recovery_runtime_binding,
)
from noetrium_platform.composition.operator.wiring import entrypoint as cli


def recovery_binding(tmp_path):
    ws, original, roots, row = recorded(tmp_path)
    runtime = platform(tmp_path / "recovery-runtime")
    git_repository(runtime)
    result = GitRunner().run(("git", "-C", str(runtime), "checkout", "--detach"))
    assert result.returncode == 0
    revision = observed_source_revision(runtime)
    note = {
        "data_root": row["data_root"],
        "original_platform_root": row["platform_root"],
        "original_project_roots": row["project_roots"],
        "runtime_root": str(runtime),
        "runtime_revision": revision,
    }
    path = Path(row["data_root"]) / "RUNTIME_RECOVERY.json"
    path.write_text(json.dumps(note))
    return row, runtime, path, note


def test_lifecycle_uses_pinned_recovery_runtime_and_retains_original_state(tmp_path):
    row, runtime, path, note = recovery_binding(tmp_path)
    original = dict(row)
    calls = []

    class Runner:
        def run(self, argv, **kwargs):
            calls.append((argv, kwargs))
            return SimpleNamespace(returncode=0, stdout="", stderr="")

    assert cli._backend(row, ["inspect"], [], Runner()) == 0
    argv, kwargs = calls[0]
    assert argv[0] == str(runtime / "deploy/noetrium")
    assert kwargs["cwd"] == runtime
    assert kwargs["environment"]["NOETRIUM_DATA_ROOT"] == row["data_root"]
    assert all(root in argv for root in row["project_roots"])
    assert row == original


def test_mismatched_recovery_run_is_rejected_before_execution(tmp_path):
    row, runtime, path, note = recovery_binding(tmp_path)
    note["data_root"] = "/some/other/run"
    path.write_text(json.dumps(note))
    with pytest.raises(ValueError, match="another execution"):
        execution_record(row)


def test_runtime_commit_drift_is_rejected(tmp_path):
    row, runtime, path, note = recovery_binding(tmp_path)
    note["runtime_revision"] = "f" * 40
    path.write_text(json.dumps(note))
    with pytest.raises(ValueError, match="pinned detached commit"):
        execution_record(row)


def test_runtime_binding_symlink_is_rejected(tmp_path):
    row, runtime, path, note = recovery_binding(tmp_path)
    saved = path.with_suffix(".saved")
    path.rename(saved)
    path.symlink_to(saved)
    with pytest.raises(ValueError, match="symlink"):
        recovery_runtime_binding(row)


def test_status_reports_actual_runtime_without_starting_providers(
    tmp_path, monkeypatch, capsys
):
    row, runtime, path, note = recovery_binding(tmp_path)
    monkeypatch.setattr(
        cli, "_command_runner", lambda: pytest.fail("status started providers")
    )
    assert cli._show_record(row) == 0
    assert "Execution runtime: " + str(runtime) in capsys.readouterr().out
