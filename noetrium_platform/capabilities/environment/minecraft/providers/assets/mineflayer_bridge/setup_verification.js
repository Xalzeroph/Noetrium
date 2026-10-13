'use strict'

const { Vec3 } = require('vec3')

function normalizedName (value) {
  return String(value == null ? '' : value)
    .replace(/^minecraft:/, '')
    .replace(/[^a-zA-Z0-9]+/g, '')
    .toLowerCase()
}

function canonicalDimension (value) {
  const text = String(value == null ? '' : value).replace(/^minecraft:/, '')
  if (text === 'overworld') return 'overworld'
  if (text === 'the_nether' || text === 'nether') return 'the_nether'
  if (text === 'the_end' || text === 'end') return 'the_end'
  return text
}

function agentBlockOrigin (bot) {
  const position = bot.entity && bot.entity.position
  if (!position) throw new Error('setup verification requires agent position')
  return new Vec3(Math.floor(position.x), Math.floor(position.y), Math.floor(position.z))
}

function blockPosition (bot, values, anchor) {
  const [x, y, z] = values.map(Number)
  if (anchor === 'world') return new Vec3(x, y, z)
  const origin = agentBlockOrigin(bot)
  return new Vec3(origin.x + x, origin.y + y, origin.z + z)
}

function entityPosition (bot, values, anchor) {
  const [x, y, z] = values.map(Number)
  if (anchor === 'world') return new Vec3(x, y, z)
  const position = bot.entity && bot.entity.position
  if (!position) throw new Error('setup verification requires agent position')
  return new Vec3(position.x + x, position.y + y, position.z + z)
}

function itemName (item) {
  return item && item.name ? String(item.name).replace(/^minecraft:/, '') : null
}

function inventoryCounts (bot) {
  const result = {}
  const rows = bot.inventory && typeof bot.inventory.items === 'function'
    ? bot.inventory.items()
    : []
  for (const item of rows) {
    const name = itemName(item)
    if (!name) continue
    result[name] = (result[name] || 0) + Number(item.count || 0)
  }
  return result
}

const EQUIPMENT_INDEX = {
  mainhand: 0,
  offhand: 1,
  feet: 2,
  legs: 3,
  chest: 4,
  head: 5
}

function sourceInventorySlotItem (bot, sourceIndex) {
  const equipment = (bot.entity && Array.isArray(bot.entity.equipment))
    ? bot.entity.equipment
    : []
  if (sourceIndex === 36) return equipment[EQUIPMENT_INDEX.feet] || null
  if (sourceIndex === 37) return equipment[EQUIPMENT_INDEX.legs] || null
  if (sourceIndex === 38) return equipment[EQUIPMENT_INDEX.chest] || null
  if (sourceIndex === 39) return equipment[EQUIPMENT_INDEX.head] || null
  if (sourceIndex === 40) return equipment[EQUIPMENT_INDEX.offhand] || null
  const slots = bot.inventory && Array.isArray(bot.inventory.slots)
    ? bot.inventory.slots
    : []
  if (sourceIndex >= 0 && sourceIndex <= 8) return slots[36 + sourceIndex] || null
  if (sourceIndex >= 9 && sourceIndex <= 35) return slots[sourceIndex] || null
  return null
}

function verifyInventory (bot, expectedRows) {
  const counts = inventoryCounts(bot)
  const equipment = (bot.entity && Array.isArray(bot.entity.equipment))
    ? bot.entity.equipment
    : []
  const failures = []
  const checks = []
  if (expectedRows.length === 0) {
    const nonzero = Object.entries(counts).filter(([, count]) => count > 0)
    const equipped = equipment.map(itemName).filter(Boolean)
    const ok = nonzero.length === 0 && equipped.length === 0
    checks.push({ kind: 'initial_inventory_empty', ok, observed_item_kinds: nonzero.length, equipped })
    if (!ok) failures.push({ kind: 'initial_inventory_empty', observed_counts: counts, equipped })
    return { checks, failures }
  }
  for (const row of expectedRows) {
    const name = String(row.item || '').replace(/^minecraft:/, '')
    const count = Number(row.count || 1)
    const slot = row.slot === undefined || row.slot === null ? '' : String(row.slot).trim()
    if (slot && Object.prototype.hasOwnProperty.call(EQUIPMENT_INDEX, slot)) {
      const observedItem = equipment[EQUIPMENT_INDEX[slot]] || null
      const observed = itemName(observedItem)
      const observedCount = Number((observedItem && observedItem.count) || (observed ? 1 : 0))
      const ok = observed === name && observedCount >= count
      checks.push({ kind: 'initial_equipment', item: name, slot, expected_min: count, observed, observed_count: observedCount, ok })
      if (!ok) failures.push({ kind: 'initial_equipment', item: name, slot, expected_min: count, observed, observed_count: observedCount })
    } else if (/^\d+$/.test(slot)) {
      const sourceIndex = Number(slot)
      const observedItem = sourceInventorySlotItem(bot, sourceIndex)
      const observed = itemName(observedItem)
      const observedCount = Number((observedItem && observedItem.count) || (observed ? 1 : 0))
      const ok = sourceIndex >= 0 && sourceIndex <= 40 && observed === name && observedCount >= count
      checks.push({ kind: 'initial_inventory_slot', item: name, slot: sourceIndex, expected_min: count, observed, observed_count: observedCount, ok })
      if (!ok) failures.push({ kind: 'initial_inventory_slot', item: name, slot: sourceIndex, expected_min: count, observed, observed_count: observedCount })
    } else {
      const observed = Number(counts[name] || 0)
      const ok = observed >= count
      checks.push({ kind: 'initial_inventory', item: name, expected_min: count, observed, ok })
      if (!ok) failures.push({ kind: 'initial_inventory', item: name, expected_min: count, observed })
    }
  }
  return { checks, failures }
}

function entityMatches (entity, expected) {
  const target = normalizedName(expected)
  return [entity.name, entity.username, entity.displayName, entity.type]
    .some(value => normalizedName(value) === target)
}

function validEntities (bot) {
  return Object.values(bot.entities || {})
    .filter(entity => entity && entity !== bot.entity && entity.isValid !== false && entity.position)
}

function verifyInitialMobs (bot, rows) {
  const checks = []
  const failures = []
  const origin = bot.entity && bot.entity.position
  for (const row of rows) {
    const expected = String(row.entity || '').replace(/^minecraft:/, '')
    const minimum = Number(row.count || 1)
    const matches = validEntities(bot).filter(entity =>
      entityMatches(entity, expected) && (!origin || entity.position.distanceTo(origin) <= 12)
    )
    const ok = matches.length >= minimum
    checks.push({ kind: 'initial_mob', entity: expected, expected_min: minimum, observed: matches.length, ok })
    if (!ok) failures.push({ kind: 'initial_mob', entity: expected, expected_min: minimum, observed: matches.length })
  }
  return { checks, failures }
}

function verifyBlockRegion (bot, operation) {
  const start = blockPosition(bot, operation.start, operation.anchor)
  const end = blockPosition(bot, operation.end, operation.anchor)
  const minimum = new Vec3(
    Math.min(start.x, end.x), Math.min(start.y, end.y), Math.min(start.z, end.z)
  )
  const maximum = new Vec3(
    Math.max(start.x, end.x), Math.max(start.y, end.y), Math.max(start.z, end.z)
  )
  const expected = String(operation.block).replace(/^minecraft:/, '')
  let observed = 0
  let matched = 0
  const mismatches = []
  for (let x = minimum.x; x <= maximum.x; x++) {
    for (let y = minimum.y; y <= maximum.y; y++) {
      for (let z = minimum.z; z <= maximum.z; z++) {
        observed++
        const position = new Vec3(x, y, z)
        const block = bot.blockAt(position)
        const actual = block && block.name ? String(block.name) : null
        if (actual === expected) matched++
        else if (mismatches.length < 8) mismatches.push({ x, y, z, observed: actual })
      }
    }
  }
  return {
    operation_id: String(operation.operation_id),
    kind: 'fill', expected_block: expected,
    expected_count: observed, matched_count: matched,
    mismatch_count: observed - matched, mismatch_sample: mismatches,
    ok: observed > 0 && matched === observed
  }
}

function verifySetBlock (bot, operation) {
  const position = blockPosition(bot, operation.position, operation.anchor)
  const expected = String(operation.block).replace(/^minecraft:/, '')
  const block = bot.blockAt(position)
  const observed = block && block.name ? String(block.name) : null
  return {
    operation_id: String(operation.operation_id), kind: 'set_block', expected_block: expected,
    position: { x: position.x, y: position.y, z: position.z }, observed,
    ok: observed === expected
  }
}

function verifySummon (bot, operation) {
  const expected = String(operation.entity).replace(/^minecraft:/, '')
  const position = entityPosition(bot, operation.position, operation.anchor)
  const candidates = validEntities(bot)
    .filter(entity => entityMatches(entity, expected))
    .map(entity => ({ entity, distance: entity.position.distanceTo(position) }))
    .filter(row => row.distance <= 1.75)
    .sort((left, right) => left.distance - right.distance)
  return {
    operation_id: String(operation.operation_id), kind: 'summon', entity: expected,
    expected_position: { x: position.x, y: position.y, z: position.z },
    observed_count: candidates.length,
    nearest_distance: candidates.length ? candidates[0].distance : null,
    nearest_entity_id: candidates.length ? candidates[0].entity.id : null,
    ok: candidates.length > 0
  }
}

function effectDescriptor (bot, expected) {
  const target = normalizedName(expected)
  const rows = bot.registry && bot.registry.effectsByName ? bot.registry.effectsByName : {}
  return Object.values(rows).find(row => normalizedName(row && row.name) === target) || null
}

function verifyEffect (bot, operation) {
  const descriptor = effectDescriptor(bot, operation.effect)
  const effects = (bot.entity && bot.entity.effects) || {}
  const observed = descriptor ? effects[descriptor.id] : null
  const expectedAmplifier = Number(operation.amplifier || 0)
  const actualAmplifier = observed && Number.isFinite(Number(observed.amplifier))
    ? Number(observed.amplifier)
    : null
  return {
    operation_id: String(operation.operation_id), kind: 'effect',
    effect: String(operation.effect), effect_id: descriptor ? descriptor.id : null,
    expected_amplifier: expectedAmplifier, observed_amplifier: actualAmplifier,
    observed_duration: observed && Number.isFinite(Number(observed.duration)) ? Number(observed.duration) : null,
    ok: Boolean(descriptor && observed && actualAmplifier === expectedAmplifier)
  }
}

function verifyWorldOperations (bot, operations) {
  return operations.map(operation => {
    const kind = String(operation.kind || '')
    if (kind === 'fill') return verifyBlockRegion(bot, operation)
    if (kind === 'set_block') return verifySetBlock(bot, operation)
    if (kind === 'summon') return verifySummon(bot, operation)
    if (kind === 'effect') return verifyEffect(bot, operation)
    return { operation_id: String(operation.operation_id || ''), kind, ok: false, error: 'unsupported_world_operation' }
  })
}

function currentWeather (bot) {
  return bot.thunderState > 0 ? 'thunder' : bot.rainState > 0 ? 'rain' : 'clear'
}

function verifyPhysicalAnchor (bot) {
  const entity = bot.entity
  const position = entity && entity.position
  const observed = position
    ? { x: Number(position.x), y: Number(position.y), z: Number(position.z) }
    : null
  const finitePosition = observed != null && ['x', 'y', 'z'].every(axis => Number.isFinite(observed[axis]))
  const onGround = Boolean(entity && entity.onGround === true)
  return {
    kind: 'physical_anchor',
    expected: 'on_ground',
    observed_position: finitePosition ? observed : null,
    observed_on_ground: onGround,
    ok: finitePosition && onGround
  }
}

function verifyAuthorityPosition (bot, expected) {
  const position = bot.entity && bot.entity.position
  const axes = ['x', 'y', 'z']
  const target = {}
  let expectedValid = true
  for (const axis of axes) {
    const value = Number(expected && expected[axis])
    if (!Number.isFinite(value)) expectedValid = false
    target[axis] = value
  }
  const observed = position
    ? { x: Number(position.x), y: Number(position.y), z: Number(position.z) }
    : null
  const observedValid = observed != null && axes.every(axis => Number.isFinite(observed[axis]))
  const sameVoxel = expectedValid && observedValid && axes.every(axis =>
    Math.floor(target[axis]) === Math.floor(observed[axis])
  )
  return {
    kind: 'authority_position',
    expected: expectedValid ? target : null,
    observed: observedValid ? observed : null,
    expected_voxel: expectedValid
      ? { x: Math.floor(target.x), y: Math.floor(target.y), z: Math.floor(target.z) }
      : null,
    observed_voxel: observedValid
      ? { x: Math.floor(observed.x), y: Math.floor(observed.y), z: Math.floor(observed.z) }
      : null,
    ok: sameVoxel
  }
}

function observedBiomeName (bot) {
  const position = bot.entity && bot.entity.position
  if (!position) return null

  const block = typeof bot.blockAt === 'function' ? bot.blockAt(position) : null
  const direct = block && block.biome && block.biome.name
  if (direct) return String(direct).replace(/^minecraft:/, '')

  const world = bot.world
  if (!world || typeof world.getColumnAt !== 'function' || typeof world.getBiome !== 'function') return null
  const column = world.getColumnAt(position)
  if (!column) return null
  const biomeId = Number(world.getBiome(position))
  if (!Number.isFinite(biomeId)) return null
  const byId = bot.registry && bot.registry.biomes ? bot.registry.biomes[biomeId] : null
  if (byId && byId.name) return String(byId.name).replace(/^minecraft:/, '')
  const byName = bot.registry && bot.registry.biomesByName ? bot.registry.biomesByName : {}
  const descriptor = Object.values(byName).find(row => row && Number(row.id) === biomeId)
  return descriptor && descriptor.name ? String(descriptor.name).replace(/^minecraft:/, '') : null
}

function waitForSetupProjection (bot, setup, timeoutMs = 8000) {
  const timeout = Number(timeoutMs)
  if (!Number.isFinite(timeout) || timeout <= 0) {
    throw new Error('setup verification timeout must be positive')
  }

  return new Promise(resolve => {
    const listeners = []
    let settled = false
    let scheduled = false
    let latest = null
    let timer = null

    const listen = (emitter, event, handler) => {
      if (!emitter || typeof emitter.on !== 'function' || typeof emitter.removeListener !== 'function') return
      emitter.on(event, handler)
      listeners.push([emitter, event, handler])
    }
    const cleanup = () => {
      for (const [emitter, event, handler] of listeners) emitter.removeListener(event, handler)
      if (timer !== null) clearTimeout(timer)
    }
    const finish = (proof, timedOut) => {
      if (settled) return
      settled = true
      cleanup()
      resolve({ ...proof, timed_out: Boolean(timedOut) })
    }
    const evaluate = () => {
      scheduled = false
      if (settled) return
      latest = verifySetupProjection(bot, setup)
      if (latest.verified) finish(latest, false)
    }
    const schedule = () => {
      if (settled || scheduled) return
      scheduled = true
      queueMicrotask(evaluate)
    }

    // Attach before the first read so a packet arriving between the initial
    // mutation/readback cut cannot be lost. Re-evaluation is driven only by
    // provider state events; there is no periodic setup polling.
    listen(bot.inventory, 'updateSlot', schedule)
    for (const event of [
      'heldItemChanged', 'forcedMove', 'physicsTick', 'chunkColumnLoad', 'entitySpawn',
      'entityEffect', 'blockUpdate'
    ]) listen(bot, event, schedule)
    const client = bot._client
    for (const event of ['update_time', 'game_state_change', 'respawn']) {
      listen(client, event, schedule)
    }

    timer = setTimeout(() => {
      latest = verifySetupProjection(bot, setup)
      finish(latest, true)
    }, timeout)
    evaluate()
  })
}

function verifySetupProjection (bot, setup) {
  const checks = []
  const failures = []
  const push = row => {
    checks.push(row)
    if (!row.ok && failures.length < 16) failures.push(row)
  }

  if (setup.require_physical_anchor === true) {
    push(verifyPhysicalAnchor(bot))
  }
  if (setup.dimension) {
    const observed = canonicalDimension(bot.game && bot.game.dimension)
    const expected = canonicalDimension(setup.dimension)
    push({ kind: 'dimension', expected, observed, ok: observed === expected })
  }
  let authorityPositionReady = true
  if (setup.authority_position) {
    const authorityPosition = verifyAuthorityPosition(bot, setup.authority_position)
    push(authorityPosition)
    authorityPositionReady = authorityPosition.ok
  }
  if (setup.biome && authorityPositionReady) {
    const observed = observedBiomeName(bot)
    const expected = String(setup.biome).replace(/^minecraft:/, '')
    push({ kind: 'biome', expected, observed, ok: observed === expected })
  }
  if (setup.weather) {
    const observed = currentWeather(bot)
    const expected = String(setup.weather)
    push({ kind: 'weather', expected, observed, ok: observed === expected })
  }
  if (setup.start_at_night === true) {
    const observed = bot.time && Number.isFinite(Number(bot.time.timeOfDay))
      ? Number(bot.time.timeOfDay)
      : null
    const ok = observed != null && observed >= 13000 && observed <= 23000
    push({ kind: 'start_at_night', expected: true, observed_time_of_day: observed, ok })
  }

  const inventory = verifyInventory(bot, Array.isArray(setup.initial_inventory) ? setup.initial_inventory : [])
  for (const row of inventory.checks) push(row)
  const mobs = verifyInitialMobs(bot, Array.isArray(setup.initial_mobs) ? setup.initial_mobs : [])
  for (const row of mobs.checks) push(row)
  const operations = verifyWorldOperations(bot, Array.isArray(setup.world_ops) ? setup.world_ops : [])
  for (const row of operations) push(row)

  return {
    schema: 'noetrium.minecraft-task-setup-physical-proof.v1',
    verified: failures.length === 0,
    check_count: checks.length,
    checks,
    failures
  }
}

module.exports = {
  agentBlockOrigin,
  canonicalDimension,
  normalizedName,
  observedBiomeName,
  verifyAuthorityPosition,
  verifyPhysicalAnchor,
  verifySetupProjection,
  verifyWorldOperations,
  waitForSetupProjection
}
