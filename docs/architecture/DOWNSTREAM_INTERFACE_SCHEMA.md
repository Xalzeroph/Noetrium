# Downstream interface schemas

Noetrium exposes one downstream surface: `noetrium.api`. Generated system facades remain internal registry material. The capability catalog and interface schema provide machine-readable ownership and callable contracts behind that single entrypoint.

The generated sidecar is:

    noetrium/contracts/interface_schema.json

It is produced from the canonical system registry and public api modules. For
each public export it records the symbol kind, source module, signatures,
parameters, annotations, defaults, return annotations, decorators, class
fields, Protocol methods, documentation and re-export provenance.

Downstream code can inspect it without importing implementation modules:

    from noetrium import api

    schemas = api.describe("MinecraftBridgePort")

The schema describes the public boundary; providers, credentials and runtime
service lookup remain private. Downstream code uses only `noetrium.api`; generated system facades remain registry-backed implementation material behind that single entrypoint.

After changing a registry descriptor or public api export, run:

    python scripts/update_generated_docs.py

Use --check for the CI invariant. It fails when the generated interface schema
is stale or the public surface has drifted.
