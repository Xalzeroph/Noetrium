"""Environment-independent agent context compilation for arbitrary Unit methods.

Only the owner of a source can decide what it means: an environment projects
public observations, a capability authority reports allowed actions, and a
method decides when/how/what memory to retrieve. The compiler provides one
presentation path without interpreting environment-specific fields or treating
recalled statements as physical facts.
"""
from __future__ import annotations

from collections import deque
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any

from noetrium_platform.foundation.kernel.kernel import canonical_digest, canonical_text, thaw_json


_ENVIRONMENT_TRUTHS = frozenset({"declared", "authorized", "observed", "evidenced"})


@dataclass(frozen=True, slots=True)
class AgentContextProjection:
    """One auditable prompt, with no fixed Minecraft/GUI/robotics ontology."""

    text: str
    section_count: int


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise TypeError(f"agent context {field} must be a mapping")
    return value


def _source(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"agent context {field} must be non-empty text")
    return value



def _compile_current_control_feedback(history: Mapping[str, Any]) -> dict[str, Any]:
    """Expose Method-owned *current* control feedback, never free history.

    ``action_results`` is a durable execution trace.  It remains available to
    runtime watchdogs, metrics, and explicit Method memory ingestion, but the
    universal Context Engine must not turn it into an implicit short-term
    memory channel.  The current Environment observation already owns the
    immediately preceding transition feedback.  Any evidence that must survive
    beyond that next decision has to re-enter through the Method's explicit
    memory/control state.
    """
    if "action_evidence" in history:
        raise ValueError("method cannot override platform execution evidence")
    return {
        key: thaw_json(value)
        for key, value in history.items()
        if key != "action_results"
    }

def _unchanged_read_only_observation_signal(
    history: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Expose a verified planning stall without inventing environment truth.

    Only the capability authority may classify an action as read-only, and
    only identical public, observed/evidenced Provider facets may establish
    that repeating the action yielded no new information in those facets.
    Mutations, uncertain effects, and other changed facets are never folded
    into a no-effect assertion.
    """
    actions = history.get("action_results", ())
    if not isinstance(actions, (tuple, list)) or len(actions) < 2:
        return None
    previous, current = actions[-2:]
    if not isinstance(previous, Mapping) or not isinstance(current, Mapping):
        return None
    proposal = current.get("action")
    if not isinstance(proposal, Mapping) or dict(proposal) != previous.get("action"):
        return None
    action_type = proposal.get("action_type")
    if not isinstance(action_type, str) or not action_type:
        return None
    catalog = capabilities.get("actions")
    if not isinstance(catalog, Mapping):
        return None
    columns, rows = catalog.get("columns"), catalog.get("rows")
    if not isinstance(columns, (tuple, list)) or not isinstance(rows, (tuple, list)):
        return None
    if "action_type" not in columns or "mutates_world" not in columns:
        return None
    type_index, mutation_index = columns.index("action_type"), columns.index("mutates_world")
    is_read_only = any(
        isinstance(row, (tuple, list))
        and len(row) > max(type_index, mutation_index)
        and row[type_index] == action_type
        and row[mutation_index] is False
        for row in rows
    )
    if not is_read_only:
        return None

    def public_observations(entry: Mapping[str, Any]) -> dict[tuple[str, str, str], Any]:
        result = entry.get("outcome")
        if not isinstance(result, Mapping):
            return {}
        receipt = result.get("effect_receipt")
        if isinstance(receipt, Mapping) and receipt.get("certainty") == "indeterminate":
            return {}
        facets = result.get("agent_context_facets")
        if not isinstance(facets, (tuple, list)):
            return {}
        visible: dict[tuple[str, str, str], Any] = {}
        for facet in facets:
            if not isinstance(facet, Mapping) or "value" not in facet:
                continue
            truth = facet.get("truth_class")
            source, label = facet.get("source"), facet.get("label")
            if (truth in {"observed", "evidenced"}
                and isinstance(source, str) and source
                and isinstance(label, str) and label):
                validity = facet.get("validity", "as_declared_by_source")
                if isinstance(validity, Mapping):
                    # Fresh observations necessarily have distinct evidence
                    # IDs. Their *content* can be unchanged even though the
                    # provenance references must remain distinct. Compare
                    # validity semantics and world generation, not the ID.
                    validity = {
                        key: value for key, value in validity.items()
                        if key != "observation_id"
                    }
                visible[(label, source, truth)] = (
                    facet["value"], validity
                )
        return visible

    prior = public_observations(previous)
    recent = public_observations(current)
    stable = sorted({
        label for (label, source, truth), value in prior.items()
        if (label, source, truth) in recent
        and recent[(label, source, truth)] == value
    })
    if not stable:
        return None
    return {
        "source": "execution_evidence",
        "action": thaw_json(dict(proposal)),
        "unchanged_public_observation_labels": stable,
        "instruction": (
            "The most recent read-only action exactly repeats the preceding "
            "action and returned identical information for the named public "
            "observation facets. Do not repeat the same query expecting new "
            "information without a justified world change. Choose a different "
            "authorized action or materially different query that advances "
            "the goal. Other facets may have changed; no physical success is implied."
        ),
    }


def _rejected_mutation_stall_signal(
    history: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Warn about recurring *proved rejections*, not hypothetical world facts.

    The signal contains no raw environment state: only action identities and
    Provider-authorized feedback codes. Alternating failed actions are caught
    without forbidding an Agent's right to choose a different strategy.
    """
    raw = history.get("action_results", ())
    if not isinstance(raw, (tuple, list)) or len(raw) < 2:
        return None
    catalog = capabilities.get("actions")
    if not isinstance(catalog, Mapping):
        return None
    columns, rows = catalog.get("columns"), catalog.get("rows")
    if not isinstance(columns, (tuple, list)) or not isinstance(rows, (tuple, list)):
        return None
    if "action_type" not in columns or "mutates_world" not in columns:
        return None
    name_index, effect_index = columns.index("action_type"), columns.index("mutates_world")
    mutating = {
        row[name_index]
        for row in rows if isinstance(row, (tuple, list))
        and len(row) > max(name_index, effect_index)
        and row[effect_index] is True
        and isinstance(row[name_index], str)
    }
    # Inspect only the current no-effect epoch. A confirmed mutating effect or
    # an indeterminate effect may have changed the world, so rejection history
    # before that boundary is no longer valid current-control evidence. This
    # watchdog may use durable history internally, but it must not become a
    # second memory channel across physical state transitions.
    current_epoch: list[Mapping[str, Any]] = []
    for entry in reversed(raw[-8:]):
        if not isinstance(entry, Mapping):
            continue
        action, outcome = entry.get("action"), entry.get("outcome")
        if not isinstance(action, Mapping) or not isinstance(outcome, Mapping):
            continue
        receipt = outcome.get("effect_receipt")
        receipt = receipt if isinstance(receipt, Mapping) else {}
        certainty = receipt.get("certainty")
        action_type = action.get("action_type")
        if certainty == "indeterminate":
            break
        if certainty == "effect_confirmed" and action_type in mutating:
            break
        current_epoch.append(entry)
    current_epoch.reverse()

    failures: dict[str, dict[str, Any]] = {}
    for entry in current_epoch:
        action, outcome = entry.get("action"), entry.get("outcome")
        if not isinstance(action, Mapping) or not isinstance(outcome, Mapping):
            continue
        if action.get("action_type") not in mutating:
            continue
        receipt = outcome.get("effect_receipt")
        if not isinstance(receipt, Mapping) or receipt.get("certainty") != "effect_rejected":
            continue
        public = None
        facets = outcome.get("agent_context_facets")
        if not isinstance(facets, (tuple, list)):
            continue
        for facet in facets:
            if (
                isinstance(facet, Mapping)
                and isinstance(facet.get("label"), str)
                and facet["label"].endswith(".last_action_feedback")
                and facet.get("truth_class") in {"observed", "evidenced"}
                and isinstance(facet.get("source"), str)
                and facet["source"].startswith("environment.")
                and isinstance(facet.get("value"), Mapping)
            ):
                public = facet["value"].get("outcome")
                break
        if not isinstance(public, Mapping) or public.get("status") != "rejected":
            continue
        code = public.get("code")
        if not isinstance(code, str) or not code.strip():
            continue
        digest = canonical_digest(dict(action))
        result = failures.setdefault(digest, {
            "action_type": action["action_type"],
            "action_arguments": thaw_json(dict(action.get("arguments", {})))
                if isinstance(action.get("arguments", {}), Mapping) else {},
            "public_rejection_codes": [],
            "rejection_count": 0,
        })
        result["rejection_count"] += 1
        if code not in result["public_rejection_codes"]:
            result["public_rejection_codes"].append(code)
    repeated = [row for row in failures.values() if row["rejection_count"] >= 2]
    if not repeated:
        return None
    return {
        "source": "execution_evidence",
        "truth_class": "evidenced",
        "repeated_rejected_mutating_actions": repeated,
        "instruction": (
            "The listed requests were physically rejected repeatedly in recent"
            " executions. Repeating the identical request without a new"
            " premise is not progress. Check authorized observations,"
            " prerequisites and available actions, then select a meaningfully"
            " different input, target or permitted skill. The world may have"
            " changed between requests; this record proves rejection history"
            " only, not absence of resources elsewhere or task failure."
        ),
    }



def _fulfilled_bounded_mutation_signal(
    history: Mapping[str, Any],
    capabilities: Mapping[str, Any],
) -> dict[str, Any] | None:
    """Surface one Provider-declared completed bounded mutation request.

    The Context Engine does not infer domain progress from fields such as item
    counts or distances. A Provider may instead publish a typed control-only
    ``bounded_request_completed`` constraint. When the immediately preceding
    action is Authority-declared mutating and its effect is confirmed, expose a
    short advisory signal for the next decision. The signal is intentionally
    weaker than task success and never hard-forbids a repeated action.
    """
    raw = history.get("action_results", ())
    if not isinstance(raw, (tuple, list)) or not raw:
        return None
    entry = raw[-1]
    if not isinstance(entry, Mapping):
        return None
    action, outcome = entry.get("action"), entry.get("outcome")
    if not isinstance(action, Mapping) or not isinstance(outcome, Mapping):
        return None
    action_type = action.get("action_type")
    if not isinstance(action_type, str) or not action_type:
        return None

    catalog = capabilities.get("actions")
    if not isinstance(catalog, Mapping):
        return None
    columns, rows = catalog.get("columns"), catalog.get("rows")
    if not isinstance(columns, (tuple, list)) or not isinstance(rows, (tuple, list)):
        return None
    if "action_type" not in columns or "mutates_world" not in columns:
        return None
    type_index, mutation_index = columns.index("action_type"), columns.index("mutates_world")
    if not any(
        isinstance(row, (tuple, list))
        and len(row) > max(type_index, mutation_index)
        and row[type_index] == action_type
        and row[mutation_index] is True
        for row in rows
    ):
        return None

    receipt = outcome.get("effect_receipt")
    if not isinstance(receipt, Mapping) or receipt.get("certainty") != "effect_confirmed":
        return None
    indexed = outcome.get("decision_constraints", ())
    if not isinstance(indexed, (tuple, list)):
        return None
    for row in indexed:
        if not isinstance(row, Mapping):
            continue
        source, truth = row.get("source"), row.get("truth_class")
        constraint = row.get("constraint")
        if not (
            isinstance(source, str) and source.startswith("environment.")
            and truth in _ENVIRONMENT_TRUTHS
            and isinstance(constraint, Mapping)
            and constraint.get("kind") == "bounded_request_completed"
            and constraint.get("valid_until") == "physical_effect"
        ):
            continue
        requested = constraint.get("requested_count")
        observed = constraint.get("observed_count")
        if not (
            type(requested) is int and requested > 0
            and type(observed) is int and observed >= requested
        ):
            continue
        return {
            "source": "execution_evidence",
            "truth_class": "evidenced",
            "fulfilled_bounded_request": {
                "action": thaw_json(dict(action)),
                "scope": "request_only_not_task_goal",
            },
            "instruction": (
                "The prior bounded request is complete, not the task. Re-evaluate "
                "the current goal and prerequisites before repeating the same target; "
                "repeat only if current evidence shows additional unmet quantity or "
                "a materially new premise."
            ),
        }
    return None

def _structured_environment_context(
    observations: Sequence[Mapping[str, Any]],
    capabilities: Mapping[str, Any],
) -> dict[str, Any]:
    """One environment-neutral decision tree; paths belong to Providers.

    Original facets remain source-of-truth evidence. This is solely their
    model-facing JSON projection; neither strategy nor world facts are inferred.
    An authorized action catalog is injected from Authority, not a Provider.
    """
    tree: dict[str, Any] = {}
    ungrouped: list[dict[str, Any]] = []
    for row in observations:
        path = row.get("path")
        # Provenance identity stays on the durable facet.  The Provider has
        # already passed the visibility cut, so opaque source/evidence IDs and
        # normal observation generations cannot change the next action.  Keep
        # only truth/value plus an exceptional validity warning when the latest
        # snapshot is explicitly not proof of the current world.
        validity = row.get("validity")
        exceptional_validity = (
            validity
            if isinstance(validity, str)
            and validity not in {"as_declared_by_source"}
            else None
        )
        leaf = {
            "truth": row["truth_class"],
            "value": row["value"],
            **({"validity": exceptional_validity}
               if exceptional_validity is not None else {}),
        }
        if path is None:
            ungrouped.append({"label": row["label"], **leaf})
            continue
        if (not isinstance(path, (tuple, list)) or not path
            or any(not isinstance(part, str) or not part.strip()
                   for part in path)):
            raise ValueError("environment decision path must be nonempty text segments")
        current = tree
        for segment in path[:-1]:
            child = current.setdefault(segment, {})
            if not isinstance(child, dict) or "truth" in child:
                raise ValueError("environment decision path prefix collision")
            current = child
        if path[-1] in current:
            raise ValueError("duplicate environment decision path")
        current[path[-1]] = leaf
    if ungrouped:
        if "observations" in tree:
            raise ValueError("environment observations path reserved")
        tree["observations"] = ungrouped
    if "actions" in tree and not isinstance(tree["actions"], dict):
        raise ValueError("environment actions path conflict")
    actions = tree.setdefault("actions", {})
    if "authorized" in actions:
        raise ValueError("only Authority may populate authorized actions")
    actions["authorized"] = {
        "truth": "authorized", "source": "authority",
        "value": thaw_json(capabilities),
    }
    return tree


def _environment_jsonl(
    observations: Sequence[Mapping[str, Any]],
    capabilities: Mapping[str, Any],
) -> str:
    """Compact source-typed JSON Lines without another world-truth store.

    The immutable authorized catalog comes first for shared model KV prefix
    reuse; each other record is one already-visibility-cut observation facet.
    Values are never guessed, promoted, summarized, or silently truncated.
    """
    def records():
        yield {
            "record": "capability_catalog",
            "truth": "authorized",
            "source": "authority",
            "value": capabilities,
        }
        for row in observations:
            # Provenance IDs remain in the durable facet/evidence record. They
            # are audit identity, not next-action information. Model context
            # keeps source truth class and only an exceptional validity state
            # when the latest visible snapshot cannot prove the current world.
            validity = row.get("validity")
            exceptional_validity = (
                validity
                if isinstance(validity, str)
                and validity not in {"as_declared_by_source"}
                else None
            )
            yield {
                "path": row.get("path", [row["label"]]),
                "truth": row["truth_class"],
                **({"validity": exceptional_validity}
                   if exceptional_validity is not None else {}),
                "value": row["value"],
            }
    # Streaming encoder traversal: no second array of all facet records.
    return "\n".join(canonical_text(row) for row in records())


def compile_agent_context(context: Mapping[str, Any]) -> AgentContextProjection:
    """Project source-typed Unit values into one provenance-separated view.

    The environment must already be Agent-authorized by its own Provider's
    visibility cut. The compiler cannot and must not infer environment labels.
    Nothing truncates method memory: context-budget failure is observable
    rather than silently dropping evidence or research-method state.
    """
    root = _mapping(context, "root")
    keys = set(root)
    allowed = {"goal", "environment", "capabilities", "history", "memory", "method", "output"}
    unknown = keys - allowed
    if unknown:
        raise ValueError("unrecognized agent context semantic roots: " + ",".join(sorted(unknown)))
    goal = _mapping(root.get("goal", {}), "goal")
    environment = root.get("environment", ())
    if isinstance(environment, Mapping):
        # Method code passes its opaque EnvironmentAction result without
        # interpreting any domain state. Only the Provider owns the facets.
        # A nonempty result without declared facets is not safe to convert.
        if environment and "agent_context_facets" not in environment:
            raise ValueError("environment result lacks capability-owned agent context facets")
        environment = environment.get("agent_context_facets", ())
    if not isinstance(environment, (tuple, list)):
        raise TypeError("agent context environment must be ordered capability-owned facets")

    # A last observed state may predate an indeterminate side effect. It
    # remains historical evidence, not fresh proof of the current world.
    raw_environment = root.get("environment", ())
    receipt = raw_environment.get("effect_receipt", {}) if isinstance(raw_environment, Mapping) else {}
    certainty = receipt.get("certainty") if isinstance(receipt, Mapping) else None
    unresolved_effect = certainty == "indeterminate" or (
        isinstance(raw_environment, Mapping)
        and raw_environment.get("effect_disposition") == "indeterminate"
    )

    observations: list[dict[str, Any]] = []
    for i, facet in enumerate(environment):
        row = _mapping(facet, f"environment[{i}]")
        if set(row) - {
            "label", "path", "truth_class", "source", "value",
            "evidence_ref", "validity", "history_retention",
            "decision_constraint",
        }:
            raise ValueError("environment facet contains undeclared provenance fields")
        truth = _source(row.get("truth_class"), "truth_class")
        if truth not in _ENVIRONMENT_TRUTHS:
            raise ValueError("environment facet truth_class must be declared/authorized/observed/evidenced")
        label = _source(row.get("label"), "label")
        source = _source(row.get("source"), "source")
        if "value" not in row:
            raise ValueError("environment facet must retain its source value")
        observations.append({
            "label": label,
            **({"path": row["path"]} if "path" in row else {}),
            "truth_class": truth,
            "source": source,
            "value": thaw_json(row["value"]),
            **({"evidence_ref": row["evidence_ref"]} if "evidence_ref" in row else {}),
            "validity": (
                "previous_snapshot_not_current_effect_proof"
                if unresolved_effect and truth in {"observed", "evidenced"}
                else row.get("validity", "as_declared_by_source")
            ),
        })

    history = _mapping(root.get("history", {}), "history")
    capabilities = _mapping(root.get("capabilities", {}), "capabilities")
    progress_signals = tuple(
        signal for signal in (
            _unchanged_read_only_observation_signal(history, capabilities),
            _rejected_mutation_stall_signal(history, capabilities),
            _fulfilled_bounded_mutation_signal(history, capabilities),
        ) if signal is not None
    )
    # Model prefix-caching starts at the beginning of the request, not
    # at each section boundary. Canonical JSON puts the stable Authority
    # action catalog first inside ENVIRONMENT_CONTEXT. Keep that immutable,
    # provider-sourced information before dynamic goals, observations and
    # Method memory so concurrent trials may share its KV prefix without
    # suppressing or changing a single decision-relevant fact.
    # The Provider selects only serialization, never a different truth model.
    # The same verified facets feed structured JSON or compact JSONL records.
    environment_format = (
        raw_environment.get("agent_context_format", "json")
        if isinstance(raw_environment, Mapping) else "json"
    )
    if environment_format not in {"json", "jsonl"}:
        raise ValueError("environment context format is unsupported")
    environment_value = (
        _environment_jsonl(observations, capabilities)
        if environment_format == "jsonl"
        else _structured_environment_context(observations, capabilities)
    )
    current_control_feedback = _compile_current_control_feedback(
        _mapping(root.get("history", {}), "history")
    )
    chunks = [
        ("ENVIRONMENT_CONTEXT", environment_value),
        ("GOAL", {"source": "method", "value": thaw_json(goal)}),
        ("RETRIEVED_METHOD_MEMORY", {
            "source": "downstream_method",
            "truth_class": "recalled_not_live_observation",
            "value": thaw_json(_mapping(root.get("memory", {}), "memory")),
        }),
        ("METHOD_POLICY", {
            "source": "downstream_method",
            "value": thaw_json(_mapping(root.get("method", {}), "method")),
        }),
        *tuple(("EXECUTION_PROGRESS_SIGNAL", signal)
               for signal in progress_signals),
        ("OUTPUT_CONTRACT", {
            "source": "method",
            "value": thaw_json(_mapping(root.get("output", {}), "output")),
        }),
    ]
    if current_control_feedback:
        # Control feedback is current Method state, not an execution-history
        # replay. Keep it near the dynamic policy rather than manufacturing a
        # second Environment or memory channel.
        insert_at = next(
            index for index, (heading, _value) in enumerate(chunks)
            if heading == "RETRIEVED_METHOD_MEMORY"
        )
        chunks.insert(insert_at, (
            "CURRENT_CONTROL_FEEDBACK",
            {"source": "method", "value": current_control_feedback},
        ))
    if not goal:
        raise ValueError("agent context must provide a goal")
    text = "\n\n".join(
        f"## {heading}\n{value if heading == 'ENVIRONMENT_CONTEXT' and environment_format == 'jsonl' else canonical_text(value)}"
        for heading, value in chunks
    )
    return AgentContextProjection(text=text, section_count=len(chunks))
