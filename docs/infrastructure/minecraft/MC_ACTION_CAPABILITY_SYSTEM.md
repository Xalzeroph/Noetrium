# Minecraft action capability system

## Scope

The Minecraft environment owns a provider-neutral typed action ABI. Mineflayer
is one provider implementation; downstream planners, memory systems and research methods do
not import Mineflayer or JavaScript action handlers.

The action catalog is authoritative in
`noetrium_platform/capabilities/environment/minecraft/api/contracts.py`. Each entry declares
its category, effect behavior, bounded timeout, purpose and planner-visible
argument contract. The same catalog drives Python validation, planner tool
publication, transport command support and the Mineflayer handshake check.

## Provider modules

| Module | Responsibility |
|---|---|
| `runtime.js` | Bot binding, navigation primitives, entity/inventory lookup and stable result construction |
| `movement.js` | Coordinate navigation, entity navigation and bounded retreat |
| `resources.js` | Collection, crafting, furnace operations and block placement |
| `inventory.js` | Equipment, consumption, discard/give and container transactions |
| `combat.js` | Entity/player melee, ranged attack and bounded self-defence |
| `bridge.js` | JSONL lifecycle, snapshots, routing, capability handshake and result envelopes |

The bridge has no task-planning, prompt, memory or evolution authority.

## Effect evidence

Every external task action emits exactly one `action_result` with:

- the exact requested `action_id`;
- an action object whose `tool` equals the requested action type;
- a stable outcome `status` and `code`;
- a mapping outcome containing observable before/after facts;
- a Boolean `verified` flag.

`applied` requires observed evidence of the requested effect. `rejected` means
the provider deterministically established that the requested effect was not
applied. `partial` means some progress or an unconfirmed external effect may
exist and therefore requires reconciliation. Transport acknowledgement alone
never proves an MC effect.

Internal observation queries carry no task action ID and are audit-only. They
cannot overwrite `last_action_verified` or be treated by downstream memory as successful task
experience.

### Completion and reconciliation authority

Planner intent is never completion authority. A `planner_finish` or
`last_action_verified` goal can close only when the last action receipt is accepted, its
authoritative effect certainty is `confirmed`, and an explicit verification value is not
`False`. A Boolean `verified=True` cannot override `possible`, `unknown`, or `rejected`
effect certainty; contradictory receipts therefore fail closed. Accepted-but-unconfirmed
or explicitly unverified effects remain incomplete.

Environment-to-agent receipts preserve the kernel effect certainty instead of inferring it
from a Boolean verification field: confirmed effects map to `confirmed`, possible effects
remain `possible`, rejected/no-effect outcomes map to `rejected`, and unresolved evidence
remains `unknown`. The provider effect identity is copied from the authoritative
`EffectReceipt`; it is not reconstructed from diagnostics.

Prepared-action and generic reconciliation preserve the same four-way semantics:
`APPLIED -> EFFECT_CONFIRMED`, `REJECTED -> EFFECT_REJECTED`,
`NOT_APPLIED -> NO_EFFECT`, and `UNKNOWN` produces no terminal effect truth. A missing
action-recovery record is therefore unknown, never retry-safe absence.

### Frozen JSON-array consumer contract

High-level `minecraft.build` block arrays and `minecraft.resource_plan` step arrays accept
the Participant public frozen JSON-array representation (tuple-backed) as well as the
legacy in-process list shape. Array elements remain Minecraft-validated mappings; strings,
mappings used as arrays, and malformed element/payload shapes fail closed. Environment
therefore consumes the typed immutable Participant boundary without reintroducing mutable
builtin inheritance.

## Craft and resource invariants

- Collection resolves canonical drop identities from the live block registry, verifies `canHarvest(heldItemType)` before destructive dig, and counts only expected-drop inventory/own-collection evidence. Source block identity and collected item identity are never assumed equal; unrelated positive inventory deltas do not advance `collected_count`.
- Crafting resolves the canonical registry item, uses a nearby crafting table
  or places an available one, computes recipe output per execution and verifies
  the requested inventory increase.
- Every block interaction approaches through Mineflayer PathFinder's
  GoalLookAtBlock, so proximity is not mistaken for a valid raycast or click
  surface. Every placement approaches through GoalPlaceBlock, and uses the
  exact reference face selected by that goal; the old hand-written face
  enumeration is not an execution path.
- Smelting rejects conflicting furnace contents, calculates bounded fuel use,
  closes the furnace in all paths and verifies output returned to inventory.
- Furnace clearing and chest operations close windows in `finally` paths.
- Placement verifies the resulting world block instead of treating a
  Mineflayer call return as sufficient proof.

## Combat invariants

- Targets are resolved by exact entity ID, exact player username or bounded
  name query according to the action contract.
- Melee equips the strongest available weapon, bounds pressure by actual melee `attackedTarget` events and always stops the PvP plugin.
- `attackedTarget` proves only an attack was performed. Confirmed melee damage requires `entityHurt(target, source)` attributed to this bot; unattributed hurt or attack-only evidence remains partial.
- Ranged attacks require weapon and ammunition, bound shot count/charge time,
  and use hurt/death signals for confirmation. Ammunition loss without a hit
  remains partial.
- Self-defence considers an explicit bounded hostile registry, target count and
  radius.

## Hot-path selection

A single dug-block drop capture maintains at most sixteen correlated fallback entities in
fixed slots. Spawn/drop/collect/gone events update those slots in constant time.
`pickupTarget()` checks only that fixed bounded set, preserving exact nearest-by-current-bot
distance semantics with `O(1)` worst-case work. If more than sixteen distinct entities are
correlated to one block action, the watcher records overflow and the fallback returns no
target rather than scanning unbounded world state or selecting from an incomplete set. The
normal matched `itemDrop` evidence path is unaffected.

The bound is a defensive action-local resource limit, not a claim that Mineflayer's global
entity set is constant-size. Mineflayer's documented `bot.nearestEntity(predicate)` also
selects the nearest matching entity, but this provider does not hide an unbounded scan behind
that API to satisfy complexity governance.

## Verification

Provider module tests run without a Minecraft server:

```bash
cd noetrium_platform/capabilities/environment/minecraft/providers/assets/mineflayer_bridge
npm ci
node --test actions.test.js
```

Python contract, transport, state/evidence and planner tests are in
`tests/test_minecraft_environment_v1.py`,
`tests/test_sem_minecraft_evidence_v1.py`,
`tests/test_sem_minecraft_runtime_adapter_v1.py` and
`tests/test_sem_model_planner_v1.py`.

A real Java server smoke remains a separate environment qualification step. It
never silently substitutes mocks for live Minecraft evidence. The operator may
provide a pinned server JAR or explicitly request official Mojang acquisition;
both routes preserve the exact content digest in the run identity. See
`MC_RUNTIME_BOOTSTRAP_AND_SCENARIOS.md` for the source-world fixture and live
smoke contract.


## Live-provider P0 invariants

- `collect_block` is non-destructive when the live block reports the held tool cannot harvest it; the grounded rejection code is `HARVEST_TOOL_REQUIRED`.
- Expected drops come from the live block/registry `drops` contract. Source-block identity and collected-item identity remain distinct.
- `goto_entity` delegates to the dynamic entity-follow primitive and verifies distance against the same live entity identity after navigation.
- Melee evidence is tiered: attack performed, bot-attributed target hurt, and target defeated are distinct facts. A polling loop iteration is never a hit.
- Read-only `observe_entities` may execute without mutating-action recovery identity; mutating/action-mode dispatch still traverses durable `ActionRecoveryJournal` admission.

Locked upstream anchors for this contract are Mineflayer 4.37.1 / release commit `03eba44`, mineflayer-pathfinder `GoalFollow(entity, range)`, prismarine-block `Block.canHarvest()` / `Block.drops`, and mineflayer-pvp `attackedTarget`. Mineflayer's typed event ABI supplies `entityHurt(entity, source)`, allowing source attribution rather than inferring damage from attack attempts.
