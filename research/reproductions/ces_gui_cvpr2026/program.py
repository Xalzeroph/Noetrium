from __future__ import annotations
from noetrium.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="ces_gui_cvpr2026"
TITLE="Training High-Level Schedulers with Execution-Feedback Reinforcement Learning for Long-Horizon GUI Automation"
VENUE="CVPR 2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Deng_Training_High-Level_Schedulers_with_Execution-Feedback_Reinforcement_Learning_for_Long-Horizon_GUI_CVPR_2026_paper.html"
BENCHMARK_IDS=("aitz", "amex", "gui-odyssey")
PROTOCOL=("warm-start Coordinator and State Tracker with SFT", "stage RL by training Coordinator first with frozen Executor, then train State Tracker with Coordinator and Executor frozen", "use execution feedback rather than imitation-only scores as the high-level reward signal", "evaluate AITZ, AMEX and GUI-Odyssey long-horizon tasks separately")
METRICS=("task_success", "type_accuracy", "grounding_rate", "state_loss_rate", "steps", "context_tokens")
ABLATIONS=("without Coordinator", "without State Tracker", "without execution-feedback RL", "single-agent unified policy")
PHASES=(
    AgentPhaseSpec("coordinate", "ces.coordinator", "Read the user goal, current screen and compressed task state; emit one atomic sub-instruction."),
    AgentPhaseSpec("execute", "ces.executor", "Use the frozen low-level GUI executor to reason over the sub-instruction and emit the concrete GUI action."),
    AgentPhaseSpec("observe_feedback", "ces.executor", "Capture execution outcome and environment feedback after the GUI action."),
    AgentPhaseSpec("track_state", "ces.state_tracker", "Compress previous state and execution feedback into an updated progress summary."),
    AgentPhaseSpec("replan", "ces.coordinator", "Use the new state summary to continue, revise, or terminate the high-level plan."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="ces_gui_cvpr2026.phase-workflow.v1",phases=PHASES,
    max_cycles=128,
    configuration={"paper_uri":PAPER_URI,"venue":VENUE,"benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL","TITLE","VENUE"]
