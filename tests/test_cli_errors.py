"""The CLI error contract, malformed input, help, and version."""

from __future__ import annotations

import json
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

import pytest

from pv_calc import __version__
from pv_calc.cli import app
from pv_calc.contracts import CALC_SCHEMA_VERSION

from _cli_helpers import (
    EXAMPLES,
    MATERIALS_FILE,
    _error_payload,
    runner,
)


def test_engineering_failure_and_invalid_envelope_are_successful_calculations() -> None:
    tube_request = json.loads((EXAMPLES / "tube_9_0401_ksi.json").read_text(encoding="utf-8"))
    tube_request["inputs"]["external_pressure"]["value"] = 20_000
    failed = runner.invoke(app, ["tube", "--input", "-", "--json"], input=json.dumps(tube_request))
    assert failed.exit_code == 0, failed.output
    assert json.loads(failed.stdout)["result"]["margin"] < 0

    plate_request = json.loads((EXAMPLES / "plate_9_0384_ksi.json").read_text(encoding="utf-8"))
    plate_request["inputs"]["plate_thickness"]["value"] = 2
    invalid = runner.invoke(app, ["plate", "--input", "-", "--json"], input=json.dumps(plate_request))
    assert invalid.exit_code == 0, invalid.output
    assert json.loads(invalid.stdout)["result"]["validity_violations"]

    hemisphere_request = json.loads(
        (EXAMPLES / "hemisphere_subsea_screen.json").read_text(encoding="utf-8")
    )
    hemisphere_request["inputs"]["external_pressure"]["value"] = 20.0
    hemisphere_failure = runner.invoke(
        app,
        ["hemisphere", "--input", "-", "--json"],
        input=json.dumps(hemisphere_request),
    )
    assert hemisphere_failure.exit_code == 0, hemisphere_failure.output
    assert json.loads(hemisphere_failure.stdout)["result"]["stress_margin"] < 0

    hemisphere_request["inputs"]["external_pressure"]["value"] = 6.0
    hemisphere_request["inputs"]["wall_thickness"]["value"] = 10.0
    hemisphere_invalid = runner.invoke(
        app,
        ["hemisphere", "--input", "-", "--json"],
        input=json.dumps(hemisphere_request),
    )
    assert hemisphere_invalid.exit_code == 0, hemisphere_invalid.output
    assert json.loads(hemisphere_invalid.stdout)["result"][
        "buckling_validity_violations"
    ]


@pytest.mark.parametrize(
    ("args", "stdin", "error_code"),
    [
        (
            [
                "tube",
                "--external-pressure",
                "1MPa",
                "--internal-radius",
                "10mm",
                "--wall-thickness",
                "1mm",
                "--json",
            ],
            None,
            "missing_material_source",
        ),
        (
            [
                "tube",
                "--external-pressure",
                "1MPa",
                "--internal-radius",
                "10mm",
                "--wall-thickness",
                "1mm",
                "--material",
                "Al-6061-T6",
                "--yield-strength",
                "200MPa",
                "--failure-category",
                "ductile_metal",
                "--material-provenance",
                "conflicting record",
                "--json",
            ],
            None,
            "material_source_conflict",
        ),
        (
            [
                "tube",
                "--external-pressure",
                "1mm",
                "--internal-radius",
                "10mm",
                "--wall-thickness",
                "1mm",
                "--yield-strength",
                "200MPa",
                "--failure-category",
                "ductile_metal",
                "--material-provenance",
                "test record",
                "--json",
            ],
            None,
            "incompatible_unit",
        ),
        (
            [
                "tube",
                "--external-pressure",
                "1 **",
                "--internal-radius",
                "10mm",
                "--wall-thickness",
                "1mm",
                "--yield-strength",
                "200MPa",
                "--failure-category",
                "ductile_metal",
                "--material-provenance",
                "test record",
                "--json",
            ],
            None,
            "invalid_quantity",
        ),
    ],
)
def test_malformed_or_unevaluable_input_returns_structured_error(
    args: list[str], stdin: str | None, error_code: str
) -> None:
    result = runner.invoke(app, args, input=stdin)
    payload = _error_payload(result)
    assert payload["schema_version"] == CALC_SCHEMA_VERSION
    assert payload["error"]["code"] == error_code
    assert payload["error"]["message"]


@pytest.mark.parametrize(
    ("args", "stdin", "error_code", "message_fragment"),
    [
        (
            [
                "tube",
                "--external-pressure",
                "1 mm",
                "--internal-radius",
                "10 mm",
                "--wall-thickness",
                "1 mm",
                "--yield-strength",
                "200 MPa",
                "--failure-category",
                "ductile_metal",
                "--material-provenance",
                "test record",
                "--json",
            ],
            None,
            "incompatible_unit",
            "must have units compatible with MPa",
        ),
        (
            [
                "tube",
                "--external-pressure",
                "1 MPa",
                "--internal-radius",
                "10 mm",
                "--yield-strength",
                "200 MPa",
                "--failure-category",
                "ductile_metal",
                "--material-provenance",
                "test record",
                "--json",
            ],
            None,
            "invalid_request",
            "inputs.wall_thickness",
        ),
        (
            [
                "tube",
                "--external-pressure",
                "1 MPa",
                "--internal-radius",
                "10 mm",
                "--wall-thickness",
                "1 mm",
                "--material",
                "not-a-material",
                "--materials-file",
                str(MATERIALS_FILE),
                "--json",
            ],
            None,
            "unknown_material",
            "not present",
        ),
        (
            [
                "tube",
                "--external-pressure",
                "1 MPa",
                "--internal-radius",
                "10 mm",
                "--wall-thickness",
                "1 mm",
                "--material",
                "Al-6061-T6",
                "--json",
            ],
            None,
            "missing_materials_file",
            "requires --materials-file",
        ),
        (
            ["tube", "--input", "-", "--json"],
            "{bad",
            "invalid_json",
            "invalid JSON at line 1",
        ),
        (
            [
                "tube",
                "--external-pressure",
                "-1 MPa",
                "--internal-radius",
                "10 mm",
                "--wall-thickness",
                "1 mm",
                "--yield-strength",
                "200 MPa",
                "--failure-category",
                "ductile_metal",
                "--material-provenance",
                "test record",
                "--json",
            ],
            None,
            "unevaluable_model",
            "external_pressure_mpa must be finite and positive",
        ),
        (
            [
                "mass-properties",
                "--solid-volume",
                "2.5 L",
                "--displaced-volume",
                "6.0 L",
                "--fluid-density",
                "1025 kg/m^3",
                "--gravity",
                "9.81 MPa",
                "--material-density",
                "2700 kg/m^3",
                "--json",
            ],
            None,
            "incompatible_unit",
            "inputs.gravity must have units compatible with m/s^2",
        ),
        (
            [
                "mass-properties",
                "--solid-volume",
                "7 L",
                "--displaced-volume",
                "6.0 L",
                "--fluid-density",
                "1025 kg/m^3",
                "--gravity",
                "9.81 m/s^2",
                "--material-density",
                "2700 kg/m^3",
                "--json",
            ],
            None,
            "unevaluable_model",
            "inputs.solid_volume must not exceed inputs.displaced_volume",
        ),
        (
            [
                "mass-properties",
                "--solid-volume",
                "2.5 L",
                "--displaced-volume",
                "6.0 L",
                "--fluid-density",
                "1025 kg/m^3",
                "--gravity",
                "-9.81 m/s^2",
                "--material-density",
                "2700 kg/m^3",
                "--json",
            ],
            None,
            "unevaluable_model",
            "gravity_m_per_s2 must be finite and positive",
        ),
        (
            # A drawing-style upper-case unit token; the message names it.
            [
                "tube",
                "--external-pressure",
                "1000 PSI",
                "--internal-radius",
                "3 in",
                "--wall-thickness",
                "0.47 in",
                "--yield-strength",
                "62 ksi",
                "--failure-category",
                "ductile_metal",
                "--json",
            ],
            None,
            "invalid_quantity",
            "external_pressure must be a scalar value with an explicit unit: 'PSI' is not defined",
        ),
        (
            # An option before the size subcommand would be silently dropped.
            [
                "tube",
                "--external-pressure",
                "99999 psi",
                "size",
                "--external-pressure",
                "7 ksi",
                "--json",
            ],
            None,
            "invalid_request",
            "options must follow the size subcommand",
        ),
    ],
)
def test_common_cli_errors_are_clear_one_line_failures(
    args: list[str],
    stdin: str | None,
    error_code: str,
    message_fragment: str,
) -> None:
    result = runner.invoke(app, args, input=stdin)

    payload = _error_payload(result)
    assert payload["error"]["code"] == error_code
    assert message_fragment in payload["error"]["message"]
    assert len(result.stderr.splitlines()) == 1


def _tube_with_wall_thickness(wall_thickness: str) -> list[str]:
    return [
        "tube",
        "--external-pressure",
        "1 MPa",
        "--internal-radius",
        "76.2 mm",
        "--wall-thickness",
        wall_thickness,
        "--yield-strength",
        "200 MPa",
        "--failure-category",
        "ductile_metal",
        "--json",
    ]


@pytest.mark.parametrize(
    ("wall_thickness", "offending_token"),
    [
        # pint's expression parser deletes the comma and reads 25 mm.
        ("2,5 mm", "'2,5 mm'"),
        # The digit-group reading happens to be right, so it cannot be told
        # apart from the decimal-comma one; both are refused.
        ("1,000 mm", "'1,000 mm'"),
        # Implicit multiplication: pint reads 1 * 000 * mm, which is 0 mm.
        ("1 000 mm", "'1 000 mm'"),
        # U+2212, what a minus sign pastes as from a PDF: pint drops it and
        # reads +5 mm, defeating the downstream positivity check.
        ("−5 mm", "'\\u22125 mm'"),
        # A unit with no number at all: pint reads one of it.
        ("mm", "'mm'"),
        # Trailing token: pint multiplies and reads 2 mm.
        ("1 mm 2", "'1 mm 2'"),
        # A pasted list: pint concatenates the digits and reads 12 mm.
        ("[1,2] mm", "'[1,2] mm'"),
        # A drawing fraction, which pint evaluates to 0.5 in.
        ("1/2 in", "'1/2 in'"),
        # An unbalanced bracket used to escape as a tokenizer traceback.
        ("1 mm)", "'1 mm)'"),
        # pint refuses a unit-half scale factor only when it is not 1, so every
        # form below reached it as a scale of exactly 1 and quietly dropped the
        # smuggled digits: '1,1 mm' evaluated to 1 mm, discarding the tenth.
        ("1,1 mm", "'1,1 mm'"),
        ("0,1 in", "'0,1 in'"),
        ("76,1 mm", "'76,1 mm'"),
        ("1,1e0 mm", "'1,1e0 mm'"),
        ("1, 1 mm", "'1, 1 mm'"),
        ("1,1*mm", "'1,1*mm'"),
        ("1 1 mm", "'1 1 mm'"),
        ("1 1.0 mm", "'1 1.0 mm'"),
        ("1 (1) mm", "'1 (1) mm'"),
        ("1 2/2 mm", "'1 2/2 mm'"),
        ("1 2**0 mm", "'1 2**0 mm'"),
        ("1 +1 mm", "'1 +1 mm'"),
        # A parenthesized exponent is rejected with the rest, not special-cased.
        ("1 m**(2)", "'1 m**(2)'"),
        ("1;1 mm", "'1;1 mm'"),
        ("1|1 mm", "'1|1 mm'"),
        # A zero or vanishing exponent, which pint fails to apply.
        ("1 mm^0", "'1 mm^0'"),
        ("1 mm^(1-1)", "'1 mm^(1-1)'"),
        ("1 mm/0", "'1 mm/0'"),
        ("1 mm//0", "'1 mm//0'"),
        ("1 psi^999999999", "'1 psi^999999999'"),
        # Unicode digits are refused, as they are on the JSON path, where a
        # magnitude is a JSON number and so ASCII by construction.
        ("٥ mm", "'\\u0665 mm'"),
        # A number with no unit at all.
        ("0.1", "'0.1'"),
        # pint admits named dimensionless factors as unit components and folds
        # them into the magnitude at conversion: '2 pi mm' would exit 0 as
        # 6.283 mm and '1 ppm mm' as 1e-06 mm.
        ("2 pi mm", "'2 pi mm'"),
        ("1 ppm mm", "'1 ppm mm'"),
        # '%' is the number 0.01 spelled as a character.
        ("1 %mm", "'1 %mm'"),
        # pint's preprocessor deletes a comma between unit letters and fuses
        # them into one prefixed unit: 'm,m' would read as millimeter, 'c,m'
        # as centimeter -- a silently different quantity at exit 0.
        ("5 m,m", "'5 m,m'"),
        ("2 c,m", "'2 c,m'"),
        # Quoted text and '#' comments are dropped by pint with their digits.
        ("1 '2' mm", "\"1 '2' mm\""),
        ("1 mm#2", "'1 mm#2'"),
        ("1 mm # 25", "'1 mm # 25'"),
        # A leading-zero exponent is not a Python numeric literal, so pint's
        # own tokenizer reads it differently across interpreter versions
        # ('mm^0' times 1 on 3.11, 'mm^1' on 3.12+); it is refused for one
        # verdict everywhere.
        ("12.7 mm^01", "'12.7 mm^01'"),
    ],
)
def test_quantity_options_reject_forms_pint_would_read_as_another_number(
    wall_thickness: str, offending_token: str
) -> None:
    result = runner.invoke(app, _tube_with_wall_thickness(wall_thickness))

    payload = _error_payload(result)
    assert result.exit_code == 2
    assert payload["error"]["code"] == "invalid_quantity"
    assert offending_token in payload["error"]["message"]
    # One JSON line, never a traceback: _error_payload parses stderr as JSON.
    assert len(result.stderr.splitlines()) == 1


def test_option_conflicts_name_the_options_as_typed() -> None:
    """Conflict and ignored-option details echo CLI spellings, not parameter names."""
    result = runner.invoke(
        app, ["tube", "--json", "size", "--external-pressure", "7 ksi"]
    )

    payload = _error_payload(result)
    assert payload["error"]["code"] == "invalid_request"
    assert payload["error"]["details"] == [{"ignored_options": ["--json"]}]


@pytest.mark.parametrize(
    ("wall_thickness", "expected_mm"),
    [
        ("12.7 mm", 12.7),
        # The README promises the unit quoted or attached.
        ("12.7mm", 12.7),
        ("0.5 in", 12.7),
        ("0.5in", 12.7),
        (".5 in", 12.7),
        ("+12.7 mm", 12.7),
        ("1.27e1 mm", 12.7),
        ("1.27E+1 mm", 12.7),
        # Python's underscore digit grouping, which float() reads unambiguously.
        ("1_2.7 mm", 12.7),
    ],
)
def test_quantity_options_accept_every_documented_number_and_unit_form(
    wall_thickness: str, expected_mm: float
) -> None:
    result = runner.invoke(app, _tube_with_wall_thickness(wall_thickness))

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)["result"]["wall_thickness_mm"]
    assert parsed == {"unit": "mm", "value": pytest.approx(expected_mm)}


@pytest.mark.parametrize("pressure_unit", ["ft_H2O", "ftH2O", "inH2O", "cmH2O"])
def test_quantity_options_accept_digits_inside_a_unit_name(pressure_unit: str) -> None:
    # A digit continuing a unit name is not a number: pint never splits digits
    # out of an identifier, so water-column pressure units stay parseable.
    from pv_calc.units import Q_

    args = _tube_with_wall_thickness("12.7 mm")
    args[args.index("--external-pressure") + 1] = f"3 {pressure_unit}"
    result = runner.invoke(app, args)

    assert result.exit_code == 0, result.output
    parsed = json.loads(result.stdout)["result"]["external_pressure_mpa"]
    assert parsed["value"] == pytest.approx(Q_(3, pressure_unit).to("MPa").magnitude)


@pytest.mark.parametrize(
    ("wall_thickness", "error_code", "message_fragment"),
    [
        # An ASCII minus belongs to the number, so the sign survives parsing and
        # the calculation's own check is what reports it, in its own words.
        ("-5 mm", "unevaluable_model", "wall_thickness_mm must be finite and positive"),
        # A real unit of the wrong dimension is well formed; the dimension gate
        # rejects it, temperatures included.
        ("2 degC", "incompatible_unit", "must have units compatible with mm"),
        ("2 °C", "incompatible_unit", "must have units compatible with mm"),
        # An exponent pint can evaluate but no length can satisfy. The magnitude
        # is untouched, so this is a dimension question, not a parsing one.
        ("1 mm^1e400", "incompatible_unit", "must have units compatible with mm"),
    ],
)
def test_well_formed_quantities_are_left_for_the_model_to_reject(
    wall_thickness: str, error_code: str, message_fragment: str
) -> None:
    result = runner.invoke(app, _tube_with_wall_thickness(wall_thickness))

    payload = _error_payload(result)
    assert payload["error"]["code"] == error_code
    assert message_fragment in payload["error"]["message"]
    assert len(result.stderr.splitlines()) == 1


def _tube_json_request(wall_thickness_unit: str) -> str:
    return json.dumps(
        {
            "schema_version": CALC_SCHEMA_VERSION,
            "model": "tube",
            "inputs": {
                "external_pressure": {"value": 100, "unit": "psi"},
                "internal_radius": {"value": 1.719, "unit": "in"},
                "wall_thickness": {"value": 0.531, "unit": wall_thickness_unit},
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
    )


@pytest.mark.parametrize(
    "unit",
    [
        # Each escaped pint's evaluator as a raw traceback: ZeroDivisionError,
        # KeyError, and tokenize.TokenError in turn.
        "in/0",
        "mm^0",
        "mm)",
        # Each was silently normalized: ',1 mm' reached pint as a scale of
        # exactly 1 and read as plain mm; 'pi*millimeter' multiplied the JSON
        # magnitude by pi at conversion.
        ",1 mm",
        "pi*millimeter",
        # A unit name pint does not define, the option path's own verdict;
        # this path once misread it as a dimension mismatch.
        "kg/m3",
    ],
)
def test_json_input_units_pass_the_same_screen_as_option_quantities(unit: str) -> None:
    result = runner.invoke(
        app, ["tube", "--input", "-", "--json"], input=_tube_json_request(unit)
    )

    payload = _error_payload(result)
    assert result.exit_code == 2
    assert payload["error"]["code"] == "invalid_quantity"
    # One JSON line, never a traceback.
    assert len(result.stderr.splitlines()) == 1


def test_forward_and_sizing_report_the_same_code_for_a_doubly_invalid_request(
    tmp_path: Path,
) -> None:
    """Material completeness is checked before input conversion on both paths.

    A request whose material is unusable and whose input is unconvertible
    reports invalid_material from the forward operation and from its sizing
    counterpart alike; consumers switch on the code, so the precedence is
    contract.
    """
    database = tmp_path / "materials.yaml"
    database.write_text(
        "materials:\n"
        "  Yield-Only:\n"
        "    failure_category: ductile_metal\n"
        "    yield_strength_mpa: 250.0\n"
        '    source: "yield-only record"\n',
        encoding="utf-8",
    )
    bad_pressure = {"value": 1.0, "unit": "kg"}
    forward = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "plate",
        "inputs": {
            "external_pressure": bad_pressure,
            "free_radius": {"value": 100.0, "unit": "mm"},
            "plate_thickness": {"value": 8.0, "unit": "mm"},
            "boundary_condition": "fixed",
        },
        "material": {"type": "named", "name": "Yield-Only"},
    }
    sizing = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "plate",
        "operation": "size",
        "inputs": {
            "external_pressure": bad_pressure,
            "free_radius": {"value": 100.0, "unit": "mm"},
            "boundary_condition": "fixed",
            "plate_thickness_bounds": {
                "lower": {"value": 6.0, "unit": "mm"},
                "upper": {"value": 9.5, "unit": "mm"},
            },
            "minimum_margin": 0.25,
        },
        "material": {"type": "named", "name": "Yield-Only"},
    }
    for arguments, request in ((["plate"], forward), (["plate", "size"], sizing)):
        result = runner.invoke(
            app,
            [*arguments, "--input", "-", "--materials-file", str(database), "--json"],
            input=json.dumps(request),
        )
        payload = _error_payload(result)
        assert payload["error"]["code"] == "invalid_material", (arguments, result.output)
        assert "plate material properties are incomplete" in payload["error"]["message"]


@pytest.mark.parametrize(
    ("external_pressure", "internal_radius", "wall_thickness"),
    [
        ("1e308 MPa", "10 mm", "1 mm"),
        ("1 MPa", "1e-308 mm", "1e-308 mm"),
    ],
)
def test_numerically_unevaluable_input_returns_structured_error(
    external_pressure: str,
    internal_radius: str,
    wall_thickness: str,
) -> None:
    result = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure",
            external_pressure,
            "--internal-radius",
            internal_radius,
            "--wall-thickness",
            wall_thickness,
            "--yield-strength",
            "200 MPa",
            "--failure-category",
            "ductile_metal",
            "--material-provenance",
            "test record",
            "--json",
        ],
    )

    assert _error_payload(result)["error"]["code"] == "unevaluable_model"


def test_non_utf8_input_file_returns_structured_error(tmp_path: Path) -> None:
    request = tmp_path / "request.json"
    request.write_bytes(b"\xff")

    result = runner.invoke(app, ["tube", "--input", str(request), "--json"])

    assert _error_payload(result)["error"]["code"] == "input_read_error"


def test_calculation_source_identifies_the_package_not_the_repository_tree() -> None:
    """A result names its package and model, not a hash of the whole checkout."""
    calculated = runner.invoke(
        app,
        ["tube", "--input", str(EXAMPLES / "tube_9_0401_ksi.json"), "--json"],
    )
    described = runner.invoke(app, ["describe", "tube", "--json"])

    assert calculated.exit_code == 0, calculated.output
    assert described.exit_code == 0, described.output
    source = json.loads(calculated.stdout)["calculation_source"]
    assert source == json.loads(described.stdout)["calculation_source"]
    assert set(source) == {"function", "model_id", "model_version", "package_version"}
    assert source["package_version"] == __version__


def test_help_lists_every_command_and_example() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "tube" in result.output
    assert "plate" in result.output
    assert "describe" in result.output
    assert "smooth-buckling" in result.output
    assert "ring-shell" in result.output
    assert "hemisphere" in result.output
    assert "mass-properties" in result.output
    assert "sweep" in result.output
    assert "compare-materials" in result.output
    assert "--version" in result.output
    assert "Example:" in result.output
    assert "size" not in result.output

    tube_help = runner.invoke(app, ["tube", "--help"])
    assert tube_help.exit_code == 0
    assert "size" in tube_help.output
    assert "wall-thickness sizing" in tube_help.output
    assert "pv-calc tube --input request.json --json" in tube_help.output

    plate_help = runner.invoke(app, ["plate", "--help"])
    assert plate_help.exit_code == 0
    assert "size" in plate_help.output
    assert "plate-thickness sizing" in plate_help.output

    # The examples are repository fixtures, not packaged data, so no help text
    # may name one: the wheel ships none of them and a copied command would
    # fail with input_read_error.
    commands_and_examples = (
        (["tube", "size", "--help"], "pv-calc tube size --input request.json --json"),
        (["plate", "--help"], "pv-calc plate --input request.json --json"),
        (["plate", "size", "--help"], "pv-calc plate size --input request.json --json"),
        (["hemisphere", "--help"], "pv-calc hemisphere --input request.json --json"),
        (
            ["smooth-buckling", "--help"],
            "pv-calc smooth-buckling --input request.json --json",
        ),
        (
            ["smooth-buckling", "size", "--help"],
            "pv-calc smooth-buckling size --input request.json --json",
        ),
        (["ring-shell", "--help"], "pv-calc ring-shell --input request.json --json"),
        (
            ["mass-properties", "--help"],
            "pv-calc mass-properties --input request.json --json",
        ),
        (["sweep", "--help"], "pv-calc sweep --input request.json --json"),
        (
            ["compare-materials", "--help"],
            "pv-calc compare-materials --input request.json --json",
        ),
        (["describe", "--help"], "pv-calc describe hemisphere --json"),
    )
    for args, example_text in commands_and_examples:
        command_help = runner.invoke(app, args)
        assert command_help.exit_code == 0, command_help.output
        assert "Example:" in command_help.output
        assert example_text in command_help.output


def test_version_uses_package_version() -> None:
    result = runner.invoke(app, ["--version"])

    assert result.exit_code == 0, result.output
    assert result.stdout.strip() == __version__
    # __version__ is what results report as package_version, and the
    # distribution states its version separately in pyproject.toml. Drift
    # between the two would make that provenance false.
    try:
        installed = version("pv-calc")
    except PackageNotFoundError:
        pytest.skip("pv-calc is not installed as a distribution here")
    assert installed == __version__
