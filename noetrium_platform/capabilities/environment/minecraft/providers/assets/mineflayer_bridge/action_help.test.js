"use strict"

const test = require("node:test")
const assert = require("node:assert/strict")
const { describe_action } = require("./action_help")

const reference = Object.freeze({
  action_type: "equip_item", category: "inventory",
  description: "Equip an inventory item to an equipment destination.",
  arguments: "{item:string, destination?:hand|off-hand|head|torso|legs|feet}",
  argument_schema: {
    type: "object", additionalProperties: false,
    required: ["item"],
    properties: {
      item: {type: "string"},
      destination: {type: "string",
        enum: ["hand", "off-hand", "head", "torso", "legs", "feet"]}
    }
  },
  applicability: ["requires the item to exist in the currently observed inventory"],
  argument_semantics: {item: "minecraft.item_name"}, mutates_world: true
})

test("describe_action returns one exact Authority-supplied definition, no world claims", () => {
  const result = describe_action({
    action_type: "equip_item",
    _authorized_action_reference: reference
  })
  assert.equal(result.outcome.code, "ACTION_DESCRIBED")
  assert.deepEqual(result.outcome.action_contract.argument_schema, reference.argument_schema)
  assert.equal(result.outcome.truth_class, "declared")
  assert.equal(result.outcome.physical_world_observed, false)
  assert.equal(result.outcome.invocation_format.executable_example, false)
  assert.equal(result.outcome.action_contract.argument_schema.properties.destination.enum.includes("main_hand"), false)
})

test("missing or forged target authority cannot cause a reference leak", () => {
  for (const msg of [
    {action_type: "equip_item"},
    {action_type: "equip_item", _authorized_action_reference: {...reference, action_type: "hidden_action"}},
    {action_type: "unknown_action", _authorized_action_reference: reference}
  ]) {
    const result = describe_action(msg)
    assert.equal(result.outcome.code, "ACTION_HELP_AUTHORITY_MISSING")
    assert.equal(result.outcome.status, "rejected")
    assert.equal(result.outcome.action_contract, undefined)
  }
})

test("describe_action compiles actionable field requirements without inventing items", () => {
  const result = describe_action({
    action_type: "equip_item", _authorized_action_reference: reference
  })
  const guide = result.outcome.argument_guide
  assert.equal(guide.source, "authorized_environment_capability")
  assert.equal(guide.truth_class, "declared")
  assert.equal(guide.action_type, "equip_item")
  assert.deepEqual(guide.required_parameter_names, ["item"])
  assert.deepEqual(guide.optional_parameter_names, ["destination"])
  assert.deepEqual(guide.parameters[1].permitted_values,
    ["hand", "off-hand", "head", "torso", "legs", "feet"])
  assert.equal(guide.parameters[0].registry_semantic, "minecraft.item_name")
  assert.equal(guide.parameters[0].registry_name_resolution_suggested, true)
  assert.equal(guide.parameters[0].current_world_evidence_required, undefined)
  assert.equal(guide.unknown_parameters_permitted, false)
  assert.equal(guide.evidence_rules.registry_name_not_possession, true)
  assert.equal(guide.evidence_rules.do_not_repeat_indeterminate_physical_effect, true)
  assert.equal(result.outcome.physical_world_observed, false)
})

test("describe_action preserves nested schema and source numeric bounds without guessing arguments", () => {
  const contract = {
    action_type: "goto_pos",
    category: "movement",
    arguments: "{target:{x:number,y:number,z:number},distance?:1..16}",
    argument_schema: {
      type: "object",
      additionalProperties: false,
      required: ["target"],
      properties: {
        target: {
          type: "object", required: ["x", "y", "z"], additionalProperties: false,
          properties: {
            x: {type: "number"}, y: {type: "number"}, z: {type: "number"}
          }
        },
        distance: {type: "integer", minimum: 1, maximum: 16}
      }
    },
    mutates_world: true
  }
  const result = describe_action({
    action_type: "goto_pos", _authorized_action_reference: contract
  })
  const guide = result.outcome.argument_guide
  assert.deepEqual(guide.parameters[0].nested_schema,
    contract.argument_schema.properties.target)
  assert.deepEqual(guide.parameters[1].numeric_or_length_bounds,
    {minimum:1,maximum:16})
  assert.equal(guide.mutates_world, true)
  assert.equal(guide.invocations_are_examples, false)
  assert.equal(JSON.stringify(guide).includes("oak_log"), false)
})

test("describe_action rejects malformed Authority schemas instead of misleading the planner", () => {
  for (const schema of [
    {type:"object", required:["missing"],properties:{valid:{type:"string"}}},
    {type:"object", required:"item",properties:{item:{type:"string"}}},
    {type:"object", required:["item"],properties:null}
  ]) {
    const res=describe_action({
      action_type:"equip_item",
      _authorized_action_reference:{
        ...reference,argument_schema:schema
      }
    })
    assert.equal(res.outcome.status,"rejected")
    assert.equal(res.outcome.code,"ACTION_HELP_AUTHORITY_MALFORMED")
  }
})


test("describe_action exposes only the requested Authority-supplied handbook, not world claims", () => {
  const guide = {
    use_when: "Select a verified held tool for one equipment slot.",
    prepare: "Inspect actual inventory first.",
    verify: "Observe the changed equipment slot.",
    when_not_completed: "Recheck owned items before retrying.",
    few_shots: [
      {only_when: "Pickaxe held", arguments: {item: "iron_pickaxe", destination: "hand"}, check_afterwards: "Verify hand slot"},
      {only_when: "Helmet held", arguments: {item: "iron_helmet", destination: "head"}, check_afterwards: "Verify head slot"}
    ],
    counterexamples: [
      {arguments: {item: "iron_pickaxe", destination: "main_hand"}, why_not: "Invalid destination"},
      {arguments: {item: "invented_item"}, why_not: "No physical possession established"}
    ]
  }
  const result = describe_action({
    action_type: "equip_item",
    _authorized_action_reference: {...reference, usage_guide: guide}
  })
  assert.equal(result.outcome.code, "ACTION_DESCRIBED")
  assert.deepEqual(result.outcome.action_contract.usage_guide, guide)
  assert.equal(result.outcome.argument_guide.invocations_are_examples, true)
  assert.match(result.outcome.argument_guide.example_interpretation, /Hypothetical examples only/)
  assert.equal(result.outcome.physical_world_observed, false)
  assert.equal(result.outcome.invocation_format.executable_example, false)
})
