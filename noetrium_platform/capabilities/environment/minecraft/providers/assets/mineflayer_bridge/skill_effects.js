'use strict'

// The single bridge ActionRecoveryJournal owns child effects too. This is
// *not* a second action dispatcher or effect ledger: all nested physical
// intents use the same write-ahead journal as root actions. Child physical
// effects additionally retain the exact Unit authorization lineage supplied
// by the host runtime; the bridge treats those Unit digests as opaque authority
// attestations and never attempts to recreate host Unit semantics.
const { createHash } = require('node:crypto')

const UNIT_DIGEST = /^[0-9a-f]{64}$/

function stableJson (value) {
  if (Array.isArray(value)) return value.map(stableJson)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, stableJson(value[key])])
    )
  }
  return value
}

function requireUnitDigest (value, code) {
  const digest = String(value || '')
  if (!UNIT_DIGEST.test(digest)) throw new Error(code)
  return digest
}

function authorizedActionUnitMap (value) {
  if (!(value instanceof Map)) throw new Error('SKILL_CHILD_UNIT_AUTHORITY_REQUIRED')
  const result = new Map()
  for (const [name, digest] of value.entries()) {
    const actionType = String(name || '')
    if (!/^[a-z][a-z0-9_]*$/.test(actionType)) {
      throw new Error('SKILL_CHILD_ACTION_TYPE_INVALID')
    }
    result.set(actionType, requireUnitDigest(
      digest, 'SKILL_CHILD_ACTION_SPEC_UNIT_INVALID'))
  }
  return result
}

function childIdentity (parentActionId, parentDigest, index, actionType, payload, lineage) {
  if (!String(parentActionId || '').trim() ||
      !UNIT_DIGEST.test(String(parentDigest || '')) ||
      !Number.isSafeInteger(index) || index < 0 ||
      !/^[a-z][a-z0-9_]*$/.test(String(actionType || '')) ||
      !lineage || typeof lineage !== 'object') {
    throw new Error('SKILL_CHILD_IDENTITY_INVALID')
  }
  const rootInvocationUnitDigest = requireUnitDigest(
    lineage.root_invocation_unit_digest, 'SKILL_ROOT_INVOCATION_UNIT_INVALID')
  const authorizationUnitDigest = requireUnitDigest(
    lineage.authorization_unit_digest, 'SKILL_AUTHORIZATION_UNIT_INVALID')
  const actionSpecUnitDigest = requireUnitDigest(
    lineage.action_spec_unit_digest, 'SKILL_CHILD_ACTION_SPEC_UNIT_INVALID')
  const request = JSON.stringify(stableJson({
    parent_action_id: parentActionId,
    parent_request_digest: parentDigest,
    child_index: index,
    action_type: actionType,
    arguments: payload,
    root_invocation_unit_digest: rootInvocationUnitDigest,
    authorization_unit_digest: authorizationUnitDigest,
    action_spec_unit_digest: actionSpecUnitDigest
  }))
  const digest = createHash('sha256').update(request).digest('hex')
  return {
    action_id: 'minecraft-skill-child:' + digest,
    request_digest: digest,
    parent_action_id: parentActionId,
    parent_request_digest: parentDigest,
    child_index: index,
    root_invocation_unit_digest: rootInvocationUnitDigest,
    authorization_unit_digest: authorizationUnitDigest,
    action_spec_unit_digest: actionSpecUnitDigest
  }
}

function createSkillEffectRecorder (journal, parent, authorizedActionUnits) {
  if (!journal || typeof journal.begin !== 'function' ||
      typeof journal.complete !== 'function') {
    throw new TypeError('SKILL_EFFECT_AUTHORITY_REQUIRED')
  }
  if (!parent || !String(parent.action_id || '').trim() ||
      !UNIT_DIGEST.test(String(parent.request_digest || ''))) {
    throw new Error('SKILL_PARENT_IDENTITY_INVALID')
  }
  const rootInvocationUnitDigest = requireUnitDigest(
    parent.root_invocation_unit_digest, 'SKILL_ROOT_INVOCATION_UNIT_INVALID')
  const authorizationUnitDigest = requireUnitDigest(
    parent.authorization_unit_digest, 'SKILL_AUTHORIZATION_UNIT_INVALID')
  const allowed = authorizedActionUnitMap(authorizedActionUnits)
  return async function recordChildEffect (index, actionType, payload, execute) {
    if (!allowed.has(actionType)) throw new Error('SKILL_CHILD_CAPABILITY_NOT_AUTHORIZED')
    if (typeof execute !== 'function') throw new TypeError('SKILL_EXECUTOR_REQUIRED')
    const actionSpecUnitDigest = allowed.get(actionType)
    const id = childIdentity(
      parent.action_id, parent.request_digest, index, actionType, payload,
      {
        root_invocation_unit_digest: rootInvocationUnitDigest,
        authorization_unit_digest: authorizationUnitDigest,
        action_spec_unit_digest: actionSpecUnitDigest
      }
    )
    const begun = journal.begin(id.action_id, id.request_digest, actionType, {
      action_id: parent.action_id,
      request_digest: parent.request_digest,
      child_index: index,
      root_invocation_unit_digest: rootInvocationUnitDigest,
      authorization_unit_digest: authorizationUnitDigest,
      action_spec_unit_digest: actionSpecUnitDigest
    })
    if (!begun.execute) {
      // Reconciliation cannot prove an interrupted intent was not applied.
      // Never run the handler a second time on a duplicate child identity.
      return {
        verified: false,
        effect_disposition: 'unknown',
        outcome: {
          status: 'partial',
          code: 'SKILL_CHILD_ALREADY_SUBMITTED_NO_REEXECUTION',
          prior_disposition: begun.record.disposition
        },
        child_effect_ref: {...id, state: begun.record.state},
        physical_handler_skipped: true
      }
    }
    // A thrown exception leaves the child durable as UNKNOWN. Parent
    // recovery will report this prefix rather than rerun physical mutations.
    const result = await execute(id)
    if (!result || !result.outcome || ![
      'applied', 'rejected', 'not_applied', 'unknown'
    ].includes(result.effect_disposition)) {
      throw new Error('SKILL_CHILD_RESULT_UNVERIFIABLE')
    }
    journal.complete(id.action_id, id.request_digest, actionType, result)
    return {...result, child_effect_ref: {
      ...id, state: 'terminal', disposition: result.effect_disposition
    }}
  }
}

module.exports = { childIdentity, createSkillEffectRecorder }
