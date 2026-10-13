"""Provider-owned decision help for the authorized Minecraft action contracts.

This is documentation, not another action interpreter, planning policy, or
world authority. Signatures and numeric bounds come ONLY from contracts.py.
The agent receives ONE guide when it explicitly asks describe_action; default
context never includes the full catalog of long guides.
"""
from __future__ import annotations

from typing import Any, Mapping

from noetrium_platform.foundation.kernel.kernel import freeze_json, thaw_json


def _guide(
    when: str, prerequisites: str, verify: str, recovery: str,
    examples: tuple[tuple[str, Mapping[str, Any], str], ...],
    avoid: tuple[tuple[Mapping[str, Any], str], ...],
) -> Mapping[str, Any]:
    if not all((when.strip(), prerequisites.strip(), verify.strip(), recovery.strip())):
        raise ValueError("Each usage guide must explain intent, preparation, proof and recovery")
    if len(examples) < 2 or len(avoid) < 2:
        raise ValueError("Each action needs two contextual examples and two counterexamples")
    return freeze_json({
        "use_when": when,
        "prepare": prerequisites,
        "verify": verify,
        "when_not_completed": recovery,
        "few_shots": tuple({
            "only_when": situation,
            "arguments": dict(args),
            "check_afterwards": evidence,
        } for situation, args, evidence in examples),
        "counterexamples": tuple({
            "arguments": dict(args),
            "why_not": reason,
        } for args, reason in avoid),
    })


_GUIDES: Mapping[str, Mapping[str, Any]] = {
    "goto": _guide(
        "Choose exact world coordinates when the destination itself is known, not merely a block name.",
        "Use observed navigable coordinates and an arrival radius; check dimension, height and whether movement is safe. No digging or building is implied.",
        "Check returned actual position and distance to target, not only that navigation was attempted.",
        "If a path is blocked or movement is partial, reobserve and choose a new target or authorized action; do not pretend arrival.",
        (
            ("A known clear point is at (8,69,3).", {"position":{"x":8,"y":69,"z":3},"radius":2}, "Position must be within 2 blocks of target."),
            ("The agent has observed an unobstructed platform at (14,70,-1).", {"position":{"x":14,"y":70,"z":-1},"radius":1}, "Inspect actual position and movement evidence."),
        ),
        (
            ({"position":{"x":8,"y":69}}, "Missing z; an incomplete position is invalid."),
            ({"position":{"x":8000,"y":69,"z":3}}, "Never assume distant or unloaded terrain is traversable; observe first."),
        ),
    ),
    "goto_block": _guide(
        "Navigate to interaction range of a currently observed block type, without mining it.",
        "Confirm the exact registry block ID using observation or registry_search; make sure a reachable instance is within the bounded radius.",
        "Verify selected block position and final navigation state; arriving near a block does not harvest or activate it.",
        "If no reachable loaded target exists, inspect nearby blocks or change location. Buried targets require separately authorized actions.",
        (
            ("Oak logs were just observed in loaded terrain.", {"block":"oak_log","max_distance":24}, "Verify near an observed oak_log; inventory must not change merely from navigation."),
            ("A crafting table is visible and interaction is needed.", {"block":"crafting_table","max_distance":12}, "Verify within interaction range; craft is a distinct action."),
        ),
        (
            ({"block":"oak_planks"}, "Inventory item names are not proof of a physically present block."),
            ({"block":"zombie"}, "Entity names belong to goto_entity, not goto_block."),
        ),
    ),
    "goto_entity": _guide(
        "Approach a visible entity by its registered type to a bounded radius.",
        "Use observe_entities first to confirm identity, distance, current visibility and hazards.",
        "Inspect resulting distance to the entity and any partial movement; moving does not attack, trade or mount.",
        "Entities can move or despawn. If the target changes, reobserve instead of assuming old position is current.",
        (
            ("A villager is currently observed nearby.", {"entity":"villager","max_distance":20,"radius":3}, "Verify final distance before showing trades."),
            ("A cow is visible at safe range.", {"entity":"cow","max_distance":12,"radius":2}, "Verify proximity; do not assume mounting is supported."),
        ),
        (
            ({"entity":"oak_log"}, "A block is not an entity."),
            ({"entity":"villager","radius":0}, "Zero radius is outside the authorized schema and inappropriate for an entity."),
        ),
    ),
    "move_away": _guide(
        "Create physical separation from a threat or from the current location.",
        "Observe any target entity before specifying it; pick a bounded distance that does not imply an unexplored safe path.",
        "Check actual displacement and final entity separation; requested retreat alone is not proof of safety.",
        "If blocked, inspect the world and select a safe alternative. No offensive combat is automatically performed.",
        (
            ("A visible zombie is too close.", {"entity":"zombie","distance":7,"max_distance":16}, "Observe greater separation from the zombie."),
            ("The agent wants to clear its current interaction spot.", {"distance":4}, "Verify moved position, not a fabricated safe destination."),
        ),
        (
            ({"entity":"imaginary_dragon","distance":7}, "Never claim an unobserved target exists."),
            ({"distance":0}, "Requested retreat must be positive."),
        ),
    ),
    "follow_player": _guide(
        "Follow an observed player for a short controlled interval, not indefinitely.",
        "Confirm exact current player username and visibility; choose both follow distance and duration.",
        "Check updates, distance trend and end position, not a promise of continued follow after this action.",
        "Reobserve moving players and choose another bounded interval if follow is still needed.",
        (
            ("Player Alex is visible and consents to following.", {"player":"Alex","duration_s":12,"distance":3}, "Check end distance and movement updates."),
            ("Player Steve is at a nearby rendezvous.", {"player":"Steve","duration_s":5,"distance":5,"max_distance":32}, "Verify bounded following happened."),
        ),
        (
            ({"player":"Alex","duration_s":600}, "An unbounded follow period is not authorized."),
            ({"player":"unknown_user"}, "Do not invent a current visible player or username."),
        ),
    ),
    "stay": _guide(
        "Hold position for a bounded time when an explicit wait-with-position intent is needed.",
        "Choose duration under the time budget; inspect hazards before remaining stationary.",
        "Verify the action's bounded wait and any reported displacement; standing still is not task success.",
        "If interrupted or displaced, observe current position and decide whether holding position is still appropriate.",
        (
            ("Wait near a safe landmark briefly.", {"duration_s":6}, "Verify the interval completed without assuming the world stayed unchanged."),
            ("Pause for another agent's local action.", {"duration_s":15}, "Check current surroundings after the interval."),
        ),
        (
            ({"duration_s":300}, "A long open-ended hold exceeds the bounded contract."),
            ({"duration_s":0}, "Stay requires a positive duration; use wait for a zero-millisecond no-op."),
        ),
    ),
    "collect_block": _guide(
        "Collect actual dropped items from observable source blocks, OR explicitly remove a single chosen block.",
        "Use the observed exact block/drop name. Default effect=collect counts verified *items*, not mined blocks. Omit tool to let the local controller choose an already-held harvest-capable tool; set tool only when the task requires one exact already-held tool. With position, use integer x/y/z and count=1; effect=remove demands that exact target and cannot carry a tool constraint. It never crafts tools.",
        "For collect check block removal together with inventory delta, collected_count and any requested_tool/tool_constraint_verified evidence; for remove check verified world-block change even with zero drops. Partial progress is not full fulfillment.",
        "Read acceptable_tools, observed count, candidate exhaustion and navigation failure. If an exact requested tool cannot harvest the block, change the strategic plan rather than letting the Provider silently substitute another tool. Never blindly repeat a partial or uncertain effect.",
        (
            ("A visible oak_log source is accessible and two actual logs are needed.", {"block":"oak_log","count":2,"max_distance":24}, "Verify actual oak_log gain, not merely two dig attempts."),
            ("A benchmark objective explicitly requires the held stone pickaxe for one iron-ore harvest.", {"block":"raw_iron","count":1,"max_distance":24,"tool":"stone_pickaxe"}, "Verify the requested tool constraint and actual raw_iron gain."),
        ),
        (
            ({"block":"oak_planks","count":4}, "Manufactured planks may need crafting; a registry item is not necessarily a mineable world block."),
            ({"block":"stone","effect":"remove"}, "Removal without an exact observed position is forbidden; no arbitrary excavation."),
        ),
    ),
    "excavate_region": _guide(
        "Clear a small explicit loaded-world block region when the Agent has chosen the exact local geometry that must be opened.",
        "Observe the intended coordinates first. Keep the axis-aligned region within 16 blocks per axis, 128 cells total and the declared distance bound; every block must pass the provider safety oracle.",
        "Verify REGION_EXCAVATED or inspect removed_count, remaining_count and each child effect. Every physical removal is separately journaled as collect_block(effect=remove).",
        "If the region is unsafe, unobserved, out of range or the bound is reached, select a smaller/new explicit region from fresh observations; the provider will not invent a tunnel destination.",
        (
            ("A two-block-high local obstruction has been observed and the Agent chooses its exact coordinates.", {"corner_a":{"x":2,"y":64,"z":0},"corner_b":{"x":4,"y":65,"z":0},"max_blocks":6,"max_distance":16}, "Check every removed child and whether remaining_count reached zero."),
            ("One exact obstructing block should be cleared as part of an Agent-selected passage.", {"corner_a":{"x":3,"y":64,"z":1},"corner_b":{"x":3,"y":64,"z":1},"max_blocks":1}, "Confirm the exact coordinate was removed, not a neighboring block."),
        ),
        (
            ({"corner_a":{"x":0,"y":0,"z":0},"corner_b":{"x":100,"y":0,"z":0}}, "The region exceeds the bounded local extent and cannot authorize a long hidden tunnel."),
            ({"corner_a":{"x":1.5,"y":64,"z":0},"corner_b":{"x":2,"y":64,"z":0}}, "Excavation targets exact block-grid coordinates, never fractional positions."),
        ),
    ),
    "craft_item": _guide(
        "Craft a named output item from ingredients already physically present.",
        "Resolve the canonical output identifier and actual input-to-output ratio through recipe_dependencies if unknown. Obtain ingredients first; a nearby table is required for table-sized recipes.",
        "Verify crafted output in inventory_delta or produced_items. Public recipe existence is not evidence of executable current-world crafting.",
        "If materials, station or recipe is missing, inspect observed inventory and the public dependency reference; choose a new prerequisite, do not repeat unchanged craft.",
        (
            ("The inventory physically holds one oak_log and reference recipe is appropriate.", {"item":"oak_planks","count":4}, "Verify newly gained oak_planks from the actual server craft."),
            ("The required oak_planks are held and sticks are needed.", {"item":"stick","count":4}, "Check produced stick count rather than trusting a declared recipe."),
        ),
        (
            ({"item":"oak_planks","count":64}, "Do not demand arbitrary output quantity without checking batches and held inputs."),
            ({"item":"oak_log","count":4}, "Logs are typically gathered rather than crafted; check a real recipe instead of inventing one."),
        ),
    ),
    "craft_grid": _guide(
        "Test a deliberate inventory or table crafting-grid arrangement, including unknown recipes.",
        "Supply exactly four comma-separated row-major slots for inventory or nine for table; use '_' for empty cells and genuine held item names for occupied slots.",
        "Only a server-acknowledged output slot plus real inventory delta establishes output. A submitted grid is an experiment, not recipe discovery by assertion.",
        "On no output, observe resources and adjust the grid based on evidence; do not report a recipe as valid without a physical response.",
        (
            ("Four grid slots; one physically held log in top-left.", {"station":"inventory","grid":"oak_log,_,_,_"}, "Check output slot acknowledgement and actual item delta."),
            ("Nine table slots and held planks; testing a vertical pair.", {"station":"table","grid":"oak_planks,_,_,oak_planks,_,_,_,_,_"}, "Confirm station access, server response and produced item."),
        ),
        (
            ({"station":"inventory","grid":"oak_log"}, "Inventory grid must have four entries."),
            ({"station":"table","grid":"diamond,diamond"}, "Table grid must have nine entries; do not invent recipe success."),
        ),
    ),
    "smelt_item": _guide(
        "Smelt a physically held input at a currently reachable furnace with bounded waiting.",
        "Verify input quantity, usable nearby furnace and physical fuel or existing furnace burn state. Choose explicit fuel if selection is required.",
        "Inspect furnace output and inventory increase; setting furnace slots or elapsed time alone is not proof of production.",
        "If input/fuel/workstation absent, inspect holdings and furnace state. Respect max_wait_s and report partial production honestly.",
        (
            ("Raw iron and coal are held, a furnace was observed.", {"item":"raw_iron","count":2,"fuel":"coal","max_wait_s":60}, "Verify produced iron_ingot count and consumed resources."),
            ("Sand and fuel source were physically verified.", {"item":"sand","count":1,"fuel":"coal","max_distance":12,"max_wait_s":35}, "Confirm actual glass output."),
        ),
        (
            ({"item":"iron_ingot","fuel":"coal"}, "Smelt input must have a real applicable processing recipe; don't guess."),
            ({"item":"raw_iron","count":8,"max_wait_s":10}, "Short wait is not proof eight ingots finished; check actual output and fuel."),
        ),
    ),
    "enchant_item": _guide(
        "Apply one actually offered enchantment to a held item at a reachable enchanting table.",
        "Observe table availability, held item, experience and lapis; choice index refers only to a current server-provided option.",
        "Verify the item changed and the enchantment result was acknowledged, not just a menu selection.",
        "If the table, materials or option is missing, reobserve physical conditions and offered choices.",
        (
            ("An enchanting table and a valid offered option 0 are observed.", {"item":"iron_pickaxe","choice":0,"max_distance":12}, "Verify enchantment receipt and actual item state."),
            ("A valid second offered choice exists for a held sword.", {"item":"iron_sword","choice":1}, "Verify server-confirmed enchantment, not assumed level."),
        ),
        (
            ({"item":"iron_pickaxe","choice":3}, "Only indices 0 through 2 are authorized."),
            ({"item":"netherite_sword","choice":0}, "Do not assume a rare item or enough experience is held without observation."),
        ),
    ),
    "clear_furnace": _guide(
        "Retrieve existing input, fuel and output from one observed accessible furnace.",
        "Locate a nearby furnace and ensure its contents are worth reclaiming; clearing can interrupt an active process.",
        "Check returned slot state and actual inventory changes; expected contents are not guaranteed before opening.",
        "If no furnace or inventory is full, inspect the environment and adjust resource handling before retrying.",
        (
            ("An earlier smelt is finished and output remains in a furnace.", {"max_distance":12}, "Check item transfer from furnace to own inventory."),
            ("An abandoned furnace contains unneeded inputs.", {"max_distance":24}, "Verify which slots were physically cleared."),
        ),
        (
            ({"max_distance":256}, "Search bound is outside the action schema."),
            ({}, "Do not clear an active, shared furnace without an explicit Agent decision; this changes physical resources."),
        ),
    ),
    "place_block": _guide(
        "Place one physically held block either in a safe adjacent position or an exact known coordinate.",
        "Verify item exists in inventory, target is replaceable and support/interactable placement geometry is valid.",
        "Check resulting world block at the selected coordinate and inventory change; attempting placement alone proves nothing.",
        "If blocked, inspect actual support and target occupancy rather than repeating or replacing unrelated blocks.",
        (
            ("A torch is held and a nearby suitable support exists.", {"item":"torch"}, "Verify a torch was placed on an allowed surface."),
            ("A cobblestone block is held and target cell is observed empty.", {"item":"cobblestone","position":{"x":5,"y":65,"z":7}}, "Verify exactly the requested cell changed."),
        ),
        (
            ({"item":"oak_planks","position":{"x":5,"y":65,"z":7}}, "Do not place into an unobserved occupied or unsupported coordinate."),
            ({"item":"diamond"}, "An arbitrary inventory item is not necessarily a placeable block."),
        ),
    ),
    "pickup_items": _guide(
        "Pick up nearby observed ground item entities, optionally restricted to one identified item type.",
        "Observe dropped entities and use exact item name only if identified; max_items limits entities, not stack quantity.",
        "Verify matching inventory gain for a filtered request. Incidental acquisition of another item is not success.",
        "Unknown drop identity is skipped, not guessed; if no matching drop is observed, inspect a new local region.",
        (
            ("A dropped oak_log entity was observed nearby.", {"item":"oak_log","max_distance":12,"max_items":2}, "Check oak_log inventory delta specifically."),
            ("Several known nearby drops should be collected regardless of type.", {"max_distance":10,"max_items":6}, "Inspect actual collected entities and inventory delta."),
        ),
        (
            ({"item":"oak_planks"}, "An inventory recipe reference does not establish an oak_planks drop on the ground."),
            ({"item":"oak_log","max_items":50}, "The permitted max_items entity bound is 32."),
        ),
    ),
    "auto_light": _guide(
        "Place a single light source only when the observed bounded area lacks sufficient lighting.",
        "Check current local light and physically held torch; provider makes only this bounded placement, not an exploration or torch-crafting plan.",
        "Inspect placed light position and inventory delta; light level assumptions are not physical proof.",
        "If a torch or safe surface is missing, observe inventory and surroundings and choose an explicit prerequisite.",
        (
            ("A torch is held in a visibly dark and safe corridor.", {"max_distance":8}, "Confirm a torch placement or an explicit no-action result."),
            ("A dark workshop has a supported adjacent block.", {"max_distance":12}, "Verify only one intended light was placed."),
        ),
        (
            ({"max_distance":40}, "The maximum search radius is 16."),
            ({}, "Do not assume auto_light creates torches or guarantees mob-proof lighting everywhere."),
        ),
    ),
    "fish": _guide(
        "Use a held fishing rod in reachable water for a bounded number of casts.",
        "Confirm the fishing rod in inventory/hand and an appropriate observed water area; catches depend on server outcomes.",
        "Verify reported catch count and actual inventory gain; no hook motion alone confirms an item.",
        "If no catch or equipment is unavailable, inspect surroundings and current held rod rather than assuming success.",
        (
            ("A fishing rod is held and a safe pond was observed.", {"casts":2,"max_wait_s":45}, "Check item delta and confirmed catches."),
            ("One short fishing attempt is wanted near water.", {"casts":1,"max_wait_s":25}, "Record catch or no-catch as actually observed."),
        ),
        (
            ({"casts":50}, "A single request is limited to eight casts."),
            ({"casts":2,"max_wait_s":0}, "Zero wait cannot provide a valid bounded fishing attempt."),
        ),
    ),
    "equip_item": _guide(
        "Select a physically held item for a specific equipment slot before another action.",
        "Confirm item exists in observed inventory and destination is an exact enum: hand, off-hand, head, torso, legs or feet.",
        "Verify the actual equipment slot after mutation; a named registry item is not possession.",
        "If the item is absent, acquire it through a separate decision; if slot conflicts, inspect current equipment.",
        (
            ("An iron_pickaxe is physically held for mining.", {"item":"iron_pickaxe","destination":"hand"}, "Check held tool is iron_pickaxe."),
            ("A helmet is physically held.", {"item":"iron_helmet","destination":"head"}, "Check actual head slot."),
        ),
        (
            ({"item":"diamond_pickaxe","destination":"main_hand"}, "The permitted slot is hand, not main_hand."),
            ({"item":"iron_pickaxe"}, "Do not infer possession from recipes or registry; check observed stock before equip."),
        ),
    ),
    "consume_item": _guide(
        "Consume one owned usable item such as food or an applicable potion.",
        "Observe inventory and reason about health, hunger and status effects before consuming. The named item must be consumable.",
        "Verify inventory decrement and any observed health, food or potion-effect change; predicted effects are not receipts.",
        "If rejected or interrupted, inspect actual state to avoid consuming more than intended.",
        (
            ("Food is low and one bread is physically held.", {"item":"bread"}, "Verify one bread consumed and food response."),
            ("A usable healing potion is held and consumption is intended.", {"item":"potion"}, "Check server-acknowledged use and subsequent status."),
        ),
        (
            ({"item":"diamond"}, "A diamond is not a normal consumable."),
            ({"item":"bread","count":5}, "Consume is a single-use action; count is not an authorized parameter."),
        ),
    ),
    "discard_item": _guide(
        "Drop a selected count of a physically owned item from inventory into the world.",
        "Verify exact canonical item ID, available stack quantity, and whether the area is safe for dropping.",
        "Confirm inventory decrease and item-drop evidence; dropping does not guarantee another player picked it up.",
        "If the item is absent or effect uncertain, reobserve inventory before any repeated discard to avoid double loss.",
        (
            ("One expendable dirt block is held.", {"item":"dirt","count":1}, "Verify inventory decreased by one."),
            ("Two cobblestone should be released deliberately.", {"item":"cobblestone","count":2}, "Verify actual count dropped."),
        ),
        (
            ({"item":"diamond","count":64}, "Do not discard valuable or unverified holdings merely because an item is named."),
            ({"item":"dirt","count":0}, "Count must be positive; zero is not an authorized discard."),
        ),
    ),
    "give_item": _guide(
        "Deliver owned inventory items to a currently visible named player by approaching and dropping them.",
        "Verify exact player identity, visibility, item possession and intended quantity; giving involves movement and item loss.",
        "Confirm own inventory reduction and provider drop/delivery receipts. A drop near a player is not automatically a confirmed pickup.",
        "If the player moves or collection is uncertain, inspect current location and inventory before attempting again.",
        (
            ("Alex is visible and one apple is held for transfer.", {"player":"Alex","item":"apple","count":1}, "Check own inventory decrement and interaction outcome."),
            ("Steve is nearby and needs two cobblestone.", {"player":"Steve","item":"cobblestone","count":2}, "Verify bounded transfer attempt to Steve."),
        ),
        (
            ({"player":"Alex","item":"diamond","count":64}, "Do not assume the inventory holds the offered quantity."),
            ({"player":"nonexistent","item":"dirt"}, "A username string does not prove the player is actually visible."),
        ),
    ),
    "chest_inspect": _guide(
        "Read the contents of one nearby observable chest, trapped chest or barrel without transferring items.",
        "Observe a physically accessible container; search distance limits which loaded candidate is inspected.",
        "Check the actual returned container inventory and identity; inspection is not withdrawal and does not grant items.",
        "If none found, move or observe a new area. Do not assume contents from another container.",
        (
            ("A chest is seen within eight blocks.", {"max_distance":8}, "Inspect returned item slots; own inventory stays unchanged."),
            ("A nearby barrel contains uncertain supplies.", {"max_distance":16}, "Read server-observed contents only."),
        ),
        (
            ({"max_distance":200}, "The search bound exceeds the authorized schema."),
            ({}, "Never treat a previously viewed container as unchanged without refreshing observation."),
        ),
    ),
    "chest_deposit": _guide(
        "Transfer an exact count of a held item into a reachable container.",
        "Confirm own item quantity and target container location; inspect capacity if uncertain before depositing.",
        "Verify own inventory decreases and container gains; an opened chest alone is not a completed deposit.",
        "If container is full, missing or action partial, reobserve both inventories before another transfer.",
        (
            ("Two oak_logs are held and a chest is within range.", {"item":"oak_log","count":2,"max_distance":12}, "Confirm two logs transferred into the selected container."),
            ("A safe nearby barrel will store one iron_ingot.", {"item":"iron_ingot","count":1,"max_distance":8}, "Inspect before/after item counts."),
        ),
        (
            ({"item":"oak_log","count":50}, "Do not request more than verified available inventory."),
            ({"item":"oak_log","count":1,"container_id":19}, "Arbitrary container_id is not in this action's schema."),
        ),
    ),
    "chest_withdraw": _guide(
        "Retrieve a requested count of an observed item from a nearby physical container.",
        "Inspect chest contents and capacity first; confirm canonical item and available stack count.",
        "Verify own inventory gain AND container inventory reduction; seeing an item in a container is not possession.",
        "If missing stock or inventory space, refresh container state and choose another action before retrying.",
        (
            ("Chest inspection confirmed three oak_logs.", {"item":"oak_log","count":2,"max_distance":12}, "Confirm two logs enter own inventory."),
            ("Barrel contents show one coal.", {"item":"coal","count":1,"max_distance":8}, "Verify real withdrawal."),
        ),
        (
            ({"item":"diamond","count":64}, "A registry name or stale inspection does not prove available chest stock."),
            ({"item":"coal","count":-1}, "Negative withdrawal count is invalid."),
        ),
    ),
    "till_and_sow": _guide(
        "Prepare one viable soil location and place one physically held seed.",
        "Observe valid dirt/grass farmland conditions, support and available seed in inventory.",
        "Verify both tilling and crop/seed placement in world; removing a seed from inventory alone is incomplete.",
        "If soil or seed is missing, reobserve and use separate acquisition/positioning decisions.",
        (
            ("Wheat seeds are held near observed grass with open space above.", {"seed":"wheat_seeds","max_distance":12}, "Verify changed farmland and planted wheat."),
            ("Carrot is held for planting at prepared soil.", {"seed":"carrot","max_distance":10}, "Verify crop block and consumed seed."),
        ),
        (
            ({"seed":"oak_log"}, "A log is not a plantable seed."),
            ({"seed":"wheat_seeds","max_distance":100}, "The action's bounded soil search is at most 32."),
        ),
    ),
    "attack_nearest": _guide(
        "Attack the nearest currently visible mob of one registered entity type for bounded hits.",
        "Observe nearby threats and exact entity type; inspect equipment, health, distance and whether violence is intended.",
        "Check hit/own-hurt signals, target state and actual effects; swinging is not guaranteed damage or kill.",
        "If target unavailable or danger increases, reobserve or retreat under a separately chosen action.",
        (
            ("A zombie has been observed within 10 blocks and combat is authorized.", {"entity":"zombie","max_distance":10,"max_hits":3}, "Check confirmed own damage and target visibility."),
            ("One spider is a deliberate combat target.", {"entity":"spider","max_distance":12,"max_hits":2}, "Inspect hit receipts and own health."),
        ),
        (
            ({"entity":"oak_log"}, "Blocks are not combat entity targets."),
            ({"entity":"zombie","max_hits":100}, "A single request is bounded to at most 20 hits."),
        ),
    ),
    "attack_entity": _guide(
        "Precisely attack one currently observed entity ID, not an unspecified nearest mob.",
        "Use a fresh observe_entities result to identify numeric entity_id; ensure line of sight, range and combat intent.",
        "Verify effects on the exact entity ID and own health; do not substitute another target when entity disappears.",
        "If ID is stale or target vanished, reobserve before requesting a different entity ID.",
        (
            ("Entity 42 is an observed hostile zombie.", {"entity_id":42,"max_distance":12,"max_hits":2}, "Verify the same entity receives confirmed attack effects."),
            ("Entity 87 was freshly identified as the intended mob.", {"entity_id":87,"max_distance":8,"max_hits":1}, "Confirm targeted swing and feedback."),
        ),
        (
            ({"entity_id":"zombie"}, "Exact entity ID must be an integer, not a type string."),
            ({"entity_id":999999}, "Never assume an arbitrary ID corresponds to a live target."),
        ),
    ),
    "attack_player": _guide(
        "Attack one currently observed player by exact username in an authorized PvP scenario.",
        "Confirm player identity, visibility, combat authorization and current health/equipment; a username alone is not physical presence.",
        "Inspect actual target damage signals and own state; weapon swings do not prove a PvP hit.",
        "If the player disappears, PvP is prohibited or effect uncertain, stop and re-evaluate before another action.",
        (
            ("PvP is explicitly permitted and player Alex is observed as an opponent.", {"player":"Alex","max_distance":12,"max_hits":1}, "Check target-specific attack feedback."),
            ("Steve is an authorized duel opponent within reach.", {"player":"Steve","max_distance":8,"max_hits":2}, "Verify bounded hits, not assumed elimination."),
        ),
        (
            ({"player":"unknown","max_hits":1}, "An unverified username does not identify a present opponent."),
            ({"player":"Alex","max_hits":100}, "Exceeds the 40-hit action limit and intended bounded PvP."),
        ),
    ),
    "ranged_attack": _guide(
        "Fire bounded bow/crossbow shots toward a visible entity with a physically held compatible weapon/ammo.",
        "Observe the exact entity type and current position, line of sight and adequate projectiles; the provider owns charge timing.",
        "Verify fired projectiles and hit evidence separately. A shot is not proof of damage, death or drop.",
        "If line of sight, projectile supply or target tracking fails, inspect state before further shots.",
        (
            ("A skeleton is visible at safe range, bow and arrows held.", {"entity":"skeleton","max_distance":24,"shots":1}, "Check shot and actual hit signals."),
            ("A visible zombie is targeted with a loaded crossbow.", {"entity":"zombie","max_distance":20,"shots":2}, "Verify consumed ammo and observed effects."),
        ),
        (
            ({"entity":"stone","shots":1}, "A block is not a ranged entity target."),
            ({"entity":"zombie","shots":30}, "The contract allows at most eight shots per call."),
        ),
    ),
    "fire_projectile": _guide(
        "Physically use a held bow or crossbow when the intended action is firing itself and no target selection is required.",
        "Confirm the exact ranged weapon and enough compatible ammunition are physically held; current yaw/pitch define the firing direction.",
        "Verify PROJECTILES_RELEASED, exact weapon, shots_released and ammunition consumption. This action never proves a hit, kill or benchmark success by itself.",
        "If weapon, ammunition or release evidence is missing, inspect holdings before another explicit firing decision; never infer a target or silently switch to melee.",
        (
            ("A bow and at least one arrow are held and the intended physical act is to fire it.", {"weapon":"bow","shots":1}, "Confirm bow use from release and ammunition evidence without claiming a hit."),
            ("A compatible ranged weapon is already held and one target-independent shot is intended.", {"shots":1}, "Check which weapon and ammunition the provider actually used."),
        ),
        (
            ({"weapon":"trident","shots":1}, "This primitive supports bow or crossbow use only; trident has different physical semantics."),
            ({"weapon":"bow","shots":30}, "One local firing action is bounded to at most eight shots."),
        ),
    ),
    "defend_self": _guide(
        "Engage a bounded number of nearby hostile mobs only when this defensive scope is authorized.",
        "Inspect visible hostile entities, own health and equipped gear; radius and hit/target limits cap work, not risk.",
        "Check each reported target and real attack effects; never treat defense invocation as a guarantee of safety.",
        "If overwhelmed, evaluate retreat and equipment decisions using fresh observations instead of repeated blind defense.",
        (
            ("Two nearby hostile zombies threaten the agent.", {"radius":10,"max_targets":2,"max_hits":6}, "Inspect which targets actually received damage."),
            ("One close hostile spider needs immediate bounded response.", {"radius":6,"max_targets":1,"max_hits":3}, "Verify own and target effects."),
        ),
        (
            ({"radius":100,"max_targets":25}, "Radius and target bounds exceed authorized limits."),
            ({}, "Do not treat default defense as a universal kill-all or as permission to attack peaceful entities."),
        ),
    ),
    "use_shield": _guide(
        "Raise a physically held shield in the off hand for one bounded defensive interval without choosing a broader combat plan.",
        "Confirm a shield is present in verified inventory and that the current situation actually calls for blocking rather than attacking or retreating.",
        "Verify the shield is equipped off hand, the provider entered held-item use for the requested interval, and the use state was cleanly released.",
        "If no shield is available, activation is unconfirmed, or the interval is interrupted, reobserve equipment and threat state before another decision.",
        (
            ("A shield is held and a nearby hostile may attack during the next second.", {"duration_ms":1000}, "Check SHIELD_USED evidence and current health/threat state afterwards."),
            ("A skeleton is visible and a short defensive hold is intended before the next planning decision.", {"duration_ms":1500}, "Verify off-hand activation completed and then reobserve the attacker."),
        ),
        (
            ({"duration_ms":50}, "The duration is below the action contract minimum and cannot establish a bounded shield-use interval."),
            ({"duration_ms":20000}, "The duration exceeds the per-action bound; long defense requires another explicit Agent decision."),
        ),
    ),
    "mount": _guide(
        "Try to mount one currently observed and deliberately selected entity.",
        "Confirm nearby physical entity type, chosen target and appropriate game constraints; do not assume every entity can be ridden.",
        "Verify actual vehicle/mounted state, not merely that the client issued an interaction.",
        "If mounting fails, inspect entity state and possible prerequisites before another distinct decision.",
        (
            ("A horse is observed nearby and mounting is intended.", {"entity":"horse","max_distance":10}, "Check actual vehicle state after interaction."),
            ("A boat entity is visible and chosen for riding.", {"entity":"boat","max_distance":8}, "Verify mounted state without assuming success."),
        ),
        (
            ({"entity":"stone"}, "A block is not a mountable entity."),
            ({"entity":"zombie"}, "Do not infer rideability from a registry entity name."),
        ),
    ),
    "dismount": _guide(
        "Leave the currently mounted boat, horse or other vehicle.",
        "Verify from live state that the agent is actually riding; dismount has no parameters.",
        "Confirm the vehicle state cleared and that agent position is valid after dismount.",
        "If not mounted or a world transition is pending, reobserve instead of assuming safe ground.",
        (
            ("A horse is currently the agent's verified vehicle.", {}, "Check vehicle is no longer attached."),
            ("The agent is riding a boat beside a safe shore.", {}, "Confirm separate agent position after leaving the boat."),
        ),
        (
            ({"entity":"horse"}, "Dismount accepts no entity argument; it acts on the current vehicle."),
            ({"force":True}, "Force and arbitrary teleport semantics are not supported."),
        ),
    ),
    "use_door": _guide(
        "Open a currently observed accessible door, not an arbitrary surrounding structure.",
        "Observe a nearby door within range, including current open state and safe movement path.",
        "Verify the door open-state observation; merely interacting does not guarantee the doorway is clear.",
        "If blocked or door absent, reobserve the exact block and choose whether to move or interact again.",
        (
            ("A wooden door is observed two blocks ahead.", {"max_distance":6}, "Check door state changed to open."),
            ("A closed village door is visible nearby.", {"max_distance":12}, "Verify one selected door's observed result."),
        ),
        (
            ({"max_distance":128}, "The maximum bounded door range is 32."),
            ({"block":"oak_door"}, "This action has no block selector: do not pretend it opens a specified remote door."),
        ),
    ),
    "go_to_bed": _guide(
        "Approach an observed bed and request sleep for a bounded interval.",
        "Observe a bed, whether it is accessible, and current dimension/time constraints.",
        "Check the server's actual sleep state or reason for rejection; bed proximity alone is not successful sleep.",
        "If sleeping is not permitted now, do not loop forever: observe time, dangers and bed availability.",
        (
            ("A bed is within eight blocks at nighttime.", {"max_distance":8,"max_wait_s":30}, "Verify server-confirmed sleep result."),
            ("The agent sees a nearby village bed.", {"max_distance":16,"max_wait_s":40}, "Check whether the bed was actually usable."),
        ),
        (
            ({"max_wait_s":120}, "Sleep wait is limited to 60 seconds."),
            ({"max_distance":4}, "Do not assume every visible bed is unoccupied or that daytime sleeping is allowed."),
        ),
    ),
    "activate_nearest_block": _guide(
        "Activate one nearby observed interactive block by canonical block name.",
        "Observe the target type and location (button, lever, trapdoor or other supported interaction); choose a safe physical interaction.",
        "Verify the server-confirmed block-state transition where observable; sending activation is not proof of a lasting effect.",
        "If block is out of range or state unchanged, inspect the actual target; no hidden redstone outcome is inferred.",
        (
            ("A stone_button was observed within reach.", {"block":"stone_button","max_distance":6}, "Check actual activation acknowledgement."),
            ("An oak_trapdoor is observed in a reachable hallway.", {"block":"oak_trapdoor","max_distance":10}, "Verify changed open state if available."),
        ),
        (
            ({"block":"zombie"}, "An entity is not an interactive block."),
            ({"block":"lever","max_distance":90}, "The bounded interaction distance must be at most 32."),
        ),
    ),
    "show_villager_trades": _guide(
        "Read the current trade offers of an observed adult employed villager.",
        "Locate an accessible eligible villager. Prices, stock and trade availability must come from current server observation.",
        "Verify returned offer list and item names. Viewing offers does not transfer currency or items.",
        "If no offers exist, reobserve villager profession and access; don't fabricate trade indices.",
        (
            ("A librarian villager is observed close by.", {"max_distance":10}, "Inspect exact trade list, cost and output."),
            ("A farmer villager is visibly nearby.", {"max_distance":16}, "Read current server offers before making a purchase."),
        ),
        (
            ({"max_distance":100}, "The authorized range is at most 32."),
            ({"trade_index":0}, "This action is read-only; use trade_villager to make a deliberate trade."),
        ),
    ),
    "trade_villager": _guide(
        "Execute a chosen number of trades using a server-observed offer index.",
        "Call show_villager_trades and inspect current indexed offer, necessary inputs and available inventory before trading.",
        "Verify input deduction, output gain and confirmed trade count; selecting an index alone is not proof.",
        "Trades can be depleted or repriced. If rejected, reobserve offers instead of repeating stale indices.",
        (
            ("Offer index 0 was observed and its price is physically held.", {"trade_index":0,"max_trades":1,"max_distance":10}, "Check actual traded input and output."),
            ("Offer index 2 remains available for two verified purchases.", {"trade_index":2,"max_trades":2,"max_distance":12}, "Check trade completion and current stock."),
        ),
        (
            ({"trade_index":99}, "Do not invent a trade index not observed in the current offers."),
            ({"trade_index":0,"max_trades":100}, "Maximum trades per action is 16; do not assume adequate stock."),
        ),
    ),
    "use_tool_on": _guide(
        "Use the currently equipped item on an observed block or entity to request a specific interaction.",
        "Observe exact target type and held tool. target_type should be block or entity if ambiguity exists; effects are environment-specific.",
        "Verify the resulting block/entity state and item change; sending an interaction is not proof of transformation.",
        "When unsupported or ineffective, inspect tool/target compatibility and new world state before another attempt.",
        (
            ("A tree trunk is observed and an appropriate held item should be used on it.", {"target":"oak_log","target_type":"block","max_distance":8}, "Check returned interaction and actual block changes."),
            ("A sheep is observed and the agent holds the intended tool.", {"target":"sheep","target_type":"entity","max_distance":10}, "Verify any actual target/item effects."),
        ),
        (
            ({"target":"oak_log","target_type":"player"}, "target_type must be block or entity."),
            ({"target":"diamond_block"}, "A name alone does not prove the target is present or that the held tool has an effect."),
        ),
    ),
    "wait": _guide(
        "Wait for an explicitly bounded number of milliseconds when no physical action should be performed.",
        "Choose a duration consistent with the remaining time budget and any dangers in the current location.",
        "Verify elapsed bounded wait and refresh observations before decisions depending on changes during wait.",
        "An empty result does not imply work progressed; do not use wait as a substitute for crafting, mining or sleeping.",
        (
            ("A mechanism may finish shortly after triggering.", {"ms":250}, "Reobserve its physical state after waiting."),
            ("A bounded delay is explicitly needed before new sensing.", {"ms":1000}, "Verify only the elapsed wait, not a fabricated event."),
        ),
        (
            ({"ms":60000}, "The API limits one wait to 10,000 milliseconds."),
            ({"seconds":5}, "Use ms, not an invented seconds argument."),
        ),
    ),
    "chat": _guide(
        "Send one ordinary text message through Minecraft chat.",
        "Choose intentional text; this is a physical communication effect, not a way to bypass tool permissions or execute server commands.",
        "Verify bridge/server acknowledgement; do not assume a player read or obeyed the message.",
        "If rejected, check chat permissions and session state; avoid resending identical messages blindly.",
        (
            ("The Agent is announcing its arrival in a cooperative session.", {"message":"I reached the camp."}, "Check chat send receipt only."),
            ("The Agent wants to ask another player a question.", {"message":"Do you have spare wheat seeds?"}, "Check message was sent, not that a reply exists."),
        ),
        (
            ({"message":"/give @p diamond 64"}, "Do not treat chat as an authorized admin-command or inventory grant."),
            ({"message":""}, "Empty text is not a meaningful chat action."),
        ),
    ),
    "observe_blocks": _guide(
        "Sense bounded currently loaded blocks by scan, or inspect one exact block-grid coordinate without movement or chunk loading.",
        "Use query/limit for a bounded survey. Use position alone with max_distance when exact local geometry matters; exact mode is O(1) and cannot be combined with query or limit.",
        "For scans read observed names, positions and counts. For exact mode read observed/block or the explicit local constraint; neither mode proves harvestability or unloaded-world absence.",
        "If an exact coordinate is unobserved/out of range, reposition or choose another explicit observation. The provider will not load a hidden chunk or infer the block from registry data.",
        (
            ("Locate actual oak_log candidates near the agent.", {"query":"oak_log","max_distance":24,"limit":20}, "Inspect precise observed block positions and names."),
            ("Inspect one observed corridor coordinate before choosing excavation geometry.", {"position":{"x":2,"y":64,"z":0},"max_distance":16}, "Use only the returned live block or explicit unobserved constraint."),
        ),
        (
            ({"query":"oak_log","position":{"x":2,"y":64,"z":0}}, "Exact-position mode is exclusive with query/limit; do not mix scan and point inspection semantics."),
            ({"max_distance":256,"limit":100}, "Requested observation radius exceeds the 128-block schema bound."),
        ),
    ),
    "observe_entities": _guide(
        "Refresh real nearby entity and player observations before interacting, attacking or following.",
        "Use a bounded range and result limit; entity positions and identifiers can become stale immediately.",
        "Read exact entity IDs/types, distance and other public visible state; observing does not imply successful interaction.",
        "If no match, reobserve elsewhere instead of creating or inferring a target from registry existence.",
        (
            ("An exact mob ID is needed for a precision action.", {"max_distance":16,"limit":30}, "Use only actual returned entity IDs."),
            ("Check whether villagers and hostile mobs are currently nearby.", {"max_distance":24,"limit":50}, "Inspect observed types and relative positions."),
        ),
        (
            ({"query":"zombie"}, "This action has no query argument; filter observed returned entities in the Agent."),
            ({"max_distance":200}, "Observation radius exceeds the 128-block cap."),
        ),
    ),
    "registry_search": _guide(
        "Resolve canonical names of public item, block or entity types before constructing an exact-name action.",
        "Provide a meaningful textual query; public registry knowledge never establishes inventory or current-world presence.",
        "Check candidate canonical names and their classes; follow with physical observation or inventory check before mutation.",
        "If no canonical match, correct the spelling or use observed names rather than inventing an ID.",
        (
            ("The Agent is unsure whether oak planks is plural.", {"query":"oak plank","limit":10}, "Verify canonical oak_planks before crafting."),
            ("The Agent needs the canonical entity name for a nearby mob.", {"query":"villager","limit":8}, "Separate registry name from actual observed villager."),
        ),
        (
            ({"query":"diamond","limit":100}, "Registry existence does not grant diamonds or prove them physically nearby."),
            ({"query":""}, "An empty lookup cannot resolve a meaningful canonical name."),
        ),
    ),
    "recipe_lookup": _guide(
        "Inspect declared version-pinned vanilla crafting recipes, not current-world executable recipes.",
        "Use a canonical item name; verify against inventory and actual server behavior before asserting materials can produce output.",
        "Read alternative recipes and output batches as reference only. Hidden datapacks and world changes are outside this observation.",
        "If no vanilla recipe exists, investigate noncrafting acquisition methods; never infer global impossibility.",
        (
            ("The Agent needs the public recipe variants for sticks.", {"item":"stick","limit":8}, "Read input requirements and per-craft output quantity."),
            ("The Agent wants vanilla recipe information for a wooden pickaxe.", {"item":"wooden_pickaxe","limit":12}, "Check listed ingredients before computing physical shortages."),
        ),
        (
            ({"item":"oak_log"}, "No vanilla crafting recipe does not mean a log is unavailable; it may be gathered."),
            ({"item":"oak_planks","count":4}, "Use recipe_dependencies for quantity-aware shortages; count is not a recipe_lookup parameter."),
        ),
    ),
    "recipe_dependencies": _guide(
        "Compute reference alternatives and missing ingredients for a desired quantity using public vanilla recipes plus observed inventory.",
        "First identify a canonical output item and quantity. Treat the declared recipe tree separately from physical inventory and source reachability.",
        "Read output-per-craft, batch counts, alternative input profiles and current inventory shortages. No generated plan or actual craft is implied.",
        "If reference prerequisites conflict with the server/datapack or local sources, use direct observations and actual effects to revise your plan.",
        (
            ("Goal is four sticks and current wood inventory is known.", {"item":"stick","count":4}, "Compare ingredient ratios with current holdings before choosing collection."),
            ("Goal is eight oak_planks and actual logs are held.", {"item":"oak_planks","count":8}, "Compute required input batches and unmet quantities from reference."),
        ),
        (
            ({"item":"stick","count":0}, "Quantity must be positive."),
            ({"item":"oak_planks","count":4}, "Do not treat returned shortage candidates as a confirmed reachable resource or executable recipe."),
        ),
    ),
    "describe_action": _guide(
        "Request the full authorized description of ONE unfamiliar action, including parameter schema and decision-use examples.",
        "Specify an action_type that is present in the current Authority-supplied action catalog; this cannot enumerate unauthorized actions.",
        "Read the returned parameter names, bounds, applicability, few-shots and counterexamples as declared documentation only.",
        "If action help is rejected, do not guess or bypass Authority; choose a different authorized action or inspect current capabilities.",
        (
            ("The Agent does not know how to request exact block removal.", {"action_type":"collect_block"}, "Read effect, position and count restrictions before selecting an action."),
            ("The Agent is unsure how to configure furnace fuel and waiting.", {"action_type":"smelt_item"}, "Read current authorized schema and preconditions."),
        ),
        (
            ({"action_type":"invented_root_permission"}, "Do not invent an action or expect help to reveal unauthorized capabilities."),
            ({}, "An exact action_type is required; this is not a bulk-dump endpoint."),
        ),
    ),
}


def minecraft_action_usage_guide(action_type: str) -> dict[str, Any]:
    """Return the immutable declared handbook entry for one authorized action.

    Caller must enforce authorization BEFORE calling this lookup. Neither
    examples nor counterexamples are executable commands or live-world facts.
    """
    if not isinstance(action_type, str) or action_type not in _GUIDES:
        raise ValueError("No public usage guide exists for this action")
    return thaw_json(_GUIDES[action_type])


def minecraft_action_usage_guide_types() -> frozenset[str]:
    """Used by catalog conformance checks to guarantee all actions documented."""
    return frozenset(_GUIDES)


def minecraft_action_handbook_markdown() -> str:
    """Render the human-readable reference from the SAME authorized contracts.

    The Markdown file in docs/ is generated, not a second authored catalog.
    """
    import json

    from . import minecraft_action_catalog

    lines = [
        "# Minecraft Agent Action Handbook",
        "",
        "Generated from the single Noetrium Minecraft action catalog and "
        "its provider-owned usage guides. Do not edit this file directly.",
        "",
        "Examples are hypothetical, **not automatic instructions**. Confirm "
        "current inventory, observed targets, Authority permissions and "
        "effect receipts for every real invocation. Public recipes and "
        "registered names are not proof of current-world availability.",
        "",
    ]
    for contract in minecraft_action_catalog():
        name = contract.action_type
        guide = minecraft_action_usage_guide(name)
        lines.extend((
            f"## `{name}`",
            "",
            f"**Category:** `{contract.category}`. "
            f"**Physical mutation:** `{contract.mutates_world}`.",
            "",
            f"**Arguments:** `{contract.arguments}`.",
            "",
            f"**Purpose:** {contract.description}",
            "",
        ))
        for header, key in (
            ("When to use", "use_when"),
            ("Before invoking", "prepare"),
            ("What counts as success", "verify"),
            ("Failure or partial effect", "when_not_completed"),
        ):
            lines.extend((f"**{header}:** {guide[key]}", ""))
        for index, item in enumerate(guide["few_shots"], 1):
            action = {"action_type": name, "arguments": item["arguments"]}
            lines.extend((
                f"### Few-shot {index}",
                "",
                f"Context: {item['only_when']}",
                "",
                "```json",
                json.dumps(action, sort_keys=True, ensure_ascii=False),
                "```",
                "",
                f"Evidence to inspect: {item['check_afterwards']}",
                "",
            ))
        for index, item in enumerate(guide["counterexamples"], 1):
            action = {"action_type": name, "arguments": item["arguments"]}
            lines.extend((
                f"### Forbidden or mistaken example {index}",
                "",
                "```json",
                json.dumps(action, sort_keys=True, ensure_ascii=False),
                "```",
                "",
                f"**Do not do this:** {item['why_not']}",
                "",
            ))
    return "\n".join(lines).rstrip() + "\n"


__all__ = [
    "minecraft_action_usage_guide",
    "minecraft_action_usage_guide_types",
    "minecraft_action_handbook_markdown",
]
