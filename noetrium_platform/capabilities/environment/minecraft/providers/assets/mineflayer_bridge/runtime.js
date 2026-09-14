'use strict'

const { Movements, goals: { GoalNear, GoalFollow, GoalLookAtBlock } } = require('mineflayer-pathfinder')
const { Vec3 } = require('vec3')

let bot = null
let movements = null

function bindBot (value) {
  bot = value
  movements = null
}

function requireBot () {
  if (!bot || !bot.entity) throw new Error('bot not connected/spawned')
  return bot
}

function getBot () { return requireBot() }
function vec (value) { return value ? { x: Number(value.x), y: Number(value.y), z: Number(value.z) } : null }
function sleep (ms) { return new Promise(resolve => setTimeout(resolve, ms)) }

function stopMotion () {
  if (!bot) return
  try { if (bot.pathfinder && typeof bot.pathfinder.stop === 'function') bot.pathfinder.stop() } catch (_) {}
  try { if (bot.pvp && typeof bot.pvp.stop === 'function') bot.pvp.stop() } catch (_) {}
  try { if (typeof bot.stopDigging === 'function') bot.stopDigging() } catch (_) {}
  try { if (typeof bot.clearControlStates === 'function') bot.clearControlStates() } catch (_) {}
}

function actionTimeoutMs (msg, fallbackMs = 45000) {
  const raw = Number(msg && msg._action_timeout_ms)
  const budget = Number.isFinite(raw) && raw > 0 ? raw : fallbackMs
  return Math.max(500, Math.floor(budget * 0.95))
}

function remainingMs (deadlineMs, capMs) {
  const remaining = deadlineMs - Date.now()
  if (remaining <= 0) throw new Error('ACTION_DEADLINE_EXCEEDED')
  return Math.max(250, Math.min(remaining, capMs))
}

function withTimeout (promise, timeoutMs, label, onTimeout = stopMotion) {
  return new Promise((resolve, reject) => {
    let settled = false
    const timer = setTimeout(() => {
      if (settled) return
      settled = true
      try { if (onTimeout) onTimeout() } catch (_) {}
      const error = new Error(`${label}_TIMEOUT`)
      error.code = `${label}_TIMEOUT`
      reject(error)
    }, Math.max(1, timeoutMs))
    Promise.resolve(promise).then(value => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      resolve(value)
    }, error => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      reject(error)
    })
  })
}

function itemSummary (item) { return item ? { name: item.name, count: item.count, slot: item.slot } : null }

function matchName (name, query) {
  if (!query) return false
  const q = String(query).toLowerCase()
  const n = String(name || '').toLowerCase()
  if (q.startsWith('re:')) return new RegExp(q.slice(3)).test(n)
  return n === q || n.includes(q)
}

function entityMatches (entity, query) {
  return [entity.name, entity.username, entity.displayName, entity.type]
    .some(value => matchName(value, query))
}

function findEntity (query, maxDistance = 32, predicate = null) {
  const activeBot = requireBot()
  const candidates = Object.values(activeBot.entities || {})
    .filter(entity => entity && entity !== activeBot.entity && entity.position && entity.isValid !== false)
    .filter(entity => (!query || entityMatches(entity, query)) && (!predicate || predicate(entity)))
    .map(entity => ({ entity, distance: entity.position.distanceTo(activeBot.entity.position) }))
    .filter(candidate => candidate.distance <= maxDistance)
    .sort((left, right) => left.distance - right.distance)
  return candidates.length > 0 ? candidates[0].entity : null
}

function waitForPhysicsTicks (count = 10, timeoutMs = 2000) {
  const activeBot = requireBot()
  const target = Math.max(1, Number(count))
  return new Promise(resolve => {
    let ticks = 0
    let settled = false
    const finish = () => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      activeBot.removeListener('physicsTick', onTick)
      resolve()
    }
    const onTick = () => { if (++ticks >= target) finish() }
    const timer = setTimeout(finish, Math.max(1, timeoutMs))
    activeBot.on('physicsTick', onTick)
  })
}

async function waitForInventoryIncrease (name, before, timeoutMs = 2500) {
  const deadline = Date.now() + Math.max(1, timeoutMs)
  while (Date.now() < deadline) {
    const current = inventoryCount(name)
    if (current > before) return current - before
    await sleep(Math.min(100, Math.max(1, deadline - Date.now())))
  }
  return Math.max(0, inventoryCount(name) - before)
}

function inventoryCount (name) {
  const activeBot = requireBot()
  return activeBot.inventory.items()
    .filter(item => item.name === name)
    .reduce((total, item) => total + item.count, 0)
}

function inventoryMap () {
  const activeBot = requireBot()
  const out = {}
  for (const item of activeBot.inventory.items()) out[item.name] = (out[item.name] || 0) + item.count
  return out
}

function inventoryDelta (before, after) {
  const out = {}
  for (const name of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const delta = Number(after[name] || 0) - Number(before[name] || 0)
    if (delta !== 0) out[name] = delta
  }
  return out
}

function isDroppedItemEntity (entity) {
  if (!entity || !entity.position || entity.isValid === false) return false
  if (typeof entity.getDroppedItem === 'function') {
    try { if (entity.getDroppedItem()) return true } catch (_) {}
  }
  const name = String(entity.name || '').toLowerCase()
  return name === 'item' || name === 'item_stack'
}

function droppedItemName (entity) {
  if (!isDroppedItemEntity(entity) || typeof entity.getDroppedItem !== 'function') return null
  try {
    const item = entity.getDroppedItem()
    return item && item.name ? String(item.name) : null
  } catch (_) {
    return null
  }
}

function captureItemDropNear (position, itemName = null, maxDistance = 0.5) {
  const expectedNames = Array.isArray(itemName)
    ? itemName.map(String).filter(Boolean)
    : itemName ? [String(itemName)] : []
  const matchesExpectedName = name => expectedNames.length === 0 || (name != null && expectedNames.includes(name))
  const activeBot = requireBot()
  const blockPos = position instanceof Vec3 ? position : new Vec3(Number(position.x), Number(position.y), Number(position.z))
  const center = blockPos.offset(0.5, 0.5, 0.5)
  // Mineflayer 4.37.1 emits entitySpawn from spawn_entity before itemDrop,
  // which is emitted later from entity_metadata carrying item_stack. Track both
  // lifecycle stages so fast pickup cannot erase the drop before metadata arrives.
  const candidates = []
  const spawnCandidates = []
  const collectionCandidates = []
  // One block action may correlate only a bounded number of nearby drop entities.
  // Keeping the fallback set fixed-size makes pickup selection constant-time and
  // fail-closed under anomalous/adversarial entity floods instead of scanning
  // world-sized state. Sixteen slots is intentionally generous for one block drop.
  const trackedSlots = [
    null, null, null, null, null, null, null, null,
    null, null, null, null, null, null, null, null
  ]
  const trackedSlotById = new Map()
  const freeTrackedSlots = [15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
  const collectedByBot = new Set()
  let trackedOverflow = false
  const trackEntity = entity => {
    if (!entity || entity.id == null) return false
    const existing = trackedSlotById.get(entity.id)
    if (existing != null) {
      trackedSlots[existing] = entity
      return true
    }
    const slot = freeTrackedSlots.pop()
    if (slot == null) {
      trackedOverflow = true
      return false
    }
    trackedSlots[slot] = entity
    trackedSlotById.set(entity.id, slot)
    return true
  }
  const untrackEntity = entity => {
    if (!entity || entity.id == null) return
    const slot = trackedSlotById.get(entity.id)
    if (slot == null) return
    trackedSlotById.delete(entity.id)
    trackedSlots[slot] = null
    freeTrackedSlots.push(slot)
  }
  const protocolPackets = []
  const tracedPacketNames = new Set([
    'spawn_entity', 'entity_metadata', 'collect', 'set_slot',
    'window_items', 'entity_destroy', 'block_change'
  ])
  let settled = false
  let resolvePromise
  const promise = new Promise(resolve => { resolvePromise = resolve })
  const finish = entity => {
    if (settled) return
    settled = true
    activeBot.removeListener('itemDrop', onDrop)
    resolvePromise(entity)
  }
  const association = entity => {
    const dropped = isDroppedItemEntity(entity)
    const distance = entity && entity.position ? entity.position.distanceTo(center) : null
    return { dropped, distance, within: dropped && distance != null && distance <= maxDistance }
  }
  const onProtocolPacket = (data, metadata) => {
    const name = metadata && metadata.name ? String(metadata.name) : ''
    if (!tracedPacketNames.has(name)) return
    const packet = { sequence: protocolPackets.length + 1, packet: name }
    if (data && data.entityId != null) packet.entity_id = data.entityId
    if (data && data.collectedEntityId != null) packet.collected_entity_id = data.collectedEntityId
    if (data && data.collectorEntityId != null) packet.collector_entity_id = data.collectorEntityId
    if (data && data.pickupItemCount != null) packet.pickup_item_count = data.pickupItemCount
    if (data && data.type != null && name === 'spawn_entity') packet.entity_type = data.type
    if (data && data.x != null) packet.x = data.x
    if (data && data.y != null) packet.y = data.y
    if (data && data.z != null) packet.z = data.z
    if (data && data.windowId != null) packet.window_id = data.windowId
    if (data && data.slot != null) packet.slot = data.slot
    if (data && Array.isArray(data.entityIds)) packet.entity_ids = data.entityIds.slice()
    if (data && Array.isArray(data.metadata)) packet.metadata_types = data.metadata.map(row => row.type)
    if (data && Array.isArray(data.items)) packet.item_slots = data.items.length
    if (data && data.item) packet.item_count = data.item.itemCount ?? data.item.count ?? null
    protocolPackets.push(packet)
  }
  const onSpawn = entity => {
    const row = association(entity)
    if (!row.dropped) return
    spawnCandidates.push({
      entity_id: entity.id ?? null,
      item_name: droppedItemName(entity),
      position: vec(entity.position),
      distance_to_block_center: row.distance,
      matched: row.within
    })
    if (row.within && entity.id != null) trackEntity(entity)
  }
  const onDrop = entity => {
    const dropped = isDroppedItemEntity(entity)
    const observedName = dropped ? droppedItemName(entity) : null
    const distance = entity && entity.position ? entity.position.distanceTo(center) : null
    const candidate = {
      entity_id: entity && entity.id != null ? entity.id : null,
      item_name: observedName,
      position: entity && entity.position ? vec(entity.position) : null,
      distance_to_block_center: distance,
      is_valid: Boolean(entity && entity.isValid !== false),
      matched: false,
      rejection: null
    }
    if (!dropped) candidate.rejection = 'NOT_DROPPED_ITEM_ENTITY'
    else if (distance == null || distance > maxDistance) candidate.rejection = 'OUTSIDE_ASSOCIATION_RADIUS'
    else if (!matchesExpectedName(observedName)) candidate.rejection = 'ITEM_NAME_MISMATCH'
    else candidate.matched = true
    candidates.push(candidate)
    if (dropped && distance != null && distance <= maxDistance && entity.id != null) {
      if (observedName == null || matchesExpectedName(observedName)) trackEntity(entity)
      else untrackEntity(entity)
    }
    if (candidate.matched) finish(entity)
  }
  const onCollect = (collector, collected) => {
    const own = Boolean(collector && activeBot.entity && collector.id === activeBot.entity.id)
    const tracked = Boolean(collected && collected.id != null && trackedSlotById.has(collected.id))
    if (!tracked) return
    collectionCandidates.push({
      entity_id: collected.id,
      item_name: droppedItemName(collected),
      position: collected.position ? vec(collected.position) : null,
      own_collector: own,
      tracked: true
    })
    if (own) {
      collectedByBot.add(collected.id)
      untrackEntity(collected)
    }
  }
  const onGone = entity => {
    untrackEntity(entity)
  }
  if (activeBot._client && typeof activeBot._client.on === 'function') {
    activeBot._client.on('packet', onProtocolPacket)
  }
  activeBot.on('entitySpawn', onSpawn)
  activeBot.on('itemDrop', onDrop)
  activeBot.on('playerCollect', onCollect)
  activeBot.on('entityGone', onGone)
  const cancel = () => {
    activeBot.removeListener('entitySpawn', onSpawn)
    activeBot.removeListener('playerCollect', onCollect)
    activeBot.removeListener('entityGone', onGone)
    if (activeBot._client && typeof activeBot._client.removeListener === 'function') {
      activeBot._client.removeListener('packet', onProtocolPacket)
    }
    finish(null)
  }
  const pickupTarget = () => {
    if (trackedOverflow) return null
    const boundedCandidates = [
      trackedSlots[0], trackedSlots[1], trackedSlots[2], trackedSlots[3],
      trackedSlots[4], trackedSlots[5], trackedSlots[6], trackedSlots[7],
      trackedSlots[8], trackedSlots[9], trackedSlots[10], trackedSlots[11],
      trackedSlots[12], trackedSlots[13], trackedSlots[14], trackedSlots[15]
    ]
    let nearest = null
    let nearestDistance = Infinity
    for (const entity of boundedCandidates) {
      if (!entity || entity.isValid === false || collectedByBot.has(entity.id)) continue
      const name = droppedItemName(entity)
      if (expectedNames.length > 0 && name != null && !expectedNames.includes(name)) continue
      const distance = entity.position.distanceTo(activeBot.entity.position)
      if (distance < nearestDistance) {
        nearest = entity
        nearestDistance = distance
      }
    }
    return nearest
  }
  return {
    promise,
    cancel,
    candidates,
    spawn_candidates: spawnCandidates,
    collection_candidates: collectionCandidates,
    protocol_packets: protocolPackets,
    pickupTarget,
    hasCandidateOverflow: () => trackedOverflow,
    hasOwnCollection: () => collectedByBot.size > 0
  }
}

function findNearbyDroppedItem (position, maxDistance = 6) {
  const activeBot = requireBot()
  const origin = position instanceof Vec3 ? position : new Vec3(Number(position.x), Number(position.y), Number(position.z))
  let nearest = null
  let nearestBotDistance = Infinity
  for (const entity of Object.values(activeBot.entities || {})) {
    if (entity === activeBot.entity || !isDroppedItemEntity(entity)) continue
    if (entity.position.distanceTo(origin) > maxDistance) continue
    const botDistance = entity.position.distanceTo(activeBot.entity.position)
    if (botDistance < nearestBotDistance) {
      nearest = entity
      nearestBotDistance = botDistance
    }
  }
  return nearest
}

function findInventoryItem (name) {
  return requireBot().inventory.items().find(item => item.name === name) || null
}

async function ensureMovements () {
  const activeBot = requireBot()
  if (!movements) movements = new Movements(activeBot)
  activeBot.pathfinder.setMovements(movements)
}

async function gotoEntity (entity, radius = 0, timeoutMs = 30000) {
  const activeBot = requireBot()
  if (!entity || entity.isValid === false || !entity.position) throw new Error('ENTITY_TARGET_INVALID')
  await ensureMovements()
  const boundedRadius = Math.max(0, Number(radius))
  await withTimeout(
    activeBot.pathfinder.goto(new GoalFollow(entity, boundedRadius)),
    timeoutMs,
    'PATHFINDER_FOLLOW'
  )
  const live = activeBot.entities && activeBot.entities[entity.id] ? activeBot.entities[entity.id] : entity
  return { entity_id: entity.id, position: vec(live.position), valid: live.isValid !== false }
}

function waitForOwnCollection (entity, timeoutMs = 5000) {
  const activeBot = requireBot()
  const targetId = entity && entity.id
  return new Promise(resolve => {
    let settled = false
    let timer = null
    const finish = value => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      activeBot.removeListener('playerCollect', onCollect)
      resolve(value)
    }
    const onCollect = (collector, collected) => {
      if (collector && collected && collector.id === activeBot.entity.id && collected.id === targetId) finish(true)
    }
    activeBot.on('playerCollect', onCollect)
    timer = setTimeout(() => finish(false), Math.max(1, timeoutMs))
  })
}

async function gotoPos (position, radius = 1.5, timeoutMs = 30000) {
  const activeBot = requireBot()
  await ensureMovements()
  const target = new Vec3(Number(position.x), Number(position.y), Number(position.z))
  const boundedRadius = Math.max(1, Number(radius))
  await withTimeout(
    activeBot.pathfinder.goto(
      new GoalNear(Math.floor(target.x), Math.floor(target.y), Math.floor(target.z), boundedRadius)
    ),
    timeoutMs,
    'PATHFINDER_GOTO'
  )
  const distance = activeBot.entity.position.distanceTo(target)
  return {
    target: vec(target),
    position: vec(activeBot.entity.position),
    distance,
    within_radius: distance <= Math.max(2.5, boundedRadius + 1)
  }
}

// Prefer pathfinder's interaction-aware goal for every block action. A GoalNear
// can leave the bot technically close enough while still unable to
// raycast/interact with the target.
async function gotoBlockInteraction (position, timeoutMs = 30000) {
  const activeBot = requireBot()
  if (!activeBot.pathfinder.movements) await ensureMovements()
  const target = new Vec3(Number(position.x), Number(position.y), Number(position.z))
  await withTimeout(
    activeBot.pathfinder.goto(new GoalLookAtBlock(target, activeBot.world)),
    timeoutMs,
    'PATHFINDER_LOOK_AT_BLOCK'
  )
  const distance = activeBot.entity.position.distanceTo(target)
  return {
    target: vec(target),
    position: vec(activeBot.entity.position),
    distance,
    navigation_goal: 'look_at_block'
  }
}

function result (tool, action, status, code, details = {}) {
  if (!['applied', 'partial', 'rejected'].includes(status)) throw new Error(`invalid action status ${status}`)
  return {
    action: { tool, ...action },
    outcome: { status, code, ...details },
    verified: status === 'applied'
  }
}

function applied (tool, action, code, details = {}) { return result(tool, action, 'applied', code, details) }
function partial (tool, action, code, details = {}) { return result(tool, action, 'partial', code, details) }
function rejected (tool, action, code, details = {}) { return result(tool, action, 'rejected', code, details) }

module.exports = {
  actionTimeoutMs,
  applied,
  bindBot,
  ensureMovements,
  entityMatches,
  findEntity,
  captureItemDropNear,
  droppedItemName,
  findInventoryItem,
  findNearbyDroppedItem,
  getBot,
  gotoBlockInteraction,
  gotoEntity,
  gotoPos,
  inventoryCount,
  inventoryDelta,
  inventoryMap,
  isDroppedItemEntity,
  itemSummary,
  waitForInventoryIncrease,
  waitForOwnCollection,
  waitForPhysicsTicks,
  matchName,
  partial,
  remainingMs,
  rejected,
  requireBot,
  sleep,
  stopMotion,
  vec,
  withTimeout
}
