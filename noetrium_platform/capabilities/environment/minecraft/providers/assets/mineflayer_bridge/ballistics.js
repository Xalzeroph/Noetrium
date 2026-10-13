'use strict'

const { Vec3 } = require('vec3')

// Minecraft projectile constants, centralized as physical world semantics.
// These are not scheduling/tuning knobs.
const ARROW_DRAG = 0.99
const ARROW_GRAVITY = 0.05
const BOW_FULL_DRAW_TICKS = 20
const CROSSBOW_BASE_CHARGE_TICKS = 25
const QUICK_CHARGE_REDUCTION_TICKS = 5

const PROJECTILE_PHYSICS = Object.freeze({
  bow: Object.freeze({
    speed: 3,
    drag: ARROW_DRAG,
    gravity: ARROW_GRAVITY
  }),
  crossbow: Object.freeze({
    speed: 3.15,
    drag: ARROW_DRAG,
    gravity: ARROW_GRAVITY
  })
})

function finiteVec (value) {
  if (!value) return null
  const x = Number(value.x)
  const y = Number(value.y)
  const z = Number(value.z)
  return Number.isFinite(x) && Number.isFinite(y) && Number.isFinite(z)
    ? new Vec3(x, y, z)
    : null
}

function enchantmentLevel (item, name) {
  const rows = item && Array.isArray(item.enchants) ? item.enchants : []
  let level = 0
  for (const row of rows) {
    if (!row || String(row.name || '') !== String(name)) continue
    const parsed = Number(row.lvl)
    if (Number.isFinite(parsed)) level = Math.max(level, parsed)
  }
  return level
}

function chargeTicks (weapon) {
  if (!weapon || !weapon.name) return null
  if (weapon.name === 'bow') return BOW_FULL_DRAW_TICKS
  if (weapon.name === 'crossbow') {
    return Math.max(
      1,
      CROSSBOW_BASE_CHARGE_TICKS -
      QUICK_CHARGE_REDUCTION_TICKS * enchantmentLevel(weapon, 'quick_charge')
    )
  }
  return null
}

function physicsFor (weapon, ammo) {
  if (!weapon || !weapon.name) return null
  if (ammo !== 'arrow') return null
  return PROJECTILE_PHYSICS[weapon.name] || null
}

function dragSeries (drag, ticks) {
  if (drag === 1) return ticks
  return (1 - Math.pow(drag, ticks)) / (1 - drag)
}

function futureTargetCenter (target, velocity, ticks) {
  return target.position
    .offset(0, Number(target.height) / 2, 0)
    .plus(velocity.scaled(ticks))
}

function inheritedShooterVelocity (activeBot) {
  const velocity = finiteVec(activeBot.entity.velocity) || new Vec3(0, 0, 0)
  // Vanilla projectile launch inherits horizontal motion. Grounded vertical
  // motion is not a launch contribution.
  if (activeBot.entity.onGround) velocity.y = 0
  return velocity
}

function requiredLaunchVector (
  activeBot,
  target,
  targetVelocity,
  physics,
  ticks
) {
  if (!(ticks > 0)) return null
  const eyeHeight = Number(activeBot.entity.eyeHeight)
  if (!Number.isFinite(eyeHeight)) return null
  const origin = activeBot.entity.position.offset(0, eyeHeight, 0)
  const destination = futureTargetCenter(target, targetVelocity, ticks)
  const displacement = destination.minus(origin)
  const series = dragSeries(physics.drag, ticks)
  if (!Number.isFinite(series) || series <= 0) return null

  const gravityTerm = (
    physics.gravity / (1 - physics.drag) *
    (ticks - series)
  )
  const requiredTotal = new Vec3(
    displacement.x / series,
    (displacement.y + gravityTerm) / series,
    displacement.z / series
  )
  return requiredTotal.minus(inheritedShooterVelocity(activeBot))
}

function speedError (activeBot, target, targetVelocity, physics, ticks) {
  const vector = requiredLaunchVector(
    activeBot,
    target,
    targetVelocity,
    physics,
    ticks
  )
  return vector ? vector.norm() - physics.speed : Number.POSITIVE_INFINITY
}

function flightUpperBound (activeBot, physics) {
  const eyeHeight = Number(activeBot.entity.eyeHeight)
  const minY = Number(activeBot.game && activeBot.game.minY)
  if (!Number.isFinite(eyeHeight) || !Number.isFinite(minY)) return null
  if (!(physics.gravity > 0) || !(physics.drag > 0 && physics.drag < 1)) return null

  const originY = Number(activeBot.entity.position.y) + eyeHeight
  const inherited = inheritedShooterVelocity(activeBot)
  let previous = Number.NEGATIVE_INFINITY
  let descending = false
  for (let ticks = 1; ; ticks += 1) {
    const series = dragSeries(physics.drag, ticks)
    const maxY = (
      originY +
      (physics.speed + inherited.y) * series -
      physics.gravity / (1 - physics.drag) * (ticks - series)
    )
    if (maxY < previous) descending = true
    if (descending && maxY < minY) return ticks
    previous = maxY
  }
}

function bisectRoot (
  activeBot,
  target,
  targetVelocity,
  physics,
  lower,
  upper
) {
  let lo = lower
  let hi = upper
  let flo = lo === 0
    ? Number.POSITIVE_INFINITY
    : speedError(activeBot, target, targetVelocity, physics, lo)
  const tolerance = Math.sqrt(Number.EPSILON) * Math.max(1, physics.speed)

  for (;;) {
    const mid = (lo + hi) / 2
    if (mid === lo || mid === hi) return mid
    const fmid = speedError(
      activeBot,
      target,
      targetVelocity,
      physics,
      mid
    )
    if (Math.abs(fmid) <= tolerance) return mid
    if ((flo > 0) === (fmid > 0)) {
      lo = mid
      flo = fmid
    } else {
      hi = mid
    }
  }
}

function candidateFlightTimes (activeBot, target, targetVelocity, physics) {
  const upper = flightUpperBound(activeBot, physics)
  if (!Number.isInteger(upper) || upper < 1) return []

  const brackets = []
  let bestTick = 1
  let bestAbsError = Number.POSITIVE_INFINITY
  let previousTick = 0
  let previousError = Number.POSITIVE_INFINITY

  for (let tick = 1; tick <= upper; tick += 1) {
    const error = speedError(
      activeBot,
      target,
      targetVelocity,
      physics,
      tick
    )
    const absolute = Math.abs(error)
    if (absolute < bestAbsError) {
      bestAbsError = absolute
      bestTick = tick
    }
    if (Number.isFinite(error) && (previousError > 0) !== (error > 0)) {
      brackets.push([previousTick, tick])
    }
    previousTick = tick
    previousError = error
  }

  const roots = brackets.map(([lo, hi]) => bisectRoot(
    activeBot,
    target,
    targetVelocity,
    physics,
    lo,
    hi
  ))
  roots.push(bestTick)

  roots.sort((a, b) => a - b)
  const tolerance = Math.sqrt(Number.EPSILON)
  return roots.filter((value, index) => (
    index === 0 || Math.abs(value - roots[index - 1]) > tolerance
  ))
}

function staticTargetAabb (target) {
  const width = Number(target.width)
  const height = Number(target.height)
  if (!(width > 0) || !(height > 0)) return null
  return {
    minX: -width / 2,
    maxX: width / 2,
    minY: 0,
    maxY: height,
    minZ: -width / 2,
    maxZ: width / 2
  }
}

function segmentAabbFraction (start, end, box) {
  let low = 0
  let high = 1
  for (const [startValue, endValue, minValue, maxValue] of [
    [start.x, end.x, box.minX, box.maxX],
    [start.y, end.y, box.minY, box.maxY],
    [start.z, end.z, box.minZ, box.maxZ]
  ]) {
    const delta = endValue - startValue
    if (delta === 0) {
      if (startValue < minValue || startValue > maxValue) return null
      continue
    }
    let a = (minValue - startValue) / delta
    let b = (maxValue - startValue) / delta
    if (a > b) [a, b] = [b, a]
    low = Math.max(low, a)
    high = Math.min(high, b)
    if (low > high) return null
  }
  return low
}

function blockHitFraction (activeBot, start, end) {
  if (!activeBot.world || typeof activeBot.world.raycast !== 'function') {
    return null
  }
  const delta = end.minus(start)
  const distance = delta.norm()
  if (!(distance > 0)) return null
  const hit = activeBot.world.raycast(start, delta.scaled(1 / distance), distance)
  if (!hit) return null
  const point = finiteVec(hit.intersect)
  if (!point) return 0
  return Math.min(1, Math.max(0, start.distanceTo(point) / distance))
}

function simulateCandidate (
  activeBot,
  target,
  targetVelocity,
  physics,
  launchVector,
  flightTicks
) {
  const eyeHeight = Number(activeBot.entity.eyeHeight)
  const targetBox = staticTargetAabb(target)
  if (!Number.isFinite(eyeHeight) || !targetBox) {
    return { hit: false, reason: 'geometry_unavailable' }
  }

  let position = activeBot.entity.position.offset(0, eyeHeight, 0)
  let velocity = launchVector.plus(inheritedShooterVelocity(activeBot))
  const steps = Math.max(1, Math.ceil(flightTicks) + 1)

  for (let tick = 0; tick < steps; tick += 1) {
    const next = position.plus(velocity)
    const targetNow = target.position.plus(targetVelocity.scaled(tick))
    const targetNext = target.position.plus(targetVelocity.scaled(tick + 1))
    const relativeStart = position.minus(targetNow)
    const relativeEnd = next.minus(targetNext)
    const entityFraction = segmentAabbFraction(
      relativeStart,
      relativeEnd,
      targetBox
    )
    const worldFraction = blockHitFraction(activeBot, position, next)

    if (
      entityFraction !== null &&
      (worldFraction === null || entityFraction < worldFraction)
    ) {
      return {
        hit: true,
        hit_tick: tick,
        hit_fraction: entityFraction,
        block_fraction: worldFraction
      }
    }
    if (worldFraction !== null) {
      return {
        hit: false,
        reason: 'blocked',
        blocked_tick: tick,
        block_fraction: worldFraction
      }
    }

    position = next
    velocity = velocity.scaled(physics.drag)
    velocity.y -= physics.gravity
  }
  return { hit: false, reason: 'target_not_intersected' }
}

function launchAngles (launchVector) {
  const horizontal = Math.hypot(launchVector.x, launchVector.z)
  return {
    yaw: Math.atan2(-launchVector.x, -launchVector.z),
    pitch: Math.atan2(launchVector.y, horizontal)
  }
}

function solveArrowShot (activeBot, target, weapon) {
  const physics = physicsFor(weapon, 'arrow')
  if (!physics) return null
  const targetVelocity = finiteVec(target.velocity) || new Vec3(0, 0, 0)
  const candidates = candidateFlightTimes(
    activeBot,
    target,
    targetVelocity,
    physics
  )

  const evaluated = []
  for (const flightTicks of candidates) {
    const required = requiredLaunchVector(
      activeBot,
      target,
      targetVelocity,
      physics,
      flightTicks
    )
    if (!required || !(required.norm() > 0)) continue
    const launchVector = required.scaled(physics.speed / required.norm())
    const simulation = simulateCandidate(
      activeBot,
      target,
      targetVelocity,
      physics,
      launchVector,
      flightTicks
    )
    evaluated.push({
      flight_ticks: flightTicks,
      simulation
    })
    if (!simulation.hit) continue
    return {
      ...launchAngles(launchVector),
      flight_ticks: flightTicks,
      target_velocity: {
        x: targetVelocity.x,
        y: targetVelocity.y,
        z: targetVelocity.z
      },
      physics: {
        speed: physics.speed,
        drag: physics.drag,
        gravity: physics.gravity
      },
      candidate_count: candidates.length,
      simulation
    }
  }
  return {
    hit: false,
    candidate_count: candidates.length,
    evaluated
  }
}

module.exports = {
  PROJECTILE_PHYSICS,
  chargeTicks,
  solveArrowShot
}
