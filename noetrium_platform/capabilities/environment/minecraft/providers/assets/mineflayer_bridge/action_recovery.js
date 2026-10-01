'use strict'

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
    this.memory.set(value.action_id, value)
  }

  _loadLegacyRecords () {
    for (const name of fs.readdirSync(this.root).sort()) {
      if (!name.endsWith('.json')) continue
      const target = path.join(this.root, name)
      const stat = fs.statSync(target)
      if (!stat.isFile()) continue
      this._remember(JSON.parse(fs.readFileSync(target, 'utf8')))
    }
  }

  _loadJournal () {
    if (!this.journalPath || !fs.existsSync(this.journalPath)) return
    const raw = fs.readFileSync(this.journalPath, 'utf8')
    if (!raw) return
    const lastNewline = raw.lastIndexOf('\n')
    if (lastNewline < 0) return
    const durablePrefix = raw.slice(0, lastNewline)
    for (const line of durablePrefix.split('\n')) {
      if (!line) continue
      this._remember(JSON.parse(line))
    }
  }

  configure (root) {
    this._closeFd()
    this.root = root && String(root).trim() ? path.resolve(String(root)) : null
    this.memory.clear()
    if (!this.root) return
    fs.mkdirSync(this.root, { recursive: true })
    this.journalPath = path.join(this.root, 'actions.jsonl')
    this._loadLegacyRecords()
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
    this._remember(record)
    if (this.fd === null) return
    const payload = Buffer.from(JSON.stringify(record) + '\n', 'utf8')
    let offset = 0
    while (offset < payload.length) {
      offset += fs.writeSync(this.fd, payload, offset, payload.length - offset, null)
    }
    fs.fsyncSync(this.fd)
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

  reconcile (actionId, requestDigest) {
    requireIdentity(actionId, requestDigest)
    const record = this._read(actionId)
    if (!record) return { disposition: 'unknown', state: 'absent', durability: this.durability }
    if (record.request_digest !== requestDigest) throw new Error('ACTION_RECOVERY_IDENTITY_DRIFT')
    return {
      disposition: record.disposition || 'unknown',
      state: record.state,
      durability: this.durability,
      outcome: record.outcome || null
    }
  }
}

module.exports = { ActionRecoveryJournal }
