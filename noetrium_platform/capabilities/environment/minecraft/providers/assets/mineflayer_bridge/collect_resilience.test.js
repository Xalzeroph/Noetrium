'use strict'

const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const test = require('node:test')
const { Vec3 } = require('vec3')

const resources = require('./resources')
const runtime = require('./runtime')

function resilientBot () {
  const items = []
  const bot = new EventEmitter()
  bot._client = new EventEmitter()
  bot.entity = { id: 1, position: new Vec3(0, 64, 0), yaw: 0 }
  bot.inventory = { items: () => items, slots: items }
  bot.heldItem = { name: 'hand', type: null, count: 1, slot: 0 }
  bot.registry = { items: { 9: { id: 9, name: 'oak_log' } }, itemsByName: {}, blocksByName: {} }
  bot.pathfinder = {
    searchRadius: -1,
    movements: { safeToBreak: () => true },
    setMovements: () => {}
  }
  bot.tool = { equipForBlock: async () => {} }
  const near = new Vec3(2, 64, 0)
  const far = new Vec3(6, 64, 0)
  const live = new Map([[near.toString(), true], [far.toString(), true]])
  const blockAt = position => {
    const key = position.toString()
    if (!live.has(key) || !live.get(key)) return { name: 'air', position, drops: [] }
    return { name: 'oak_log', position, drops: [9] }
  }
  bot.blockAt = blockAt
  bot.findBlocks = options => [near, far]
    .map(blockAt)
    .filter(block => block.name !== 'air' && options.matching(block))
    .filter(block => typeof options.useExtraInfo !== 'function' || options.useExtraInfo(block))
    .slice(0, options.count)
    .map(block => block.position)
  let digCalls = 0
  bot.dig = async target => {
    digCalls += 1
    assert.equal(target.position.equals(far), true)
    live.set(far.toString(), false)
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
  }
  return { bot, digCalls: () => digCalls, near, far }
}

test('collect_block skips a proven NoPath target and expands the frontier in the same action', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  const oldEnsure = runtime.ensureMovements
  const oldGotoBlockInteraction = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async (position, timeoutMs) => {
    assert.ok(timeoutMs > 0 && timeoutMs <= 777)
    if (position.equals(fixture.near)) {
      const error = new Error('No path to the goal!')
      error.name = 'NoPath'
      error.code = 'NoPath'
      throw error
    }
    return { target: runtime.vec(position), distance: 0, navigation_goal: 'look_at_block' }
  }
  try {
    const result = await resources.collect_block({
      block: 'oak_log', count: 1, max_distance: 16, _action_provider_window_ms: 777
    })
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(result.outcome.collected_count, 1)
    assert.equal(result.outcome.candidate_strategy, 'verified-sequential-collection')
    assert.equal(result.outcome.segment_target_count, 2)
    assert.deepEqual(result.outcome.unreachable_targets, ['2,64,0'])
    assert.equal(fixture.digCalls(), 1)
  } finally {
    runtime.gotoBlockInteraction = oldGotoBlockInteraction
    runtime.ensureMovements = oldEnsure
  }
})

test('collect_block batches remaining equivalent targets into one native multi-goal reachability search', async () => {
  const items = []
  const bot = new EventEmitter()
  bot._client = new EventEmitter()
  bot.entity = { id: 1, position: new Vec3(0, 64, 0), yaw: 0 }
  bot.inventory = { items: () => items, slots: items }
  bot.heldItem = { name: 'hand', type: null, count: 1, slot: 0 }
  bot.registry = { items: { 9: { id: 9, name: 'oak_log' } }, itemsByName: {}, blocksByName: {} }
  bot.pathfinder = { searchRadius: -1, movements: { safeToBreak: () => true }, setMovements: () => {} }
  bot.tool = { equipForBlock: async () => {} }
  const positions = [1, 2, 3, 4].map(x => new Vec3(x, 64, 0))
  const live = new Set(positions.map(p => p.toString()))
  let selectedReachable = false
  bot.blockAt = position => live.has(position.toString())
    ? { name: 'oak_log', position, drops: [9], canHarvest: () => true, harvestTools: {} }
    : { name: 'air', position, drops: [] }
  bot.findBlocks = options => positions
    .filter(pos => live.has(pos.toString()))
    .map(pos => bot.blockAt(pos))
    .filter(block => options.matching(block))
    .filter(block => typeof options.useExtraInfo !== 'function' || options.useExtraInfo(block))
    .slice(0, options.count)
    .map(block => block.position)
  bot.canDigBlock = block => selectedReachable && block.position.equals(positions[3])
  bot.dig = async block => {
    assert.equal(block.position.equals(positions[3]), true)
    live.delete(block.position.toString())
    items.push({ name: 'oak_log', type: 9, count: 4, slot: 1 })
  }
  runtime.bindBot(bot)
  const originalEnsure = runtime.ensureMovements
  const originalSingle = runtime.gotoBlockInteraction
  const originalAny = runtime.gotoAnyBlockVicinity
  let singleCalls = 0
  let multiCalls = 0
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async position => {
    singleCalls += 1
    if (!position.equals(positions[3])) {
      const error = new Error('No path to the goal!')
      error.name = 'NoPath'
      error.code = 'NoPath'
      throw error
    }
    selectedReachable = true
    return { target: runtime.vec(position), distance: 0, navigation_goal: 'look_at_block' }
  }
  runtime.gotoAnyBlockVicinity = async (candidates, timeoutMs) => {
    multiCalls += 1
    assert.ok(timeoutMs > 0 && timeoutMs <= 1234)
    assert.deepEqual(candidates.map(p => p.toString()), positions.map(p => p.toString()))
    selectedReachable = true
    return {
      target: runtime.vec(positions[3]),
      distance: 0,
      candidate_count: candidates.length,
      selected_candidate_index: 3,
      navigation_goal: 'get_to_any_block'
    }
  }
  try {
    const result = await resources.collect_block({
      block: 'oak_log', count: 4, max_distance: 16,
      _action_timeout_ms: 5000, _action_provider_window_ms: 1234
    })
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED', JSON.stringify(result))
    assert.equal(result.outcome.collected_count, 4)
    assert.equal(multiCalls, 1)
    assert.equal(singleCalls, 0)
  } finally {
    runtime.ensureMovements = originalEnsure
    runtime.gotoBlockInteraction = originalSingle
    runtime.gotoAnyBlockVicinity = originalAny
  }
})

test('collect_block keeps palette matching position-free and applies safety only to world blocks', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  let paletteMatched = false
  let worldFiltered = false
  fixture.bot.findBlocks = options => {
    const paletteBlock = { name: 'oak_log', position: null, drops: [9] }
    paletteMatched = options.matching(paletteBlock) === true
    const worldBlock = fixture.bot.blockAt(fixture.far)
    worldFiltered = typeof options.useExtraInfo === 'function' && options.useExtraInfo(worldBlock) === true
    return paletteMatched && worldFiltered ? [fixture.far] : []
  }
  const oldGotoBlockInteraction = runtime.gotoBlockInteraction
  runtime.gotoBlockInteraction = async position => ({
    target: runtime.vec(position),
    distance: 0,
    navigation_goal: 'look_at_block'
  })
  try {
    const result = await resources.collect_block({
      block: 'oak_log', count: 1, max_distance: 16, _action_timeout_ms: 2000
    })
    assert.equal(paletteMatched, true)
    assert.equal(worldFiltered, true)
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(result.outcome.collected_count, 1)
  } finally {
    runtime.gotoBlockInteraction = oldGotoBlockInteraction
  }
})


test('collect_block exposes unseen loaded-world boundary without autonomous exploration', async () => {
  const items = []
  const bot = new EventEmitter()
  bot._client = new EventEmitter()
  bot.entity = { id: 1, position: new Vec3(0, 64, 0), yaw: 0 }
  bot.inventory = { items: () => items, slots: items }
  bot.heldItem = { name: 'hand', type: null, count: 1, slot: 0 }
  bot.registry = {
    items: { 9: { id: 9, name: 'oak_log' } },
    itemsByName: {},
    blocksByName: { oak_log: { id: 17, name: 'oak_log' } }
  }
  bot.pathfinder = {
    searchRadius: -1,
    movements: { safeToBreak: () => true },
    setMovements: () => {}
  }
  bot.tool = { equipForBlock: async () => {} }
  bot.world = {
    getColumns: () => [
      { chunkX: 0, chunkZ: 0, column: {} },
      { chunkX: 1, chunkZ: 0, column: {} }
    ]
  }
  const target = new Vec3(40, 64, 0)
  let live = true
  bot.blockAt = position => (
    live && position.equals(target)
      ? { name: 'oak_log', position: target, drops: [9] }
      : { name: 'air', position, drops: [] }
  )
  bot.findBlocks = options => {
    const block = bot.blockAt(target)
    if (
      block.name !== 'air' &&
      bot.entity.position.distanceTo(target) <= options.maxDistance &&
      options.matching(block) &&
      (typeof options.useExtraInfo !== 'function' || options.useExtraInfo(block))
    ) return [target]
    return []
  }
  bot.dig = async block => {
    assert.equal(block.position.equals(target), true)
    live = false
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
  }

  runtime.bindBot(bot)
  const oldEnsure = runtime.ensureMovements
  const oldNavigateGoal = runtime.navigateGoal
  const oldGotoBlockInteraction = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  runtime.navigateGoal = async goal => {
    bot.entity.position = new Vec3(goal.x, 64, goal.z)
    return { navigation_attempts: [{ strategy: 'coverage-test', status: 'success' }] }
  }
  runtime.gotoBlockInteraction = async position => ({
    target: runtime.vec(position),
    position: runtime.vec(bot.entity.position),
    distance: bot.entity.position.distanceTo(position),
    navigation_goal: 'look_at_block'
  })
  try {
    const origin = bot.entity.position.clone()
    const result = await resources.collect_block({
      block: 'oak_log', count: 1, max_distance: 32, _action_timeout_ms: 3000
    })
    assert.equal(result.outcome.status, 'rejected')
    assert.equal(result.outcome.code, 'BLOCK_NOT_COLLECTED')
    assert.equal(result.outcome.world_frontier.truth_class, 'observed')
    assert.ok(result.outcome.world_frontier.candidates.length > 0)
    assert.equal(bot.entity.position.equals(origin), true)
    assert.equal(items.length, 0)
  } finally {
    runtime.gotoBlockInteraction = oldGotoBlockInteraction
    runtime.navigateGoal = oldNavigateGoal
    runtime.ensureMovements = oldEnsure
  }
})

test('collect_block records confirmed displacement even if every dig target has NoPath', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  const previousEnsure = runtime.ensureMovements
  const previousGoto = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async () => {
    fixture.bot.entity.position = new Vec3(1, 64, 0)
    const failure = new Error('No path to the goal!')
    failure.name = 'NoPath'
    failure.code = 'NoPath'
    throw failure
  }
  try {
    const result = await resources.collect_block({ block: 'oak_log', count: 1, max_distance: 16 })
    assert.equal(result.outcome.code, 'COLLECTION_SEGMENT_APPLIED')
    assert.equal(result.outcome.collected_count, 0)
    assert.equal(result.outcome.moved, 1)
    assert.equal(result.outcome.position_before.x, 0)
    assert.equal(result.outcome.position_after.x, 1)
    assert.equal(result.effect_disposition, 'applied')
    assert.equal(result.outcome.status, 'partial')
  } finally {
    runtime.ensureMovements = previousEnsure
    runtime.gotoBlockInteraction = previousGoto
  }
})

test('collect_block records tool equip as physical effect even without collected items', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  const previousEnsure = runtime.ensureMovements
  const previousGoto = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  fixture.bot.tool.equipForBlock = async () => {
    fixture.bot.heldItem = { name: 'wooden_pickaxe', type: 270, count: 1 }
  }
  runtime.gotoBlockInteraction = async () => {
    const failure = new Error('No path to the goal!')
    failure.name = 'NoPath'
    failure.code = 'NoPath'
    throw failure
  }
  try {
    const result = await resources.collect_block({ block: 'oak_log', count: 1, max_distance: 16 })
    assert.equal(result.outcome.code, 'COLLECTION_SEGMENT_APPLIED')
    assert.equal(result.outcome.collected_count, 0)
    assert.equal(result.outcome.moved, 0)
    assert.equal(result.outcome.equipment_changed, true)
    assert.equal(result.effect_disposition, 'applied')
  } finally {
    runtime.ensureMovements = previousEnsure
    runtime.gotoBlockInteraction = previousGoto
  }
})


test('collect_block fulfills a multi-block semantic request with per-block evidence', async () => {
  const fixture = resilientBot()
  const bot = fixture.bot
  const items = bot.inventory.items()
  const remaining = new Set([fixture.near.toString(), fixture.far.toString()])
  bot.blockAt = position => remaining.has(position.toString())
    ? { name: 'oak_log', position, drops: [9] }
    : { name: 'air', position, drops: [] }
  bot.findBlocks = options => [fixture.near, fixture.far]
    .map(bot.blockAt)
    .filter(block => block.name !== 'air' && options.matching(block))
    .filter(block => !options.useExtraInfo || options.useExtraInfo(block))
    .slice(0, options.count)
    .map(block => block.position)
  let digs = 0
  bot.dig = async block => {
    assert.equal(remaining.delete(block.position.toString()), true)
    digs += 1
    items.push({ name: 'oak_log', type: 9, count: 1, slot: digs })
  }
  runtime.bindBot(bot)
  const originalEnsure = runtime.ensureMovements
  const originalGoto = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async position => ({
    target: runtime.vec(position), distance: 0
  })
  try {
    const result = await resources.collect_block({
      block: 'oak_log', count: 2, max_distance: 16
    })
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(result.outcome.collected_count, 2)
    assert.equal(digs, 2)
    assert.equal(result.outcome.collection_steps.length, 2)
    assert.deepEqual(
      result.outcome.collection_steps.map(step => step.cumulative_collected_count),
      [1, 2]
    )
    assert.deepEqual(
      result.outcome.collection_steps.map(step => step.block_confirmed_removed),
      [true, true]
    )
  } finally {
    runtime.ensureMovements = originalEnsure
    runtime.gotoBlockInteraction = originalGoto
  }
})


test('collection stops after a physically removed block fails to increase inventory', async () => {
  const positions = [2, 4, 6].map(x => new Vec3(x, 64, 0))
  const remaining = new Set(positions.map(pos => pos.toString()))
  const items = []
  const bot = new EventEmitter()
  bot._client = new EventEmitter()
  bot.entity = { id: 1, position: new Vec3(0, 64, 0), yaw: 0 }
  bot.inventory = { items: () => items, slots: items }
  bot.heldItem = { name: 'hand', type: null, count: 1 }
  bot.registry = { items: { 9: { id: 9, name: 'oak_log' } }, itemsByName: {}, blocksByName: {} }
  bot.pathfinder = { movements: { safeToBreak: () => true }, setMovements: () => {} }
  bot.tool = { equipForBlock: async () => {} }
  bot.canDigBlock = () => true
  bot.blockAt = pos => ({
    name: remaining.has(pos.toString()) ? 'oak_log' : 'air',
    position: pos, drops: [9]
  })
  bot.findBlocks = opts => positions
    .filter(pos => remaining.has(pos.toString()))
    .map(bot.blockAt)
    .filter(block => opts.matching(block) && (!opts.useExtraInfo || opts.useExtraInfo(block)))
    .slice(0, opts.count).map(block => block.position)
  let digs = 0
  bot.dig = async block => {
    digs++
    remaining.delete(block.position.toString())
    if (digs === 1) items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
  }
  runtime.bindBot(bot)
  const old = runtime.ensureMovements
  const oldCapture = runtime.captureItemDropNear
  runtime.captureItemDropNear = () => ({
    pickupTarget: () => null,
    promise: Promise.resolve(null),
    cancel: () => {}
  })
  runtime.ensureMovements = async () => {}
  try {
    const outcome = await resources.collect_block({
      block: 'oak_log', count: 3, max_distance: 16
    })
    assert.equal(digs, 2)
    assert.equal(outcome.outcome.code, 'COLLECTION_SEGMENT_APPLIED')
    assert.equal(outcome.outcome.collected_count, 1)
    assert.deepEqual(outcome.outcome.collection_steps.map(step => step.cumulative_collected_count), [1, 1])
    assert.equal(remaining.has(positions[2].toString()), true)
  } finally {
    runtime.ensureMovements = old
    runtime.captureItemDropNear = oldCapture
  }
})


test('an explicit position selects exactly that observed block without a second mining engine', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  fixture.bot.findBlocks = () => {
    throw new Error('explicit target must not run nearest-block search')
  }
  const oldEnsure = runtime.ensureMovements
  const oldGoto = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async position => ({
    target: runtime.vec(position), distance: 0
  })
  try {
    const result = await resources.collect_block({
      block: 'oak_log', position: runtime.vec(fixture.far),
      count: 1, max_distance: 16
    })
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(fixture.digCalls(), 1)
    assert.deepEqual(result.outcome.target_positions, [runtime.vec(fixture.far)])
  } finally {
    runtime.ensureMovements = oldEnsure
    runtime.gotoBlockInteraction = oldGoto
  }
})

test('an exact block target cannot silently switch to a nearby matching block', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  const oldEnsure = runtime.ensureMovements
  runtime.ensureMovements = async () => {}
  try {
    const missing = await resources.collect_block({
      block: 'stone', position: runtime.vec(fixture.far),
      count: 1, max_distance: 16
    })
    assert.equal(missing.outcome.code, 'EXACT_TARGET_CHANGED')
    assert.equal(missing.outcome.observed_block, 'oak_log')
    assert.equal(fixture.digCalls(), 0)
    const tooMany = await resources.collect_block({
      block: 'oak_log', position: runtime.vec(fixture.far),
      count: 2, max_distance: 16
    })
    assert.equal(tooMany.outcome.code, 'INVALID_EXACT_BLOCK_TARGET')
    assert.equal(fixture.digCalls(), 0)
    const tooFar = await resources.collect_block({
      block: 'oak_log', position: runtime.vec(fixture.far),
      count: 1, max_distance: 4
    })
    assert.equal(tooFar.outcome.code, 'EXACT_TARGET_OUT_OF_RANGE')
    assert.equal(fixture.digCalls(), 0)
  } finally {
    runtime.ensureMovements = oldEnsure
  }
})


test('collect_block count means verified items, not mined source blocks', async () => {
  const fixture = resilientBot()
  const bot = fixture.bot
  const observed = fixture.far
  let intact = true
  const stock = bot.inventory.items()
  bot.findBlocks = opts => intact ? [observed] : []
  bot.blockAt = position => ({
    name: intact ? 'clay' : 'air', position, drops: [9]
  })
  bot.canDigBlock = () => true
  bot.dig = async () => {
    intact = false
    stock.push({ name: 'clay_ball', type: 9, count: 4, slot: 1 })
  }
  bot.registry.items[9] = { id: 9, name: 'clay_ball' }
  runtime.bindBot(bot)
  const old = runtime.ensureMovements
  runtime.ensureMovements = async () => {}
  try {
    const result = await resources.collect_block({
      block: 'clay_ball', count: 4, max_distance: 16
    })
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(result.outcome.collected_count, 4)
    assert.equal(result.outcome.collection_steps.length, 1)
    assert.equal(result.outcome.broken.length, 1)
  } finally { runtime.ensureMovements = old }
})


test('exact block removal confirms world effect even when nothing enters inventory', async () => {
  const fixture = resilientBot()
  const bot = fixture.bot
  let intact = true
  let digs = 0
  bot.tool = null
  bot.blockAt = position => ({
    name: intact ? 'oak_log' : 'air', position, drops: []
  })
  bot.dig = async () => { digs += 1; intact = false }
  bot.findBlocks = () => { throw new Error('target substitution forbidden') }
  runtime.bindBot(bot)
  const oldEnsure = runtime.ensureMovements
  const oldGoto = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async () => ({ distance: 0 })
  try {
    const result = await resources.collect_block({
      block: 'oak_log', position: runtime.vec(fixture.far),
      count: 1, max_distance: 16, effect: 'remove'
    })
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'BLOCK_REMOVED')
    assert.equal(result.outcome.removed_count, 1)
    assert.equal(result.outcome.collected_count, 0)
    assert.equal(result.outcome.broken.length, 1)
    assert.equal(digs, 1)
  } finally {
    runtime.ensureMovements = oldEnsure
    runtime.gotoBlockInteraction = oldGoto
  }
})

test('block removal never mines an unspecified or multi-block target', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  for (const action of [
    { block: 'oak_log', count: 1, max_distance: 16, effect: 'remove' },
    { block: 'oak_log', count: 2, max_distance: 16,
      position: runtime.vec(fixture.far), effect: 'remove' },
    { block: 'oak_log', count: 1, max_distance: 16,
      position: runtime.vec(fixture.far), effect: 'invented' }
  ]) {
    const result = await resources.collect_block(action)
    assert.equal(result.verified, false)
    assert.equal(result.outcome.code, 'INVALID_EXACT_REMOVAL_REQUEST')
  }
  assert.equal(fixture.digCalls(), 0)
})

test('collect_block waits for each segment pickup even after earlier segments increased inventory', async () => {
  const fixture = resilientBot()
  const bot = fixture.bot
  const items = bot.inventory.items()
  const remaining = new Set([fixture.near.toString(), fixture.far.toString()])
  bot.blockAt = position => remaining.has(position.toString())
    ? { name: 'oak_log', position, drops: [9] }
    : { name: 'air', position, drops: [] }
  bot.findBlocks = options => [fixture.near, fixture.far]
    .map(bot.blockAt)
    .filter(block => block.name !== 'air' && options.matching(block))
    .filter(block => !options.useExtraInfo || options.useExtraInfo(block))
    .slice(0, options.count)
    .map(block => block.position)
  let digs = 0
  bot.dig = async block => {
    assert.equal(remaining.delete(block.position.toString()), true)
    digs++
    if (digs === 1) {
      items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
    }
  }
  runtime.bindBot(bot)
  const originalEnsure = runtime.ensureMovements
  const originalGoto = runtime.gotoBlockInteraction
  const originalCapture = runtime.captureItemDropNear
  const originalDroppedName = runtime.droppedItemName
  const originalWait = runtime.waitForInventoryIncrease
  let watches = 0
  let pickups = 0
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async position => ({
    target: runtime.vec(position), distance: 0
  })
  runtime.captureItemDropNear = () => {
    watches++
    return {
      pickupTarget: () => watches === 2 ? { id: 44, isValid: true } : null,
      promise: Promise.resolve(null),
      hasOwnCollection: () => true,
      cancel: () => {}
    }
  }
  runtime.droppedItemName = () => 'oak_log'
  runtime.waitForInventoryIncrease = async (item, previousCount) => {
    assert.equal(item, 'oak_log')
    assert.equal(previousCount, 1)
    pickups++
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 2 })
    return true
  }
  try {
    const result = await resources.collect_block({
      block: 'oak_log', count: 2, max_distance: 16
    })
    assert.equal(digs, 2)
    assert.equal(watches, 2)
    assert.equal(pickups, 1, 'second segment must await its own delayed pickup')
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED', JSON.stringify(result))
    assert.equal(result.outcome.collected_count, 2)
    assert.deepEqual(
      result.outcome.collection_steps.map(step => step.cumulative_collected_count),
      [1, 2]
    )
  } finally {
    runtime.ensureMovements = originalEnsure
    runtime.gotoBlockInteraction = originalGoto
    runtime.captureItemDropNear = originalCapture
    runtime.droppedItemName = originalDroppedName
    runtime.waitForInventoryIncrease = originalWait
  }
})


test('collect_block follows a tracked spawn that precedes item metadata instead of closing partial', async () => {
  const fixture = resilientBot()
  const bot = fixture.bot
  const position = fixture.far
  let live = true
  const items = []
  const inventory = new EventEmitter()
  inventory.items = () => items
  inventory.slots = items
  bot.inventory = inventory
  bot.blockAt = p => live
    ? { name: 'oak_log', position: p, drops: [9], diggable: true }
    : { name: 'air', position: p, drops: [] }
  bot.findBlocks = options => live && options.matching(bot.blockAt(position))
    ? [position]
    : []
  bot.canDigBlock = () => true
  const drop = {
    id: 77,
    name: 'item',
    position: position.offset(0.5, 0.5, 0.5),
    isValid: true,
    getDroppedItem: () => null
  }
  bot.dig = async () => {
    live = false
    setImmediate(() => {
      bot.emit('entitySpawn', drop)
      setImmediate(() => bot.emit('physicsTick'))
    })
  }
  runtime.bindBot(bot)
  const originalGotoEntity = runtime.gotoEntity
  let pickupNavigations = 0
  runtime.gotoEntity = async entity => {
    assert.equal(entity, drop)
    pickupNavigations += 1
    items.push({ name: 'oak_log', type: 9, count: 1, slot: 1 })
    bot.emit('playerCollect', bot.entity, drop)
    inventory.emit('updateSlot', 1, null, items[0])
    return { goal_satisfied: true }
  }
  const scope = runtime.createActionCancellationScope('spawn-before-metadata', 3000)
  try {
    const result = await runtime.runWithActionCancellationScope(scope, () =>
      resources.collect_block({ block: 'oak_log', count: 1, max_distance: 16 })
    )
    assert.equal(pickupNavigations, 1)
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'BLOCKS_COLLECTED')
    assert.equal(result.outcome.collected_count, 1)
  } finally {
    runtime.gotoEntity = originalGotoEntity
  }
})

test('collect_block closes a server-confirmed removed segment at the next physics observation boundary', async () => {
  const fixture = resilientBot()
  const bot = fixture.bot
  const position = fixture.far
  let live = true
  const inventory = new EventEmitter()
  inventory.items = () => []
  inventory.slots = []
  bot.inventory = inventory
  bot.blockAt = p => live
    ? { name: 'oak_log', position: p, drops: [9], diggable: true }
    : { name: 'air', position: p, drops: [] }
  bot.findBlocks = options => live && options.matching(bot.blockAt(position))
    ? [position]
    : []
  bot.canDigBlock = () => true
  bot.dig = async () => {
    live = false
    setImmediate(() => bot.emit('physicsTick'))
  }
  runtime.bindBot(bot)
  const scope = runtime.createActionCancellationScope('removed-without-pickup-proof', 3000)
  const action = runtime.runWithActionCancellationScope(scope, () =>
    resources.collect_block({ block: 'oak_log', count: 1, max_distance: 16 })
  )
  const first = await Promise.race([
    action.then(value => ({ kind: 'result', value })),
    new Promise(resolve => setImmediate(() => setImmediate(() => resolve({ kind: 'stalled' }))))
  ])
  if (first.kind !== 'result') await scope.cancel('TEST_PROBE_COMPLETE')
  assert.equal(first.kind, 'result')
  assert.equal(first.value.effect_disposition, 'applied')
  assert.equal(first.value.outcome.code, 'COLLECTION_SEGMENT_APPLIED')
  assert.equal(first.value.outcome.collected_count, 0)
  assert.equal(first.value.outcome.broken.length, 1)
  assert.equal(first.value.outcome.collection_steps[0].block_confirmed_removed, true)
  assert.equal(bot.listenerCount('physicsTick'), 0)
  assert.equal(bot.listenerCount('itemDrop'), 0)
  assert.equal(bot.listenerCount('playerCollect'), 0)
  assert.equal(inventory.listenerCount('updateSlot'), 0)
})

test('excavate_region journals each exact removal through child effect authority', async () => {
  const fixture = resilientBot()
  runtime.bindBot(fixture.bot)
  const oldEnsure = runtime.ensureMovements
  const oldGoto = runtime.gotoBlockInteraction
  runtime.ensureMovements = async () => {}
  runtime.gotoBlockInteraction = async position => ({ target: runtime.vec(position), distance: 0 })
  const scope = runtime.createActionCancellationScope('excavate-test', 10000)
  const children = []
  scope.recordChildEffect = async (index, actionType, payload, execute) => {
    children.push({ index, actionType, payload })
    const result = await execute({ action_id: `child-${index}` })
    return { ...result, child_effect_ref: `child-${index}` }
  }
  try {
    const result = await runtime.runWithActionCancellationScope(scope, () =>
      resources.excavate_region({
        corner_a: runtime.vec(fixture.far),
        corner_b: runtime.vec(fixture.far),
        max_blocks: 1,
        max_distance: 16
      })
    )
    assert.equal(result.verified, true, JSON.stringify(result))
    assert.equal(result.outcome.code, 'REGION_EXCAVATED')
    assert.equal(result.outcome.removed_count, 1)
    assert.equal(result.outcome.remaining_count, 0)
    assert.equal(children.length, 1)
    assert.equal(children[0].actionType, 'collect_block')
    assert.equal(children[0].payload.effect, 'remove')
    assert.deepEqual(children[0].payload.position, runtime.vec(fixture.far))
  } finally {
    runtime.ensureMovements = oldEnsure
    runtime.gotoBlockInteraction = oldGoto
  }
})

test('excavate_region fail-closes unsafe geometry before any child physical effect', async () => {
  const fixture = resilientBot()
  fixture.bot.pathfinder.movements.safeToBreak = () => false
  runtime.bindBot(fixture.bot)
  const oldEnsure = runtime.ensureMovements
  runtime.ensureMovements = async () => {}
  const scope = runtime.createActionCancellationScope('excavate-unsafe-test', 10000)
  let childCalls = 0
  scope.recordChildEffect = async (_index, _type, _payload, execute) => {
    childCalls += 1
    return execute({ action_id: 'unexpected-child' })
  }
  try {
    const result = await runtime.runWithActionCancellationScope(scope, () =>
      resources.excavate_region({
        corner_a: runtime.vec(fixture.far),
        corner_b: runtime.vec(fixture.far),
        max_blocks: 1,
        max_distance: 16
      })
    )
    assert.equal(result.outcome.status, 'rejected')
    assert.equal(result.outcome.code, 'UNSAFE_EXCAVATION_REGION')
    assert.equal(result.effect_disposition, 'not_applied')
    assert.equal(childCalls, 0)
  } finally {
    runtime.ensureMovements = oldEnsure
  }
})
