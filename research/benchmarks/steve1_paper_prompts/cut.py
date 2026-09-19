from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

STEVE1_PAPER_PROMPTS_BENCHMARK_ID = "steve1-paper-prompts"
STEVE1_PAPER_PROMPTS_REPOSITORY = "https://github.com/Shalev-Lifshitz/STEVE-1"
STEVE1_PAPER_PROMPTS_COMMIT = "874cf9b808c9dd0a5d4446ef2e008e3789c55c57"
STEVE1_PAPER_PROMPTS_PATH = "steve1/run_agent/paper_prompts.py"
STEVE1_PAPER_PROMPTS_BLOB_SHA = "74f7522f9030a511e1f5c35c075adbe8f399047c"
STEVE1_PAPER_PROMPT_SCHEMA_ID = "steve1.paper-prompt-cell.v1"
STEVE1_PAPER_PROMPT_NAMES = (
    "dig",
    "dirt",
    "sky",
    "leaves",
    "wood",
    "seeds",
    "flower",
    "explore",
    "swim",
    "underwater",
    "inventory",
)
STEVE1_TEXT_PROMPTS = (
    ("dig", "dig as far as possible"),
    ("dirt", "get dirt, dig hole, dig dirt, gather a ton of dirt, collect dirt"),
    ("sky", "look at the sky"),
    ("leaves", "break leaves"),
    ("wood", "chop down the tree, gather wood, pick up wood, chop it down, break tree"),
    ("seeds", "break tall grass, break grass, collect seeds, punch the ground, run around in circles getting seeds from bushes"),
    ("flower", "break a flower"),
    ("explore", "go explore"),
    ("swim", "go swimming"),
    ("underwater", "go underwater"),
    ("inventory", "open inventory"),
)
STEVE1_PROMPT_MODALITIES = ("text", "visual")
STEVE1_RELEASED_PROMPT_COUNT = 11
STEVE1_RELEASED_CELL_COUNT = 22
STEVE1_ALL_SPLIT = "all-22"
STEVE1_TEXT_SPLIT = "text-11"
STEVE1_VISUAL_SPLIT = "visual-11"


def steve1_paper_prompt_source_digest() -> str:
    return canonical_digest({
        "repository": STEVE1_PAPER_PROMPTS_REPOSITORY,
        "commit": STEVE1_PAPER_PROMPTS_COMMIT,
        "path": STEVE1_PAPER_PROMPTS_PATH,
        "git_blob_sha": STEVE1_PAPER_PROMPTS_BLOB_SHA,
        "prompt_names": STEVE1_PAPER_PROMPT_NAMES,
        "text_prompts": STEVE1_TEXT_PROMPTS,
        "modalities": STEVE1_PROMPT_MODALITIES,
        "visual_prompt_locator": "data/visual_prompt_embeds/{prompt_name}.pkl",
        "runner": "steve1/run_agent/run_agent.py",
        "programmatic_evaluator": "steve1/run_agent/programmatic_eval.py",
    })


def steve1_paper_prompt_revision() -> str:
    return (
        f"steve1-prompts@{STEVE1_PAPER_PROMPTS_COMMIT}:"
        f"{steve1_paper_prompt_source_digest()}"
    )


def build_steve1_paper_prompt_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=STEVE1_PAPER_PROMPTS_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=steve1_paper_prompt_revision(),
        locator=STEVE1_PAPER_PROMPTS_REPOSITORY,
        content_digest=steve1_paper_prompt_source_digest(),
        metadata={
            "paper_prompts_path": STEVE1_PAPER_PROMPTS_PATH,
            "paper_prompts_git_blob_sha": STEVE1_PAPER_PROMPTS_BLOB_SHA,
            "semantic_prompt_count": str(STEVE1_RELEASED_PROMPT_COUNT),
            "evaluation_cell_count": str(STEVE1_RELEASED_CELL_COUNT),
            "modalities": "text,visual",
            "visual_prompt_embeddings": "released-data-artifacts",
            "paper_13_task_claim": "not-identified-by-released-prompt-table",
        },
    )


def build_steve1_paper_prompt_cut() -> BenchmarkTaskSet:
    source = build_steve1_paper_prompt_source()
    prompt_map = dict(STEVE1_TEXT_PROMPTS)
    tasks: list[TaskDefinition] = []
    text_ids: list[str] = []
    visual_ids: list[str] = []
    for modality in STEVE1_PROMPT_MODALITIES:
        for name in STEVE1_PAPER_PROMPT_NAMES:
            task_id = f"steve1:{modality}:{name}"
            if modality == "text":
                prompt_payload = {
                    "name": name,
                    "modality": modality,
                    "text": prompt_map[name],
                }
                text_ids.append(task_id)
            else:
                prompt_payload = {
                    "name": name,
                    "modality": modality,
                    "visual_prompt_locator": (
                        f"data/visual_prompt_embeds/{name}.pkl"
                    ),
                }
                visual_ids.append(task_id)

            content_digest = canonical_digest({
                "source_digest": source.content_digest,
                "prompt": prompt_payload,
                "runner_gameplay_length": 1000,
                "runner_fps": 30,
                "text_cond_scale": 6.0,
                "visual_cond_scale": 7.0,
                "metrics": ("log", "dirt", "seed", "travel_dist"),
            })
            tasks.append(
                TaskDefinition(
                    task_id=task_id,
                    revision_id=STEVE1_PAPER_PROMPTS_COMMIT,
                    family=f"steve1_{modality}_prompt",
                    schema_id=STEVE1_PAPER_PROMPT_SCHEMA_ID,
                    content_digest=content_digest,
                    lineage_refs=(
                        f"paper-prompt:{name}",
                        f"prompt-modality:{modality}",
                        f"source-blob:{STEVE1_PAPER_PROMPTS_BLOB_SHA}",
                        "runner-gameplay-length:1000",
                        "programmatic-metrics:log,dirt,seed,travel_dist",
                    ),
                    package=TaskPackageSpec(
                        package_schema_id=(
                            "steve1.minecraft.raw-control-prompt.v1"
                        ),
                        instruction_digest=canonical_digest(prompt_payload),
                        environment_requirement_id=(
                            "environment.minecraft.raw-control"
                        ),
                        verifier_requirement_id=(
                            "benchmark.steve1.programmatic-evaluator"
                        ),
                        verifier_isolation=TaskVerifierIsolation.SEPARATE,
                    ),
                )
            )

    if len(tasks) != STEVE1_RELEASED_CELL_COUNT:
        raise RuntimeError("STEVE-1 released prompt cell count drifted")
    tasks = sorted(tasks, key=lambda row: row.task_id)
    all_ids = tuple(row.task_id for row in tasks)
    return BenchmarkTaskSet(
        benchmark_id=STEVE1_PAPER_PROMPTS_BENCHMARK_ID,
        revision_id=source.revision_id,
        source_digest=source.content_digest,
        task_schema_id=STEVE1_PAPER_PROMPT_SCHEMA_ID,
        tasks=tuple(tasks),
        splits=(
            TaskSetSplit(STEVE1_ALL_SPLIT, all_ids),
            TaskSetSplit(STEVE1_TEXT_SPLIT, tuple(text_ids)),
            TaskSetSplit(STEVE1_VISUAL_SPLIT, tuple(visual_ids)),
        ),
        selection_policy_digest=canonical_digest({
            "source_digest": source.content_digest,
            "semantic_prompt_count": STEVE1_RELEASED_PROMPT_COUNT,
            "cell_count": STEVE1_RELEASED_CELL_COUNT,
            "text_task_ids": tuple(text_ids),
            "visual_task_ids": tuple(visual_ids),
        }),
    )


def bind_steve1_paper_prompt_cut() -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_steve1_paper_prompt_source(),
        task_set=build_steve1_paper_prompt_cut(),
    )


__all__ = [
    "STEVE1_ALL_SPLIT",
    "STEVE1_PAPER_PROMPT_NAMES",
    "STEVE1_PAPER_PROMPT_SCHEMA_ID",
    "STEVE1_PAPER_PROMPTS_BENCHMARK_ID",
    "STEVE1_PAPER_PROMPTS_BLOB_SHA",
    "STEVE1_PAPER_PROMPTS_COMMIT",
    "STEVE1_PAPER_PROMPTS_PATH",
    "STEVE1_PAPER_PROMPTS_REPOSITORY",
    "STEVE1_PROMPT_MODALITIES",
    "STEVE1_RELEASED_CELL_COUNT",
    "STEVE1_RELEASED_PROMPT_COUNT",
    "STEVE1_TEXT_PROMPTS",
    "STEVE1_TEXT_SPLIT",
    "STEVE1_VISUAL_SPLIT",
    "bind_steve1_paper_prompt_cut",
    "build_steve1_paper_prompt_cut",
    "build_steve1_paper_prompt_source",
    "steve1_paper_prompt_revision",
    "steve1_paper_prompt_source_digest",
]
