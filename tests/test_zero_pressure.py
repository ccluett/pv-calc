"""Zero load is a forward case, not an infinite margin or an inverse target."""

import copy
import json

import pytest
from _cli_helpers import EXAMPLES, SWEEP_FORWARD_EXAMPLES, runner

from pv_calc.api import calculate
from pv_calc.cli import app
from pv_calc.errors import CalcCliError
from pv_calc.presentation import assess_response


def _example(name):
    return json.loads((EXAMPLES / name).read_text())


@pytest.mark.parametrize("model,name", SWEEP_FORWARD_EXAMPLES.items())
def test_zero_load_preserves_capacities_and_applicability(model, name):
    request = _example(name)
    request["inputs"]["external_pressure"] = {"value": 1e-6, "unit": "MPa"}
    loaded = calculate(request)["result"]
    request["inputs"]["external_pressure"]["value"] = 0
    before = copy.deepcopy(request)
    response = calculate(request)
    result = response["result"]
    assert request == before
    assert result["external_pressure_mpa"]["value"] == 0
    assert all(value is None for key, value in result.items() if key.endswith("margin"))
    capacities = [key for key in result if "pressure" in key and key.endswith("_mpa") and key != "external_pressure_mpa"]
    assert capacities
    for key in capacities:
        assert result[key]["value"] == pytest.approx(loaded[key]["value"])
    for key in ("governing_stress_mpa", "governing_bending_stress_mpa", "maximum_deflection_mm", "working_circumferential_membrane_stress_mpa"):
        if key in result:
            assert result[key]["value"] == 0
    # The advisory ring-shell capacity remains unavailable for acceptance,
    # even when no load is applied.
    assert assess_response(response)["status"] == ("indeterminate" if model == "ring-shell" else "pass")
    json.dumps(response, allow_nan=False)
    cli = runner.invoke(app, [model, "--input", "-", "--json"], input=json.dumps(request))
    assert cli.exit_code == 0, cli.output
    assert json.loads(cli.stdout) == json.loads(json.dumps(response))


@pytest.mark.parametrize("name", SWEEP_FORWARD_EXAMPLES.values())
def test_negative_forward_pressure_is_still_rejected(name):
    request = _example(name)
    request["inputs"]["external_pressure"] = {"value": -1, "unit": "Pa"}
    with pytest.raises(CalcCliError, match="non-negative"):
        calculate(request)


@pytest.mark.parametrize("name", ["tube_size_7_ksi.json", "plate_size_deflection_limited.json", "smooth_buckling_size_moderate.json"])
def test_zero_is_not_a_sizing_target(name):
    request = _example(name)
    request["inputs"]["external_pressure"] = {"value": 0, "unit": "MPa"}
    with pytest.raises(CalcCliError, match="positive"):
        calculate(request)


def test_zero_depth_and_zero_axis_are_ordinary_forward_results():
    request = _example("tube_9_0401_ksi.json")
    del request["inputs"]["external_pressure"]
    request["inputs"].update({
        "depth": {"value": 0, "unit": "m"},
        "fluid_density": {"value": 1025, "unit": "kg/m^3"},
        "gravity": {"value": 9.81, "unit": "m/s^2"},
        "design_factor": 1.25,
    })
    response = calculate(request)
    assert response["loading"]["design_external_pressure"]["value"] == 0
    assert assess_response(response)["status"] == "pass"
    sweep = _example("sweep_tube_pressure_range.json")
    sweep["inputs"]["external_pressure"]["start"] = {"value": 0, "unit": "Pa"}
    point = calculate(sweep)["sweep"]["points"][0]["response"]
    assert point["result"]["external_pressure_mpa"]["value"] == 0
    assert point["result"]["margin"] is None
