"""Fluid statics: pressure at depth, and mass and buoyancy of a submerged body."""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Literal


HYDROSTATIC_PRESSURE_MODEL_ID = "hydrostatic_external_pressure_from_depth"
HYDROSTATIC_PRESSURE_MODEL_VERSION = "1.0.0"
HYDROSTATIC_PRESSURE_SOURCE = (
    "B. Lautrup, Physics of Continuous Matter, sec. 4.1 'Incompressible sea', "
    "p. 59, draft revision 7.7 of 2004-01-22: Eq. (4-3) p - p0 = rho0*g0*h for a "
    "fluid of constant density rho0 under constant gravity g0, and Eq. (4-4) "
    "p = p0 - rho0*g0*z in flat-earth coordinates with the surface at z = 0 and "
    "depth h = -z"
)
HYDROSTATIC_PRESSURE_SCOPE_NOTES = (
    "Depth is the vertical distance below the free surface, positive downwards, and "
    "is one scalar: the vessel's own vertical extent is not resolved.",
    "The reported pressures are differentials across the wall with the interior held "
    "at zero gauge, that is at the surface pressure p0 of Eq. (4-3). No absolute "
    "pressure is reported, and internal gas compression is outside this result.",
    "The fluid has one uniform density and gravity is uniform over the depth. Layered "
    "fluids, depth-varying density profiles, and fluid compressibility are outside "
    "this result; the source notes that to 11 km the density of water changes by "
    "about 4.5% while gravity changes by about 0.35%.",
    "The design factor is the caller's policy multiplier on the service pressure; no "
    "factor is taken from the source.",
)

SUBMERGED_MASS_MODEL_ID = "archimedes_submerged_mass_and_buoyancy"
SUBMERGED_MASS_MODEL_VERSION = "1.0.0"
SUBMERGED_MASS_SOURCE = (
    "Archimedes, On Floating Bodies, Book I, Proposition 7 (a solid heavier than the "
    "fluid weighs less in it by the weight of the fluid displaced) and Proposition 6 "
    "(a solid lighter than the fluid, held under, is driven up by the difference); "
    "B. Lautrup, Physics of Continuous Matter, sec. 5.1 Archimedes' principle, "
    "Eqs. (5-5) to (5-8), pp. 78-79, draft revision 7.7 of 2004-01-22, for the "
    "constant-gravity forms F_G = M_body*g, F_B = -M_fluid*g, "
    "F = (M_body - M_fluid)*g, and the neutral condition M_body = M_fluid"
)
SUBMERGED_MASS_SCOPE_NOTES = (
    "The body is fully submerged, rigid, closed, and not flooded; the two volumes are "
    "the caller's resolved undeformed geometry, not volumes deformed by pressure.",
    "Gravity is uniform over the body and the fluid has one uniform density.",
    "Net submerged mass is structural air mass minus displaced-fluid mass: positive "
    "sinks, zero is neutral, negative is buoyant.",
    "The buoyant force is a magnitude; it acts opposite gravity.",
    "Payloads, penetrators, openings, flooding, trapped gas, centre of gravity, centre "
    "of buoyancy, stability, and drag are outside this result.",
)


@dataclass(frozen=True)
class ExternalPressureFromDepthResult:
    model_id: str
    model_version: str
    source_reference: str
    pressure_reference_convention: Literal["differential_across_wall_interior_at_zero_gauge"]
    depth_m: float
    fluid_density_kg_per_m3: float
    gravity_m_per_s2: float
    design_factor: float
    service_external_pressure_mpa: float
    design_external_pressure_mpa: float
    notes: tuple[str, ...]


@dataclass(frozen=True)
class SubmergedMassResult:
    model_id: str
    model_version: str
    source_reference: str
    submergence_condition: Literal["fully_submerged_rigid_non_flooded"]
    net_mass_sign_convention: Literal["positive_heavier_than_displaced_fluid"]
    buoyant_force_direction: Literal["opposes_gravity"]
    solid_volume_m3: float
    displaced_volume_m3: float
    material_density_kg_per_m3: float
    fluid_density_kg_per_m3: float
    gravity_m_per_s2: float
    structural_air_mass_kg: float
    displaced_fluid_mass_kg: float
    net_submerged_mass_kg: float
    buoyant_force_n: float
    notes: tuple[str, ...]


def _positive_finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def _non_negative_finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result < 0.0:
        raise ValueError(f"{name} must be finite and non-negative")
    return result


def external_pressure_from_depth(
    *,
    depth_m: float,
    fluid_density_kg_per_m3: float,
    gravity_m_per_s2: float,
    design_factor: float,
) -> ExternalPressureFromDepthResult:
    """Service and design external pressure at a depth in a uniform fluid.

    Depth is metres below the free surface, positive downwards; fluid density is
    kilograms per cubic metre and gravity is metres per second squared, so the
    product is pascals and both reported pressures are megapascals. The fluid
    density, gravity, and design factor are the caller's, not this module's.

    The service pressure is ``rho * g * h`` from Lautrup Eq. (4-3), the pressure
    rise from the surface down to depth ``h`` in a fluid of constant density under
    constant gravity. It is reported as the differential across the vessel wall
    with the interior held at zero gauge, that is at the same reference as the
    surface pressure ``p0``: only the difference across the wall is returned, and
    no absolute pressure is formed. The design pressure is that differential
    scaled by the caller's design factor.

    Both pressures are single left-to-right products, so the design pressure is
    ``rho * g * h * factor / 1e6`` rather than the service pressure times the
    factor; floating-point multiplication is not associative, and the two forms
    round differently for depths and factors this repository already uses.
    """

    depth = _non_negative_finite(depth_m, "depth_m")
    fluid_density = _positive_finite(fluid_density_kg_per_m3, "fluid_density_kg_per_m3")
    gravity = _positive_finite(gravity_m_per_s2, "gravity_m_per_s2")
    factor = _positive_finite(design_factor, "design_factor")

    service_pressure = fluid_density * gravity * depth / 1_000_000.0
    design_pressure = fluid_density * gravity * depth * factor / 1_000_000.0
    if not math.isfinite(service_pressure) or not math.isfinite(design_pressure):
        raise ValueError("calculated external pressures must be finite")

    return ExternalPressureFromDepthResult(
        model_id=HYDROSTATIC_PRESSURE_MODEL_ID,
        model_version=HYDROSTATIC_PRESSURE_MODEL_VERSION,
        source_reference=HYDROSTATIC_PRESSURE_SOURCE,
        pressure_reference_convention="differential_across_wall_interior_at_zero_gauge",
        depth_m=depth,
        fluid_density_kg_per_m3=fluid_density,
        gravity_m_per_s2=gravity,
        design_factor=factor,
        service_external_pressure_mpa=service_pressure,
        design_external_pressure_mpa=design_pressure,
        notes=HYDROSTATIC_PRESSURE_SCOPE_NOTES,
    )


def submerged_mass_and_buoyancy(
    *,
    solid_volume_m3: float,
    displaced_volume_m3: float,
    material_density_kg_per_m3: float,
    fluid_density_kg_per_m3: float,
    gravity_m_per_s2: float,
) -> SubmergedMassResult:
    """Mass in air, displaced-fluid mass, net submerged mass, and buoyant force.

    All inputs are SI: cubic metres, kilograms per cubic metre, and metres per
    second squared. ``solid_volume_m3`` is the structural material volume and
    ``displaced_volume_m3`` is the volume of fluid the wetted envelope displaces;
    the caller resolves both from its own geometry, and the fluid density and
    gravity are the caller's, not this module's.

    Structural air mass is ``rho_material * V_solid`` and displaced-fluid mass is
    ``rho_fluid * V_displaced``. Net submerged mass is air mass minus displaced
    mass, so it is positive when the body is heavier than the fluid it displaces,
    zero at neutral buoyancy, and negative when the body is buoyant; multiplying
    it by gravity gives the body's apparent weight, positive downwards. The
    reported buoyant force is the magnitude ``rho_fluid * V_displaced * g`` and
    acts opposite gravity.
    """

    solid_volume = _positive_finite(solid_volume_m3, "solid_volume_m3")
    displaced_volume = _positive_finite(displaced_volume_m3, "displaced_volume_m3")
    material_density = _positive_finite(
        material_density_kg_per_m3, "material_density_kg_per_m3"
    )
    fluid_density = _positive_finite(fluid_density_kg_per_m3, "fluid_density_kg_per_m3")
    gravity = _positive_finite(gravity_m_per_s2, "gravity_m_per_s2")

    # Unit conversions that denote the same physical volume can differ by a
    # floating-point rounding bit. Accept that numerical equivalence, but keep
    # the closed-body invariant at the kernel boundary for every caller.
    if solid_volume > displaced_volume and not math.isclose(
        solid_volume,
        displaced_volume,
        rel_tol=1.0e-12,
        abs_tol=0.0,
    ):
        raise ValueError(
            "solid_volume_m3 must not exceed displaced_volume_m3 for a fully "
            "submerged closed body"
        )

    structural_air_mass = solid_volume * material_density
    displaced_fluid_mass = displaced_volume * fluid_density
    net_submerged_mass = structural_air_mass - displaced_fluid_mass
    buoyant_force = displaced_fluid_mass * gravity
    if not all(
        math.isfinite(value)
        for value in (
            structural_air_mass,
            displaced_fluid_mass,
            net_submerged_mass,
            buoyant_force,
        )
    ):
        raise ValueError("calculated mass and buoyancy values must be finite")
    return SubmergedMassResult(
        model_id=SUBMERGED_MASS_MODEL_ID,
        model_version=SUBMERGED_MASS_MODEL_VERSION,
        source_reference=SUBMERGED_MASS_SOURCE,
        submergence_condition="fully_submerged_rigid_non_flooded",
        net_mass_sign_convention="positive_heavier_than_displaced_fluid",
        buoyant_force_direction="opposes_gravity",
        solid_volume_m3=solid_volume,
        displaced_volume_m3=displaced_volume,
        material_density_kg_per_m3=material_density,
        fluid_density_kg_per_m3=fluid_density,
        gravity_m_per_s2=gravity,
        structural_air_mass_kg=structural_air_mass,
        displaced_fluid_mass_kg=displaced_fluid_mass,
        net_submerged_mass_kg=net_submerged_mass,
        buoyant_force_n=buoyant_force,
        notes=SUBMERGED_MASS_SCOPE_NOTES,
    )
