# Downstream runtime UX

The common downstream path is: declare Program and Study semantics, compile requirements, open one managed runtime, execute, and consume journal/evidence outputs. Authors should not manually discover GPUs, allocate endpoints, launch model servers, shard trials, maintain controller loops, or wire cleanup.

Repeated infrastructure setup in two or more reproductions is a signal to improve the platform composition surface rather than copy glue into downstream code.
