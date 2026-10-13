'use strict'

const readline = require('readline')
const v8 = require('node:v8')
const util = require('node:util')

// stdout is the JSONL wire protocol, not a logging stream. Capture its writer
// before importing any third-party Minecraft dependency, then revoke ambient
// stdout ownership for the remainder of the process. This turns accidental
// dependency banners/debug prints into stderr diagnostics without corrupting
// protocol framing.
const protocolStdoutWrite = process.stdout.write.bind(process.stdout)
function diagnosticWrite (...args) {
  const rendered = util.format(...args)
  process.stderr.write(rendered.endsWith('\n') ? rendered : rendered + '\n')
}
console.log = diagnosticWrite
console.info = diagnosticWrite
process.stdout.write = function nonProtocolStdoutWrite (chunk, encoding, callback) {
  const value = Buffer.isBuffer(chunk) ? chunk.toString() : String(chunk)
  process.stderr.write(value)
  if (typeof encoding === 'function') encoding()
  if (typeof callback === 'function') callback()
  return true
}

const { Vec3 } = require('vec3')
const mineflayer = require('mineflayer')
const minecraftData = require('minecraft-data')
const { pathfinder } = require('mineflayer-pathfinder')
const { plugin: pvp } = require('mineflayer-pvp')
const { plugin: tool } = require('mineflayer-tool')
const runtime = require('./runtime')
const movement = require('./movement')
const resources = require('./resources')
const { craft_grid: craftGridAction } = require('./craft_grid')
const inventory = require('./inventory')
const combat = require('./combat')
const interactions = require('./interactions')
const { searchRegistry, referenceCraftingRecipes } = require('./registry_search')
const { currentInventoryCounts, referenceRecipeDependencies, observedLocalAcquisitionSources } = require('./recipe_dependencies')
const actionHelp = require('./action_help')
const { observeWorldFrontiers } = require('./world_frontier')
const { ActionRecoveryJournal, replayActionResult } = require('./action_recovery')
const { createSkillEffectRecorder } = require('./skill_effects')
const { MinecraftBotActor } = require('./control_kernel')
const { verifySetupProjection, waitForSetupProjection } = require('./setup_verification')

const PROTOCOL_VERSION = 'minecraft-jsonl-v1'
let sequence = 0
let bot = null
const actionRecovery = new ActionRecoveryJournal()
const botActor = new MinecraftBotActor()

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
  protocolStdoutWrite(JSON.stringify(value) + '\n')
}

function ack (cmd, payload = {}, requestId = null) {
  const value = { type: 'ack', protocol_version: PROTOCOL_VERSION, cmd, ...payload }
  if (requestId) value.request_id = String(requestId)
  protocolStdoutWrite(JSON.stringify(value) + '\n')
}

function blockNameAt (activeBot, position) {
  const block = activeBot.blockAt(position)
  return block && block.name ? String(block.name) : null
}

const { verticalColumnObservation } = require('./world_column')

function finiteOrNull (value) {
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : null
}

function booleanOrNull (value) {
  return typeof value === 'boolean' ? value : null
}

function pathfinderBoolean (activeBot, name) {
  if (!activeBot.pathfinder || typeof activeBot.pathfinder[name] !== 'function') return null
  try { return Boolean(activeBot.pathfinder[name]()) } catch (_) { return null }
}

function selfSnapshot (requestId = null) {
  const activeBot = runtime.getBot()
  const equipment = activeBot.entity.equipment || []
  const equipmentSlots = ['hand', 'off_hand', 'feet', 'legs', 'torso', 'head']
  const timeOfDay = activeBot.time && Number.isFinite(Number(activeBot.time.timeOfDay))
    ? Number(activeBot.time.timeOfDay)
    : null
  const weather = activeBot.thunderState > 0
    ? 'thunder'
    : activeBot.rainState > 0
      ? 'rain'
      : 'clear'
  const position = activeBot.entity.position
  const verticalColumn = verticalColumnObservation(activeBot)
  const currentBlock = activeBot.blockAt(position)
  const biome = currentBlock && currentBlock.biome && currentBlock.biome.name
    ? String(currentBlock.biome.name)
    : null
  emit('self_snapshot', {
    username: activeBot.username,
    position: runtime.vec(position),
    yaw: activeBot.entity.yaw,
    pitch: activeBot.entity.pitch,
    health: activeBot.health,
    food: activeBot.food,
    physical_state: {
      velocity: runtime.vec(activeBot.entity.velocity),
      saturation: finiteOrNull(activeBot.foodSaturation),
      oxygen: finiteOrNull(activeBot.oxygenLevel),
      on_ground: booleanOrNull(activeBot.entity.onGround),
      time_since_on_ground: finiteOrNull(activeBot.entity.timeSinceOnGround),
      in_water: booleanOrNull(activeBot.entity.isInWater),
      in_lava: booleanOrNull(activeBot.entity.isInLava),
      in_web: booleanOrNull(activeBot.entity.isInWeb),
      collided_horizontally: booleanOrNull(activeBot.entity.isCollidedHorizontally),
      collided_vertically: booleanOrNull(activeBot.entity.isCollidedVertically),
      inventory_used: (
        typeof activeBot.inventoryUsed === 'function'
          ? finiteOrNull(activeBot.inventoryUsed())
          : null
      ),
      pathfinder: {
        moving: pathfinderBoolean(activeBot, 'isMoving'),
        mining: pathfinderBoolean(activeBot, 'isMining'),
        building: pathfinderBoolean(activeBot, 'isBuilding')
      }
    },
    time_of_day: timeOfDay,
    weather,
    biome,
    surroundings: {
      below: blockNameAt(activeBot, position.offset(0, -1, 0)),
      legs: blockNameAt(activeBot, position),
      head: blockNameAt(activeBot, position.offset(0, 1, 0)),
      vertical_bounds: verticalColumn.vertical_bounds,
      first_solid_above_head: verticalColumn.first_solid_above_head,
      surface: verticalColumn.surface
    },
    held_item: runtime.itemSummary(activeBot.heldItem),
    equipment: Object.fromEntries(
      equipmentSlots.map((slot, index) => [slot, runtime.itemSummary(equipment[index])])
    ),
    inventory: activeBot.inventory.items().map(runtime.itemSummary),
    // Mindcraft-style default nearby observation: physical loaded-world
    // sensing only, bounded and identical for every scientific treatment.
    // Never query server-only blocks, hidden datapacks or evaluator state.
    nearby_blocks: runtime.defaultNearbyBlocksProjection(16, 12).blocks.map(block => ({
      name: block.name,
      position: block.position,
      distance: block.distance
    })),
    dimension: activeBot.game ? activeBot.game.dimension : null
  }, requestId)
}

function currentEntityRows (maxDistance = 16, limit = 32) {
  const activeBot = runtime.getBot()
  const origin = activeBot.entity.position
  const candidates = Object.values(activeBot.entities || {})
    .filter(entity => entity && entity !== activeBot.entity && entity.position && entity.isValid !== false)
    .map(entity => ({ entity, distance: entity.position.distanceTo(origin) }))
    .filter(candidate => candidate.distance <= maxDistance)
    .sort((left, right) => left.distance - right.distance)
    .slice(0, limit)
  return { rows: candidates.map(({ entity, distance }) => ({
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
  })) }
}

function observeEntities (maxDistance = 16, limit = 32, requestId = null) {
  const { rows } = currentEntityRows(maxDistance, limit)
  emit('entity_snapshot', {
    entities: rows,
    max_distance: maxDistance,
    limit: limit,
    scope: 'currently_loaded_and_observable'
  }, requestId)
  return rows.length
}

function registrySearch (msg) {
  const activeBot = runtime.getBot()
  return searchRegistry(
    activeBot.registry,
    msg.query,
    msg.limit
  )
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

async function observeBlocksAction (msg) {
  const action = {
    query: msg.query == null ? null : String(msg.query),
    position: msg.position == null ? null : {
      x: Number(msg.position.x), y: Number(msg.position.y), z: Number(msg.position.z)
    },
    max_distance: Number(msg.max_distance || 16),
    limit: msg.position == null ? Number(msg.limit || 32) : null
  }
  if (action.position !== null) {
    const observation = runtime.observeExactBlock(action.position, action.max_distance)
    return runtime.applied(
      'observe_blocks', action,
      observation.observed ? 'BLOCK_POSITION_OBSERVED' : 'BLOCK_POSITION_UNOBSERVED',
      observation
    )
  }
  const observation = runtime.observeBlocks(
    action.query,
    action.max_distance,
    action.limit
  )
  return runtime.applied(
    'observe_blocks',
    action,
    'BLOCKS_OBSERVED',
    { ...observation, world_frontier: observeWorldFrontiers(runtime.getBot(), action.max_distance) }
  )
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
  const action = { query: String(msg.query || ''), limit: Number(msg.limit) }
  return runtime.applied('registry_search', action, 'REGISTRY_SEARCHED', registrySearch(msg))
}

async function recipeLookupAction (msg) {
  const action = { item: String(msg.item || ''), limit: Number(msg.limit) }
  // Load independent vanilla reference data, never a mutable live server
  // registry: a MirrorCraft datapack may alter current-world recipes.
  const version = runtime.getBot().version
  const vanilla = minecraftData(version)
  if (!vanilla || vanilla.version.minecraftVersion !== version) {
    throw new Error('REFERENCE_RECIPE_VANILLA_VERSION_MISMATCH')
  }
  const reference = referenceCraftingRecipes(vanilla, action.item, action.limit)
  return runtime.applied('recipe_lookup', action, 'VANILLA_RECIPES_REFERENCED', reference)
}

async function recipeDependenciesAction (msg) {
  const action = { item: String(msg.item || ''), count: Number(msg.count) }
  const bot = runtime.getBot()
  const version = bot.version
  const vanilla = minecraftData(version)
  if (!vanilla || vanilla.version.minecraftVersion !== version) {
    throw new Error('REFERENCE_RECIPE_VANILLA_VERSION_MISMATCH')
  }
  const inventory = currentInventoryCounts(bot)
  const reference = referenceRecipeDependencies(vanilla, action.item, action.count, inventory)
  const nearby = observedLocalAcquisitionSources(bot, reference.root_alternative_dependency_profiles)
  return runtime.applied('recipe_dependencies', action, 'RECIPE_DEPENDENCIES_REFERENCED', {
    ...reference,
    observed_local_acquisition_sources: nearby
  })
}

const ACTION_HANDLERS = Object.freeze({
  ...movement,
  ...resources,
  craft_grid: craftGridAction,
  ...inventory,
  ...combat,
  ...interactions,
  wait: waitAction,
  chat: chatAction,
  observe_blocks: observeBlocksAction,
  observe_entities: observeEntitiesAction,
  registry_search: registrySearchAction,
  recipe_lookup: recipeLookupAction,
  recipe_dependencies: recipeDependenciesAction,
  ...actionHelp
})

const SIDE_EFFECT_DOMAINS = new Set([
  'movement', 'excavation', 'placement', 'inventory', 'equipment',
  'combat', 'world_loading', 'interaction', 'time', 'chat'
])

function actionSideEffectEnvelope (msg) {
  const raw = msg._action_side_effect_envelope
  if (!Array.isArray(raw) || raw.some(value =>
    typeof value !== 'string' || !SIDE_EFFECT_DOMAINS.has(value))) {
    throw new Error('ACTION_SIDE_EFFECT_ENVELOPE_INVALID')
  }
  if (new Set(raw).size !== raw.length) {
    throw new Error('ACTION_SIDE_EFFECT_ENVELOPE_DUPLICATE')
  }
  const effectClass = String(msg._action_effect_class || '')
  if (!['pure', 'idempotent', 'reconcilable', 'external_exactly_once'].includes(effectClass)) {
    throw new Error('ACTION_EFFECT_CLASS_INVALID')
  }
  if (effectClass === 'pure' && raw.length !== 0) {
    throw new Error('PURE_ACTION_SIDE_EFFECT_ENVELOPE_NONEMPTY')
  }
  if (effectClass !== 'pure' && raw.length === 0) {
    throw new Error('EFFECTFUL_ACTION_SIDE_EFFECT_ENVELOPE_EMPTY')
  }
  return raw
}

function canonicalEffectProjection (value) {
  if (Array.isArray(value)) return value.map(canonicalEffectProjection)
  if (value && typeof value === 'object') {
    return Object.fromEntries(
      Object.keys(value).sort().map(key => [key, canonicalEffectProjection(value[key])])
    )
  }
  return value
}

function actionEffectProjection (sideEffects) {
  const domains = new Set(sideEffects)
  const observesPosition = domains.has('movement') || domains.has('world_loading')
  const observesInventory = domains.has('inventory') || domains.has('equipment') ||
    domains.has('excavation') || domains.has('placement')
  const observesCombat = domains.has('combat')
  const observesInteraction = domains.has('interaction')
  if (!observesPosition && !observesInventory && !observesCombat && !observesInteraction) return null
  const activeBot = runtime.getBot()
  const projection = {}
  if (observesPosition) {
    projection.position = runtime.vec(activeBot.entity.position)
  }
  if (observesInventory || observesCombat) {
    projection.inventory = runtime.inventoryMap()
    projection.held_item = runtime.itemSummary(activeBot.heldItem)
    projection.equipment = (activeBot.entity.equipment || []).map(runtime.itemSummary)
  }
  if (observesCombat) {
    projection.health = Number(activeBot.health)
    projection.food = Number(activeBot.food)
  }
  if (observesInteraction) {
    projection.vehicle_id = activeBot.vehicle && Number.isSafeInteger(activeBot.vehicle.id)
      ? activeBot.vehicle.id : null
    projection.using_held_item = Boolean(activeBot.usingHeldItem)
  }
  return canonicalEffectProjection(projection)
}

function actionEffectObserved (before, after) {
  if (before == null || after == null) return false
  return JSON.stringify(before) !== JSON.stringify(after)
}

function connect (options) {
  if (bot) throw new Error('bot already exists')
  const requestId = options.request_id || null
  const port = Number(options.port)
  if (!Number.isInteger(port) || port < 1 || port > 65535) {
    throw new Error('minecraft connect requires a Resource-assigned port')
  }
  const host = String(options.host || '').trim()
  const username = String(options.username || '').trim()
  const auth = String(options.auth || '').trim()
  if (!host) throw new Error('minecraft connect requires an Authority-provided host')
  if (!username) throw new Error('minecraft connect requires an Agent-provided username')
  if (!auth) throw new Error('minecraft connect requires an Agent-provided auth mode')
  const createOptions = { host, port, username, auth }
  if (options.version != null && String(options.version).trim()) {
    createOptions.version = String(options.version).trim()
  }
  bot = mineflayer.createBot(createOptions)
  runtime.bindBot(bot)
  actionRecovery.configure(options.action_recovery_dir || null)
  bot.loadPlugin(pathfinder)
  bot.loadPlugin(tool)
  bot.loadPlugin(pvp)
  bot.once('spawn', () => {
    emit('bridge_status', {
      status: 'spawned',
      username: bot.username,
      version: bot.version,
      action_types: Object.keys(ACTION_HANDLERS).sort(),
      terminal_settlement_ms: runtime.actionTerminalSettlementMs()
    }, requestId)
    selfSnapshot(requestId)
  })
  bot.on('health', () => emit('health', { health: bot.health, food: bot.food }))
  bot.on('death', () => emit('death', { username: bot.username }))
  bot.on('kicked', (reason, loggedIn) => emit('kicked', { reason: String(reason), logged_in: Boolean(loggedIn) }))
  bot.on('error', error => emit('error', { message: String(error && error.message ? error.message : error) }))
  bot.on('end', reason => emit('end', { reason: String(reason || '') }))
}

function bridgeMemorySnapshot () {
  const memory = process.memoryUsage()
  const heap = v8.getHeapStatistics()
  // Provider telemetry is observed truth, not lifecycle policy.  Do not turn
  // an arbitrary heap-reserve heuristic into a hidden Authority decision.
  // Explicit cleanup failure/transport uncertainty may request a recycle;
  // capacity policy belongs to the host resource/lifecycle layer.
  return {
    rss_bytes: Number(memory.rss || 0),
    heap_total_bytes: Number(memory.heapTotal || 0),
    heap_used_bytes: Number(memory.heapUsed || 0),
    heap_size_limit_bytes: Number(heap.heap_size_limit || 0),
    total_available_size_bytes: Number(heap.total_available_size || 0),
    external_bytes: Number(memory.external || 0),
    array_buffers_bytes: Number(memory.arrayBuffers || 0)
  }
}

function emitQueryResult (cmd, msg, result) {
  const requestId = msg.request_id || null
  emit('query_result', {
    query_type: cmd,
    truth_class: 'observed',
    outcome: result.outcome,
    verified: Boolean(result.verified),
    no_physical_effect: true
  }, requestId)
  ack(cmd, {
    verified: Boolean(result.verified),
    query_result: true,
    outcome_code: result.outcome && result.outcome.code
      ? String(result.outcome.code) : null
  }, requestId)
}

function emitActionResult (cmd, msg, result, forceRecycle = false) {
  const actionId = msg.action_id == null ? null : String(msg.action_id)
  const requestId = msg.request_id || actionId || null
  const bridgeMemory = bridgeMemorySnapshot()
  emit('action_result', {
    action_id: actionId,
    request_digest: msg._request_digest || null,
    action_invocation_unit_digest: msg._action_invocation_unit_digest || null,
    action_authorization_unit_digest: msg._action_authorization_unit_digest || null,
    task_id: msg.task_id || null,
    task_lineage: msg.task_lineage || null,
    task: msg.task || '',
    context: msg.context || {},
    action: result.action,
    outcome: result.outcome,
    effect_disposition: result.effect_disposition,
    child_effects: Array.isArray(result.child_effects) ? result.child_effects : [],
    execution_control: result.execution_control || null,
    anchors: Array.isArray(msg.anchors) ? msg.anchors : [],
    verified: Boolean(result.verified),
    bridge_memory: bridgeMemory
  }, requestId)
  // The physical-effect receipt is terminal authority. A secondary observation
  // failure must never erase that receipt or strand the host ledger in UNKNOWN.
  let snapshotError = null
  try {
    selfSnapshot(requestId)
  } catch (error) {
    snapshotError = String(error && error.message ? error.message : error)
    emit('error', {
      message: snapshotError,
      code: 'ACTION_RESULT_SNAPSHOT_FAILED',
      cmd
    }, requestId)
  }
  ack(cmd, {
    verified: Boolean(result.verified),
    rejected: result.outcome.status === 'rejected',
    effect_disposition: result.effect_disposition,
    outcome_code: result.outcome.code,
    bridge_recycle_recommended: Boolean(forceRecycle),
    snapshot_error: snapshotError
  }, requestId)
  return bridgeMemory
}

function rootActionUnitLineage (msg) {
  const root = String(msg._action_invocation_unit_digest || '')
  const authorization = String(msg._action_authorization_unit_digest || '')
  if (!/^[0-9a-f]{64}$/.test(root) || !/^[0-9a-f]{64}$/.test(authorization)) {
    throw new Error('ACTION_UNIT_LINEAGE_REQUIRED')
  }
  return {
    root_invocation_unit_digest: root,
    authorization_unit_digest: authorization
  }
}

async function runPureAction (cmd, msg) {
  const handler = ACTION_HANDLERS[cmd]
  if (!handler) throw new Error(`unknown action command ${cmd}`)
  const actionId = String(msg.action_id || '')
  const requestDigest = String(msg._request_digest || '')
  rootActionUnitLineage(msg)
  actionSideEffectEnvelope(msg)
  const rawChildren = msg._authorized_child_action_units
  if (!rawChildren || Array.isArray(rawChildren) || typeof rawChildren !== 'object' ||
      Object.keys(rawChildren).length !== 0) {
    throw new Error('PURE_ACTION_CHILD_CAPABILITY_INVALID')
  }
  const timeoutMs = runtime.actionTimeoutMs(msg)
  const cancellationScope = runtime.createActionCancellationScope(
    String(cmd) + ':' + actionId, timeoutMs
  )
  botActor.attachScope(actionId, requestDigest, cancellationScope)
  let result
  let recycleBridge = false
  try {
    result = await runtime.runWithActionCancellationScope(
      cancellationScope,
      () => runtime.withTimeout(
        Promise.resolve().then(() => handler(msg)),
        timeoutMs,
        `ACTION_${String(cmd).toUpperCase()}`
      )
    )
  } catch (error) {
    recycleBridge = Boolean(error && error.cleanup_failed)
    result = runtime.rejected(cmd, {}, 'PURE_ACTION_BOUNDED_FAILURE', {
      error: String(error && error.message ? error.message : error),
      cancellation_cleanup_failed: recycleBridge,
      cancellation_cleanup_errors: Array.isArray(error && error.cleanup_errors)
        ? error.cleanup_errors.map(String) : []
    }, 'not_applied')
  }
  const executionControl = botActor.recordResult(
    actionId, requestDigest, result.effect_disposition
  )
  emitActionResult(
    cmd, msg, { ...result, execution_control: executionControl }, recycleBridge
  )
}

async function runAction (cmd, msg) {
  const effectClass = String(msg._action_effect_class || '')
  if (effectClass === 'pure') return runPureAction(cmd, msg)
  if (effectClass === 'reconcilable') return runEffectAction(cmd, msg)
  throw new Error('ACTION_EFFECT_CLASS_INVALID')
}

async function runEffectAction (cmd, msg) {
  const handler = ACTION_HANDLERS[cmd]
  if (!handler) throw new Error(`unknown action command ${cmd}`)
  const actionId = String(msg.action_id || '')
  const requestDigest = String(msg._request_digest || '')
  const rootUnitLineage = rootActionUnitLineage(msg)
  const sideEffects = actionSideEffectEnvelope(msg)
  const prepared = actionRecovery.begin(actionId, requestDigest, cmd, null, rootUnitLineage)
  if (!prepared.execute) {
    const executionControl = botActor.recordResult(
      actionId, requestDigest, prepared.record.disposition || 'unknown')
    emitActionResult(cmd, msg, {
      ...replayActionResult(cmd, prepared.record),
      child_effects: actionRecovery.descendants(actionId),
      execution_control: executionControl
    })
    return
  }
  const timeoutMs = runtime.actionTimeoutMs(msg)
  const cancellationScope = runtime.createActionCancellationScope(
    String(cmd) + ':' + actionId,
    timeoutMs
  )
  botActor.attachScope(actionId, requestDigest, cancellationScope)
  cancellationScope.onSkillChildTransition = (phase, index, actionType, outcome) =>
    botActor.childTransition(actionId, requestDigest, phase, index, actionType, outcome)
  // The host Unit graph is the sole capability-closure authority.  The bridge
  // validates and consumes opaque Unit digests but never re-derives which child
  // skills a composite ought to have; that would create a second semantic source.
  const invocationUnitDigest = rootUnitLineage.root_invocation_unit_digest
  const authorizationUnitDigest = rootUnitLineage.authorization_unit_digest
  const rawChildUnits = msg._authorized_child_action_units
  const childUnits = new Map()
  let skillAuthorizationDenied = !rawChildUnits || Array.isArray(rawChildUnits) ||
    typeof rawChildUnits !== 'object'
  if (!skillAuthorizationDenied) {
    for (const [name, digest] of Object.entries(rawChildUnits)) {
      if (!/^[a-z][a-z0-9_]*$/.test(name) || !/^[0-9a-f]{64}$/.test(String(digest || ''))) {
        skillAuthorizationDenied = true
        break
      }
      childUnits.set(name, String(digest))
    }
  }
  cancellationScope.authorizedChildActionUnits = childUnits
  cancellationScope.rootInvocationUnitDigest = invocationUnitDigest
  cancellationScope.authorizationUnitDigest = authorizationUnitDigest

  const rootEffectParent = {
    action_id: actionId,
    request_digest: requestDigest,
    root_invocation_unit_digest: invocationUnitDigest,
    authorization_unit_digest: authorizationUnitDigest
  }
  if (!skillAuthorizationDenied && childUnits.size > 0) {
    cancellationScope.createChildEffectRecorder = identity =>
      createSkillEffectRecorder(actionRecovery, {
        ...identity,
        root_invocation_unit_digest: invocationUnitDigest,
        authorization_unit_digest: authorizationUnitDigest
      }, childUnits)
    cancellationScope.recordChildEffect = createSkillEffectRecorder(
      actionRecovery, rootEffectParent, childUnits
    )
  }
  const effectBefore = actionEffectProjection(sideEffects)
  let result
  let recycleBridge = false
  try {
    result = skillAuthorizationDenied
      ? runtime.rejected(cmd, {}, 'SKILL_CHILD_AUTHORIZATION_MISSING', {},
        'not_applied')
      : await runtime.runWithActionCancellationScope(
      cancellationScope,
      () => runtime.withTimeout(
        Promise.resolve().then(() => handler(msg)),
        timeoutMs,
        `ACTION_${String(cmd).toUpperCase()}`
      )
    )
  } catch (error) {
    recycleBridge = Boolean(error && error.cleanup_failed)
    const effectAfter = actionEffectProjection(sideEffects)
    const observedEffect = actionEffectObserved(effectBefore, effectAfter)
    result = runtime.partial(cmd, {}, 'ACTION_HANDLER_BOUNDED_FAILURE', {
      error: String(error && error.message ? error.message : error),
      error_code: error && error.code ? String(error.code) : null,
      error_evidence: runtime.errorEvidence(error),
      timeout_ms: timeoutMs,
      cancellation_cleanup_failed: recycleBridge,
      cancellation_cleanup_errors: Array.isArray(error && error.cleanup_errors)
        ? error.cleanup_errors.map(String)
        : [],
      observed_effect: observedEffect,
      generic_projection_is_not_action_causality_proof: true,
      effect_before: effectBefore,
      effect_after: effectAfter
    }, 'unknown')
  }
  actionRecovery.complete(actionId, requestDigest, cmd, result)
  const executionControl = botActor.recordResult(actionId, requestDigest, result.effect_disposition)
  emitActionResult(cmd, msg, {
    ...result,
    child_effects: actionRecovery.descendants(actionId),
    execution_control: executionControl
  }, recycleBridge)
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
    // One coherent client-side observation cut, one JSONL request/ACK pair.
    // Emit one bounded entity table instead of N per-entity wire events.
    selfSnapshot(requestId)
    if (msg.include_entities === true) {
      const { rows } = currentEntityRows(
        Number(msg.entity_distance), Number(msg.entity_limit))
      emit('entity_snapshot', {
        entities: rows,
        max_distance: Number(msg.entity_distance),
        limit: Number(msg.entity_limit),
        scope: 'currently_loaded_and_observable'
      }, requestId)
    }
    ack(cmd, {}, requestId)
    return
  }
  if (cmd === 'setup_verify') {
    const activeBot = runtime.requireBot()
    const proof = verifySetupProjection(activeBot, msg.setup || {})
    ack(cmd, proof, requestId)
    return
  }
  if (cmd === 'setup_verify_wait') {
    const activeBot = runtime.requireBot()
    const timeoutMs = Number(msg.timeout_ms || 8000)
    const proof = await waitForSetupProjection(activeBot, msg.setup || {}, timeoutMs)
    ack(cmd, proof, requestId)
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
  if (
    (cmd === 'observe_entities' || cmd === 'observe_blocks') &&
    !String(msg.action_id || '').trim()
  ) {
    const result = cmd === 'observe_blocks'
      ? await observeBlocksAction(msg)
      : await observeEntitiesAction(msg)
    emitQueryResult(cmd, msg, result)
    return
  }
  if (cmd === 'prepare_action') {
    const actionId = String(msg.action_id || '')
    const requestDigest = String(msg.request_digest || '')
    const actionType = String(msg.action_type || '')
    const prepared = actionRecovery.prepare(
      actionId, requestDigest, actionType, rootActionUnitLineage(msg)
    )
    ack(cmd, {
      state: prepared.record.state,
      disposition: prepared.record.disposition,
      durability: actionRecovery.durability
    }, requestId)
    return
  }
  if (ACTION_HANDLERS[cmd]) {
    await runAction(cmd, msg)
    return
  }
  if (cmd === 'reconcile_action') {
    const proof = actionRecovery.reconcile(
      String(msg.action_id || ''),
      String(msg.request_digest || ''),
      rootActionUnitLineage(msg)
    )
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
  // Sideband control does not wait behind the active physical action.
  // It never invents a terminal world-effect receipt.
  if (message.cmd === 'interrupt_action') {
    const proof = botActor.interrupt(
      String(message.action_id || ''),
      String(message.request_digest || ''),
      String(message.reason || 'AGENT_INTERRUPTED')
    )
    ack('interrupt_action', proof, message.request_id || null)
    return
  }
  if (message.cmd === 'execution_status') {
    ack('execution_status', botActor.status(), message.request_id || null)
    return
  }
  const isAction = Object.hasOwn(ACTION_HANDLERS, String(message.cmd || ''))
  // Session observation probes intentionally have no action identity and
  // never start a durable physical-action journal.
  const identity = isAction && String(message.action_id || '').trim() ? {
    actionId: message.action_id,
    digest: message._request_digest,
    maxChildDepth: message._authorized_child_max_depth
  } : null
  let operationEntered = false
  const operation = () => {
    operationEntered = true
    return command(message)
  }
  Promise.resolve().then(() => botActor.dispatch(message.cmd, operation, identity)).catch(error => {
    const requestId = message.request_id || message.action_id || null
    const errorMessage = String(error && error.message ? error.message : error)
    const errorCode = String(error && error.code ? error.code : errorMessage)
    // Once an action identity exists, every terminal path must carry an
    // identity-bound action_result.  If dispatch rejected before operation()
    // entered, no physical effect was possible.  If operation() did enter,
    // conservatively preserve UNKNOWN rather than inventing no-effect truth.
    if (identity) {
      const details = {
        error: errorMessage,
        error_code: errorCode,
        dispatch_operation_entered: operationEntered
      }
      const result = operationEntered
        ? runtime.partial(
            String(message.cmd || ''), {}, 'ACTION_DISPATCH_FAILURE', details,
            'unknown'
          )
        : runtime.rejected(
            String(message.cmd || ''), {}, 'ACTION_DISPATCH_REJECTED', details,
            'not_applied'
          )
      emitActionResult(String(message.cmd || ''), message, result)
      return
    }
    emit('error', { message: errorMessage, cmd: message.cmd || null }, requestId)
    ack(String(message.cmd || ''), {
      verified: false,
      rejected: true,
      error: errorMessage
    }, requestId)
  })
})

module.exports = { ACTION_HANDLERS }
