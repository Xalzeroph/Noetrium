'use strict'

const runtime = require('./runtime')

async function equipItem (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || ''), destination: String(msg.destination || 'hand') }
  const item = runtime.findInventoryItem(action.item)
  if (!item) {
    const registryItems = activeBot.registry && activeBot.registry.itemsByName
      ? Object.keys(activeBot.registry.itemsByName)
      : []
    const query = action.item.toLowerCase()
    const concreteCandidates = registryItems
      .filter(name => name === query || name.endsWith('_' + query))
      .sort()
    const availableCandidates = activeBot.inventory.items()
      .map(row => row && row.name ? String(row.name) : '')
      .filter(name => name && (name === query || name.endsWith('_' + query)))
      .filter((name, index, values) => values.indexOf(name) === index)
      .sort()
    const exactRegistryItem = Boolean(
      activeBot.registry && activeBot.registry.itemsByName && activeBot.registry.itemsByName[action.item]
    )
    const details = {
      semantic_domain: 'minecraft.item_name',
      target_classification: exactRegistryItem
        ? 'item'
        : concreteCandidates.length > 0 ? 'item_family' : 'unknown',
      prerequisites: {
        inventory_contains_requested_item: false,
        exact_registry_item: exactRegistryItem,
        available_concrete_items: availableCandidates,
        concrete_registry_candidates: concreteCandidates
      },
      rejected_argument_constraints: [{
        argument_path: ['item'],
        rejected_value: action.item,
        validity: { until_state_change: [['inventory']] }
      }]
    }
    return runtime.rejected('equip_item', action, 'ITEM_NOT_AVAILABLE', details)
  }
  const destinationSlot = action.destination === 'hand'
    ? null
    : activeBot.getEquipmentDestSlot(action.destination)
  const equippedBefore = action.destination === 'hand'
    ? activeBot.heldItem
    : activeBot.inventory.slots[destinationSlot]
  if (equippedBefore && equippedBefore.name === action.item) {
    return runtime.satisfied('equip_item', action, 'ITEM_ALREADY_EQUIPPED', {
      equipped: runtime.itemSummary(equippedBefore)
    })
  }
  await activeBot.equip(item, action.destination)
  const equipped = action.destination === 'hand'
    ? activeBot.heldItem
    : activeBot.inventory.slots[destinationSlot]
  return equipped && equipped.name === action.item
    ? runtime.applied('equip_item', action, 'ITEM_EQUIPPED', { equipped: runtime.itemSummary(equipped) })
    : runtime.partial('equip_item', action, 'EQUIP_NOT_CONFIRMED')
}


async function useShield (msg) {
  const activeBot = runtime.getBot()
  const action = { duration_ms: Number(msg.duration_ms || 1200) }
  const shield = runtime.findInventoryItem('shield')
  if (!shield) return runtime.rejected('use_shield', action, 'SHIELD_NOT_AVAILABLE')
  const beforeHealth = Number(activeBot.health)
  await activeBot.equip(shield, 'off-hand')
  const slot = activeBot.getEquipmentDestSlot('off-hand')
  const equipped = activeBot.inventory.slots[slot]
  if (!equipped || equipped.name !== 'shield') {
    return runtime.partial('use_shield', action, 'SHIELD_EQUIP_UNCONFIRMED', {
      equipped: runtime.itemSummary(equipped)
    })
  }
  let activated = false
  let heldUsing = false
  const unregister = runtime.onActionCancel('mineflayer:shield-use', async () => {
    if (activeBot.usingHeldItem && typeof activeBot.deactivateItem === 'function') {
      activeBot.deactivateItem()
    }
  })
  try {
    activeBot.activateItem(true)
    activated = activeBot.usingHeldItem === true
    await runtime.sleep(action.duration_ms)
    heldUsing = activeBot.usingHeldItem === true
  } finally {
    if (typeof activeBot.deactivateItem === 'function') activeBot.deactivateItem()
    unregister()
  }
  const released = activeBot.usingHeldItem === false
  const details = {
    offhand_item: equipped.name,
    activated,
    held_using: heldUsing,
    released,
    duration_ms: action.duration_ms,
    health_before: beforeHealth,
    health_after: Number(activeBot.health)
  }
  return activated && heldUsing && released
    ? runtime.applied('use_shield', action, 'SHIELD_USED', details)
    : runtime.partial('use_shield', action, 'SHIELD_USE_UNCONFIRMED', details)
}

async function consumeItem (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || '') }
  const item = runtime.findInventoryItem(action.item)
  if (!item) return runtime.rejected('consume_item', action, 'ITEM_NOT_AVAILABLE')

  const before = {
    count: runtime.inventoryCount(action.item),
    food: activeBot.food,
    health: activeBot.health
  }
  await activeBot.equip(item, 'hand')

  let providerError = null
  let providerCompletionObserved = false
  try {
    await activeBot.consume()
    providerCompletionObserved = true
  } catch (error) {
    providerError = error
  }

  const after = {
    count: runtime.inventoryCount(action.item),
    food: activeBot.food,
    health: activeBot.health
  }
  const stateDeltaObserved = (
    after.count < before.count ||
    after.food > before.food ||
    after.health > before.health
  )
  const details = {
    before,
    after,
    provider_completion_observed: providerCompletionObserved,
    state_delta_observed: stateDeltaObserved,
    provider_error: providerError ? runtime.errorEvidence(providerError) : null
  }

  if (providerCompletionObserved || stateDeltaObserved) {
    return runtime.applied(
      'consume_item',
      action,
      providerError
        ? 'ITEM_CONSUMED_DESPITE_PROVIDER_ERROR'
        : 'ITEM_CONSUMED',
      details
    )
  }
  if (providerError) {
    return runtime.rejected(
      'consume_item',
      action,
      'CONSUMPTION_REJECTED',
      details,
      'not_applied'
    )
  }
  return runtime.partial(
    'consume_item',
    action,
    'CONSUMPTION_COMPLETION_UNCONFIRMED',
    details,
    'unknown'
  )
}

async function discardItem (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || ''), count: Number(msg.count || 1) }
  const item = runtime.findInventoryItem(action.item)
  const before = runtime.inventoryCount(action.item)
  if (!item || before < action.count) return runtime.rejected('discard_item', action, 'ITEM_COUNT_NOT_AVAILABLE', { before })
  await activeBot.toss(item.type, null, action.count)
  const after = runtime.inventoryCount(action.item)
  return before - after >= action.count
    ? runtime.applied('discard_item', action, 'ITEM_DISCARDED', { before, after })
    : runtime.partial('discard_item', action, 'DISCARD_COUNT_INCOMPLETE', { before, after })
}

async function giveItem (msg) {
  const activeBot = runtime.getBot()
  const action = { player: String(msg.player || ''), item: String(msg.item || ''), count: Number(msg.count || 1) }
  const target = runtime.findEntity(action.player, 64, entity => entity.type === 'player' && entity.username === action.player)
  if (!target) return runtime.rejected('give_item', action, 'PLAYER_NOT_FOUND')
  const item = runtime.findInventoryItem(action.item)
  const before = runtime.inventoryCount(action.item)
  if (!item || before < action.count) return runtime.rejected('give_item', action, 'ITEM_COUNT_NOT_AVAILABLE', { before })
  await runtime.gotoEntity(target, 2)
  await activeBot.lookAt(target.position.offset(0, 1.5, 0), true)
  await activeBot.toss(item.type, null, action.count)
    const after = runtime.inventoryCount(action.item)
  return before - after >= action.count
    ? runtime.applied('give_item', action, 'ITEM_DROPPED_TO_PLAYER', { player_entity_id: target.id, before, after })
    : runtime.partial('give_item', action, 'GIVE_COUNT_INCOMPLETE', { player_entity_id: target.id, before, after })
}

function findContainerBlock (maxDistance) {
  const activeBot = runtime.getBot()
  return activeBot.findBlock({
    matching: block => block && ['chest', 'trapped_chest', 'barrel'].includes(block.name),
    maxDistance
  })
}

function containerItems (container) {
  if (typeof container.containerItems === 'function') return container.containerItems()
  if (typeof container.items === 'function') return container.items()
  return []
}

async function withContainer (msg, maxDistance, callback) {
  const activeBot = runtime.getBot()
  const providerWindow = runtime.createActionProviderWindow(msg)
  await runtime.ensureMovements()
  const block = findContainerBlock(maxDistance)
  if (!block) return { missing: true, position: null, value: null }
  await runtime.gotoBlockInteraction(block.position, providerWindow.remainingMs())
  let container = null
  try {
    container = await runtime.withTimeout(
      activeBot.openContainer(activeBot.blockAt(block.position)),
      providerWindow.remainingMs(),
      'CONTAINER_OPEN'
    )
    const value = await runtime.withTimeout(
      Promise.resolve().then(() => callback(container)),
      providerWindow.remainingMs(),
      'CONTAINER_OPERATION'
    )
    return { missing: false, position: runtime.vec(block.position), value }
  } finally {
    if (container) container.close()
  }
}

async function chestInspect (msg) {
  const action = { max_distance: Number(msg.max_distance || 32) }
  const opened = await withContainer(msg, action.max_distance, async container => (
    containerItems(container).map(runtime.itemSummary)
  ))
  if (opened.missing) return runtime.rejected('chest_inspect', action, 'CONTAINER_NOT_FOUND')
  return runtime.applied('chest_inspect', action, 'CONTAINER_INSPECTED', {
    position: opened.position,
    items: opened.value
  })
}

async function chestDeposit (msg) {
  const action = { item: String(msg.item || ''), count: Number(msg.count || 1), max_distance: Number(msg.max_distance || 32) }
  const available = runtime.inventoryCount(action.item)
  const item = runtime.findInventoryItem(action.item)
  if (!item || available < action.count) return runtime.rejected('chest_deposit', action, 'ITEM_COUNT_NOT_AVAILABLE', { available })
  const opened = await withContainer(msg, action.max_distance, async container => {
    await container.deposit(item.type, null, action.count)
    return runtime.inventoryCount(action.item)
  })
  if (opened.missing) return runtime.rejected('chest_deposit', action, 'CONTAINER_NOT_FOUND')
  const deposited = available - opened.value
  const details = { position: opened.position, before: available, after: opened.value, deposited }
  return deposited >= action.count
    ? runtime.applied('chest_deposit', action, 'ITEM_DEPOSITED', details)
    : runtime.partial('chest_deposit', action, 'DEPOSIT_COUNT_INCOMPLETE', details)
}

async function chestWithdraw (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || ''), count: Number(msg.count || 1), max_distance: Number(msg.max_distance || 32) }
  const itemDefinition = activeBot.registry.itemsByName[action.item]
  if (!itemDefinition) return runtime.rejected('chest_withdraw', action, 'UNKNOWN_ITEM')
  const before = runtime.inventoryCount(action.item)
  const opened = await withContainer(msg, action.max_distance, async container => {
    const inContainer = containerItems(container)
      .filter(item => item.name === action.item)
      .reduce((sum, item) => sum + item.count, 0)
    if (inContainer < action.count) return { available: inContainer, after: before }
    await container.withdraw(itemDefinition.id, null, action.count)
    return { available: inContainer, after: runtime.inventoryCount(action.item) }
  })
  if (opened.missing) return runtime.rejected('chest_withdraw', action, 'CONTAINER_NOT_FOUND')
  const withdrawn = opened.value.after - before
  const details = { position: opened.position, before, after: opened.value.after, available: opened.value.available, withdrawn }
  if (opened.value.available < action.count) return runtime.rejected('chest_withdraw', action, 'CONTAINER_ITEM_COUNT_NOT_AVAILABLE', details)
  return withdrawn >= action.count
    ? runtime.applied('chest_withdraw', action, 'ITEM_WITHDRAWN', details)
    : runtime.partial('chest_withdraw', action, 'WITHDRAW_COUNT_INCOMPLETE', details)
}

module.exports = {
  chest_deposit: chestDeposit,
  chest_inspect: chestInspect,
  chest_withdraw: chestWithdraw,
  consume_item: consumeItem,
  discard_item: discardItem,
  equip_item: equipItem,
  use_shield: useShield,
  give_item: giveItem
}
