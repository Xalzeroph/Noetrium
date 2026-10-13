'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { Vec3 } = require('vec3')
const { verticalColumnObservation } = require('./world_column')

// Independent exhaustive oracle: always visit the complete legal dimension.
function exhaustive (bot) {
  const originY = Math.floor(bot.entity.position.y)
  const minY = bot.game.minY
  const maxY = minY + bot.game.height
  let aboveOne = null
  let aboveTwo = null
  let surface = null
  let obstruction = null
  for (let y = maxY - 1; y >= minY; y--) {
    const block = bot.blockAt(new Vec3(4, y, 9))
    const physical = Boolean(block && block.name && block.boundingBox !== 'empty')
    const air = item => item && ['air', 'cave_air', 'void_air'].includes(item.name)
    if (surface === null && physical && air(aboveOne) && air(aboveTwo)) {
      surface = {
        block: block.name,
        block_y: y,
        standing_position: { x: 4.5, y: y + 1, z: 9.5 }
      }
    }
    if (physical && y >= originY + 2) {
      obstruction = { name: block.name, blocks_up: y - originY - 2 }
    }
    aboveTwo = aboveOne
    aboveOne = block
  }
  return {
    vertical_bounds: { min_y: minY, height: bot.game.height, max_y_exclusive: maxY },
    first_solid_above_head: obstruction,
    surface
  }
}

function world (occupied, counter, { minY = -64, height = 384, originY = 64 } = {}) {
  return {
    game: { minY, height },
    entity: { position: new Vec3(4.5, originY, 9.5) },
    blockAt: position => {
      counter.count++
      const name = occupied.get(position.y) || 'air'
      return { name, boundingBox: name === 'air' ? 'empty' : 'block' }
    }
  }
}

test('early stopping preserves exhaustive vertical truths across representative dimensions', () => {
  const cases = [
    [new Map([[63, 'grass_block']]), {}],
    [new Map([[61, 'dirt'], [66, 'oak_log'], [99, 'stone']]), {}],
    [new Map([[63, 'grass_block'], [67, 'stone']]), { minY: 0, height: 256 }],
    [new Map([[63, 'grass_block'], [66, 'stone'], [70, 'stone']]), { minY: -64, height: 384 }],
    [new Map([[30, 'stone']]), { minY: -64, height: 384, originY: 130 }],
    [new Map(), {}],
    [new Map([[100, 'stone'], [101, 'stone'], [102, 'stone']]), {}]
  ]
  for (const [blocks, spec] of cases) {
    const counter = { count: 0 }
    const bot = world(blocks, counter, spec)
    const expected = exhaustive(bot)
    counter.count = 0
    assert.deepEqual(verticalColumnObservation(bot), expected)
    assert.ok(counter.count <= bot.game.height)
  }
})

test('standable ground terminates without scanning unreachable bedrock levels', () => {
  const counter = { count: 0 }
  const bot = world(new Map([[63, 'grass_block']]), counter)
  const result = verticalColumnObservation(bot)
  assert.equal(result.surface.block, 'grass_block')
  assert.equal(result.surface.block_y, 63)
  assert.equal(result.first_solid_above_head, null)
  assert.equal(counter.count, 257)
  assert.ok(counter.count < bot.game.height)
})

test('absence of any observed standable surface conservatively scans whole dimension', () => {
  const counter = { count: 0 }
  const bot = world(new Map(), counter, { minY: 0, height: 128, originY: 64 })
  const result = verticalColumnObservation(bot)
  assert.equal(result.surface, null)
  assert.equal(counter.count, 128)
})
