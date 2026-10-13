'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const runtime = require('./runtime')

test('action evidence keeps command identity when an action argument is also named tool', () => {
  const result = runtime.applied(
    'collect_block',
    { block: 'cobblestone', count: 8, tool: 'iron_pickaxe' },
    'BLOCKS_COLLECTED'
  )

  assert.equal(result.action.tool, 'collect_block')
  assert.equal(result.action.requested_tool, 'iron_pickaxe')
  assert.equal(result.action.block, 'cobblestone')
  assert.equal(result.action.count, 8)
})

test('action evidence is unchanged for actions without a colliding tool argument', () => {
  const result = runtime.applied('craft_item', { item: 'stick', count: 4 }, 'ITEM_CRAFTED')

  assert.deepEqual(result.action, { item: 'stick', count: 4, tool: 'craft_item' })
})
