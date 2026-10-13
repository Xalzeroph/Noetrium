'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const runtime = require('./runtime')

test('static registry matcher is reused by identity and changes with new Minecraft registry', () => {
  let enumerations = 0
  const blocks = new Proxy({
    oak_log: { name: 'oak_log', id: 30 },
    birch_log: { name: 'birch_log', id: 31 },
    stone: { name: 'stone', id: 4 },
    air: { name: 'air', id: 0 }
  }, {
    ownKeys (target) {
      enumerations++
      return Reflect.ownKeys(target)
    }
  })
  const first = runtime.observedBlockRegistryIds(blocks, 'log')
  assert.deepEqual([...first], [30, 31])
  assert.equal(enumerations, 1)
  assert.throws(() => first.push(999), TypeError)
  const again = runtime.observedBlockRegistryIds(blocks, 'log')
  assert.strictEqual(first, again)
  assert.equal(enumerations, 1)
  assert.deepEqual([...runtime.observedBlockRegistryIds(blocks, '')], [30, 31, 4])
  assert.equal(enumerations, 2)
  const newVersion = { oak_log: { name: 'oak_log', id: 333 } }
  assert.deepEqual([...runtime.observedBlockRegistryIds(newVersion, 'log')], [333])
})

test('physical block positions are queried fresh on every call, not cached by static registry', () => {
  const staticRegistry = { oak_log: { name: 'oak_log', id: 30 } }
  let calls = 0
  const origin = { x: 0, y: 65, z: 0 }
  runtime.bindBot({
    registry: { blocksByName: staticRegistry },
    entity: { position: origin },
    findBlocks ({ matching, maxDistance, count }) {
      calls++
      assert.deepEqual([...matching], [30])
      assert.equal(maxDistance, 18)
      assert.equal(count, 4)
      const x = calls
      return [{
        x, y: 65, z: 1,
        distanceTo () { return x }
      }]
    },
    blockAt (position) {
      return {
        position, name: 'oak_log', metadata: 0,
        isWaterlogged: false
      }
    }
  })
  const before = runtime.observeBlocks('log', 18, 4)
  const after = runtime.observeBlocks('log', 18, 4)
  assert.equal(calls, 2)
  assert.equal(before.blocks[0].position.x, 1)
  assert.equal(after.blocks[0].position.x, 2)
  assert.equal(before.registry_match_count, 1)
  assert.equal(after.registry_match_count, 1)
  assert.equal(before.truth_class, 'observed')
  assert.equal(after.authoritative_for_current_world, true)
})

test('registry matcher cache remains bounded for long-lived multi-paper execution', () => {
  let enumerations = 0
  const blocks = new Proxy({ stone: { name: 'stone', id: 4 } }, {
    ownKeys (target) { enumerations++; return Reflect.ownKeys(target) }
  })
  for (let n = 0; n < 150; n++) {
    runtime.observedBlockRegistryIds(blocks, 'nomatch_' + n)
  }
  const count = enumerations
  runtime.observedBlockRegistryIds(blocks, 'nomatch_149')
  assert.equal(enumerations, count)
  runtime.observedBlockRegistryIds(blocks, 'nomatch_0')
  assert.equal(enumerations, count + 1)
})


test('unfiltered sensing samples diverse physical blocks instead of only nearest soil', () => {
  const positions = Array.from({ length: 13 }, (_, n) => ({
    x: n + 1, y: 65, z: 0,
    distanceTo () { return n + 1 }
  }))
  const calls = []
  runtime.bindBot({
    registry: { blocksByName: {
      grass_block: { name: 'grass_block', id: 1 },
      oak_log: { name: 'oak_log', id: 2 }
    } },
    entity: { position: { x: 0, y: 65, z: 0 } },
    findBlocks ({ matching, count }) {
      calls.push({ matching: [...matching], count })
      return matching.length === 1 ? [positions[12]] : positions.slice(0, count)
    },
    blockAt (position) {
      return {
        position,
        name: position.x === 13 ? 'oak_log' : 'grass_block',
        metadata: 0, isWaterlogged: false
      }
    }
  })
  const result = runtime.observeBlocks(null, 16, 4)
  assert.equal(calls[0].count, 64)
  assert.equal(result.candidate_count, 13)
  assert.equal(result.observed_count, 4)
  assert.equal(result.sampling, 'nearest-per-observed-type')
  assert.equal(result.counts.oak_log, 1)
  assert.deepEqual(result.blocks.map(row => row.name), [
    'grass_block', 'oak_log', 'grass_block', 'grass_block'
  ])
  const filtered = runtime.observeBlocks('oak_log', 16, 4)
  assert.equal(calls[1].count, 4)
  assert.equal(filtered.sampling, 'closest')
  assert.deepEqual(filtered.blocks.map(row => row.name), ['oak_log'])
})
