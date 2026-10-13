"""Read-only causal closure over the sole committed Machine Journal."""

from __future__ import annotations

from collections import defaultdict, deque

from .canonical import canonical_digest
from .inspection import MachineHistoryInspection
from .journal import MachineJournalPort
from .machine import MachineCommit, MachineCut, MachineIntegrityError


def _verified_machine_closure(
    root: MachineHistoryInspection, journal: MachineJournalPort
) -> "tuple[NoetriumUnit, dict[str, tuple[MachineCommit, ...]]]":
    """Certify linked child cuts and retain exactly their verified histories."""
    if not isinstance(root, MachineHistoryInspection):
        raise TypeError("causal coverage requires verified Machine inspection")
    if not isinstance(journal, MachineJournalPort):
        raise TypeError("causal coverage requires Machine Journal authority")

    # Root itself must originate from this authoritative Journal.
    root_history = journal.commits(root.identity.machine_id)
    if (len(root_history) < root.revision or tuple(
        commit.commit_id for commit in root_history[:root.revision]
    ) != root.commit_ids):
        raise MachineIntegrityError("causal root cut is not present in Journal")
    histories: dict[str, tuple[MachineCommit, ...]] = {
        root.identity.machine_id: root.transitions
    }
    validated: dict[str, int] = {root.identity.machine_id: root.revision}
    outgoing: dict[str, set[str]] = defaultdict(set)
    link_cuts: list[tuple[str, str, int, str, str]] = []
    pending = deque((root.identity.machine_id, link) for link in root.children)
    expanded_upto: dict[str, int] = {}

    while pending:
        parent_id, link = pending.popleft()
        name = link.child_machine_id
        if link.parent_machine_id != parent_id:
            raise MachineIntegrityError("causal child parent identity drifted")
        commits = histories.get(name)
        if commits is None:
            commits = journal.commits(name)
            histories[name] = commits
        end = link.child_transition_end
        if end < 1 or end > len(commits):
            raise MachineIntegrityError("causal child Machine cut is missing")
        already = validated.get(name, 0)
        for offset in range(already, end):
            commit = commits[offset]
            previous = commits[offset - 1] if offset else None
            if (commit.machine_id != name
                or commit.revision != offset + 1
                or commit.base_revision != offset
                or commit.previous_commit_id != (
                    None if previous is None else previous.commit_id
                )
                or (previous is not None
                    and commit.before_state_digest != previous.state_digest)):
                raise MachineIntegrityError("causal child history is not continuous")
        validated[name] = max(already, end)
        if (commits[0].unit_digest != link.child_unit_digest
            or commits[0].execution_lock_digest
            != link.child_execution_lock_digest):
            raise MachineIntegrityError("causal child Unit binding drifted")
        for commit in commits[already:end]:
            if (commit.unit_digest != link.child_unit_digest
                or commit.execution_lock_digest
                != link.child_execution_lock_digest):
                raise MachineIntegrityError("causal child execution lock drifted")
        cut = MachineCut.from_commit(commits[end - 1])
        expected = f"machine:{name}:cut:{end}:{cut.cut_digest}"
        if link.child_snapshot_ref != expected:
            raise MachineIntegrityError("causal child snapshot cut drifted")
        outgoing[parent_id].add(name)
        link_cuts.append((parent_id, name, end, link.link_digest, cut.cut_digest))
        # Each accepted child transition is expanded at most once, even when
        # many parents cite progressively longer cuts of the same Machine.
        expanded = expanded_upto.get(name, 0)
        if end > expanded:
            expanded_upto[name] = end
            for commit in commits[expanded:end]:
                pending.extend((name, child) for child in commit.child_links)

    indegree = {machine_id: 0 for machine_id in histories}
    for children in outgoing.values():
        for child in children:
            indegree[child] += 1
    ready = deque(machine_id for machine_id, degree in indegree.items() if not degree)
    visited = 0
    while ready:
        node = ready.popleft()
        visited += 1
        for child in outgoing[node]:
            indegree[child] -= 1
            if indegree[child] == 0:
                ready.append(child)
    if visited != len(histories):
        raise MachineIntegrityError("causal child Machine graph contains a cycle")

    from noetrium_platform.foundation.kernel.unit import NoetriumUnit

    immutable_cut = root.journal_coverage_unit()
    machine_cuts = tuple(
        (name, revision, MachineCut.from_commit(histories[name][revision - 1]).cut_digest)
        for name, revision in validated.items() if revision > 0
    )
    evidence_digest = canonical_digest({
        "schema": "machine.causal-coverage.v1",
        "root_cut": immutable_cut.unit_digest,
        "linked_cuts": tuple(link_cuts),
        "machine_cuts": machine_cuts,
    })
    proof = NoetriumUnit(
        f"machine-causal-coverage:{evidence_digest}",
        schemas=("machine.causal-coverage.v1",),
        attributes={
            "kind": "derived-evidence",
            "coverage_scope": "linked-committed-machine-cuts",
            "root_machine_id": root.identity.machine_id,
            "root_cut_unit_digest": immutable_cut.unit_digest,
            "causal_closure_digest": evidence_digest,
            "verified_child_link_count": len(link_cuts),
            "verified_child_machine_count": len(histories) - 1,
            "verified_machine_cuts": machine_cuts,
            "external_effects_verified": False,
            "referenced_artifacts_verified": False,
            "child_results_verified": False,
        },
    )
    return proof, histories


def verify_machine_causal_closure(
    root: MachineHistoryInspection, journal: MachineJournalPort
) -> "NoetriumUnit":
    """Public proof-only projection of the one authoritative traversal."""
    return _verified_machine_closure(root, journal)[0]



__all__ = ["verify_machine_causal_closure", "iter_causal_accepted_event_units"]


def iter_causal_accepted_event_units(
    root: MachineHistoryInspection, journal: MachineJournalPort
):
    """Stream each event in the verified transitive Machine cut exactly once."""
    from .inspection import iter_machine_commit_event_units

    proof, histories = _verified_machine_closure(root, journal)
    for machine_id, revision, cut_digest in proof.attribute("verified_machine_cuts"):
        commits = histories[machine_id]
        if len(commits) < revision:
            raise MachineIntegrityError("certified Machine cut disappeared")
        if MachineCut.from_commit(commits[revision - 1]).cut_digest != cut_digest:
            raise MachineIntegrityError("certified Machine cut changed during projection")
        yield from iter_machine_commit_event_units(commits[:revision])
