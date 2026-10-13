'use strict'

const fs = require('fs')
const path = require('path')
const ROOT = process.cwd()

function readJson (relative) {
  return JSON.parse(fs.readFileSync(path.join(ROOT, relative), 'utf8'))
}

function requireVersion (pkg, expected) {
  const actual = readJson('node_modules/' + pkg + '/package.json').version
  if (actual !== expected) {
    throw new Error('unsupported ' + pkg + ' version: expected ' + expected + ', got ' + actual)
  }
}

function replaceOnce (relative, before, after) {
  const file = path.join(ROOT, relative)
  const source = fs.readFileSync(file, 'utf8')
  const first = source.indexOf(before)
  if (first < 0) throw new Error('patch anchor missing: ' + relative)
  if (source.indexOf(before, first + before.length) >= 0) {
    throw new Error('patch anchor is not unique: ' + relative)
  }
  fs.writeFileSync(file, source.slice(0, first) + after + source.slice(first + before.length))
}

requireVersion('mineflayer', '4.39.0')
requireVersion('mineflayer-pathfinder', '2.4.5')
requireVersion('mineflayer-collectblock', '1.6.0')
requireVersion('mineflayer-tool', '1.2.0')
requireVersion('mineflayer-pvp', '1.3.2')

replaceOnce(
  'node_modules/mineflayer/lib/plugins/inventory.js',
  '    await withTimeout(eatingTask.promise, CONSUME_TIMEOUT)\n',
  '    await eatingTask.promise\n'
)

replaceOnce(
  'node_modules/mineflayer/lib/plugins/bed.js',
  '  async function sleep (bedBlock) {\n',
  '  async function sleep (bedBlock, timeoutMs) {\n'
)

replaceOnce(
  'node_modules/mineflayer/lib/plugins/bed.js',
  '      const waitingPromise = waitUntilSleep()\n',
  '      const waitingPromise = waitUntilSleep(timeoutMs)\n'
)

replaceOnce(
  'node_modules/mineflayer/lib/plugins/bed.js',
  "  async function waitUntilSleep () {\n    return new Promise((resolve, reject) => {\n      const timeoutForSleep = setTimeout(() => {\n        reject(new Error('bot is not sleeping'))\n      }, 3000)\n\n      bot.once('sleep', () => {\n        clearTimeout(timeoutForSleep)\n        resolve()\n      })\n    })\n  }\n",
  "  async function waitUntilSleep (timeoutMs) {\n    const timeout = Number(timeoutMs)\n    if (!Number.isFinite(timeout) || timeout <= 0) throw new Error('sleep timeout must be finite and positive')\n    return new Promise((resolve, reject) => {\n      const timeoutForSleep = setTimeout(() => {\n        reject(new Error('bot is not sleeping'))\n      }, timeout)\n\n      bot.once('sleep', () => {\n        clearTimeout(timeoutForSleep)\n        resolve()\n      })\n    })\n  }\n"
)

replaceOnce(
  'node_modules/mineflayer-tool/lib/Inventory.js',
  "            catch (err) {\n                if (cb != null)\n                    cb(err);\n                throw err;\n            }\n        }\n    });\n}\nexports.retrieveTools = retrieveTools;\n",
  "            catch (err) {\n                if (cb != null)\n                    cb(err);\n                throw err;\n            }\n        }\n        const err = (0, Tool_1.error)('NoChest', 'There are no chests with available tools in them!');\n        if ((cb != null) && typeof cb === 'function')\n            cb(err);\n        throw err;\n    });\n}\nexports.retrieveTools = retrieveTools;\n"
)

replaceOnce(
  'node_modules/mineflayer-pvp/lib/PVP.js',
  "this.bot.on('physicTick', () => this.update());",
  "this.bot.on('physicsTick', () => this.update());"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/index.js',
  "  const waterType = bot.registry.blocksByName.water.id\n",
  ""
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/index.js',
  "  bot.pathfinder.getPathTo = (movements, goal, timeout) => {\n    const generator = bot.pathfinder.getPathFromTo(movements, bot.entity.position, goal, { timeout })\n",
  "  bot.pathfinder.getPathTo = (movements, goal, timeout) => {\n    if (typeof movements.updateLavaAvoidance === 'function') movements.updateLavaAvoidance()\n    const generator = bot.pathfinder.getPathFromTo(movements, bot.entity.position, goal, { timeout })\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/index.js',
  "      if (curPoint.toBreak.length > 0 || curPoint.toPlace.length > 0) break\n",
  "      if (curPoint.toBreak.length > 0 || curPoint.toPlace.some(p => !p.useOne)) break\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/index.js',
  "      const b = bot.blockAt(new Vec3(curPoint.x, curPoint.y, curPoint.z))\n      if (b && (b.type === waterType || ((b.type === ladderId || b.type === vineId) && i + 1 < path.length && path[i + 1].y < curPoint.y))) {\n",
  "      const b = bot.blockAt(new Vec3(curPoint.x, curPoint.y, curPoint.z))\n      const doorway = stateMovements && stateMovements.openable && b && stateMovements.openable.has(b.type)\n      const liquid = b && b.boundingBox === 'empty' && (stateMovements.liquids.has(b.type) || b.isWaterlogged === true)\n      if (b && (liquid || doorway || ((b.type === ladderId || b.type === vineId) && i + 1 < path.length && path[i + 1].y < curPoint.y))) {\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/index.js',
  "  bot.pathfinder.stop = () => {\n    stopPathing = true\n  }\n",
  "  bot.pathfinder.stop = () => {\n    if (!stateGoal && path.length === 0) return\n    stopPathing = true\n  }\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/index.js',
  "    if (bot.entity.isInWater) {\n      bot.setControlState('jump', true)\n      bot.setControlState('sprint', false)\n    } else if (stateMovements.allowSprinting && physics.canStraightLine(path, true)) {\n",
  "    if (bot.entity.isInWater || bot.entity.isInLava) {\n      bot.setControlState('jump', true)\n      bot.setControlState('sprint', false)\n    } else if (stateMovements.allowSprinting && physics.canStraightLine(path, true)) {\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    this.liquids.add(registry.blocksByName.water.id)\n    this.liquids.add(registry.blocksByName.lava.id)\n",
  "    this.liquids.add(registry.blocksByName.water.id)\n    this.liquids.add(registry.blocksByName.lava.id)\n    for (const name of ['seagrass', 'tall_seagrass', 'kelp', 'kelp_plant', 'bubble_column']) {\n      if (registry.blocksByName[name]) this.liquids.add(registry.blocksByName[name].id)\n    }\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    b.liquid = this.liquids.has(b.type)\n",
  "    b.liquid = this.liquids.has(b.type) || b.isWaterlogged === true\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "      cost += this.exclusionPlace(blockC)\n      toPlace.push({ x: node.x, y: node.y - 1, z: node.z, dx: dir.x, dy: 0, dz: dir.z })\n",
  "      cost += this.exclusionPlace(blockD)\n      toPlace.push({ x: node.x, y: node.y - 1, z: node.z, dx: dir.x, dy: 0, dz: dir.z })\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    const blockC = this.getBlock(node, dir.x, 0, dir.z) // Landing block or standing on block when jumping up by 1\n    const y = blockC.physical ? 1 : 0\n\n    const block0 = this.getBlock(node, 0, -1, 0)\n",
  "    const blockC = this.getBlock(node, dir.x, 0, dir.z) // Landing block or standing on block when jumping up by 1\n    const y = blockC.physical ? 1 : 0\n    if (y === 1) return\n\n    const block0 = this.getBlock(node, 0, -1, 0)\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    const blockD1 = this.getBlock(node, 0, y - 1, dir.z)\n    cost1 += this.safeOrBreak(blockB1, toBreak1)\n",
  "    const blockD1 = this.getBlock(node, 0, y - 1, dir.z)\n    if (!blockB1.safe || !blockC1.safe) return\n    cost1 += this.safeOrBreak(blockB1, toBreak1)\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    const blockD2 = this.getBlock(node, dir.x, y - 1, 0)\n    cost2 += this.safeOrBreak(blockB2, toBreak2)\n",
  "    const blockD2 = this.getBlock(node, dir.x, y - 1, 0)\n    if (!blockB2.safe || !blockC2.safe) return\n    cost2 += this.safeOrBreak(blockB2, toBreak2)\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    this.blocksToAvoid.add(registry.blocksByName.lava.id)\n",
  "    if (!bot.entity || !bot.entity.isInLava) this.blocksToAvoid.add(registry.blocksByName.lava.id)\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    this.climbables.add(registry.blocksByName.ladder.id)\n    // this.climbables.add(registry.blocksByName.vine.id)\n",
  "    this.climbables.add(registry.blocksByName.ladder.id)\n    for (const name of ['vine', 'weeping_vines', 'weeping_vines_plant', 'twisting_vines', 'twisting_vines_plant', 'cave_vines', 'cave_vines_plant']) {\n      if (registry.blocksByName[name]) this.climbables.add(registry.blocksByName[name].id)\n    }\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "      if (this.interactableBlocks.has(block.name) && block.name.toLowerCase().includes('gate') && !block.name.toLowerCase().includes('iron')) {\n",
  "      const name = block.name.toLowerCase()\n      if (this.interactableBlocks.has(block.name) && (name.includes('gate') || name.includes('door') || name.includes('trapdoor')) && !name.includes('iron')) {\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    this.canOpenDoors = false // Causes issues. Probably due to none paper servers.\n",
  "    this.canOpenDoors = true\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    b.safe = (b.boundingBox === 'empty' || b.climbable || this.carpets.has(b.type)) && !this.blocksToAvoid.has(b.type)\n    b.physical = b.boundingBox === 'block' && !this.fences.has(b.type)\n",
  "    const isOpenTrapdoor = b.openable && b.name.includes('trapdoor') && b._properties && b._properties.open === true\n    const isClosedTrapdoor = b.openable && b.name.includes('trapdoor') && (!b._properties || b._properties.open !== true)\n    b.safe = (b.boundingBox === 'empty' || b.climbable || this.carpets.has(b.type) || isOpenTrapdoor) && !this.blocksToAvoid.has(b.type)\n    b.physical = (b.boundingBox === 'block' && !this.fences.has(b.type)) || isClosedTrapdoor\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    if (block.safe) return cost\n    if (!this.safeToBreak(block)) return 100 // Can't break, so can't move\n",
  "    if (block.safe) return cost\n    if (this.canOpenDoors && block.openable) return cost\n    if (!this.safeToBreak(block)) return 100 // Can't break, so can't move\n"
)

replaceOnce(
  'node_modules/mineflayer-pathfinder/lib/movements.js',
  "    // Open fence gates\n    if (this.canOpenDoors && blockC.openable && blockC.shapes && blockC.shapes.length !== 0) {\n",
  "    // Open wooden gates, doors and trapdoors rather than treating them as breakable obstacles.\n    if (this.canOpenDoors && blockC.openable && (!blockC._properties || blockC._properties.open !== true)) {\n"
)

const movementFile = path.join(ROOT, 'node_modules/mineflayer-pathfinder/lib/movements.js')
let movementSource = fs.readFileSync(movementFile, 'utf8')
const classEnd = '\n}\n\nmodule.exports = Movements\n'
if (!movementSource.includes(classEnd)) throw new Error('movements class end anchor missing')
movementSource = movementSource.replace(
  classEnd,
  "\n  updateLavaAvoidance () {\n    const lava = this.bot.registry.blocksByName.lava\n    if (!lava) return\n    if (this.bot.entity && this.bot.entity.isInLava) this.blocksToAvoid.delete(lava.id)\n    else this.blocksToAvoid.add(lava.id)\n  }\n" + classEnd
)
fs.writeFileSync(movementFile, movementSource)

console.log('Noetrium Mineflayer dependency patches applied')
