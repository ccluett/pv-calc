"""Regression cases from the workflow review."""

import csv
import io
import json
from copy import deepcopy

import pytest
from _cli_helpers import EXAMPLES, runner

from pv_calc.api import calculate
from pv_calc.cli import app
from pv_calc.presentation import summarize_response


def q(value, unit="mm"):
    return {"value": value, "unit": unit}


def tube_request():
    request = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text())
    request["inputs"]["external_pressure"] = q(1, "MPa")
    return request


def depth_request():
    request = tube_request()
    del request["inputs"]["external_pressure"]
    request["inputs"].update({
        "depth": q(100, "m"), "fluid_density": q(1025, "kg/m^3"),
        "gravity": q(9.81, "m/s^2"), "design_factor": 1.25,
    })
    return request


def invoke(request, output_format, command="check", *options):
    return runner.invoke(app, [command, "--input", "-", "--format", output_format, *options], input=json.dumps(request))


@pytest.mark.parametrize("output_format", ["json", "summary", "text", "csv"])
def test_check_comparison_preserves_identities_and_entry_errors(tmp_path, output_format):
    database = tmp_path / "materials.yaml"
    database.write_text("""materials:
  Good: {source: Test, failure_category: ductile_metal, yield_strength_mpa: 200}
  Weak: {source: Test, failure_category: ductile_metal, yield_strength_mpa: 20}
  Missing: {source: Test, failure_category: ductile_metal}
""")
    size = {"schema_version": "5.0.0", "model": "tube", "operation": "size",
            "material": {"type": "named", "name": "Good"},
            "inputs": {"external_pressure": q(1, "MPa"), "internal_radius": q(50),
                       "wall_thickness_bounds": {"lower": q(0.1), "upper": q(1)}, "stock_thicknesses": [q(1)]}}
    request = {"schema_version": "5.0.0", "model": "compare-materials", "request": size,
               "inputs": {"materials": ["Good", "Weak", "Missing"]}}
    expected = calculate(request, materials_file=database)["comparison"]["entries"]
    result = invoke(request, output_format, "check", "--materials-file", str(database))
    assert result.exit_code == 3, result.output
    if output_format in {"json", "summary"}:
        response = json.loads(result.stdout)
        assert response["operation"] == "compare-materials"
        entries = ([item["context"] for item in response["assessment"]["entries"]]
                   if output_format == "json" else response["entries"])
        assert [item["material"] for item in entries] == ["Good", "Weak", "Missing"]
        assert [item["outcome"] for item in entries] == ["evaluated", "no_reliable_solution", "invalid_material"]
        for index in (1, 2):
            assert entries[index]["message"] == expected[index]["message"]
        assert entries[1]["details"] == expected[1]["details"]
    elif output_format == "text":
        assert "compare-materials" in result.stdout
        for entry in expected:
            assert entry["material"] in result.stdout
            if "message" in entry:
                assert entry["message"] in result.stdout
        assert "details=" not in result.stdout
    else:
        rows = list(csv.DictReader(io.StringIO(result.stdout)))
        assert [row["material"] for row in rows] == ["Good", "Weak", "Missing"]
        assert [row["outcome"] for row in rows] == ["evaluated", "no_reliable_solution", "invalid_material"]
        assert all(row["operation"] == "compare-materials" for row in rows)
        for index in (1, 2):
            assert rows[index]["message"] == expected[index]["message"]


@pytest.mark.parametrize("axis,unit,values", [("external_pressure", "MPa", [0, 1]), ("depth", "m", [0, 100]), ("wall_thickness", "mm", [5, 6])])
def test_check_sweep_preserves_coordinates_in_json_summary_and_csv(axis, unit, values):
    quantities = [q(value, unit) for value in values]
    axis_input = {"type": "list", "values": quantities}
    inputs = ({"geometry": axis, "axis": axis_input} if axis == "wall_thickness" else {axis: axis_input})
    if axis == "depth":
        inputs.update(fluid_density=q(1025, "kg/m^3"), gravity=q(9.81, "m/s^2"), design_factor=1.25)
    request = {"schema_version": "5.0.0", "model": "sweep", "request": tube_request(), "inputs": inputs}
    raw = invoke(request, "json")
    assert raw.exit_code == 0, raw.output
    payload = json.loads(raw.stdout)
    assert payload["operation"] == "sweep"
    assert [entry["context"][axis] for entry in payload["assessment"]["entries"]] == quantities
    summary = json.loads(invoke(request, "summary").stdout)
    assert [entry[axis] for entry in summary["entries"]] == quantities
    rows = list(csv.DictReader(io.StringIO(invoke(request, "csv").stdout)))
    assert [float(row["axis_value"]) for row in rows] == values
    assert all(row["axis"] == axis and row["axis_unit"] == unit and row["operation"] == "sweep" for row in rows)


@pytest.mark.parametrize("batch", [None, "compare-materials", "sweep"])
@pytest.mark.parametrize("command", ["run", "check"])
def test_depth_loading_survives_summary_text_and_csv(batch, command):
    request = depth_request()
    if batch:
        inputs = ({"materials": ["Al-6061-T6", "Ti-6Al-4V"]} if batch == "compare-materials" else
                  {"geometry": "wall_thickness", "axis": {"type": "list", "values": [q(5), q(6)]}})
        request = {"schema_version": "5.0.0", "model": batch, "request": request, "inputs": inputs}
    full = calculate(request)
    original = deepcopy(full)
    summarize_response(full)
    assert full == original
    result = invoke(request, "summary", command)
    assert result.exit_code == 0, result.output
    summary = json.loads(result.stdout)
    summaries = [entry["summary"] for entry in summary["entries"]] if batch else [summary]
    for item in summaries:
        loading = item["loading"]
        assert loading["depth"] == q(100, "m")
        assert loading["design_factor"] == 1.25
        assert loading["fluid_density"] == q(1025, "kg/m^3")
        assert loading["gravity"] == q(9.81, "m/s^2")
        assert loading["service_external_pressure"]["value"] == pytest.approx(1.005525)
        assert loading["design_external_pressure"]["value"] == pytest.approx(1.25690625)
    text = invoke(request, "text", command)
    assert text.exit_code == 0
    assert "depth 100 m" in text.stdout and "factor 1.25" in text.stdout
    assert "service pressure" in text.stdout and "design pressure" in text.stdout
    rows = list(csv.DictReader(io.StringIO(invoke(request, "csv", command).stdout)))
    assert all(float(row["depth_m"]) == 100 and float(row["design_factor"]) == 1.25 for row in rows)
    assert all(float(row["design_external_pressure_mpa"]) == pytest.approx(1.25690625) for row in rows)


@pytest.mark.parametrize("command", ["run", "check"])
def test_depth_axis_reports_its_own_loading_in_every_format(command):
    # The axis has different fluid, gravity, and factor than the base depth
    # request, and retains its original mixed units as point coordinates.
    depths = [q(0, "m"), q(100, "ft"), q(100, "m")]
    request = {"schema_version": "5.0.0", "model": "sweep", "request": depth_request(),
               "inputs": {"depth": {"type": "list", "values": depths}, "fluid_density": q(1000, "kg/m^3"),
                          "gravity": q(10, "m/s^2"), "design_factor": 1.5}}
    full = calculate(request)
    original = deepcopy(full)
    summary = summarize_response(full)
    assert full == original
    assert [entry["depth"] for entry in summary["entries"]] == depths
    expected_depths = [0, 30.48, 100]
    for output_format in ("summary", "json", "text", "csv"):
        result = invoke(request, output_format, command)
        assert result.exit_code == 0, result.output
        if output_format == "summary":
            entries = json.loads(result.stdout)["entries"]
            loads = [entry["summary"]["loading"] for entry in entries]
            assert [load["depth"]["value"] for load in loads] == pytest.approx(expected_depths)
            assert all(load["depth"]["unit"] == "m" and load["design_factor"] == 1.5 for load in loads)
            assert all(load["fluid_density"] == q(1000, "kg/m^3") and load["gravity"] == q(10, "m/s^2") for load in loads)
        elif output_format == "json" and command == "check":
            entries = json.loads(result.stdout)["assessment"]["entries"]
            assert [entry["context"]["depth"] for entry in entries] == depths
            assert [entry["loading"]["depth"]["value"] for entry in entries] == pytest.approx(expected_depths)
            assert all(entry["loading"]["design_factor"] == 1.5 for entry in entries)
        elif output_format == "text":
            assert "factor 1.5" in result.stdout and "depth 30.48 m" in result.stdout
        elif output_format == "csv":
            rows = list(csv.DictReader(io.StringIO(result.stdout)))
            assert [row["axis_unit"] for row in rows] == ["m", "ft", "m"]
            assert [float(row["depth_m"]) for row in rows] == pytest.approx(expected_depths)
            assert all(float(row["design_factor"]) == 1.5 for row in rows)
            assert [float(row["service_external_pressure_mpa"]) for row in rows] == pytest.approx([0, 0.3048, 1])
            assert [float(row["design_external_pressure_mpa"]) for row in rows] == pytest.approx([0, 0.4572, 1.5])


DEPTH_ONLY_COMMANDS = [
    ["tube", "size", "--internal-radius", "50 mm", "--wall-thickness-lower", "0.1 mm", "--wall-thickness-upper", "4 mm"],
    ["plate", "size", "--free-radius", "50 mm", "--boundary-condition", "fixed", "--plate-thickness-lower", "1 mm", "--plate-thickness-upper", "10 mm"],
    ["smooth-buckling", "size", "--external-radius", "55 mm", "--unsupported-length", "300 mm", "--wall-thickness-lower", "0.5 mm", "--wall-thickness-upper", "4 mm"],
    ["ring-shell", "--shell-mid-surface-radius", "100 mm", "--wall-thickness", "1 mm", "--unsupported-length", "1000 mm", "--ring-spacing", "100 mm", "--ring-axial-width", "3 mm", "--ring-radial-height", "10 mm", "--ring-location", "internal"],
]


@pytest.mark.parametrize("command", DEPTH_ONLY_COMMANDS)
@pytest.mark.parametrize("options", [["--fluid-density", "garbage"], ["--gravity", "also garbage"], ["--fluid-density", "1025 kg/m^3", "--gravity", "9.81 m/s^2"]])
def test_depth_only_options_cannot_be_silently_ignored(command, options):
    result = runner.invoke(app, [*command, "--external-pressure", "1 MPa", "--material", "Al-6061-T6", *options])
    assert result.exit_code == 2, result.output
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "invalid_request"
    assert "require --depth" in error["message"]


@pytest.mark.parametrize("command", DEPTH_ONLY_COMMANDS)
def test_depth_only_options_are_consumed_with_a_depth_load(command):
    result = runner.invoke(app, [*command, "--depth", "10 m", "--design-factor", "1.25",
                                "--fluid-density", "1025 kg/m^3", "--gravity", "9.81 m/s^2",
                                "--material", "Al-6061-T6", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["loading"]["design_external_pressure"]["value"] == pytest.approx(0.125690625)


def test_fluid_options_still_supply_forward_submergence():
    result = runner.invoke(app, ["tube", "--external-pressure", "1 MPa", "--internal-radius", "50 mm",
                                "--wall-thickness", "3 mm", "--axial-length", "300 mm", "--material", "Al-6061-T6",
                                "--fluid-density", "1025 kg/m^3", "--gravity", "9.81 m/s^2", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert "mass_properties" in payload and "failure_depths" in payload
    assert "loading" not in payload
