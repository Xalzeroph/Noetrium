# Round 148 — restore bundled Minecraft provider upstream

Date: 2026-08-28

## Boundary correction

The initial 0.43.0 repository extraction incorrectly treated the reusable Minecraft environment provider as downstream-owned. The project split rule is narrower: benchmark/task/scientific composition is downstream, while a provider that is independently reusable across projects may remain upstream.

Version 0.43.1 restores `noetrium_platform/capabilities/environment/minecraft`, its active infrastructure docs and provider tests from the preserved pre-split Git state. SEM/project-specific Minecraft composition remains downstream.

## Packaging and runtime

Mineflayer bridge JavaScript/package-lock assets are explicit Python package data. The generic Docker image remains lightweight, while `Dockerfile.minecraft` and `compose.minecraft.yaml` provide an opt-in Java 21 + Node 22 + Mineflayer runtime.

`minecraft-doctor` verifies Python/package identity, Java, Node/npm, locked Mineflayer dependency versions and writable Minecraft state.

## Verification

Focused restored-provider/platform boundary regression: 100 passed. Complete platform regression: 1082 passed, 6 skipped, 4 subtests passed. Test taxonomy: 290 files. Architecture and source repository boundary gates pass.

Linux Minecraft image qualification reported Java 21.0.12, Node 22.22.2, Mineflayer 4.37.1, pathfinder 2.4.5, pvp 1.3.2 and vec3 0.1.8. The bridge suite passed 14/14 tests.

The candidate image identity was `sha256:75661da87c84f474869c66a24ded79a26a8adaacf87321766221d7a8fe663cc8`.
