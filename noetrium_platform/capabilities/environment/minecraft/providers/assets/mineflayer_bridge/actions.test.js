'use strict'

const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const test = require('node:test')
const { Vec3 } = require('vec3')

const combat = require('./combat')
const interactions = require('./interactions')
const inventory = require('./inventory')
const movement = require('./movement')
const resources = require('./resources')
const runtime = require('./runtime')

function fakeBot (items = []) {
  const bot = new EventEmitter()
  bot._client = new EventEmitter()
  bot.entity = { id: 1, position: new Vec3(0, 64, 0), yaw: 0 }
  bot.entities = { 1: bot.entity }
  bot.inventory = Object.assign(new EventEmitter(), {
    items: () => items,
    slots: items
  })
  bot.heldItem = items[0] || { name: 'hand', type: null, count: 1, slot: 0 }
  bot.pathfinder = {
    movements: { safeToBreak: () => true },
    setMovements: () => {},
    goto: async () => {},
    bestHarvestTool: block => items.find(item =>
      typeof block.canHarvest !== 'function' || block.canHarvest(item.type)
    ) || (
      bot.heldItem &&
      (typeof block.canHarvest !== 'function' || block.canHarvest(bot.heldItem.type))
        ? bot.heldItem
        : null
    )
  }
  bot.equip = async item => { bot.heldItem = item }
  bot.findBlocks = options => {
    const block = typeof bot.findBlock === 'function' ? bot.findBlock(options) : null
    return block ? [block.position] : []
  }
  bot.tool = {
    equipForBlock: async block => {
      const best = bot.pathfinder.bestHarvestTool(block)
      if (!best || (typeof block.canHarvest === 'function' && !block.canHarvest(best.type))) {
        const error = new Error('Bot does not have a harvestable tool!')
        error.name = 'NoItem'
        throw error
      }
      await bot.equip(best, 'hand')
    }
  }
  bot.collectBlock = {
    collect: async targets => {
      for (const target of targets) {
        await bot.tool.equipForBlock(target)
        await bot.dig(target)
      }
    }
  }
  bot.world = { getBlock: () => null }
  bot.registry = { itemsByName: {}, blocksByName: {} }
  return bot
}

async function withoutMovementConstruction (callback) {
  const originalEnsureMovements = runtime.ensureMovements
  const originalWaitForPhysicsTicks = runtime.waitForPhysicsTicks
  runtime.ensureMovements = async () => {}
  runtime.waitForPhysicsTicks = count => {
    const promise = originalWaitForPhysicsTicks(count)
    const activeBot = runtime.getBot()
    const ticks = Math.max(1, Math.floor(Number(count)))
    for (let index = 0; index < ticks; index += 1) {
      setImmediate(() => activeBot.emit('physicsTick'))
    }
    return promise
  }
  const scope = runtime.createActionCancellationScope(
    'node-test-action',
    10000
  )
  try {
    return await runtime.runWithActionCancellationScope(scope, callback)
  } finally {
    runtime.ensureMovements = originalEnsureMovements
    runtime.waitForPhysicsTicks = originalWaitForPhysicsTicks
  }
}

test('domain modules expose the complete modular handler surface', () => {
  const handlers = { ...movement, ...resources, ...inventory, ...combat, ...interactions }
  assert.deepEqual(Object.keys(handlers).sort(), [
    'activate_nearest_block', 'attack_entity', 'attack_nearest', 'attack_player',
    'auto_light', 'chest_deposit', 'chest_inspect', 'chest_withdraw',
    'clear_furnace', 'collect_block', 'consume_item', 'craft_item', 'defend_self',
    'discard_item', 'dismount', 'enchant_item', 'equip_item', 'excavate_region', 'fire_projectile', 'fish', 'follow_player', 'give_item',
    'go_to_bed', 'goto', 'goto_block', 'goto_entity', 'mount', 'move_away', 'pickup_items',
    'place_block', 'ranged_attack', 'show_villager_trades', 'smelt_item', 'stay',
    'till_and_sow', 'trade_villager', 'use_door', 'use_shield', 'use_tool_on'
  ])
})

test('equip_item reports an already-satisfied equipment postcondition as no effect', async () => {
  const coal = { name: 'coal', type: 263, count: 8, slot: 0 }
  const bot = fakeBot([coal])
  let equipCalls = 0
  bot.equip = async item => { equipCalls += 1; bot.heldItem = item }
  runtime.bindBot(bot)

  const result = await inventory.equip_item({ item: 'coal', destination: 'hand' })

  assert.equal(equipCalls, 0)
  assert.equal(result.verified, false)
  assert.equal(result.outcome.status, 'satisfied')
  assert.equal(result.outcome.code, 'ITEM_ALREADY_EQUIPPED')
  assert.equal(result.outcome.goal_satisfied, true)
  assert.equal(result.effect_disposition, 'not_applied')
  assert.equal(result.outcome.equipped.name, 'coal')
})

test('use_shield verifies off-hand equipment and bounded active use', async () => {
  const shield = { name: 'shield', type: 513, count: 1, slot: 0 }
  const bot = fakeBot([shield, null, null])
  bot.health = 20
  bot.usingHeldItem = false
  bot.getEquipmentDestSlot = destination => destination === 'off-hand' ? 2 : 0
  bot.equip = async (item, destination) => {
    if (destination === 'off-hand') bot.inventory.slots[2] = item
    else bot.heldItem = item
  }
  bot.activateItem = offHand => {
    assert.equal(offHand, true)
    bot.usingHeldItem = true
  }
  bot.deactivateItem = () => { bot.usingHeldItem = false }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() =>
    inventory.use_shield({ duration_ms: 100 }))
  assert.equal(result.outcome.status, 'applied')
  assert.equal(result.outcome.code, 'SHIELD_USED')
  assert.equal(result.outcome.offhand_item, 'shield')
  assert.equal(result.outcome.activated, true)
  assert.equal(result.outcome.held_using, true)
  assert.equal(result.outcome.released, true)
  assert.equal(result.verified, true)
})

test('unknown craft item exposes registry spelling and read-only recovery without effects', async () => {
  const bot = fakeBot()
  bot.registry.itemsByName = {
    oak_planks: { id: 5, name: 'oak_planks' },
    oak_log: { id: 17, name: 'oak_log' }
  }
  bot.registry.items = Object.values(bot.registry.itemsByName)
  runtime.bindBot(bot)
  const result = await resources.craft_item({ item: 'oak_plank', count: 4 })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'UNKNOWN_ITEM')
  assert.equal(result.effect_disposition, 'rejected')
  assert.ok(result.outcome.canonical_item_candidates.some(c => c.name === 'oak_planks'))
  assert.deepEqual(result.outcome.recovery, {
    action_type: 'registry_search',
    arguments: { query: 'oak_plank', limit: 12 }
  })
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['item'],
    rejected_value: 'oak_plank',
    validity: { while_provider_instance: true }
  }])
})

test('collect_block publishes provider-stable registry rejection evidence', async () => {
  const bot = fakeBot()
  bot.registry.blocksByName = { stone: { id: 1, name: 'stone' } }
  bot.registry.itemsByName = { stick: { id: 280, name: 'stick' } }
  bot.registry.entitiesByName = {}
  runtime.bindBot(bot)
  const result = await resources.collect_block({
    block: 'definitely_not_a_registered_block_or_drop', count: 1, max_distance: 16
  })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'UNKNOWN_BLOCK_OR_DROP')
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['block'],
    rejected_value: 'definitely_not_a_registered_block_or_drop',
    validity: { while_provider_instance: true }
  }])
})

test('goto_block rejects an entity target before physical navigation', async () => {
  const bot = fakeBot()
  bot.registry.entitiesByName = { zombie: { id: 54, name: 'zombie' } }
  runtime.bindBot(bot)
  const result = await movement.goto_block({ block: 'zombie', max_distance: 32 })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'TARGET_IS_ENTITY_NOT_BLOCK')
  assert.equal(result.outcome.target_classification, 'entity')
  assert.equal(result.effect_disposition, 'rejected')
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['block'],
    rejected_value: 'zombie',
    validity: { while_provider_instance: true }
  }])
})

test('goto_block uses interaction-aware navigation for a real block', async () => {
  const bot = fakeBot()
  bot.registry.blocksByName = { crafting_table: { id: 58, name: 'crafting_table' } }
  const target = {
    name: 'crafting_table',
    position: new Vec3(4, 64, 0)
  }
  bot.findBlock = () => target
  runtime.bindBot(bot)
  const original = runtime.gotoAnyBlockVicinity
  runtime.gotoAnyBlockVicinity = async positions => ({
    target: runtime.vec(positions[0]),
    position: runtime.vec(bot.entity.position),
    distance: bot.entity.position.distanceTo(positions[0]),
    navigation_goal: 'get_to_any_block',
    candidate_count: positions.length,
    selected_candidate_index: 0
  })
  try {
    const result = await movement.goto_block({
      block: 'crafting_table',
      max_distance: 32
    })
    assert.equal(result.outcome.status, 'applied')
    assert.equal(result.outcome.code, 'BLOCK_REACHED')
    assert.equal(result.outcome.block, 'crafting_table')
    assert.equal(result.verified, true)
  } finally {
    runtime.gotoAnyBlockVicinity = original
  }
})

test('result helpers keep applied, partial and rejected semantics distinct', () => {
  assert.equal(runtime.applied('wait', {}, 'OK').verified, true)
  const partial = runtime.partial('wait', {}, 'MAYBE')
  assert.equal(partial.verified, false)
  assert.equal(partial.effect_disposition, 'applied')
  assert.equal(runtime.partial('wait', {}, 'UNCERTAIN', {}, 'unknown').effect_disposition, 'unknown')
  assert.equal(runtime.rejected('wait', {}, 'NO').outcome.status, 'rejected')
})


test('stay drift is a confirmed partial effect, not an indeterminate replay candidate', async () => {
  const bot = fakeBot()
  runtime.bindBot(bot)
  const originalSleep = runtime.sleep
  runtime.sleep = async () => {
    bot.entity.position = new Vec3(7, 64, 0)
  }
  try {
    const result = await interactions.stay({ duration_s: 1 })
    assert.equal(result.outcome.status, 'partial')
    assert.equal(result.outcome.code, 'STAY_DRIFTED')
    assert.equal(result.verified, false)
    assert.equal(result.effect_disposition, 'applied')
    assert.equal(result.outcome.moved, 7)
  } finally {
    runtime.sleep = originalSleep
  }
})

test('craft_item proves the requested inventory delta', async () => {
  const items = [{ name: 'oak_log', type: 1, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  bot.registry.itemsByName.oak_planks = { id: 2, name: 'oak_planks' }
  const recipe = { result: { count: 4 } }
  bot.recipesFor = () => [recipe]
  bot.craft = async (_recipe, executions) => {
    assert.equal(executions, 1)
    items.push({ name: 'oak_planks', type: 2, count: 4, slot: 1 })
  }
  runtime.bindBot(bot)

  const result = await resources.craft_item({ item: 'oak_planks', count: 4 })

  assert.equal(result.verified, true)
  assert.equal(result.outcome.code, 'ITEM_CRAFTED')
  assert.equal(result.outcome.crafted, 4)
})

test('place_block delegates reference-face selection to pathfinder placement navigation', async () => {
  const items = [{ name: 'torch', type: 10, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  const target = new Vec3(1, 64, 0)
  let placedName = 'air'
  let navigationCalled = false
  bot.equip = async item => { bot.heldItem = item }
  bot.blockAt = position => position.equals(target)
    ? { name: placedName, position }
    : { name: 'stone', position }
  bot.placeBlock = async (reference, face) => {
    assert.deepEqual(reference.position, new Vec3(0, 64, 0))
    assert.deepEqual(face, new Vec3(1, 0, 0))
    placedName = 'torch'
    setImmediate(() => bot.emit('physicsTick'))
  }
  const original = runtime.gotoBlockPlacement
  runtime.gotoBlockPlacement = async position => {
    navigationCalled = true
    assert.deepEqual(position, target)
    return { reference: { name: 'stone', position: new Vec3(0, 64, 0) }, face: new Vec3(1, 0, 0) }
  }
  runtime.bindBot(bot)
  try {
    const result = await withoutMovementConstruction(() => resources.place_block({
      item: 'torch',
      position: target,
      _action_timeout_ms: 2000
    }))
    assert.equal(result.verified, true)
    assert.equal(result.outcome.code, 'BLOCK_PLACED')
    assert.equal(navigationCalled, true)
  } finally {
    runtime.gotoBlockPlacement = original
  }
})

test('discard_item rejects unavailable counts and verifies exact removal', async () => {
  const items = [{ name: 'dirt', type: 3, count: 3, slot: 0 }]
  const bot = fakeBot(items)
  bot.toss = async (_type, _metadata, count) => { items[0].count -= count }
  runtime.bindBot(bot)

  const rejected = await inventory.discard_item({ item: 'dirt', count: 4 })
  assert.equal(rejected.outcome.status, 'rejected')

  const applied = await inventory.discard_item({ item: 'dirt', count: 2 })
  assert.equal(applied.verified, true)
  assert.equal(applied.outcome.before, 3)
  assert.equal(applied.outcome.after, 1)
})

test('attack actions reject missing targets without producing effects', async () => {
  runtime.bindBot(fakeBot())
  const result = await combat.attack_nearest({ entity: 'zombie', max_distance: 16, max_hits: 2 })
  assert.equal(result.verified, false)
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'TARGET_NOT_FOUND')
})

test('smelt_item verifies furnace output returned to inventory', async () => {
  const items = [
    { name: 'raw_iron', type: 4, count: 1, slot: 0 },
    { name: 'coal', type: 5, count: 1, slot: 1 }
  ]
  const bot = fakeBot(items)
  const furnaceBlock = { name: 'furnace', position: new Vec3(1, 64, 0) }
  let output = null
  const furnace = Object.assign(new EventEmitter(), {
    outputItem: () => output,
    inputItem: () => null,
    fuelItem: () => null,
    putFuel: async (_type, _metadata, count) => { items[1].count -= count },
    putInput: async (_type, _metadata, count) => {
      items[0].count -= count
      output = { name: 'iron_ingot', type: 6, count, slot: 2 }
      queueMicrotask(() => furnace.emit('update'))
    },
    takeOutput: async () => { items.push(output); output = null },
    close: () => {}
  })
  bot.findBlock = () => furnaceBlock
  bot.blockAt = () => furnaceBlock
  bot.openFurnace = async () => furnace
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.smelt_item({
    item: 'raw_iron', count: 1, fuel: 'coal', max_distance: 8, max_wait_s: 10
  }))

  assert.equal(result.verified, true)
  assert.equal(result.outcome.code, 'ITEM_SMELTED')
  assert.equal(result.outcome.produced, 1)
})

test('chest_deposit closes the container and proves inventory removal', async () => {
  const items = [{ name: 'oak_log', type: 7, count: 3, slot: 0 }]
  const bot = fakeBot(items)
  const chestBlock = { name: 'chest', position: new Vec3(1, 64, 0) }
  let closed = false
  let goalName = null
  bot.findBlock = () => chestBlock
  bot.blockAt = () => chestBlock
  bot.pathfinder.goto = async goal => { goalName = goal.constructor.name }
  bot.openContainer = async () => ({
    deposit: async (_type, _metadata, count) => { items[0].count -= count },
    close: () => { closed = true }
  })
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => inventory.chest_deposit({
    item: 'oak_log', count: 2, max_distance: 8
  }))

  assert.equal(result.verified, true)
  assert.equal(result.outcome.deposited, 2)
  assert.equal(closed, true)
  assert.equal(goalName, 'GoalLookAtBlock')
})

test('container actions consume one host provider window across navigation and protocol transactions', async () => {
  const bot = fakeBot()
  const chestBlock = { name: 'chest', position: new Vec3(1, 64, 0) }
  let closed = false
  bot.findBlock = () => chestBlock
  bot.blockAt = () => chestBlock
  bot.openContainer = async () => ({
    containerItems: () => [],
    close: () => { closed = true }
  })
  runtime.bindBot(bot)

  const originalGoto = runtime.gotoBlockInteraction
  const originalWithTimeout = runtime.withTimeout
  const observedTimeouts = []
  runtime.gotoBlockInteraction = async (_position, timeoutMs) => {
    observedTimeouts.push(['navigation', timeoutMs])
  }
  runtime.withTimeout = async (promise, timeoutMs, label) => {
    observedTimeouts.push([label, timeoutMs])
    return await promise
  }
  try {
    const result = await withoutMovementConstruction(() => inventory.chest_inspect({
      max_distance: 8, _action_provider_window_ms: 321
    }))
    assert.equal(result.verified, true)
    assert.equal(result.outcome.code, 'CONTAINER_INSPECTED')
    assert.equal(closed, true)
    assert.deepEqual(observedTimeouts.map(row => row[0]), [
      'navigation', 'CONTAINER_OPEN', 'CONTAINER_OPERATION'
    ])
    for (const [, timeoutMs] of observedTimeouts) {
      assert.ok(timeoutMs > 0 && timeoutMs <= 321)
    }
  } finally {
    runtime.gotoBlockInteraction = originalGoto
    runtime.withTimeout = originalWithTimeout
  }
})

test('combat rejects missing mineflayer-pvp instead of using a second melee engine', async () => {
  const bot = fakeBot()
  bot.entities[2] = { id: 2, name: 'zombie', position: new Vec3(1, 64, 0), isValid: true }
  runtime.bindBot(bot)

  const result = await combat.attack_entity({ entity_id: 2, max_distance: 8, max_hits: 1 })

  assert.equal(result.verified, false)
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'MINEFLAYER_PVP_UNAVAILABLE')
})


test('mineflayer-pvp combat verifies only damage attributed to this bot', async () => {
  const items = [{ name: 'iron_sword', type: 8, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  const target = { id: 2, name: 'zombie', displayName: 'Zombie', type: 'mob', isValid: true, position: new Vec3(2, 64, 0) }
  bot.entities[2] = target
  bot.equip = async item => { bot.heldItem = item }
  bot.pvp = {
    attack: entity => {
      bot.emit('entityHurt', entity, bot.entity)
      bot.emit('attackedTarget', entity)
    },
    stop: () => {}
  }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => combat.attack_nearest({ entity: 'zombie', max_distance: 8, max_hits: 1 }))
  assert.equal(result.verified, true)
  assert.equal(result.outcome.code, 'TARGET_HIT_CONFIRMED')
  assert.equal(result.outcome.attack_signals, 1)
  assert.equal(result.outcome.own_hurt_signals, 1)
})

test('mineflayer-pvp combat does not attribute third-party damage to this bot', async () => {
  const bot = fakeBot([])
  const target = { id: 2, name: 'zombie', displayName: 'Zombie', type: 'mob', isValid: true, position: new Vec3(2, 64, 0) }
  const other = { id: 99, name: 'skeleton', isValid: true, position: new Vec3(3, 64, 0) }
  bot.entities[2] = target
  bot.entities[99] = other
  bot.pvp = { attack: entity => { bot.emit('attackedTarget'); bot.emit('entityHurt', entity, other) }, stop: () => {} }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => combat.attack_nearest({ entity: 'zombie', max_distance: 8, max_hits: 1 }))
  assert.equal(result.verified, false)
  assert.equal(result.outcome.code, 'ATTACK_PERFORMED_HIT_UNCONFIRMED')
  assert.equal(result.outcome.attack_signals, 1)
  assert.equal(result.outcome.own_hurt_signals, 0)
})
test('runtime timeout cancels a hung provider operation', async () => {
  let cancelled = false
  await assert.rejects(
    runtime.withTimeout(new Promise(() => {}), 20, 'TEST_PHASE', () => { cancelled = true }),
    /TEST_PHASE_TIMEOUT/
  )
  assert.equal(cancelled, true)
})

test('dropped-item detection follows prismarine-entity without deprecated getters', () => {
  const bot = fakeBot([])
  const drop = {
    id: 2, name: 'item', displayName: 'Item', position: new Vec3(1, 64, 0), isValid: true,
    getDroppedItem: () => ({ name: 'oak_log', count: 1 }),
    get objectType () { throw new Error('deprecated objectType accessed') },
    get mobType () { throw new Error('deprecated mobType accessed') }
  }
  bot.entities[2] = drop
  runtime.bindBot(bot)
  assert.equal(runtime.isDroppedItemEntity(drop), true)
  assert.equal(runtime.findNearbyDroppedItem(new Vec3(1, 64, 0), 3), drop)
})

test('drop targeting preserves nearest-bot selection across multiple candidates', () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const block = new Vec3(3, 64, 0)
  const watcher = runtime.captureItemDropNear(block, 'oak_log', 8)
  const far = { id: 20, name: 'item', position: new Vec3(5, 64, 0), isValid: true, getDroppedItem: () => ({ name: 'oak_log' }) }
  const near = { id: 21, name: 'item', position: new Vec3(1, 64, 0), isValid: true, getDroppedItem: () => ({ name: 'oak_log' }) }
  const middle = { id: 22, name: 'item', position: new Vec3(3, 64, 0), isValid: true, getDroppedItem: () => ({ name: 'oak_log' }) }
  bot.entities[20] = far
  bot.entities[21] = near
  bot.entities[22] = middle
  bot.emit('entitySpawn', far)
  bot.emit('entitySpawn', near)
  bot.emit('entitySpawn', middle)

  assert.equal(watcher.pickupTarget(), near)
  assert.equal(runtime.findNearbyDroppedItem(block, 8), near)
  watcher.cancel()
})

test('drop targeting fails closed when one block correlation exceeds bounded capacity', () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const block = new Vec3(3, 64, 0)
  const watcher = runtime.captureItemDropNear(block, 'oak_log', 8)
  for (let id = 100; id < 117; id += 1) {
    const drop = {
      id, name: 'item', position: new Vec3(3, 64, 0), isValid: true,
      getDroppedItem: () => ({ name: 'oak_log' })
    }
    bot.entities[id] = drop
    bot.emit('entitySpawn', drop)
  }

  assert.equal(watcher.hasCandidateOverflow(), true)
  assert.equal(watcher.pickupTarget(), null)
  watcher.cancel()
})
test('itemDrop capture binds the actual drop emitted for the dug block', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const position = new Vec3(3, 64, 0)
  const watcher = runtime.captureItemDropNear(position, 'oak_log', 0.5)
  const wrong = { id: 2, name: 'item', position: position.offset(0.5, 0.5, 0.5), isValid: true, getDroppedItem: () => ({ name: 'dirt' }) }
  const correct = { id: 3, name: 'item', position: position.offset(0.5, 0.5, 0.5), isValid: true, getDroppedItem: () => ({ name: 'oak_log' }) }
  bot.emit('itemDrop', wrong)
  setImmediate(() => bot.emit('itemDrop', correct))
  assert.equal(await watcher.promise, correct)
  assert.equal(watcher.candidates.length, 2)
  assert.equal(watcher.candidates[0].entity_id, 2)
  assert.equal(watcher.candidates[0].item_name, 'dirt')
  assert.equal(watcher.candidates[0].rejection, 'ITEM_NAME_MISMATCH')
  assert.equal(watcher.candidates[0].matched, false)
  assert.equal(watcher.candidates[1].entity_id, 3)
  assert.equal(watcher.candidates[1].rejection, null)
  assert.equal(watcher.candidates[1].matched, true)
  watcher.cancel()
})

test('itemDrop capture accepts expected drop-name sets and rejects nearby unrelated items', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const position = new Vec3(3, 64, 0)
  const watcher = runtime.captureItemDropNear(position, ['cobblestone', 'raw_iron'], 0.5)
  const wrong = { id: 70, name: 'item', position: position.offset(0.5, 0.5, 0.5), isValid: true, getDroppedItem: () => ({ name: 'dirt' }) }
  const correct = { id: 71, name: 'item', position: position.offset(0.5, 0.5, 0.5), isValid: true, getDroppedItem: () => ({ name: 'cobblestone' }) }
  bot.emit('itemDrop', wrong)
  setImmediate(() => bot.emit('itemDrop', correct))
  assert.equal(await watcher.promise, correct)
  assert.equal(watcher.candidates[0].matched, false)
  assert.equal(watcher.candidates[0].rejection, 'ITEM_NAME_MISMATCH')
  assert.equal(watcher.candidates[1].matched, true)
  watcher.cancel()
})

test('itemDrop capture records out-of-radius drops without widening the association rule', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const position = new Vec3(3, 64, 0)
  const watcher = runtime.captureItemDropNear(position, 'oak_log', 0.5)
  const far = { id: 4, name: 'item', position: position.offset(1.1, 0.5, 0.5), isValid: true, getDroppedItem: () => ({ name: 'oak_log' }) }
  const correct = { id: 5, name: 'item', position: position.offset(0.5, 0.5, 0.5), isValid: true, getDroppedItem: () => ({ name: 'oak_log' }) }
  bot.emit('itemDrop', far)
  setImmediate(() => bot.emit('itemDrop', correct))
  assert.equal(await watcher.promise, correct)
  assert.equal(watcher.candidates[0].entity_id, 4)
  assert.equal(watcher.candidates[0].rejection, 'OUTSIDE_ASSOCIATION_RADIUS')
  assert.equal(watcher.candidates[0].matched, false)
  assert.equal(watcher.candidates[1].entity_id, 5)
  assert.equal(watcher.candidates[1].matched, true)
  watcher.cancel()
})

test('playerCollect only confirms collection by this bot', async () => {
  const bot = fakeBot([])
  const drop = { id: 2, name: 'item', position: new Vec3(1, 64, 0), isValid: true }
  runtime.bindBot(bot)
  const confirmed = runtime.waitForOwnCollection(drop, 500)
  bot.emit('playerCollect', { id: 99 }, drop)
  setImmediate(() => bot.emit('playerCollect', bot.entity, drop))
  assert.equal(await confirmed, true)
})

test('collect_block fulfills its requested semantic count with sequential verified effects', async () => {
  const items = []
  const bot = fakeBot(items)
  const positions = [new Vec3(2, 64, 0), new Vec3(2, 65, 0)]
  const live = [true, true]
  const blocks = positions.map((position, index) => ({
    name: 'oak_log', position, drops: [9], index
  }))
  bot.registry.items = { 9: { id: 9, name: 'oak_log' } }
  bot.findBlocks = options => positions
    .filter((position, index) => live[index] && options.matching(blocks[index]))
    .slice(0, options.count)
  bot.blockAt = position => {
    const index = positions.findIndex(value => value.equals(position))
    return live[index] ? { ...blocks[index] } : { name: 'air', position }
  }
  let digCalls = 0
  let toolCalls = 0
  bot.tool.equipForBlock = async block => {
    toolCalls += 1
    bot.heldItem = { name: 'stone_pickaxe', type: 877, count: 1, slot: 0 }
    assert.equal(block.name, 'oak_log')
  }
  bot.dig = async target => {
    digCalls += 1
    const index = positions.findIndex(value => value.equals(target.position))
    live[index] = false
    items.push({ name: 'oak_log', type: 9, count: 1, slot: index + 1 })
    bot.inventory.emit('updateSlot', index + 1)
  }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'oak_log', count: 2, max_distance: 16, _action_timeout_ms: 3000
  }))

  assert.equal(result.verified, true, JSON.stringify(result))
  assert.equal(result.effect_disposition, 'applied')
  assert.equal(result.outcome.status, 'applied')
  assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
  assert.equal(result.outcome.native_provider, 'mineflayer-direct-dig')
  assert.equal(result.outcome.candidate_strategy, 'verified-sequential-collection')
  assert.equal(result.outcome.confirmed_dig_count, 2)
  assert.equal(result.outcome.collected_count, 2)
  assert.equal(result.outcome.inventory_delta.oak_log, 2)
  assert.deepEqual(
    result.outcome.collection_steps.map(step => step.cumulative_collected_count),
    [1, 2]
  )
  assert.equal(digCalls, 2)
  assert.equal(toolCalls, 2)
})
test('collect_block completes from a post-dig inventory event when the drop entity is missed', async () => {
  const ironPickaxe = { name: 'iron_pickaxe', type: 900, count: 1, slot: 0 }
  const items = [ironPickaxe]
  const bot = fakeBot(items)
  const position = new Vec3(2, 64, 0)
  let live = true
  const source = {
    name: 'stone', position, drops: [35], diggable: true,
    canHarvest: type => type === ironPickaxe.type,
    harvestTools: { [ironPickaxe.type]: true }
  }
  bot.registry.items = {
    35: { id: 35, name: 'cobblestone' },
    900: { id: 900, name: 'iron_pickaxe' }
  }
  bot.findBlocks = options => live && options.matching(source) ? [position] : []
  bot.blockAt = () => live ? { ...source } : { name: 'air', position, drops: [] }
  bot.canDigBlock = block => block.name === 'stone'
  bot.dig = async target => {
    assert.equal(target.name, 'stone')
    live = false
    setImmediate(() => {
      items.push({ name: 'cobblestone', type: 35, count: 1, slot: 1 })
      bot.inventory.emit('updateSlot', 1)
    })
  }
  runtime.bindBot(bot)

  const scope = runtime.createActionCancellationScope('inventory-proof-race', 3000)
  const action = runtime.runWithActionCancellationScope(scope, () => resources.collect_block({
    block: 'cobblestone', count: 1, max_distance: 16,
    tool: 'iron_pickaxe', _action_timeout_ms: 3000
  }))
  const first = await Promise.race([
    action.then(value => ({ kind: 'result', value })),
    new Promise(resolve => setImmediate(() => setImmediate(() => resolve({ kind: 'stalled' }))))
  ])
  if (first.kind !== 'result') await scope.cancel('TEST_PROBE_COMPLETE')
  assert.equal(first.kind, 'result')
  assert.equal(first.value.verified, true, JSON.stringify(first.value))
  assert.equal(first.value.outcome.code, 'BLOCKS_COLLECTED')
  assert.equal(first.value.outcome.inventory_delta.cobblestone, 1)
  assert.equal(bot.inventory.listenerCount('updateSlot'), 0)
  assert.equal(bot.listenerCount('itemDrop'), 0)
  assert.equal(bot.listenerCount('playerCollect'), 0)
})

test('collect_block digs physically reachable blocks without a redundant path search', async () => {
  const items = []
  const bot = fakeBot(items)
  const position = new Vec3(2, 64, 0)
  let live = true
  const source = { name: 'oak_log', position, drops: [9], diggable: true }
  bot.registry.items = { 9: { id: 9, name: 'oak_log' } }
  bot.findBlocks = () => live ? [position] : []
  bot.blockAt = () => live ? { ...source } : { name: 'air', position }
  let nativeReachChecks = 0
  bot.canDigBlock = block => {
    nativeReachChecks += 1
    return block.name === 'oak_log' && block.diggable === true
  }
  bot.pathfinder.goto = async () => {
    throw new Error('unexpected pathfinding for reachable block')
  }
  bot.tool.equipForBlock = async () => {}
  bot.dig = async block => {
    assert.equal(block.name, 'oak_log')
    live = false
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
    bot.inventory.emit('updateSlot', 1)
  }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'oak_log', count: 1, max_distance: 16, _action_timeout_ms: 3000
  }))
  assert.equal(nativeReachChecks, 1)
  assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
  assert.equal(result.outcome.collected_count, 1)
  assert.equal(result.outcome.inventory_delta.oak_log, 1)
})

test('native pathfinder timeout may finish collection only after physical dig reach is proven', async () => {
  const items = []
  const bot = fakeBot(items)
  const position = new Vec3(8, 64, 0)
  let live = true
  const source = { name: 'oak_log', position, drops: [9], diggable: true }
  bot.registry.items = { 9: { id: 9, name: 'oak_log' } }
  bot.findBlocks = () => live ? [position] : []
  bot.blockAt = () => live ? { ...source } : { name: 'air', position }
  bot.canDigBlock = block => (
    block && block.diggable === true &&
    bot.entity.position.offset(0, 1.65, 0)
      .distanceTo(block.position.offset(0.5, 0.5, 0.5)) <= 5.1
  )
  bot.pathfinder.goto = async () => {
    // The native A* navigation timed out while the bot physically walked
    // close enough to reach the original observed block.
    bot.entity.position = new Vec3(6, 64, 0)
    const error = new Error('Took to long to decide path to goal!')
    error.name = 'Timeout'
    throw error
  }
  bot.tool.equipForBlock = async () => {}
  bot.dig = async target => {
    assert.equal(target.name, 'oak_log')
    live = false
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
    bot.inventory.emit('updateSlot', 1)
  }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'oak_log', count: 1, max_distance: 16, _action_timeout_ms: 3000
  }))
  assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
  assert.equal(result.outcome.collected_count, 1)
  assert.equal(result.outcome.errors[0].phase,
    'native-navigation-timeout-after-reaching-dig-range')
})

test('collect_block suggests read-only recipe reference without assuming craftability', async () => {
  const bot = fakeBot([])
  bot.registry.itemsByName = { stick: { id: 777, name: 'stick' } }
  bot.findBlocks = () => []
  let nativeRecipeCalls = 0
  bot.recipesAll = (id, metadata, station) => {
    nativeRecipeCalls += 1
    assert.equal(id, 777)
    assert.equal(station, null)
    return [{ result: { id, count: 4 } }]
  }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stick', count: 1, max_distance: 16, _action_timeout_ms: 3000
  }))
  assert.equal(nativeRecipeCalls, 1)
  assert.equal(result.outcome.code, 'BLOCK_NOT_COLLECTED')
  assert.equal(result.outcome.collected_count, 0)
  assert.deepEqual(result.outcome.recovery, {
    action_type: 'recipe_dependencies',
    arguments: { item: 'stick', count: 1 }
  })
  assert.equal(result.outcome.alternative_production_evidence.source,
    'minecraft.native_recipe_catalog')
  assert.equal(result.outcome.alternative_production_evidence.prerequisites_verified, false)
  assert.equal(result.outcome.alternative_production_evidence.recipe_requires_station, null)
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['max_distance'],
    rejected_value: 16,
    when_arguments: [{ argument_path: ['block'], value: 'stick' }],
    validity: {
      until_state_change: [['position'], ['nearby_blocks']],
      while_provider_instance: true
    }
  }])
  assert.deepEqual(
    result.outcome.prerequisites.retry_requires_state_change,
    ['position', 'nearby_blocks']
  )

  bot.recipesAll = () => []
  const withoutRecipe = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stick', count: 1, max_distance: 16, _action_timeout_ms: 3000
  }))
  assert.equal(withoutRecipe.outcome.code, 'BLOCK_NOT_COLLECTED')
  assert.equal(withoutRecipe.outcome.recovery, undefined)

  const implicitBound = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stick', count: 1, _action_timeout_ms: 3000
  }))
  assert.equal(implicitBound.outcome.code, 'BLOCK_NOT_COLLECTED')
  assert.equal(implicitBound.outcome.rejected_argument_constraints, undefined)
})

test('collect_block resolves requested resources through native block drops with an exact requested tool', async () => {
  const requestedTool = { name: 'wooden_pickaxe', type: 900, count: 1, slot: 0 }
  const items = [requestedTool]
  const bot = fakeBot(items)
  const position = new Vec3(2, 64, 0)
  let live = true
  const source = {
    name: 'stone', position, drops: [35],
    canHarvest: type => type === requestedTool.type,
    harvestTools: { [requestedTool.type]: true }
  }
  bot.registry.items = {
    35: { id: 35, name: 'cobblestone' },
    900: { id: 900, name: 'wooden_pickaxe' }
  }
  bot.findBlocks = options => {
    assert.equal(options.matching(source), true)
    return [position]
  }
  bot.blockAt = () => live ? { ...source } : { name: 'air', position, drops: [] }
  bot.tool.equipForBlock = async block => {
    assert.equal(block.name, 'stone')
    bot.heldItem = { name: 'wooden_pickaxe', type: 900, count: 1, slot: 0 }
  }
  bot.dig = async target => {
    assert.equal(target.name, 'stone')
    live = false
    items.push({ name: 'cobblestone', type: 35, count: 1, slot: 1 })
    bot.inventory.emit('updateSlot', 1)
  }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'cobblestone', count: 1, max_distance: 16,
    tool: 'wooden_pickaxe', _action_timeout_ms: 2000
  }))

  assert.equal(result.verified, true, JSON.stringify(result))
  assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
  assert.equal(result.outcome.requested_resource, 'cobblestone')
  assert.deepEqual(result.outcome.source_blocks, ['stone'])
  assert.equal(result.outcome.inventory_delta.cobblestone, 1)
  assert.equal(result.outcome.requested_tool, 'wooden_pickaxe')
  assert.equal(result.outcome.tool_constraint_verified, true)
  assert.equal(result.outcome.held_after.name, 'wooden_pickaxe')
})

test('collect_block rejects an explicitly requested incapable tool before navigation or digging', async () => {
  const golden = { name: 'golden_pickaxe', type: 901, count: 1, slot: 0 }
  const bot = fakeBot([golden])
  const position = new Vec3(2, 64, 0)
  const diamondOre = {
    name: 'diamond_ore', position, drops: [902],
    canHarvest: type => type === 903,
    harvestTools: { 903: true }
  }
  bot.registry.items = {
    902: { id: 902, name: 'diamond' },
    903: { id: 903, name: 'iron_pickaxe' }
  }
  bot.findBlocks = () => [position]
  bot.blockAt = () => ({ ...diamondOre })
  let digCalls = 0
  let navigationCalls = 0
  bot.dig = async () => { digCalls += 1 }
  runtime.bindBot(bot)
  const originalGoto = runtime.gotoBlockInteraction
  runtime.gotoBlockInteraction = async () => { navigationCalls += 1 }
  try {
    const result = await withoutMovementConstruction(() => resources.collect_block({
      block: 'diamond', count: 1, max_distance: 16,
      tool: 'golden_pickaxe', _action_timeout_ms: 2000
    }))
    assert.equal(result.verified, false)
    assert.equal(result.outcome.code, 'REQUESTED_TOOL_CANNOT_HARVEST')
    assert.equal(result.outcome.requested_tool, 'golden_pickaxe')
    assert.deepEqual(result.outcome.acceptable_tools, ['iron_pickaxe'])
    assert.deepEqual(result.outcome.rejected_argument_constraints, [{
      argument_path: ['tool'],
      rejected_value: 'golden_pickaxe',
      when_arguments: [{ argument_path: ['block'], value: 'diamond' }],
      validity: { until_state_change: [['inventory']] }
    }])
    assert.equal(navigationCalls, 0)
    assert.equal(digCalls, 0)
  } finally {
    runtime.gotoBlockInteraction = originalGoto
  }
})

test('collect_block fails closed when the native collector cannot harvest', async () => {
  const items = []
  const bot = fakeBot(items)
  const position = new Vec3(2, 64, 0)
  const live = { name: 'stone', position, drops: [35] }
  bot.registry.items = { 35: { id: 35, name: 'cobblestone' } }
  bot.findBlocks = () => [position]
  bot.blockAt = () => ({ ...live })
  let digCalls = 0
  bot.tool.equipForBlock = async () => {
    const error = new Error('no harvestable tool')
    error.name = 'NoItem'
    throw error
  }
  bot.dig = async () => { digCalls += 1 }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stone', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))

  assert.equal(result.verified, false)
  assert.equal(result.outcome.code, 'HARVEST_TOOL_REQUIRED')
  assert.equal(result.outcome.native_provider, 'mineflayer-direct-dig')
  assert.equal(digCalls, 0)
  assert.equal(result.outcome.errors[0].phase, 'direct-single-block-collection')
})

test('drop capture tracks entitySpawn before item metadata and own collection', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const position = new Vec3(3, 64, 0)
  const watcher = runtime.captureItemDropNear(position, 'oak_log', 0.5)
  const early = { id: 6, name: 'item', position: position.offset(0.5, 0.5, 0.5), isValid: true, getDroppedItem: () => null }
  bot.entities[6] = early
  bot.emit('entitySpawn', early)
  bot.emit('playerCollect', bot.entity, early)
  assert.equal(watcher.spawn_candidates.length, 1)
  assert.equal(watcher.spawn_candidates[0].matched, true)
  assert.equal(watcher.hasOwnCollection(), true)
  assert.equal(watcher.collection_candidates[0].entity_id, 6)
  watcher.cancel()
})


test('drop capture records relevant raw protocol packet order without changing association', () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const position = new Vec3(3, 64, 0)
  const watcher = runtime.captureItemDropNear(position, 'oak_log', 0.5)
  bot._client.emit('packet', { entityId: 8, type: 69, x: 3.5, y: 64.25, z: 0.5 }, { name: 'spawn_entity' })
  bot._client.emit('packet', { entityId: 8, metadata: [{ key: 8, type: 'item_stack', value: {} }] }, { name: 'entity_metadata' })
  bot._client.emit('packet', { collectedEntityId: 8, collectorEntityId: 1, pickupItemCount: 1 }, { name: 'collect' })
  bot._client.emit('packet', { windowId: 0, slot: 36, item: { itemCount: 1 } }, { name: 'set_slot' })
  assert.deepEqual(watcher.protocol_packets.map(row => row.packet), [
    'spawn_entity', 'entity_metadata', 'collect', 'set_slot'
  ])
  assert.equal(watcher.protocol_packets[2].pickup_item_count, 1)
  assert.equal(watcher.protocol_packets[3].slot, 36)
  watcher.cancel()
  bot._client.emit('packet', { entityId: 9 }, { name: 'spawn_entity' })
  assert.equal(watcher.protocol_packets.length, 4)
})


test('goto records a partial applied effect when navigation moved but missed the target', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const original = runtime.gotoPos
  runtime.gotoPos = async () => {
    bot.entity.position = new Vec3(3, 64, 0)
    return { distance: 7, within_radius: false }
  }
  try {
    const result = await movement.goto({ position: { x: 10, y: 64, z: 0 }, radius: 1.5 })
    assert.equal(result.outcome.status, 'partial')
    assert.equal(result.effect_disposition, 'applied')
    assert.equal(result.verified, false)
    assert.equal(result.outcome.moved, 3)
  } finally {
    runtime.gotoPos = original
  }
})


test('goto proves not_applied when navigation ends without displacement', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const original = runtime.gotoPos
  runtime.gotoPos = async () => ({ distance: 10, within_radius: false })
  try {
    const result = await movement.goto({ position: { x: 10, y: 64, z: 0 }, radius: 1.5 })
    assert.equal(result.outcome.status, 'rejected')
    assert.equal(result.effect_disposition, 'not_applied')
    assert.equal(result.verified, false)
    assert.equal(result.outcome.moved, 0)
  } finally {
    runtime.gotoPos = original
  }
})


test('goto preserves applied certainty when pathfinder fails after displacement', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const original = runtime.gotoPos
  runtime.gotoPos = async () => {
    bot.entity.position = new Vec3(2, 64, 0)
    const error = new Error('No path to goal')
    error.code = 'NoPath'
    throw error
  }
  try {
    const result = await movement.goto({ position: { x: 10, y: 64, z: 0 }, radius: 1.5 })
    assert.equal(result.outcome.status, 'partial')
    assert.equal(result.effect_disposition, 'applied')
    assert.equal(result.outcome.moved, 2)
    assert.equal(result.outcome.navigation_error.code, 'NoPath')
  } finally {
    runtime.gotoPos = original
  }
})


test('goto proves not_applied when pathfinder fails before displacement', async () => {
  const bot = fakeBot([])
  runtime.bindBot(bot)
  const original = runtime.gotoPos
  runtime.gotoPos = async () => {
    const error = new Error('No path to goal')
    error.code = 'NoPath'
    throw error
  }
  try {
    const result = await movement.goto({ position: { x: 10, y: 64, z: 0 }, radius: 1.5 })
    assert.equal(result.outcome.status, 'rejected')
    assert.equal(result.effect_disposition, 'not_applied')
    assert.equal(result.outcome.moved, 0)
  } finally {
    runtime.gotoPos = original
  }
})


test('goto_entity delegates moving targets to runtime GoalFollow navigation', async () => {
  const bot = fakeBot([])
  const target = { id: 2, name: 'zombie', isValid: true, position: new Vec3(4, 64, 0) }
  bot.entities[2] = target
  runtime.bindBot(bot)
  let dynamicCalls = 0
  let staticCalls = 0
  const oldDynamic = runtime.gotoEntity
  const oldStatic = runtime.gotoPos
  runtime.gotoEntity = async entity => { dynamicCalls += 1; return { entity_id: entity.id, valid: true, goal_satisfied: true } }
  runtime.gotoPos = async () => { staticCalls += 1; return { distance: 0, within_radius: true } }
  try {
    const result = await withoutMovementConstruction(() => movement.goto_entity({
      entity: 'zombie', max_distance: 16, radius: 2.5, _action_timeout_ms: 5000
    }))
    assert.equal(result.verified, false)
    assert.equal(result.outcome.goal_satisfied, true)
    assert.equal(result.outcome.moved, 0)
    assert.equal(result.effect_disposition, 'not_applied')
    assert.equal(dynamicCalls, 1)
    assert.equal(staticCalls, 0)
  } finally {
    runtime.gotoEntity = oldDynamic
    runtime.gotoPos = oldStatic
  }
})


test('entity interaction actions reuse moving-target GoalFollow navigation', async () => {
  const coal = { name: 'coal', type: 263, count: 2, slot: 0 }
  const bot = fakeBot([coal])
  const player = {
    id: 2, type: 'player', username: 'alice', name: 'player',
    isValid: true, position: new Vec3(8, 64, 0)
  }
  const horse = {
    id: 3, type: 'mob', name: 'horse', isValid: true,
    position: new Vec3(8, 64, 1), passengers: []
  }
  const villager = {
    id: 4, type: 'mob', name: 'villager', displayName: 'villager',
    isBaby: false, isValid: true, position: new Vec3(8, 64, 2)
  }
  const zombie = {
    id: 5, type: 'mob', name: 'zombie', isValid: true,
    position: new Vec3(8, 64, 3)
  }
  Object.assign(bot.entities, { 2: player, 3: horse, 4: villager, 5: zombie })
  bot.lookAt = async () => {}
  bot.toss = async (_type, _metadata, count) => { coal.count -= count }
  bot.mount = entity => {
    bot.vehicle = entity
    entity.passengers = [bot.entity]
    bot.emit('mount', entity)
  }
  bot.openVillager = async entity => ({
    trades: [],
    close: () => {},
    entity
  })
  bot.useOn = async () => {}
  runtime.bindBot(bot)

  const dynamicCalls = []
  let staticCalls = 0
  const oldDynamic = runtime.gotoEntity
  const oldStatic = runtime.gotoPos
  runtime.gotoEntity = async (entity, radius) => {
    dynamicCalls.push([entity.id, radius])
    return { entity_id: entity.id, valid: true, goal_satisfied: true }
  }
  runtime.gotoPos = async () => {
    staticCalls += 1
    throw new Error('moving entity must not use a frozen coordinate')
  }
  try {
    await withoutMovementConstruction(() => inventory.give_item({
      player: 'alice', item: 'coal', count: 1
    }))
    await withoutMovementConstruction(() => interactions.mount({
      entity: 'horse', max_distance: 16
    }))
    await withoutMovementConstruction(() => interactions.show_villager_trades({
      max_distance: 16
    }))
    await withoutMovementConstruction(() => interactions.use_tool_on({
      target: 'zombie', target_type: 'entity', max_distance: 16
    }))
  } finally {
    runtime.gotoEntity = oldDynamic
    runtime.gotoPos = oldStatic
  }

  assert.deepEqual(dynamicCalls, [[2, 2], [3, 2], [4, 3], [5, 3]])
  assert.equal(staticCalls, 0)
})

test('villager trade uses Mineflayer use counters and one native counted trade', async () => {
  const emerald = { name: 'emerald', type: 388, count: 8, slot: 0 }
  const bread = { name: 'bread', type: 297, count: 0, slot: 1 }
  const bot = fakeBot([emerald, bread])
  const villager = {
    id: 4, type: 'mob', name: 'villager', displayName: 'villager',
    isBaby: false, isValid: true, position: new Vec3(4, 64, 0)
  }
  bot.entities[4] = villager
  const trade = {
    nbTradeUses: 1,
    maximumNbTradeUses: 5,
    tradeDisabled: false,
    inputItem1: { name: 'emerald', count: 1, slot: 0 },
    inputItem2: null,
    outputItem: { name: 'bread', count: 1, slot: 2 }
  }
  const nativeCalls = []
  const window = {
    trades: [trade],
    close: () => {},
    trade: async (index, count) => {
      nativeCalls.push([index, count])
      assert.equal(index, 0)
      assert.equal(count, 3)
      trade.nbTradeUses += count
      emerald.count -= count
      bread.count += count
    }
  }
  bot.openVillager = async () => window
  runtime.bindBot(bot)
  const oldDynamic = runtime.gotoEntity
  runtime.gotoEntity = async entity => ({
    entity_id: entity.id, valid: true, goal_satisfied: true
  })
  try {
    const inspected = await withoutMovementConstruction(() =>
      interactions.show_villager_trades({ max_distance: 16 }))
    assert.equal(inspected.outcome.trades[0].uses, 1)
    assert.equal(inspected.outcome.trades[0].max_uses, 5)
    assert.equal(inspected.outcome.trades[0].disabled, false)

    const result = await withoutMovementConstruction(() =>
      interactions.trade_villager({
        trade_index: 0, max_trades: 3, max_distance: 16
      }))
    assert.equal(result.outcome.status, 'applied')
    assert.equal(result.outcome.code, 'TRADE_EXECUTED')
    assert.equal(result.outcome.executions, 3)
    assert.equal(result.outcome.available, 4)
    assert.equal(result.outcome.inventory_delta.emerald, -3)
    assert.equal(result.outcome.inventory_delta.bread, 3)
    assert.deepEqual(nativeCalls, [[0, 3]])
  } finally {
    runtime.gotoEntity = oldDynamic
  }
})

test('follow_player installs one native dynamic GoalFollow without static goto polling', async () => {
  const bot = fakeBot([])
  const target = {
    id: 2, type: 'player', username: 'alice', name: 'player',
    isValid: true, position: new Vec3(20, 64, 0)
  }
  bot.entities[2] = target
  let currentGoal = null
  const goalWrites = []
  bot.pathfinder.setGoal = (goal, dynamic = false) => {
    currentGoal = goal
    goalWrites.push({ goal, dynamic })
    if (goal) bot.emit('path_update', { status: 'success' })
  }
  Object.defineProperty(bot.pathfinder, 'goal', { get: () => currentGoal })
  runtime.bindBot(bot)
  const oldGoto = runtime.gotoPos
  const oldTicks = runtime.waitForPhysicsTicks
  runtime.gotoPos = async () => { throw new Error('static goto must not be used') }
  runtime.waitForPhysicsTicks = async () => { throw new Error('outer physics polling must not be used') }
  const scope = runtime.createActionCancellationScope('follow-dynamic-test', 1000)
  try {
    const result = await runtime.runWithActionCancellationScope(scope, () => interactions.follow_player({
      player: 'alice', duration_s: 0.01, distance: 4, max_distance: 64
    }))
    assert.equal(result.outcome.code, 'FOLLOW_INTERVAL_COMPLETED')
    assert.equal(result.outcome.navigation_mode, 'dynamic_goal_follow')
    assert.equal(result.outcome.updates, 1)
    assert.equal(goalWrites.filter(row => row.goal && row.dynamic === true).length, 1)
    assert.equal(goalWrites.at(-1).goal, null)
    assert.equal(bot.pathfinder.goal, null)
  } finally {
    runtime.gotoPos = oldGoto
    runtime.waitForPhysicsTicks = oldTicks
  }
})


test('follow_player exits from entityGone event and retires its dynamic goal immediately', async () => {
  const bot = fakeBot([])
  const target = {
    id: 2, type: 'player', username: 'alice', name: 'player',
    isValid: true, position: new Vec3(20, 64, 0)
  }
  bot.entities[2] = target
  let currentGoal = null
  bot.pathfinder.setGoal = (goal, dynamic = false) => { currentGoal = goal }
  Object.defineProperty(bot.pathfinder, 'goal', { get: () => currentGoal })
  runtime.bindBot(bot)
  const scope = runtime.createActionCancellationScope('follow-gone-test', 2000)
  const started = Date.now()
  setImmediate(() => {
    delete bot.entities[target.id]
    target.isValid = false
    bot.emit('entityGone', target)
  })
  const result = await runtime.runWithActionCancellationScope(scope, () => interactions.follow_player({
    player: 'alice', duration_s: 1, distance: 4, max_distance: 64
  }))
  assert.equal(result.outcome.code, 'FOLLOW_INTERVAL_COMPLETED')
  assert.equal(result.outcome.target_gone, true)
  assert.equal(bot.pathfinder.goal, null)
  assert.ok(Date.now() - started < 250, 'entityGone should end follow without waiting for duration')
  assert.equal(bot.listenerCount('entityGone'), 0)
})


test('collect_block selects safe resource sources instead of rejecting nearer unsafe blocks', async () => {
  const items = []
  const bot = fakeBot(items)
  const unsafePos = new Vec3(0, 63, 0)
  const safePos = new Vec3(3, 64, 0)
  let safeLive = true
  const blocks = [
    { name: 'stone', position: unsafePos, drops: [35], safe: false },
    { name: 'stone', position: safePos, drops: [35], safe: true }
  ]
  bot.registry.items = { 35: { id: 35, name: 'cobblestone' } }
  bot.pathfinder.movements.safeToBreak = block => Boolean(block.safe)
  bot.findBlocks = options => blocks
    .filter(block => options.matching(block))
    .filter(block => typeof options.useExtraInfo !== 'function' || options.useExtraInfo(block))
    .slice(0, options.count)
    .map(block => block.position)
  bot.blockAt = position => {
    if (position.equals(unsafePos)) return { ...blocks[0] }
    if (position.equals(safePos)) return safeLive ? { ...blocks[1] } : { name: 'air', position, drops: [], safe: true }
    return { name: 'air', position, drops: [], safe: true }
  }
  bot.tool.equipForBlock = async block => {
    assert.equal(block.position.equals(safePos), true)
    bot.heldItem = { name: 'wooden_pickaxe', type: 900, count: 1, slot: 0 }
  }
  bot.dig = async target => {
    assert.equal(target.position.equals(safePos), true)
    safeLive = false
    items.push({ name: 'cobblestone', type: 35, count: 1, slot: 1 })
  }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'cobblestone', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))

  assert.equal(result.verified, true, JSON.stringify(result))
  assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
  assert.deepEqual(result.outcome.source_blocks, ['stone'])
  assert.equal(result.outcome.inventory_delta.cobblestone, 1)
})

test('collect_block reports observed unsafe world block in one search pass', async () => {
  const bot = fakeBot([])
  const position = new Vec3(2, 63, 0)
  const unsafe = { name: 'iron_ore', position, drops: [], safe: false }
  bot.registry.blocksByName = { iron_ore: { id: 15, name: 'iron_ore' } }
  bot.pathfinder.movements.safeToBreak = block => Boolean(block.safe)
  let searchCount = 0
  bot.findBlocks = options => {
    searchCount++
    const matched = options.matching(unsafe)
    assert.equal(matched, true)
    return !options.useExtraInfo || options.useExtraInfo(unsafe) ? [position] : []
  }
  bot.blockAt = () => unsafe
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'iron_ore', count: 64, max_distance: 16, _action_timeout_ms: 2000
  }))

  assert.equal(searchCount, 1)
  assert.equal(result.verified, false)
  assert.equal(result.outcome.code, 'UNSAFE_BLOCK_BREAK')
  assert.deepEqual(result.outcome.unsafe, [{ name: 'iron_ore', position: { x: 2, y: 63, z: 0 } }])
})

test('collect_block rejects unsafe targets before invoking the native collector', async () => {
  const bot = fakeBot([])
  const position = new Vec3(2, 64, 0)
  bot.findBlocks = () => [position]
  bot.blockAt = () => ({ name: 'stone', position, drops: [35] })
  bot.pathfinder.movements.safeToBreak = () => false
  let collectCalls = 0
  bot.collectBlock.collect = async () => { collectCalls += 1 }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stone', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))

  assert.equal(result.verified, false)
  assert.equal(result.outcome.code, 'UNSAFE_BLOCK_BREAK')
  assert.equal(collectCalls, 0)
})

test('read-only observe_entities without action_id is a query, never action evidence', async () => {
  const { spawn } = require('node:child_process')
  const path = require('node:path')
  const child = spawn(process.execPath, [path.join(__dirname, 'bridge.js')], {
    cwd: __dirname,
    env: process.env,
    stdio: ['pipe', 'pipe', 'pipe']
  })
  let output = ''
  child.stdout.on('data', chunk => { output += chunk.toString() })
  child.stderr.on('data', chunk => { output += chunk.toString() })
  child.stdin.write(JSON.stringify({ cmd: 'observe_entities', request_id: 'node-test-observe', max_distance: 8, limit: 1 }) + '\n')
  const deadline = Date.now() + 3000
  while (!output.includes('node-test-observe') && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  child.kill()
  assert.ok(output.includes('node-test-observe'))
  assert.ok(!output.includes('ACTION_RECOVERY_ACTION_ID_REQUIRED'))
  assert.ok(!output.includes('"kind":"action_result"'))
})

test('collect_block preserves native NoPath evidence and proves no effect', async () => {
  const items = []
  const bot = fakeBot(items)
  const position = new Vec3(4, 64, 0)
  const live = { name: 'oak_log', position, drops: [9] }
  bot.registry.items = { 9: { id: 9, name: 'oak_log' } }
  bot.findBlocks = options => options.matching(live) ? [position] : []
  bot.blockAt = () => ({ ...live })
  bot.tool.equipForBlock = async () => {}
  runtime.bindBot(bot)
  const originalGotoBlockInteraction = runtime.gotoBlockInteraction
  runtime.gotoBlockInteraction = async () => {
    const error = new Error('No path to the goal!')
    error.name = 'NoPath'
    error.code = 'NoPath'
    throw error
  }

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'oak_log', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))
  runtime.gotoBlockInteraction = originalGotoBlockInteraction

  assert.equal(result.verified, false)
  assert.equal(result.effect_disposition, 'not_applied')
  assert.equal(result.outcome.code, 'COLLECTION_FAILED')
  assert.equal(result.outcome.broken.length, 0)
  assert.equal(result.outcome.collected_count, 0)
  assert.equal(result.outcome.errors[0].phase, 'direct-single-block-collection')
  assert.equal(result.outcome.errors[0].name, 'NoPath')
  assert.equal(result.outcome.errors[0].code, 'NoPath')
  assert.equal(result.outcome.errors[0].message, 'No path to the goal!')
  assert.match(result.outcome.errors[0].stack, /No path to the goal!/)
})


test('placement navigation adapts GoalPlaceBlock coordinates to Mineflayer placement ABI', async () => {
  const bot = fakeBot([])
  const target = new Vec3(1, 64, 0)
  const ref = target.offset(0, -1, 0)
  const support = {
    name: 'stone', type: 1, boundingBox: 'block', position: ref,
    shapes: [[0, 0, 0, 1, 1, 1]]
  }
  bot.world = {
    getBlock: position => position.equals(ref) ? support : null,
    raycast: () => ({ position: ref, face: 1 })
  }
  bot.blockAt = position => position.equals(ref) ? support : null
  bot.pathfinder.goto = async goal => {
    assert.equal(goal.isEnd(bot.entity.position.floored()), true)
  }
  runtime.bindBot(bot)

  const direct = await runtime.gotoBlockPlacement(target, 2000)
  assert.equal(direct.reference, support)
  assert.equal(Math.abs(direct.face.x), 0)
  assert.equal(direct.face.y, 1)
  assert.equal(Math.abs(direct.face.z), 0)
  assert.deepEqual(direct.reference.position.plus(direct.face), target)

  const any = await runtime.gotoAnyBlockPlacement([target], 2000)
  assert.equal(any.reference, support)
  assert.equal(Math.abs(any.face.x), 0)
  assert.equal(any.face.y, 1)
  assert.equal(Math.abs(any.face.z), 0)
  assert.deepEqual(any.reference.position.plus(any.face), target)
})


test('place_block reconciles applied world state when mineflayer throws after placement', async () => {
  const items = [{ name: 'torch', type: 10, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  const target = new Vec3(1, 64, 0)
  let placedName = 'air'
  bot.blockAt = position => position.equals(target)
    ? { name: placedName, position }
    : { name: 'stone', position }
  bot.placeBlock = async () => {
    placedName = 'torch'
    setImmediate(() => bot.emit('physicsTick'))
    throw new Error('provider acknowledgement lost after physical placement')
  }
  const original = runtime.gotoBlockPlacement
  runtime.gotoBlockPlacement = async () => ({
    reference: { name: 'stone', position: new Vec3(0, 64, 0) },
    face: new Vec3(1, 0, 0)
  })
  runtime.bindBot(bot)
  try {
    const result = await withoutMovementConstruction(() => resources.place_block({
      item: 'torch',
      position: target,
      _action_timeout_ms: 2000
    }))
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.effect_disposition, 'applied')
    assert.equal(result.outcome.code, 'BLOCK_PLACED_DESPITE_PROVIDER_ERROR')
    assert.equal(result.outcome.placed, 'torch')
    assert.match(result.outcome.provider_error.message, /acknowledgement lost/)
  } finally {
    runtime.gotoBlockPlacement = original
  }
})

test('observeBlocks reports live-world truth separately from registry existence', () => {
  const bot = fakeBot([])
  const oak = new Vec3(3, 64, 0)
  const birch = new Vec3(5, 64, 0)
  bot.registry.blocksByName = {
    air: { id: 0, name: 'air' },
    oak_log: { id: 1, name: 'oak_log' },
    birch_log: { id: 2, name: 'birch_log' }
  }
  bot.findBlocks = options => {
    assert.deepEqual(options.matching, [1])
    assert.equal(options.maxDistance, 16)
    return [oak]
  }
  bot.blockAt = position => {
    if (position.equals(oak)) {
      return { name: 'oak_log', position, metadata: 0, isWaterlogged: false }
    }
    if (position.equals(birch)) {
      return { name: 'birch_log', position, metadata: 0, isWaterlogged: false }
    }
    return null
  }
  runtime.bindBot(bot)

  const result = runtime.observeBlocks('oak_log', 16, 8)
  assert.equal(result.truth_class, 'observed')
  assert.equal(result.authoritative_for_current_world, true)
  assert.equal(result.loaded_world_only, true)
  assert.equal(result.registry_match_count, 1)
  assert.equal(result.observed_count, 1)
  assert.equal(result.blocks[0].name, 'oak_log')
  assert.deepEqual(result.blocks[0].position, { x: 3, y: 64, z: 0 })
  assert.deepEqual(result.counts, { oak_log: 1 })
})

test('move_away uses entity-relative pathfinder avoidance when a target is supplied', async () => {
  const bot = fakeBot([])
  const target = {
    id: 2,
    name: 'zombie',
    displayName: 'Zombie',
    isValid: true,
    position: new Vec3(2, 64, 0)
  }
  bot.entities[2] = target
  runtime.bindBot(bot)
  const original = runtime.moveAwayFromEntity
  runtime.moveAwayFromEntity = async (entity, distance) => {
    assert.equal(entity, target)
    assert.equal(distance, 5)
    bot.entity.position = new Vec3(10, 64, 0)
    return { entity_id: entity.id, distance: 8, goal_satisfied: true }
  }
  try {
    const result = await movement.move_away({
      entity: 'zombie',
      distance: 5,
      max_distance: 16
    })
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'ENTITY_DISTANCE_CREATED')
    assert.equal(result.outcome.distance_before, 2)
    assert.equal(result.outcome.distance_after, 8)
  } finally {
    runtime.moveAwayFromEntity = original
  }
})

test('defend_self derives hostile classification from versioned registry truth', async () => {
  const bot = fakeBot([])
  const cow = {
    id: 2,
    name: 'cow',
    isValid: true,
    position: new Vec3(2, 64, 0)
  }
  const zombie = {
    id: 3,
    name: 'zombie',
    isValid: true,
    position: new Vec3(3, 64, 0)
  }
  bot.entities[2] = cow
  bot.entities[3] = zombie
  bot.registry.entitiesByName = {
    cow: { name: 'cow', type: 'animal', category: 'Passive mobs' },
    zombie: { name: 'zombie', type: 'hostile', category: 'Hostile mobs' }
  }
  bot.pvp = {
    attack: entity => {
      assert.equal(entity, zombie)
      zombie.isValid = false
      setImmediate(() => bot.emit('attackedTarget', zombie))
    },
    stop: () => {}
  }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => combat.defend_self({
    radius: 8,
    max_targets: 4,
    max_hits: 1
  }))
  // Native PvP was invoked, but the hostile disappeared before an
  // attributed attack signal. An unknown effect is not proven success.
  assert.equal(result.verified, false, JSON.stringify(result))
  assert.equal(result.outcome.code, 'DEFENSE_EFFECT_UNATTRIBUTED')
  assert.equal(result.effect_disposition, 'unknown')
  assert.equal(result.outcome.targets_observed, 1)
})


test('consume_item trusts Mineflayer server completion instead of sleeping a guessed duration', async () => {
  const items = [{ name: 'bread', type: 297, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  bot.food = 10
  bot.health = 20
  bot.consume = async () => {
    items[0].count = 0
    bot.food = 15
  }
  runtime.bindBot(bot)

  const result = await inventory.consume_item({ item: 'bread' })

  assert.equal(result.verified, true)
  assert.equal(result.outcome.code, 'ITEM_CONSUMED')
  assert.equal(result.outcome.provider_completion_observed, true)
  assert.equal(result.outcome.state_delta_observed, true)
})

test('consume_item proves no effect when Mineflayer rejects before consumption', async () => {
  const items = [{ name: 'bread', type: 297, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  bot.food = 20
  bot.health = 20
  bot.consume = async () => { throw new Error('Food is full') }
  runtime.bindBot(bot)

  const result = await inventory.consume_item({ item: 'bread' })

  assert.equal(result.verified, false)
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'CONSUMPTION_REJECTED')
  assert.equal(result.effect_disposition, 'not_applied')
})


test('goto_block delegates all loaded targets to one joint pathfinder goal', async () => {
  const bot = fakeBot()
  bot.registry.blocksByName = { oak_log: { id: 17, name: 'oak_log' } }
  const near = new Vec3(2, 64, 0)
  const reachable = new Vec3(8, 64, 0)
  bot.findBlocks = () => [near, reachable]
  bot.blockAt = position => ({
    name: (position.equals(near) || position.equals(reachable)) ? 'oak_log' : 'air',
    position: position.clone ? position.clone() : position
  })
  runtime.bindBot(bot)

  const original = runtime.gotoAnyBlockVicinity
  runtime.gotoAnyBlockVicinity = async positions => {
    assert.deepEqual(positions, [near, reachable])
    bot.entity.position = new Vec3(6, 64, 0)
    return {
      target: runtime.vec(reachable),
      candidate_count: positions.length,
      selected_candidate_index: 1,
      navigation_goal: 'get_to_any_block'
    }
  }
  try {
    const result = await movement.goto_block({
      block: 'oak_log',
      max_distance: 32,
      _action_timeout_ms: 2000
    })
    assert.equal(result.verified, true)
    assert.equal(result.outcome.code, 'BLOCK_REACHED')
    assert.equal(result.outcome.loaded_world_candidate_count, 2)
    assert.equal(result.outcome.target_selection, 'pathfinder_goal_any_get_to_block_kd')
    assert.deepEqual(result.outcome.block_position, runtime.vec(reachable))
  } finally {
    runtime.gotoAnyBlockVicinity = original
  }
})


test('place_block without a position selects safe local geometry instead of a fixed offset', async () => {
  const items = [{ name: 'crafting_table', type: 58, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  const base = bot.entity.position.floored()
  const east = base.offset(1, 0, 0)
  const west = base.offset(-1, 0, 0)
  let placedName = 'air'

  bot.world = { getBlock: () => null, raycast: () => null }
  bot.pathfinder.movements = {
    replaceables: new Set([0]),
    blocksToAvoid: new Set()
  }
  bot.blockAt = position => {
    if (position.y === 63) {
      return { name: 'stone', type: 1, boundingBox: 'block', position }
    }
    if (position.equals(east) || position.equals(west)) {
      return {
        name: placedName,
        type: placedName === 'air' ? 0 : 58,
        boundingBox: placedName === 'air' ? 'empty' : 'block',
        position
      }
    }
    return { name: 'stone', type: 1, boundingBox: 'block', position }
  }
  bot.equip = async item => { bot.heldItem = item }
  bot.placeBlock = async () => {
    placedName = 'crafting_table'
    setImmediate(() => bot.emit('physicsTick'))
  }

  const original = runtime.gotoAnyBlockPlacement
  runtime.gotoAnyBlockPlacement = async positions => {
    assert.deepEqual(positions, [east, west])
    return {
      target: runtime.vec(west),
      reference: { name: 'stone', position: west.offset(0, -1, 0) },
      face: new Vec3(0, 1, 0),
      candidate_count: positions.length,
      selected_candidate_index: 1,
      navigation_goal: 'place_any_block'
    }
  }
  runtime.bindBot(bot)
  try {
    const result = await withoutMovementConstruction(() => resources.place_block({
      item: 'crafting_table',
      _action_timeout_ms: 2000
    }))
    assert.equal(result.verified, true)
    assert.equal(result.outcome.code, 'BLOCK_PLACED')
    assert.equal(result.outcome.target_selection, 'pathfinder_goal_place_any_local')
    assert.equal(result.outcome.local_candidate_count, 2)
    assert.deepEqual(result.outcome.position, runtime.vec(west))
  } finally {
    runtime.gotoAnyBlockPlacement = original
  }
})


test('entity lookup uses exact canonical type identity instead of substrings', () => {
  const bot = fakeBot([])
  bot.entities[2] = { id: 2, name: 'piglin', displayName: 'Piglin', type: 'mob', isValid: true, position: new Vec3(2, 64, 0) }
  runtime.bindBot(bot)
  assert.equal(runtime.findEntity('pig', 16), null)
  assert.equal(runtime.findEntity('piglin', 16).id, 2)
})

test('goto_entity returns observed frontier facts without moving or choosing exploration', async () => {
  const bot = fakeBot([])
  bot.registry.entitiesByName = { zombie: { id: 54, name: 'zombie' } }
  bot.world.getColumns = () => [{ chunkX: 0, chunkZ: 0, column: {} }]
  runtime.bindBot(bot)
  const original = bot.entity.position.clone()
  const result = await movement.goto_entity({ entity: 'zombie', max_distance: 32, radius: 2.5 })
  assert.equal(result.outcome.code, 'ENTITY_NOT_FOUND')
  assert.equal(result.effect_disposition, 'rejected')
  assert.ok(result.outcome.world_frontier.candidates.length > 0)
  assert.equal(bot.entity.position.equals(original), true)
})

test('attack_nearest returns observation constraint without navigation policy when absent', async () => {
  const bot = fakeBot([])
  bot.registry.entitiesByName = { zombie: { id: 54, name: 'zombie' } }
  runtime.bindBot(bot)
  const result = await combat.attack_nearest({ entity: 'zombie', max_distance: 16, max_hits: 2 })
  assert.equal(result.outcome.code, 'TARGET_NOT_FOUND')
  assert.equal(result.effect_disposition, 'not_applied')
  assert.equal(result.outcome.observed_entity_in_range, false)
  assert.equal(Object.hasOwn(result.outcome, 'recovery'), false)
})


test('smelt_item requires explicit fuel instead of guessing an inventory fuel', async () => {
  const items = [{ name: 'raw_iron', type: 4, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  const furnaceBlock = { name: 'furnace', position: new Vec3(1, 64, 0) }
  let inputTransfers = 0
  const furnace = Object.assign(new EventEmitter(), {
    fuel: 0,
    outputItem: () => null,
    inputItem: () => null,
    fuelItem: () => null,
    putFuel: async () => { throw new Error('unexpected fuel transfer') },
    putInput: async () => { inputTransfers += 1 },
    close: () => {}
  })
  bot.findBlock = () => furnaceBlock
  bot.blockAt = () => furnaceBlock
  bot.openFurnace = async () => furnace
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.smelt_item({
    item: 'raw_iron', count: 1, max_distance: 8, max_wait_s: 10
  }))
  assert.equal(result.outcome.code, 'FUEL_SELECTION_REQUIRED')
  assert.equal(result.effect_disposition, 'not_applied')
  assert.equal(inputTransfers, 0)
})

test('smelt_item replenishes explicit fuel from server events instead of a capacity table', async () => {
  const items = [
    { name: 'raw_iron', type: 4, count: 2, slot: 0 },
    { name: 'coal', type: 5, count: 2, slot: 1 }
  ]
  const bot = fakeBot(items)
  const furnaceBlock = { name: 'furnace', position: new Vec3(1, 64, 0) }
  let output = null
  const fuelTransfers = []
  const furnace = Object.assign(new EventEmitter(), {
    fuel: 0,
    outputItem: () => output,
    inputItem: () => null,
    fuelItem: () => null,
    putFuel: async (_type, _metadata, count) => {
      fuelTransfers.push(count)
      items[1].count -= count
    },
    putInput: async (_type, _metadata, count) => {
      items[0].count -= count
      output = { name: 'iron_ingot', type: 6, count, slot: 2 }
      queueMicrotask(() => furnace.emit('update'))
    },
    takeOutput: async () => { items.push(output); output = null },
    close: () => {}
  })
  bot.findBlock = () => furnaceBlock
  bot.blockAt = () => furnaceBlock
  bot.openFurnace = async () => furnace
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.smelt_item({
    item: 'raw_iron', count: 2, fuel: 'coal', max_distance: 8, max_wait_s: 10
  }))
  assert.equal(result.verified, true, JSON.stringify(result))
  assert.equal(result.outcome.code, 'ITEM_SMELTED')
  assert.deepEqual(fuelTransfers, [1])
  assert.equal(result.outcome.output.fuel_units_inserted, 1)
})

test('craft_item table recipe reports missing materials before station availability', async () => {
  const items = [{ name: 'spruce_log', type: 17, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  bot.version = '1.21.1'
  bot.registry.itemsByName.wooden_shovel = { id: 767, name: 'wooden_shovel' }
  bot.recipesFor = () => []
  bot.findBlock = () => { throw new Error('station scan must not run for impossible recipe') }
  bot.findBlocks = () => { throw new Error('source scan must not run for impossible recipe') }
  bot.craft = async () => { throw new Error('craft must not execute without materials') }
  runtime.bindBot(bot)

  const result = await resources.craft_item({ item: 'wooden_shovel', count: 1 })

  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'NO_RECIPE_OR_MATERIALS')
  assert.equal(Object.hasOwn(result.outcome.prerequisites, 'nearby_crafting_table'), false)
  assert.equal(result.outcome.prerequisites.executable_table_recipe_with_current_inventory, false)
  assert.deepEqual(result.outcome.prerequisites.retry_requires_state_change, ['inventory'])
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['item'],
    rejected_value: 'wooden_shovel',
    validity: {
      until_state_change: [['inventory']],
      while_provider_instance: true
    }
  }])
  assert.ok(result.outcome.production_reference, JSON.stringify(result))
  assert.equal(result.effect_disposition, 'rejected')
})

test('craft_item reports station requirement only after materials are executable', async () => {
  const items = [
    { name: 'spruce_planks', type: 1, count: 1, slot: 0 },
    { name: 'stick', type: 2, count: 2, slot: 1 }
  ]
  const bot = fakeBot(items)
  bot.version = '1.21.1'
  bot.registry.itemsByName.wooden_shovel = { id: 767, name: 'wooden_shovel' }
  const recipe = { result: { count: 1 } }
  bot.recipesFor = (_id, _meta, _count, table) => table ? [recipe] : []
  bot.findBlock = () => null
  bot.craft = async () => { throw new Error('craft must not execute without a station') }
  runtime.bindBot(bot)

  const result = await resources.craft_item({ item: 'wooden_shovel', count: 1 })

  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'CRAFTING_TABLE_REQUIRED')
  assert.equal(result.outcome.prerequisites.nearby_crafting_table, false)
  assert.equal(result.outcome.prerequisites.carried_crafting_table, false)
  assert.equal(result.outcome.prerequisites.executable_table_recipe_with_current_inventory, true)
  assert.equal(result.effect_disposition, 'rejected')
})

test('craft_item missing intermediate ingredients does not misdiagnose a crafting table', async () => {
  const items = [{ name: 'oak_log', type: 17, count: 3, slot: 0 }]
  const bot = fakeBot(items)
  bot.version = '1.21.1'
  bot.registry.itemsByName.stick = { id: 760, name: 'stick' }
  bot.recipesFor = () => []
  bot.findBlock = () => null
  bot.craft = async () => { throw new Error('craft must not execute without materials') }
  runtime.bindBot(bot)
  const result = await resources.craft_item({ item: 'stick', count: 4 })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'NO_RECIPE_OR_MATERIALS')
  assert.equal(result.outcome.prerequisites.executable_inventory_grid_recipe, false)
  assert.equal(result.outcome.prerequisites.public_no_table_recipe_known, true)
  assert.deepEqual(result.outcome.recovery, {
    action_type: 'recipe_dependencies',
    arguments: { item: 'stick', count: 4 }
  })
  assert.deepEqual(result.outcome.prerequisites.retry_requires_state_change, ['inventory'])
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['count'],
    rejected_value: 4,
    when_arguments: [{ argument_path: ['item'], value: 'stick' }],
    validity: {
      until_state_change: [['inventory']],
      while_provider_instance: true
    }
  }])
  assert.equal(result.effect_disposition, 'rejected')
})

test('craft_item cannot place a carried workstation without separately authorized side effects', async () => {
  const items = [{ name: 'crafting_table', type: 58, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  bot.registry.itemsByName.oak_planks = { id: 5, name: 'oak_planks' }
  const recipe = { result: { count: 4 } }
  bot.recipesFor = (_id, _meta, _count, table) => table ? [recipe] : []
  let physicalEffects = 0
  bot.placeBlock = async () => { physicalEffects += 1 }
  bot.craft = async () => { physicalEffects += 1 }
  bot.findBlock = () => null
  runtime.bindBot(bot)

  const result = await resources.craft_item({ item: 'oak_planks', count: 4 })

  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'CRAFTING_STATION_PLACEMENT_NOT_AUTHORIZED')
  assert.equal(result.outcome.required_side_effect_capability, 'place_block')
  assert.equal(physicalEffects, 0)
  assert.equal(result.effect_disposition, 'not_applied')
})

test('craft_item rejects impossible materials before moving to an observed station', async () => {
  const bot = fakeBot([])
  bot.registry.itemsByName.iron_pickaxe = { id: 250, name: 'iron_pickaxe' }
  const tablePos = new Vec3(2, 64, 0)
  bot.world.getColumns = () => [{ chunkX: 0, chunkZ: 0 }]
  let stationScans = 0
  bot.findBlock = () => { stationScans += 1; return { name: 'crafting_table', position: tablePos } }
  bot.findBlocks = () => { throw new Error('source scan must not run for impossible recipe') }
  bot.recipesFor = () => []
  bot.craft = async () => { throw new Error('must reject before craft') }
  runtime.bindBot(bot)
  const original = runtime.gotoBlockInteraction
  let calls = 0
  runtime.gotoBlockInteraction = async () => { calls += 1 }
  try {
    const result = await resources.craft_item({ item: 'iron_pickaxe', count: 1 })
    assert.equal(result.outcome.code, 'NO_RECIPE_OR_MATERIALS')
    assert.equal(Object.hasOwn(result.outcome.prerequisites, 'nearby_crafting_table'), false)
    assert.equal(result.effect_disposition, 'rejected')
    assert.equal(stationScans, 0)
    assert.equal(calls, 0)
  } finally {
    runtime.gotoBlockInteraction = original
  }
})

test('place_block navigation failure preserves observed displacement as applied effect', async () => {
  const items = [{ name: 'stone', type: 1, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  runtime.bindBot(bot)
  const original = runtime.gotoBlockPlacement
  runtime.gotoBlockPlacement = async () => {
    bot.entity.position = new Vec3(2, 64, 0)
    const error = new Error('No path to placement target')
    error.code = 'NoPath'
    throw error
  }
  try {
    const result = await resources.place_block({
      item: 'stone', position: { x: 4, y: 64, z: 0 }
    })
    assert.equal(result.outcome.code, 'PATHFINDER_PLACE_BLOCK_FAILED')
    assert.equal(result.outcome.status, 'partial')
    assert.equal(result.outcome.moved, 2)
    assert.deepEqual(result.outcome.position_before, { x: 0, y: 64, z: 0 })
    assert.deepEqual(result.outcome.position_after, { x: 2, y: 64, z: 0 })
    assert.equal(result.effect_disposition, 'applied')
  } finally {
    runtime.gotoBlockPlacement = original
  }
})

test('place_block path failure with no displacement remains provably not applied', async () => {
  const items = [{ name: 'stone', type: 1, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  runtime.bindBot(bot)
  const original = runtime.gotoBlockPlacement
  runtime.gotoBlockPlacement = async () => {
    throw new Error('No path to placement target')
  }
  try {
    const result = await resources.place_block({
      item: 'stone', position: { x: 4, y: 64, z: 0 }
    })
    assert.equal(result.outcome.code, 'PATHFINDER_PLACE_BLOCK_FAILED')
    assert.equal(result.outcome.status, 'rejected')
    assert.equal(result.outcome.moved, 0)
    assert.equal(result.effect_disposition, 'not_applied')
  } finally {
    runtime.gotoBlockPlacement = original
  }
})

test('smelt_item rejects missing input before opening or initializing pathfinder', async () => {
  const bot = fakeBot([])
  bot.findBlock = () => { throw new Error('furnace search must not run') }
  runtime.bindBot(bot)
  const original = runtime.ensureMovements
  let calls = 0
  runtime.ensureMovements = async () => { calls += 1 }
  try {
    const result = await resources.smelt_item({
      item: 'raw_iron', count: 2, fuel: 'coal'
    })
    assert.equal(result.outcome.code, 'INPUT_NOT_AVAILABLE')
    assert.equal(result.outcome.prerequisites.required_count, 2)
    assert.equal(result.effect_disposition, 'rejected')
    assert.equal(calls, 0)
  } finally {
    runtime.ensureMovements = original
  }
})

test('smelt_item cannot report no effect after navigating to an obstructed furnace', async () => {
  const bot = fakeBot([
    { name: 'raw_iron', type: 101, count: 2, slot: 0 },
    { name: 'coal', type: 102, count: 1, slot: 1 }
  ])
  const furnacePosition = new Vec3(3, 64, 0)
  bot.findBlock = () => ({ name: 'furnace', position: furnacePosition })
  bot.blockAt = position => ({ name: 'furnace', position })
  bot.openFurnace = async () => ({
    outputItem: () => ({ name: 'iron_ingot', type: 103, count: 1 }),
    close: () => {}
  })
  runtime.bindBot(bot)
  const original = runtime.gotoBlockInteraction
  runtime.gotoBlockInteraction = async () => {
    bot.entity.position = new Vec3(2, 64, 0)
    return { goal_satisfied: true }
  }
  try {
    const result = await resources.smelt_item({
      item: 'raw_iron', count: 2, fuel: 'coal', max_distance: 32
    })
    assert.equal(result.outcome.code, 'FURNACE_OUTPUT_NOT_EMPTY')
    assert.equal(result.outcome.status, 'partial')
    assert.equal(result.effect_disposition, 'applied')
    assert.equal(result.outcome.moved, 2)
    assert.deepEqual(result.outcome.position_before, { x: 0, y: 64, z: 0 })
    assert.deepEqual(result.outcome.position_after, { x: 2, y: 64, z: 0 })
  } finally {
    runtime.gotoBlockInteraction = original
  }
})


test('missing craft ingredients return public recipe alternatives without a second action', async () => {
  const mcData = require('minecraft-data')
  const bot = fakeBot([])
  bot.version = '1.20.4'
  bot.registry = mcData(bot.version)
  bot.recipesFor = () => []
  bot.findBlock = () => null
  bot.findBlocks = () => []
  bot.world.getColumns = () => []
  bot.craft = () => { throw new Error('must not craft missing materials') }
  runtime.bindBot(bot)

  const result = await resources.craft_item({ item: 'stick', count: 4 })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.effect_disposition, 'rejected')
  assert.equal(result.outcome.code, 'NO_RECIPE_OR_MATERIALS')
  const reference = result.outcome.production_reference
  assert.ok(reference, JSON.stringify(result))
  assert.equal(reference.source, 'version_pinned_vanilla_minecraft_data')
  assert.equal(reference.authoritative_for_current_world_recipe, false)
  assert.equal(reference.no_physical_effect, true)
  assert.deepEqual(reference.inventory_before, {})
  assert.ok(reference.root_alternative_dependency_profiles.length > 0)
  assert.equal(Object.hasOwn(reference, 'observed_local_acquisition_sources'), false)
})


test('pickup_items with item selects only a physically identified matching drop', async () => {
  const items = []
  const bot = fakeBot(items)
  const drop = (id, name, x) => ({
    id, name: 'item', position: new Vec3(x, 64, 0), isValid: true,
    getDroppedItem: () => name == null ? null : { name, count: 1 }
  })
  const wrong = drop(3, 'dirt', 1)
  const unknown = drop(4, null, 1.5)
  const wanted = drop(5, 'oak_log', 3)
  bot.entities = { 1: bot.entity, 3: wrong, 4: unknown, 5: wanted }
  runtime.bindBot(bot)
  const previous = runtime.gotoEntity
  const visited = []
  runtime.gotoEntity = async entity => {
    visited.push(entity.id)
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
    bot.emit('playerCollect', bot.entity, entity)
  }
  try {
    const result = await withoutMovementConstruction(() => interactions.pickup_items({
      item: 'oak_log', max_distance: 16, max_items: 3
    }))
    assert.equal(result.outcome.code, 'ITEMS_PICKED_UP')
    assert.equal(result.verified, true)
    assert.deepEqual(visited, [5])
    assert.equal(result.outcome.matching_gain, 1)
    assert.equal(result.outcome.skipped_nonmatching_or_unidentified, 2)
  } finally { runtime.gotoEntity = previous }
})

test('pickup_items pre-arms collection witnesses and skips targets collected incidentally in transit', async () => {
  const items = []
  const bot = fakeBot(items)
  const drop = (id, x) => ({
    id, name: 'item', position: new Vec3(x, 64, 0), isValid: true,
    getDroppedItem: () => ({ name: 'oak_log', count: 1 })
  })
  const first = drop(6, 2)
  const second = drop(7, 3)
  bot.entities = { 1: bot.entity, 6: first, 7: second }
  runtime.bindBot(bot)
  const previous = runtime.gotoEntity
  const visited = []
  runtime.gotoEntity = async entity => {
    visited.push(entity.id)
    if (entity.id !== first.id) throw new Error('incidental pickup should avoid second navigation')
    items.push({ name: 'oak_log', type: 9, count: 2, slot: 1 })
    bot.emit('playerCollect', bot.entity, first)
    bot.emit('playerCollect', bot.entity, second)
  }
  try {
    const result = await withoutMovementConstruction(() => interactions.pickup_items({
      item: 'oak_log', max_distance: 16, max_items: 2
    }))
    assert.equal(result.outcome.code, 'ITEMS_PICKED_UP')
    assert.equal(result.outcome.collected, 2)
    assert.equal(result.outcome.matching_gain, 2)
    assert.deepEqual(visited, [6])
    assert.equal(bot.listenerCount('playerCollect'), 0)
  } finally { runtime.gotoEntity = previous }
})

test('pickup_items cancellation resolves shared collection waiters without leaking listeners', async () => {
  const bot = fakeBot([])
  const drop = {
    id: 9, name: 'item', position: new Vec3(2, 64, 0), isValid: true,
    getDroppedItem: () => ({ name: 'oak_log', count: 1 })
  }
  bot.entities = { 1: bot.entity, 9: drop }
  runtime.bindBot(bot)
  const previous = runtime.gotoEntity
  runtime.gotoEntity = async () => {}
  const scope = runtime.createActionCancellationScope('pickup-cancel-test', 2000)
  try {
    const pending = runtime.runWithActionCancellationScope(scope, () => interactions.pickup_items({
      item: 'oak_log', max_distance: 16, max_items: 1
    }))
    await new Promise(resolve => setImmediate(resolve))
    await scope.cancel('TEST_CANCEL')
    const result = await pending
    assert.equal(result.outcome.status, 'rejected')
    assert.equal(result.outcome.collected, 0)
    assert.equal(bot.listenerCount('playerCollect'), 0)
  } finally { runtime.gotoEntity = previous }
})

test('pickup_items rejects missing matching drop rather than inferring registry possession', async () => {
  const bot = fakeBot([])
  bot.entities[8] = {
    id: 8, name: 'item', position: new Vec3(2, 64, 0), isValid: true,
    getDroppedItem: () => null
  }
  runtime.bindBot(bot)
  const previous = runtime.gotoEntity
  runtime.gotoEntity = () => { throw new Error('unknown drop was targeted') }
  try {
    const result = await interactions.pickup_items({
      item: 'oak_log', max_distance: 16, max_items: 3
    })
    assert.equal(result.outcome.code, 'MATCHING_ITEM_DROP_NOT_OBSERVED')
    assert.equal(result.outcome.status, 'rejected')
    assert.equal(result.outcome.candidates, 0)
    assert.equal(result.outcome.loaded_world_only, true)
  } finally { runtime.gotoEntity = previous }
})

test('an authorized crafting-station placement may attempt setup, but a missing safe location still fails closed', async () => {
  const items = [{name: 'crafting_table', type: 58, count: 1, slot: 0}]
  const bot = fakeBot(items)
  bot.registry.itemsByName.stick = {id: 280, name: 'stick'}
  const recipe = {result: {count: 4}}
  bot.recipesFor = (_id, _meta, _count, table) => table ? [recipe] : []
  bot.findBlock = () => null
  let placed = 0
  bot.placeBlock = async () => {placed++}
  runtime.bindBot(bot)
  const scope = runtime.createActionCancellationScope('craft-scope', 3000)
  scope.authorizedChildActionUnits = new Map([['place_block', '3'.repeat(64)]])
  const {ActionRecoveryJournal} = require('./action_recovery')
  const {createSkillEffectRecorder} = require('./skill_effects')
  const journal = new ActionRecoveryJournal()
  journal.configure(null)
  scope.recordChildEffect = createSkillEffectRecorder(
    journal,
    {
      action_id: 'test-craft-optional-station',
      request_digest: 'b'.repeat(64),
      root_invocation_unit_digest: '1'.repeat(64),
      authorization_unit_digest: '2'.repeat(64)
    },
    new Map([['place_block', '3'.repeat(64)]])
  )
  const result = await runtime.runWithActionCancellationScope(
    scope, () => resources.craft_item({item: 'stick', count: 4})
  )
  assert.equal(result.outcome.code, 'CRAFTING_STATION_SETUP_UNAVAILABLE')
  assert.equal(result.outcome.station_setup.code, 'NO_SAFE_LOCAL_PLACEMENT_TARGET')
  assert.equal(placed, 0)
  assert.equal(result.effect_disposition, 'not_applied')
})

test('smelt_item checks aggregate inventory across slots before furnace lookup', async () => {
  const bot = fakeBot([
    { name: 'raw_iron', type: 4, count: 1, slot: 0 },
    { name: 'raw_iron', type: 4, count: 1, slot: 1 },
    { name: 'coal', type: 5, count: 1, slot: 2 }
  ])
  let searches = 0
  bot.findBlock = () => { searches++; return null }
  runtime.bindBot(bot)
  const result = await resources.smelt_item({
    item: 'raw_iron', count: 2, fuel: 'coal', max_distance: 8
  })
  assert.equal(searches, 1, 'sufficient split inventory must reach furnace availability check')
  assert.equal(result.outcome.code, 'FURNACE_NOT_FOUND')
  assert.equal(result.outcome.status, 'rejected')
})

test('smelt_item never attributes unrelated inventory gain to furnace output', async () => {
  const stock = [
    { name: 'raw_iron', type: 4, count: 1, slot: 0 },
    { name: 'coal', type: 5, count: 1, slot: 1 }
  ]
  const bot = fakeBot(stock)
  const furnaceBlock = { name: 'furnace', position: new Vec3(1, 64, 0) }
  let output = null
  const furnace = Object.assign(new EventEmitter(), {
    outputItem: () => output,
    inputItem: () => null,
    fuelItem: () => null,
    putFuel: async (_type, _metadata, count) => { stock[1].count -= count },
    putInput: async (_type, _metadata, count) => {
      stock[0].count -= count
      output = { name: 'iron_ingot', type: 6, count, slot: 2 }
      // A separate inventory event occurred, but the furnace output was not received.
      stock.push({ name: 'oak_planks', type: 9, count: count, slot: 3 })
      queueMicrotask(() => furnace.emit('update'))
    },
    takeOutput: async () => { output = null },
    close: () => {}
  })
  bot.findBlock = () => furnaceBlock
  bot.blockAt = () => furnaceBlock
  bot.openFurnace = async () => furnace
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.smelt_item({
    item: 'raw_iron', count: 1, fuel: 'coal', max_distance: 8
  }))
  assert.equal(result.outcome.code, 'SMELT_INCOMPLETE', JSON.stringify(result))
  assert.equal(result.outcome.produced, 0)
  assert.equal(result.outcome.inventory_delta.oak_planks, 1)
  assert.equal(result.verified, false)
})

test('smelt navigation failure reports no-effect or partial displacement rather than unknown', async () => {
  for (const displacement of [0, 2]) {
    const bot = fakeBot([
      {name: 'raw_iron', type: 101, count: 1, slot: 0},
      {name: 'coal', type: 102, count: 1, slot: 1}
    ])
    const furnacePosition = new Vec3(4, 64, 0)
    bot.findBlock = () => ({name: 'furnace', position: furnacePosition})
    bot.openFurnace = () => { throw Error('must not open after failed navigation') }
    runtime.bindBot(bot)
    const originalGoto = runtime.gotoBlockInteraction
    runtime.gotoBlockInteraction = async () => {
      bot.entity.position = new Vec3(displacement, 64, 0)
      const failure = new Error('unreachable furnace')
      failure.code = 'NoPath'
      throw failure
    }
    try {
      const result = await withoutMovementConstruction(() => resources.smelt_item({
        item: 'raw_iron', count: 1, fuel: 'coal'
      }))
      assert.equal(result.outcome.code, 'FURNACE_NAVIGATION_INTERRUPTED')
      assert.equal(result.outcome.moved, displacement)
      assert.equal(result.effect_disposition, displacement ? 'applied' : 'not_applied')
      assert.equal(result.outcome.status, displacement ? 'partial' : 'rejected')
      assert.equal(result.outcome.position_after.x, displacement)
    } finally {
      runtime.gotoBlockInteraction = originalGoto
    }
  }
})

test('identity-bound pre-dispatch rejection emits terminal action_result before ack', async () => {
  const { spawn } = require('node:child_process')
  const path = require('node:path')
  const child = spawn(process.execPath, [path.join(__dirname, 'bridge.js')], {
    cwd: __dirname,
    env: process.env,
    stdio: ['pipe', 'pipe', 'pipe']
  })
  let output = ''
  child.stdout.on('data', chunk => { output += chunk.toString() })
  child.stderr.on('data', chunk => { output += chunk.toString() })
  const actionId = 'node-test-dispatch-reject'
  child.stdin.write(JSON.stringify({
    cmd: 'wait',
    request_id: actionId,
    action_id: actionId,
    _request_digest: 'a'.repeat(64),
    _action_invocation_unit_digest: 'b'.repeat(64),
    _action_authorization_unit_digest: 'c'.repeat(64),
    _authorized_child_action_units: {},
    _authorized_child_max_depth: -1,
    _action_effect_class: 'pure',
    _action_side_effect_envelope: [],
    _action_timeout_ms: 1000,
    ms: 1
  }) + '\n')
  const deadline = Date.now() + 3000
  while ((!output.includes('"kind":"action_result"') || !output.includes('"type":"ack"')) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  child.kill()
  const rows = output.split(/\r?\n/).filter(Boolean).map(line => {
    try { return JSON.parse(line) } catch (_) { return null }
  }).filter(Boolean)
  const result = rows.find(row => row.type === 'event' && row.kind === 'action_result')
  const ackRow = rows.find(row => row.type === 'ack' && row.request_id === actionId)
  assert.ok(result, output)
  assert.ok(ackRow, output)
  assert.equal(result.payload.action_id, actionId)
  assert.equal(result.payload.request_digest, 'a'.repeat(64))
  assert.equal(result.payload.outcome.status, 'rejected')
  assert.equal(result.payload.outcome.code, 'ACTION_DISPATCH_REJECTED')
  assert.equal(result.payload.effect_disposition, 'not_applied')
  assert.equal(ackRow.rejected, true)
  assert.equal(ackRow.effect_disposition, 'not_applied')
  assert.ok(rows.indexOf(result) < rows.indexOf(ackRow))
})

test('identity-bound failure after operation entry preserves unknown effect truth', async () => {
  const { spawn } = require('node:child_process')
  const path = require('node:path')
  const child = spawn(process.execPath, [path.join(__dirname, 'bridge.js')], {
    cwd: __dirname,
    env: process.env,
    stdio: ['pipe', 'pipe', 'pipe']
  })
  let output = ''
  child.stdout.on('data', chunk => { output += chunk.toString() })
  child.stderr.on('data', chunk => { output += chunk.toString() })
  const actionId = 'node-test-entered-failure'
  child.stdin.write(JSON.stringify({
    cmd: 'wait', request_id: actionId, action_id: actionId,
    _request_digest: 'd'.repeat(64),
    _action_invocation_unit_digest: 'e'.repeat(64),
    _action_authorization_unit_digest: 'f'.repeat(64),
    _authorized_child_action_units: {},
    _authorized_child_max_depth: 0,
    _action_effect_class: 'invalid-effect-class',
    _action_side_effect_envelope: [],
    _action_timeout_ms: 1000, ms: 1
  }) + '\n')
  const deadline = Date.now() + 3000
  while ((!output.includes('"kind":"action_result"') || !output.includes('"type":"ack"')) && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  child.kill()
  const rows = output.split(/\r?\n/).filter(Boolean).map(line => {
    try { return JSON.parse(line) } catch (_) { return null }
  }).filter(Boolean)
  const result = rows.find(row => row.type === 'event' && row.kind === 'action_result')
  assert.ok(result, output)
  assert.equal(result.payload.action_id, actionId)
  assert.equal(result.payload.outcome.status, 'partial')
  assert.equal(result.payload.outcome.code, 'ACTION_DISPATCH_FAILURE')
  assert.equal(result.payload.outcome.dispatch_operation_entered, true)
  assert.equal(result.payload.effect_disposition, 'unknown')
})

test('canonical reconciliable effect-class ABI reaches effectful dispatcher', async () => {
  const { spawn } = require('node:child_process')
  const path = require('node:path')
  const child = spawn(process.execPath, [path.join(__dirname, 'bridge.js')], {
    cwd: __dirname,
    env: process.env,
    stdio: ['pipe', 'pipe', 'pipe']
  })
  let output = ''
  child.stdout.on('data', chunk => { output += chunk.toString() })
  child.stderr.on('data', chunk => { output += chunk.toString() })
  const actionId = 'node-test-reconcilable-wire'
  child.stdin.write(JSON.stringify({
    cmd: 'wait', request_id: actionId, action_id: actionId,
    _request_digest: '1'.repeat(64),
    _action_invocation_unit_digest: '2'.repeat(64),
    _action_authorization_unit_digest: '3'.repeat(64),
    _authorized_child_action_units: {},
    _authorized_child_max_depth: 0,
    _action_effect_class: 'reconcilable',
    _action_side_effect_envelope: ['time'],
    _action_timeout_ms: 1000,
    ms: 1
  }) + '\n')
  const deadline = Date.now() + 3000
  while (!output.includes('"kind":"action_result"') && Date.now() < deadline) {
    await new Promise(resolve => setTimeout(resolve, 25))
  }
  child.kill()
  const rows = output.split(/\r?\n/).filter(Boolean).map(line => {
    try { return JSON.parse(line) } catch (_) { return null }
  }).filter(Boolean)
  const results = rows.filter(row => row.type === 'event' && row.kind === 'action_result')
  assert.ok(results.length > 0, output)
  assert.equal(results[0].payload.action_id, actionId)
  assert.notEqual(results[0].payload.outcome.code, 'ACTION_DISPATCH_FAILURE')
  assert.notEqual(results[0].payload.outcome.code, 'ACTION_DISPATCH_REJECTED')
  assert.equal(results[0].payload.outcome.code, 'WAIT_COMPLETED')
})
