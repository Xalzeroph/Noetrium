'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const { Vec3 } = require('vec3')
const runtime = require('./runtime')

function fixture () {
  const bot = new EventEmitter()
  let scans = 0
  bot.entity = { position: new Vec3(0, 64, 0) }
  bot.game = { dimension: 'overworld' }
  bot.registry = { blocksByName: { stone: { id: 1, name: 'stone' } } }
  bot.findBlocks = () => { scans += 1; return [new Vec3(1, 63, 0)] }
  bot.blockAt = position => ({ name: 'stone', position, metadata: 0, isWaterlogged: false })
  return { bot, scans: () => scans }
}

test('default nearby projection reuses one world scan until local evidence changes', () => {
  const { bot, scans } = fixture()
  runtime.bindBot(bot)
  runtime.defaultNearbyBlocksProjection(16, 12)
  runtime.defaultNearbyBlocksProjection(16, 12)
  assert.equal(scans(), 1)
  bot.entity.position = new Vec3(1, 64, 0)
  runtime.defaultNearbyBlocksProjection(16, 12)
  assert.equal(scans(), 2)
  bot.emit('blockUpdate', { position: new Vec3(2, 64, 0) }, { position: new Vec3(2, 64, 0) })
  runtime.defaultNearbyBlocksProjection(16, 12)
  assert.equal(scans(), 3)
})

test('distant block updates preserve local cache and explicit observation remains live', () => {
  const { bot, scans } = fixture()
  runtime.bindBot(bot)
  runtime.defaultNearbyBlocksProjection(16, 12)
  bot.emit('blockUpdate', { position: new Vec3(100, 64, 100) }, { position: new Vec3(100, 64, 100) })
  runtime.defaultNearbyBlocksProjection(16, 12)
  assert.equal(scans(), 1)
  runtime.observeBlocks(null, 16, 12)
  runtime.observeBlocks(null, 16, 12)
  assert.equal(scans(), 3)
})


test('exact block inspection is one O(1) loaded-world read and never invokes findBlocks', () => {
  const { bot, scans } = fixture()
  runtime.bindBot(bot)
  const result = runtime.observeExactBlock(new Vec3(1, 63, 0), 16)
  assert.equal(result.observed, true)
  assert.equal(result.block.name, 'stone')
  assert.deepEqual(result.exact_position, { x: 1, y: 63, z: 0 })
  assert.equal(scans(), 0)
})

test('exact block inspection reports out-of-range or unloaded coordinates without loading/search', () => {
  const { bot, scans } = fixture()
  runtime.bindBot(bot)
  const far = runtime.observeExactBlock(new Vec3(100, 64, 0), 16)
  assert.equal(far.observed, false)
  assert.equal(far.observation_constraint, 'out_of_range')
  bot.blockAt = () => null
  const unloaded = runtime.observeExactBlock(new Vec3(1, 64, 0), 16)
  assert.equal(unloaded.observed, false)
  assert.equal(unloaded.observation_constraint, 'not_loaded_or_unobserved')
  assert.equal(scans(), 0)
})
