'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { Vec3 } = require('vec3')
const frontier = require('./world_frontier')

function fakeBot () {
  const columns = []
  for (let x = -2; x <= 2; x += 1) {
    for (let z = -2; z <= 2; z += 1) columns.push({ chunkX: x, chunkZ: z, column: {} })
  }
  return {
    entity: { position: new Vec3(8, 64, 8) },
    world: { getColumns: () => columns }
  }
}

test('frontier observation is deterministic, side-effect-free and non-oracular', () => {
  const left = fakeBot()
  const right = fakeBot()
  const start = left.entity.position.clone()
  const one = frontier.observeWorldFrontiers(left, 48)
  const two = frontier.observeWorldFrontiers(right, 48)
  assert.deepEqual(one, two)
  assert.equal(one.truth_class, 'observed')
  assert.equal(one.authoritative_for_unloaded_world, false)
  assert.ok(one.candidates.length > 0)
  assert.ok(one.candidates.every(row => row.path_reachable === null))
  assert.equal(left.entity.position.equals(start), true)
})

test('world frontiers report all loaded boundaries without selecting an agent destination', () => {
  const bot = {
    entity: { position: new Vec3(8, 64, 8) },
    world: {
      getColumns: () => [
        { chunkX: 0, chunkZ: 0 }, { chunkX: 1, chunkZ: 0 },
        { chunkX: 2, chunkZ: 0 }, { chunkX: 0, chunkZ: 1 },
        { chunkX: 0, chunkZ: 2 }
      ]
    }
  }
  const facts = frontier.observeWorldFrontiers(bot, 128)
  assert.equal(facts.candidates.length, 5)
  const row = facts.candidates.find(item => item.chunk_x === 0 && item.chunk_z === 1)
  assert.equal(row.adjacent_columns_not_loaded, 2)
  assert.equal(facts.candidates.some(item => 'selected' in item), false)
})

test('frontier observation does not invent coverage when world is unavailable', () => {
  const facts = frontier.observeWorldFrontiers({ entity: { position: new Vec3(0, 64, 0) } }, 64)
  assert.equal(facts.status, 'no_loaded_columns')
  assert.deepEqual(facts.candidates, [])
})

test('loaded-world coverage radius encloses every loaded column', () => {
  const bot = fakeBot()
  const radius = frontier.loadedWorldCoverageRadius(bot)
  assert.ok(Number.isFinite(radius))
  const edge = frontier.MINECRAFT_CHUNK_EDGE
  for (const column of bot.world.getColumns()) {
    const minX = column.chunkX * edge
    const minZ = column.chunkZ * edge
    for (const x of [minX, minX + edge]) {
      for (const z of [minZ, minZ + edge]) {
        const dx = x - bot.entity.position.x
        const dz = z - bot.entity.position.z
        assert.ok(Math.sqrt(dx * dx + dz * dz) <= radius + Number.EPSILON)
      }
    }
  }
})

test('coverage reduction ignores duplicate/invalid columns without sorting or reallocating', () => {
  const bot = fakeBot()
  const baseline = frontier.loadedWorldCoverageRadius(bot)
  const input = bot.world.getColumns()
  bot.world.getColumns = () => [
    ...input,
    ...input,
    { chunkX: NaN, chunkZ: 0 },
    { chunkX: 'bad', chunkZ: 0 },
    { chunkX: 0.25, chunkZ: 0 }
  ]
  assert.equal(frontier.loadedWorldCoverageRadius(bot), baseline)
  assert.equal(frontier.observeWorldFrontiers(bot, 48).loaded_column_count, input.length)
})

test('frontier indexing preserves canonical evidence when source columns are unordered and duplicated', () => {
  const bot = fakeBot()
  const original = bot.world.getColumns()
  const expected = frontier.observeWorldFrontiers(bot, 96)
  bot.world.getColumns = () => [
    ...original.slice().reverse(),
    ...original,
    { chunkX: 'not-a-column', chunkZ: 0 },
    { chunkX: 0.25, chunkZ: 0 }
  ]
  const observed = frontier.observeWorldFrontiers(bot, 96)
  assert.deepEqual(observed, expected)
  const sorted = frontier.loadedColumns(bot)
  assert.equal(sorted.length, original.length)
  assert.deepEqual(sorted[0], { chunkX: -2, chunkZ: -2 })
  assert.deepEqual(sorted[sorted.length - 1], { chunkX: 2, chunkZ: 2 })
})
