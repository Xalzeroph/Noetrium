"""Publication provenance for the first 2026 frontier reproduction wave."""

from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceRegistry,
    PublicationSourceLane,
)


AGE_MEM_ACL_2026 = PublicationSourceLane(
    lane_id="agemem_acl2026_final",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.981",
    publication_uri="https://aclanthology.org/2026.acl-long.981/",
    revision="ACL 2026 Volume 1 final paper",
)
MM_MEM_ACL_2026 = PublicationSourceLane(
    lane_id="mm_mem_acl2026_final",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.533",
    publication_uri="https://aclanthology.org/2026.acl-long.533/",
    revision="ACL 2026 Volume 1 final paper",
)
MEM_GALLERY_ACL_2026 = PublicationSourceLane(
    lane_id="mem_gallery_acl2026_final",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.1892",
    publication_uri="https://aclanthology.org/2026.acl-long.1892/",
    revision="ACL 2026 Volume 1 final paper",
)
OS_SYMPHONY_ACL_2026 = PublicationSourceLane(
    lane_id="os_symphony_acl2026_final",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.1021",
    publication_uri="https://aclanthology.org/2026.acl-long.1021/",
    revision="ACL 2026 Volume 1 final paper",
)
IMPLEMENT_ACL_2026 = PublicationSourceLane(
    lane_id="implement_acl2026_final",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.827",
    publication_uri="https://aclanthology.org/2026.acl-long.827/",
    revision="ACL 2026 Volume 1 final paper",
)
ORBIT_ACL_2026 = PublicationSourceLane(
    lane_id="orbit_acl2026_final",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.1822",
    publication_uri="https://aclanthology.org/2026.acl-long.1822/",
    revision="ACL 2026 Volume 1 final paper",
)
EAGLET_ACL_2026 = PublicationSourceLane(
    lane_id="eaglet_acl2026_final",
    venue="ACL",
    year=2026,
    publication_id="2026.acl-long.597",
    publication_uri="https://aclanthology.org/2026.acl-long.597/",
    revision="ACL 2026 Volume 1 final paper",
)
REFACT_CVPR_2026 = PublicationSourceLane(
    lane_id="refact_cvpr2026_final",
    venue="CVPR",
    year=2026,
    publication_id="Wu_ReFAct_CVPR_2026",
    publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_ReFAct_Empowering_Multimodal_Web_Agents_with_Visual_and_Context_Focusing_CVPR_2026_paper.html",
    revision="CVPR 2026 final proceedings paper",
)
EGO2WEB_CVPR_2026 = PublicationSourceLane(
    lane_id="ego2web_cvpr2026_final",
    venue="CVPR",
    year=2026,
    publication_id="Yu_Ego2Web_CVPR_2026",
    publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Yu_Ego2Web_A_Web_Agent_Benchmark_Grounded_in_Egocentric_Videos_CVPR_2026_paper.html",
    revision="CVPR 2026 final proceedings paper",
)
MMBENCH_GUI_CVPR_2026 = PublicationSourceLane(
    lane_id="mmbench_gui_cvpr2026_final",
    venue="CVPR",
    year=2026,
    publication_id="Wang_MMBench_GUI_CVPR_2026",
    publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wang_MMBench-GUI_A_Unified_Hierarchical_Evaluation_Framework_for_Multi-Platform_GUI_Agents_CVPR_2026_paper.html",
    revision="CVPR 2026 final proceedings paper",
)
ECHOTRAIL_GUI_CVPRF_2026 = PublicationSourceLane(
    lane_id="echotrail_gui_cvprf2026_final",
    venue="CVPR Findings",
    year=2026,
    publication_id="Li_EchoTrail_GUI_CVPRF_2026",
    publication_uri="https://openaccess.thecvf.com/content/CVPR2026F/html/Li_EchoTrail-GUI_Building_Actionable_Memory_for_GUI_Agents_via_Critic-Guided_Self-Exploration_CVPRF_2026_paper.html",
    revision="CVPR 2026 Findings final proceedings paper",
)
STAR_TOGGLE_CVPR_2026 = PublicationSourceLane(
    lane_id="star_toggle_cvpr2026_final",
    venue="CVPR",
    year=2026,
    publication_id="Wu_See_Think_Act_CVPR_2026",
    publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Wu_See_Think_Act_Teaching_Multimodal_Agents_to_Effectively_Interact_with_CVPR_2026_paper.html",
    revision="CVPR 2026 final proceedings paper",
)

SOURCES = MethodSourceRegistry(
    lanes=(
        AGE_MEM_ACL_2026,
        MM_MEM_ACL_2026,
        MEM_GALLERY_ACL_2026,
        OS_SYMPHONY_ACL_2026,
        IMPLEMENT_ACL_2026,
        ORBIT_ACL_2026,
        EAGLET_ACL_2026,
        REFACT_CVPR_2026,
        EGO2WEB_CVPR_2026,
        MMBENCH_GUI_CVPR_2026,
        ECHOTRAIL_GUI_CVPRF_2026,
        STAR_TOGGLE_CVPR_2026,
    )
)

__all__ = [
    "AGE_MEM_ACL_2026",
    "MM_MEM_ACL_2026",
    "MEM_GALLERY_ACL_2026",
    "OS_SYMPHONY_ACL_2026",
    "IMPLEMENT_ACL_2026",
    "ORBIT_ACL_2026",
    "EAGLET_ACL_2026",
    "REFACT_CVPR_2026",
    "EGO2WEB_CVPR_2026",
    "MMBENCH_GUI_CVPR_2026",
    "ECHOTRAIL_GUI_CVPRF_2026",
    "STAR_TOGGLE_CVPR_2026",
    "SOURCES",
]
