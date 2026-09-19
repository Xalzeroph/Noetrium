from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Iterator, Mapping
from contextlib import contextmanager

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.foundation.kernel.concurrency.api import TaskGroupPort
from noetrium_platform.composition.concurrency import build_execution_concurrency_runtime
from noetrium_platform.composition.platform_meta import build_in_memory_platform_meta
from noetrium_platform.infrastructure.lifecycle.host.composition import compose_local_host
from noetrium_platform.infrastructure.lifecycle.server.composition import (
    ServerManagementComposition,
    compose_environment_server,
    load_server_management_environment,
)
from noetrium_platform.infrastructure.lifecycle.server.health.api import ServerRuntimeHealthSpec
from noetrium_platform.infrastructure.lifecycle.server.health.composition import compose_server_runtime_health_spec
from noetrium_platform.infrastructure.lifecycle.server.identity.composition import compose_environment_server_identity
from noetrium_platform.infrastructure.lifecycle.server.identity.api import ServerProfileCatalog
from noetrium_platform.infrastructure.lifecycle.server.identity.providers import (
    build_server_profile_catalog,
)
from noetrium_platform.infrastructure.lifecycle.server.lifecycle.composition import compose_ssh_server_session_control
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionSpec
from noetrium_platform.infrastructure.lifecycle.session.api import PersistentSessionControlPort
from noetrium_platform.infrastructure.lifecycle.session.runtime import (
    BoundPersistentSessionStatusProbe,
    DirectoryPersistentSessionBindingStore,
    PersistentSessionManager,
)




@contextmanager
def server_cli_concurrency_scope(scope_id: str) -> Iterator[TaskGroupPort]:
    """Own every concurrent resource created by one server CLI invocation.

    Server tools are short-lived process roots.  They therefore get exactly one
    process-level concurrency runtime and one task group; all journals/actors
    created by the command are children of that group and physical shutdown is
    proved before the CLI returns.
    """

    normalized = str(scope_id).strip()
    if not normalized:
        raise ValueError("server CLI concurrency scope id required")
    runtime = build_execution_concurrency_runtime(
        blocking_io_thread_name_prefix=f"{normalized}-blocking-io",
        timer_name=f"{normalized}-timer",
    )
    group = runtime.open_task_group(f"server-cli:{normalized}")
    try:
        yield group
    finally:
        runtime.close()


@dataclass(frozen=True, slots=True)
class ServerOperatorSessionComposition:
    """Shared entrypoint composition for the profile-bound operator session."""

    server: ServerManagementComposition
    control: PersistentSessionControlPort
    manager: PersistentSessionManager
    spec: PersistentSessionSpec
    bindings: DirectoryPersistentSessionBindingStore


def compose_server_from_environment(
    server_id: str,
    *,
    environ: Mapping[str, str],
    task_group: TaskGroupPort,
) -> ServerManagementComposition:
    """Compose the outer host/platform route once, then bind runtime/server."""

    meta = build_in_memory_platform_meta()
    host = compose_local_host(planner=meta.capability_composition)
    identity = compose_environment_server_identity(
        operating_system=host.operating_system,
        host_operating_system_offer=host.operating_system_offer,
        planner=meta.capability_composition,
        task_group=task_group,
    )
    return compose_environment_server(
        server_id,
        environ=environ,
        identity=identity,
        task_group=task_group,
    )


def compose_script_server(
    server_id: str,
    *,
    profile_file: str | None,
    task_group: TaskGroupPort,
) -> tuple[Mapping[str, str], ServerManagementComposition]:
    environ = load_server_management_environment(profile_file)
    catalog = build_server_profile_catalog(environ, source=profile_file or "environment")
    entry = catalog.entry(server_id)
    if not entry.composition_ready:
        missing = ", ".join(entry.missing_profile_fields)
        raise ValueError(f"server profile is incomplete for {server_id}: missing {missing}")
    selected = catalog.environment_for(server_id)
    return selected, compose_server_from_environment(server_id, environ=selected, task_group=task_group)


def load_script_environment(profile_file: str | None) -> Mapping[str, str]:
    return load_server_management_environment(profile_file)


def compose_script_server_catalog(
    profile_file: str | None,
) -> tuple[Mapping[str, str], ServerProfileCatalog]:
    environ = load_script_environment(profile_file)
    source = profile_file or "environment"
    return environ, build_server_profile_catalog(environ, source=source)


def server_health_spec(server: ServerManagementComposition) -> ServerRuntimeHealthSpec:
    return compose_server_runtime_health_spec(server.remote_profile)


def compose_server_operator_session(
    server: ServerManagementComposition,
    *,
    interactive: bool,
    session_name: str | None = None,
) -> ServerOperatorSessionComposition:
    """Materialize the one operator-session binding used by all server tools."""

    profile = server.remote_profile
    selected_name = session_name or profile.session_name
    control = compose_ssh_server_session_control(
        connection=server.connection,
        profile=profile,
        interactive=interactive,
    )
    profile.local_binding_root.mkdir(parents=True, exist_ok=True)
    bindings = DirectoryPersistentSessionBindingStore(profile.local_binding_root)
    manager = PersistentSessionManager(control, bindings)
    spec = PersistentSessionSpec(
        session_name=selected_name,
        command_argv=(profile.operator_shell, *profile.operator_shell_args),
        cwd=profile.operator_cwd,
        control_id=f"operator-shell:{profile.server_id}",
        runtime_manifest_digest=canonical_digest(
            {
                "server_profile_digest": server.profile_digest,
                "server_id": profile.server_id,
                "platform_root": profile.platform_root,
                "operator_cwd": profile.operator_cwd,
                "repository_root": profile.repository_root,
                "operator_shell": profile.operator_shell,
                "operator_shell_args": profile.operator_shell_args,
                "remote_path": profile.remote_path,
                "session_environment": profile.session_environment,
            }
        ),
        process_environment=profile.session_environment,
    )
    return ServerOperatorSessionComposition(server, control, manager, spec, bindings)


def compose_server_session_observation(
    composition: ServerOperatorSessionComposition,
):
    return BoundPersistentSessionStatusProbe(
        composition.control,
        composition.bindings,
        composition.spec.session_name,
        expected_spec=composition.spec,
    ).observe()


__all__ = [
    "compose_script_server",
    "compose_script_server_catalog",
    "compose_server_operator_session",
    "compose_server_from_environment",
    "compose_server_session_observation",
    "load_script_environment",
    "server_health_spec",
    "server_cli_concurrency_scope",
    "ServerOperatorSessionComposition",
]
