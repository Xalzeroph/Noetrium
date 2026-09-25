# Managed runtime public facade

The public facade exposes composition, not internal managers.

- Downstream code should bind/start/close managed execution through stable typed entry points.
- Internal controller, lease, scheduler, and replica implementations remain replaceable.
- Public API projection is generated from canonical exports.
- Common execution plumbing belongs upstream, not in paper Programs.
