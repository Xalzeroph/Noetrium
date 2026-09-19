'use strict'

const { Vec3 } = require('vec3')
const runtime = require('./runtime')

const DOOR_NAMES = new Set([
  'oak_door', 'spruce_door', 'birch_door', 'jungle_door', 'acacia_door',
  'dark_oak_door', 'mangrove_door', 'cherry_door', 'bamboo_door', 'crimson_door', 'warped_door'
])
const BED_NAMES = new Set([
  'white_bed', 'orange_bed', 'magenta_bed', 'light_blue_bed', 'yellow_bed', 'lime_bed',
  'pink_bed', 'gray_bed', 'light_gray_bed', 'cyan_bed', 'purple_bed', 'blue_bed',
  'brown_bed', 'green_bed', 'red_bed', 'black_bed'
])
const RIDEABLE_NAMES = new Set(['boat', 'chest_boat', 'minecart', 'horse', 'donkey', 'mule', 'camel', 'pig', 'strider'])

function blockProperty (block, name) {
  const properties = block && block.getProperties()
  return properties && Object.prototype.hasOwnProperty.call(properties, name) ? properties[name] : undefined
}

function nearbyBlock (predicate, maxDistance) {
  const bot = runtime.getBot()
  return typeof bot.findBlock === 'function'
    ? bot.findBlock({ matching: predicate, maxDistance })
    : null
}

async function navigateToBlock (block) {
  return runtime.gotoBlockInteraction(block.position)
}

async function activateBlock (block) {
  const bot = runtime.getBot()
  if (typeof bot.activateBlock !== 'function') throw new Error('provider does not expose activateBlock')
  await bot.activateBlock(block)
}

async function useDoor (msg) {
  const action = { max_distance: Number(msg.max_distance || 16) }
  const door = nearbyBlock(block => block && DOOR_NAMES.has(block.name), action.max_distance)
  if (!door) return runtime.rejected('use_door', action, 'DOOR_NOT_FOUND')
  await navigateToBlock(door)
  const before = blockProperty(door, 'open')
  await activateBlock(door)
  await runtime.sleep(100)
  const afterBlock = runtime.getBot().blockAt(door.position)
  const after = blockProperty(afterBlock, 'open')
  const details = { position: runtime.vec(door.position), before, after }
  if (after === true || (before !== true && after === undefined)) return runtime.applied('use_door', action, 'DOOR_ACTIVATED', details)
  return runtime.partial('use_door', action, 'DOOR_STATE_NOT_CONFIRMED', details)
}

async function goToBed (msg) {
  const bot = runtime.getBot()
  const action = { max_distance: Number(msg.max_distance || 32), max_wait_s: Number(msg.max_wait_s || 30) }
  const bed = nearbyBlock(block => block && BED_NAMES.has(block.name), action.max_distance)
  if (!bed) return runtime.rejected('go_to_bed', action, 'BED_NOT_FOUND')
  await navigateToBlock(bed, 3)
  if (typeof bot.sleep !== 'function') return runtime.rejected('go_to_bed', action, 'SLEEP_PROVIDER_UNAVAILABLE')
  try {
    await bot.sleep(bed)
  } catch (error) {
    return runtime.rejected('go_to_bed', action, 'SLEEP_REJECTED', { message: error.message })
  }
  const deadline = Date.now() + action.max_wait_s * 1000
  while (Date.now() < deadline && !bot.isSleeping) await runtime.sleep(100)
  return bot.isSleeping
    ? runtime.applied('go_to_bed', action, 'SLEEP_STARTED', { position: runtime.vec(bed.position) })
    : runtime.partial('go_to_bed', action, 'SLEEP_STATE_NOT_CONFIRMED', { position: runtime.vec(bed.position) })
}

async function tillAndSow (msg) {
  const bot = runtime.getBot()
  const action = { seed: String(msg.seed || ''), max_distance: Number(msg.max_distance || 16) }
  const seed = runtime.findInventoryItem(action.seed)
  const hoe = bot.inventory.items().find(item => /hoe$/.test(item.name))
  if (!seed) return runtime.rejected('till_and_sow', action, 'SEED_NOT_AVAILABLE')
  if (!hoe) return runtime.rejected('till_and_sow', action, 'HOE_NOT_AVAILABLE')
  const soil = nearbyBlock(block => block && ['dirt', 'grass_block', 'coarse_dirt', 'rooted_dirt', 'farmland'].includes(block.name), action.max_distance)
  if (!soil) return runtime.rejected('till_and_sow', action, 'SOIL_NOT_FOUND')
  await navigateToBlock(soil)
  const target = bot.blockAt(soil.position)
  await bot.equip(hoe, 'hand')
  if (target && target.name !== 'farmland') await activateBlock(target)
  const farmland = bot.blockAt(soil.position)
  if (!farmland || farmland.name !== 'farmland') return runtime.partial('till_and_sow', action, 'FARMLAND_NOT_CONFIRMED', { position: runtime.vec(soil.position) })
  await bot.equip(seed, 'hand')
  await activateBlock(farmland)
  await runtime.sleep(150)
  const crop = bot.blockAt(new Vec3(soil.position.x, soil.position.y + 1, soil.position.z))
  const planted = crop && crop.name && (crop.name.endsWith('_seeds') || crop.name.endsWith('_crop') || crop.name === 'beetroot')
  return planted
    ? runtime.applied('till_and_sow', action, 'SEED_PLANTED', { position: runtime.vec(soil.position), crop: crop.name })
    : runtime.partial('till_and_sow', action, 'PLANTING_NOT_CONFIRMED', { position: runtime.vec(soil.position), crop: crop ? crop.name : null })
}

function droppedEntities (maxDistance) {
  const bot = runtime.getBot()
  return Object.values(bot.entities || {})
    .filter(entity => entity && entity.position && entity.isValid !== false)
    .filter(entity => runtime.isDroppedItemEntity(entity))
    .map(entity => ({ entity, distance: entity.position.distanceTo(bot.entity.position) }))
    .filter(row => row.distance <= maxDistance)
    .sort((left, right) => left.distance - right.distance)
}

async function pickupItems (msg) {
  const action = { max_distance: Number(msg.max_distance || 16), max_items: Number(msg.max_items || 8) }
  const bot = runtime.getBot()
  const before = runtime.inventoryMap()
  const targets = droppedEntities(action.max_distance).slice(0, action.max_items)
  let collected = 0
  for (const row of targets) {
    const live = bot.entities[row.entity.id]
    if (!live || live.isValid === false) continue
    const ownCollection = runtime.waitForOwnCollection(live, 8000)
    try { await runtime.gotoEntity(live, 0, 8000) } catch (_) {}
    if (await ownCollection) collected++
    await runtime.sleep(100)
  }
  const after = runtime.inventoryMap()
  const delta = runtime.inventoryDelta(before, after)
  const gained = Object.values(delta).filter(value => value > 0).reduce((sum, value) => sum + value, 0)
  const details = { candidates: targets.length, collected, inventory_delta: delta, gained }
  if (gained > 0) return runtime.applied('pickup_items', action, 'ITEMS_PICKED_UP', details)
  if (collected > 0) return runtime.partial('pickup_items', action, 'ITEM_ENTITIES_REMOVED_UNCONFIRMED', details)
  return runtime.applied('pickup_items', action, 'NO_DROPPED_ITEMS', details)
}

async function autoLight (msg) {
  const bot = runtime.getBot()
  const action = { max_distance: Number(msg.max_distance || 8) }
  const torch = bot.inventory.items().find(item => item.name === 'torch' || item.name === 'soul_torch')
  if (!torch) return runtime.rejected('auto_light', action, 'TORCH_NOT_AVAILABLE')
  const nearbyTorch = nearbyBlock(block => block && (block.name === 'torch' || block.name === 'soul_torch'), action.max_distance)
  if (nearbyTorch) return runtime.applied('auto_light', action, 'LIGHT_ALREADY_PRESENT', { position: runtime.vec(nearbyTorch.position) })
  const origin = bot.entity.position.floored()
  const target = origin.offset(0, 0, 1)
  let navigation
  try {
    navigation = await runtime.gotoBlockPlacement(target)
  } catch (error) {
    return runtime.rejected('auto_light', action, 'PATHFINDER_PLACE_BLOCK_FAILED', { error: error.message })
  }
  await bot.equip(torch, 'hand')
  try {
    await bot.placeBlock(navigation.reference, navigation.face)
  } catch (error) {
    return runtime.rejected('auto_light', action, 'PLACE_TORCH_FAILED', { error: error.message })
  }
  const placed = bot.blockAt(target)
  return placed && (placed.name === 'torch' || placed.name === 'soul_torch')
    ? runtime.applied('auto_light', action, 'TORCH_PLACED', { position: runtime.vec(target), block: placed.name })
    : runtime.partial('auto_light', action, 'TORCH_NOT_CONFIRMED', { position: runtime.vec(target) })
}

async function followPlayer (msg) {
  const bot = runtime.getBot()
  const action = { player: String(msg.player || ''), duration_s: Number(msg.duration_s || 10), distance: Number(msg.distance || 4), max_distance: Number(msg.max_distance || 64) }
  const target = runtime.findEntity(action.player, action.max_distance, entity => entity.type === 'player' && entity.username === action.player)
  if (!target) return runtime.rejected('follow_player', action, 'PLAYER_NOT_FOUND')
  const start = bot.entity.position.clone()
  const deadline = Date.now() + action.duration_s * 1000
  let updates = 0
  while (Date.now() < deadline) {
    const live = bot.entities[target.id]
    if (!live || !live.position) break
    const distance = live.position.distanceTo(bot.entity.position)
    if (distance > action.distance + 0.75) {
      try { await runtime.gotoPos(live.position, action.distance) } catch (_) {}
      updates++
    }
    await runtime.sleep(250)
  }
  const end = bot.entity.position.clone()
  const moved = end.distanceTo(start)
  return runtime.applied('follow_player', action, 'FOLLOW_INTERVAL_COMPLETED', { updates, moved, final_distance: bot.entities[target.id] && bot.entities[target.id].position ? bot.entities[target.id].position.distanceTo(end) : null })
}

async function stay (msg) {
  const bot = runtime.getBot()
  const action = { duration_s: Number(msg.duration_s || 10) }
  if (bot.pathfinder && typeof bot.pathfinder.stop === 'function') bot.pathfinder.stop()
  const start = bot.entity.position.clone()
  await runtime.sleep(action.duration_s * 1000)
  const moved = bot.entity.position.distanceTo(start)
  return moved <= 2.5
    ? runtime.applied('stay', action, 'STAY_COMPLETED', { moved })
    : runtime.partial('stay', action, 'STAY_DRIFTED', { moved })
}

async function mount (msg) {
  const bot = runtime.getBot()
  const action = { entity: msg.entity ? String(msg.entity) : null, max_distance: Number(msg.max_distance || 16) }
  const target = runtime.findEntity(action.entity || '', action.max_distance, entity => RIDEABLE_NAMES.has(String(entity.name || entity.displayName || '').toLowerCase()))
  if (!target) return runtime.rejected('mount', action, 'RIDEABLE_NOT_FOUND')
  await runtime.gotoPos(target.position, 2)
  if (typeof bot.mount !== 'function') return runtime.rejected('mount', action, 'MOUNT_PROVIDER_UNAVAILABLE')
  await bot.mount(target)
  await runtime.sleep(150)
  const mounted = bot.vehicle === target || (Array.isArray(target.passengers) && target.passengers.includes(bot.entity))
  return mounted ? runtime.applied('mount', action, 'MOUNTED', { entity_id: target.id }) : runtime.partial('mount', action, 'MOUNT_NOT_CONFIRMED', { entity_id: target.id })
}

async function dismount () {
  const bot = runtime.getBot()
  const action = {}
  if (!bot.vehicle) return runtime.applied('dismount', action, 'NOT_MOUNTED')
  if (typeof bot.dismount !== 'function') return runtime.rejected('dismount', action, 'DISMOUNT_PROVIDER_UNAVAILABLE')
  await bot.dismount()
  return bot.vehicle ? runtime.partial('dismount', action, 'DISMOUNT_NOT_CONFIRMED') : runtime.applied('dismount', action, 'DISMOUNTED')
}

async function activateNearestBlock (msg) {
  const action = { block: String(msg.block || ''), max_distance: Number(msg.max_distance || 16) }
  const block = nearbyBlock(candidate => candidate && runtime.matchName(candidate.name, action.block), action.max_distance)
  if (!block) return runtime.rejected('activate_nearest_block', action, 'BLOCK_NOT_FOUND')
  await navigateToBlock(block)
  await activateBlock(block)
  return runtime.applied('activate_nearest_block', action, 'BLOCK_ACTIVATED', { position: runtime.vec(block.position), block: block.name })
}

function villagerFromWorld (maxDistance) {
  return runtime.findEntity('villager', maxDistance, entity => String(entity.name || entity.displayName || '').toLowerCase() === 'villager' && !entity.isBaby)
}

async function openVillager (maxDistance) {
  const bot = runtime.getBot()
  const villager = villagerFromWorld(maxDistance)
  if (!villager) return { error: runtime.rejected('show_villager_trades', { max_distance: maxDistance }, 'VILLAGER_NOT_FOUND') }
  await runtime.gotoPos(villager.position, 3)
  if (typeof bot.openVillager !== 'function') return { error: runtime.rejected('show_villager_trades', { max_distance: maxDistance }, 'VILLAGER_PROVIDER_UNAVAILABLE') }
  try { return { villager, window: await bot.openVillager(villager) } } catch (error) { return { error: runtime.rejected('show_villager_trades', { max_distance: maxDistance }, 'VILLAGER_OPEN_REJECTED', { message: error.message }) } }
}

function tradeSummary (trade, index) {
  return {
    index,
    disabled: Boolean(trade.disabled),
    uses: Number(trade.tradeUses || trade.uses || 0),
    max_uses: Number(trade.maxTradeUses || trade.maxUses || 0),
    input_a: runtime.itemSummary(trade.inputItem1 || trade.inputItem),
    input_b: runtime.itemSummary(trade.inputItem2),
    output: runtime.itemSummary(trade.outputItem || trade.result)
  }
}

async function showVillagerTrades (msg) {
  const action = { max_distance: Number(msg.max_distance || 16) }
  const opened = await openVillager(action.max_distance)
  if (opened.error) return opened.error
  try {
    const trades = (opened.window.trades || []).map(tradeSummary)
    return runtime.applied('show_villager_trades', action, 'TRADES_INSPECTED', { trades })
  } finally { if (opened.window && typeof opened.window.close === 'function') opened.window.close() }
}

async function tradeVillager (msg) {
  const action = { trade_index: Number(msg.trade_index), max_trades: Number(msg.max_trades || 1), max_distance: Number(msg.max_distance || 16) }
  const opened = await openVillager(action.max_distance)
  if (opened.error) { const error = opened.error; error.action.tool = 'trade_villager'; return error }
  try {
    const trade = opened.window.trades && opened.window.trades[action.trade_index]
    if (!trade) return runtime.rejected('trade_villager', action, 'TRADE_NOT_FOUND')
    const available = Math.max(0, Number(trade.maxTradeUses || 0) - Number(trade.tradeUses || 0))
    if (trade.disabled || available <= 0) return runtime.rejected('trade_villager', action, 'TRADE_UNAVAILABLE', { available })
    const executions = Math.min(action.max_trades, available)
    const before = runtime.inventoryMap()
    for (let index = 0; index < executions; index++) await opened.window.trade(trade, 1)
    await runtime.sleep(200)
    const after = runtime.inventoryMap()
    const delta = runtime.inventoryDelta(before, after)
    return runtime.applied('trade_villager', action, 'TRADE_EXECUTED', { executions, available, inventory_delta: delta })
  } finally { if (opened.window && typeof opened.window.close === 'function') opened.window.close() }
}

async function fish (msg) {
  const bot = runtime.getBot()
  const action = { casts: Number(msg.casts || 1), max_wait_s: Number(msg.max_wait_s || 60) }
  const rod = runtime.findInventoryItem('fishing_rod')
  if (!rod) return runtime.rejected('fish', action, 'FISHING_ROD_NOT_AVAILABLE')
  if (typeof bot.fish !== 'function') return runtime.rejected('fish', action, 'FISHING_PROVIDER_UNAVAILABLE')
  await bot.equip(rod, 'hand')
  const before = runtime.inventoryMap()
  let catches = 0
  for (let index = 0; index < action.casts; index++) {
    try { await Promise.race([bot.fish(), runtime.sleep(action.max_wait_s * 1000)]); catches++ } catch (_) { break }
  }
  const after = runtime.inventoryMap()
  const delta = runtime.inventoryDelta(before, after)
  const gained = Object.values(delta).filter(value => value > 0).reduce((sum, value) => sum + value, 0)
  const details = { casts: action.casts, catches, inventory_delta: delta, gained }
  if (gained > 0) return runtime.applied('fish', action, 'FISH_CAUGHT', details)
  if (catches > 0) return runtime.partial('fish', action, 'CATCH_NOT_OBSERVED', details)
  return runtime.rejected('fish', action, 'FISHING_NOT_COMPLETED', details)
}

async function useToolOn (msg) {
  const bot = runtime.getBot()
  const action = { target: String(msg.target || ''), target_type: String(msg.target_type || 'block'), max_distance: Number(msg.max_distance || 16) }
  if (action.target_type === 'entity') {
    const entity = runtime.findEntity(action.target, action.max_distance)
    if (!entity) return runtime.rejected('use_tool_on', action, 'ENTITY_NOT_FOUND')
    await runtime.gotoPos(entity.position, 3)
    if (typeof bot.useOn !== 'function') return runtime.rejected('use_tool_on', action, 'USE_ON_PROVIDER_UNAVAILABLE')
    await bot.useOn(entity)
    return runtime.applied('use_tool_on', action, 'TOOL_USED_ON_ENTITY', { entity_id: entity.id })
  }
  const block = nearbyBlock(candidate => candidate && runtime.matchName(candidate.name, action.target), action.max_distance)
  if (!block) return runtime.rejected('use_tool_on', action, 'BLOCK_NOT_FOUND')
  await navigateToBlock(block)
  if (typeof bot.activateBlock !== 'function') return runtime.rejected('use_tool_on', action, 'USE_ON_PROVIDER_UNAVAILABLE')
  await bot.activateBlock(block)
  return runtime.applied('use_tool_on', action, 'TOOL_USED_ON_BLOCK', { position: runtime.vec(block.position), block: block.name })
}

module.exports = {
  activate_nearest_block: activateNearestBlock,
  auto_light: autoLight,
  dismount,
  fish,
  follow_player: followPlayer,
  go_to_bed: goToBed,
  mount,
  pickup_items: pickupItems,
  show_villager_trades: showVillagerTrades,
  stay,
  till_and_sow: tillAndSow,
  trade_villager: tradeVillager,
  use_door: useDoor,
  use_tool_on: useToolOn
}
