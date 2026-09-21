# Managed runtime downstream minimalism

Repeated runtime glue is a platform defect.

- A paper should normally provide Program, Study, and genuinely novel semantics only.
- Resource discovery, admission, model placement, sharding, receipts, recovery, observability, and shutdown are platform responsibilities.
- Repeated downstream wiring should be promoted to the smallest stable typed abstraction.
- Promotion must not move paper-private concepts into the kernel.
