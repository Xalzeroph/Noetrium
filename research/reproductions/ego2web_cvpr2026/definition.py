from __future__ import annotations
from noetrium_platform.research.reproduction import ReferenceBaseline, ReportedResult, ReproductionAssetKind, ReproductionAssetRef, ReproductionCatalog, ReproductionDefinition, ReproductionIdentity, ReproductionLifecycle
REPRODUCTION=ReproductionDefinition(
    package="ego2web_cvpr2026",lifecycle=ReproductionLifecycle.PROTOCOL_BOUND,
    identity=ReproductionIdentity(method_id="ego2web_cvpr2026",title="Ego2Web: A Web Agent Benchmark Grounded in Egocentric Videos",paper_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Yu_Ego2Web_A_Web_Agent_Benchmark_Grounded_in_Egocentric_Videos_CVPR_2026_paper.html",year=2026,paper_revision="CVPR 2026 final proceedings"),
    catalog=ReproductionCatalog(domains=("agent","frontier-2026","benchmark"),families=("benchmark", "egocentric-video", "web-agent", "multimodal"),priority=1,benchmark_ids=("ego2web",),platform_pressure=("benchmark","evidence","execution/workflow","experimentation/study","model/request"),method_owned=("Extract task-relevant evidence from first-person video.", "Ground the online task in observed physical-world evidence.", "Plan the required online workflow.", "Execute web actions under the frozen benchmark environment.", "Score completion with Ego2WebJudge and retain judge evidence."),platform_owned=("MethodProgram execution and Machine Journal truth","provider-independent model/tool dispatch and receipts","content-addressed benchmark task identity","Study/Experiment orchestration and measurement artifacts","run/evidence provenance and replay")),
    assets=(ReproductionAssetRef(ReproductionAssetKind.BENCHMARK,"research/reproductions/ego2web_cvpr2026/benchmark.py"),ReproductionAssetRef(ReproductionAssetKind.METHOD_PROGRAM,"research/reproductions/ego2web_cvpr2026/program.py"),ReproductionAssetRef(ReproductionAssetKind.STUDY,"research/reproductions/ego2web_cvpr2026/study.py")),
    primary_executable="research/reproductions/ego2web_cvpr2026/program.py",
    reported_results=(
        ReportedResult(claim_id="ego2web_judge_agreement",metric_id="judge_human_agreement",value=84,qualifiers={"unit": "percent", "source": "CVPR 2026 final paper abstract", "approximate": True}),
    ),
    reference_baselines=(
        ReferenceBaseline(baseline_id="baseline_01",description="SoTA web agents evaluated in the final paper"),
        ReferenceBaseline(baseline_id="baseline_02",description="video-ablated controls"),
        ReferenceBaseline(baseline_id="baseline_03",description="existing automatic web-agent judges"),
    ),
    blockers=("Matched execution requires released video-task pairs, website state and frozen Ego2WebJudge model/configuration.", "Web and video execution must generate Machine Journal and evaluator receipts."),evidence_refs=(),scientific_tests=("tests/test_scientific_frontier_2026_wave_01.py",),
)
__all__=["REPRODUCTION"]
