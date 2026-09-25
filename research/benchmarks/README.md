# Research benchmark assets

This directory contains downstream benchmark-specific assets that consume the generic
Noetrium Study benchmark ABI. It is not a new platform subsystem and owns no runtime
authority.

The platform-generic contracts remain in
`noetrium_platform.research.experimentation.study.api.benchmark`.

A benchmark asset may define:

- immutable benchmark/source revision identity;
- task definitions and task-set cuts;
- canonical split membership and ordering;
- benchmark selection policy and source metadata;
- adapters that materialize those facts into `BenchmarkSourceSpec` and
  `BenchmarkTaskSet`.

A benchmark asset must not implement environment lifecycle (`reset`, `observe`,
`act`, `step`, checkpoint/recovery), model invocation, method policy, or scientific
result authority. Those remain Environment, Model, Method, and Experimentation
responsibilities respectively.

This separation lets many method reproductions reuse one benchmark cut without
copying benchmark facts or coupling benchmark identity to an environment provider.

Run `python scripts/sync_benchmark_manifests.py` to regenerate `research/catalog/benchmark_catalog.json`. `scripts/sync_research_program.py` is the only writer of the final Research Program.\n