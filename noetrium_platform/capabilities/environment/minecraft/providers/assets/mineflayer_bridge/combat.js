'use strict'

const runtime = require('./runtime')
const ballistics = require('./ballistics')
const { suggestRegistryKind } = require('./registry_search')

function isHostileEntity (activeBot, entity) {
  if (!entity || entity.isValid === false) return false
  const name = String(entity.name || '').trim()
  if (!name) return false
  const canonical = activeBot.registry &&
    activeBot.registry.entitiesByName &&
    activeBot.registry.entitiesByName[name]
  return Boolean(canonical && canonical.type === 'hostile')
}


function isDeclaredWeapon (activeBot, item) {
  if (!item || !item.name) return false
  const definition = activeBot.registry && activeBot.registry.itemsByName
    ? activeBot.registry.itemsByName[item.name]
    : null
  return Boolean(
    definition &&
    Array.isArray(definition.enchantCategories) &&
    definition.enchantCategories.includes('weapon')
  )
}

// Combat uses the exact version-pinned registry already bound to the bot.
 // No parallel Minecraft material-tier table or benchmark-specific weapon rule.
 // If the registry does not declare damage, durability is used strictly as a
 // conservative wear/availability proxy, never labeled an optimal DPS claim.
function observedWeaponQuality (activeBot, item) {
  const definition = activeBot.registry.itemsByName[item.name]
  const maximum = Number(item.maxDurability ?? definition.maxDurability)
  const used = Number(item.durabilityUsed ?? 0)
  const remaining = Number.isFinite(maximum) && maximum > 0
    ? Math.max(0, maximum - (Number.isFinite(used) ? Math.max(0, used) : 0))
    : null
  const rawDamage = Number(definition.attackDamage)
  const hasDamage = Number.isFinite(rawDamage) && rawDamage > 0
  const categories = Array.isArray(definition.enchantCategories)
    ? definition.enchantCategories : []
  return {
    item,
    declared_damage: hasDamage ? rawDamage : null,
    durability_remaining: remaining,
    durability_maximum: Number.isFinite(maximum) && maximum > 0 ? maximum : null,
    is_sword: categories.includes('sword'),
    currently_held: activeBot.heldItem === item ||
      (activeBot.heldItem && activeBot.heldItem.slot === item.slot &&
       activeBot.heldItem.name === item.name)
  }
}

function compareWeaponQuality (a, b) {
  // A complete damage specification takes precedence over a durability proxy.
  // Mixed/unknown damage metadata is never silently equated to zero damage.
  if (a.declared_damage !== null && b.declared_damage !== null &&
      a.declared_damage !== b.declared_damage) {
    return b.declared_damage - a.declared_damage
  }
  // A sword is the generic melee choice only among otherwise undocumented
  // weapon types. This is a category from the versioned item registry.
  if (a.is_sword !== b.is_sword) return Number(b.is_sword) - Number(a.is_sword)
  const aWear = a.durability_remaining ?? -1
  const bWear = b.durability_remaining ?? -1
  if (aWear !== bWear) return bWear - aWear
  if (a.currently_held !== b.currently_held) return Number(b.currently_held) - Number(a.currently_held)
  return String(a.item.name).localeCompare(String(b.item.name))
}

async function equipDeclaredMeleeWeapon () {
  const activeBot = runtime.getBot()
  const items = activeBot.inventory.items()
  const available = [...items]
  if (activeBot.heldItem && !available.some(row =>
    row === activeBot.heldItem ||
    (row && activeBot.heldItem && row.slot === activeBot.heldItem.slot &&
     row.name === activeBot.heldItem.name)
  )) available.push(activeBot.heldItem)
  const scored = available.filter(item => isDeclaredWeapon(activeBot, item))
    .map(item => observedWeaponQuality(activeBot, item))
    .filter(row => row.durability_remaining === null || row.durability_remaining > 0)
    .sort(compareWeaponQuality)
  const selected = scored[0] || null
  if (!selected) return {
    selected_weapon: null, selection_basis: 'no_usable_declared_melee_weapon',
    registry_damage_available: false, equipped: false
  }
  const alreadyHeld = Boolean(selected.currently_held)
  if (!alreadyHeld) await activeBot.equip(selected.item, 'hand')
  return {
    selected_weapon: selected.item.name,
    selection_basis: scored.length > 1
      ? 'versioned_registry_damage_then_weapon_category_and_remaining_durability'
      : 'only_usable_declared_melee_weapon',
    registry_damage_available: selected.declared_damage !== null,
    selected_declared_damage: selected.declared_damage,
    selected_durability_remaining: selected.durability_remaining,
    equipped: !alreadyHeld
  }
}

async function attackTarget (tool, action, target, maxHits) {
  const activeBot = runtime.getBot()
  const pvpAvailable = Boolean(
    activeBot.pvp &&
    typeof activeBot.pvp.attack === 'function' &&
    typeof activeBot.pvp.stop === 'function'
  )
  if (!pvpAvailable) {
    return runtime.rejected(tool, action, 'MINEFLAYER_PVP_UNAVAILABLE')
  }
  await runtime.ensureMovements()
  const targetId = target.id
  const weaponSelection = await equipDeclaredMeleeWeapon()
  const weapon = weaponSelection.selected_weapon
  let attackSignals = 0
  let attackInvoked = false
  let hurtSignals = 0
  let ownHurtSignals = 0
  let pvpStopped = false
  let completionResolve
  let completionReject
  let unregisterCancel = null
  const completion = new Promise((resolve, reject) => {
    completionResolve = resolve
    completionReject = reject
  })
  const stopPvp = () => {
    if (
      !pvpStopped &&
      pvpAvailable &&
      typeof activeBot.pvp.stop === 'function'
    ) activeBot.pvp.stop()
    pvpStopped = true
  }
  const finishIfComplete = () => {
    const live = activeBot.entities[targetId]
    if (!live || live.isValid === false || !live.position) {
      completionResolve('target-gone')
      return
    }
    if (attackSignals >= maxHits) {
      stopPvp()
      completionResolve('attack-limit')
    }
  }
  const onAttackedTarget = attacked => {
    if (attacked && attacked.id != null && attacked.id !== targetId) return
    attackSignals++
    finishIfComplete()
  }
  const onEntityHurt = (entity, source) => {
    if (!entity || entity.id !== targetId) return
    hurtSignals++
    if (
      source &&
      activeBot.entity &&
      source.id === activeBot.entity.id
    ) ownHurtSignals++
    finishIfComplete()
  }
  const onEntityGone = entity => {
    if (entity && entity.id === targetId) completionResolve('target-gone')
  }
  activeBot.on('attackedTarget', onAttackedTarget)
  activeBot.on('entityHurt', onEntityHurt)
  activeBot.on('entityGone', onEntityGone)
  unregisterCancel = runtime.onActionCancel(
    'mineflayer:pvp-observer',
    () => {
      const error = new Error('ACTION_CANCELLED')
      error.code = 'ACTION_CANCELLED'
      completionReject(error)
    }
  )
  try {
    // Native attack invocation is a possible physical side effect, even
    // when the server's damage/attack event is delayed or never delivered.
    // Keep its certainty distinct from an attributed hit.
    attackInvoked = true
    activeBot.pvp.attack(target)
    finishIfComplete()
    await completion
  } finally {
    stopPvp()
    if (unregisterCancel) unregisterCancel()
    activeBot.removeListener('attackedTarget', onAttackedTarget)
    activeBot.removeListener('entityHurt', onEntityHurt)
    activeBot.removeListener('entityGone', onEntityGone)
  }
  const liveAfter = activeBot.entities[targetId]
  const defeated = !liveAfter || liveAfter.isValid === false
  const details = {
    target_id: targetId,
    target_name: target.username || target.displayName || target.name || null,
    weapon,
    weapon_selection: weaponSelection,
    combat_mode: 'mineflayer-pvp',
    hits: attackSignals,
    native_attack_invoked: attackInvoked,
    attack_signals: attackSignals,
    hurt_signals: hurtSignals,
    own_hurt_signals: ownHurtSignals,
    target_valid_after: !defeated
  }
  if (defeated && ownHurtSignals > 0) return runtime.applied(tool, action, 'TARGET_DEFEATED', details)
  if (ownHurtSignals > 0) return runtime.applied(tool, action, 'TARGET_HIT_CONFIRMED', details)
  if (attackSignals > 0) return runtime.partial(tool, action, 'ATTACK_PERFORMED_HIT_UNCONFIRMED', details)
  if (hurtSignals > 0) return runtime.partial(
    tool, action, 'TARGET_HURT_SOURCE_UNATTRIBUTED', details, 'unknown'
  )
  if (attackInvoked) return runtime.partial(
    tool, action, 'MELEE_EFFECT_UNATTRIBUTED', details, 'unknown'
  )
  return runtime.rejected(tool, action, 'ATTACK_NOT_APPLIED', details, 'not_applied')
}
function entityTypeRejection (tool, action, activeBot) {
  const registry = activeBot.registry && activeBot.registry.entitiesByName
  if (!registry || Object.keys(registry).length === 0 || registry[action.entity]) return null
  return runtime.rejected(tool, action, 'UNKNOWN_ENTITY_TYPE', {
    semantic_domain: 'minecraft.entity_type',
    canonical_candidates: suggestRegistryKind(activeBot.registry, action.entity, 'entity'),
    resolution: { status: 'candidates_available' }
  })
}

async function attackNearest (msg) {
  const action = {
    entity: String(msg.entity || msg.query || ''),
    max_distance: Number(msg.max_distance || 32),
    max_hits: Number(msg.max_hits || 8)
  }
  const activeBot = runtime.getBot()
  const invalid = entityTypeRejection('attack_nearest', action, activeBot)
  if (invalid) return invalid
  const target = runtime.findEntity(action.entity, action.max_distance)
  if (!target) {
    return runtime.rejected('attack_nearest', action, 'TARGET_NOT_FOUND', {
      semantic_domain: 'minecraft.entity_type',
      target_observed: false,
      observed_entity_in_range: false
    }, 'not_applied')
  }
  return attackTarget('attack_nearest', action, target, action.max_hits)
}

async function attackEntity (msg) {
  const activeBot = runtime.getBot()
  const action = {
    entity_id: Number(msg.entity_id),
    max_distance: Number(msg.max_distance || 32),
    max_hits: Number(msg.max_hits || 12)
  }
  const target = activeBot.entities[action.entity_id]
  if (!target || target.isValid === false || !target.position) {
    return runtime.rejected('attack_entity', action, 'TARGET_NOT_FOUND')
  }
  const distance = target.position.distanceTo(activeBot.entity.position)
  if (distance > action.max_distance) return runtime.rejected('attack_entity', action, 'TARGET_OUT_OF_RANGE', { distance })
  return attackTarget('attack_entity', action, target, action.max_hits)
}

async function attackPlayer (msg) {
  const action = {
    player: String(msg.player || ''),
    max_distance: Number(msg.max_distance || 64),
    max_hits: Number(msg.max_hits || 20)
  }
  const target = runtime.findEntity(action.player, action.max_distance, entity => (
    entity.type === 'player' && entity.username === action.player
  ))
  if (!target) return runtime.rejected('attack_player', action, 'PLAYER_NOT_FOUND')
  return attackTarget('attack_player', action, target, action.max_hits)
}

function findRangedWeapon () {
  const crossbow = runtime.findInventoryItem('crossbow')
  if (crossbow) return crossbow
  return runtime.findInventoryItem('bow')
}

async function fireProjectile (msg) {
  const activeBot = runtime.getBot()
  const action = {
    ...(msg.weapon == null ? {} : { weapon: String(msg.weapon) }),
    shots: Number(msg.shots || 1)
  }
  const weapon = action.weapon
    ? runtime.findInventoryItem(action.weapon)
    : findRangedWeapon()
  if (!weapon || !['bow', 'crossbow'].includes(String(weapon.name))) {
    return runtime.rejected('fire_projectile', action, 'RANGED_WEAPON_NOT_AVAILABLE', {
      requested_weapon: action.weapon || null,
      available_ranged_weapon: false
    }, 'not_applied')
  }
  const arrows = runtime.inventoryCount('arrow')
  const rockets = runtime.inventoryCount('firework_rocket')
  const ammoName = arrows > 0
    ? 'arrow'
    : weapon.name === 'crossbow' && rockets > 0
      ? 'firework_rocket'
      : 'arrow'
  const ammoBefore = runtime.inventoryCount(ammoName)
  if (ammoBefore < action.shots) {
    return runtime.rejected('fire_projectile', action, 'AMMUNITION_NOT_AVAILABLE', {
      weapon: weapon.name,
      ammo: ammoName,
      available: ammoBefore,
      requested_shots: action.shots
    }, 'not_applied')
  }
  const requiredChargeTicks = ballistics.chargeTicks(weapon)
  if (!Number.isInteger(requiredChargeTicks) || requiredChargeTicks < 1) {
    return runtime.rejected(
      'fire_projectile', action, 'WEAPON_CHARGE_SEMANTICS_UNAVAILABLE',
      { weapon: weapon.name }, 'not_applied'
    )
  }

  await activeBot.equip(weapon, 'hand')
  let shotsReleased = 0
  const shotEvidence = []
  try {
    for (let index = 0; index < action.shots; index += 1) {
      activeBot.activateItem()
      await runtime.waitForPhysicsTicks(requiredChargeTicks)
      if (weapon.name === 'crossbow') {
        activeBot.deactivateItem()
        await runtime.waitForPhysicsTicks(1)
        activeBot.activateItem()
        activeBot.deactivateItem()
      } else {
        activeBot.deactivateItem()
      }
      shotsReleased += 1
      await runtime.waitForPhysicsTicks(1)
      shotEvidence.push({
        released: true,
        weapon: weapon.name,
        ammo: ammoName,
        charge_ticks: requiredChargeTicks,
        aim_mode: 'current_facing'
      })
    }
  } finally {
    activeBot.deactivateItem()
  }
  const ammoAfter = runtime.inventoryCount(ammoName)
  const ammoConsumed = Math.max(0, ammoBefore - ammoAfter)
  const details = {
    weapon: weapon.name,
    requested_weapon: action.weapon || null,
    ammo: ammoName,
    ammo_before: ammoBefore,
    ammo_after: ammoAfter,
    ammo_consumed: ammoConsumed,
    shots_released: shotsReleased,
    charge_ticks: requiredChargeTicks,
    aim_mode: 'current_facing',
    shots: shotEvidence,
    no_target_selected: true,
    hit_or_damage_claimed: false
  }
  if (shotsReleased > 0 && ammoConsumed > 0) {
    return runtime.applied(
      'fire_projectile', action, 'PROJECTILES_RELEASED', details
    )
  }
  if (shotsReleased > 0) {
    return runtime.partial(
      'fire_projectile', action, 'RANGED_EFFECT_UNCONFIRMED', details, 'unknown'
    )
  }
  return runtime.rejected(
    'fire_projectile', action, 'SHOT_NOT_OBSERVED', details, 'not_applied'
  )
}

async function rangedAttack (msg) {
  const activeBot = runtime.getBot()
  const action = {
    entity: String(msg.entity || msg.player || ''),
    max_distance: Number(msg.max_distance || 48),
    shots: Number(msg.shots || 1)
  }
  const invalid = entityTypeRejection('ranged_attack', action, activeBot)
  if (invalid) return invalid
  const target = runtime.findEntity(action.entity, action.max_distance)
  if (!target) {
    return runtime.rejected('ranged_attack', action, 'TARGET_NOT_FOUND', {
      semantic_domain: 'minecraft.entity_type',
      target_observed: false,
      observed_entity_in_range: false
    }, 'not_applied')
  }

  const weapon = findRangedWeapon()
  if (!weapon) {
    return runtime.rejected(
      'ranged_attack',
      action,
      'RANGED_WEAPON_NOT_AVAILABLE'
    )
  }

  const arrows = runtime.inventoryCount('arrow')
  const rockets = runtime.inventoryCount('firework_rocket')
  const ammoName = arrows > 0
    ? 'arrow'
    : weapon.name === 'crossbow' && rockets > 0
      ? 'firework_rocket'
      : 'arrow'
  const ammoBefore = runtime.inventoryCount(ammoName)
  if (ammoBefore < action.shots) {
    return runtime.rejected(
      'ranged_attack',
      action,
      'AMMUNITION_NOT_AVAILABLE',
      { ammo: ammoName, available: ammoBefore }
    )
  }

  const requiredChargeTicks = ballistics.chargeTicks(weapon)
  if (!Number.isInteger(requiredChargeTicks) || requiredChargeTicks < 1) {
    return runtime.rejected(
      'ranged_attack',
      action,
      'WEAPON_CHARGE_SEMANTICS_UNAVAILABLE'
    )
  }

  await activeBot.equip(weapon, 'hand')
  let shotsReleased = 0
  let hurtSignals = 0
  let ownHurtSignals = 0
  const shotEvidence = []
  const onEntityHurt = (entity, source) => {
    if (!entity || entity.id !== target.id) return
    hurtSignals += 1
    // A nearby mob or another player can injure the same target during the
    // shot. Temporal correlation cannot establish who caused the damage.
    if (source && activeBot.entity && source.id === activeBot.entity.id) {
      ownHurtSignals += 1
    }
  }
  activeBot.on('entityHurt', onEntityHurt)
  try {
    for (let index = 0; index < action.shots; index += 1) {
      let live = activeBot.entities[target.id]
      if (!live || live.isValid === false || !live.position) break

      activeBot.activateItem()
      await runtime.waitForPhysicsTicks(requiredChargeTicks)

      // Crossbows load on release, then fire the loaded projectile with the
      // next use action. Bows fire on this release.
      if (weapon.name === 'crossbow') {
        activeBot.deactivateItem()
        await runtime.waitForPhysicsTicks(1)
      }

      live = activeBot.entities[target.id]
      if (!live || live.isValid === false || !live.position) break

      let aim = null
      if (ammoName === 'arrow') {
        aim = ballistics.solveArrowShot(activeBot, live, weapon)
        if (!aim || aim.hit === false) {
          if (weapon.name === 'bow') activeBot.deactivateItem()
          shotEvidence.push({
            released: false,
            reason: 'NO_CLEAR_BALLISTIC_SOLUTION',
            ballistic: aim
          })
          break
        }
        await activeBot.look(aim.yaw, aim.pitch, true)
      } else {
        // Firework rockets do not follow arrow gravity semantics. Preserve
        // capability without pretending arrow ballistics apply.
        await activeBot.lookAt(
          live.position.offset(
            0,
            Math.max(0, Number(live.height || 0)) / 2,
            0
          ),
          true
        )
      }

      if (weapon.name === 'crossbow') {
        activeBot.activateItem()
        activeBot.deactivateItem()
      } else {
        activeBot.deactivateItem()
      }
      shotsReleased += 1
      await runtime.waitForPhysicsTicks(1)
      shotEvidence.push({
        released: true,
        ammo: ammoName,
        charge_ticks: requiredChargeTicks,
        aim_mode: ammoName === 'arrow'
          ? 'discrete_drag_ballistics'
          : 'direct_firework',
        ballistic: aim
      })
    }
  } finally {
    activeBot.deactivateItem()
    activeBot.removeListener('entityHurt', onEntityHurt)
  }

  const ammoAfter = runtime.inventoryCount(ammoName)
  const liveAfter = activeBot.entities[target.id]
  const defeated = !liveAfter || liveAfter.isValid === false
  const ammoConsumed = Math.max(0, ammoBefore - ammoAfter)
  const attributedDamage = (
    ownHurtSignals > 0 &&
    shotsReleased > 0 &&
    ammoConsumed > 0
  )
  const details = {
    target_id: target.id,
    weapon: weapon.name,
    ammo: ammoName,
    ammo_before: ammoBefore,
    ammo_after: ammoAfter,
    ammo_consumed: ammoConsumed,
    shots_released: shotsReleased,
    charge_ticks: requiredChargeTicks,
    hurt_signals: hurtSignals,
    own_hurt_signals: ownHurtSignals,
    damage_attribution: ownHurtSignals > 0 ? 'own_player_observed'
      : hurtSignals > 0 ? 'other_or_unknown_source' : 'not_observed',
    target_valid_after: !defeated,
    shots: shotEvidence
  }

  if (defeated && attributedDamage) {
    return runtime.applied(
      'ranged_attack', action, 'TARGET_DEFEATED_AFTER_VERIFIED_SHOT', details
    )
  }
  if (attributedDamage) {
    return runtime.applied(
      'ranged_attack', action, 'TARGET_HIT_ATTRIBUTED_TO_OWN_SHOT', details
    )
  }
  if (defeated && shotsReleased > 0 && ammoConsumed > 0) {
    return runtime.partial(
      'ranged_attack', action, 'TARGET_DISAPPEARED_AFTER_SHOT_UNATTRIBUTED',
      details, 'applied'
    )
  }
  if (shotsReleased > 0 && ammoConsumed > 0) {
    return runtime.partial(
      'ranged_attack',
      action,
      'SHOTS_RELEASED_HIT_UNCONFIRMED',
      details,
      'applied'
    )
  }
  if (shotsReleased > 0) {
    // A firing command with no attributable ammo delta might still have
    // emitted a projectile (e.g. a server-specific infinity effect). It is
    // unsafe to retry as though the shot definitely had no physical effect.
    return runtime.partial(
      'ranged_attack', action, 'RANGED_EFFECT_UNCONFIRMED', details, 'unknown'
    )
  }
  if (
    shotEvidence.some(row => (
      row && row.reason === 'NO_CLEAR_BALLISTIC_SOLUTION'
    ))
  ) {
    return runtime.rejected(
      'ranged_attack',
      action,
      'NO_CLEAR_BALLISTIC_SOLUTION',
      details,
      'not_applied'
    )
  }
  return runtime.rejected(
    'ranged_attack',
    action,
    'SHOT_NOT_OBSERVED',
    details,
    'not_applied'
  )
}

function nearbyHostiles (radius) {
  const activeBot = runtime.getBot()
  return Object.values(activeBot.entities || {})
    .filter(entity => entity && entity !== activeBot.entity && entity.position && entity.isValid !== false)
    .filter(entity => isHostileEntity(activeBot, entity))
    .map(entity => ({ entity, distance: entity.position.distanceTo(activeBot.entity.position) }))
    .filter(candidate => candidate.distance <= radius)
    .sort((left, right) => left.distance - right.distance)
    .map(candidate => candidate.entity)
}

async function defendSelf (msg) {
  const action = {
    radius: Number(msg.radius || 12),
    max_targets: Number(msg.max_targets || 4),
    max_hits: Number(msg.max_hits || 12)
  }
  const initial = nearbyHostiles(action.radius)
  if (initial.length === 0) {
    return runtime.applied('defend_self', action, 'NO_THREATS', {
      targets_observed: 0, no_hostiles_observed_in_radius: true
    })
  }

  // A static target snapshot goes stale as mobs move, despawn, or enter the
  // area. Re-observe after each bounded, physically mediated PvP engagement,
  // but never retry the same unresolved target without a new Agent decision.
  const handled = new Set()
  const outcomes = []
  let anyObservedAttack = false
  let anyUncertainEffect = false
  for (let index = 0; index < action.max_targets; index += 1) {
    const target = nearbyHostiles(action.radius).find(row => !handled.has(row.id))
    if (!target) break
    handled.add(target.id)
    const report = await attackTarget('defend_self', action, target, action.max_hits)
    outcomes.push({
      target_id: target.id,
      ...report.outcome,
    })
    if (report.outcome.attack_signals > 0 || report.outcome.own_hurt_signals > 0) {
      anyObservedAttack = true
    }
    if (report.effect_disposition === 'unknown') {
      anyUncertainEffect = true
      // Do not initiate more irreversible attacks with an unresolved
      // physical result under the same semantic action request.
      break
    }
    // Missing PvP provider, unavailable movement authority or another
    // deterministic no-effect rejection does not grant an applied effect.
    if (report.outcome.status === 'rejected' && !anyObservedAttack) {
      return runtime.rejected('defend_self', action, report.outcome.code, {
        targets_observed: initial.length,
        target_outcomes: outcomes,
        remaining: nearbyHostiles(action.radius).length
      }, 'not_applied')
    }
  }
  const remaining = nearbyHostiles(action.radius).length
  const details = {
    targets_observed: initial.length,
    targets_engaged: handled.size,
    remaining,
    target_outcomes: outcomes
  }
  if (anyUncertainEffect) {
    return runtime.partial('defend_self', action,
      'DEFENSE_EFFECT_UNATTRIBUTED', details, 'unknown')
  }
  if (remaining === 0 && anyObservedAttack) {
    return runtime.applied('defend_self', action, 'AREA_SECURED', details)
  }
  if (anyObservedAttack) return runtime.partial('defend_self', action, 'THREATS_REMAIN', details)
  // The world might have changed independently, but no locally attributed
  // combat happened. Never turn that observation into an applied action.
  return runtime.rejected('defend_self', action, 'DEFENSE_NOT_APPLIED', details, 'not_applied')
}

module.exports = {
  attack_entity: attackEntity,
  attack_nearest: attackNearest,
  attack_player: attackPlayer,
  defend_self: defendSelf,
  fire_projectile: fireProjectile,
  ranged_attack: rangedAttack
}
