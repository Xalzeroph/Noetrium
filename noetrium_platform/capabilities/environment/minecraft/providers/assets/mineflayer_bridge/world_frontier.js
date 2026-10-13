'use strict'

// The provider reports only client-loaded chunk geometry. Choosing where to
// explore is a Method decision, never an implicit side effect of observation,
// collection or navigation.
const MINECRAFT_CHUNK_EDGE = 16

function key (x, z) {
  return String(x) + ',' + String(z)
}

function uniqueLoadedColumns (activeBot) {
  const rows = activeBot && activeBot.world && typeof activeBot.world.getColumns === 'function'
    ? activeBot.world.getColumns()
    : null
  if (!Array.isArray(rows)) return new Map()
  const unique = new Map()
  for (const row of rows) {
    const x = Number(row && row.chunkX)
    const z = Number(row && row.chunkZ)
    if (Number.isInteger(x) && Number.isInteger(z)) {
      unique.set(key(x, z), { chunkX: x, chunkZ: z })
    }
  }
  return unique
}

function loadedColumns (activeBot) {
  return [...uniqueLoadedColumns(activeBot).values()].sort(
    (a, b) => a.chunkX - b.chunkX || a.chunkZ - b.chunkZ
  )
}

function loadedWorldCoverageRadius (activeBot) {
  if (!activeBot || !activeBot.entity || !activeBot.entity.position) return null
  // This is a commutative max reduction: sorting/deduplicating columns
  // changes neither the answer nor the physical evidence. Scan the raw
  // loaded-column stream once, O(N) time and O(1) auxiliary space.
  const columns = activeBot.world && typeof activeBot.world.getColumns === 'function'
    ? activeBot.world.getColumns()
    : null
  if (!Array.isArray(columns) || columns.length === 0) return null
  const { x, z } = activeBot.entity.position
  let maximum = 0
  let observed = 0
  for (const column of columns) {
    const chunkX = Number(column && column.chunkX)
    const chunkZ = Number(column && column.chunkZ)
    if (!Number.isInteger(chunkX) || !Number.isInteger(chunkZ)) continue
    observed += 1
    const centerX = chunkX * MINECRAFT_CHUNK_EDGE + MINECRAFT_CHUNK_EDGE / 2
    const centerZ = chunkZ * MINECRAFT_CHUNK_EDGE + MINECRAFT_CHUNK_EDGE / 2
    const dx = x - centerX
    const dz = z - centerZ
    maximum = Math.max(maximum, dx * dx + dz * dz)
  }
  return observed ? Math.sqrt(maximum) + Math.SQRT2 * MINECRAFT_CHUNK_EDGE / 2 : null
}

const NEIGHBORS = Object.freeze([
  Object.freeze([-1, 0]), Object.freeze([1, 0]),
  Object.freeze([0, -1]), Object.freeze([0, 1])
])

function observeWorldFrontiers (activeBot, maxDistance) {
  const origin = activeBot && activeBot.entity && activeBot.entity.position
  const distance = Number(maxDistance)
  if (!origin || !Number.isFinite(distance) || distance <= 0) {
    return { truth_class: 'observed', status: 'unavailable', candidates: [] }
  }
  // Build the exact loaded-column membership set once. Most columns lie
  // inside the loaded area, so sort only the exposed boundary candidates
  // rather than sorting every world column. Output remains canonical.
  const loaded = uniqueLoadedColumns(activeBot)
  const candidates = []
  const maxSquared = distance * distance
  for (const column of loaded.values()) {
    const x = column.chunkX * MINECRAFT_CHUNK_EDGE + MINECRAFT_CHUNK_EDGE / 2
    const z = column.chunkZ * MINECRAFT_CHUNK_EDGE + MINECRAFT_CHUNK_EDGE / 2
    const dx = x - origin.x
    const dz = z - origin.z
    const distanceSquared = dx * dx + dz * dz
    if (!Number.isFinite(distanceSquared) || distanceSquared > maxSquared) continue
    let unloaded = 0
    for (const [stepX, stepZ] of NEIGHBORS) {
      if (!loaded.has(key(column.chunkX + stepX, column.chunkZ + stepZ))) unloaded++
    }
    if (unloaded === 0) continue
    candidates.push({
      chunk_x: column.chunkX,
      chunk_z: column.chunkZ,
      center_x: x,
      center_z: z,
      distance_xz: Math.sqrt(distanceSquared),
      adjacent_columns_not_loaded: unloaded,
      path_reachable: null
    })
  }
  candidates.sort((a, b) => a.chunk_x - b.chunk_x || a.chunk_z - b.chunk_z)
  return {
    truth_class: 'observed',
    authoritative_for_unloaded_world: false,
    status: loaded.size ? 'observed_loaded_boundaries' : 'no_loaded_columns',
    loaded_column_count: loaded.size,
    searched_max_distance: distance,
    candidates
  }
}

module.exports = {
  MINECRAFT_CHUNK_EDGE,
  loadedColumns,
  loadedWorldCoverageRadius,
  observeWorldFrontiers
}
