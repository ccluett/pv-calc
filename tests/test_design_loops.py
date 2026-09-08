"""Geometry design loops, fixed-OD sizing, and independently checked stock sizes."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    MaterialComparisonRequest,
    SmoothBucklingSizeRequest,
    SweepRequest,
    TubeSizeRequest,
)
from pv_calc.errors import CalcCliError
from pv_calc.evaluate import (
    _evaluate_single_request,
    _evaluate_material_comparison,
    _evaluate_sweep,
)
from pv_calc.pressure_vessel import (
    closed_end_tube_stress,
    smooth_cylinder_external_pressure_buckling,
)

from _cli_helpers import EXAMPLES, MATERIALS_FILE, SWEEP_FORWARD_EXAMPLES


def q(value: float, unit: str = "mm") -> dict[str, Any]:
    return {"value": float(value), "unit": unit}


def size_request(model: str = "smooth-buckling", *, outer: bool = True) -> dict[str, Any]:
    request = json.loads((EXAMPLES / "smooth_buckling_size_moderate.json").read_text())
    request["model"] = model
    request["inputs"]["wall_thickness_bounds"] = {"lower": q(1), "upper": q(20)}
    if outer:
        request["inputs"]["external_radius"] = request["inputs"].pop("internal_radius")
    if model == "tube":
        request["inputs"]["axial_length"] = request["inputs"].pop("unsupported_length")
        # Tube request material contracts do not carry proportional limits.
        request["material"]["properties"].pop("proportional_limit")
    return request


def evaluate_size(request: dict[str, Any]) -> dict[str, Any]:
    return _evaluate_single_request(request["model"], request, None)


def comparison(request: dict[str, Any], names: list[str]) -> MaterialComparisonRequest:
    return MaterialComparisonRequest.model_validate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "compare-materials",
        "request": request,
        "inputs": {"materials": names},
    })


@pytest.mark.parametrize("model", list(SWEEP_FORWARD_EXAMPLES))
def test_geometry_sweep_points_equal_independent_forward_calls(model: str) -> None:
    base = json.loads((EXAMPLES / SWEEP_FORWARD_EXAMPLES[model]).read_text())
    variable = "plate_thickness" if model == "plate" else "wall_thickness"
    original = base["inputs"][variable]
    values = [original, {**original, "value": original["value"] * 0.8}, original]
    request = SweepRequest.model_validate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "sweep",
        "request": base,
        "inputs": {"geometry": variable, "axis": {"type": "list", "values": values}},
    })
    result = _evaluate_sweep(request, MATERIALS_FILE)
    assert result["sweep"]["swept_input"] == f"inputs.{variable}"
    for index, point in enumerate(result["sweep"]["points"]):
        single = copy.deepcopy(base)
        single["inputs"][variable] = values[index]
        assert point[variable] == values[index]
        assert point["response"] == _evaluate_single_request(model, single, MATERIALS_FILE)


def test_geometry_range_interpolates_lengths_and_keeps_descending_endpoints() -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text())
    request = SweepRequest.model_validate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "sweep",
        "request": base,
        "inputs": {"geometry": "axial_length", "axis": {
            "type": "range", "start": q(1, "m"), "stop": q(100), "count": 3,
        }},
    })
    result = _evaluate_sweep(request, MATERIALS_FILE)
    assert [point["axial_length"] for point in result["sweep"]["points"]] == [q(1000), q(550), q(100)]


def test_geometry_sweep_validates_model_axis_and_dimension() -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text())
    payload = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": base,
        "inputs": {"geometry": "ring_spacing", "axis": {"type": "list", "values": [q(10)]}},
    }
    with pytest.raises(ValidationError, match="tube geometry sweep supports"):
        SweepRequest.model_validate(payload)
    payload["inputs"]["geometry"] = "wall_thickness"
    payload["inputs"]["axis"]["values"] = [q(1, "MPa")]
    with pytest.raises(CalcCliError) as exc:
        _evaluate_sweep(SweepRequest.model_validate(payload), MATERIALS_FILE)
    assert exc.value.code == "incompatible_unit"
    assert exc.value.details[-1]["point_index"] == 0
    payload["inputs"]["external_pressure"] = {"type": "list", "values": [q(1, "MPa")]}
    with pytest.raises(ValidationError):
        SweepRequest.model_validate(payload)


def test_fixed_od_tube_root_matches_independent_lame_inversion() -> None:
    request = size_request("tube")
    request["inputs"]["external_pressure"] = q(10, "MPa")
    result = evaluate_size(request)
    wall = result["sizing"]["selected_wall_thickness"]["value"]
    # At the bore VM = sqrt(3)*p*Ro^2/(Ro^2-Ri^2), Ri = Ro-t.
    expected = 100 * (1 - math.sqrt(1 - math.sqrt(3) * 10 * 1.25 / 250))
    assert wall == pytest.approx(expected, abs=5e-9)
    assert result["result"]["internal_radius_mm"] == q(100 - wall)
    assert result["result"]["axial_length_mm"] == q(700)
    assert result["sizing"]["verified_bracket"]["lower"]["minimum_margin"] < 0.25
    assert result["sizing"]["selected_minimum_margin"] >= 0.25


@pytest.mark.parametrize("model", ["tube", "smooth-buckling"])
def test_sizing_requires_exactly_one_radius_and_positive_bore(model: str) -> None:
    payload = size_request(model)
    contract = TubeSizeRequest if model == "tube" else SmoothBucklingSizeRequest
    payload["inputs"]["internal_radius"] = q(90)
    with pytest.raises(ValidationError, match="exactly one"):
        contract.model_validate(payload)
    payload["inputs"].pop("internal_radius")
    payload["inputs"].pop("external_radius")
    with pytest.raises(ValidationError, match="exactly one"):
        contract.model_validate(payload)
    payload["inputs"]["external_radius"] = q(20)
    with pytest.raises(CalcCliError, match="positive bore") as exc:
        evaluate_size(payload)
    assert exc.value.code == "invalid_bounds"


@pytest.mark.parametrize("length", [100, 700, 2000, 4000])
def test_fixed_od_smooth_sizing_selects_eligible_geometry_and_respects_earlier_domains(length: int) -> None:
    request = size_request()
    request["inputs"]["unsupported_length"] = q(length)
    result = evaluate_size(request)
    wall = result["sizing"]["selected_wall_thickness"]["value"]
    assert result["sizing"]["shell_mid_surface_radius_convention"] == "external_radius_minus_half_wall_thickness"
    assert result["sizing"]["selected_shell_mid_surface_radius"] == q(100 - wall / 2)
    selected = result["selected_results"]
    assert selected["tube"]["result"]["internal_radius_mm"] == q(100 - wall)
    assert selected["smooth-buckling"]["result"]["capacity_status"] == "released"
    assert result["sizing"]["selected_minimum_margin"] >= 0.25
    # Probe the earlier domain independently through the kernels, including
    # overlap/plasticity bands. No eligible earlier point may meet both targets.
    for index in range(101):
        candidate = 1 + (wall - 1) * index / 102
        tube = closed_end_tube_stress(
            external_pressure_mpa=2, internal_radius_mm=100-candidate,
            wall_thickness_mm=candidate, material_failure_category="ductile_metal",
            strength_mpa=250,
        )
        buckling = smooth_cylinder_external_pressure_buckling(
            external_pressure_mpa=2, shell_mid_surface_radius_mm=100-candidate/2,
            wall_thickness_mm=candidate, unsupported_length_mm=length,
            elastic_modulus_mpa=70000, poisson_ratio=0.3,
            load_case="hydrostatic_closed_end", proportional_limit_mpa=200,
            yield_strength_mpa=250,
        )
        if buckling.capacity_status == "released":
            assert tube.margin is not None and buckling.margin is not None
            assert min(tube.margin, buckling.margin) < 0.25


def test_fixed_od_search_crosses_withheld_overlap_and_rejects_thick_shell_band() -> None:
    request = size_request()
    request["inputs"]["unsupported_length"] = q(2000)
    result = evaluate_size(request)
    excluded = result["sizing"]["excluded_thickness_intervals"]
    assert any("overlap" in " ".join(entry["withheld_reasons"]) for entry in excluded)
    boundaries = {entry["boundary"]: entry for entry in result["sizing"]["derived_branch_partition"]}
    assert boundaries["buckling_thin_shell_radius_thickness_limit"]["wall_thickness"]["value"] == pytest.approx(100/10.5)
    request["inputs"]["wall_thickness_bounds"] = {"lower": q(10), "upper": q(20)}
    with pytest.raises(CalcCliError) as exc:
        evaluate_size(request)
    assert exc.value.code == "no_reliable_solution"
    assert exc.value.details[0]["withheld_evaluations"]


@pytest.mark.parametrize("outer", [True, False])
def test_stock_checks_all_candidates_retains_unknowns_and_selects_smallest_pass(outer: bool) -> None:
    request = size_request(outer=outer)
    request["inputs"]["unsupported_length"] = q(100)
    request["inputs"]["stock_thicknesses"] = [q(3), q(1), q(2), q(25), q(2)]
    result = evaluate_size(request)
    sizing = result["sizing"]
    assert sizing["selected_wall_thickness"] == q(2)
    assert sizing["solution_type"] == "stock_candidate"
    assert sizing["algorithm"] == "stock_candidate_evaluation"
    assert sizing["bisection_iterations"] == 0
    assert sizing["verified_bracket"] is None
    assert [row["outcome"] for row in sizing["stock_candidates"]] == [
        "unavailable", "fails_targets", "meets_targets", "outside_bounds", "meets_targets",
    ]
    for row in sizing["stock_candidates"]:
        if row["outcome"] == "outside_bounds":
            continue
        t = row["thickness"]["value"]
        inner = 100-t if outer else 100
        tube = closed_end_tube_stress(
            external_pressure_mpa=2, internal_radius_mm=inner, wall_thickness_mm=t,
            material_failure_category="ductile_metal", strength_mpa=250,
        )
        assert row["check_margins"]["cylindrical_shell_stress"] == tube.margin
        if row["outcome"] != "unavailable":
            buckling = smooth_cylinder_external_pressure_buckling(
                external_pressure_mpa=2, shell_mid_surface_radius_mm=inner+t/2,
                wall_thickness_mm=t, unsupported_length_mm=100,
                elastic_modulus_mpa=70000, poisson_ratio=0.3,
                load_case="hydrostatic_closed_end", proportional_limit_mpa=200,
                yield_strength_mpa=250,
            )
            assert row["check_margins"]["smooth_cylinder_buckling"] == buckling.margin


def test_stock_failure_preserves_failed_and_unavailable_candidates() -> None:
    request = size_request()
    request["inputs"]["unsupported_length"] = q(100)
    request["inputs"]["stock_thicknesses"] = [q(3), q(1), q(25)]
    with pytest.raises(CalcCliError) as exc:
        evaluate_size(request)
    assert exc.value.code == "no_reliable_solution"
    rows = exc.value.details[0]["stock_candidates"]
    assert [row["outcome"] for row in rows] == ["unavailable", "fails_targets", "outside_bounds"]
    assert rows[0]["details"]["withheld_reasons"]
    request["inputs"]["stock_thicknesses"] = [q(0)]
    with pytest.raises(CalcCliError, match="must be positive"):
        evaluate_size(request)


def test_plate_stock_uses_bending_and_deflection_at_each_stock_size() -> None:
    request = json.loads((EXAMPLES / "plate_size_deflection_limited.json").read_text())
    request["inputs"]["plate_thickness_bounds"] = {"lower": q(1), "upper": q(15)}
    request["inputs"]["stock_thicknesses"] = [q(15), q(1), q(9.5), q(9)]
    result = evaluate_size(request)
    rows = result["sizing"]["stock_candidates"]
    assert rows[0]["outcome"] == "unavailable"
    assert rows[1]["outcome"] in {"unavailable", "fails_targets"}
    assert result["sizing"]["selected_plate_thickness"] == q(9.5)
    assert set(result["sizing"]["selected_check_margins"]) == {"flat_endcap_bending", "center_deflection"}


def test_sized_comparison_uses_each_materials_geometry_and_actual_shell_mass() -> None:
    request = size_request("tube")
    request["inputs"]["external_pressure"] = q(10, "MPa")
    names = ["Al-6061-T6", "Ti-6Al-4V", "Al-6061-T6"]
    result = _evaluate_material_comparison(comparison(request, names), MATERIALS_FILE)
    entries = result["comparison"]["entries"]
    assert [entry["material"] for entry in entries] == names
    assert all(entry["outcome"] == "evaluated" for entry in entries)
    assert entries[0]["selected_geometry"]["wall_thickness"]["value"] > entries[1]["selected_geometry"]["wall_thickness"]["value"]
    for entry in entries:
        geometry = entry["selected_geometry"]
        outer = geometry["external_radius"]["value"]
        inner = geometry["internal_radius"]["value"]
        length = geometry["axial_length"]["value"]
        density = entry["structural_mass"]["material_density"]["value"]
        assert outer == pytest.approx(100)
        assert entry["structural_mass"]["mass"]["value"] == pytest.approx(math.pi*(outer**2-inner**2)*length*density/1e9)
    assert entries[0] == entries[2]


def test_sized_comparison_keeps_unavailable_materials_and_no_solution_rows(tmp_path: Path) -> None:
    import yaml

    database = tmp_path / "materials.yaml"
    data = yaml.safe_load(MATERIALS_FILE.read_text())
    data["materials"]["NoDensity"] = copy.deepcopy(data["materials"]["Al-6061-T6"])
    data["materials"]["NoDensity"].pop("density_kg_per_m3", None)
    data["materials"]["NoElastic"] = copy.deepcopy(data["materials"]["Al-6061-T6"])
    data["materials"]["NoElastic"].pop("elastic_modulus_mpa", None)
    database.write_text(yaml.safe_dump(data))
    request = size_request()
    # A proportional limit is missing from several bundled material records.
    names = ["Al-6061-T6", "Al-7075-T6", "NoElastic", "missing", "NoDensity"]
    result = _evaluate_material_comparison(comparison(request, names), database)
    entries = result["comparison"]["entries"]
    assert [entry["material"] for entry in entries] == names
    assert entries[0]["outcome"] == "evaluated"
    assert entries[1]["outcome"] == "no_reliable_solution"
    assert entries[2]["outcome"] == "invalid_material"
    assert entries[3]["outcome"] == "unknown_material"
    assert entries[4]["outcome"] == "evaluated"
    assert entries[4]["structural_mass"]["status"] == "unavailable"
    assert entries[4]["structural_mass"]["mass"]["value"] is None


@pytest.mark.parametrize("model", ["tube", "plate", "smooth-buckling"])
def test_sizing_explicitly_rejects_zero_design_pressure(model: str) -> None:
    request = (json.loads((EXAMPLES / "plate_size_deflection_limited.json").read_text())
               if model == "plate" else size_request(model))
    request["inputs"]["external_pressure"] = q(0, "MPa")
    with pytest.raises(CalcCliError, match="sizing requires positive design pressure"):
        evaluate_size(request)


def test_cylinder_geometry_sweep_runs_shared_stress_and_buckling_checks() -> None:
    base = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "cylinder",
        "inputs": {
            "external_pressure": q(1, "MPa"), "internal_radius": q(50),
            "wall_thickness": q(1), "unsupported_length": q(300),
        },
        "material": {"type": "named", "name": "Al-6061-T6"},
    }
    request = SweepRequest.model_validate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": base,
        "inputs": {"geometry": "unsupported_length", "axis": {
            "type": "list", "values": [q(300), q(100)],
        }},
    })
    result = _evaluate_sweep(request, MATERIALS_FILE)
    points = result["sweep"]["points"]
    assert [point["response"]["assessment"]["status"] for point in points] == ["fail", "pass"]
    assert all(point["response"]["assessment"]["governing_check"] == "smooth_cylinder_buckling" for point in points)
    for point in points:
        single = copy.deepcopy(base)
        single["inputs"]["unsupported_length"] = point["unsupported_length"]
        assert point["response"] == _evaluate_single_request("cylinder", single, MATERIALS_FILE)
    compared = _evaluate_material_comparison(
        comparison(base, ["Al-6061-T6", "Ti-6Al-4V"]), MATERIALS_FILE,
    )
    assert [entry["material"] for entry in compared["comparison"]["entries"]] == ["Al-6061-T6", "Ti-6Al-4V"]
    for entry in compared["comparison"]["entries"]:
        assert entry["outcome"] == "evaluated"
        assert len(entry["response"]["assessment"]["checks"]) == 2


def test_sized_comparison_withholds_mass_alone_when_geometry_is_missing() -> None:
    tube = size_request("tube")
    tube["inputs"].pop("axial_length")
    entry = _evaluate_material_comparison(comparison(tube, ["Al-6061-T6"]), MATERIALS_FILE)["comparison"]["entries"][0]
    assert entry["outcome"] == "evaluated"
    assert entry["structural_mass"]["status"] == "unavailable"
    assert "axial_length" in entry["structural_mass"]["reason"]
    plate = json.loads((EXAMPLES / "plate_size_deflection_limited.json").read_text())
    entry = _evaluate_material_comparison(comparison(plate, ["Al-6061-T6"]), MATERIALS_FILE)["comparison"]["entries"][0]
    assert entry["outcome"] == "evaluated"
    assert entry["structural_mass"]["status"] == "unavailable"
    plate["inputs"]["outside_radius"] = q(110)
    entry = _evaluate_material_comparison(comparison(plate, ["Al-6061-T6"]), MATERIALS_FILE)["comparison"]["entries"][0]
    assert entry["structural_mass"]["status"] == "available"
    t = entry["selected_geometry"]["plate_thickness"]["value"]
    assert entry["structural_mass"]["mass"]["value"] == pytest.approx(math.pi * 110**2 * t * 2700 / 1e9)


def test_stock_sizing_metadata_matches_advertised_contract() -> None:
    from pv_calc.contracts import SmoothBucklingSizingMetadata

    payload = size_request()
    payload["inputs"]["stock_thicknesses"] = [q(1), q(5), q(20)]
    result = evaluate_size(payload)
    validated = SmoothBucklingSizingMetadata.model_validate(result["sizing"])
    assert validated.selection_scope == "stock_candidates"
    assert validated.stock_candidates is not None
    assert len(validated.stock_candidates) == 3
