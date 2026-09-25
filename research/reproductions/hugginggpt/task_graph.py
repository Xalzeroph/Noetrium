from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, replace
import re


_GENERATED_PATTERN = re.compile(r"<GENERATED>-(\d+)")


@dataclass(frozen=True, slots=True)
class HuggingGPTTask:
    task_id: int
    task: str
    args: tuple[tuple[str, str], ...]
    dependencies: tuple[int, ...] = ()

    def __post_init__(self) -> None:
        if type(self.task_id) is not int or self.task_id < 0:
            raise ValueError("HuggingGPT task_id must be a non-negative integer")
        if not isinstance(self.task, str) or not self.task.strip():
            raise ValueError("HuggingGPT task must be non-empty")
        if not isinstance(self.args, tuple) or any(
            not isinstance(key, str)
            or not key.strip()
            or not isinstance(value, str)
            for key, value in self.args
        ):
            raise TypeError("HuggingGPT task args must be canonical string pairs")
        if not isinstance(self.dependencies, tuple) or any(
            type(dep) is not int or dep < 0 for dep in self.dependencies
        ):
            raise TypeError("HuggingGPT dependencies must be non-negative integer tuple")
        if len(self.dependencies) != len(set(self.dependencies)):
            raise ValueError("HuggingGPT dependencies must not contain duplicates")

    @property
    def args_map(self) -> dict[str, str]:
        return dict(self.args)


def infer_hugginggpt_dependencies(args: Mapping[str, str]) -> tuple[int, ...]:
    """Infer upstream task ids from paper-era `<GENERATED>-N` argument references."""

    if not isinstance(args, Mapping):
        raise TypeError("HuggingGPT args must be a mapping")
    dependencies: set[int] = set()
    for key, value in args.items():
        if not isinstance(key, str) or not key.strip() or not isinstance(value, str):
            raise TypeError("HuggingGPT args must map non-empty strings to strings")
        dependencies.update(int(match.group(1)) for match in _GENERATED_PATTERN.finditer(value))
    return tuple(sorted(dependencies))


def build_hugginggpt_task(
    *,
    task_id: int,
    task: str,
    args: Mapping[str, str],
) -> HuggingGPTTask:
    pairs = tuple(sorted(args.items()))
    return HuggingGPTTask(
        task_id=task_id,
        task=task,
        args=pairs,
        dependencies=infer_hugginggpt_dependencies(args),
    )


def unfold_hugginggpt_generated_arguments(task: HuggingGPTTask) -> tuple[HuggingGPTTask, ...]:
    """Reproduce JARVIS unfolding when one argument names multiple generated resources."""

    if not isinstance(task, HuggingGPTTask):
        raise TypeError("HuggingGPT task must be typed")
    for key, value in task.args:
        references = tuple(_GENERATED_PATTERN.fullmatch(part.strip()) for part in value.split(","))
        if len(references) <= 1 or any(reference is None for reference in references):
            continue
        rows: list[HuggingGPTTask] = []
        for reference, part in zip(references, value.split(","), strict=True):
            assert reference is not None
            args = task.args_map
            args[key] = part.strip()
            dependency = int(reference.group(1))
            rows.append(
                replace(
                    task,
                    args=tuple(sorted(args.items())),
                    dependencies=(dependency,),
                )
            )
        return tuple(rows)
    return (task,)


def hugginggpt_ready_task_ids(
    tasks: tuple[HuggingGPTTask, ...],
    completed_task_ids: tuple[int, ...],
) -> tuple[int, ...]:
    if not isinstance(tasks, tuple) or any(not isinstance(task, HuggingGPTTask) for task in tasks):
        raise TypeError("HuggingGPT tasks must be a typed tuple")
    if not isinstance(completed_task_ids, tuple) or any(
        type(task_id) is not int or task_id < 0 for task_id in completed_task_ids
    ):
        raise TypeError("completed_task_ids must be a non-negative integer tuple")
    completed = set(completed_task_ids)
    return tuple(
        task.task_id
        for task in sorted(tasks, key=lambda row: row.task_id)
        if set(task.dependencies).issubset(completed)
    )


__all__ = [
    "HuggingGPTTask",
    "build_hugginggpt_task",
    "hugginggpt_ready_task_ids",
    "infer_hugginggpt_dependencies",
    "unfold_hugginggpt_generated_arguments",
]
