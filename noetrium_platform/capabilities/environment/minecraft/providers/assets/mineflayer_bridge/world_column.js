'use strict'

const { Vec3 } = require('vec3')

const OPEN_AIR_NAMES = new Set(['air', 'cave_air', 'void_air'])

function dimensionVerticalBounds (activeBot) {
  const minY = Number(activeBot && activeBot.game && activeBot.game.minY)
  const height = Number(activeBot && activeBot.game && activeBot.game.height)
  if (!Number.isInteger(minY) || !Number.isInteger(height) || height <= 0) {
    return null
  }
  return {
    min_y: minY,
    height,
    max_y_exclusive: minY + height
  }
}

function isOpenAir (block) {
  return Boolean(block && OPEN_AIR_NAMES.has(String(block.name || '')))
}

function verticalColumnObservation (activeBot) {
  const bounds = dimensionVerticalBounds(activeBot)
  if (!bounds || !activeBot || !activeBot.entity || !activeBot.entity.position) {
    return {
      vertical_bounds: bounds,
      first_solid_above_head: null,
      surface: null
    }
  }

  const origin = activeBot.entity.position
  const x = Math.floor(Number(origin.x))
  const z = Math.floor(Number(origin.z))
  const originY = Math.floor(Number(origin.y))
  let firstSolidAboveHead = null
  let surface = null
  let aboveOne = null
  let aboveTwo = null

  // One exact dimension-bounded scan computes both vertical observables.
  // Scanning top-down means the first standable surface is globally highest
  // in this loaded column, while overwriting firstSolidAboveHead yields the
  // nearest physical obstruction above the bot by the end of the pass.
  for (
    let y = bounds.max_y_exclusive - 1;
    y >= bounds.min_y;
    y -= 1
  ) {
    const block = activeBot.blockAt(new Vec3(x, y, z))
    const physical = Boolean(
      block &&
      block.name &&
      block.boundingBox !== 'empty'
    )

    if (
      surface === null &&
      physical &&
      isOpenAir(aboveOne) &&
      isOpenAir(aboveTwo)
    ) {
      surface = {
        block: String(block.name),
        block_y: y,
        standing_position: {
          x: x + 0.5,
          y: y + 1,
          z: z + 0.5
        }
      }
    }

    if (physical && y >= originY + 2) {
      firstSolidAboveHead = {
        name: String(block.name),
        blocks_up: y - (originY + 2)
      }
    }

    // Once the highest legal surface is known, no block below it can
    // improve that observation. The nearest obstruction above the head
    // is also final after visiting height originY+2. A full scan beyond
    // this point cannot change either observable.
    if (surface !== null && y <= originY + 2) break

    aboveTwo = aboveOne
    aboveOne = block
  }

  return {
    vertical_bounds: bounds,
    first_solid_above_head: firstSolidAboveHead,
    surface
  }
}

module.exports = { verticalColumnObservation }
