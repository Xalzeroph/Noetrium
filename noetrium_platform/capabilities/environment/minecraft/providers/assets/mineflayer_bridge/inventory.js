'use strict'

const runtime = require('./runtime')

async function equipItem (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || ''), destination: String(msg.destination || 'hand') }
  const item = runtime.findInventoryItem(action.item)
  if (!item) return runtime.rejected('equip_item', action, 'ITEM_NOT_AVAILABLE')
  await activeBot.equip(item, action.destination)
  const equipped = action.destination === 'hand'
    ? activeBot.heldItem
    : activeBot.inventory.slots[activeBot.getEquipmentDestSlot(action.destination)]
  return equipped && equipped.name === action.item
    ? runtime.applied('equip_item', action, 'ITEM_EQUIPPED', { equipped: runtime.itemSummary(equipped) })
    : runtime.partial('equip_item', action, 'EQUIP_NOT_CONFIRMED')
}

async function consumeItem (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || '') }
  const item = runtime.findInventoryItem(action.item)
  if (!item) return runtime.rejected('consume_item', action, 'ITEM_NOT_AVAILABLE')
  const before = { count: runtime.inventoryCount(action.item), food: activeBot.food, health: activeBot.health }
  await activeBot.equip(item, 'hand')
  try {
    await activeBot.consume()
  } catch (_) {
    activeBot.activateItem()
    await runtime.sleep(1800)
    activeBot.deactivateItem()
  }
  await runtime.sleep(100)
  const after = { count: runtime.inventoryCount(action.item), food: activeBot.food, health: activeBot.health }
  const observed = after.count < before.count || after.food > before.food || after.health > before.health
  return observed
    ? runtime.applied('consume_item', action, 'ITEM_CONSUMED', { before, after })
    : runtime.rejected('consume_item', action, 'CONSUMPTION_NOT_OBSERVED', { before, after })
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
  await runtime.gotoPos(target.position, 2)
  await activeBot.lookAt(target.position.offset(0, 1.5, 0), true)
  await activeBot.toss(item.type, null, action.count)
  await runtime.sleep(250)
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

async function withContainer (maxDistance, callback) {
  const activeBot = runtime.getBot()
  await runtime.ensureMovements()
  const block = findContainerBlock(maxDistance)
  if (!block) return { missing: true, position: null, value: null }
  await runtime.gotoBlockInteraction(block.position)
  let container = null
  try {
    container = await activeBot.openContainer(activeBot.blockAt(block.position))
    return { missing: false, position: runtime.vec(block.position), value: await callback(container) }
  } finally {
    if (container) container.close()
  }
}

async function chestInspect (msg) {
  const action = { max_distance: Number(msg.max_distance || 32) }
  const opened = await withContainer(action.max_distance, async container => (
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
  const opened = await withContainer(action.max_distance, async container => {
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
  const opened = await withContainer(action.max_distance, async container => {
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
  give_item: giveItem
}
