"""Declare multi-agent communication as Unit semantics; runtime transport stays internal."""
from noetrium import NoetriumUnit


def build_research() -> NoetriumUnit:
    manager = NoetriumUnit.make_symbol("manager", traits=("research.participant",))
    worker = NoetriumUnit.make_symbol("worker", traits=("research.participant",))
    communication = NoetriumUnit.make_relation(
        (NoetriumUnit.make_endpoint(None, "manager"),),
        (NoetriumUnit.make_endpoint(None, "worker"),),
        "manager-to-worker",
        traits=("research.communication",),
    )
    return NoetriumUnit.make_structure(
        "multi-agent-paper",
        traits=("research.portfolio",),
        symbols=(manager, worker),
        relations=(communication,),
    )


if __name__ == "__main__":
    root = build_research()
    print(root.unit_id, root.unit_digest)
