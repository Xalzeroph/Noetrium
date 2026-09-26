from __future__ import annotations

METHOD_ID="hats_cvpr2026"

TITLE="HATS: Hardness-Aware Trajectory Synthesis for GUI Agents"

VENUE="CVPR 2026"

PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Shao_HATS_Hardness-Aware_Trajectory_Synthesis_for_GUI_Agents_CVPR_2026_paper.html"

BENCHMARK_IDS=("androidworld", "webarena")

PROTOCOL=("reproduce hardness-driven MCTS rather than uniform random exploration", "replay every synthesized instruction before corpus admission", "preserve action-level reconstruction recall threshold R>=0.7", "feed misalignment signals back into future exploration hardness")

METRICS=("task_success", "trajectory_alignment_recall", "accepted_trajectory_count", "semantic_ambiguous_coverage", "androidworld_score", "webarena_score")

ABLATIONS=("uniform exploration", "without alignment-guided refinement", "without hardness feedback", "one-shot instruction synthesis")

PHASES = (
    {
        "phase_id": 'estimate_hardness',
        "role": 'hats.explorer',
        "instruction": 'Estimate semantic ambiguity and under-representation of candidate GUI actions.',
    },
    {
        "phase_id": 'hd_mcts_select',
        "role": 'hats.explorer',
        "instruction": 'Select and expand GUI states with hardness-driven UCB Monte Carlo Tree Search.',
    },
    {
        "phase_id": 'synthesize_instruction',
        "role": 'hats.refiner',
        "instruction": 'Generate an instruction from the explored action trajectory.',
    },
    {
        "phase_id": 'replay_instruction',
        "role": 'hats.refiner',
        "instruction": 'Replay the synthesized instruction in the environment to reconstruct the trajectory.',
    },
    {
        "phase_id": 'measure_alignment',
        "role": 'hats.refiner',
        "instruction": 'Measure action-level reconstruction recall between instruction replay and source trajectory.',
    },
    {
        "phase_id": 'refine_or_accept',
        "role": 'hats.refiner',
        "instruction": 'Inject missing contextual cues until alignment reaches the paper threshold, then admit the trajectory.',
    },
)

METHOD_SPEC = {
    "method_id": METHOD_ID,
    "version": '2026-paper-protocol',
    "semantic_contract": 'hats_cvpr2026.phase-workflow.v1',
    "entrypoint": PHASES[0]["phase_id"],
}

def configure_method(method):
    method.configure({'paper_uri': PAPER_URI, 'venue': VENUE, 'benchmark_ids': BENCHMARK_IDS, 'protocol': PROTOCOL, 'ablations': ABLATIONS})
    method.policy(evidence=(METHOD_ID + '.phase-transcript', METHOD_ID + '.model-tool-receipts', METHOD_ID + '.metric-artifacts'), metrics=METRICS, artifacts=(METHOD_ID + '_trajectory', METHOD_ID + '_experiment_manifest'))
    method.phases(PHASES, max_cycles=32)

METHOD_CONFIGURER = configure_method
METHOD_ENTRYPOINT = METHOD_SPEC["entrypoint"]
METHOD_CONFIGURER_ARGS = ()
METHOD_CONFIGURER_KWARGS = {}

__all__ = ["METHOD_SPEC", "configure_method", "METHOD_CONFIGURER", "METHOD_ENTRYPOINT", "METHOD_CONFIGURER_ARGS", "METHOD_CONFIGURER_KWARGS", 'PHASES']
