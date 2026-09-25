# vNext Boundary: portfolio/project

SYSTEM = "portfolio"
NODE = "portfolio/project"
OWNS = "project metadata, configuration references and lifecycle"
MUST_NOT_OWN = "experiment/run execution state"
AUTHORITY = "project_metadata"

# This module is intentionally declarative. Concrete behavior belongs in runtime/providers.
