"""Alternate depth inputs compose through CLI and API batch operations."""

from __future__ import annotations

import copy
import json
from pathlib import Path
from typing import Any

import pytest

from pv_calc.api import calculate
from pv_calc.cli import app
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.errors import CalcCliError

from _cli_helpers import EXAMPLES, runner


def q(value: float, unit: str) -> dict[str, Any]:
    return {"value": float(value), "unit": unit}


def depth_request(example: str) -> dict[str, Any]:
    request = json.loads((EXAMPLES / example).read_text())
    request["inputs"].pop("external_pressure")
    request["inputs"].update({
        "depth": q(100, "m"), "fluid_density": q(1025, "kg/m^3"),
        "gravity": q(9.81, "m/s^2"), "design_factor": 1.25,
    })
    return request


@pytest.mark.parametrize("example", ["smooth_buckling_size_moderate.json", "tube_size_7_ksi.json", "cylinder_check.json"])
def test_material_comparison_normalizes_nested_depth_and_keeps_each_conversion(example: str) -> None:
    base = depth_request(example)
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "compare-materials",
        "inputs": {"materials": ["Al-6061-T6", "Ti-6Al-4V"]}, "request": base,
    }
    original = copy.deepcopy(request)
    response = calculate(request)
    assert request == original
    for entry in response["comparison"]["entries"]:
        single = copy.deepcopy(base)
        single["material"] = {"type": "named", "name": entry["material"]}
        assert entry["response"] == calculate(single)
        assert entry["response"]["loading"]["depth"] == q(100, "m")
        assert entry["response"]["loading"]["design_external_pressure"]["value"] == pytest.approx(1.25690625)
    # Result provenance dictionaries must not alias across batch entries.
    response["comparison"]["entries"][0]["response"]["loading"]["depth"]["value"] = -1
    assert response["comparison"]["entries"][1]["response"]["loading"]["depth"] == q(100, "m")


def test_geometry_sweep_uses_nested_depth_and_preserves_point_equivalence() -> None:
    base = depth_request("cylinder_check.json")
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": base,
        "inputs": {"geometry": "unsupported_length", "axis": {
            "type": "list", "values": [q(300, "mm"), q(100, "mm")],
        }},
    }
    original = copy.deepcopy(request)
    response = calculate(request)
    assert request == original
    for point in response["sweep"]["points"]:
        single = copy.deepcopy(base)
        single["inputs"]["unsupported_length"] = point["unsupported_length"]
        assert point["response"] == calculate(single)


@pytest.mark.parametrize("axis", ["external_pressure", "depth"])
def test_load_sweep_overrides_nested_depth_without_stale_loading(axis: str) -> None:
    base = depth_request("cylinder_check.json")
    values = [q(0, "m"), q(20, "m")] if axis == "depth" else [q(0, "MPa"), q(0.1, "MPa")]
    inputs: dict[str, Any] = {axis: {"type": "list", "values": values}}
    if axis == "depth":
        # Distinct axis fluid and design factor prove the base conversion is
        # replaced instead of being silently carried into the swept load.
        inputs.update(fluid_density=q(1000, "kg/m^3"), gravity=q(10, "m/s^2"), design_factor=2.0)
    request = {"schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "inputs": inputs, "request": base}
    response = calculate(request)
    assert "loading" not in response
    for index, point in enumerate(response["sweep"]["points"]):
        assert "loading" not in point["response"]
        applied = point["response"]["components"]["tube"]["result"]["external_pressure_mpa"]
        assert applied == (q(index * 0.4, "MPa") if axis == "depth" else values[index])
    if axis == "depth":
        assert response["sweep"]["depth_to_pressure"]["design_factor"] == 2.0
        assert response["sweep"]["depth_to_pressure"]["fluid_density"] == q(1000, "kg/m^3")


@pytest.mark.parametrize("command", ["compare-materials", "sweep", "run"])
def test_cli_retains_nested_load_conversion_after_typed_validation(command: str, tmp_path: Path) -> None:
    model = "sweep" if command == "sweep" else "compare-materials"
    inputs = ({"geometry": "wall_thickness", "axis": {"type": "list", "values": [q(1, "mm")]}}
              if model == "sweep" else {"materials": ["Al-6061-T6"]})
    request = {"schema_version": CALC_SCHEMA_VERSION, "model": model, "inputs": inputs,
               "request": depth_request("cylinder_check.json")}
    path = tmp_path / "request.json"
    path.write_text(json.dumps(request))
    result = runner.invoke(app, [command, "--input", str(path), "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == json.loads(json.dumps(calculate(request)))


def test_nested_depth_load_still_rejects_conflicting_pressure_and_preserves_partial_comparison() -> None:
    base = depth_request("smooth_buckling_size_moderate.json")
    request = {"schema_version": CALC_SCHEMA_VERSION, "model": "compare-materials", "request": base,
               "inputs": {"materials": ["Al-7075-T6", "Al-6061-T6"]}}
    response = calculate(request)
    entries = response["comparison"]["entries"]
    assert entries[0]["outcome"] == "no_reliable_solution"
    assert "response" not in entries[0]
    assert entries[1]["response"]["loading"]["depth"] == q(100, "m")
    base["inputs"]["external_pressure"] = q(1, "MPa")
    with pytest.raises(CalcCliError) as exc:
        calculate(request)
    assert exc.value.code == "input_source_conflict"


@pytest.mark.parametrize("example", [
    "tube_9_0401_ksi.json", "plate_9_0384_ksi.json", "hemisphere_subsea_screen.json",
    "smooth_buckling_moderate_nasa.json", "ring_shell_dtmb_17_spaces.json", "cylinder_check.json",
    "tube_size_7_ksi.json", "plate_size_deflection_limited.json", "smooth_buckling_size_moderate.json",
])
def test_positive_direct_depth_matches_explicit_design_pressure_without_mutation(example: str) -> None:
    request = depth_request(example)
    original = copy.deepcopy(request)
    depth_response = calculate(request)
    assert request == original
    pressure_request = copy.deepcopy(request)
    for key in ("depth", "fluid_density", "gravity", "design_factor"):
        pressure_request["inputs"].pop(key)
    pressure_request["inputs"]["external_pressure"] = q(1025 * 9.81 * 100 * 1.25 / 1e6, "MPa")
    pressure_response = calculate(pressure_request)
    assert {key: value for key, value in depth_response.items() if key != "loading"} == pressure_response
    assert depth_response["loading"]["design_external_pressure"] == pressure_request["inputs"]["external_pressure"]
    assert depth_response["loading"]["service_external_pressure"]["value"] == pytest.approx(1.005525)


def test_public_api_accepts_typed_forward_and_sizing_requests() -> None:
    from pv_calc.contracts import TubeRequest, TubeSizeRequest

    for example, contract in [("tube_9_0401_ksi.json", TubeRequest), ("tube_size_7_ksi.json", TubeSizeRequest)]:
        raw = json.loads((EXAMPLES / example).read_text())
        typed = contract.model_validate(raw)
        original = typed.model_dump()
        assert calculate(typed) == calculate(raw)
        assert typed.model_dump() == original


@pytest.mark.parametrize("change,code", [
    ("missing_factor", "invalid_request"),
    ("missing_gravity", "invalid_request"),
    ("wrong_depth_dimension", "incompatible_unit"),
    ("pressure_conflict", "input_source_conflict"),
])
def test_direct_depth_rejects_incomplete_or_conflicting_loading_without_mutation(change: str, code: str) -> None:
    request = depth_request("tube_9_0401_ksi.json")
    if change == "missing_factor":
        request["inputs"].pop("design_factor")
    elif change == "missing_gravity":
        request["inputs"].pop("gravity")
    elif change == "wrong_depth_dimension":
        request["inputs"]["depth"] = q(100, "MPa")
    else:
        request["inputs"]["external_pressure"] = q(1, "MPa")
    original = copy.deepcopy(request)
    with pytest.raises(CalcCliError) as exc:
        calculate(request)
    assert exc.value.code == code
    assert request == original


@pytest.mark.parametrize("model", [[], {}])
def test_malformed_model_shape_returns_structured_api_and_cli_error(model: Any) -> None:
    request = {"schema_version": CALC_SCHEMA_VERSION, "model": model, "inputs": {}}
    with pytest.raises(CalcCliError) as exc:
        calculate(request)
    assert exc.value.code == "unknown_model"
    result = runner.invoke(app, ["run", "--input", "-", "--json"], input=json.dumps(request))
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "unknown_model"
