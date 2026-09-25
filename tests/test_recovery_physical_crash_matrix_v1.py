from __future__ import annotations

from pathlib import Path

from scripts.verify_physical_crash_assurance import REQUIRED_L3, validate_matrix


ROOT = Path(__file__).resolve().parents[1]


def test_physical_crash_matrix_has_exactly_40_executable_cells() -> None:
    matrix = validate_matrix(ROOT)
    assert len(matrix["cases"]) == 40
    assert [case["id"] for case in matrix["cases"]] == [
        f"C{index:02d}" for index in range(1, 41)
    ]


def test_physical_crash_matrix_names_every_mandatory_l3_fault() -> None:
    matrix = validate_matrix(ROOT)
    qualification_cases = {
        case["L3"]["qualification_case"] for case in matrix["cases"]
    }
    assert REQUIRED_L3 <= qualification_cases


def test_unverified_server_cells_cannot_pass_the_strict_l3_gate() -> None:
    matrix = validate_matrix(ROOT)
    if any(case["L3"]["status"] != "passed" for case in matrix["cases"]):
        try:
            validate_matrix(ROOT, require_l3=True)
        except ValueError as exc:
            assert "L3 is not passed" in str(exc)
        else:
            raise AssertionError("strict L3 gate accepted unverified server cells")
