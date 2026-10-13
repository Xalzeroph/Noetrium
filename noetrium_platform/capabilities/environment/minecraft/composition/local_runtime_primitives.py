"""Minecraft-local runtime primitives exposed only to the adjacent composition layer.

Provider implementations stay private to the Minecraft capability. Platform
composition receives one capability-owned surface instead of importing provider
modules directly.
"""
from __future__ import annotations
from pathlib import Path
from ..api import MinecraftRconEndpoint, MinecraftServerSpec
from ..providers.rcon import MinecraftRconConsole
from ..providers.server_files import prepare_server_files
from ..providers.pristine_world import MinecraftPristineWorldTemplateCache, MinecraftPristineWorldTemplateReservation, PRISTINE_WORLD_TEMPLATE_SCHEMA
from ..providers.bridge_distribution import (
    BRIDGE_RUNTIME_DISTRIBUTION_SCHEMA,
    MinecraftBridgeRuntimeDistribution,
    MinecraftBridgeRuntimeDistributionCache,
)
from ..providers.server_distribution import (
    MinecraftServerRuntimeDistribution,
    MinecraftServerRuntimeDistributionCache,
    SERVER_RUNTIME_DISTRIBUTION_SCHEMA,
)

def prepare_local_server_files(spec:MinecraftServerSpec, *, rcon_password:str|None):
    return prepare_server_files(spec,accept_eula=True,rcon_password=rcon_password)

def execute_local_rcon(endpoint:MinecraftRconEndpoint, *, password:str, command:str, timeout_s:float=10.0)->str:
    return MinecraftRconConsole(endpoint,secret_provider=lambda:password).execute(command,timeout_s=timeout_s).response

def local_pristine_world_cache(root:Path)->MinecraftPristineWorldTemplateCache:
    return MinecraftPristineWorldTemplateCache(root)

def local_bridge_runtime_source_root()->Path:
    root=(Path(__file__).resolve().parent.parent / "providers" / "assets" / "mineflayer_bridge").resolve()
    if not root.is_dir():
        raise FileNotFoundError(root)
    return root

__all__=[
    'BRIDGE_RUNTIME_DISTRIBUTION_SCHEMA',
    'MinecraftBridgeRuntimeDistribution',
    'MinecraftBridgeRuntimeDistributionCache',
    'MinecraftPristineWorldTemplateCache',
    'MinecraftPristineWorldTemplateReservation',
    'PRISTINE_WORLD_TEMPLATE_SCHEMA',
    'MinecraftServerRuntimeDistribution',
    'MinecraftServerRuntimeDistributionCache',
    'SERVER_RUNTIME_DISTRIBUTION_SCHEMA',
    'execute_local_rcon',
    'local_bridge_runtime_source_root',
    'local_pristine_world_cache',
    'prepare_local_server_files',
]
