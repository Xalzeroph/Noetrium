"""Canonical MovieChat-1K long-video benchmark authority."""

from .cut import (
    MOVIECHAT_1K_BENCHMARK_ID,
    MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO,
    MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO,
    MOVIECHAT_1K_SCHEMA_ID,
    MOVIECHAT_1K_SOURCE_URI,
    MOVIECHAT_1K_TEST_SPLIT,
    MOVIECHAT_1K_VIDEO_COUNT,
    MovieChatQuestion,
    MovieChatVideoRecord,
    bind_moviechat_1k_test_cut,
    build_moviechat_1k_source,
    build_moviechat_1k_test_cut,
)

__all__ = [
    "MOVIECHAT_1K_BENCHMARK_ID",
    "MOVIECHAT_1K_BREAKPOINT_QA_PER_VIDEO",
    "MOVIECHAT_1K_GLOBAL_QA_PER_VIDEO",
    "MOVIECHAT_1K_SCHEMA_ID",
    "MOVIECHAT_1K_SOURCE_URI",
    "MOVIECHAT_1K_TEST_SPLIT",
    "MOVIECHAT_1K_VIDEO_COUNT",
    "MovieChatQuestion",
    "MovieChatVideoRecord",
    "bind_moviechat_1k_test_cut",
    "build_moviechat_1k_source",
    "build_moviechat_1k_test_cut",
]
