"""Generate the exact, non-degrading recovery sequence for an interrupted model run."""
from noetrium_platform.foundation.kernel.kernel import ImmutableModelIdentity
from noetrium_platform.capabilities.model.serving.api import ModelPhase, ModelRunState
from noetrium_platform.capabilities.model.serving.runtime import RecoveryPlanner


def main() -> None:
    identity = ImmutableModelIdentity(
        logical_name="example-model",
        model_id="example/model",
        revision="example-revision",
        engine="example-engine",
        engine_version="1.0.0",
        dtype="bfloat16",
        quantization=None,
        context_length=32768,
    )
    state = ModelRunState.initial("example_interrupted_run", identity).transition(ModelPhase.INVENTORY).transition(ModelPhase.PREPARE).transition(ModelPhase.INTERRUPTED)
    plan = RecoveryPlanner().plan(state, identity)
    for i, step in enumerate(plan.steps, 1):
        print(f"{i}. {step.value}")


if __name__ == "__main__":
    main()
