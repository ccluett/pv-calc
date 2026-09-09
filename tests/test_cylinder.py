"""Composition acceptance and geometric accounting, independently of CLI rendering."""

from __future__ import annotations

import copy
import json
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from pv_calc.cylinder import CylinderRequest, describe_cylinder, evaluate_cylinder
from pv_calc.errors import CalcCliError
from pv_calc.pressure_vessel import closed_end_tube_stress, smooth_cylinder_external_pressure_buckling


def q(value: float | None, unit: str = "mm") -> dict[str, Any]:
    return {"value": value, "unit": unit}


@pytest.fixture
def payload() -> dict[str, Any]:
    return {
        "schema_version": "5.0.0",
        "model": "cylinder",
        "inputs": {
            "external_pressure": q(0.1, "MPa"),
            "internal_radius": q(50.0),
            "wall_thickness": q(1.0),
            "unsupported_length": q(300.0),
        },
        "material": {
            "type": "explicit",
            "name": "Illustrative metal",
            "provenance": "Test values, not a qualified material record.",
            "properties": {
                "failure_category": "ductile_metal",
                "yield_strength": q(250.0, "MPa"),
                "elastic_modulus": q(70000.0, "MPa"),
                "poisson_ratio": 0.33,
                "proportional_limit": q(180.0, "MPa"),
                "density": q(2700.0, "kg/m^3"),
            },
        },
    }


def evaluate(payload: dict[str, Any]) -> dict[str, Any]:
    return evaluate_cylinder(CylinderRequest.model_validate(payload))


def checks(response: dict[str, Any]) -> dict[str, dict[str, Any]]:
    return {check["id"]: check for check in response["assessment"]["checks"]}


def add_closures(payload: dict[str, Any]) -> None:
    payload["inputs"]["closures"] = [
        {
            "model": "plate", "plate_thickness": q(4.0),
            "boundary_condition": "fixed", "maximum_deflection": q(0.1),
            "material": copy.deepcopy(payload["material"]),
        },
        {"model": "hemisphere", "material": copy.deepcopy(payload["material"])},
    ]


def test_combined_assessment_matches_existing_kernels(payload: dict[str, Any]) -> None:
    response = evaluate(payload)
    tube = closed_end_tube_stress(
        external_pressure_mpa=0.1, internal_radius_mm=50.0, wall_thickness_mm=1.0,
        material_failure_category="ductile_metal", strength_mpa=250.0,
        elastic_modulus_mpa=70000.0, poisson_ratio=0.33, axial_length_mm=300.0,
    )
    buckling = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=0.1, shell_mid_surface_radius_mm=50.5, wall_thickness_mm=1.0,
        unsupported_length_mm=300.0, elastic_modulus_mpa=70000.0, poisson_ratio=0.33,
        yield_strength_mpa=250.0, proportional_limit_mpa=180.0,
        load_case="hydrostatic_closed_end",
    )
    assert response["assessment"]["status"] == "pass"
    assert response["assessment"]["required_check_coverage"]["complete"]
    assert response["assessment"]["governing_check"] == "smooth_cylinder_buckling"
    result = checks(response)
    assert result["cylindrical_shell_stress"]["margin"] == pytest.approx(tube.margin)
    assert result["smooth_cylinder_buckling"]["margin"] == pytest.approx(buckling.margin)
    assert response["components"]["tube"]["result"]["mean_radius_mm"] == q(50.5)
    assert response["components"]["smooth_buckling"]["result"]["shell_mid_surface_radius_mm"] == q(50.5)
    assert response["components"]["smooth_buckling"]["result"]["load_case"] == "hydrostatic_closed_end"
    assert response["geometry"]["axial_length"] == q(300.0)
    assert "End closures" in response["assessment"]["omissions"][0]


def test_positive_stress_margin_cannot_hide_buckling_failure(payload: dict[str, Any]) -> None:
    payload["inputs"]["external_pressure"] = q(1.0, "MPa")
    response = evaluate(payload)
    result = checks(response)
    assert result["cylindrical_shell_stress"]["status"] == "pass"
    assert result["smooth_cylinder_buckling"]["status"] == "fail"
    assert response["assessment"]["status"] == "fail"


def test_minimum_margin_changes_acceptance_without_changing_calculations(payload: dict[str, Any]) -> None:
    baseline = evaluate(payload)
    payload["inputs"]["minimum_margin"] = 4.0
    response = evaluate(payload)
    assert response["assessment"]["status"] == "fail"
    assert response["components"] == baseline["components"]
    assert checks(response)["smooth_cylinder_buckling"]["required_margin"] == 4.0


@pytest.mark.parametrize("wall", [1.0, 5.0, 6.0])
def test_withheld_or_inelastic_capacity_is_indeterminate(payload: dict[str, Any], wall: float) -> None:
    payload["inputs"]["wall_thickness"] = q(wall)
    if wall == 1.0:
        del payload["material"]["properties"]["proportional_limit"]
    response = evaluate(payload)
    buckling = checks(response)["smooth_cylinder_buckling"]
    assert response["assessment"]["status"] == "indeterminate"
    assert buckling["capacity"] == q(None, "MPa")
    assert buckling["margin"] is None
    assert buckling["reasons"]
    assert response["assessment"]["required_check_coverage"]["indeterminate"] == ["smooth_cylinder_buckling"]


def test_known_failure_takes_precedence_over_unavailable_buckling(payload: dict[str, Any]) -> None:
    del payload["material"]["properties"]["proportional_limit"]
    payload["inputs"]["external_pressure"] = q(8.0, "MPa")
    response = evaluate(payload)
    assert checks(response)["smooth_cylinder_buckling"]["status"] == "indeterminate"
    assert response["assessment"]["status"] == "fail"
    assert response["assessment"]["governing_check"] is None


@pytest.mark.parametrize("with_closures", [False, True])
def test_zero_demand_is_finite_and_keeps_positive_load_capacities(
    payload: dict[str, Any], with_closures: bool
) -> None:
    if with_closures:
        add_closures(payload)
    positive = checks(evaluate(payload))
    payload["inputs"]["external_pressure"] = q(0.0, "MPa")
    response = evaluate(payload)
    assert response["assessment"]["status"] == "pass"
    for check in checks(response).values():
        assert check["demand"]["value"] == 0.0
        assert check["status"] == "pass"
        assert check["margin"] is None
        assert check["reasons"]
        assert check["capacity"]["value"] == pytest.approx(positive[check["id"]]["capacity"]["value"])
    json.dumps(response, allow_nan=False)


def test_zero_demand_does_not_release_unavailable_capacity(payload: dict[str, Any]) -> None:
    del payload["material"]["properties"]["proportional_limit"]
    payload["inputs"]["external_pressure"] = q(0.0, "MPa")
    response = evaluate(payload)
    assert response["assessment"]["status"] == "indeterminate"
    assert checks(response)["cylindrical_shell_stress"]["status"] == "pass"
    assert checks(response)["smooth_cylinder_buckling"]["capacity"]["value"] is None


def test_mixed_closure_accounting_and_payload(payload: dict[str, Any]) -> None:
    add_closures(payload)
    payload["inputs"]["axial_length"] = q(350.0)
    payload["inputs"]["payload"] = {"mass": q(0.5, "kg"), "volume": q(100.0, "cm^3")}
    payload["inputs"]["submergence"] = {
        "fluid_density": q(1025.0, "kg/m^3"), "gravity": q(9.81, "m/s^2"),
    }
    # A different closure density proves the total is component-wise.
    payload["inputs"]["closures"][1]["material"]["properties"]["density"] = q(4500.0, "kg/m^3")
    response = evaluate(payload)
    assert response["assessment"]["status"] == "pass"
    tube_solid = math.pi * (51.0**2 - 50.0**2) * 350.0 / 1e9
    plate_solid = math.pi * 51.0**2 * 4.0 / 1e9
    head_solid = 2.0 / 3.0 * math.pi * (51.0**3 - 50.0**3) / 1e9
    cavity = (math.pi * 50.0**2 * 350.0 + 2.0 / 3.0 * math.pi * 50.0**3) / 1e9
    displaced = (math.pi * 51.0**2 * 350.0 + math.pi * 51.0**2 * 4.0 +
                 2.0 / 3.0 * math.pi * 51.0**3) / 1e9
    mass = (tube_solid + plate_solid) * 2700.0 + head_solid * 4500.0
    properties = response["mass_properties"]
    assert properties["structural_mass"]["value"] == pytest.approx(mass)
    assert properties["total_air_mass"]["value"] == pytest.approx(mass + 0.5)
    assert properties["internal_geometric_volume"]["value"] == pytest.approx(cavity)
    assert properties["displaced_volume"]["value"] == pytest.approx(displaced)
    assert properties["solid_volume"]["value"] == pytest.approx(displaced - cavity)
    assert properties["remaining_internal_volume"]["value"] == pytest.approx(cavity - 0.0001)
    assert properties["net_submerged_mass"]["value"] == pytest.approx(mass + 0.5 - 1025.0 * displaced)
    assert properties["buoyant_force"]["value"] == pytest.approx(1025.0 * displaced * 9.81)
    assert checks(response)["closure_1.center_deflection"]["status"] == "pass"
    assert checks(response)["closure_2.hemisphere_buckling"]["status"] == "pass"


def test_deflection_limit_is_only_required_when_requested(payload: dict[str, Any]) -> None:
    add_closures(payload)
    payload["inputs"]["closures"][0]["maximum_deflection"] = q(0.001)
    assert checks(evaluate(payload))["closure_1.center_deflection"]["status"] == "fail"
    del payload["inputs"]["closures"][0]["maximum_deflection"]
    response = evaluate(payload)
    assert response["assessment"]["status"] == "pass"
    assert "closure_1.center_deflection" not in checks(response)


def test_withheld_plate_deflection_cannot_be_used_for_acceptance(payload: dict[str, Any]) -> None:
    add_closures(payload)
    payload["inputs"]["closures"][0]["plate_thickness"] = q(10.0)
    response = evaluate(payload)
    result = checks(response)
    assert result["closure_1.flat_endcap_bending"]["status"] == "pass"
    assert result["closure_1.center_deflection"]["status"] == "indeterminate"
    assert result["closure_1.center_deflection"]["demand"] == q(None)
    assert response["assessment"]["status"] == "indeterminate"


def test_butt_bearing_uses_weaker_contact_material(payload: dict[str, Any]) -> None:
    add_closures(payload)
    closure = payload["inputs"]["closures"][1]
    closure["material"]["properties"]["yield_strength"] = q(100.0, "MPa")
    closure["material"]["properties"]["proportional_limit"] = q(80.0, "MPa")
    response = evaluate(payload)
    assert checks(response)["closure_2.seat_bearing"]["capacity"]["value"] == pytest.approx(
        100.0 * (51.0**2 - 50.0**2) / 51.0**2
    )


def test_brittle_bending_uses_tension_while_seat_uses_compression(payload: dict[str, Any]) -> None:
    add_closures(payload)
    material = payload["inputs"]["closures"][0]["material"]
    material["properties"] = {
        "failure_category": "brittle",
        "ultimate_tensile_strength": q(10.0, "MPa"),
        "ultimate_compressive_strength": q(1000.0, "MPa"),
        "elastic_modulus": q(70000.0, "MPa"),
        "poisson_ratio": 0.33,
    }
    response = evaluate(payload)
    result = checks(response)
    assert result["closure_1.flat_endcap_bending"]["status"] == "fail"
    assert result["closure_1.seat_bearing"]["status"] == "pass"
    assert result["closure_1.seat_bearing"]["capacity"]["value"] == pytest.approx(
        250.0 * (51.0**2 - 50.0**2) / 51.0**2
    )


def test_missing_closure_property_retains_other_known_failures(payload: dict[str, Any]) -> None:
    add_closures(payload)
    payload["inputs"]["external_pressure"] = q(1.0, "MPa")
    material = payload["inputs"]["closures"][0]["material"]
    material["properties"] = {
        "failure_category": "brittle",
        "ultimate_compressive_strength": q(1.0, "MPa"),
        "elastic_modulus": q(70000.0, "MPa"),
        "poisson_ratio": 0.33,
    }
    response = evaluate(payload)
    result = checks(response)
    assert result["closure_1.flat_endcap_bending"]["status"] == "indeterminate"
    assert result["closure_1.center_deflection"]["status"] == "indeterminate"
    assert result["closure_1.seat_bearing"]["status"] == "fail"
    assert result["smooth_cylinder_buckling"]["status"] == "fail"
    assert response["assessment"]["status"] == "fail"
    assert response["components"]["closures"][0]["error"]["code"] == "invalid_material"


def test_closure_failure_retained_when_its_buckling_is_withheld(payload: dict[str, Any]) -> None:
    add_closures(payload)
    material = payload["inputs"]["closures"][1]["material"]
    material["properties"]["yield_strength"] = q(1.0, "MPa")
    material["properties"]["proportional_limit"] = q(0.8, "MPa")
    response = evaluate(payload)
    result = checks(response)
    assert result["closure_2.hemispherical_shell_stress"]["status"] == "fail"
    assert result["closure_2.hemisphere_buckling"]["status"] == "indeterminate"
    assert response["assessment"]["status"] == "fail"


def test_named_material_missing_elastic_data_keeps_closed_end_stress(
    payload: dict[str, Any], tmp_path: Path
) -> None:
    database = tmp_path / "materials.yaml"
    database.write_text("materials:\n  stress_only:\n    failure_category: ductile_metal\n"
                        "    yield_strength_mpa: 1\n    density_kg_per_m3: 2700\n"
                        "    source: Illustrative test values\n")
    payload["material"] = {"type": "named", "name": "stress_only"}
    response = evaluate_cylinder(CylinderRequest.model_validate(payload), database)
    assert checks(response)["cylindrical_shell_stress"]["status"] == "fail"
    assert checks(response)["smooth_cylinder_buckling"]["status"] == "indeterminate"
    assert response["assessment"]["status"] == "fail"


def test_missing_density_withholds_mass_without_blocking_strength(payload: dict[str, Any]) -> None:
    del payload["material"]["properties"]["density"]
    response = evaluate(payload)
    assert response["assessment"]["status"] == "pass"
    assert response["mass_properties"]["structural_mass"]["value"] is None
    assert response["mass_properties"]["status"] == "withheld_missing_density"
    assert response["mass_properties"]["internal_geometric_volume"]["value"] > 0


@pytest.mark.parametrize("mutation,match", [
    ({"axial_length": q(299.0)}, "axial_length"),
    ({"payload": {"volume": q(100.0, "liter")}}, "exceeds"),
    ({"payload": {"mass": q(-1.0, "kg")}}, "non-negative"),
    ({"wall_thickness": q(0.0)}, "positive"),
    ({"unsupported_length": q(1.0, "kg")}, "unit"),
])
def test_impossible_geometry_and_payload_rejected(
    payload: dict[str, Any], mutation: dict[str, Any], match: str
) -> None:
    payload["inputs"].update(mutation)
    with pytest.raises(CalcCliError, match=match):
        evaluate(payload)


@pytest.mark.parametrize("index,field,value", [(0, "outside_radius", 52.0), (1, "wall_thickness", 2.0)])
def test_butt_geometry_mismatch_rejected(
    payload: dict[str, Any], index: int, field: str, value: float
) -> None:
    add_closures(payload)
    payload["inputs"]["closures"][index][field] = q(value)
    with pytest.raises(CalcCliError, match="must equal"):
        evaluate(payload)


def test_closures_require_exactly_two_and_forbid_unknown_fields(payload: dict[str, Any]) -> None:
    add_closures(payload)
    payload["inputs"]["closures"].pop()
    with pytest.raises(ValidationError):
        CylinderRequest.model_validate(payload)
    del payload["inputs"]["closures"]
    payload["inputs"]["load_case"] = "lateral_only"
    with pytest.raises(ValidationError):
        CylinderRequest.model_validate(payload)


def test_describe_exposes_strict_schema_and_nested_dimensions() -> None:
    description = describe_cylinder()
    inputs = description["input_contract"]
    assert inputs["json_schema"]["additionalProperties"] is False
    from test_describe import _assert_workflow_schema
    _assert_workflow_schema(inputs["json_schema"], CylinderRequest)
    assert inputs["json_quantity_dimensions"]["inputs.payload.mass"] == "mass"
    assert inputs["json_quantity_dimensions"]["inputs.closures.plate_thickness"] == "length"
    assert inputs["json_quantity_dimensions"]["inputs.closures.maximum_deflection"] == "length"
    assert inputs["json_quantity_dimensions"]["inputs.payload.volume"] == "volume"
    closures = inputs["json_schema"]["$defs"]["CylinderInputs"]["properties"]["closures"]["anyOf"][0]
    assert closures["minItems"] == closures["maxItems"] == 2
    assert "indeterminate" in description["output_contract"]["assessment"]


@pytest.mark.parametrize("name", ["cylinder_check.json", "cylinder_housing.json"])
def test_examples_are_finite_and_evaluable(name: str) -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / name
    response = evaluate(json.loads(example.read_text()))
    assert response["assessment"]["status"] == "pass"
    json.dumps(response, allow_nan=False)
