"""Response assembly: result unit maps, quantity wrapping, and the response envelope."""

from __future__ import annotations

import json
from dataclasses import asdict
from typing import Any, Literal

from pv_calc import __version__
from pv_calc.contracts import CALC_SCHEMA_VERSION, _quantity
from pv_calc.errors import CalcCliError
from pv_calc.hydrostatics import SubmergedMassResult
from pv_calc.pressure_vessel import (
    FlatCircularPlateResult,
    HemisphereResult,
    RingShellResult,
    SmoothCylinderBucklingResult,
    TubeStressResult,
)
from pv_calc.resolve import ResolvedMassMaterial, ResolvedMaterial

TUBE_RESULT_UNITS = {
    "internal_radius_mm": "mm",
    "external_radius_mm": "mm",
    "mean_radius_mm": "mm",
    "wall_thickness_mm": "mm",
    "axial_length_mm": "mm",
    "external_pressure_mpa": "MPa",
    "strength_mpa": "MPa",
    "elastic_modulus_mpa": "MPa",
    "governing_radius_mm": "mm",
    "governing_stress_mpa": "MPa",
    "theoretical_failure_pressure_mpa": "MPa",
    "axial_length_change_mm": "mm",
}
TUBE_STATE_UNITS = {
    "radius_mm": "mm",
    "radial_stress_mpa": "MPa",
    "hoop_stress_mpa": "MPa",
    "axial_stress_mpa": "MPa",
    "principal_stresses_mpa": "MPa",
    "von_mises_stress_mpa": "MPa",
    "radial_displacement_mm": "mm",
}
HEMISPHERE_RESULT_UNITS = {
    "internal_radius_mm": "mm",
    "external_radius_mm": "mm",
    "mean_radius_mm": "mm",
    "wall_thickness_mm": "mm",
    "external_pressure_mpa": "MPa",
    "elastic_modulus_mpa": "MPa",
    "strength_mpa": "MPa",
    "proportional_limit_mpa": "MPa",
    "governing_radius_mm": "mm",
    "governing_stress_mpa": "MPa",
    "theoretical_stress_failure_pressure_mpa": "MPa",
    "seat_bearing_stress_mpa": "MPa",
    "theoretical_seat_failure_pressure_mpa": "MPa",
    "classical_critical_pressure_mpa": "MPa",
    "nasa_candidate_design_pressure_mpa": "MPa",
    "nasa_candidate_critical_membrane_stress_mpa": "MPa",
    "roark_probable_minimum_pressure_mpa": "MPa",
    "released_buckling_pressure_mpa": "MPa",
    "released_buckling_critical_membrane_stress_mpa": "MPa",
}
HEMISPHERE_STRESS_STATE_UNITS = {
    "radius_mm": "mm",
    "radial_stress_mpa": "MPa",
    "meridional_stress_mpa": "MPa",
    "hoop_stress_mpa": "MPa",
    "principal_stresses_mpa": "MPa",
    "von_mises_stress_mpa": "MPa",
    "radial_displacement_mm": "mm",
}
PLATE_RESULT_UNITS = {
    "external_pressure_mpa": "MPa",
    "free_radius_mm": "mm",
    "free_diameter_mm": "mm",
    "outside_radius_mm": "mm",
    "plate_thickness_mm": "mm",
    "elastic_modulus_mpa": "MPa",
    "strength_mpa": "MPa",
    "compressive_strength_mpa": "MPa",
    "flexural_rigidity_n_mm": "N*mm",
    "maximum_radial_bending_stress_mpa": "MPa",
    "maximum_tangential_bending_stress_mpa": "MPa",
    "governing_bending_stress_mpa": "MPa",
    "transverse_shear_stress_mpa": "MPa",
    "maximum_deflection_mm": "mm",
    "shear_corrected_deflection_estimate_mm": "mm",
    "released_maximum_deflection_mm": "mm",
    "theoretical_radial_failure_pressure_mpa": "MPa",
    "theoretical_tangential_failure_pressure_mpa": "MPa",
    "theoretical_failure_pressure_mpa": "MPa",
    "seat_bearing_stress_mpa": "MPa",
    "theoretical_seat_failure_pressure_mpa": "MPa",
}
SMOOTH_BUCKLING_RESULT_UNITS = {
    "external_pressure_mpa": "MPa",
    "shell_mid_surface_radius_mm": "mm",
    "wall_thickness_mm": "mm",
    "unsupported_length_mm": "mm",
    "elastic_modulus_mpa": "MPa",
    "yield_strength_mpa": "MPa",
    "proportional_limit_mpa": "MPa",
    "flexural_rigidity_n_mm": "N*mm",
    "circumferential_line_load_n_per_mm": "N/mm",
    "axial_line_load_n_per_mm": "N/mm",
    "ideal_critical_pressure_mpa": "MPa",
    "correlated_critical_pressure_mpa": "MPa",
    "correlated_critical_circumferential_stress_mpa": "MPa",
    "working_circumferential_membrane_stress_mpa": "MPa",
    "elastic_applicability_limit_mpa": "MPa",
    "roark_probable_minimum_pressure_mpa": "MPa",
}
SMOOTH_BUCKLING_CANDIDATE_UNITS = {
    "ideal_critical_pressure_mpa": "MPa",
    "correlated_critical_pressure_mpa": "MPa",
    "correlated_critical_circumferential_stress_mpa": "MPa",
    "eq25_simplified_critical_pressure_mpa": "MPa",
}
RING_SHELL_RESULT_UNITS = {
    "external_pressure_mpa": "MPa",
    "shell_mid_surface_radius_mm": "mm",
    "wall_thickness_mm": "mm",
    "unsupported_length_mm": "mm",
    "ring_spacing_mm": "mm",
    "elastic_modulus_mpa": "MPa",
    "yield_strength_mpa": "MPa",
    "proportional_limit_mpa": "MPa",
    "ring_axial_width_mm": "mm",
    "ring_radial_height_mm": "mm",
    "ring_area_mm2": "mm^2",
    "ring_centroid_from_shell_surface_mm": "mm",
    "ring_centroidal_inertia_mm4": "mm^4",
    "ring_torsional_constant_mm4": "mm^4",
    "ring_eccentricity_from_shell_mid_surface_mm": "mm",
    "torsion_ideal_pressure_effect_mpa": "MPa",
    "torsion_adjusted_pressure_effect_mpa": "MPa",
    "global_critical_circumferential_membrane_stress_mpa": "MPa",
    "elastic_applicability_limit_mpa": "MPa",
    "advisory_governing_pressure_mpa": "MPa",
}
RING_GLOBAL_RESULT_UNITS = {
    "ideal_critical_pressure_mpa": "MPa",
    "adjusted_critical_pressure_mpa": "MPa",
    "ring_eccentricity_from_shell_mid_surface_mm": "mm",
    "ring_torsion_contribution_n_mm": "N*mm",
    "orthotropic_extensional_x_n_per_mm": "N/mm",
    "orthotropic_extensional_y_n_per_mm": "N/mm",
    "orthotropic_extensional_xy_n_per_mm": "N/mm",
    "orthotropic_shear_xy_n_per_mm": "N/mm",
    "orthotropic_bending_x_n_mm": "N*mm",
    "orthotropic_bending_y_n_mm": "N*mm",
    "orthotropic_bending_xy_n_mm": "N*mm",
    "orthotropic_coupling_y_n": "N",
}
RING_MODE_SEARCH_ITERATION_UNITS = {
    "ideal_critical_pressure_mpa": "MPa",
    "frontier_minimum_pressure_mpa": "MPa",
}
MASS_PROPERTIES_RESULT_UNITS = {
    "solid_volume_m3": "m^3",
    "displaced_volume_m3": "m^3",
    "material_density_kg_per_m3": "kg/m^3",
    "fluid_density_kg_per_m3": "kg/m^3",
    "gravity_m_per_s2": "m/s^2",
    "structural_air_mass_kg": "kg",
    "displaced_fluid_mass_kg": "kg",
    "net_submerged_mass_kg": "kg",
    "buoyant_force_n": "N",
}


def _json_text(payload: dict[str, Any], *, compact: bool) -> str:
    if compact:
        return json.dumps(
            payload,
            allow_nan=False,
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
    return json.dumps(payload, allow_nan=False, ensure_ascii=True, indent=2, sort_keys=True)


def _ensure_json_representable(payload: dict[str, Any]) -> None:
    """Reject a non-finite nested result while its batch position is known."""
    try:
        _json_text(payload, compact=True)
    except (TypeError, ValueError) as exc:
        raise CalcCliError(
            "unevaluable_model",
            "calculation produced a result that cannot be represented as finite JSON",
        ) from exc


def _serialize_result(
    result: (
        TubeStressResult
        | HemisphereResult
        | FlatCircularPlateResult
        | SmoothCylinderBucklingResult
        | RingShellResult
        | SubmergedMassResult
    ),
) -> dict[str, Any]:
    payload = asdict(result)
    if isinstance(result, TubeStressResult):
        units = TUBE_RESULT_UNITS
    elif isinstance(result, HemisphereResult):
        units = HEMISPHERE_RESULT_UNITS
    elif isinstance(result, FlatCircularPlateResult):
        units = PLATE_RESULT_UNITS
    elif isinstance(result, SmoothCylinderBucklingResult):
        units = SMOOTH_BUCKLING_RESULT_UNITS
    elif isinstance(result, SubmergedMassResult):
        units = MASS_PROPERTIES_RESULT_UNITS
    else:
        units = RING_SHELL_RESULT_UNITS
    for name, unit in units.items():
        payload[name] = _quantity(payload[name], unit)
    if isinstance(result, TubeStressResult):
        states: list[dict[str, Any]] = []
        for state in payload["stress_states"]:
            for name, unit in TUBE_STATE_UNITS.items():
                state[name] = _quantity(state[name], unit)
            states.append(state)
        payload["stress_states"] = states
    elif isinstance(result, HemisphereResult):
        states = []
        for state in payload["stress_states"]:
            for name, unit in HEMISPHERE_STRESS_STATE_UNITS.items():
                state[name] = _quantity(state[name], unit)
            states.append(state)
        payload["stress_states"] = states
    elif isinstance(result, SmoothCylinderBucklingResult):
        candidates: list[dict[str, Any]] = []
        for candidate in payload["candidates"]:
            for name, unit in SMOOTH_BUCKLING_CANDIDATE_UNITS.items():
                candidate[name] = _quantity(candidate[name], unit)
            candidates.append(candidate)
        payload["candidates"] = candidates
    elif isinstance(result, RingShellResult):
        for global_name in (
            "global_without_ring_torsion",
            "global_with_ring_torsion",
        ):
            global_result = payload[global_name]
            for name, unit in RING_GLOBAL_RESULT_UNITS.items():
                global_result[name] = _quantity(global_result[name], unit)
            iterations: list[dict[str, Any]] = []
            for iteration in global_result["iterations"]:
                for name, unit in RING_MODE_SEARCH_ITERATION_UNITS.items():
                    iteration[name] = _quantity(iteration[name], unit)
                iterations.append(iteration)
            global_result["iterations"] = iterations
        inter_ring = payload["inter_ring_shell_buckling"]
        for name, unit in SMOOTH_BUCKLING_RESULT_UNITS.items():
            inter_ring[name] = _quantity(inter_ring[name], unit)
        candidates = []
        for candidate in inter_ring["candidates"]:
            for name, unit in SMOOTH_BUCKLING_CANDIDATE_UNITS.items():
                candidate[name] = _quantity(candidate[name], unit)
            candidates.append(candidate)
        inter_ring["candidates"] = candidates
    return payload


def _material_payload(
    material: ResolvedMaterial | ResolvedMassMaterial,
    *,
    model: Literal[
        "tube",
        "plate",
        "smooth-buckling",
        "hemisphere",
        "ring-shell",
        "mass-properties",
    ],
) -> dict[str, Any]:
    properties: dict[str, Any]
    if isinstance(material, ResolvedMassMaterial):
        properties = {"density": _quantity(material.density_kg_per_m3, "kg/m^3")}
    else:
        # Every model that reads a strength record also reads both elastic
        # constants; only the three buckling models read a proportional limit.
        # The stress models read the category's strengths, the plate alone
        # reading a brittle record's tensile strength; the buckling models
        # read a yield strength only to bound the proportional limit.
        strengths = material.strengths_mpa()
        if model in {"smooth-buckling", "ring-shell"}:
            strengths = {k: v for k, v in strengths.items() if k == "yield_strength"}
        elif model != "plate":
            strengths.pop("ultimate_tensile_strength", None)
        properties = {
            "failure_category": material.failure_category,
            **{name: _quantity(value, "MPa") for name, value in strengths.items()},
            "elastic_modulus": _quantity(material.elastic_modulus_mpa, "MPa"),
            "poisson_ratio": material.poisson_ratio,
        }
        if model in {"smooth-buckling", "hemisphere", "ring-shell"}:
            properties["proportional_limit"] = _quantity(
                material.proportional_limit_mpa,
                "MPa",
            )
    return {
        "source": {
            "type": material.source_type,
            "name": material.name,
            "database": material.database,
            "provenance": material.provenance,
        },
        "properties_used": properties,
    }


def _calculation_source(
    function: str,
    model_id: str,
    model_version: str,
    *,
    module: str,
) -> dict[str, Any]:
    return {
        "function": f"{module}.{function}",
        "model_id": model_id,
        "model_version": model_version,
        "package_version": __version__,
    }


def _response(
    *,
    model: Literal[
        "tube",
        "plate",
        "smooth-buckling",
        "hemisphere",
        "ring-shell",
        "mass-properties",
    ],
    result: (
        TubeStressResult
        | HemisphereResult
        | FlatCircularPlateResult
        | SmoothCylinderBucklingResult
        | RingShellResult
        | SubmergedMassResult
    ),
    material: ResolvedMaterial | ResolvedMassMaterial,
    function: str,
    module: str,
) -> dict[str, Any]:
    return {
        "calculation_source": _calculation_source(
            function,
            result.model_id,
            result.model_version,
            module=module,
        ),
        "material": _material_payload(material, model=model),
        "model": model,
        "result": _serialize_result(result),
        "schema_version": CALC_SCHEMA_VERSION,
    }
