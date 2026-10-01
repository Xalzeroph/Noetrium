'use strict'

const runtime = require('./runtime')

function movementEvidence (start, activeBot, details = {}) {
  const end = activeBot.entity.position.clone()
  const moved = end.distanceTo(start)
  return {
    ...details,
    start: runtime.vec(start),
    position: runtime.vec(end),
    moved
  }
}

function incompleteMovementResult (tool, action, code, evidence) {
  // External-effect certainty is stricter than task success. Any observable
  // displacement means the navigation effect already happened and must not be
  // blindly replayed, even when the requested target was not reached. Only an
  // exactly unchanged, observable terminal position proves NOT_APPLIED.
  return Number.isFinite(evidence.moved) && evidence.moved > 0
    ? runtime.partial(tool, action, code, evidence, 'applied')
    : runtime.rejected(tool, action, code, evidence, 'not_applied')
}

async function goto (msg) {
  const action = { position: msg.position, radius: Number(msg.radius || 1.5) }
  const activeBot = runtime.getBot()
  const start = activeBot.entity.position.clone()
  try {
    const outcome = await runtime.gotoPos(msg.position || {}, action.radius)
    const evidence = movementEvidence(start, activeBot, outcome)
    return outcome.within_radius
      ? runtime.applied('goto', action, 'TARGET_REACHED', evidence)
      : incompleteMovementResult('goto', action, 'TARGET_NOT_CONFIRMED', evidence)
  } catch (error) {
    const evidence = movementEvidence(start, activeBot, { navigation_error: runtime.errorEvidence(error) })
    return incompleteMovementResult('goto', action, 'PATH_INTERRUPTED', evidence)
  }
}

async function gotoEntity (msg) {
  const action = {
    entity: String(msg.entity || ''),
    max_distance: Number(msg.max_distance || 64),
    radius: Number(msg.radius || 2.5)
  }
  const entity = runtime.findEntity(action.entity, action.max_distance)
  if (!entity) return runtime.rejected('goto_entity', action, 'ENTITY_NOT_FOUND')
  const activeBot = runtime.getBot()
  const start = activeBot.entity.position.clone()
  try {
    const outcome = await runtime.gotoEntity(entity, action.radius)
    const live = activeBot.entities[entity.id]
    const distance = live && live.position ? live.position.distanceTo(activeBot.entity.position) : outcome.distance
    const details = movementEvidence(start, activeBot, { ...outcome, entity_id: entity.id, entity_distance: distance })
    return distance <= action.radius + 1.5
      ? runtime.applied('goto_entity', action, 'ENTITY_REACHED', details)
      : incompleteMovementResult('goto_entity', action, 'ENTITY_MOVED', details)
  } catch (error) {
    const details = movementEvidence(start, activeBot, {
      entity_id: entity.id,
      navigation_error: runtime.errorEvidence(error)
    })
    return incompleteMovementResult('goto_entity', action, 'PATH_INTERRUPTED', details)
  }
}

async function moveAway (msg) {
  const activeBot = runtime.getBot()
  const distance = Number(msg.distance || 8)
  const start = activeBot.entity.position.clone()
  const yaw = Number(activeBot.entity.yaw || 0)
  const target = start.offset(-Math.sin(yaw) * distance, 0, Math.cos(yaw) * distance)
  let navigation
  try {
    navigation = await runtime.gotoPos(target, 1.5)
  } catch (error) {
    const details = movementEvidence(start, activeBot, { navigation_error: runtime.errorEvidence(error) })
    return details.moved >= Math.max(2, distance * 0.6)
      ? runtime.applied('move_away', { distance }, 'DISTANCE_CREATED', details)
      : incompleteMovementResult('move_away', { distance }, 'PATH_INTERRUPTED', details)
  }
  const details = movementEvidence(start, activeBot, navigation)
  return details.moved >= Math.max(2, distance * 0.6)
    ? runtime.applied('move_away', { distance }, 'DISTANCE_CREATED', details)
    : incompleteMovementResult('move_away', { distance }, 'DISTANCE_NOT_CONFIRMED', details)
}

module.exports = { goto, goto_entity: gotoEntity, move_away: moveAway }
