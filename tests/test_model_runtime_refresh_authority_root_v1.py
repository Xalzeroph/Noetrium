from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.composition import model_runtime_refresh
from noetrium_platform.composition.model_runtime_bootstrap import RequiredModelRuntime


def test_refresh_materializes_missing_authority_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    authority_root = tmp_path / "state" / "authorities"
    project_root = tmp_path / "project"
    project_root.mkdir()

    def bootstrap(**kwargs):
        assert kwargs["authority_root"] == authority_root
        assert authority_root.is_dir()
        return "bootstrap-receipt"

    monkeypatch.setattr(
        model_runtime_refresh,
        "bootstrap_required_qualified_model_runtime",
        bootstrap,
    )

    receipts = model_runtime_refresh.refresh_required_qualified_model_runtimes(
        authority_root=authority_root,
        project_root=project_root,
        required_models=(RequiredModelRuntime(model_id="qwen3-8b", role="agent"),),
        assets=None,
        compute_scheduler=None,
        model_resources=None,
        state_root=tmp_path / "model",
        model_replica_pool=object(),
        deployment_runtime=None,
        compute_inventory=None,
        execution_pool=None,
    )

    assert receipts == ("bootstrap-receipt",)
    assert authority_root.is_dir()


def test_refresh_rejects_symlink_authority_root(
    tmp_path: Path,
) -> None:
    real_root = tmp_path / "real"
    real_root.mkdir()
    authority_root = tmp_path / "authorities"
    authority_root.symlink_to(real_root, target_is_directory=True)
    project_root = tmp_path / "project"
    project_root.mkdir()

    with pytest.raises(RuntimeError, match="must be a real directory"):
        model_runtime_refresh.refresh_required_qualified_model_runtimes(
            authority_root=authority_root,
            project_root=project_root,
            required_models=(RequiredModelRuntime(model_id="qwen3-8b", role="agent"),),
            assets=None,
            compute_scheduler=None,
            model_resources=None,
            state_root=tmp_path / "model",
            model_replica_pool=object(),
            deployment_runtime=None,
            compute_inventory=None,
            execution_pool=None,
        )
