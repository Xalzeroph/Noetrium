'use strict'

const { Vec3 } = require('vec3')
const runtime = require('./runtime')

function blockProperties (block) {
  if (!block || typeof block.getProperties !== 'function') return {}
  const value = block.getProperties()
  return value && typeof value === 'object' ? value : {}
}

function isDoorBlock (block) {
  const properties = blockProperties(block)
  return (
    Object.prototype.hasOwnProperty.call(properties, 'open') &&
    Object.prototype.hasOwnProperty.call(properties, 'hinge') &&
    Object.prototype.hasOwnProperty.call(properties, 'half')
  )
}

function isBedBlock (block) {
  const properties = blockProperties(block)
  return (
    Object.prototype.hasOwnProperty.call(properties, 'occupied') &&
    Object.prototype.hasOwnProperty.call(properties, 'part')
  )
}


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
  const door = nearbyBlock(block => isDoorBlock(block), action.max_distance)
  if (!door) return runtime.rejected('use_door', action, 'DOOR_NOT_FOUND')
  await navigateToBlock(door)
  const before = blockProperty(door, 'open')
  const updated = runtime.waitForEventCondition(
    runtime.getBot(),
    'blockUpdate:' + String(door.position),
    (...args) => args.length > 0
      ? (args[1] || runtime.getBot().blockAt(door.position))
      : false
  )
  await activateBlock(door)
  await updated
  const afterBlock = runtime.getBot().blockAt(door.position)
  const after = blockProperty(afterBlock, 'open')
  const details = { position: runtime.vec(door.position), before, after }
  if (after === true || (before !== true && after === undefined)) return runtime.applied('use_door', action, 'DOOR_ACTIVATED', details)
  return runtime.partial('use_door', action, 'DOOR_STATE_NOT_CONFIRMED', details)
}

async function goToBed (msg) {
  const bot = runtime.getBot()
  const action = { max_distance: Number(msg.max_distance || 32), max_wait_s: Number(msg.max_wait_s || 30) }
  const bed = nearbyBlock(block => isBedBlock(block), action.max_distance)
  if (!bed) return runtime.rejected('go_to_bed', action, 'BED_NOT_FOUND')
  await navigateToBlock(bed, 3)
  if (typeof bot.sleep !== 'function') return runtime.rejected('go_to_bed', action, 'SLEEP_PROVIDER_UNAVAILABLE')
  const unregisterWake = runtime.onActionCancel('mineflayer:sleep', async () => {
    if (bot.isSleeping && typeof bot.wake === 'function') await bot.wake()
  })
  try {
    try {
      await bot.sleep(
        bed,
        Math.min(
          runtime.actionRemainingMs(),
          action.max_wait_s * 1000
        )
      )
    } catch (error) {
      return runtime.rejected('go_to_bed', action, 'SLEEP_REJECTED', {
        message: error.message
      })
    }
    return bot.isSleeping
      ? runtime.applied('go_to_bed', action, 'SLEEP_STARTED', { position: runtime.vec(bed.position) })
      : runtime.partial('go_to_bed', action, 'SLEEP_STATE_NOT_CONFIRMED', { position: runtime.vec(bed.position) })
  } finally {
    unregisterWake()
  }
}

async function tillAndSow (msg) {
  const bot = runtime.getBot()
  const action = { seed: String(msg.seed || ''), max_distance: Number(msg.max_distance || 16) }
  const seed = runtime.findInventoryItem(action.seed)
  const hoe = bot.inventory.items().find(item => /hoe$/.test(item.name))
  if (!seed) {
    const details = {
      semantic_domain: 'minecraft.item_name',
      prerequisites: { requested_seed: action.seed, seed_available: false }
    }
    return runtime.rejected('till_and_sow', action, 'SEED_NOT_AVAILABLE', details)
  }
  if (!hoe) {
    const details = {
      semantic_domain: 'minecraft.item_name',
      prerequisites: { required_tool_family: 'hoe', tool_available: false }
    }
    return runtime.rejected('till_and_sow', action, 'HOE_NOT_AVAILABLE', details)
  }
  const soil = nearbyBlock(block => block && ['dirt', 'grass_block', 'coarse_dirt', 'rooted_dirt', 'farmland'].includes(block.name), action.max_distance)
  if (!soil) return runtime.rejected('till_and_sow', action, 'SOIL_NOT_FOUND')
  await navigateToBlock(soil)
  const target = bot.blockAt(soil.position)
  await bot.equip(hoe, 'hand')
  if (target && target.name !== 'farmland') {
    const farmlandUpdate = runtime.waitForEventCondition(
      bot,
      'blockUpdate:' + String(soil.position),
      (...args) => {
        if (args.length === 0) return false
        const candidate = args[1] || bot.blockAt(soil.position)
        return candidate && candidate.name === 'farmland' ? candidate : false
      }
    )
    await activateBlock(target)
    await farmlandUpdate
  }
  const farmland = bot.blockAt(soil.position)
  if (!farmland || farmland.name !== 'farmland') return runtime.partial('till_and_sow', action, 'FARMLAND_NOT_CONFIRMED', { position: runtime.vec(soil.position) })
  await bot.equip(seed, 'hand')
  const cropPosition = new Vec3(
    soil.position.x,
    soil.position.y + 1,
    soil.position.z
  )
  const cropUpdate = runtime.waitForEventCondition(
    bot,
    'blockUpdate:' + String(cropPosition),
    (...args) => {
      if (args.length === 0) return false
      const candidate = args[1] || bot.blockAt(cropPosition)
      return candidate && candidate.name && candidate.name !== 'air'
        ? candidate
        : false
    }
  )
  await activateBlock(farmland)
  await cropUpdate
  const crop = bot.blockAt(cropPosition)
  const planted = crop && crop.name && (crop.name.endsWith('_seeds') || crop.name.endsWith('_crop') || crop.name === 'beetroot')
  const plantingEvidence = {
    position: runtime.vec(soil.position),
    crop: crop ? crop.name : null,
    hoe_used: hoe.name
  }
  return planted
    ? runtime.applied('till_and_sow', action, 'SEED_PLANTED', plantingEvidence)
    : runtime.partial('till_and_sow', action, 'PLANTING_NOT_CONFIRMED', plantingEvidence)
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
  const action = {
    max_distance: Number(msg.max_distance || 16),
    max_items: Number(msg.max_items || 8),
    ...(msg.item == null ? {} : { item: String(msg.item) })
  }
  const bot = runtime.getBot()
  const before = runtime.inventoryMap()
  const origin = bot.entity.position.clone()
  const observed = droppedEntities(action.max_distance)
  // A concrete item request is a physical target constraint, not a license
  // to infer item identity from registry entries or unstable entity names.
  // Unknown item metadata must never be accepted as a matching witness.
  const matches = action.item == null
    ? observed
    : observed.filter(row => runtime.droppedItemName(row.entity) === action.item)
  const targets = matches.slice(0, action.max_items)

  // Arm one collection observer for the complete bounded target set BEFORE
  // movement starts.  Walking toward one drop can legitimately collect nearby
  // later targets; registering listeners one target at a time loses those
  // already-observed effects and then performs redundant navigation.  This is
  // still observation only: playerCollect from this exact bot is the sole
  // entity-level proof and inventory delta remains the physical item proof.
  const targetIds = new Set(targets.map(row => row.entity.id))
  const collectedIds = new Set()
  const collectionWaiters = new Map()
  let collectionObserverClosed = false
  const resolveCollection = (id, value) => {
    const resolve = collectionWaiters.get(id)
    if (resolve) {
      collectionWaiters.delete(id)
      resolve(value)
    }
  }
  const onCollect = (collector, entity) => {
    if (
      collector && entity &&
      collector.id === bot.entity.id &&
      targetIds.has(entity.id)
    ) {
      collectedIds.add(entity.id)
      resolveCollection(entity.id, true)
    }
  }
  bot.on('playerCollect', onCollect)
  const unregisterCancel = runtime.onActionCancel(
    'mineflayer:pickup-items-collection-observer',
    () => {
      collectionObserverClosed = true
      bot.removeListener('playerCollect', onCollect)
      for (const [id, resolve] of collectionWaiters) {
        collectionWaiters.delete(id)
        resolve(false)
      }
    }
  )
  const waitForCollection = id => {
    if (collectedIds.has(id)) return Promise.resolve(true)
    if (collectionObserverClosed) return Promise.resolve(false)
    return new Promise(resolve => collectionWaiters.set(id, resolve))
  }
  const closeCollectionObserver = () => {
    if (collectionObserverClosed) return
    collectionObserverClosed = true
    bot.removeListener('playerCollect', onCollect)
    unregisterCancel()
    for (const [id, resolve] of collectionWaiters) {
      collectionWaiters.delete(id)
      resolve(false)
    }
  }

  let collected = 0
  try {
    for (const row of targets) {
      const id = row.entity.id
      if (collectedIds.has(id)) {
        collected++
        continue
      }
      const live = bot.entities[id]
      if (!live || live.isValid === false) continue
      if (action.item != null && runtime.droppedItemName(live) !== action.item) continue
      try { await runtime.gotoEntity(live, 0) } catch (_) {}
      if (collectedIds.has(id)) {
        collected++
        continue
      }
      const stillLive = bot.entities[id]
      if (!stillLive || stillLive.isValid === false) continue
      if (await waitForCollection(id)) collected++
    }
  } finally {
    closeCollectionObserver()
  }
  const after = runtime.inventoryMap()
  const delta = runtime.inventoryDelta(before, after)
  const gained = Object.values(delta).filter(value => value > 0).reduce((sum, value) => sum + value, 0)
  const matchingGain = action.item == null ? gained : Math.max(0, delta[action.item] || 0)
  const moved = bot.entity.position.distanceTo(origin)
  const details = {
    observed_drop_entities: observed.length,
    candidates: targets.length,
    skipped_nonmatching_or_unidentified: observed.length - matches.length,
    collected, inventory_delta: delta, gained, matching_gain: matchingGain,
    moved
  }
  if (action.item == null) {
    // Preserve the original unfiltered action's externally observed contract.
    if (gained > 0) return runtime.applied('pickup_items', action, 'ITEMS_PICKED_UP', details)
    if (collected > 0) return runtime.partial('pickup_items', action, 'ITEM_ENTITIES_REMOVED_UNCONFIRMED', details)
    return runtime.applied('pickup_items', action, 'NO_DROPPED_ITEMS', details)
  }
  if (matchingGain > 0) return runtime.applied('pickup_items', action, 'ITEMS_PICKED_UP', details)
  if (collected > 0 || moved > 0 || gained > 0) {
    return runtime.partial('pickup_items', action, 'PICKUP_EFFECT_INCOMPLETE', details, 'applied')
  }
  return runtime.rejected('pickup_items', action,
    targets.length > 0 ? 'MATCHING_ITEM_PICKUP_UNCONFIRMED' : 'MATCHING_ITEM_DROP_NOT_OBSERVED',
    { ...details, loaded_world_only: true })
}

async function autoLight (msg) {
  const bot = runtime.getBot()
  const action = { max_distance: Number(msg.max_distance || 8) }
  const torch = bot.inventory.items().find(item => item.name === 'torch' || item.name === 'soul_torch')
  if (!torch) {
    const details = {
      semantic_domain: 'minecraft.item_name',
      prerequisites: { required_item_family: 'torch', torch_available: false }
    }
    return runtime.rejected('auto_light', action, 'TORCH_NOT_AVAILABLE', details)
  }
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
  let navigation
  try {
    navigation = await runtime.followEntityFor(
      target,
      action.distance,
      action.duration_s * 1000
    )
  } catch (error) {
    const moved = bot.entity.position.distanceTo(start)
    return moved > 0
      ? runtime.partial('follow_player', action, 'FOLLOW_INTERRUPTED', {
          moved,
          navigation_error: runtime.errorEvidence(error)
        }, 'applied')
      : runtime.rejected('follow_player', action, 'FOLLOW_NOT_STARTED', {
          moved,
          navigation_error: runtime.errorEvidence(error)
        }, 'not_applied')
  }
  const moved = bot.entity.position.distanceTo(start)
  return runtime.applied('follow_player', action, 'FOLLOW_INTERVAL_COMPLETED', {
    updates: navigation.pathfinder_evidence.path_update_count,
    moved,
    final_distance: navigation.final_distance,
    target_gone: navigation.target_gone,
    navigation_mode: navigation.navigation_mode,
    pathfinder_evidence: navigation.pathfinder_evidence
  })
}

async function stay (msg) {
  const bot = runtime.getBot()
  const action = { duration_s: Number(msg.duration_s || 10) }
  runtime.stopMotion()
  const start = bot.entity.position.clone()
  await runtime.sleep(action.duration_s * 1000)
  runtime.stopMotion()
  const moved = bot.entity.position.distanceTo(start)
  return moved <= 2.5
    ? runtime.applied('stay', action, 'STAY_COMPLETED', { moved })
    // The interval completed and the terminal displacement is observed, so
    // external-effect execution is certain even when the stay objective was
    // only partially satisfied. Keep outcome success separate from effect
    // certainty: replaying this action as UNKNOWN could duplicate an already
    // executed external effect.
    : runtime.partial('stay', action, 'STAY_DRIFTED', { moved }, 'applied')
}

async function mount (msg) {
  const bot = runtime.getBot()
  const action = {
    entity: String(msg.entity || ''),
    max_distance: Number(msg.max_distance || 16)
  }
  const target = runtime.findEntity(action.entity, action.max_distance)
  if (!target) {
    return runtime.rejected('mount', action, 'ENTITY_NOT_FOUND', {
      semantic_domain: 'minecraft.entity_type',
      target_observed: false
    })
  }
  await runtime.gotoEntity(target, 2)
  if (typeof bot.mount !== 'function') return runtime.rejected('mount', action, 'MOUNT_PROVIDER_UNAVAILABLE')
  const mountEvent = runtime.waitForEventCondition(
    bot,
    'mount',
    () => (
      bot.vehicle === target ||
      (Array.isArray(target.passengers) && target.passengers.includes(bot.entity))
    )
  )
  bot.mount(target)
  const mounted = Boolean(await mountEvent)
  return mounted ? runtime.applied('mount', action, 'MOUNTED', { entity_id: target.id }) : runtime.partial('mount', action, 'MOUNT_NOT_CONFIRMED', { entity_id: target.id })
}

async function dismount () {
  const bot = runtime.getBot()
  const action = {}
  if (!bot.vehicle) return runtime.applied('dismount', action, 'NOT_MOUNTED')
  if (typeof bot.dismount !== 'function') return runtime.rejected('dismount', action, 'DISMOUNT_PROVIDER_UNAVAILABLE')
  const dismountEvent = runtime.waitForEventCondition(
    bot,
    'dismount',
    () => bot.vehicle == null
  )
  bot.dismount()
  const dismounted = Boolean(await dismountEvent)
  return dismounted
    ? runtime.applied('dismount', action, 'DISMOUNTED')
    : runtime.partial('dismount', action, 'DISMOUNT_NOT_CONFIRMED')
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
  await runtime.gotoEntity(villager, 3)
  if (typeof bot.openVillager !== 'function') return { error: runtime.rejected('show_villager_trades', { max_distance: maxDistance }, 'VILLAGER_PROVIDER_UNAVAILABLE') }
  try { return { villager, window: await bot.openVillager(villager) } } catch (error) { return { error: runtime.rejected('show_villager_trades', { max_distance: maxDistance }, 'VILLAGER_OPEN_REJECTED', { message: error.message }) } }
}

function tradeUseCounts (trade) {
  const uses = Number(
    trade && (trade.nbTradeUses ?? trade.tradeUses ?? trade.uses ?? 0)
  )
  const maxUses = Number(
    trade && (
      trade.maximumNbTradeUses ?? trade.maxTradeUses ?? trade.maxUses ?? 0
    )
  )
  return {
    uses: Number.isFinite(uses) ? Math.max(0, uses) : 0,
    max_uses: Number.isFinite(maxUses) ? Math.max(0, maxUses) : 0
  }
}

function tradeSummary (trade, index) {
  const counts = tradeUseCounts(trade)
  return {
    index,
    disabled: Boolean(trade.tradeDisabled ?? trade.disabled),
    uses: counts.uses,
    max_uses: counts.max_uses,
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
    const counts = tradeUseCounts(trade)
    const available = Math.max(0, counts.max_uses - counts.uses)
    if (Boolean(trade.tradeDisabled ?? trade.disabled) || available <= 0) return runtime.rejected('trade_villager', action, 'TRADE_UNAVAILABLE', { available })
    const executions = Math.min(action.max_trades, available)
    const before = runtime.inventoryMap()
    await opened.window.trade(action.trade_index, executions)
    const after = runtime.inventoryMap()
    const delta = runtime.inventoryDelta(before, after)
    return runtime.applied('trade_villager', action, 'TRADE_EXECUTED', { executions, available, inventory_delta: delta })
  } finally { if (opened.window && typeof opened.window.close === 'function') opened.window.close() }
}

async function fish (msg) {
  const bot = runtime.getBot()
  const action = { casts: Number(msg.casts || 1), max_wait_s: Number(msg.max_wait_s || 60) }
  const rod = runtime.findInventoryItem('fishing_rod')
  if (!rod) {
    const details = {
      semantic_domain: 'minecraft.item_name',
      prerequisites: { required_item: 'fishing_rod', item_available: false }
    }
    return runtime.rejected('fish', action, 'FISHING_ROD_NOT_AVAILABLE', details)
  }
  if (typeof bot.fish !== 'function') return runtime.rejected('fish', action, 'FISHING_PROVIDER_UNAVAILABLE')
  await bot.equip(rod, 'hand')
  const before = runtime.inventoryMap()
  let catches = 0
  let fishingActive = false
  const unregisterFishingCancel = runtime.onActionCancel('mineflayer:fishing', () => {
    if (fishingActive && typeof bot.activateItem === 'function') bot.activateItem()
  })
  try {
    for (let index = 0; index < action.casts; index++) {
      fishingActive = true
      try {
        await runtime.withTimeout(
          bot.fish(),
          action.max_wait_s * 1000,
          'FISH_CAST'
        )
        catches++
      } catch (error) {
        if (error && error.code === 'FISH_CAST_TIMEOUT') break
        throw error
      } finally {
        fishingActive = false
      }
    }
  } finally {
    unregisterFishingCancel()
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
  const heldItem = bot.heldItem && bot.heldItem.name ? String(bot.heldItem.name) : null
  if (action.target_type === 'entity') {
    const entity = runtime.findEntity(action.target, action.max_distance)
    if (!entity) return runtime.rejected('use_tool_on', action, 'ENTITY_NOT_FOUND')
    await runtime.gotoEntity(entity, 3)
    if (typeof bot.useOn !== 'function') return runtime.rejected('use_tool_on', action, 'USE_ON_PROVIDER_UNAVAILABLE')
    await bot.useOn(entity)
    return runtime.applied('use_tool_on', action, 'TOOL_USED_ON_ENTITY', {
      entity_id: entity.id,
      held_item: heldItem
    })
  }
  const block = nearbyBlock(candidate => candidate && runtime.matchName(candidate.name, action.target), action.max_distance)
  if (!block) return runtime.rejected('use_tool_on', action, 'BLOCK_NOT_FOUND')
  await navigateToBlock(block)
  if (typeof bot.activateBlock !== 'function') return runtime.rejected('use_tool_on', action, 'USE_ON_PROVIDER_UNAVAILABLE')
  await bot.activateBlock(block)
  return runtime.applied('use_tool_on', action, 'TOOL_USED_ON_BLOCK', {
    position: runtime.vec(block.position),
    block: block.name,
    held_item: heldItem
  })
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
