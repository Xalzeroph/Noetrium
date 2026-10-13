'use strict'

const { Movements, goals: { Goal, GoalNear, GoalFollow, GoalInvert, GoalCompositeAny, GoalPlaceBlock, GoalLookAtBlock } } = require('mineflayer-pathfinder')
const { Vec3 } = require('vec3')
const { AsyncLocalStorage } = require('node:async_hooks')

let bot = null
let movements = null
let defaultNearbyBlocksCache = null
let boundBlockUpdateListener = null
const DEFAULT_NEARBY_BLOCK_RADIUS = 16
const actionCancellationStorage = new AsyncLocalStorage()
const ACTION_CLEANUP_TIMEOUT_MS = 2000
const ACTION_PROVIDER_QUIESCENCE_TIMEOUT_MS = 2000
// Terminal projection/publication gets one existing provider window beyond the
// cancellation + quiescence upper bound. This is derived from the provider's
// own liveness windows rather than a task- or benchmark-specific slack value.
const ACTION_TERMINAL_PUBLICATION_WINDOW_MS = Math.max(
  ACTION_CLEANUP_TIMEOUT_MS, ACTION_PROVIDER_QUIESCENCE_TIMEOUT_MS
)
const ACTION_TERMINAL_SETTLEMENT_MS = ACTION_CLEANUP_TIMEOUT_MS +
  ACTION_PROVIDER_QUIESCENCE_TIMEOUT_MS + ACTION_TERMINAL_PUBLICATION_WINDOW_MS

class ActionCancelledError extends Error {
  constructor (reason = 'ACTION_CANCELLED') {
    super(String(reason || 'ACTION_CANCELLED'))
    this.name = 'ActionCancelledError'
    this.code = 'ACTION_CANCELLED'
  }
}

function baseSleep (ms) {
  return new Promise(resolve => setTimeout(resolve, Math.max(0, Number(ms) || 0)))
}

async function settleCleanup (promise, timeoutMs, name) {
  let timer = null
  try {
    return await Promise.race([
      Promise.resolve(promise),
      new Promise((resolve, reject) => {
        timer = setTimeout(() => {
          const error = new Error(`ACTION_CANCEL_CLEANUP_TIMEOUT:${name}`)
          error.code = 'ACTION_CANCEL_CLEANUP_TIMEOUT'
          reject(error)
        }, Math.max(1, Number(timeoutMs) || 1))
      })
    ])
  } finally {
    if (timer) clearTimeout(timer)
  }
}

class ActionCancellationScope {
  constructor (label, cleanupTimeoutMs = ACTION_CLEANUP_TIMEOUT_MS) {
    this.label = String(label || 'minecraft-action')
    this.cleanupTimeoutMs = Math.max(100, Number(cleanupTimeoutMs) || 2000)
    this.cancelled = false
    this.reason = null
    this._cleanups = []
    this._sleepers = new Set()
    this._cancelPromise = null
    this._interruptListeners = new Set()
    this.cleanupErrors = []
  }

  onCancel (name, cleanup) {
    if (typeof cleanup !== 'function') throw new TypeError('action cancellation cleanup must be callable')
    const row = { name: String(name || 'cleanup'), cleanup, active: true }
    this._cleanups.push(row)
    if (this.cancelled) {
      row.active = false
      void settleCleanup(Promise.resolve().then(cleanup), this.cleanupTimeoutMs, row.name)
        .catch(error => { this.cleanupErrors.push(error) })
    }
    return () => { row.active = false }
  }

  onInterrupt (callback) {
    if (typeof callback !== 'function') throw new TypeError('interrupt listener must be callable')
    if (this.cancelled) {
      queueMicrotask(callback)
      return () => {}
    }
    this._interruptListeners.add(callback)
    return () => this._interruptListeners.delete(callback)
  }

  throwIfCancelled () {
    if (this.cancelled) throw new ActionCancelledError(this.reason || 'ACTION_CANCELLED')
  }

  sleep (ms) {
    this.throwIfCancelled()
    return new Promise((resolve, reject) => {
      const row = { timer: null, reject }
      const finish = () => {
        if (!this._sleepers.delete(row)) return
        resolve()
      }
      row.timer = setTimeout(finish, Math.max(0, Number(ms) || 0))
      this._sleepers.add(row)
    })
  }

  cancel (reason = 'ACTION_CANCELLED') {
    if (this._cancelPromise) return this._cancelPromise
    this.cancelled = true
    this.reason = String(reason || 'ACTION_CANCELLED')
    const listeners = [...this._interruptListeners]
    this._interruptListeners.clear()
    const cancelledError = new ActionCancelledError(this.reason)
    for (const row of [...this._sleepers]) {
      this._sleepers.delete(row)
      if (row.timer) clearTimeout(row.timer)
      row.reject(cancelledError)
    }
    const cleanups = [...this._cleanups].reverse().filter(row => row.active)
    this._cleanups = []
    this._cancelPromise = (async () => {
      // Cancellation handlers own independent provider resources (movement,
      // windows, event waiters, collectors). Start them together so terminal
      // settlement is bounded by one cleanup window rather than N serial
      // cleanup windows. Preserve reverse registration order in error evidence.
      const results = await Promise.all(cleanups.map(async row => {
        try {
          await settleCleanup(
            Promise.resolve().then(row.cleanup),
            this.cleanupTimeoutMs,
            row.name
          )
          return null
        } catch (error) {
          return error
        }
      }))
      for (const error of results) {
        if (error) this.cleanupErrors.push(error)
      }
      return { clean: this.cleanupErrors.length === 0, errors: [...this.cleanupErrors] }
    })()
    // Publish after _cancelPromise exists, preventing recursive cancellation
    // from allocating a second cleanup sequence.
    for (const notify of listeners) queueMicrotask(notify)
    return this._cancelPromise
  }
}

function currentActionCancellationScope () {
  return actionCancellationStorage.getStore() || null
}

// Composite effects are recorded by the SAME ActionRecoveryJournal. No
// physical mutation may be executed from a Goal skill without an identity
// and a durable intent written by its enclosing bridge action.
function isSkillChildAuthorized (actionType) {
  const scope = currentActionCancellationScope()
  return Boolean(
    scope && scope.authorizedChildActionUnits instanceof Map &&
    scope.authorizedChildActionUnits.has(actionType)
  )
}

async function runSkillChildEffect (index, actionType, payload, execute) {
  const scope = currentActionCancellationScope()
  if (!scope || typeof scope.recordChildEffect !== 'function') {
    throw new Error('SKILL_CHILD_EFFECT_AUTHORITY_REQUIRED')
  }
  scope.throwIfCancelled()
  const notify = typeof scope.onSkillChildTransition === 'function'
    ? scope.onSkillChildTransition : null
  if (notify) notify('start', index, actionType)
  try {
    const result = await scope.recordChildEffect(index, actionType, payload, childIdentity => {
      if (typeof scope.createChildEffectRecorder !== 'function') {
        return execute()
      }
      // The nested skill shares the SAME cancellation/deadline and WAL.
      // Only its causal parent action identity changes.
      const nested = Object.create(scope)
      nested.recordChildEffect = scope.createChildEffectRecorder(childIdentity)
      return runWithActionCancellationScope(nested, execute)
    })
    if (notify) notify(
      'finish', index, actionType,
      result && result.outcome && typeof result.outcome.status === 'string'
        ? result.outcome.status : null
    )
    return result
  } catch (error) {
    if (notify) notify('fault', index, actionType)
    throw error
  }
}

function runWithActionCancellationScope (scope, fn) {
  if (!(scope instanceof ActionCancellationScope)) throw new TypeError('invalid action cancellation scope')
  return actionCancellationStorage.run(scope, fn)
}

function onActionCancel (name, cleanup) {
  const scope = currentActionCancellationScope()
  return scope ? scope.onCancel(name, cleanup) : () => {}
}

function createActionCancellationScope (label, timeoutMs = null) {
  const scope = new ActionCancellationScope(label)
  if (timeoutMs !== null) {
    const parsed = Number(timeoutMs)
    if (!Number.isFinite(parsed) || parsed <= 0) {
      const error = new Error('ACTION_TIMEOUT_REQUIRED')
      error.code = 'ACTION_TIMEOUT_REQUIRED'
      throw error
    }
    scope.deadlineMs = Date.now() + Math.floor(parsed)
  } else {
    scope.deadlineMs = null
  }
  scope.onCancel('mineflayer:window-close', () => {
    if (!bot || !bot.currentWindow || typeof bot.closeWindow !== 'function') return
    bot.closeWindow(bot.currentWindow)
  })
  scope.onCancel('mineflayer:active-item', () => {
    if (bot && typeof bot.deactivateItem === 'function') bot.deactivateItem()
  })
  scope.onCancel('mineflayer:collect-block', async () => {
    if (bot && bot.collectBlock && typeof bot.collectBlock.cancelTask === 'function') {
      await bot.collectBlock.cancelTask()
    }
  })
  scope.onCancel('mineflayer:motion', () => stopMotion())
  return scope
}

function bindBot (value) {
  if (bot && boundBlockUpdateListener && typeof bot.removeListener === 'function') {
    bot.removeListener('blockUpdate', boundBlockUpdateListener)
  }
  bot = value
  movements = null
  defaultNearbyBlocksCache = null
  boundBlockUpdateListener = null
  if (bot && typeof bot.on === 'function') {
    boundBlockUpdateListener = (oldBlock, newBlock) => {
      const changed = (newBlock && newBlock.position) || (oldBlock && oldBlock.position)
      const origin = bot && bot.entity && bot.entity.position
      if (!changed || !origin) {
        defaultNearbyBlocksCache = null
        return
      }
      const dx = Number(changed.x) - Number(origin.x)
      const dy = Number(changed.y) - Number(origin.y)
      const dz = Number(changed.z) - Number(origin.z)
      const invalidationRadius = DEFAULT_NEARBY_BLOCK_RADIUS + 2
      if (Number.isFinite(dx) && Number.isFinite(dy) && Number.isFinite(dz) &&
          dx * dx + dy * dy + dz * dz <= invalidationRadius * invalidationRadius) {
        defaultNearbyBlocksCache = null
      }
    }
    bot.on('blockUpdate', boundBlockUpdateListener)
  }
}

function requireBot () {
  if (!bot || !bot.entity) throw new Error('bot not connected/spawned')
  return bot
}

function getBot () { return requireBot() }
function vec (value) { return value ? { x: Number(value.x), y: Number(value.y), z: Number(value.z) } : null }
function sleep (ms) {
  const scope = currentActionCancellationScope()
  return scope ? scope.sleep(ms) : baseSleep(ms)
}

function stopMotion () {
  if (!bot) return
  try { if (bot.pathfinder && typeof bot.pathfinder.stop === 'function') bot.pathfinder.stop() } catch (_) {}
  try { if (bot.pvp && typeof bot.pvp.stop === 'function') bot.pvp.stop() } catch (_) {}
  try { if (typeof bot.stopDigging === 'function') bot.stopDigging() } catch (_) {}
  try { if (typeof bot.clearControlStates === 'function') bot.clearControlStates() } catch (_) {}
}

function actionTerminalSettlementMs () {
  return ACTION_TERMINAL_SETTLEMENT_MS
}

function actionTimeoutMs (msg) {
  const raw = Number(msg && msg._action_timeout_ms)
  if (!Number.isFinite(raw) || raw <= 0) {
    const error = new Error('ACTION_TIMEOUT_REQUIRED')
    error.code = 'ACTION_TIMEOUT_REQUIRED'
    throw error
  }
  return Math.floor(raw)
}

function actionProviderWindowMs (msg) {
  if (msg && Object.prototype.hasOwnProperty.call(msg, '_action_provider_window_ms')) {
    const raw = Number(msg._action_provider_window_ms)
    if (!Number.isFinite(raw) || raw <= 0) {
      const error = new Error('ACTION_PROVIDER_WINDOW_REQUIRED')
      error.code = 'ACTION_PROVIDER_WINDOW_REQUIRED'
      throw error
    }
    return Math.floor(raw)
  }
  // Direct provider unit tests and standalone bridge probes predate the host
  // primitive-window field.  When they do supply the legacy whole-action
  // timeout, retain bounded behavior without inventing a second policy.
  if (msg && Object.prototype.hasOwnProperty.call(msg, '_action_timeout_ms')) {
    return actionTimeoutMs(msg)
  }
  return null
}

function actionRemainingMs (capMs = null) {
  const scope = currentActionCancellationScope()
  const deadlineMs = scope && Number.isFinite(Number(scope.deadlineMs))
    ? Number(scope.deadlineMs)
    : null
  const cap = capMs === null ? null : Number(capMs)
  if (cap !== null && (!Number.isFinite(cap) || cap <= 0)) {
    const error = new Error('ACTION_TIMEOUT_REQUIRED')
    error.code = 'ACTION_TIMEOUT_REQUIRED'
    throw error
  }
  if (deadlineMs === null && cap === null) {
    const error = new Error('ACTION_DEADLINE_REQUIRED')
    error.code = 'ACTION_DEADLINE_REQUIRED'
    throw error
  }
  const remaining = deadlineMs === null ? cap : deadlineMs - Date.now()
  if (!Number.isFinite(remaining) || remaining <= 0) {
    const error = new Error('ACTION_DEADLINE_EXCEEDED')
    error.code = 'ACTION_DEADLINE_EXCEEDED'
    throw error
  }
  return Math.floor(cap === null ? remaining : Math.min(remaining, cap))
}

function createActionProviderWindow (msg) {
  const declared = actionProviderWindowMs(msg)
  const scope = currentActionCancellationScope()
  if (declared === null && !scope) {
    return {
      timeout_ms: null,
      remainingMs: () => null
    }
  }
  const initial = actionRemainingMs(declared)
  const deadlineMs = Date.now() + initial
  return {
    timeout_ms: initial,
    remainingMs: () => {
      const localRemaining = deadlineMs - Date.now()
      if (!Number.isFinite(localRemaining) || localRemaining <= 0) {
        const error = new Error('ACTION_PROVIDER_WINDOW_EXCEEDED')
        error.code = 'ACTION_PROVIDER_WINDOW_EXCEEDED'
        throw error
      }
      return actionRemainingMs(localRemaining)
    }
  }
}


function waitForEventCondition (
  emitter,
  eventName,
  condition,
  capMs = null
) {
  if (!emitter || typeof emitter.on !== 'function' || typeof emitter.removeListener !== 'function') {
    throw new TypeError('event emitter is unavailable')
  }
  if (typeof condition !== 'function') {
    throw new TypeError('event condition must be callable')
  }

  const scope = currentActionCancellationScope()
  if (!scope) {
    const error = new Error('ACTION_DEADLINE_REQUIRED')
    error.code = 'ACTION_DEADLINE_REQUIRED'
    throw error
  }

  const childLimitMs = capMs === null ? null : actionRemainingMs(capMs)
  return new Promise((resolve, reject) => {
    let settled = false
    let timer = null
    let unregisterCancel = null

    const cleanup = () => {
      emitter.removeListener(eventName, onEvent)
      if (timer) clearTimeout(timer)
      if (unregisterCancel) unregisterCancel()
    }
    const settle = value => {
      if (settled) return
      settled = true
      cleanup()
      resolve(value)
    }
    const fail = error => {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }
    const check = args => {
      try {
        const value = condition(...args)
        if (value) settle(value)
      } catch (error) {
        fail(error)
      }
    }
    const onEvent = (...args) => check(args)

    emitter.on(eventName, onEvent)
    unregisterCancel = onActionCancel(
      'mineflayer:event:' + String(eventName),
      () => fail(new ActionCancelledError('ACTION_CANCELLED'))
    )

    // Close the race between current state and listener installation.
    check([])

    // A child timer exists only when the caller supplied a semantic cap
    // (for example max_wait_s). Normal provider waits are governed solely by
    // the outer action deadline.
    if (!settled && childLimitMs !== null) {
      timer = setTimeout(() => settle(null), childLimitMs)
    }
  })
}

function withTimeout (promise, timeoutMs, label, onTimeout = stopMotion) {
  const original = Promise.resolve(promise)
  const scope = currentActionCancellationScope()
  let originalSettled = false
  original.then(
    () => { originalSettled = true },
    () => { originalSettled = true }
  )
  return new Promise((resolve, reject) => {
    let settled = false
    let timer = null
    let unregisterInterrupt = () => {}
    const interrupt = async (reason, external) => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      unregisterInterrupt()
      const cleanupErrors = []
      try {
        const report = scope
          ? await scope.cancel(reason)
          : (onTimeout ? await onTimeout() : null)
        if (report && Array.isArray(report.errors)) {
          cleanupErrors.push(...report.errors.map(value =>
            String(value && value.message ? value.message : value)))
        }
        if (report && report.clean === false && cleanupErrors.length === 0) {
          cleanupErrors.push('ACTION_CANCEL_CLEANUP_FAILED')
        }
      } catch (error) {
        cleanupErrors.push(String(error && error.message ? error.message : error))
      }
      if (!originalSettled) {
        const quiesced = await Promise.race([
          original.then(() => true, () => true),
          baseSleep(ACTION_PROVIDER_QUIESCENCE_TIMEOUT_MS).then(() => false)
        ])
        if (!quiesced) cleanupErrors.push('ACTION_CANCEL_DID_NOT_SETTLE')
      }
      const code = external ? 'ACTION_INTERRUPTED' : label + '_TIMEOUT'
      const error = new Error(code)
      error.code = code
      if (cleanupErrors.length > 0) {
        error.cleanup_failed = true
        error.cleanup_errors = cleanupErrors
      }
      reject(error)
    }
    timer = setTimeout(() => { void interrupt(label + '_TIMEOUT', false) },
      Math.max(1, timeoutMs))
    if (scope) {
      unregisterInterrupt = scope.onInterrupt(
        () => { void interrupt(scope.reason || 'ACTION_INTERRUPTED', true) }
      )
    }
    original.then(value => {
      if (settled) return
      settled = true
      clearTimeout(timer)
      unregisterInterrupt()
      resolve(value)
    }, error => {
      if (settled) return
      // A cooperative wait may reject before its interrupt callback is
      // dispatched. Keep one stable interruption outcome in both orders.
      if (scope && scope.cancelled) {
        void interrupt(scope.reason || 'ACTION_INTERRUPTED', true)
        return
      }
      settled = true
      clearTimeout(timer)
      unregisterInterrupt()
      reject(error)
    })
  })
}

function itemSummary (item) {
  if (!item) return null
  const summary = { name: item.name, count: item.count, slot: item.slot }
  const maxDurability = Number(item.maxDurability)
  const durabilityUsed = Number(item.durabilityUsed)
  if (Number.isFinite(maxDurability) && maxDurability > 0) {
    summary.max_durability = maxDurability
    if (Number.isFinite(durabilityUsed)) {
      const boundedUsed = Math.max(0, Math.min(maxDurability, durabilityUsed))
      const remaining = maxDurability - boundedUsed
      summary.durability_used = boundedUsed
      summary.durability_remaining = remaining
      summary.durability_remaining_ratio = remaining / maxDurability
    }
  }
  return summary
}

function matchName (name, query) {
  if (!query) return false
  const q = String(query).toLowerCase()
  const n = String(name || '').toLowerCase()
  if (q.startsWith('re:')) return new RegExp(q.slice(3)).test(n)
  return n === q || n.includes(q)
}

function entityMatches (entity, query) {
  const raw = String(query == null ? '' : query).trim().toLowerCase()
  if (!raw) return false
  if (raw.startsWith('re:')) {
    const pattern = new RegExp(raw.slice(3))
    return [entity.name, entity.username, entity.displayName, entity.type]
      .some(value => pattern.test(String(value == null ? '' : value).toLowerCase()))
  }
  return [entity.name, entity.username, entity.displayName, entity.type]
    .some(value => String(value == null ? '' : value).trim().toLowerCase() === raw)
}

function findEntity (query, maxDistance = 32, predicate = null) {
  const activeBot = requireBot()
  const entities = activeBot.entities || {}
  const origin = activeBot.entity.position
  let nearest = null
  let bestDistance = Number(maxDistance)
  // A nearest-neighbor query over the live entity map does not need sorting.
  // Keep the first encountered entity on ties, matching stable-sort semantics.
  // This is O(N) time and O(1) auxiliary space, independent of entity count.
  for (const key in entities) {
    if (!Object.prototype.hasOwnProperty.call(entities, key)) continue
    const entity = entities[key]
    if (!entity || entity === activeBot.entity || !entity.position || entity.isValid === false) continue
    if (query && !entityMatches(entity, query)) continue
    if (predicate && !predicate(entity)) continue
    const distance = entity.position.distanceTo(origin)
    if (distance > bestDistance || (nearest !== null && distance === bestDistance)) continue
    nearest = entity
    bestDistance = distance
  }
  return nearest
}

function waitForPhysicsTicks (count = 1, timeoutMs = null) {
  const activeBot = requireBot()
  const target = Math.max(1, Math.floor(Number(count)))
  const scope = currentActionCancellationScope()
  const childLimitMs = timeoutMs === null ? null : actionRemainingMs(timeoutMs)
  if (!scope && childLimitMs === null) {
    const error = new Error('ACTION_DEADLINE_REQUIRED')
    error.code = 'ACTION_DEADLINE_REQUIRED'
    throw error
  }
  return new Promise((resolve, reject) => {
    let ticks = 0
    let settled = false
    let timer = null
    let unregisterCancel = null
    const cleanup = () => {
      activeBot.removeListener('physicsTick', onTick)
      if (timer) clearTimeout(timer)
      if (unregisterCancel) unregisterCancel()
    }
    const finish = () => {
      if (settled) return
      settled = true
      cleanup()
      resolve(ticks)
    }
    const fail = error => {
      if (settled) return
      settled = true
      cleanup()
      reject(error)
    }
    const onTick = () => {
      ticks += 1
      if (ticks >= target) finish()
    }
    activeBot.on('physicsTick', onTick)
    unregisterCancel = onActionCancel(
      'mineflayer:physics-ticks',
      () => fail(new ActionCancelledError('ACTION_CANCELLED'))
    )
    if (childLimitMs !== null) {
      timer = setTimeout(() => {
        const error = new Error('ACTION_PROVIDER_WINDOW_EXCEEDED')
        error.code = 'ACTION_PROVIDER_WINDOW_EXCEEDED'
        fail(error)
      }, childLimitMs)
    }
  })
}

function captureInventoryIncrease (names, beforeInventory) {
  const activeBot = requireBot()
  const expectedNames = [...new Set(
    (Array.isArray(names) ? names : [names]).map(String).filter(Boolean)
  )]
  if (expectedNames.length === 0) {
    throw new TypeError('inventory increase capture requires at least one item name')
  }
  const inventory = activeBot.inventory
  if (!inventory || typeof inventory.on !== 'function' || typeof inventory.removeListener !== 'function') {
    return null
  }
  actionRemainingMs()
  const before = Object.fromEntries(
    expectedNames.map(name => [name, Number((beforeInventory && beforeInventory[name]) || 0)])
  )
  const current = () => {
    for (const name of expectedNames) {
      const count = inventoryCount(name)
      const delta = count - before[name]
      if (delta > 0) return { name, delta, count, before: before[name] }
    }
    return null
  }
  let settled = false
  let unregisterCancel = null
  let resolvePromise
  const promise = new Promise(resolve => { resolvePromise = resolve })
  const finish = value => {
    if (settled) return
    settled = true
    if (unregisterCancel) unregisterCancel()
    inventory.removeListener('updateSlot', onUpdate)
    resolvePromise(value)
  }
  const onUpdate = () => {
    const proof = current()
    if (proof) finish(proof)
  }
  inventory.on('updateSlot', onUpdate)
  unregisterCancel = onActionCancel(
    'mineflayer:inventory-increase-capture',
    () => finish(null)
  )
  onUpdate()
  return { promise, current, cancel: () => finish(null) }
}

function waitForInventoryIncrease (name, before, timeoutMs = null) {
  const activeBot = requireBot()
  const initial = inventoryCount(name)
  if (initial > before) return Promise.resolve(initial - before)
  const scope = currentActionCancellationScope()
  if (!scope) {
    const error = new Error('ACTION_DEADLINE_REQUIRED')
    error.code = 'ACTION_DEADLINE_REQUIRED'
    throw error
  }
  const inventory = activeBot.inventory
  if (!inventory || typeof inventory.on !== 'function' || typeof inventory.removeListener !== 'function') {
    const error = new Error('MINEFLAYER_INVENTORY_EVENT_UNAVAILABLE')
    error.code = 'MINEFLAYER_INVENTORY_EVENT_UNAVAILABLE'
    throw error
  }
  const subTimeout = timeoutMs == null ? null : actionRemainingMs(timeoutMs)
  return new Promise(resolve => {
    let settled = false
    let timer = null
    let unregisterCancel = null
    const finish = () => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      if (unregisterCancel) unregisterCancel()
      inventory.removeListener('updateSlot', onUpdate)
      resolve(Math.max(0, inventoryCount(name) - before))
    }
    const onUpdate = () => {
      if (inventoryCount(name) > before) finish()
    }
    inventory.on('updateSlot', onUpdate)
    unregisterCancel = onActionCancel(
      'mineflayer:inventory-increase',
      finish
    )
    if (subTimeout != null) timer = setTimeout(finish, subTimeout)
    onUpdate()
  })
}

// The versioned registry is declared, static Minecraft data. Cache only the
// immutable set of matching block IDs; NEVER cache physical block positions,
// loaded chunks or actual world observations, which may change each tick.
const observedBlockMatcherCache = new WeakMap()
const OBSERVED_BLOCK_MATCHER_CACHE_LIMIT = 128
const AIR_BLOCK_NAMES = new Set(['air', 'cave_air', 'void_air'])

function observedBlockRegistryIds (blockRegistry, normalizedQuery) {
  if (blockRegistry == null || typeof blockRegistry !== 'object') return []
  let cache = observedBlockMatcherCache.get(blockRegistry)
  if (cache !== undefined && cache.has(normalizedQuery)) {
    const hit = cache.get(normalizedQuery)
    cache.delete(normalizedQuery)
    cache.set(normalizedQuery, hit)
    return hit
  }
  const matchingIds = Object.freeze([...new Set(
    Object.values(blockRegistry)
      .filter(block => block && block.name && !AIR_BLOCK_NAMES.has(String(block.name)))
      .filter(block => !normalizedQuery || String(block.name).includes(normalizedQuery))
      .map(block => Number(block.id))
      .filter(Number.isFinite)
  )])
  if (cache === undefined) {
    cache = new Map()
    observedBlockMatcherCache.set(blockRegistry, cache)
  }
  cache.set(normalizedQuery, matchingIds)
  if (cache.size > OBSERVED_BLOCK_MATCHER_CACHE_LIMIT) {
    cache.delete(cache.keys().next().value)
  }
  return matchingIds
}

function observeBlocks (query = null, maxDistance = 16, limit = 32) {
  const activeBot = requireBot()
  const normalizedQuery = query == null ? '' : String(query).trim().toLowerCase()
  const matchingIds = observedBlockRegistryIds(
    activeBot.registry.blocksByName, normalizedQuery
  )
  if (matchingIds.length === 0) {
    return {
      truth_class: 'observed',
      authoritative_for_current_world: true,
      query: normalizedQuery || null,
      registry_match_count: 0,
      searched_max_distance: Number(maxDistance),
      observed_count: 0,
      blocks: [],
      counts: {}
    }
  }
  const requestedLimit = Math.max(1, Number(limit))
  // Unfiltered observations must not be exhausted by the nearest ground
  // blocks. Sample a bounded, larger physical frontier and retain a
  // distance-ordered representative of each observed block type.
  const candidateLimit = normalizedQuery
    ? requestedLimit
    : Math.max(requestedLimit, Math.min(512, requestedLimit * 16))
  const positions = activeBot.findBlocks({
    matching: matchingIds,
    maxDistance: Number(maxDistance),
    count: candidateLimit
  })
  const origin = activeBot.entity.position
  const rows = (Array.isArray(positions) ? positions : [])
    .map(position => activeBot.blockAt(position))
    .filter(block => block && block.position && block.name)
    .map(block => {
      const name = String(block.name)
      const row = {
        name,
        position: vec(block.position),
        distance: block.position.distanceTo(origin),
        metadata: Number.isFinite(Number(block.metadata))
          ? Number(block.metadata)
          : null,
        waterlogged: block.isWaterlogged === true
      }
      if (name === 'water' || name === 'lava') {
        row.fluid_state = Number(block.metadata) === 0 ? 'source' : 'flowing'
      }
      return row
    })
    .sort((left, right) => (
      left.distance - right.distance ||
      left.name.localeCompare(right.name) ||
      left.position.x - right.position.x ||
      left.position.y - right.position.y ||
      left.position.z - right.position.z
    ))
  let selected = rows.slice(0, requestedLimit)
  if (!normalizedQuery) {
    const byName = new Map()
    for (const row of rows) {
      if (!byName.has(row.name)) byName.set(row.name, [])
      byName.get(row.name).push(row)
    }
    selected = []
    for (let depth = 0; selected.length < requestedLimit; depth++) {
      let emitted = false
      for (const entries of byName.values()) {
        if (depth >= entries.length) continue
        selected.push(entries[depth])
        emitted = true
        if (selected.length >= requestedLimit) break
      }
      if (!emitted) break
    }
  }
  const counts = {}
  for (const row of selected) counts[row.name] = Number(counts[row.name] || 0) + 1
  return {
    truth_class: 'observed',
    authoritative_for_current_world: true,
    loaded_world_only: true,
    query: normalizedQuery || null,
    registry_match_count: matchingIds.length,
    searched_max_distance: Number(maxDistance),
    sampling: normalizedQuery ? 'closest' : 'nearest-per-observed-type',
    candidate_count: rows.length,
    observed_count: selected.length,
    blocks: selected,
    counts: Object.fromEntries(Object.entries(counts).sort(([a], [b]) => a.localeCompare(b)))
  }
}

function observeExactBlock (position, maxDistance = 16) {
  const activeBot = requireBot()
  const target = position instanceof Vec3
    ? position
    : new Vec3(Number(position && position.x), Number(position && position.y), Number(position && position.z))
  if (![target.x, target.y, target.z].every(Number.isSafeInteger)) {
    throw new TypeError('exact block observation requires integer coordinates')
  }
  const distance = target.distanceTo(activeBot.entity.position)
  const bound = Number(maxDistance)
  if (!Number.isFinite(bound) || bound < 1 || bound > 128) {
    throw new TypeError('exact block observation maxDistance must be in [1, 128]')
  }
  if (distance > bound) {
    return {
      truth_class: 'observed',
      authoritative_for_current_world: true,
      loaded_world_only: true,
      exact_position: vec(target),
      searched_max_distance: bound,
      distance,
      observed: false,
      observation_constraint: 'out_of_range'
    }
  }
  const block = activeBot.blockAt(target)
  if (!block || !block.position || !block.name) {
    return {
      truth_class: 'observed',
      authoritative_for_current_world: true,
      loaded_world_only: true,
      exact_position: vec(target),
      searched_max_distance: bound,
      distance,
      observed: false,
      observation_constraint: 'not_loaded_or_unobserved'
    }
  }
  const name = String(block.name)
  const row = {
    name,
    position: vec(block.position),
    distance,
    metadata: Number.isFinite(Number(block.metadata)) ? Number(block.metadata) : null,
    waterlogged: block.isWaterlogged === true
  }
  if (name === 'water' || name === 'lava') {
    row.fluid_state = Number(block.metadata) === 0 ? 'source' : 'flowing'
  }
  return {
    truth_class: 'observed',
    authoritative_for_current_world: true,
    loaded_world_only: true,
    exact_position: vec(target),
    searched_max_distance: bound,
    distance,
    observed: true,
    block: row
  }
}

function defaultNearbyBlocksProjection (maxDistance = 16, limit = 12) {
  const activeBot = requireBot()
  const distance = Number(maxDistance)
  const requestedLimit = Number(limit)
  if (!Number.isFinite(distance) || distance <= 0 ||
      !Number.isInteger(requestedLimit) || requestedLimit <= 0) {
    throw new TypeError('default nearby-block projection requires positive bounded arguments')
  }
  const position = activeBot.entity.position
  const dimension = activeBot.game && activeBot.game.dimension != null
    ? String(activeBot.game.dimension) : ''
  const key = [
    dimension, Math.floor(Number(position.x)), Math.floor(Number(position.y)),
    Math.floor(Number(position.z)), distance, requestedLimit
  ].join(':')
  if (defaultNearbyBlocksCache && defaultNearbyBlocksCache.key === key) {
    return defaultNearbyBlocksCache.value
  }
  const value = observeBlocks(null, distance, requestedLimit)
  defaultNearbyBlocksCache = { key, value }
  return value
}

function inventoryCount (name) {
  const activeBot = requireBot()
  return activeBot.inventory.items()
    .filter(item => item.name === name)
    .reduce((total, item) => total + item.count, 0)
}

function inventoryMap () {
  const activeBot = requireBot()
  const out = {}
  for (const item of activeBot.inventory.items()) out[item.name] = (out[item.name] || 0) + item.count
  return out
}

function inventoryDelta (before, after) {
  const out = {}
  for (const name of new Set([...Object.keys(before), ...Object.keys(after)])) {
    const delta = Number(after[name] || 0) - Number(before[name] || 0)
    if (delta !== 0) out[name] = delta
  }
  return out
}

function isDroppedItemEntity (entity) {
  if (!entity || !entity.position || entity.isValid === false) return false
  if (typeof entity.getDroppedItem === 'function') {
    try { if (entity.getDroppedItem()) return true } catch (_) {}
  }
  const name = String(entity.name || '').toLowerCase()
  return name === 'item' || name === 'item_stack'
}

function droppedItemName (entity) {
  if (!isDroppedItemEntity(entity) || typeof entity.getDroppedItem !== 'function') return null
  try {
    const item = entity.getDroppedItem()
    return item && item.name ? String(item.name) : null
  } catch (_) {
    return null
  }
}

function captureItemDropNear (position, itemName = null, maxDistance = 0.5) {
  const expectedNames = Array.isArray(itemName)
    ? itemName.map(String).filter(Boolean)
    : itemName ? [String(itemName)] : []
  const matchesExpectedName = name => expectedNames.length === 0 || (name != null && expectedNames.includes(name))
  const activeBot = requireBot()
  const blockPos = position instanceof Vec3 ? position : new Vec3(Number(position.x), Number(position.y), Number(position.z))
  const center = blockPos.offset(0.5, 0.5, 0.5)
  // Mineflayer 4.37.1 emits entitySpawn from spawn_entity before itemDrop,
  // which is emitted later from entity_metadata carrying item_stack. Track both
  // lifecycle stages so fast pickup cannot erase the drop before metadata arrives.
  const candidates = []
  const spawnCandidates = []
  const collectionCandidates = []
  // One block action may correlate only a bounded number of nearby drop entities.
  // Keeping the fallback set fixed-size makes pickup selection constant-time and
  // fail-closed under anomalous/adversarial entity floods instead of scanning
  // world-sized state. Sixteen slots is intentionally generous for one block drop.
  const trackedSlots = [
    null, null, null, null, null, null, null, null,
    null, null, null, null, null, null, null, null
  ]
  const trackedSlotById = new Map()
  const freeTrackedSlots = [15, 14, 13, 12, 11, 10, 9, 8, 7, 6, 5, 4, 3, 2, 1, 0]
  const collectedByBot = new Set()
  let trackedOverflow = false
  const trackEntity = entity => {
    if (!entity || entity.id == null) return false
    const existing = trackedSlotById.get(entity.id)
    if (existing != null) {
      trackedSlots[existing] = entity
      return true
    }
    const slot = freeTrackedSlots.pop()
    if (slot == null) {
      trackedOverflow = true
      return false
    }
    trackedSlots[slot] = entity
    trackedSlotById.set(entity.id, slot)
    return true
  }
  const untrackEntity = entity => {
    if (!entity || entity.id == null) return
    const slot = trackedSlotById.get(entity.id)
    if (slot == null) return
    trackedSlotById.delete(entity.id)
    trackedSlots[slot] = null
    freeTrackedSlots.push(slot)
  }
  const protocolPackets = []
  const tracedPacketNames = new Set([
    'spawn_entity', 'entity_metadata', 'collect', 'set_slot',
    'window_items', 'entity_destroy', 'block_change'
  ])
  let settled = false
  let unregisterCancellation = () => {}
  let resolvePromise
  const promise = new Promise(resolve => { resolvePromise = resolve })
  const finish = entity => {
    if (settled) return
    settled = true
    unregisterCancellation()
    activeBot.removeListener('itemDrop', onDrop)
    resolvePromise(entity)
  }
  const association = entity => {
    const dropped = isDroppedItemEntity(entity)
    const distance = entity && entity.position ? entity.position.distanceTo(center) : null
    return { dropped, distance, within: dropped && distance != null && distance <= maxDistance }
  }
  const onProtocolPacket = (data, metadata) => {
    const name = metadata && metadata.name ? String(metadata.name) : ''
    if (!tracedPacketNames.has(name)) return
    const packet = { sequence: protocolPackets.length + 1, packet: name }
    if (data && data.entityId != null) packet.entity_id = data.entityId
    if (data && data.collectedEntityId != null) packet.collected_entity_id = data.collectedEntityId
    if (data && data.collectorEntityId != null) packet.collector_entity_id = data.collectorEntityId
    if (data && data.pickupItemCount != null) packet.pickup_item_count = data.pickupItemCount
    if (data && data.type != null && name === 'spawn_entity') packet.entity_type = data.type
    if (data && data.x != null) packet.x = data.x
    if (data && data.y != null) packet.y = data.y
    if (data && data.z != null) packet.z = data.z
    if (data && data.windowId != null) packet.window_id = data.windowId
    if (data && data.slot != null) packet.slot = data.slot
    if (data && Array.isArray(data.entityIds)) packet.entity_ids = data.entityIds.slice()
    if (data && Array.isArray(data.metadata)) packet.metadata_types = data.metadata.map(row => row.type)
    if (data && Array.isArray(data.items)) packet.item_slots = data.items.length
    if (data && data.item) packet.item_count = data.item.itemCount ?? data.item.count ?? null
    protocolPackets.push(packet)
  }
  const onSpawn = entity => {
    const row = association(entity)
    if (!row.dropped) return
    spawnCandidates.push({
      entity_id: entity.id ?? null,
      item_name: droppedItemName(entity),
      position: vec(entity.position),
      distance_to_block_center: row.distance,
      matched: row.within
    })
    if (row.within && entity.id != null) trackEntity(entity)
  }
  const onDrop = entity => {
    const dropped = isDroppedItemEntity(entity)
    const observedName = dropped ? droppedItemName(entity) : null
    const distance = entity && entity.position ? entity.position.distanceTo(center) : null
    const candidate = {
      entity_id: entity && entity.id != null ? entity.id : null,
      item_name: observedName,
      position: entity && entity.position ? vec(entity.position) : null,
      distance_to_block_center: distance,
      is_valid: Boolean(entity && entity.isValid !== false),
      matched: false,
      rejection: null
    }
    if (!dropped) candidate.rejection = 'NOT_DROPPED_ITEM_ENTITY'
    else if (distance == null || distance > maxDistance) candidate.rejection = 'OUTSIDE_ASSOCIATION_RADIUS'
    else if (!matchesExpectedName(observedName)) candidate.rejection = 'ITEM_NAME_MISMATCH'
    else candidate.matched = true
    candidates.push(candidate)
    if (dropped && distance != null && distance <= maxDistance && entity.id != null) {
      if (observedName == null || matchesExpectedName(observedName)) trackEntity(entity)
      else untrackEntity(entity)
    }
    if (candidate.matched) finish(entity)
  }
  const onCollect = (collector, collected) => {
    const own = Boolean(collector && activeBot.entity && collector.id === activeBot.entity.id)
    const tracked = Boolean(collected && collected.id != null && trackedSlotById.has(collected.id))
    if (!tracked) return
    collectionCandidates.push({
      entity_id: collected.id,
      item_name: droppedItemName(collected),
      position: collected.position ? vec(collected.position) : null,
      own_collector: own,
      tracked: true
    })
    if (own) {
      collectedByBot.add(collected.id)
      untrackEntity(collected)
    }
  }
  const onGone = entity => {
    untrackEntity(entity)
  }
  if (activeBot._client && typeof activeBot._client.on === 'function') {
    activeBot._client.on('packet', onProtocolPacket)
  }
  activeBot.on('entitySpawn', onSpawn)
  activeBot.on('itemDrop', onDrop)
  activeBot.on('playerCollect', onCollect)
  activeBot.on('entityGone', onGone)
  const cancel = () => {
    activeBot.removeListener('entitySpawn', onSpawn)
    activeBot.removeListener('playerCollect', onCollect)
    activeBot.removeListener('entityGone', onGone)
    if (activeBot._client && typeof activeBot._client.removeListener === 'function') {
      activeBot._client.removeListener('packet', onProtocolPacket)
    }
    finish(null)
  }
  unregisterCancellation = onActionCancel('mineflayer:item-drop-capture', cancel)
  const pickupTarget = () => {
    if (trackedOverflow) return null
    const boundedCandidates = [
      trackedSlots[0], trackedSlots[1], trackedSlots[2], trackedSlots[3],
      trackedSlots[4], trackedSlots[5], trackedSlots[6], trackedSlots[7],
      trackedSlots[8], trackedSlots[9], trackedSlots[10], trackedSlots[11],
      trackedSlots[12], trackedSlots[13], trackedSlots[14], trackedSlots[15]
    ]
    let nearest = null
    let nearestDistance = Infinity
    for (const entity of boundedCandidates) {
      if (!entity || entity.isValid === false || collectedByBot.has(entity.id)) continue
      const name = droppedItemName(entity)
      if (expectedNames.length > 0 && name != null && !expectedNames.includes(name)) continue
      const distance = entity.position.distanceTo(activeBot.entity.position)
      if (distance < nearestDistance) {
        nearest = entity
        nearestDistance = distance
      }
    }
    return nearest
  }
  return {
    promise,
    cancel,
    candidates,
    spawn_candidates: spawnCandidates,
    collection_candidates: collectionCandidates,
    protocol_packets: protocolPackets,
    pickupTarget,
    hasCandidateOverflow: () => trackedOverflow,
    hasOwnCollection: () => collectedByBot.size > 0
  }
}

function findNearbyDroppedItem (position, maxDistance = 6) {
  const activeBot = requireBot()
  const origin = position instanceof Vec3 ? position : new Vec3(Number(position.x), Number(position.y), Number(position.z))
  let nearest = null
  let nearestBotDistance = Infinity
  for (const entity of Object.values(activeBot.entities || {})) {
    if (entity === activeBot.entity || !isDroppedItemEntity(entity)) continue
    if (entity.position.distanceTo(origin) > maxDistance) continue
    const botDistance = entity.position.distanceTo(activeBot.entity.position)
    if (botDistance < nearestBotDistance) {
      nearest = entity
      nearestBotDistance = botDistance
    }
  }
  return nearest
}

function findInventoryItem (name) {
  return requireBot().inventory.items().find(item => item.name === name) || null
}

function applyMovements (activeBot, value) {
  if (activeBot.pathfinder && typeof activeBot.pathfinder.setMovements === 'function') {
    activeBot.pathfinder.setMovements(value)
    return
  }
  if (activeBot.pathfinder && activeBot.pathfinder.movements) return
  throw new Error('PATHFINDER_MOVEMENTS_UNAVAILABLE')
}

// A weak-keyed capability projection is shared only by checks that borrow
// the same movement instance; physical world blocks are NEVER cached.
const explicitHarvestMovements = new WeakMap()

function safeToHarvestBlock (block) {
  const activeBot = requireBot()
  const nav = activeBot.pathfinder && activeBot.pathfinder.movements
  if (!block || !nav || typeof nav.safeToBreak !== 'function') return false
  // Navigation deliberately forbids incidental digging. Mineflayer's
  // safeToBreak() checks canDig before inspecting any physical hazard:
  // invoking it directly would therefore reject *every* explicitly
  // requested collect_block, irrespective of terrain or held tool.
  //
  // Borrow the SINGLE native safety oracle under a per-call capability
  // projection. This never mutates the live navigation configuration,
  // permits no unrequested digging, and keeps every actual physical
  // exclusion: fluid flow, falling blocks, occupied blocks, forbidden
  // block types and exclusionBreak.
  if (nav.canDig !== false) return Boolean(nav.safeToBreak(block))
  let explicitHarvest = explicitHarvestMovements.get(nav)
  if (explicitHarvest === undefined) {
    explicitHarvest = Object.create(nav)
    explicitHarvest.canDig = true
    explicitHarvestMovements.set(nav, explicitHarvest)
  }
  return Boolean(nav.safeToBreak.call(explicitHarvest, block))
}

async function ensureMovements () {
  const activeBot = requireBot()
  if (!movements) {
    // The physical movement primitive may not perform unrequested digging,
    // door activation or tower-block placement. Method owns those actions.
    // Build one reusable movement model per bound bot, not for each goal.
    const baseline = activeBot.pathfinder.movements || new Movements(activeBot)
    // A borrowed pathfinder movement configuration belongs to its owner.
    // Keep a derived, independently mutable configuration; never change the
    // host bot's initial settings in order to perform one Noetrium action.
    movements = Object.assign(Object.create(Object.getPrototypeOf(baseline)), baseline)
    movements.canDig = false
    movements.canOpenDoors = false
    movements.allow1by1towers = false
  }
  applyMovements(activeBot, movements)
}

function pathStatus (value) {
  return value && typeof value.status === 'string' ? value.status : 'unknown'
}


function observePathfinderExecution (activeBot) {
  const evidence = {
    path_update_count: 0,
    path_status_counts: {},
    path_reset_count: 0,
    path_reset_reasons: {},
    path_stop_count: 0,
    goal_reached_count: 0
  }
  if (!activeBot || typeof activeBot.on !== 'function' || typeof activeBot.removeListener !== 'function') {
    return { evidence, close: () => {} }
  }
  const onUpdate = result => {
    evidence.path_update_count += 1
    const status = pathStatus(result)
    evidence.path_status_counts[status] = Number(evidence.path_status_counts[status] || 0) + 1
  }
  const onReset = reason => {
    evidence.path_reset_count += 1
    const key = String(reason || 'unknown')
    evidence.path_reset_reasons[key] = Number(evidence.path_reset_reasons[key] || 0) + 1
  }
  const onStop = () => { evidence.path_stop_count += 1 }
  const onReached = () => { evidence.goal_reached_count += 1 }
  activeBot.on('path_update', onUpdate)
  activeBot.on('path_reset', onReset)
  activeBot.on('path_stop', onStop)
  activeBot.on('goal_reached', onReached)
  return {
    evidence,
    close: () => {
      activeBot.removeListener('path_update', onUpdate)
      activeBot.removeListener('path_reset', onReset)
      activeBot.removeListener('path_stop', onStop)
      activeBot.removeListener('goal_reached', onReached)
    }
  }
}

async function navigateGoal (goal, timeoutMs, label) {
  const activeBot = requireBot()
  const priorMovements = activeBot.pathfinder.movements
  await ensureMovements()
  const pathfinderObservation = observePathfinderExecution(activeBot)
  const started = process.hrtime.bigint()
  try {
    // Exactly one native pathfinder search and execution, under the
    // already-authorized Action Scope. No duplicate getPathTo probes, hidden
    // door activations or provider-selected retries.
    await withTimeout(
      activeBot.pathfinder.goto(goal),
      actionRemainingMs(timeoutMs),
      label
    )
    return {
      navigation_mode: 'single_non_destructive_pathfinder',
      pathfinder_elapsed_ms: Number(process.hrtime.bigint() - started) / 1e6,
      pathfinder_evidence: pathfinderObservation.evidence
    }
  } finally {
    pathfinderObservation.close()
    if (priorMovements) applyMovements(activeBot, priorMovements)
  }
}

async function moveAwayFromEntity (entity, distance, timeoutMs = null) {
  const activeBot = requireBot()
  if (!entity || entity.isValid === false || !entity.position) {
    throw new Error('ENTITY_TARGET_INVALID')
  }
  const boundedDistance = Math.max(0, Number(distance))
  const goal = new GoalInvert(new GoalFollow(entity, boundedDistance))
  const navigation = await navigateGoal(
    goal,
    actionRemainingMs(timeoutMs),
    'PATHFINDER_AVOID_ENTITY'
  )
  const live = activeBot.entities && activeBot.entities[entity.id]
    ? activeBot.entities[entity.id]
    : entity
  const node = activeBot.entity.position.floored()
  return {
    entity_id: entity.id,
    position: vec(activeBot.entity.position),
    entity_position: live && live.position ? vec(live.position) : null,
    distance: (
      live && live.position
        ? live.position.distanceTo(activeBot.entity.position)
        : null
    ),
    goal_satisfied: goal.isEnd(node),
    ...navigation
  }
}

async function gotoEntity (entity, radius = 0, timeoutMs = null) {
  const activeBot = requireBot()
  if (!entity || entity.isValid === false || !entity.position) throw new Error('ENTITY_TARGET_INVALID')
  await ensureMovements()
  const boundedRadius = Math.max(0, Number(radius))
  const goal = new GoalFollow(entity, boundedRadius)
  const navigation = await navigateGoal(
    goal,
    actionRemainingMs(timeoutMs),
    'PATHFINDER_FOLLOW'
  )
  const live = activeBot.entities && activeBot.entities[entity.id] ? activeBot.entities[entity.id] : entity
  const node = activeBot.entity.position.floored()
  return {
    entity_id: entity.id,
    position: vec(live.position),
    valid: live.isValid !== false,
    goal_satisfied: goal.isEnd(node),
    ...navigation
  }
}

async function followEntityFor (entity, radius, durationMs) {
  const activeBot = requireBot()
  if (!entity || entity.isValid === false || !entity.position) {
    throw new Error('ENTITY_TARGET_INVALID')
  }
  if (!activeBot.pathfinder || typeof activeBot.pathfinder.setGoal !== 'function') {
    throw new Error('PATHFINDER_DYNAMIC_GOAL_UNAVAILABLE')
  }
  const boundedRadius = Math.max(0, Number(radius))
  const boundedDurationMs = actionRemainingMs(durationMs)
  const priorMovements = activeBot.pathfinder.movements
  await ensureMovements()
  const goal = new GoalFollow(entity, boundedRadius)
  const observation = observePathfinderExecution(activeBot)
  const started = process.hrtime.bigint()
  let targetGone = false
  try {
    // GoalFollow already owns moving-target invalidation. Dynamic mode lets
    // mineflayer-pathfinder update/replan from its native physics/event loop;
    // Noetrium must not poll the entity and repeatedly launch static gotos.
    activeBot.pathfinder.setGoal(goal, true)
    targetGone = Boolean(await waitForEventCondition(
      activeBot,
      'entityGone',
      gone => {
        const live = activeBot.entities && activeBot.entities[entity.id]
        if (gone && gone.id === entity.id) return true
        return !live || live.isValid === false || !live.position
      },
      boundedDurationMs
    ))
  } finally {
    // Retire only the goal installed by this action. Actor serialization means
    // another physical action should not overlap, but identity checking keeps
    // cleanup from clobbering an independently replaced goal if that invariant
    // is ever relaxed.
    if (activeBot.pathfinder.goal === goal) activeBot.pathfinder.setGoal(null)
    observation.close()
    if (priorMovements) applyMovements(activeBot, priorMovements)
  }
  const live = activeBot.entities && activeBot.entities[entity.id]
    ? activeBot.entities[entity.id]
    : null
  const finalDistance = live && live.position
    ? live.position.distanceTo(activeBot.entity.position)
    : null
  return {
    entity_id: entity.id,
    target_gone: targetGone,
    final_distance: finalDistance,
    goal_satisfied: finalDistance !== null && finalDistance <= boundedRadius,
    duration_ms: Number(process.hrtime.bigint() - started) / 1e6,
    navigation_mode: 'dynamic_goal_follow',
    pathfinder_evidence: observation.evidence
  }
}

function waitForOwnCollection (entity, timeoutMs = null) {
  const activeBot = requireBot()
  const targetId = entity && entity.id
  const subTimeout = timeoutMs == null ? null : actionRemainingMs(timeoutMs)
  // Validate that an outer action deadline exists even when no shorter local
  // bound is requested.
  if (timeoutMs == null) actionRemainingMs()
  return new Promise(resolve => {
    let settled = false
    let timer = null
    let unregisterCancel = null
    const finish = value => {
      if (settled) return
      settled = true
      if (timer) clearTimeout(timer)
      if (unregisterCancel) unregisterCancel()
      activeBot.removeListener('playerCollect', onCollect)
      resolve(value)
    }
    const onCollect = (collector, collected) => {
      if (
        collector &&
        collected &&
        collector.id === activeBot.entity.id &&
        collected.id === targetId
      ) finish(true)
    }
    activeBot.on('playerCollect', onCollect)
    unregisterCancel = onActionCancel(
      'mineflayer:player-collect-observer',
      () => finish(false)
    )
    if (subTimeout != null) timer = setTimeout(() => finish(false), subTimeout)
  })
}

async function gotoPos (position, radius = 1.5, timeoutMs = null) {
  const activeBot = requireBot()
  await ensureMovements()
  const target = new Vec3(Number(position.x), Number(position.y), Number(position.z))
  const boundedRadius = Math.max(1, Number(radius))
  const goal = new GoalNear(
    Math.floor(target.x),
    Math.floor(target.y),
    Math.floor(target.z),
    boundedRadius
  )
  const navigation = await navigateGoal(
    goal,
    actionRemainingMs(timeoutMs),
    'PATHFINDER_GOTO'
  )
  const distance = activeBot.entity.position.distanceTo(target)
  const node = activeBot.entity.position.floored()
  return {
    target: vec(target),
    position: vec(activeBot.entity.position),
    distance,
    within_radius: goal.isEnd(node),
    goal_satisfied: goal.isEnd(node),
    ...navigation
  }
}

function integerPositionKey (x, y, z) {
  return String(x) + ',' + String(y) + ',' + String(z)
}

function compareKdPoint (axis) {
  const otherA = (axis + 1) % 3
  const otherB = (axis + 2) % 3
  const fields = ['x', 'y', 'z']
  return (left, right) => (
    left[fields[axis]] - right[fields[axis]] ||
    left[fields[otherA]] - right[fields[otherA]] ||
    left[fields[otherB]] - right[fields[otherB]] ||
    left.id - right.id
  )
}

function buildBalancedKdTree (points) {
  if (!Array.isArray(points) || points.length === 0) return null
  const sorted = [0, 1, 2].map(axis => (
    points.slice().sort(compareKdPoint(axis))
  ))

  function build (axisSorted) {
    const size = axisSorted[0].length
    if (size === 0) return null
    let axis = 0
    let bestSpan = -Infinity
    for (let candidateAxis = 0; candidateAxis < 3; candidateAxis += 1) {
      const rows = axisSorted[candidateAxis]
      const field = ['x', 'y', 'z'][candidateAxis]
      const span = rows[rows.length - 1][field] - rows[0][field]
      if (span > bestSpan) {
        bestSpan = span
        axis = candidateAxis
      }
    }
    const axisRows = axisSorted[axis]
    const middle = Math.floor(size / 2)
    const point = axisRows[middle]
    const leftIds = new Set(axisRows.slice(0, middle).map(row => row.id))
    const leftSorted = axisSorted.map(rows => rows.filter(row => leftIds.has(row.id)))
    const rightSorted = axisSorted.map(rows => rows.filter(
      row => row.id !== point.id && !leftIds.has(row.id)
    ))
    return {
      axis,
      point,
      left: build(leftSorted),
      right: build(rightSorted)
    }
  }

  return build(sorted)
}

function nearestKdDistanceSquared (tree, query, best = Infinity) {
  if (!tree) return best
  const dx = query.x - tree.point.x
  const dy = query.y - tree.point.y
  const dz = query.z - tree.point.z
  let nextBest = Math.min(best, dx * dx + dy * dy + dz * dz)
  const field = ['x', 'y', 'z'][tree.axis]
  const delta = query[field] - tree.point[field]
  const near = delta <= 0 ? tree.left : tree.right
  const far = delta <= 0 ? tree.right : tree.left
  nextBest = nearestKdDistanceSquared(near, query, nextBest)
  if (delta * delta < nextBest) {
    nextBest = nearestKdDistanceSquared(far, query, nextBest)
  }
  return nextBest
}

const GET_TO_BLOCK_END_OFFSETS = Object.freeze([
  Object.freeze([-1, 0, 0]),
  Object.freeze([1, 0, 0]),
  Object.freeze([0, 0, -1]),
  Object.freeze([0, 0, 1]),
  Object.freeze([-1, -1, 0]),
  Object.freeze([1, -1, 0]),
  Object.freeze([0, -1, -1]),
  Object.freeze([0, -1, 1]),
  Object.freeze([0, 1, 0]),
  Object.freeze([0, -2, 0])
])

// Use the same exact terminal geometry as GoalAnyGetToBlock. This is a
// bounded observation-only check, not a new navigation policy or a second
// success criterion.
function observedGetToBlockGoal (activeBot, name, maxDistance) {
  if (!activeBot || !activeBot.entity || !activeBot.entity.position ||
      typeof activeBot.blockAt !== 'function') return null
  const node = activeBot.entity.position.floored()
  const radius = Number(maxDistance)
  if (!Number.isFinite(radius) || radius <= 0) return null
  const radiusSquared = radius * radius
  for (const [dx, dy, dz] of GET_TO_BLOCK_END_OFFSETS) {
    const candidate = node.offset(-dx, -dy, -dz)
    // The loaded-world search's requested distance bound is a semantic
    // precondition, even if the bot already satisfies a pathfinder endpoint.
    const x = candidate.x - node.x
    const y = candidate.y - node.y
    const z = candidate.z - node.z
    if (x * x + y * y + z * z > radiusSquared) continue
    const observed = activeBot.blockAt(candidate)
    if (!observed || observed.name !== name || !observed.position) continue
    return observed.position
  }
  return null
}

class GoalAnyGetToBlock extends Goal {
  constructor (positions) {
    super()
    const uniqueTargets = new Map()
    for (const value of Array.isArray(positions) ? positions : []) {
      const position = value instanceof Vec3
        ? value.floored()
        : new Vec3(
            Math.floor(Number(value.x)),
            Math.floor(Number(value.y)),
            Math.floor(Number(value.z))
          )
      if (
        !Number.isFinite(position.x) ||
        !Number.isFinite(position.y) ||
        !Number.isFinite(position.z)
      ) continue
      const key = integerPositionKey(position.x, position.y, position.z)
      if (!uniqueTargets.has(key)) uniqueTargets.set(key, position)
    }
    this.targets = [...uniqueTargets.values()]
    this.endTargetIndexByKey = new Map()
    const endPointsByKey = new Map()
    for (let targetIndex = 0; targetIndex < this.targets.length; targetIndex += 1) {
      const target = this.targets[targetIndex]
      for (const [dx, dy, dz] of GET_TO_BLOCK_END_OFFSETS) {
        const x = target.x + dx
        const y = target.y + dy
        const z = target.z + dz
        const key = integerPositionKey(x, y, z)
        if (!this.endTargetIndexByKey.has(key)) {
          this.endTargetIndexByKey.set(key, targetIndex)
        }
        if (!endPointsByKey.has(key)) {
          endPointsByKey.set(key, {
            id: endPointsByKey.size,
            x,
            y,
            z
          })
        }
      }
    }
    this._endTree = buildBalancedKdTree([...endPointsByKey.values()])
  }

  heuristic (node) {
    const squared = nearestKdDistanceSquared(this._endTree, node)
    return Number.isFinite(squared) ? Math.sqrt(squared) : Infinity
  }

  isEnd (node) {
    return this.targetIndexForNode(node) >= 0
  }

  isValid () {
    return this.targets.length > 0
  }

  targetIndexForNode (node) {
    const key = integerPositionKey(
      Math.floor(Number(node.x)),
      Math.floor(Number(node.y)),
      Math.floor(Number(node.z))
    )
    const index = this.endTargetIndexByKey.get(key)
    return Number.isInteger(index) ? index : -1
  }
}

async function gotoAnyBlockVicinity (positions, timeoutMs = null) {
  const activeBot = requireBot()
  if (!activeBot.pathfinder.movements) await ensureMovements()
  const goal = new GoalAnyGetToBlock(positions)
  if (!goal.isValid()) {
    const error = new Error('PATHFINDER_BLOCK_TARGETS_REQUIRED')
    error.code = 'PATHFINDER_BLOCK_TARGETS_REQUIRED'
    throw error
  }

  const navigation = await navigateGoal(
    goal,
    actionRemainingMs(timeoutMs),
    'PATHFINDER_GET_TO_ANY_BLOCK'
  )

  const node = activeBot.entity.position.floored()
  const selectedIndex = goal.targetIndexForNode(node)
  if (selectedIndex < 0) {
    const error = new Error('PATHFINDER_MULTI_TARGET_UNRESOLVED')
    error.code = 'PATHFINDER_MULTI_TARGET_UNRESOLVED'
    throw error
  }

  const target = goal.targets[selectedIndex]
  return {
    target: vec(target),
    position: vec(activeBot.entity.position),
    distance: activeBot.entity.position.distanceTo(target),
    navigation_goal: 'get_to_any_block',
    candidate_count: goal.targets.length,
    selected_candidate_index: selectedIndex,
    heuristic_index: 'balanced_kd_tree',
    terminal_lookup: 'constant_time',
    ...navigation
  }
}

async function gotoBlockInteraction (position, timeoutMs = null) {
  const activeBot = requireBot()
  const target = new Vec3(Number(position.x), Number(position.y), Number(position.z))
  const goal = new GoalLookAtBlock(target, activeBot.world)
  let alreadySatisfied = false
  try { alreadySatisfied = goal.isEnd(activeBot.entity.position.floored()) === true } catch (_) {}
  if (alreadySatisfied) {
    return {
      target: vec(target),
      position: vec(activeBot.entity.position),
      distance: activeBot.entity.position.distanceTo(target),
      navigation_goal: 'look_at_block',
      navigation_mode: 'already_satisfied',
      pathfinder_elapsed_ms: 0,
      pathfinder_evidence: {
        path_update_count: 0,
        path_status_counts: {},
        path_reset_count: 0,
        path_reset_reasons: {},
        path_stop_count: 0,
        goal_reached_count: 0
      }
    }
  }
  if (!activeBot.pathfinder.movements) await ensureMovements()
  const navigation = await navigateGoal(
    goal,
    actionRemainingMs(timeoutMs),
    'PATHFINDER_LOOK_AT_BLOCK'
  )
  const distance = activeBot.entity.position.distanceTo(target)
  return {
    target: vec(target),
    position: vec(activeBot.entity.position),
    distance,
    navigation_goal: 'look_at_block',
    ...navigation
  }
}

async function gotoAnyBlockPlacement (positions, timeoutMs = null) {
  const activeBot = requireBot()
  if (!activeBot.pathfinder.movements) await ensureMovements()
  const targets = (Array.isArray(positions) ? positions : [])
    .map(position => (
      position instanceof Vec3
        ? position.clone()
        : new Vec3(Number(position.x), Number(position.y), Number(position.z))
    ))
    .filter(position => (
      Number.isFinite(position.x) &&
      Number.isFinite(position.y) &&
      Number.isFinite(position.z)
    ))
  if (targets.length === 0) {
    const error = new Error('PATHFINDER_PLACEMENT_TARGETS_REQUIRED')
    error.code = 'PATHFINDER_PLACEMENT_TARGETS_REQUIRED'
    throw error
  }

  const goals = targets.map(target => new GoalPlaceBlock(target, activeBot.world, {}))
  const composite = new GoalCompositeAny(goals)
  const navigation = await navigateGoal(
    composite,
    actionRemainingMs(timeoutMs),
    'PATHFINDER_PLACE_ANY_BLOCK'
  )
  const node = activeBot.entity.position.floored()
  const headPosition = activeBot.entity.position.offset(0, 1.6, 0)

  let selectedIndex = -1
  let placement = null
  for (let index = 0; index < goals.length; index += 1) {
    let satisfied = false
    try { satisfied = goals[index].isEnd(node) } catch (_) {}
    if (!satisfied) continue
    const candidatePlacement = goals[index].getFaceAndRef(headPosition)
    if (!candidatePlacement) continue
    selectedIndex = index
    placement = candidatePlacement
    break
  }
  if (selectedIndex < 0 || !placement) {
    const error = new Error('PATHFINDER_COMPOSITE_PLACEMENT_UNRESOLVED')
    error.code = 'PATHFINDER_COMPOSITE_PLACEMENT_UNRESOLVED'
    throw error
  }

  const target = targets[selectedIndex]
  // GoalPlaceBlock exposes a reference *position* and a face vector pointing
  // from the target toward that reference. Mineflayer.placeBlock requires the
  // concrete reference Block and the inverse vector (reference -> target).
  const reference = activeBot.blockAt(placement.ref)
  if (!reference || !reference.position) {
    const error = new Error('PATHFINDER_PLACEMENT_REFERENCE_UNAVAILABLE')
    error.code = 'PATHFINDER_PLACEMENT_REFERENCE_UNAVAILABLE'
    throw error
  }
  const face = placement.face.scaled(-1)
  return {
    target: vec(target),
    position: vec(activeBot.entity.position),
    distance: activeBot.entity.position.distanceTo(target),
    navigation_goal: 'place_any_block',
    candidate_count: targets.length,
    selected_candidate_index: selectedIndex,
    reference,
    face,
    ...navigation
  }
}

async function gotoBlockPlacement (position, timeoutMs = null) {
  const activeBot = requireBot()
  if (!activeBot.pathfinder.movements) await ensureMovements()
  const target = new Vec3(Number(position.x), Number(position.y), Number(position.z))
  const goal = new GoalPlaceBlock(target, activeBot.world, {})
  const navigation = await navigateGoal(
    goal,
    actionRemainingMs(timeoutMs),
    'PATHFINDER_PLACE_BLOCK'
  )
  const headPosition = activeBot.entity.position.offset(0, 1.6, 0)
  const placement = goal.getFaceAndRef(headPosition)
  if (!placement) throw new Error('PATHFINDER_NO_PLACEMENT_FACE')
  const reference = activeBot.blockAt(placement.ref)
  if (!reference || !reference.position) {
    const error = new Error('PATHFINDER_PLACEMENT_REFERENCE_UNAVAILABLE')
    error.code = 'PATHFINDER_PLACEMENT_REFERENCE_UNAVAILABLE'
    throw error
  }
  const face = placement.face.scaled(-1)
  return {
    target: vec(target),
    position: vec(activeBot.entity.position),
    distance: activeBot.entity.position.distanceTo(target),
    navigation_goal: 'place_block',
    reference,
    face,
    ...navigation
  }
}

function result (tool, action, status, code, details = {}, effectDisposition = null) {
  if (!['applied', 'satisfied', 'partial', 'rejected'].includes(status)) throw new Error(`invalid action status ${status}`)
  const disposition = effectDisposition || (
    status === 'applied' ? 'applied' : status === 'rejected' ? 'rejected' : 'unknown'
  )
  if (!['applied', 'rejected', 'not_applied', 'unknown'].includes(disposition)) {
    throw new Error(`invalid action effect disposition ${disposition}`)
  }
  if (status === 'applied' && disposition !== 'applied') {
    throw new Error('applied action must prove applied effect')
  }
  if (status === 'satisfied' && (disposition !== 'not_applied' || details.goal_satisfied !== true)) {
    throw new Error('satisfied action must prove goal satisfaction with no physical effect')
  }
  if (status === 'rejected' && !['rejected', 'not_applied'].includes(disposition)) {
    throw new Error('rejected action must prove rejection or no effect')
  }
  if (status === 'partial' && !['applied', 'unknown'].includes(disposition)) {
    throw new Error('partial action effect disposition is invalid')
  }
  const actionEvidence = { ...action }
  if (Object.prototype.hasOwnProperty.call(actionEvidence, 'tool')) {
    actionEvidence.requested_tool = actionEvidence.tool
  }
  actionEvidence.tool = tool
  return {
    action: actionEvidence,
    outcome: { status, code, ...details },
    effect_disposition: disposition,
    verified: status === 'applied'
  }
}

function applied (tool, action, code, details = {}) { return result(tool, action, 'applied', code, details, 'applied') }
function satisfied (tool, action, code, details = {}) { return result(tool, action, 'satisfied', code, { ...details, goal_satisfied: true }, 'not_applied') }
function partial (tool, action, code, details = {}, effectDisposition = 'applied') { return result(tool, action, 'partial', code, details, effectDisposition) }
function rejected (tool, action, code, details = {}, effectDisposition = 'rejected') { return result(tool, action, 'rejected', code, details, effectDisposition) }

function errorEvidence (error, depth = 0) {
  if (error == null) return null
  if (depth >= 4) return { message: String(error) }
  const evidence = {
    name: String(error.name || 'Error'),
    code: String(error.code || error.name || 'ERROR'),
    message: String(error.message || error)
  }
  if (typeof error.stack === 'string' && error.stack.trim()) evidence.stack = error.stack
  if (error.cause != null && error.cause !== error) {
    evidence.cause = errorEvidence(error.cause, depth + 1)
  }
  const properties = {}
  for (const key of Object.keys(error).sort()) {
    if (['name', 'code', 'message', 'stack', 'cause'].includes(key)) continue
    const value = error[key]
    if (value == null || ['string', 'number', 'boolean'].includes(typeof value)) {
      properties[key] = value
    }
  }
  if (Object.keys(properties).length > 0) evidence.properties = properties
  return evidence
}

module.exports = {
  ActionCancellationScope,
  ActionCancelledError,
  actionRemainingMs,
  actionTimeoutMs,
  actionProviderWindowMs,
  createActionProviderWindow,
  actionTerminalSettlementMs,
  applied,
  satisfied,
  bindBot,
  ensureMovements,
  safeToHarvestBlock,
  errorEvidence,
  entityMatches,
  findEntity,
  captureItemDropNear,
  captureInventoryIncrease,
  createActionCancellationScope,
  currentActionCancellationScope,
  droppedItemName,
  findInventoryItem,
  findNearbyDroppedItem,
  getBot,
  GoalAnyGetToBlock,
  gotoAnyBlockVicinity,
  gotoAnyBlockPlacement,
  gotoBlockInteraction,
  gotoBlockPlacement,
  gotoEntity,
  followEntityFor,
  gotoPos,
  moveAwayFromEntity,
  inventoryCount,
  inventoryDelta,
  observeBlocks,
  observeExactBlock,
  defaultNearbyBlocksProjection,
  observedGetToBlockGoal,
  observedBlockRegistryIds,
  inventoryMap,
  onActionCancel,
  isSkillChildAuthorized,
  isDroppedItemEntity,
  itemSummary,
  waitForEventCondition,
  waitForInventoryIncrease,
  waitForOwnCollection,
  waitForPhysicsTicks,
  matchName,
  navigateGoal,
  partial,
  rejected,
  requireBot,
  runWithActionCancellationScope,
  runSkillChildEffect,
  sleep,
  stopMotion,
  vec,
  withTimeout
}
