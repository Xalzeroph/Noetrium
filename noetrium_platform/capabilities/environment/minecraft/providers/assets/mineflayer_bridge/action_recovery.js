'use strict'

const crypto = require('node:crypto')
const fs = require('node:fs')
const path = require('node:path')

function requireIdentity (actionId, requestDigest) {
  if (!String(actionId || '').trim()) throw new Error('ACTION_RECOVERY_ACTION_ID_REQUIRED')
  if (!/^[0-9a-f]{64}$/.test(String(requestDigest || ''))) throw new Error('ACTION_RECOVERY_REQUEST_DIGEST_INVALID')
}

class ActionRecoveryJournal {
  constructor () {
    this.root = null
    this.memory = new Map()
  }

  configure (root) {
    this.root = root && String(root).trim() ? path.resolve(String(root)) : null
    if (this.root) fs.mkdirSync(this.root, { recursive: true })
  }

  get durability () { return this.root ? 'crash_durable' : 'process_local' }

  _key (actionId) { return crypto.createHash('sha256').update(String(actionId)).digest('hex') }
  _path (actionId) { return this.root ? path.join(this.root, `${this._key(actionId)}.json`) : null }

  _read (actionId) {
    if (!this.root) return this.memory.get(actionId) || null
    const target = this._path(actionId)
    if (!fs.existsSync(target)) return null
    const value = JSON.parse(fs.readFileSync(target, 'utf8'))
    if (!value || value.schema !== 'minecraft-action-recovery-v1' || value.action_id !== actionId) {
      throw new Error('ACTION_RECOVERY_RECORD_IDENTITY_INVALID')
    }
    return value
  }

  _write (record) {
    this.memory.set(record.action_id, record)
    if (!this.root) return
    fs.mkdirSync(this.root, { recursive: true })
    const target = this._path(record.action_id)
    const temporary = `${target}.${process.pid}.${crypto.randomUUID()}.tmp`
    const fd = fs.openSync(temporary, 'wx', 0o600)
    try {
      fs.writeFileSync(fd, JSON.stringify(record) + '\n', { encoding: 'utf8' })
      fs.fsyncSync(fd)
    } finally {
      fs.closeSync(fd)
    }
    fs.renameSync(temporary, target)
    if (process.platform !== 'win32') {
      const dirFd = fs.openSync(this.root, fs.constants.O_RDONLY)
      try { fs.fsyncSync(dirFd) } finally { fs.closeSync(dirFd) }
    }
  }

  begin (actionId, requestDigest, actionType) {
    requireIdentity(actionId, requestDigest)
    const existing = this._read(actionId)
    if (existing) {
      if (existing.request_digest !== requestDigest || existing.action_type !== actionType) {
        throw new Error('ACTION_RECOVERY_IDENTITY_DRIFT')
      }
      return { execute: false, record: existing }
    }
    const record = {
      schema: 'minecraft-action-recovery-v1',
      action_id: actionId,
      request_digest: requestDigest,
      action_type: actionType,
      state: 'intent',
      disposition: 'unknown'
    }
    this._write(record)
    return { execute: true, record }
  }

  complete (actionId, requestDigest, actionType, result) {
    requireIdentity(actionId, requestDigest)
    const existing = this._read(actionId)
    if (!existing || existing.request_digest !== requestDigest || existing.action_type !== actionType) {
      throw new Error('ACTION_RECOVERY_INTENT_MISSING')
    }
    const status = result && result.outcome ? result.outcome.status : null
    const disposition = result && result.verified === true
      ? 'applied'
      : status === 'rejected' ? 'not_applied' : 'unknown'
    const record = {
      ...existing,
      state: 'terminal',
      disposition,
      verified: Boolean(result && result.verified),
      outcome_status: status || null,
      outcome_code: result && result.outcome ? result.outcome.code || null : null
    }
    this._write(record)
    return record
  }

  reconcile (actionId, requestDigest) {
    requireIdentity(actionId, requestDigest)
    const record = this._read(actionId)
    if (!record) return { disposition: 'unknown', state: 'absent', durability: this.durability }
    if (record.request_digest !== requestDigest) throw new Error('ACTION_RECOVERY_IDENTITY_DRIFT')
    return { disposition: record.disposition || 'unknown', state: record.state, durability: this.durability }
  }
}

module.exports = { ActionRecoveryJournal }