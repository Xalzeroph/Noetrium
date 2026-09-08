from __future__ import annotations

from noetrium_platform.foundation.governance.system_registry.api import system_catalog

from noetrium_platform.capabilities.environment.category.api.contracts import (
    EnvironmentCategoryDescriptor,
    EnvironmentCategoryId,
    EnvironmentCategoryStatus,
    EnvironmentImplementationDescriptor,
)


def _environment_family_descriptor(category_id: EnvironmentCategoryId):
    key = f"environment/{category_id.value}"
    by_key = {row.identity.key: row for row in system_catalog()}
    try:
        descriptor = by_key[key]
    except KeyError as exc:
        raise RuntimeError(f"environment category is not registered as a system: {key}") from exc
    expected_capability = f"environment.{category_id.value}.contract"
    if expected_capability not in descriptor.provides:
        raise RuntimeError(
            f"environment category system {key} must provide {expected_capability}"
        )
    return descriptor


def _registered_environment_category_ids() -> frozenset[str]:
    rows = set()
    for descriptor in system_catalog():
        if descriptor.parent_key != "environment":
            continue
        segment = descriptor.identity.subsystem_path[-1]
        if f"environment.{segment}.contract" in descriptor.provides:
            rows.add(segment)
    return frozenset(rows)


def _category(
    category_id: EnvironmentCategoryId,
    description: str,
    modalities: tuple[str, ...],
    surfaces: tuple[str, ...],
    properties: tuple[str, ...],
    implementations: tuple[str, ...] = (),
    planned: tuple[str, ...] = (),
) -> EnvironmentCategoryDescriptor:
    descriptor = _environment_family_descriptor(category_id)
    return EnvironmentCategoryDescriptor(
        category_id=category_id,
        version="1",
        package=descriptor.identity.key.replace("/", "."),
        description=description,
        modalities=modalities,
        interaction_surfaces=surfaces,
        world_properties=properties,
        implementation_ids=implementations,
        planned_implementation_ids=planned,
    )


def canonical_environment_categories() -> tuple[EnvironmentCategoryDescriptor, ...]:
    enum_ids = frozenset(item.value for item in EnvironmentCategoryId)
    registered_ids = _registered_environment_category_ids()
    if enum_ids != registered_ids:
        raise RuntimeError(
            "environment category enum/registry drift: "
            f"enum={sorted(enum_ids)!r} registered={sorted(registered_ids)!r}"
        )
    return (
        _category(
            EnvironmentCategoryId.MINECRAFT,
            "Persistent voxel open-world environments with spatial state and game actions.",
            ("text", "structured", "visual"),
            ("world_api", "visual", "command"),
            ("persistent_state", "spatial", "stochastic"),
            ("minecraft.mineflayer", "minecraft.rcon"),
        ),
        _category(
            EnvironmentCategoryId.EMBODIED,
            "Physical or simulated worlds where an agent acts through an embodiment.",
            ("visual", "sensor", "control"),
            ("sensor", "actuator", "trajectory"),
            ("continuous_time", "physical_constraints", "partial_observability"),
            ("embodied.adapter",),
            ("embodied.habitat", "embodied.maniskill", "embodied.real_robot"),
        ),
        _category(
            EnvironmentCategoryId.GUI,
            "Desktop and mobile operating-system interfaces controlled through GUI actions.",
            ("visual", "structured", "accessibility"),
            ("pixels", "accessibility_tree", "keyboard_mouse", "touch"),
            ("persistent_state", "event_driven", "partially_observable"),
            planned=("gui.desktop_vm", "gui.mobile_emulator"),
        ),
        _category(
            EnvironmentCategoryId.WEB,
            "Stateful browser and web-application worlds exposed through web surfaces.",
            ("visual", "structured", "text"),
            ("dom", "pixels", "browser_navigation", "http"),
            ("persistent_state", "networked", "partially_observable"),
            planned=("web.browser", "web.live_application"),
        ),
        _category(
            EnvironmentCategoryId.SOFTWARE,
            "Repository and operating-system workspaces changed through software actions.",
            ("text", "code", "structured"),
            ("terminal", "filesystem", "repository", "test_runner"),
            ("persistent_state", "deterministic_or_stochastic", "artifact_producing"),
            planned=("software.repository", "software.terminal"),
        ),
        _category(
            EnvironmentCategoryId.TEXT_WORLD,
            "Text-mediated worlds whose state evolves in response to textual actions.",
            ("text", "structured"),
            ("text_command", "text_observation"),
            ("stateful", "turn_based", "partially_observable"),
            planned=("text_world.interactive_fiction", "text_world.simulation"),
        ),
    )


def canonical_environment_implementations() -> tuple[EnvironmentImplementationDescriptor, ...]:
    return (
        EnvironmentImplementationDescriptor(
            implementation_id="minecraft.mineflayer",
            category_id=EnvironmentCategoryId.MINECRAFT,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.MINECRAFT).package_prefix,
            backend_kind="game_server_bridge",
            capabilities=("actions", "observations", "raw_records"),
            resource_profile={"requires": ["node", "minecraft_server"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="minecraft.rcon",
            category_id=EnvironmentCategoryId.MINECRAFT,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.MINECRAFT).package_prefix,
            backend_kind="rcon_bridge",
            capabilities=("commands", "observations", "raw_records"),
            resource_profile={"requires": ["minecraft_server"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="embodied.adapter",
            category_id=EnvironmentCategoryId.EMBODIED,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.EMBODIED).package_prefix,
            backend_kind="provider_adapter",
            capabilities=("sensors", "actions", "raw_records"),
            resource_profile={"supports": ["simulator", "hardware"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="embodied.habitat",
            category_id=EnvironmentCategoryId.EMBODIED,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.EMBODIED).package_prefix,
            backend_kind="simulator_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("sensors", "actions", "trajectory"),
            resource_profile={"requires": ["habitat"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="embodied.maniskill",
            category_id=EnvironmentCategoryId.EMBODIED,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.EMBODIED).package_prefix,
            backend_kind="simulator_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("sensors", "actions", "trajectory"),
            resource_profile={"requires": ["maniskill"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="embodied.real_robot",
            category_id=EnvironmentCategoryId.EMBODIED,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.EMBODIED).package_prefix,
            backend_kind="hardware_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("sensors", "actions", "trajectory"),
            resource_profile={"requires": ["robot_controller"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="gui.desktop_vm",
            category_id=EnvironmentCategoryId.GUI,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.GUI).package_prefix,
            backend_kind="desktop_vm_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("pixels", "accessibility", "keyboard_mouse"),
            resource_profile={"requires": ["desktop_vm"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="gui.mobile_emulator",
            category_id=EnvironmentCategoryId.GUI,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.GUI).package_prefix,
            backend_kind="mobile_emulator_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("pixels", "accessibility", "touch"),
            resource_profile={"requires": ["mobile_emulator"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="web.browser",
            category_id=EnvironmentCategoryId.WEB,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.WEB).package_prefix,
            backend_kind="browser_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("dom", "pixels", "browser_navigation"),
            resource_profile={"requires": ["browser_runtime"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="web.live_application",
            category_id=EnvironmentCategoryId.WEB,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.WEB).package_prefix,
            backend_kind="web_application_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("dom", "http", "browser_navigation"),
            resource_profile={"requires": ["application_under_test"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="software.repository",
            category_id=EnvironmentCategoryId.SOFTWARE,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.SOFTWARE).package_prefix,
            backend_kind="repository_workspace_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("filesystem", "repository", "test_runner"),
            resource_profile={"requires": ["workspace"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="software.terminal",
            category_id=EnvironmentCategoryId.SOFTWARE,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.SOFTWARE).package_prefix,
            backend_kind="terminal_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("terminal", "process", "artifacts"),
            resource_profile={"requires": ["terminal"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="text_world.interactive_fiction",
            category_id=EnvironmentCategoryId.TEXT_WORLD,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.TEXT_WORLD).package_prefix,
            backend_kind="interactive_fiction_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("text_command", "text_observation"),
            resource_profile={"requires": ["text_world_runtime"]},
        ),
        EnvironmentImplementationDescriptor(
            implementation_id="text_world.simulation",
            category_id=EnvironmentCategoryId.TEXT_WORLD,
            version="1",
            provider_package=_environment_family_descriptor(EnvironmentCategoryId.TEXT_WORLD).package_prefix,
            backend_kind="text_simulation_adapter",
            status=EnvironmentCategoryStatus.CONTRACT_ONLY,
            capabilities=("text_command", "text_observation", "state_query"),
            resource_profile={"requires": ["text_simulator"]},
        ),
    )


__all__ = [
    "canonical_environment_categories",
    "canonical_environment_implementations",
]
