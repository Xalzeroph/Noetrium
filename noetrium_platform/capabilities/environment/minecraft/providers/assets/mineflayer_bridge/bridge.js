'use strict'

const readline = require('readline')
const mineflayer = require('mineflayer')
const { pathfinder } = require('mineflayer-pathfinder')
const { plugin: pvp } = require('mineflayer-pvp')
const runtime = require('./runtime')
const movement = require('./movement')
const resources = require('./resources')
const inventory = require('./inventory')
const combat = require('./combat')
const interactions = require('./interactions')
const { ActionRecoveryJournal } = require('./action_recovery')

const PROTOCOL_VERSION = 'minecraft-jsonl-v1'
let sequence = 0
let bot = null
const actionRecovery = new ActionRecoveryJournal()

function emit (kind, payload = {}, requestId = null) {
  const value = {
    type: 'event',
    protocol_version: PROTOCOL_VERSION,
    kind,
    source: 'mineflayer',
    seq: ++sequence,
    ts_ms: Date.now(),
    payload
  }
  if (requestId) value.request_id = String(requestId)
  process.stdout.write(JSON.stringify(value) + '\n')
}

function ack (cmd, payload = {}, requestId = null) {
  const value = { type: 'ack', protocol_version: PROTOCOL_VERSION, cmd, ...payload }
  if (requestId) value.request_id = String(requestId)
  process.stdout.write(JSON.stringify(value) + '\n')
}

function selfSnapshot (requestId = null) {
  const activeBot = runtime.getBot()
  emit('self_snapshot', {
    username: activeBot.username,
    position: runtime.vec(activeBot.entity.position),
    yaw: activeBot.entity.yaw,
    pitch: activeBot.entity.pitch,
    health: activeBot.health,
    food: activeBot.food,
    held_item: runtime.itemSummary(activeBot.heldItem),
    inventory: activeBot.inventory.items().map(runtime.itemSummary),
    dimension: activeBot.game ? activeBot.game.dimension : null
  }, requestId)
}

function observeEntities (maxDistance = 16, limit = 32, requestId = null) {
  const activeBot = runtime.getBot()
  const origin = activeBot.entity.position
  const entities = Object.values(activeBot.entities || {})
    .filter(entity => entity && entity !== activeBot.entity && entity.position && entity.isValid !== false)
    .map(entity => ({ entity, distance: entity.position.distanceTo(origin) }))
    .filter(candidate => candidate.distance <= maxDistance)
    .sort((left, right) => left.distance - right.distance)
    .slice(0, limit)
  for (const { entity, distance } of entities) {
    emit('entity_observation', {
      id: entity.id,
      uuid: entity.uuid || null,
      name: entity.name || null,
      username: entity.username || null,
      display_name: entity.displayName || null,
      type: entity.type || null,
      mob_type: entity.displayName || null,
      position: runtime.vec(entity.position),
      distance,
      is_valid: entity.isValid !== false
    }, requestId)
  }
  return entities.length
}

function registrySearch (msg) {
  const activeBot = runtime.getBot()
  const query = String(msg.query || '').toLowerCase()
  const limit = Math.max(1, Math.min(100, Number(msg.limit || 20)))
  return {
    items: Object.values(activeBot.registry.items || {})
      .filter(value => value && String(value.name).includes(query))
      .slice(0, limit)
      .map(value => value.name),
    blocks: Object.values(activeBot.registry.blocks || {})
      .filter(value => value && String(value.name).includes(query))
      .slice(0, limit)
      .map(value => value.name)
  }
}

async function waitAction (msg) {
  const ms = Math.max(0, Math.min(10000, Number(msg.ms || 500)))
  await runtime.sleep(ms)
  return runtime.applied('wait', { ms }, 'WAIT_COMPLETED', { waited_ms: ms })
}

async function chatAction (msg) {
  const activeBot = runtime.getBot()
  const message = String(msg.message || '')
  activeBot.chat(message)
  return runtime.applied('chat', { message }, 'CHAT_SENT', { message })
}

async function observeEntitiesAction (msg) {
  const action = {
    max_distance: Number(msg.max_distance || 16),
    limit: Number(msg.limit || 32)
  }
  const count = observeEntities(action.max_distance, action.limit, msg.request_id || msg.action_id || null)
  return runtime.applied('observe_entities', action, 'ENTITIES_OBSERVED', { observed_count: count })
}

async function registrySearchAction (msg) {
  const action = { query: String(msg.query || ''), limit: Number(msg.limit || 20) }
  return runtime.applied('registry_search', action, 'REGISTRY_SEARCHED', registrySearch(msg))
}

const ACTION_HANDLERS = Object.freeze({
  ...movement,
  ...resources,
  ...inventory,
  ...combat,
  ...interactions,
  wait: waitAction,
  chat: chatAction,
  observe_entities: observeEntitiesAction,
  registry_search: registrySearchAction
})

function connect (options) {
  if (bot) throw new Error('bot already exists')
  const requestId = options.request_id || null
  bot = mineflayer.createBot({
    host: options.host || '127.0.0.1',
    port: Number(options.port || 25565),
    username: options.username || 'ResearchBot',
    auth: options.auth || 'offline',
    version: options.version || false,
    checkTimeoutInterval: Number(options.checkTimeoutInterval || 30000),
    hideErrors: true
  })
  runtime.bindBot(bot)
  actionRecovery.configure(options.action_recovery_dir || null)
  bot.loadPlugin(pathfinder)
  bot.loadPlugin(pvp)
  bot.once('spawn', () => {
    emit('bridge_status', {
      status: 'spawned',
      username: bot.username,
      version: bot.version,
      action_types: Object.keys(ACTION_HANDLERS).sort()
    }, requestId)
    selfSnapshot(requestId)
  })
  bot.on('health', () => emit('health', { health: bot.health, food: bot.food }))
  bot.on('death', () => emit('death', { username: bot.username }))
  bot.on('kicked', (reason, loggedIn) => emit('kicked', { reason: String(reason), logged_in: Boolean(loggedIn) }))
  bot.on('error', error => emit('error', { message: String(error && error.message ? error.message : error) }))
  bot.on('end', reason => emit('end', { reason: String(reason || '') }))
}

function emitActionResult (cmd, msg, result) {
  const requestId = msg.request_id || msg.action_id || null
  emit('action_result', {
    action_id: msg.action_id || null,
    task_id: msg.task_id || null,
    task_lineage: msg.task_lineage || null,
    task: msg.task || '',
    context: msg.context || {},
    action: result.action,
    outcome: result.outcome,
    anchors: Array.isArray(msg.anchors) ? msg.anchors : [],
    verified: Boolean(result.verified)
  }, requestId)
  selfSnapshot(requestId)
  ack(cmd, {
    verified: Boolean(result.verified),
    rejected: result.outcome.status === 'rejected',
    outcome_code: result.outcome.code
  }, requestId)
}

async function runAction (cmd, msg) {
  const handler = ACTION_HANDLERS[cmd]
  if (!handler) throw new Error(`unknown action command ${cmd}`)
  const actionId = String(msg.action_id || '')
  const requestDigest = String(msg._request_digest || '')
  const prepared = actionRecovery.begin(actionId, requestDigest, cmd)
  if (!prepared.execute) {
    const disposition = prepared.record.disposition || 'unknown'
    const replay = disposition === 'applied'
      ? runtime.applied(cmd, {}, 'ACTION_RECOVERY_CONFIRMED', { recovery_state: prepared.record.state })
      : disposition === 'not_applied'
        ? runtime.rejected(cmd, {}, 'ACTION_RECOVERY_NOT_APPLIED', { recovery_state: prepared.record.state })
        : runtime.partial(cmd, {}, 'ACTION_RECOVERY_UNCERTAIN', { recovery_state: prepared.record.state })
    emitActionResult(cmd, msg, replay)
    return
  }
  const timeoutMs = runtime.actionTimeoutMs(msg)
  let result
  try {
    result = await runtime.withTimeout(
      handler(msg), timeoutMs, `ACTION_${String(cmd).toUpperCase()}`, runtime.stopMotion
    )
  } catch (error) {
    result = runtime.partial(cmd, {}, 'ACTION_HANDLER_BOUNDED_FAILURE', {
      error: String(error && error.message ? error.message : error),
      error_code: error && error.code ? String(error.code) : null,
      timeout_ms: timeoutMs
    })
  }
  actionRecovery.complete(actionId, requestDigest, cmd, result)
  emitActionResult(cmd, msg, result)
}

async function command (msg) {
  const cmd = String(msg.cmd || '')
  const requestId = msg.request_id || null
  if (cmd === 'connect') {
    connect(msg)
    ack(cmd, {}, requestId)
    return
  }
  if (cmd === 'snapshot') {
    selfSnapshot(requestId)
    ack(cmd, {}, requestId)
    return
  }
  if (cmd === 'task_event') {
    runtime.requireBot()
    emit('task_event', {
      task_id: msg.task_id || null,
      task: msg.task || msg.goal || '',
      goal: msg.goal || msg.task || '',
      context: msg.context || {},
      task_lineage: msg.task_lineage || msg.task_id || null,
      anchors: Array.isArray(msg.anchors) ? msg.anchors : [],
      status: msg.status || 'OBSERVED'
    }, requestId)
    ack(cmd, {}, requestId)
    return
  }
  if (cmd === 'observe_entities' && !String(msg.action_id || '').trim()) {
    const result = await observeEntitiesAction(msg)
    emitActionResult(cmd, msg, result)
    return
  }
  if (ACTION_HANDLERS[cmd]) {
    await runAction(cmd, msg)
    return
  }
  if (cmd === 'reconcile_action') {
    const proof = actionRecovery.reconcile(String(msg.action_id || ''), String(msg.request_digest || ''))
    ack(cmd, proof, requestId)
    return
  }
  if (cmd === 'quit') {
    ack(cmd, {}, requestId)
    if (bot) bot.quit('Noetrium bridge shutdown')
    setTimeout(() => process.exit(0), 20)
    return
  }
  throw new Error(`unknown command: ${cmd}`)
}

const readlineInterface = readline.createInterface({ input: process.stdin, crlfDelay: Infinity })
readlineInterface.on('line', line => {
  let message
  try {
    message = JSON.parse(line)
  } catch (error) {
    emit('error', { message: `invalid json command: ${error.message}` })
    return
  }
  Promise.resolve(command(message)).catch(error => {
    const requestId = message.request_id || message.action_id || null
    emit('error', { message: String(error.message || error), cmd: message.cmd || null }, requestId)
    ack(String(message.cmd || ''), {
      verified: false,
      rejected: true,
      error: String(error.message || error)
    }, requestId)
  })
})

module.exports = { ACTION_HANDLERS }
