from __future__ import annotations

from dataclasses import dataclass


CAMEL_PAPER_ERA_COMMIT = "6915c00a69447fecb796702dc30dec03681173ac"


@dataclass(frozen=True, slots=True)
class CAMELRolePlayingFidelity:
    """NeurIPS-2023 CAMEL AI-Society role-playing semantics.

    Framework constructor defaults and the actual AI-Society data-generation
    protocol are recorded separately. Formal reproduction follows the released
    data-generation script, not convenience defaults in RolePlaying.__init__.
    """

    paper_uri: str = (
        "https://proceedings.neurips.cc/paper_files/paper/2023/file/"
        "a3621ee907def47c1b952ade25c67698-Paper-Conference.pdf"
    )
    source_repository: str = "https://github.com/camel-ai/camel"
    audited_commit: str = CAMEL_PAPER_ERA_COMMIT
    role_playing_artifact: str = "camel/agent/role_playing.py"
    generator_artifact: str = "camel/generator.py"
    chat_agent_artifact: str = "camel/agent/chat_agent.py"
    data_generation_artifact: str = "examples/ai_society/role_playing_multiprocess.py"
    task_agent_artifact: str = "camel/agent/task_agent.py"

    participant_count: int = 2
    required_roles: tuple[str, ...] = ("assistant", "user")
    independent_agent_histories: bool = True
    reset_both_agents_before_init: bool = True
    turn_order: tuple[str, ...] = ("user_agent", "assistant_agent")

    # Generic RolePlaying defaults.
    constructor_task_specification_default: bool = True
    constructor_task_planning_default: bool = False

    # Actual released AI-Society generation protocol.
    paper_task_specification: bool = True
    paper_task_planning: bool = True
    task_specifier_temperature: float = 1.4
    default_chat_temperature: float = 0.2
    task_specifier_word_limit: int = 50
    max_saved_messages: int = 40
    tasks_per_role_pair: int = 10
    assistant_role_count: int = 50
    user_role_count: int = 50
    conversation_population: int = 25_000

    user_no_instruction_threshold: int = 3
    assistant_instruction_threshold: int = 1
    repeated_word_threshold: int = 4
    repeated_words: tuple[str, ...] = (
        "goodbye",
        "good bye",
        "thank",
        "bye",
        "welcome",
        "language model",
    )
    instruction_marker: str = "Instruction:"
    task_done_token: str = "<CAMEL_TASK_DONE>"
    repeat_threshold_breaks_inner_loop_only: bool = True

    role_conditioned_system_messages: bool = True
    task_conditioned_system_messages: bool = True
    hidden_assistant_bootstrap_call: bool = True
    token_overflow_terminates_agent: bool = True

    assistant_roles_blob: str = "a03be3fa45fd4c1bfb2ff14704ea06c7b2f6517e"
    user_roles_blob: str = "2ad6f9274da46161d277201cd0c19f775fb69692"
    assistant_prompt_blob: str = "a713005986cef98d56fd9083d5fd080938f3a79e"
    user_prompt_blob: str = "6d2294d63bcd9326f8f5aa5d837ad9bd757253b1"
    task_specify_prompt_blob: str = "43a224b203b2b82139726bc939024fac43d5404d"
    generate_tasks_prompt_blob: str = "2e8f18f2bd4baa460a8edf23f27499bc7ee6adcb"

    paper_agent_evaluation_sample_size: int = 100
    single_shot_baseline_model: str = "gpt-3.5-turbo"
    pairwise_judges: tuple[str, ...] = ("human", "gpt-4")

    def __post_init__(self) -> None:
        if len(self.audited_commit) != 40:
            raise ValueError("CAMEL audited commit must be a git SHA")
        if self.participant_count != 2 or self.required_roles != ("assistant", "user"):
            raise ValueError("paper-era CAMEL AI Society requires one assistant and one user")
        if (
            not self.constructor_task_specification_default
            or self.constructor_task_planning_default
        ):
            raise ValueError("CAMEL generic RolePlaying constructor defaults drifted")
        if not self.paper_task_specification or not self.paper_task_planning:
            raise ValueError("CAMEL AI-Society generation must specify and plan tasks")
        if self.task_specifier_temperature != 1.4 or self.default_chat_temperature != 0.2:
            raise ValueError("CAMEL paper-era decoding temperatures drifted")
        if (
            self.assistant_role_count
            * self.user_role_count
            * self.tasks_per_role_pair
            != self.conversation_population
        ):
            raise ValueError("CAMEL AI-Society population cardinality drifted")
        if self.max_saved_messages != 40:
            raise ValueError("CAMEL AI-Society message limit drifted")
        if self.turn_order != ("user_agent", "assistant_agent"):
            raise ValueError("CAMEL alternating role-play order drifted")
        if (
            self.user_no_instruction_threshold != 3
            or self.assistant_instruction_threshold != 1
            or self.repeated_word_threshold != 4
        ):
            raise ValueError("CAMEL released termination thresholds drifted")
        if not self.repeat_threshold_breaks_inner_loop_only:
            raise ValueError("CAMEL released repeat-word control-flow behavior drifted")
        if not all(
            (
                self.independent_agent_histories,
                self.reset_both_agents_before_init,
                self.role_conditioned_system_messages,
                self.task_conditioned_system_messages,
                self.hidden_assistant_bootstrap_call,
                self.token_overflow_terminates_agent,
            )
        ):
            raise ValueError("CAMEL dialogue lifecycle semantics drifted")
        for blob in (
            self.assistant_roles_blob,
            self.user_roles_blob,
            self.assistant_prompt_blob,
            self.user_prompt_blob,
            self.task_specify_prompt_blob,
            self.generate_tasks_prompt_blob,
        ):
            if len(blob) != 40 or any(ch not in "0123456789abcdef" for ch in blob):
                raise ValueError("CAMEL paper artifact identity must be a git blob SHA")


CAMEL_ROLE_PLAYING_FIDELITY = CAMELRolePlayingFidelity()


__all__ = [
    "CAMEL_PAPER_ERA_COMMIT",
    "CAMEL_ROLE_PLAYING_FIDELITY",
    "CAMELRolePlayingFidelity",
]
