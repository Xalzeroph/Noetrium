'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const mcData = require('minecraft-data')('1.21.1')
const { Vec3 } = require('vec3')
const { goals: { GoalGetToBlock } } = require('mineflayer-pathfinder')
const runtime = require('./runtime')

function fakeBot ({ pathProbe, blockAt, activateBlock }) {
  const originalMovements = { name: 'standard-existing' }
  const bot = {
    registry: mcData,
    inventory: { items: () => [] },
    entities: {},
    entity: {
      position: new Vec3(0, 64, 0),
      effects: {},
      onGround: true
    },
    blockAt: blockAt || (() => null),
    activateBlock: activateBlock || (async () => {}),
    pathfinder: {
      movements: originalMovements,
      getPathTo: (candidate, goal) => pathProbe(candidate, goal),
      setMovements: candidate => { bot.pathfinder.movements = candidate },
      goto: async () => {
        bot._movementsAtGoto = bot.pathfinder.movements
      },
      stop: () => {}
    },
    stopDigging: () => {},
    clearControlStates: () => {}
  }
  return { bot, originalMovements }
}

test('navigation executes one non-destructive native path without duplicate probes', async () => {
  let probeCount = 0
  let gotoCount = 0
  const { bot, originalMovements } = fakeBot({
    pathProbe: () => { probeCount++; return { status: 'success' } }
  })
  bot.pathfinder.goto = async () => {
    gotoCount++
    assert.equal(bot.pathfinder.movements.canDig, false)
    assert.equal(bot.pathfinder.movements.canOpenDoors, false)
    assert.equal(bot.pathfinder.movements.allow1by1towers, false)
  }
  runtime.bindBot(bot)

  const outcome = await runtime.navigateGoal({}, 1000, 'TEST_NAVIGATION')

  assert.equal(probeCount, 0)
  assert.equal(gotoCount, 1)
  assert.equal(outcome.navigation_mode, 'single_non_destructive_pathfinder')
  assert.ok(outcome.pathfinder_elapsed_ms >= 0)
  assert.equal(bot.pathfinder.movements, originalMovements)
  assert.equal(Object.hasOwn(originalMovements, 'canDig'), false)
  assert.equal(Object.hasOwn(originalMovements, 'canOpenDoors'), false)
  assert.equal(Object.hasOwn(originalMovements, 'allow1by1towers'), false)
})

test('block interaction skips A* when upstream GoalLookAtBlock already accepts the live node', async () => {
  let gotoCount = 0
  const target = new Vec3(-22, 104, 15)
  const { bot, originalMovements } = fakeBot({ pathProbe: () => ({ status: 'success' }) })
  bot.entity.position = new Vec3(-23.5, 104, 16.51825718835813)
  bot.world = { raycast: () => ({ position: target.clone(), face: 2 }) }
  bot.pathfinder.goto = async () => { gotoCount++ }
  runtime.bindBot(bot)

  const outcome = await runtime.gotoBlockInteraction(target, 1000)

  assert.equal(gotoCount, 0)
  assert.equal(outcome.navigation_mode, 'already_satisfied')
  assert.equal(outcome.pathfinder_elapsed_ms, 0)
  assert.equal(outcome.pathfinder_evidence.path_update_count, 0)
  assert.ok(outcome.distance < 3)
  assert.equal(bot.pathfinder.movements, originalMovements)
})

test('navigation cannot implicitly activate doors even after pathfinder failure', async () => {
  let activations = 0
  let gotoCount = 0
  const door = { name: 'oak_door', position: new Vec3(0, 64, 0) }
  const { bot } = fakeBot({
    pathProbe: () => { throw new Error('duplicate preflight probe') },
    blockAt: () => door,
    activateBlock: async () => { activations++ }
  })
  bot.pathfinder.goto = async () => {
    gotoCount++
    throw new Error('NoPath')
  }
  runtime.bindBot(bot)

  await assert.rejects(
    runtime.navigateGoal({}, 1000, 'TEST_PASSAGE_RECOVERY'),
    /NoPath/
  )
  assert.equal(gotoCount, 1)
  assert.equal(activations, 0)
})


test('navigation records pathfinder runtime event truth without owning scheduling policy', async () => {
  const originalMovements = { name: 'standard-existing' }
  const bot = Object.assign(new EventEmitter(), {
    registry: mcData,
    inventory: { items: () => [] },
    entities: {},
    entity: {
      position: new Vec3(0, 64, 0),
      effects: {},
      onGround: true
    },
    blockAt: () => null,
    activateBlock: async () => {},
    stopDigging: () => {},
    clearControlStates: () => {}
  })
  bot.pathfinder = {
    movements: originalMovements,
    getPathTo: () => ({ status: 'success', path: [{}] }),
    setMovements: candidate => { bot.pathfinder.movements = candidate },
    goto: async () => {
      bot.emit('path_update', { status: 'partial', path: [{}] })
      bot.emit('path_reset', 'block_updated')
      bot.emit('path_update', { status: 'success', path: [{}] })
      bot.emit('goal_reached', {})
    },
    stop: () => {}
  }
  runtime.bindBot(bot)

  const outcome = await runtime.navigateGoal({}, 1000, 'TEST_PATHFINDER_EVENTS')

  assert.equal(outcome.pathfinder_evidence.path_update_count, 2)
  assert.deepEqual(outcome.pathfinder_evidence.path_status_counts, {
    partial: 1,
    success: 1
  })
  assert.equal(outcome.pathfinder_evidence.path_reset_count, 1)
  assert.deepEqual(outcome.pathfinder_evidence.path_reset_reasons, {
    block_updated: 1
  })
  assert.equal(outcome.pathfinder_evidence.goal_reached_count, 1)
  assert.equal(outcome.pathfinder_evidence.path_stop_count, 0)
})


test('multi-target block goal exactly matches upstream GoalGetToBlock terminals', () => {
  const targets = [
    new Vec3(10, 64, 10),
    new Vec3(-3, 20, 5),
    new Vec3(0, -40, 0)
  ]
  const multi = new runtime.GoalAnyGetToBlock(targets)
  for (const target of targets) {
    for (let dx = -3; dx <= 3; dx += 1) {
      for (let dy = -3; dy <= 3; dy += 1) {
        for (let dz = -3; dz <= 3; dz += 1) {
          const node = target.offset(dx, dy, dz)
          const anyExpected = targets.some(candidate => (
            new GoalGetToBlock(candidate.x, candidate.y, candidate.z).isEnd(node)
          ))
          assert.equal(
            multi.isEnd(node),
            anyExpected,
            'terminal mismatch at ' + String(node)
          )
        }
      }
    }
  }
})

test('multi-target block goal heuristic is zero exactly at terminal states', () => {
  const targets = [
    new Vec3(4, 64, 0),
    new Vec3(40, 70, 40)
  ]
  const multi = new runtime.GoalAnyGetToBlock(targets)
  const terminal = new Vec3(3, 64, 0)
  const remote = new Vec3(0, 64, 0)
  assert.equal(multi.isEnd(terminal), true)
  assert.equal(multi.heuristic(terminal), 0)
  assert.ok(multi.heuristic(remote) > 0)
})
