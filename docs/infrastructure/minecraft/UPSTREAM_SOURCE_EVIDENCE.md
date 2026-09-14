# Minecraft upstream source evidence

## Locked dependency

- Upstream repository: `PrismarineJS/mineflayer`.
- Locked Mineflayer version: `4.37.1`.
- Official release commit recorded by the workspace source audit: `03eba44`.
- Cached official tag archive SHA-256: `AA2728EB1FC5850CDBACBDC0480EC6DA7ADFCED855836427BB4A5DA3B38C2CF6`.
- Local bridge package requires Node `>=22` and pins Mineflayer exactly to `4.37.1`.

This evidence is the source lock for Minecraft provider changes. The cached archive is an immutable read-only input; provider behavior must not be inferred from an unpinned latest package.

## Upstream design absorption

The bridge uses the locked Mineflayer ecosystem as its execution substrate and reimplements the higher-level policy inside Noetrium:

- mineflayer-pathfinder 2.4.5 supplies GoalFollow for moving entities, GoalLookAtBlock for every block interaction, GoalPlaceBlock for placement, and bestHarvestTool for tool ranking. The provider never replaces these with a second navigation or tool-selection framework.
- mineflayer-collectblock informed the dynamic target refresh and interaction-aware approach model, but its task loop is not imported. Noetrium retains its own bounded drop correlation and durable action/effect receipts.
- Voyager/MindCraft-style skill composition informed the separation between primitive provider actions and higher-level planning. Their agent loops, prompts and skill stores are not runtime dependencies of the bridge.

The resulting rule is strict: Mineflayer APIs own transport and world interaction; Noetrium owns action identity, bounded policy, verification and recovery.

## Upstream semantics used by the provider

The locked Mineflayer API exposes separate entity lifecycle events including `entitySpawn`, `itemDrop`, and `playerCollect(collector, collected)`. The official API also defines `bot.nearestEntity(predicate)` as nearest matching-entity selection. The provider uses these semantics only as observations/selection meaning: it does not hide an unbounded global entity scan behind that helper. Drop association remains action-local and bounded; a transport/event occurrence by itself is not durable external-effect certainty.

The locked connection lifecycle forwards client error/end state to bot lifecycle events. Upstream promise/timeout helpers are process-local and do not provide crash-durable intent, exactly-once execution, or action reconciliation. Noetrium therefore owns the durable action-recovery journal and must preserve `UNKNOWN` when durable external-effect evidence is absent or corrupt.

## Local extension and non-degradation rule

The local provider intentionally adds stronger semantics than upstream:

- action request and provider identity binding;
- crash-durable action recovery and four-way reconciliation;
- environment/effect receipts that retain confirmed/possible/rejected/unknown certainty;
- drop association that keeps Mineflayer event semantics while bounding one block action to sixteen fallback candidates; nearest-by-current-bot-distance selection is exact within that fixed set, and correlation overflow fails closed instead of scanning unbounded world state.

Any future Mineflayer version change must repeat the exact-version source audit before changing lifecycle, entity, pathfinding, inventory, combat, or recovery behavior.
