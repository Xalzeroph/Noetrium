# Managed runtime controller supervision

`ManagedResearchRuntime` owns lifecycle supervision, not scientific semantics.

## Invariants

- Background controller failure must surface through `assert_healthy()` and shutdown.
- Controller restart must never mutate compiled run, trial, treatment, model-role, or evidence identity.
- Controller tasks remain infrastructure effects and must not become Machine Journal scientific facts unless they produce a typed effect receipt consumed by a run.
- A closed runtime cannot admit new controller work.
- Supervision must remain generic; paper-specific recovery belongs in the paper Program.
