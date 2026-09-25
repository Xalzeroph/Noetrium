# Public runtime facade

The public facade exposes the smallest stable composition entry point needed by downstream research. Internal controllers, stores, schedulers, lease managers, replica managers, and worker topology remain behind typed platform contracts.

Public schema and stubs are generated from canonical exports. Downstream authors should not import infrastructure implementation modules to start a research runtime.
