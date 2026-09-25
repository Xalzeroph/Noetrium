# Authority Decomposition v27

A subsystem is not considered decoupled merely because functions live in different files. Durable mutation authority must be unique and mechanically visible.

## Prompt OS

`GenerationStorageAuthority != ActivePromotionAuthority`

Generation storage may create write-once candidate bytes. Promotion may only verify an existing generation against complete qualification evidence and atomically switch ACTIVE.

## Forensics OS

`AuthoritativeLedger != DisposableIndex`

The index remains reconstructible. Its reader cannot mutate; its writer cannot become the source of truth. Rebuild remains an explicit lease-protected maintenance transaction over verified authoritative ledgers.
