from __future__ import annotations

from noetrium_platform.foundation.kernel.kernel import canonical_digest
from noetrium_platform.research.experimentation.study.api import (
    BenchmarkSourceKind,
    BenchmarkSourceResolution,
    BenchmarkSourceSpec,
    BenchmarkTaskSet,
    TaskDefinition,
    TaskPackageSpec,
    TaskSetSplit,
    TaskVerifierIsolation,
)

ROBOCODEGEN_BENCHMARK_ID = "robocodegen-37"
ROBOCODEGEN_TASK_SCHEMA_ID = "robocodegen.function-synthesis.v1"
ROBOCODEGEN_REPOSITORY = "https://github.com/google-research/google-research"
ROBOCODEGEN_SOURCE_COMMIT = "71896d4b6816983672aa6999e2dc92a3cfe904e4"
ROBOCODEGEN_NOTEBOOK_PATH = (
    "code_as_policies/Experiment_ Robot Code-Gen Benchmark.ipynb"
)
ROBOCODEGEN_NOTEBOOK_BLOB_SHA = "a8a33ad43758be446e033a3cb65ace4a2cb031f3"
ROBOCODEGEN_ALL_SPLIT = "all"
ROBOCODEGEN_TASK_COUNT = 37
ROBOCODEGEN_TESTS_PER_TASK = 5

ROBOCODEGEN_TASK_SIGNATURES = (
    ("get_top_most_idx", "idx = get_top_most_idx(points_np)"),
    ("get_bottom_most_idx", "idx = get_bottom_most_idx(points_np)"),
    ("get_left_most_idx", "idx = get_left_most_idx(points_np)"),
    ("get_right_most_idx", "idx = get_right_most_idx(points_np)"),
    ("get_farthest_idx", "idx = get_farthest_idx(points_np, point_np)"),
    ("get_closest_idx", "idx = get_closest_idx(points_np, point_np)"),
    ("get_bbox_xyxy_area", "area = get_bbox_xyxy_area(bbox_xyxy)"),
    ("bbox_xyxy_contains_pt", "contains = bbox_xyxy_contains_pt(bbox_xyxy)"),
    ("interpolate_pts_np", "pts = interpolate_pts_np(start, end, n)"),
    ("reverse_pts", "pts = reverse_pts(pts_np)"),
    ("normalize_vector", "normalized_vector = normalize_vector(vector)"),
    ("translate_pts_np", "new_pts_np = translate_pts_np(pts_np, delta_np)"),
    ("rotate_pts_around_pts_center_np", "new_pts_np = rotate_pts_around_pts_center_np(pts_np, angle_deg)"),
    ("scale_pts_around_centroid_np", "new_pts_np = scale_pts_around_centroid_np(pts_np, scale_x=1.5, scale_y=1.5)"),
    ("fit_2d_np_polys", "(poly_x_coeffs, poly_y_coeffs) = fit_2d_np_polys(ts, pts_2d_np, deg)"),
    ("evaluate_pts_2d_from_poly_coeffs", "pts_2d_np = evaluate_pts_2d_from_poly_coeffs(poly_x_coeffs, poly_y_coeffs, ts)"),
    ("pd_control", "u = pd_control(x_curr, x_goal, x_dot, Kp, Kv)"),
    ("end_effector_impedance_control", "tau = end_effector_impedance_control(x_curr, x_goal, x_dot, K_x_mat, D_x_mat, J)"),
    ("is_discrete_system_stable", "is_stable = is_discrete_system_stable(A_mat)"),
    ("is_closed_loop_discrete_system_stable", "is_stable = is_closed_loop_discrete_system_stable(A_mat, B_mat, K_mat)"),
    ("get_closest_point_on_line_to_point", "point_np = get_closest_point_on_line_to_point(line, pt_np)"),
    ("get_direction_orthogonal_to_line", "direction = get_direction_orthogonal_to_line(line)"),
    ("get_direction_orthogonal_to_line_to_point", "direction = get_direction_orthogonal_to_line_to_point(line, pt_np)"),
    ("get_points_from_polygon", "points_np = get_points_from_polygon(polygon)"),
    ("interpolate_pts_along_exterior", "pts_coords = interpolate_pts_along_exterior(exterior=shape.exterior, n=5)"),
    ("interpolate_pts_on_line", "pts_coords = interpolate_pts_on_line(line, n)"),
    ("make_line", "line = make_line(start_pt_np, end_pt_np)"),
    ("make_circle", "circle = make_circle(radius, center)"),
    ("make_rectangle", "rectangle = make_rectangle(width, height, center)"),
    ("make_ellipse", "ellipse = make_ellipse(center, major_axis, minor_axis)"),
    ("obj_shape_does_not_contain_others", "ret_val = obj_shape_does_not_contain_others(obj_name, other_obj_names)"),
    ("is_obj0_bigger_than_obj1", "ret_val = is_obj0_bigger_than_obj1(obj0_name, obj1_name)"),
    ("get_one_bbox_xyxy_of_all_objs", "bbox_xyxy = get_one_bbox_xyxy_of_all_objs(all_obj_names)"),
    ("are_obj_centers_close", "ret_val = are_obj_centers_close(obj_names, threshold)"),
    ("get_name_of_biggest_obj", "obj_name = get_name_of_biggest_obj(obj_names)"),
    ("do_any_object_shapes_intersect_with_each_other", "ret_val = do_any_object_shapes_intersect_with_each_other(obj_names)"),
    ("get_name_of_obj_with_min_dist_to_pt", "obj_name = get_name_of_obj_with_min_dist_to_pt(pt_np, obj_names)"),
)

ROBOCODEGEN_PROTOCOL_DIGEST = canonical_digest({
    "benchmark_id": ROBOCODEGEN_BENCHMARK_ID,
    "source_commit": ROBOCODEGEN_SOURCE_COMMIT,
    "notebook_path": ROBOCODEGEN_NOTEBOOK_PATH,
    "notebook_blob_sha": ROBOCODEGEN_NOTEBOOK_BLOB_SHA,
    "task_signatures": ROBOCODEGEN_TASK_SIGNATURES,
    "tests_per_task": ROBOCODEGEN_TESTS_PER_TASK,
    "test_generation": "paper-notebook-numpy-random-no-fixed-seed",
    "evaluation": "execute-generated-function-against-reference-equivalence",
})


def robocodegen_revision() -> str:
    return (
        f"icra2023@{ROBOCODEGEN_SOURCE_COMMIT}:"
        f"protocol:{ROBOCODEGEN_PROTOCOL_DIGEST}"
    )


def build_robocodegen_source() -> BenchmarkSourceSpec:
    return BenchmarkSourceSpec(
        source_id=ROBOCODEGEN_BENCHMARK_ID,
        kind=BenchmarkSourceKind.GIT,
        revision_id=robocodegen_revision(),
        locator=ROBOCODEGEN_REPOSITORY,
        content_digest=ROBOCODEGEN_PROTOCOL_DIGEST,
        metadata={
            "paper_venue": "ICRA 2023",
            "task_count": str(ROBOCODEGEN_TASK_COUNT),
            "tests_per_task": str(ROBOCODEGEN_TESTS_PER_TASK),
            "notebook_path": ROBOCODEGEN_NOTEBOOK_PATH,
            "notebook_blob_sha": ROBOCODEGEN_NOTEBOOK_BLOB_SHA,
            "test_seed": "not-fixed-by-paper-notebook",
        },
    )


def build_robocodegen_37_cut() -> BenchmarkTaskSet:
    revision = robocodegen_revision()
    tasks = tuple(
        sorted(
            (
                TaskDefinition(
                    task_id=f"robocodegen-37:{name}",
                    revision_id=revision,
                    family="robot_code_generation",
                    schema_id=ROBOCODEGEN_TASK_SCHEMA_ID,
                    content_digest=canonical_digest({
                        "source_commit": ROBOCODEGEN_SOURCE_COMMIT,
                        "notebook_blob_sha": ROBOCODEGEN_NOTEBOOK_BLOB_SHA,
                        "function_name": name,
                        "function_signature": signature,
                        "tests_per_task": ROBOCODEGEN_TESTS_PER_TASK,
                    }),
                    lineage_refs=(
                        f"function:{name}",
                        f"signature:{signature}",
                        "test-count:5",
                        "test-seed:paper-notebook-unfixed",
                    ),
                    package=TaskPackageSpec(
                        package_schema_id="robocodegen.function-synthesis-package.v1",
                        instruction_digest=canonical_digest({
                            "function_name": name,
                            "function_signature": signature,
                        }),
                        environment_requirement_id=(
                            "benchmark.robocodegen.paper-era-python-scientific-stack"
                        ),
                        verifier_requirement_id=(
                            "benchmark.robocodegen.reference-function-equivalence"
                        ),
                        verifier_isolation=TaskVerifierIsolation.SEPARATE,
                    ),
                )
                for name, signature in ROBOCODEGEN_TASK_SIGNATURES
            ),
            key=lambda row: row.task_id,
        )
    )
    task_ids = tuple(row.task_id for row in tasks)
    return BenchmarkTaskSet(
        benchmark_id=ROBOCODEGEN_BENCHMARK_ID,
        revision_id=revision,
        source_digest=ROBOCODEGEN_PROTOCOL_DIGEST,
        task_schema_id=ROBOCODEGEN_TASK_SCHEMA_ID,
        tasks=tasks,
        splits=(TaskSetSplit(ROBOCODEGEN_ALL_SPLIT, task_ids),),
        selection_policy_digest=canonical_digest({
            "protocol_digest": ROBOCODEGEN_PROTOCOL_DIGEST,
            "task_ids": task_ids,
        }),
    )


def bind_robocodegen_37_cut() -> BenchmarkSourceResolution:
    return BenchmarkSourceResolution(
        source=build_robocodegen_source(),
        task_set=build_robocodegen_37_cut(),
    )


__all__ = [
    "ROBOCODEGEN_ALL_SPLIT",
    "ROBOCODEGEN_BENCHMARK_ID",
    "ROBOCODEGEN_NOTEBOOK_BLOB_SHA",
    "ROBOCODEGEN_NOTEBOOK_PATH",
    "ROBOCODEGEN_PROTOCOL_DIGEST",
    "ROBOCODEGEN_REPOSITORY",
    "ROBOCODEGEN_SOURCE_COMMIT",
    "ROBOCODEGEN_TASK_COUNT",
    "ROBOCODEGEN_TASK_SCHEMA_ID",
    "ROBOCODEGEN_TASK_SIGNATURES",
    "ROBOCODEGEN_TESTS_PER_TASK",
    "bind_robocodegen_37_cut",
    "build_robocodegen_37_cut",
    "build_robocodegen_source",
    "robocodegen_revision",
]
