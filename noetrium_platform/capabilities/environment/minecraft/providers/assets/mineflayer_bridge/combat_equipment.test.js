'use strict'

const assert = require('node:assert/strict')
const test = require('node:test')
const { EventEmitter } = require('node:events')
const { Vec3 } = require('vec3')
const runtime = require('./runtime')
const combat = require('./combat')

function fixture (swords, heldIndex = 0) {
  const bot = new EventEmitter()
  bot.entity = { id: 1, position: new Vec3(0, 64, 0) }
  const target = { id: 2, name: 'zombie', type: 'mob',
    isValid: true, position: new Vec3(2, 64, 0) }
  bot.entities = { 1: bot.entity, 2: target }
  const inventory = swords.map((row, idx) => ({
    name: row.name, type: idx+5, slot: idx, count:1,
    durabilityUsed: row.used || 0
  }))
  bot.inventory = { items: () => inventory }
  bot.heldItem = inventory[heldIndex]
  bot.registry = { entitiesByName: { zombie: { type: 'hostile' } },
    itemsByName: Object.fromEntries(swords.map(row => [
      row.name, { enchantCategories: ['weapon','sword'],
        maxDurability: row.max, ...(row.damage ? {attackDamage:row.damage} : {}) }
    ])) }
  let equips=0, attacks=0
  bot.equip = async item => { equips++;bot.heldItem=item }
  bot.pvp = {
    attack: entity => {
      attacks++
      bot.emit('entityHurt',entity,bot.entity)
      bot.emit('attackedTarget',entity)
    },
    stop: () => {}
  }
  return { bot, target, equipCount: () => equips, attackCount: () => attacks }
}

async function runMelee (fixtureValue) {
  const prev=runtime.ensureMovements
  runtime.ensureMovements=async () => {}
  runtime.bindBot(fixtureValue.bot)
  try {
    return await combat.attack_nearest({entity:'zombie',max_distance:8,max_hits:1})
  } finally {
    runtime.ensureMovements=prev
  }
}

test('melee equips the more durable observed registry-declared sword instead of alphabetic first', async () => {
  const f=fixture([
    {name:'wooden_sword',max:59},
    {name:'netherite_sword',max:2031}
  ])
  const result=await runMelee(f)
  assert.equal(result.outcome.code,'TARGET_HIT_CONFIRMED')
  assert.equal(result.outcome.weapon,'netherite_sword')
  assert.equal(f.equipCount(),1)
  assert.equal(f.attackCount(),1)
  assert.equal(result.outcome.weapon_selection.selected_durability_remaining,2031)
  assert.equal(result.outcome.weapon_selection.registry_damage_available,false)
})

test('melee preserves the currently held weapon when it outranks other usable tools', async () => {
  const f=fixture([
    {name:'diamond_sword',max:1561},
    {name:'wooden_sword',max:59}
  ])
  const result=await runMelee(f)
  assert.equal(result.outcome.weapon,'diamond_sword')
  assert.equal(f.equipCount(),0)
  assert.equal(result.outcome.weapon_selection.equipped,false)
})

test('melee uses declared damage where both weapons expose versioned attack damage', async () => {
  const f=fixture([
    {name:'low_damage_sword',max:3000,damage:3},
    {name:'high_damage_sword',max:500,damage:8}
  ])
  const result=await runMelee(f)
  assert.equal(result.outcome.weapon,'high_damage_sword')
  assert.equal(result.outcome.weapon_selection.selected_declared_damage,8)
  assert.equal(result.outcome.weapon_selection.registry_damage_available,true)
})

test('melee refuses to equip exhausted broken sword when a functional one exists', async () => {
  const f=fixture([
    {name:'spent_sword',max:100,used:100},
    {name:'wooden_sword',max:59}
  ])
  const result=await runMelee(f)
  assert.equal(result.outcome.weapon,'wooden_sword')
  assert.equal(result.outcome.weapon_selection.selected_durability_remaining,59)
})

test('missing target never triggers equipment changes or melee effects', async () => {
  const f=fixture([{name:'diamond_sword',max:1561}])
  delete f.bot.entities[2]
  const result=await runMelee(f)
  assert.equal(result.outcome.code,'TARGET_NOT_FOUND')
  assert.equal(f.equipCount(),0)
  assert.equal(f.attackCount(),0)
})

test('defend_self re-observes live hostile entities across bounded engagements', async () => {
  const f=fixture([{name:'diamond_sword',max:1561}])
  let engagement=0
  f.bot.pvp.attack=target => {
    engagement++
    delete f.bot.entities[target.id]
    f.bot.emit('entityHurt',target,f.bot.entity)
    f.bot.emit('attackedTarget',target)
    if (engagement===1) {
      f.bot.entities[3]={
        id:3, name:'zombie', type:'mob', isValid:true,
        position:new Vec3(3,64,0)
      }
    }
  }
  const prev=runtime.ensureMovements
  runtime.ensureMovements=async () => {}
  runtime.bindBot(f.bot)
  try {
    const result=await combat.defend_self({radius:8,max_targets:2,max_hits:1})
    assert.equal(result.outcome.code,'AREA_SECURED')
    assert.equal(result.outcome.targets_engaged,2)
    assert.equal(result.outcome.remaining,0)
    assert.deepEqual(result.outcome.target_outcomes.map(row=>row.target_id),[2,3])
  } finally {
    runtime.ensureMovements=prev
  }
})

test('defend_self missing PvP provider never claims applied defensive effects', async () => {
  const f=fixture([{name:'diamond_sword',max:1561}])
  delete f.bot.pvp
  runtime.bindBot(f.bot)
  const result=await combat.defend_self({radius:8,max_targets:2,max_hits:1})
  assert.equal(result.outcome.status,'rejected')
  assert.equal(result.outcome.code,'MINEFLAYER_PVP_UNAVAILABLE')
  assert.equal(result.effect_disposition,'not_applied')
  assert.equal(f.equipCount(),0)
})

test('defend_self does not repeat the same unresolved hostile target indefinitely', async () => {
  const f=fixture([{name:'diamond_sword',max:1561}])
  let strikes=0
  f.bot.pvp.attack=target=>{
    strikes++
    f.bot.emit('attackedTarget',target)
  }
  const prev=runtime.ensureMovements
  runtime.ensureMovements=async()=>{}
  runtime.bindBot(f.bot)
  try {
    const result=await combat.defend_self({radius:8,max_targets:12,max_hits:1})
    assert.equal(strikes,1)
    assert.equal(result.outcome.status,'partial')
    assert.equal(result.outcome.code,'THREATS_REMAIN')
    assert.equal(result.outcome.targets_engaged,1)
  } finally {
    runtime.ensureMovements=prev
  }
})

function rangedFixture (damageSource, consumeAmmo = true) {
  const bow={ name:'bow', type:8, count:1, slot:0 }
  const arrow={ name:'arrow', type:9, count:3, slot:1 }
  const f=fixture([])
  f.bot.inventory={items:()=>[bow,arrow]}
  f.bot.heldItem=bow
  f.bot.equip=async item=>{f.bot.heldItem=item}
  f.bot.look=async()=>{}
  f.bot.activateItem=()=>{}
  let released=false
  f.bot.deactivateItem=()=>{
    if (released) return
    released=true
    if (consumeAmmo && arrow.count>0) arrow.count--
    if (damageSource) {
      const target=f.bot.entities[2]
      f.bot.emit('entityHurt',target,
        damageSource==='own' ? f.bot.entity :
        {id:99,name:'other_player'})
    }
  }
  return f
}

async function runRanged (f) {
  const ballistics=require('./ballistics')
  const old={
    ticks:runtime.waitForPhysicsTicks,
    charge:ballistics.chargeTicks,
    solve:ballistics.solveArrowShot
  }
  runtime.waitForPhysicsTicks=async()=>{}
  ballistics.chargeTicks=()=>1
  ballistics.solveArrowShot=()=>({hit:true,yaw:0,pitch:0})
  runtime.bindBot(f.bot)
  try {
    return await combat.ranged_attack({
      entity:'zombie',max_distance:8,shots:1
    })
  } finally {
    runtime.waitForPhysicsTicks=old.ticks
    ballistics.chargeTicks=old.charge
    ballistics.solveArrowShot=old.solve
  }
}

test('ranged shots do not attribute third-party harm to this agent', async () => {
  const f=rangedFixture('other')
  const r=await runRanged(f)
  assert.equal(r.outcome.code,'SHOTS_RELEASED_HIT_UNCONFIRMED')
  assert.equal(r.verified,false)
  assert.equal(r.outcome.hurt_signals,1)
  assert.equal(r.outcome.own_hurt_signals,0)
  assert.equal(r.outcome.damage_attribution,'other_or_unknown_source')
  assert.equal(r.outcome.ammo_consumed,1)
})

test('ranged shots attribute observed damage only when source is our agent', async () => {
  const f=rangedFixture('own')
  const r=await runRanged(f)
  assert.equal(r.outcome.code,'TARGET_HIT_ATTRIBUTED_TO_OWN_SHOT')
  assert.equal(r.verified,true)
  assert.equal(r.outcome.own_hurt_signals,1)
})

test('unconfirmed ammunition delta retains uncertain physical shot identity', async () => {
  const f=rangedFixture(null,false)
  const r=await runRanged(f)
  assert.equal(r.outcome.code,'RANGED_EFFECT_UNCONFIRMED')
  assert.equal(r.outcome.status,'partial')
  assert.equal(r.effect_disposition,'unknown')
})


test('target-independent projectile use proves bow use from ammunition release', async () => {
  const f=rangedFixture(null,true)
  const oldTicks=runtime.waitForPhysicsTicks
  const ballistics=require('./ballistics')
  const oldCharge=ballistics.chargeTicks
  runtime.waitForPhysicsTicks=async()=>{}
  ballistics.chargeTicks=()=>1
  runtime.bindBot(f.bot)
  try {
    const result=await combat.fire_projectile({weapon:'bow',shots:1})
    assert.equal(result.outcome.status,'applied')
    assert.equal(result.outcome.code,'PROJECTILES_RELEASED')
    assert.equal(result.outcome.weapon,'bow')
    assert.equal(result.outcome.shots_released,1)
    assert.equal(result.outcome.ammo_consumed,1)
    assert.equal(result.outcome.no_target_selected,true)
    assert.equal(result.outcome.hit_or_damage_claimed,false)
  } finally {
    runtime.waitForPhysicsTicks=oldTicks
    ballistics.chargeTicks=oldCharge
  }
})

test('target-independent projectile use rejects exact unavailable ranged weapon before activation', async () => {
  const f=rangedFixture(null,true)
  runtime.bindBot(f.bot)
  const result=await combat.fire_projectile({weapon:'crossbow',shots:1})
  assert.equal(result.outcome.status,'rejected')
  assert.equal(result.outcome.code,'RANGED_WEAPON_NOT_AVAILABLE')
  assert.equal(result.effect_disposition,'not_applied')
})
