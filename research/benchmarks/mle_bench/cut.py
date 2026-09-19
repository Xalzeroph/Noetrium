from __future__ import annotations

from dataclasses import dataclass

from noetrium_platform.foundation.kernel.kernel import canonical_digest, require_sha256
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskSetSplit,
)

MLE_BENCH_BENCHMARK_ID = "mle-bench"
MLE_BENCH_OFFICIAL_REPOSITORY = "https://github.com/openai/mle-bench"
MLE_BENCH_MARS_CONTEMPORANEOUS_COMMIT = "1d391b013baf9de8cfca521f284f03b5b5aa82d2"
MLE_BENCH_REVISION = f"mle-bench@{MLE_BENCH_MARS_CONTEMPORANEOUS_COMMIT}"
MLE_BENCH_TASK_SCHEMA_ID = "mle-bench.kaggle-competition.v1"
MLE_BENCH_FULL75_SPLIT = "split75"
MLE_BENCH_LOW_SPLIT = "low"
MLE_BENCH_MEDIUM_SPLIT = "medium"
MLE_BENCH_HIGH_SPLIT = "high"
MLE_BENCH_FULL75_COMPETITIONS = (
    "3d-object-detection-for-autonomous-vehicles",
    "AI4Code",
    "aerial-cactus-identification",
    "alaska2-image-steganalysis",
    "aptos2019-blindness-detection",
    "billion-word-imputation",
    "bms-molecular-translation",
    "cassava-leaf-disease-classification",
    "cdiscount-image-classification-challenge",
    "chaii-hindi-and-tamil-question-answering",
    "champs-scalar-coupling",
    "denoising-dirty-documents",
    "detecting-insults-in-social-commentary",
    "dog-breed-identification",
    "dogs-vs-cats-redux-kernels-edition",
    "facebook-recruiting-iii-keyword-extraction",
    "freesound-audio-tagging-2019",
    "google-quest-challenge",
    "google-research-identify-contrails-reduce-global-warming",
    "h-and-m-personalized-fashion-recommendations",
    "herbarium-2020-fgvc7",
    "herbarium-2021-fgvc8",
    "herbarium-2022-fgvc9",
    "histopathologic-cancer-detection",
    "hms-harmful-brain-activity-classification",
    "hotel-id-2021-fgvc8",
    "hubmap-kidney-segmentation",
    "icecube-neutrinos-in-deep-ice",
    "imet-2020-fgvc7",
    "inaturalist-2019-fgvc6",
    "iwildcam-2019-fgvc6",
    "iwildcam-2020-fgvc7",
    "jigsaw-toxic-comment-classification-challenge",
    "jigsaw-unintended-bias-in-toxicity-classification",
    "kuzushiji-recognition",
    "leaf-classification",
    "learning-agency-lab-automated-essay-scoring-2",
    "lmsys-chatbot-arena",
    "mlsp-2013-birds",
    "multi-modal-gesture-recognition",
    "new-york-city-taxi-fare-prediction",
    "nfl-player-contact-detection",
    "nomad2018-predict-transparent-conductors",
    "osic-pulmonary-fibrosis-progression",
    "petfinder-pawpularity-score",
    "plant-pathology-2020-fgvc7",
    "plant-pathology-2021-fgvc8",
    "predict-volcanic-eruptions-ingv-oe",
    "random-acts-of-pizza",
    "ranzcr-clip-catheter-line-classification",
    "rsna-2022-cervical-spine-fracture-detection",
    "rsna-breast-cancer-detection",
    "rsna-miccai-brain-tumor-radiogenomic-classification",
    "seti-breakthrough-listen",
    "siim-covid19-detection",
    "siim-isic-melanoma-classification",
    "smartphone-decimeter-2022",
    "spooky-author-identification",
    "stanford-covid-vaccine",
    "statoil-iceberg-classifier-challenge",
    "tabular-playground-series-dec-2021",
    "tabular-playground-series-may-2022",
    "tensorflow-speech-recognition-challenge",
    "tensorflow2-question-answering",
    "text-normalization-challenge-english-language",
    "text-normalization-challenge-russian-language",
    "tgs-salt-identification-challenge",
    "the-icml-2013-whale-challenge-right-whale-redux",
    "tweet-sentiment-extraction",
    "us-patent-phrase-to-phrase-matching",
    "uw-madison-gi-tract-image-segmentation",
    "ventilator-pressure-prediction",
    "vesuvius-challenge-ink-detection",
    "vinbigdata-chest-xray-abnormalities-detection",
    "whale-categorization-playground",
)
MLE_BENCH_LOW_COMPETITIONS = (
    "aerial-cactus-identification",
    "aptos2019-blindness-detection",
    "denoising-dirty-documents",
    "detecting-insults-in-social-commentary",
    "dog-breed-identification",
    "dogs-vs-cats-redux-kernels-edition",
    "histopathologic-cancer-detection",
    "jigsaw-toxic-comment-classification-challenge",
    "leaf-classification",
    "mlsp-2013-birds",
    "new-york-city-taxi-fare-prediction",
    "nomad2018-predict-transparent-conductors",
    "plant-pathology-2020-fgvc7",
    "random-acts-of-pizza",
    "ranzcr-clip-catheter-line-classification",
    "siim-isic-melanoma-classification",
    "spooky-author-identification",
    "tabular-playground-series-dec-2021",
    "tabular-playground-series-may-2022",
    "text-normalization-challenge-english-language",
    "text-normalization-challenge-russian-language",
    "the-icml-2013-whale-challenge-right-whale-redux",
)
MLE_BENCH_MEDIUM_COMPETITIONS = (
    "AI4Code",
    "alaska2-image-steganalysis",
    "billion-word-imputation",
    "cassava-leaf-disease-classification",
    "cdiscount-image-classification-challenge",
    "chaii-hindi-and-tamil-question-answering",
    "champs-scalar-coupling",
    "facebook-recruiting-iii-keyword-extraction",
    "freesound-audio-tagging-2019",
    "google-quest-challenge",
    "h-and-m-personalized-fashion-recommendations",
    "herbarium-2020-fgvc7",
    "herbarium-2021-fgvc8",
    "herbarium-2022-fgvc9",
    "hotel-id-2021-fgvc8",
    "hubmap-kidney-segmentation",
    "icecube-neutrinos-in-deep-ice",
    "imet-2020-fgvc7",
    "inaturalist-2019-fgvc6",
    "iwildcam-2020-fgvc7",
    "jigsaw-unintended-bias-in-toxicity-classification",
    "kuzushiji-recognition",
    "learning-agency-lab-automated-essay-scoring-2",
    "lmsys-chatbot-arena",
    "multi-modal-gesture-recognition",
    "osic-pulmonary-fibrosis-progression",
    "petfinder-pawpularity-score",
    "plant-pathology-2021-fgvc8",
    "seti-breakthrough-listen",
    "statoil-iceberg-classifier-challenge",
    "tensorflow-speech-recognition-challenge",
    "tensorflow2-question-answering",
    "tgs-salt-identification-challenge",
    "tweet-sentiment-extraction",
    "us-patent-phrase-to-phrase-matching",
    "uw-madison-gi-tract-image-segmentation",
    "ventilator-pressure-prediction",
    "whale-categorization-playground",
)
MLE_BENCH_HIGH_COMPETITIONS = (
    "3d-object-detection-for-autonomous-vehicles",
    "bms-molecular-translation",
    "google-research-identify-contrails-reduce-global-warming",
    "hms-harmful-brain-activity-classification",
    "iwildcam-2019-fgvc6",
    "nfl-player-contact-detection",
    "predict-volcanic-eruptions-ingv-oe",
    "rsna-2022-cervical-spine-fracture-detection",
    "rsna-breast-cancer-detection",
    "rsna-miccai-brain-tumor-radiogenomic-classification",
    "siim-covid19-detection",
    "smartphone-decimeter-2022",
    "stanford-covid-vaccine",
    "vesuvius-challenge-ink-detection",
    "vinbigdata-chest-xray-abnormalities-detection",
)
MLE_BENCH_SPLIT_BLOB_SHA1 = {
    "split75": "4ecea04147fbcb9c696ebc702247f3342341aaae",
    "low": "5897e3e922bbcfebc8c925428883a344643b5a43",
    "medium": "9f1a21d852de04d8b7f0865937486c131f6fe934",
    "high": "d0d0f359d53851be7228c15c2ac52f01acda84bf",
}
MLE_BENCH_SELECTION_POLICY_DIGEST = canonical_digest({
    "benchmark_id": MLE_BENCH_BENCHMARK_ID,
    "revision": MLE_BENCH_REVISION,
    "full75": MLE_BENCH_FULL75_COMPETITIONS,
    "low": MLE_BENCH_LOW_COMPETITIONS,
    "medium": MLE_BENCH_MEDIUM_COMPETITIONS,
    "high": MLE_BENCH_HIGH_COMPETITIONS,
})

@dataclass(frozen=True, slots=True)
class MleBenchCompetitionRecord:
    competition_id: str
    content_digest: str

    def __post_init__(self) -> None:
        if self.competition_id not in MLE_BENCH_FULL75_COMPETITIONS:
            raise ValueError("competition is not part of the frozen MLE-Bench full75 cut")
        require_sha256(self.content_digest, "MLE-Bench competition content_digest")

    @property
    def task_id(self) -> str:
        return f"mle-bench:{self.competition_id}"

def build_mle_bench_source_spec(*, content_digest: str) -> BenchmarkSourceSpec:
    require_sha256(content_digest, "MLE-Bench source content_digest")
    return BenchmarkSourceSpec(
        source_id=MLE_BENCH_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=MLE_BENCH_REVISION,
        locator=f"{MLE_BENCH_OFFICIAL_REPOSITORY}/tree/{MLE_BENCH_MARS_CONTEMPORANEOUS_COMMIT}",
        content_digest=content_digest,
        metadata={
            "split75_blob_sha1": MLE_BENCH_SPLIT_BLOB_SHA1["split75"],
            "low_blob_sha1": MLE_BENCH_SPLIT_BLOB_SHA1["low"],
            "medium_blob_sha1": MLE_BENCH_SPLIT_BLOB_SHA1["medium"],
            "high_blob_sha1": MLE_BENCH_SPLIT_BLOB_SHA1["high"],
            "competition_count": str(len(MLE_BENCH_FULL75_COMPETITIONS)),
        },
    )

def _family(competition_id: str) -> str:
    if competition_id in MLE_BENCH_LOW_COMPETITIONS:
        return "low"
    if competition_id in MLE_BENCH_MEDIUM_COMPETITIONS:
        return "medium"
    if competition_id in MLE_BENCH_HIGH_COMPETITIONS:
        return "high"
    raise ValueError("MLE-Bench complexity family is unknown")

def build_mle_bench_task_set(
    records: tuple[MleBenchCompetitionRecord, ...],
    *,
    source_digest: str,
) -> BenchmarkTaskSet:
    if type(records) is not tuple or any(type(row) is not MleBenchCompetitionRecord for row in records):
        raise TypeError("MLE-Bench records must be a tuple of MleBenchCompetitionRecord")
    require_sha256(source_digest, "MLE-Bench source_digest")
    by_id = {row.competition_id: row for row in records}
    if len(records) != 75 or set(by_id) != set(MLE_BENCH_FULL75_COMPETITIONS):
        raise ValueError("MLE-Bench full cut requires exactly all 75 competitions")
    tasks = tuple(sorted((
        TaskDefinition(
            task_id=row.task_id,
            revision_id=MLE_BENCH_REVISION,
            family=_family(row.competition_id),
            schema_id=MLE_BENCH_TASK_SCHEMA_ID,
            content_digest=row.content_digest,
            lineage_refs=(
                f"competition:{row.competition_id}",
                f"source-commit:{MLE_BENCH_MARS_CONTEMPORANEOUS_COMMIT}",
            ),
        )
        for row in records
    ), key=lambda row: row.task_id))
    def ids(comp_ids: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(f"mle-bench:{competition_id}" for competition_id in comp_ids)
    return BenchmarkTaskSet(
        benchmark_id=MLE_BENCH_BENCHMARK_ID,
        revision_id=MLE_BENCH_REVISION,
        source_digest=source_digest,
        task_schema_id=MLE_BENCH_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(
            TaskSetSplit(MLE_BENCH_FULL75_SPLIT, ids(MLE_BENCH_FULL75_COMPETITIONS)),
            TaskSetSplit(MLE_BENCH_LOW_SPLIT, ids(MLE_BENCH_LOW_COMPETITIONS)),
            TaskSetSplit(MLE_BENCH_MEDIUM_SPLIT, ids(MLE_BENCH_MEDIUM_COMPETITIONS)),
            TaskSetSplit(MLE_BENCH_HIGH_SPLIT, ids(MLE_BENCH_HIGH_COMPETITIONS)),
        ),
        selection_policy_digest=MLE_BENCH_SELECTION_POLICY_DIGEST,
    )

__all__ = [
    "MLE_BENCH_BENCHMARK_ID",
    "MLE_BENCH_FULL75_COMPETITIONS",
    "MLE_BENCH_FULL75_SPLIT",
    "MLE_BENCH_HIGH_COMPETITIONS",
    "MLE_BENCH_HIGH_SPLIT",
    "MLE_BENCH_LOW_COMPETITIONS",
    "MLE_BENCH_LOW_SPLIT",
    "MLE_BENCH_MARS_CONTEMPORANEOUS_COMMIT",
    "MLE_BENCH_MEDIUM_COMPETITIONS",
    "MLE_BENCH_MEDIUM_SPLIT",
    "MLE_BENCH_OFFICIAL_REPOSITORY",
    "MLE_BENCH_REVISION",
    "MLE_BENCH_SELECTION_POLICY_DIGEST",
    "MLE_BENCH_SPLIT_BLOB_SHA1",
    "MLE_BENCH_TASK_SCHEMA_ID",
    "MleBenchCompetitionRecord",
    "build_mle_bench_source_spec",
    "build_mle_bench_task_set",
]
