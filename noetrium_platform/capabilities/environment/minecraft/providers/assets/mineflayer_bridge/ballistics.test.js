'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')
const { Vec3 } = require('vec3')
const ballistics = require('./ballistics')

function botFixture () {
  return {
    entity: {
      position: new Vec3(0, 64, 0),
      velocity: new Vec3(0, 0, 0),
      eyeHeight: 1.62,
      onGround: true
    },
    game: { minY: -64 },
    world: { raycast: () => null }
  }
}

test('bow charge timing is expressed in game ticks, not wall-clock guesses', () => {
  assert.equal(ballistics.chargeTicks({ name: 'bow', enchants: [] }), 20)
  assert.equal(ballistics.chargeTicks({
    name: 'crossbow',
    enchants: [{ name: 'quick_charge', lvl: 3 }]
  }), 10)
})

test('discrete drag solver finds a clear static-target bow trajectory', () => {
  const bot = botFixture()
  const target = {
    position: new Vec3(20, 64, 0),
    velocity: new Vec3(0, 0, 0),
    width: 0.6,
    height: 1.8
  }
  const shot = ballistics.solveArrowShot(bot, target, { name: 'bow' })
  assert.ok(shot)
  assert.notEqual(shot.hit, false)
  assert.ok(Number.isFinite(shot.yaw))
  assert.ok(Number.isFinite(shot.pitch))
  assert.ok(shot.flight_ticks > 0)
})

test('discrete drag solver leads a moving target and rejects blocked trajectories', () => {
  const bot = botFixture()
  const target = {
    position: new Vec3(18, 64, 0),
    velocity: new Vec3(0, 0, 0.08),
    width: 0.6,
    height: 1.8
  }
  const moving = ballistics.solveArrowShot(bot, target, { name: 'bow' })
  assert.ok(moving)
  assert.notEqual(moving.hit, false)
  assert.ok(Math.abs(moving.target_velocity.z - 0.08) < Number.EPSILON)

  bot.world.raycast = (start, direction, distance) => ({
    intersect: start.plus(direction.scaled(Math.min(distance, 1)))
  })
  const blocked = ballistics.solveArrowShot(bot, target, { name: 'bow' })
  assert.ok(blocked)
  assert.equal(blocked.hit, false)
})
