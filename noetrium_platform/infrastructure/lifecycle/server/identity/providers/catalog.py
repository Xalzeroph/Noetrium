from __future__ import annotations

from collections.abc import Mapping
import re

from ..api import (
    ServerProfileCatalog,
    ServerProfileCatalogEntry,
    ServerProfileCatalogError,
    server_environment_prefix,
)


_CATALOG_IDS_KEY = "RP_SERVER_CATALOG_IDS"
_PROFILE_FILE_KEY = "RP_SERVER_PROFILE_FILE"
_IDENTITY_FIELDS = ("HOST", "PORT", "USER")
# These are the fields consumed by ServerRemoteProfile. Keeping the schema at
# the catalog boundary lets offline diagnostics report all missing data before
# any adapter attempts network I/O. RELEASE_ROOT has a deliberate default.
_RUNTIME_FIELDS = (
    "PLATFORM_ROOT",
    "OPERATOR_CWD",
    "REPOSITORY_ROOT",
    "OPERATOR_SHELL",
    "OPERATOR_SHELL_ARGS",
    "REMOTE_ENV",
    "SHA256SUM",
    "PYTHON",
    "PYTHON_SHA256",
    "PYTHON_PACKAGES_SHA256",
    "NODE",
    "NODE_SHA256",
    "JAVA",
    "JAVA_SHA256",
    "PLATFORM_MANAGE",
    "PLATFORM_MANAGE_SHA256",
    "TMUX",
    "TMUX_SHA256",
    "TMUX_SERVER_LABEL",
    "TMUX_CONFIG",
    "TMUX_SOCKET_DIRECTORY",
    "SESSION_NAME",
    "LOCAL_BINDING_ROOT",
    "REMOTE_HOME",
    "REMOTE_PATH",
    "TERM",
)
_SERVER_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
_TRIE_TERMINAL = "\0"


def _declared_prefix_trie(prefixes: Mapping[str, str]) -> dict[str, object]:
    """Build a prefix-free namespace index for one declared server catalog."""

    root: dict[str, object] = {}
    for server_id, prefix in prefixes.items():
        token = prefix + "_"
        node = root
        for character in token:
            if _TRIE_TERMINAL in node:
                raise ServerProfileCatalogError(
                    f"server ids create overlapping environment namespaces: {server_id}"
                )
            child = node.setdefault(character, {})
            if not isinstance(child, dict):
                raise ServerProfileCatalogError("server profile namespace index is invalid")
            node = child
        if _TRIE_TERMINAL in node or node:
            raise ServerProfileCatalogError(
                f"server ids create overlapping environment namespaces: {server_id}"
            )
        node[_TRIE_TERMINAL] = server_id
    return root


def _declared_server_for_key(trie: dict[str, object], key: str) -> str | None:
    node = trie
    for character in key:
        child = node.get(character)
        if not isinstance(child, dict):
            return None
        node = child
        server_id = node.get(_TRIE_TERMINAL)
        if isinstance(server_id, str):
            return server_id
    return None


def _missing_profile_fields(
    environ: Mapping[str, str], prefix: str, fields: tuple[str, ...]
) -> tuple[str, ...]:
    return tuple(
        field
        for field in fields
        if not str(environ.get(f"{prefix}_{field}", "")).strip()
    )


def build_server_profile_catalog(
    environ: Mapping[str, str],
    *,
    source: str = "environment",
) -> ServerProfileCatalog:
    """Build the one immutable membership projection for a server profile.

    Membership is explicit.  Inferring ``server-a`` from ``SERVER_A``
    would make underscores and hyphens ambiguous and would turn a typo into a
    different host.  Every ``RP_SERVER_<ID>_*`` key must belong to a declared
    id, and connection/runtime fields are checked before any adapter can
    attempt network I/O. Remote existence remains the health system's job.
    """

    raw_ids = str(environ.get(_CATALOG_IDS_KEY, "")).strip()
    if not raw_ids:
        raise ServerProfileCatalogError(
            f"{_CATALOG_IDS_KEY} is required; declare comma-separated logical server ids"
        )
    server_ids = tuple(part.strip() for part in raw_ids.split(","))
    if any(not _SERVER_ID_RE.fullmatch(server_id) for server_id in server_ids):
        raise ServerProfileCatalogError(
            f"{_CATALOG_IDS_KEY} contains an unsafe or empty server id"
        )
    if len(server_ids) != len(set(server_ids)):
        raise ServerProfileCatalogError(f"{_CATALOG_IDS_KEY} contains duplicate server ids")

    prefixes = {server_id: server_environment_prefix(server_id) for server_id in server_ids}
    prefix_trie = _declared_prefix_trie(prefixes)
    configured_by_server = {server_id: [] for server_id in server_ids}
    allowed_control_keys = {_CATALOG_IDS_KEY, _PROFILE_FILE_KEY}
    for key in environ:
        if not key.startswith("RP_SERVER_") or key in allowed_control_keys:
            continue
        server_id = _declared_server_for_key(prefix_trie, key)
        if server_id is None:
            raise ServerProfileCatalogError(
                f"server profile key is outside declared catalog membership: {key}"
            )
        prefix = prefixes[server_id]
        configured_by_server[server_id].append(key[len(prefix) + 1 :])

    entries: list[ServerProfileCatalogEntry] = []
    for server_id in server_ids:
        prefix = prefixes[server_id]
        configured = tuple(sorted(configured_by_server[server_id]))
        missing = _missing_profile_fields(environ, prefix, _IDENTITY_FIELDS)
        missing_runtime = _missing_profile_fields(environ, prefix, _RUNTIME_FIELDS)
        entries.append(
            ServerProfileCatalogEntry(
                server_id,
                prefix,
                configured,
                missing,
                missing_runtime,
            )
        )
    return ServerProfileCatalog(source, tuple(entries), environ)


__all__ = ["build_server_profile_catalog"]
