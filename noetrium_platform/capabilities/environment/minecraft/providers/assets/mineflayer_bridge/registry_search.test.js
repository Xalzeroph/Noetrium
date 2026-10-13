'use strict'

const test = require('node:test')
const assert = require('node:assert/strict')
const {
  editDistance,
  referenceCraftingRecipes,
  searchRegistry,
  suggestRegistryKind
} = require('./registry_search')

function registry () {
  return {
    items: {
      oak_log: { name: 'oak_log', displayName: 'Oak Log' },
      oak_planks: { name: 'oak_planks', displayName: 'Oak Planks' },
      birch_log: { name: 'birch_log', displayName: 'Birch Log' },
      stone: { name: 'stone', displayName: 'Stone' }
    },
    blocks: {
      oak_log: { name: 'oak_log', displayName: 'Oak Log' },
      oak_leaves: { name: 'oak_leaves', displayName: 'Oak Leaves' },
      oak_door: { name: 'oak_door', displayName: 'Oak Door' },
      birch_log: { name: 'birch_log', displayName: 'Birch Log' }
    },
    entities: {
      zombie: { name: 'zombie', displayName: 'Zombie' },
      cow: { name: 'cow', displayName: 'Cow' }
    }
  }
}

test('registry search keeps exact registry identity first', () => {
  const result = searchRegistry(registry(), 'oak_log', 4)
  assert.equal(result.blocks[0], 'oak_log')
  assert.equal(result.items[0], 'oak_log')
  assert.equal(result.ranked_candidates[0].name, 'oak_log')
  assert.equal(result.ranked_candidates[0].exact, true)
})

test('registry search recovers executable candidates from conceptual names without aliases', () => {
  const result = searchRegistry(registry(), 'oak_tree', 4)
  assert.ok(result.blocks.includes('oak_log'))
  const oakIndex = result.blocks.indexOf('oak_log')
  const birchIndex = result.blocks.indexOf('birch_log')
  assert.ok(oakIndex >= 0)
  assert.ok(birchIndex < 0 || oakIndex < birchIndex)
  assert.ok(
    result.ranked_candidates.some(row => (
      row.kind === 'block' &&
      row.name === 'oak_log' &&
      row.shared_tokens.includes('oak')
    ))
  )
})

test('registry search fuzzy fallback works when no query token is exact', () => {
  const result = searchRegistry(registry(), 'zombi', 2)
  assert.equal(result.entities[0], 'zombie')
  assert.equal(editDistance('zombi', 'zombie'), 1)
})

test('registry search rejects missing normalization owned by the action contract', () => {
  assert.throws(
    () => searchRegistry(registry(), 'oak', 0),
    /REGISTRY_SEARCH_LIMIT_INVALID/
  )
})


test('canonical suggestion frontier preserves conceptual ambiguity without aliases', () => {
  const rows = suggestRegistryKind(registry(), 'oak_tree', 'block')
  const names = rows.map(row => row.name)
  assert.ok(names.includes('oak_log'))
  assert.ok(names.includes('oak_leaves'))
  assert.ok(names.includes('oak_door'))
  assert.ok(!names.includes('birch_log'))
})

test('canonical suggestion frontier prefers exact token prefix structure', () => {
  const custom = registry()
  custom.blocks.grass_block = { name: 'grass_block', displayName: 'Grass Block' }
  custom.blocks.short_grass = { name: 'short_grass', displayName: 'Short Grass' }
  custom.blocks.tall_grass = { name: 'tall_grass', displayName: 'Tall Grass' }
  const rows = suggestRegistryKind(custom, 'grass', 'block')
  assert.deepEqual(rows.map(row => row.name), ['grass_block'])
})

test('canonical suggestion frontier keeps typo correction fail-close but focused', () => {
  const rows = suggestRegistryKind(registry(), 'zombi', 'entity')
  assert.deepEqual(rows.map(row => row.name), ['zombie'])
})


test('a version-pinned registry is indexed only once across repeated queries', () => {
  const source = registry()
  let enumerations = 0
  source.blocks = new Proxy(source.blocks, {
    ownKeys (target) { enumerations += 1; return Reflect.ownKeys(target) }
  })
  const first = searchRegistry(source, 'oak', 4)
  const second = searchRegistry(source, 'birch', 4)
  assert.equal(enumerations, 1)
  assert.ok(first.blocks.includes('oak_log'))
  assert.equal(second.blocks[0], 'birch_log')
  const other = registry()
  assert.ok(searchRegistry(other, 'oak', 4).blocks.includes('oak_log'))
})

test('vanilla recipe reference identifies actual ingredient names, output counts and station constraints', () => {
  const mcData = require('minecraft-data')('1.21.1')
  const planks = referenceCraftingRecipes(mcData, 'oak_planks', 20)
  assert.equal(planks.truth_class, 'declared')
  assert.equal(planks.authoritative_for_current_world, false)
  assert.equal(planks.datapack_rules_included, false)
  assert.equal(planks.minecraft_version, '1.21.1')
  assert.deepEqual(planks.recipes[0].ingredients, ['oak_log'])
  assert.equal(planks.recipes[0].result_count, 4)
  assert.equal(planks.recipes[0].requires_crafting_table, false)
  const pickaxe = referenceCraftingRecipes(mcData, 'iron_pickaxe', 20)
  assert.deepEqual(pickaxe.recipes[0].shape, [
    ['iron_ingot', 'iron_ingot', 'iron_ingot'],
    [null, 'stick', null],
    [null, 'stick', null]
  ])
  assert.equal(pickaxe.recipes[0].requires_crafting_table, true)
})

test('reference does not reveal live or hidden datapack recipes', () => {
  const data = require('minecraft-data')('1.21.1')
  const unmodified = referenceCraftingRecipes(data, 'iron_pickaxe', 10)
  const hiddenShift = { ...data, worldDatapackRecipes: {
    iron_pickaxe: { ingredients: ['iron_hoe'] }
  }}
  assert.deepEqual(referenceCraftingRecipes(hiddenShift, 'iron_pickaxe', 10), unmodified)
  assert.equal(unmodified.recipes[0].shape[0][0], 'iron_ingot')
  assert.equal(referenceCraftingRecipes(data, 'nonexistent_item', 10).item_known, false)
  assert.throws(() => referenceCraftingRecipes(data, 'iron_pickaxe', 0), /LIMIT_INVALID/)
})

test('reference remains pinned to the actual minecraft protocol version', () => {
  const mcData = require('minecraft-data')
  for (const version of ['1.21.1', '1.21.4']) {
    const lookup = referenceCraftingRecipes(mcData(version), 'wooden_pickaxe', 2)
    assert.equal(lookup.minecraft_version, version)
    assert.equal(lookup.recipes_recorded >= lookup.recipes.length, true)
    assert.equal(lookup.recipes_truncated, lookup.recipes_recorded > 2)
  }
  assert.throws(() => referenceCraftingRecipes({ itemsByName: {}, recipes: {} }, 'stick', 10), /VERSION_UNAVAILABLE/)
})

test('every available vanilla crafting recipe is losslessly resolvable by the reference index', () => {
  const mcData = require('minecraft-data')
  for (const version of ['1.21.1', '1.21.4']) {
    const data = mcData(version)
    let tested = 0
    for (const item of Object.values(data.itemsByName)) {
      if (!data.recipes[item.id]) continue
      // Zero-output vanilla-data sentinel is not an executable recipe.
      if (!data.recipes[item.id].some(row => row.result && row.result.count > 0)) {
        assert.throws(
          () => referenceCraftingRecipes(data, item.name, 100),
          /REFERENCE_RECIPE_RESULT_INVALID/
        )
        continue
      }
      const result = referenceCraftingRecipes(data, item.name, 100)
      assert.equal(result.item, item.name)
      assert.equal(result.recipes.length, result.recipes_recorded)
      assert.equal(result.recipes_truncated, false)
      tested += 1
    }
    assert.ok(tested > 500)
  }
})

test('memoized public registry lookups are exact, bounded and immutable across callers and registries', () => {
  const game = registry()
  const first = searchRegistry(game, 'oak_log', 4)
  const original = JSON.parse(JSON.stringify(first))
  first.blocks[0] = 'malicious_fake_block'
  first.ranked_candidates[0].name = 'malicious_fake_block'
  const replay = searchRegistry(game, 'oak_log', 4)
  assert.deepEqual(replay, original)
  assert.notStrictEqual(replay, first)
  const narrower = searchRegistry(game, 'oak_log', 1)
  assert.equal(narrower.blocks.length, 1)
  const different = registry()
  different.blocks.diamond_block = { name: 'diamond_block', displayName: 'Diamond Block' }
  assert.equal(searchRegistry(different, 'diamond_block', 4).blocks[0], 'diamond_block')
  assert.notDeepEqual(searchRegistry(game, 'diamond_block', 4).blocks,
    searchRegistry(different, 'diamond_block', 4).blocks)
})
