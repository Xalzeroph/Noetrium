'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const minecraftData = require('minecraft-data')
const { Vec3 } = require('vec3')
const resources = require('./resources')
const runtime = require('./runtime')

function harvestFixture (blockName, inventoryItems = []) {
  const data = minecraftData('1.21.1')
  const definition = data.blocksByName[blockName]
  const position = new Vec3(4, 32, 0)
  const live = {
    name: blockName,
    position,
    drops: definition.drops,
    harvestTools: definition.harvestTools,
    canHarvest: () => false
  }
  let equipCalls = 0
  const bot = {
    version: '1.21.1',
    registry: data,
    entity: { id: 1, position: new Vec3(0, 32, 0), effects: {}, onGround: true },
    entities: {},
    inventory: { items: () => inventoryItems, slots: [] },
    heldItem: null,
    pathfinder: {
      movements: { safeToBreak: () => true },
      setMovements: () => {},
      stop: () => {}
    },
    tool: {
      equipForBlock: async () => {
        equipCalls += 1
        const error = new Error('no harvestable tool')
        error.name = 'NoItem'
        throw error
      }
    },
    findBlocks: options => {
      // Mirror Mineflayer's two-stage contract: palette blocks have no world
      // position, while useExtraInfo receives a materialized block.
      const palette = { name: blockName, position: null, drops: definition.drops }
      if (!options.matching(palette)) return []
      if (typeof options.useExtraInfo === 'function' && !options.useExtraInfo(live)) return []
      return [position]
    },
    blockAt: query => query && query.equals(position) ? { ...live } : null,
    dig: async () => { throw new Error('dig must not run without a harvest tool') },
    clearControlStates: () => {},
    stopDigging: () => {}
  }
  bot._testEquipCalls = () => equipCalls
  return bot
}

async function collectWithoutMovementConstruction (blockName, inventoryItems = []) {
  const bot = harvestFixture(blockName, inventoryItems)
  runtime.bindBot(bot)
  const oldEnsure = runtime.ensureMovements
  runtime.ensureMovements = async () => {}
  try {
    const result = await resources.collect_block({
      block: blockName,
      count: 1,
      max_distance: 32,
      _action_timeout_ms: 2000
    })
    return { result, bot }
  } finally {
    runtime.ensureMovements = oldEnsure
  }
}

test('iron ore exposes physical harvest tool constraints without a strategy', async () => {
  const { result, bot } = await collectWithoutMovementConstruction('iron_ore')
  assert.equal(result.outcome.code, 'HARVEST_TOOL_REQUIRED')
  assert.ok(Array.isArray(result.outcome.prerequisites.acceptable_tools))
  assert.ok(result.outcome.prerequisites.acceptable_tools.includes('stone_pickaxe'))
  assert.equal(result.outcome.prerequisites.held_tool, null)
  assert.deepEqual(result.outcome.prerequisites.owned_acceptable_tools, [])
  assert.deepEqual(result.outcome.prerequisites.retry_requires_state_change, ['inventory'])
  assert.deepEqual(result.outcome.rejected_argument_constraints, [{
    argument_path: ['block'],
    rejected_value: 'iron_ore',
    validity: { until_state_change: [['inventory']] }
  }])
  assert.equal(bot._testEquipCalls(), 0)
  assert.equal(Object.hasOwn(result.outcome, 'recovery'), false)
  assert.equal(Object.hasOwn(result.outcome.prerequisites, 'tool_recovery_selection'), false)
})

test('diamond ore does not select a tool or construct a prerequisite policy', async () => {
  const { result } = await collectWithoutMovementConstruction('diamond_ore')
  assert.equal(result.outcome.code, 'HARVEST_TOOL_REQUIRED')
  assert.ok(result.outcome.prerequisites.acceptable_tools.includes('iron_pickaxe'))
  assert.equal(Object.hasOwn(result.outcome, 'recovery'), false)
  assert.equal(Object.hasOwn(result.outcome.prerequisites, 'selected_plan'), false)
})


test('multi-target missing-tool proof short-circuits before pathfinder navigation', async () => {
  const bot = harvestFixture('iron_ore')
  const definition = bot.registry.blocksByName.iron_ore
  const positions = [new Vec3(8, 32, 0), new Vec3(12, 32, 0)]
  const blocks = positions.map(position => ({
    name: 'iron_ore', position, drops: definition.drops,
    harvestTools: definition.harvestTools, canHarvest: () => false
  }))
  bot.findBlocks = options => blocks
    .filter(block => options.matching({
      name: block.name, position: null, drops: block.drops
    }) && (!options.useExtraInfo || options.useExtraInfo(block)))
    .map(block => block.position)
  bot.blockAt = query => blocks.find(block => block.position.equals(query)) || null
  bot.canDigBlock = () => false
  runtime.bindBot(bot)
  const oldEnsure = runtime.ensureMovements
  const oldNavigate = runtime.gotoAnyBlockVicinity
  let navigationCalls = 0
  runtime.ensureMovements = async () => {}
  runtime.gotoAnyBlockVicinity = async () => {
    navigationCalls += 1
    throw new Error('navigation must not run when every candidate lacks a usable tool')
  }
  try {
    const result = await resources.collect_block({
      block: 'iron_ore', count: 2, max_distance: 32, _action_timeout_ms: 2000
    })
    assert.equal(result.outcome.code, 'HARVEST_TOOL_REQUIRED')
    assert.equal(result.outcome.target_count, 2)
    assert.deepEqual(result.outcome.prerequisites.owned_acceptable_tools, [])
    assert.deepEqual(result.outcome.prerequisites.retry_requires_state_change, ['inventory'])
    assert.deepEqual(result.outcome.rejected_argument_constraints, [{
      argument_path: ['block'],
      rejected_value: 'iron_ore',
      validity: { until_state_change: [['inventory']] }
    }])
    assert.equal(navigationCalls, 0)
    assert.equal(bot._testEquipCalls(), 0)
  } finally {
    runtime.ensureMovements = oldEnsure
    runtime.gotoAnyBlockVicinity = oldNavigate
  }
})

test('preflight preserves native tool selection when a compatible tool is owned', async () => {
  const data = minecraftData('1.21.1')
  const stonePickaxe = data.itemsByName.stone_pickaxe
  const { result, bot } = await collectWithoutMovementConstruction('iron_ore', [{
    name: 'stone_pickaxe', type: stonePickaxe.id, count: 1
  }])
  assert.equal(result.outcome.code, 'HARVEST_TOOL_REQUIRED')
  assert.equal(bot._testEquipCalls(), 1)
})
