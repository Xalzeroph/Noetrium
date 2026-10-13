'use strict'

// One session owns one bot. Only this actor dispatches wire commands that
// can touch that bot. Lifecycle state is control truth, never world-effect truth.
const EDGES = Object.freeze({
  queued: Object.freeze({ start: 'running', interrupt: 'stopped' }),
  running: Object.freeze({ interrupt: 'stopping', settle: 'reconciling' }),
  stopping: Object.freeze({ settle: 'reconciling' }),
  reconciling: Object.freeze({ finish: 'settled' })
})

class ActionControlStatechart {
  constructor (actionId = null, maxChildDepth = 0) {
    if (!Number.isSafeInteger(maxChildDepth) || maxChildDepth < 0) {
      throw new Error('ACTION_CONTROL_CHILD_DEPTH_BOUND_INVALID')
    }
    this.actionId = actionId
    this.maxChildDepth = maxChildDepth
    this.state = 'queued'
    this.reason = null
    this.effectDisposition = 'unknown'
    this.transitions = 0
    this._steps = []
    this.finishedChildAttempts = 0
    this.lastChildStep = null
  }

  childTransition (phase, index, actionType, outcome = null) {
    if (!Number.isSafeInteger(index) || index < 0 ||
        !/^[a-z][a-z0-9_]*$/.test(String(actionType || ''))) {
      throw new Error('ACTION_CONTROL_CHILD_IDENTITY_INVALID')
    }
    if (this.state !== 'running' && this.state !== 'stopping') {
      throw new Error('ACTION_CONTROL_CHILD_NOT_EXECUTING')
    }
    if (phase === 'start') {
      if (this._steps.length >= this.maxChildDepth) {
        throw new Error('ACTION_CONTROL_CHILD_DEPTH_EXCEEDED')
      }
      this._steps.push({ index, action_type: actionType })
    } else if (phase === 'finish' || phase === 'fault') {
      const active = this._steps[this._steps.length - 1]
      if (!active || active.index !== index || active.action_type !== actionType) {
        throw new Error('ACTION_CONTROL_CHILD_NESTING_MISMATCH')
      }
      this._steps.pop()
      this.finishedChildAttempts++
      this.lastChildStep = {
        ...active,
        phase,
        outcome: typeof outcome === 'string' ? outcome : null
      }
    } else {
      throw new Error('ACTION_CONTROL_CHILD_EVENT_INVALID')
    }
    return this.snapshot()
  }

  transition (event, detail = null) {
    const next = EDGES[this.state] && EDGES[this.state][event]
    if (!next) throw new Error('ACTION_CONTROL_INVALID_TRANSITION:' + this.state + ':' + event)
    this.state = next
    this.transitions++
    if (event === 'interrupt') this.reason = String(detail || 'ACTION_INTERRUPTED')
    if (event === 'finish') this.effectDisposition = String(detail || 'unknown')
    return this.state
  }

  snapshot () {
    return {
      state: this.state,
      reason: this.reason,
      effect_disposition: this.effectDisposition,
      transitions: this.transitions,
      max_child_depth: this.maxChildDepth,
      active_child: this._steps.length
        ? { ...this._steps[this._steps.length - 1], depth: this._steps.length }
        : null,
      completed_child_attempts: this.finishedChildAttempts,
      last_child: this.lastChildStep ? { ...this.lastChildStep } : null
    }
  }
}

class MinecraftBotActor {
  constructor () {
    this._tail = Promise.resolve()
    this._pending = new Map()
    this._active = null
    this._lastSettled = null
  }

  dispatch (command, operation, identity = null) {
    if (typeof operation !== 'function') throw new TypeError('actor operation must be a function')
    const actionId = identity ? String(identity.actionId || '') : ''
    const digest = identity ? String(identity.digest || '') : ''
    const maxChildDepth = identity && identity.maxChildDepth != null
      ? Number(identity.maxChildDepth) : 0
    if (identity && (!actionId || !digest || !Number.isSafeInteger(maxChildDepth) || maxChildDepth < 0)) {
      throw new Error('ACTION_CONTROL_IDENTITY_REQUIRED')
    }
    if (actionId && this._pending.has(actionId)) throw new Error('ACTION_CONTROL_DUPLICATE_ID')
    const entry = {
      command: String(command),
      actionId,
      digest,
      chart: new ActionControlStatechart(actionId || null, maxChildDepth),
      scope: null,
      resultDisposition: 'unknown',
      interrupted: false
    }
    if (actionId) this._pending.set(actionId, entry)
    const execute = async () => {
      this._active = entry
      try {
        if (entry.interrupted) {
          // No physical handler was invoked; a previously durable PREPARED
          // record still reconciles to NOT_APPLIED.
          throw new Error('ACTION_INTERRUPTED_BEFORE_DISPATCH')
        }
        entry.chart.transition('start')
        return await operation()
      } finally {
        if (entry.chart.state === 'running' || entry.chart.state === 'stopping') {
          // A composite cannot settle while a child effect is still open.
          // Mark it unknown rather than silently discarding causal state.
          if (entry.chart._steps.length > 0) entry.resultDisposition = 'unknown'
          entry.chart.transition('settle')
        }
        if (entry.chart.state === 'reconciling') {
          entry.chart.transition('finish', entry.resultDisposition)
        }
        this._lastSettled = entry.chart.snapshot()
        this._active = null
        if (actionId) this._pending.delete(actionId)
      }
    }
    // The rejection is observed by the caller; the tail must never poison
    // subsequent commands. O(1) scheduling and no secondary worker queue.
    const promise = this._tail.then(execute)
    this._tail = promise.then(() => undefined, () => undefined)
    return promise
  }

  attachScope (actionId, digest, scope) {
    const entry = this._active
    if (!entry || entry.actionId !== actionId || entry.digest !== digest) {
      throw new Error('ACTION_CONTROL_SCOPE_IDENTITY_MISMATCH')
    }
    if (entry.scope) throw new Error('ACTION_CONTROL_SCOPE_ALREADY_OWNED')
    entry.scope = scope
    if (entry.interrupted) void scope.cancel(entry.chart.reason).catch(() => {})
  }

  childTransition (actionId, digest, phase, index, actionType, outcome = null) {
    const entry = this._active
    if (!entry || entry.actionId !== actionId || entry.digest !== digest) {
      throw new Error('ACTION_CONTROL_CHILD_PARENT_MISMATCH')
    }
    return entry.chart.childTransition(phase, index, actionType, outcome)
  }

  recordResult (actionId, digest, disposition) {
    const entry = this._active
    if (!entry || entry.actionId !== actionId || entry.digest !== digest) {
      throw new Error('ACTION_CONTROL_RESULT_IDENTITY_MISMATCH')
    }
    if (!['applied', 'rejected', 'not_applied', 'unknown'].includes(disposition)) {
      throw new Error('ACTION_CONTROL_RESULT_DISPOSITION_INVALID')
    }
    entry.resultDisposition = disposition
    if (entry.chart.state === 'running' || entry.chart.state === 'stopping') {
      entry.chart.transition('settle')
    }
    if (entry.chart.state === 'reconciling') {
      entry.chart.transition('finish', disposition)
    }
    return entry.chart.snapshot()
  }

  interrupt (actionId, digest, reason = 'AGENT_INTERRUPTED') {
    const entry = this._pending.get(String(actionId))
    if (!entry || entry.digest !== String(digest)) {
      return { accepted: false, code: 'ACTION_CONTROL_IDENTITY_NOT_ACTIVE' }
    }
    if (entry.interrupted) return { accepted: true, ...entry.chart.snapshot() }
    if (entry.chart.state === 'reconciling' || entry.chart.state === 'settled' ||
        entry.chart.state === 'stopped') {
      return { accepted: false, code: 'ACTION_CONTROL_ALREADY_TERMINAL', ...entry.chart.snapshot() }
    }
    entry.interrupted = true
    entry.chart.transition('interrupt', reason)
    if (entry.scope) {
      // Acknowledging an interrupt means it was requested, not that physical
      // effects have quiesced. The normal action receipt still owns truth.
      void entry.scope.cancel(reason).catch(() => {})
    }
    return { accepted: true, ...entry.chart.snapshot() }
  }

  lastSettledSnapshot () {
    const snapshot = this._lastSettled
    if (!snapshot) return null
    // Never expose actor-owned mutable state to tests/diagnostics. No arbitrary
    // hierarchy or string bounds are imposed here; the control statechart
    // remains governed by actual causal nesting.
    return {
      ...snapshot,
      active_child: snapshot.active_child ? { ...snapshot.active_child } : null,
      last_child: snapshot.last_child ? { ...snapshot.last_child } : null
    }
  }

  status () {
    return {
      active: this._active
        ? { action_id: this._active.actionId || null, command: this._active.command, ...this._active.chart.snapshot() }
        : null,
      outstanding: this._pending.size
    }
  }
}

module.exports = { ActionControlStatechart, MinecraftBotActor }
