'use strict'
const test = require('node:test')
const assert = require('node:assert/strict')
const minecraftData = require('minecraft-data')
const { currentInventoryCounts, referenceRecipeDependencies, observedLocalAcquisitionSources } = require('./recipe_dependencies')
const registry = minecraftData('1.21.1')

test('Mindcraft-style dependencies distinguish absent tool from registry existence', () => {
  const result = referenceRecipeDependencies(registry, 'iron_pickaxe', 1, {})
  assert.equal(result.item_known, true)
  assert.equal(result.no_physical_effect, true)
  assert.equal(result.authoritative_for_current_world_recipe, false)
  assert.equal(result.datapack_rules_included, false)
  assert.equal(result.unresolved_acquisition_inputs.iron_ingot, 3)
  assert.ok(result.reference_crafting_steps.some(step => step.output_item === 'stick'))
  assert.ok(result.reference_crafting_steps.some(step => step.output_item === 'iron_pickaxe'))
  assert.equal(result.selection_semantics, 'observed_source_and_inventory_weighted_acyclic_vanilla_reference_not_globally_optimal_or_verified')
})

test('actual inventory is used without inventing resources or mutating source', () => {
  const source = Object.freeze({ iron_ingot: 3, stick: 2 })
  const a = referenceRecipeDependencies(registry, 'iron_pickaxe', 1, source)
  const b = referenceRecipeDependencies(registry, 'iron_pickaxe', 1, {})
  assert.deepEqual(a.unresolved_acquisition_inputs, {})
  assert.equal(a.reference_crafting_steps.length, 1)
  assert.ok(Object.keys(b.unresolved_acquisition_inputs).length > 0)
  assert.equal(source.iron_ingot, 3)
  assert.equal(source.stick, 2)
})

test('noncraftable items are missing acquisition inputs, never assumed impossible', () => {
  const out = referenceRecipeDependencies(registry, 'ancient_debris', 1, {})
  assert.deepEqual(out.unresolved_acquisition_inputs, { ancient_debris: 1 })
  assert.equal(out.reference_crafting_steps.length, 0)
  assert.equal(out.authoritative_for_current_world_recipe, false)
})

test('diamond-block to diamond crafting cycle is not hallucinated as free material', () => {
  const out = referenceRecipeDependencies(registry, 'diamond', 1, {})
  assert.ok(out.cycles_detected.length > 0)
  assert.deepEqual(out.unresolved_acquisition_inputs, { diamond_block: 1 })
  assert.ok(out.reference_crafting_steps.some(step => step.cyclic_recipe_dependency_unresolved))
})

test('reversible storage recipe stops before the back-edge and exposes the direct root input', () => {
  const out = referenceRecipeDependencies(registry, 'redstone_block', 1, {})
  assert.deepEqual(out.unresolved_acquisition_inputs, { redstone: 9 })
  assert.ok(out.reference_crafting_steps.some(step =>
    step.output_item === 'redstone_block' && step.input_items.redstone === 9
  ))
  assert.ok(!Object.hasOwn(out.unresolved_acquisition_inputs, 'redstone_block'))
})

test('bounded recursion terminates cyclic vanilla craft graphs', () => {
  const out = referenceRecipeDependencies(registry, 'stick', 4, {})
  assert.equal(out.count, 4)
  assert.ok(Array.isArray(out.cycles_detected))
  assert.ok(out.reference_crafting_steps.length < 100)
})

test('all stick recipe branches remain visible without inventing a preferred source', () => {
  const out = referenceRecipeDependencies(registry, 'stick', 4, {})
  const profiles = out.root_alternative_dependency_profiles
  assert.equal(profiles.length, out.root_recipe_alternatives.length)
  assert.ok(profiles.some(p => p.unresolved_acquisition_inputs.oak_log === 1))
  assert.ok(profiles.some(p => p.unresolved_acquisition_inputs.bamboo === 8))
  assert.equal(profiles[0].unobserved_item_quantity, 1)
  assert.equal(out.alternative_ranking_semantics,
    'declared_shortage_complexity_only_not_physical_availability')
  assert.equal(out.authoritative_for_current_world_recipe, false)
})

test('loaded local sources match public recipe branches without asserting harvestability', () => {
  const ref = referenceRecipeDependencies(registry, 'stick', 4, {})
  const source = { name: 'oak_log', drops: [registry.itemsByName.oak_log.id] }
  let observations = 0
  const local = observedLocalAcquisitionSources({
    registry,
    findBlocks: opts => {
      observations += 1
      assert.equal(opts.maxDistance, 16)
      assert.equal(opts.matching(source), true)
      return [{ x: 2, y: 69, z: 3 }, { x: 2, y: 69, z: 3 }]
    },
    blockAt: () => source
  }, ref.root_alternative_dependency_profiles)
  assert.equal(observations, 1)
  assert.equal(local.truth_class, 'observed')
  assert.equal(local.candidates.length, 1)
  assert.equal(local.candidates[0].source_block, 'oak_log')
  assert.equal(local.candidates[0].physically_acquired, false)
  assert.equal(local.candidates[0].path_reachable, null)
  const oakIndex = ref.root_alternative_dependency_profiles.find(
    p => p.unresolved_acquisition_inputs.oak_log === 1
  ).reference_recipe_index
  assert.ok(local.candidates[0].matched_reference_recipe_indices.includes(oakIndex))
})

test('unavailable local sensing cannot fabricate recipe ingredient sources', () => {
  const ref = referenceRecipeDependencies(registry, 'stick', 4, {})
  const observed = observedLocalAcquisitionSources({}, ref.root_alternative_dependency_profiles)
  assert.equal(observed.observation_status, 'observation_unavailable')
  assert.deepEqual(observed.candidates, [])
  assert.equal(observed.no_global_absence_or_harvestability_claim, true)
})

test('a stale loaded-block read is explicitly partial, not a global absence', () => {
  const ref = referenceRecipeDependencies(registry, 'stick', 4, {})
  const out = observedLocalAcquisitionSources({
    findBlocks: () => [{ x: 1, y: 70, z: 1 }],
    blockAt: () => { throw new Error('chunk unloaded') }
  }, ref.root_alternative_dependency_profiles)
  assert.equal(out.observation_status, 'partial_bounded_loaded_world_observation')
  assert.deepEqual(out.candidates, [])
  assert.equal(out.no_global_absence_or_harvestability_claim, true)
})

test('inventory observation requires valid world source', () => {
  assert.deepEqual(currentInventoryCounts({
    inventory: {items: () => [{name:'oak_log',count:2},{name:'oak_log',count:1}]}
  }), {oak_log:3})
  assert.throws(() => currentInventoryCounts({inventory:{}}), /INVENTORY_NOT_OBSERVED/)
})

test('oak logs yield an inventory-feasible stick path instead of unavailable bamboo', () => {
  const result = referenceRecipeDependencies(registry, 'stick', 4, { oak_log: 2 })
  assert.deepEqual(result.unresolved_acquisition_inputs, {})
  assert.ok(result.reference_crafting_steps.some(step => step.output_item === 'oak_planks'))
  assert.ok(result.reference_crafting_steps.some(step => step.output_item === 'stick'))
  assert.ok(result.alternative_selection_notes.some(step =>
    step.item === 'stick' && step.reference_recipe_index !== 0))
  assert.equal(result.inventory_after_reference_allocation.oak_log, 1)
})

test('the choice of crafting table ingredients depends on observed log types', () => {
  const result = referenceRecipeDependencies(registry, 'crafting_table', 1, { oak_log: 2 })
  assert.deepEqual(result.unresolved_acquisition_inputs, {})
  assert.ok(result.reference_crafting_steps.some(step => step.output_item === 'oak_planks'))
  assert.ok(!result.reference_crafting_steps.some(step => step.output_item === 'cherry_planks'))
})

test('recipe exploration cannot invent materials from a cyclic conversion', () => {
  const result = referenceRecipeDependencies(registry, 'diamond', 1, {})
  assert.ok(result.cycles_detected.length > 0)
  assert.ok(Object.values(result.unresolved_acquisition_inputs).some(value => value > 0))
  assert.ok(!Object.hasOwn(result.unresolved_acquisition_inputs, 'diamond'))
})

test('nearby physically observed oak favors logs over absent bamboo without fabricating stock', () => {
  const observed = new Set(['oak_log'])
  const result = referenceRecipeDependencies(registry, 'stick', 4, {}, {observedResourceNames: observed})
  assert.deepEqual(result.unresolved_acquisition_inputs, {oak_log: 1})
  assert.ok(result.reference_crafting_steps.some(step => step.output_item === 'oak_planks'))
  assert.equal(result.inventory_before.oak_log, undefined)
})

test('reference dependency cost counts each inaccessible leaf exactly once at every depth', () => {
  const hidden = new Set()
  const planks = referenceRecipeDependencies(
    registry, 'oak_planks', 4, {}, { observedResourceNames: hidden }
  )
  const planksCost = planks.alternative_selection_notes.find(
    row => row.item === 'oak_planks'
  )
  assert.deepEqual(planks.unresolved_acquisition_inputs, { oak_log: 1 })
  assert.equal(planksCost.estimated_inaccessible_material_quantity, 1)

  const stairs = referenceRecipeDependencies(
    registry, 'oak_stairs', 4, {}, { observedResourceNames: hidden }
  )
  const stairsCost = stairs.alternative_selection_notes.find(
    row => row.item === 'oak_stairs'
  )
  assert.deepEqual(stairs.unresolved_acquisition_inputs, { oak_log: 2 })
  assert.equal(stairsCost.estimated_inaccessible_material_quantity, 2)
})

test('observed stone exposes cobblestone as a declared drop source without asserting possession', () => {
  const source = {
    name: 'stone',
    drops: [registry.itemsByName.cobblestone.id]
  }
  const position = { x: 2, y: 64, z: 3 }
  const bot = {
    registry,
    findBlocks: options => {
      assert.equal(options.matching({ ...source, position: null }), true)
      return [position]
    },
    blockAt: () => ({ ...source, position })
  }
  const report = observedLocalAcquisitionSources(bot, [{
    reference_recipe_index: 5,
    unresolved_acquisition_inputs: { cobblestone: 3 }
  }])
  assert.equal(report.truth_class, 'observed')
  assert.equal(report.candidates.length, 1)
  assert.equal(report.candidates[0].source_block, 'stone')
  assert.deepEqual(report.candidates[0].matched_reference_item_names, ['cobblestone'])
  assert.deepEqual(report.candidates[0].matched_reference_recipe_indices, [5])
  assert.equal(report.candidates[0].physically_acquired, false)
  assert.equal(report.candidates[0].path_reachable, null)
})
test('observed stone is not a direct source for stone when its declared drop is cobblestone', () => {
  const source = {
    name: 'stone',
    drops: [registry.itemsByName.cobblestone.id]
  }
  const position = { x: 2, y: 64, z: 3 }
  const bot = {
    registry,
    findBlocks: options => {
      assert.equal(options.matching({ ...source, position: null }), false)
      return []
    },
    blockAt: () => ({ ...source, position })
  }
  const report = observedLocalAcquisitionSources(bot, [{
    reference_recipe_index: 5,
    unresolved_acquisition_inputs: { stone: 3 }
  }])
  assert.equal(report.truth_class, 'observed')
  assert.deepEqual(report.candidates, [])
})

test('dependency acquisition discovery fails closed when declared drop metadata is absent', () => {
  const source = { name: 'mystery_block', drops: [] }
  const bot = {
    registry,
    findBlocks: options => {
      assert.equal(options.matching(source), false)
      return []
    },
    blockAt: () => source
  }
  const report = observedLocalAcquisitionSources(bot, [{
    reference_recipe_index: 1,
    unresolved_acquisition_inputs: { mystery_block: 1 }
  }])
  assert.deepEqual(report.candidates, [])
})
