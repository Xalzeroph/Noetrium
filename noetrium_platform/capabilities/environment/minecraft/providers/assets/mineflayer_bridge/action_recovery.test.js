'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')
const { ActionRecoveryJournal, replayActionResult } = require('./action_recovery')

const digest = 'a'.repeat(64)

test('durable journal makes an intent visible after process-local reconstruction', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-'))
  try {
    const first = new ActionRecoveryJournal()
    first.configure(root)
    assert.equal(first.durability, 'crash_durable')
    assert.equal(first.begin('action-1', digest, 'chat').execute, true)

    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    assert.deepEqual(restarted.reconcile('action-1', digest), {
      disposition: 'unknown', state: 'intent', durability: 'crash_durable', outcome: null
    })
    assert.equal(restarted.begin('action-1', digest, 'chat').execute, false)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})

test('prepared proof survives reconstruction as not_applied and begin atomically enters intent', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-'))
  try {
    const first = new ActionRecoveryJournal()
    first.configure(root)
    const prepared = first.prepare('action-prepared', digest, 'stay')
    assert.equal(prepared.created, true)
    assert.equal(prepared.record.state, 'prepared')
    assert.equal(prepared.record.disposition, 'not_applied')
    first.close()

    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    assert.deepEqual(restarted.reconcile('action-prepared', digest), {
      disposition: 'not_applied', state: 'prepared', durability: 'crash_durable', outcome: null
    })
    const begun = restarted.begin('action-prepared', digest, 'stay')
    assert.equal(begun.execute, true)
    assert.equal(begun.record.state, 'intent')
    assert.equal(begun.record.disposition, 'unknown')
    assert.equal(restarted.begin('action-prepared', digest, 'stay').execute, false)
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})

test('terminal applied proof survives reconstruction without re-execution', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-'))
  try {
    const first = new ActionRecoveryJournal()
    first.configure(root)
    first.begin('action-2', digest, 'wait')
    first.complete('action-2', digest, 'wait', {
      verified: true,
      effect_disposition: 'applied',
      outcome: { status: 'applied', code: 'WAIT_COMPLETED' }
    })

    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    const reconciled = restarted.reconcile('action-2', digest)
    assert.equal(reconciled.disposition, 'applied')
    assert.deepEqual(reconciled.outcome, { status: 'applied', code: 'WAIT_COMPLETED' })
    const duplicate = restarted.begin('action-2', digest, 'wait')
    assert.equal(duplicate.execute, false)
    assert.equal(duplicate.record.disposition, 'applied')
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})

test('absence is unknown and identity drift is rejected', () => {
  const journal = new ActionRecoveryJournal()
  journal.configure(null)
  assert.equal(journal.reconcile('missing', digest).disposition, 'unknown')
  journal.begin('action-3', digest, 'chat')
  assert.throws(() => journal.reconcile('action-3', 'b'.repeat(64)), /IDENTITY_DRIFT/)
})

test('terminal not_applied provider outcome survives reconstruction', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-'))
  try {
    const first = new ActionRecoveryJournal()
    first.configure(root)
    first.begin('action-4', digest, 'collect_block')
    first.complete('action-4', digest, 'collect_block', {
      verified: false,
      effect_disposition: 'not_applied',
      outcome: {
        status: 'rejected',
        code: 'COLLECTION_FAILED',
        errors: [{ phase: 'collectblock', name: 'NoPath', code: 'NoPath', message: 'No path to the goal!' }]
      }
    })

    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    const reconciled = restarted.reconcile('action-4', digest)
    assert.equal(reconciled.disposition, 'not_applied')
    assert.equal(reconciled.outcome.code, 'COLLECTION_FAILED')
    assert.equal(reconciled.outcome.errors[0].name, 'NoPath')
    assert.equal(reconciled.outcome.errors[0].message, 'No path to the goal!')
    const duplicate = restarted.begin('action-4', digest, 'collect_block')
    assert.equal(duplicate.execute, false)
    assert.equal(duplicate.record.outcome.errors[0].name, 'NoPath')
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})


test('trailing torn journal record is ignored after crash reconstruction', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-'))
  try {
    const first = new ActionRecoveryJournal()
    first.configure(root)
    first.begin('action-torn', digest, 'chat')
    first.close()

    fs.appendFileSync(path.join(root, 'actions.jsonl'), '{"schema":"minecraft-action-recovery-v1"')
    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    const reconciled = restarted.reconcile('action-torn', digest)
    assert.equal(reconciled.state, 'intent')
    assert.equal(reconciled.disposition, 'unknown')
    restarted.close()
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})


test('duplicate recovery never upgrades a partially fulfilled goal into verified success', () => {
  const record = {
    state: 'terminal',
    disposition: 'applied',
    verified: false,
    outcome: {status: 'partial', code: 'COLLECTION_GOAL_PARTIALLY_FULFILLED',
      collected_count: 1, requested_count: 4}
  }
  const replayed = replayActionResult('collect_block', record)
  assert.equal(replayed.effect_disposition, 'applied')
  assert.equal(replayed.outcome.status, 'partial')
  assert.equal(replayed.outcome.collected_count, 1)
  assert.equal(replayed.outcome.requested_count, 4)
  assert.equal(replayed.verified, false)
  assert.equal(replayed.outcome.prior_outcome_not_current_world_truth, true)

  const unknown = replayActionResult('excavate_region',
    {state: 'intent', disposition: 'unknown'})
  assert.equal(unknown.outcome.status, 'partial')
  assert.equal(unknown.effect_disposition, 'unknown')
  assert.equal(unknown.verified, false)
})

test('torn journal tail is removed before the next durable append', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-'))
  try {
    const journal = new ActionRecoveryJournal()
    journal.configure(root)
    journal.begin('action-1', digest, 'chat')
    journal.close()
    fs.appendFileSync(path.join(root, 'actions.jsonl'), '{"broken":"partial"')
    const restart = new ActionRecoveryJournal()
    restart.configure(root)
    restart.begin('action-2', digest, 'wait')
    restart.close()
    const proof = new ActionRecoveryJournal()
    proof.configure(root)
    assert.equal(proof.reconcile('action-1', digest).state, 'intent')
    assert.equal(proof.reconcile('action-2', digest).state, 'intent')
    proof.close()
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})

test('parent child reconciliation is indexed by exact child identities', () => {
  const journal = new ActionRecoveryJournal()
  journal.configure(null)
  for (let i = 0; i < 48; i++) {
    const action = 'irrelevant-' + i
    journal.begin(action, digest, 'wait')
  }
  const parentLineage = {
    action_id: 'parent', request_digest: 'b'.repeat(64),
    root_invocation_unit_digest: 'c'.repeat(64),
    authorization_unit_digest: 'd'.repeat(64)
  }
  journal.begin('child-4', digest, 'craft_item', {
    ...parentLineage, child_index: 4, action_spec_unit_digest: 'e'.repeat(64)
  })
  journal.begin('child-2', digest, 'collect_block', {
    ...parentLineage, child_index: 2, action_spec_unit_digest: 'f'.repeat(64)
  })
  journal.complete('child-2', digest, 'collect_block', {
    verified: true, effect_disposition: 'applied',
    outcome: { status: 'applied', code: 'BLOCK_COLLECTED' }
  })
  assert.deepEqual(journal.children('parent').map(row => row.step_index), [2, 4])
  assert.equal(journal.children('parent')[0].outcome_code, 'BLOCK_COLLECTED')
  assert.equal(journal.children('irrelevant-11').length, 0)
})


test('root prepared recovery binds immutable Unit lineage across restart', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-lineage-'))
  const lineage = {
    root_invocation_unit_digest: '1'.repeat(64),
    authorization_unit_digest: '2'.repeat(64)
  }
  try {
    const first = new ActionRecoveryJournal()
    first.configure(root)
    first.prepare('lineage-action', digest, 'wait', lineage)
    first.close()

    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    assert.equal(
      restarted.reconcile('lineage-action', digest, lineage).disposition,
      'not_applied'
    )
    assert.throws(() => restarted.reconcile('lineage-action', digest, {
      ...lineage, authorization_unit_digest: '3'.repeat(64)
    }), /IDENTITY_DRIFT/)
    assert.throws(() => restarted.begin('lineage-action', digest, 'wait', null, {
      ...lineage, root_invocation_unit_digest: '4'.repeat(64)
    }), /IDENTITY_DRIFT/)
    restarted.close()
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
