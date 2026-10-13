'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { Vec3 } = require('vec3')
const runtime = require('./runtime')

test('nearest entity is linear, stable on ties and respects all physical filters', () => {
  const bot = {
    entity: { id: 0, position: new Vec3(0, 64, 0) },
    entities: {
      2: { id: 2, name: 'cow', position: new Vec3(2, 64, 0) },
      3: { id: 3, name: 'cow', position: new Vec3(-2, 64, 0) },
      4: { id: 4, name: 'cow', position: new Vec3(1, 64, 0), isValid: false },
      5: { id: 5, name: 'pig', position: new Vec3(0.5, 64, 0) }
    }
  }
  runtime.bindBot(bot)
  assert.equal(runtime.findEntity('cow', 3).id, 2)
  assert.equal(runtime.findEntity('cow', 1), null)
  assert.equal(runtime.findEntity('cow', 3, row => row.id !== 2).id, 3)
  assert.equal(runtime.findEntity('pig', 2).id, 5)
  assert.equal(runtime.findEntity('wolf', 32), null)
})
