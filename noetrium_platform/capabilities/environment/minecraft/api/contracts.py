from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
import os
from pathlib import Path
import re
from typing import Any, Mapping, TypeAlias

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.infrastructure.resources.allocation.api import EndpointAllocationRequest
from noetrium_platform.foundation.scope.path.api import is_absolute_target_path
from noetrium_platform.foundation.scope.api import ScopeKind


MinecraftJsonValue: TypeAlias = (
    str
    | int
    | float
    | bool
    | None
    | list["MinecraftJsonValue"]
    | dict[str, "MinecraftJsonValue"]
)


class MinecraftActionCategory(StrEnum):
    MOVEMENT = "movement"
    RESOURCE = "resource"
    INVENTORY = "inventory"
    COMBAT = "combat"
    INTERACTION = "interaction"
    OBSERVATION = "observation"


class MinecraftActionOutcomeStatus(StrEnum):
    """Provider-neutral disposition of one accepted Minecraft command."""

    APPLIED = "applied"
    PARTIAL = "partial"
    REJECTED = "rejected"


@dataclass(frozen=True, slots=True)
class MinecraftPlannerActionContract:
    """Serializable planner view of one exact MC action capability."""

    action_type: str
    category: str
    description: str
    arguments: str
    mutates_world: bool

    def as_payload(self) -> dict[str, str | bool]:
        return {
            "action_type": self.action_type,
            "category": self.category,
            "description": self.description,
            "arguments": self.arguments,
            "mutates_world": self.mutates_world,
        }


@dataclass(frozen=True, slots=True)
class MinecraftActionSpec:
    action_type: str
    category: MinecraftActionCategory
    mutates_world: bool
    description: str
    argument_contract: str
    timeout_multiplier: float = 1.0

    def __post_init__(self) -> None:
        if (
            not re.fullmatch(r"[a-z][a-z0-9_]*", self.action_type)
            or not self.description.strip()
            or not self.argument_contract.strip()
            or self.timeout_multiplier < 1.0
        ):
            raise ValueError("Minecraft action specification is invalid")

    def planner_contract(self) -> MinecraftPlannerActionContract:
        return MinecraftPlannerActionContract(
            action_type=self.action_type,
            category=self.category.value,
            description=self.description,
            arguments=self.argument_contract,
            mutates_world=self.mutates_world,
        )


MINECRAFT_ACTION_SPECS: tuple[MinecraftActionSpec, ...] = (
    MinecraftActionSpec("goto", MinecraftActionCategory.MOVEMENT, True, "Navigate to world coordinates.", "{position:{x:number,y:number,z:number}, radius?:0.1..64}", 2.0),
    MinecraftActionSpec("goto_entity", MinecraftActionCategory.MOVEMENT, True, "Navigate near a visible entity.", "{entity:string, max_distance?:1..128, radius?:1..16}", 2.0),
    MinecraftActionSpec("move_away", MinecraftActionCategory.MOVEMENT, True, "Create distance in the direction opposite current view.", "{distance?:1..64}", 2.0),
    MinecraftActionSpec("follow_player", MinecraftActionCategory.MOVEMENT, True, "Follow a visible player for a bounded interval and verify progress.", "{player:string, duration_s?:1..60, distance?:1..16, max_distance?:1..128}", 3.0),
    MinecraftActionSpec("stay", MinecraftActionCategory.MOVEMENT, False, "Remain within a bounded area for a cancellable interval.", "{duration_s?:1..60}"),
    MinecraftActionSpec("collect_block", MinecraftActionCategory.RESOURCE, True, "Find, mine and pick up matching blocks.", "{block:string, count?:1..64, max_distance?:4..128}", 4.0),
    MinecraftActionSpec("craft_item", MinecraftActionCategory.RESOURCE, True, "Craft an exact inventory item, using or placing a table when required.", "{item:string, count?:1..64}", 2.0),
    MinecraftActionSpec("smelt_item", MinecraftActionCategory.RESOURCE, True, "Smelt inventory input in a nearby furnace with bounded waiting.", "{item:string, count?:1..8, fuel?:string, max_distance?:1..128, max_wait_s?:10..180}", 4.0),
    MinecraftActionSpec("clear_furnace", MinecraftActionCategory.RESOURCE, True, "Take all input, fuel and output from a nearby furnace.", "{max_distance?:1..128}", 2.0),
    MinecraftActionSpec("place_block", MinecraftActionCategory.RESOURCE, True, "Place an inventory block at an optional exact position.", "{item:string, position?:{x:number,y:number,z:number}}", 2.0),
    MinecraftActionSpec("pickup_items", MinecraftActionCategory.RESOURCE, True, "Approach nearby dropped items and verify inventory progress.", "{max_distance?:1..64, max_items?:1..32}", 3.0),
    MinecraftActionSpec("auto_light", MinecraftActionCategory.RESOURCE, True, "Place one torch when the bounded local area lacks lighting.", "{max_distance?:1..16}"),
    MinecraftActionSpec("equip_item", MinecraftActionCategory.INVENTORY, True, "Equip an inventory item to an equipment destination.", "{item:string, destination?:hand|off-hand|head|torso|legs|feet}"),
    MinecraftActionSpec("consume_item", MinecraftActionCategory.INVENTORY, True, "Consume one usable food, potion or similar inventory item.", "{item:string}"),
    MinecraftActionSpec("discard_item", MinecraftActionCategory.INVENTORY, True, "Drop an exact count from inventory.", "{item:string, count?:1..64}"),
    MinecraftActionSpec("give_item", MinecraftActionCategory.INVENTORY, True, "Move near a visible player and drop items to them.", "{player:string, item:string, count?:1..64}", 2.0),
    MinecraftActionSpec("chest_inspect", MinecraftActionCategory.INVENTORY, False, "Inspect the nearest chest, trapped chest or barrel.", "{max_distance?:1..128}", 2.0),
    MinecraftActionSpec("chest_deposit", MinecraftActionCategory.INVENTORY, True, "Deposit an exact item count into a nearby container.", "{item:string, count?:1..64, max_distance?:1..128}", 2.0),
    MinecraftActionSpec("chest_withdraw", MinecraftActionCategory.INVENTORY, True, "Withdraw an exact item count from a nearby container.", "{item:string, count?:1..64, max_distance?:1..128}", 2.0),
    MinecraftActionSpec("till_and_sow", MinecraftActionCategory.INVENTORY, True, "Till a nearby soil block and sow a selected seed.", "{seed:string, max_distance?:1..32}"),
    MinecraftActionSpec("attack_nearest", MinecraftActionCategory.COMBAT, True, "Attack the nearest visible entity matching a name.", "{entity:string, max_distance?:1..128, max_hits?:1..20}", 2.0),
    MinecraftActionSpec("attack_entity", MinecraftActionCategory.COMBAT, True, "Attack one visible entity by numeric entity ID.", "{entity_id:integer, max_distance?:1..128, max_hits?:1..40}", 2.0),
    MinecraftActionSpec("attack_player", MinecraftActionCategory.COMBAT, True, "Attack one visible player by exact username.", "{player:string, max_distance?:1..128, max_hits?:1..40}", 2.0),
    MinecraftActionSpec("ranged_attack", MinecraftActionCategory.COMBAT, True, "Fire a bow or crossbow at a visible entity.", "{entity:string, max_distance?:1..128, shots?:1..8, charge_ms?:100..2000}", 2.0),
    MinecraftActionSpec("defend_self", MinecraftActionCategory.COMBAT, True, "Engage bounded hostile mobs near the bot.", "{radius?:1..32, max_targets?:1..16, max_hits?:1..40}", 3.0),
    MinecraftActionSpec("fish", MinecraftActionCategory.RESOURCE, True, "Fish with a rod for a bounded number of catches.", "{casts?:1..8, max_wait_s?:10..120}", 4.0),
    MinecraftActionSpec("mount", MinecraftActionCategory.INTERACTION, True, "Approach and mount one visible rideable entity.", "{entity?:string, max_distance?:1..32}"),
    MinecraftActionSpec("dismount", MinecraftActionCategory.INTERACTION, True, "Leave the current vehicle and verify the vehicle state.", "{}"),
    MinecraftActionSpec("use_door", MinecraftActionCategory.INTERACTION, True, "Open a nearby door and verify its open state.", "{max_distance?:1..32}"),
    MinecraftActionSpec("go_to_bed", MinecraftActionCategory.INTERACTION, True, "Navigate to a nearby bed and request sleep.", "{max_distance?:1..64, max_wait_s?:10..60}", 2.0),
    MinecraftActionSpec("activate_nearest_block", MinecraftActionCategory.INTERACTION, True, "Activate one nearby button, lever, trapdoor or interactive block.", "{block:string, max_distance?:1..32}"),
    MinecraftActionSpec("show_villager_trades", MinecraftActionCategory.INTERACTION, False, "Inspect a nearby adult employed villager trade list.", "{max_distance?:1..32}"),
    MinecraftActionSpec("trade_villager", MinecraftActionCategory.INTERACTION, True, "Execute a bounded trade with a nearby villager after resource checks.", "{trade_index:integer, max_trades?:1..16, max_distance?:1..32}"),
    MinecraftActionSpec("use_tool_on", MinecraftActionCategory.INTERACTION, True, "Use the equipped item on a nearby block or entity and verify the call.", "{target:string, target_type?:block|entity, max_distance?:1..32}"),
    MinecraftActionSpec("wait", MinecraftActionCategory.INTERACTION, False, "Wait for a bounded duration.", "{ms?:0..10000}"),
    MinecraftActionSpec("chat", MinecraftActionCategory.INTERACTION, True, "Send one Minecraft chat message.", "{message:string}"),
    MinecraftActionSpec("observe_entities", MinecraftActionCategory.OBSERVATION, False, "Refresh bounded nearby entity observations.", "{max_distance?:1..128, limit?:1..100}"),
    MinecraftActionSpec("registry_search", MinecraftActionCategory.OBSERVATION, False, "Search canonical Minecraft item and block registry names.", "{query:string, limit?:1..100}"),
)

MINECRAFT_ACTION_SPEC_BY_TYPE = {spec.action_type: spec for spec in MINECRAFT_ACTION_SPECS}
if len(MINECRAFT_ACTION_SPEC_BY_TYPE) != len(MINECRAFT_ACTION_SPECS):
    raise RuntimeError("Minecraft action specification contains duplicate action types")
MINECRAFT_ACTION_TYPES: frozenset[str] = frozenset(MINECRAFT_ACTION_SPEC_BY_TYPE)


@dataclass(frozen=True, slots=True)
class MinecraftEndpointSpec:
    """Operational network location for one MC environment instance."""

    host: str = "127.0.0.1"
    port: int = 25565

    def __post_init__(self) -> None:
        if not self.host.strip():
            raise ValueError("Minecraft endpoint host is required")
        if not 1 <= self.port <= 65535:
            raise ValueError("Minecraft endpoint port must be between 1 and 65535")


@dataclass(frozen=True, slots=True)
class MinecraftAgentSpec:
    """Scientific agent conditions independent of the server's network address."""

    username: str = "ResearchBot"
    auth: str = "offline"
    version: str = ""

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[A-Za-z0-9_]{3,16}", self.username):
            raise ValueError(
                "Minecraft agent username must match [A-Za-z0-9_]{3,16}"
            )
        if not self.auth.strip():
            raise ValueError("Minecraft agent username and auth are required")


@dataclass(frozen=True, slots=True)
class MinecraftBridgeSpec:
    """Frozen bridge process contract; server lifecycle is owned elsewhere."""

    command: tuple[str, ...]
    cwd: str
    stderr_log_path: str | None = None
    action_recovery_root: str | None = None
    connect_timeout_s: float = 45.0
    command_timeout_s: float = 45.0
    stdout_queue_capacity: int = 4096

    def __post_init__(self) -> None:
        if not self.command or any(not item.strip() for item in self.command):
            raise ValueError("Minecraft bridge command must be non-empty")
        if not self.cwd.strip():
            raise ValueError("Minecraft bridge cwd must be non-empty")
        if self.action_recovery_root is not None and (
            not self.action_recovery_root.strip()
            or not is_absolute_target_path(self.action_recovery_root)
        ):
            raise ValueError("Minecraft bridge action_recovery_root must be absolute when provided")
        if min(self.connect_timeout_s, self.command_timeout_s) <= 0:
            raise ValueError("Minecraft bridge timeouts must be positive")
        if self.stdout_queue_capacity <= 0:
            raise ValueError("Minecraft bridge stdout_queue_capacity must be positive")


@dataclass(frozen=True, slots=True)
class MinecraftEnvironmentSpec:
    """One immutable MC environment selection without runtime state."""

    endpoint: MinecraftEndpointSpec
    bridge: MinecraftBridgeSpec
    agent: MinecraftAgentSpec = field(default_factory=MinecraftAgentSpec)
    implementation_version: str = "1"
    abi_version: str = "1"
    schema_version: str = "1"
    provider_id: str = "minecraft.mineflayer.jsonl.v1"
    max_entities: int = 256
    entity_observation_distance: int = 32

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.implementation_version,
                self.abi_version,
                self.schema_version,
                self.provider_id,
            )
        ):
            raise ValueError("Minecraft environment identity fields must be non-empty")
        if self.max_entities < 1:
            raise ValueError("Minecraft environment max_entities must be positive")
        if not 4 <= self.entity_observation_distance <= 128:
            raise ValueError("Minecraft entity_observation_distance must be in [4, 128]")

    def scientific_identity_digest(self) -> str:
        """Identity of conditions that can change a scientific paired comparison."""

        return canonical_digest(
            {
                "agent": self.agent,
                "implementation_version": self.implementation_version,
                "abi_version": self.abi_version,
                "schema_version": self.schema_version,
                "provider_id": self.provider_id,
                "max_entities": self.max_entities,
                "entity_observation_distance": self.entity_observation_distance,
                "bridge_contract": {
                    "command": self.bridge.command,
                    "cwd": self.bridge.cwd,
                    "connect_timeout_s": self.bridge.connect_timeout_s,
                    "command_timeout_s": self.bridge.command_timeout_s,
                    "stdout_queue_capacity": self.bridge.stdout_queue_capacity,
                },
            }
        )

    def operational_binding_digest(self) -> str:
        """Identity of transport/process placement, recorded as runtime evidence only."""

        return canonical_digest({"endpoint": self.endpoint, "bridge": self.bridge})


@dataclass(frozen=True, slots=True)
class MinecraftSessionRuntimeIdentity:
    """MC-owned session runtime identity exposed before participant binding."""

    runtime_id: str
    runtime_version: str
    abi_version: str
    artifact_digest: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (self.runtime_id, self.runtime_version, self.abi_version, self.artifact_digest)
        ):
            raise ValueError("Minecraft session runtime identity fields must be non-empty")


@dataclass(frozen=True, slots=True)
class MinecraftServerSpec:
    """Immutable vanilla-server configuration; it owns no process lifecycle."""

    jar_path: str
    workdir: str
    java_executable: str
    libraries_dir: str | None = None
    host: str = "127.0.0.1"
    port: int = 25565
    level_name: str = "research-world"
    level_seed: str = "NOETRIUM_FIXED_WORLD_V1"
    online_mode: bool = False
    xms: str = "512M"
    xmx: str = "2G"
    rcon_endpoint: MinecraftRconEndpoint | None = None

    def __post_init__(self) -> None:
        for name, value in (
            ("jar_path", self.jar_path),
            ("workdir", self.workdir),
            ("java_executable", self.java_executable),
        ):
            if not value.strip() or not is_absolute_target_path(value):
                raise ValueError(f"Minecraft server {name} must be an absolute path")
        if self.libraries_dir is not None and (
            not self.libraries_dir.strip() or not is_absolute_target_path(self.libraries_dir)
        ):
            raise ValueError("Minecraft server libraries_dir must be an absolute path when provided")
        if not self.host.strip() or not 1 <= self.port <= 65535:
            raise ValueError("Minecraft server host/port is invalid")
        if (
            not self.level_name.strip()
            or "/" in self.level_name
            or "\\" in self.level_name
            or not self.level_seed.strip()
        ):
            raise ValueError("Minecraft server level identity is invalid")
        if not self.xms.strip() or not self.xmx.strip():
            raise ValueError("Minecraft server heap sizes must be non-empty")

    def command(self) -> tuple[str, ...]:
        if self.libraries_dir is not None:
            library_jars = tuple(
                str(path)
                for path in sorted(Path(self.libraries_dir).rglob("*.jar"))
                if path.is_file()
            )
            if not library_jars:
                raise ValueError(f"Minecraft server libraries_dir contains no jar files: {self.libraries_dir}")
            classpath = os.pathsep.join((str(Path(self.jar_path)), *library_jars))
            return (
                self.java_executable,
                f"-Xms{self.xms}",
                f"-Xmx{self.xmx}",
                "-cp",
                classpath,
                "net.minecraft.server.Main",
                "nogui",
            )
        return (
            self.java_executable,
            f"-Xms{self.xms}",
            f"-Xmx{self.xmx}",
            "-jar",
            str(Path(self.jar_path)),
            "nogui",
        )


@dataclass(frozen=True, slots=True)
class MinecraftServerPreparedFiles:
    """Prepared server configuration facts, not a server process identity."""

    eula_path: str
    properties_path: str
    eula_accepted: bool
    properties_digest: str

    def __post_init__(self) -> None:
        if not self.eula_path or not self.properties_path or not self.properties_digest:
            raise ValueError("Minecraft prepared-file identity is incomplete")


@dataclass(frozen=True, slots=True)
class MinecraftRconEndpoint:
    """MC-native control endpoint; the secret is resolved outside this value."""

    host: str = "127.0.0.1"
    port: int = 25575
    command_timeout_s: float = 10.0

    def __post_init__(self) -> None:
        if not self.host.strip() or not 1 <= self.port <= 65535:
            raise ValueError("Minecraft RCON endpoint is invalid")
        if self.command_timeout_s <= 0:
            raise ValueError("Minecraft RCON command timeout must be positive")


@dataclass(frozen=True, slots=True)
class MinecraftConsoleCommandResult:
    """A server-console command response without any credential material."""

    command: str
    response: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not self.command.strip() or "\x00" in self.command:
            raise ValueError("Minecraft console command is invalid")
        if not self.evidence_ref.strip():
            raise ValueError("Minecraft console evidence_ref is required")


@dataclass(frozen=True, slots=True)
class MinecraftWorldQuiescence:
    """Evidence that a live MC world reached a save/quiescent cut."""

    source_workdir: str
    level_name: str
    server_contract_digest: str
    process_identity_digest: str
    save_evidence_ref: str

    def __post_init__(self) -> None:
        if not self.source_workdir.strip() or not is_absolute_target_path(self.source_workdir):
            raise ValueError("Minecraft world quiescence source_workdir must be absolute")
        if (
            not self.level_name.strip()
            or "/" in self.level_name
            or "\\" in self.level_name
            or self.level_name in {".", ".."}
        ):
            raise ValueError("Minecraft world quiescence level_name is invalid")
        for name, value in (
            ("server_contract_digest", self.server_contract_digest),
            ("process_identity_digest", self.process_identity_digest),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
                raise ValueError(f"Minecraft quiescence {name} must be a SHA-256 digest")
        if not self.save_evidence_ref.strip():
            raise ValueError("Minecraft world quiescence requires save evidence")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MinecraftWorldCut:
    """Immutable identity of a verified, reusable Minecraft world cut."""

    cut_id: str
    snapshot_ref: str
    manifest_ref: str
    level_name: str
    server_contract_digest: str
    process_identity_digest: str
    manifest_digest: str
    save_evidence_ref: str

    def __post_init__(self) -> None:
        if any(
            not value.strip()
            for value in (
                self.cut_id,
                self.snapshot_ref,
                self.manifest_ref,
                self.level_name,
                self.server_contract_digest,
                self.process_identity_digest,
                self.manifest_digest,
                self.save_evidence_ref,
            )
        ):
            raise ValueError("Minecraft world cut identity is incomplete")
        for name, value in (
            ("server_contract_digest", self.server_contract_digest),
            ("process_identity_digest", self.process_identity_digest),
            ("manifest_digest", self.manifest_digest),
        ):
            if len(value) != 64 or any(char not in "0123456789abcdef" for char in value.lower()):
                raise ValueError(f"Minecraft world cut {name} must be a SHA-256 digest")
        if "/" in self.level_name or "\\" in self.level_name:
            raise ValueError("Minecraft world cut level_name must be a single path component")

    def digest(self) -> str:
        return canonical_digest(self)


@dataclass(frozen=True, slots=True)
class MinecraftWorldBranch:
    """Identity and cleanup authority for one isolated branch materialization."""

    branch_id: str
    cut_id: str
    workdir: str
    level_name: str
    manifest_digest: str
    cleanup_ref: str

    def __post_init__(self) -> None:
        if not self.branch_id.strip() or not self.cut_id.strip() or not self.workdir.strip():
            raise ValueError("Minecraft world branch identity is incomplete")
        if not is_absolute_target_path(self.workdir):
            raise ValueError("Minecraft world branch workdir must be absolute")
        if not self.level_name.strip() or "/" in self.level_name or "\\" in self.level_name:
            raise ValueError("Minecraft world branch level_name is invalid")
        if len(self.manifest_digest) != 64 or any(char not in "0123456789abcdef" for char in self.manifest_digest.lower()):
            raise ValueError("Minecraft world branch manifest_digest must be a SHA-256 digest")
        if not self.cleanup_ref.strip():
            raise ValueError("Minecraft world branch cleanup_ref is required")


@dataclass(frozen=True, slots=True)
class MinecraftBranchRuntimeRequest:
    """Frozen input for realizing one isolated branch runtime."""

    branch: MinecraftWorldBranch
    endpoint_allocation: EndpointAllocationRequest
    environment_template: MinecraftEnvironmentSpec
    server_template: MinecraftServerSpec
    session_id: str
    rcon_endpoint_allocation: EndpointAllocationRequest | None = None

    def __post_init__(self) -> None:
        if not self.session_id.strip():
            raise ValueError("Minecraft branch runtime session_id is required")
        if self.endpoint_allocation.holder_scope.kind is not ScopeKind.BRANCH:
            raise ValueError("Minecraft branch endpoint allocation must be held by a branch scope")
        if self.rcon_endpoint_allocation is not None and self.rcon_endpoint_allocation.holder_scope.kind is not ScopeKind.BRANCH:
            raise ValueError("Minecraft branch RCON allocation must be held by a branch scope")
        if (self.server_template.rcon_endpoint is None) != (self.rcon_endpoint_allocation is None):
            raise ValueError("Minecraft branch RCON template and allocation must be supplied together")


@dataclass(frozen=True, slots=True)
class MinecraftObservationEvent:
    """Architecture-neutral event decoded from one bridge envelope."""

    kind: str
    payload: Mapping[str, MinecraftJsonValue]
    sequence: int = 0
    timestamp_ms: int = 0
    source: str = "mineflayer"
    request_id: str | None = None

    def __post_init__(self) -> None:
        if not self.kind.strip() or self.sequence < 0 or self.timestamp_ms < 0:
            raise ValueError("Minecraft observation event identity is invalid")
        if not self.source.strip():
            raise ValueError("Minecraft observation event source is required")
        if self.request_id is not None and not self.request_id.strip():
            raise ValueError("Minecraft observation event request_id must be non-empty")


@dataclass(frozen=True, slots=True)
class MinecraftActionResultEvidence:
    """Identity-bound effect evidence emitted by an MC provider action.

    ``verified`` means the requested effect was observed, rather than merely
    that a command reached Mineflayer. ``status`` separates a deterministic
    rejection from an action that may have partially changed the world.
    """

    action_id: str
    action_type: str
    status: MinecraftActionOutcomeStatus
    verified: bool
    outcome: Mapping[str, MinecraftJsonValue]

    @classmethod
    def from_event(
        cls,
        event: MinecraftObservationEvent,
        *,
        expected_action_id: str,
        expected_action_type: str,
    ) -> "MinecraftActionResultEvidence":
        if event.kind != "action_result":
            raise ValueError("Minecraft action evidence must be an action_result event")
        payload = event.payload
        action_id = payload.get("action_id")
        if not isinstance(action_id, str) or action_id != expected_action_id:
            raise ValueError(
                "Minecraft action_result action_id does not match the request"
            )
        action = payload.get("action")
        if not isinstance(action, Mapping) or action.get("tool") != expected_action_type:
            raise ValueError(
                "Minecraft action_result tool does not match the request action_type"
            )
        outcome = payload.get("outcome")
        if not isinstance(outcome, Mapping):
            raise ValueError("Minecraft action_result outcome must be a mapping")
        verified = payload.get("verified")
        if not isinstance(verified, bool):
            raise ValueError("Minecraft action_result verified must be boolean")
        raw_status = outcome.get("status")
        if raw_status is None:
            raise ValueError("Minecraft action_result outcome.status is required")
        try:
            status = MinecraftActionOutcomeStatus(str(raw_status))
        except ValueError as exc:
            raise ValueError("Minecraft action_result status is invalid") from exc
        if status is MinecraftActionOutcomeStatus.REJECTED and verified:
            raise ValueError("Rejected Minecraft action_result cannot be verified")
        if status is MinecraftActionOutcomeStatus.APPLIED and not verified:
            raise ValueError("Applied Minecraft action_result must be verified")
        return cls(
            action_id=action_id,
            action_type=expected_action_type,
            status=status,
            verified=verified,
            outcome=dict(outcome),
        )


@dataclass(frozen=True, slots=True)
class MinecraftBridgeEnvelope:
    """Validated wire envelope emitted by a Minecraft bridge.

    This is the direct, architecture-neutral extraction of v034's
    ``BridgeEnvelope``. It deliberately contains no task, memory, benchmark or
    evolution fields; those remain payload data owned by the composing project.
    """

    kind: str
    timestamp_ms: int
    payload: Mapping[str, MinecraftJsonValue]
    source: str = "mineflayer"
    sequence: int = 0
    request_id: str | None = None

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "MinecraftBridgeEnvelope":
        if value.get("type") != "event":
            raise ValueError("Minecraft bridge envelope must have type=event")
        kind = str(value.get("kind", ""))
        if not kind.strip():
            raise ValueError("Minecraft bridge event kind is required")
        payload = value.get("payload", {})
        if not isinstance(payload, Mapping):
            raise ValueError("Minecraft bridge event payload must be a mapping")
        timestamp_ms = int(value.get("ts_ms", 0))
        sequence = int(value.get("seq", 0))
        source = str(value.get("source", "mineflayer"))
        request_id_value = value.get("request_id")
        request_id = None if request_id_value is None else str(request_id_value)
        return cls(
            kind=kind,
            timestamp_ms=timestamp_ms,
            payload=dict(payload),
            source=source,
            sequence=sequence,
            request_id=request_id,
        )

    def as_observation(self) -> MinecraftObservationEvent:
        return MinecraftObservationEvent(
            kind=self.kind,
            payload=dict(self.payload),
            sequence=self.sequence,
            timestamp_ms=self.timestamp_ms,
            source=self.source,
            request_id=self.request_id,
        )
