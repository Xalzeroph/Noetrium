from __future__ import annotations

import pytest

from noetrium_platform.composition.docker_service_process_backend import (
    _docker_gpu_device_request,
)


def test_multi_gpu_request_is_one_quoted_docker_csv_field() -> None:
    assert _docker_gpu_device_request(("GPU-a", "GPU-b")) == '"device=GPU-a,GPU-b"'


def test_single_gpu_request_uses_same_canonical_encoding() -> None:
    assert _docker_gpu_device_request(("GPU-a",)) == '"device=GPU-a"'


def test_gpu_request_rejects_empty_identity_set() -> None:
    with pytest.raises(ValueError, match="non-empty device identities"):
        _docker_gpu_device_request(())
