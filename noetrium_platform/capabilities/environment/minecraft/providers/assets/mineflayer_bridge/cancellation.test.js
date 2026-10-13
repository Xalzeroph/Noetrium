'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const { EventEmitter } = require('node:events')
const runtime = require('./runtime')
const { Vec3 } = require('vec3')

test('action cancellation interrupts scope-owned sleep and runs cleanup', async () => {
  const scope = new runtime.ActionCancellationScope('sleep-cancel', 200)
  let cleaned = 0
  scope.onCancel('test-cleanup', () => { cleaned++ })
  const pending = runtime.runWithActionCancellationScope(scope, () => runtime.sleep(60000))
  const report = await scope.cancel('TEST_CANCEL')
  assert.equal(report.clean, true)
  assert.equal(cleaned, 1)
  await assert.rejects(pending, error => error && error.code === 'ACTION_CANCELLED')
})

test('independent cancellation cleanups start concurrently within one cleanup window', async () => {
  const scope = new runtime.ActionCancellationScope('parallel-cleanup', 200)
  const started = []
  const releases = []
  const cleanup = name => new Promise(resolve => {
    started.push(name)
    releases.push(resolve)
  })
  scope.onCancel('slow-a', () => cleanup('a'))
  scope.onCancel('slow-b', () => cleanup('b'))
  const pending = scope.cancel('TEST_PARALLEL_CANCEL')
  await new Promise(resolve => setImmediate(resolve))
  assert.deepEqual(new Set(started), new Set(['a', 'b']))
  for (const release of releases) release()
  const report = await pending
  assert.equal(report.clean, true)
})

test('action timeout proves original promise quiescence after cancellation', async () => {
  const scope = new runtime.ActionCancellationScope('cooperative-timeout', 200)
  let rejectOriginal
  const original = new Promise((resolve, reject) => { rejectOriginal = reject })
  scope.onCancel('settle-original', () => rejectOriginal(new Error('cancelled by cleanup')))
  await assert.rejects(
    runtime.runWithActionCancellationScope(
      scope,
      () => runtime.withTimeout(original, 5, 'COOPERATIVE')
    ),
    error => error && error.code === 'COOPERATIVE_TIMEOUT' && !error.cleanup_failed
  )
})

test('action timeout fails closed when provider work does not quiesce', async () => {
  const scope = new runtime.ActionCancellationScope('non-cooperative-timeout', 100)
  await assert.rejects(
    runtime.runWithActionCancellationScope(
      scope,
      () => runtime.withTimeout(new Promise(() => {}), 5, 'NON_COOPERATIVE')
    ),
    error => error &&
      error.code === 'NON_COOPERATIVE_TIMEOUT' &&
      error.cleanup_failed === true &&
      Array.isArray(error.cleanup_errors) &&
      error.cleanup_errors.includes('ACTION_CANCEL_DID_NOT_SETTLE')
  )
})

test('block navigation preserves the pathfinder-owned search policy', async () => {
  let observedRadius = null
  const fakeBot = {
    entity: { position: new Vec3(0, 64, 0) },
    world: {},
    pathfinder: {
      searchRadius: -1,
      movements: {},
      goto: async () => { observedRadius = fakeBot.pathfinder.searchRadius }
    }
  }
  runtime.bindBot(fakeBot)
  await runtime.gotoBlockInteraction(new Vec3(0, 4, 0), 1000)
  assert.equal(observedRadius, -1)
  assert.equal(fakeBot.pathfinder.searchRadius, -1)
  assert.equal(runtime.pathfinderSearchRadiusForDistance, undefined)
  assert.equal(runtime.withPathfinderSearchBudget, undefined)
})



test('child waits inherit one outer action deadline and may only tighten it', async () => {
  const scope = runtime.createActionCancellationScope('deadline-truth', 1000)
  await runtime.runWithActionCancellationScope(scope, async () => {
    const outer = runtime.actionRemainingMs()
    const tighter = runtime.actionRemainingMs(100)
    assert.ok(outer > 100)
    assert.ok(tighter > 0 && tighter <= 100)
    await runtime.sleep(5)
    const later = runtime.actionRemainingMs()
    assert.ok(later > 0)
    assert.ok(later <= outer)
  })
})


test('physics observation barrier obeys the provider-local liveness window', async () => {
  const fakeBot = new EventEmitter()
  fakeBot.entity = { position: new Vec3(0, 64, 0) }
  runtime.bindBot(fakeBot)
  const scope = runtime.createActionCancellationScope('physics-provider-window', 1000)
  const started = Date.now()
  await assert.rejects(
    runtime.runWithActionCancellationScope(
      scope,
      () => runtime.waitForPhysicsTicks(1, 20)
    ),
    error => error && error.code === 'ACTION_PROVIDER_WINDOW_EXCEEDED'
  )
  assert.ok(Date.now() - started < 500)
})
