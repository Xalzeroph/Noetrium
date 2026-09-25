from __future__ import annotations

from pathlib import Path

from noetrium_platform.infrastructure.lifecycle.host.api import OperatingSystemFamily
from noetrium_platform.composition.platform_meta import build_in_memory_platform_meta
from noetrium_platform.infrastructure.lifecycle.host.composition import compose_local_host
from noetrium_platform.foundation.scope.path.api import (
    PathFlavor,
    is_absolute_target_path,
    require_absolute_target_path,
)
from noetrium_platform.foundation.scope.path.composition import build_target_path_resolver


def test_target_path_contract_accepts_both_remote_path_flavors() -> None:
    assert is_absolute_target_path("/srv/research")
    assert is_absolute_target_path(r"C:\research")
    assert not is_absolute_target_path("relative/research")
    assert require_absolute_target_path("/srv/research", field="cwd") == "/srv/research"


def test_target_path_resolver_keeps_explicit_flavor() -> None:
    resolver = build_target_path_resolver()
    assert resolver.normalize("/srv/../data", flavor=PathFlavor.POSIX) == "/data"
    assert resolver.normalize(r"C:\srv\..\data", flavor=PathFlavor.WINDOWS) == r"C:\data"


def test_local_os_route_exposes_one_host_identity_and_conventions() -> None:
    meta = build_in_memory_platform_meta()
    route = compose_local_host(planner=meta.capability_composition).operating_system
    assert route.identity.family in set(OperatingSystemFamily)
    assert route.temporary_root().is_absolute()
    assert route.null_device()
