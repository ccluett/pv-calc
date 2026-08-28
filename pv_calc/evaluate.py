"""The forward, sweep, and material-comparison evaluations: one request in, one response out."""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any, Literal

from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    COMPARE_MATERIALS_OPERATION_VERSION,
    COMPARE_MATERIALS_SUBSTITUTED_INPUT,
    SWEEP_DEPTH_SUBSTITUTED_PRESSURE,
    SWEEP_OPERATION_VERSION,
    SWEEP_SWEPT_INPUT,
    DepthSweepInputs,
    HemisphereInputs,
    HemisphereRequest,
    MassPropertiesRequest,
    MaterialComparisonRequest,
    PlateInputs,
    PlateRequest,
    QuantityInput,
    RingShellRequest,
    SmoothBucklingInputs,
    SmoothBucklingRequest,
    SweepAxisList,
    SweepAxisRange,
    SweepRequest,
    TubeInputs,
    TubeRequest,
    _quantity,
    _to_unit,
    _validate_request,
)
from pv_calc.errors import CalcCliError
from pv_calc.hydrostatics import (
    ExternalPressureFromDepthResult,
    external_pressure_from_depth,
    submerged_mass_and_buoyancy,
)
from pv_calc.pressure_vessel import (
    FlatCircularPlateResult,
    HemisphereResult,
    SmoothCylinderBucklingResult,
    TubeStressResult,
    closed_end_tube_stress,
    flat_circular_plate,
    hemispherical_head_external_pressure,
    ring_stiffened_shell_external_pressure,
    smooth_cylinder_external_pressure_buckling,
)
from pv_calc.resolve import (
    ResolvedMassMaterial,
    ResolvedMaterial,
    _resolve_mass_material,
    _resolve_material,
)
from pv_calc.serialize import _calculation_source, _ensure_json_representable, _response


def _calculate_tube_result(
    *,
    external_pressure_mpa: float,
    internal_radius_mm: float,
    wall_thickness_mm: float,
    material: ResolvedMaterial,
    force_thick: bool,
    axial_length_mm: float | None = None,
) -> TubeStressResult:
    try:
        return closed_end_tube_stress(
            external_pressure_mpa=external_pressure_mpa,
            internal_radius_mm=internal_radius_mm,
            wall_thickness_mm=wall_thickness_mm,
            material_failure_category=material.failure_category,
            strength_mpa=material.shell_strength_mpa(),
            elastic_modulus_mpa=material.elastic_modulus_mpa,
            poisson_ratio=material.poisson_ratio,
            axial_length_mm=axial_length_mm,
            force_thick=force_thick,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc


def _evaluate_tube(request: TubeRequest, materials_file: Path | None) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    result = _calculate_tube_result(
        external_pressure_mpa=_to_unit(
            request.inputs.external_pressure,
            "MPa",
            "inputs.external_pressure",
        ),
        internal_radius_mm=_to_unit(
            request.inputs.internal_radius,
            "mm",
            "inputs.internal_radius",
        ),
        wall_thickness_mm=_to_unit(
            request.inputs.wall_thickness,
            "mm",
            "inputs.wall_thickness",
        ),
        material=material,
        force_thick=request.inputs.force_thick,
        axial_length_mm=(
            _to_unit(request.inputs.axial_length, "mm", "inputs.axial_length")
            if request.inputs.axial_length is not None
            else None
        ),
    )
    payload = _response(
        model="tube",
        result=result,
        material=material,
        function="closed_end_tube_stress",
        module="pv_calc.pressure_vessel",
    )
    payload.update(
        _submergence_payloads(
            model="tube",
            request=request,
            material=material,
            result=result,
        )
    )
    return payload


def _plate_strengths(material: ResolvedMaterial) -> tuple[float, float | None]:
    """The plate's bending strength and, for a brittle record, its seat strength.

    A brittle plate bends its convex face into tension, so it reads the
    ultimate tensile strength the shell models never need.
    """
    if material.failure_category != "brittle":
        return material.shell_strength_mpa(), None
    if material.ultimate_tensile_strength_mpa is None:
        raise CalcCliError(
            "invalid_material",
            "brittle plate material properties are incomplete: "
            "ultimate_tensile_strength is required",
        )
    return material.ultimate_tensile_strength_mpa, material.shell_strength_mpa()


def _calculate_plate_result(
    *,
    external_pressure_mpa: float,
    free_radius_mm: float,
    plate_thickness_mm: float,
    material: ResolvedMaterial,
    boundary_condition: Literal["fixed", "simply_supported"],
    outside_radius_mm: float | None = None,
) -> FlatCircularPlateResult:
    strength_mpa, compressive_strength_mpa = _plate_strengths(material)
    elastic_modulus_mpa, poisson_ratio = material.elastic_constants_mpa("plate")
    try:
        return flat_circular_plate(
            external_pressure_mpa=external_pressure_mpa,
            free_radius_mm=free_radius_mm,
            plate_thickness_mm=plate_thickness_mm,
            elastic_modulus_mpa=elastic_modulus_mpa,
            poisson_ratio=poisson_ratio,
            material_failure_category=material.failure_category,
            strength_mpa=strength_mpa,
            compressive_strength_mpa=compressive_strength_mpa,
            boundary_condition=boundary_condition,
            outside_radius_mm=outside_radius_mm,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc


def _evaluate_plate(request: PlateRequest, materials_file: Path | None) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    # Fail fast, before input conversion: the sizing operations check in the
    # same order, so a doubly-invalid request reports the same code on both.
    material.elastic_constants_mpa("plate")
    result = _calculate_plate_result(
        external_pressure_mpa=_to_unit(
            request.inputs.external_pressure,
            "MPa",
            "inputs.external_pressure",
        ),
        free_radius_mm=_to_unit(
            request.inputs.free_radius,
            "mm",
            "inputs.free_radius",
        ),
        plate_thickness_mm=_to_unit(
            request.inputs.plate_thickness,
            "mm",
            "inputs.plate_thickness",
        ),
        material=material,
        boundary_condition=request.inputs.boundary_condition,
        outside_radius_mm=(
            _to_unit(request.inputs.outside_radius, "mm", "inputs.outside_radius")
            if request.inputs.outside_radius is not None
            else None
        ),
    )
    payload = _response(
        model="plate",
        result=result,
        material=material,
        function="flat_circular_plate",
        module="pv_calc.pressure_vessel",
    )
    payload.update(
        _submergence_payloads(
            model="plate",
            request=request,
            material=material,
            result=result,
        )
    )
    return payload


def _evaluate_hemisphere(
    request: HemisphereRequest,
    materials_file: Path | None,
) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    elastic_modulus_mpa, poisson_ratio = material.elastic_constants_mpa("hemisphere")
    try:
        result = hemispherical_head_external_pressure(
            external_pressure_mpa=_to_unit(
                request.inputs.external_pressure,
                "MPa",
                "inputs.external_pressure",
            ),
            internal_radius_mm=_to_unit(
                request.inputs.internal_radius,
                "mm",
                "inputs.internal_radius",
            ),
            wall_thickness_mm=_to_unit(
                request.inputs.wall_thickness,
                "mm",
                "inputs.wall_thickness",
            ),
            elastic_modulus_mpa=elastic_modulus_mpa,
            poisson_ratio=poisson_ratio,
            material_failure_category=material.failure_category,
            strength_mpa=material.shell_strength_mpa(),
            proportional_limit_mpa=material.proportional_limit_mpa,
            force_thick=request.inputs.force_thick,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc
    payload = _response(
        model="hemisphere",
        result=result,
        material=material,
        function="hemispherical_head_external_pressure",
        module="pv_calc.pressure_vessel",
    )
    payload.update(
        _submergence_payloads(
            model="hemisphere",
            request=request,
            material=material,
            result=result,
        )
    )
    return payload


def _calculate_smooth_buckling_result(
    *,
    external_pressure_mpa: float,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
    material: ResolvedMaterial,
    load_case: Literal["lateral_only", "hydrostatic_closed_end"],
) -> SmoothCylinderBucklingResult:
    elastic_modulus_mpa, poisson_ratio = material.elastic_constants_mpa("smooth-buckling")
    try:
        return smooth_cylinder_external_pressure_buckling(
            external_pressure_mpa=external_pressure_mpa,
            shell_mid_surface_radius_mm=shell_mid_surface_radius_mm,
            wall_thickness_mm=wall_thickness_mm,
            unsupported_length_mm=unsupported_length_mm,
            elastic_modulus_mpa=elastic_modulus_mpa,
            poisson_ratio=poisson_ratio,
            yield_strength_mpa=material.yield_strength_mpa,
            load_case=load_case,
            proportional_limit_mpa=material.proportional_limit_mpa,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc


def _evaluate_smooth_buckling(
    request: SmoothBucklingRequest,
    materials_file: Path | None,
) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    # Fail fast, before input conversion: the sizing operations check in the
    # same order, so a doubly-invalid request reports the same code on both.
    material.elastic_constants_mpa("smooth-buckling")
    result = _calculate_smooth_buckling_result(
        external_pressure_mpa=_to_unit(
            request.inputs.external_pressure,
            "MPa",
            "inputs.external_pressure",
        ),
        shell_mid_surface_radius_mm=_to_unit(
            request.inputs.shell_mid_surface_radius,
            "mm",
            "inputs.shell_mid_surface_radius",
        ),
        wall_thickness_mm=_to_unit(
            request.inputs.wall_thickness,
            "mm",
            "inputs.wall_thickness",
        ),
        unsupported_length_mm=_to_unit(
            request.inputs.unsupported_length,
            "mm",
            "inputs.unsupported_length",
        ),
        material=material,
        load_case=request.inputs.load_case,
    )
    payload = _response(
        model="smooth-buckling",
        result=result,
        material=material,
        function="smooth_cylinder_external_pressure_buckling",
        module="pv_calc.pressure_vessel",
    )
    payload.update(
        _submergence_payloads(
            model="smooth-buckling",
            request=request,
            material=material,
            result=result,
        )
    )
    return payload


def _evaluate_ring_shell(
    request: RingShellRequest,
    materials_file: Path | None,
) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    elastic_modulus_mpa, poisson_ratio = material.elastic_constants_mpa("ring-shell")
    try:
        result = ring_stiffened_shell_external_pressure(
            external_pressure_mpa=_to_unit(
                request.inputs.external_pressure,
                "MPa",
                "inputs.external_pressure",
            ),
            shell_mid_surface_radius_mm=_to_unit(
                request.inputs.shell_mid_surface_radius,
                "mm",
                "inputs.shell_mid_surface_radius",
            ),
            wall_thickness_mm=_to_unit(
                request.inputs.wall_thickness,
                "mm",
                "inputs.wall_thickness",
            ),
            unsupported_length_mm=_to_unit(
                request.inputs.unsupported_length,
                "mm",
                "inputs.unsupported_length",
            ),
            ring_spacing_mm=_to_unit(
                request.inputs.ring_spacing,
                "mm",
                "inputs.ring_spacing",
            ),
            ring_axial_width_mm=_to_unit(
                request.inputs.ring_axial_width,
                "mm",
                "inputs.ring_axial_width",
            ),
            ring_radial_height_mm=_to_unit(
                request.inputs.ring_radial_height,
                "mm",
                "inputs.ring_radial_height",
            ),
            ring_location=request.inputs.ring_location,
            elastic_modulus_mpa=elastic_modulus_mpa,
            poisson_ratio=poisson_ratio,
            yield_strength_mpa=material.yield_strength_mpa,
            proportional_limit_mpa=material.proportional_limit_mpa,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc
    return _response(
        model="ring-shell",
        result=result,
        material=material,
        function="ring_stiffened_shell_external_pressure",
        module="pv_calc.pressure_vessel",
    )


def _evaluate_mass_properties(
    request: MassPropertiesRequest,
    materials_file: Path | None,
) -> dict[str, Any]:
    material = _resolve_mass_material(request.material, materials_file)
    if material.density_kg_per_m3 is None:
        raise CalcCliError(
            "invalid_material",
            "mass-properties material properties are incomplete",
        )
    solid_volume_m3 = _to_unit(request.inputs.solid_volume, "m^3", "inputs.solid_volume")
    displaced_volume_m3 = _to_unit(
        request.inputs.displaced_volume,
        "m^3",
        "inputs.displaced_volume",
    )
    if solid_volume_m3 > displaced_volume_m3 and not math.isclose(
        solid_volume_m3,
        displaced_volume_m3,
        rel_tol=1.0e-12,
        abs_tol=0.0,
    ):
        raise CalcCliError(
            "unevaluable_model",
            "inputs.solid_volume must not exceed inputs.displaced_volume for a "
            "fully submerged closed body",
        )
    try:
        result = submerged_mass_and_buoyancy(
            solid_volume_m3=solid_volume_m3,
            displaced_volume_m3=displaced_volume_m3,
            material_density_kg_per_m3=material.density_kg_per_m3,
            fluid_density_kg_per_m3=_to_unit(
                request.inputs.fluid_density,
                "kg/m^3",
                "inputs.fluid_density",
            ),
            gravity_m_per_s2=_to_unit(
                request.inputs.gravity,
                "m/s^2",
                "inputs.gravity",
            ),
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc
    return _response(
        model="mass-properties",
        result=result,
        material=material,
        function="submerged_mass_and_buoyancy",
        module="pv_calc.hydrostatics",
    )


# The failure pressures a submergence block expresses as depths, per model; a
# withheld pressure keeps its null.
FAILURE_PRESSURE_FIELDS: dict[str, tuple[str, ...]] = {
    "tube": ("theoretical_failure_pressure_mpa",),
    "plate": ("theoretical_failure_pressure_mpa", "theoretical_seat_failure_pressure_mpa"),
    "hemisphere": (
        "theoretical_stress_failure_pressure_mpa",
        "theoretical_seat_failure_pressure_mpa",
        "released_buckling_pressure_mpa",
        "roark_probable_minimum_pressure_mpa",
    ),
    "smooth-buckling": (
        "correlated_critical_pressure_mpa",
        "roark_probable_minimum_pressure_mpa",
    ),
}
FAILURE_DEPTH_BASIS = (
    "h = p / (rho * g) in the request's fluid, the inverse of "
    "pv_calc.hydrostatics.external_pressure_from_depth; each depth follows its "
    "published formula pressure, not a released margin, and a withheld pressure "
    "has no depth. "
    "The request's density is constant, so the depth carries no rise in seawater density "
    "with depth; against a depth-dependent density the same pressure sits shallower, "
    "by a margin that grows with depth."
)


def _closed_body_volumes_m3(
    inputs: TubeInputs | PlateInputs | HemisphereInputs | SmoothBucklingInputs,
) -> tuple[float, float, str]:
    """The model's structural and displaced volumes as a closed body, and their basis.

    Dispatches on the input type itself: the request contract already binds
    each model to its own inputs class, so the type is the model.
    """
    cubic_mm_per_m3 = 1.0e9
    if isinstance(inputs, PlateInputs):
        if inputs.outside_radius is None:
            raise CalcCliError(
                "invalid_request",
                "inputs.submergence needs inputs.outside_radius as the plate's disc radius",
            )
        outer = _to_unit(inputs.outside_radius, "mm", "inputs.outside_radius")
        thickness = _to_unit(inputs.plate_thickness, "mm", "inputs.plate_thickness")
        volume = math.pi * outer**2 * thickness / cubic_mm_per_m3
        return volume, volume, "solid disc of the outside radius: pi*R_o^2*t"
    if isinstance(inputs, HemisphereInputs):
        inner = _to_unit(inputs.internal_radius, "mm", "inputs.internal_radius")
        outer = inner + _to_unit(inputs.wall_thickness, "mm", "inputs.wall_thickness")
        return (
            2.0 / 3.0 * math.pi * (outer**3 - inner**3) / cubic_mm_per_m3,
            2.0 / 3.0 * math.pi * outer**3 / cubic_mm_per_m3,
            "closed hemispherical shell: solid 2/3*pi*(R_o^3 - R_i^3), displaced 2/3*pi*R_o^3",
        )
    thickness = _to_unit(inputs.wall_thickness, "mm", "inputs.wall_thickness")
    if isinstance(inputs, TubeInputs):
        if inputs.axial_length is None:
            raise CalcCliError(
                "invalid_request",
                "inputs.submergence needs inputs.axial_length as the tube length",
            )
        inner = _to_unit(inputs.internal_radius, "mm", "inputs.internal_radius")
        outer = inner + thickness
        length = _to_unit(inputs.axial_length, "mm", "inputs.axial_length")
        basis = (
            "closed tube of the axial length with weightless closures: "
            "solid pi*(R_o^2 - R_i^2)*L, displaced pi*R_o^2*L"
        )
    else:
        mid = _to_unit(inputs.shell_mid_surface_radius, "mm", "inputs.shell_mid_surface_radius")
        inner = mid - thickness / 2.0
        outer = mid + thickness / 2.0
        length = _to_unit(inputs.unsupported_length, "mm", "inputs.unsupported_length")
        basis = (
            "closed shell of the unsupported length with weightless closures, "
            "R_i and R_o at the mid-surface radius -/+ t/2: "
            "solid pi*(R_o^2 - R_i^2)*L, displaced pi*R_o^2*L"
        )
    return (
        math.pi * (outer**2 - inner**2) * length / cubic_mm_per_m3,
        math.pi * outer**2 * length / cubic_mm_per_m3,
        basis,
    )


def _submergence_payloads(
    *,
    model: Literal["tube", "plate", "hemisphere", "smooth-buckling"],
    request: TubeRequest | PlateRequest | HemisphereRequest | SmoothBucklingRequest,
    material: ResolvedMaterial,
    result: (
        TubeStressResult
        | FlatCircularPlateResult
        | HemisphereResult
        | SmoothCylinderBucklingResult
    ),
) -> dict[str, Any]:
    """The mass properties and failure depths an ``inputs.submergence`` block adds."""
    submergence = request.inputs.submergence
    if submergence is None:
        return {}
    solid_m3, displaced_m3, volume_basis = _closed_body_volumes_m3(request.inputs)
    if material.density_kg_per_m3 is None:
        raise CalcCliError(
            "invalid_material",
            "inputs.submergence needs a material density for mass properties: give "
            "material.properties.density (--material-density) or name a record that carries one",
        )
    fluid_density = _to_unit(submergence.fluid_density, "kg/m^3", "inputs.submergence.fluid_density")
    gravity = _to_unit(submergence.gravity, "m/s^2", "inputs.submergence.gravity")
    try:
        mass_result = submerged_mass_and_buoyancy(
            solid_volume_m3=solid_m3,
            displaced_volume_m3=displaced_m3,
            material_density_kg_per_m3=material.density_kg_per_m3,
            fluid_density_kg_per_m3=fluid_density,
            gravity_m_per_s2=gravity,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc
    mass = _response(
        model="mass-properties",
        result=mass_result,
        material=ResolvedMassMaterial(
            source_type=material.source_type,
            name=material.name,
            database=material.database,
            provenance=material.provenance,
            density_kg_per_m3=material.density_kg_per_m3,
        ),
        function="submerged_mass_and_buoyancy",
        module="pv_calc.hydrostatics",
    )
    metres_per_mpa = 1.0e6 / (fluid_density * gravity)
    depths = {
        name: _quantity(None if (p := getattr(result, name)) is None else p * metres_per_mpa, "m")
        for name in FAILURE_PRESSURE_FIELDS[model]
    }
    return {
        "mass_properties": {**mass, "volume_basis": volume_basis},
        "failure_depths": {"basis": FAILURE_DEPTH_BASIS, "depths": depths},
    }


def _axis_quantities(
    axis: SweepAxisList | SweepAxisRange,
    *,
    unit: str,
    field_name: str,
) -> list[QuantityInput]:
    """Return the ordered axis values as request quantities.

    A list axis substitutes the caller's own quantities unchanged, in the order
    given. A range axis interpolates in ``unit`` as ``start*(1 - w) + stop*w``
    with ``w = i/(count - 1)``, so the first and last points are exactly the
    requested endpoints.
    """
    if isinstance(axis, SweepAxisList):
        return list(axis.values)
    start = _to_unit(axis.start, unit, f"{field_name}.start")
    stop = _to_unit(axis.stop, unit, f"{field_name}.stop")
    last_index = axis.count - 1
    quantities: list[QuantityInput] = []
    for index in range(axis.count):
        weight = index / last_index
        quantities.append(
            QuantityInput(value=start * (1.0 - weight) + stop * weight, unit=unit)
        )
    return quantities


def _evaluate_forward_request(
    model: str,
    payload: dict[str, Any],
    materials_file: Path | None,
) -> dict[str, Any]:
    """Run one forward payload through its model's single-point path."""
    if model == "tube":
        return _evaluate_tube(_validate_request(TubeRequest, payload), materials_file)
    if model == "plate":
        return _evaluate_plate(_validate_request(PlateRequest, payload), materials_file)
    if model == "hemisphere":
        return _evaluate_hemisphere(
            _validate_request(HemisphereRequest, payload),
            materials_file,
        )
    if model == "smooth-buckling":
        return _evaluate_smooth_buckling(
            _validate_request(SmoothBucklingRequest, payload),
            materials_file,
        )
    return _evaluate_ring_shell(
        _validate_request(RingShellRequest, payload),
        materials_file,
    )


def _design_pressure_from_depth(
    inputs: DepthSweepInputs,
    depth: QuantityInput,
) -> ExternalPressureFromDepthResult:
    """Convert one swept depth with the hydrostatic kernel."""
    try:
        return external_pressure_from_depth(
            depth_m=_to_unit(depth, "m", "inputs.depth"),
            fluid_density_kg_per_m3=_to_unit(
                inputs.fluid_density,
                "kg/m^3",
                "inputs.fluid_density",
            ),
            gravity_m_per_s2=_to_unit(inputs.gravity, "m/s^2", "inputs.gravity"),
            design_factor=inputs.design_factor,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc


def _depth_to_pressure_payload(
    converted: ExternalPressureFromDepthResult,
) -> dict[str, Any]:
    """Describe the one depth-to-pressure conversion every point shares."""
    return {
        "assumptions": list(converted.notes),
        "calculation_source": _calculation_source(
            "external_pressure_from_depth",
            converted.model_id,
            converted.model_version,
            module="pv_calc.hydrostatics",
        ),
        "design_factor": converted.design_factor,
        "fluid_density": _quantity(converted.fluid_density_kg_per_m3, "kg/m^3"),
        "gravity": _quantity(converted.gravity_m_per_s2, "m/s^2"),
        "pressure_reference_convention": converted.pressure_reference_convention,
        "source_reference": converted.source_reference,
        "substituted_pressure": SWEEP_DEPTH_SUBSTITUTED_PRESSURE,
    }


def _evaluate_sweep(request: SweepRequest, materials_file: Path | None) -> dict[str, Any]:
    inputs = request.inputs
    base = request.request.model_dump(mode="json")
    if isinstance(inputs, DepthSweepInputs):
        depth_inputs: DepthSweepInputs | None = inputs
        axis: SweepAxisList | SweepAxisRange = inputs.depth
        axis_variable = "depth"
    else:
        depth_inputs = None
        axis = inputs.external_pressure
        axis_variable = "external_pressure"
    depth_to_pressure: dict[str, Any] | None = None
    points: list[dict[str, Any]] = []
    for index, value in enumerate(
        _axis_quantities(
            axis,
            unit="m" if depth_inputs is not None else "MPa",
            field_name=f"inputs.{axis_variable}",
        )
    ):
        axis_value = value.model_dump(mode="json")
        point: dict[str, Any] = {axis_variable: axis_value}
        try:
            if depth_inputs is not None:
                converted = _design_pressure_from_depth(depth_inputs, value)
                if depth_to_pressure is None:
                    depth_to_pressure = _depth_to_pressure_payload(converted)
                # The design differential external pressure drives the model.
                pressure = _quantity(converted.design_external_pressure_mpa, "MPa")
                point["service_external_pressure"] = _quantity(
                    converted.service_external_pressure_mpa,
                    "MPa",
                )
                point["design_external_pressure"] = pressure
            else:
                pressure = axis_value
            payload = {
                **base,
                "inputs": {**base["inputs"], "external_pressure": pressure},
            }
            point["response"] = _evaluate_forward_request(
                base["model"],
                payload,
                materials_file,
            )
            _ensure_json_representable(point["response"])
        except CalcCliError as exc:
            # A point keeps its own error code and message; the axis position
            # is added so a long sweep names the request that failed.
            raise CalcCliError(
                exc.code,
                exc.message,
                [*exc.details, {axis_variable: axis_value, "point_index": index}],
            ) from exc
        points.append(point)
    sweep: dict[str, Any] = {
        "axis": axis.model_dump(mode="json"),
        "operation_version": SWEEP_OPERATION_VERSION,
        "points": points,
        "swept_input": SWEEP_SWEPT_INPUT,
    }
    if depth_to_pressure is not None:
        sweep["depth_to_pressure"] = depth_to_pressure
    return {
        "model": base["model"],
        "operation": "sweep",
        "schema_version": CALC_SCHEMA_VERSION,
        "sweep": sweep,
    }


def _evaluate_material_comparison(
    request: MaterialComparisonRequest,
    materials_file: Path | None,
) -> dict[str, Any]:
    base = request.request.model_dump(mode="json")
    mass_inputs = (
        request.inputs.mass_properties.model_dump(mode="json")
        if request.inputs.mass_properties is not None
        else None
    )
    entries: list[dict[str, Any]] = []
    for index, name in enumerate(request.inputs.materials):
        material = {"type": "named", "name": name}
        entry: dict[str, Any] = {"material": name, "outcome": "evaluated"}
        try:
            entry["response"] = _evaluate_forward_request(
                base["model"],
                {**base, "material": material},
                materials_file,
            )
            if mass_inputs is not None:
                entry["mass_properties"] = _evaluate_mass_properties(
                    _validate_request(
                        MassPropertiesRequest,
                        {
                            "schema_version": CALC_SCHEMA_VERSION,
                            "model": "mass-properties",
                            "inputs": mass_inputs,
                            "material": material,
                        },
                    ),
                    materials_file,
                )
            _ensure_json_representable(entry)
        except CalcCliError as exc:
            if exc.code != "invalid_material":
                # Every other failure is a property of the request or of the
                # database rather than of one listed material, so it fails the
                # whole comparison with its own code, message, and position.
                raise CalcCliError(
                    exc.code,
                    exc.message,
                    [*exc.details, {"entry_index": index, "material": name}],
                ) from exc
            # A record lacking a property the requested calculations read
            # carries that model's own invalid_material outcome and no result,
            # exactly as a single-material invocation would report it. The
            # remaining entries are unaffected.
            entry = {
                "material": name,
                "message": exc.message,
                "outcome": "invalid_material",
            }
        entries.append(entry)
    return {
        "comparison": {
            "entries": entries,
            "operation_version": COMPARE_MATERIALS_OPERATION_VERSION,
            "substituted_input": COMPARE_MATERIALS_SUBSTITUTED_INPUT,
        },
        "model": base["model"],
        "operation": "compare-materials",
        "schema_version": CALC_SCHEMA_VERSION,
    }
