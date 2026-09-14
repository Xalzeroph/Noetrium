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
  bot.inventory = {
    items: () => items,
    slots: items
  }
  bot.pathfinder = { setMovements: () => {}, goto: async () => {} }
  bot.registry = { itemsByName: {}, blocksByName: {} }
  return bot
}

async function withoutMovementConstruction (callback) {
  const original = runtime.ensureMovements
  runtime.ensureMovements = async () => {}
  try {
    return await callback()
  } finally {
    runtime.ensureMovements = original
  }
}

test('domain modules expose the complete modular handler surface', () => {
  const handlers = { ...movement, ...resources, ...inventory, ...combat, ...interactions }
  assert.deepEqual(Object.keys(handlers).sort(), [
    'activate_nearest_block', 'attack_entity', 'attack_nearest', 'attack_player',
    'auto_light', 'chest_deposit', 'chest_inspect', 'chest_withdraw',
    'clear_furnace', 'collect_block', 'consume_item', 'craft_item', 'defend_self',
    'discard_item', 'dismount', 'equip_item', 'fish', 'follow_player', 'give_item',
    'go_to_bed', 'goto', 'goto_entity', 'mount', 'move_away', 'pickup_items',
    'place_block', 'ranged_attack', 'show_villager_trades', 'smelt_item', 'stay',
    'till_and_sow', 'trade_villager', 'use_door', 'use_tool_on'
  ])
})

test('result helpers keep applied, partial and rejected semantics distinct', () => {
  assert.equal(runtime.applied('wait', {}, 'OK').verified, true)
  assert.equal(runtime.partial('wait', {}, 'MAYBE').verified, false)
  assert.equal(runtime.rejected('wait', {}, 'NO').outcome.status, 'rejected')
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
  const furnace = {
    outputItem: () => output,
    inputItem: () => null,
    fuelItem: () => null,
    putFuel: async (_type, _metadata, count) => { items[1].count -= count },
    putInput: async (_type, _metadata, count) => {
      items[0].count -= count
      output = { name: 'iron_ingot', type: 6, count, slot: 2 }
    },
    takeOutput: async () => { items.push(output); output = null },
    close: () => {}
  }
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
  bot.findBlock = () => chestBlock
  bot.blockAt = () => chestBlock
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
})

test('mineflayer-pvp combat verifies only damage attributed to this bot', async () => {
  const items = [{ name: 'iron_sword', type: 8, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  const target = { id: 2, name: 'zombie', displayName: 'Zombie', type: 'mob', isValid: true, position: new Vec3(2, 64, 0) }
  bot.entities[2] = target
  bot.equip = async item => { bot.heldItem = item }
  bot.pvp = {
    attack: entity => { bot.emit('attackedTarget'); setTimeout(() => bot.emit('entityHurt', entity, bot.entity), 50) },
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

test('collect_block skips pathfinding when the block is already reachable', async () => {
  const items = []
  const bot = fakeBot(items)
  const position = new Vec3(2, 64, 0)
  let live = { name: 'oak_log', position }
  let gotoCalls = 0
  bot.findBlock = () => live && live.name === 'oak_log' ? live : null
  bot.blockAt = () => live
  bot.lookAt = async () => {}
  bot.pathfinder.goto = async () => { gotoCalls += 1; throw new Error('unexpected goto') }
  bot.dig = async () => {
    live = { name: 'air', position }
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 0 })
  }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'oak_log', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))

  assert.equal(result.verified, true)
  assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
  assert.equal(result.outcome.collected_count, 1)
  assert.equal(gotoCalls, 0)
})

test('collect_block uses an interaction-aware goal for distant blocks', async () => {
  const items = [{ name: 'stone_pickaxe', type: 877, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  bot.world = {}
  bot.pathfinder.movements = {}
  bot.registry.items = { 35: { id: 35, name: 'cobblestone' } }
  bot.registry.itemsByName = { dirt: { id: 9 }, cobblestone: { id: 35, name: 'cobblestone' } }
  bot.registry.blocksByName = {
    chest: { id: 1 }, fire: { id: 2 }, lava: { id: 3 }, water: { id: 4 },
    sand: { id: 5 }, gravel: { id: 6 }, ladder: { id: 7 }, air: { id: 8 }
  }
  bot.registry.blocksArray = []
  const position = new Vec3(8, 64, 0)
  let live = {
    name: 'stone',
    position,
    drops: [35],
    canHarvest: type => type === 877,
    digTime: type => type === 877 ? 1 : 100
  }
  let goalName = null
  bot.findBlock = () => live && live.name === 'stone' ? live : null
  bot.blockAt = () => live
  bot.lookAt = async () => {}
  bot.equip = async item => { bot.heldItem = item }
  bot.pathfinder.goto = async goal => {
    goalName = goal.constructor.name
    bot.entity.position = new Vec3(7, 64, 0)
  }
  bot.dig = async () => {
    live = { name: 'air', position }
    items.push({ name: 'cobblestone', type: 35, count: 1, slot: 1 })
  }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stone', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))

  assert.equal(result.verified, true)
  assert.equal(goalName, 'GoalLookAtBlock')
})

test('collect_block waits for delayed pickup from a vertical block stack', async () => {
  const items = []
  const bot = fakeBot(items)
  const blocks = [
    { name: 'oak_log', position: new Vec3(3, 64, 0) },
    { name: 'oak_log', position: new Vec3(3, 65, 0) }
  ]
  bot.findBlock = () => blocks.find(block => block.name === 'oak_log') || null
  bot.blockAt = position => blocks.find(block => block.position.equals(position)) || { name: 'air', position }
  bot.lookAt = async () => {}
  bot.dig = async live => {
    live.name = 'air'
    setTimeout(() => {
      const held = items.find(item => item.name === 'oak_log')
      if (held) held.count += 1
      else items.push({ name: 'oak_log', type: 9, count: 1, slot: 0 })
    }, 80)
  }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'oak_log', count: 2, max_distance: 16, _action_timeout_ms: 5000
  }))
  assert.equal(result.verified, true)
  assert.equal(result.outcome.collected_count, 2)
  assert.equal(result.outcome.errors.length, 0)
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


test('collect_block follows spawned item when itemDrop metadata is delayed', async () => {
  const items = []
  const bot = fakeBot(items)
  const blocks = [
    { name: 'oak_log', position: new Vec3(3, 64, 0) },
    { name: 'oak_log', position: new Vec3(3, 65, 0) }
  ]
  let nextEntityId = 10
  bot.findBlock = () => blocks.find(block => block.name === 'oak_log') || null
  bot.blockAt = position => blocks.find(block => block.position.equals(position)) || { name: 'air', position }
  bot.lookAt = async () => {}
  bot.dig = async live => {
    const position = live.position.clone()
    live.name = 'air'
    const drop = { id: nextEntityId++, name: 'item', position: position.offset(0.5, 0.5, 0.5), isValid: true, getDroppedItem: () => null }
    bot.entities[drop.id] = drop
    setImmediate(() => { bot.emit('entitySpawn', drop); for (let i = 0; i < 10; i++) bot.emit('physicsTick') })
  }

  runtime.bindBot(bot)
  const originalGotoEntity = runtime.gotoEntity
  runtime.gotoEntity = async entity => {
    const held = items.find(item => item.name === 'oak_log')
    if (held) held.count += 1
    else items.push({ name: 'oak_log', type: 9, count: 1, slot: 0 })
    bot.emit('playerCollect', bot.entity, entity)
    entity.isValid = false
    delete bot.entities[entity.id]
    return { entity_id: entity.id, position: runtime.vec(entity.position), valid: false }
  }
  try {
    const result = await withoutMovementConstruction(() => resources.collect_block({
      block: 'oak_log', count: 2, max_distance: 16, _action_timeout_ms: 8000
    }))
    assert.equal(result.verified, true)
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(result.outcome.collected_count, 2)
    assert.equal(result.outcome.errors.length, 0)
  } finally {
    runtime.gotoEntity = originalGotoEntity
  }
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


test('goto_entity delegates moving targets to runtime GoalFollow navigation', async () => {
  const bot = fakeBot([])
  const target = { id: 2, name: 'zombie', isValid: true, position: new Vec3(4, 64, 0) }
  bot.entities[2] = target
  runtime.bindBot(bot)
  let dynamicCalls = 0
  let staticCalls = 0
  const oldDynamic = runtime.gotoEntity
  const oldStatic = runtime.gotoPos
  runtime.gotoEntity = async entity => { dynamicCalls += 1; return { entity_id: entity.id, valid: true } }
  runtime.gotoPos = async () => { staticCalls += 1; return { distance: 0, within_radius: true } }
  try {
    const result = await movement.goto_entity({ entity: 'zombie', max_distance: 16, radius: 2.5 })
    assert.equal(result.verified, true)
    assert.equal(dynamicCalls, 1)
    assert.equal(staticCalls, 0)
  } finally {
    runtime.gotoEntity = oldDynamic
    runtime.gotoPos = oldStatic
  }
})


test('collect_block rejects an unharvestable block before destructive dig', async () => {
  const bot = fakeBot([])
  const position = new Vec3(2, 64, 0)
  const live = { name: 'stone', position, harvestTools: { 877: true }, canHarvest: () => false }
  let digCalls = 0
  bot.findBlock = () => live
  bot.blockAt = () => live
  bot.lookAt = async () => {}
  bot.dig = async () => { digCalls += 1 }
  runtime.bindBot(bot)
  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stone', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))
  assert.equal(result.verified, false)
  assert.equal(result.outcome.code, 'HARVEST_TOOL_REQUIRED')
  assert.equal(digCalls, 0)
  assert.deepEqual(result.outcome.errors[0].required_tool_ids, [877])
})

test('collect_block equips the fastest harvestable inventory tool before digging', async () => {
  const items = [{ name: 'stone_pickaxe', type: 877, count: 1, slot: 0 }]
  const bot = fakeBot(items)
  bot.registry.items = { 35: { id: 35, name: 'cobblestone' } }
  const position = new Vec3(2, 64, 0)
  const live = {
    name: 'stone',
    position,
    drops: [35],
    canHarvest: type => type === 877,
    digTime: type => type === 877 ? 1 : 100
  }
  bot.findBlock = () => live.name === 'stone' ? live : null
  bot.blockAt = () => live
  bot.lookAt = async () => {}
  bot.equip = async item => { bot.heldItem = item }
  bot.dig = async block => {
    block.name = 'air'
    items.push({ name: 'cobblestone', type: 35, count: 1, slot: 1 })
  }
  runtime.bindBot(bot)

  const result = await withoutMovementConstruction(() => resources.collect_block({
    block: 'stone', count: 1, max_distance: 16, _action_timeout_ms: 2000
  }))

  assert.equal(result.verified, true)
  assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
  assert.equal(bot.heldItem.name, 'stone_pickaxe')
  assert.equal(result.outcome.broken[0].selected_tool.name, 'stone_pickaxe')
})


test('collect_block follows the actual stone drop identity instead of the block name', async () => {
  const items = []
  const bot = fakeBot(items)
  bot.registry.items = { 35: { id: 35, name: 'cobblestone' } }
  bot.heldItem = { name: 'wooden_pickaxe', type: 877 }
  const position = new Vec3(2, 64, 0)
  const live = { name: 'stone', position, drops: [35], canHarvest: type => type === 877 }
  bot.findBlock = () => live.name === 'stone' ? live : null
  bot.blockAt = () => live
  bot.lookAt = async () => {}
  bot.dig = async block => {
    block.name = 'air'
    const drop = { id: 30, name: 'item', isValid: true, position: position.offset(0.5, 0.5, 0.5), getDroppedItem: () => ({ name: 'cobblestone' }) }
    bot.entities[drop.id] = drop
    setImmediate(() => bot.emit('itemDrop', drop))
  }
  runtime.bindBot(bot)
  const oldGoto = runtime.gotoEntity
  runtime.gotoEntity = async entity => {
    items.push({ name: 'cobblestone', type: 35, count: 1, slot: 0 })
    items.push({ name: 'dirt', type: 10, count: 5, slot: 1 })
    bot.emit('playerCollect', bot.entity, entity)
    entity.isValid = false
    return { entity_id: entity.id, valid: false }
  }
  try {
    const result = await withoutMovementConstruction(() => resources.collect_block({
      block: 'stone', count: 1, max_distance: 16, _action_timeout_ms: 5000
    }))
    assert.equal(result.verified, true)
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(result.outcome.inventory_delta.cobblestone, 1)
    assert.equal(result.outcome.inventory_delta.dirt, 5)
    assert.equal(result.outcome.collected_count, 1)
    assert.equal(result.outcome.grounded_collected_items, 1)
    assert.equal(result.outcome.grounded_collected_blocks, 1)
  } finally {
    runtime.gotoEntity = oldGoto
  }
})


test('read-only observe_entities without action_id bypasses action recovery identity', async () => {
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
})
