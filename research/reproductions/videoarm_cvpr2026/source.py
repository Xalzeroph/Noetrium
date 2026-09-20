from __future__ import annotations

from noetrium_platform.research.provenance import MethodSourceLane, MethodSourceLaneKind, MethodSourceRegistry, PublicationSourceLane

VIDEOARM_PUBLICATION = PublicationSourceLane(
    lane_id="cvpr_2026",
    venue="CVPR",
    year=2026,
    publication_id="videoarm-cvpr-2026",
    publication_uri="https://openaccess.thecvf.com/content/CVPR2026/html/Yin_VideoARM_Agentic_Reasoning_over_Hierarchical_Memory_for_Long-Form_Video_Understanding_CVPR_2026_paper.html",
    revision="CVPR 2026 proceedings publication",
)

VIDEOARM_OFFICIAL_EXECUTABLE = MethodSourceLane(
    lane_id="official_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/MILVLG/videoarm",
    commit="af1973ad8ffdb1ae3815c1f4e3f22b8c82858ef6",
    artifacts=("README.md",),
)

SOURCES = MethodSourceRegistry(
    lanes=(VIDEOARM_PUBLICATION, VIDEOARM_OFFICIAL_EXECUTABLE)
)

__all__ = ["VIDEOARM_PUBLICATION","SOURCES"]
