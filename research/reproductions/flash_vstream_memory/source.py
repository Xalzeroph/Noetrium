from __future__ import annotations

from noetrium_platform.research.provenance import (
    MethodSourceLane,
    MethodSourceLaneKind,
    MethodSourceRegistry,
    PublicationSourceLane,
)

FLASH_VSTREAM_LLAVA_PRECURSOR_COMMIT = (
    "f7cccf5286b7849a814f6fca2f225f251ed7adbb"
)
FLASH_VSTREAM_QWEN_ICCV_COMMIT = (
    "6a82abfeac43012731610f27946d7ab2e86d6f8c"
)

FLASH_VSTREAM_ICCV_2025 = PublicationSourceLane(
    lane_id="iccv_2025_camera_ready",
    venue="ICCV",
    year=2025,
    publication_id="flash-vstream-iccv-2025",
    publication_uri=(
        "https://openaccess.thecvf.com/content/ICCV2025/html/"
        "Zhang_Flash-VStream_Efficient_Real-Time_Understanding_"
        "for_Long_Video_Streams_ICCV_2025_paper.html"
    ),
    revision="ICCV 2025 camera-ready paper",
)

FLASH_VSTREAM_LLAVA_PRECURSOR = MethodSourceLane(
    lane_id="official_llava_2024_precursor",
    kind=MethodSourceLaneKind.OFFICIAL_ARTIFACT,
    repository="https://github.com/IVGSZ/Flash-VStream",
    commit=FLASH_VSTREAM_LLAVA_PRECURSOR_COMMIT,
    artifacts=(
        "flash_vstream/model/vstream_arch.py",
        "flash_vstream/model/compress_functions.py",
        "flash_vstream/train/train.py",
        "scripts/train_and_eval.sh",
    ),
)

FLASH_VSTREAM_QWEN_ICCV_EXECUTABLE = MethodSourceLane(
    lane_id="official_qwen_iccv_2025_executable",
    kind=MethodSourceLaneKind.OFFICIAL_EXECUTABLE,
    repository="https://github.com/IVGSZ/Flash-VStream",
    commit=FLASH_VSTREAM_QWEN_ICCV_COMMIT,
    artifacts=(
        "Flash-VStream-Qwen/models/flash_memory_constants.py",
        "Flash-VStream-Qwen/models/vstream_qwen2vl_model.py",
        "Flash-VStream-Qwen/models/compress_functions.py",
        "Flash-VStream-Qwen/models/vstream_qwen2vl_processor.py",
        "Flash-VStream-Qwen/inference_mcq_vqa.py",
    ),
)

SOURCES = MethodSourceRegistry(
    lanes=(
        FLASH_VSTREAM_ICCV_2025,
        FLASH_VSTREAM_QWEN_ICCV_EXECUTABLE,
        FLASH_VSTREAM_LLAVA_PRECURSOR,
    ),
)

__all__ = [
    "FLASH_VSTREAM_ICCV_2025",
    "FLASH_VSTREAM_LLAVA_PRECURSOR",
    "FLASH_VSTREAM_LLAVA_PRECURSOR_COMMIT",
    "FLASH_VSTREAM_QWEN_ICCV_EXECUTABLE",
    "FLASH_VSTREAM_QWEN_ICCV_COMMIT",
    "SOURCES",
]
