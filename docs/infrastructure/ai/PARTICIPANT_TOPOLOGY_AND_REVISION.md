# Participant Topology and Architecture Revision

ROLE04 now exposes immutable scientific identities for multi-participant experiments without moving collaboration policy into Platform.
`AgentCoordinationHub` has been removed. Message routing, inbox state, participant generation and logical scheduling are RuntimeProgram/ParticipantProgram semantics committed through the Machine Journal; `ParticipantTopology` remains immutable scientific identity rather than a routing authority.

`ParticipantTopologyMember` binds participant id, scientific role, participant requirement, accepted binding, and participant architecture revision.
`ParticipantTopology` canonicalizes member ordering so declaration order is not mistaken for scientific topology.
A later topology revision must bind the exact predecessor digest.
`ParticipantTopologyTransition` records explicit add/remove/replace/rebind changes; silent mutation is not an accepted transition.

`ParticipantMessageSchedule` is a distinct identity from the member topology.
It binds topology digest, participant set, zero-based message order, sender/recipients, and causal parent message ids.
Therefore two runs with the same message set but a different schedule have different schedule digests.
Unknown participants, duplicate messages, non-contiguous order, and future/self causal dependencies fail closed.
## Participant architecture revisions

`ParticipantArchitectureRevision` binds a participant to an immutable set of component identities.
Each component separates semantic capability id from implementation digest, configuration digest, and optional state schema.
`ParticipantArchitectureTransition` records typed add/remove/replace/reconfigure operations between exact revision digests.
Checkpoint/resume helpers require exact topology and architecture revision digests and reject incompatible continuation.

These contracts intentionally do not define planner/team policy, routing strategy, scheduling algorithm, or runtime service placement.
They are producer-owned scientific identity/provenance facts for ROLE03 replay, checkpoint and evidence binding.
Downstream projects may define arbitrary collaboration and cognition modules while reusing these identities without adding a Platform registry entry.
## Transactional revision preparation

Dynamic revision now has a separate transaction layer instead of treating a
transition declaration as proof of commit.

`ParticipantRevisionProposal` binds the exact predecessor, open update-contract
identity, reason, optional migration adapter, and evidence references.
`PreparedParticipantRevision` carries the typed predecessor, typed candidate,
and typed transition together with recovery anchor, validation plan, and
preparation generation. Construction verifies all three digests agree.

`ParticipantRevisionCommit` is a distinct receipt produced only after validation
evidence is supplied. Its successor identity is the candidate carried by the
prepared object; a caller cannot swap in another successor at commit time.

`ParticipantStateRevision` and `ParticipantStateTransition` cover online policy,
memory, learner-state, or other state-changing updates that do not require an
architecture component replacement. Update-contract ids remain project-extensible.
A crash after prepare therefore leaves explicit prepared state rather than an
ambiguous live mutation.
