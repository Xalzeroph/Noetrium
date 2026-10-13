from __future__ import annotations

from dataclasses import dataclass

from .source import CODE_AS_POLICIES_AUDITED_COMMIT


@dataclass(frozen=True, slots=True)
class CodeAsPoliciesFidelity:
    paper_uri: str = "https://arxiv.org/abs/2209.07753"
    source_repository: str = (
        "https://github.com/google-research/google-research"
    )
    audited_commit: str = CODE_AS_POLICIES_AUDITED_COMMIT

    hierarchical_code_generation: bool = True
    recursively_defines_undefined_functions: bool = True
    direct_name_calls_only: bool = True
    assignment_overrides_call_signature: bool = True
    child_helpers_generated_before_parent_rebind: bool = True
    fixed_and_variable_namespace_split: bool = True
    session_history_supported: bool = True
    context_injection_supported: bool = True

    tabletop_temperature: float = 0.0
    tabletop_max_tokens: int = 512
    tabletop_query_prefix: str = "# "
    tabletop_query_suffix: str = "."
    tabletop_stop_tokens: tuple[str, ...] = ("#", "objects = [")
    function_query_prefix: str = "# define function: "
    function_query_suffix: str = "."
    function_stop_tokens: tuple[str, ...] = ("# define", "# example")

    original_exec_banned_phrases: tuple[str, ...] = ("import", "__")
    original_exec_shadows: tuple[str, ...] = ("exec", "eval")
    original_exec_is_qualified_sandbox: bool = False
    generated_program_execution_is_effectful: bool = True

    post_paper_chain_of_code_included: bool = False
    post_paper_lmpc_included: bool = False

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError(
                "Code as Policies audited commit must be a git SHA"
            )
        if not all((
            self.hierarchical_code_generation,
            self.recursively_defines_undefined_functions,
            self.direct_name_calls_only,
            self.assignment_overrides_call_signature,
            self.child_helpers_generated_before_parent_rebind,
            self.fixed_and_variable_namespace_split,
            self.session_history_supported,
            self.context_injection_supported,
        )):
            raise ValueError("Code as Policies core semantics drifted")
        if (self.tabletop_temperature, self.tabletop_max_tokens) != (0.0, 512):
            raise ValueError("Code as Policies generation defaults drifted")
        if self.tabletop_stop_tokens != ("#", "objects = ["):
            raise ValueError("Code as Policies tabletop stop tokens drifted")
        if self.function_stop_tokens != ("# define", "# example"):
            raise ValueError("Code as Policies function stop tokens drifted")
        if self.original_exec_banned_phrases != ("import", "__"):
            raise ValueError("Code as Policies historical exec filter drifted")
        if self.original_exec_shadows != ("exec", "eval"):
            raise ValueError("Code as Policies historical exec shadowing drifted")
        if self.original_exec_is_qualified_sandbox:
            raise ValueError(
                "paper-era exec_safe must not be relabelled as isolation"
            )
        if self.post_paper_chain_of_code_included or self.post_paper_lmpc_included:
            raise ValueError(
                "post-paper Chain-of-Code/LMPC semantics must not be backported"
            )


CODE_AS_POLICIES_FIDELITY = CodeAsPoliciesFidelity()

__all__ = [
    "CODE_AS_POLICIES_FIDELITY",
    "CodeAsPoliciesFidelity",
]
