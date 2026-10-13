"""Declare an environment requirement without exposing provider catalogs."""
from noetrium import NoetriumUnit


def build_research() -> NoetriumUnit:
    environment = NoetriumUnit.make_symbol(
        "environment",
        traits=("research.environment",),
        parameters={"capabilities": ("observe", "act")},
    )
    return NoetriumUnit.make_structure(
        "environment-paper",
        traits=("research.portfolio",),
        symbols=(environment,),
    )


if __name__ == "__main__":
    root = build_research()
    print(root.unit_id, root.unit_digest)
