"""Compose existing pressure-vessel models into one idealized cylinder assessment.

The composition introduces no joint or shell-interaction model. Optional end
closures meet the tube at two butt planes, with the same bore and outer radius.
"""

from __future__ import annotations

import math
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    Closure as Closure,
    CylinderInputs as CylinderInputs,
    CylinderMaterial as CylinderMaterial,
    CylinderRequest as CylinderRequest,
    HemisphereClosure as HemisphereClosure,
    Mass as Mass,
    PayloadInputs as PayloadInputs,
    PlateClosure as PlateClosure,
    HemisphereInputs,
    HemisphereRequest,
    QuantityInput,
    _quantity,
    _to_unit,
    quantity_dimensions,
)
from pv_calc.errors import CalcCliError
from pv_calc.evaluate import (
    _calculate_plate_result,
    _calculate_smooth_buckling_result,
    _calculate_tube_result,
    _evaluate_hemisphere,
)
from pv_calc.resolve import ResolvedMaterial, _resolve_material
from pv_calc.serialize import _calculation_source, _ensure_json_representable, _response


CYLINDER_MODEL_ID = "cylinder_assessment"
CYLINDER_MODEL_VERSION = "1.0.0"


def describe_cylinder(cli_options: Mapping[str, str] | None = None) -> dict[str, Any]:
    """The strict request schema and the composition's acceptance contract."""
    from pv_calc.describe import _workflow_contract

    return _workflow_contract({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "cylinder",
        "available_operations": ["forward"],
        "calculation_source": _calculation_source(
            "evaluate_cylinder", CYLINDER_MODEL_ID, CYLINDER_MODEL_VERSION,
            module="pv_calc.cylinder",
        ),
        "input_contract": {
            "cli_dimensioned_options": dict(cli_options or {}),
            "json_schema": CylinderRequest.model_json_schema(),
            "json_quantity_dimensions": quantity_dimensions(CylinderRequest),
        },
        "output_contract": {
            "required_top_level_fields": [
                "schema_version", "model", "calculation_source", "load_case",
                "geometry", "assumptions", "components", "assessment", "mass_properties",
            ],
            "components": "Detailed tube, smooth_buckling, and optional closure responses.",
            "assessment": "Required checks report demand, released capacity, margin, "
            "required_margin, applicability, reasons, and pass/fail/indeterminate status. "
            "Any failed check yields fail; otherwise any unavailable check yields "
            "indeterminate. A released zero-demand check passes with a null margin.",
            "mass_properties": "Tube and optional closures add at two non-overlapping "
            "butt planes. Density is optional; missing component density withholds "
            "structural and total mass. Payload mass and volume default to zero. "
            "Payload volume cannot exceed the internal geometric cavity volume.",
        },
        "geometry_constraints": [
            "axial_length defaults to unsupported_length and cannot be shorter.",
            "Optional closures must contain exactly two entries.",
            "Closure bore and outside radius match the cylinder; a hemisphere wall "
            "therefore matches the cylinder wall, and a flat plate has no overhang.",
        ],
    })


def _dimension(
    quantity: QuantityInput, unit: str, name: str, *, zero_allowed: bool = False
) -> float:
    value = _to_unit(quantity, unit, name)
    if value < 0 or (value == 0 and not zero_allowed):
        raise CalcCliError(
            "unevaluable_model",
            f"{name} must be {'non-negative' if zero_allowed else 'positive'}",
        )
    return value


def _check(
    name: str,
    demand: float | None,
    capacity: float | None,
    *,
    unit: str = "MPa",
    required_margin: float = 0.0,
    applicability: str = "released",
    reasons: list[str] | None = None,
) -> dict[str, Any]:
    """Only released, applicable capacities participate in acceptance."""
    released = applicability == "released"
    capacity = capacity if released else None
    margin = (
        capacity / demand - 1.0
        if capacity is not None and demand is not None and demand > 0.0
        else None
    )
    notes = list(reasons or [])
    if not released or demand is None or capacity is None:
        status = "indeterminate"
        if not notes:
            notes.append("The required calculation has no released demand or capacity.")
    elif demand == 0:
        status = "pass"
        notes.append("Zero demand: the capacity-to-demand margin is undefined (null).")
    else:
        status = "pass" if capacity >= demand * (1.0 + required_margin) else "fail"
        if status == "fail":
            notes.append("Released capacity does not meet demand and the required margin.")
    return {
        "id": name,
        "status": status,
        "demand": _quantity(demand, unit),
        "capacity": _quantity(capacity, unit),
        "margin": margin,
        "required_margin": required_margin,
        "applicability": applicability,
        "reasons": notes,
    }


def _assessment(checks: list[dict[str, Any]], *, closures_included: bool) -> dict[str, Any]:
    failures = [check for check in checks if check["status"] == "fail"]
    unresolved = [check for check in checks if check["status"] == "indeterminate"]
    status = "fail" if failures else "indeterminate" if unresolved else "pass"
    # The governing numerical mode is unknown if any required check is
    # unavailable, even when a known failure already establishes rejection.
    candidates = sorted(
        (check for check in checks if check["margin"] is not None and not unresolved),
        key=lambda check: check["margin"] - check["required_margin"],
    )
    omissions = [
        "Seals, leak tightness, closure retention, bolts, welds, and attachment strength.",
        "Local joint stresses, grooves, penetrations, and shell/closure interaction.",
        "Manufacturing imperfections, corrosion, fatigue, and pressure cycling.",
        "Qualification of the assumed end-support and closure boundary conditions.",
    ]
    if not closures_included:
        omissions.insert(0, "End closures: no closure geometry or strength checks were requested.")
    return {
        "status": status,
        "checks": checks,
        "governing_check": candidates[0]["id"] if candidates else None,
        "required_check_coverage": {
            "required": [check["id"] for check in checks],
            "evaluated": [check["id"] for check in checks if check["status"] != "indeterminate"],
            "indeterminate": [check["id"] for check in unresolved],
            "complete": not unresolved,
        },
        "scope": "Acceptance is limited to the requested, idealized component checks; "
        "it is not a housing qualification or a code-compliance determination.",
        "omissions": omissions,
    }


def _mass(
    *,
    parts: list[tuple[str, float, ResolvedMaterial]],
    displaced_volume: float,
    internal_volume: float,
    inputs: CylinderInputs,
) -> dict[str, Any]:
    part_properties: list[dict[str, Any]] = []
    missing: list[str] = []
    known_mass = 0.0
    for name, volume, material in parts:
        density = material.density_kg_per_m3
        if density is None:
            missing.append(name)
        elif density <= 0:
            raise CalcCliError("invalid_material", f"{name} material density must be positive")
        part_mass = volume * density if density is not None else None
        known_mass += part_mass or 0.0
        part_properties.append({
            "id": name,
            "solid_volume": _quantity(volume, "m^3"),
            "density": _quantity(density, "kg/m^3"),
            "structural_mass": _quantity(part_mass, "kg"),
        })
    payload = inputs.payload
    payload_mass = (
        _dimension(payload.mass, "kg", "inputs.payload.mass", zero_allowed=True)
        if payload is not None and payload.mass is not None else 0.0
    )
    payload_volume = (
        _dimension(payload.volume, "m^3", "inputs.payload.volume", zero_allowed=True)
        if payload is not None and payload.volume is not None else 0.0
    )
    if payload_volume > internal_volume and not math.isclose(
        payload_volume, internal_volume, rel_tol=1e-12
    ):
        raise CalcCliError("invalid_request", "inputs.payload.volume exceeds internal geometric volume")
    structural_mass = None if missing else known_mass
    total_mass = structural_mass + payload_mass if structural_mass is not None else None
    result: dict[str, Any] = {
        "components": part_properties,
        "solid_volume": _quantity(sum(part[1] for part in parts), "m^3"),
        "displaced_volume": _quantity(displaced_volume, "m^3"),
        "internal_geometric_volume": _quantity(internal_volume, "m^3"),
        "payload_mass": _quantity(payload_mass, "kg"),
        "payload_volume": _quantity(payload_volume, "m^3"),
        "remaining_internal_volume": _quantity(max(0.0, internal_volume - payload_volume), "m^3"),
        "structural_mass": _quantity(structural_mass, "kg"),
        "total_air_mass": _quantity(total_mass, "kg"),
        "status": "withheld_missing_density" if missing else "calculated",
        "reasons": [f"Material density is missing for {name}." for name in missing],
        "volume_basis": "The tube axial length spans two butt planes. Flat discs extend "
        "outward and add their solid/displaced volume but no cavity volume. Hemispheres "
        "extend outward and add their shell, outer-envelope, and inner-cavity volumes. "
        "There is no overlap, inserted spigot, groove, or joint hardware. Internal volume "
        "is geometric volume, not a guarantee that a payload shape fits.",
    }
    if inputs.closures is None:
        result["volume_basis"] += (
            " With no supplied closures, the closed tube envelope assumes massless, "
            "zero-thickness end planes; structural mass covers only the tube."
        )
    if inputs.submergence is not None:
        rho = _dimension(inputs.submergence.fluid_density, "kg/m^3", "inputs.submergence.fluid_density")
        gravity = _dimension(inputs.submergence.gravity, "m/s^2", "inputs.submergence.gravity")
        displaced_mass = rho * displaced_volume
        result.update({
            "fluid_density": _quantity(rho, "kg/m^3"),
            "gravity": _quantity(gravity, "m/s^2"),
            "displaced_fluid_mass": _quantity(displaced_mass, "kg"),
            "buoyant_force": _quantity(displaced_mass * gravity, "N"),
            "net_submerged_mass": _quantity(
                total_mass - displaced_mass if total_mass is not None else None, "kg"
            ),
        })
    return result


def evaluate_cylinder(
    request: CylinderRequest, materials_file: Path | None = None
) -> dict[str, Any]:
    """Assess one cylinder and, optionally, two compatible idealized closures."""
    inputs = request.inputs
    pressure = _dimension(inputs.external_pressure, "MPa", "inputs.external_pressure", zero_allowed=True)
    inner = _dimension(inputs.internal_radius, "mm", "inputs.internal_radius")
    wall = _dimension(inputs.wall_thickness, "mm", "inputs.wall_thickness")
    span = _dimension(inputs.unsupported_length, "mm", "inputs.unsupported_length")
    length = (
        _dimension(inputs.axial_length, "mm", "inputs.axial_length")
        if inputs.axial_length is not None else span
    )
    if length < span and not math.isclose(length, span, rel_tol=1e-12):
        raise CalcCliError("invalid_request", "inputs.axial_length must be at least unsupported_length")
    outer = inner + wall
    material = _resolve_material(request.material, materials_file)
    target = inputs.minimum_margin
    checks: list[dict[str, Any]] = []
    components: dict[str, Any] = {"closures": []}
    try:
        tube = _calculate_tube_result(
            external_pressure_mpa=pressure, internal_radius_mm=inner,
            wall_thickness_mm=wall, material=material, force_thick=False,
            axial_length_mm=length,
        )
        components["tube"] = _response(
            model="tube", result=tube, material=material,
            function="closed_end_tube_stress", module="pv_calc.pressure_vessel",
        )
        checks.append(_check(
            "cylindrical_shell_stress", pressure, tube.theoretical_failure_pressure_mpa,
            required_margin=target,
        ))
    except CalcCliError as exc:
        if exc.code != "invalid_material":
            raise
        components["tube"] = {"model": "tube", "error": {"code": exc.code, "message": exc.message}}
        checks.append(_check("cylindrical_shell_stress", pressure, None,
                             required_margin=target, applicability="missing_material_property",
                             reasons=[exc.message]))
    try:
        buckling = _calculate_smooth_buckling_result(
            external_pressure_mpa=pressure, shell_mid_surface_radius_mm=inner + wall / 2.0,
            wall_thickness_mm=wall, unsupported_length_mm=span, material=material,
            load_case="hydrostatic_closed_end",
        )
        components["smooth_buckling"] = _response(
            model="smooth-buckling", result=buckling, material=material,
            function="smooth_cylinder_external_pressure_buckling", module="pv_calc.pressure_vessel",
        )
        reasons = [*buckling.validity_violations, *buckling.release_gate_violations]
        if buckling.capacity_status == "released_pending_plasticity":
            reasons.append("The elastic critical stress exceeds the proportional limit; "
                           "the formula pressure is an upper bound pending an inelastic correction.")
        checks.append(_check(
            "smooth_cylinder_buckling", pressure, buckling.correlated_critical_pressure_mpa,
            required_margin=target, applicability=buckling.capacity_status, reasons=reasons,
        ))
    except CalcCliError as exc:
        if exc.code != "invalid_material":
            raise
        components["smooth_buckling"] = {
            "model": "smooth-buckling", "error": {"code": exc.code, "message": exc.message}
        }
        checks.append(_check("smooth_cylinder_buckling", pressure, None,
                             required_margin=target, applicability="missing_material_property",
                             reasons=[exc.message]))
    solid = math.pi * wall * (outer + inner) * length / 1e9
    displaced = math.pi * outer**2 * length / 1e9
    internal = math.pi * inner**2 * length / 1e9
    parts = [("tube", solid, material)]
    for index, closure in enumerate(inputs.closures or []):
        name = f"closure_{index + 1}"
        closure_material = _resolve_material(closure.material, materials_file)
        if isinstance(closure, PlateClosure):
            if closure.outside_radius is not None and not math.isclose(
                _dimension(closure.outside_radius, "mm", f"inputs.closures[{index}].outside_radius"),
                outer, rel_tol=1e-12,
            ):
                raise CalcCliError("invalid_request", "Butt plate outside_radius must equal the "
                                   "cylinder outside radius; overhang/contact geometry is not modeled")
            thickness = _dimension(closure.plate_thickness, "mm", f"inputs.closures[{index}].plate_thickness")
            limit = (
                _dimension(closure.maximum_deflection, "mm", f"inputs.closures[{index}].maximum_deflection")
                if closure.maximum_deflection is not None else None
            )
            try:
                plate = _calculate_plate_result(
                    external_pressure_mpa=pressure, free_radius_mm=inner,
                    plate_thickness_mm=thickness, material=closure_material,
                    boundary_condition=closure.boundary_condition, outside_radius_mm=outer,
                )
                response = _response(
                    model="plate", result=plate, material=closure_material,
                    function="flat_circular_plate", module="pv_calc.pressure_vessel",
                )
                checks.append(_check(
                    f"{name}.flat_endcap_bending", pressure, plate.theoretical_failure_pressure_mpa,
                    required_margin=target, applicability=plate.bending_status,
                    reasons=list(plate.validity_violations),
                ))
                if limit is not None:
                    checks.append(_check(
                        f"{name}.center_deflection", plate.released_maximum_deflection_mm, limit,
                        unit="mm", applicability=plate.deflection_status,
                        reasons=list(plate.deflection_validity_violations),
                    ))
            except CalcCliError as exc:
                if exc.code != "invalid_material":
                    raise
                response = {"model": "plate", "error": {"code": exc.code, "message": exc.message}}
                checks.append(_check(f"{name}.flat_endcap_bending", pressure, None,
                                     required_margin=target, applicability="missing_material_property",
                                     reasons=[exc.message]))
                if limit is not None:
                    checks.append(_check(f"{name}.center_deflection", None, limit,
                                         unit="mm", applicability="missing_material_property",
                                         reasons=[exc.message]))
            closure_solid = math.pi * outer**2 * thickness / 1e9
            displaced += closure_solid
        else:
            if closure.wall_thickness is not None and not math.isclose(
                _dimension(closure.wall_thickness, "mm", f"inputs.closures[{index}].wall_thickness"),
                wall, rel_tol=1e-12,
            ):
                raise CalcCliError("invalid_request", "Butt hemisphere wall_thickness must equal "
                                   "the cylinder wall; unequal annular contact is not modeled")
            try:
                response = _evaluate_hemisphere(HemisphereRequest(
                    schema_version=CALC_SCHEMA_VERSION, model="hemisphere", material=closure.material,
                    inputs=HemisphereInputs(external_pressure=inputs.external_pressure,
                                            internal_radius=inputs.internal_radius,
                                            wall_thickness=inputs.wall_thickness),
                ), materials_file)
                result = response["result"]
                checks.extend([
                    _check(f"{name}.hemispherical_shell_stress", pressure,
                           result["theoretical_stress_failure_pressure_mpa"]["value"], required_margin=target),
                    _check(f"{name}.hemisphere_buckling", pressure,
                           result["released_buckling_pressure_mpa"]["value"], required_margin=target,
                           applicability=result["buckling_capacity_status"],
                           reasons=list(result["buckling_validity_violations"])),
                ])
            except CalcCliError as exc:
                if exc.code != "invalid_material":
                    raise
                response = {"model": "hemisphere", "error": {"code": exc.code, "message": exc.message}}
                checks.extend(_check(f"{name}.{mode}", pressure, None, required_margin=target,
                                     applicability="missing_material_property", reasons=[exc.message])
                              for mode in ("hemispherical_shell_stress", "hemisphere_buckling"))
            closure_solid = 2.0 / 3.0 * math.pi * (outer**3 - inner**3) / 1e9
            displaced += 2.0 / 3.0 * math.pi * outer**3 / 1e9
            internal += 2.0 / 3.0 * math.pi * inner**3 / 1e9
        # The existing seat formula: pressure on the outside projected disc,
        # supported by the shared annulus. Check both contacting materials.
        # Written as a unit-pressure capacity so zero demand stays finite.
        try:
            seat_capacity = min(material.shell_strength_mpa(), closure_material.shell_strength_mpa()) * (
                wall * (outer + inner) / outer**2
            )
            checks.append(_check(f"{name}.seat_bearing", pressure, seat_capacity,
                                 required_margin=target,
                                 reasons=["Average bearing on the shared butt annulus, using the "
                                          "weaker uniaxial compressive allowance of tube and closure; "
                                          "local contact stresses and retention are not evaluated."]))
        except CalcCliError as exc:
            if exc.code != "invalid_material":
                raise
            checks.append(_check(f"{name}.seat_bearing", pressure, None, required_margin=target,
                                 applicability="missing_material_property", reasons=[exc.message]))
        components["closures"].append({"id": name, **response})
        parts.append((name, closure_solid, closure_material))
    response = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "cylinder",
        "calculation_source": _calculation_source(
            "evaluate_cylinder", CYLINDER_MODEL_ID, CYLINDER_MODEL_VERSION, module="pv_calc.cylinder"
        ),
        "load_case": "hydrostatic_closed_end",
        "geometry": {
            "internal_radius": _quantity(inner, "mm"), "external_radius": _quantity(outer, "mm"),
            "wall_thickness": _quantity(wall, "mm"), "shell_mid_surface_radius": _quantity(inner + wall / 2.0, "mm"),
            "unsupported_length": _quantity(span, "mm"), "axial_length": _quantity(length, "mm"),
        },
        "assumptions": [
            "The same uniform differential external pressure acts on a closed-end cylinder "
            "and all supplied closures; the interior is the zero-gauge reference.",
            "Cylinder buckling uses simply supported circular ends separated by unsupported_length; "
            "stress uses the exact closed-end Lamé solution away from junctions.",
            "Each closure inherits the tube bore and outer radius. Plates use the requested "
            "idealized edge support; hemispherical buckling assumes a clamped equator. "
            "The assembly does not establish that its connections provide these restraints.",
        ],
        "components": components,
        "assessment": _assessment(checks, closures_included=inputs.closures is not None),
        "mass_properties": _mass(parts=parts, displaced_volume=displaced, internal_volume=internal, inputs=inputs),
    }
    _ensure_json_representable(response)
    return response
