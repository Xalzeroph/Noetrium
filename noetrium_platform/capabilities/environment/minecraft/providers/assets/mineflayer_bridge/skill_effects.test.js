'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const fs = require('node:fs')
const os = require('node:os')
const path = require('node:path')
const {ActionRecoveryJournal} = require('./action_recovery')
const {childIdentity, createSkillEffectRecorder} = require('./skill_effects')

const ROOT_INVOCATION = '1'.repeat(64)
const AUTHORIZATION = '2'.repeat(64)
const ACTION_UNITS = Object.freeze({
  craft_item: '3'.repeat(64),
  collect_block: '4'.repeat(64),
  place_block: '5'.repeat(64)
})
function authorized (...names) {
  return new Map(names.map(name => [name, ACTION_UNITS[name]]))
}
const parent = {
  action_id: 'paper:episode:goal',
  request_digest: 'a'.repeat(64),
  root_invocation_unit_digest: ROOT_INVOCATION,
  authorization_unit_digest: AUTHORIZATION
}
const input = {item: 'oak_planks', count: 4}

test('one parent journals independently identified children, reconstructs the causal prefix and refuses unsafe replay', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-skill-children-'))
  try {
    const original = new ActionRecoveryJournal()
    original.configure(root)
    original.begin(parent.action_id, parent.request_digest, 'excavate_region')
    const record = createSkillEffectRecorder(original, parent, authorized('collect_block'))
    let executed = 0
    const first = await record(0, 'collect_block', {block: 'oak_log', count: 1}, async () => {
      executed++
      return {verified: true, effect_disposition: 'applied', outcome: {
        status: 'applied', code: 'BLOCKS_COLLECTED',
        inventory_delta: {oak_log: 1}
      }}
    })
    assert.equal(first.child_effect_ref.state, 'terminal')
    assert.equal(executed, 1)
    original.close()

    const recovered = new ActionRecoveryJournal()
    recovered.configure(root)
    const interruptedParent = recovered.reconcile(
      parent.action_id, parent.request_digest
    )
    assert.equal(interruptedParent.disposition, 'unknown')
    assert.equal(interruptedParent.child_effects.length, 1)
    assert.equal(interruptedParent.child_effects[0].outcome_code, 'BLOCKS_COLLECTED')
    const rerun = createSkillEffectRecorder(recovered, parent, authorized('collect_block'))
    const duplicate = await rerun(0, 'collect_block', {block: 'oak_log', count: 1}, async () => {
      executed++
      throw new Error('irreversible block effect must never repeat')
    })
    assert.equal(executed, 1)
    assert.equal(duplicate.physical_handler_skipped, true)
    assert.equal(duplicate.effect_disposition, 'unknown')
    assert.equal(duplicate.child_effect_ref.action_id, first.child_effect_ref.action_id)
    recovered.close()
  } finally {
    fs.rmSync(root, {recursive: true, force: true})
  }
})

test('crash between durable child INTENT and completion is reported UNKNOWN, not replayed', async () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-skill-children-'))
  try {
    const journal = new ActionRecoveryJournal()
    journal.configure(root)
    const record = createSkillEffectRecorder(journal, parent, authorized('collect_block'))
    const payload = {block: 'oak_log', count: 1}
    await assert.rejects(() => record(1, 'collect_block', payload, async () => {
      throw new Error('simulated crash after uncontrolled physical effect')
    }), /simulated crash/)
    journal.close()
    const resumed = new ActionRecoveryJournal()
    resumed.configure(root)
    const children = resumed.children(parent.action_id)
    assert.equal(children.length, 1)
    assert.equal(children[0].disposition, 'unknown')
    const replay = createSkillEffectRecorder(resumed, parent, authorized('collect_block'))
    const result = await replay(1, 'collect_block', payload, async () => {
      throw new Error('must not execute')
    })
    assert.equal(result.effect_disposition, 'unknown')
    assert.equal(result.physical_handler_skipped, true)
    resumed.close()
  } finally {
    fs.rmSync(root, {recursive: true, force: true})
  }
})

test('authority must authorize child before any child journal entry or execution', async () => {
  const journal = new ActionRecoveryJournal()
  journal.configure(null)
  const recorder = createSkillEffectRecorder(journal, parent, authorized('craft_item'))
  let invoked = false
  await assert.rejects(() => recorder(1, 'collect_block', {block: 'oak_log'}, async () => {
    invoked = true
  }), /SKILL_CHILD_CAPABILITY_NOT_AUTHORIZED/)
  assert.equal(invoked, false)
  assert.deepEqual(journal.children(parent.action_id), [])
  assert.notEqual(
    childIdentity(parent.action_id, parent.request_digest, 0, 'craft_item', input, {root_invocation_unit_digest: ROOT_INVOCATION, authorization_unit_digest: AUTHORIZATION, action_spec_unit_digest: ACTION_UNITS.craft_item}).action_id,
    childIdentity(parent.action_id, parent.request_digest, 1, 'craft_item', input, {root_invocation_unit_digest: ROOT_INVOCATION, authorization_unit_digest: AUTHORIZATION, action_spec_unit_digest: ACTION_UNITS.craft_item}).action_id
  )
})

test('child identity is bound to Unit authorization lineage, not action name alone', () => {
  const base = {
    root_invocation_unit_digest: ROOT_INVOCATION,
    authorization_unit_digest: AUTHORIZATION,
    action_spec_unit_digest: ACTION_UNITS.craft_item
  }
  const first = childIdentity(parent.action_id, parent.request_digest, 0, 'craft_item', input, base)
  const changedAuthorization = childIdentity(parent.action_id, parent.request_digest, 0, 'craft_item', input, {
    ...base, authorization_unit_digest: '6'.repeat(64)
  })
  const changedSpec = childIdentity(parent.action_id, parent.request_digest, 0, 'craft_item', input, {
    ...base, action_spec_unit_digest: '7'.repeat(64)
  })
  assert.notEqual(first.action_id, changedAuthorization.action_id)
  assert.notEqual(first.action_id, changedSpec.action_id)
  assert.equal(first.root_invocation_unit_digest, ROOT_INVOCATION)
  assert.equal(first.authorization_unit_digest, AUTHORIZATION)
})

test('nested craft workstation effects retain causal parent and cannot replay after interruption', async () => {
  const runtime = require('./runtime')
  const root = fs.mkdtempSync(path.join(os.tmpdir(), 'mc-skill-nested-'))
  try {
    const ledger = new ActionRecoveryJournal()
    ledger.configure(root)
    const scope = runtime.createActionCancellationScope('nested-craft-test', 5000)
    scope.authorizedChildActionUnits = authorized('craft_item', 'place_block')
    scope.recordChildEffect = createSkillEffectRecorder(
      ledger, parent, scope.authorizedChildActionUnits
    )
    scope.createChildEffectRecorder = child =>
      createSkillEffectRecorder(ledger, child, scope.authorizedChildActionUnits)
    let placements = 0
    const result = await runtime.runWithActionCancellationScope(scope, () =>
      runtime.runSkillChildEffect(0, 'craft_item', {item: 'stick', count: 4}, () =>
        runtime.runSkillChildEffect(0, 'place_block', {item: 'crafting_table'}, async () => {
          placements++
          return {
            verified: true, effect_disposition: 'applied',
            outcome: {status: 'applied', code: 'BLOCK_PLACED', placed: 'crafting_table'}
          }
        })
      )
    )
    const children = ledger.children(parent.action_id)
    assert.equal(children.length, 1)
    assert.equal(children[0].action_type, 'craft_item')
    const grandchildren = ledger.children(children[0].action_id)
    assert.equal(grandchildren.length, 1)
    assert.equal(grandchildren[0].action_type, 'place_block')
    assert.equal(grandchildren[0].disposition, 'applied')
    assert.equal(placements, 1)
    assert.equal(result.effect_disposition, 'applied')
    ledger.close()
    const restored = new ActionRecoveryJournal()
    restored.configure(root)
    assert.equal(restored.children(parent.action_id).length, 1)
    assert.equal(restored.children(children[0].action_id).length, 1)
    const descendants = restored.descendants(parent.action_id)
    assert.equal(descendants.length, 2)
    assert.deepEqual(descendants.map(row => [row.depth, row.action_type]), [
      [1, 'craft_item'], [2, 'place_block']
    ])
    assert.equal(descendants[1].parent_action_id, descendants[0].action_id)
    assert.equal(descendants[1].root_invocation_unit_digest, ROOT_INVOCATION)
    assert.equal(descendants[1].authorization_unit_digest, AUTHORIZATION)
    const reentry = createSkillEffectRecorder(restored, parent, authorized('craft_item'))
    const replay = await reentry(0, 'craft_item', {item: 'stick', count: 4},
      async () => { throw new Error('must never apply physical effects twice') })
    assert.equal(replay.physical_handler_skipped, true)
    assert.equal(placements, 1)
    restored.close()
  } finally { fs.rmSync(root, {recursive: true, force: true}) }
})
