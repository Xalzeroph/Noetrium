# Program Authority

A paper's executable semantics have one authority: its typed Program. Compiler IR, runtime plans, journal events, projections, and schemas are derived views and must never become editable shadow definitions.

## Contract

- Paper-specific semantics stay in downstream Program/rules/handlers.
- Platform Machines interpret typed operations; they do not encode paper names or algorithms.
- A derived representation must retain the Program identity and provenance from which it was compiled.
- Recompilation from the same frozen inputs must not require hand-edited runtime glue.

This invariant keeps Noetrium a research OS and universal-machine substrate rather than a collection of paper-specific runners.
