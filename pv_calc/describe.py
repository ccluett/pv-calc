"""The `describe` contracts: each model's and operation's published input/output schema."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, get_args

from pydantic import TypeAdapter

from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    CATEGORY_STRENGTHS,
    COMPARE_MATERIALS_OPERATION_VERSION,
    COMPARE_MATERIALS_SUBSTITUTED_INPUT,
    FORWARD_MODELS,
    PLATE_SIZE_OPERATION_VERSION,
    PLATE_SIZING_BENDING_CHECK,
    PLATE_SIZING_DEFLECTION_CHECK,
    SMOOTH_BUCKLING_SIZE_OPERATION_VERSION,
    SMOOTH_BUCKLING_SIZING_CHECK_SET,
    SMOOTH_BUCKLING_SIZING_LOAD_CASE,
    SMOOTH_BUCKLING_SIZING_RADIUS_CONVENTION,
    SWEEP_AXIS_VARIABLES,
    SWEEP_DEPTH_SUBSTITUTED_PRESSURE,
    SWEEP_OPERATION_VERSION,
    SWEEP_SWEPT_INPUT,
    TUBE_SIZE_OPERATION_VERSION,
    TUBE_SIZING_CHECK_SET,
    ContractModel,
    HemisphereRequest,
    MassPropertiesRequest,
    MaterialComparisonRequest,
    PlateRequest,
    PlateSizeRequest,
    PlateSizingMetadata,
    RingShellRequest,
    SmoothBucklingRequest,
    SmoothBucklingSizeRequest,
    SmoothBucklingSizingMetadata,
    SweepRequest,
    TubeRequest,
    TubeSizeRequest,
    TubeSizingMetadata,
    quantity_dimensions,
)
from pv_calc.errors import CalcCliError
from pv_calc.evaluate import FAILURE_PRESSURE_FIELDS
from pv_calc.hydrostatics import (
    HYDROSTATIC_PRESSURE_MODEL_ID,
    HYDROSTATIC_PRESSURE_MODEL_VERSION,
    HYDROSTATIC_PRESSURE_SOURCE,
    SUBMERGED_MASS_MODEL_ID,
    SUBMERGED_MASS_MODEL_VERSION,
    SUBMERGED_MASS_SCOPE_NOTES,
    SUBMERGED_MASS_SOURCE,
    SubmergedMassResult,
)
from pv_calc.pressure_vessel import (
    FLAT_CIRCULAR_PLATE_MODEL_ID,
    FLAT_CIRCULAR_PLATE_MODEL_VERSION,
    FLAT_CIRCULAR_PLATE_SCOPE_NOTES,
    FLAT_CIRCULAR_PLATE_SOURCE,
    HEMISPHERE_BUCKLING_SOURCE,
    HEMISPHERE_MEMBRANE_DISPLACEMENT_SOURCE,
    HEMISPHERE_MODEL_ID,
    HEMISPHERE_MODEL_VERSION,
    HEMISPHERE_SCOPE_NOTES,
    HEMISPHERE_SOFTWARE_PARITY_SOURCE,
    HEMISPHERE_THICK_STRESS_SOURCE,
    HEMISPHERE_THIN_STRESS_SOURCE,
    MATERIAL_FAILURE_SOURCE,
    RING_SHELL_BENCHMARK_SOURCE,
    RING_SHELL_MODEL_ID,
    RING_SHELL_MODEL_VERSION,
    RING_SHELL_SECTION_SOURCE,
    RING_SHELL_SOURCE,
    SEAT_BEARING_STRESS_SOURCE,
    SMOOTH_CYLINDER_BUCKLING_MODEL_ID,
    SMOOTH_CYLINDER_BUCKLING_MODEL_VERSION,
    SMOOTH_CYLINDER_BUCKLING_SOURCE,
    SMOOTH_CYLINDER_ROARK_OVERLAP_SOURCE,
    SMOOTH_CYLINDER_SCOPE_NOTES,
    TUBE_SCOPE_NOTES,
    TUBE_STRESS_MODEL_ID,
    TUBE_STRESS_MODEL_VERSION,
    TUBE_THICK_DISPLACEMENT_SOURCE,
    TUBE_THICK_SOURCE,
    TUBE_THIN_DISPLACEMENT_SOURCE,
    TUBE_THIN_SOURCE,
    FlatCircularPlateResult,
    HemisphereResult,
    RingShellResult,
    SmoothCylinderBucklingResult,
    TubeStressResult,
)
from pv_calc.schemas import MaterialFailureCategory
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
    _calculation_source,
)
from pv_calc.sizing import (
    _SMOOTH_BUCKLING_REGIME_BOUNDARIES,
    _SMOOTH_BUCKLING_THIN_SHELL_BOUNDARY,
    _SMOOTH_BUCKLING_TUBE_BRANCH_BOUNDARY,
)


# Result fields whose presence is conditional on something neither the field
# name nor its unit conveys.  Without the note a consumer reads the contract,
# sees a nullable number, and has no way to learn when it is populated.
_RESULT_FIELD_DESCRIPTIONS: dict[str, str] = {
    "eq25_simplified_critical_pressure_mpa": (
        "NASA/SP-8007-2020/REV 2 Eq. 25, printed p. 27, which that source states only "
        "for nu = 0.316. Populated when poisson_ratio is exactly 0.316 and null at "
        "every other ratio, including the values every bundled material record "
        "carries. It is the source's rounded 0.926 restatement of the Eq. 24 "
        "capacity and stands 0.0873% above it, so it is reported to keep the printed "
        "value traceable and sets no capacity, margin, or regime."
    ),
    "elastic_applicability": (
        "Screen, not a capacity: compares working_circumferential_membrane_stress_mpa "
        "with elastic_applicability_limit_mpa using the same strict comparison the "
        "plasticity check applies to the correlated critical stress. 'exceeded' means "
        "every capacity at or above the applied pressure exceeds that limit too, at "
        "every unsupported length, because only wall thickness moves this stress: with "
        "a proportional limit supplied such a capacity is an elastic upper bound "
        "reported as released_pending_plasticity, and with only a yield strength it is "
        "withheld for the missing limit. "
        "'undetermined' means neither a proportional limit nor a yield strength was "
        "supplied. It never withholds a result and never sets a margin."
    ),
    "elastic_applicability_limit_mpa": (
        "The stress limit the elastic-applicability screen compared against: the "
        "proportional limit when one was supplied, otherwise the yield strength, "
        "otherwise null. elastic_applicability_limit_basis names which. Yield is a "
        "valid fallback because this model already requires proportional_limit_mpa <= "
        "yield_strength_mpa, so yield bounds every admissible proportional limit."
    ),
    "global_critical_circumferential_membrane_stress_mpa": (
        "The shell circumferential membrane stress p*r/t the global Eq. 64/65 advisory "
        "capacity implies, as a positive compression magnitude. It is the demand the "
        "global mode would have to reach, and exists to make the "
        "global_elastic_applicability comparison readable."
    ),
    "global_elastic_applicability": (
        "Screen, not a capacity, and unlike the inter-ring result's "
        "elastic_applicability it compares a capacity stress rather than the applied "
        "working stress: 'exceeded' means "
        "global_critical_circumferential_membrane_stress_mpa stands above "
        "elastic_applicability_limit_mpa, so the global pressure is an elastic upper "
        "bound. NASA gives plasticity factors for unstiffened cylinders only, so that "
        "bound is labelled rather than corrected. 'undetermined' means neither a "
        "proportional limit nor a yield strength was supplied, or the mode search "
        "produced no pressure to screen. On a record another gate already withheld, "
        "an exceedance joins validity_violations instead of adding a pending-"
        "validation note: no advisory pressure exists for one to describe."
    ),
    "advisory_governing_status": (
        "Whether the selected advisory_governing_pressure_mpa is an elastic upper "
        "bound: 'advisory_pending_plasticity' when the winning mode's critical "
        "membrane stress exceeds elastic_applicability_limit_mpa, "
        "'advisory_plasticity_undetermined' when no limit was available to screen it, "
        "and 'advisory' otherwise. Null when every mode was withheld. It describes the "
        "selected mode alone, so read global_elastic_applicability alongside it: the "
        "global capacity is regularly over the limit while a lower inter-ring capacity "
        "wins the minimum and reports a plain 'advisory'. The whole result stays "
        "advisory in every case."
    ),
    "working_circumferential_membrane_stress_mpa": (
        "Applied thin-shell circumferential membrane stress p*r/t at the mid-surface "
        "radius, as a positive compression magnitude. It is the demand counterpart of "
        "correlated_critical_circumferential_stress_mpa and exists to make the "
        "elastic_applicability comparison readable; it is not a capacity or a margin."
    ),
    "advisory_candidate_modes": (
        "The modes that entered the advisory_governing_mode minimum, which admits every "
        "mode whose pressure was not withheld, one labelled an elastic upper bound "
        "included, because plasticity could only reduce that elastic estimate. A mode "
        "absent here was withheld rather than compared, so advisory_governing_mode "
        "naming the global mode does not by itself mean the inter-ring result lost; read "
        "capacity_status and inter_ring_shell_buckling.capacity_status for which "
        "withheld it."
    ),
}


def _unitized_result_schema(
    result_type: (
        type[TubeStressResult]
        | type[HemisphereResult]
        | type[FlatCircularPlateResult]
        | type[SmoothCylinderBucklingResult]
        | type[RingShellResult]
        | type[SubmergedMassResult]
    ),
    units: dict[str, str],
    *,
    nested_definitions: tuple[tuple[str, dict[str, str]], ...] = (),
) -> dict[str, Any]:
    schema = TypeAdapter(result_type).json_schema()
    schema["additionalProperties"] = False

    def unitize(properties: dict[str, Any], mapping: dict[str, str]) -> None:
        for name, unit in mapping.items():
            value_schema = properties[name]
            title = value_schema.pop("title", name)
            properties[name] = {
                "additionalProperties": False,
                "properties": {
                    "unit": {"const": unit, "type": "string"},
                    "value": value_schema,
                },
                "required": ["value", "unit"],
                "title": title,
                "type": "object",
            }

    def annotate(properties: dict[str, Any]) -> None:
        for name, description in _RESULT_FIELD_DESCRIPTIONS.items():
            if name in properties:
                properties[name]["description"] = description

    unitize(schema["properties"], units)
    annotate(schema["properties"])
    for definition, nested_units in nested_definitions:
        nested = schema["$defs"][definition]
        nested["additionalProperties"] = False
        unitize(nested["properties"], nested_units)
        annotate(nested["properties"])
    return schema


_FAILURE_CATEGORY_CONTRACT = {
    "allowed": list(get_args(MaterialFailureCategory)),
    "dimensionless": True,
    "role": "selects the strength a stress model reads and the stress it is compared with",
}
_STRENGTH_CONTRACTS = {
    "yield_strength": {
        "dimension": "pressure",
        "normalized_unit": "MPa",
        "role": "ductile_metal: compared with the von Mises (shell) or surface bending (plate) stress",
    },
    "working_strength": {
        "dimension": "pressure",
        "normalized_unit": "MPa",
        "role": "plastic: compared with the maximum hoop (shell) or surface bending (plate) stress",
    },
    "ultimate_compressive_strength": {
        "dimension": "pressure",
        "normalized_unit": "MPa",
        "role": "brittle: compared with the maximum hoop (shell) and seat bearing stress",
    },
    "ultimate_tensile_strength": {
        "dimension": "pressure",
        "normalized_unit": "MPa",
        "role": "brittle: compared with the plate's surface bending stress",
    },
}
_SHELL_STRENGTH_CONTRACTS = {
    name: contract
    for name, contract in _STRENGTH_CONTRACTS.items()
    if name != "ultimate_tensile_strength"
}
_BUCKLING_STRENGTH_CONTRACTS = {
    "yield_strength": {
        "dimension": "pressure",
        "normalized_unit": "MPa",
        "optional": True,
        "role": "ductile_metal only; read to bound the proportional limit",
    },
}
# The strength each category must carry, per model family: a shell reads the
# category's first strength; the plate also reads a brittle tensile strength.
_SHELL_STRENGTH_BY_CATEGORY = {
    category: [names[0]] for category, names in CATEGORY_STRENGTHS.items()
}
_PLATE_STRENGTH_BY_CATEGORY = {
    category: list(names) for category, names in CATEGORY_STRENGTHS.items()
}


def _describe_model(
    model: str,
    *,
    cli_options: Mapping[str, str],
    size_cli_options: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    """One model's contract; the option maps come from the typer command signatures."""
    if model == "tube":
        available_operations = ["forward", "size"]
        model_id, model_version = TUBE_STRESS_MODEL_ID, TUBE_STRESS_MODEL_VERSION
        function = "closed_end_tube_stress"
        module = "pv_calc.pressure_vessel"
        sources = [
            TUBE_THIN_SOURCE,
            TUBE_THICK_SOURCE,
            MATERIAL_FAILURE_SOURCE,
            TUBE_THIN_DISPLACEMENT_SOURCE,
            TUBE_THICK_DISPLACEMENT_SOURCE,
        ]
        assumptions = list(TUBE_SCOPE_NOTES)
        checks = [
            "closed-end thin-wall mean-radius membrane stress",
            "closed-end thick-wall Lame radial, hoop, and axial stress",
            (
                "material failure under the category's criterion: von Mises stress against "
                "yield strength for a ductile metal, maximum hoop stress against the working "
                "strength for a plastic or the ultimate compressive strength for a brittle material"
            ),
            (
                "scalar radial displacement at each stress-state radius, uniform axial "
                "strain, and the axial length change over a supplied gauge length, "
                "released only with both elastic properties"
            ),
        ]
        omissions = [
            "shell stability",
            "end closures",
            "tube/endcap interface and local effects",
            (
                "displacement from junction effects, local restraint at closures, "
                "ovalization, instability, plasticity, and ring-frame restraint"
            ),
        ]
        material_properties = {
            "failure_category": _FAILURE_CATEGORY_CONTRACT,
            **_SHELL_STRENGTH_CONTRACTS,
            "elastic_modulus": {
                "dimension": "pressure",
                "normalized_unit": "MPa",
                "optional": True,
                "role": "required with poisson_ratio to release displacement",
            },
            "poisson_ratio": {
                "dimensionless": True,
                "exclusive_range": [0, 0.5],
                "optional": True,
                "role": "required with elastic_modulus to release displacement",
            },
        }
        request_type: type[ContractModel] = TubeRequest
        output_schema = _unitized_result_schema(
            TubeStressResult,
            TUBE_RESULT_UNITS,
            nested_definitions=(("TubeStressState", TUBE_STATE_UNITS),),
        )
    elif model == "hemisphere":
        available_operations = ["forward"]
        model_id, model_version = HEMISPHERE_MODEL_ID, HEMISPHERE_MODEL_VERSION
        function = "hemispherical_head_external_pressure"
        module = "pv_calc.pressure_vessel"
        sources = [
            HEMISPHERE_THIN_STRESS_SOURCE,
            HEMISPHERE_THICK_STRESS_SOURCE,
            MATERIAL_FAILURE_SOURCE,
            HEMISPHERE_BUCKLING_SOURCE,
            HEMISPHERE_SOFTWARE_PARITY_SOURCE,
            HEMISPHERE_MEMBRANE_DISPLACEMENT_SOURCE,
            SEAT_BEARING_STRESS_SOURCE,
        ]
        assumptions = list(HEMISPHERE_SCOPE_NOTES)
        checks = [
            "thin biaxial spherical membrane stress or thick-sphere Lame stress",
            "material failure under the category's criterion, as for the tube",
            "average seat bearing stress on the equator annulus, its failure pressure and margin",
            "classical Zoelly elastic pressure and NASA SP-8032 clamped-cap correlation",
            "Roark probable-minimum comparator",
            "thin-shell, lambda, and explicit proportional-limit buckling release gates",
            "thin-branch membrane radial displacement, withheld on the thick branch",
        ]
        omissions = [
            "equator-junction bending, bearing-contact distribution, attachment, and seal response",
            "cutouts, penetrations, thickness variation, and local flat spots",
            "plastic buckling interaction and inelastic material corrections",
            "fabrication imperfections, residual stress, and pressure-hull safety factors",
            "thick-sphere displacement, displacement fields, post-buckling deformation, and "
            "ring-stiffened service displacement",
        ]
        material_properties = {
            "elastic_modulus": {"dimension": "pressure", "normalized_unit": "MPa"},
            "failure_category": _FAILURE_CATEGORY_CONTRACT,
            "poisson_ratio": {"dimensionless": True, "exclusive_range": [0, 0.5]},
            **_SHELL_STRENGTH_CONTRACTS,
            "proportional_limit": {
                "dimension": "pressure",
                "normalized_unit": "MPa",
                "role": "required elastic applicability limit for released buckling capacity",
            },
        }
        request_type = HemisphereRequest
        output_schema = _unitized_result_schema(
            HemisphereResult,
            HEMISPHERE_RESULT_UNITS,
            nested_definitions=((
                "HemisphereStressState",
                HEMISPHERE_STRESS_STATE_UNITS,
            ),),
        )
    elif model == "plate":
        available_operations = ["forward", "size"]
        model_id, model_version = FLAT_CIRCULAR_PLATE_MODEL_ID, FLAT_CIRCULAR_PLATE_MODEL_VERSION
        function = "flat_circular_plate"
        module = "pv_calc.pressure_vessel"
        sources = [FLAT_CIRCULAR_PLATE_SOURCE, MATERIAL_FAILURE_SOURCE, SEAT_BEARING_STRESS_SOURCE]
        assumptions = [
            "Uniform transverse pressure on a flat circular plate.",
            "The declared fixed or simply-supported boundary is an idealization.",
            *FLAT_CIRCULAR_PLATE_SCOPE_NOTES,
        ]
        checks = [
            "fixed or simply-supported surface bending stress",
            (
                "center deflection, released on its own swept-FEA validity floor "
                "and subject to the small-deflection check"
            ),
            "transverse shear response",
            (
                "material failure pressure and margin under the category's criterion: surface "
                "bending stress against yield strength (ductile metal), working strength "
                "(plastic), or ultimate tensile strength (brittle); the margin is released "
                "on its own swept-FEA validity floor and subject to the small-deflection "
                "check, and the failure pressure is published either way"
            ),
            (
                "average seat bearing stress, failure pressure, and margin when an "
                "outside radius is supplied"
            ),
        ]
        omissions = [
            "bearing-contact distribution outside the average seat stress",
            "attachment and seal response",
            "penetrations and local-edge details",
        ]
        material_properties = {
            "elastic_modulus": {"dimension": "pressure", "normalized_unit": "MPa"},
            "failure_category": _FAILURE_CATEGORY_CONTRACT,
            "poisson_ratio": {"dimensionless": True, "exclusive_range": [0, 0.5]},
            **_STRENGTH_CONTRACTS,
        }
        request_type = PlateRequest
        output_schema = _unitized_result_schema(FlatCircularPlateResult, PLATE_RESULT_UNITS)
    elif model == "smooth-buckling":
        available_operations = ["forward", "size"]
        model_id = SMOOTH_CYLINDER_BUCKLING_MODEL_ID
        model_version = SMOOTH_CYLINDER_BUCKLING_MODEL_VERSION
        function = "smooth_cylinder_external_pressure_buckling"
        module = "pv_calc.pressure_vessel"
        sources = [
            SMOOTH_CYLINDER_BUCKLING_SOURCE,
            SMOOTH_CYLINDER_ROARK_OVERLAP_SOURCE,
        ]
        assumptions = list(SMOOTH_CYLINDER_SCOPE_NOTES)
        checks = [
            "NASA curvature parameter Z and lateral/hydrostatic pressure line loads",
            "continuous-aspect-ratio short Eqs. 19-22 with sqrt(gamma)=0.75 inside",
            "moderate Eqs. 23-25 with sqrt(gamma)=0.75",
            "long oval Eqs. 26-27 with gamma=0.90 and n=2",
            "moderate/long correlation-overlap, thin-tube, and explicit "
            "proportional-limit release gates",
            "Roark case-20 probable-minimum comparator and lobe count",
        ]
        omissions = [
            "released capacity in the moderate/long correlation overlap, where NASA gives no "
            "rule between gamma=0.5625 in Eqs. 23-25 and gamma=0.90 in Eqs. 26-27",
            "inelastic Esec/Etan corrections from NASA Eqs. 30-32, so a correlated critical "
            "membrane stress above the proportional limit releases an elastic upper bound as "
            "released_pending_plasticity rather than a capacity",
            "rings, cutouts, penetrations, fabrication effects, and nonuniform loading",
            "end-restraint capacity increases and safety factors",
        ]
        material_properties = {
            "elastic_modulus": {"dimension": "pressure", "normalized_unit": "MPa"},
            "failure_category": _FAILURE_CATEGORY_CONTRACT,
            "poisson_ratio": {"dimensionless": True, "exclusive_range": [0, 0.5]},
            **_BUCKLING_STRENGTH_CONTRACTS,
            "proportional_limit": {
                "dimension": "pressure",
                "normalized_unit": "MPa",
                "role": "required elastic applicability limit for released capacity",
            },
        }
        request_type = SmoothBucklingRequest
        output_schema = _unitized_result_schema(
            SmoothCylinderBucklingResult,
            SMOOTH_BUCKLING_RESULT_UNITS,
            nested_definitions=((
                "SmoothCylinderBucklingCandidate",
                SMOOTH_BUCKLING_CANDIDATE_UNITS,
            ),),
        )
    elif model == "ring-shell":
        available_operations = ["forward"]
        model_id = RING_SHELL_MODEL_ID
        model_version = RING_SHELL_MODEL_VERSION
        function = "ring_stiffened_shell_external_pressure"
        module = "pv_calc.pressure_vessel"
        sources = [
            RING_SHELL_SOURCE,
            RING_SHELL_SECTION_SOURCE,
            RING_SHELL_BENCHMARK_SOURCE,
            SMOOTH_CYLINDER_BUCKLING_SOURCE,
        ]
        assumptions = [
            "Hydrostatic closed-end pressure and simply supported global boundary idealization.",
            "Shell radius is the shell mid-surface radius.",
            "Shell and ring use one isotropic material record.",
            "The physical ring is one non-overlapping solid rectangle.",
            "The global result uses NASA Eqs. 64-65 and 82-91, including exact rectangular-ring torsion.",
            "The 0.75 global pressure multiplier is source-recommended and not user-adjustable.",
            "The inter-ring calculation is an advisory isolated smooth bay over ring center spacing.",
        ]
        checks = [
            "solid rectangular A_r, centroidal I_r, eccentricity, and exact Saint-Venant J_r",
            "NASA Eq. 64/65 global pressure before and after the separate Eq. 91 torsion term",
            "expanding integer m,n search with stability, frontier, bounds, and termination evidence",
            "source-gated advisory isolated-bay smooth-shell buckling",
            "the global capacity's implied membrane stress against the proportional limit or yield strength",
            "advisory minimum over every mode that produced a pressure, tagged when it is an elastic upper bound",
            "machine-readable implemented, advisory, not-applicable, and external-blocker dispositions",
        ]
        omissions = [
            "capacity for in-service use because NASA gives no numeric Eq. 64/Eq. 66 long-cylinder transition",
            "inelastic correction of an over-limit global capacity: NASA states plasticity factors for unstiffened cylinders only",
            "validated finite-width inter-ring local skin buckling and local/global interaction",
            "ring material strength, stiffener crippling, and frame tripping or rolling",
            "attachment, weld, residual-stress, tolerance, and fabrication effects",
            "code allowables and safety factors",
        ]
        material_properties = {
            "elastic_modulus": {"dimension": "pressure", "normalized_unit": "MPa"},
            "failure_category": _FAILURE_CATEGORY_CONTRACT,
            "poisson_ratio": {"dimensionless": True, "exclusive_range": [0, 0.5]},
            **_BUCKLING_STRENGTH_CONTRACTS,
            "yield_strength": {
                **_BUCKLING_STRENGTH_CONTRACTS["yield_strength"],
                "role": (
                    "ductile_metal only; read to bound the proportional limit and, failing"
                    " one, as the elastic applicability limit the global capacity is"
                    " screened against"
                ),
            },
            "proportional_limit": {
                "dimension": "pressure",
                "normalized_unit": "MPa",
                "role": (
                    "optional elastic applicability limit for the advisory inter-ring result"
                    " and for the global capacity's implied membrane stress, which falls back"
                    " to the yield strength"
                ),
            },
        }
        request_type = RingShellRequest
        output_schema = _unitized_result_schema(
            RingShellResult,
            RING_SHELL_RESULT_UNITS,
            nested_definitions=(
                ("RingGlobalBucklingResult", RING_GLOBAL_RESULT_UNITS),
                ("RingModeSearchIteration", RING_MODE_SEARCH_ITERATION_UNITS),
                ("SmoothCylinderBucklingResult", SMOOTH_BUCKLING_RESULT_UNITS),
                ("SmoothCylinderBucklingCandidate", SMOOTH_BUCKLING_CANDIDATE_UNITS),
            ),
        )
    elif model == "mass-properties":
        available_operations = ["forward"]
        model_id = SUBMERGED_MASS_MODEL_ID
        model_version = SUBMERGED_MASS_MODEL_VERSION
        function = "submerged_mass_and_buoyancy"
        module = "pv_calc.hydrostatics"
        sources = [SUBMERGED_MASS_SOURCE]
        assumptions = list(SUBMERGED_MASS_SCOPE_NOTES)
        checks = [
            "structural air mass from material density and resolved structural volume",
            "displaced-fluid mass from fluid density and resolved displaced volume",
            "net submerged mass as air mass minus displaced-fluid mass",
            "buoyant-force magnitude, opposing gravity",
            "closed-body consistency: structural volume at or below displaced volume",
        ]
        omissions = [
            "payloads, penetrators, openings, flooding, and trapped gas",
            "centre of gravity, centre of buoyancy, stability, and drag",
            "volumes deformed by pressure",
            "geometry resolution: both volumes come from the caller",
            "any fluid database: fluid density and gravity are request inputs",
        ]
        material_properties = {
            "density": {"dimension": "density", "normalized_unit": "kg/m^3"},
        }
        request_type = MassPropertiesRequest
        output_schema = _unitized_result_schema(
            SubmergedMassResult,
            MASS_PROPERTIES_RESULT_UNITS,
        )
    else:
        raise CalcCliError(
            "unknown_model",
            f"unknown model {model!r}; available describe targets are compare-materials, hemisphere, mass-properties, plate, ring-shell, smooth-buckling, sweep, and tube",
            [
                {
                    "available_models": [
                        "hemisphere",
                        "mass-properties",
                        "plate",
                        "ring-shell",
                        "smooth-buckling",
                        "tube",
                    ],
                    "available_operations": ["compare-materials", "sweep"],
                }
            ],
        )

    # Which strength is required depends on the failure category, so the
    # strengths leave the flat property list and return keyed by category; the
    # buckling models require none, reading a yield strength only when present.
    required_material_properties = {
        name: contract
        for name, contract in material_properties.items()
        if name not in _STRENGTH_CONTRACTS
    }
    if model in {"tube", "hemisphere"}:
        required_material_properties["strength_by_failure_category"] = _SHELL_STRENGTH_BY_CATEGORY
    if model == "plate":
        required_material_properties["strength_by_failure_category"] = _PLATE_STRENGTH_BY_CATEGORY
    if model == "ring-shell":
        required_material_properties.pop("proportional_limit")
    if model == "tube":
        # Elastic properties are reported in properties_used because the model
        # reads them, but a stress-only record is complete without them.
        required_material_properties.pop("elastic_modulus")
        required_material_properties.pop("poisson_ratio")

    description: dict[str, Any] = {
        "assumptions": assumptions,
        "available_operations": available_operations,
        "calculation_source": _calculation_source(
            function,
            model_id,
            model_version,
            module=module,
        ),
        "implemented_checks": checks,
        "input_contract": {
            "cli_dimensioned_options": dict(cli_options),
            "json_quantity_dimensions": quantity_dimensions(request_type),
            "json_schema": request_type.model_json_schema(),
            "stdin": "use --input -",
        },
        "known_omissions": omissions,
        "material_source_rule": (
            "exactly one of a named entry from an explicit --materials-file"
            " database or an explicit property record"
        ),
        "model": model,
        "model_id": model_id,
        "model_version": model_version,
        "output_contract": {
            "material": {
                "properties_used": material_properties,
                "source_fields": ["type", "name", "database", "provenance"],
            },
            "required_top_level_fields": [
                "schema_version", "model", "calculation_source", "material", "result"
            ],
            "result_json_schema": output_schema,
        },
        "required_material_properties": required_material_properties,
        "schema_version": CALC_SCHEMA_VERSION,
        "source_references": sources,
    }
    if model in FAILURE_PRESSURE_FIELDS:
        description["output_contract"]["optional_top_level_fields"] = {
            "mass_properties": (
                "with inputs.submergence: the mass-properties response for the model's own "
                "closed-body volumes and the material density, plus volume_basis"
            ),
            "failure_depths": (
                "with inputs.submergence: each of "
                + ", ".join(FAILURE_PRESSURE_FIELDS[model])
                + " as the depth p / (rho * g) in that fluid, plus basis"
            ),
        }
    if model == "tube":
        description["size_contract"] = _tube_size_contract(output_schema, size_cli_options or {})
    if model == "plate":
        description["size_contract"] = _plate_size_contract(output_schema, size_cli_options or {})
    if model == "smooth-buckling":
        description["size_contract"] = _smooth_buckling_size_contract(size_cli_options or {})
    return description


def _tube_size_contract(
    selected_result_schema: dict[str, Any], cli_options: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "command": "pv-calc tube size",
        "operation_version": TUBE_SIZE_OPERATION_VERSION,
        "varied_input": "wall_thickness",
        "fixed_inputs": [
            "external_pressure",
            "internal_radius",
            "material",
            "force_thick",
        ],
        "declared_check_set": list(TUBE_SIZING_CHECK_SET),
        "minimum_margin": {
            "dimensionless": True,
            "minimum": 0.0,
            "default": 0.0,
        },
        "input_contract": {
            "cli_dimensioned_options": dict(cli_options),
            "json_quantity_dimensions": quantity_dimensions(TubeSizeRequest),
            "json_schema": TubeSizeRequest.model_json_schema(),
            "stdin": "use --input -",
        },
        "output_contract": {
            "complete_forward_contract_at_selected_thickness": True,
            "required_top_level_fields": [
                "schema_version",
                "model",
                "operation",
                "calculation_source",
                "material",
                "result",
                "sizing",
            ],
            "selected_result_json_schema": selected_result_schema,
            "sizing_json_schema": TubeSizingMetadata.model_json_schema(),
        },
        "failure": {
            "error_codes": [
                "invalid_bounds",
                "no_reliable_solution",
                "unevaluable_model",
            ],
            "exit_status": "nonzero",
            "scope": "inverse solver; common input and material errors use the CLI error contract",
        },
    }


def _plate_size_contract(
    selected_result_schema: dict[str, Any], cli_options: Mapping[str, str]
) -> dict[str, Any]:
    return {
        "assumptions": [
            "One plate and one variable: the plate thickness, solved for"
            " inside the caller's bounds, with the free radius, pressure,"
            " edge condition, and material held fixed. No shell variable is"
            " coupled to it.",
            "The two constraints carry separate targets, because they are not"
            " the same kind of thing: inputs.minimum_margin is the bending"
            " margin, and inputs.maximum_deflection is a limit, met at margin"
            " zero. Both margins keep the allowable/actual - 1 form the models"
            " use, the second against the caller's own limit.",
            "Both released margins rise smoothly with thickness, the bending"
            " stress as (free_radius/thickness)^2 and the centre deflection as"
            " 1/thickness^3, so the bounds are one continuous piece and there"
            " is no branch boundary to partition at. That rise is still"
            " verified against every evaluated thickness before any solution"
            " is returned.",
            "The two outputs carry separate FEA-derived evidence floors on"
            " free_diameter/thickness, and both are upper limits on thickness,"
            " so they move as the search varies it and are re-read at every"
            " candidate rather than resolved once.",
            "Only the outputs this request needs are required: without a"
            " maximum deflection the centre deflection constrains nothing and"
            " its stricter floor never decides anything.",
            "A withheld output is not a margin. Any thickness the search has"
            " to evaluate whose needed bending or centre deflection the model"
            " withholds ends the operation with no_reliable_solution, naming"
            " the thickness, the withheld outputs, and the reasons.",
        ],
        "command": "pv-calc plate size",
        "possible_check_set": [
            PLATE_SIZING_BENDING_CHECK,
            PLATE_SIZING_DEFLECTION_CHECK,
        ],
        "declared_check_rule": {
            PLATE_SIZING_BENDING_CHECK: "always",
            PLATE_SIZING_DEFLECTION_CHECK: (
                "only when inputs.maximum_deflection is supplied"
            ),
        },
        "fixed_inputs": [
            "external_pressure",
            "free_radius",
            "boundary_condition",
            "material",
        ],
        "input_contract": {
            "cli_dimensioned_options": dict(cli_options),
            "json_quantity_dimensions": quantity_dimensions(PlateSizeRequest),
            "json_schema": PlateSizeRequest.model_json_schema(),
            "stdin": "use --input -",
        },
        "known_omissions": [
            "the shell: no cylinder variable is coupled to the closure, and"
            " the wall-thickness operations are separate",
            "material selection, mass, and cost: one material is held fixed",
            "any second variable, including the free radius and the edge"
            " condition",
            "thick-plate shear-deformation bending and large-deflection"
            " membrane action: both are outside the released model, so"
            " thicknesses that need them are refused rather than approximated",
        ],
        "maximum_deflection": {
            "dimension": "length",
            "optional": True,
            "role": (
                "caller serviceability limit on the released Kirchhoff centre"
                " deflection; the"
                f" {PLATE_SIZING_DEFLECTION_CHECK} check is declared only when"
                " it is supplied, at target margin 0.0, and then requires that"
                " output's own stricter evidence floor"
            ),
        },
        "minimum_margin": {
            "default": 0.0,
            "dimensionless": True,
            "minimum": 0.0,
            "role": f"target margin for {PLATE_SIZING_BENDING_CHECK}",
        },
        "operation_version": PLATE_SIZE_OPERATION_VERSION,
        "output_contract": {
            "complete_forward_contract_at_selected_thickness": True,
            "required_top_level_fields": [
                "schema_version",
                "model",
                "operation",
                "calculation_source",
                "material",
                "result",
                "sizing",
            ],
            "selected_result_json_schema": selected_result_schema,
            "sizing_json_schema": PlateSizingMetadata.model_json_schema(),
        },
        "varied_input": "plate_thickness",
        "failure": {
            "error_codes": [
                "invalid_bounds",
                "no_reliable_solution",
                "unevaluable_model",
            ],
            "exit_status": "nonzero",
            "scope": "inverse solver; common input and material errors use the CLI error contract",
        },
    }


def _smooth_buckling_size_contract(cli_options: Mapping[str, str]) -> dict[str, Any]:
    return {
        "assumptions": [
            "One cylinder and one variable: the wall thickness, solved for"
            " inside the caller's bounds, with the internal radius, unsupported"
            " length, pressure, and material held fixed.",
            "The buckling model's shell mid-surface radius is not an input. It"
            " is internal_radius + wall_thickness / 2 at every candidate"
            " thickness, which is the tube model's own mean radius, so both"
            " checks read the same cylinder.",
            "The load case is not an input either: the shell stress check has only"
            " the closed-end hydrostatic one, so the buckling check uses the"
            " matching hydrostatic_closed_end case.",
            "The bounds are partitioned at every branch boundary that applies:"
            " the tube model's thin-to-thick transition, the buckling model's"
            " thin-shell limit, and the four NASA regime boundaries, whose"
            " thicknesses are solved for rather than assumed, because they"
            " depend on the correlation factor gamma and on the mid-surface"
            " radius that moves with the thickness.",
            "Inside one branch the minimum margin is expected to rise with"
            " thickness, and that is verified against every evaluated"
            " thickness before any solution is returned.",
            "A smooth-cylinder capacity that is withheld, or released only as"
            " an elastic upper bound pending plasticity, is not a sizing margin."
            " Any thickness the search has to evaluate that reaches either state"
            " ends the operation with no_reliable_solution, naming the thickness,"
            " the regime, the capacity status, and the reasons.",
            "For a ductile metal, whenever the buckling capacity is fully"
            " released, the buckling margin is the smaller of the two: the"
            " released status requires the correlated critical circumferential"
            " stress to be at or below the proportional limit,"
            " which is at or below the yield"
            " strength, while von Mises yielding could only govern above"
            " 2/sqrt(3) times the yield strength. A plastic's working strength"
            " or a brittle material's ultimate compressive strength is not"
            " ordered against its proportional limit, so either check may"
            " govern. The governing check is reported at every evaluated"
            " thickness rather than assumed.",
        ],
        "command": "pv-calc smooth-buckling size",
        "declared_check_set": list(SMOOTH_BUCKLING_SIZING_CHECK_SET),
        "derived_branch_boundaries": [
            _SMOOTH_BUCKLING_TUBE_BRANCH_BOUNDARY,
            _SMOOTH_BUCKLING_THIN_SHELL_BOUNDARY,
            *(name for name, _, _, _ in _SMOOTH_BUCKLING_REGIME_BOUNDARIES),
        ],
        "fixed_inputs": [
            "external_pressure",
            "internal_radius",
            "unsupported_length",
            "material",
        ],
        "input_contract": {
            "cli_dimensioned_options": dict(cli_options),
            "json_quantity_dimensions": quantity_dimensions(SmoothBucklingSizeRequest),
            "json_schema": SmoothBucklingSizeRequest.model_json_schema(),
            "stdin": "use --input -",
        },
        "known_omissions": [
            "end closures: neither endcap is sized, and the flat-plate and"
            " hemispherical models are separate operations",
            "material selection, mass, and cost: one material is held fixed",
            "any second variable, including unsupported length, ring spacing,"
            " and ring geometry",
            "the withheld moderate/long overlap, and every thickness whose"
            " capacity is released only as an elastic upper bound pending"
            " plasticity: neither carries a sizing capacity, so no thickness"
            " inside them can be selected",
        ],
        "load_case": SMOOTH_BUCKLING_SIZING_LOAD_CASE,
        "minimum_margin": {
            "default": 0.0,
            "dimensionless": True,
            "minimum": 0.0,
        },
        "operation_version": SMOOTH_BUCKLING_SIZE_OPERATION_VERSION,
        # Beyond the forward model's requirements: the shell stress check reads
        # the category's strength, and the buckling capacity the proportional limit.
        "required_material_properties": {
            "strength_by_failure_category": _SHELL_STRENGTH_BY_CATEGORY,
            "proportional_limit": {
                "dimension": "pressure",
                "normalized_unit": "MPa",
                "role": "required to release buckling capacity, so required for any solution",
            },
        },
        "output_contract": {
            "complete_forward_contract_at_selected_thickness": True,
            "required_top_level_fields": [
                "schema_version",
                "model",
                "operation",
                "selected_results",
                "sizing",
            ],
            "selected_results_fields": ["smooth-buckling", "tube"],
            "sizing_json_schema": SmoothBucklingSizingMetadata.model_json_schema(),
        },
        "shell_mid_surface_radius_convention": (
            SMOOTH_BUCKLING_SIZING_RADIUS_CONVENTION
        ),
        "varied_input": "wall_thickness",
        "failure": {
            "error_codes": [
                "invalid_bounds",
                "invalid_material",
                "no_reliable_solution",
                "unevaluable_model",
            ],
            "exit_status": "nonzero",
            "scope": "inverse solver; common input and material errors use the CLI error contract",
        },
    }


def _describe_sweep(cli_options: Mapping[str, str]) -> dict[str, Any]:
    return {
        "assumptions": [
            "The swept request is one complete forward request; its own"
            f" {SWEEP_SWEPT_INPUT} is replaced at every point and is otherwise"
            " unused.",
            "Each point runs that model's single-point validation, material"
            " resolution, kernel, and serialization path, so a point response"
            " equals the response of the same single-point invocation.",
            "The axis is exactly one variable: external pressure, or depth.",
            "A depth axis converts each depth with"
            " pv_calc.hydrostatics.external_pressure_from_depth and runs the"
            f" model at the {SWEEP_DEPTH_SUBSTITUTED_PRESSURE},"
            " rho*g*h*design_factor. The service pressure rho*g*h is reported"
            " at every point and drives no model.",
            "Both reported pressures are differentials across the wall with the"
            " interior held at zero gauge; no absolute pressure is formed.",
            "A list axis substitutes the caller's quantities unchanged, in the"
            " order given.",
            "A range axis interpolates in MPa, or in m for a depth axis, as"
            " start*(1 - w) + stop*w with w = i/(count - 1), so the first and"
            " last points are exactly the requested endpoints.",
            "A withheld capacity is a normal point result. A point that cannot"
            " be evaluated fails the whole sweep with that point's own error"
            " code and message.",
        ],
        "depth_axis": {
            "calculation_source": _calculation_source(
                "external_pressure_from_depth",
                HYDROSTATIC_PRESSURE_MODEL_ID,
                HYDROSTATIC_PRESSURE_MODEL_VERSION,
                module="pv_calc.hydrostatics",
            ),
            "pressure_reference_convention": (
                "differential_across_wall_interior_at_zero_gauge"
            ),
            "required_inputs": ["depth", "fluid_density", "gravity", "design_factor"],
            "source_reference": HYDROSTATIC_PRESSURE_SOURCE,
            "substituted_pressure": SWEEP_DEPTH_SUBSTITUTED_PRESSURE,
        },
        "input_contract": {
            "cli_dimensioned_options": dict(cli_options),
            "json_quantity_dimensions": quantity_dimensions(SweepRequest),
            "json_schema": SweepRequest.model_json_schema(),
            "request_source_rule": (
                "the swept forward request comes only from --input; the sweep"
                " adds no per-model options"
            ),
            "stdin": "use --input -",
        },
        "known_omissions": [
            "inverse operations: the swept request is a forward request",
            "adaptive sampling and interpolation between evaluated points",
            "plotting, tabular export, and persisted output",
            "multiprocessing: points are evaluated in order in one process",
            "absolute pressure, internal gas compression, layered fluids, and"
            " depth-varying density profiles on the depth axis",
        ],
        "operation": "sweep",
        "operation_version": SWEEP_OPERATION_VERSION,
        "output_contract": {
            "complete_single_point_response_per_point": True,
            "point_fields": {
                "depth": [
                    "depth",
                    "service_external_pressure",
                    "design_external_pressure",
                    "response",
                ],
                "external_pressure": ["external_pressure", "response"],
            },
            "required_top_level_fields": [
                "schema_version",
                "operation",
                "model",
                "sweep",
            ],
            "sweep_fields": {
                "depth": [
                    "axis",
                    "depth_to_pressure",
                    "operation_version",
                    "points",
                    "swept_input",
                ],
                "external_pressure": [
                    "axis",
                    "operation_version",
                    "points",
                    "swept_input",
                ],
            },
        },
        "failure": {
            "error_codes": [
                "axis_source_conflict",
                "invalid_number",
                "invalid_quantity",
                "invalid_request",
                "missing_input",
            ],
            "exit_status": "nonzero",
            "scope": (
                "axis and request-source selection; a failing point reports the"
                " single-point error code with its axis position added"
            ),
        },
        "schema_version": CALC_SCHEMA_VERSION,
        "supported_models": list(FORWARD_MODELS),
        "swept_input": SWEEP_SWEPT_INPUT,
        "axis_variables": list(SWEEP_AXIS_VARIABLES),
    }


def _describe_material_comparison() -> dict[str, Any]:
    return {
        "assumptions": [
            "The compared request is one complete forward request; its own"
            f" {COMPARE_MATERIALS_SUBSTITUTED_INPUT} is replaced for every"
            " listed material and is otherwise unused.",
            "Each entry runs that model's single-point validation, material"
            " resolution, kernel, and serialization path, so an entry equals"
            " the response of the same single-material invocation.",
            "Every compared material is a named entry in the explicit"
            " --materials-file database; the list carries no explicit property"
            " records.",
            "Entries are returned in the caller's order, once per listed"
            " material, including repeats.",
            "With inputs.mass_properties, each entry also carries the"
            " mass-properties response for that material, from the same two"
            " volumes, fluid density, and gravity.",
            "A listed material whose record lacks a property the requested"
            " calculations read carries outcome invalid_material with that"
            " model's own message and no result; the remaining entries are"
            " unaffected and the comparison still exits zero.",
            "A withheld capacity is a normal entry result.",
        ],
        "entry_outcomes": {
            "evaluated": (
                "the complete forward response, and the mass-properties"
                " response when the request supplies its volume inputs"
            ),
            "invalid_material": (
                "no result: the named record lacks a property the requested"
                " calculations read, and the model's own invalid_material"
                " message is carried as this entry's outcome"
            ),
        },
        "input_contract": {
            "cli_options": {
                "--material": (
                    "named --materials-file entry; repeat once per compared"
                    " material, in order"
                ),
                "--materials-file": (
                    "materials database every listed material is resolved from"
                ),
            },
            "json_quantity_dimensions": quantity_dimensions(MaterialComparisonRequest),
            "json_schema": MaterialComparisonRequest.model_json_schema(),
            "material_list_source_rule": (
                "exactly one material list: the request's inputs, or repeated"
                " --material options"
            ),
            "request_source_rule": (
                "the compared forward request comes only from --input; the"
                " comparison adds no per-model options"
            ),
            "stdin": "use --input -",
        },
        "known_omissions": [
            "scoring, ranking, recommending, and narrating: entries are"
            " returned unordered by merit, in the caller's order",
            "inferred properties: a missing property is reported, never"
            " filled in from another property",
            "explicit property records in the compared list: every compared"
            " material is a named database entry",
            "geometry, thickness, and load variation: exactly one fixed"
            " request is compared, and pv-calc sweep varies the load",
            "geometry resolution for mass properties: both volumes are the"
            " caller's and are the same for every material",
        ],
        "operation": "compare-materials",
        "operation_version": COMPARE_MATERIALS_OPERATION_VERSION,
        "output_contract": {
            "complete_single_material_response_per_entry": True,
            "entry_fields": {
                "evaluated": [
                    "material",
                    "outcome",
                    "response",
                    "mass_properties (only with inputs.mass_properties)",
                ],
                "invalid_material": ["material", "outcome", "message"],
            },
            "entry_order": "the caller's inputs.materials order",
            "comparison_fields": [
                "entries",
                "operation_version",
                "substituted_input",
            ],
            "required_top_level_fields": [
                "schema_version",
                "operation",
                "model",
                "comparison",
            ],
        },
        "failure": {
            "error_codes": [
                "invalid_material_database",
                "invalid_request",
                "material_source_conflict",
                "missing_input",
                "missing_materials_file",
                "unknown_material",
            ],
            "exit_status": "nonzero",
            "scope": (
                "material-list and request-source selection, and any failure"
                " that is not one material's missing property; such a failure"
                " reports the single-material error code with the failing"
                " entry's position added"
            ),
        },
        "schema_version": CALC_SCHEMA_VERSION,
        "substituted_input": COMPARE_MATERIALS_SUBSTITUTED_INPUT,
        "supported_models": list(FORWARD_MODELS),
    }
