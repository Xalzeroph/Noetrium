'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const mcData = require('minecraft-data')('1.21.1')
const Item = require('prismarine-item')(mcData)
const runtime = require('./runtime')
const { craft_grid, validateGrid } = require('./craft_grid')

// A deterministic physicsTick in the unit test represents the single real
// server-tick synchronization boundary; production uses runtime's timed Scope.
runtime.waitForPhysicsTicks = async () => 1

function makeBot ({ emitActualServerOutput }) {
  const items = { oak_log: 1 }
  const window = {
    id: 0,
    inventoryStart: 9,
    inventoryEnd: 45,
    selectedItem: null,
    slots: Array.from({ length: 46 }, () => null),
    findInventoryItem (id) {
      const found = Object.entries(items).find(([name, count]) =>
        count > 0 && mcData.itemsByName[name].id === id
      )
      return found ? { name: found[0], type: id, slot: 10 } : null
    },
    items () {
      return Object.entries(items).filter(([,count]) => count > 0)
        .map(([name,count]) => ({ name, count }))
    }
  }
  const bot = {
    registry: mcData,
    entity: {
      position: {
        x: 1, y: 65, z: 1,
        distanceTo () { return 0 },
        clone () { return { x:1, y:65, z:1, distanceTo () { return 0 } } }
      }
    },
    inventory: window,
    _client: new EventEmitter(),
    async clickWindow (slot, button) {
      if (slot === 10) {
        window.selectedItem = { name: 'oak_log', count: items.oak_log }
      } else if (slot >= 1 && slot <= 4 && button === 1) {
        window.slots[slot] = { name: 'oak_log', count: 1 }
        items.oak_log -= 1
        window.selectedItem = null
        // Test even a forged optimistic local result cannot prove physical output.
        window.slots[0] = { name: 'oak_planks', count: 4 }
        if (emitActualServerOutput) {
          bot._client.emit('packet', {
            windowId: 0, slot: 0,
            item: Item.toNotch(new Item(mcData.itemsByName.oak_planks.id, 4))
          }, { name: 'set_slot' })
        }
      }
    },
    async putAway (slot) {
      if (slot === 0 && window.slots[0]) {
        items.oak_planks = 4
        window.slots[0] = null
        window.slots[1] = null
      } else if (window.slots[slot]) {
        items[window.slots[slot].name] = (items[window.slots[slot].name] || 0) + 1
        window.slots[slot] = null
      }
    },
    async putSelectedItemRange () { window.selectedItem = null }
  }
  runtime.bindBot(bot)
  return { bot, items }
}

test('custom grid preconditions reject unowned ingredients and unknown items before effects', async () => {
  makeBot({ emitActualServerOutput: false })
  assert.deepEqual(validateGrid(runtime.getBot(), 'oak_log,_,_,_', 'inventory').wanted, { oak_log: 1 })
  assert.equal(validateGrid(runtime.getBot(), 'diamond,_,_,_', 'inventory').error, 'MISSING_GRID_INGREDIENTS')
  assert.equal(validateGrid(runtime.getBot(), 'unknown_block,_,_,_', 'inventory').error, 'UNKNOWN_ITEM')
  assert.equal(validateGrid(runtime.getBot(), '_,_,_,_', 'inventory').error, 'EMPTY_CRAFT_GRID')
  const result = await craft_grid({ grid: 'diamond,_,_,_', station: 'inventory' })
  assert.equal(result.outcome.code, 'MISSING_GRID_INGREDIENTS')
  assert.equal(result.effect_disposition, 'rejected')
})

test('local optimistic output without server slot packet must not count as crafted', async () => {
  const { items } = makeBot({ emitActualServerOutput: false })
  const result = await craft_grid({ grid: 'oak_log,_,_,_', station: 'inventory' })
  assert.notEqual(result.outcome.code, 'SERVER_RECIPE_CRAFTED')
  assert.equal(result.outcome.code, 'CRAFT_GRID_RESULT_UNCONFIRMED')
  assert.equal(result.effect_disposition, 'unknown')
  assert.equal(items.oak_log, 1)
  assert.equal(items.oak_planks || 0, 0)
})

test('only server slot evidence plus actual inventory gain proves a custom recipe', async () => {
  const { items } = makeBot({ emitActualServerOutput: true })
  const result = await craft_grid({ grid: 'oak_log,_,_,_', station: 'inventory' })
  assert.equal(result.outcome.code, 'SERVER_RECIPE_CRAFTED')
  assert.equal(result.outcome.produced_items.oak_planks, 4)
  assert.equal(result.outcome.server_output_packet.name, 'oak_planks')
  assert.equal(items.oak_planks, 4)
  assert.equal(items.oak_log, 0)
})

test('an already occupied grid is rejected without stealing unknown prior materials', async () => {
  const { bot, items } = makeBot({ emitActualServerOutput: true })
  bot.inventory.slots[1] = { name: 'stick', count: 1 }
  const result = await craft_grid({ grid: 'oak_log,_,_,_', station: 'inventory' })
  assert.equal(result.outcome.code, 'CRAFT_GRID_NOT_EMPTY')
  assert.equal(result.effect_disposition, 'rejected')
  assert.equal(items.oak_log, 1)
  assert.deepEqual(result.outcome.occupied_slots, [1])
})
