'use strict'

const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const test = require('node:test')
const { ActionRecoveryJournal } = require('./action_recovery')

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

test('legacy per-action record migrates forward through append journal', () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-action-recovery-'))
  try {
    const legacy = {
      schema: 'minecraft-action-recovery-v1',
      action_id: 'action-legacy',
      request_digest: digest,
      action_type: 'wait',
      state: 'intent',
      disposition: 'unknown'
    }
    const legacyPath = path.join(root, 'legacy.json')
    fs.writeFileSync(legacyPath, JSON.stringify(legacy) + '\n')

    const first = new ActionRecoveryJournal()
    first.configure(root)
    first.complete('action-legacy', digest, 'wait', {
      verified: true,
      effect_disposition: 'applied',
      outcome: { status: 'applied', code: 'WAIT_COMPLETED' }
    })
    first.close()
    fs.unlinkSync(legacyPath)

    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    const reconciled = restarted.reconcile('action-legacy', digest)
    assert.equal(reconciled.state, 'terminal')
    assert.equal(reconciled.disposition, 'applied')
    assert.equal(reconciled.outcome.code, 'WAIT_COMPLETED')
    restarted.close()
  } finally { fs.rmSync(root, { recursive: true, force: true }) }
})
