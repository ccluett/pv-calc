"""Concise views retain release gates, check scope, and batch context."""

from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from pathlib import Path

import pytest

from pv_calc.api import calculate
from pv_calc.contracts import CALC_SCHEMA_VERSION, PlateSizeRequest, SmoothBucklingSizeRequest, _validate_request
from pv_calc.errors import CalcCliError
from pv_calc.evaluate import _evaluate_single_request
from pv_calc.presentation import CSV_FIELDS, assess_response, render_csv, render_text, summarize_response
from pv_calc.sizing import _evaluate_plate_size, _evaluate_smooth_buckling_size


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def _example(model: str, name: str) -> dict:
    return _evaluate_single_request(model, json.loads((EXAMPLES / name).read_text()), None)


def _q(value: float | None, unit: str = "MPa") -> dict:
    return {"value": value, "unit": unit}


def test_summary_is_concise_retains_quantities_and_does_not_mutate() -> None:
    response = _example("tube", "tube_9_0401_ksi.json")
    original = deepcopy(response)
    summary = summarize_response(response)
    check = summary["assessment"]["checks"][0]
    assert check["id"] == "cylindrical_shell_stress"
    assert check["demand"] == response["result"]["governing_stress_mpa"]
    assert check["capacity"] == response["result"]["strength_mpa"]
    assert check["status"] == "pass"
    assert len(json.dumps(summary)) < len(json.dumps(response)) / 2
    assert "cylindrical_shell_stress: PASS" in render_text(response)
    assert "displacement: withheld_missing_elastic_properties" in render_text(response)
    assert response == original


@pytest.mark.parametrize("release_status", [
    "released_pending_plasticity", "withheld_applicability", "withheld_correlation_overlap",
])
def test_elastic_estimates_never_become_capacities(release_status: str) -> None:
    response = _example("smooth-buckling", "smooth_buckling_moderate_nasa.json")
    response["result"].update(capacity_status=release_status, margin=10.0,
                              release_gate_violations=["This is an elastic formula estimate."])
    summary = summarize_response(response)
    check = summary["assessment"]["checks"][0]
    assert check["status"] == "indeterminate"
    assert check["eligible"] is False
    assert check["capacity"]["value"] is None
    assert check["margin"] is None
    assert "elastic formula estimate" in render_text(response)
    assert summary["assessment"]["governing_check"] is None


def test_known_failure_takes_precedence_over_missing_requested_check() -> None:
    response = _example("tube", "tube_9_0401_ksi.json")
    response["result"].update(governing_stress_mpa=_q(500), strength_mpa=_q(200), margin=-0.6)
    assessment = assess_response(response, ["cylindrical_shell_stress", "smooth_cylinder_buckling"])
    assert assessment["status"] == "fail"
    assert [check["status"] for check in assessment["checks"]] == ["fail", "indeterminate"]
    assert assessment["required_check_coverage"]["complete"] is False
    assert assessment["governing_check"] is None
    # Conversely, a requested absent buckling calculation cannot be rescued
    # by a passing stress result elsewhere in the response.
    assert assess_response(response, ["smooth_cylinder_buckling"])["status"] == "indeterminate"


def test_scope_and_required_margin_are_explicit() -> None:
    response = _example("tube", "tube_9_0401_ksi.json")
    assert assess_response(response, minimum_margin=9.0)["status"] == "fail"
    assert "listed calculation checks" in assess_response(response)["scope"]
    for checks in ([], "cylindrical_shell_stress", [""]):
        with pytest.raises(CalcCliError, match="sequence"):
            assess_response(response, checks)  # type: ignore[arg-type]
    for target in (-1, float("inf"), True):
        with pytest.raises(CalcCliError, match="finite and nonnegative"):
            assess_response(response, minimum_margin=target)


def test_zero_demand_pass_requires_released_positive_capacity() -> None:
    response = _example("smooth-buckling", "smooth_buckling_moderate_nasa.json")
    response["result"].update(external_pressure_mpa=_q(0), margin=None)
    check = assess_response(response, minimum_margin=5.0)["checks"][0]
    assert check["status"] == "pass"
    assert check["margin"] is None
    assert "Zero demand" in " ".join(check["reasons"])
    response["result"]["capacity_status"] = "withheld_applicability"
    assert assess_response(response)["status"] == "indeterminate"


def test_thick_plate_withholds_bending_but_seat_check_can_remain_available() -> None:
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "plate",
        "inputs": {"external_pressure": _q(1), "free_radius": _q(50, "mm"),
                   "outside_radius": _q(60, "mm"), "plate_thickness": _q(15, "mm"),
                   "boundary_condition": "fixed"},
        "material": {"type": "named", "name": "Al-6061-T6"},
    }
    response = _evaluate_single_request("plate", request, None)
    checks = summarize_response(response)["assessment"]["checks"]
    assert checks[0]["id"] == "flat_endcap_bending"
    assert checks[0]["status"] == "indeterminate"
    assert checks[0]["capacity"]["value"] is None
    assert checks[1]["id"] == "seat_bearing"
    assert checks[1]["eligible"]
    assert assess_response(response, ["center_deflection"])["status"] == "indeterminate"


def test_coupled_sizing_retains_both_checks_and_targets() -> None:
    request = _validate_request(SmoothBucklingSizeRequest, json.loads((EXAMPLES / "smooth_buckling_size_moderate.json").read_text()))
    response = _evaluate_smooth_buckling_size(request, None)
    summary = summarize_response(response)
    checks = summary["assessment"]["checks"]
    assert [check["id"] for check in checks] == ["cylindrical_shell_stress", "smooth_cylinder_buckling"]
    assert summary["assessment"]["status"] == "pass"
    assert all(check["required_margin"] == response["sizing"]["target_minimum_margin"] for check in checks)
    assert summary["sizing"]["selected_wall_thickness"] == response["sizing"]["selected_wall_thickness"]


def test_plate_sizing_deflection_check_has_its_own_units_and_criterion() -> None:
    request = _validate_request(PlateSizeRequest, json.loads((EXAMPLES / "plate_size_deflection_limited.json").read_text()))
    response = _evaluate_plate_size(request, None)
    check = next(check for check in assess_response(response)["checks"] if check["id"] == "center_deflection")
    assert check["capacity"] == response["sizing"]["maximum_deflection"]
    assert check["demand"]["unit"] == "mm"
    assert check["required_margin"] == 0
    assert check["status"] == "pass"


def test_csv_has_one_row_per_point_and_check_and_preserves_unavailable_entries() -> None:
    tube = _example("tube", "tube_9_0401_ksi.json")
    sweep = {"model": "tube", "operation": "sweep", "sweep": {"points": [
        {"depth": _q(100, "m"), "response": tube},
        {"depth": _q(200, "m"), "response": tube},
    ]}}
    rows = list(csv.DictReader(io.StringIO(render_csv(sweep))))
    assert tuple(rows[0]) == CSV_FIELDS
    assert [row["axis_value"] for row in rows] == ["100", "200"]
    assert all(row["axis"] == "depth" and row["axis_unit"] == "m" for row in rows)
    comparison = {"model": "tube", "operation": "compare-materials", "comparison": {"entries": [
        {"material": "good", "outcome": "evaluated", "response": tube},
        {"material": "missing", "outcome": "invalid_material", "message": "Material lacks strength."},
    ]}}
    rows = list(csv.DictReader(io.StringIO(render_csv(comparison))))
    assert len(rows) == 2
    assert rows[1]["material"] == "missing"
    assert rows[1]["status"] == "indeterminate"
    assert rows[1]["reasons"] == "Material lacks strength."
    assert summarize_response(comparison)["assessment"]["status"] == "indeterminate"


def test_existing_cylinder_assessment_can_be_retargeted_without_mutation() -> None:
    response = {"model": "cylinder", "assessment": {
        "scope": "Tube stress and stability only.", "omissions": ["Seal design."],
        "checks": [{"id": "cylindrical_shell_stress", "demand": _q(1), "capacity": _q(2),
                    "margin": 1.0, "required_margin": 0.5, "applicability": "released", "reasons": []}],
    }}
    original = deepcopy(response)
    assert assess_response(response)["status"] == "pass"
    assert assess_response(response, minimum_margin=2)["status"] == "fail"
    assert summarize_response(response)["assessment"]["omissions"] == ["Seal design."]
    assert response == original


@pytest.mark.parametrize(("target", "expected"), [(0.2, "pass"), (1.1, "fail")])
def test_cylinder_boundary_status_is_unchanged_by_summary_or_check_retarget(
    target: float, expected: str,
) -> None:
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "cylinder",
        "inputs": {"external_pressure": _q(1), "internal_radius": _q(50, "mm"),
                   "wall_thickness": _q(1, "mm"), "unsupported_length": _q(100, "mm")},
        "material": {"type": "named", "name": "Al-6061-T6"},
    }
    capacity = calculate(request)["assessment"]["checks"][1]["capacity"]["value"]
    request["inputs"]["external_pressure"] = _q(capacity / (1 + target))
    base = calculate(request)
    # Raising the target uses the same capacity-demand comparison as native
    # cylinder evaluation at that target, without a numerical tolerance.
    assert assess_response(base, minimum_margin=target)["status"] == expected
    request["inputs"]["minimum_margin"] = target
    response = calculate(request)
    assert response["assessment"]["status"] == expected
    assert summarize_response(response)["assessment"]["status"] == expected
    assert expected.upper() in render_text(response)


def test_selected_stock_sizing_boundary_retains_solver_decision() -> None:
    material = {"type": "named", "name": "Al-6061-T6"}
    cylinder = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "cylinder", "material": material,
        "inputs": {"external_pressure": _q(1), "internal_radius": _q(50, "mm"),
                   "wall_thickness": _q(1, "mm"), "unsupported_length": _q(100, "mm")},
    })
    capacity = cylinder["assessment"]["checks"][1]["capacity"]["value"]
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "smooth-buckling", "operation": "size", "material": material,
        "inputs": {"external_pressure": _q(capacity / 2.1), "internal_radius": _q(50, "mm"),
                   "unsupported_length": _q(100, "mm"), "minimum_margin": 1.1,
                   "wall_thickness_bounds": {"lower": _q(0.5, "mm"), "upper": _q(1, "mm")},
                   "stock_thicknesses": [_q(1, "mm")]},
    })
    assert response["sizing"]["selected_check_margins"]["smooth_cylinder_buckling"] == 1.1
    assert summarize_response(response)["assessment"]["status"] == "pass"
    assert assess_response(response, minimum_margin=1.2)["status"] == "fail"
