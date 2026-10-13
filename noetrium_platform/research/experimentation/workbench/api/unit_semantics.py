"""Static workbench semantics on the universal NoetriumUnit carrier."""
from __future__ import annotations

from collections.abc import Mapping
import math
from types import SimpleNamespace

from noetrium_platform.foundation.kernel.kernel import JsonValue, freeze_json, require_sha256
from noetrium_platform.foundation.kernel.structure import NoetriumUnit, structure_unit
from .contracts import AggregationFunction, FigureCategory, FigureKind

BASELINE_TRAIT = "research.baseline"
AGGREGATION_TRAIT = "research.aggregation"
CANDIDATE_PROGRAM_TRAIT = "research.candidate-program"


def _text(value: object, field: str) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError(f"{field} must be non-empty text")
    return value.strip()


def baseline_unit(
    *,
    baseline_id: str,
    implementation_id: str,
    configuration_digest: str,
    dataset_digest: str,
    protocol_digest: str,
    description: str = "",
    reference: str = "",
    source_uri: str = "",
    license: str = "",
    tags: tuple[str, ...] = (),
) -> NoetriumUnit:
    baseline_id=_text(baseline_id,"baseline_id")
    implementation_id=_text(implementation_id,"implementation_id")
    for name,value in (
        ("configuration_digest",configuration_digest),
        ("dataset_digest",dataset_digest),
        ("protocol_digest",protocol_digest),
    ):
        require_sha256(value,f"baseline {name}")
    for name,value in (
        ("description",description),("reference",reference),
        ("source_uri",source_uri),("license",license),
    ):
        if type(value) is not str:
            raise TypeError(f"baseline {name} must be string")
    if type(tags) is not tuple or any(type(x) is not str or not x.strip() for x in tags):
        raise TypeError("baseline tags must be non-empty text tuple")
    if len(tags)!=len(set(tags)):
        raise ValueError("baseline tags must be unique")
    return structure_unit(
        baseline_id,
        traits=(BASELINE_TRAIT,),
        parameters={
            "implementation_id":implementation_id,
            "configuration_digest":configuration_digest,
            "dataset_digest":dataset_digest,
            "protocol_digest":protocol_digest,
            "description":description,
            "reference":reference,
            "source_uri":source_uri,
            "license":license,
            "tags":tags,
        },
    )


def require_baseline(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(BASELINE_TRAIT):
        raise TypeError("baseline must be research.baseline NoetriumUnit")
    return value


def baseline_field(value: NoetriumUnit, name: str):
    value=require_baseline(value)
    if name=="baseline_id":
        return value.unit_id
    if name=="baseline_digest":
        return value.unit_digest
    return value.parameters[name]


def aggregation_unit(
    output_name: str,
    function: AggregationFunction,
    source_column: str | None = None,
    data_type: str = "float",
) -> NoetriumUnit:
    output_name=_text(output_name,"aggregation output_name")
    if not isinstance(function,AggregationFunction):
        raise TypeError("aggregation function must be AggregationFunction")
    if function is not AggregationFunction.COUNT:
        _text(source_column,"aggregation source_column")
    elif source_column is not None:
        _text(source_column,"aggregation source_column")
    data_type=_text(data_type,"aggregation data_type")
    return structure_unit(
        output_name,
        traits=(AGGREGATION_TRAIT,),
        parameters={
            "function":function.value,
            "source_column":source_column,
            "data_type":data_type,
        },
    )


def require_aggregation(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(AGGREGATION_TRAIT):
        raise TypeError("aggregation must be research.aggregation NoetriumUnit")
    return value


def aggregation_output_name(value: NoetriumUnit) -> str:
    return require_aggregation(value).unit_id


def aggregation_function(value: NoetriumUnit) -> AggregationFunction:
    return AggregationFunction(str(require_aggregation(value).parameters["function"]))


def aggregation_source_column(value: NoetriumUnit) -> str | None:
    raw=require_aggregation(value).parameters.get("source_column")
    return None if raw is None else str(raw)


def aggregation_data_type(value: NoetriumUnit) -> str:
    return str(require_aggregation(value).parameters["data_type"])


def candidate_program_unit(
    *,
    candidate_id: str,
    generation: int,
    source_artifact_id: str,
    source_content_sha256: str,
    language: str,
    entrypoint: str,
    interface_schema_id: str,
    parent_candidate_digests: tuple[str, ...] = (),
) -> NoetriumUnit:
    candidate_id=_text(candidate_id,"candidate_id")
    if type(generation) is not int or generation<0:
        raise ValueError("candidate generation must be non-negative")
    source_artifact_id=_text(source_artifact_id,"source artifact_id")
    require_sha256(source_content_sha256,"candidate source digest")
    language=_text(language,"candidate language")
    entrypoint=_text(entrypoint,"candidate entrypoint")
    interface_schema_id=_text(interface_schema_id,"candidate interface_schema_id")
    if type(parent_candidate_digests) is not tuple:
        raise TypeError("candidate parent digests must be tuple")
    for digest in parent_candidate_digests:
        require_sha256(digest,"candidate parent digest")
    parents=tuple(sorted(parent_candidate_digests))
    if len(parents)!=len(set(parents)):
        raise ValueError("candidate parent digests must be unique")
    return structure_unit(
        candidate_id,
        traits=(CANDIDATE_PROGRAM_TRAIT,),
        parameters={
            "generation":generation,
            "source_artifact_id":source_artifact_id,
            "source_content_sha256":source_content_sha256,
            "language":language,
            "entrypoint":entrypoint,
            "interface_schema_id":interface_schema_id,
            "parent_candidate_digests":parents,
        },
    )


def require_candidate_program(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(CANDIDATE_PROGRAM_TRAIT):
        raise TypeError("candidate program must be NoetriumUnit")
    return value


def candidate_field(value: NoetriumUnit, name: str):
    value=require_candidate_program(value)
    if name=="candidate_id":
        return value.unit_id
    if name=="candidate_digest":
        return value.unit_digest
    return value.parameters[name]


FIGURE_TRAIT = "research.figure"


def figure_point(
    x: str | float,
    y: float,
    error_low: float | None = None,
    error_high: float | None = None,
) -> Mapping[str, JsonValue]:
    if isinstance(x, bool) or not isinstance(x, (str, int, float)):
        raise TypeError("figure point x must be text or numeric")
    if isinstance(x, str):
        _text(x, "figure point x")
    if isinstance(y, bool) or not isinstance(y, (int, float)) or not math.isfinite(float(y)):
        raise ValueError("figure point y must be finite numeric")
    for name,value in (("error_low",error_low),("error_high",error_high)):
        if value is not None and (
            isinstance(value,bool) or not isinstance(value,(int,float))
            or not math.isfinite(float(value))
        ):
            raise ValueError(f"figure point {name} must be finite numeric or None")
    if (error_low is None)!=(error_high is None):
        raise ValueError("figure point error bounds must be provided together")
    if error_low is not None and float(error_low)>float(error_high):
        raise ValueError("figure point error bounds are invalid")
    return freeze_json({
        "x":x,"y":float(y),"error_low":error_low,"error_high":error_high,
    })


def figure_series(
    name: str,
    points: tuple[Mapping[str, JsonValue], ...],
) -> Mapping[str, JsonValue]:
    name=_text(name,"figure series name")
    if type(points) is not tuple or not points or any(not isinstance(x,Mapping) for x in points):
        raise TypeError("figure series points must be non-empty mapping tuple")
    return freeze_json({"name":name,"points":points})


def figure_cell(
    *,
    row: JsonValue,
    column: JsonValue,
    value: float,
) -> Mapping[str, JsonValue]:
    if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(float(value)):
        raise ValueError("figure cell value must be finite numeric")
    return freeze_json({"row":row,"column":column,"value":float(value)})


def figure_style_nature() -> Mapping[str, JsonValue]:
    return freeze_json({
        "name":"nature",
        "palette":(
            "#0072B2","#D55E00","#009E73","#CC79A7",
            "#E69F00","#56B4E9","#F0E442","#000000",
        ),
        "background":"#FFFFFF",
        "foreground":"#1F2937",
        "grid":"#D9E1EA",
        "font_family":"Arial",
        "title_size":16,
        "label_size":12,
        "tick_size":10,
        "legend_size":10,
        "line_width":2.2,
        "marker_size":4.0,
        "show_grid":True,
        "transparent":False,
    })


def figure_style_science() -> Mapping[str, JsonValue]:
    base=dict(figure_style_nature())
    base.update({
        "name":"science",
        "palette":("#0B3C5D","#328CC1","#D9B310","#1D2731","#984447","#6B7A8F"),
        "grid":"#D7DEE7",
    })
    return freeze_json(base)


def _validate_figure_style(style: Mapping[str, JsonValue]) -> Mapping[str, JsonValue]:
    if not isinstance(style,Mapping):
        raise TypeError("figure style must be mapping")
    required=(
        "name","palette","background","foreground","grid","font_family",
        "title_size","label_size","tick_size","legend_size","line_width",
        "marker_size","show_grid","transparent",
    )
    if any(key not in style for key in required):
        raise ValueError("figure style is incomplete")
    return freeze_json(style)


def figure_unit(
    *,
    figure_id: str,
    title: str,
    kind: FigureKind,
    series: tuple[Mapping[str, JsonValue], ...] = (),
    x_label: str = "",
    y_label: str = "",
    width: int = 800,
    height: int = 480,
    cells: tuple[Mapping[str, JsonValue], ...] = (),
    caption: str = "",
    source_digests: tuple[str, ...] = (),
    metadata: tuple[tuple[str, str], ...] = (),
    style: Mapping[str, JsonValue] | None = None,
) -> NoetriumUnit:
    figure_id=_text(figure_id,"figure id")
    title=_text(title,"figure title")
    if not isinstance(kind,FigureKind):
        raise TypeError("figure kind must be FigureKind")
    if type(series) is not tuple or any(not isinstance(x,Mapping) for x in series):
        raise TypeError("figure series must be mapping tuple")
    matrix={FigureKind.HEATMAP,FigureKind.CONFUSION_MATRIX}
    if not series and kind not in matrix:
        raise ValueError("non-matrix figures require series")
    if type(cells) is not tuple or any(not isinstance(x,Mapping) for x in cells):
        raise TypeError("figure cells must be mapping tuple")
    if kind in matrix and not cells:
        raise ValueError("matrix figures require cells")
    if type(width) is not int or width<240 or type(height) is not int or height<180:
        raise ValueError("figure dimensions are too small")
    if type(caption) is not str:
        raise TypeError("figure caption must be text")
    if type(source_digests) is not tuple:
        raise TypeError("figure source digests must be tuple")
    for digest in source_digests:
        require_sha256(digest,"figure source digest")
    if len(source_digests)!=len(set(source_digests)):
        raise ValueError("figure source digests must be unique")
    if type(metadata) is not tuple or any(
        type(row) is not tuple or len(row)!=2 or type(row[0]) is not str
        or not row[0].strip() or type(row[1]) is not str
        for row in metadata
    ):
        raise ValueError("figure metadata must be string pairs")
    if len({row[0] for row in metadata})!=len(metadata):
        raise ValueError("figure metadata keys must be unique")
    style=_validate_figure_style(
        figure_style_nature() if style is None else style
    )
    return structure_unit(
        figure_id,
        traits=(FIGURE_TRAIT,),
        parameters={
            "title":title,
            "kind":kind.value,
            "series":series,
            "x_label":x_label,
            "y_label":y_label,
            "width":width,
            "height":height,
            "cells":cells,
            "caption":caption,
            "source_digests":source_digests,
            "metadata":metadata,
            "style":style,
        },
    )


def require_figure(value: NoetriumUnit) -> NoetriumUnit:
    if type(value) is not NoetriumUnit or not value.has_trait(FIGURE_TRAIT):
        raise TypeError("figure must be research.figure NoetriumUnit")
    return value


def figure_category(value: NoetriumUnit) -> FigureCategory:
    kind=FigureKind(str(require_figure(value).parameters["kind"]))
    return {
        FigureKind.LINE:FigureCategory.TREND,
        FigureKind.BAR:FigureCategory.COMPARISON,
        FigureKind.SCATTER:FigureCategory.COMPARISON,
        FigureKind.HISTOGRAM:FigureCategory.DISTRIBUTION,
        FigureKind.BOXPLOT:FigureCategory.DISTRIBUTION,
        FigureKind.VIOLIN:FigureCategory.DISTRIBUTION,
        FigureKind.ECDF:FigureCategory.DISTRIBUTION,
        FigureKind.HEATMAP:FigureCategory.MATRIX,
        FigureKind.CONFUSION_MATRIX:FigureCategory.MATRIX,
        FigureKind.ROC:FigureCategory.CLASSIFICATION,
        FigureKind.PRECISION_RECALL:FigureCategory.CLASSIFICATION,
        FigureKind.CALIBRATION:FigureCategory.CLASSIFICATION,
        FigureKind.PARETO:FigureCategory.TRADEOFF,
        FigureKind.FOREST:FigureCategory.EFFECT,
    }[kind]


def _namespace(value):
    if isinstance(value,Mapping):
        return SimpleNamespace(**{str(k):_namespace(v) for k,v in value.items()})
    if isinstance(value,tuple):
        return tuple(_namespace(v) for v in value)
    return value


def figure_view(value: NoetriumUnit):
    """Ephemeral object-style renderer view; it has no identity or persistence."""

    value=require_figure(value)
    payload={key:_namespace(val) for key,val in value.parameters.items()}
    payload["figure_id"]=value.unit_id
    payload["figure_digest"]=value.unit_digest
    payload["kind"]=FigureKind(str(value.parameters["kind"]))
    payload["category"]=figure_category(value)
    return SimpleNamespace(**payload)
