from __future__ import annotations

import pytest

from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerProfileCatalogError
from noetrium_platform.infrastructure.lifecycle.server.identity.providers import build_server_profile_catalog


def test_profile_catalog_projects_explicit_membership_without_cross_server_values() -> None:
    values = {
        "PATH": "/usr/bin",
        "RP_SERVER_CATALOG_IDS": "server-a,lab-02",
        "RP_SERVER_SERVER_A_HOST": "sem.example",
        "RP_SERVER_SERVER_A_PORT": "60320",
        "RP_SERVER_SERVER_A_USER": "ubuntu",
        "RP_SERVER_LAB_02_HOST": "lab.example",
        "RP_SERVER_LAB_02_PORT": "22",
        "RP_SERVER_LAB_02_USER": "runner",
    }
    catalog = build_server_profile_catalog(values, source="test-profile")

    assert catalog.server_ids == ("server-a", "lab-02")
    selected = catalog.environment_for("server-a")
    assert selected["PATH"] == "/usr/bin"
    assert selected["RP_SERVER_SERVER_A_HOST"] == "sem.example"
    assert "RP_SERVER_LAB_02_HOST" not in selected


def test_profile_catalog_reports_incomplete_identity_before_network() -> None:
    catalog = build_server_profile_catalog(
        {
            "RP_SERVER_CATALOG_IDS": "server-a",
            "RP_SERVER_SERVER_A_HOST": "sem.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
        }
    )

    entry = catalog.entry("server-a")
    assert entry.missing_identity_fields == ("USER",)
    assert not entry.composition_ready


def test_profile_catalog_reports_runtime_schema_gaps_before_network() -> None:
    catalog = build_server_profile_catalog(
        {
            "RP_SERVER_CATALOG_IDS": "server-a",
            "RP_SERVER_SERVER_A_HOST": "sem.example",
            "RP_SERVER_SERVER_A_PORT": "60320",
            "RP_SERVER_SERVER_A_USER": "ubuntu",
            "RP_SERVER_SERVER_A_PLATFORM_ROOT": "/data/noetrium",
        }
    )

    entry = catalog.entry("server-a")
    assert entry.missing_identity_fields == ()
    assert entry.missing_runtime_fields[0] == "OPERATOR_CWD"
    assert "PLATFORM_ROOT" not in entry.missing_runtime_fields
    assert entry.missing_profile_fields == entry.missing_runtime_fields
    assert not entry.composition_ready


def test_profile_catalog_marks_a_complete_runtime_profile_ready() -> None:
    fields = {
        "HOST": "sem.example",
        "PORT": "60320",
        "USER": "ubuntu",
        "PLATFORM_ROOT": "/data/noetrium",
        "OPERATOR_CWD": "/data/noetrium",
        "REPOSITORY_ROOT": "/data/noetrium/repositories",
        "OPERATOR_SHELL": "/usr/bin/bash",
        "OPERATOR_SHELL_ARGS": "-il",
        "REMOTE_ENV": "/usr/bin/env",
        "SHA256SUM": "/usr/bin/sha256sum",
        "PYTHON": "/data/env/bin/python",
        "PYTHON_SHA256": "a" * 64,
        "PYTHON_PACKAGES_SHA256": "b" * 64,
        "NODE": "/data/node/bin/node",
        "NODE_SHA256": "c" * 64,
        "JAVA": "/data/java/bin/java",
        "JAVA_SHA256": "d" * 64,
        "PLATFORM_MANAGE": "/data/env/bin/noetrium-manage",
        "PLATFORM_MANAGE_SHA256": "e" * 64,
        "TMUX": "/usr/local/bin/tmux",
        "TMUX_SHA256": "f" * 64,
        "TMUX_SERVER_LABEL": "noetrium",
        "TMUX_CONFIG": "/dev/null",
        "TMUX_SOCKET_DIRECTORY": "/tmp",
        "SESSION_NAME": "noetrium-shell",
        "LOCAL_BINDING_ROOT": "/tmp/noetrium-state",
        "REMOTE_HOME": "/data/users/ubuntu",
        "REMOTE_PATH": "/data/env/bin:/usr/bin:/bin",
        "TERM": "xterm-256color",
    }
    values = {"RP_SERVER_CATALOG_IDS": "server-a"}
    values.update({f"RP_SERVER_SERVER_A_{key}": value for key, value in fields.items()})

    entry = build_server_profile_catalog(values, source="complete-test").entry("server-a")

    assert entry.missing_profile_fields == ()
    assert entry.composition_ready


def test_profile_catalog_rejects_undeclared_server_namespace() -> None:
    with pytest.raises(ServerProfileCatalogError, match="outside declared catalog membership"):
        build_server_profile_catalog(
            {
                "RP_SERVER_CATALOG_IDS": "server-a",
                "RP_SERVER_SERVER_A_HOST": "sem.example",
                "RP_SERVER_SERVER_A_PORT": "60320",
                "RP_SERVER_SERVER_A_USER": "ubuntu",
                "RP_SERVER_OTHER_HOST": "other.example",
            }
        )


def test_profile_catalog_requires_explicit_membership() -> None:
    with pytest.raises(ServerProfileCatalogError, match="RP_SERVER_CATALOG_IDS"):
        build_server_profile_catalog(
            {
                "RP_SERVER_SERVER_A_HOST": "sem.example",
                "RP_SERVER_SERVER_A_PORT": "60320",
                "RP_SERVER_SERVER_A_USER": "ubuntu",
            }
        )


def test_profile_catalog_rejects_normalized_namespace_collision() -> None:
    with pytest.raises(ServerProfileCatalogError, match="overlapping environment namespaces"):
        build_server_profile_catalog(
            {
                "RP_SERVER_CATALOG_IDS": "server-a,server_a",
            }
        )


def test_profile_catalog_rejects_nested_namespace_prefixes() -> None:
    with pytest.raises(ServerProfileCatalogError, match="overlapping environment namespaces"):
        build_server_profile_catalog(
            {
                "RP_SERVER_CATALOG_IDS": "a,a_b",
            }
        )
