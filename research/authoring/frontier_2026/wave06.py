from __future__ import annotations

from noetrium_platform.research.execution.workflow.api import AgentMethodSpec, AgentPhaseSpec
from research.authoring.frontier_2026.study import PaperStudySpec


def _paper(method_id, title, venue, uri, benchmarks, phases, metrics, ablations, protocol):
    spec = PaperStudySpec(method_id=method_id, title=title, venue=venue, paper_uri=uri, benchmark_ids=benchmarks, protocol=protocol, metrics=metrics, ablations=ablations)
    method = AgentMethodSpec(
        method_id=method_id,
        implementation_version="2026-paper-protocol",
        schema_version=f"{method_id}.phase-workflow.v1",
        phases=tuple(AgentPhaseSpec(*row) for row in phases),
        max_cycles=128,
        configuration={"paper_uri": uri, "venue": venue, "benchmark_ids": benchmarks, "protocol": protocol, "ablations": ablations},
        evidence_obligations=(f"{method_id}.phase-transcript", f"{method_id}.model-tool-receipts", f"{method_id}.metric-artifacts"),
        metric_names=metrics,
        artifact_kinds=(f"{method_id}_trajectory", f"{method_id}_experiment_manifest", f"{method_id}_result_table"),
    )
    return method.compile(), spec


PAPERS = {}
def _add(key, *args): PAPERS[key] = _paper(key, *args)


_add(
    "vismem_cvpr2026",
    "VisMem: Latent Vision Memory Unlocks Potential of Vision-Language Models",
    "CVPR 2026",
    "https://openaccess.thecvf.com/content/CVPR2026/html/Yu_VisMem_Latent_Vision_Memory_Unlocks_Potential_of_Vision-Language_Models_CVPR_2026_paper.html",
    ("multimodal-understanding", "multimodal-reasoning", "visual-generation"),
    (("encode_visual", "vismem.perception", "Encode current visual evidence into latent tokens."),
     ("update_short_term", "vismem.stm", "Maintain visually dominant short-term latent memory."),
     ("consolidate_long_term", "vismem.ltm", "Consolidate abstract semantic information into long-term latent memory."),
     ("invoke_memory", "vismem.retrieve", "Dynamically inject short- and long-term latent memories during generation."),
     ("reason_generate", "vismem.reason", "Generate grounded output while preserving perceptual and semantic consistency.")),
    ("average_accuracy", "reasoning_accuracy", "generation_quality", "relative_gain"),
    ("no latent memory", "short-term only", "long-term only", "static memory invocation"),
    ("evaluate the reported understanding, reasoning and generation benchmark suite", "preserve dual short-term/long-term latent-memory separation", "reproduce memory-component ablations and the reported average gain"),
)

_add(
    "r4_cvpr2026",
    "R4: Retrieval-Augmented Reasoning for Vision-Language Models in 4D Spatio-Temporal Space",
    "CVPR 2026",
    "https://openaccess.thecvf.com/content/CVPR2026/html/Sohn_R4_Retrieval-Augmented_Reasoning_for_Vision-Language_Models_in_4D_Spatio-Temporal_Space_CVPR_2026_paper.html",
    ("embodied-question-answering", "embodied-navigation"),
    (("observe", "r4.perception", "Extract object-level semantic observations with metric pose and time."),
     ("update_4d_db", "r4.memory", "Append observations to the persistent structured 4D world model."),
     ("decompose_query", "r4.query", "Decompose language request into semantic, spatial and temporal retrieval keys."),
     ("retrieve", "r4.retrieve", "Retrieve grounded observations directly from 4D space."),
     ("iterate_reason", "r4.reason", "Alternate retrieval and VLM reasoning until evidence is sufficient."),
     ("answer_or_act", "r4.action", "Answer embodied questions or select navigation actions.")),
    ("qa_accuracy", "navigation_success", "retrieval_recall", "spatiotemporal_grounding_accuracy"),
    ("no 4D memory", "semantic-only retrieval", "no iterative retrieval", "single-agent memory"),
    ("run the paper embodied QA and navigation protocols", "retain metric-space plus temporal grounding and persistent cross-episode memory", "compare training-free R4 against retrieval and no-memory baselines with component ablations"),
)

_add(
    "refact_cvpr2026",
    "ReFAct: Empowering Multimodal Web Agents with Visual and Context Focusing",
    "CVPR 2026",
    "https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html",
    ("groundedvqa", "multimodal-web-agent"),
    (("observe_page", "refact.observe", "Acquire visual and textual web context."),
     ("ground_focus", "refact.ground", "Use active visual grounding to filter task-relevant information."),
     ("defocus", "refact.memory", "Externalize currently irrelevant context instead of retaining it in active context."),
     ("refocus", "refact.retrieve", "Restore externalized evidence when later reasoning makes it relevant."),
     ("reason_act", "refact.agent", "Reason and interact with the web under focused multimodal context.")),
    ("task_success", "grounding_accuracy", "context_tokens", "action_steps"),
    ("no grounding tool", "no defocus/refocus", "full context", "text-only context"),
    ("evaluate GroundedVQA and the paper's established web-agent benchmarks", "preserve active grounding plus external Defocus/Refocus semantics", "measure success, grounding and context-efficiency ablations"),
)

_add(
    "embodiedsplat_cvpr2026",
    "EmbodiedSplat: Online Feed-Forward Semantic 3DGS for Open-Vocabulary 3D Scene Understanding",
    "CVPR 2026",
    "https://openaccess.thecvf.com/content/CVPR2026/html/Lee_EmbodiedSplat_Online_Feed-Forward_Semantic_3DGS_for_Open-Vocabulary_3D_Scene_Understanding_CVPR_2026_paper.html",
    ("open-vocabulary-3d-scene-understanding",),
    (("stream_frames", "embodiedsplat.observe", "Consume streaming RGB observations online."),
     ("reconstruct_3dgs", "embodiedsplat.geometry", "Feed-forward reconstruct semantic 3D Gaussian scene state."),
     ("bind_clip", "embodiedsplat.semantic", "Bind 2D CLIP evidence through sparse coefficients and a global codebook."),
     ("aggregate_geometry", "embodiedsplat.3d", "Inject geometric priors through partial-point-cloud aggregation."),
     ("query_open_vocab", "embodiedsplat.query", "Resolve open-vocabulary semantic queries against the online scene representation.")),
    ("semantic_accuracy", "reconstruction_quality", "throughput_fps", "memory_usage"),
    ("no sparse coefficient field", "no global codebook", "no 3D geometric aggregation", "offline reconstruction"),
    ("stream the reported scene sequences in original order", "measure online reconstruction and open-vocabulary semantics jointly", "reproduce speed-memory-quality component ablations"),
)

_add(
    "implement_acl2026",
    "Model-Based Imaginative Planning for Embodied Agents",
    "ACL 2026",
    "https://aclanthology.org/2026.acl-long.827/",
    ("alfworld",),
    (("perceive", "implement.perception", "Convert raw visual observations into object-centric symbolic state."),
     ("propose", "implement.llm", "Have the frozen LLM propose candidate actions."),
     ("imagine", "implement.world_model", "Predict future states for hypothetical actions."),
     ("sample_futures", "implement.uncertainty", "Monte-Carlo sample plausible futures under partial observability."),
     ("meta_adapt", "implement.meta_icl", "Condition world-model predictions on accumulated interaction history."),
     ("policy_iterate", "implement.plan", "Refine the action decision from simulated trajectories and execute.")),
    ("success_rate", "average_reward", "planning_efficiency", "world_model_prediction_accuracy"),
    ("no world model", "deterministic single future", "no Meta-ICL", "no iterative replanning"),
    ("run official ALFWorld task splits with frozen LLM policy", "preserve visual-to-symbolic world-model and Monte-Carlo future simulation", "compare finetuning and test-time-scaling baselines plus all planning ablations"),
)

_add(
    "embodied_reasoner_acl2026",
    "Embodied-Reasoner: Synergizing Visual Search, Reasoning, and Action for Embodied Interactive Tasks",
    "ACL 2026",
    "https://aclanthology.org/2026.acl-long.1910/",
    ("embodied-interactive-tasks",),
    (("observe", "embodied_reasoner.observe", "Consume ego-centric visual observation."),
     ("visual_search", "embodied_reasoner.search", "Actively seek task-relevant visual evidence."),
     ("spatial_temporal_reason", "embodied_reasoner.reason", "Reason over spatial state and interaction history."),
     ("reflect", "embodied_reasoner.reflect", "Diagnose prior action and reasoning failures."),
     ("plan_verify", "embodied_reasoner.plan", "Plan and verify the next action against accumulated evidence."),
     ("act", "embodied_reasoner.act", "Execute the selected environment action and continue the OTA trajectory.")),
    ("task_success", "reasoning_accuracy", "interaction_steps", "visual_search_efficiency"),
    ("no visual search", "no reflection", "no verification", "direct action prediction"),
    ("reproduce the paper's observation-thought-action interactive evaluation", "retain egocentric images and interleaved environment feedback", "separate search, reasoning, reflection, planning and verification ablations"),
)

_add(
    "evu_acl2026",
    "Seeing Isn't Believing: Mitigating Belief Inertia via Active Intervention in Embodied Agents",
    "Findings ACL 2026",
    "https://aclanthology.org/2026.findings-acl.1884/",
    ("embodied-belief-update",),
    (("observe", "evu.observe", "Receive potentially belief-conflicting embodied observation."),
     ("externalize_belief", "evu.belief", "Generate an explicit textual belief state."),
     ("detect_inertia", "evu.detect", "Detect conflict between current evidence and stale belief."),
     ("intervene", "evu.update", "Actively revise the belief state when evidence warrants intervention."),
     ("reason_act", "evu.agent", "Plan and act from the updated belief rather than inert history.")),
    ("task_success", "belief_update_accuracy", "conflict_recovery_rate", "intervention_rate"),
    ("no EVU", "implicit belief only", "no active intervention", "prompting-only baseline"),
    ("run all three reported embodied benchmarks", "record belief state and intervention decisions in the trajectory", "compare prompting- and training-based integrations with belief-inertia ablations"),
)

_add(
    "agentrevive_acl2026",
    "Taming Zombie Agents: A Markov State-Aware Framework for Resilient Multi-Agent Evolution",
    "ACL 2026",
    "https://aclanthology.org/2026.acl-long.373/",
    ("multi-agent-reasoning",),
    (("observe_agents", "agentrevive.state", "Estimate each collaborator state from current behavior and memory."),
     ("transition", "agentrevive.markov", "Transition agents among Active, Standby and Terminated states."),
     ("route_messages", "agentrevive.communication", "Propagate messages according to soft state-aware collaboration policy."),
     ("revive", "agentrevive.recovery", "Reactivate recoverable standby agents when later evidence raises their utility."),
     ("aggregate", "agentrevive.solve", "Aggregate surviving and revived contributions into the task solution.")),
    ("task_accuracy", "token_cost", "agent_recovery_rate", "active_agent_count"),
    ("hard pruning", "no standby state", "no revival", "static topology"),
    ("reproduce reported multi-agent task suite and communication rounds", "preserve three-state Markov lifecycle instead of irreversible pruning", "measure quality-cost tradeoff and recovery under transient agent failures"),
)

_add(
    "agentslimming_acl2026",
    "AgentSlimming: Towards Efficient and Cost-Aware Multi-Agent Systems",
    "ACL 2026",
    "https://aclanthology.org/2026.acl-long.1387/",
    ("multi-agent-reasoning",),
    (("profile_graph", "agentslimming.graph", "Observe the graph-structured multi-agent workflow."),
     ("score_importance", "agentslimming.score", "Estimate agent importance with the hybrid scoring mechanism."),
     ("prune_or_quantize", "agentslimming.compress", "Remove redundant agents or replace them with lower-cost models."),
     ("validate", "agentslimming.accept", "Accept a compression only when baseline-anchored quality constraints hold."),
     ("execute", "agentslimming.run", "Run the compressed workflow and collect quality/cost evidence.")),
    ("task_accuracy", "prompt_tokens", "completion_tokens", "cost_reduction"),
    ("no pruning", "pruning only", "replacement only", "no baseline-anchored acceptance"),
    ("reproduce graph-workflow compression across the reported tasks", "evaluate every mutation against its uncompressed baseline", "report Pareto quality-cost frontier and component ablations"),
)

_add(
    "longvideoagent_acl2026",
    "LongVideoAgent: Multi-Agent Reasoning with Long Videos",
    "ACL 2026",
    "https://aclanthology.org/2026.acl-long.1876/",
    ("long-video-qa",),
    (("plan", "longvideoagent.master", "Master agent decides what temporal evidence is needed under a step budget."),
     ("ground", "longvideoagent.grounder", "Ground question-relevant temporal segments."),
     ("inspect", "longvideoagent.vision", "Extract targeted visual observations from selected clips."),
     ("integrate", "longvideoagent.master", "Fuse grounded clips, subtitles and visual details."),
     ("rl_optimize", "longvideoagent.train", "Optimize concise correct cooperation with reinforcement learning."),
     ("answer", "longvideoagent.answer", "Produce the final answer from interpretable multi-agent evidence.")),
    ("qa_accuracy", "grounding_accuracy", "agent_steps", "frames_or_clips_inspected"),
    ("master only", "no grounding agent", "no vision agent", "no RL", "lossy full-video summary"),
    ("evaluate the paper long-video QA suite under the original step limit", "retain master-grounder-vision role separation and targeted clip access", "measure answer quality, temporal grounding and inference-efficiency ablations"),
)


__all__ = ["PAPERS"]
