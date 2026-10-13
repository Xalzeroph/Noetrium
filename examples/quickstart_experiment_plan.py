"""Minimal Unit-native research declaration."""
from noetrium import NoetriumUnit


def _solve(call):
    return {"value": call.input_value}


def build_research() -> NoetriumUnit:
    method = NoetriumUnit.make_symbol(
        "method",
        traits=("research.method",),
        implementation=NoetriumUnit.from_python_callable("method.impl", _solve),
        parameters={"entrypoint": "solve", "metrics": ("success_rate", "steps")},
    )
    model = NoetriumUnit.make_symbol(
        "solver",
        traits=("research.model",),
        parameters={"role": "solver"},
    )
    benchmark = NoetriumUnit.make_symbol(
        "hello-agent-research",
        traits=("research.benchmark",),
    )
    experiment = NoetriumUnit.make_structure(
        "experiment",
        traits=("research.experiment",),
        symbols=(method, model, benchmark),
        parameters={
            "variants": (
                {"id": "control", "temperature": 0.0},
                {"id": "treatment", "temperature": 0.2},
            ),
            "repetitions": 3,
            "seeds": ("seed-0", "seed-1", "seed-2"),
        },
    )
    return NoetriumUnit.make_structure(
        "noetrium-quickstart",
        traits=("research.portfolio",),
        members=(experiment,),
    )


def main() -> None:
    root = build_research()
    print(f"root={root.unit_id}")
    print(f"digest={root.unit_digest}")


if __name__ == "__main__":
    main()
