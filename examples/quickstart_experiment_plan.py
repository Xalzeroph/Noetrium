from __future__ import annotations

from noetrium import api


def _view(call):
    return {
        "instruction": "Solve the assigned research task.",
        "input": call.input_value,
        "state": call.state,
    }


def _return(call):
    return {"value": call.previous_value}


def configure_method(method):
    method.agent(
        "solve",
        "quickstart.solve",
        "solver",
        ("return",),
        view=_view,
        evidence=("quickstart.solve",),
    )
    method.return_node("return", "quickstart.return", _return)


def build_research() -> api.ResearchPortfolio:
    portfolio = api.ResearchPortfolioBuilder("noetrium-quickstart")
    program = portfolio.program("quickstart-paper")
    program.method(
        "method",
        configure_method,
        entrypoint="solve",
        metrics=("success_rate", "steps"),
    )
    program.model("solver")
    program.benchmark("hello-agent-research")
    program.experiment(
        "experiment",
        definitions=("method", "solver", "hello-agent-research"),
        config={
            "variants": (
                {"id": "control", "temperature": 0.0},
                {"id": "treatment", "temperature": 0.2},
            ),
            "repetitions": 3,
            "seeds": ("seed-0", "seed-1", "seed-2"),
        },
    )
    return portfolio.freeze()


def main() -> None:
    portfolio = build_research()
    program = portfolio.programs[0]
    print(f"portfolio={portfolio.portfolio_id}")
    print(f"program={program.program_id}")
    print(f"program_digest={program.program_digest}")
    print(f"portfolio_digest={portfolio.portfolio_digest}")


if __name__ == "__main__":
    main()
