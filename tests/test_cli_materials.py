"""Material selection, failure categories, and the calc material loader through the CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from pv_calc.cli import app
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.materials import CalcMaterial, load_calc_materials
from pv_calc.units import Q_, magnitude

from _cli_helpers import (
    MATERIALS_FILE,
    _error_payload,
    runner,
)


def test_named_material_returns_only_values_used_by_model() -> None:
    result = runner.invoke(
        app,
        [
            "plate",
            "--external-pressure",
            "1MPa",
            "--free-radius",
            "50mm",
            "--plate-thickness",
            "10mm",
            "--boundary-condition",
            "fixed",
            "--material",
            "Al-6061-T6",
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    material = json.loads(result.stdout)["material"]
    assert material["source"]["type"] == "named"
    assert material["source"]["name"] == "Al-6061-T6"
    assert material["source"]["provenance"].startswith(
        "ASTM B221 and ASTM B241 specification minimums for wrought aluminum 6061-T6"
    )
    assert material["properties_used"] == {
        "elastic_modulus": {"unit": "MPa", "value": 68900.0},
        "failure_category": "ductile_metal",
        "poisson_ratio": 0.33,
        "yield_strength": {"unit": "MPa", "value": 241.0},
    }


def test_calc_material_database_carries_only_what_a_model_reads(tmp_path: Path) -> None:
    """A yield-only database runs the tube model, and only the tube model.

    pv-calc validates what it reads, so no mass or ultimate-strength data is
    needed. The models that do read elasticity say so at the point of use: the
    plate rejects the record, while the tube keeps every stress result and
    reports empty elastic slots beside a withheld displacement.
    """
    calc_only = tmp_path / "materials.yaml"
    calc_only.write_text(
        "materials:\n"
        "  Al-6061-T6:\n"
        "    yield_strength_mpa: 276\n"
        "    failure_category: ductile_metal\n"
        "    source: \"Yield-only calculator property set\"\n",
        encoding="utf-8",
    )
    named = ["--material", "Al-6061-T6", "--materials-file", str(calc_only), "--json"]

    tube = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure",
            "1000psi",
            "--internal-radius",
            "3inch",
            "--wall-thickness",
            "0.470inch",
            *named,
        ],
    )
    assert tube.exit_code == 0, tube.output
    tube_payload = json.loads(tube.stdout)
    tube_material = tube_payload["material"]
    assert tube_material["source"]["name"] == "Al-6061-T6"
    assert tube_material["properties_used"] == {
        "elastic_modulus": {"unit": "MPa", "value": None},
        "failure_category": "ductile_metal",
        "poisson_ratio": None,
        "yield_strength": {"unit": "MPa", "value": 276.0},
    }
    assert tube_payload["result"]["displacement_status"] == (
        "withheld_missing_elastic_properties"
    )
    assert tube_payload["result"]["margin"] is not None

    plate = runner.invoke(
        app,
        [
            "plate",
            "--external-pressure",
            "1MPa",
            "--free-radius",
            "50mm",
            "--plate-thickness",
            "10mm",
            "--boundary-condition",
            "fixed",
            *named,
        ],
    )
    assert _error_payload(plate)["error"]["code"] == "invalid_material"

    # The same omissions in an explicit property set are caught earlier, by the
    # request schema, which requires both fields for the plate model.
    explicit = runner.invoke(
        app,
        [
            "plate",
            "--external-pressure",
            "1MPa",
            "--free-radius",
            "50mm",
            "--plate-thickness",
            "10mm",
            "--boundary-condition",
            "fixed",
            "--yield-strength",
            "276MPa",
            "--failure-category",
            "ductile_metal",
            "--json",
        ],
    )
    assert _error_payload(explicit)["error"]["code"] == "invalid_request"


def test_plastic_tube_options_and_json_agree_and_report_the_working_strength() -> None:
    """The manual's PVC report sample: 3.438 in I.D., 0.531 in wall, at 100 psi."""
    options = [
        "tube",
        "--external-pressure", "100 psi",
        "--internal-radius", "1.719 in",
        "--wall-thickness", "0.531 in",
        "--failure-category", "plastic",
        "--working-strength", "6 ksi",
        "--elastic-modulus", "350000 psi",
        "--poisson-ratio", "0.36",
        "--json",
    ]
    from_options = runner.invoke(app, options)
    assert from_options.exit_code == 0, from_options.output
    request = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "tube",
        "inputs": {
            "external_pressure": {"value": 100, "unit": "psi"},
            "internal_radius": {"value": 1.719, "unit": "in"},
            "wall_thickness": {"value": 0.531, "unit": "in"},
        },
        "material": {
            "type": "explicit",
            "properties": {
                "failure_category": "plastic",
                "working_strength": {"value": 6, "unit": "ksi"},
                "elastic_modulus": {"value": 350000, "unit": "psi"},
                "poisson_ratio": 0.36,
            },
        },
    }
    from_json = runner.invoke(app, ["tube", "--input", "-", "--json"], input=json.dumps(request))
    assert from_json.exit_code == 0, from_json.output
    assert json.loads(from_options.stdout) == json.loads(from_json.stdout)

    payload = json.loads(from_json.stdout)
    assert payload["material"]["properties_used"] == {
        "elastic_modulus": {"unit": "MPa", "value": pytest.approx(350_000 * 0.006894757293168361)},
        "failure_category": "plastic",
        "poisson_ratio": 0.36,
        "working_strength": {"unit": "MPa", "value": pytest.approx(6_000 * 0.006894757293168361)},
    }
    result = payload["result"]
    assert result["failure_criterion"] == "maximum_hoop_stress_vs_working_strength"
    assert magnitude(Q_(result["governing_stress_mpa"]["value"], "MPa"), "psi") == pytest.approx(
        480.42, abs=0.005
    )
    assert magnitude(
        Q_(result["theoretical_failure_pressure_mpa"]["value"], "MPa"), "ksi"
    ) == pytest.approx(1.2489, abs=0.00005)


def test_brittle_plate_reads_both_ultimate_strengths_and_the_shells_read_one(
    tmp_path: Path,
) -> None:
    database = tmp_path / "materials.yaml"
    database.write_text(
        "materials:\n"
        "  Glass-brittle-both-ultimates:\n"
        "    failure_category: brittle\n"
        "    ultimate_tensile_strength_mpa: 34.5\n"
        "    ultimate_compressive_strength_mpa: 1448\n"
        "    elastic_modulus_mpa: 82000\n"
        "    poisson_ratio: 0.206\n"
        "    source: \"Illustrative brittle record with both ultimates\"\n"
        "  Sapphire-no-tensile:\n"
        "    failure_category: brittle\n"
        "    ultimate_compressive_strength_mpa: 2000\n"
        "    elastic_modulus_mpa: 345000\n"
        "    poisson_ratio: 0.29\n"
        "    source: \"Compressive-only brittle record\"\n",
        encoding="utf-8",
    )
    plate_options = [
        "plate",
        "--external-pressure", "1000 psi",
        "--free-radius", "2.5 in",
        "--plate-thickness", "0.625 in",
        "--boundary-condition", "simply_supported",
        "--outside-radius", "3 in",
        "--materials-file", str(database),
        "--json",
    ]
    plate = runner.invoke(
        app, [*plate_options, "--material", "Glass-brittle-both-ultimates"]
    )
    assert plate.exit_code == 0, plate.output
    payload = json.loads(plate.stdout)
    assert payload["material"]["properties_used"] == {
        "elastic_modulus": {"unit": "MPa", "value": 82000.0},
        "failure_category": "brittle",
        "poisson_ratio": 0.206,
        "ultimate_compressive_strength": {"unit": "MPa", "value": 1448.0},
        "ultimate_tensile_strength": {"unit": "MPa", "value": 34.5},
    }
    result = payload["result"]
    assert result["failure_criterion"] == "surface_bending_stress_vs_ultimate_tensile_strength"
    assert result["strength_mpa"] == {"unit": "MPa", "value": 34.5}
    assert result["compressive_strength_mpa"] == {"unit": "MPa", "value": 1448.0}
    seat_mpa = result["seat_bearing_stress_mpa"]["value"]
    assert result["seat_margin"] == pytest.approx(1448.0 / seat_mpa - 1.0)

    # The plate alone needs the tensile strength; the tube runs on the
    # compressive one and reports only what it read.
    missing = runner.invoke(app, [*plate_options, "--material", "Sapphire-no-tensile"])
    error = _error_payload(missing)["error"]
    assert error["code"] == "invalid_material"
    assert "ultimate_tensile_strength" in error["message"]
    tube = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure", "1000 psi",
            "--internal-radius", "3 in",
            "--wall-thickness", "0.25 in",
            "--material", "Glass-brittle-both-ultimates",
            "--materials-file", str(database),
            "--json",
        ],
    )
    assert tube.exit_code == 0, tube.output
    tube_payload = json.loads(tube.stdout)
    assert set(tube_payload["material"]["properties_used"]) == {
        "elastic_modulus",
        "failure_category",
        "poisson_ratio",
        "ultimate_compressive_strength",
    }
    assert tube_payload["result"]["failure_criterion"] == (
        "maximum_hoop_stress_vs_ultimate_compressive_strength"
    )
    assert any("compression" in note for note in tube_payload["result"]["notes"])


def test_explicit_strengths_must_match_the_failure_category() -> None:
    base = [
        "tube",
        "--external-pressure", "1000 psi",
        "--internal-radius", "3 in",
        "--wall-thickness", "0.470 in",
        "--json",
    ]
    wrong_strength = runner.invoke(
        app, [*base, "--failure-category", "ductile_metal", "--working-strength", "20 MPa"]
    )
    error = _error_payload(wrong_strength)["error"]
    assert error["code"] == "invalid_request"
    assert "ductile_metal requires yield_strength" in json.dumps(error["details"])

    foreign_strength = runner.invoke(
        app,
        [
            *base,
            "--failure-category", "plastic",
            "--working-strength", "20 MPa",
            "--yield-strength", "200 MPa",
        ],
    )
    error = _error_payload(foreign_strength)["error"]
    assert error["code"] == "invalid_request"
    assert "plastic does not carry yield_strength" in json.dumps(error["details"])


def test_buckling_requires_no_strength_and_the_stress_models_ask_at_the_point_of_use(
    tmp_path: Path,
) -> None:
    database = tmp_path / "materials.yaml"
    database.write_text(
        "materials:\n"
        "  Elastic-only-plastic:\n"
        "    failure_category: plastic\n"
        "    elastic_modulus_mpa: 2830\n"
        "    poisson_ratio: 0.35\n"
        "    proportional_limit_mpa: 30\n"
        "    source: \"A plastic record with no working strength\"\n",
        encoding="utf-8",
    )
    named = ["--material", "Elastic-only-plastic", "--materials-file", str(database), "--json"]
    geometry = [
        "--external-pressure", "50 psi",
        "--shell-mid-surface-radius", "2.62 in",
        "--wall-thickness", "0.24 in",
        "--unsupported-length", "10 in",
    ]
    smooth = runner.invoke(app, ["smooth-buckling", *geometry, "--load-case", "lateral_only", *named])
    assert smooth.exit_code == 0, smooth.output
    assert "working_strength" not in json.loads(smooth.stdout)["material"]["properties_used"]
    ring = runner.invoke(
        app,
        [
            "ring-shell", *geometry,
            "--ring-spacing", "2 in", "--ring-axial-width", "0.2 in",
            "--ring-radial-height", "0.3 in", "--ring-location", "internal",
            *named,
        ],
    )
    assert ring.exit_code == 0, ring.output

    # The same record cannot run a stress model, and the message names the gap.
    tube = runner.invoke(
        app,
        ["tube", "--external-pressure", "50 psi", "--internal-radius", "2.5 in",
         "--wall-thickness", "0.24 in", *named],
    )
    error = _error_payload(tube)["error"]
    assert error["code"] == "invalid_material"
    assert "plastic requires working_strength" in error["message"]

    # An explicit buckling record needs no strength either, but still rejects a
    # foreign one; the sizing operation's record stays strict.
    explicit = [
        "--failure-category", "ductile_metal", "--elastic-modulus", "70 GPa",
        "--poisson-ratio", "0.33", "--proportional-limit", "200 MPa", "--json",
    ]
    no_yield = runner.invoke(app, ["smooth-buckling", *geometry, "--load-case", "lateral_only", *explicit])
    assert no_yield.exit_code == 0, no_yield.output
    assert json.loads(no_yield.stdout)["result"]["yield_strength_mpa"] == {"unit": "MPa", "value": None}
    foreign = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "ring-shell",
        "inputs": {
            "external_pressure": {"value": 50, "unit": "psi"},
            "shell_mid_surface_radius": {"value": 2.62, "unit": "in"},
            "wall_thickness": {"value": 0.24, "unit": "in"},
            "unsupported_length": {"value": 10, "unit": "in"},
            "ring_spacing": {"value": 2, "unit": "in"},
            "ring_axial_width": {"value": 0.2, "unit": "in"},
            "ring_radial_height": {"value": 0.3, "unit": "in"},
            "ring_location": "internal",
        },
        "material": {
            "type": "explicit",
            "properties": {
                "failure_category": "ductile_metal",
                "working_strength": {"value": 20, "unit": "MPa"},
                "elastic_modulus": {"value": 70, "unit": "GPa"},
                "poisson_ratio": 0.33,
            },
        },
    }
    rejected = runner.invoke(app, ["ring-shell", "--input", "-", "--json"], input=json.dumps(foreign))
    assert _error_payload(rejected)["error"]["code"] == "invalid_request"
    sizing = runner.invoke(
        app,
        [
            "smooth-buckling", "size",
            "--external-pressure", "50 psi", "--internal-radius", "2.5 in",
            "--unsupported-length", "10 in",
            "--wall-thickness-lower", "0.1 in", "--wall-thickness-upper", "0.5 in",
            *explicit,
        ],
    )
    error = _error_payload(sizing)["error"]
    assert error["code"] == "invalid_request"
    assert "ductile_metal requires yield_strength" in json.dumps(error["details"])


def test_buckling_reads_no_strength_and_every_category_sizes(tmp_path: Path) -> None:
    database = tmp_path / "materials.yaml"
    database.write_text(
        "materials:\n"
        "  Acetal:\n"
        "    failure_category: plastic\n"
        "    working_strength_mpa: 20.7\n"
        "    elastic_modulus_mpa: 2830\n"
        "    poisson_ratio: 0.35\n"
        "    proportional_limit_mpa: 30\n"
        "    source: \"Manual acetal record with a working strength raised to 3 ksi\"\n",
        encoding="utf-8",
    )
    named = ["--material", "Acetal", "--materials-file", str(database), "--json"]
    smooth = runner.invoke(
        app,
        [
            "smooth-buckling",
            "--external-pressure", "50 psi",
            "--shell-mid-surface-radius", "2.62 in",
            "--wall-thickness", "0.24 in",
            "--unsupported-length", "10 in",
            "--load-case", "hydrostatic_closed_end",
            *named,
        ],
    )
    assert smooth.exit_code == 0, smooth.output
    smooth_payload = json.loads(smooth.stdout)
    # A plastic has no yield strength to bound the proportional limit with, and
    # nothing else in buckling reads a strength.
    assert smooth_payload["material"]["properties_used"] == {
        "elastic_modulus": {"unit": "MPa", "value": 2830.0},
        "failure_category": "plastic",
        "poisson_ratio": 0.35,
        "proportional_limit": {"unit": "MPa", "value": 30.0},
    }
    assert smooth_payload["result"]["yield_strength_mpa"] == {"unit": "MPa", "value": None}

    # The cylinder sizing operations size the plastic under the shell stress
    # check, whose criterion the selected forward result names.
    tube_size = runner.invoke(
        app,
        [
            "tube", "size",
            "--external-pressure", "50 psi",
            "--internal-radius", "2.5 in",
            "--wall-thickness-lower", "0.1 in",
            "--wall-thickness-upper", "0.5 in",
            *named,
        ],
    )
    assert tube_size.exit_code == 0, tube_size.output
    tube_size_payload = json.loads(tube_size.stdout)
    assert tube_size_payload["sizing"]["declared_check_set"] == ["cylindrical_shell_stress"]
    assert set(tube_size_payload["sizing"]["selected_check_margins"]) == {"cylindrical_shell_stress"}
    assert tube_size_payload["result"]["failure_criterion"] == "maximum_hoop_stress_vs_working_strength"
    assert any("creep" in note for note in tube_size_payload["result"]["notes"])

    # A plastic's working strength is not ordered against its proportional
    # limit, so unlike a ductile metal its shell stress can govern the coupled
    # search: at 3 MPa working strength the governing check crosses over.
    coupled = runner.invoke(
        app,
        [
            "smooth-buckling", "size",
            "--external-pressure", "0.2 MPa",
            "--internal-radius", "100 mm",
            "--unsupported-length", "700 mm",
            "--wall-thickness-lower", "2 mm",
            "--wall-thickness-upper", "9 mm",
            "--minimum-margin", "0.25",
            "--failure-category", "plastic",
            "--working-strength", "3 MPa",
            "--proportional-limit", "30 MPa",
            "--elastic-modulus", "2830 MPa",
            "--poisson-ratio", "0.35",
            "--json",
        ],
    )
    assert coupled.exit_code == 0, coupled.output
    sizing = json.loads(coupled.stdout)["sizing"]
    assert sizing["declared_check_set"] == ["cylindrical_shell_stress", "smooth_cylinder_buckling"]
    assert sizing["selected_governing_check"] == "cylindrical_shell_stress"
    assert sizing["selected_check_margins"]["cylindrical_shell_stress"] == pytest.approx(0.25, abs=1e-6)
    assert [(c["from_state"], c["to_state"]) for c in sizing["governing_check_changes"]] == [
        ("smooth_cylinder_buckling", "cylindrical_shell_stress")
    ]

    # The plate's declared check is category-neutral, so it sizes a plastic.
    plate_size = runner.invoke(
        app,
        [
            "plate", "size",
            "--external-pressure", "20 psi",
            "--free-radius", "2.5 in",
            "--boundary-condition", "simply_supported",
            "--plate-thickness-lower", "0.5 in",
            "--plate-thickness-upper", "1 in",
            "--minimum-margin", "0.5",
            *named,
        ],
    )
    assert plate_size.exit_code == 0, plate_size.output
    assert json.loads(plate_size.stdout)["result"]["failure_criterion"] == (
        "surface_bending_stress_vs_working_strength"
    )


def test_shipped_materials_file_runs_every_record_through_its_models() -> None:
    """Every record in the shipped database resolves and evaluates.

    The database is small enough to exercise whole: each record runs through
    the tube model, whatever its failure category, and the one record that
    carries an ultimate tensile strength also runs through the plate, which is
    the only model that reads it.
    """
    database = MATERIALS_FILE
    named = ["--materials-file", str(database), "--json"]
    records = load_calc_materials(database)
    assert len(records) == 10
    categories = sorted(record.failure_category for record in records.values())
    assert categories == [
        "brittle",
        *["ductile_metal"] * 7,
        *["plastic"] * 2,
    ]
    for name in records:
        tube = runner.invoke(
            app,
            [
                "tube",
                "--external-pressure", "100 psi",
                "--internal-radius", "2 in",
                "--wall-thickness", "0.25 in",
                "--material", name,
                *named,
            ],
        )
        assert tube.exit_code == 0, (name, tube.output)
        assert json.loads(tube.stdout)["result"]["margin"] is not None
    brittle = [
        name
        for name, record in records.items()
        if record.ultimate_tensile_strength_mpa is not None
    ]
    assert brittle == ["Glass-Fused-Silica"]
    for name in brittle:
        plate = runner.invoke(
            app,
            [
                "plate",
                "--external-pressure", "100 psi",
                "--free-radius", "2 in",
                "--plate-thickness", "0.5 in",
                "--boundary-condition", "simply_supported",
                "--material", name,
                *named,
            ],
        )
        assert plate.exit_code == 0, (name, plate.output)
        assert json.loads(plate.stdout)["result"]["failure_criterion"] == (
            "surface_bending_stress_vs_ultimate_tensile_strength"
        )


def test_published_example_failure_pressures_reproduce_at_the_displayed_precision() -> None:
    """Two worked examples of the software this calculator is compared against.

    Both run on explicit properties rather than a database record, because the
    displayed values are only reproducible against the property set that tool
    evaluated. validation/published/ records which tool it is and where the
    values print.
    """
    # Example 1: 6061-T6 at 35 ksi yield, 3 in bore, 1.03 in wall, thick branch.
    example_1 = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure", "4500 psi",
            "--internal-radius", "3 in",
            "--wall-thickness", "1.03 in",
            "--force-thick",
            "--failure-category", "ductile_metal",
            "--yield-strength", "35 ksi",
            "--json",
        ],
    )
    assert example_1.exit_code == 0, example_1.output
    assert magnitude(
        Q_(json.loads(example_1.stdout)["result"]["theoretical_failure_pressure_mpa"]["value"], "MPa"),
        "psi",
    ) == pytest.approx(9009.3, abs=0.5)
    # Example 2: 7075-T6 at 62 ksi yield, 3 in free radius, 1.28 in thick.
    example_2 = runner.invoke(
        app,
        [
            "plate",
            "--external-pressure", "4500 psi",
            "--free-radius", "3 in",
            "--outside-radius", "3.47 in",
            "--plate-thickness", "1.28 in",
            "--boundary-condition", "simply_supported",
            "--failure-category", "ductile_metal",
            "--yield-strength", "62 ksi",
            "--elastic-modulus", "10.3 Mpsi",
            "--poisson-ratio", "0.33",
            "--json",
        ],
    )
    assert example_2.exit_code == 0, example_2.output
    result = json.loads(example_2.stdout)["result"]
    assert magnitude(Q_(result["theoretical_failure_pressure_mpa"]["value"], "MPa"), "psi") == (
        pytest.approx(9038.0, abs=0.5)
    )
    assert magnitude(Q_(result["theoretical_seat_failure_pressure_mpa"]["value"], "MPa"), "psi") == (
        pytest.approx(15_658.0, abs=0.5)
    )


def test_calc_material_loader_ignores_fields_the_models_never_read() -> None:
    material = CalcMaterial.model_validate(
        {
            "density_kg_per_m3": 2700,
            "ultimate_strength_mpa": 310,
            "yield_strength_mpa": 276,
            "failure_category": "ductile_metal",
            "source": "reference properties",
            "some_future_field": "ignored",
        }
    )
    assert not hasattr(material, "ultimate_strength_mpa")
    assert not hasattr(material, "some_future_field")
    assert material.yield_strength_mpa == 276.0
    assert material.elastic_modulus_mpa is None
    # Density is read now that the mass-properties operation consumes it.
    assert material.density_kg_per_m3 == 2700.0


def test_calc_material_still_enforces_the_properties_it_reads() -> None:
    base = {
        "yield_strength_mpa": 276,
        "failure_category": "ductile_metal",
        "source": "reference properties",
    }
    for override in (
        {"yield_strength_mpa": -1},
        {"poisson_ratio": 0.5},
        {"proportional_limit_mpa": 300},
        {"density_kg_per_m3": 0},
        {"density_kg_per_m3": True},
        {"source": "   "},
        {"failure_category": "unobtainium"},
    ):
        with pytest.raises(ValidationError):
            CalcMaterial.model_validate({**base, **override})


def test_material_names_yaml_reads_as_non_strings_are_refused(tmp_path: Path) -> None:
    """An unquoted 316 is a number to YAML and an unquoted on is a boolean.

    A record under such a name could never be found by the string every
    lookup sends, so the loader refuses the file with the quoting fix instead
    of failing each later lookup.
    """
    database = tmp_path / "materials.yaml"
    database.write_text(
        "materials:\n"
        "  316:\n"
        "    failure_category: ductile_metal\n"
        "    source: test record\n"
        "    yield_strength_mpa: 276\n",
        encoding="utf-8",
    )
    result = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure",
            "1 ksi",
            "--internal-radius",
            "3 in",
            "--wall-thickness",
            "0.47 in",
            "--material",
            "316",
            "--materials-file",
            str(database),
            "--json",
        ],
    )
    payload = _error_payload(result)
    assert payload["error"]["code"] == "invalid_material_database"
    assert "quote" in payload["error"]["message"]
    assert "316" in payload["error"]["message"]

    database.write_text(
        "materials:\n"
        "  on:\n"
        "    failure_category: ductile_metal\n"
        "    source: test record\n"
        "    yield_strength_mpa: 276\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="material name True"):
        load_calc_materials(database)
