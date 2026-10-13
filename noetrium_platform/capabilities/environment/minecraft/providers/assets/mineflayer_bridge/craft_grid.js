'use strict'

// An intentionally server-evidenced grid action for worlds with custom
// datapack recipes. Never use a vanilla recipe result as physical truth;
// Mineflayer bot.craft() optimistically synthesizes its expected output slot.
const Item = require('prismarine-item')
const runtime = require('./runtime')

function validateGrid (bot, gridText, station) {
  const length = station === 'table' ? 9 : station === 'inventory' ? 4 : 0
  if (!length) return { error: 'INVALID_CRAFT_STATION' }
  const rows = String(gridText || '').split(',').map(value => value.trim())
  if (rows.length !== length) return { error: 'INVALID_CRAFT_GRID_SIZE', expected_slots: length }
  const wanted = {}
  for (const name of rows) {
    if (name === '_') continue
    if (!/^[a-z0-9_]+$/.test(name)) return { error: 'INVALID_CRAFT_GRID_ITEM', item: name }
    if (!(bot.registry.itemsByName || {})[name]) return { error: 'UNKNOWN_ITEM', item: name }
    wanted[name] = (wanted[name] || 0) + 1
  }
  if (!Object.keys(wanted).length) return { error: 'EMPTY_CRAFT_GRID' }
  for (const [name, count] of Object.entries(wanted)) {
    const available = runtime.inventoryCount(name)
    if (available < count) {
      return { error: 'MISSING_GRID_INGREDIENTS',
        prerequisites: { item: name, needed: count, available } }
    }
  }
  return { rows, wanted }
}

async function craftGrid (msg) {
  const bot = runtime.getBot()
  const action = {
    grid: String(msg.grid || ''),
    station: String(msg.station || 'inventory'),
    max_distance: Number(msg.max_distance || 32)
  }
  const validated = validateGrid(bot, action.grid, action.station)
  if (validated.error) return runtime.rejected('craft_grid', action, validated.error, validated)
  if (!bot._client || typeof bot._client.on !== 'function') {
    return runtime.rejected('craft_grid', action, 'SERVER_SLOT_EVIDENCE_UNAVAILABLE')
  }
  const startingPosition = bot.entity.position.clone()
  const inventoryBefore = runtime.inventoryMap()
  let table = null
  let window = bot.inventory
  let gridChangesAttempted = false
  let serverOutput = null
  let clientItems = null
  const { rows } = validated
  const onPacket = (data, meta) => {
    const name = meta && meta.name
    if (!window || !data || !meta || (name !== 'set_slot' && name !== 'window_items')) return
    if (Number(data.windowId) !== Number(window.id)) return
    const raw = name === 'set_slot'
      ? (Number(data.slot) === 0 ? data.item : undefined)
      : (Array.isArray(data.items) ? data.items[0] : undefined)
    if (raw === undefined) return
    try {
      const decoded = Item(bot.registry).fromNotch(raw)
      if (decoded && decoded.name && decoded.count > 0) {
        serverOutput = { name: decoded.name, count: decoded.count }
      }
    } catch (_) {
      // An unparseable packet must never prove a recipe success.
    }
  }
  try {
    if (action.station === 'table') {
      table = bot.findBlock({
        matching: block => block && block.name === 'crafting_table',
        maxDistance: action.max_distance
      })
      if (!table) return runtime.rejected('craft_grid', action, 'CRAFTING_TABLE_NOT_FOUND', {
        prerequisites: { nearby_crafting_table: false, carried_crafting_table:
          runtime.inventoryCount('crafting_table') > 0 }
      })
      await runtime.ensureMovements()
      await runtime.gotoBlockInteraction(table.position)
      window = await new Promise((resolve, reject) => {
        const remaining = runtime.actionRemainingMs()
        const timer = setTimeout(() => {
          bot.removeListener('windowOpen', opened)
          reject(new Error('CRAFTING_TABLE_WINDOW_NOT_OPEN'))
        }, remaining)
        function opened (openedWindow) {
          clearTimeout(timer)
          resolve(openedWindow)
        }
        bot.once('windowOpen', opened)
        bot.activateBlock(bot.blockAt(table.position))
      })
      if (!window.type.startsWith('minecraft:crafting')) throw new Error('CRAFTING_WINDOW_WRONG_TYPE')
    }
    clientItems = window
    const occupied = []
    for (let slot = 0; slot <= rows.length; slot++) {
      if (window.slots[slot]) occupied.push(slot)
    }
    if (occupied.length) {
      const moved = bot.entity.position.distanceTo(startingPosition)
      const evidence = {
        occupied_slots: occupied, moved,
        position_before: runtime.vec(startingPosition),
        position_after: runtime.vec(bot.entity.position)
      }
      return moved > 0
        ? runtime.partial('craft_grid', action, 'CRAFT_GRID_NOT_EMPTY', evidence, 'applied')
        : runtime.rejected('craft_grid', action, 'CRAFT_GRID_NOT_EMPTY', evidence)
    }
    bot._client.on('packet', onPacket)
    for (let index = 0; index < rows.length; index++) {
      const name = rows[index]
      if (name === '_') continue
      const item = bot.registry.itemsByName[name]
      const source = window.findInventoryItem(item.id, null)
      if (!source) throw new Error('CRAFT_GRID_INGREDIENT_DISAPPEARED')
      const targetSlot = index + 1
      await bot.clickWindow(source.slot, 0, 0)
      await bot.clickWindow(targetSlot, 1, 0)
      gridChangesAttempted = true
      if (window.selectedItem) {
        await bot.putSelectedItemRange(
          window.inventoryStart, window.inventoryEnd, window, source.slot
        )
      }
    }
    // Wait for one native world/server tick to allow the authoritative
    // recipe response to arrive after the final click. This is physical
    // synchronization, not a guessed fixed-time sleep or an extra retry.
    await runtime.waitForPhysicsTicks(1)
    // No local optimistic recipe prediction: only a server output-slot packet
    // may authorize taking a result from slot zero.
    const actualServerOutput = serverOutput
    if (actualServerOutput && window.slots[0] &&
        window.slots[0].name === actualServerOutput.name) {
      await bot.putAway(0)
    }
    // Put every unused or rejected grid ingredient back into inventory.
    for (let slot = 1; slot <= rows.length; slot++) {
      if (window.slots[slot]) await bot.putAway(slot)
    }
    const after = runtime.inventoryMap()
    const delta = runtime.inventoryDelta(inventoryBefore, after)
    const added = Object.fromEntries(Object.entries(delta).filter(([,count]) => count > 0))
    const moved = bot.entity.position.distanceTo(startingPosition)
    const details = {
      position_before: runtime.vec(startingPosition),
      position_after: runtime.vec(bot.entity.position),
      moved,
      server_output_packet: actualServerOutput,
      inventory_before: inventoryBefore,
      inventory_after: after,
      inventory_delta: delta,
      produced_items: added,
      grid_changes_attempted: gridChangesAttempted,
      recipe_authority: 'server_crafting_output_slot'
    }
    if (actualServerOutput && (added[actualServerOutput.name] || 0) > 0) {
      return runtime.applied('craft_grid', action, 'SERVER_RECIPE_CRAFTED', details)
    }
    // A click returning locally is not by itself an acknowledged physical
    // effect. If the server never confirmed output, preserve uncertainty
    // rather than converting an attempted grid placement into false truth.
    const verifiedStateChange = moved > 0 || Object.values(delta).some(value => value !== 0)
    if (verifiedStateChange || gridChangesAttempted) {
      return runtime.partial(
        'craft_grid', action, 'CRAFT_GRID_RESULT_UNCONFIRMED', details,
        verifiedStateChange ? 'applied' : 'unknown'
      )
    }
    return runtime.rejected('craft_grid', action, 'NO_SERVER_RECIPE_MATCH', details)
  } finally {
    bot._client.removeListener('packet', onPacket)
    if (table && clientItems && typeof bot.closeWindow === 'function') {
      await bot.closeWindow(clientItems)
    }
  }
}

module.exports = { craft_grid: craftGrid, validateGrid }
