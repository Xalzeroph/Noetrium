'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const runtime = require('./runtime')

test('an external interrupt resolves a cancellable physical wait before its deadline', async () => {
  const scope = runtime.createActionCancellationScope('agent-replan', 60000)
  const pending = runtime.runWithActionCancellationScope(
    scope,
    () => runtime.withTimeout(runtime.sleep(60000), 60000, 'MINECRAFT_ACTION')
  )
  await Promise.resolve()
  const started = performance.now()
  const cleanup = await scope.cancel('AGENT_REPLAN')
  assert.equal(cleanup.clean, true)
  await assert.rejects(pending, error =>
    error && error.code === 'ACTION_INTERRUPTED' && !error.cleanup_failed)
  assert.ok(performance.now() - started < 3000)
})

test('external preemption preserves failure when a physical handler cannot quiesce', async () => {
  const scope = runtime.createActionCancellationScope('blocked-provider', 100)
  const pending = runtime.runWithActionCancellationScope(
    scope,
    () => runtime.withTimeout(new Promise(() => {}), 60000, 'MINECRAFT_ACTION')
  )
  await Promise.resolve()
  await scope.cancel('AGENT_STOP')
  await assert.rejects(pending, error =>
    error && error.code === 'ACTION_INTERRUPTED' &&
    error.cleanup_failed === true &&
    error.cleanup_errors.includes('ACTION_CANCEL_DID_NOT_SETTLE'))
})

test('skill child progress derives from the same physical WAL callback', async () => {
  const scope = new runtime.ActionCancellationScope('composite-test')
  const events = []
  scope.onSkillChildTransition = (...args) => events.push(args)
  scope.recordChildEffect = async (_index, _name, _payload, execute) =>
    execute({ action_id: 'child', request_digest: 'a'.repeat(64) })
  const result = await runtime.runWithActionCancellationScope(scope, () =>
    runtime.runSkillChildEffect(2, 'collect_block', { block: 'oak_log' }, () =>
      ({ outcome: { status: 'applied' }, effect_disposition: 'applied' })))
  assert.equal(result.effect_disposition, 'applied')
  assert.deepEqual(events, [
    ['start', 2, 'collect_block'],
    ['finish', 2, 'collect_block', 'applied']
  ])
})

test('a child physical exception reports a fault, not fabricated completion', async () => {
  const scope = new runtime.ActionCancellationScope('composite-fault')
  const events = []
  scope.onSkillChildTransition = (...args) => events.push(args)
  scope.recordChildEffect = async (_index, _name, _payload, execute) => execute()
  await assert.rejects(runtime.runWithActionCancellationScope(scope, () =>
    runtime.runSkillChildEffect(0, 'craft_item', { item: 'stick' }, () => {
      throw new Error('physical-effect-unknown')
    })), /physical-effect-unknown/)
  assert.deepEqual(events, [
    ['start', 0, 'craft_item'],
    ['fault', 0, 'craft_item']
  ])
})
