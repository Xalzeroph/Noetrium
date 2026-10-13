'use strict'
const assert = require('node:assert/strict')
const test = require('node:test')
const { Vec3 } = require('vec3')
const { Movements } = require('mineflayer-pathfinder')
const runtime = require('./runtime')
const pos = new Vec3(1,65,1)
const ore = { name:'iron_ore', type:15, position:pos }
function nav (options={}) {
  const m = Object.create(Movements.prototype)
  m.canDig = false
  m.dontCreateFlow = true
  m.dontMineUnderFallingBlock = true
  m.blocksCantBreak = new Set(options.forbidden ? [15] : [])
  m.getBlock = (_pos, _x, y) => ({ liquid:!!options.fluid, canFall:!!options.falling && y===1 })
  m.getNumEntitiesAt = () => options.occupied ? 1 : 0
  m.exclusionBreak = () => 0
  return m
}
test('explicit collection runs the native safety oracle while navigation stays nondestructive',()=>{
 const movements=nav()
 runtime.bindBot({entity:{position:pos},pathfinder:{movements}})
 assert.equal(movements.safeToBreak(ore),false)
 assert.equal(runtime.safeToHarvestBlock(ore),true)
 assert.equal(movements.canDig,false)
 assert.equal(movements.safeToBreak(ore),false)
})
test('physical flow falling occupancy and block exclusions remain enforced',()=>{
 for(const hazard of [{fluid:true},{falling:true},{occupied:true},{forbidden:true}]){
  const movements=nav(hazard)
  runtime.bindBot({entity:{position:pos},pathfinder:{movements}})
  assert.equal(runtime.safeToHarvestBlock(ore),false,JSON.stringify(hazard))
  assert.equal(movements.canDig,false)
 }
})
test('missing safety oracle stays fail closed',()=>{
 runtime.bindBot({entity:{position:pos},pathfinder:{movements:{canDig:false}}})
 assert.equal(runtime.safeToHarvestBlock(ore),false)
 assert.equal(runtime.safeToHarvestBlock(null),false)
})

test('reused harvest view observes changing world hazards',()=>{
 const m=nav()
 runtime.bindBot({entity:{position:pos},pathfinder:{movements:m}})
 assert.equal(runtime.safeToHarvestBlock(ore),true)
 m.getBlock=()=>({liquid:true,canFall:false})
 assert.equal(runtime.safeToHarvestBlock(ore),false)
 m.getBlock=()=>({liquid:false,canFall:false})
 assert.equal(runtime.safeToHarvestBlock(ore),true)
 assert.equal(m.canDig,false)
})
