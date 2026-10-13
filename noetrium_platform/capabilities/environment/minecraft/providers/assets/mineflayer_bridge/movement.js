'use strict'

const runtime = require('./runtime')
const worldFrontier = require('./world_frontier')
const { suggestRegistryKind } = require('./registry_search')

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

function completedMovementResult (tool, action, code, evidence) {
  // Goal satisfaction and physical effect truth are separate. If the actor is
  // already in the requested end-set, the command succeeded as a predicate but
  // caused no world transition and therefore must not reset effect watchdogs.
  const details = { ...evidence, goal_satisfied: true }
  return Number.isFinite(details.moved) && details.moved > 0
    ? runtime.applied(tool, action, code, details)
    : runtime.satisfied(tool, action, code, details)
}

async function goto (msg) {
  const action = { position: msg.position, radius: Number(msg.radius || 1.5) }
  const activeBot = runtime.getBot()
  const start = activeBot.entity.position.clone()
  try {
    const outcome = await runtime.gotoPos(msg.position || {}, action.radius)
    const evidence = movementEvidence(start, activeBot, outcome)
    return outcome.within_radius
      ? completedMovementResult('goto', action, 'TARGET_REACHED', evidence)
      : incompleteMovementResult('goto', action, 'TARGET_NOT_CONFIRMED', evidence)
  } catch (error) {
    const evidence = movementEvidence(start, activeBot, { navigation_error: runtime.errorEvidence(error) })
    return incompleteMovementResult('goto', action, 'PATH_INTERRUPTED', evidence)
  }
}

async function gotoBlock (msg) {
  const action = {
    block: String(msg.block || ''),
    max_distance: Number(msg.max_distance || 64)
  }
  const activeBot = runtime.getBot()
  const blockRegistry = activeBot.registry.blocksByName
  const blockType = blockRegistry && blockRegistry[action.block]
  if (blockRegistry && !blockType) {
    const entityType = activeBot.registry.entitiesByName && activeBot.registry.entitiesByName[action.block]
    const itemType = activeBot.registry.itemsByName && activeBot.registry.itemsByName[action.block]
    const classification = entityType ? 'entity' : itemType ? 'item' : 'unknown'
    const code = entityType
      ? 'TARGET_IS_ENTITY_NOT_BLOCK'
      : itemType
        ? 'TARGET_IS_ITEM_NOT_BLOCK'
        : 'UNKNOWN_BLOCK_TYPE'
    const canonicalCandidates = classification === 'unknown'
      ? suggestRegistryKind(activeBot.registry, action.block, 'block')
      : []
    return runtime.rejected('goto_block', action, code, {
      semantic_domain: 'minecraft.block_name',
      target_classification: classification,
      canonical_candidates: canonicalCandidates,
      resolution: { status: canonicalCandidates.length > 0 ? 'candidates_available' : 'unknown_name' },
      rejected_argument_constraints: [{
        argument_path: ['block'],
        rejected_value: action.block,
        validity: { while_provider_instance: true }
      }]
    })
  }
  // A loaded block already in the exact physical end-set is sufficient to
  // satisfy the navigation intent; do not run A* for a zero-distance goal.
  const observedGoal = runtime.observedGetToBlockGoal(activeBot, action.block, action.max_distance)
  if (observedGoal) {
    return completedMovementResult('goto_block', action, 'BLOCK_REACHED', {
      block: action.block,
      block_position: runtime.vec(observedGoal),
      position: runtime.vec(activeBot.entity.position),
      moved: 0,
      loaded_world_candidate_count: 1,
      target_selection: 'observed-goal-endpoint'
    })
  }
  const positions = typeof activeBot.findBlocks === 'function'
    ? activeBot.findBlocks({
        matching: candidate => candidate && candidate.name === action.block,
        maxDistance: action.max_distance,
        count: Number.POSITIVE_INFINITY
      })
    : (() => {
        const candidate = activeBot.findBlock({
          matching: block => block && block.name === action.block,
          maxDistance: action.max_distance
        })
        return candidate && candidate.position ? [candidate.position] : []
      })()
  if (!Array.isArray(positions) || positions.length === 0) {
    const details = {
      semantic_domain: 'minecraft.block_name',
      target_classification: 'block',
      prerequisites: {
        nearby_target_observed: false,
        searched_max_distance: action.max_distance
      }
    }
    details.world_frontier = worldFrontier.observeWorldFrontiers(activeBot, action.max_distance)
    return runtime.rejected('goto_block', action, 'BLOCK_NOT_FOUND', details)
  }
  const start = activeBot.entity.position.clone()
  try {
    const outcome = await runtime.gotoAnyBlockVicinity(positions)
    const details = movementEvidence(start, activeBot, {
      ...outcome,
      block: action.block,
      block_position: outcome.target,
      loaded_world_candidate_count: positions.length,
      target_selection: 'pathfinder_goal_any_get_to_block_kd'
    })
    return runtime.applied('goto_block', action, 'BLOCK_REACHED', details)
  } catch (error) {
    const details = movementEvidence(start, activeBot, {
      block: action.block,
      loaded_world_candidate_count: positions.length,
      target_selection: 'pathfinder_goal_any_get_to_block_kd',
      navigation_error: runtime.errorEvidence(error),
      prerequisites: {
        provider_navigation_recovery_exhausted: true
      }
    })
    return incompleteMovementResult('goto_block', action, 'PATH_INTERRUPTED', details)
  }
}

async function gotoEntity (msg) {
  const action = {
    entity: String(msg.entity || ''),
    max_distance: Number(msg.max_distance || 64),
    radius: Number(msg.radius || 2.5)
  }
  const activeBot = runtime.getBot()
  const entityRegistry = activeBot.registry.entitiesByName
  const entityType = entityRegistry && entityRegistry[action.entity]
  if (entityRegistry && !entityType) {
    const blockType = activeBot.registry.blocksByName && activeBot.registry.blocksByName[action.entity]
    const itemType = activeBot.registry.itemsByName && activeBot.registry.itemsByName[action.entity]
    const classification = blockType ? 'block' : itemType ? 'item' : 'unknown'
    const code = blockType
      ? 'TARGET_IS_BLOCK_NOT_ENTITY'
      : itemType
        ? 'TARGET_IS_ITEM_NOT_ENTITY'
        : 'UNKNOWN_ENTITY_TYPE'
    const canonicalCandidates = classification === 'unknown'
      ? suggestRegistryKind(activeBot.registry, action.entity, 'entity')
      : []
    return runtime.rejected('goto_entity', action, code, {
      semantic_domain: 'minecraft.entity_type',
      target_classification: classification,
      canonical_candidates: canonicalCandidates,
      resolution: { status: canonicalCandidates.length > 0 ? 'candidates_available' : 'unknown_name' }
    })
  }
  const entity = runtime.findEntity(action.entity, action.max_distance)
  const start = activeBot.entity.position.clone()
  if (!entity) {
    return runtime.rejected('goto_entity', action, 'ENTITY_NOT_FOUND', {
      semantic_domain: 'minecraft.entity_type',
      target_classification: 'entity',
      world_frontier: worldFrontier.observeWorldFrontiers(activeBot, action.max_distance),
      prerequisites: { target_observed: false }
    })
  }
  try {
    const outcome = await runtime.gotoEntity(
      entity,
      action.radius,
      runtime.actionRemainingMs()
    )
    const live = activeBot.entities[entity.id]
    const distance = live && live.position ? live.position.distanceTo(activeBot.entity.position) : outcome.distance
    const details = movementEvidence(start, activeBot, {
      ...outcome,
      entity_id: entity.id,
      entity_distance: distance
    })
    return outcome.goal_satisfied
      ? completedMovementResult('goto_entity', action, 'ENTITY_REACHED', details)
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
  const action = {
    distance: Number(msg.distance || 8),
    entity: msg.entity == null ? null : String(msg.entity),
    max_distance: Number(msg.max_distance || 64)
  }
  const start = activeBot.entity.position.clone()

  if (action.entity) {
    const entity = runtime.findEntity(action.entity, action.max_distance)
    if (!entity) {
      return runtime.rejected('move_away', action, 'ENTITY_NOT_FOUND', {
        semantic_domain: 'minecraft.entity_type',
        target_observed: false
      })
    }
    const beforeDistance = entity.position.distanceTo(start)
    try {
      const navigation = await runtime.moveAwayFromEntity(entity, action.distance)
      const live = activeBot.entities[entity.id]
      const afterDistance = (
        live && live.position
          ? live.position.distanceTo(activeBot.entity.position)
          : navigation.distance
      )
      const details = movementEvidence(start, activeBot, {
        ...navigation,
        target_entity_id: entity.id,
        target_entity: action.entity,
        distance_before: beforeDistance,
        distance_after: afterDistance
      })
      return navigation.goal_satisfied
        ? runtime.applied('move_away', action, 'ENTITY_DISTANCE_CREATED', details)
        : incompleteMovementResult(
          'move_away',
          action,
          'ENTITY_DISTANCE_NOT_CONFIRMED',
          details
        )
    } catch (error) {
      const live = activeBot.entities[entity.id]
      const afterDistance = (
        live && live.position
          ? live.position.distanceTo(activeBot.entity.position)
          : null
      )
      const details = movementEvidence(start, activeBot, {
        target_entity_id: entity.id,
        target_entity: action.entity,
        distance_before: beforeDistance,
        distance_after: afterDistance,
        navigation_error: runtime.errorEvidence(error)
      })
      return Number.isFinite(afterDistance) && afterDistance > beforeDistance
        ? runtime.partial(
          'move_away',
          action,
          'ENTITY_DISTANCE_INCREASED',
          details,
          'applied'
        )
        : incompleteMovementResult(
          'move_away',
          action,
          'PATH_INTERRUPTED',
          details
        )
    }
  }

  const yaw = Number(activeBot.entity.yaw || 0)
  const target = start.offset(
    -Math.sin(yaw) * action.distance,
    0,
    Math.cos(yaw) * action.distance
  )
  let navigation
  try {
    navigation = await runtime.gotoPos(target, 1.5)
  } catch (error) {
    const details = movementEvidence(
      start,
      activeBot,
      { navigation_error: runtime.errorEvidence(error) }
    )
    return incompleteMovementResult('move_away', action, 'PATH_INTERRUPTED', details)
  }
  const details = movementEvidence(start, activeBot, navigation)
  return navigation.goal_satisfied || navigation.within_radius
    ? completedMovementResult('move_away', action, 'DISTANCE_CREATED', details)
    : incompleteMovementResult(
      'move_away',
      action,
      'DISTANCE_NOT_CONFIRMED',
      details
    )
}

module.exports = { goto, goto_block: gotoBlock, goto_entity: gotoEntity, move_away: moveAway }
