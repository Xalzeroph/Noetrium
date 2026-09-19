# Minecraft Infrastructure

Minecraft is a first-party bundled environment provider of Noetrium. It is upstream because its contracts, lifecycle, world-state projection, server control, action ABI and bridge runtime are reusable across independent research projects.

Project-specific task suites, benchmark manifests, scientific methods and experiment compositions remain downstream.

- `MC_ACTION_CAPABILITY_SYSTEM.md` documents the typed action/evidence contract.
- `MC_RUNTIME_BOOTSTRAP_AND_SCENARIOS.md` documents server/runtime acquisition, source-world provisioning and qualification.
- MC_ENDPOINT_GENERATION_BINDING.md documents READY-process endpoint proofs and checkpoint restart generation replacement.
- `DOCKER_COMPOSE_RUNTIME.md` documents the optional Minecraft container overlay.
- `UPSTREAM_SOURCE_EVIDENCE.md` records the exact Mineflayer source lock and the local safety extensions derived from it.

Provider source lives under `noetrium_platform/capabilities/environment/minecraft/`. Mineflayer bridge assets are shipped as Python package data so wheel installations retain the locked JavaScript runtime contract.

Minecraft provider changes must follow the exact-version upstream-source audit rule in [`../../governance/DOCUMENTATION_CHANGE_POLICY.md`](../../governance/DOCUMENTATION_CHANGE_POLICY.md). Do not infer protocol, pathfinder or entity behavior when the locked upstream source can establish it.
