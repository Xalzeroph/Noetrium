'use strict'

const CARDINAL_XZ = Object.freeze([
  Object.freeze({ x: 1, z: 0 }),
  Object.freeze({ x: -1, z: 0 }),
  Object.freeze({ x: 0, z: 1 }),
  Object.freeze({ x: 0, z: -1 })
])

function pathfinderMovements (activeBot) {
  return activeBot && activeBot.pathfinder
    ? activeBot.pathfinder.movements || null
    : null
}

function replaceableAt (activeBot, position) {
  const block = activeBot.blockAt(position)
  if (!block) return false
  const movements = pathfinderMovements(activeBot)
  if (
    movements &&
    movements.replaceables instanceof Set &&
    Number.isFinite(Number(block.type))
  ) {
    return movements.replaceables.has(block.type)
  }
  return block.boundingBox === 'empty'
}

function safeSupportAt (activeBot, position) {
  const block = activeBot.blockAt(position)
  if (!block || block.boundingBox !== 'block') return false
  const movements = pathfinderMovements(activeBot)
  if (
    movements &&
    movements.blocksToAvoid instanceof Set &&
    movements.blocksToAvoid.has(block.type)
  ) return false
  return true
}

function localPlacementTargets (activeBot) {
  if (!activeBot || !activeBot.entity || !activeBot.entity.position) return []
  if (typeof activeBot.blockAt !== 'function') return []
  const base = activeBot.entity.position.floored()
  const targets = []
  for (const offset of CARDINAL_XZ) {
    const target = base.offset(offset.x, 0, offset.z)
    if (!replaceableAt(activeBot, target)) continue
    if (!safeSupportAt(activeBot, target.offset(0, -1, 0))) continue
    targets.push(target)
  }
  return targets
}

module.exports = {
  CARDINAL_XZ,
  localPlacementTargets,
  replaceableAt,
  safeSupportAt
}
