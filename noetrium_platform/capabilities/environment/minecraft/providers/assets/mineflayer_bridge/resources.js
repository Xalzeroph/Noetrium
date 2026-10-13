'use strict'

const { Vec3 } = require('vec3')
const minecraftData = require('minecraft-data')
const runtime = require('./runtime')
const worldFrontier = require('./world_frontier')
const worldGeometry = require('./world_geometry')
const { suggestRegistryKind, referenceCraftingRecipes } = require('./registry_search')
const { currentInventoryCounts, referenceRecipeDependencies, dropNamesForBlock } = require('./recipe_dependencies')

async function collectBlock (msg) {
  const activeBot = runtime.getBot()
  const action = {
    block: String(msg.block || msg.query || ''),
    count: Number(msg.count),
    max_distance: Number(msg.max_distance || 48),
    ...(msg.tool == null ? {} : { tool: String(msg.tool) }),
    ...(msg.position == null ? {} : { position: msg.position }),
    ...(msg.effect == null ? {} : { effect: String(msg.effect) })
  }
  if (!action.block || !Number.isInteger(action.count) || action.count <= 0) {
    return runtime.rejected('collect_block', action, 'INVALID_COLLECTION_REQUEST')
  }
  if (!Number.isFinite(action.max_distance) || action.max_distance <= 0) {
    return runtime.rejected('collect_block', action, 'INVALID_COLLECTION_DISTANCE')
  }
  if (action.tool != null && !action.tool.trim()) {
    return runtime.rejected('collect_block', action, 'INVALID_COLLECTION_TOOL')
  }
  const removalOnly = action.effect === 'remove'
  if ((action.effect != null && !['remove', 'collect'].includes(action.effect)) ||
      (removalOnly && (action.position == null || action.count !== 1 || action.tool != null))) {
    return runtime.rejected('collect_block', action, 'INVALID_EXACT_REMOVAL_REQUEST')
  }
  // Validate here as well as at the Python contract boundary: an exact
  // target must never silently become a general nearest-block search.
  let exactTarget = null
  if (action.position != null) {
    const p = action.position
    if (!p || !['x', 'y', 'z'].every(
      axis => Number.isSafeInteger(p[axis])
    ) || action.count !== 1) {
      return runtime.rejected('collect_block', action, 'INVALID_EXACT_BLOCK_TARGET')
    }
    exactTarget = new Vec3(p.x, p.y, p.z)
    if (activeBot.entity.position.distanceTo(exactTarget) > action.max_distance) {
      return runtime.rejected('collect_block', action, 'EXACT_TARGET_OUT_OF_RANGE', {
        target: runtime.vec(exactTarget),
        searched_max_distance: action.max_distance,
        physical_effect: false
      })
    }
    const observed = activeBot.blockAt(exactTarget)
    if (!observed) {
      return runtime.rejected('collect_block', action, 'EXACT_TARGET_NOT_OBSERVED', {
        target: runtime.vec(exactTarget), loaded_world_only: true
      })
    }
    // Matching this observed target against drops uses exactly the same
    // registry and effect validation as the normal semantic collection.
  }
  const blockRegistry = activeBot.registry.blocksByName
  const itemRegistry = activeBot.registry.itemsByName
  const blockRegistryReady = blockRegistry && Object.keys(blockRegistry).length > 0
  const itemRegistryReady = itemRegistry && Object.keys(itemRegistry).length > 0
  const blockType = blockRegistryReady ? blockRegistry[action.block] : null
  const itemType = itemRegistryReady ? itemRegistry[action.block] : null
  if ((blockRegistryReady || itemRegistryReady) && !blockType && !itemType) {
    const entityType = activeBot.registry.entitiesByName && activeBot.registry.entitiesByName[action.block]
    return runtime.rejected(
      'collect_block',
      action,
      entityType ? 'TARGET_IS_ENTITY_NOT_BLOCK_OR_DROP' : 'UNKNOWN_BLOCK_OR_DROP',
      {
        semantic_domain: 'minecraft.block_or_block_drop_name',
        target_classification: entityType ? 'entity' : 'unknown',
        canonical_block_candidates: entityType
          ? []
          : suggestRegistryKind(activeBot.registry, action.block, 'block'),
        canonical_item_candidates: entityType
          ? []
          : suggestRegistryKind(activeBot.registry, action.block, 'item'),
        resolution: { status: entityType ? 'wrong_semantic_domain' : 'candidates_available' },
        rejected_argument_constraints: [{
          argument_path: ['block'],
          rejected_value: action.block,
          validity: { while_provider_instance: true }
        }]
      }
    )
  }
  const requestedTool = action.tool == null
    ? null
    : runtime.findInventoryItem(action.tool)
  if (action.tool != null && !requestedTool) {
    return runtime.rejected('collect_block', action, 'REQUESTED_TOOL_NOT_AVAILABLE', {
      requested_tool: action.tool,
      inventory_contains_requested_tool: false,
      rejected_argument_constraints: [{
        argument_path: ['tool'],
        rejected_value: action.tool,
        validity: { until_state_change: [['inventory']] },
        repair: { operation: 'omit_argument', argument_path: ['tool'] }
      }]
    })
  }
  await runtime.ensureMovements()
  if (!removalOnly && requestedTool == null &&
      (!activeBot.tool || typeof activeBot.tool.equipForBlock !== 'function')) {
    return runtime.rejected('collect_block', action, 'MINEFLAYER_TOOL_UNAVAILABLE')
  }
  if (!activeBot.pathfinder || !activeBot.pathfinder.movements ||
      typeof activeBot.pathfinder.movements.safeToBreak !== 'function') {
    return runtime.rejected('collect_block', action, 'MINEFLAYER_PATHFINDER_SAFETY_UNAVAILABLE')
  }

  const matchesRequestedResource = block => block && (
    block.name === action.block ||
    (!removalOnly && dropNamesForBlock(activeBot, block).includes(action.block))
  )
  const safeToBreak = block => runtime.safeToHarvestBlock(block)
  const keyForPosition = position => (
    position &&
    Number.isFinite(Number(position.x)) &&
    Number.isFinite(Number(position.y)) &&
    Number.isFinite(Number(position.z))
      ? String(position.x) + ',' + String(position.y) + ',' + String(position.z)
      : null
  )
  const distanceToBot = block => activeBot.entity.position.distanceTo(block.position)
  const acceptableToolNames = block => Object.keys((block && block.harvestTools) || {})
    .map(value => Number(value))
    .filter(value => Number.isFinite(value))
    .map(id => activeBot.registry.items && activeBot.registry.items[id])
    .filter(Boolean)
    .map(item => item.name)
    .filter((name, index, values) => values.indexOf(name) === index)
    .sort()
  const isNoPath = error => Boolean(error && (
    String(error.name || '') === 'NoPath' || String(error.code || '') === 'NoPath'
  ))

  // This is one explicit, bounded semantic collection intent. Resolve it
  // as a sequence of physically observed single-block effects, retaining
  // their individual evidence within one action ledger identity. Never mine
  // ahead when the preceding block produced no observable inventory progress.
  // The coordinator still owns exact action-id reconciliation across crashes.
  const before = runtime.inventoryMap()
  const startingPosition = activeBot.entity.position.clone()
  const startingHeldItem = activeBot.heldItem
    ? { name: activeBot.heldItem.name, type: activeBot.heldItem.type }
    : null
  const expectedItems = new Set()
  const observedTargets = new Map()
  const unreachable = new Set()
  const completed = new Set()
  const errors = []
  const collectionSteps = []
  let terminalFailure = null
  let exhausted = false
  let acceptableTools = []
  let ownedAcceptableTools = []
  let segmentsAttempted = 0
  const attempted = new Set()

  const remember = block => {
    const key = keyForPosition(block && block.position)
    if (key !== null && !observedTargets.has(key)) {
      observedTargets.set(key, {
        name: block.name,
        position: block.position.clone ? block.position.clone() : block.position
      })
    }
    for (const name of dropNamesForBlock(activeBot, block)) expectedItems.add(name)
  }

  let observedUnsafe = null
  const admissibleWorldCandidate = block => {
    if (!block || !block.position) return false
    if (!safeToBreak(block)) {
      // Mineflayer's position-resolved useExtraInfo callback already proves
      // this candidate was observed in the requested loaded-world scan.
      // Retain one physical witness, avoiding an otherwise redundant full
      // search just to decide whether the rejection was safety-related.
      if (observedUnsafe === null) observedUnsafe = block
      return false
    }
    const key = keyForPosition(block.position)
    return key !== null && !unreachable.has(key) && !attempted.has(key)
  }

  const progress = () => {
    const after = runtime.inventoryMap()
    const inventoryDelta = runtime.inventoryDelta(before, after)
    const collectedDelta = Object.fromEntries(
      Object.entries(inventoryDelta).filter(([name, count]) => expectedItems.has(name) && count > 0)
    )
    const collectedCount = Object.values(collectedDelta)
      .reduce((sum, count) => sum + Number(count), 0)
    return { after, inventoryDelta, collectedDelta, collectedCount }
  }

  // Exclude only targets that have been physically proven unreachable. Search
  // breadth is derived from the remaining requested effect count: equivalent
  // physical targets share one native multi-goal reachability proof instead of
  // paying one full pathfinder search for each geometrically-near dead end.
  while (!terminalFailure && !exhausted) {
    // The enclosing Scope is the outer deadline authority.  Each physical
    // collection segment also receives one host-declared provider liveness
    // window, preventing one navigation/pickup primitive from consuming the
    // entire multiplied composite-action budget.
    if (runtime.currentActionCancellationScope()) runtime.actionRemainingMs()
    const providerWindow = runtime.createActionProviderWindow(msg)
    const confirmedBeforeStep = progress().collectedCount
    observedUnsafe = null
    const positions = exactTarget ? (
      unreachable.has(keyForPosition(exactTarget))
        ? []
        : (() => {
            const exactBlock = activeBot.blockAt(exactTarget)
            return exactBlock && matchesRequestedResource(exactBlock)
              ? [exactTarget] : []
          })()
    ) : activeBot.findBlocks({
      // Mineflayer invokes `matching` on section-palette blocks whose world
      // position is intentionally null. Keep this predicate position-free so
      // palette pruning remains valid and O(palette) per section. World-space
      // safety/unreachable checks belong to `useExtraInfo`, which receives the
      // fully materialized block from blockAt(point, true).
      matching: matchesRequestedResource,
      useExtraInfo: admissibleWorldCandidate,
      maxDistance: action.max_distance,
      count: Math.max(1, action.count - confirmedBeforeStep)
    })
    if (!Array.isArray(positions) || positions.length === 0) {
      if (exactTarget && !unreachable.has(keyForPosition(exactTarget))) {
        const seen = activeBot.blockAt(exactTarget)
        return runtime.rejected('collect_block', action, 'EXACT_TARGET_CHANGED', {
          target: runtime.vec(exactTarget),
          observed_block: seen ? seen.name : null,
          requested_resource: action.block,
          loaded_world_only: true
        })
      }
      if (observedUnsafe !== null) {
        remember(observedUnsafe)
        if (completed.size > 0 || progress().collectedCount > 0) {
          terminalFailure = { name: 'UnsafeBlockBreak', message: 'UNSAFE_BLOCK_BREAK' }
          exhausted = true
          break
        }
        return runtime.rejected('collect_block', action, 'UNSAFE_BLOCK_BREAK', {
          requested_count: action.count,
          target_count: 1,
          unsafe: [{ name: observedUnsafe.name, position: runtime.vec(observedUnsafe.position) }]
        })
      }
      exhausted = true
      break
    }
    let candidatePosition = positions[0]
    let preflightInventoryItems = null
    if (!exactTarget && positions.length > 1) {
      let directlyReachable = null
      let missingToolProved = !removalOnly && requestedTool == null
      const materializedToolBlocked = []
      const acceptableToolIds = new Set()
      for (const position of positions) {
        const block = activeBot.blockAt(position)
        if (
          block && matchesRequestedResource(block) &&
          typeof activeBot.canDigBlock === 'function' &&
          activeBot.canDigBlock(block) === true
        ) {
          directlyReachable = position
          missingToolProved = false
          break
        }
        if (!missingToolProved) continue
        if (!block || !matchesRequestedResource(block) || !safeToBreak(block)) {
          missingToolProved = false
          continue
        }
        const toolIds = Object.keys(block.harvestTools || {})
          .map(value => Number(value))
          .filter(value => Number.isFinite(value))
        if (toolIds.length === 0) {
          missingToolProved = false
          continue
        }
        if (preflightInventoryItems === null) {
          preflightInventoryItems = activeBot.inventory.items()
        }
        if (preflightInventoryItems.some(item => toolIds.includes(Number(item.type)))) {
          missingToolProved = false
          continue
        }
        materializedToolBlocked.push(block)
        for (const id of toolIds) acceptableToolIds.add(id)
      }
      if (
        directlyReachable === null && missingToolProved &&
        materializedToolBlocked.length === positions.length
      ) {
        for (const block of materializedToolBlocked) remember(block)
        acceptableTools = [...acceptableToolIds]
          .map(id => activeBot.registry.items && activeBot.registry.items[id])
          .filter(Boolean)
          .map(item => item.name)
          .filter((name, index, values) => values.indexOf(name) === index)
          .sort()
        ownedAcceptableTools = []
        terminalFailure = {
          name: 'NoItem',
          code: 'NO_HARVEST_TOOL_IN_INVENTORY',
          message: 'No harvest-capable tool is present in inventory'
        }
        errors.push({
          phase: 'harvest-tool-preflight',
          code: terminalFailure.code,
          candidate_count: materializedToolBlocked.length
        })
        break
      }
      if (directlyReachable) {
        candidatePosition = directlyReachable
      } else {
        const explicitTimeout = Number(msg._action_timeout_ms)
        const multiGoalAuthorized = Boolean(runtime.currentActionCancellationScope()) || (
          Number.isFinite(explicitTimeout) && explicitTimeout > 0
        )
        if (multiGoalAuthorized) {
          try {
            const navigation = await runtime.gotoAnyBlockVicinity(
              positions, providerWindow.remainingMs()
            )
            candidatePosition = new Vec3(
              Number(navigation.target.x),
              Number(navigation.target.y),
              Number(navigation.target.z)
            )
          } catch (error) {
            if (isNoPath(error)) {
              for (const position of positions) {
                const key = keyForPosition(position)
                if (key !== null) unreachable.add(key)
                const block = activeBot.blockAt(position)
                if (block && matchesRequestedResource(block)) remember(block)
              }
              errors.push({
                phase: 'batched-block-reachability',
                attempt_mode: 'native-multi-goal',
                candidate_count: positions.length,
                ...runtime.errorEvidence(error)
              })
              continue
            }
            const reachedAfterMovement = positions.find(position => {
              const block = activeBot.blockAt(position)
              return Boolean(
                block && matchesRequestedResource(block) &&
                error && error.name === 'Timeout' &&
                String(error.message || '').includes('decide path to goal') &&
                typeof activeBot.canDigBlock === 'function' &&
                activeBot.canDigBlock(block) === true
              )
            })
            if (reachedAfterMovement) {
              candidatePosition = reachedAfterMovement
              errors.push({
                phase: 'native-navigation-timeout-after-reaching-dig-range',
                attempt_mode: 'native-multi-goal',
                candidate_count: positions.length,
                target: runtime.vec(candidatePosition),
                ...runtime.errorEvidence(error)
              })
            } else if (String(error && error.code || '') === 'PATHFINDER_MULTI_TARGET_UNRESOLVED') {
              // The joint goal could not map its terminal node back to a
              // candidate. No target has been proven unreachable, so retain
              // the original single-target path as a semantics-preserving
              // fallback within this same bounded action.
              errors.push({
                phase: 'batched-block-target-unresolved',
                attempt_mode: 'native-multi-goal-fallback-single',
                candidate_count: positions.length,
                ...runtime.errorEvidence(error)
              })
            } else {
              throw error
            }
          }
        }
      }
    }
    const candidate = activeBot.blockAt(candidatePosition)
    if (!candidate || !matchesRequestedResource(candidate)) {
      exhausted = true
      break
    }
    if (!safeToBreak(candidate)) {
      remember(candidate)
      if (completed.size > 0 || progress().collectedCount > 0) {
        terminalFailure = { name: 'UnsafeBlockBreak', message: 'UNSAFE_BLOCK_BREAK' }
        break
      }
      return runtime.rejected('collect_block', action, 'UNSAFE_BLOCK_BREAK', {
        requested_count: action.count,
        target_count: 1,
        unsafe: [{ name: candidate.name, position: runtime.vec(candidate.position) }]
      })
    }
    const candidateKey = keyForPosition(candidate.position)
    if (candidateKey === null) {
      exhausted = true
      break
    }
    // Mineflayer's real findBlocks honors useExtraInfo, but retain a second
    // materialized-world guard so custom worlds/test doubles cannot re-offer
    // the same proven-unreachable coordinate forever.  Recovery is monotone:
    // every NoPath either exposes a new target or exhausts this bounded action.
    if (unreachable.has(candidateKey) || completed.has(candidateKey)) {
      exhausted = true
      break
    }
    remember(candidate)
    attempted.add(candidateKey)
    segmentsAttempted++
    acceptableTools = acceptableToolNames(candidate)
    const inventoryToolNames = new Set(
      (preflightInventoryItems || activeBot.inventory.items())
        .map(item => String(item.name))
    )
    ownedAcceptableTools = acceptableTools.filter(name => inventoryToolNames.has(name))
    if (!removalOnly && requestedTool == null &&
        acceptableTools.length > 0 && ownedAcceptableTools.length === 0) {
      terminalFailure = {
        name: 'NoItem',
        code: 'NO_HARVEST_TOOL_IN_INVENTORY',
        message: 'No harvest-capable tool is present in inventory'
      }
      errors.push({
        phase: 'harvest-tool-preflight',
        code: terminalFailure.code,
        target: runtime.vec(candidate.position)
      })
      break
    }
    let dropWatcher = null
    let inventoryWatcher = null
    try {
      if (!removalOnly && requestedTool != null) {
        if (typeof candidate.canHarvest !== 'function') {
          return runtime.rejected(
            'collect_block', action, 'REQUESTED_TOOL_HARVEST_SEMANTICS_UNAVAILABLE', {
              requested_tool: action.tool,
              acceptable_tools: acceptableTools,
              target: runtime.vec(candidate.position)
            }
          )
        }
        if (!candidate.canHarvest(requestedTool.type)) {
          return runtime.rejected(
            'collect_block', action, 'REQUESTED_TOOL_CANNOT_HARVEST', {
              requested_tool: action.tool,
              acceptable_tools: acceptableTools,
              owned_acceptable_tools: ownedAcceptableTools,
              target: runtime.vec(candidate.position),
              source_block: candidate.name,
              rejected_argument_constraints: [{
                argument_path: ['tool'],
                rejected_value: action.tool,
                when_arguments: [{ argument_path: ['block'], value: action.block }],
                validity: { until_state_change: [['inventory']] }
              }]
            }
          )
        }
        await activeBot.equip(requestedTool, 'hand')
      } else if (!removalOnly) {
        await activeBot.tool.equipForBlock(candidate, {
          requireHarvest: true,
          getFromChest: false,
          maxTools: 1
        })
      }
      const heldType = activeBot.heldItem ? activeBot.heldItem.type : null
      if (
        !removalOnly &&
        typeof candidate.canHarvest === 'function' &&
        !candidate.canHarvest(heldType)
      ) {
        const error = new Error('No harvest-capable tool is equipped')
        error.name = 'NoItem'
        throw error
      }

      // Mineflayer's own reach/diggability oracle already proves when a
      // block can be dug from the current position. Searching a path to a
      // goal already satisfied is both unnecessary and may time out under
      // dense terrain. Never bypass physical reach or harvest safety.
      const reachableNow = (
        typeof activeBot.canDigBlock === 'function'
        && activeBot.canDigBlock(candidate) === true
      )
      if (!reachableNow) {
        try {
          await runtime.gotoBlockInteraction(candidate.position, providerWindow.remainingMs())
        } catch (error) {
          // The native search may report planning timeout *after* the bot
          // physically reached digging distance. Recheck Mineflayer's
          // physical dig oracle before treating that navigation status as
          // failure. A cancelled action or unavailable target still fails.
          const timedOutInNativePlanner = (
            error && error.name === 'Timeout' &&
            String(error.message || '').includes('decide path to goal')
          )
          const reachedAfterMovement = (
            timedOutInNativePlanner &&
            typeof activeBot.canDigBlock === 'function' &&
            activeBot.canDigBlock(candidate) === true
          )
          if (!reachedAfterMovement) throw error
          errors.push({
            phase: 'native-navigation-timeout-after-reaching-dig-range',
            target: runtime.vec(candidate.position),
            ...runtime.errorEvidence(error)
          })
        }
      }
      const liveBlock = activeBot.blockAt(candidate.position)
      if (!liveBlock || !matchesRequestedResource(liveBlock)) {
        unreachable.add(candidateKey)
        continue
      }
      if (!safeToBreak(liveBlock)) {
        if (completed.size > 0 || progress().collectedCount > 0) {
          terminalFailure = { name: 'UnsafeBlockBreak', message: 'UNSAFE_BLOCK_BREAK' }
          break
        }
        return runtime.rejected('collect_block', action, 'UNSAFE_BLOCK_BREAK', {
          requested_count: action.count,
          target_count: 1,
          unsafe: [{ name: liveBlock.name, position: runtime.vec(liveBlock.position) }]
        })
      }

      const expectedDropNames = dropNamesForBlock(activeBot, liveBlock)
      // Every segment must prove *its own* pickup; using the initial action
      // inventory as a per-segment threshold falsely confirms the second log
      // with the first log's inventory increase.
      const beforeSegment = runtime.inventoryMap()
      // Observe the actual post-break drop, not only vanilla drop names.
      // Datapacks may alter outputs; selection remains bounded to newly
      // spawned item entities near the exact mined block. Actual inventory
      // delta, rather than a guessed recipe, is the physical evidence.
      if (!removalOnly) {
        dropWatcher = runtime.captureItemDropNear(
          liveBlock.position,
          null,
          1.5
        )
        if (expectedDropNames.length > 0) {
          inventoryWatcher = runtime.captureInventoryIncrease(
            expectedDropNames,
            beforeSegment
          )
        }
      }
      await activeBot.dig(liveBlock)
      completed.add(candidateKey)

      // Mineflayer dig() resolves only after the server confirms the target
      // block update. If the inventory already changed, no additional wait is
      // necessary. Otherwise wait for the actual matching drop entity rather
      // than sleeping an arbitrary number of physics ticks.
      let segmentProgress = progress()
      if (!removalOnly && segmentProgress.collectedCount <= confirmedBeforeStep) {
        let pickup = dropWatcher.pickupTarget()
        let inventoryProof = inventoryWatcher ? inventoryWatcher.current() : null
        if (!pickup && !inventoryProof) {
          const evidenceWaiters = [
            ...(inventoryWatcher
              ? [inventoryWatcher.promise.then(proof => ({ kind: 'inventory', proof }))]
              : []),
            dropWatcher.promise.then(entity => ({ kind: 'drop', entity }))
          ]
          if (runtime.currentActionCancellationScope()) {
            evidenceWaiters.push(
              runtime.waitForPhysicsTicks(1, providerWindow.remainingMs())
                .then(() => ({ kind: 'observation_barrier' }))
            )
          }
          const evidence = await Promise.race(evidenceWaiters)
          if (evidence.kind === 'inventory') inventoryProof = evidence.proof
          else if (evidence.kind === 'drop') pickup = evidence.entity
          else {
            // entitySpawn precedes itemDrop metadata in Mineflayer. The physics
            // boundary may race after the spawn but before metadata/inventory.
            // Re-read the already registered watchers before declaring the
            // pickup unobserved; this adds no wait and preserves spatial
            // correlation to the exact dug block.
            inventoryProof = inventoryWatcher ? inventoryWatcher.current() : null
            pickup = dropWatcher.pickupTarget()
            if (!inventoryProof && !pickup) {
              errors.push({
                phase: 'post-dig-pickup-observation',
                attempt_mode: 'next-provider-physics-boundary',
                target: runtime.vec(liveBlock.position),
                name: 'PickupNotObserved',
                message: 'PICKUP_NOT_OBSERVED_AT_PHYSICS_BOUNDARY'
              })
            }
          }
        }
        if (inventoryProof) {
          segmentProgress = progress()
        } else if (pickup && pickup.isValid !== false) {
          const observedDropName = runtime.droppedItemName(pickup)
          const beforeDropCount = observedDropName
            ? Number(beforeSegment[observedDropName] || 0)
            : null
          if (!dropWatcher.hasOwnCollection()) {
            const ownCollection = runtime.waitForOwnCollection(
              pickup, providerWindow.remainingMs()
            )
            try {
              await runtime.gotoEntity(pickup, 0, providerWindow.remainingMs())
            } catch (_) {}
            await ownCollection
          }
          if (observedDropName && beforeDropCount != null) {
            await runtime.waitForInventoryIncrease(
              observedDropName,
              beforeDropCount,
              providerWindow.remainingMs()
            )
          }
          segmentProgress = progress()
        }
      }
    } catch (error) {
      const evidence = runtime.errorEvidence(error)
      errors.push({
        phase: 'direct-single-block-collection',
        attempt_mode: 'single-target-segment',
        target: runtime.vec(candidate.position),
        ...evidence
      })
      if (isNoPath(error)) {
        unreachable.add(candidateKey)
        continue
      }
      terminalFailure = evidence
      break
    } finally {
      if (inventoryWatcher) inventoryWatcher.cancel()
      if (dropWatcher) dropWatcher.cancel()
    }
    const segment = progress()
    const blockAfter = activeBot.blockAt(candidate.position)
    const blockRemoved = Boolean(
      blockAfter && blockAfter.name !== candidate.name
    )
    collectionSteps.push({
      target: runtime.vec(candidate.position),
      source_block: candidate.name,
      block_confirmed_removed: blockRemoved,
      cumulative_collected_count: segment.collectedCount
    })
    // Each next block remains the exact same requested resource. Failure to
    // observe either a corresponding inventory gain or physical block removal
    // closes this action instead of multiplying uncertain world effects.
    if (removalOnly) break
    if (segment.collectedCount >= action.count) break
    if (!blockRemoved || segment.collectedCount <= confirmedBeforeStep) break
  }

  const current = progress()
  const broken = [...observedTargets.values()]
    .map(block => {
      const currentBlock = activeBot.blockAt(block.position)
      return currentBlock && currentBlock.name !== block.name
        ? { name: block.name, position: runtime.vec(block.position) }
        : null
    })
    .filter(Boolean)
  const movementDistance = activeBot.entity.position.distanceTo(startingPosition)
  // A requested item may be craftable even though no matching physical block
  // exists in the currently loaded world. Mineflayer's versioned recipe
  // catalog is declared item knowledge, not an observed material supply.
  // Expose only a read-only reference query when the native catalog has
  // a possible recipe. Recipe existence does NOT imply physically held
  // ingredients, an available workstation, or an executable craft.
  // Never issue a mutating recovery action from declared catalog truth.
  let recipeRecovery = null
  let recipeCandidateEvidence = null
  if (
    exhausted && observedTargets.size === 0 && itemType &&
    typeof activeBot.recipesAll === 'function'
  ) {
    try {
      const declaredRecipes = activeBot.recipesAll(itemType.id, null, null)
      if (Array.isArray(declaredRecipes) && declaredRecipes.length > 0) {
        recipeRecovery = {
          action_type: 'recipe_dependencies',
          arguments: { item: action.block, count: action.count }
        }
        recipeCandidateEvidence = {
          source: 'minecraft.native_recipe_catalog',
          catalog_recipe_count: declaredRecipes.length,
          prerequisites_verified: false,
          recipe_requires_station: null
        }
      }
    } catch (_) {
      // An unavailable recipe catalog cannot authorize a recovery hint.
    }
  }
  const currentHeldItem = activeBot.heldItem
    ? { name: activeBot.heldItem.name, type: activeBot.heldItem.type }
    : null
  const equipmentChanged = JSON.stringify(startingHeldItem) !== JSON.stringify(currentHeldItem)
  const details = {
    native_provider: 'mineflayer-direct-dig',
    position_before: runtime.vec(startingPosition),
    position_after: runtime.vec(activeBot.entity.position),
    moved: movementDistance,
    held_before: startingHeldItem,
    held_after: currentHeldItem,
    equipment_changed: equipmentChanged,
    candidate_strategy: 'verified-sequential-collection',
    requested_count: action.count,
    requested_tool: action.tool || null,
    tool_constraint_verified: action.tool == null
      ? null
      : Boolean(currentHeldItem && currentHeldItem.name === action.tool),
    ...(removalOnly ? { removal_effect: 'exact_block_world_state',
      removed_count: collectionSteps.filter(step => step.block_confirmed_removed).length } : {}),
    collection_steps: collectionSteps,
    segment_target_count: observedTargets.size,
    confirmed_dig_count: completed.size,
    target_count: observedTargets.size,
    target_positions: [...observedTargets.values()].map(block => runtime.vec(block.position)),
    requested_resource: action.block,
    source_blocks: [...new Set([...observedTargets.values()].map(block => block.name))],
    expected_items: [...expectedItems],
    unreachable_targets: [...unreachable],
    candidate_frontier_exhausted: exhausted,
    broken,
    errors,
    inventory_before: before,
    inventory_after: current.after,
    inventory_delta: current.inventoryDelta,
    collected_delta: current.collectedDelta,
    collected_count: current.collectedCount,
    acceptable_tools: acceptableTools,
    ...(recipeRecovery ? {
      recovery: recipeRecovery,
      alternative_production_evidence: recipeCandidateEvidence
    } : {}),
    world_frontier: worldFrontier.observeWorldFrontiers(activeBot, action.max_distance)
  }
  // Count is a quantity of verified received resource items, not a count
  // of mined source blocks. One harvested block may physically yield several
  // items (for example, clay). Still require a separately observed block
  // removal so unrelated inventory gains cannot satisfy collection.
  if (removalOnly && broken.length === 1) {
    return runtime.applied('collect_block', action, 'BLOCK_REMOVED', details)
  }
  if (broken.length > 0 && current.collectedCount >= action.count) {
    return runtime.applied('collect_block', action, 'BLOCKS_COLLECTED', details)
  }
  if (terminalFailure && terminalFailure.name === 'NoItem') {
    const evidence = {
      ...details,
      semantic_domain: 'minecraft.block_or_block_drop_name',
      prerequisites: {
        acceptable_tools: acceptableTools,
        owned_acceptable_tools: ownedAcceptableTools,
        held_tool: activeBot.heldItem ? String(activeBot.heldItem.name) : null,
        retry_requires_state_change: ownedAcceptableTools.length === 0 ? ['inventory'] : []
      },
      ...(ownedAcceptableTools.length === 0 ? {
        rejected_argument_constraints: [{
          argument_path: ['block'],
          rejected_value: action.block,
          validity: { until_state_change: [['inventory']] }
        }]
      } : {})
    }
    return movementDistance > 0 || equipmentChanged
      ? runtime.partial('collect_block', action, 'HARVEST_TOOL_REQUIRED', evidence, 'applied')
      : runtime.rejected('collect_block', action, 'HARVEST_TOOL_REQUIRED', evidence)
  }
  // The requested resource is only one dimension of physical truth.
  // Pathfinder displacement and equipping tools are confirmed world effects
  // even when a target proved unreachable or zero items were collected.
  if (broken.length > 0 || current.collectedCount > 0 ||
      movementDistance > 0 || equipmentChanged) {
    return runtime.partial('collect_block', action, removalOnly
      ? 'BLOCK_REMOVAL_EFFECT_UNCONFIRMED' : 'COLLECTION_SEGMENT_APPLIED', details, 'applied')
  }
  const exhaustedLoadedFrontier = (
    !terminalFailure && unreachable.size === 0 && exhausted === true
  )
  const explicitSearchBound = Object.prototype.hasOwnProperty.call(msg, 'max_distance')
  const rejectionDetails = exhaustedLoadedFrontier && explicitSearchBound
    ? {
        ...details,
        prerequisites: {
          ...(details.prerequisites || {}),
          retry_requires_state_change: ['position', 'nearby_blocks']
        },
        rejected_argument_constraints: [{
          argument_path: ['max_distance'],
          rejected_value: action.max_distance,
          when_arguments: [{ argument_path: ['block'], value: action.block }],
          validity: {
            until_state_change: [['position'], ['nearby_blocks']],
            while_provider_instance: true
          }
        }]
      }
    : details
  return runtime.rejected(
    'collect_block',
    action,
    terminalFailure || unreachable.size > 0 ? 'COLLECTION_FAILED' : 'BLOCK_NOT_COLLECTED',
    rejectionDetails,
    terminalFailure || unreachable.size > 0 ? 'not_applied' : 'rejected'
  )
}
async function excavateRegion (msg) {
  const activeBot = runtime.getBot()
  const toPoint = value => new Vec3(
    Number(value && value.x), Number(value && value.y), Number(value && value.z)
  )
  const a = toPoint(msg.corner_a)
  const b = toPoint(msg.corner_b)
  const action = {
    corner_a: runtime.vec(a),
    corner_b: runtime.vec(b),
    max_blocks: Number(msg.max_blocks || 16),
    max_distance: Number(msg.max_distance || 32)
  }
  if (![a, b].every(point => [point.x, point.y, point.z].every(Number.isSafeInteger)) ||
      !Number.isInteger(action.max_blocks) || action.max_blocks < 1 || action.max_blocks > 32 ||
      !Number.isFinite(action.max_distance) || action.max_distance < 4 || action.max_distance > 64) {
    return runtime.rejected('excavate_region', action, 'INVALID_EXCAVATION_REQUEST')
  }
  const min = new Vec3(
    Math.min(a.x, b.x), Math.min(a.y, b.y), Math.min(a.z, b.z)
  )
  const max = new Vec3(
    Math.max(a.x, b.x), Math.max(a.y, b.y), Math.max(a.z, b.z)
  )
  const extents = [max.x - min.x + 1, max.y - min.y + 1, max.z - min.z + 1]
  const volume = extents[0] * extents[1] * extents[2]
  if (extents.some(value => value > 16) || volume > 128) {
    return runtime.rejected('excavate_region', action, 'EXCAVATION_REGION_TOO_LARGE', {
      extents, volume, max_volume: 128
    }, 'not_applied')
  }
  const origin = activeBot.entity.position.clone()
  const corners = []
  for (const x of [min.x, max.x]) for (const y of [min.y, max.y]) for (const z of [min.z, max.z]) {
    corners.push(new Vec3(x, y, z))
  }
  const farthest = Math.max(...corners.map(point => origin.distanceTo(point)))
  if (farthest > action.max_distance) {
    return runtime.rejected('excavate_region', action, 'EXCAVATION_REGION_OUT_OF_RANGE', {
      farthest_corner_distance: farthest,
      max_distance: action.max_distance
    }, 'not_applied')
  }

  await runtime.ensureMovements()
  const candidates = []
  const unobserved = []
  const unsafe = []
  for (let x = min.x; x <= max.x; x += 1) {
    for (let y = min.y; y <= max.y; y += 1) {
      for (let z = min.z; z <= max.z; z += 1) {
        const point = new Vec3(x, y, z)
        const block = activeBot.blockAt(point)
        if (!block) {
          unobserved.push(runtime.vec(point))
          continue
        }
        if (['air', 'cave_air', 'void_air'].includes(String(block.name))) continue
        if (!runtime.safeToHarvestBlock(block)) {
          unsafe.push({ name: block.name, position: runtime.vec(point) })
          continue
        }
        candidates.push({ name: block.name, position: point })
      }
    }
  }
  if (unobserved.length > 0) {
    return runtime.rejected('excavate_region', action, 'REGION_NOT_FULLY_OBSERVED', {
      region: { min: runtime.vec(min), max: runtime.vec(max), volume },
      unobserved_count: unobserved.length,
      first_unobserved: unobserved[0],
      loaded_world_only: true
    }, 'not_applied')
  }
  if (unsafe.length > 0) {
    return runtime.rejected('excavate_region', action, 'UNSAFE_EXCAVATION_REGION', {
      region: { min: runtime.vec(min), max: runtime.vec(max), volume },
      unsafe_count: unsafe.length,
      first_unsafe: unsafe[0]
    }, 'not_applied')
  }
  candidates.sort((left, right) => {
    const dl = origin.distanceSquared(left.position)
    const dr = origin.distanceSquared(right.position)
    return dl - dr || left.position.y - right.position.y ||
      left.position.x - right.position.x || left.position.z - right.position.z
  })
  if (candidates.length === 0) {
    return runtime.applied('excavate_region', action, 'REGION_ALREADY_CLEAR', {
      region: { min: runtime.vec(min), max: runtime.vec(max), volume },
      removed_count: 0,
      remaining_count: 0,
      child_effects_attempted: 0
    })
  }

  const removed = []
  const childResults = []
  const selected = candidates.slice(0, action.max_blocks)
  for (let index = 0; index < selected.length; index += 1) {
    if (runtime.currentActionCancellationScope()) runtime.actionRemainingMs()
    const candidate = selected[index]
    const childArguments = {
      block: candidate.name,
      count: 1,
      max_distance: action.max_distance,
      position: runtime.vec(candidate.position),
      effect: 'remove'
    }
    const result = await runtime.runSkillChildEffect(
      index, 'collect_block', childArguments,
      () => collectBlock(childArguments)
    )
    childResults.push({
      index,
      position: runtime.vec(candidate.position),
      source_block: candidate.name,
      status: result.outcome.status,
      code: result.outcome.code,
      effect_disposition: result.effect_disposition,
      child_effect_ref: result.child_effect_ref || null
    })
    if (result.outcome.code === 'BLOCK_REMOVED' && result.effect_disposition === 'applied') {
      removed.push(runtime.vec(candidate.position))
      continue
    }
    const details = {
      region: { min: runtime.vec(min), max: runtime.vec(max), volume },
      removed,
      removed_count: removed.length,
      blocked_position: runtime.vec(candidate.position),
      blocked_code: result.outcome.code,
      child_results: childResults
    }
    if (result.effect_disposition === 'unknown') {
      return runtime.partial(
        'excavate_region', action, 'EXCAVATION_EFFECT_UNCERTAIN', details, 'unknown'
      )
    }
    return removed.length > 0 || result.effect_disposition === 'applied'
      ? runtime.partial(
          'excavate_region', action, 'EXCAVATION_BLOCKED_AFTER_PROGRESS',
          details, 'applied'
        )
      : runtime.rejected(
          'excavate_region', action, 'EXCAVATION_BLOCKED', details, 'not_applied'
        )
  }

  const remaining = []
  for (const candidate of candidates) {
    const live = activeBot.blockAt(candidate.position)
    if (live && !['air', 'cave_air', 'void_air'].includes(String(live.name))) {
      remaining.push({ name: live.name, position: runtime.vec(candidate.position) })
    }
  }
  const details = {
    region: { min: runtime.vec(min), max: runtime.vec(max), volume },
    removed,
    removed_count: removed.length,
    remaining_count: remaining.length,
    remaining: remaining.slice(0, 16),
    max_blocks: action.max_blocks,
    child_results: childResults
  }
  if (remaining.length === 0) {
    return runtime.applied('excavate_region', action, 'REGION_EXCAVATED', details)
  }
  return runtime.partial(
    'excavate_region', action, 'EXCAVATION_BOUND_REACHED', details, 'applied'
  )
}

async function craftItem (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || ''), count: Number(msg.count || 1) }
  const item = activeBot.registry.itemsByName[action.item]
  if (!item) {
    const blockType = activeBot.registry.blocksByName && activeBot.registry.blocksByName[action.item]
    const entityType = activeBot.registry.entitiesByName && activeBot.registry.entitiesByName[action.item]
    // Registry spelling is immutable declared knowledge, not a world effect.
    // Report bounded alternatives and a read-only next query, never silently
    // substitute an item or craft anything on the agent's behalf.
    const canonicalCandidates = suggestRegistryKind(activeBot.registry, action.item, 'item').slice(0, 8)
    return runtime.rejected('craft_item', action, 'UNKNOWN_ITEM', {
      semantic_domain: 'minecraft.item_name',
      target_classification: blockType ? 'block' : entityType ? 'entity' : 'unknown',
      canonical_item_candidates: canonicalCandidates,
      recovery: {
        action_type: 'registry_search',
        arguments: { query: action.item, limit: 12 }
      },
      rejected_argument_constraints: [{
        argument_path: ['item'],
        rejected_value: action.item,
        validity: { while_provider_instance: true }
      }]
    })
  }
  const before = runtime.inventoryCount(action.item)
  const inventoryBefore = runtime.inventoryMap()
  // A failed Mineflayer recipe feasibility query with an assumed crafting
  // table is authoritative for the *current inventory*.  Movement cannot make
  // the same material set executable.  Publish that source-owned retry
  // boundary instead of forcing the planner to rediscover it from prose.
  // For count>1, a smaller quantity may still be feasible, so constrain only
  // the rejected count; count=1 safely constrains the item itself.
  const impossibleCraftRetryEvidence = prerequisites => ({
    prerequisites: {
      ...prerequisites,
      retry_requires_state_change: ['inventory']
    },
    rejected_argument_constraints: [action.count <= 1
      ? {
          argument_path: ['item'],
          rejected_value: action.item,
          validity: {
            until_state_change: [['inventory']],
            while_provider_instance: true
          }
        }
      : {
          argument_path: ['count'],
          rejected_value: action.count,
          when_arguments: [{ argument_path: ['item'], value: action.item }],
          validity: {
            until_state_change: [['inventory']],
            while_provider_instance: true
          }
        }]
  })
  // A native executable inventory-grid recipe needs no fallback vanilla
  // dependency expansion. Compute public recipe diagnostics only on failure,
  // avoiding needless reference-graph work on the fast physical craft path.
  let recipes = activeBot.recipesFor(item.id, null, action.count, null)
  const vanilla = (!recipes || recipes.length === 0) &&
    typeof activeBot.version === 'string'
    ? minecraftData(activeBot.version) : null
  const catalog = vanilla && vanilla.version &&
    vanilla.version.minecraftVersion === activeBot.version
    ? referenceCraftingRecipes(vanilla, action.item, 100) : null
  const hasNoTableReference = Boolean(catalog && catalog.recipes.some(
    recipe => recipe.requires_crafting_table === false
  ))
  const referenceRecovery = catalog && catalog.recipes.length > 0
    ? { action_type: 'recipe_dependencies',
        arguments: { item: action.item, count: action.count } }
    : null
  // A rejected craft must tell the Agent WHY, without another model/action
  // roundtrip. These are only public vanilla references plus the observed
  // inventory/world; they cannot certify an active datapack recipe or decide
  // which external materials the Agent should seek.
  const missingIngredientReference = () => {
    if (!vanilla || !catalog || catalog.recipes.length === 0) return {}
    try {
      const reference = referenceRecipeDependencies(
        vanilla, action.item, action.count, inventoryBefore
      )
      return { production_reference: {
        item: reference.item,
        count: reference.count,
        item_known: reference.item_known,
        minecraft_version: reference.minecraft_version,
        source: reference.source,
        alternative_ranking_semantics: reference.alternative_ranking_semantics,
        selection_semantics: reference.selection_semantics,
        truth_class: 'declared',
        authoritative_for_current_world_recipe: false,
        datapack_rules_included: false,
        no_physical_effect: true,
        inventory_before: inventoryBefore,
        inventory_source: 'currently_observed_mineflayer_inventory',
        root_alternative_dependency_profiles: reference.root_alternative_dependency_profiles,
        root_recipes_truncated: reference.root_recipes_truncated
      } }
    } catch (_) {
      // If the versioned reference is unavailable, preserve the physical
      // rejection rather than fabricating prerequisite knowledge.
      return {}
    }
  }
  let table = null
  let ownTemporaryTable = null
  let workstationPlacement = null
  if (!recipes || recipes.length === 0) {
    // Recipe feasibility is pure provider-local registry/inventory work. Prove
    // impossibility before any loaded-world station/source scan: a crafting
    // table cannot make an otherwise non-executable recipe executable. The
    // dedicated recipe_dependencies/observe actions own optional source/world
    // discovery, so a rejected craft remains a minimal no-effect witness.
    const tableRecipes = activeBot.recipesFor(item.id, null, action.count, true)
    const executableTableRecipe = Boolean(tableRecipes && tableRecipes.length > 0)
    if (!executableTableRecipe) {
      return runtime.rejected('craft_item', action, 'NO_RECIPE_OR_MATERIALS', {
        before,
        semantic_domain: 'minecraft.item_name',
        ...impossibleCraftRetryEvidence({
          executable_table_recipe_with_current_inventory: false,
          executable_inventory_grid_recipe: false,
          public_no_table_recipe_known: catalog ? hasNoTableReference : null
        }),
        ...(referenceRecovery ? {recovery: referenceRecovery} : {}),
        ...missingIngredientReference()
      })
    }
    const loadedWorldRadius = worldFrontier.loadedWorldCoverageRadius(activeBot)
    let tableBlock = (
      Number.isFinite(loadedWorldRadius) && loadedWorldRadius > 0
        ? activeBot.findBlock({
            matching: block => block && block.name === 'crafting_table',
            maxDistance: loadedWorldRadius
          })
        : null
    )
    if (!tableBlock) {
      const carriedTable = runtime.findInventoryItem('crafting_table')
      const prerequisiteState = {
        nearby_crafting_table: false,
        carried_crafting_table: Boolean(carriedTable),
        executable_table_recipe_with_current_inventory: true,
        executable_inventory_grid_recipe: false,
        public_no_table_recipe_known: catalog ? hasNoTableReference : null
      }
      if (!carriedTable) {
        return runtime.rejected('craft_item', action, 'CRAFTING_TABLE_REQUIRED', {
          before,
          semantic_domain: 'minecraft.item_name',
          prerequisites: prerequisiteState,
          ...(referenceRecovery ? {recovery: referenceRecovery} : {}),
          ...missingIngredientReference(),
          world_frontier: worldFrontier.observeWorldFrontiers(activeBot, loadedWorldRadius)
        })
      }
      // A crafting goal never grants unrequested block-placement authority.
      // The already-observed workbench route above remains usable without
      // this permission; only the conditional physical placement needs it.
      if (!runtime.isSkillChildAuthorized('place_block')) {
        return runtime.rejected('craft_item', action,
          'CRAFTING_STATION_PLACEMENT_NOT_AUTHORIZED', {
            before,
            carried_crafting_table: true,
            executable_table_recipe_with_current_inventory: true,
            required_side_effect_capability: 'place_block'
          }, 'not_applied')
      }
      workstationPlacement = await runtime.runSkillChildEffect(
        0, 'place_block', {item: 'crafting_table'},
        () => placeBlock({item: 'crafting_table'})
      )
      if (
        workstationPlacement.outcome.status !== 'applied' ||
        workstationPlacement.outcome.placed !== 'crafting_table' ||
        workstationPlacement.outcome.physical_call_skipped
      ) {
        const details = {
          station_setup: workstationPlacement.outcome,
          station_setup_disposition: workstationPlacement.effect_disposition,
          current_inventory: runtime.inventoryMap()
        }
        // A rejected placement with no effect is not an indeterminate
        // physical mutation. Preserve its actual certainty.
        return workstationPlacement.effect_disposition === 'applied'
          ? runtime.partial('craft_item', action, 'CRAFTING_STATION_SETUP_INCOMPLETE', details, 'applied')
          : workstationPlacement.effect_disposition === 'unknown'
            ? runtime.partial('craft_item', action, 'CRAFTING_STATION_SETUP_INCOMPLETE', details, 'unknown')
            : runtime.rejected('craft_item', action, 'CRAFTING_STATION_SETUP_UNAVAILABLE', details, 'not_applied')
      }
      ownTemporaryTable = workstationPlacement.outcome.position
      const placedPosition = new Vec3(
        ownTemporaryTable.x, ownTemporaryTable.y, ownTemporaryTable.z
      )
      tableBlock = activeBot.blockAt(placedPosition)
      if (!tableBlock || tableBlock.name !== 'crafting_table') {
        return runtime.partial('craft_item', action, 'CRAFTING_STATION_POST_PLACEMENT_UNKNOWN', {
          station_setup: workstationPlacement.outcome,
          station_position: ownTemporaryTable
        }, 'unknown')
      }
    }
    // Recipe/inventory feasibility is a pure, cheap registry query. Reject
    // before navigation if no materials can satisfy the declared craft intent:
    // otherwise an unsuccessful craft silently moves the world actor.
    const executableTableRecipes = activeBot.recipesFor(item.id, null, action.count, true)
    if (!executableTableRecipes || executableTableRecipes.length === 0) {
      const details = {
        before,
        semantic_domain: 'minecraft.item_name',
        temporary_station_position: ownTemporaryTable,
        ...impossibleCraftRetryEvidence({
          nearby_crafting_table: true,
          executable_recipe_with_current_inventory: false
        }),
        ...(referenceRecovery ? { recovery: referenceRecovery } : {}),
        ...missingIngredientReference()
      }
      return ownTemporaryTable
        ? runtime.partial('craft_item', action, 'NO_RECIPE_AFTER_STATION_PLACEMENT', details, 'applied')
        : runtime.rejected('craft_item', action, 'NO_RECIPE_OR_MATERIALS', details)
    }
    await runtime.ensureMovements()
    await runtime.gotoBlockInteraction(tableBlock.position)
    table = activeBot.blockAt(tableBlock.position)
    recipes = activeBot.recipesFor(item.id, null, action.count, table)
  }
  if (!recipes || recipes.length === 0) {
    const details = {
      before,
      used_table: Boolean(table),
      semantic_domain: 'minecraft.item_name',
      ...impossibleCraftRetryEvidence({
        crafting_table_available: Boolean(table),
        executable_recipe_with_current_inventory: false
      }),
      ...(referenceRecovery ? { recovery: referenceRecovery } : {}),
      ...missingIngredientReference()
    }
    return ownTemporaryTable
      ? runtime.partial('craft_item', action, 'NO_RECIPE_AFTER_STATION_PLACEMENT', {
        ...details, temporary_station_position: ownTemporaryTable
      }, 'applied')
      : runtime.rejected('craft_item', action, 'NO_RECIPE_OR_MATERIALS', details)
  }
  const recipe = recipes[0]
  const outputPerCraft = Math.max(1, Number(recipe.result && recipe.result.count ? recipe.result.count : 1))
  const executions = Math.ceil(action.count / outputPerCraft)
  await activeBot.craft(recipe, executions, table)
  // Reclaim only the precise station we physically placed, never a nearby
  // public table selected by a generic collect search.
  let workstationReclaim = null
  if (ownTemporaryTable) {
    const pos = new Vec3(
      ownTemporaryTable.x, ownTemporaryTable.y, ownTemporaryTable.z
    )
    const live = activeBot.blockAt(pos)
    if (!live || live.name !== 'crafting_table' || !runtime.safeToHarvestBlock(live)) {
      workstationReclaim = { status: 'not_reclaimed', reason: 'exact_station_not_safe_or_present' }
    } else {
      const beforeTables = runtime.inventoryCount('crafting_table')
      try {
        await activeBot.tool.equipForBlock(live, {
          requireHarvest: true, getFromChest: false, maxTools: 1
        })
        if (!(typeof activeBot.canDigBlock === 'function' && activeBot.canDigBlock(live))) {
          await runtime.gotoBlockInteraction(pos)
        }
        const observed = activeBot.blockAt(pos)
        if (!observed || observed.name !== 'crafting_table') {
          throw new Error('TEMPORARY_STATION_CHANGED_BEFORE_RECLAIM')
        }
        const watcher = runtime.captureItemDropNear(pos, null, 1.5)
        try {
          await activeBot.dig(observed)
          let dropped = watcher.pickupTarget()
          if (!dropped) dropped = await watcher.promise
          if (dropped && dropped.isValid !== false) {
            const collected = runtime.waitForOwnCollection(dropped)
            try { await runtime.gotoEntity(dropped, 0) } catch (_) {}
            await collected
          }
        } finally {
          watcher.cancel()
        }
        workstationReclaim = {
          status: runtime.inventoryCount('crafting_table') > beforeTables
            ? 'reclaimed_verified' : 'broken_but_pickup_unconfirmed',
          position: ownTemporaryTable
        }
      } catch (error) {
        workstationReclaim = {
          status: 'reclaim_failed_or_unconfirmed',
          position: ownTemporaryTable,
          error: runtime.errorEvidence(error)
        }
      }
    }
  }
  const after = runtime.inventoryCount(action.item)
  const inventoryAfter = runtime.inventoryMap()
  const inventoryDelta = runtime.inventoryDelta(inventoryBefore, inventoryAfter)
  const crafted = Math.max(0, after - before)
  const unexpectedProduced = Object.fromEntries(
    Object.entries(inventoryDelta).filter(([name, count]) =>
      name !== action.item && Number(count) > 0
    )
  )
  const details = {
    before, after, crafted, executions, output_per_craft: outputPerCraft,
    used_table: Boolean(table), temporary_station_position: ownTemporaryTable,
    workstation_reclaim: workstationReclaim,
    inventory_before: inventoryBefore,
    inventory_after: inventoryAfter, inventory_delta: inventoryDelta,
    unexpected_produced: unexpectedProduced
  }
  if (crafted >= action.count) return runtime.applied('craft_item', action, 'ITEM_CRAFTED', details)
  if (crafted > 0) return runtime.partial('craft_item', action, 'CRAFT_COUNT_INCOMPLETE', details, 'applied')
  // A hidden world rule may convert a requested recipe into a different
  // output. Never assert rejection when server-observed inventory changed.
  if (Object.values(inventoryDelta).some(count => Number(count) !== 0)) {
    return runtime.partial('craft_item', action, 'CRAFT_OUTPUT_CHANGED', details, 'applied')
  }
  return runtime.rejected('craft_item', action, 'CRAFT_EFFECT_NOT_OBSERVED', details)
}

async function smeltItem (msg) {
  const activeBot = runtime.getBot()
  const action = {
    item: String(msg.item || ''),
    count: Number(msg.count || 1),
    fuel: msg.fuel ? String(msg.fuel) : null,
    max_distance: Number(msg.max_distance || 32),
    max_wait_s: Number(msg.max_wait_s || 90)
  }
  const input = runtime.findInventoryItem(action.item)
  const availableInputCount = runtime.inventoryCount(action.item)
  if (!input || availableInputCount < action.count) {
    const details = {
      semantic_domain: 'minecraft.item_name',
      prerequisites: {
        input_item: action.item,
        required_count: action.count,
        available_count: availableInputCount
      }
    }
    return runtime.rejected('smelt_item', action, 'INPUT_NOT_AVAILABLE', details)
  }
  const requestedFuel = action.fuel ? runtime.findInventoryItem(action.fuel) : null
  if (action.fuel && (!requestedFuel || Number(requestedFuel.count) <= 0)) {
    return runtime.rejected('smelt_item', action, 'FUEL_NOT_AVAILABLE', {
      semantic_domain: 'minecraft.item_name',
      prerequisites: { fuel_available: false, requested_fuel: action.fuel }
    })
  }
  const block = activeBot.findBlock({
    matching: candidate => candidate && ['furnace', 'blast_furnace', 'smoker'].includes(candidate.name),
    maxDistance: action.max_distance
  })
  if (!block) {
    const details = {
      semantic_domain: 'minecraft.block_name',
      prerequisites: {
        nearby_furnace: false,
        carried_furnace: runtime.inventoryCount('furnace') > 0
      }
    }
    return runtime.rejected('smelt_item', action, 'FURNACE_NOT_FOUND', details)
  }
  // A missing input, missing explicit fuel or absent furnace must fail
  // before any pathfinder realization is initialized. Preserve actual actor
  // displacement when navigation fails, rather than letting the bridge
  // collapse this recoverable, observed effect into UNKNOWN.
  const startingPosition = activeBot.entity.position.clone()
  const physicalRejection = (code, evidence, disposition = 'not_applied') => {
    const moved = activeBot.entity.position.distanceTo(startingPosition)
    const details = {
      ...evidence,
      position_before: runtime.vec(startingPosition),
      position_after: runtime.vec(activeBot.entity.position),
      moved
    }
    return moved > 0
      ? runtime.partial('smelt_item', action, code, details, 'applied')
      : runtime.rejected('smelt_item', action, code, details, disposition)
  }
  try {
    await runtime.ensureMovements()
    await runtime.gotoBlockInteraction(block.position)
  } catch (error) {
    return physicalRejection('FURNACE_NAVIGATION_INTERRUPTED', {
      furnace: runtime.vec(block.position),
      navigation_error: runtime.errorEvidence(error),
      loaded_world_only: true
    })
  }
  const before = runtime.inventoryMap()
  let furnace = null
  let outputObserved = null
  let collectedOutput = null
  try {
    furnace = await activeBot.openFurnace(activeBot.blockAt(block.position))
    const existingOutput = furnace.outputItem()
    if (existingOutput) {
      return physicalRejection('FURNACE_OUTPUT_NOT_EMPTY', {
        furnace: runtime.vec(block.position),
        output: runtime.itemSummary(existingOutput),
        prerequisites: { furnace_output_empty: false }
      })
    }
    const existingInput = furnace.inputItem()
    if (existingInput && existingInput.type !== input.type) {
      return physicalRejection('FURNACE_INPUT_CONFLICT', {
        furnace: runtime.vec(block.position),
        input: runtime.itemSummary(existingInput),
        prerequisites: { furnace_input_compatible: false }
      })
    }
    const existingInputCount = existingInput ? existingInput.count : 0
    const inputNeeded = Math.max(0, action.count - existingInputCount)
    let fuelUnitsInserted = 0
    let fuelExhausted = null
    const hasActiveFuel = () => Boolean(
      furnace.fuelItem() ||
      (furnace.fuel !== null && Number(furnace.fuel) > 0)
    )
    const insertOneFuel = async () => {
      if (!action.fuel) return { inserted: false, reason: 'fuel_selection_required' }
      const candidate = runtime.findInventoryItem(action.fuel)
      if (!candidate || Number(candidate.count) <= 0) {
        return { inserted: false, reason: 'fuel_not_available' }
      }
      const beforeCount = runtime.inventoryCount(action.fuel)
      try {
        await furnace.putFuel(candidate.type, null, 1)
      } catch (error) {
        const afterCount = runtime.inventoryCount(action.fuel)
        return {
          inserted: afterCount < beforeCount,
          reason: 'fuel_transfer_rejected',
          error: runtime.errorEvidence(error),
          before_count: beforeCount,
          after_count: afterCount
        }
      }
      const afterCount = runtime.inventoryCount(action.fuel)
      const inserted = afterCount < beforeCount
      if (inserted) fuelUnitsInserted += beforeCount - afterCount
      return { inserted, reason: inserted ? null : 'fuel_transfer_unconfirmed', before_count: beforeCount, after_count: afterCount }
    }

    if (!hasActiveFuel()) {
      if (!action.fuel) {
        return physicalRejection('FUEL_SELECTION_REQUIRED', {
          semantic_domain: 'minecraft.item_name',
          prerequisites: { explicit_fuel_required: true, furnace_has_active_fuel: false },
          inventory_items: activeBot.inventory.items().map(item => String(item.name)).sort()
        }, 'not_applied')
      }
      const firstFuel = await insertOneFuel()
      if (!firstFuel.inserted) {
        return physicalRejection('FUEL_NOT_ACCEPTED', {
          fuel: action.fuel,
          transfer: firstFuel
        }, 'not_applied')
      }
    }

    if (inputNeeded > 0) await furnace.putInput(input.type, null, inputNeeded)

    while (true) {
      const currentOutput = furnace.outputItem()
      if (currentOutput && currentOutput.count >= action.count) {
        outputObserved = runtime.itemSummary(currentOutput)
        break
      }

      const event = await runtime.waitForEventCondition(
        furnace,
        'update',
        () => {
          const output = furnace.outputItem()
          if (output && output.count >= action.count) {
            return { kind: 'output_ready', output }
          }
          const fuelStateKnown = furnace.fuel !== null
          if (fuelStateKnown && !hasActiveFuel()) return { kind: 'fuel_needed' }
          return false
        },
        action.max_wait_s * 1000
      )

      if (event && event.kind === 'output_ready') {
        outputObserved = runtime.itemSummary(event.output)
        break
      }
      if (event && event.kind === 'fuel_needed') {
        const added = await insertOneFuel()
        if (!added.inserted) {
          fuelExhausted = added
          break
        }
      }
    }

    const readyToCollect = furnace.outputItem()
    if (readyToCollect) {
      // Credit only the exact server-observed output item transferred to inventory.
      collectedOutput = runtime.itemSummary(readyToCollect)
      await furnace.takeOutput()
    }
    if (fuelExhausted) outputObserved = { ...(outputObserved || {}), fuel_exhausted: fuelExhausted }
    outputObserved = { ...(outputObserved || {}), fuel_units_inserted: fuelUnitsInserted }
  } finally {
    if (furnace) furnace.close()
  }
  const after = runtime.inventoryMap()
  const delta = runtime.inventoryDelta(before, after)
  const produced = collectedOutput && collectedOutput.name
    ? Math.min(
      Math.max(0, Number(collectedOutput.count) || 0),
      Math.max(0, Number(delta[collectedOutput.name]) || 0)
    ) : 0
  const details = { furnace: runtime.vec(block.position), output: outputObserved,
    collected_output: collectedOutput, inventory_delta: delta, produced }
  if (produced >= action.count) return runtime.applied('smelt_item', action, 'ITEM_SMELTED', details)
  const effectObserved = produced > 0 || Object.values(delta).some(value => Number(value) !== 0)
  return runtime.partial('smelt_item', action, 'SMELT_INCOMPLETE', { ...details, effect_observed: effectObserved }, 'applied')
}

async function enchantItem (msg) {
  const activeBot = runtime.getBot()
  await runtime.ensureMovements()
  const action = {
    item: String(msg.item || ''),
    choice: Number(msg.choice || 0),
    max_distance: Number(msg.max_distance || 16)
  }
  const target = runtime.findInventoryItem(action.item)
  if (!target) {
    const details = {
      semantic_domain: 'minecraft.item_name',
      prerequisites: { item_available: false, requested_item: action.item }
    }
    return runtime.rejected('enchant_item', action, 'ITEM_NOT_AVAILABLE', details)
  }
  const tableBlock = activeBot.findBlock({
    matching: block => block && block.name === 'enchanting_table',
    maxDistance: action.max_distance
  })
  if (!tableBlock) {
    const details = {
      semantic_domain: 'minecraft.block_name',
      prerequisites: {
        nearby_enchanting_table: false,
        carried_enchanting_table: runtime.inventoryCount('enchanting_table') > 0
      }
    }
    return runtime.rejected(
      'enchant_item',
      action,
      'ENCHANTING_TABLE_NOT_FOUND',
      details
    )
  }
  const gameMode = activeBot.game && String(activeBot.game.gameMode || '')
  if (gameMode !== 'creative' && runtime.inventoryCount('lapis_lazuli') <= 0) {
    const details = {
      semantic_domain: 'minecraft.item_name',
      prerequisites: { lapis_lazuli_available: false }
    }
    return runtime.rejected('enchant_item', action, 'LAPIS_NOT_AVAILABLE', details)
  }
  await runtime.gotoBlockInteraction(tableBlock.position)
  let table = null
  try {
    table = await activeBot.openEnchantmentTable(activeBot.blockAt(tableBlock.position))
    await table.putTargetItem(target)
    const lapis = runtime.findInventoryItem('lapis_lazuli')
    if (lapis && typeof table.putLapis === 'function') await table.putLapis(lapis)
    if (!Array.isArray(table.enchantments) || !table.enchantments[action.choice] || Number(table.enchantments[action.choice].level) < 0) {
      return runtime.rejected('enchant_item', action, 'ENCHANTMENT_CHOICE_UNAVAILABLE')
    }
    const enchanted = await table.enchant(action.choice)
    const taken = (typeof table.takeTargetItem === 'function') ? await table.takeTargetItem() : enchanted
    return runtime.applied('enchant_item', action, 'ITEM_ENCHANTED', {
      table: runtime.vec(tableBlock.position),
      choice: action.choice,
      level: Number(table.enchantments[action.choice].level),
      enchanted_item: runtime.itemSummary(taken || enchanted)
    })
  } catch (error) {
    return runtime.rejected('enchant_item', action, 'ENCHANTMENT_FAILED', runtime.errorEvidence(error))
  } finally {
    if (table) table.close()
  }
}

async function clearFurnace (msg) {
  const activeBot = runtime.getBot()
  await runtime.ensureMovements()
  const action = { max_distance: Number(msg.max_distance || 32) }
  const block = activeBot.findBlock({
    matching: candidate => candidate && ['furnace', 'blast_furnace', 'smoker'].includes(candidate.name),
    maxDistance: action.max_distance
  })
  if (!block) return runtime.rejected('clear_furnace', action, 'FURNACE_NOT_FOUND')
  await runtime.gotoBlockInteraction(block.position)
  const before = runtime.inventoryMap()
  let furnace = null
  try {
    furnace = await activeBot.openFurnace(activeBot.blockAt(block.position))
    if (furnace.outputItem()) await furnace.takeOutput()
    if (furnace.inputItem()) await furnace.takeInput()
    if (furnace.fuelItem()) await furnace.takeFuel()
  } finally {
    if (furnace) furnace.close()
  }
  const after = runtime.inventoryMap()
  return runtime.applied('clear_furnace', action, 'FURNACE_CLEARED', {
    furnace: runtime.vec(block.position),
    inventory_delta: runtime.inventoryDelta(before, after)
  })
}

async function placeBlock (msg) {
  const activeBot = runtime.getBot()
  const action = { item: String(msg.item || ''), position: msg.position || null }
  const item = runtime.findInventoryItem(action.item)
  if (!item) return runtime.rejected('place_block', action, 'ITEM_NOT_AVAILABLE')
  let target
  let targetSelection
  let placementCandidates = null
  if (action.position) {
    target = new Vec3(
      Math.floor(Number(action.position.x)),
      Math.floor(Number(action.position.y)),
      Math.floor(Number(action.position.z))
    )
    targetSelection = 'explicit_position'
  } else {
    placementCandidates = worldGeometry.localPlacementTargets(activeBot)
    if (placementCandidates.length === 0) {
      return runtime.rejected(
        'place_block',
        action,
        'NO_SAFE_LOCAL_PLACEMENT_TARGET',
        {
          target_selection: 'safe_local_geometry',
          local_candidate_count: 0
        },
        'not_applied'
      )
    }
    target = null
    targetSelection = 'pathfinder_goal_place_any_local'
  }
  // Feasibility/geometry are cheaper than physical navigation setup.
  await runtime.ensureMovements()
  const startingPosition = activeBot.entity.position.clone()
  let navigation
  try {
    navigation = placementCandidates === null
      ? await runtime.gotoBlockPlacement(target)
      : await runtime.gotoAnyBlockPlacement(placementCandidates)
    if (placementCandidates !== null) {
      target = new Vec3(
        Number(navigation.target.x),
        Number(navigation.target.y),
        Number(navigation.target.z)
      )
    }
  } catch (error) {
    const moved = activeBot.entity.position.distanceTo(startingPosition)
    const evidence = {
      position: target ? runtime.vec(target) : null,
      target_selection: targetSelection,
      local_candidate_count: placementCandidates === null ? null : placementCandidates.length,
      position_before: runtime.vec(startingPosition),
      position_after: runtime.vec(activeBot.entity.position),
      moved,
      error_evidence: runtime.errorEvidence(error)
    }
    return moved > 0
      ? runtime.partial('place_block', action, 'PATHFINDER_PLACE_BLOCK_FAILED', evidence, 'applied')
      : runtime.rejected('place_block', action, 'PATHFINDER_PLACE_BLOCK_FAILED', evidence, 'not_applied')
  }

  const beforeBlock = activeBot.blockAt(target)
  const beforeBlockName = beforeBlock && beforeBlock.name
    ? String(beforeBlock.name)
    : null
  if (beforeBlockName === action.item) {
    return runtime.applied('place_block', action, 'BLOCK_ALREADY_PRESENT', {
      position: runtime.vec(target),
      placed: beforeBlockName,
      target_selection: targetSelection,
      physical_call_skipped: true
    })
  }
  const beforeInventory = runtime.inventoryMap()
  await activeBot.equip(item, 'hand')
  let providerError = null
  try {
    await activeBot.placeBlock(navigation.reference, navigation.face)
  } catch (error) {
    providerError = error
  }
  const placed = activeBot.blockAt(target)
  const placedName = placed && placed.name ? String(placed.name) : null
  const afterInventory = runtime.inventoryMap()
  const inventoryDelta = runtime.inventoryDelta(beforeInventory, afterInventory)
  const blockChanged = placedName !== null && placedName !== beforeBlockName
  const targetConfirmed = placedName === action.item
  const inventoryChanged = Object.values(inventoryDelta)
    .some(value => Number(value) !== 0)
  const details = {
    position: runtime.vec(target),
    target_selection: targetSelection,
    local_candidate_count: placementCandidates === null ? null : placementCandidates.length,
    before_block: beforeBlockName,
    placed: placedName,
    inventory_delta: inventoryDelta,
    provider_error: providerError ? runtime.errorEvidence(providerError) : null
  }
  if (targetConfirmed) {
    return runtime.applied(
      'place_block',
      action,
      providerError ? 'BLOCK_PLACED_DESPITE_PROVIDER_ERROR' : 'BLOCK_PLACED',
      details
    )
  }
  if (blockChanged || inventoryChanged) {
    return runtime.partial(
      'place_block',
      action,
      providerError
        ? 'PLACE_EFFECT_OBSERVED_AFTER_PROVIDER_ERROR'
        : 'PLACE_EFFECT_OBSERVED_TARGET_UNCONFIRMED',
      details,
      'applied'
    )
  }
  if (placedName !== null && beforeBlockName !== null) {
    return runtime.rejected(
      'place_block',
      action,
      providerError ? 'PLACE_BLOCK_FAILED_NO_EFFECT' : 'BLOCK_NOT_OBSERVED',
      details,
      'not_applied'
    )
  }
  return runtime.partial(
    'place_block',
    action,
    providerError ? 'PLACE_EFFECT_UNCERTAIN_AFTER_PROVIDER_ERROR' : 'BLOCK_OBSERVATION_UNAVAILABLE',
    details,
    'unknown'
  )
}

module.exports = {
  clear_furnace: clearFurnace,
  collect_block: collectBlock,
  excavate_region: excavateRegion,
  craft_item: craftItem,
  enchant_item: enchantItem,
  place_block: placeBlock,
  smelt_item: smeltItem
}
