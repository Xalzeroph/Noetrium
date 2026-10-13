'use strict'

const fs = require('node:fs')
const path = require('node:path')

const SHA256 = /^[0-9a-f]{64}$/

function requireIdentity (actionId, requestDigest) {
  if (!String(actionId || '').trim()) throw new Error('ACTION_RECOVERY_ACTION_ID_REQUIRED')
  if (!SHA256.test(String(requestDigest || ''))) throw new Error('ACTION_RECOVERY_REQUEST_DIGEST_INVALID')
}

function normalizeRootLineage (lineage) {
  if (lineage == null) return null
  if (!lineage || typeof lineage !== 'object') {
    throw new Error('ACTION_RECOVERY_UNIT_LINEAGE_INVALID')
  }
  const root = String(lineage.root_invocation_unit_digest || '')
  const authorization = String(lineage.authorization_unit_digest || '')
  if (!SHA256.test(root) || !SHA256.test(authorization)) {
    throw new Error('ACTION_RECOVERY_UNIT_LINEAGE_INVALID')
  }
  return {
    root_invocation_unit_digest: root,
    authorization_unit_digest: authorization
  }
}

class ActionRecoveryJournal {
  constructor () {
    this.root = null
    this.memory = new Map()
    // The only child-effect index: parent -> child index -> exact action ID.
    // Parent reconciliation now costs O(children), not O(all session actions).
    this.childrenByParent = new Map()
    this.fd = null
    this.journalPath = null
  }

  _closeFd () {
    if (this.fd !== null) fs.closeSync(this.fd)
    this.fd = null
    this.journalPath = null
  }

  close () { this._closeFd() }

  _remember (value) {
    if (!value || value.schema !== 'minecraft-action-recovery-v1' || !String(value.action_id || '').trim()) {
      throw new Error('ACTION_RECOVERY_RECORD_IDENTITY_INVALID')
    }
    const rootLineage = [
      value.root_invocation_unit_digest, value.authorization_unit_digest
    ]
    const anyRootLineage = rootLineage.some(item => item !== undefined)
    if (anyRootLineage && !rootLineage.every(item => SHA256.test(String(item || '')))) {
      throw new Error('ACTION_RECOVERY_UNIT_LINEAGE_INVALID')
    }
    if (value.parent_action_id) {
      if (!Number.isSafeInteger(value.child_index) || value.child_index < 0) {
        throw new Error('ACTION_RECOVERY_CHILD_INDEX_INVALID')
      }
      const lineage = [
        value.parent_request_digest,
        value.root_invocation_unit_digest,
        value.authorization_unit_digest,
        value.action_spec_unit_digest
      ]
      const anyLineage = lineage.some(item => item !== undefined)
      if (anyLineage && !lineage.every(item => SHA256.test(String(item || '')))) {
        throw new Error('ACTION_RECOVERY_CHILD_LINEAGE_INVALID')
      }
      let children = this.childrenByParent.get(value.parent_action_id)
      if (!children) {
        children = new Map()
        this.childrenByParent.set(value.parent_action_id, children)
      }
      const existing = children.get(value.child_index)
      if (existing && existing !== value.action_id) {
        throw new Error('ACTION_RECOVERY_CHILD_INDEX_DRIFT')
      }
      children.set(value.child_index, value.action_id)
    }
    this.memory.set(value.action_id, value)
  }

  _loadJournal () {
    if (!this.journalPath || !fs.existsSync(this.journalPath)) return
    // Rebuild only the index, not a second full in-memory copy of the WAL.
    // Working set is O(max record bytes + action identities), not WAL bytes.
    const fd = fs.openSync(this.journalPath, 'r+')
    try {
      const chunk = Buffer.allocUnsafe(65536)
      let carry = Buffer.alloc(0)
      let position = 0
      let durableOffset = 0
      for (;;) {
        const size = fs.readSync(fd, chunk, 0, chunk.length, position)
        if (size === 0) break
        position += size
        const data = carry.length
          ? Buffer.concat([carry, chunk.subarray(0, size)])
          : chunk.subarray(0, size)
        let start = 0
        for (let index = 0; index < data.length; index++) {
          if (data[index] !== 10) continue
          if (index !== start) {
            this._remember(JSON.parse(data.toString('utf8', start, index)))
          }
          start = index + 1
        }
        // Offset from the start of the file, even when a UTF-8 line straddles
        // several read buffers.
        durableOffset = position - (data.length - start)
        carry = start === data.length ? Buffer.alloc(0) : Buffer.from(data.subarray(start))
      }
      if (carry.length) {
        fs.ftruncateSync(fd, durableOffset)
        fs.fsyncSync(fd)
      }
    } finally {
      fs.closeSync(fd)
    }
  }

  configure (root) {
    this._closeFd()
    this.root = root && String(root).trim() ? path.resolve(String(root)) : null
    this.memory.clear()
    this.childrenByParent.clear()
    if (!this.root) return
    fs.mkdirSync(this.root, { recursive: true })
    this.journalPath = path.join(this.root, 'actions.jsonl')
    this._loadJournal()
    const existed = fs.existsSync(this.journalPath)
    this.fd = fs.openSync(this.journalPath, 'a', 0o600)
    if (!existed && process.platform !== 'win32') {
      fs.fsyncSync(this.fd)
      const dirFd = fs.openSync(this.root, fs.constants.O_RDONLY)
      try { fs.fsyncSync(dirFd) } finally { fs.closeSync(dirFd) }
    }
  }

  get durability () { return this.root ? 'crash_durable' : 'process_local' }

  _read (actionId) { return this.memory.get(actionId) || null }

  _write (record) {
    if (this.fd !== null) {
      const payload = Buffer.from(JSON.stringify(record) + '\n', 'utf8')
      let offset = 0
      while (offset < payload.length) {
        const written = fs.writeSync(this.fd, payload, offset, payload.length - offset, null)
        if (written <= 0) throw new Error('ACTION_RECOVERY_WRITE_STALLED')
        offset += written
      }
      fs.fsyncSync(this.fd)
    }
    // A physical handler can start only after the INTENT is durable. Never
    // expose an uncommitted in-memory action state when fsync failed.
    this._remember(record)
  }

  prepare (actionId, requestDigest, actionType, lineage = null) {
    requireIdentity(actionId, requestDigest)
    const rootLineage = normalizeRootLineage(lineage)
    const existing = this._read(actionId)
    if (existing) {
      if (existing.request_digest !== requestDigest || existing.action_type !== actionType ||
          (rootLineage !== null && (
            existing.root_invocation_unit_digest !== rootLineage.root_invocation_unit_digest ||
            existing.authorization_unit_digest !== rootLineage.authorization_unit_digest
          ))) {
        throw new Error('ACTION_RECOVERY_IDENTITY_DRIFT')
      }
      return { created: false, record: existing }
    }
    // PREPARED is a durable proof that the provider knows the exact action but
    // physical execution has not started.  Its reconciliation is therefore
    // provably NOT_APPLIED, closing the outer-effect PREPARED -> provider-send
    // crash window without weakening fail-close semantics once execution begins.
    const record = {
      schema: 'minecraft-action-recovery-v1',
      action_id: actionId,
      request_digest: requestDigest,
      action_type: actionType,
      ...(rootLineage === null ? {} : rootLineage),
      state: 'prepared',
      disposition: 'not_applied'
    }
    this._write(record)
    return { created: true, record }
  }

  begin (actionId, requestDigest, actionType, parent = null, lineage = null) {
    requireIdentity(actionId, requestDigest)
    const rootLineage = parent === null ? normalizeRootLineage(lineage) : null
    if (parent !== null && lineage !== null) {
      throw new Error('ACTION_RECOVERY_CHILD_ROOT_LINEAGE_DUPLICATED')
    }
    if (parent !== null && (
      !parent || typeof parent !== 'object' ||
      !String(parent.action_id || '').trim() ||
      !SHA256.test(String(parent.request_digest || '')) ||
      !Number.isSafeInteger(parent.child_index) || parent.child_index < 0 ||
      !SHA256.test(String(parent.root_invocation_unit_digest || '')) ||
      !SHA256.test(String(parent.authorization_unit_digest || '')) ||
      !SHA256.test(String(parent.action_spec_unit_digest || ''))
    )) throw new Error('ACTION_RECOVERY_PARENT_IDENTITY_INVALID')
    const existing = this._read(actionId)
    if (existing) {
      if (existing.request_digest !== requestDigest || existing.action_type !== actionType ||
          (rootLineage !== null && (
            existing.root_invocation_unit_digest !== rootLineage.root_invocation_unit_digest ||
            existing.authorization_unit_digest !== rootLineage.authorization_unit_digest
          )) ||
          (parent !== null && (
            existing.parent_action_id !== parent.action_id ||
            existing.parent_request_digest !== parent.request_digest ||
            existing.child_index !== parent.child_index ||
            existing.root_invocation_unit_digest !== parent.root_invocation_unit_digest ||
            existing.authorization_unit_digest !== parent.authorization_unit_digest ||
            existing.action_spec_unit_digest !== parent.action_spec_unit_digest
          ))) {
        throw new Error('ACTION_RECOVERY_IDENTITY_DRIFT')
      }
      if (existing.state === 'prepared') {
        const record = {
          ...existing,
          state: 'intent',
          disposition: 'unknown'
        }
        this._write(record)
        return { execute: true, record }
      }
      return { execute: false, record: existing }
    }
    // Backward-safe direct execution path: if a caller has no separate prepare
    // phase, execution still durably records INTENT before invoking the handler.
    const record = {
      schema: 'minecraft-action-recovery-v1',
      action_id: actionId,
      request_digest: requestDigest,
      action_type: actionType,
      state: 'intent',
      disposition: 'unknown',
      ...(parent === null
        ? (rootLineage === null ? {} : rootLineage)
        : {
        parent_action_id: parent.action_id,
        parent_request_digest: parent.request_digest,
        child_index: parent.child_index,
        root_invocation_unit_digest: parent.root_invocation_unit_digest,
        authorization_unit_digest: parent.authorization_unit_digest,
        action_spec_unit_digest: parent.action_spec_unit_digest
      })
    }
    this._write(record)
    return { execute: true, record }
  }

  children (parentActionId) {
    const ids = this.childrenByParent.get(parentActionId)
    if (!ids) return []
    return [...ids.entries()]
      .sort((a, b) => a[0] - b[0])
      .map(([, id]) => this.memory.get(id))
      .map(record => ({
        action_id: record.action_id,
        request_digest: record.request_digest,
        action_type: record.action_type,
        parent_action_id: record.parent_action_id,
        step_index: record.child_index,
        parent_request_digest: record.parent_request_digest || null,
        root_invocation_unit_digest: record.root_invocation_unit_digest || null,
        authorization_unit_digest: record.authorization_unit_digest || null,
        action_spec_unit_digest: record.action_spec_unit_digest || null,
        state: record.state,
        disposition: record.disposition,
        outcome_status: record.outcome_status || null,
        outcome_code: record.outcome_code || null
      }))
  }

  descendants (parentActionId) {
    const result = []
    const stack = this.children(parentActionId)
      .slice().reverse().map(child => ({ child, depth: 1 }))
    while (stack.length) {
      const current = stack.pop()
      result.push({ ...current.child, depth: current.depth })
      const nested = this.children(current.child.action_id)
      for (let index = nested.length - 1; index >= 0; index--) {
        stack.push({ child: nested[index], depth: current.depth + 1 })
      }
    }
    return result
  }

  complete (actionId, requestDigest, actionType, result) {
    requireIdentity(actionId, requestDigest)
    const existing = this._read(actionId)
    if (!existing || existing.request_digest !== requestDigest || existing.action_type !== actionType) {
      throw new Error('ACTION_RECOVERY_INTENT_MISSING')
    }
    const status = result && result.outcome ? result.outcome.status : null
    const disposition = result ? String(result.effect_disposition || '') : ''
    if (!['applied', 'rejected', 'not_applied', 'unknown'].includes(disposition)) {
      throw new Error('ACTION_RECOVERY_EFFECT_DISPOSITION_INVALID')
    }
    const record = {
      ...existing,
      state: 'terminal',
      disposition,
      verified: Boolean(result && result.verified),
      outcome_status: status || null,
      outcome_code: result && result.outcome ? result.outcome.code || null : null,
      outcome: result && result.outcome ? result.outcome : null
    }
    this._write(record)
    return record
  }

  reconcile (actionId, requestDigest, lineage = null) {
    requireIdentity(actionId, requestDigest)
    const rootLineage = normalizeRootLineage(lineage)
    const record = this._read(actionId)
    if (!record) return { disposition: 'unknown', state: 'absent', durability: this.durability }
    if (record.request_digest !== requestDigest ||
        (rootLineage !== null && (
          record.root_invocation_unit_digest !== rootLineage.root_invocation_unit_digest ||
          record.authorization_unit_digest !== rootLineage.authorization_unit_digest
        ))) {
      throw new Error('ACTION_RECOVERY_IDENTITY_DRIFT')
    }
    const childEffects = this.descendants(actionId)
    return {
      disposition: record.disposition || 'unknown',
      state: record.state,
      durability: this.durability,
      outcome: record.outcome || null,
      ...(childEffects.length ? { child_effects: childEffects } : {})
    }
  }
}

// A durable APPLIED effect is not necessarily a completed *goal*. Preserve
// the exact prior outcome status rather than upgrading a partial effect to a
// fictitious successful task on duplicate submission.
function replayActionResult (actionType, record) {
  const disposition = record && record.disposition || 'unknown'
  const terminal = record && record.state === 'terminal'
  const prior = terminal && record.outcome &&
    typeof record.outcome === 'object' ? record.outcome : null
  if (prior && disposition !== 'unknown') {
    return {
      action: {tool: actionType, recovered: true},
      outcome: {
        ...prior,
        recovered_prior_effect: true,
        prior_outcome_not_current_world_truth: true,
      },
      effect_disposition: disposition,
      verified: record.verified === true && prior.status === 'applied'
    }
  }
  return {
    action: {tool: actionType, recovered: true},
    outcome: {
      status: disposition === 'unknown' ? 'partial' : 'rejected',
      code: disposition === 'unknown'
        ? 'ACTION_RECOVERY_UNCERTAIN' : 'ACTION_RECOVERY_NOT_APPLIED',
      recovery_state: record && record.state || 'absent',
      prior_outcome_not_current_world_truth: true,
    },
    effect_disposition: disposition,
    verified: false
  }
}

module.exports = { ActionRecoveryJournal, replayActionResult }
