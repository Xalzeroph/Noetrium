'use strict'

const runtime = require('./runtime')

async function goto (msg) {
  const action = { position: msg.position, radius: Number(msg.radius || 1.5) }
  const outcome = await runtime.gotoPos(msg.position || {}, action.radius)
  return outcome.within_radius
    ? runtime.applied('goto', action, 'TARGET_REACHED', outcome)
    : runtime.partial('goto', action, 'TARGET_NOT_CONFIRMED', outcome)
}

async function gotoEntity (msg) {
  const action = {
    entity: String(msg.entity || ''),
    max_distance: Number(msg.max_distance || 64),
    radius: Number(msg.radius || 2.5)
  }
  const entity = runtime.findEntity(action.entity, action.max_distance)
  if (!entity) return runtime.rejected('goto_entity', action, 'ENTITY_NOT_FOUND')
  const outcome = await runtime.gotoEntity(entity, action.radius)
  const activeBot = runtime.getBot()
  const live = activeBot.entities[entity.id]
  const distance = live && live.position ? live.position.distanceTo(activeBot.entity.position) : outcome.distance
  const details = { ...outcome, entity_id: entity.id, entity_distance: distance }
  return distance <= action.radius + 1.5
    ? runtime.applied('goto_entity', action, 'ENTITY_REACHED', details)
    : runtime.partial('goto_entity', action, 'ENTITY_MOVED', details)
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
    const moved = activeBot.entity.position.distanceTo(start)
    return moved >= Math.max(2, distance * 0.6)
      ? runtime.applied('move_away', { distance }, 'DISTANCE_CREATED', { moved, navigation_error: error.message })
      : runtime.partial('move_away', { distance }, 'PATH_INTERRUPTED', { moved, navigation_error: error.message })
  }
  const moved = activeBot.entity.position.distanceTo(start)
  const details = { moved, start: runtime.vec(start), ...navigation }
  return moved >= Math.max(2, distance * 0.6)
    ? runtime.applied('move_away', { distance }, 'DISTANCE_CREATED', details)
    : runtime.partial('move_away', { distance }, 'DISTANCE_NOT_CONFIRMED', details)
}

module.exports = { goto, goto_entity: gotoEntity, move_away: moveAway }
