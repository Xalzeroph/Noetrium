'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { Vec3 } = require('vec3')
const { observedBiomeName, verifySetupProjection, waitForSetupProjection } = require('./setup_verification')

function botFixture () {
  const blocks = new Map()
  const entity = {
    id: 1,
    position: new Vec3(10.25, 64, 20.75),
    equipment: [null, null, null, null, null, null],
    effects: {}
  }
  const bot = new EventEmitter()
  bot.entity = entity
  bot.entities = { 1: entity }
  bot.registry = {
    effectsByName: { Blindness: { id: 14, name: 'Blindness' } },
    biomes: { 39: { id: 39, name: 'plains' } },
    biomesByName: { plains: { id: 39, name: 'plains' } }
  }
  bot.game = { dimension: 'overworld' }
  bot.rainState = 0
  bot.thunderState = 0
  bot.time = { timeOfDay: 6000 }
  bot.inventory = new EventEmitter()
  bot.inventory.items = () => []
  bot.inventory.slots = Array(46).fill(null)
  bot._client = new EventEmitter()
  bot.blockAt = position => {
    const key = `${Math.floor(position.x)},${Math.floor(position.y)},${Math.floor(position.z)}`
    return blocks.get(key) || {
      name: 'air', position,
      biome: { name: 'forest' }
    }
  }
  bot._blocks = blocks
  return bot
}

function setBlock (bot, x, y, z, name, biome = 'forest') {
  bot._blocks.set(`${x},${y},${z}`, {
    name, position: new Vec3(x, y, z), biome: { name: biome }
  })
}

test('one compact proof verifies a 275-cell fill without expanding wire commands', () => {
  const bot = botFixture()
  for (let x = 11; x <= 15; x++) {
    for (let y = 64; y <= 74; y++) {
      for (let z = 21; z <= 25; z++) setBlock(bot, x, y, z, 'oak_log')
    }
  }
  setBlock(bot, 10, 64, 20, 'grass_block', 'forest')
  const proof = verifySetupProjection(bot, {
    dimension: 'overworld', biome: 'forest', weather: 'clear',
    initial_inventory: [], initial_mobs: [],
    world_ops: [{
      operation_id: 'logs', kind: 'fill', anchor: 'agent',
      start: [1, 0, 1], end: [5, 10, 5], block: 'oak_log'
    }]
  })
  assert.equal(proof.verified, true)
  const fill = proof.checks.find(row => row.kind === 'fill')
  assert.equal(fill.expected_count, 275)
  assert.equal(fill.matched_count, 275)
  assert.equal(fill.mismatch_count, 0)
  assert.deepEqual(fill.mismatch_sample, [])
  assert.ok(JSON.stringify(fill).length < 320)
})

test('fill proof fails closed and keeps only a bounded mismatch sample', () => {
  const bot = botFixture()
  for (let x = 11; x <= 15; x++) {
    for (let y = 64; y <= 74; y++) {
      for (let z = 21; z <= 25; z++) setBlock(bot, x, y, z, 'stone')
    }
  }
  const proof = verifySetupProjection(bot, {
    initial_inventory: [], initial_mobs: [],
    world_ops: [{
      operation_id: 'logs', kind: 'fill', anchor: 'agent',
      start: [1, 0, 1], end: [5, 10, 5], block: 'oak_log'
    }]
  })
  assert.equal(proof.verified, false)
  const fill = proof.checks.find(row => row.kind === 'fill')
  assert.equal(fill.mismatch_count, 275)
  assert.equal(fill.mismatch_sample.length, 8)
})

test('setblock summon effect inventory mobs and environment are live-read back', () => {
  const bot = botFixture()
  bot.time.timeOfDay = 18000
  bot.thunderState = 1
  setBlock(bot, 10, 64, 20, 'grass_block', 'forest')
  setBlock(bot, 12, 64, 20, 'crafting_table')
  bot.inventory.items = () => [{ name: 'wooden_axe', count: 1 }]
  bot.entity.effects[14] = { id: 14, amplifier: 1, duration: 5900 }
  bot.entities[2] = {
    id: 2, name: 'zombie', type: 'mob', isValid: true,
    position: new Vec3(13.25, 64, 20.75)
  }
  const proof = verifySetupProjection(bot, {
    dimension: 'overworld', biome: 'forest', weather: 'thunder', start_at_night: true,
    initial_inventory: [{ item: 'wooden_axe', count: 1 }],
    initial_mobs: [{ entity: 'zombie', count: 1 }],
    world_ops: [
      { operation_id: 'table', kind: 'set_block', anchor: 'agent', position: [2, 0, 0], block: 'crafting_table' },
      { operation_id: 'zombie', kind: 'summon', anchor: 'agent', position: [3, 0, 0], entity: 'zombie' },
      { operation_id: 'blind', kind: 'effect', target: 'agent', effect: 'blindness', duration_seconds: 300, amplifier: 1, hide_particles: true }
    ]
  })
  assert.equal(proof.verified, true, JSON.stringify(proof.failures))
  assert.equal(proof.checks.find(row => row.kind === 'summon').observed_count, 1)
  assert.equal(proof.checks.find(row => row.kind === 'effect').observed_amplifier, 1)
})

test('empty initial inventory is an asserted postcondition, not an omitted check', () => {
  const bot = botFixture()
  bot.inventory.items = () => [{ name: 'diamond', count: 1 }]
  const proof = verifySetupProjection(bot, {
    initial_inventory: [], initial_mobs: [], world_ops: []
  })
  assert.equal(proof.verified, false)
  assert.equal(proof.failures[0].kind, 'initial_inventory_empty')
})


test('biome readback falls back to loaded world biome id when block biome metadata is empty', () => {
  const bot = botFixture()
  bot.blockAt = position => ({ name: 'air', position, biome: { name: '' } })
  bot.world = {
    getColumnAt: () => ({}),
    getBiome: () => 39
  }
  assert.equal(observedBiomeName(bot), 'plains')
  const proof = verifySetupProjection(bot, {
    biome: 'plains', initial_inventory: [], initial_mobs: [], world_ops: []
  })
  assert.equal(proof.verified, true, JSON.stringify(proof.failures))
})

test('setup convergence is event driven and resolves on inventory update without polling', async () => {
  const bot = botFixture()
  let items = []
  bot.inventory.items = () => items
  const started = process.hrtime.bigint()
  const pending = waitForSetupProjection(bot, {
    initial_inventory: [{ item: 'diamond_axe', count: 1 }],
    initial_mobs: [], world_ops: []
  }, 1000)
  setTimeout(() => {
    items = [{ name: 'diamond_axe', count: 1 }]
    bot.inventory.emit('updateSlot', 36, null, items[0])
  }, 5)
  const proof = await pending
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6
  assert.equal(proof.verified, true, JSON.stringify(proof.failures))
  assert.equal(proof.timed_out, false)
  assert.ok(elapsedMs < 100, `event-driven convergence took ${elapsedMs.toFixed(2)}ms`)
})


test('survival anchor convergence wakes on physicsTick without polling', async () => {
  const bot = botFixture()
  bot.entity.onGround = false
  const started = process.hrtime.bigint()
  const pending = waitForSetupProjection(bot, { require_physical_anchor: true }, 1000)
  setTimeout(() => {
    bot.entity.position = new Vec3(10.25, 62, 20.75)
    bot.entity.onGround = true
    bot.emit('physicsTick')
  }, 5)
  const proof = await pending
  const elapsedMs = Number(process.hrtime.bigint() - started) / 1e6
  assert.equal(proof.verified, true, JSON.stringify(proof.failures))
  assert.equal(proof.timed_out, false)
  const anchor = proof.checks.find(row => row.kind === 'physical_anchor')
  assert.equal(anchor.observed_on_ground, true)
  assert.equal(anchor.observed_position.y, 62)
  assert.ok(elapsedMs < 100, `physics convergence took ${elapsedMs.toFixed(2)}ms`)
})

test('MineDojo numeric inventory slots are verified as physical slots, not aggregate counts', () => {
  const bot = botFixture()
  bot.inventory.slots[37] = { name: 'diamond_axe', count: 1 } // source slot 1 -> hotbar.1
  bot.inventory.slots[38] = { name: 'diamond_hoe', count: 1 } // source slot 2 -> hotbar.2
  bot.inventory.slots[39] = { name: 'diamond_sword', count: 1 }
  bot.inventory.slots[40] = { name: 'diamond_shovel', count: 1 }
  bot.entity.equipment[0] = { name: 'diamond_pickaxe', count: 1 }
  bot.inventory.items = () => [
    bot.inventory.slots[37], bot.inventory.slots[38], bot.inventory.slots[39], bot.inventory.slots[40]
  ]
  const expected = [
    { item: 'diamond_axe', count: 1, slot: '1' },
    { item: 'diamond_hoe', count: 1, slot: '2' },
    { item: 'diamond_sword', count: 1, slot: '3' },
    { item: 'diamond_shovel', count: 1, slot: '4' },
    { item: 'diamond_pickaxe', count: 1, slot: 'mainhand' }
  ]
  const proof = verifySetupProjection(bot, { initial_inventory: expected, initial_mobs: [], world_ops: [] })
  assert.equal(proof.verified, true, JSON.stringify(proof.failures))

  // Same aggregate items, wrong physical slot: must fail closed.
  bot.inventory.slots[37] = null
  bot.inventory.slots[41] = { name: 'diamond_axe', count: 1 }
  const wrong = verifySetupProjection(bot, { initial_inventory: expected, initial_mobs: [], world_ops: [] })
  assert.equal(wrong.verified, false)
  assert.equal(wrong.failures[0].kind, 'initial_inventory_slot')
  assert.equal(wrong.failures[0].slot, 1)
})


test('biome verification defers until client reaches server-authoritative voxel', async () => {
  const bot = botFixture()
  bot.entity.position = new Vec3(10.25, 64, 20.75)
  setBlock(bot, 10, 64, 20, 'grass_block', 'dark_forest')
  const setup = {
    biome: 'swamp',
    authority_position: { x: 160.25, y: 70, z: -96.75 },
    initial_inventory: [], initial_mobs: [], world_ops: []
  }

  const stale = verifySetupProjection(bot, setup)
  assert.equal(stale.verified, false)
  assert.equal(stale.failures.length, 1)
  assert.equal(stale.failures[0].kind, 'authority_position')
  assert.equal(stale.checks.some(row => row.kind === 'biome'), false)

  const pending = waitForSetupProjection(bot, setup, 1000)
  setTimeout(() => {
    bot.entity.position = new Vec3(160.25, 70, -96.75)
    setBlock(bot, 160, 70, -97, 'air', 'swamp')
    bot.emit('forcedMove')
  }, 5)
  const proof = await pending
  assert.equal(proof.verified, true, JSON.stringify(proof.failures))
  assert.equal(proof.timed_out, false)
  assert.equal(proof.checks.find(row => row.kind === 'authority_position').ok, true)
  assert.equal(proof.checks.find(row => row.kind === 'biome').observed, 'swamp')
})


test('aligned authoritative position still fails closed on a real biome mismatch', () => {
  const bot = botFixture()
  const proof = verifySetupProjection(bot, {
    biome: 'swamp',
    authority_position: { x: 10.25, y: 64, z: 20.75 },
    initial_inventory: [], initial_mobs: [], world_ops: []
  })
  assert.equal(proof.verified, false)
  assert.equal(proof.failures.length, 1)
  assert.equal(proof.failures[0].kind, 'biome')
  assert.equal(proof.failures[0].observed, 'forest')
})
