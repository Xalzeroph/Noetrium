from __future__ import annotations

from pathlib import Path

import pytest

from noetrium_platform.infrastructure.lifecycle.session.runtime import (
    ControllerEnvironmentFileError,
    load_controller_environment,
)


def test_controller_environment_loader_is_literal_and_canonical(tmp_path: Path) -> None:
    path = tmp_path / "controller.env"
    path.write_text("export ZED=two\nALPHA='one value'\n", encoding="utf-8")
    assert load_controller_environment(path) == (("ALPHA", "one value"), ("ZED", "two"))


def test_controller_environment_loader_rejects_duplicate_keys(tmp_path: Path) -> None:
    path = tmp_path / "controller.env"
    path.write_text("ALPHA=one\nALPHA=two\n", encoding="utf-8")
    with pytest.raises(ControllerEnvironmentFileError):
        load_controller_environment(path)
