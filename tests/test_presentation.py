"""Concise views retain release gates, check scope, and batch context."""

from __future__ import annotations

import csv
import io
import json
import math
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


def _qualified_aluminium() -> dict:
    """Test-only scoped material for checks unrelated to material selection."""
    return {
        "type": "explicit",
        "name": "Test 6061-T6 extrusion in qualified LT compression",
        "provenance": (
            "Test fixture scoped to a 6061-T6 extrusion and LT compression; "
            "not a generic alloy record."
        ),
        "properties": {
            "failure_category": "ductile_metal",
            "yield_strength": _q(241.0),
            "elastic_modulus": _q(68900.0),
            "poisson_ratio": 0.33,
            "proportional_limit": _q(183.4),
        },
    }


def test_ring_summary_reports_lowest_buckling_pressure_without_changing_acceptance() -> None:
    response = _example("ring-shell", "ring_shell_dtmb_17_spaces.json")
    before = deepcopy(response)
    summary = summarize_response(response)
    buckling = summary["ring_buckling"]
    governing = buckling["advisory_governing_pressure_mpa"]
    assert governing["unit"] == "MPa"
    assert governing == response["result"]["advisory_governing_pressure_mpa"]
    assert buckling["advisory_governing_mode"] == "global_eq64_with_eq91_ring_torsion"
    assert buckling["critical_circumferential_lobes_n"] == 3
    assert summary["assessment"]["status"] == "indeterminate"
    assert not any(check["eligible"] for check in summary["assessment"]["checks"])
    text = render_text(response)
    assert text.splitlines()[0] == "ring-shell: INDETERMINATE"
    assert "Lowest buckling or collapse pressure: " in text
    assert "Axisymmetric collapse (Lunchick, perfect shell): " in text
    assert "Bay surface von Mises at the applied pressure: " in text
    assert "Global buckling is elastic" in text
    assert response == before


@pytest.mark.parametrize("yield_mpa", [10.0, None])
def test_ring_pressure_display_retains_applicable_material_limits(yield_mpa) -> None:
    request = json.loads((EXAMPLES / "ring_shell_dtmb_17_spaces.json").read_text())
    properties = request["material"]["properties"]
    if yield_mpa is None:
        properties.pop("yield_strength")
    else:
        properties["yield_strength"] = _q(yield_mpa)
    response = calculate(request)
    summary = summarize_response(response)
    text = render_text(response)
    assert "Lowest buckling or collapse pressure: " in text
    if yield_mpa is None:
        # Without a yield strength there is no collapse mode, and the global
        # mode keeps its undetermined material label.
        assert summary["ring_buckling"]["advisory_governing_status"] == (
            "advisory_plasticity_undetermined"
        )
        assert "proportional limit not supplied" in text
        assert "ring_collapse" not in summary
    else:
        # A 10 MPa yield puts every buckling pressure above yield; the shell
        # collapses by yield first, and the global mode stays labelled an
        # elastic upper bound in its own screen.
        assert summary["ring_buckling"]["advisory_governing_mode"] == (
            "axisymmetric_collapse_lunchick"
        )
        assert summary["ring_buckling"]["advisory_governing_status"] == "advisory"
        assert response["result"]["global_elastic_applicability"] == "exceeded"
        assert "axisymmetric collapse, Lunchick" in text
    assert summary["assessment"]["status"] == "indeterminate"


def test_ring_display_with_a_plasticity_corrected_bay_governing_is_not_called_elastic() -> None:
    material = _qualified_aluminium()
    material["properties"].update(ramberg_osgood_n=20, compressive_proof_stress=_q(241.0))
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "ring-shell",
        "inputs": {
            "external_pressure": _q(1.0),
            "shell_mid_surface_radius": _q(100, "mm"),
            "wall_thickness": _q(3, "mm"),
            "unsupported_length": _q(600, "mm"),
            "ring_spacing": _q(60, "mm"),
            "ring_axial_width": _q(8, "mm"),
            "ring_radial_height": _q(10, "mm"),
            "ring_location": "external",
        },
        "material": material,
    })
    result = response["result"]
    bay = result["inter_ring_shell_buckling"]
    assert result["advisory_governing_mode"] == "inter_ring_smooth_shell"
    assert bay["capacity_status"] == "released"
    assert 0.0 < bay["plasticity_factor"] < 1.0
    governing = bay["correlated_critical_pressure_mpa"]
    # Corrected at the bay's mid-bay hoop stress; p*r/t gave 7.33657 MPa.
    assert bay["circumferential_stress_basis"] == "ring_stiffened_mid_bay_hoop_membrane"
    assert governing["value"] == pytest.approx(7.764324783821008)
    assert governing["value"] < result["global_with_ring_torsion"]["adjusted_critical_pressure_mpa"]["value"]

    summary = summarize_response(response)
    assert summary["ring_buckling"]["advisory_governing_pressure_mpa"] == governing
    assert "critical_circumferential_lobes_n" not in summary["ring_buckling"]
    text = render_text(response)
    assert "Lowest buckling or collapse pressure: 7.76432 MPa (inter-ring bay)" in text
    assert "Global buckling is elastic" in text
    assert "Elastic buckling only" not in text
    assert summary["assessment"]["status"] == "indeterminate"


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
    "released_pending_plasticity", "released_unqualified_material",
    "withheld_applicability", "withheld_correlation_overlap",
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


@pytest.mark.parametrize(
    ("ring_width", "parent_status", "inter_ring_status"),
    [(5.0, "advisory", "advisory"),
     (160.0, "withheld_invalid_applicability", "withheld_invalid_applicability")],
)
def test_ring_bay_estimate_cannot_be_promoted_to_a_released_check(
    ring_width: float, parent_status: str, inter_ring_status: str,
) -> None:
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "ring-shell",
        "inputs": {
            "external_pressure": _q(0.1),
            "shell_mid_surface_radius": _q(100, "mm"),
            "wall_thickness": _q(1, "mm"),
            "unsupported_length": _q(600, "mm"),
            "ring_spacing": _q(150, "mm"),
            "ring_axial_width": _q(ring_width, "mm"),
            "ring_radial_height": _q(5, "mm"),
            "ring_location": "external",
        },
        "material": _qualified_aluminium(),
    })
    estimate = response["result"]["inter_ring_shell_buckling"][
        "correlated_critical_pressure_mpa"
    ]
    assert response["result"]["capacity_status"] == parent_status
    assert estimate["value"] == pytest.approx(0.3211519092350811)

    default = assess_response(response)
    selected = assess_response(response, ["inter_ring_shell_buckling"])
    assert default["status"] == selected["status"] == "indeterminate"
    check = selected["checks"][0]
    assert check["applicability"] == inter_ring_status
    assert check["eligible"] is False
    assert check["capacity"]["value"] is None
    assert check["margin"] is None
    assert "advisory" in " ".join(check["reasons"])
    if ring_width > 150:
        assert "do not overlap" in " ".join(check["reasons"])

    summary = summarize_response(response, ["inter_ring_shell_buckling"])
    assert summary["assessment"] == selected
    assert ("ring_buckling" in summary) == (parent_status == "advisory")
    selected_payload = {
        "schema_version": response["schema_version"],
        "model": response["model"],
        "assessment": selected,
    }
    text = render_text(selected_payload)
    assert "ring-shell: INDETERMINATE" in text
    assert "inter_ring_shell_buckling: INDETERMINATE" in text
    assert "capacity unavailable" in text
    row = next(csv.DictReader(io.StringIO(render_csv(selected_payload))))
    assert row["status"] == "indeterminate"
    assert row["eligible"] == "False"
    assert row["applicability"] == inter_ring_status
    assert row["capacity"] == ""


def test_reference_only_ring_bay_remains_advisory_and_unqualified() -> None:
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "ring-shell",
        "inputs": {
            "external_pressure": _q(0.1),
            "shell_mid_surface_radius": _q(100, "mm"),
            "wall_thickness": _q(1, "mm"),
            "unsupported_length": _q(600, "mm"),
            "ring_spacing": _q(150, "mm"),
            "ring_axial_width": _q(5, "mm"),
            "ring_radial_height": _q(5, "mm"),
            "ring_location": "external",
        },
        "material": {"type": "named", "name": "Al-6061-T6"},
    })

    bay = response["result"]["inter_ring_shell_buckling"]
    assert bay["capacity_status"] == "released_unqualified_material"
    assert bay["correlated_critical_pressure_mpa"]["value"] is not None
    check = assess_response(response, ["inter_ring_shell_buckling"])["checks"][0]
    assert check["applicability"] == "advisory_unqualified_material"
    assert check["eligible"] is False
    assert check["capacity"]["value"] is None
    assert check["status"] == "indeterminate"


def test_converged_lobar_search_cannot_pass_with_a_lower_excluded_axisymmetric_mode() -> None:
    # An independent n=0 reduction of the smeared equations gives a lower
    # elastic pressure than the converged lobar search for this geometry.
    # It is a scope counterexample, not a validated axisymmetric capacity.
    e, nu, r, t, length, pitch, width, height = 70_000, 0.33, 100, 1, 500, 20, 2, 20
    dx = e*t**3/(12*(1-nu**2))
    membrane = e*(t + width*height/pitch)
    continuous_m = length/math.pi * (membrane/(dx*r*r))**0.25
    axisymmetric_pressure = min(
        2/r * (dx*(m*math.pi/length)**2 + membrane/(r*r*(m*math.pi/length)**2))
        for m in (math.floor(continuous_m), math.ceil(continuous_m))
    )
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "ring-shell",
        "inputs": {
            "external_pressure": _q(0.1),
            "shell_mid_surface_radius": _q(r, "mm"),
            "wall_thickness": _q(t, "mm"),
            "unsupported_length": _q(length, "mm"),
            "ring_spacing": _q(pitch, "mm"),
            "ring_axial_width": _q(width, "mm"),
            "ring_radial_height": _q(height, "mm"),
            "ring_location": "external",
        },
        "material": {"type": "explicit", "properties": {
            "failure_category": "ductile_metal",
            "elastic_modulus": _q(e), "poisson_ratio": nu,
            "proportional_limit": _q(10_000), "yield_strength": _q(10_000),
        }},
    })
    result = response["result"]
    lobar = result["global_with_ring_torsion"]
    assert lobar["converged"] is True
    assert lobar["mode_domain"] == "1<=m<=maximum_axial_half_waves_m,n>=2"
    assert axisymmetric_pressure < lobar["ideal_critical_pressure_mpa"]["value"]
    assert result["global_elastic_applicability"] == "within"
    dispositions = {item["mode"]: item["disposition"] for item in result["mode_dispositions"]}
    assert dispositions["axisymmetric_hydrostatic_buckling"] == "not_implemented"
    assert dispositions["physical_end_restraint"] == "external_blocker"

    selected = summarize_response(response, ["ring_shell_global_buckling"])
    check = selected["assessment"]["checks"][0]
    assert selected["assessment"]["status"] == "indeterminate"
    assert check["eligible"] is False
    assert check["capacity"]["value"] is None
    assert check["margin"] is None
    assert "n=0" in " ".join(check["reasons"])
    assert "n=0" in render_text(selected)
    row = next(csv.DictReader(io.StringIO(render_csv(selected))))
    assert row["status"] == "indeterminate"
    assert row["capacity"] == ""
    assert "n=0" in row["reasons"]


def _uncorrected_titanium() -> dict:
    """Exercise the proportional-limit screen without the bundled curve."""
    return {
        "type": "explicit",
        "name": "Ti-6Al-4V without a compressive curve",
        "properties": {
            "failure_category": "ductile_metal",
            "yield_strength": _q(827.0),
            "elastic_modulus": _q(113800.0),
            "poisson_ratio": 0.34,
            "proportional_limit": _q(602.0),
        },
    }


@pytest.mark.parametrize("model", ["cylinder", "smooth-buckling"])
@pytest.mark.parametrize(
    ("pressure", "expected_status"),
    [(1.0, "indeterminate"), (92.35134, "fail")],
)
def test_pending_pressure_is_visible_and_its_elastic_upper_bound_can_reject(
    model: str, pressure: float, expected_status: str,
) -> None:
    wall = 152.4 / 10.55
    radius_input = (
        {"internal_radius": _q(152.4 - wall, "mm")}
        if model == "cylinder" else {
            "shell_mid_surface_radius": _q(152.4 - wall / 2.0, "mm"),
            "load_case": "hydrostatic_closed_end",
        }
    )
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": model,
        "material": _uncorrected_titanium(),
        "inputs": {"external_pressure": _q(pressure), "wall_thickness": _q(wall, "mm"),
                   "unsupported_length": _q(609.6, "mm"), **radius_input},
    })
    original = deepcopy(response)
    summary = summarize_response(response)
    estimate = summary["outputs"]["elastic_buckling_estimate"]
    assert estimate["status"] == "released_pending_plasticity"
    assert estimate["value"]["value"] == pytest.approx(63.685456731934785)
    check = next(c for c in summary["assessment"]["checks"] if c["id"] == "smooth_cylinder_buckling")
    assert check["status"] == expected_status
    assert check["capacity"]["value"] is None
    assert check["upper_bound"]["value"] == pytest.approx(63.685456731934785)
    assert check["margin"] is None
    assert "elastic_buckling_estimate: released_pending_plasticity | 63.6855 MPa" in render_text(response)
    assert "upper bound 63.6855 MPa" in render_text(response)
    if expected_status == "fail":
        assert any("could only reduce or withhold it" in reason for reason in check["reasons"])
        row = next(csv.DictReader(io.StringIO(render_csv(response))))
        if model == "cylinder":
            row = next(
                item
                for item in csv.DictReader(io.StringIO(render_csv(response)))
                if item["check"] == "smooth_cylinder_buckling"
            )
        assert float(row["upper_bound"]) == pytest.approx(63.685456731934785)
    assert response == original


@pytest.mark.parametrize("model", ["cylinder", "smooth-buckling"])
@pytest.mark.parametrize(
    ("pressure", "expected_status"),
    [(63.0, "indeterminate"), (64.0, "fail")],
)
def test_reference_curve_uses_the_elastic_bound_not_the_corrected_estimate(
    model: str, pressure: float, expected_status: str,
) -> None:
    wall = 152.4 / 10.55
    radius_input = (
        {"internal_radius": _q(152.4 - wall, "mm")}
        if model == "cylinder" else {
            "shell_mid_surface_radius": _q(152.4 - wall / 2.0, "mm"),
            "load_case": "hydrostatic_closed_end",
        }
    )
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": model,
        "material": {"type": "named", "name": "Ti-6Al-4V"},
        "inputs": {
            "external_pressure": _q(pressure),
            "wall_thickness": _q(wall, "mm"),
            "unsupported_length": _q(609.6, "mm"),
            **radius_input,
        },
    })

    summary = summarize_response(response)
    check = next(
        item
        for item in summary["assessment"]["checks"]
        if item["id"] == "smooth_cylinder_buckling"
    )
    assert check["applicability"] == "released_unqualified_material"
    assert check["status"] == expected_status
    assert check["capacity"]["value"] is None
    assert check["upper_bound"]["value"] == pytest.approx(63.685456731934785)
    assert summary["outputs"]["reference_buckling_estimate"]["value"][
        "value"
    ] == pytest.approx(62.7161928406424)
    reason = next(reason for reason in check["reasons"] if "reference-only" in reason)
    assert render_text(response).count(reason) == 1
    if expected_status == "fail":
        coverage = summary["assessment"]["required_check_coverage"]
        assert "smooth_cylinder_buckling" in coverage["evaluated"]
        assert coverage["complete"] is False
        assert summary["assessment"]["governing_check"] is None
    if pressure == 63.0:
        # A different qualified curve could lie above the reference correction,
        # up to the elastic bound. A stricter requested margin can still make
        # rejection certain without turning the estimate into a capacity.
        assert assess_response(response, minimum_margin=0.02)["status"] == "fail"


@pytest.mark.parametrize("model", ["cylinder", "smooth-buckling"])
def test_compressive_curve_replaces_the_pending_estimate_with_a_capacity(model: str) -> None:
    wall = 152.4 / 10.55
    radius_input = (
        {"internal_radius": _q(152.4 - wall, "mm")}
        if model == "cylinder" else {
            "shell_mid_surface_radius": _q(152.4 - wall / 2.0, "mm"),
            "load_case": "hydrostatic_closed_end",
        }
    )
    material = _uncorrected_titanium()
    material["name"] = "Ti-6Al-4V with an explicit compressive curve"
    material["properties"].update({
        "ramberg_osgood_n": 21.0,
        "compressive_proof_stress": _q(827.0),
    })
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": model,
        "material": material,
        "inputs": {"external_pressure": _q(92.35134), "wall_thickness": _q(wall, "mm"),
                   "unsupported_length": _q(609.6, "mm"), **radius_input},
    })
    summary = summarize_response(response)
    assert "elastic_buckling_estimate" not in summary.get("outputs", {})
    check = next(c for c in summary["assessment"]["checks"] if c["id"] == "smooth_cylinder_buckling")
    assert check["capacity"]["value"] == pytest.approx(62.7161928406424)
    assert check["margin"] is not None
    assert check["status"] == "fail"


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


@pytest.mark.parametrize(("strength_fraction", "required_margin"), [
    (2 / 3, 0.5), (3 / 4, 1 / 3),
])
@pytest.mark.parametrize(("load_fraction", "expected"), [(0.99, "pass"), (1.01, "fail")])
def test_strength_fraction_targets_agree_for_tube_and_cylinder(
    strength_fraction: float, required_margin: float,
    load_fraction: float, expected: str,
) -> None:
    """A policy target changes acceptance without changing material strength."""
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "tube",
        "inputs": {"external_pressure": _q(1), "internal_radius": _q(50, "mm"),
                   "wall_thickness": _q(1, "mm")},
        "material": {"type": "named", "name": "Al-6061-T6"},
    }
    reference = calculate(request)["result"]
    failure_pressure = reference["theoretical_failure_pressure_mpa"]["value"]
    request["inputs"]["external_pressure"] = _q(
        failure_pressure * strength_fraction * load_fraction,
    )
    response = calculate(request)
    result = response["result"]
    assert result["strength_mpa"] == reference["strength_mpa"]
    assert result["governing_stress_mpa"]["value"] == pytest.approx(
        result["strength_mpa"]["value"] * strength_fraction * load_fraction,
    )
    assert assess_response(
        response, ["cylindrical_shell_stress"], minimum_margin=required_margin,
    )["status"] == expected

    cylinder = calculate({
        **request, "model": "cylinder",
        "inputs": {**request["inputs"], "unsupported_length": _q(100, "mm"),
                   "minimum_margin": required_margin},
    })
    stress_check = next(
        check for check in cylinder["assessment"]["checks"]
        if check["id"] == "cylindrical_shell_stress"
    )
    assert stress_check["status"] == expected
    assert assess_response(cylinder, ["cylindrical_shell_stress"])["status"] == expected


def test_assessment_is_importable_from_both_modules() -> None:
    import pv_calc.assessment
    import pv_calc.presentation

    assert pv_calc.presentation.assess_response is pv_calc.assessment.assess_response


@pytest.mark.parametrize(("demand", "capacity"), [(-1.0, 5.0), (1.0, 0.0), (1.0, -5.0), (None, 5.0)])
def test_check_decision_is_indeterminate_without_a_nonnegative_demand_and_positive_capacity(
    demand: float | None, capacity: float | None,
) -> None:
    from pv_calc.assessment import check_decision

    decision = check_decision(
        demand=demand, capacity=capacity, applicability="released", required_margin=0.0,
    )
    assert decision.status == "indeterminate"
    assert not decision.eligible


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


@pytest.mark.parametrize(
    ("pressure", "expected_status"),
    [(6.0, "indeterminate"), (20.0, "fail")],
)
def test_named_hemisphere_reference_estimate_uses_its_elastic_upper_bound(
    pressure: float, expected_status: str,
) -> None:
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "hemisphere",
        "inputs": {
            "external_pressure": _q(pressure),
            "internal_radius": _q(100, "mm"),
            "wall_thickness": _q(100 / 39.5, "mm"),
        },
        "material": {"type": "named", "name": "Al-6061-T6"},
    })

    assert response["result"]["buckling_capacity_status"] == (
        "released_unqualified_material"
    )
    summary = summarize_response(response)
    buckling = next(
        check for check in summary["assessment"]["checks"]
        if check["id"] == "hemisphere_buckling"
    )
    assert buckling["status"] == expected_status
    assert buckling["capacity"]["value"] is None
    assert buckling["upper_bound"]["value"] == pytest.approx(8.018849005433532)
    estimate = summary["outputs"]["reference_buckling_estimate"]
    assert estimate["value"]["value"] is not None
    assert "reference_buckling_estimate: released_unqualified_material" in render_text(
        response
    )


def test_coupled_sizing_retains_both_checks_and_targets() -> None:
    request = _validate_request(SmoothBucklingSizeRequest, json.loads((EXAMPLES / "smooth_buckling_size_moderate.json").read_text()))
    response = _evaluate_smooth_buckling_size(request, None)
    summary = summarize_response(response)
    checks = summary["assessment"]["checks"]
    assert [check["id"] for check in checks] == ["cylindrical_shell_stress", "smooth_cylinder_buckling"]
    assert summary["assessment"]["status"] == "pass"
    assert all(check["required_margin"] == response["sizing"]["target_minimum_margin"] for check in checks)
    assert summary["sizing"]["selected_wall_thickness"] == response["sizing"]["selected_wall_thickness"]


def test_reference_only_curve_can_size_preliminarily_without_passing_check() -> None:
    raw = json.loads((EXAMPLES / "smooth_buckling_size_moderate.json").read_text())
    raw["material"] = {"type": "named", "name": "Al-6061-T6"}
    request = _validate_request(SmoothBucklingSizeRequest, raw)
    response = _evaluate_smooth_buckling_size(request, None)

    assert response["sizing"]["selected_wall_thickness"]["value"] > 0
    assert response["sizing"]["buckling_data_qualification"] == "reference_only"
    buckling = response["selected_results"]["smooth-buckling"]["result"]
    assert buckling["capacity_status"] == "released_unqualified_material"
    summary = summarize_response(response)
    assert summary["assessment"]["status"] == "indeterminate"
    estimate = summary["outputs"]["reference_buckling_estimate"]
    assert estimate["value"] == buckling["correlated_critical_pressure_mpa"]


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


@pytest.mark.parametrize(("offset", "expected"), [(-1.0e-9, "pass"), (1.0e-9, "fail")])
def test_cylinder_boundary_status_is_unchanged_by_summary_or_check_retarget(
    offset: float, expected: str,
) -> None:
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "cylinder",
        "inputs": {"external_pressure": _q(1), "internal_radius": _q(50, "mm"),
                   "wall_thickness": _q(1, "mm"), "unsupported_length": _q(100, "mm")},
        "material": _qualified_aluminium(),
    }
    capacity = calculate(request)["assessment"]["checks"][1]["capacity"]["value"]
    # Straddle the target to avoid testing the last bit of division rounding.
    request["inputs"]["external_pressure"] = _q(capacity / 2.1)
    target = 1.1 + offset
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
    material = _qualified_aluminium()
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
