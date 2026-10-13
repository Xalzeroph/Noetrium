# Semantic Boundary: data/query/cross

SYSTEM = "data"
NODE = "data/query/cross"
OWNS = "cross-authority read composition and query federation"
MUST_NOT_OWN = "writes, durable state, and authority mutation"
AUTHORITY = "cross_query"

# This is a real typed semantic boundary, not a generic leaf scaffold.
# Public execution is ResearchResultQuery -> ResearchResultPage through
# ResearchResultQueryPort / ResearchResultSourcePort. It deliberately exposes
# no generic operation handler, checkpoint store, restore surface, or hidden
# mutable state authority.

__all__ = ["AUTHORITY", "MUST_NOT_OWN", "NODE", "OWNS", "SYSTEM"]
