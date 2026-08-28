"""Forward CLI commands against their kernels: tube, plate, hemisphere, smooth, ring, mass."""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from pv_calc.cli import app
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.hydrostatics import submerged_mass_and_buoyancy
from pv_calc.pressure_vessel import (
    closed_end_tube_stress,
    flat_circular_plate,
    hemispherical_head_external_pressure,
    ring_stiffened_shell_external_pressure,
    smooth_cylinder_external_pressure_buckling,
)
from pv_calc.units import Q_, magnitude

from _cli_helpers import (
    EXAMPLES,
    MATERIALS_FILE,
    _error_payload,
    _json_result,
    _without_quantity_wrappers,
    runner,
)


def test_default_output_is_indented_and_json_is_one_line() -> None:
    args = ["tube", "--input", str(EXAMPLES / "tube_9_0401_ksi.json")]

    indented = runner.invoke(app, args)
    assert indented.exit_code == 0, indented.output
    assert len(indented.stdout.splitlines()) > 1

    compact = runner.invoke(app, [*args, "--json"])
    assert compact.exit_code == 0, compact.output
    assert len(compact.stdout.splitlines()) == 1

    assert json.loads(compact.stdout) == json.loads(indented.stdout)


def test_tube_example_options_file_and_kernel_are_identical() -> None:
    example = EXAMPLES / "tube_9_0401_ksi.json"
    file_result = runner.invoke(app, ["tube", "--input", str(example), "--json"])
    option_args = [
        "tube",
        "--external-pressure",
        "1000psi",
        "--internal-radius",
        "3inch",
        "--wall-thickness",
        "0.470inch",
        "--yield-strength",
        "62ksi",
        "--failure-category",
        "ductile_metal",
        "--material-provenance",
        "Illustrative example value; not a source-verified material database entry.",
        "--json",
    ]
    option_result = runner.invoke(app, option_args)

    assert file_result.exit_code == 0, file_result.output
    assert option_result.exit_code == 0, option_result.output
    file_payload = json.loads(file_result.stdout)
    option_payload = json.loads(option_result.stdout)
    assert file_result.stdout == runner.invoke(app, ["tube", "--input", str(example), "--json"]).stdout
    assert option_payload["result"] == file_payload["result"]

    kernel = closed_end_tube_stress(
        external_pressure_mpa=magnitude(Q_(1000, "psi"), "MPa"),
        internal_radius_mm=magnitude(Q_(3, "inch"), "mm"),
        wall_thickness_mm=magnitude(Q_(0.470, "inch"), "mm"),
        strength_mpa=magnitude(Q_(62, "ksi"), "MPa"),
        material_failure_category="ductile_metal",
    )
    assert _without_quantity_wrappers(file_payload["result"]) == _json_result(kernel)
    assert "assumptions" not in file_payload
    assert file_payload["material"]["properties_used"]["yield_strength"] == {
        "unit": "MPa",
        "value": kernel.strength_mpa,
    }


def test_tube_withholds_displacement_without_both_elastic_properties() -> None:
    example = EXAMPLES / "tube_9_0401_ksi.json"
    result = runner.invoke(app, ["tube", "--input", str(example), "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)["result"]
    assert payload["displacement_status"] == "withheld_missing_elastic_properties"
    assert payload["displacement_validity_violations"] == [
        "elastic_modulus_mpa is required to calculate radial displacement and axial strain",
        "poisson_ratio is required to calculate radial displacement and axial strain",
    ]
    assert payload["axial_strain"] is None
    assert payload["axial_length_change_mm"]["value"] is None
    assert payload["axial_length_mm"]["value"] is None
    assert payload["elastic_modulus_mpa"]["value"] is None
    assert payload["poisson_ratio"] is None
    assert all(
        state["radial_displacement_mm"]["value"] is None
        for state in payload["stress_states"]
    )


def test_tube_named_material_releases_displacement_and_matches_kernel() -> None:
    args = [
        "tube",
        "--external-pressure",
        "2MPa",
        "--internal-radius",
        "100mm",
        "--wall-thickness",
        "5mm",
        "--axial-length",
        "0.5m",
        "--material",
        "Al-6061-T6",
        "--materials-file",
        str(MATERIALS_FILE),
        "--json",
    ]
    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    kernel = closed_end_tube_stress(
        external_pressure_mpa=2.0,
        internal_radius_mm=100.0,
        wall_thickness_mm=5.0,
        strength_mpa=241.0,
        material_failure_category="ductile_metal",
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        axial_length_mm=magnitude(Q_(0.5, "m"), "mm"),
    )
    assert _without_quantity_wrappers(payload["result"]) == _json_result(kernel)
    assert payload["result"]["displacement_status"] == "released"
    assert payload["result"]["displacement_validity_violations"] == []
    assert payload["result"]["axial_strain"] < 0.0
    assert payload["result"]["axial_length_change_mm"]["value"] < 0.0
    assert payload["result"]["stress_states"][0]["radial_displacement_mm"] == {
        "unit": "mm",
        "value": kernel.stress_states[0].radial_displacement_mm,
    }


def test_tube_with_one_elastic_property_names_the_missing_one() -> None:
    """One elastic property is not an error, it is a stated withholding.

    Both properties are optional on the tube contract, so the request stays
    valid; the result reports the modulus it was given and says which property
    it still needs, rather than the CLI restating the kernel's own rule.
    """
    args = [
        "tube",
        "--external-pressure",
        "2MPa",
        "--internal-radius",
        "100mm",
        "--wall-thickness",
        "5mm",
        "--yield-strength",
        "276MPa",
        "--failure-category",
        "ductile_metal",
        "--elastic-modulus",
        "68900MPa",
        "--json",
    ]
    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)["result"]
    assert payload["elastic_modulus_mpa"] == {"unit": "MPa", "value": 68_900.0}
    assert payload["displacement_status"] == "withheld_missing_elastic_properties"
    assert payload["displacement_validity_violations"] == [
        "poisson_ratio is required to calculate radial displacement and axial strain",
    ]


def test_plate_example_stdin_and_kernel_are_identical() -> None:
    example = EXAMPLES / "plate_9_0384_ksi.json"
    result = runner.invoke(
        app,
        ["plate", "--input", "-", "--json"],
        input=example.read_text(encoding="utf-8"),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    kernel = flat_circular_plate(
        external_pressure_mpa=magnitude(Q_(4500, "psi"), "MPa"),
        free_radius_mm=magnitude(Q_(3, "inch"), "mm"),
        plate_thickness_mm=magnitude(Q_(1.280, "inch"), "mm"),
        elastic_modulus_mpa=magnitude(Q_(10_300_000, "psi"), "MPa"),
        poisson_ratio=0.33,
        strength_mpa=magnitude(Q_(62, "ksi"), "MPa"),
        material_failure_category="ductile_metal",
        boundary_condition="simply_supported",
    )
    assert _without_quantity_wrappers(payload["result"]) == _json_result(kernel)
    assert "assumptions" not in payload
    assert payload["material"]["properties_used"]["elastic_modulus"] == {
        "unit": "MPa",
        "value": kernel.elastic_modulus_mpa,
    }
    assert payload["result"]["seat_bearing_stress_mpa"] == {"unit": "MPa", "value": None}


def test_plate_outside_radius_option_and_json_release_the_same_seat_stress() -> None:
    options = [
        "plate",
        "--external-pressure", "4500 psi",
        "--free-radius", "3 in",
        "--plate-thickness", "1.280 in",
        "--boundary-condition", "simply_supported",
        "--outside-radius", "3.47 in",
        "--elastic-modulus", "10300000 psi",
        "--poisson-ratio", "0.33",
        "--yield-strength", "62 ksi",
        "--failure-category", "ductile_metal",
        "--json",
    ]
    from_options = runner.invoke(app, options)
    assert from_options.exit_code == 0, from_options.output
    request = json.loads((EXAMPLES / "plate_9_0384_ksi.json").read_text(encoding="utf-8"))
    request["inputs"]["outside_radius"] = {"value": 3.47, "unit": "in"}
    from_json = runner.invoke(
        app, ["plate", "--input", "-", "--json"], input=json.dumps(request)
    )
    assert from_json.exit_code == 0, from_json.output

    assert json.loads(from_options.stdout)["result"] == json.loads(from_json.stdout)["result"]
    result = json.loads(from_json.stdout)["result"]
    # The comparison software's Example 2 seat failure, displayed as 15,658 psi;
    # validation/published/ records which tool that is and where it prints.
    assert magnitude(
        Q_(result["theoretical_seat_failure_pressure_mpa"]["value"], "MPa"), "psi"
    ) == pytest.approx(15_658.0, abs=0.5)
    assert result["seat_margin"] == pytest.approx(
        62_000.0 / (4_500.0 * 6.94**2 / (6.94**2 - 6.0**2)) - 1.0
    )
    assert result["outside_radius_mm"] == {"unit": "mm", "value": pytest.approx(3.47 * 25.4)}


def test_hemisphere_example_options_file_and_kernel_are_identical() -> None:
    example = EXAMPLES / "hemisphere_subsea_screen.json"
    file_result = runner.invoke(app, ["hemisphere", "--input", str(example), "--json"])
    option_result = runner.invoke(
        app,
        [
            "hemisphere",
            "--external-pressure",
            "6 MPa",
            "--internal-radius",
            "100 mm",
            "--wall-thickness",
            "2.5316455696202533 mm",
            "--elastic-modulus",
            "68900 MPa",
            "--poisson-ratio",
            "0.33",
            "--yield-strength",
            "276 MPa",
            "--proportional-limit",
            "200 MPa",
            "--failure-category",
            "ductile_metal",
            "--material-provenance",
            (
                "Committed equation-verification example only; replace with "
                "source-traceable product-form properties before design use."
            ),
            "--json",
        ],
    )

    assert file_result.exit_code == 0, file_result.output
    assert option_result.exit_code == 0, option_result.output
    file_payload = json.loads(file_result.stdout)
    option_payload = json.loads(option_result.stdout)
    assert option_payload["result"] == file_payload["result"]

    kernel = hemispherical_head_external_pressure(
        external_pressure_mpa=6.0,
        internal_radius_mm=100.0,
        wall_thickness_mm=2.5316455696202533,
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        strength_mpa=276.0,
        proportional_limit_mpa=200.0,
        material_failure_category="ductile_metal",
    )
    assert _without_quantity_wrappers(file_payload["result"]) == _json_result(kernel)
    assert "assumptions" not in file_payload
    assert file_payload["result"]["buckling_capacity_status"] == "released"
    assert file_payload["result"]["displacement_status"] == "released"
    assert file_payload["result"]["stress_states"][0]["radial_displacement_mm"] == {
        "unit": "mm",
        "value": kernel.stress_states[0].radial_displacement_mm,
    }
    assert file_payload["material"]["properties_used"]["proportional_limit"] == {
        "unit": "MPa",
        "value": 200.0,
    }


def test_hemisphere_named_material_without_proportional_limit_withholds_buckling() -> None:
    # SS-316-316L is one of the database records that stores no proportional
    # limit, so the elastic buckling capacity stays withheld for it.
    result = runner.invoke(
        app,
        [
            "hemisphere",
            "--external-pressure",
            "6 MPa",
            "--internal-radius",
            "100 mm",
            "--wall-thickness",
            "2.5316455696202533 mm",
            "--material",
            "SS-316-316L",
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["result"]["buckling_capacity_status"] == "withheld_applicability"
    assert any(
        "proportional_limit" in item
        for item in payload["result"]["buckling_validity_violations"]
    )
    assert payload["material"]["properties_used"]["proportional_limit"] == {
        "unit": "MPa",
        "value": None,
    }


@pytest.mark.parametrize(
    ("filename", "regime", "capacity_status", "expected_pressure"),
    [
        (
            "smooth_buckling_short_nasa.json",
            "short",
            "released",
            1.1048723194661603,
        ),
        (
            "smooth_buckling_moderate_nasa.json",
            "moderate",
            "released",
            0.1338264239601989,
        ),
        (
            "smooth_buckling_long_nasa.json",
            "long",
            "released",
            2.1634615384615383,
        ),
    ],
)
def test_smooth_examples_cli_and_kernel_are_identical(
    filename: str,
    regime: str,
    capacity_status: str,
    expected_pressure: float | None,
) -> None:
    example = EXAMPLES / filename
    raw = json.loads(example.read_text(encoding="utf-8"))
    cli = runner.invoke(app, ["smooth-buckling", "--input", str(example), "--json"])
    assert cli.exit_code == 0, cli.output
    assert cli.stdout == runner.invoke(
        app,
        ["smooth-buckling", "--input", str(example), "--json"],
    ).stdout
    payload = json.loads(cli.stdout)
    inputs = raw["inputs"]
    properties = raw["material"]["properties"]
    kernel = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=magnitude(
            Q_(inputs["external_pressure"]["value"], inputs["external_pressure"]["unit"]),
            "MPa",
        ),
        shell_mid_surface_radius_mm=magnitude(
            Q_(
                inputs["shell_mid_surface_radius"]["value"],
                inputs["shell_mid_surface_radius"]["unit"],
            ),
            "mm",
        ),
        wall_thickness_mm=magnitude(
            Q_(inputs["wall_thickness"]["value"], inputs["wall_thickness"]["unit"]),
            "mm",
        ),
        unsupported_length_mm=magnitude(
            Q_(
                inputs["unsupported_length"]["value"],
                inputs["unsupported_length"]["unit"],
            ),
            "mm",
        ),
        elastic_modulus_mpa=magnitude(
            Q_(properties["elastic_modulus"]["value"], properties["elastic_modulus"]["unit"]),
            "MPa",
        ),
        poisson_ratio=properties["poisson_ratio"],
        yield_strength_mpa=magnitude(
            Q_(properties["yield_strength"]["value"], properties["yield_strength"]["unit"]),
            "MPa",
        ),
        load_case=inputs["load_case"],
        proportional_limit_mpa=magnitude(
            Q_(
                properties["proportional_limit"]["value"],
                properties["proportional_limit"]["unit"],
            ),
            "MPa",
        ),
    )
    assert _without_quantity_wrappers(payload["result"]) == _json_result(kernel)
    assert "assumptions" not in payload
    assert payload["result"]["regime"] == regime
    assert payload["result"]["capacity_status"] == capacity_status
    pressure_value = payload["result"]["correlated_critical_pressure_mpa"]["value"]
    if expected_pressure is None:
        assert pressure_value is None
    else:
        assert pressure_value == pytest.approx(expected_pressure)


@pytest.mark.parametrize(
    ("filename", "expected_adjusted_psi", "expected_lobes"),
    [
        ("ring_shell_dtmb_17_spaces.json", 403.5374002678851, 3),
        ("ring_shell_dtmb_21_spaces.json", 337.673467, 2),
        ("ring_shell_dtmb_23_spaces.json", 284.445374, 2),
        ("ring_shell_dtmb_25_spaces.json", 249.706309, 2),
        ("ring_shell_dtmb_26_spaces.json", 236.968615, 2),
        ("ring_shell_dtmb_27_spaces.json", 226.500267, 2),
        ("ring_shell_dtmb_28_spaces.json", 217.856001, 2),
        ("ring_shell_dtmb_29_spaces.json", 210.686678, 2),
        ("ring_shell_dtmb_31_spaces.json", 199.727069, 2),
        ("ring_shell_dtmb_33_spaces.json", 192.023284, 2),
    ],
)
def test_ring_examples_cli_and_kernel_are_identical(
    filename: str,
    expected_adjusted_psi: float,
    expected_lobes: int,
) -> None:
    example = EXAMPLES / filename
    raw = json.loads(example.read_text(encoding="utf-8"))
    cli = runner.invoke(app, ["ring-shell", "--input", str(example), "--json"])
    assert cli.exit_code == 0, cli.output
    assert cli.stdout == runner.invoke(
        app,
        ["ring-shell", "--input", str(example), "--json"],
    ).stdout
    payload = json.loads(cli.stdout)
    inputs = raw["inputs"]
    properties = raw["material"]["properties"]

    def normalized_input(name: str, unit: str) -> float:
        quantity = inputs[name]
        return magnitude(Q_(quantity["value"], quantity["unit"]), unit)

    kernel = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=normalized_input("external_pressure", "MPa"),
        shell_mid_surface_radius_mm=normalized_input(
            "shell_mid_surface_radius",
            "mm",
        ),
        wall_thickness_mm=normalized_input("wall_thickness", "mm"),
        unsupported_length_mm=normalized_input("unsupported_length", "mm"),
        ring_spacing_mm=normalized_input("ring_spacing", "mm"),
        ring_axial_width_mm=normalized_input("ring_axial_width", "mm"),
        ring_radial_height_mm=normalized_input("ring_radial_height", "mm"),
        ring_location=inputs["ring_location"],
        elastic_modulus_mpa=magnitude(
            Q_(
                properties["elastic_modulus"]["value"],
                properties["elastic_modulus"]["unit"],
            ),
            "MPa",
        ),
        poisson_ratio=properties["poisson_ratio"],
        yield_strength_mpa=magnitude(
            Q_(
                properties["yield_strength"]["value"],
                properties["yield_strength"]["unit"],
            ),
            "MPa",
        ),
    )
    assert _without_quantity_wrappers(payload["result"]) == _json_result(kernel)
    assert "assumptions" not in payload
    assert payload["result"]["capacity_status"] == "advisory"
    global_result = payload["result"]["global_with_ring_torsion"]
    assert magnitude(
        Q_(
            global_result["adjusted_critical_pressure_mpa"]["value"],
            global_result["adjusted_critical_pressure_mpa"]["unit"],
        ),
        "psi",
    ) == pytest.approx(expected_adjusted_psi, abs=1e-6)
    assert global_result["critical_circumferential_lobes_n"] == expected_lobes


def test_ring_cli_withholds_internal_rectangle_that_closes_the_bore(tmp_path) -> None:
    raw = json.loads(
        (EXAMPLES / "ring_shell_dtmb_17_spaces.json").read_text(encoding="utf-8")
    )
    raw["inputs"]["ring_location"] = "internal"
    raw["inputs"]["ring_radial_height"] = {"value": 150.0, "unit": "mm"}
    request_path = tmp_path / "invalid_internal_ring.json"
    request_path.write_text(json.dumps(raw), encoding="utf-8")

    cli = runner.invoke(app, ["ring-shell", "--input", str(request_path), "--json"])

    assert cli.exit_code == 0, cli.output
    result = json.loads(cli.stdout)["result"]
    assert result["capacity_status"] == "withheld_invalid_applicability"
    assert result["advisory_governing_pressure_mpa"]["value"] is None
    assert any("positive clear bore" in item for item in result["validity_violations"])


def test_ring_options_and_file_contract_are_identical() -> None:
    example = EXAMPLES / "ring_shell_dtmb_17_spaces.json"
    from_file = runner.invoke(app, ["ring-shell", "--input", str(example), "--json"])
    from_options = runner.invoke(
        app,
        [
            "ring-shell",
            "--external-pressure",
            "473 psi",
            "--shell-mid-surface-radius",
            "4.0765 inch",
            "--wall-thickness",
            "0.035 inch",
            "--unsupported-length",
            "19.584 inch",
            "--ring-spacing",
            "1.152 inch",
            "--ring-axial-width",
            "0.086 inch",
            "--ring-radial-height",
            "0.169 inch",
            "--ring-location",
            "external",
            "--elastic-modulus",
            "30000000 psi",
            "--poisson-ratio",
            "0.3",
            "--yield-strength",
            "85000 psi",
            "--failure-category",
            "ductile_metal",
            "--material-provenance",
            (
                "DTMB Report 1324 pp. 3 and 10: nominal E and Poisson ratio; "
                "85,000 psi yield strength; no proportional limit reported."
            ),
            "--json",
        ],
    )

    assert from_file.exit_code == 0, from_file.output
    assert from_options.exit_code == 0, from_options.output
    assert json.loads(from_file.stdout)["result"] == json.loads(from_options.stdout)["result"]


def test_smooth_options_and_file_contract_are_identical() -> None:
    example = EXAMPLES / "smooth_buckling_moderate_nasa.json"
    from_file = runner.invoke(app, ["smooth-buckling", "--input", str(example), "--json"])
    from_options = runner.invoke(
        app,
        [
            "smooth-buckling",
            "--external-pressure",
            "0.01 MPa",
            "--shell-mid-surface-radius",
            "500 mm",
            "--wall-thickness",
            "5 mm",
            "--unsupported-length",
            "1800 mm",
            "--load-case",
            "hydrostatic_closed_end",
            "--elastic-modulus",
            "70000 MPa",
            "--poisson-ratio",
            "0.3",
            "--yield-strength",
            "250 MPa",
            "--proportional-limit",
            "200 MPa",
            "--failure-category",
            "ductile_metal",
            "--material-provenance",
            "Independent calculation from NASA/SP-8007-2020/REV 2 Eqs. 23-24 and 28.",
            "--json",
        ],
    )
    assert from_file.exit_code == from_options.exit_code == 0
    assert json.loads(from_file.stdout)["result"] == json.loads(from_options.stdout)["result"]


def test_smooth_named_material_without_proportional_limit_withholds_capacity() -> None:
    # SS-316-316L is one of the database records that stores no proportional
    # limit, so the correlated capacity stays withheld for it.
    result = runner.invoke(
        app,
        [
            "smooth-buckling",
            "--external-pressure",
            "0.01 MPa",
            "--shell-mid-surface-radius",
            "500 mm",
            "--wall-thickness",
            "5 mm",
            "--unsupported-length",
            "1800 mm",
            "--load-case",
            "hydrostatic_closed_end",
            "--material",
            "SS-316-316L",
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["result"]["capacity_status"] == "withheld_applicability"
    assert payload["material"]["properties_used"]["proportional_limit"] == {
        "unit": "MPa",
        "value": None,
    }
    assert any(
        "proportional_limit_mpa is required" in item
        for item in payload["result"]["validity_violations"]
    )


def test_smooth_requires_an_explicit_pressure_load_case() -> None:
    result = runner.invoke(
        app,
        [
            "smooth-buckling",
            "--external-pressure",
            "1 MPa",
            "--shell-mid-surface-radius",
            "500 mm",
            "--wall-thickness",
            "5 mm",
            "--unsupported-length",
            "1800 mm",
            "--material",
            "Al-6061-T6",
            "--json",
        ],
    )
    assert _error_payload(result)["error"]["code"] == "invalid_request"


MASS_PROPERTIES_EXAMPLE_OPTIONS = [
    "mass-properties",
    "--solid-volume",
    "2.5 L",
    "--displaced-volume",
    "6.0 L",
    "--fluid-density",
    "1025 kg/m^3",
    "--gravity",
    "9.81 m/s^2",
]


def test_mass_properties_named_and_explicit_density_agree_and_match_kernel() -> None:
    example = EXAMPLES / "mass_properties_aluminium_housing.json"
    file_result = runner.invoke(app, ["mass-properties", "--input", str(example), "--json"])
    named_result = runner.invoke(
        app,
        [
            *MASS_PROPERTIES_EXAMPLE_OPTIONS,
            "--material",
            "Al-6061-T6",
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )

    assert file_result.exit_code == 0, file_result.output
    assert named_result.exit_code == 0, named_result.output
    file_payload = json.loads(file_result.stdout)
    named_payload = json.loads(named_result.stdout)
    # The example carries the same density explicitly that the named record
    # stores, so the two material sources must produce identical arithmetic.
    assert named_payload["result"] == file_payload["result"]

    kernel = submerged_mass_and_buoyancy(
        solid_volume_m3=magnitude(Q_(2.5, "L"), "m^3"),
        displaced_volume_m3=magnitude(Q_(6.0, "L"), "m^3"),
        material_density_kg_per_m3=2700.0,
        fluid_density_kg_per_m3=1025.0,
        gravity_m_per_s2=9.81,
    )
    assert _without_quantity_wrappers(file_payload["result"]) == _json_result(kernel)
    assert "assumptions" not in file_payload
    assert file_payload["calculation_source"]["function"] == (
        "pv_calc.hydrostatics.submerged_mass_and_buoyancy"
    )
    assert file_payload["material"]["source"]["type"] == "explicit"
    named_source = named_payload["material"]["source"]
    assert named_source["type"] == "named"
    assert named_source["name"] == "Al-6061-T6"
    assert named_source["database"] == str(MATERIALS_FILE)
    assert named_source["provenance"].startswith(
        "ASTM B221 and ASTM B241 specification minimums"
    )
    assert named_payload["material"]["properties_used"] == {
        "density": {"unit": "kg/m^3", "value": 2700.0}
    }


def test_mass_properties_normalizes_every_input_unit() -> None:
    si = runner.invoke(
        app,
        [*MASS_PROPERTIES_EXAMPLE_OPTIONS, "--material-density", "2700 kg/m^3", "--json"],
    )
    mixed = runner.invoke(
        app,
        [
            "mass-properties",
            "--solid-volume",
            "2500000 mm^3",
            "--displaced-volume",
            "6000000 mm^3",
            "--fluid-density",
            "1.025 g/cm^3",
            "--gravity",
            "981 cm/s^2",
            "--material-density",
            "2.7 g/cm^3",
            "--json",
        ],
    )

    assert si.exit_code == 0, si.output
    assert mixed.exit_code == 0, mixed.output
    si_result = json.loads(si.stdout)["result"]
    mixed_result = json.loads(mixed.stdout)["result"]
    for name, si_value in si_result.items():
        if not isinstance(si_value, dict):
            continue
        assert mixed_result[name]["unit"] == si_value["unit"]
        assert mixed_result[name]["value"] == pytest.approx(si_value["value"], rel=1e-12)
    assert si_result["structural_air_mass_kg"]["value"] == pytest.approx(6.75, rel=1e-12)
    assert si_result["displaced_fluid_mass_kg"]["value"] == pytest.approx(6.15, rel=1e-12)
    assert si_result["net_submerged_mass_kg"]["value"] == pytest.approx(0.6, rel=1e-12)
    assert si_result["buoyant_force_n"]["value"] == pytest.approx(6.15 * 9.81, rel=1e-12)


def test_mass_properties_accepts_equal_volumes_after_mixed_unit_conversion() -> None:
    result = runner.invoke(
        app,
        [
            "mass-properties",
            "--solid-volume",
            "1 L",
            "--displaced-volume",
            "1000000 mm^3",
            "--fluid-density",
            "1000 kg/m^3",
            "--gravity",
            "10 m/s^2",
            "--material-density",
            "1000 kg/m^3",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["result"]["net_submerged_mass_kg"]["value"] == (
        pytest.approx(0.0, abs=1.0e-15)
    )


def test_mass_properties_named_stress_only_record_is_invalid_material(tmp_path: Path) -> None:
    """A stress-only record stays valid everywhere else and fails only here."""
    stress_only = tmp_path / "materials.yaml"
    stress_only.write_text(
        "materials:\n"
        "  Al-6061-T6:\n"
        "    yield_strength_mpa: 276\n"
        "    failure_category: ductile_metal\n"
        "    source: \"Yield-only calculator property set\"\n",
        encoding="utf-8",
    )
    named = ["--material", "Al-6061-T6", "--materials-file", str(stress_only), "--json"]

    mass = runner.invoke(app, [*MASS_PROPERTIES_EXAMPLE_OPTIONS, *named])
    assert _error_payload(mass)["error"]["code"] == "invalid_material"

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


def test_density_only_named_record_is_valid_only_for_mass_properties(
    tmp_path: Path,
) -> None:
    database = tmp_path / "materials.yaml"
    database.write_text(
        "materials:\n"
        "  Ballast:\n"
        "    density_kg_per_m3: 7800\n"
        "    source: \"Density-only mass record\"\n",
        encoding="utf-8",
    )
    named = ["--material", "Ballast", "--materials-file", str(database), "--json"]

    mass = runner.invoke(app, [*MASS_PROPERTIES_EXAMPLE_OPTIONS, *named])
    assert mass.exit_code == 0, mass.output
    assert json.loads(mass.stdout)["material"]["properties_used"] == {
        "density": {"unit": "kg/m^3", "value": 7800.0}
    }

    tube = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure",
            "1 MPa",
            "--internal-radius",
            "75 mm",
            "--wall-thickness",
            "5 mm",
            *named,
        ],
    )
    assert _error_payload(tube)["error"]["code"] == "invalid_material"


def test_mass_properties_material_source_rules_match_the_other_models() -> None:
    conflict = runner.invoke(
        app,
        [
            *MASS_PROPERTIES_EXAMPLE_OPTIONS,
            "--material",
            "Al-6061-T6",
            "--materials-file",
            str(MATERIALS_FILE),
            "--material-density",
            "2700 kg/m^3",
            "--json",
        ],
    )
    assert _error_payload(conflict)["error"]["code"] == "material_source_conflict"

    missing = runner.invoke(app, [*MASS_PROPERTIES_EXAMPLE_OPTIONS, "--json"])
    assert _error_payload(missing)["error"]["code"] == "missing_material_source"

    no_database = runner.invoke(
        app,
        [*MASS_PROPERTIES_EXAMPLE_OPTIONS, "--material", "Al-6061-T6", "--json"],
    )
    assert _error_payload(no_database)["error"]["code"] == "missing_materials_file"

    with_file = runner.invoke(
        app,
        [
            "mass-properties",
            "--input",
            str(EXAMPLES / "mass_properties_aluminium_housing.json"),
            "--solid-volume",
            "2.5 L",
            "--json",
        ],
    )
    conflict_error = _error_payload(with_file)["error"]
    assert conflict_error["code"] == "input_source_conflict"
    # Details echo the CLI spelling the caller typed, not a parameter name.
    assert conflict_error["details"] == [{"conflicting_options": ["--solid-volume"]}]


LB_PER_KG = 2.2046226218
SEAWATER_64_LB_PER_FT3 = ["--fluid-density", "64 lb/ft^3", "--gravity", "9.80665 m/s^2"]


def test_submergence_adds_the_manual_tube_weights_and_failure_depths() -> None:
    """The comparison software's Example 1: 6061-T6, 6.00 in I.D., 1.03 in wall,
    24 in long, weight in air 53.503 lb and in water 8.1464 lb (printed p. 16),
    that manual's seawater being 64 lb/ft^3 to its displayed precision.

    validation/published/ records which tool the displayed weights come from."""
    options = [
        "tube",
        "--external-pressure", "4500 psi",
        "--internal-radius", "3 in",
        "--wall-thickness", "1.03 in",
        "--axial-length", "24 in",
        "--force-thick",
        "--failure-category", "ductile_metal",
        "--yield-strength", "35 ksi",
        "--material-density", "0.098 lb/in^3",
        *SEAWATER_64_LB_PER_FT3,
        "--json",
    ]
    from_options = runner.invoke(app, options)
    assert from_options.exit_code == 0, from_options.output
    payload = json.loads(from_options.stdout)

    request = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "tube",
        "inputs": {
            "external_pressure": {"value": 4500, "unit": "psi"},
            "internal_radius": {"value": 3, "unit": "in"},
            "wall_thickness": {"value": 1.03, "unit": "in"},
            "axial_length": {"value": 24, "unit": "in"},
            "force_thick": True,
            "submergence": {
                "fluid_density": {"value": 64, "unit": "lb/ft^3"},
                "gravity": {"value": 9.80665, "unit": "m/s^2"},
            },
        },
        "material": {
            "type": "explicit",
            "properties": {
                "failure_category": "ductile_metal",
                "yield_strength": {"value": 35, "unit": "ksi"},
                "density": {"value": 0.098, "unit": "lb/in^3"},
            },
        },
    }
    from_json = runner.invoke(app, ["tube", "--input", "-", "--json"], input=json.dumps(request))
    assert from_json.exit_code == 0, from_json.output
    assert json.loads(from_json.stdout) == payload

    mass = payload["mass_properties"]
    assert mass["model"] == "mass-properties"
    assert mass["result"]["structural_air_mass_kg"]["value"] * LB_PER_KG == pytest.approx(
        53.503, abs=0.0005
    )
    assert mass["result"]["net_submerged_mass_kg"]["value"] * LB_PER_KG == pytest.approx(
        8.1464, abs=0.005
    )
    assert mass["material"]["properties_used"]["density"]["value"] == pytest.approx(
        0.098 * 27679.9047, rel=1.0e-6
    )
    assert "weightless closures" in mass["volume_basis"]
    # The block is the standalone operation on the closed tube's own volumes.
    solid_in3 = math.pi * (4.03**2 - 3.0**2) * 24.0
    displaced_in3 = math.pi * 4.03**2 * 24.0
    standalone = runner.invoke(
        app,
        [
            "mass-properties",
            "--solid-volume", f"{solid_in3} in^3",
            "--displaced-volume", f"{displaced_in3} in^3",
            "--material-density", "0.098 lb/in^3",
            *SEAWATER_64_LB_PER_FT3,
            "--json",
        ],
    )
    assert standalone.exit_code == 0, standalone.output
    for name in ("structural_air_mass_kg", "displaced_fluid_mass_kg", "net_submerged_mass_kg"):
        assert mass["result"][name]["value"] == pytest.approx(
            json.loads(standalone.stdout)["result"][name]["value"], rel=1.0e-12
        )

    depths = payload["failure_depths"]
    rho = 64.0 * 0.45359237 / 0.3048**3
    failure_mpa = payload["result"]["theoretical_failure_pressure_mpa"]["value"]
    assert set(depths["depths"]) == {"theoretical_failure_pressure_mpa"}
    assert depths["depths"]["theoretical_failure_pressure_mpa"] == {
        "unit": "m",
        "value": pytest.approx(failure_mpa * 1.0e6 / (rho * 9.80665)),
    }
    assert depths["basis"].startswith("h = p / (rho * g)")


def test_submergence_reproduces_the_manual_plate_hemisphere_and_report_weights() -> None:
    plate = runner.invoke(
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
            "--material-density", "0.101 lb/in^3",
            *SEAWATER_64_LB_PER_FT3,
            "--json",
        ],
    )
    assert plate.exit_code == 0, plate.output
    plate_payload = json.loads(plate.stdout)
    # Example 2 (printed p. 21): weight in air 4.89 lb, in water 3.10 lb.
    plate_mass = plate_payload["mass_properties"]["result"]
    assert plate_mass["structural_air_mass_kg"]["value"] * LB_PER_KG == pytest.approx(4.89, abs=0.005)
    assert plate_mass["net_submerged_mass_kg"]["value"] * LB_PER_KG == pytest.approx(3.10, abs=0.005)
    assert plate_mass["solid_volume_m3"]["value"] == plate_mass["displaced_volume_m3"]["value"]
    assert set(plate_payload["failure_depths"]["depths"]) == {
        "theoretical_failure_pressure_mpa",
        "theoretical_seat_failure_pressure_mpa",
    }

    hemisphere = runner.invoke(
        app,
        [
            "hemisphere",
            "--external-pressure", "1000 psi",
            "--internal-radius", "1.75 in",
            "--wall-thickness", "0.25 in",
            "--failure-category", "ductile_metal",
            "--yield-strength", "35 ksi",
            "--elastic-modulus", "9.9 Mpsi",
            "--poisson-ratio", "0.33",
            "--material-density", "0.098 lb/in^3",
            *SEAWATER_64_LB_PER_FT3,
            "--json",
        ],
    )
    assert hemisphere.exit_code == 0, hemisphere.output
    hemisphere_payload = json.loads(hemisphere.stdout)
    # The manual's hemispherical-endcap dialog: 0.54199 lb in air (printed p. 64).
    assert hemisphere_payload["mass_properties"]["result"]["structural_air_mass_kg"][
        "value"
    ] * LB_PER_KG == pytest.approx(0.54199, abs=0.000005)
    hemisphere_depths = hemisphere_payload["failure_depths"]["depths"]
    assert hemisphere_depths["released_buckling_pressure_mpa"] == {"unit": "m", "value": None}
    assert hemisphere_depths["roark_probable_minimum_pressure_mpa"]["value"] > 0

    report = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure", "100 psi",
            "--internal-radius", "1.719 in",
            "--wall-thickness", "0.531 in",
            "--axial-length", "10 in",
            "--failure-category", "plastic",
            "--working-strength", "6 ksi",
            "--material-density", "0.0476 lb/in^3",
            *SEAWATER_64_LB_PER_FT3,
            "--json",
        ],
    )
    assert report.exit_code == 0, report.output
    report_mass = json.loads(report.stdout)["mass_properties"]["result"]
    # The report sample (printed p. 76): 3.1516 lb in air, -2.7393 lb in water.
    assert report_mass["structural_air_mass_kg"]["value"] * LB_PER_KG == pytest.approx(
        3.1516, abs=0.00005
    )
    assert report_mass["net_submerged_mass_kg"]["value"] * LB_PER_KG == pytest.approx(
        -2.7393, abs=0.0015
    )


def test_submergence_names_the_geometry_and_density_it_needs() -> None:
    base = [
        "tube",
        "--external-pressure", "1000 psi",
        "--internal-radius", "3 in",
        "--wall-thickness", "0.25 in",
        "--failure-category", "ductile_metal",
        "--yield-strength", "35 ksi",
        *SEAWATER_64_LB_PER_FT3,
        "--json",
    ]
    no_length = runner.invoke(app, [*base, "--material-density", "2700 kg/m^3"])
    error = _error_payload(no_length)["error"]
    assert error["code"] == "invalid_request"
    assert "inputs.axial_length" in error["message"]

    no_density = runner.invoke(app, [*base, "--axial-length", "10 in"])
    error = _error_payload(no_density)["error"]
    assert error["code"] == "invalid_material"
    assert "material.properties.density" in error["message"]

    # Without the block, no explicit density is read and no block is emitted.
    plain = runner.invoke(app, [*base[:-5], "--json"])
    assert plain.exit_code == 0, plain.output
    payload = json.loads(plain.stdout)
    assert "mass_properties" not in payload and "failure_depths" not in payload

    smooth = runner.invoke(
        app,
        [
            "smooth-buckling",
            "--external-pressure", "50 psi",
            "--shell-mid-surface-radius", "2.62 in",
            "--wall-thickness", "0.24 in",
            "--unsupported-length", "10 in",
            "--load-case", "hydrostatic_closed_end",
            "--failure-category", "plastic",
            "--elastic-modulus", "0.41 Mpsi",
            "--poisson-ratio", "0.4",
            "--material-density", "0.0526 lb/in^3",
            *SEAWATER_64_LB_PER_FT3,
            "--json",
        ],
    )
    assert smooth.exit_code == 0, smooth.output
    smooth_payload = json.loads(smooth.stdout)
    depths = smooth_payload["failure_depths"]["depths"]
    assert depths["correlated_critical_pressure_mpa"] == {"unit": "m", "value": None}
    # Example 4's displayed 266.60 psi thin-wall buckling at 64 lb/ft^3 is 599.9 ft.
    assert depths["roark_probable_minimum_pressure_mpa"]["value"] / 0.3048 == pytest.approx(
        266.60 * 6894.757 / (64.0 * 0.45359237 / 0.3048**3 * 9.80665) / 0.3048, rel=1.0e-4
    )
    assert "mid-surface radius" in smooth_payload["mass_properties"]["volume_basis"]
