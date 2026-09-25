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
      disposition: 'unknown', state: 'intent', durability: 'crash_durable'
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
    first.complete('action-2', digest, 'wait', { verified: true, outcome: { status: 'applied', code: 'WAIT_COMPLETED' } })

    const restarted = new ActionRecoveryJournal()
    restarted.configure(root)
    assert.equal(restarted.reconcile('action-2', digest).disposition, 'applied')
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