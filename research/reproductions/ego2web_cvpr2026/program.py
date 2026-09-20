from __future__ import annotations
from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
METHOD_ID="ego2web_cvpr2026"
PAPER_URI="https://openaccess.thecvf.com/content/CVPR2026/html/Yu_Ego2Web_A_Web_Agent_Benchmark_Grounded_in_Egocentric_Videos_CVPR_2026_paper.html"
BENCHMARK_IDS=("ego2web",)
PROTOCOL=("preserve human-verified video-task pairs and task categories", "evaluate video understanding, web planning and interaction jointly", "run final-paper task-design ablations", "validate automatic judge agreement against human labels")
METRICS=("task_success", "video_understanding", "web_execution_success", "judge_human_agreement", "steps", "latency")
ABLATIONS=("without video evidence", "weakened video understanding", "judge alternatives")
PHASES=(
    AgentPhaseSpec("video_understand", "ego2web.agent", "Extract task-relevant evidence from first-person video."),
    AgentPhaseSpec("goal_ground", "ego2web.agent", "Ground the online task in observed physical-world evidence."),
    AgentPhaseSpec("web_plan", "ego2web.agent", "Plan the required online workflow."),
    AgentPhaseSpec("web_execute", "ego2web.agent", "Execute web actions under the frozen benchmark environment."),
    AgentPhaseSpec("judge", "ego2web.judge", "Score completion with Ego2WebJudge and retain judge evidence."),
)
METHOD_PROGRAM=AgentMethodSpec(
    method_id=METHOD_ID,implementation_version="2026-paper-protocol",schema_version="ego2web_cvpr2026.phase-workflow.v1",phases=PHASES,
    configuration={"paper_uri":PAPER_URI,"venue":"CVPR 2026","benchmark_ids":BENCHMARK_IDS,"protocol":PROTOCOL,"ablations":ABLATIONS},
    evidence_obligations=(METHOD_ID+".phase-transcript",METHOD_ID+".model-tool-receipts",METHOD_ID+".metric-artifacts"),
    metric_names=METRICS,artifact_kinds=(METHOD_ID+"_trajectory",METHOD_ID+"_experiment_manifest"),
).compile()
__all__=["ABLATIONS","BENCHMARK_IDS","METHOD_ID","METHOD_PROGRAM","METRICS","PAPER_URI","PHASES","PROTOCOL"]
