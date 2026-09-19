"""Experiment composition is Program-driven.

Concrete applications bind a frozen CompiledExperimentProgram to an execution
adapter, aggregation implementation and optional TaskGroupPort. No independent
ExperimentRunner facade owns another execution loop.
"""

from noetrium_platform.research.experimentation.api import (
    CompiledExperimentProgram,
    ExperimentProgramBinding,
)

__all__ = ["CompiledExperimentProgram", "ExperimentProgramBinding"]
