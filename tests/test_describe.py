"""The describe command's discoverable contracts."""

from __future__ import annotations

import json
from copy import deepcopy
from dataclasses import fields
from typing import Any, get_type_hints

import pytest
import typer
from _cli_helpers import (
    EXAMPLES,
    MATERIALS_FILE,
    SWEEP_FORWARD_EXAMPLES,
    _error_payload,
    runner,
)

from pv_calc import cli as calc_cli
from pv_calc.cli import app
from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    COMPARE_MATERIALS_OPERATION_VERSION,
    SWEEP_GEOMETRY_VARIABLES,
    SWEEP_OPERATION_VERSION,
    ContractModel,
    CylinderRequest,
    HemisphereRequest,
    MassPropertiesRequest,
    MaterialComparisonRequest,
    PlateSizeRequest,
    PlateSizingMetadata,
    QuantityInput,
    RingShellRequest,
    SmoothBucklingSizeRequest,
    SmoothBucklingSizingMetadata,
    SweepRequest,
    TubeRequest,
    TubeSizeRequest,
    TubeSizingMetadata,
    quantity_dimensions,
)


from pv_calc.hydrostatics import SubmergedMassResult
from pv_calc.pressure_vessel import (
    FlatCircularPlateResult,
    HemisphereResult,
    HemisphereStressState,
    RingGlobalBucklingResult,
    RingModeSearchIteration,
    RingShellResult,
    SmoothCylinderBucklingCandidate,
    SmoothCylinderBucklingResult,
    TubeStressResult,
    TubeStressState,
)
from pv_calc.serialize import (
    HEMISPHERE_RESULT_UNITS,
    HEMISPHERE_STRESS_STATE_UNITS,
    MASS_PROPERTIES_RESULT_UNITS,
    PLATE_RESULT_UNITS,
    RING_GLOBAL_RESULT_UNITS,
    RING_MODE_SEARCH_ITERATION_UNITS,
    RING_SHELL_RESULT_UNITS,
    SMOOTH_BUCKLING_CANDIDATE_UNITS,
    SMOOTH_BUCKLING_RESULT_UNITS,
    TUBE_RESULT_UNITS,
    TUBE_STATE_UNITS,
)

def _assert_workflow_schema(schema: dict[str, Any], request: type[ContractModel]) -> None:
    """Only the public load/radius alternatives may extend the strict schema.

    Keep the base properties, nested material/geometry definitions, and envelope
    exact. Check the alternatives' constraints too, so simply making formerly
    required quantities optional cannot satisfy this regression test.
    """
    base = request.model_json_schema()
    original = deepcopy(schema)
    # Batch schemas contain several ordinary input definitions. Their own
    # pressure/depth axes are deliberately excluded: they have axis schemas,
    # whereas each model pressure is a single QuantityInput.
    restored = deepcopy(schema)
    for input_name, base_inputs in base["$defs"].items():
        if base_inputs.get("properties", {}).get("external_pressure") != {"$ref": "#/$defs/QuantityInput"}:
            continue
        inputs = schema["$defs"][input_name]
        _assert_workflow_input_schema(inputs, base_inputs)
        restored["$defs"][input_name] = deepcopy(base_inputs)
    assert restored == base
    assert schema == original


def _assert_workflow_input_schema(inputs: dict[str, Any], base_inputs: dict[str, Any]) -> None:
    load_names = ["depth", "fluid_density", "gravity", "design_factor"]
    assert {name: inputs["properties"][name] for name in base_inputs["properties"]} == base_inputs["properties"]
    assert set(inputs["properties"]) == set(base_inputs["properties"]) | set(load_names)
    assert all(inputs["properties"][name] == {"$ref": "#/$defs/QuantityInput"} for name in load_names[:3])
    assert inputs["properties"]["design_factor"] == {"type": "number", "exclusiveMinimum": 0}
    assert inputs["required"] == [name for name in base_inputs["required"] if name != "external_pressure"]
    conditions = [{"oneOf": [
        {"required": ["external_pressure"], "not": {"anyOf": [{"required": [name]} for name in load_names]}},
        {"required": load_names, "not": {"required": ["external_pressure"]}},
    ]}]
    if "external_radius" in base_inputs["properties"]:
        conditions.append({"oneOf": [
            {"required": ["internal_radius"], "properties": {
                "internal_radius": {"$ref": "#/$defs/QuantityInput"}, "external_radius": {"type": "null"},
            }},
            {"required": ["external_radius"], "properties": {
                "external_radius": {"$ref": "#/$defs/QuantityInput"}, "internal_radius": {"type": "null"},
            }},
        ]})
    assert inputs["allOf"] == conditions
    # Removing exactly the checked extension restores the complete input
    # definition, including every original bound and strict-extra policy.
    restored_inputs = deepcopy(inputs)
    for name in load_names:
        del restored_inputs["properties"][name]
    restored_inputs["required"] = base_inputs["required"]
    del restored_inputs["allOf"]
    assert restored_inputs == base_inputs

def test_describe_reports_complete_discoverable_contracts() -> None:
    for model, result_type in (
        ("tube", TubeStressResult),
        ("plate", FlatCircularPlateResult),
        ("hemisphere", HemisphereResult),
        ("smooth-buckling", SmoothCylinderBucklingResult),
        ("ring-shell", RingShellResult),
        ("mass-properties", SubmergedMassResult),
    ):
        result = runner.invoke(app, ["describe", model, "--json"])
        assert result.exit_code == 0, result.output
        description = json.loads(result.stdout)
        assert description["schema_version"] == CALC_SCHEMA_VERSION
        assert description["implemented_checks"]
        assert description["known_omissions"]
        assert description["source_references"]
        assert description["required_material_properties"]
        result_schema = description["output_contract"]["result_json_schema"]
        assert set(result_schema["properties"]) == {field.name for field in fields(result_type)}
        assert result_schema["additionalProperties"] is False

    tube = json.loads(runner.invoke(app, ["describe", "tube", "--json"]).stdout)
    pressure_schema = tube["output_contract"]["result_json_schema"]["properties"][
        "external_pressure_mpa"
    ]
    assert pressure_schema["properties"]["unit"]["const"] == "MPa"
    assert tube["available_operations"] == ["forward", "size"]
    # The two elastic properties are reported because the model reads them for
    # displacement, and are absent from the required set because a stress-only
    # record is complete without them. The contract lists every strength a
    # category can carry; a response reports only its own category's.
    assert set(tube["output_contract"]["material"]["properties_used"]) == {
        "elastic_modulus",
        "failure_category",
        "poisson_ratio",
        "yield_strength",
        "working_strength",
        "ultimate_compressive_strength",
    }
    assert set(tube["required_material_properties"]) == {
        "failure_category",
        "strength_by_failure_category",
    }
    assert tube["required_material_properties"]["strength_by_failure_category"] == {
        "ductile_metal": ["yield_strength"],
        "plastic": ["working_strength"],
        "brittle": ["ultimate_compressive_strength"],
    }
    assert "inputs.axial_length" in tube["input_contract"]["json_quantity_dimensions"]
    size_contract = tube["size_contract"]
    assert size_contract["declared_check_set"] == ["cylindrical_shell_stress"]
    assert size_contract["varied_input"] == "wall_thickness"
    _assert_workflow_schema(size_contract["input_contract"]["json_schema"], TubeSizeRequest)
    assert "Exactly one non-null" in size_contract["fixed_radius_rule"]
    assert "sizing.stock_candidates" in size_contract["stock_selection"]
    assert (
        size_contract["output_contract"]["sizing_json_schema"]
        == TubeSizingMetadata.model_json_schema()
    )
    tube_point = size_contract["output_contract"]["sizing_json_schema"]["$defs"][
        "TubeSizingPoint"
    ]["properties"]
    assert tube_point["branch"]["const"] == "thick"
    assert tube_point["governing_location"]["const"] == "internal"
    assert size_contract["failure"] == {
        "error_codes": [
            "invalid_bounds",
            "no_reliable_solution",
            "unevaluable_model",
        ],
        "exit_status": "nonzero",
        "scope": "inverse solver; common input and material errors use the CLI error contract",
    }
    assert size_contract["output_contract"]["complete_forward_contract_at_selected_thickness"]

    plate = json.loads(runner.invoke(app, ["describe", "plate", "--json"]).stdout)
    assert plate["available_operations"] == ["forward", "size"]
    plate_size = plate["size_contract"]
    assert plate_size["command"] == "pv-calc plate size"
    assert plate_size["varied_input"] == "plate_thickness"
    assert plate_size["possible_check_set"] == [
        "flat_endcap_bending",
        "center_deflection",
    ]
    assert plate_size["declared_check_rule"] == {
        "flat_endcap_bending": "always",
        "center_deflection": "only when inputs.maximum_deflection is supplied",
    }
    assert plate_size["minimum_margin"]["role"] == (
        "target margin for flat_endcap_bending"
    )
    assert plate_size["maximum_deflection"]["optional"]
    assert "declared only when" in plate_size["maximum_deflection"]["role"]
    assert "stricter evidence floor" in plate_size["maximum_deflection"]["role"]
    _assert_workflow_schema(plate_size["input_contract"]["json_schema"], PlateSizeRequest)
    assert "sizing.stock_candidates" in plate_size["stock_selection"]
    assert plate_size["output_contract"]["sizing_json_schema"] == (
        PlateSizingMetadata.model_json_schema()
    )
    assert plate_size["output_contract"]["selected_result_json_schema"] == (
        plate["output_contract"]["result_json_schema"]
    )
    assert "no_reliable_solution" in plate_size["failure"]["error_codes"]
    assert any("re-read at every" in item for item in plate_size["assumptions"])
    assert any("Only model-eligible thicknesses" in item for item in plate_size["assumptions"])
    assert any("the shell" in item for item in plate_size["known_omissions"])

    smooth = json.loads(
        runner.invoke(app, ["describe", "smooth-buckling", "--json"]).stdout
    )
    assert smooth["available_operations"] == ["forward", "size"]
    assert "lateral_only" in json.dumps(smooth["input_contract"]["json_schema"])
    assert "proportional_limit" in smooth["required_material_properties"]
    assert any(
        "moderate/long correlation overlap" in item
        for item in smooth["known_omissions"]
    )
    smooth_size = smooth["size_contract"]
    assert smooth_size["command"] == "pv-calc smooth-buckling size"
    assert smooth_size["varied_input"] == "wall_thickness"
    assert smooth_size["declared_check_set"] == [
        "cylindrical_shell_stress",
        "smooth_cylinder_buckling",
    ]
    assert smooth_size["load_case"] == "hydrostatic_closed_end"
    assert smooth_size["shell_mid_surface_radius_convention"] == (
        "internal_radius_plus_half_wall_thickness"
    )
    assert smooth_size["shell_mid_surface_radius_conventions_by_fixed_radius"] == {
        "internal_radius": "internal_radius_plus_half_wall_thickness",
        "external_radius": "external_radius_minus_half_wall_thickness",
    }
    assert smooth_size["derived_branch_boundaries"] == [
        "buckling_thin_shell_radius_thickness_limit",
        "short_regime_gamma_z_limit",
        "moderate_regime_gamma_z_limit",
        "moderate_regime_more_than_two_wave_limit",
        "long_regime_oval_wave_limit",
        "short_regime_proportional_limit",
        "moderate_regime_proportional_limit",
        "long_regime_proportional_limit",
    ]
    _assert_workflow_schema(smooth_size["input_contract"]["json_schema"], SmoothBucklingSizeRequest)
    assert "external_radius - thickness" in smooth_size["fixed_radius_rule"]
    assert smooth_size["output_contract"]["sizing_json_schema"] == (
        SmoothBucklingSizingMetadata.model_json_schema()
    )
    smooth_point = smooth_size["output_contract"]["sizing_json_schema"]["$defs"][
        "SmoothBucklingSizingPoint"
    ]["properties"]
    assert smooth_point["tube_branch"]["const"] == "thick"
    assert smooth_size["output_contract"]["selected_results_fields"] == [
        "smooth-buckling",
        "tube",
    ]
    assert "no_reliable_solution" in smooth_size["failure"]["error_codes"]
    assert any("withheld" in item for item in smooth_size["assumptions"])

    hemisphere = json.loads(
        runner.invoke(app, ["describe", "hemisphere", "--json"]).stdout
    )
    assert hemisphere["available_operations"] == ["forward"]
    _assert_workflow_schema(hemisphere["input_contract"]["json_schema"], HemisphereRequest)
    assert "proportional_limit" in hemisphere["required_material_properties"]
    assert any("plastic buckling" in item for item in hemisphere["known_omissions"])

    ring = json.loads(runner.invoke(app, ["describe", "ring-shell", "--json"]).stdout)
    assert ring["available_operations"] == ["forward"]
    _assert_workflow_schema(ring["input_contract"]["json_schema"], RingShellRequest)
    assert "proportional_limit" not in ring["required_material_properties"]
    assert any("Eq. 64/Eq. 66" in item for item in ring["known_omissions"])

    mass = json.loads(runner.invoke(app, ["describe", "mass-properties", "--json"]).stdout)
    assert mass["available_operations"] == ["forward"]
    assert mass["input_contract"]["json_schema"] == (
        MassPropertiesRequest.model_json_schema()
    )
    assert mass["calculation_source"]["function"] == (
        "pv_calc.hydrostatics.submerged_mass_and_buoyancy"
    )
    assert mass["required_material_properties"] == {
        "density": {"dimension": "density", "normalized_unit": "kg/m^3"}
    }
    assert any("fluid database" in item for item in mass["known_omissions"])

    cylinder = json.loads(runner.invoke(app, ["describe", "cylinder", "--json"]).stdout)
    assert cylinder["available_operations"] == ["forward"]
    _assert_workflow_schema(cylinder["input_contract"]["json_schema"], CylinderRequest)
    assert cylinder["input_contract"]["json_quantity_dimensions"]["inputs.depth"] == "length"
    assert "loading" in cylinder["output_contract"]["optional_top_level_fields"]
    assert "indeterminate" in cylinder["output_contract"]["assessment"]
    assert "missing component density" in cylinder["output_contract"]["mass_properties"]

    swept = json.loads(runner.invoke(app, ["describe", "sweep", "--json"]).stdout)
    assert swept["operation"] == "sweep"
    assert swept["operation_version"] == SWEEP_OPERATION_VERSION
    assert swept["swept_input"] == "inputs.external_pressure"
    assert swept["axis_variables"] == ["depth", "external_pressure", "geometry"]
    assert swept["supported_models"] == sorted([*SWEEP_FORWARD_EXAMPLES, "cylinder"])
    assert swept["geometry_variables"] == {model: list(names) for model, names in SWEEP_GEOMETRY_VARIABLES.items()}
    assert swept["geometry_variables"]["cylinder"] == ["internal_radius", "wall_thickness", "unsupported_length", "axial_length"]
    _assert_workflow_schema(swept["input_contract"]["json_schema"], SweepRequest)
    assert swept["output_contract"]["complete_single_point_response_per_point"]
    assert "nested_loading" in swept["output_contract"]
    assert "loading" not in swept["output_contract"].get("optional_top_level_fields", {})
    # Nested requests retain OWN_CONTRACT dimension ownership: their detailed
    # quantities are published by describe <model>, while this map is the axis.
    assert swept["input_contract"]["json_quantity_dimensions"] == quantity_dimensions(SweepRequest)
    assert swept["depth_axis"]["substituted_pressure"] == "design_external_pressure"
    assert swept["depth_axis"]["required_inputs"] == [
        "depth",
        "fluid_density",
        "gravity",
        "design_factor",
    ]
    assert swept["depth_axis"]["calculation_source"]["model_id"] == (
        "hydrostatic_external_pressure_from_depth"
    )
    assert swept["output_contract"]["point_fields"]["depth"] == [
        "depth",
        "service_external_pressure",
        "design_external_pressure",
        "response",
    ]
    assert "depth_to_pressure" in swept["output_contract"]["sweep_fields"]["depth"]
    assert swept["failure"]["error_codes"] == [
        "axis_source_conflict",
        "invalid_number",
        "invalid_quantity",
        "invalid_request",
        "missing_input",
    ]
    assert any("adaptive sampling" in item for item in swept["known_omissions"])

    compared = json.loads(
        runner.invoke(app, ["describe", "compare-materials", "--json"]).stdout
    )
    assert compared["operation"] == "compare-materials"
    assert compared["operation_version"] == COMPARE_MATERIALS_OPERATION_VERSION
    assert compared["substituted_input"] == "request.material"
    assert compared["supported_models"] == sorted([*SWEEP_FORWARD_EXAMPLES, "cylinder"])
    assert compared["supported_sizing_operations"] == {"tube": "size", "plate": "size", "smooth-buckling": "size"}
    _assert_workflow_schema(compared["input_contract"]["json_schema"], MaterialComparisonRequest)
    assert compared["output_contract"]["complete_single_material_response_per_entry"]
    assert "nested_loading" in compared["output_contract"]
    assert "loading" not in compared["output_contract"].get("optional_top_level_fields", {})
    assert compared["output_contract"]["entry_order"] == "the caller's inputs.materials order"
    assert compared["output_contract"]["entry_fields"]["invalid_material"] == [
        "material",
        "outcome",
        "message",
    ]
    # The missing-property policy is published, not just implemented.
    assert set(compared["entry_outcomes"]) == {"evaluated", "invalid_material", "no_reliable_solution"}
    assert compared["output_contract"]["entry_fields"]["no_reliable_solution"] == ["material", "outcome", "message", "details"]
    assert any("selected_geometry" in field for field in compared["output_contract"]["entry_fields"]["evaluated"])
    assert any("structural_mass" in field for field in compared["output_contract"]["entry_fields"]["evaluated"])
    request_union = compared["input_contract"]["json_schema"]["properties"]["request"]["anyOf"]
    size_variants = {variant["$ref"] for variant in request_union if "$ref" in variant}
    assert size_variants == {"#/$defs/TubeSizeRequest", "#/$defs/PlateSizeRequest", "#/$defs/SmoothBucklingSizeRequest"}
    assert "lacks a property" in compared["entry_outcomes"]["invalid_material"]
    assert any("still exits zero" in item for item in compared["assumptions"])
    assert any("never" in item for item in compared["known_omissions"])
    assert compared["failure"]["error_codes"] == [
        "invalid_material_database",
        "invalid_request",
        "material_source_conflict",
        "missing_input",
        "unknown_material",
    ]

    for contract in (size_contract, plate_size, smooth_size):
        sizing_schema = contract["output_contract"]["sizing_json_schema"]
        assert "stock_candidates" in sizing_schema["properties"]
        candidate = sizing_schema["$defs"]["StockSizingCandidate"]
        assert candidate["additionalProperties"] is False
        assert set(candidate["properties"]["outcome"]["enum"]) == {
            "outside_bounds", "unavailable", "fails_targets", "meets_targets",
        }

    unknown = runner.invoke(app, ["describe", "not-a-model", "--json"])
    unknown_payload = _error_payload(unknown)
    assert unknown_payload["error"]["code"] == "unknown_model"
    assert "mass-properties" in (
        unknown_payload["error"]["details"][0]["available_models"]
    )
    assert "cylinder" in unknown_payload["error"]["details"][0]["available_models"]
    assert unknown_payload["error"]["details"][0]["available_operations"] == [
        "compare-materials",
        "sweep",
    ]


def test_response_top_level_fields_match_the_published_contract() -> None:
    """Every declared envelope field is emitted, and nothing undeclared is.

    All six ``required_top_level_fields`` lists are hand-written, while the
    envelopes come from ``serialize._response`` and the two batch builders, so
    nothing else stops a contract from naming a field a response does not
    carry. ``--materials-file`` is passed to every case because it is inert
    for a request carrying explicit properties, as the golden suite relies on,
    and ``compare-materials`` is the one case that needs it.
    """
    cases = [(model, [], example) for model, example in SWEEP_FORWARD_EXAMPLES.items()]
    cases += [
        ("cylinder", [], "cylinder_check.json"),
        ("cylinder", [], "cylinder_housing.json"),
        ("mass-properties", [], "mass_properties_aluminium_housing.json"),
        # The one example carrying inputs.submergence, which is what releases
        # the optional top-level field the forward contract declares.
        ("tube", [], "tube_pvc_0_4166_ksi.json"),
        ("tube", ["size"], "tube_size_7_ksi.json"),
        ("plate", ["size"], "plate_size_deflection_limited.json"),
        ("smooth-buckling", ["size"], "smooth_buckling_size_moderate.json"),
        ("sweep", [], "sweep_tube_pressure_range.json"),
        ("compare-materials", [], "compare_materials_tube_housing.json"),
    ]

    for target, subcommand, example in cases:
        label = " ".join([target, *subcommand, example])
        described = runner.invoke(app, ["describe", target, "--json"])
        assert described.exit_code == 0, f"{label}: {described.output}"
        description = json.loads(described.stdout)
        contract = (description["size_contract"] if subcommand else description)[
            "output_contract"
        ]
        declared_required = set(contract["required_top_level_fields"])
        declared_optional = set(contract.get("optional_top_level_fields", {}))

        result = runner.invoke(
            app,
            [
                target,
                *subcommand,
                "--input",
                str(EXAMPLES / example),
                "--materials-file",
                str(MATERIALS_FILE),
                "--json",
            ],
        )
        assert result.exit_code == 0, f"{label}: {result.output}"
        emitted = set(json.loads(result.stdout))

        assert declared_required <= emitted, f"{label}: declared but not emitted"
        assert emitted - declared_required <= declared_optional, (
            f"{label}: emitted but not declared"
        )


@pytest.mark.parametrize(
    ("result_type", "units"),
    (
        (TubeStressResult, TUBE_RESULT_UNITS),
        (TubeStressState, TUBE_STATE_UNITS),
        (HemisphereResult, HEMISPHERE_RESULT_UNITS),
        (HemisphereStressState, HEMISPHERE_STRESS_STATE_UNITS),
        (FlatCircularPlateResult, PLATE_RESULT_UNITS),
        (SmoothCylinderBucklingResult, SMOOTH_BUCKLING_RESULT_UNITS),
        (
            SmoothCylinderBucklingCandidate,
            SMOOTH_BUCKLING_CANDIDATE_UNITS,
        ),
        (RingShellResult, RING_SHELL_RESULT_UNITS),
        (RingGlobalBucklingResult, RING_GLOBAL_RESULT_UNITS),
        (
            RingModeSearchIteration,
            RING_MODE_SEARCH_ITERATION_UNITS,
        ),
        (SubmergedMassResult, MASS_PROPERTIES_RESULT_UNITS),
    ),
)
def test_describe_unit_maps_cover_dimensioned_result_fields(result_type, units) -> None:
    field_names = {field.name for field in fields(result_type)}
    dimensionless_n_fields = {
        "circumferential_wave_count_n",
        "critical_circumferential_lobes_n",
        "roark_probable_minimum_lobes_n",
    }
    dimensioned_fields = {
        name
        for name in field_names
        if name.endswith(
            ("_mpa", "_mm", "_mm2", "_mm4", "_n_per_mm", "_m3", "_kg", "_m_per_s2")
        )
        or (name.endswith("_n") and name not in dimensionless_n_fields)
    }

    assert dimensioned_fields <= units.keys()
    assert units.keys() <= field_names


def _typer_commands():
    """Every (command name, function) the app exposes, sub-apps included."""
    for info in app.registered_commands:
        yield info.name or info.callback.__name__, info.callback
    for group in app.registered_groups:
        sub = group.typer_instance
        if sub.registered_callback is not None:
            yield group.name, sub.registered_callback.callback
        for info in sub.registered_commands:
            yield f"{group.name} {info.name}", info.callback


def _option_help(command) -> dict[str, str]:
    hints = get_type_hints(command, include_extras=True)
    out = {}
    for name, hint in hints.items():
        for extra in getattr(hint, "__metadata__", ()):
            if isinstance(extra, typer.models.OptionInfo):
                out[name] = extra.help or ""
    return out


def test_every_unit_carrying_option_has_a_dimension_and_none_is_dead() -> None:
    declared = set()
    for name, command in _typer_commands():
        for option, help_text in _option_help(command).items():
            declared.add(option)
            if "with unit" in help_text:
                assert option in calc_cli._OPTION_DIMENSIONS, f"{name} --{option}: no dimension"
    assert set(calc_cli._OPTION_DIMENSIONS) <= declared


# A CLI option's name maps onto the request path it fills; the bounds, axis,
# and explicit-density options are the ones whose names differ from the path.
_AXIS_STEMS = {"pressure": "external_pressure", "depth": "depth"}


def _path_suffix(option: str, *, sweep: bool = False) -> str:
    if option == "material_density":
        return "properties.density"
    if option == "stock_thickness":
        return "stock_thicknesses"
    if option == "depth" and not sweep:
        return "depth"
    for suffix in ("_lower", "_upper"):
        if option.endswith(suffix):
            return f"{option.removesuffix(suffix)}_bounds.{suffix[1:]}"
    for suffix in ("_start", "_stop"):
        if option.endswith(suffix):
            return f"{_AXIS_STEMS[option.removesuffix(suffix)]}.{suffix[1:]}"
    if option in _AXIS_STEMS:
        return f"{_AXIS_STEMS[option]}.values"
    return option


@pytest.mark.parametrize(
    "target",
    ["tube", "plate", "hemisphere", "smooth-buckling", "ring-shell", "mass-properties", "sweep", "cylinder"],
)
def test_describe_cli_options_name_request_quantities_of_the_same_dimension(target) -> None:
    description = json.loads(runner.invoke(app, ["describe", target, "--json"]).stdout)
    contracts = [description["input_contract"]]
    if "size_contract" in description:
        contracts.append(description["size_contract"]["input_contract"])
    for contract in contracts:
        assert contract["cli_dimensioned_options"], target
        paths = contract["json_quantity_dimensions"]
        for option, dimension in contract["cli_dimensioned_options"].items():
            suffix = _path_suffix(option.removeprefix("--").replace("-", "_"), sweep=target == "sweep")
            matches = {paths[path] for path in paths if path.endswith("." + suffix)}
            assert matches == {dimension}, (target, option, suffix, matches)


def test_quantity_dimensions_refuses_an_undeclared_quantity() -> None:
    class Undeclared(ContractModel):
        thickness: QuantityInput

    class Nested(ContractModel):
        inputs: Undeclared

    with pytest.raises(TypeError, match="inputs.thickness"):
        quantity_dimensions(Nested)
    assert quantity_dimensions(TubeRequest)["inputs.wall_thickness"] == "length"
