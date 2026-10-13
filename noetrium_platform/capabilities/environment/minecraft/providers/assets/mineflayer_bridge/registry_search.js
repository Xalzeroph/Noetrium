'use strict'

function normalizeRegistryName (value) {
  return String(value == null ? '' : value)
    .trim()
    .toLowerCase()
    .replace(/^minecraft:/, '')
    .replace(/[^a-z0-9]+/g, '_')
    .replace(/^_+|_+$/g, '')
}

function nameTokens (value) {
  const normalized = normalizeRegistryName(value)
  return normalized ? normalized.split('_').filter(Boolean) : []
}

function editDistance (leftValue, rightValue) {
  const left = normalizeRegistryName(leftValue)
  const right = normalizeRegistryName(rightValue)
  if (left === right) return 0
  if (!left) return right.length
  if (!right) return left.length

  // Wagner-Fischer with O(min(|left|, |right|)) auxiliary memory.
  let a = left
  let b = right
  if (a.length < b.length) [a, b] = [b, a]
  let previous = Array.from({ length: b.length + 1 }, (_, index) => index)
  for (let i = 1; i <= a.length; i += 1) {
    const current = [i]
    for (let j = 1; j <= b.length; j += 1) {
      current[j] = Math.min(
        current[j - 1] + 1,
        previous[j] + 1,
        previous[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1)
      )
    }
    previous = current
  }
  return previous[b.length]
}

function candidateRank (query, candidateName) {
  const normalizedQuery = normalizeRegistryName(query)
  const normalizedName = normalizeRegistryName(candidateName)
  const queryTokens = nameTokens(normalizedQuery)
  const candidateTokens = nameTokens(normalizedName)
  const candidateTokenSet = new Set(candidateTokens)
  const sharedTokens = queryTokens.filter(token => candidateTokenSet.has(token))
  const missingQueryTokens = queryTokens.length - sharedTokens.length

  let tokenEditDistance = 0
  for (const queryToken of queryTokens) {
    let nearest = Infinity
    for (const candidateToken of candidateTokens) {
      nearest = Math.min(nearest, editDistance(queryToken, candidateToken))
    }
    tokenEditDistance += Number.isFinite(nearest) ? nearest : queryToken.length
  }

  const exact = normalizedName === normalizedQuery
  const nameContainsQuery = Boolean(
    normalizedQuery && normalizedName.includes(normalizedQuery)
  )
  const queryContainsName = Boolean(
    normalizedName && normalizedQuery.includes(normalizedName)
  )
  return {
    exact,
    substring_relation: nameContainsQuery
      ? 'candidate_contains_query'
      : queryContainsName
        ? 'query_contains_candidate'
        : null,
    shared_tokens: sharedTokens,
    missing_query_tokens: missingQueryTokens,
    token_edit_distance: tokenEditDistance,
    edit_distance: editDistance(normalizedQuery, normalizedName),
    length_delta: Math.abs(normalizedQuery.length - normalizedName.length)
  }
}

function compareRankedCandidates (left, right) {
  const l = left.rank
  const r = right.rank
  return (
    Number(!l.exact) - Number(!r.exact) ||
    Number(l.substring_relation === null) - Number(r.substring_relation === null) ||
    l.missing_query_tokens - r.missing_query_tokens ||
    r.shared_tokens.length - l.shared_tokens.length ||
    l.token_edit_distance - r.token_edit_distance ||
    l.edit_distance - r.edit_distance ||
    l.length_delta - r.length_delta ||
    left.name.localeCompare(right.name) ||
    left.kind.localeCompare(right.kind)
  )
}

// Registry tables are version-pinned by the Minecraft session. Reuse the
// canonical lexical index across queries, without caching world observations.
const registryRowsByTable = new WeakMap()

function registryRows (registry, kind) {
  const source = kind === 'item'
    ? registry.items
    : kind === 'block'
      ? registry.blocks
      : registry.entities
  const cacheable = source !== null && typeof source === 'object'
  if (cacheable) {
    const cached = registryRowsByTable.get(source)
    if (cached !== undefined) return cached
  }
  const byName = new Map()
  for (const value of Object.values(source || {})) {
    if (!value || typeof value.name !== 'string' || !value.name.trim()) continue
    const name = normalizeRegistryName(value.name)
    if (!name || byName.has(name)) continue
    byName.set(name, {
      kind,
      name,
      display_name: typeof value.displayName === 'string'
        ? value.displayName
        : null
    })
  }
  const rows = Object.freeze([...byName.values()])
  if (cacheable) registryRowsByTable.set(source, rows)
  return rows
}

function rankedRegistryRows (registry, query, kind) {
  return registryRows(registry, kind)
    .map(row => ({ ...row, rank: candidateRank(query, row.name) }))
    .sort(compareRankedCandidates)
}

function publicCandidate (row) {
  return {
    kind: row.kind,
    name: row.name,
    display_name: row.display_name,
    exact: row.rank.exact,
    substring_relation: row.rank.substring_relation,
    shared_tokens: row.rank.shared_tokens,
    missing_query_tokens: row.rank.missing_query_tokens,
    token_edit_distance: row.rank.token_edit_distance,
    edit_distance: row.rank.edit_distance
  }
}

function commonPrefixTokenCount (leftValue, rightValue) {
  const left = nameTokens(leftValue)
  const right = nameTokens(rightValue)
  const width = Math.min(left.length, right.length)
  let count = 0
  while (count < width && left[count] === right[count]) count += 1
  return count
}

function suggestRegistryKind (registry, queryValue, kind) {
  const query = normalizeRegistryName(queryValue)
  if (!query) throw new Error('REGISTRY_SEARCH_QUERY_REQUIRED')
  if (!['item', 'block', 'entity'].includes(kind)) {
    throw new Error('REGISTRY_SEARCH_KIND_INVALID')
  }

  const rows = registryRows(registry, kind)
  if (rows.length === 0) return []
  const ranked = subset => subset
    .map(row => ({ ...row, rank: candidateRank(query, row.name) }))
    .sort(compareRankedCandidates)

  // Exact canonical lookup and token-prefix resolution need only linear
  // comparisons, not a full fuzzy edit-distance evaluation for every
  // Minecraft item, block and entity. Calculate expensive distances only
  // for surviving ambiguity or when true fuzzy matching is unavoidable.
  const exact = rows.filter(row => row.name === query)
  if (exact.length > 0) return ranked(exact).map(publicCandidate)

  let longestPrefix = 0
  const prefixRows = []
  for (const row of rows) {
    const count = commonPrefixTokenCount(query, row.name)
    if (count <= 0) continue
    if (count > longestPrefix) {
      longestPrefix = count
      prefixRows.length = 0
    }
    if (count === longestPrefix) prefixRows.push(row)
  }
  if (longestPrefix > 0) return ranked(prefixRows).map(publicCandidate)

  // Preserve the original comparison semantics and canonical tie ordering,
  // but avoid ranking non-substring rows for a substring-grounded lookup.
  const substringRows = rows.filter(row => (
    row.name.includes(query) || query.includes(row.name)
  ))
  if (substringRows.length > 0) {
    const candidates = ranked(substringRows)
    const bestDistance = Math.min(...candidates.map(row => row.rank.edit_distance))
    return candidates
      .filter(row => row.rank.edit_distance === bestDistance)
      .map(publicCandidate)
  }

  const candidates = ranked(rows)
  const bestDistance = Math.min(...candidates.map(row => row.rank.edit_distance))
  return candidates
    .filter(row => row.rank.edit_distance === bestDistance)
    .map(publicCandidate)
}


// The registry is immutable for the lifetime of one Minecraft protocol
// generation. Bound result memoization to the registry object with WeakMap:
// no user/task/global state can leak between independently realized worlds.
// Store JSON bytes rather than public objects: a caller cannot mutate cached
// rankings, and a query replay gets the same canonical public knowledge.
const publicSearchByRegistry = new WeakMap()
const PUBLIC_SEARCH_CACHE_LIMIT = 128

function searchRegistry (registry, queryValue, limitValue) {
  const query = normalizeRegistryName(queryValue)
  if (!query) throw new Error('REGISTRY_SEARCH_QUERY_REQUIRED')
  const limit = Number(limitValue)
  if (!Number.isInteger(limit) || limit <= 0) {
    throw new Error('REGISTRY_SEARCH_LIMIT_INVALID')
  }

  const key = query + '\u0000' + limit
  const cacheable = registry !== null && typeof registry === 'object'
  let cache = cacheable ? publicSearchByRegistry.get(registry) : undefined
  if (cache !== undefined && cache.has(key)) {
    const encoded = cache.get(key)
    // Move the exact key to the newest end of a bounded LRU.
    cache.delete(key)
    cache.set(key, encoded)
    return JSON.parse(encoded)
  }

  const byKind = {
    item: rankedRegistryRows(registry, query, 'item'),
    block: rankedRegistryRows(registry, query, 'block'),
    entity: rankedRegistryRows(registry, query, 'entity')
  }
  const ranked = [...byKind.item, ...byKind.block, ...byKind.entity]
    .sort(compareRankedCandidates)
    .slice(0, limit)
    .map(publicCandidate)

  const result = {
    query,
    query_tokens: nameTokens(query),
    items: byKind.item.slice(0, limit).map(row => row.name),
    blocks: byKind.block.slice(0, limit).map(row => row.name),
    entities: byKind.entity.slice(0, limit).map(row => row.name),
    ranked_candidates: ranked,
    truth_class: 'declared',
    authoritative_for_current_world: false
  }
  if (cacheable) {
    if (cache === undefined) {
      cache = new Map()
      publicSearchByRegistry.set(registry, cache)
    }
    cache.set(key, JSON.stringify(result))
    if (cache.size > PUBLIC_SEARCH_CACHE_LIMIT) {
      cache.delete(cache.keys().next().value)
    }
  }
  return result
}

// Public reference knowledge comes only from the version-pinned vanilla
// minecraft-data registry. A server datapack may change recipes at runtime;
// this function MUST NOT query the live server, bot inventory or recipeBook.
// In particular, this must never expose hidden MirrorCraft changes.
function referenceCraftingRecipes (registry, itemValue, limitValue) {
  const item = normalizeRegistryName(itemValue)
  const limit = Number(limitValue)
  if (!item) throw new Error('REFERENCE_RECIPE_ITEM_REQUIRED')
  if (!Number.isInteger(limit) || limit < 1 || limit > 100) {
    throw new Error('REFERENCE_RECIPE_LIMIT_INVALID')
  }
  const minecraftVersion = registry.version && registry.version.minecraftVersion
  if (typeof minecraftVersion !== 'string' || !minecraftVersion) {
    throw new Error('REFERENCE_RECIPE_VERSION_UNAVAILABLE')
  }
  const itemRecord = (registry.itemsByName || {})[item]
  const raw = itemRecord ? (registry.recipes || {})[itemRecord.id] || [] : []
  const ingredient = id => {
    if (!Number.isInteger(id)) throw new Error('REFERENCE_RECIPE_INGREDIENT_INVALID')
    const record = (registry.items || {})[id]
    if (!record || !record.name) throw new Error('REFERENCE_RECIPE_INGREDIENT_UNKNOWN')
    return record.name
  }
  const recipes = raw.slice(0, limit).map(recipe => {
    const result = recipe.result || {}
    if (!Number.isInteger(result.count) || result.count < 1 ||
        result.id !== itemRecord.id) {
      throw new Error('REFERENCE_RECIPE_RESULT_INVALID')
    }
    if (Array.isArray(recipe.inShape)) {
      const shape = recipe.inShape.map(row => {
        if (!Array.isArray(row)) throw new Error('REFERENCE_RECIPE_SHAPE_INVALID')
        return row.map(id => id === null ? null : ingredient(id))
      })
      return {
        type: 'shaped',
        shape,
        result_count: result.count,
        requires_crafting_table: shape.length > 2 || shape.some(row => row.length > 2)
      }
    }
    if (Array.isArray(recipe.ingredients)) {
      return {
        type: 'shapeless',
        ingredients: recipe.ingredients.map(ingredient),
        result_count: result.count,
        requires_crafting_table: recipe.ingredients.length > 4
      }
    }
    throw new Error('REFERENCE_RECIPE_FORMAT_UNSUPPORTED')
  })
  return {
    item,
    item_known: Boolean(itemRecord),
    minecraft_version: minecraftVersion,
    source: 'version_pinned_vanilla_minecraft_data',
    truth_class: 'declared',
    authoritative_for_current_world: false,
    datapack_rules_included: false,
    recipe_kind: 'crafting_only',
    recipes_recorded: raw.length,
    recipes_truncated: raw.length > recipes.length,
    recipes
  }
}

module.exports = {
  candidateRank,
  compareRankedCandidates,
  editDistance,
  nameTokens,
  normalizeRegistryName,
  referenceCraftingRecipes,
  searchRegistry,
  suggestRegistryKind
}
