'use strict'

const runtime = require('./runtime')

const HOSTILE_NAMES = new Set([
  'blaze', 'bogged', 'breeze', 'cave_spider', 'creeper', 'drowned', 'elder_guardian',
  'enderman', 'endermite', 'evoker', 'ghast', 'guardian', 'hoglin', 'husk', 'magma_cube',
  'phantom', 'piglin_brute', 'pillager', 'ravager', 'shulker', 'silverfish', 'skeleton',
  'slime', 'spider', 'stray', 'vex', 'vindicator', 'warden', 'witch', 'wither',
  'wither_skeleton', 'zoglin', 'zombie', 'zombie_villager', 'zombified_piglin'
])

function weaponScore (item) {
  const name = String(item && item.name ? item.name : '')
  const material = name.startsWith('netherite_') ? 60
    : name.startsWith('diamond_') ? 50
      : name.startsWith('iron_') ? 40
        : name.startsWith('stone_') ? 30
          : name.startsWith('golden_') ? 20
            : name.startsWith('wooden_') ? 10
              : 0
  const kind = name.endsWith('_axe') ? 8 : name.endsWith('_sword') ? 7 : name === 'trident' ? 6 : 0
  return material + kind
}

async function equipStrongestMelee () {
  const activeBot = runtime.getBot()
  const weapon = activeBot.inventory.items()
    .filter(item => weaponScore(item) > 0)
    .sort((left, right) => weaponScore(right) - weaponScore(left))[0]
  if (weapon) await activeBot.equip(weapon, 'hand')
  return weapon ? weapon.name : activeBot.heldItem ? activeBot.heldItem.name : null
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
  const weapon = await equipStrongestMelee()
  let attackSignals = 0
  let hurtSignals = 0
  let ownHurtSignals = 0
  let lastAttackSignalAt = 0
  let pvpStopped = false
  const stopPvp = () => {
    if (!pvpStopped && pvpAvailable && typeof activeBot.pvp.stop === 'function') activeBot.pvp.stop()
    pvpStopped = true
  }
  const onAttackedTarget = () => { attackSignals++; lastAttackSignalAt = Date.now() }
  const onEntityHurt = (entity, source) => {
    if (!entity || entity.id !== targetId) return
    hurtSignals++
    if (source && activeBot.entity && source.id === activeBot.entity.id) ownHurtSignals++
  }
  activeBot.on('attackedTarget', onAttackedTarget)
  activeBot.on('entityHurt', onEntityHurt)
  try {
    activeBot.pvp.attack(target)
    const attackDeadline = Date.now() + Math.max(1800, Number(maxHits) * 1500)
    let confirmationDeadline = null
    while (Date.now() < attackDeadline) {
      const live = activeBot.entities[targetId]
      if (!live || live.isValid === false || !live.position || ownHurtSignals > 0) break
      if (attackSignals >= maxHits) {
        stopPvp()
        if (confirmationDeadline == null) confirmationDeadline = Math.max(Date.now(), lastAttackSignalAt) + 750
        if (Date.now() >= confirmationDeadline) break
      }
      await runtime.sleep(50)
    }
  } finally {
    stopPvp()
    activeBot.removeListener('attackedTarget', onAttackedTarget)
    activeBot.removeListener('entityHurt', onEntityHurt)
  }
  const liveAfter = activeBot.entities[targetId]
  const defeated = !liveAfter || liveAfter.isValid === false
  const details = {
    target_id: targetId,
    target_name: target.username || target.displayName || target.name || null,
    weapon,
    combat_mode: 'mineflayer-pvp',
    hits: attackSignals,
    attack_signals: attackSignals,
    hurt_signals: hurtSignals,
    own_hurt_signals: ownHurtSignals,
    target_valid_after: !defeated
  }
  if (defeated && ownHurtSignals > 0) return runtime.applied(tool, action, 'TARGET_DEFEATED', details)
  if (ownHurtSignals > 0) return runtime.applied(tool, action, 'TARGET_HIT_CONFIRMED', details)
  if (attackSignals > 0) return runtime.partial(tool, action, 'ATTACK_PERFORMED_HIT_UNCONFIRMED', details)
  if (hurtSignals > 0) return runtime.partial(tool, action, 'TARGET_HURT_SOURCE_UNATTRIBUTED', details)
  return runtime.rejected(tool, action, 'ATTACK_NOT_APPLIED', details)
}
async function attackNearest (msg) {
  const action = {
    entity: String(msg.entity || msg.query || ''),
    max_distance: Number(msg.max_distance || 32),
    max_hits: Number(msg.max_hits || 8)
  }
  const target = runtime.findEntity(action.entity, action.max_distance)
  if (!target) return runtime.rejected('attack_nearest', action, 'TARGET_NOT_FOUND')
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

async function rangedAttack (msg) {
  const activeBot = runtime.getBot()
  const action = {
    entity: String(msg.entity || msg.player || ''),
    max_distance: Number(msg.max_distance || 48),
    shots: Number(msg.shots || 1),
    charge_ms: Number(msg.charge_ms || 1100)
  }
  const target = runtime.findEntity(action.entity, action.max_distance)
  if (!target) return runtime.rejected('ranged_attack', action, 'TARGET_NOT_FOUND')
  const weapon = findRangedWeapon()
  if (!weapon) return runtime.rejected('ranged_attack', action, 'RANGED_WEAPON_NOT_AVAILABLE')
  const ammoName = weapon.name === 'crossbow' && runtime.inventoryCount('firework_rocket') > 0
    ? 'firework_rocket'
    : 'arrow'
  const ammoBefore = runtime.inventoryCount(ammoName)
  if (ammoBefore < action.shots) return runtime.rejected('ranged_attack', action, 'AMMUNITION_NOT_AVAILABLE', { ammo: ammoName, available: ammoBefore })
  await activeBot.equip(weapon, 'hand')
  let shotsReleased = 0
  let hurtSignals = 0
  const onEntityHurt = entity => {
    if (entity && entity.id === target.id) hurtSignals++
  }
  activeBot.on('entityHurt', onEntityHurt)
  try {
    for (let index = 0; index < action.shots; index++) {
      const live = activeBot.entities[target.id]
      if (!live || live.isValid === false || !live.position) break
      await activeBot.lookAt(live.position.offset(0, Math.max(0.5, Number(live.height || 1.6) * 0.65), 0), true)
      activeBot.activateItem()
      await runtime.sleep(action.charge_ms)
      activeBot.deactivateItem()
      shotsReleased++
      await runtime.sleep(300)
    }
  } finally {
    activeBot.deactivateItem()
    activeBot.removeListener('entityHurt', onEntityHurt)
  }
  const ammoAfter = runtime.inventoryCount(ammoName)
  const liveAfter = activeBot.entities[target.id]
  const defeated = !liveAfter || liveAfter.isValid === false
  const details = {
    target_id: target.id,
    weapon: weapon.name,
    ammo: ammoName,
    ammo_before: ammoBefore,
    ammo_after: ammoAfter,
    shots_released: shotsReleased,
    hurt_signals: hurtSignals,
    target_valid_after: !defeated
  }
  if (defeated) return runtime.applied('ranged_attack', action, 'TARGET_DEFEATED', details)
  if (hurtSignals > 0) return runtime.applied('ranged_attack', action, 'TARGET_HIT_CONFIRMED', details)
  if (shotsReleased > 0 && ammoAfter < ammoBefore) return runtime.partial('ranged_attack', action, 'SHOTS_RELEASED_HIT_UNCONFIRMED', details)
  return runtime.rejected('ranged_attack', action, 'SHOT_NOT_OBSERVED', details)
}

function nearbyHostiles (radius) {
  const activeBot = runtime.getBot()
  return Object.values(activeBot.entities || {})
    .filter(entity => entity && entity !== activeBot.entity && entity.position && entity.isValid !== false)
    .filter(entity => HOSTILE_NAMES.has(String(entity.name || entity.displayName || '').toLowerCase()))
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
  const targets = nearbyHostiles(action.radius).slice(0, action.max_targets)
  if (targets.length === 0) return runtime.applied('defend_self', action, 'NO_THREATS', { targets_observed: 0 })
  const outcomes = []
  for (const target of targets) {
    const outcome = await attackTarget('defend_self', action, target, action.max_hits)
    outcomes.push(outcome.outcome)
  }
  const remaining = nearbyHostiles(action.radius).length
  const details = { targets_observed: targets.length, remaining, target_outcomes: outcomes }
  if (remaining === 0) return runtime.applied('defend_self', action, 'AREA_SECURED', details)
  return runtime.partial('defend_self', action, 'THREATS_REMAIN', details)
}

module.exports = {
  attack_entity: attackEntity,
  attack_nearest: attackNearest,
  attack_player: attackPlayer,
  defend_self: defendSelf,
  ranged_attack: rangedAttack
}
