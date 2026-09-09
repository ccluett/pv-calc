"""Exercise the public CLI/API paths as human and scripted design workflows."""

from __future__ import annotations

import csv
import io
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

import pytest

from pv_calc.api import calculate
from pv_calc.cli import app
from pv_calc.materials import BUNDLED_MATERIAL_DATABASE

from _cli_helpers import EXAMPLES, runner


def _q(value: float, unit: str = "mm") -> dict[str, Any]:
    return {"value": value, "unit": unit}


def _cylinder() -> dict[str, Any]:
    return json.loads((EXAMPLES / "cylinder_check.json").read_text())


def _run(payload: dict[str, Any], *options: str, command: str = "run") -> Any:
    return runner.invoke(app, [command, "--input", "-", *options], input=json.dumps(payload))


@pytest.mark.parametrize("output_format", ["json", "summary", "text", "csv"])
def test_cylinder_user_formats_preserve_checks_and_scoped_conclusion(output_format: str) -> None:
    request = _cylinder()
    response = _run(request, "--format", output_format, command="cylinder")
    assert response.exit_code == 0, response.output
    assert response.stderr == ""
    if output_format in {"json", "summary"}:
        assessment = json.loads(response.stdout)["assessment"]
        assert assessment["status"] == "pass"
        assert {check["id"] for check in assessment["checks"]} == {
            "cylindrical_shell_stress", "smooth_cylinder_buckling",
        }
        assert any("closure" in omission.lower() for omission in assessment["omissions"])
        assert "not a housing qualification" in assessment["scope"]
    elif output_format == "text":
        assert "cylinder: PASS" in response.stdout
        assert "cylindrical_shell_stress: PASS" in response.stdout
        assert "smooth_cylinder_buckling: PASS" in response.stdout
        assert "Seals" in response.stdout
        assert "No closures supplied" in response.stdout
    else:
        rows = list(csv.DictReader(io.StringIO(response.stdout)))
        assert len(rows) == 2
        assert {row["check"] for row in rows} == {"cylindrical_shell_stress", "smooth_cylinder_buckling"}
        assert all(row["demand_unit"] == "MPa" and row["status"] == "pass" for row in rows)
        assert all("Seals" in row["omissions"] and "not a housing qualification" in row["scope"] for row in rows)


@pytest.mark.parametrize(("case", "exit_code", "status"), [
    ("pass", 0, "pass"), ("fail", 1, "fail"), ("withheld", 3, "indeterminate"),
    ("absent_check", 3, "indeterminate"), ("invalid", 2, None),
])
def test_check_exit_codes_are_acceptance_results_and_input_errors_are_structured(
    case: str, exit_code: int, status: str | None,
) -> None:
    request = _cylinder()
    options = ["--json"]
    if case == "fail":
        request["inputs"]["external_pressure"] = _q(1, "MPa")
    elif case == "withheld":
        request["material"] = {"type": "named", "name": "Al-7075-T6"}
    elif case == "absent_check":
        options += ["--check", "closure_retention"]
    elif case == "invalid":
        request["inputs"]["internal_radius"] = _q(0)
    response = _run(request, *options, command="check")
    assert response.exit_code == exit_code, response.output
    if status is not None:
        payload = json.loads(response.stdout)
        assert payload["assessment"]["status"] == status
        assert response.stderr == ""
        if case == "absent_check":
            check = payload["assessment"]["checks"][0]
            assert check["id"] == "closure_retention"
            assert check["capacity"]["value"] is None
        if case == "withheld":
            unavailable = [check for check in payload["assessment"]["checks"] if check["status"] == "indeterminate"]
            assert unavailable and all(check["reasons"] for check in unavailable)
    else:
        assert response.stdout == ""
        assert json.loads(response.stderr)["error"]["code"] == "unevaluable_model"


def test_ordinary_forward_success_and_check_failure_are_distinct() -> None:
    request = _cylinder()
    request["inputs"]["external_pressure"] = _q(1, "MPa")
    response = _run(request, "--format", "summary")
    assert response.exit_code == 0
    assert json.loads(response.stdout)["assessment"]["status"] == "fail"
    assert _run(request, "--format", "summary", command="check").exit_code == 1


@pytest.mark.parametrize("options", [
    ["--format", "invalid"], ["--json", "--format", "text"],
])
def test_invalid_formatting_is_a_structured_error(options: list[str]) -> None:
    response = _run(_cylinder(), *options)
    assert response.exit_code == 2
    assert response.stdout == ""
    assert json.loads(response.stderr)["error"]["code"] in {"invalid_request", "input_source_conflict"}


def test_materials_cli_default_override_and_unknown_name(tmp_path: Path) -> None:
    listed = runner.invoke(app, ["materials", "list", "--json"])
    assert listed.exit_code == 0
    records = json.loads(listed.stdout)["materials"]
    assert len(records) == 10
    assert all(record["database"] == BUNDLED_MATERIAL_DATABASE for record in records)
    shown = runner.invoke(app, ["materials", "show", "Al-6061-T6", "--json"])
    assert shown.exit_code == 0
    record = json.loads(shown.stdout)
    assert record["properties"]["source"]
    assert record["properties"]["proportional_limit_source"]
    missing = runner.invoke(app, ["materials", "show", "not-present", "--json"])
    assert missing.exit_code == 2
    assert json.loads(missing.stderr)["error"]["code"] == "unknown_material"
    override = tmp_path / "materials.yaml"
    override.write_text("materials:\n  Ballast:\n    source: Test density only\n    density_kg_per_m3: 7800\n")
    custom = runner.invoke(app, ["materials", "list", "--materials-file", str(override), "--json"])
    assert custom.exit_code == 0
    assert [record["name"] for record in json.loads(custom.stdout)["materials"]] == ["Ballast"]
    text = runner.invoke(app, ["materials", "show", "Ballast", "--materials-file", str(override), "--format", "text"])
    assert text.exit_code == 0 and "mass_properties: available" in text.stdout
    rejected = runner.invoke(app, ["materials", "list", "--format", "csv"])
    assert rejected.exit_code == 2 and json.loads(rejected.stderr)["error"]["code"] == "invalid_request"


@pytest.mark.parametrize("command", [["list"], ["show", "Al-6061-T6"]])
def test_materials_cli_malformed_yaml_is_structured(tmp_path: Path, command: list[str]) -> None:
    database = tmp_path / "bad.yaml"
    database.write_text("materials: [\n")
    response = runner.invoke(app, ["materials", *command, "--materials-file", str(database)])
    assert response.exit_code == 2
    assert json.loads(response.stderr)["error"]["code"] == "invalid_material_database"


def test_run_and_python_api_dispatch_geometry_sweep_without_mutating_inputs() -> None:
    base = json.loads((EXAMPLES / "smooth_buckling_moderate_nasa.json").read_text())
    request = {"schema_version": "5.0.0", "model": "sweep", "request": base,
               "inputs": {"geometry": "unsupported_length", "axis": {"type": "list", "values": [_q(1000), _q(1800)]}}}
    original = deepcopy(request)
    expected = calculate(request)
    response = _run(request, "--json")
    assert response.exit_code == 0, response.output
    assert json.loads(response.stdout) == json.loads(json.dumps(expected))
    assert request == original
    csv_response = _run(request, "--format", "csv")
    assert csv_response.exit_code == 0
    rows = list(csv.DictReader(io.StringIO(csv_response.stdout)))
    assert [float(row["axis_value"]) for row in rows] == [1000, 1800]
    assert all(row["axis"] == "unsupported_length" and row["axis_unit"] == "mm" for row in rows)
    check = _run(request, "--format", "text", command="check")
    assert check.exit_code == 0, check.output
    assert "PASS" in check.stdout and "INDETERMINATE" not in check.stdout


def test_sized_material_comparison_csv_retains_selected_dimensions_and_mass() -> None:
    size = {"schema_version": "5.0.0", "model": "tube", "operation": "size",
            "material": {"type": "named", "name": "Al-6061-T6"},
            "inputs": {"external_pressure": _q(1, "MPa"), "internal_radius": _q(50), "axial_length": _q(300),
                       "minimum_margin": 1, "wall_thickness_bounds": {"lower": _q(0.1), "upper": _q(3)}}}
    request = {"schema_version": "5.0.0", "model": "compare-materials", "request": size,
               "inputs": {"materials": ["Al-6061-T6", "Ti-6Al-4V"]}}
    response = _run(request, "--format", "csv")
    assert response.exit_code == 0, response.output
    rows = list(csv.DictReader(io.StringIO(response.stdout)))
    assert [row["material"] for row in rows] == request["inputs"]["materials"]
    assert all(row["status"] == "pass" for row in rows)
    assert float(rows[0]["wall_thickness_mm"]) > float(rows[1]["wall_thickness_mm"])
    assert all(float(row["structural_air_mass_kg"]) > 0 for row in rows)
    summary = _run(request, "--format", "summary")
    entries = json.loads(summary.stdout)["entries"]
    assert all(entry["summary"]["structural_mass"]["status"] == "available" for entry in entries)


def test_structural_margin_retarget_keeps_explicit_deflection_limit() -> None:
    request = json.loads((EXAMPLES / "cylinder_housing.json").read_text())
    response = _run(request, "--minimum-margin", "0.1", "--format", "summary", command="check")
    assessment = json.loads(response.stdout)["assessment"]
    deflection = next(check for check in assessment["checks"] if check["id"].endswith(".center_deflection"))
    assert deflection["required_margin"] == 0
    assert deflection["capacity"]["unit"] == "mm"
