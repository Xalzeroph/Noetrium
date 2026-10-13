'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const mcData = require('minecraft-data')('1.21.1')
const { Vec3 } = require('vec3')
const runtime = require('./runtime')
const movement = require('./movement')
const inventory = require('./inventory')

function baseBot () {
  const originalMovements = {
    safeToBreak: () => true
  }
  const bot = {
    version: '1.21.1',
    registry: mcData,
    entity: { position: new Vec3(0, 64, 0), effects: {}, onGround: true },
    entities: {},
    inventory: { items: () => [], slots: [] },
    heldItem: null,
    pathfinder: {
      movements: originalMovements,
      setMovements: value => { bot.pathfinder.movements = value },
      getPathTo: () => ({ status: 'success' }),
      goto: async () => {},
      stop: () => {}
    },
    findBlock: () => null,
    blockAt: () => null,
    clearControlStates: () => {},
    stopDigging: () => {}
  }
  return bot
}

test('valid block absent from the observed world does not auto-recover through registry search', async () => {
  const bot = baseBot()
  runtime.bindBot(bot)
  const result = await movement.goto_block({ block: 'diamond_ore', max_distance: 64 })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'BLOCK_NOT_FOUND')
  assert.equal(result.outcome.target_classification, 'block')
  assert.equal(result.outcome.prerequisites.nearby_target_observed, false)
  assert.equal(Object.hasOwn(result.outcome.prerequisites, 'instruction'), false)
  assert.equal(Object.hasOwn(result.outcome, 'recovery'), false)
})

test('abstract item family rejection reports registry facts without a selected strategy', async () => {
  const bot = baseBot()
  runtime.bindBot(bot)
  const result = await inventory.equip_item({ item: 'pickaxe', destination: 'hand' })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'ITEM_NOT_AVAILABLE')
  assert.equal(result.outcome.target_classification, 'item_family')
  assert.equal(result.outcome.prerequisites.exact_registry_item, false)
  assert.ok(result.outcome.prerequisites.concrete_registry_candidates.includes('wooden_pickaxe'))
  assert.ok(result.outcome.prerequisites.concrete_registry_candidates.includes('diamond_pickaxe'))
  assert.equal(Object.hasOwn(result.outcome.prerequisites, 'selected_concrete_item'), false)
  assert.equal(Object.hasOwn(result.outcome.prerequisites, 'declared_plan'), false)
  assert.equal(Object.hasOwn(result.outcome, 'recovery'), false)
})

test('missing exact craftable item reports inventory constraint only', async () => {
  const bot = baseBot()
  runtime.bindBot(bot)
  const result = await inventory.equip_item({ item: 'wooden_pickaxe', destination: 'hand' })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.target_classification, 'item')
  assert.equal(result.outcome.prerequisites.inventory_contains_requested_item, false)
  assert.equal(result.outcome.prerequisites.exact_registry_item, true)
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['item'],
    rejected_value: 'wooden_pickaxe',
    validity: { until_state_change: [['inventory']] }
  }])
  assert.equal(Object.hasOwn(result.outcome, 'recovery'), false)
})


test('goto_block failure exposes passive frontier observations without a hidden exploration policy', async () => {
  const base = baseBot()
  const bot = Object.assign(new EventEmitter(), base)
  bot.world = { getColumns: () => [
    { chunkX: 0, chunkZ: 0, column: {} },
    { chunkX: 1, chunkZ: 0, column: {} }
  ] }
  runtime.bindBot(bot)
  const origin = bot.entity.position.clone()
  const result = await movement.goto_block({ block: 'diamond_ore', max_distance: 32 })
  assert.equal(result.outcome.status, 'rejected')
  assert.equal(result.outcome.code, 'BLOCK_NOT_FOUND')
  assert.equal(result.effect_disposition, 'rejected')
  assert.equal(result.outcome.world_frontier.truth_class, 'observed')
  assert.ok(result.outcome.world_frontier.candidates.length > 0)
  assert.equal(bot.entity.position.equals(origin), true)
  assert.equal(Object.hasOwn(result.outcome, 'recovery'), false)
})

test('goto_block acknowledges a verified standing target without pathfinder search', async () => {
  const bot = baseBot()
  const blockPosition = new Vec3(0, 63, 0)
  let worldQueries = 0
  bot.blockAt = position => (
    position.equals(blockPosition)
      ? { name: 'grass_block', position: blockPosition }
      : { name: 'air', position }
  )
  bot.findBlocks = () => { worldQueries += 1; throw new Error('must not scan when already at goal') }
  bot.registry.blocksByName = { grass_block: { id: 1, name: 'grass_block' } }
  runtime.bindBot(bot)

  const result = await movement.goto_block({
    block: 'grass_block', max_distance: 32, _action_timeout_ms: 100
  })
  assert.equal(result.outcome.code, 'BLOCK_REACHED')
  assert.equal(result.outcome.goal_satisfied, true)
  assert.equal(result.outcome.moved, 0)
  assert.equal(result.outcome.status, 'satisfied')
  assert.equal(result.effect_disposition, 'not_applied')
  assert.equal(result.verified, false)
  assert.equal(worldQueries, 0)
  assert.deepEqual(result.outcome.block_position, { x: 0, y: 63, z: 0 })
})

test('goto_block shares all terminal offsets with pathfinder and never scans a satisfied adjacent target', async () => {
  const bot = baseBot()
  const east = new Vec3(1, 64, 0)
  bot.registry.blocksByName = { oak_log: { id: 17, name: 'oak_log' } }
  bot.blockAt = position => ({
    name: position.equals(east) ? 'oak_log' : 'air',
    position
  })
  bot.findBlocks = () => { throw new Error('unnecessary scan from satisfied goal') }
  runtime.bindBot(bot)
  const result = await movement.goto_block({
    block: 'oak_log', max_distance: 32, _action_timeout_ms: 100
  })
  assert.equal(result.verified, false, JSON.stringify(result))
  assert.equal(result.effect_disposition, 'not_applied')
  assert.equal(result.outcome.goal_satisfied, true)
  assert.equal(result.outcome.code, 'BLOCK_REACHED')
  assert.deepEqual(result.outcome.block_position, { x: 1, y: 64, z: 0 })
  assert.equal(new runtime.GoalAnyGetToBlock([east]).isEnd(bot.entity.position.floored()), true)
})


test('goto_block immediate goal cannot bypass declared loaded-world search radius', async () => {
  const bot = baseBot()
  bot.registry.blocksByName = { dirt: { id: 3, name: 'dirt' } }
  // [0,-2,0] is a legal get-to-block endpoint, but outside max_distance=1.
  const below = bot.entity.position.floored().offset(0, -2, 0)
  bot.blockAt = position => ({
    name: position.equals(below) ? 'dirt' : 'air', position
  })
  let scanCount = 0
  bot.findBlocks = () => { scanCount += 1; return [] }
  runtime.bindBot(bot)
  const result = await movement.goto_block({ block: 'dirt', max_distance: 1 })
  assert.equal(scanCount, 1)
  assert.equal(result.outcome.code, 'BLOCK_NOT_FOUND')
  assert.equal(result.effect_disposition, 'rejected')
})
