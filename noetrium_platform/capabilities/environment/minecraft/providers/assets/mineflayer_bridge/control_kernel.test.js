'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { ActionControlStatechart, MinecraftBotActor } = require('./control_kernel')

const deferred = () => {
  let resolve, reject
  const promise = new Promise((yes, no) => { resolve = yes; reject = no })
  return { promise, resolve, reject }
}

test('control statechart is deterministic and rejects impossible transitions', () => {
  const chart = new ActionControlStatechart('a')
  chart.transition('start')
  chart.transition('interrupt', 'AGENT_CHANGED_GOAL')
  chart.transition('settle')
  chart.transition('finish', 'unknown')
  assert.deepEqual(chart.snapshot(), {
    state: 'settled', reason: 'AGENT_CHANGED_GOAL', effect_disposition: 'unknown', transitions: 4,
    max_child_depth: 0,
    active_child: null, completed_child_attempts: 0, last_child: null
  })
  assert.throws(() => chart.transition('start'), /INVALID_TRANSITION/)
})

test('one bot actor never overlaps commands; failure cannot poison later work', async () => {
  const actor = new MinecraftBotActor()
  const gate = deferred()
  let concurrent = 0
  let maximum = 0
  const run = async (id, waiting = null) => {
    concurrent++
    maximum = Math.max(maximum, concurrent)
    try {
      if (waiting) await waiting.promise
      if (id === 'bad') throw new Error('expected physical failure')
      return id
    } finally { concurrent-- }
  }
  const first = actor.dispatch('goto', () => run('one', gate), { actionId: 'a', digest: 'a'.repeat(64) })
  const second = actor.dispatch('snapshot', () => run('bad'))
  const third = actor.dispatch('craft', () => run('three'), { actionId: 'b', digest: 'b'.repeat(64) })
  gate.resolve()
  assert.equal(await first, 'one')
  await assert.rejects(second, /expected physical failure/)
  assert.equal(await third, 'three')
  assert.equal(maximum, 1)
  assert.equal(actor.status().outstanding, 0)
})

test('sideband interrupt stops a running action without claiming physical success', async () => {
  const actor = new MinecraftBotActor()
  const gate = deferred()
  const id = 'live'
  const digest = 'e'.repeat(64)
  const running = actor.dispatch('collect_block', async () => {
    const scope = {
      cancel: reason => { gate.reject(new Error(String(reason))); return Promise.resolve({ clean: true }) }
    }
    actor.attachScope(id, digest, scope)
    await gate.promise
  }, { actionId: id, digest })
  // Dispatch starts at the microtask boundary.
  await Promise.resolve()
  const denied = actor.interrupt(id, 'f'.repeat(64), 'wrong')
  assert.equal(denied.accepted, false)
  const interrupted = actor.interrupt(id, digest, 'AGENT_REPLAN')
  assert.equal(interrupted.accepted, true)
  assert.equal(interrupted.state, 'stopping')
  await assert.rejects(running, /AGENT_REPLAN/)
  assert.equal(actor.status().active, null)
})

test('queued cancellation never executes its world-mutating handler', async () => {
  const actor = new MinecraftBotActor()
  const gate = deferred()
  const blocker = actor.dispatch('wait', () => gate.promise)
  let called = false
  const queued = actor.dispatch('attack_entity', () => { called = true }, {
    actionId: 'later', digest: 'b'.repeat(64)
  })
  const request = actor.interrupt('later', 'b'.repeat(64), 'NO_LONGER_NEEDED')
  assert.equal(request.accepted, true)
  assert.equal(request.state, 'stopped')
  gate.resolve()
  await blocker
  await assert.rejects(queued, /ACTION_INTERRUPTED_BEFORE_DISPATCH/)
  assert.equal(called, false)
})

test('reconciled disposition is separate from control completion', async () => {
  const actor = new MinecraftBotActor()
  const id = 'physical'
  const digest = 'c'.repeat(64)
  const state = await actor.dispatch('mine', async () => {
    actor.recordResult(id, digest, 'applied')
    return 'done'
  }, { actionId: id, digest })
  assert.equal(state, 'done')
  assert.equal(actor.status().outstanding, 0)
  assert.throws(() => actor.recordResult(id, digest, 'applied'), /MISMATCH/)
})

test('final execution control is one settled receipt with identical effect disposition', async () => {
  const actor = new MinecraftBotActor()
  const id = 'unit-feedback'
  const digest = 'f'.repeat(64)
  const outcome = await actor.dispatch('collect_block', () => {
    return actor.recordResult(id, digest, 'applied')
  }, {actionId: id, digest})
  assert.equal(outcome.state, 'settled')
  assert.equal(outcome.effect_disposition, 'applied')
  assert.equal(outcome.transitions, 3)
})


test('nested skill child transitions retain one hierarchical control statechart', async () => {
  const actor = new MinecraftBotActor()
  const id = 'composite'
  const digest = '7'.repeat(64)
  const outcome = await actor.dispatch('excavate_region', async () => {
    actor.childTransition(id, digest, 'start', 0, 'craft_item')
    actor.childTransition(id, digest, 'start', 0, 'place_block')
    const active = actor.status().active
    assert.equal(active.active_child.action_type, 'place_block')
    assert.equal(active.active_child.depth, 2)
    actor.childTransition(id, digest, 'finish', 0, 'place_block', 'applied')
    actor.childTransition(id, digest, 'finish', 0, 'craft_item', 'partial')
    return actor.recordResult(id, digest, 'applied')
  }, { actionId: id, digest, maxChildDepth: 2 })
  assert.equal(outcome.state, 'settled')
  assert.equal(outcome.max_child_depth, 2)
  assert.equal(outcome.completed_child_attempts, 2)
  assert.equal(outcome.last_child.action_type, 'craft_item')
  assert.equal(outcome.last_child.outcome, 'partial')
  assert.equal(outcome.active_child, null)
})

test('hierarchical child completion with mismatched identity fails closed', () => {
  const chart = new ActionControlStatechart('a', 1)
  chart.transition('start')
  chart.childTransition('start', 3, 'craft_item')
  assert.throws(() => chart.childTransition('finish', 2, 'craft_item'), /NESTING_MISMATCH/)
})

test('authorized Unit child depth is the structural nesting bound', () => {
  const chart = new ActionControlStatechart('bounded-by-authority', 1)
  chart.transition('start')
  chart.childTransition('start', 0, 'craft_item')
  assert.throws(
    () => chart.childTransition('start', 0, 'place_block'),
    /CHILD_DEPTH_EXCEEDED/
  )
  assert.equal(chart.snapshot().active_child.action_type, 'craft_item')
  assert.equal(chart.snapshot().active_child.depth, 1)
  chart.childTransition('finish', 0, 'craft_item', 'applied')
  assert.equal(chart.snapshot().active_child, null)
})

test('out-of-order nested completion is rejected without corrupting active stack', async () => {
  const actor = new MinecraftBotActor()
  const id = 'nested-order'
  const digest = '8'.repeat(64)
  const result = await actor.dispatch('excavate_region', async () => {
    actor.childTransition(id, digest, 'start', 1, 'craft_item')
    actor.childTransition(id, digest, 'start', 2, 'place_block')
    assert.throws(
      () => actor.childTransition(id, digest, 'finish', 1, 'craft_item'),
      /NESTING_MISMATCH/
    )
    assert.equal(actor.status().active.active_child.action_type, 'place_block')
    actor.childTransition(id, digest, 'finish', 2, 'place_block')
    actor.childTransition(id, digest, 'finish', 1, 'craft_item')
    return actor.recordResult(id, digest, 'applied')
  }, { actionId: id, digest, maxChildDepth: 2 })
  assert.equal(result.completed_child_attempts, 2)
})

test('interrupt after physical reconciliation is refused, never rewrites terminal truth', async () => {
  const actor = new MinecraftBotActor()
  const id = 'terminal-race'
  const digest = '9'.repeat(64)
  let reconciled
  const result = await actor.dispatch('mine', async () => {
    reconciled = actor.recordResult(id, digest, 'applied')
    const late = actor.interrupt(id, digest, 'TOO_LATE')
    assert.equal(late.accepted, false)
    assert.equal(late.code, 'ACTION_CONTROL_ALREADY_TERMINAL')
    return reconciled
  }, { actionId: id, digest })
  assert.equal(result.effect_disposition, 'applied')
  assert.equal(result.reason, null)
})

test('an unclosed child effect makes terminal disposition unknown', async () => {
  const actor = new MinecraftBotActor()
  const id = 'open-child'
  const digest = 'a'.repeat(64)
  await actor.dispatch('excavate_region', async () => {
    actor.childTransition(id, digest, 'start', 0, 'craft_item')
    return 'handler-returned-with-open-effect'
  }, { actionId: id, digest, maxChildDepth: 1 })
  const result = actor.lastSettledSnapshot()
  assert.equal(result.state, 'settled')
  assert.equal(result.effect_disposition, 'unknown')
  assert.equal(result.active_child.action_type, 'craft_item')
  result.state = 'corrupted-by-caller'
  result.active_child.action_type = 'corrupted-child'
  const reread = actor.lastSettledSnapshot()
  assert.equal(reread.state, 'settled')
  assert.equal(reread.active_child.action_type, 'craft_item')
})

test('last settled snapshot is absent before any actor command', () => {
  const actor = new MinecraftBotActor()
  assert.equal(actor.lastSettledSnapshot(), null)
})
