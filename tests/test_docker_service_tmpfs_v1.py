from pathlib import Path

import pytest

from noetrium_platform.composition.docker_service_process_backend import (
    DockerServiceBindMount,
    DockerServiceProcessConfiguration,
    DockerServiceTmpfsMount,
)
from noetrium_platform.foundation.governance.api import PLATFORM_SCOPE


def test_tmpfs_mount_encodes_bounded_ephemeral_runtime_storage():
    row = DockerServiceTmpfsMount(Path("/tmp"), 4 * 1024 ** 3, executable=True)
    assert row.docker_option == (
        "/tmp:rw,exec,nosuid,nodev,size=4294967296,mode=1777"
    )


def test_tmpfs_policy_is_part_of_service_configuration_identity():
    base = DockerServiceProcessConfiguration(
        image_digest="a" * 64, holder_scope=PLATFORM_SCOPE
    )
    bounded = DockerServiceProcessConfiguration(
        image_digest="a" * 64,
        holder_scope=PLATFORM_SCOPE,
        tmpfs_mounts=(DockerServiceTmpfsMount(Path("/tmp"), 4 * 1024 ** 3),),
    )
    assert base.digest != bounded.digest


def test_tmpfs_target_cannot_shadow_bind_mount(tmp_path: Path):
    with pytest.raises(ValueError, match="conflicts with bind target"):
        DockerServiceProcessConfiguration(
            image_digest="a" * 64,
            holder_scope=PLATFORM_SCOPE,
            mounts=(DockerServiceBindMount(tmp_path, Path("/tmp")),),
            tmpfs_mounts=(DockerServiceTmpfsMount(Path("/tmp"), 1024),),
        )


def test_model_runtime_declares_ephemeral_tmpfs_policy():
    text = Path("noetrium_platform/composition/model_management.py").read_text(
        encoding="utf-8"
    )
    assert 'DockerServiceTmpfsMount(' in text
    assert 'Path("/tmp")' in text
    assert '4 * 1024 ** 3' in text
    assert 'executable=True' in text
