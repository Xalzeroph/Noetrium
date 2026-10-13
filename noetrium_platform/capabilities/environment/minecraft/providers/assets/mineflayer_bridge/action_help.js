"use strict"

// No local action registry: the Coordinator provides the exact authorized Unit
// contract for this request, including its runtime argument_schema. These
// fields are presentation only, and cannot execute or validate a physical
// action. They must not infer inventory, hidden recipes, or world state.
const runtime = require("./runtime")

function argumentGuide (reference) {
  const schema = reference.argument_schema
  const props = schema.properties || {}
  const required = new Set(schema.required || [])
  const semantics = reference.argument_semantics || {}
  const fields = Object.keys(props).map(name => {
    const definition = props[name] || {}
    const source = typeof semantics[name] === "string" ? semantics[name] : null
    const limits = {}
    for (const key of [
      "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
      "minLength", "maxLength", "minItems", "maxItems", "pattern"
    ]) {
      if (Object.hasOwn(definition, key)) limits[key] = definition[key]
    }
    return {
      name,
      required: required.has(name),
      value_type: definition.type || null,
      permitted_values: Array.isArray(definition.enum) ? [...definition.enum] : null,
      numeric_or_length_bounds: limits,
      registry_semantic: source,
      description: typeof definition.description === "string"
        ? definition.description : null,
      nested_schema: definition.type === "object" ||
                     definition.type === "array"
        ? definition : null,
      // Registry names can be looked up without physically possessing the
      // named item. World evidence is a separate requirement declared in the
      // exact action's applicability contract, not inferred from its type.
      registry_name_resolution_suggested: source !== null &&
        /minecraft\.(?:block|item|entity)/.test(source)
    }
  })
  return {
    source: "authorized_environment_capability",
    truth_class: "declared",
    action_type: reference.action_type,
    category: reference.category || null,
    mutates_world: reference.mutates_world === true,
    parameters: fields,
    required_parameter_names: fields.filter(row => row.required).map(row => row.name),
    optional_parameter_names: fields.filter(row => !row.required).map(row => row.name),
    unknown_parameters_permitted: schema.additionalProperties === true,
    applicable_when: Array.isArray(reference.applicability)
      ? [...reference.applicability] : [],
    invocations_are_examples: Array.isArray(reference.usage_guide?.few_shots) &&
      reference.usage_guide.few_shots.length > 0,
    example_interpretation: "Hypothetical examples only: confirm physical preconditions and authorize each real request separately.",
    evidence_rules: {
      registry_name_not_possession: true,
      action_request_not_physical_success: true,
      verify_effect_receipt_and_observed_state_after_mutation: true,
      do_not_repeat_indeterminate_physical_effect: true
    }
  }
}

function describeAction (msg) {
  const requested = msg.action_type
  const reference = msg._authorized_action_reference
  if (typeof requested !== "string" || !reference ||
      typeof reference !== "object" || Array.isArray(reference) ||
      reference.action_type !== requested ||
      !reference.argument_schema ||
      reference.argument_schema.type !== "object") {
    return runtime.rejected("describe_action",
      { action_type: String(requested || "") },
      "ACTION_HELP_AUTHORITY_MISSING", {})
  }
  const properties = reference.argument_schema.properties
  const required = reference.argument_schema.required || []
  if (!properties || typeof properties !== "object" ||
      Array.isArray(properties) || !Array.isArray(required) ||
      required.some(name => typeof name !== "string" ||
          !Object.hasOwn(properties, name))) {
    // The Authority must provide a coherent, complete action definition.
    // Fail closed instead of rendering a misleading argument guide.
    return runtime.rejected("describe_action",
      { action_type: requested },
      "ACTION_HELP_AUTHORITY_MALFORMED", {})
  }
  return runtime.applied("describe_action",
    { action_type: requested },
    "ACTION_DESCRIBED", {
      truth_class: "declared",
      physical_world_observed: false,
      authorized: true,
      action_contract: reference,
      argument_guide: argumentGuide(reference),
      invocation_format: {
        action_type: requested,
        arguments_contract: reference.arguments,
        executable_example: false
      }
    })
}

module.exports = { describe_action: describeAction }
