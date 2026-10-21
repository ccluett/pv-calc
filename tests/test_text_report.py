"""The terminal text report: one line per fact, values with their basis."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from pv_calc.api import calculate
from pv_calc.cli import app
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.cylinder import SMOOTH_BUCKLING_PENDING_PLASTICITY_REASON
from pv_calc.presentation import _margin, _num, assess_response, render_text


EXAMPLES = Path(__file__).resolve().parents[1] / "examples"
runner = CliRunner()


def _q(value: float, unit: str = "MPa") -> dict:
    return {"value": value, "unit": unit}


def _example(name: str) -> dict:
    return calculate(json.loads((EXAMPLES / name).read_text()))


def _titanium_cylinder() -> dict:
    """A thick 6000 m titanium cylinder whose NASA check has come down to membrane yield."""
    return calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "cylinder",
        "material": {"type": "named", "name": "Ti-6Al-4V"},
        "inputs": {
            "depth": _q(6000, "m"), "fluid_density": _q(1025, "kg/m^3"),
            "gravity": _q(9.81, "m/s^2"), "design_factor": 1.25,
            "internal_radius": _q(147.8, "mm"), "wall_thickness": _q(14.09, "mm"),
            "unsupported_length": _q(11, "inch"),
        },
    })


@pytest.mark.parametrize(("value", "text"), [
    (75.41441, "75.41"), (827.0, "827"), (6251.2, "6,251"), (10938.4, "10,940"), (9999.6, "10,000"),
    (0.0009457, "0.0009457"), (1.427e-5, "1.427e-05"), (-0.6415, "-0.6415"), (0.0, "0"),
])
def test_numbers_have_four_significant_figures(value: float, text: str) -> None:
    assert _num(value) == text


def test_margins_read_to_three_decimals_and_a_solved_target_reads_zero() -> None:
    assert _margin(0.0541171) == "0.054"
    assert _margin(4.11277e-10) == "0.000"
    assert _margin(-1e-5) == "0.000"
    assert _margin(None) == "n/a"


def test_buckling_check_shows_the_estimate_and_the_elastic_pressure_it_came_from() -> None:
    text = render_text(_titanium_cylinder())
    lines = text.splitlines()
    assert lines[3] == "Pressure: 75.41 MPa design (6,000 m depth, 60.33 MPa service x 1.25)"
    buckling = next(line for line in lines if line.startswith("smooth_cylinder_buckling"))
    # A reference-only estimate is not a capacity, here or in the JSON.
    assert buckling.split()[1] == "INDETERMINATE"
    assert "pressure 75.41 MPa / n/a" in buckling and buckling.endswith("margin n/a")
    # Elastic buckling is well above demand; the plasticity factor shows the
    # corrected value is membrane yield, not elastic instability.
    assert lines[lines.index(buckling) + 1] == (
        "  reference-only material data: estimate 75.43 MPa, margin 0.000; "
        "elastic 129.3 MPa x plasticity factor 0.583"
    )


def test_a_reference_only_sweep_marks_its_capacities_as_estimates() -> None:
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "smooth-buckling",
        "material": {"type": "named", "name": "Ti-6Al-4V"},
        "inputs": {
            "external_pressure": _q(75.41), "shell_mid_surface_radius": _q(154.8, "mm"),
            "wall_thickness": _q(14.09, "mm"), "unsupported_length": _q(11, "inch"),
            "load_case": "hydrostatic_closed_end",
        },
    }
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": request,
        "inputs": {"geometry": "wall_thickness",
                   "axis": {"type": "list", "values": [_q(12, "mm"), _q(14, "mm")]}},
    })
    lines = render_text(response).splitlines()
    rows = [line for line in lines if line.startswith(("12 mm", "14 mm"))]
    assert all("MPa (estimate)" in row and row.endswith("(estimate)") for row in rows)
    assert "  smooth_cylinder_buckling: reference-only material data" in lines


def test_hemisphere_text_adds_no_bound_the_check_does_not_have() -> None:
    request = json.loads((EXAMPLES / "hemisphere_subsea_screen.json").read_text())
    request["inputs"]["external_pressure"] = _q(9.0)
    request["material"]["properties"]["proportional_limit"] = _q(50.0)
    response = calculate(request)
    buckling = next(check for check in assess_response(response)["checks"] if check["id"] == "hemisphere_buckling")
    assert "upper_bound" not in buckling
    assert "upper bound" not in render_text(response)


def test_the_pending_plasticity_reason_gives_way_only_to_its_upper_bound() -> None:
    wall = 152.4 / 10.55
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "cylinder",
        "material": {"type": "explicit", "name": "Ti-6Al-4V without a compressive curve", "properties": {
            "failure_category": "ductile_metal", "yield_strength": _q(827.0), "elastic_modulus": _q(113800.0),
            "poisson_ratio": 0.34, "proportional_limit": _q(602.0),
        }},
        "inputs": {"external_pressure": _q(1.0), "internal_radius": _q(152.4 - wall, "mm"),
                   "wall_thickness": _q(wall, "mm"), "unsupported_length": _q(609.6, "mm")},
    })
    check = next(check for check in response["assessment"]["checks"] if check["id"] == "smooth_cylinder_buckling")
    assert SMOOTH_BUCKLING_PENDING_PLASTICITY_REASON in check["reasons"]
    assert SMOOTH_BUCKLING_PENDING_PLASTICITY_REASON not in render_text(response)
    # Without the bound there is no note to replace the reason.
    del check["upper_bound"]
    assert f"  {SMOOTH_BUCKLING_PENDING_PLASTICITY_REASON}" in render_text(response).splitlines()


def test_report_carries_no_fixed_disclaimers() -> None:
    response = _example("cylinder_check.json")
    text = render_text(response)
    for boilerplate in (response["assessment"]["scope"], "Omitted", "Seals", "joint hardware"):
        assert boilerplate not in text
    # The scope and omissions remain in the JSON assessment.
    assert response["assessment"]["omissions"]
    assert text.splitlines()[-1] == "No closures supplied."


def test_cylinder_reports_mass_buoyancy_and_free_volume_on_one_line() -> None:
    text = render_text(_example("cylinder_housing.json"))
    assert (
        "Mass: 0.8885 kg in air (0.3885 kg structure + 0.5 kg payload); displaces 2.831 kg; "
        "net -1.942 kg (buoyant); free volume 2.518 L"
    ) in text.splitlines()
    # The cylinder compares pressures, so its stress check is labelled so.
    assert "pressure 0.1 / 5.605 MPa" in next(
        line for line in text.splitlines() if line.startswith("cylindrical_shell_stress")
    )


def test_tube_stress_check_is_labelled_as_stress() -> None:
    text = render_text(_example("tube_pvc_0_4166_ksi.json"))
    assert "stress 3.312 / 13.8 MPa" in text
    assert "Displacement: radial -0.04248 mm inner, -0.03588 mm outer; axial -0.03661 mm over 254 mm" in text


def test_a_model_without_checks_has_no_verdict() -> None:
    lines = render_text(_example("mass_properties_aluminium_housing.json")).splitlines()
    assert lines[0] == "mass-properties"
    assert lines[-1] == "Mass: 6.75 kg in air; displaces 6.15 kg; net 0.6 kg (sinks)"


def test_us_units_convert_every_quantity() -> None:
    text = render_text(_example("cylinder_housing.json"), units="us")
    assert "Pressure: 14.5 psi" in text
    assert "free volume 153.7 in^3" in text
    for unit in (" MPa", " mm", " kg", " L"):
        assert unit not in text


def test_sweep_is_one_header_and_one_row_per_point() -> None:
    lines = render_text(_example("sweep_tube_depth_range.json")).splitlines()
    assert lines[3] == "Pressure: from depth at 1,025 kg/m^3, g = 9.81 m/s^2, design factor 1.25"
    assert lines[4].split() == ["depth", "design", "pressure", "status", "stress", "capacity", "margin"]
    assert lines[5].split() == ["500", "m", "6.285", "MPa", "PASS", "43.1", "MPa", "427.5", "MPa", "8.918"]
    assert len(lines) == 8


def test_us_units_convert_the_depth_conversion() -> None:
    text = render_text(_example("sweep_tube_depth_range.json"), units="us")
    assert "Pressure: from depth at 63.99 lb/ft^3, g = 32.19 ft/s^2, design factor 1.25" in text


def test_batch_margin_header_carries_the_required_margin() -> None:
    result = runner.invoke(app, [
        "check", "--input", str(EXAMPLES / "sweep_tube_depth_range.json"), "--format", "text",
        "--minimum-margin", "0.5",
    ])
    assert result.stdout.splitlines()[4].endswith("margin (required 0.5)")


def test_multi_check_sweep_reports_the_lowest_margin_per_point() -> None:
    request = json.loads((EXAMPLES / "cylinder_housing.json").read_text())
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": request,
        "inputs": {"geometry": "wall_thickness",
                   "axis": {"type": "list", "values": [_q(0.8, "mm"), _q(1.0, "mm")]}},
    })
    lines = render_text(response).splitlines()
    assert "Geometry: internal radius 50 mm, unsupported length 300 mm" in lines
    assert lines[4].split()[:5] == ["wall", "thickness", "status", "lowest", "margin"]
    assert lines[5].split()[:5] == ["0.8", "mm", "PASS", "1.610", "smooth_cylinder_buckling"]


def test_check_text_applies_the_selected_checks_to_the_full_report() -> None:
    result = runner.invoke(app, [
        "check", "--input", str(EXAMPLES / "cylinder_check.json"), "--format", "text",
        "--check", "smooth_cylinder_buckling", "--minimum-margin", "0.5",
    ])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[1] == "Material: Illustrative ductile metal"
    checks = [line for line in lines if line.split()[0].endswith(("_stress", "_buckling"))]
    assert len(checks) == 1
    assert checks[0].endswith("margin 3.546 (required 0.5)")


def test_text_errors_are_text_and_json_errors_stay_json() -> None:
    options = ["tube", "--external-pressure", "1 MPa", "--internal-radius", "50 mm",
               "--wall-thickness", "2 mm", "--material", "Unobtainium"]
    text = runner.invoke(app, [*options, "--format", "text"])
    assert text.exit_code == 2
    assert text.stderr.splitlines()[0].startswith("error (unknown_material): material 'Unobtainium'")
    assert text.stderr.splitlines()[1].startswith("  available: Acrylic-PMMA, ")
    for extra in ([], ["--format", "text", "--json"]):
        detailed = runner.invoke(app, [*options, *extra])
        assert json.loads(detailed.stderr)["error"]["code"] == "unknown_material"


def test_sizing_failure_text_names_the_bounds_and_both_ends() -> None:
    result = runner.invoke(app, [
        "smooth-buckling", "size", "--external-pressure", "75 MPa",
        "--external-radius", "4.5 inch", "--unsupported-length", "16 inch",
        "--wall-thickness-lower", "4 mm", "--wall-thickness-upper", "30 mm",
        "--material", "Ti-6Al-4V", "--format", "text",
    ])
    assert result.exit_code == 2
    lines = result.stderr.splitlines()
    assert lines[0].startswith("error (no_reliable_solution): ")
    assert lines[1] == "  bounds: 4 mm to 30 mm"
    assert lines[2].startswith("  at 4 mm: smooth_cylinder_buckling governs, margin -")
    assert lines[3].startswith("  at 30 mm: withheld (")


@pytest.mark.parametrize("options", [["--units", "us"], ["--format", "text", "--units", "metric"]])
def test_units_apply_only_to_a_known_text_system(options: list[str]) -> None:
    result = runner.invoke(app, ["run", "--input", str(EXAMPLES / "tube_9_0401_ksi.json"), *options])
    assert result.exit_code == 2


def test_materials_list_text_is_one_row_per_record() -> None:
    result = runner.invoke(app, ["materials", "list", "--format", "text"])
    assert result.exit_code == 0, result.output
    lines = result.stdout.splitlines()
    assert lines[0].split() == ["material", "category", "strength", "E", "density", "buckling", "data"]
    titanium = next(line for line in lines if line.startswith("Ti-6Al-4V "))
    assert titanium.split() == [
        "Ti-6Al-4V", "ductile", "metal", "yield", "827", "MPa", "113.8", "GPa", "4,430", "kg/m^3", "reference-only",
    ]
    assert lines[-1] == "Database: bundled:pv_calc/data/materials.yaml"


def test_ring_report_lists_every_advisory_pressure() -> None:
    lines = render_text(_example("ring_shell_dtmb_17_spaces.json")).splitlines()
    assert lines[4] == "Advisory pressures (no acceptance capacity):"
    rows = {line.strip().split("  ")[0]: line for line in lines[5:12]}
    assert "5.257 MPa" in rows["mid-bay outer first yield, Lunchick"]
    assert "lowest" in rows["global buckling, Eq. 64 x 0.75"]
    assert rows["inter-ring bay buckling"].endswith("withheld")


def test_pressure_sweep_of_a_pressure_check_shows_the_pressure_once() -> None:
    request = json.loads((EXAMPLES / "smooth_buckling_moderate_nasa.json").read_text())
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": request,
        "inputs": {"external_pressure": {"type": "list", "values": [_q(0.01), _q(0.02)]}},
    })
    lines = render_text(response).splitlines()
    assert lines[3].split() == ["external", "pressure", "status", "capacity", "margin"]
    assert lines[4].split() == ["0.01", "MPa", "PASS", "0.1338", "MPa", "12.383"]

