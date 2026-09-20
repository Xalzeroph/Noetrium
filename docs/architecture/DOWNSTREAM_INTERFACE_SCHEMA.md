# Downstream interface schemas

Noetrium exposes reusable systems through generated facades under
noetrium/contracts/systems/. The capability catalog lists ownership, public
modules and symbols. The interface schema adds the callable contract needed by
a downstream method without guessing.

The generated sidecar is:

    noetrium/contracts/interface_schema.json

It is produced from the canonical system registry and public api modules. For
each public export it records the symbol kind, source module, signatures,
parameters, annotations, defaults, return annotations, decorators, class
fields, Protocol methods, documentation and re-export provenance.

Downstream code can inspect it without importing implementation modules:

    from noetrium import api

    schema = api.symbol_schema(
        "environment/minecraft",
        "noetrium_platform.capabilities.environment.minecraft.api.ports",
        "MinecraftBridgePort",
    )

The schema describes the public boundary; providers, credentials and runtime
service lookup remain private. Downstream code uses only `noetrium.api`; generated system facades remain registry-backed implementation material behind that single entrypoint.

After changing a registry descriptor or public api export, run:

    python scripts/update_generated_docs.py

Use --check for the CI invariant. It fails when the generated interface schema
is stale or the public surface has drifted.
