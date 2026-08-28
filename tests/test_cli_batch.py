"""The multi-point operations: sweep and compare-materials."""

from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from pv_calc import evaluate, resolve
from pv_calc.cli import app
from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    MAX_BATCH_POINTS,
    MaterialComparisonRequest,
    SweepRequest,
)
from pv_calc.errors import CalcCliError
from pv_calc.units import Q_, magnitude

from _cli_helpers import (
    EXAMPLES,
    MATERIALS_FILE,
    SWEEP_FORWARD_EXAMPLES,
    _error_payload,
    runner,
)


def _written(path: Path, request: dict[str, Any]) -> str:
    path.write_text(json.dumps(request), encoding="utf-8")
    return str(path)


def _sweep_request(base: dict[str, Any], inputs: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "sweep",
        "inputs": inputs,
        "request": base,
    }


def _pressure_sweep(base: dict[str, Any], axis: dict[str, Any]) -> dict[str, Any]:
    return _sweep_request(base, {"external_pressure": axis})


# The two constants the parent repository uses, so the expected products below
# are the same doubles its committed design pressures carry.
SWEEP_DEPTH_FLUID_DENSITY = 1025.0
SWEEP_DEPTH_GRAVITY = 9.81
SWEEP_DEPTH_DESIGN_FACTOR = 1.25


def _depth_sweep(base: dict[str, Any], axis: dict[str, Any]) -> dict[str, Any]:
    return _sweep_request(
        base,
        {
            "depth": axis,
            "design_factor": SWEEP_DEPTH_DESIGN_FACTOR,
            "fluid_density": {
                "value": SWEEP_DEPTH_FLUID_DENSITY,
                "unit": "kg/m^3",
            },
            "gravity": {"value": SWEEP_DEPTH_GRAVITY, "unit": "m/s^2"},
        },
    )


@pytest.mark.parametrize("model", sorted(SWEEP_FORWARD_EXAMPLES))
def test_sweep_point_equals_independent_single_point_invocation(
    model: str, tmp_path: Path
) -> None:
    base = json.loads(
        (EXAMPLES / SWEEP_FORWARD_EXAMPLES[model]).read_text(encoding="utf-8")
    )
    example_pressure = base["inputs"]["external_pressure"]
    # Descending, so the response also proves the caller's order is preserved.
    axis_values = [
        {"value": example_pressure["value"], "unit": example_pressure["unit"]},
        {"value": example_pressure["value"] * 0.5, "unit": example_pressure["unit"]},
    ]
    swept = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "sweep.json",
                _pressure_sweep(base, {"type": "list", "values": axis_values}),
            ),
            "--json",
        ],
    )

    assert swept.exit_code == 0, swept.output
    payload = json.loads(swept.stdout)
    assert payload["schema_version"] == CALC_SCHEMA_VERSION
    assert payload["operation"] == "sweep"
    assert payload["model"] == model
    assert payload["sweep"]["swept_input"] == "inputs.external_pressure"
    points = payload["sweep"]["points"]
    assert [point["external_pressure"] for point in points] == axis_values

    for index, point in enumerate(points):
        single = runner.invoke(
            app,
            [
                model,
                "--input",
                _written(
                    tmp_path / f"single_{index}.json",
                    {
                        **base,
                        "inputs": {
                            **base["inputs"],
                            "external_pressure": point["external_pressure"],
                        },
                    },
                ),
                "--json",
            ],
        )
        assert single.exit_code == 0, single.output
        assert point["response"] == json.loads(single.stdout)


@pytest.mark.parametrize("model", sorted(SWEEP_FORWARD_EXAMPLES))
def test_sweep_depth_point_equals_independent_conversion_and_single_point(
    model: str, tmp_path: Path
) -> None:
    base = json.loads(
        (EXAMPLES / SWEEP_FORWARD_EXAMPLES[model]).read_text(encoding="utf-8")
    )
    # Sweep each model near its own example pressure: the depth whose design
    # pressure is that pressure, and half of it.
    example_pressure_mpa = magnitude(
        Q_(
            base["inputs"]["external_pressure"]["value"],
            base["inputs"]["external_pressure"]["unit"],
        ),
        "MPa",
    )
    depth_m = (
        example_pressure_mpa
        * 1_000_000.0
        / (SWEEP_DEPTH_FLUID_DENSITY * SWEEP_DEPTH_GRAVITY * SWEEP_DEPTH_DESIGN_FACTOR)
    )
    # Descending, so the response also proves the caller's order is preserved.
    axis_values = [
        {"value": depth_m, "unit": "m"},
        {"value": depth_m * 0.5, "unit": "m"},
    ]
    swept = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "sweep.json",
                _depth_sweep(base, {"type": "list", "values": axis_values}),
            ),
            "--json",
        ],
    )

    assert swept.exit_code == 0, swept.output
    payload = json.loads(swept.stdout)
    assert payload["schema_version"] == CALC_SCHEMA_VERSION
    assert payload["operation"] == "sweep"
    assert payload["model"] == model
    # The design pressure is substituted into the swept request's own input.
    assert payload["sweep"]["swept_input"] == "inputs.external_pressure"
    assert payload["sweep"]["depth_to_pressure"]["substituted_pressure"] == (
        "design_external_pressure"
    )
    points = payload["sweep"]["points"]
    assert [point["depth"] for point in points] == axis_values

    for index, point in enumerate(points):
        # Lautrup Eq. (4-3) written out here, in the kernel's left-to-right
        # order, so the comparison is exact rather than approximate.
        depth = point["depth"]["value"]
        assert point["service_external_pressure"] == {
            "unit": "MPa",
            "value": SWEEP_DEPTH_FLUID_DENSITY * SWEEP_DEPTH_GRAVITY * depth / 1e6,
        }
        assert point["design_external_pressure"] == {
            "unit": "MPa",
            "value": SWEEP_DEPTH_FLUID_DENSITY
            * SWEEP_DEPTH_GRAVITY
            * depth
            * SWEEP_DEPTH_DESIGN_FACTOR
            / 1e6,
        }
        single = runner.invoke(
            app,
            [
                model,
                "--input",
                _written(
                    tmp_path / f"single_{index}.json",
                    {
                        **base,
                        "inputs": {
                            **base["inputs"],
                            "external_pressure": point["design_external_pressure"],
                        },
                    },
                ),
                "--json",
            ],
        )
        assert single.exit_code == 0, single.output
        assert point["response"] == json.loads(single.stdout)


def test_sweep_depth_axis_reports_its_conversion_and_exact_endpoints() -> None:
    example = EXAMPLES / "sweep_tube_depth_range.json"
    result = runner.invoke(app, ["sweep", "--input", str(example), "--json"])

    assert result.exit_code == 0, result.output
    sweep = json.loads(result.stdout)["sweep"]
    assert [point["depth"] for point in sweep["points"]] == [
        {"unit": "m", "value": 500.0},
        {"unit": "m", "value": 1000.0},
        {"unit": "m", "value": 1500.0},
    ]
    conversion = sweep["depth_to_pressure"]
    assert conversion["calculation_source"]["function"] == (
        "pv_calc.hydrostatics.external_pressure_from_depth"
    )
    assert conversion["calculation_source"]["model_id"] == (
        "hydrostatic_external_pressure_from_depth"
    )
    assert conversion["design_factor"] == 1.25
    assert conversion["fluid_density"] == {"unit": "kg/m^3", "value": 1025.0}
    assert conversion["gravity"] == {"unit": "m/s^2", "value": 9.81}
    assert conversion["pressure_reference_convention"] == (
        "differential_across_wall_interior_at_zero_gauge"
    )
    assert any("interior held" in note for note in conversion["assumptions"])

    from_options = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            "-",
            "--depth-start",
            "500 m",
            "--depth-stop",
            "1500 m",
            "--depth-count",
            "3",
            "--fluid-density",
            "1025 kg/m^3",
            "--gravity",
            "9.81 m/s^2",
            "--design-factor",
            "1.25",
            "--json",
        ],
        input=json.dumps(
            {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "sweep",
                "request": json.loads(example.read_text(encoding="utf-8"))["request"],
            }
        ),
    )
    assert from_options.exit_code == 0, from_options.output
    from_options_sweep = json.loads(from_options.stdout)["sweep"]
    # The option path normalizes its units through pint, so the echoed axis
    # spells the depth unit "meter"; every evaluated point is identical.
    assert from_options_sweep["points"] == sweep["points"]
    assert from_options_sweep["depth_to_pressure"] == sweep["depth_to_pressure"]


def test_sweep_range_axis_interpolates_between_exact_endpoints() -> None:
    example = EXAMPLES / "sweep_tube_pressure_range.json"
    result = runner.invoke(app, ["sweep", "--input", str(example), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    start_mpa = magnitude(Q_(500.0, "psi"), "MPa")
    stop_mpa = magnitude(Q_(1500.0, "psi"), "MPa")
    assert [point["external_pressure"] for point in payload["sweep"]["points"]] == [
        {"unit": "MPa", "value": start_mpa},
        {"unit": "MPa", "value": start_mpa * 0.5 + stop_mpa * 0.5},
        {"unit": "MPa", "value": stop_mpa},
    ]
    assert payload["sweep"]["axis"] == json.loads(example.read_text(encoding="utf-8"))[
        "inputs"
    ]["external_pressure"]

    from_options = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            "-",
            "--pressure-start",
            "500 psi",
            "--pressure-stop",
            "1500 psi",
            "--pressure-count",
            "3",
            "--json",
        ],
        input=json.dumps(
            {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "sweep",
                "request": json.loads(example.read_text(encoding="utf-8"))["request"],
            }
        ),
    )
    assert from_options.exit_code == 0, from_options.output
    assert [
        point["response"]
        for point in json.loads(from_options.stdout)["sweep"]["points"]
    ] == [point["response"] for point in payload["sweep"]["points"]]


def test_sweep_reports_a_withheld_capacity_as_a_normal_result(tmp_path: Path) -> None:
    base = json.loads(
        (EXAMPLES / "smooth_buckling_moderate_nasa.json").read_text(encoding="utf-8")
    )
    del base["material"]["properties"]["proportional_limit"]
    result = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "sweep.json",
                _pressure_sweep(
                    base,
                    {
                        "type": "list",
                        "values": [
                            {"value": 0.01, "unit": "MPa"},
                            {"value": 0.02, "unit": "MPa"},
                        ],
                    },
                ),
            ),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    points = json.loads(result.stdout)["sweep"]["points"]
    assert [point["response"]["result"]["capacity_status"] for point in points] == [
        "withheld_applicability",
        "withheld_applicability",
    ]
    assert all(point["response"]["result"]["margin"] is None for point in points)


def test_sweep_axis_and_request_errors_use_the_cli_error_contract(
    tmp_path: Path,
) -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    one_point = {"type": "list", "values": [{"value": 1.0, "unit": "MPa"}]}
    bare = _written(
        tmp_path / "bare.json",
        {"schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": base},
    )
    committed = str(EXAMPLES / "sweep_tube_pressure_range.json")

    missing_input = runner.invoke(app, ["sweep", "--json"])
    assert _error_payload(missing_input)["error"]["code"] == "missing_input"

    both_axis_forms = runner.invoke(
        app,
        ["sweep", "--input", bare, "--pressure", "1 MPa", "--pressure-start", "1 MPa"],
    )
    assert _error_payload(both_axis_forms)["error"]["code"] == "axis_source_conflict"

    file_and_options = runner.invoke(
        app, ["sweep", "--input", committed, "--pressure", "1 MPa"]
    )
    assert _error_payload(file_and_options)["error"]["code"] == "axis_source_conflict"

    no_axis = runner.invoke(app, ["sweep", "--input", bare, "--json"])
    assert _error_payload(no_axis)["error"]["code"] == "invalid_request"

    single_point_range = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            bare,
            "--pressure-start",
            "1 MPa",
            "--pressure-stop",
            "2 MPa",
            "--pressure-count",
            "1",
        ],
    )
    assert _error_payload(single_point_range)["error"]["code"] == "invalid_request"

    fractional_count = runner.invoke(
        app, ["sweep", "--input", bare, "--pressure-count", "2.5"]
    )
    assert _error_payload(fractional_count)["error"]["code"] == "invalid_number"

    # Inverse and non-forward models are excluded by the swept request union.
    inverse = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "inverse.json",
                _pressure_sweep(
                    json.loads(
                        (EXAMPLES / "tube_size_7_ksi.json").read_text(encoding="utf-8")
                    ),
                    one_point,
                ),
            ),
        ],
    )
    assert _error_payload(inverse)["error"]["code"] == "invalid_request"

    mass = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "mass.json",
                _pressure_sweep(
                    json.loads(
                        (
                            EXAMPLES / "mass_properties_aluminium_housing.json"
                        ).read_text(encoding="utf-8")
                    ),
                    one_point,
                ),
            ),
        ],
    )
    assert _error_payload(mass)["error"]["code"] == "invalid_request"

    # A point that cannot be evaluated keeps the single-point error code and
    # adds its axis position, so a long sweep names the request that failed.
    unevaluable = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "unevaluable.json",
                _pressure_sweep(
                    base,
                    {
                        "type": "list",
                        "values": [
                            {"value": 1.0, "unit": "MPa"},
                            {"value": 0.0, "unit": "MPa"},
                        ],
                    },
                ),
            ),
        ],
    )
    payload = _error_payload(unevaluable)
    assert payload["error"]["code"] == "unevaluable_model"
    assert payload["error"]["details"][-1] == {
        "external_pressure": {"unit": "MPa", "value": 0.0},
        "point_index": 1,
    }


def test_sweep_depth_axis_errors_use_the_cli_error_contract(tmp_path: Path) -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    bare = _written(
        tmp_path / "bare.json",
        {"schema_version": CALC_SCHEMA_VERSION, "model": "sweep", "request": base},
    )

    both_axes = runner.invoke(
        app, ["sweep", "--input", bare, "--pressure", "1 MPa", "--depth", "100 m"]
    )
    assert _error_payload(both_axes)["error"]["code"] == "axis_source_conflict"

    pressure_axis_with_fluid = runner.invoke(
        app,
        ["sweep", "--input", bare, "--pressure", "1 MPa", "--gravity", "9.81 m/s^2"],
    )
    assert _error_payload(pressure_axis_with_fluid)["error"]["code"] == (
        "axis_source_conflict"
    )

    # A depth axis needs all three conversion inputs; none has a default.
    incomplete = runner.invoke(
        app, ["sweep", "--input", bare, "--depth", "100 m", "--gravity", "9.81 m/s^2"]
    )
    assert _error_payload(incomplete)["error"]["code"] == "invalid_request"

    # Both axes in one request document is rejected by the inputs union.
    both_in_request = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "both.json",
                _sweep_request(
                    base,
                    {
                        "depth": {
                            "type": "list",
                            "values": [{"value": 100.0, "unit": "m"}],
                        },
                        "design_factor": 1.25,
                        "external_pressure": {
                            "type": "list",
                            "values": [{"value": 1.0, "unit": "MPa"}],
                        },
                        "fluid_density": {"value": 1025.0, "unit": "kg/m^3"},
                        "gravity": {"value": 9.81, "unit": "m/s^2"},
                    },
                ),
            ),
        ],
    )
    assert _error_payload(both_in_request)["error"]["code"] == "invalid_request"

    # The kernel gates its own inputs; a rejected depth keeps that boundary and
    # names the axis position, exactly as a rejected pressure point does.
    negative_depth = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "negative.json",
                _depth_sweep(
                    base,
                    {
                        "type": "list",
                        "values": [
                            {"value": 100.0, "unit": "m"},
                            {"value": -1.0, "unit": "m"},
                        ],
                    },
                ),
            ),
        ],
    )
    payload = _error_payload(negative_depth)
    assert payload["error"]["code"] == "unevaluable_model"
    assert payload["error"]["message"] == "depth_m must be finite and non-negative"
    assert payload["error"]["details"][-1] == {
        "depth": {"unit": "m", "value": -1.0},
        "point_index": 1,
    }

    zero_factor_request = _depth_sweep(
        base, {"type": "list", "values": [{"value": 100.0, "unit": "m"}]}
    )
    zero_factor_request["inputs"]["design_factor"] = 0.0
    zero_factor = runner.invoke(
        app,
        ["sweep", "--input", _written(tmp_path / "factor.json", zero_factor_request)],
    )
    assert _error_payload(zero_factor)["error"]["code"] == "invalid_request"


def test_sweep_nonfinite_response_keeps_the_point_index(monkeypatch) -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    request = SweepRequest.model_validate(
        _pressure_sweep(
            base,
            {
                "type": "list",
                "values": [
                    {"value": 1.0, "unit": "MPa"},
                    {"value": 2.0, "unit": "MPa"},
                ],
            },
        )
    )
    responses = iter([{"finite": 1.0}, {"nonfinite": math.inf}])
    monkeypatch.setattr(
        evaluate,
        "_evaluate_forward_request",
        lambda *_args, **_kwargs: next(responses),
    )

    with pytest.raises(CalcCliError) as caught:
        evaluate._evaluate_sweep(request, None)

    assert caught.value.code == "unevaluable_model"
    assert caught.value.details[-1] == {
        "external_pressure": {"unit": "MPa", "value": 2.0},
        "point_index": 1,
    }


def test_sweep_parses_the_materials_database_once(tmp_path: Path, monkeypatch) -> None:
    """A batch invocation reads a named-material database once, not per point."""
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    base["material"] = {"type": "named", "name": "Al-6061-T6"}
    # A fresh path, so the count starts from a database no earlier test loaded.
    database = tmp_path / "materials.yaml"
    database.write_text(MATERIALS_FILE.read_text(encoding="utf-8"), encoding="utf-8")
    loads: list[Path] = []
    parse = resolve.load_calc_materials

    def _counted(path: Path) -> dict[str, Any]:
        loads.append(Path(path))
        return parse(path)

    monkeypatch.setattr(resolve, "load_calc_materials", _counted)

    swept = runner.invoke(
        app,
        [
            "sweep",
            "--input",
            _written(
                tmp_path / "sweep.json",
                _pressure_sweep(
                    base,
                    {
                        "type": "range",
                        "start": {"value": 1.0, "unit": "MPa"},
                        "stop": {"value": 5.0, "unit": "MPa"},
                        "count": 5,
                    },
                ),
            ),
            "--materials-file",
            str(database),
            "--json",
        ],
    )

    assert swept.exit_code == 0, swept.output
    assert len(json.loads(swept.stdout)["sweep"]["points"]) == 5
    assert loads == [database]


def test_a_rewritten_materials_database_is_never_served_stale(tmp_path: Path) -> None:
    """A later invocation reads the file's current content, not a cached parse.

    The parse cache exists for batch operations; between invocations the file
    can be edited, and its stat identity is what invalidates the entry.
    """
    database = tmp_path / "materials.yaml"

    def _database_text(yield_strength_mpa: float) -> str:
        return (
            "materials:\n"
            "  Test-Alloy:\n"
            "    failure_category: ductile_metal\n"
            f"    yield_strength_mpa: {yield_strength_mpa}\n"
            "    elastic_modulus_mpa: 70000.0\n"
            "    poisson_ratio: 0.33\n"
            '    source: "staleness test record"\n'
        )

    def _reported_yield_mpa() -> float:
        result = runner.invoke(
            app,
            [
                "tube",
                "--external-pressure",
                "1 MPa",
                "--internal-radius",
                "76.2 mm",
                "--wall-thickness",
                "6 mm",
                "--material",
                "Test-Alloy",
                "--materials-file",
                str(database),
                "--json",
            ],
        )
        assert result.exit_code == 0, result.output
        material = json.loads(result.stdout)["material"]
        return material["properties_used"]["yield_strength"]["value"]

    database.write_text(_database_text(400.0), encoding="utf-8")
    assert _reported_yield_mpa() == 400.0
    # Different digits and length, so the mtime and the size both move.
    database.write_text(_database_text(87.5), encoding="utf-8")
    assert _reported_yield_mpa() == 87.5


COMPARED_MATERIALS = ["Ti-6Al-4V", "Al-6061-T6"]
COMPARISON_MASS_PROPERTIES_INPUTS = {
    "solid_volume": {"value": 2.5, "unit": "L"},
    "displaced_volume": {"value": 6.0, "unit": "L"},
    "fluid_density": {"value": 1025.0, "unit": "kg/m^3"},
    "gravity": {"value": 9.81, "unit": "m/s^2"},
}


def _comparison_request(
    base: dict[str, Any],
    materials: list[str],
    *,
    mass_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    inputs: dict[str, Any] = {"materials": materials}
    if mass_properties is not None:
        inputs["mass_properties"] = mass_properties
    return {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "compare-materials",
        "inputs": inputs,
        "request": base,
    }


@pytest.mark.parametrize("model", sorted(SWEEP_FORWARD_EXAMPLES))
def test_comparison_entry_equals_independent_single_material_invocation(
    model: str, tmp_path: Path
) -> None:
    base = json.loads(
        (EXAMPLES / SWEEP_FORWARD_EXAMPLES[model]).read_text(encoding="utf-8")
    )
    compared = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(
                tmp_path / "comparison.json",
                _comparison_request(base, COMPARED_MATERIALS),
            ),
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert compared.exit_code == 0, compared.output
    payload = json.loads(compared.stdout)
    assert payload["schema_version"] == CALC_SCHEMA_VERSION
    assert payload["operation"] == "compare-materials"
    assert payload["model"] == model
    assert payload["comparison"]["substituted_input"] == "request.material"
    entries = payload["comparison"]["entries"]
    # The listed order, which is not the example's own material and not sorted.
    assert [entry["material"] for entry in entries] == COMPARED_MATERIALS

    for index, entry in enumerate(entries):
        assert entry["outcome"] == "evaluated"
        assert "mass_properties" not in entry
        single = runner.invoke(
            app,
            [
                model,
                "--input",
                _written(
                    tmp_path / f"single_{index}.json",
                    {
                        **base,
                        "material": {"type": "named", "name": entry["material"]},
                    },
                ),
                "--materials-file",
                str(MATERIALS_FILE),
                "--json",
            ],
        )
        assert single.exit_code == 0, single.output
        assert entry["response"] == json.loads(single.stdout)


def test_comparison_mass_properties_equal_the_standalone_operation(
    tmp_path: Path,
) -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    compared = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(
                tmp_path / "comparison.json",
                _comparison_request(
                    base,
                    COMPARED_MATERIALS,
                    mass_properties=COMPARISON_MASS_PROPERTIES_INPUTS,
                ),
            ),
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert compared.exit_code == 0, compared.output
    entries = json.loads(compared.stdout)["comparison"]["entries"]
    assert [entry["material"] for entry in entries] == COMPARED_MATERIALS

    for index, entry in enumerate(entries):
        single = runner.invoke(
            app,
            [
                "mass-properties",
                "--input",
                _written(
                    tmp_path / f"mass_{index}.json",
                    {
                        "schema_version": CALC_SCHEMA_VERSION,
                        "model": "mass-properties",
                        "inputs": COMPARISON_MASS_PROPERTIES_INPUTS,
                        "material": {"type": "named", "name": entry["material"]},
                    },
                ),
                "--materials-file",
                str(MATERIALS_FILE),
                "--json",
            ],
        )
        assert single.exit_code == 0, single.output
        assert entry["mass_properties"] == json.loads(single.stdout)


def test_comparison_carries_a_missing_property_as_that_entry_outcome(
    tmp_path: Path,
) -> None:
    """One incomplete record is that entry's outcome, not the run's failure."""
    database = tmp_path / "materials.yaml"
    database.write_text(
        "materials:\n"
        "  Al-6061-T6:\n"
        "    density_kg_per_m3: 2700\n"
        "    elastic_modulus_mpa: 68900\n"
        "    poisson_ratio: 0.33\n"
        "    yield_strength_mpa: 276\n"
        "    failure_category: ductile_metal\n"
        "    source: \"Complete calculator property set\"\n"
        "  Stress-Only:\n"
        "    yield_strength_mpa: 500\n"
        "    failure_category: ductile_metal\n"
        "    source: \"Yield-only calculator property set\"\n",
        encoding="utf-8",
    )
    materials = ["Stress-Only", "Al-6061-T6"]

    plate = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(
                tmp_path / "plate.json",
                _comparison_request(
                    json.loads(
                        (EXAMPLES / "plate_9_0384_ksi.json").read_text(encoding="utf-8")
                    ),
                    materials,
                ),
            ),
            "--materials-file",
            str(database),
            "--json",
        ],
    )
    assert plate.exit_code == 0, plate.output
    plate_entries = json.loads(plate.stdout)["comparison"]["entries"]
    assert plate_entries[0] == {
        "material": "Stress-Only",
        # The same message the single-material invocation fails with.
        "message": "plate material properties are incomplete",
        "outcome": "invalid_material",
    }
    assert plate_entries[1]["outcome"] == "evaluated"
    assert plate_entries[1]["response"]["result"]["margin"]

    # The tube model reads no elastic property, so the same record is complete
    # for it and incomplete only for the mass properties beside it.
    tube = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(
                tmp_path / "tube.json",
                _comparison_request(
                    json.loads(
                        (EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8")
                    ),
                    materials,
                    mass_properties=COMPARISON_MASS_PROPERTIES_INPUTS,
                ),
            ),
            "--materials-file",
            str(database),
            "--json",
        ],
    )
    assert tube.exit_code == 0, tube.output
    tube_entries = json.loads(tube.stdout)["comparison"]["entries"]
    assert tube_entries[0] == {
        "material": "Stress-Only",
        "message": "mass-properties material properties are incomplete",
        "outcome": "invalid_material",
    }
    assert tube_entries[1]["outcome"] == "evaluated"
    assert "mass_properties" in tube_entries[1]

    single = runner.invoke(
        app,
        [
            "plate",
            "--input",
            str(EXAMPLES / "plate_9_0384_ksi.json"),
            "--materials-file",
            str(database),
            "--json",
        ],
    )
    assert single.exit_code == 0, single.output


def test_comparison_list_and_database_errors_use_the_cli_error_contract(
    tmp_path: Path,
) -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    document = _written(
        tmp_path / "comparison.json", _comparison_request(base, COMPARED_MATERIALS)
    )

    # An unknown name is a fault in the list, not a property one record lacks,
    # so it fails the comparison with its own code and the entry's position.
    unknown = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(
                tmp_path / "unknown.json",
                _comparison_request(base, ["Al-6061-T6", "not-a-material"]),
            ),
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )
    unknown_payload = _error_payload(unknown)
    assert unknown_payload["error"]["code"] == "unknown_material"
    assert unknown_payload["error"]["details"][-1] == {
        "entry_index": 1,
        "material": "not-a-material",
    }

    missing_database = runner.invoke(
        app, ["compare-materials", "--input", document, "--json"]
    )
    assert _error_payload(missing_database)["error"]["code"] == "missing_materials_file"

    # An unreadable database is a property of the list, not of one record, so it
    # fails the whole comparison at the first entry that had to resolve from it.
    malformed = tmp_path / "malformed.yaml"
    malformed.write_text("materials: [not, a, mapping]\n", encoding="utf-8")
    unreadable_database = runner.invoke(
        app,
        ["compare-materials", "--input", document, "--materials-file", str(malformed), "--json"],
    )
    unreadable_payload = _error_payload(unreadable_database)
    assert unreadable_payload["error"]["code"] == "invalid_material_database"
    assert unreadable_payload["error"]["details"][-1] == {
        "entry_index": 0,
        "material": COMPARED_MATERIALS[0],
    }

    missing_input = runner.invoke(
        app, ["compare-materials", "--material", "Al-6061-T6", "--json"]
    )
    assert _error_payload(missing_input)["error"]["code"] == "missing_input"

    conflict = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            document,
            "--material",
            "Al-6061-T6",
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )
    assert _error_payload(conflict)["error"]["code"] == "material_source_conflict"

    empty_list = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(tmp_path / "empty.json", _comparison_request(base, [])),
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )
    assert _error_payload(empty_list)["error"]["code"] == "invalid_request"


def test_comparison_material_options_match_the_same_list_in_the_document(
    tmp_path: Path,
) -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    document = _comparison_request(
        base,
        COMPARED_MATERIALS,
        mass_properties=COMPARISON_MASS_PROPERTIES_INPUTS,
    )
    option_document = {
        **document,
        "inputs": {"mass_properties": COMPARISON_MASS_PROPERTIES_INPUTS},
    }
    from_options = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(tmp_path / "no_materials.json", option_document),
            *[option for name in COMPARED_MATERIALS for option in ("--material", name)],
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )
    from_document = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            _written(tmp_path / "comparison.json", document),
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert from_options.exit_code == 0, from_options.output
    assert from_document.exit_code == 0, from_document.output
    assert from_options.stdout == from_document.stdout


def test_comparison_nonfinite_response_keeps_the_entry_index(monkeypatch) -> None:
    base = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    request = MaterialComparisonRequest.model_validate(
        _comparison_request(base, ["Al-6061-T6"])
    )
    monkeypatch.setattr(
        evaluate,
        "_evaluate_forward_request",
        lambda *_args, **_kwargs: {"nonfinite": math.inf},
    )

    with pytest.raises(CalcCliError) as caught:
        evaluate._evaluate_material_comparison(request, MATERIALS_FILE)

    assert caught.value.code == "unevaluable_model"
    assert caught.value.details[-1] == {
        "entry_index": 0,
        "material": "Al-6061-T6",
    }


def test_multi_point_operations_reject_oversized_batches() -> None:
    tube = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    with pytest.raises(ValidationError):
        SweepRequest.model_validate(
            _pressure_sweep(
                tube,
                {
                    "type": "range",
                    "start": {"value": 1.0, "unit": "MPa"},
                    "stop": {"value": 2.0, "unit": "MPa"},
                    "count": MAX_BATCH_POINTS + 1,
                },
            )
        )
    with pytest.raises(ValidationError):
        MaterialComparisonRequest.model_validate(
            _comparison_request(
                tube,
                ["Al-6061-T6"] * (MAX_BATCH_POINTS + 1),
            )
        )


def test_committed_comparison_example_runs(tmp_path: Path) -> None:
    example = EXAMPLES / "compare_materials_tube_housing.json"
    result = runner.invoke(
        app,
        [
            "compare-materials",
            "--input",
            str(example),
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    entries = json.loads(result.stdout)["comparison"]["entries"]
    assert [entry["material"] for entry in entries] == [
        "Al-6061-T6",
        "Ti-6Al-4V",
    ]
    # One fixed geometry and load: the entries differ only by the material.
    thicknesses = {
        entry["response"]["result"]["wall_thickness_mm"]["value"] for entry in entries
    }
    assert len(thicknesses) == 1
    assert [entry["response"]["result"]["strength_mpa"]["value"] for entry in entries] == [
        241.0,
        827.0,
    ]
    assert [
        entry["mass_properties"]["result"]["structural_air_mass_kg"]["value"]
        for entry in entries
    ] == [pytest.approx(2.5e-3 * 2700.0), pytest.approx(2.5e-3 * 4430.0)]
