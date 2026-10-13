## Summary

Describe the problem and the smallest semantic change made to solve it.

## Ownership and contracts

- Owning subsystem(s):
- Public contract(s) changed or added:
- Durable state / authority affected:
- Downstream behavior affected:

## Evidence

List the exact tests, gates, measurements, or reproduction steps run on this revision.

```text
<commands and results>
```

## Failure and recovery impact

Describe changes to external effects, persistence, replay, recovery, concurrency, or fail-closed behavior. Write `None` only when these concerns are genuinely unaffected.

## Checklist

- [ ] The change is scoped to the correct ownership boundary.
- [ ] Focused regression coverage was added or updated where behavior changed.
- [ ] Documentation changed with the implementation when required.
- [ ] Uncertain external effects remain fail-closed.
- [ ] No unrelated refactor, local state, or experiment output is included.
- [ ] Test claims describe the exact revision actually exercised.
- [ ] Multilingual README files were synchronized if README semantics changed.
- [ ] Intentional compatibility or semantic breaks are documented explicitly.

## Related work

Link issues, Discussions, design documents, or downstream changes that provide necessary context.
