'use strict'

function declaredDropNamesForBlock (activeBot, block) {
  const names = []
  for (const row of Array.isArray(block && block.drops) ? block.drops : []) {
    const id = typeof row === 'number' ? row
      : row && typeof row.drop === 'number' ? row.drop
        : row && row.drop && typeof row.drop.id === 'number' ? row.drop.id
          : row && typeof row.id === 'number' ? row.id : null
    const item = id == null ? null : activeBot && activeBot.registry && activeBot.registry.items && activeBot.registry.items[id]
    if (item && item.name && !names.includes(item.name)) names.push(item.name)
  }
  return names
}

function dropNamesForBlock (activeBot, block) {
  const names = declaredDropNamesForBlock(activeBot, block)
  // Physical collection may still target an exact observed block by block
  // name when registry drop metadata is absent. This fallback must never be
  // promoted into a declared dependency acquisition relation.
  if (names.length === 0 && block && block.name) names.push(String(block.name))
  return names
}

// Same version-pinned, public vanilla recipe source as recipe_lookup; this is
// not an action policy, not a hidden datapack oracle, and not a second catalog.
// Adapt Mindcraft's inventory-aware dependency expansion, but preserve its
// unproved recipe selection as explicitly reference-only and expose all known
// alternatives rather than privileging hard-coded materials.
const { referenceCraftingRecipes } = require('./registry_search')

function currentInventoryCounts (bot) {
  if (!bot || !bot.inventory || typeof bot.inventory.items !== 'function') {
    throw new Error('RECIPE_DEPENDENCIES_INVENTORY_NOT_OBSERVED')
  }
  const stock = {}
  for (const item of bot.inventory.items()) {
    if (item && typeof item.name === 'string' && Number.isSafeInteger(item.count) &&
        item.count > 0) stock[item.name] = (stock[item.name] || 0) + item.count
  }
  return stock
}

function ingredientsForRecipe (recipe) {
  const ingredients = {}
  const push = name => {
    if (name == null) return
    if (typeof name !== 'string') throw new Error('RECIPE_DEPENDENCIES_INGREDIENT_INVALID')
    ingredients[name] = (ingredients[name] || 0) + 1
  }
  if (recipe.type === 'shaped') {
    for (const row of recipe.shape) for (const name of row) push(name)
  } else if (recipe.type === 'shapeless') {
    for (const name of recipe.ingredients) push(name)
  } else {
    throw new Error('RECIPE_DEPENDENCIES_UNKNOWN_RECIPE_TYPE')
  }
  return ingredients
}

function referenceRecipeDependencies (registry, item, count, observedInventory, options = {}) {
  const observedResourceNames = options.observedResourceNames || null
  if (!Number.isSafeInteger(count) || count <= 0 || count > 64) {
    throw new Error('RECIPE_DEPENDENCIES_COUNT_INVALID')
  }
  const referenceByItem = new Map()
  const stock = { ...observedInventory }
  const leftovers = {}
  const unresolved = {}
  const steps = []
  const choices = []
  const cycles = []

  function lookup (name) {
    if (!referenceByItem.has(name)) {
      referenceByItem.set(name, referenceCraftingRecipes(registry, name, 100))
    }
    return referenceByItem.get(name)
  }

  // Mindcraft's fixed first-recipe choice is often misleading: sticks may
  // suggest bamboo even while observed oak logs are available. Evaluate
  // every public vanilla alternative against *observed* inventory, ranking
  // cycle-free dependencies and fewer unresolved leaves first. This is only
  // an inventory-aware reference estimate: shared stock is consumed exactly
  // by expand(), not by this predictor, and live datapack rules are unknown.
  //
  // Memoize the acyclic subproblem (name, quantity, active recipe ancestors).
  // No server state or hidden evaluator information may influence selection.
  const estimateMemo = new Map()
  function estimate (name, amount, visiting) {
    const onHand = (stock[name] || 0) + (leftovers[name] || 0)
    const required = Math.max(0, amount - Math.min(onHand, amount))
    if (required === 0) return { cycles: 0, inaccessible: 0, missing: 0, steps: 0 }
    if (visiting.has(name)) return { cycles: 1, inaccessible: required, missing: required, steps: 0 }
    const reference = lookup(name)
    if (reference.recipes.length === 0) {
      return {
        cycles: 0,
        inaccessible: observedResourceNames === null || observedResourceNames.has(name) ? 0 : required,
        missing: required,
        steps: 0,
      }
    }
    const key = JSON.stringify([name, required, [...visiting].sort()])
    if (estimateMemo.has(key)) return estimateMemo.get(key)
    const next = new Set(visiting)
    next.add(name)
    let best = null
    for (const recipe of reference.recipes) {
      const batches = Math.ceil(required / recipe.result_count)
      const ingredients = ingredientsForRecipe(recipe)
      const total = { cycles: 0, inaccessible: 0, missing: 0, steps: batches }
      for (const [ingredient, quantity] of Object.entries(ingredients)) {
        const cost = estimate(ingredient, quantity * batches, next)
        total.cycles += cost.cycles
        total.inaccessible += cost.inaccessible
        total.missing += cost.missing
        total.steps += cost.steps
      }
      if (best === null || compareCost(total, best) < 0) best = total
      if (best.cycles === 0 && best.missing === 0 && best.steps === 1) break
    }
    estimateMemo.set(key, best)
    return best
  }

  function compareCost (left, right) {
    return left.cycles - right.cycles ||
      left.inaccessible - right.inaccessible ||
      left.missing - right.missing ||
      left.steps - right.steps
  }

  function chooseRecipe (name, required, visiting, forcedIndex = null) {
    const reference = lookup(name)
    const next = new Set(visiting)
    next.add(name)
    let selected = null
    reference.recipes.forEach((recipe, index) => {
      if (forcedIndex !== null && index !== forcedIndex) return
      const batches = Math.ceil(required / recipe.result_count)
      const inputs = ingredientsForRecipe(recipe)
      const cost = { cycles: 0, inaccessible: 0, missing: 0, steps: batches }
      for (const [ingredient, quantity] of Object.entries(inputs)) {
        const estimateCost = estimate(ingredient, quantity * batches, next)
        cost.cycles += estimateCost.cycles
        cost.inaccessible += estimateCost.inaccessible
        cost.missing += estimateCost.missing
        cost.steps += estimateCost.steps
      }
      if (selected === null || compareCost(cost, selected.cost) < 0) {
        selected = { recipe, index, cost }
      }
    })
    return selected
  }

  // Every successful edge consumes finite *observed* stock. Prevent
  // genuinely cyclic crafting references from recursing forever; leave the
  // unsolved dependency as an explicit acquisition requirement.
  function expand (name, amount, visiting) {
    const available = (stock[name] || 0) + (leftovers[name] || 0)
    const use = Math.min(available, amount)
    const useLeftovers = Math.min(leftovers[name] || 0, use)
    leftovers[name] = (leftovers[name] || 0) - useLeftovers
    stock[name] = (stock[name] || 0) - (use - useLeftovers)
    const required = amount - use
    if (required === 0) return

    const reference = lookup(name)
    if (visiting.has(name) || reference.recipes.length === 0) {
      unresolved[name] = (unresolved[name] || 0) + required
      if (visiting.has(name)) cycles.push(name)
      return
    }

    // Forced root indices are used only to enumerate public alternatives;
    // nested selection stays inventory-aware but reference-only.
    const forcedIndex = visiting.size === 0 &&
      Number.isSafeInteger(options.rootRecipeIndex)
      ? options.rootRecipeIndex : null
    const selected = chooseRecipe(name, required, visiting, forcedIndex)
    if (selected === null) throw new Error('RECIPE_DEPENDENCIES_REFERENCE_INDEX_INVALID')
    // A non-root dependency whose best public reference still closes a cycle
    // cannot explain how that dependency is externally obtained. Stop before
    // traversing the back-edge and expose the current dependency itself as
    // unresolved acquisition debt. Because recipe selection minimizes cycle
    // count first, this branch is taken only when no cycle-free alternative
    // exists. The root is still expanded once, preserving its direct declared
    // input relation without manufacturing free material from reversible
    // compression/decompression recipes.
    if (visiting.size > 0 && selected.cost.cycles > 0) {
      unresolved[name] = (unresolved[name] || 0) + required
      cycles.push(name)
      return
    }
    const recipe = selected.recipe
    const perBatch = recipe.result_count
    const batches = Math.ceil(required / perBatch)
    const produced = batches * perBatch
    if (produced > required) {
      leftovers[name] = (leftovers[name] || 0) + (produced - required)
    }
    const inputs = ingredientsForRecipe(recipe)
    const cyclesBefore = cycles.length
    const next = new Set(visiting)
    next.add(name)
    for (const [ingredient, perRecipe] of Object.entries(inputs)) {
      expand(ingredient, perRecipe * batches, next)
    }
    choices.push({ item: name, reference_recipe_index: selected.index,
      estimated_reference_cycles: selected.cost.cycles,
      estimated_inaccessible_material_quantity: selected.cost.inaccessible,
      estimated_unresolved_material_quantity: selected.cost.missing,
      available_reference_alternatives: reference.recipes_recorded })
    steps.push({ output_item: name, output_count: produced,
      batches, input_items: Object.fromEntries(
        Object.entries(inputs).map(([key, qty]) => [key, qty * batches])
      ),
      requires_crafting_table: recipe.requires_crafting_table,
      cyclic_recipe_dependency_unresolved: cycles.length > cyclesBefore })
  }

  const root = lookup(item)
  expand(item, count, new Set())
  // Evaluate all root recipes against independent copies of the observed
  // inventory. A candidate's leaves are public reference requirements, NOT
  // evidence that any physical source is present or reachable.
  const profiles = options.skipAlternativeProfiles ? [] : root.recipes.map((recipe, index) => {
    const variant = referenceRecipeDependencies(
      registry, item, count, observedInventory,
      { rootRecipeIndex: index, skipAlternativeProfiles: true }
    )
    const shortages = variant.unresolved_acquisition_inputs
    return {
      reference_recipe_index: index,
      result_count_per_batch: recipe.result_count,
      unresolved_acquisition_inputs: shortages,
      reference_crafting_steps: variant.reference_crafting_steps,
      unresolved_kind_count: Object.keys(shortages).length,
      unobserved_item_quantity: Object.values(shortages).reduce((a, n) => a + n, 0),
      cycles_detected: variant.cycles_detected
    }
  }).sort((a, b) =>
    Number(a.cycles_detected.length > 0) - Number(b.cycles_detected.length > 0) ||
    a.unresolved_kind_count - b.unresolved_kind_count ||
    a.unobserved_item_quantity - b.unobserved_item_quantity ||
    a.reference_crafting_steps.length - b.reference_crafting_steps.length ||
    a.reference_recipe_index - b.reference_recipe_index
  )
  return {
    item: root.item,
    count,
    item_known: root.item_known,
    minecraft_version: root.minecraft_version,
    source: 'version_pinned_vanilla_minecraft_data',
    inventory_source: 'currently_observed_mineflayer_inventory',
    inventory_before: { ...observedInventory },
    inventory_after_reference_allocation: stock,
    declared_reference_truth: true,
    observed_inventory_truth: true,
    authoritative_for_current_world_recipe: false,
    datapack_rules_included: false,
    no_physical_effect: true,
    selection_semantics: 'observed_source_and_inventory_weighted_acyclic_vanilla_reference_not_globally_optimal_or_verified',
    root_recipe_alternatives: root.recipes,
    root_alternative_dependency_profiles: profiles,
    alternative_ranking_semantics: 'declared_shortage_complexity_only_not_physical_availability',
    root_recipes_truncated: root.recipes_truncated,
    alternative_selection_notes: choices,
    unresolved_acquisition_inputs: unresolved,
    cycles_detected: [...new Set(cycles)],
    reference_crafting_steps: steps,
    disclaimer: 'Missing inputs may be obtained by mining, smelting, trading, loot or another method. No hidden or active datapack recipe has been inspected. These steps are public vanilla suggestions, not a physical execution plan.'
  }
}

// Source opportunities are independently observed in client-loaded chunks.
// They do not establish reachability, harvestability or physical possession.
function observedLocalAcquisitionSources (bot, profiles, maxDistance = 16, maxCandidates = 48) {
  const wanted = new Map()
  for (const profile of profiles) {
    for (const [name, amount] of Object.entries(profile.unresolved_acquisition_inputs || {})) {
      if (!Number.isFinite(amount) || amount <= 0) continue
      if (!wanted.has(name)) wanted.set(name, new Set())
      wanted.get(name).add(profile.reference_recipe_index)
    }
  }
  const empty = (status, candidates = []) => ({
    truth_class: 'observed',
    observation_status: status,
    loaded_world_only: true,
    max_distance: maxDistance,
    no_global_absence_or_harvestability_claim: true,
    candidates
  })
  if (wanted.size === 0) return empty('no_unheld_leaf_inputs')
  if (!bot || typeof bot.findBlocks !== 'function' ||
      typeof bot.blockAt !== 'function') return empty('observation_unavailable')
  // A physically observed block may produce an item with a different name
  // (stone -> cobblestone). These are public registry drop references, not
  // claims that the hidden world rule will produce that item.
  const matchNames = block => {
    if (!block) return []
    // A dependency source asserts that mining this block can yield the wanted
    // item. Match only version-pinned declared drops. Block-name equality is a
    // physical targeting convenience (e.g. collect/remove stone), not evidence
    // that the block drops an item with the same name (stone -> cobblestone).
    return declaredDropNamesForBlock(bot, block).filter(name => wanted.has(name))
  }
  let positions
  try {
    positions = bot.findBlocks({
      matching: block => matchNames(block).length > 0,
      maxDistance,
      count: maxCandidates
    })
  } catch (_) {
    return empty('observation_unavailable')
  }
  if (!Array.isArray(positions)) return empty('observation_unavailable')
  const seen = new Set()
  const candidates = []
  let unavailablePositions = 0
  for (const pos of positions) {
    if (!pos || !Number.isFinite(pos.x) || !Number.isFinite(pos.y) ||
        !Number.isFinite(pos.z)) continue
    const key = pos.x + ':' + pos.y + ':' + pos.z
    if (seen.has(key)) continue
    seen.add(key)
    let block
    try {
      block = bot.blockAt(pos)
    } catch (_) {
      unavailablePositions += 1
      continue
    }
    const matchedNames = matchNames(block)
    if (matchedNames.length === 0) continue
    const indices = new Set()
    for (const name of matchedNames) {
      for (const index of wanted.get(name)) indices.add(index)
    }
    candidates.push({
      source_block: block.name,
      position: { x: pos.x, y: pos.y, z: pos.z },
      matched_reference_item_names: matchedNames.sort(),
      drop_relation_truth_class: 'declared_vanilla_reference',
      matched_reference_recipe_indices: [...indices].sort((a, b) => a - b),
      physically_acquired: false,
      path_reachable: null
    })
  }
  return empty(
    unavailablePositions > 0 ? 'partial_bounded_loaded_world_observation' : 'bounded_loaded_world_observed',
    candidates
  )
}

module.exports = { currentInventoryCounts, ingredientsForRecipe, referenceRecipeDependencies, observedLocalAcquisitionSources, dropNamesForBlock }
