'use strict'

const { Vec3 } = require('vec3')
const runtime = require('./runtime')

function dropNamesForBlock (activeBot, block) {
  const names = []
  for (const row of Array.isArray(block && block.drops) ? block.drops : []) {
    const id = typeof row === 'number' ? row
      : row && typeof row.drop === 'number' ? row.drop
        : row && row.drop && typeof row.drop.id === 'number' ? row.drop.id
          : row && typeof row.id === 'number' ? row.id : null
    const item = id == null ? null : activeBot.registry.items && activeBot.registry.items[id]
    if (item && item.name && !names.includes(item.name)) names.push(item.name)
  }
  if (names.length === 0 && block && block.name) names.push(String(block.name))
  return names
}

async function collectBlock (msg) {
  const activeBot = runtime.getBot()
  await runtime.ensureMovements()
  const action = {
    block: String(msg.block || msg.query || ''),
    count: Number(msg.count),
    max_distance: Number(msg.max_distance || 48)
  }
  if (!action.block || !Number.isInteger(action.count) || action.count <= 0) {
    return runtime.rejected('collect_block', action, 'INVALID_COLLECTION_REQUEST')
  }
  if (!Number.isFinite(action.max_distance) || action.max_distance <= 0) {
    return runtime.rejected('collect_block', action, 'INVALID_COLLECTION_DISTANCE')
  }
  if (!activeBot.collectBlock || typeof activeBot.collectBlock.collect !== 'function') {
    return runtime.rejected('collect_block', action, 'MINEFLAYER_COLLECTBLOCK_UNAVAILABLE')
  }
  if (!activeBot.tool || typeof activeBot.tool.equipForBlock !== 'function') {
    return runtime.rejected('collect_block', action, 'MINEFLAYER_TOOL_UNAVAILABLE')
  }
  if (!activeBot.pathfinder || !activeBot.pathfinder.movements ||
      typeof activeBot.pathfinder.movements.safeToBreak !== 'function') {
    return runtime.rejected('collect_block', action, 'MINEFLAYER_PATHFINDER_SAFETY_UNAVAILABLE')
  }

  const positions = activeBot.findBlocks({
    matching: block => block && block.name === action.block,
    maxDistance: action.max_distance,
    count: action.count
  })
  const targets = positions
    .map(position => activeBot.blockAt(position))
    .filter(block => block && block.name === action.block)
  if (targets.length === 0) {
    return runtime.rejected('collect_block', action, 'BLOCK_NOT_FOUND', {
      requested_count: action.count,
      target_count: 0
    })
  }

  const unsafe = targets.filter(block => !activeBot.pathfinder.movements.safeToBreak(block))
  if (unsafe.length > 0) {
    return runtime.rejected('collect_block', action, 'UNSAFE_BLOCK_BREAK', {
      requested_count: action.count,
      target_count: targets.length,
      unsafe: unsafe.map(block => ({ name: block.name, position: runtime.vec(block.position) }))
    })
  }

  const before = runtime.inventoryMap()
  const expectedItems = [...new Set(targets.flatMap(block => dropNamesForBlock(activeBot, block)))]
  const deadline = Date.now() + runtime.actionTimeoutMs(msg)
  let failure = null
  try {
    await runtime.withTimeout(
      activeBot.collectBlock.collect(targets, { append: false, ignoreNoPath: false }),
      runtime.remainingMs(deadline, 60000),
      'COLLECT_BLOCK'
    )
  } catch (error) {
    failure = {
      name: String(error.name || 'Error'),
      code: String(error.code || error.name || 'COLLECTION_FAILED'),
      message: String(error.message || error)
    }
  }

  const after = runtime.inventoryMap()
  const inventoryDelta = runtime.inventoryDelta(before, after)
  const collectedDelta = Object.fromEntries(
    Object.entries(inventoryDelta).filter(([name, count]) => expectedItems.includes(name) && count > 0)
  )
  const collectedCount = Object.values(collectedDelta).reduce((sum, count) => sum + Number(count), 0)
  const broken = targets
    .map(block => {
      const current = activeBot.blockAt(block.position)
      return current && current.name !== block.name
        ? { name: block.name, position: runtime.vec(block.position) }
        : null
    })
    .filter(Boolean)
  const details = {
    native_provider: 'mineflayer-collectblock',
    requested_count: action.count,
    target_count: targets.length,
    target_positions: targets.map(block => runtime.vec(block.position)),
    expected_items: expectedItems,
    broken,
    errors: failure ? [{ phase: 'collectblock', ...failure }] : [],
    inventory_before: before,
    inventory_after: after,
    inventory_delta: inventoryDelta,
    collected_delta: collectedDelta,
    collected_count: collectedCount
  }
  if (broken.length >= action.count && collectedCount >= action.count) {
    return runtime.applied('collect_block', action, 'BLOCKS_COLLECTED', details)
  }
  if (failure && failure.name === 'NoItem') {
    return runtime.rejected('collect_block', action, 'HARVEST_TOOL_REQUIRED', details)
  }
  if (broken.length > 0 || collectedCount > 0) {
    return runtime.partial('collect_block', action, 'COLLECTION_INCOMPLETE', details)
  }
  return runtime.rejected(
    'collect_block',
    action,
    failure ? 'COLLECTION_FAILED' : 'BLOCK_NOT_COLLECTED',
    details
  )
}
async function craftItem (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || ''), count: Number(msg.count || 1) }
  const item = activeBot.registry.itemsByName[action.item]
  if (!item) return runtime.rejected('craft_item', action, 'UNKNOWN_ITEM')
  const before = runtime.inventoryCount(action.item)
  let table = null
  let recipes = activeBot.recipesFor(item.id, null, 1, null)
  if (!recipes || recipes.length === 0) {
    let tableBlock = activeBot.findBlock({
      matching: block => block && block.name === 'crafting_table',
      maxDistance: 32
    })
    if (!tableBlock) {
      const carriedTable = runtime.findInventoryItem('crafting_table')
      const tableRecipes = activeBot.recipesFor(item.id, null, 1, true)
      if (!carriedTable || !tableRecipes || tableRecipes.length === 0) {
        return runtime.rejected('craft_item', action, 'NO_RECIPE_OR_CRAFTING_TABLE', { before })
      }
      const origin = activeBot.entity.position.floored()
      let placement = null
      for (let radius = 1; radius <= 3 && !placement; radius++) {
        for (let x = -radius; x <= radius && !placement; x++) {
          for (let z = -radius; z <= radius && !placement; z++) {
            const candidate = origin.offset(x, 0, z)
            const targetBlock = activeBot.blockAt(candidate)
            const below = activeBot.blockAt(candidate.offset(0, -1, 0))
            if (targetBlock && targetBlock.name === 'air' && below && below.name !== 'air') placement = candidate
          }
        }
      }
      if (!placement) return runtime.rejected('craft_item', action, 'NO_TABLE_PLACEMENT_SPACE', { before })
      const placed = await placeBlock({ item: 'crafting_table', position: runtime.vec(placement) })
      if (!placed.verified) return runtime.rejected('craft_item', action, 'CRAFTING_TABLE_PLACEMENT_FAILED', { before, placement: placed.outcome })
      tableBlock = activeBot.blockAt(placement)
    }
    await runtime.ensureMovements()
    await runtime.gotoBlockInteraction(tableBlock.position)
    table = activeBot.blockAt(tableBlock.position)
    recipes = activeBot.recipesFor(item.id, null, 1, table)
  }
  if (!recipes || recipes.length === 0) {
    return runtime.rejected('craft_item', action, 'NO_RECIPE_OR_MATERIALS', { before, used_table: Boolean(table) })
  }
  const recipe = recipes[0]
  const outputPerCraft = Math.max(1, Number(recipe.result && recipe.result.count ? recipe.result.count : 1))
  const executions = Math.ceil(action.count / outputPerCraft)
  await activeBot.craft(recipe, executions, table)
  await runtime.sleep(250)
  const after = runtime.inventoryCount(action.item)
  const crafted = Math.max(0, after - before)
  const details = { before, after, crafted, executions, output_per_craft: outputPerCraft, used_table: Boolean(table) }
  if (crafted >= action.count) return runtime.applied('craft_item', action, 'ITEM_CRAFTED', details)
  if (crafted > 0) return runtime.partial('craft_item', action, 'CRAFT_COUNT_INCOMPLETE', details)
  return runtime.rejected('craft_item', action, 'CRAFT_EFFECT_NOT_OBSERVED', details)
}

function selectFuel (requested) {
  if (requested) return runtime.findInventoryItem(requested)
  const preferred = [
    'coal', 'charcoal', 'coal_block', 'blaze_rod', 'dried_kelp_block',
    'oak_planks', 'spruce_planks', 'birch_planks', 'jungle_planks',
    'acacia_planks', 'dark_oak_planks', 'mangrove_planks', 'cherry_planks'
  ]
  for (const name of preferred) {
    const item = runtime.findInventoryItem(name)
    if (item) return item
  }
  return null
}

function fuelCapacity (name) {
  if (name === 'coal_block') return 80
  if (['coal', 'charcoal'].includes(name)) return 8
  if (name === 'blaze_rod') return 12
  if (name === 'dried_kelp_block') return 20
  return 1.5
}

async function smeltItem (msg) {
  const activeBot = runtime.getBot()
  await runtime.ensureMovements()
  const action = {
    item: String(msg.item || ''),
    count: Number(msg.count || 1),
    fuel: msg.fuel ? String(msg.fuel) : null,
    max_distance: Number(msg.max_distance || 32),
    max_wait_s: Number(msg.max_wait_s || 90)
  }
  const input = runtime.findInventoryItem(action.item)
  if (!input || input.count < action.count) {
    return runtime.rejected('smelt_item', action, 'INPUT_NOT_AVAILABLE', { available: input ? input.count : 0 })
  }
  const fuel = selectFuel(action.fuel)
  if (!fuel) return runtime.rejected('smelt_item', action, 'FUEL_NOT_AVAILABLE')
  const block = activeBot.findBlock({
    matching: candidate => candidate && ['furnace', 'blast_furnace', 'smoker'].includes(candidate.name),
    maxDistance: action.max_distance
  })
  if (!block) return runtime.rejected('smelt_item', action, 'FURNACE_NOT_FOUND')
  await runtime.gotoBlockInteraction(block.position)
  const before = runtime.inventoryMap()
  let furnace = null
  let outputObserved = null
  try {
    furnace = await activeBot.openFurnace(activeBot.blockAt(block.position))
    const existingOutput = furnace.outputItem()
    if (existingOutput) {
      return runtime.rejected('smelt_item', action, 'FURNACE_OUTPUT_NOT_EMPTY', {
        furnace: runtime.vec(block.position),
        output: runtime.itemSummary(existingOutput)
      })
    }
    const existingInput = furnace.inputItem()
    if (existingInput && existingInput.type !== input.type) {
      return runtime.rejected('smelt_item', action, 'FURNACE_INPUT_CONFLICT', {
        furnace: runtime.vec(block.position),
        input: runtime.itemSummary(existingInput)
      })
    }
    const existingInputCount = existingInput ? existingInput.count : 0
    const inputNeeded = Math.max(0, action.count - existingInputCount)
    const existingFuel = furnace.fuelItem()
    const fuelNeeded = existingFuel ? 0 : Math.ceil(action.count / fuelCapacity(fuel.name))
    if (fuel.count < fuelNeeded) {
      return runtime.rejected('smelt_item', action, 'FUEL_COUNT_NOT_AVAILABLE', {
        available: fuel.count,
        required: fuelNeeded,
        fuel: fuel.name
      })
    }
    if (fuelNeeded > 0) await furnace.putFuel(fuel.type, null, fuelNeeded)
    if (inputNeeded > 0) await furnace.putInput(input.type, null, inputNeeded)
    const deadline = Date.now() + action.max_wait_s * 1000
    while (Date.now() < deadline) {
      const output = furnace.outputItem()
      if (output && output.count >= action.count) {
        outputObserved = runtime.itemSummary(output)
        break
      }
      await runtime.sleep(500)
    }
    if (furnace.outputItem()) await furnace.takeOutput()
  } finally {
    if (furnace) furnace.close()
  }
  const after = runtime.inventoryMap()
  const delta = runtime.inventoryDelta(before, after)
  const produced = Object.entries(delta)
    .filter(([name, value]) => name !== action.item && value > 0)
    .reduce((sum, [, value]) => sum + value, 0)
  const details = { furnace: runtime.vec(block.position), output: outputObserved, inventory_delta: delta, produced }
  if (produced >= action.count) return runtime.applied('smelt_item', action, 'ITEM_SMELTED', details)
  return runtime.partial('smelt_item', action, 'SMELT_INCOMPLETE', details)
}

async function clearFurnace (msg) {
  const activeBot = runtime.getBot()
  await runtime.ensureMovements()
  const action = { max_distance: Number(msg.max_distance || 32) }
  const block = activeBot.findBlock({
    matching: candidate => candidate && ['furnace', 'blast_furnace', 'smoker'].includes(candidate.name),
    maxDistance: action.max_distance
  })
  if (!block) return runtime.rejected('clear_furnace', action, 'FURNACE_NOT_FOUND')
  await runtime.gotoBlockInteraction(block.position)
  const before = runtime.inventoryMap()
  let furnace = null
  try {
    furnace = await activeBot.openFurnace(activeBot.blockAt(block.position))
    if (furnace.outputItem()) await furnace.takeOutput()
    if (furnace.inputItem()) await furnace.takeInput()
    if (furnace.fuelItem()) await furnace.takeFuel()
  } finally {
    if (furnace) furnace.close()
  }
  const after = runtime.inventoryMap()
  return runtime.applied('clear_furnace', action, 'FURNACE_CLEARED', {
    furnace: runtime.vec(block.position),
    inventory_delta: runtime.inventoryDelta(before, after)
  })
}

async function placeBlock (msg) {
  const activeBot = runtime.getBot()
  await runtime.ensureMovements()
  const action = { item: String(msg.item || ''), position: msg.position || null }
  const item = runtime.findInventoryItem(action.item)
  if (!item) return runtime.rejected('place_block', action, 'ITEM_NOT_AVAILABLE')
  const position = action.position || runtime.vec(activeBot.entity.position.floored().offset(1, 0, 0))
  const target = new Vec3(Math.floor(Number(position.x)), Math.floor(Number(position.y)), Math.floor(Number(position.z)))
  let navigation
  try {
    navigation = await runtime.gotoBlockPlacement(target)
  } catch (error) {
    return runtime.rejected('place_block', action, 'PATHFINDER_PLACE_BLOCK_FAILED', {
      position: runtime.vec(target),
      error: error.message
    })
  }
  await activeBot.equip(item, 'hand')
  try {
    await activeBot.placeBlock(navigation.reference, navigation.face)
  } catch (error) {
    return runtime.rejected('place_block', action, 'PLACE_BLOCK_FAILED', {
      position: runtime.vec(target),
      error: error.message
    })
  }
  const placed = activeBot.blockAt(target)
  const details = { position: runtime.vec(target), placed: placed ? placed.name : null }
  return placed && placed.name !== 'air'
    ? runtime.applied('place_block', action, 'BLOCK_PLACED', details)
    : runtime.rejected('place_block', action, 'BLOCK_NOT_OBSERVED', details)
}

module.exports = {
  clear_furnace: clearFurnace,
  collect_block: collectBlock,
  craft_item: craftItem,
  place_block: placeBlock,
  smelt_item: smeltItem
}
