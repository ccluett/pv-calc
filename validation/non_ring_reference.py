"""Independent standard-library references for every released non-ring golden.

This module intentionally imports no production calculation, adapter,
fixture, expected output, or section helper.  It transcribes the cited source
equations directly and keeps source inputs, published values, independent
calculations, and comparisons in separate records.  The inventory mapping
evidence cases to repository artifacts lives in ``coverage_inventory.py`` so
that moving a test or example cannot change this file's pinned hash.

Run from the ``pv-calc`` directory with::

    uv run python validation/non_ring_reference.py
"""

from __future__ import annotations

import json
import math
from typing import Any, Literal


PSI_TO_MPA = 0.006894757293168361
INCH_TO_MM = 25.4

# Set for the independent-vs-production comparisons before those comparisons
# were run.  Published values use separate half-last-recorded-digit limits.
REFERENCE_RELATIVE_TOLERANCE = 1.0e-9
REFERENCE_ABSOLUTE_TOLERANCE = 1.0e-10
# Half of the last digit of each accepted display or committed golden.  The
# manual displays Example 2 failure as 9,038 psi; 9.0401/9.0384 ksi are the
# repository's committed four-decimal manual-traceable goldens, not manual
# displays.  These limits are enforced by tests/test_phase5_validation.py.
PUBLISHED_TOLERANCES = {
    "manual_display_example_2_failure_ksi": 0.0005,
    "repo_four_decimal_golden_ksi": 0.00005,
    "manual_display_whole_psi": 0.5,
    "manual_display_one_decimal_psi": 0.05,
    "manual_display_two_decimal_psi": 0.005,
}

UNDERPRESSURE_MANUAL = {
    "title": "Under Pressure Version 4.0 User Manual",
    "edition_revision": "Version 4.0, manual revision 3/27/01",
    "url": "https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf",
    "sha256": "7a747e6ccd7efd6fdbf0c74a295751086b861661ca6de45f277cdda30c2e43c8",
    "retrieved_utc_date": "2026-07-22",
}
NASA_SP_8007_REV2 = {
    "title": "NASA/SP-8007-2020/REV 2, Buckling of Thin-Walled Circular Cylinders",
    "edition_revision": "Second revision November 2020, issued December 2020",
    "url": (
        "https://ntrs.nasa.gov/api/citations/20205011530/downloads/"
        "20205011530%20Rev%202FINALa%201-2023.pdf"
    ),
    "sha256": "299dfb8807862f174768356353f39c6bf6993596cb6f5933dd4fd23181e8837b",
    "retrieved_utc_date": "2026-07-22",
}
NASA_SP_8032 = {
    "title": "NASA SP-8032, Buckling of Thin-Walled Doubly Curved Shells",
    "edition_revision": "August 1969",
    "url": "https://shellbuckling.com/papers/classicNASAReports/NASASP-8032.pdf",
    "sha256": "440e309c04bf6f0833e91e1781cb1de398baf7b8ddd2e83a52c47a5bf442f5b2",
    "retrieved_utc_date": "2026-07-22",
}


def _von_mises(radial: float, hoop: float, axial: float) -> float:
    return math.sqrt(
        ((radial - hoop) ** 2 + (hoop - axial) ** 2 + (axial - radial) ** 2)
        / 2.0
    )


def closed_end_tube_reference(
    *,
    external_pressure: float,
    internal_radius: float,
    wall_thickness: float,
    yield_strength: float,
    force_thick: bool = False,
) -> dict[str, Any]:
    """Roark/Lame closed-end tube response in any consistent units.

    Pressure and stress units must be the same.  Radius and thickness units
    must be the same.  Compression is negative.  The external surface is the
    pressure-loaded surface and the internal surface is traction-free.
    """
    external_radius = internal_radius + wall_thickness
    mean_radius = internal_radius + wall_thickness / 2.0
    radius_ratio = mean_radius / wall_thickness
    branch = "thick" if force_thick or radius_ratio <= 10.0 else "thin"

    if branch == "thin":
        hoop = -external_pressure * mean_radius / wall_thickness
        axial = hoop / 2.0
        states = [
            {
                "radius": mean_radius,
                "radius_convention": "mean",
                "radial_stress": 0.0,
                "hoop_stress": hoop,
                "axial_stress": axial,
                "von_mises_stress": _von_mises(0.0, hoop, axial),
            }
        ]
    else:
        denominator = external_radius**2 - internal_radius**2
        lame_a = -external_pressure * external_radius**2 / denominator
        lame_b = (
            -external_pressure
            * internal_radius**2
            * external_radius**2
            / denominator
        )
        states = []
        for radius, convention in (
            (internal_radius, "internal"),
            (external_radius, "external"),
        ):
            radial = lame_a - lame_b / radius**2
            hoop = lame_a + lame_b / radius**2
            axial = lame_a
            states.append(
                {
                    "radius": radius,
                    "radius_convention": convention,
                    "radial_stress": radial,
                    "hoop_stress": hoop,
                    "axial_stress": axial,
                    "von_mises_stress": _von_mises(radial, hoop, axial),
                }
            )

    governing = max(states, key=lambda state: state["von_mises_stress"])
    failure_pressure = (
        external_pressure * yield_strength / governing["von_mises_stress"]
    )
    return {
        "branch": branch,
        "internal_radius": internal_radius,
        "external_radius": external_radius,
        "mean_radius": mean_radius,
        "wall_thickness": wall_thickness,
        "mean_radius_over_thickness": radius_ratio,
        "external_pressure": external_pressure,
        "yield_strength": yield_strength,
        "stress_states": states,
        "governing_radius": governing["radius"],
        "governing_von_mises_stress": governing["von_mises_stress"],
        "theoretical_failure_pressure": failure_pressure,
        "margin": failure_pressure / external_pressure - 1.0,
        "source": (
            "Roark 6th ed. Table 28 case 1c for mean-radius thin membrane "
            "stress; Table 32 cases 1a-1d for Lamé thick-cylinder stress; "
            "UnderPressure 4.0 Appendix C criterion B for ductile-metal von Mises failure"
        ),
    }


def hemispherical_head_reference(
    *,
    external_pressure: float,
    internal_radius: float,
    wall_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
    yield_strength: float,
    proportional_limit: float | None = None,
    force_thick: bool = False,
) -> dict[str, Any]:
    """Roark sphere stress plus SP-8032 hemisphere buckling reference.

    Pressure and stress units must be the same, as must radius and thickness
    units. Compression is negative. The hemisphere has a clamped equator and
    a 180-degree included angle for the NASA spherical-cap correlation.
    """
    external_radius = internal_radius + wall_thickness
    mean_radius = internal_radius + wall_thickness / 2.0
    radius_ratio = mean_radius / wall_thickness
    branch = "thick" if force_thick or radius_ratio <= 10.0 else "thin"

    if branch == "thin":
        tangential = -external_pressure * mean_radius / (2.0 * wall_thickness)
        states = [
            {
                "radius": mean_radius,
                "radius_convention": "mean",
                "radial_stress": 0.0,
                "meridional_stress": tangential,
                "hoop_stress": tangential,
                "von_mises_stress": _von_mises(0.0, tangential, tangential),
            }
        ]
    else:
        denominator = external_radius**3 - internal_radius**3
        lame_a = -external_pressure * external_radius**3 / denominator
        lame_b = lame_a * internal_radius**3
        states = []
        for radius, convention in (
            (internal_radius, "internal"),
            (external_radius, "external"),
        ):
            radial = lame_a - lame_b / radius**3
            tangential = lame_a + lame_b / (2.0 * radius**3)
            states.append(
                {
                    "radius": radius,
                    "radius_convention": convention,
                    "radial_stress": radial,
                    "meridional_stress": tangential,
                    "hoop_stress": tangential,
                    "von_mises_stress": _von_mises(
                        radial,
                        tangential,
                        tangential,
                    ),
                }
            )

    governing = max(states, key=lambda state: state["von_mises_stress"])
    yield_failure_pressure = (
        external_pressure * yield_strength / governing["von_mises_stress"]
    )
    one_minus_poisson_squared = 1.0 - poisson_ratio**2
    classical_pressure = (
        2.0
        * elastic_modulus
        / math.sqrt(3.0 * one_minus_poisson_squared)
        * (wall_thickness / mean_radius) ** 2
    )
    nasa_lambda = (
        (12.0 * one_minus_poisson_squared) ** 0.25
        * math.sqrt(radius_ratio)
        * math.sqrt(2.0)
    )
    nasa_factor = 0.14 + 3.2 / nasa_lambda**2 if nasa_lambda > 2.0 else None
    nasa_candidate_pressure = (
        nasa_factor * classical_pressure if nasa_factor is not None else None
    )
    nasa_candidate_stress = (
        nasa_candidate_pressure * mean_radius / (2.0 * wall_thickness)
        if nasa_candidate_pressure is not None
        else None
    )
    underpressure_pressure = (
        0.365 * elastic_modulus * (wall_thickness / mean_radius) ** 2
    )

    violations = []
    if radius_ratio <= 10.0:
        violations.append("mean_radius / wall_thickness must be > 10")
    if nasa_lambda <= 2.0:
        violations.append("NASA SP-8032 geometry parameter lambda must be > 2")
    if nasa_candidate_stress is not None:
        if proportional_limit is None:
            violations.append("proportional limit is required")
        elif nasa_candidate_stress > proportional_limit:
            violations.append("NASA critical membrane stress exceeds proportional limit")
    capacity_released = not violations and nasa_candidate_pressure is not None
    released_pressure = nasa_candidate_pressure if capacity_released else None

    return {
        "branch": branch,
        "internal_radius": internal_radius,
        "external_radius": external_radius,
        "mean_radius": mean_radius,
        "wall_thickness": wall_thickness,
        "mean_radius_over_thickness": radius_ratio,
        "external_pressure": external_pressure,
        "elastic_modulus": elastic_modulus,
        "poisson_ratio": poisson_ratio,
        "yield_strength": yield_strength,
        "proportional_limit": proportional_limit,
        "stress_states": states,
        "governing_radius": governing["radius"],
        "governing_von_mises_stress": governing["von_mises_stress"],
        "theoretical_yield_failure_pressure": yield_failure_pressure,
        "yield_margin": yield_failure_pressure / external_pressure - 1.0,
        "classical_critical_pressure": classical_pressure,
        "nasa_geometry_parameter_lambda": nasa_lambda,
        "nasa_correlation_factor": nasa_factor,
        "nasa_candidate_design_pressure": nasa_candidate_pressure,
        "nasa_candidate_critical_membrane_stress": nasa_candidate_stress,
        "underpressure_probable_minimum_pressure": underpressure_pressure,
        "buckling_capacity_status": (
            "released" if capacity_released else "withheld_applicability"
        ),
        "released_buckling_pressure": released_pressure,
        "released_buckling_critical_membrane_stress": (
            nasa_candidate_stress if capacity_released else None
        ),
        "buckling_margin": (
            released_pressure / external_pressure - 1.0
            if released_pressure is not None
            else None
        ),
        "buckling_validity_violations": violations,
        "source": (
            "Roark 6th ed. Tables 28/32 sphere stress and Table 35 case 22 "
            "probable minimum; NASA SP-8032 sec. 4.2.1.1 Eqs. 1-4"
        ),
    }


def tube_sizing_zero_margin_thickness(
    *,
    external_pressure: float,
    internal_radius: float,
    yield_strength: float,
    lower_thickness: float,
    upper_thickness: float,
) -> float:
    """Bisect the tube von Mises margin to zero for the CLI sizing golden."""

    def margin(thickness: float) -> float:
        return closed_end_tube_reference(
            external_pressure=external_pressure,
            internal_radius=internal_radius,
            wall_thickness=thickness,
            yield_strength=yield_strength,
        )["margin"]

    low = lower_thickness
    high = upper_thickness
    if not margin(low) < 0.0 <= margin(high):
        raise RuntimeError("sizing bracket does not straddle zero margin")
    for _ in range(200):
        mid = (low + high) / 2.0
        if margin(mid) < 0.0:
            low = mid
        else:
            high = mid
    return high


def flat_circular_plate_reference(
    *,
    external_pressure: float,
    free_radius: float,
    plate_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
    yield_strength: float,
    boundary_condition: Literal["fixed", "simply_supported"],
) -> dict[str, Any]:
    """Roark Table 24, cases 10a/10b, in any consistent units."""
    radius_thickness_squared = (free_radius / plate_thickness) ** 2
    rigidity = elastic_modulus * plate_thickness**3 / (
        12.0 * (1.0 - poisson_ratio**2)
    )
    if boundary_condition == "fixed":
        radial_coefficient = 3.0 / 4.0
        tangential_coefficient = 3.0 * (1.0 + poisson_ratio) / 8.0
        deflection_multiplier = 1.0
        radial_location = "free_diameter"
        source_case = "Roark Table 24 case 10b"
    else:
        radial_coefficient = 3.0 * (3.0 + poisson_ratio) / 8.0
        tangential_coefficient = radial_coefficient
        deflection_multiplier = (5.0 + poisson_ratio) / (1.0 + poisson_ratio)
        radial_location = "center"
        source_case = "Roark Table 24 case 10a"

    radial_stress = (
        radial_coefficient * external_pressure * radius_thickness_squared
    )
    tangential_stress = (
        tangential_coefficient * external_pressure * radius_thickness_squared
    )
    fixed_deflection = external_pressure * free_radius**4 / (64.0 * rigidity)
    deflection = fixed_deflection * deflection_multiplier
    shear = external_pressure * 2.0 * free_radius / (4.0 * plate_thickness)
    # First-order shear-deformation center increment q*a^2/(4*kappa*G*t),
    # kappa = 5/6.  The small-deflection limit is checked against this
    # estimate rather than against the measurably low Kirchhoff deflection.
    shear_modulus = elastic_modulus / (2.0 * (1.0 + poisson_ratio))
    shear_corrected_deflection = deflection + external_pressure * free_radius**2 / (
        4.0 * (5.0 / 6.0) * shear_modulus * plate_thickness
    )
    radial_failure = external_pressure * yield_strength / radial_stress
    tangential_failure = external_pressure * yield_strength / tangential_stress
    governing_stress = max(radial_stress, tangential_stress)
    diameter_thickness = 2.0 * free_radius / plate_thickness
    # Independently transcribed from the swept CAX8R evidence in
    # validation/fea/results/p5_03_plate_sweep_summary.json.
    bending_minimum_ratio = {"fixed": 10.0, "simply_supported": 4.0}[boundary_condition]
    deflection_minimum_ratio = {"fixed": 20.0, "simply_supported": 10.0}[
        boundary_condition
    ]
    poisson_band = (0.05, 0.35)
    poisson_in_band = poisson_band[0] <= poisson_ratio <= poisson_band[1]
    poisson_band_violation = (
        f"poisson_ratio is outside the swept evidence band "
        f"{poisson_band[0]} <= poisson_ratio <= {poisson_band[1]}"
    )
    small_deflection_violation = (
        "shear_corrected_deflection_estimate exceeds plate_thickness / 2, "
        "the small-deflection limit"
    )
    violations: list[str] = []
    if diameter_thickness < bending_minimum_ratio:
        violations.append(
            f"free_diameter / plate_thickness is below {bending_minimum_ratio}, "
            f"the {boundary_condition} bending-stress evidence floor"
        )
    if not poisson_in_band:
        violations.append(poisson_band_violation)
    if shear_corrected_deflection > plate_thickness / 2.0:
        violations.append(small_deflection_violation)
    deflection_violations: list[str] = []
    if diameter_thickness < deflection_minimum_ratio:
        deflection_violations.append(
            f"free_diameter / plate_thickness is below {deflection_minimum_ratio}, "
            f"the {boundary_condition} center-deflection evidence floor"
        )
    if not poisson_in_band:
        deflection_violations.append(poisson_band_violation)
    if shear_corrected_deflection > plate_thickness / 2.0:
        deflection_violations.append(small_deflection_violation)
    return {
        "boundary_condition": boundary_condition,
        "source_equation_case": source_case,
        "free_radius": free_radius,
        "free_diameter": 2.0 * free_radius,
        "plate_thickness": plate_thickness,
        "free_diameter_over_thickness": diameter_thickness,
        "external_pressure": external_pressure,
        "elastic_modulus": elastic_modulus,
        "poisson_ratio": poisson_ratio,
        "yield_strength": yield_strength,
        "flexural_rigidity": rigidity,
        "radial_bending_stress_coefficient": radial_coefficient,
        "tangential_bending_stress_coefficient": tangential_coefficient,
        "maximum_radial_bending_stress": radial_stress,
        "maximum_radial_stress_location": radial_location,
        "maximum_tangential_bending_stress": tangential_stress,
        "maximum_tangential_stress_location": "center",
        "governing_bending_stress": governing_stress,
        "transverse_shear_stress": shear,
        "maximum_deflection": deflection,
        "maximum_deflection_over_thickness": deflection / plate_thickness,
        "shear_corrected_deflection_estimate": shear_corrected_deflection,
        "shear_corrected_deflection_estimate_over_thickness": (
            shear_corrected_deflection / plate_thickness
        ),
        "deflection_status": (
            "withheld_applicability" if deflection_violations else "released"
        ),
        "released_maximum_deflection": (
            None if deflection_violations else deflection
        ),
        "deflection_validity_violations": deflection_violations,
        "bending_minimum_free_diameter_over_thickness": bending_minimum_ratio,
        "deflection_minimum_free_diameter_over_thickness": deflection_minimum_ratio,
        "poisson_ratio_evidence_band": list(poisson_band),
        "theoretical_radial_failure_pressure": radial_failure,
        "theoretical_tangential_failure_pressure": tangential_failure,
        "theoretical_failure_pressure": min(radial_failure, tangential_failure),
        "margin": yield_strength / governing_stress - 1.0,
        "validity_violations": violations,
        "source": (
            "Roark 6th ed. Table 24 cases 10a-10b, p. 429; shear follows "
            "UnderPressure 4.0 Example 2, tau=p*D_free/(4*t)"
        ),
    }


def _smooth_coefficient(beta: float, gamma_z: float, load_case: str) -> float:
    beta_squared = beta**2
    y = 1.0 + beta_squared
    numerator = y**2 + 12.0 * gamma_z**2 / (math.pi**4 * y**2)
    denominator = beta_squared if load_case == "lateral_only" else beta_squared + 0.5
    return numerator / denominator


def _independent_continuous_minimum(
    gamma_z: float,
    load_case: Literal["lateral_only", "hydrostatic_closed_end"],
) -> tuple[float, float]:
    """Minimize Eqs. 20/22 directly, without the production polynomial."""
    # First bracket on a wide logarithmic grid, then use a golden-section
    # minimization on beta itself.  This is deliberately a different numerical
    # route from the stationary-polynomial bisection in production.
    grid = [10.0 ** (-6.0 + 12.0 * index / 600.0) for index in range(601)]
    values = [_smooth_coefficient(beta, gamma_z, load_case) for beta in grid]
    minimum_index = min(range(len(grid)), key=values.__getitem__)
    if minimum_index in (0, len(grid) - 1):
        raise RuntimeError("continuous-mode minimum was not bracketed")
    lower = grid[minimum_index - 1]
    upper = grid[minimum_index + 1]
    inverse_phi = (math.sqrt(5.0) - 1.0) / 2.0
    left = upper - inverse_phi * (upper - lower)
    right = lower + inverse_phi * (upper - lower)
    left_value = _smooth_coefficient(left, gamma_z, load_case)
    right_value = _smooth_coefficient(right, gamma_z, load_case)
    for _ in range(220):
        if left_value < right_value:
            upper = right
            right = left
            right_value = left_value
            left = upper - inverse_phi * (upper - lower)
            left_value = _smooth_coefficient(left, gamma_z, load_case)
        else:
            lower = left
            left = right
            left_value = right_value
            right = lower + inverse_phi * (upper - lower)
            right_value = _smooth_coefficient(right, gamma_z, load_case)
    beta = (lower + upper) / 2.0
    return beta, _smooth_coefficient(beta, gamma_z, load_case)


def smooth_cylinder_reference(
    *,
    external_pressure_mpa: float,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    yield_strength_mpa: float,
    load_case: Literal["lateral_only", "hydrostatic_closed_end"],
    proportional_limit_mpa: float | None,
) -> dict[str, Any]:
    """Independent NASA/SP-8007 Rev. 2 Eqs. 17-29 transcription."""
    radius = shell_mid_surface_radius_mm
    thickness = wall_thickness_mm
    length = unsupported_length_mm
    one_minus_nu_squared = 1.0 - poisson_ratio**2
    radius_thickness = radius / thickness
    length_radius = length / radius
    rigidity = elastic_modulus_mpa * thickness**3 / (
        12.0 * one_minus_nu_squared
    )
    z = length**2 / (radius * thickness) * math.sqrt(one_minus_nu_squared)
    geometry_parameter = radius_thickness * math.sqrt(one_minus_nu_squared)
    moderate_long_boundary = 11.8 * geometry_parameter**2

    # NASA/SP-8007-2020/REV 2 puts the Eq. 28 correlation factor inside Eqs. 20/22
    # ("The term gamma^2 has been added to Eq. 20 and Eq. 22"), and introduces Eq. 23
    # as what those reduce to "For gamma*Z > 100". This branch therefore carries the
    # correlated capacity below that boundary rather than a gamma=1 theoretical value.
    short_gamma = 0.75**2
    short_gamma_z = short_gamma * z
    _, ideal_k = _independent_continuous_minimum(z, load_case)
    short_beta, short_k = _independent_continuous_minimum(short_gamma_z, load_case)
    scale = math.pi**2 * rigidity / (radius * length**2)
    short_correlated = short_k * scale
    short = {
        "regime": "short",
        "gamma": short_gamma,
        "gamma_z": short_gamma_z,
        "applicable": short_gamma_z <= 100.0,
        "critical_buckling_coefficient": short_k,
        "critical_aspect_ratio_beta": short_beta,
        "continuous_circumferential_wave_count": short_beta * math.pi * radius / length,
        "ideal_critical_pressure_mpa": ideal_k * scale,
        "correlated_critical_pressure_mpa": short_correlated,
        "correlated_critical_circumferential_stress_mpa": (
            short_correlated * radius_thickness
        ),
    }

    moderate_gamma = 0.75**2
    moderate_gamma_z = moderate_gamma * z
    moderate_beta, _ = _independent_continuous_minimum(
        moderate_gamma_z, load_case
    )
    moderate_ideal = 0.855 * elastic_modulus_mpa / (
        one_minus_nu_squared**0.75
        * radius_thickness**2.5
        * length_radius
    )
    moderate_correlated = 0.75 * moderate_ideal
    moderate = {
        "regime": "moderate",
        "gamma": moderate_gamma,
        "gamma_z": moderate_gamma_z,
        "applicable": (
            moderate_gamma_z > 100.0
            and moderate_gamma_z <= moderate_long_boundary
        ),
        "critical_buckling_coefficient": 1.04 * math.sqrt(moderate_gamma_z),
        "critical_aspect_ratio_beta": moderate_beta,
        "continuous_circumferential_wave_count": moderate_beta * math.pi * radius / length,
        "ideal_critical_pressure_mpa": moderate_ideal,
        "correlated_critical_pressure_mpa": moderate_correlated,
        "correlated_critical_circumferential_stress_mpa": (
            moderate_correlated * radius_thickness
        ),
        "eq25_simplified_critical_pressure_mpa": (
            0.926
            * elastic_modulus_mpa
            * 0.75
            / (radius_thickness**2.5 * length_radius)
            if math.isclose(poisson_ratio, 0.316, rel_tol=0.0, abs_tol=1.0e-12)
            else None
        ),
    }

    long_gamma = 0.90
    long_ideal = (
        elastic_modulus_mpa
        / (4.0 * one_minus_nu_squared)
        * (thickness / radius) ** 3
    )
    long_correlated = long_gamma * long_ideal
    long = {
        "regime": "long",
        "gamma": long_gamma,
        "gamma_z": long_gamma * z,
        "applicable": long_gamma * z >= moderate_long_boundary,
        "critical_buckling_coefficient": (
            3.0 * long_gamma * z / (math.pi**2 * geometry_parameter)
        ),
        "critical_aspect_ratio_beta": None,
        "continuous_circumferential_wave_count": 2.0,
        "circumferential_wave_count_n": 2,
        "ideal_critical_pressure_mpa": long_ideal,
        "correlated_critical_pressure_mpa": long_correlated,
        "correlated_critical_circumferential_stress_mpa": (
            long_correlated * radius_thickness
        ),
    }

    selected: dict[str, Any] | None = None
    if short["applicable"]:
        regime = "short"
        gate_status = "released"
        selected = short
    elif moderate["applicable"] and long["applicable"]:
        regime = "moderate_long_correlation_overlap"
        gate_status = "withheld_correlation_overlap"
    elif moderate["applicable"]:
        regime = "moderate"
        gate_status = "released"
        selected = moderate
    else:
        # Short and moderate share one gamma, so they tile gamma*Z without a gap.
        regime = "long"
        gate_status = "released"
        selected = long

    validity_violations: list[str] = []
    plasticity_pending = False
    if radius_thickness <= 10.0:
        validity_violations.append("radius/thickness must be > 10")
    if selected is not None:
        correlated_stress = selected[
            "correlated_critical_circumferential_stress_mpa"
        ]
        if proportional_limit_mpa is None:
            validity_violations.append("proportional limit is required")
        elif correlated_stress > proportional_limit_mpa:
            if validity_violations:
                # Withheld on another gate, so the exceedance is one more violation.
                validity_violations.append(
                    "critical circumferential stress exceeds proportional limit"
                )
            else:
                # Plasticity would reduce this capacity, so it is an elastic upper
                # bound reported pending validation rather than a withheld result.
                plasticity_pending = True
    if validity_violations:
        capacity_status = "withheld_applicability"
    elif plasticity_pending:
        capacity_status = "released_pending_plasticity"
    else:
        capacity_status = gate_status
    released = (
        capacity_status in {"released", "released_pending_plasticity"}
        and selected is not None
    )
    released_pressure = (
        selected["correlated_critical_pressure_mpa"] if released else None
    )
    return {
        "regime": regime,
        "capacity_status": capacity_status,
        "shell_mid_surface_radius_over_thickness": radius_thickness,
        "unsupported_length_over_radius": length_radius,
        "flexural_rigidity_n_mm": rigidity,
        "curvature_parameter_z": z,
        "geometry_mode_parameter": geometry_parameter,
        "circumferential_line_load_n_per_mm": external_pressure_mpa * radius,
        "axial_line_load_n_per_mm": (
            0.0
            if load_case == "lateral_only"
            else external_pressure_mpa * radius / 2.0
        ),
        "moderate_long_boundary_parameter": moderate_long_boundary,
        "moderate_long_overlap_start_z": moderate_long_boundary / long_gamma,
        "moderate_long_overlap_end_z": moderate_long_boundary / moderate_gamma,
        "correlation_factor_gamma": selected["gamma"] if selected else None,
        "sqrt_correlation_factor": (
            math.sqrt(selected["gamma"]) if selected else None
        ),
        "critical_buckling_coefficient": (
            selected["critical_buckling_coefficient"] if selected else None
        ),
        "critical_aspect_ratio_beta": (
            selected["critical_aspect_ratio_beta"] if selected else None
        ),
        "continuous_circumferential_wave_count": (
            selected["continuous_circumferential_wave_count"] if selected else None
        ),
        "circumferential_wave_count_n": (
            selected.get("circumferential_wave_count_n") if selected else None
        ),
        "ideal_critical_pressure_mpa": (
            selected["ideal_critical_pressure_mpa"] if selected else None
        ),
        "correlated_critical_pressure_mpa": released_pressure,
        "margin": (
            released_pressure / external_pressure_mpa - 1.0
            if released_pressure is not None
            else None
        ),
        "validity_violations": validity_violations,
        "candidates": [short, moderate, long],
        "source": (
            "NASA/SP-8007-2020/REV 2 Eqs. 3-5 and 17-29; shell mid-surface "
            "radius, simply-supported ends, lateral or closed-end hydrostatic load"
        ),
    }


def roark_case20_reference(
    *,
    elastic_modulus_psi: float,
    poisson_ratio: float,
    mean_radius_in: float,
    wall_thickness_in: float,
    unsupported_length_in: float,
) -> dict[str, Any]:
    """Roark 6th ed. Table 35 case 20 integer-mode search."""
    best: tuple[float, int] | None = None
    for nodes in range(2, 201):
        ratio = math.pi * mean_radius_in / (nodes * unsupported_length_in)
        inverse_ratio = nodes * unsupported_length_in / (
            math.pi * mean_radius_in
        )
        pressure = (
            elastic_modulus_psi
            * wall_thickness_in
            / mean_radius_in
            / (1.0 + 0.5 * ratio**2)
            * (
                1.0 / (nodes**2 * (1.0 + inverse_ratio**2) ** 2)
                + nodes**2
                * wall_thickness_in**2
                / (
                    12.0
                    * mean_radius_in**2
                    * (1.0 - poisson_ratio**2)
                )
                * (1.0 + ratio**2) ** 2
            )
        )
        if best is None or pressure < best[0]:
            best = (pressure, nodes)
    assert best is not None
    return {
        "ideal_integer_mode_pressure_psi": best[0],
        "probable_minimum_factor": 0.8,
        "probable_minimum_pressure_psi": 0.8 * best[0],
        "governing_circumferential_nodes": best[1],
        "source": "Roark 6th ed. Table 35 case 20; probable-minimum factor 0.8",
    }


def length_for_z(
    z: float,
    *,
    radius: float,
    thickness: float,
    poisson_ratio: float,
) -> float:
    return math.sqrt(
        z * radius * thickness / math.sqrt(1.0 - poisson_ratio**2)
    )


def _smooth_case(**changes: Any) -> dict[str, Any]:
    inputs: dict[str, Any] = {
        "external_pressure_mpa": 0.01,
        "shell_mid_surface_radius_mm": 500.0,
        "wall_thickness_mm": 5.0,
        "unsupported_length_mm": 1800.0,
        "elastic_modulus_mpa": 70_000.0,
        "poisson_ratio": 0.3,
        "yield_strength_mpa": 250.0,
        "load_case": "hydrostatic_closed_end",
        "proportional_limit_mpa": 200.0,
    }
    inputs.update(changes)
    return {"inputs": inputs, "result": smooth_cylinder_reference(**inputs)}


def build_evidence() -> dict[str, Any]:
    """Build the checked P5-02 independent evidence."""
    tube_example_1_inputs = {
        "external_pressure": 1.0,
        "internal_radius": 3.0,
        "wall_thickness": 0.470,
        "yield_strength": 62.0,
    }
    tube_example_1 = closed_end_tube_reference(**tube_example_1_inputs)
    tube_worked_inputs = {
        "external_pressure": 22.6243125,
        "internal_radius": 55.0,
        "wall_thickness": 22.0,
        "yield_strength": 276.0,
    }
    tube_worked = closed_end_tube_reference(**tube_worked_inputs)
    # The CLI sizing golden is the thin-branch zero-margin crossing.  The
    # margin is discontinuous at the thin/thick branch switch (thickness =
    # internal_radius / 9.5, where mean_radius/thickness = 10), so the
    # bracket stays just below that boundary.
    tube_sizing_inputs = {
        "external_pressure": 7.0,
        "internal_radius": 3.0,
        "yield_strength": 62.0,
        "lower_thickness": 0.1,
        "upper_thickness": 3.0 / 9.5 * (1.0 - 1.0e-12),
    }
    tube_sizing_thickness_in = tube_sizing_zero_margin_thickness(
        **tube_sizing_inputs
    )

    hemisphere_manual_inputs = {
        "external_pressure": 1_000.0,
        "internal_radius": 1.75,
        "wall_thickness": 0.25,
        "elastic_modulus": 9_900_000.0,
        "poisson_ratio": 0.33,
        "yield_strength": 35_000.0,
        "proportional_limit": None,
    }
    hemisphere_manual = hemispherical_head_reference(**hemisphere_manual_inputs)
    hemisphere_cli_inputs = {
        "external_pressure": 6.0,
        "internal_radius": 100.0,
        "wall_thickness": 100.0 / 39.5,
        "elastic_modulus": 68_900.0,
        "poisson_ratio": 0.33,
        "yield_strength": 276.0,
        "proportional_limit": 200.0,
    }
    hemisphere_cli = hemispherical_head_reference(**hemisphere_cli_inputs)

    plate_example_2_inputs = {
        "external_pressure": 4.5,
        "free_radius": 3.0,
        "plate_thickness": 1.280,
        "elastic_modulus": 10_300.0,
        "poisson_ratio": 0.33,
        "yield_strength": 62.0,
        "boundary_condition": "simply_supported",
    }
    plate_example_2 = flat_circular_plate_reference(**plate_example_2_inputs)
    appendix_common = {
        "external_pressure": 1_000.0,
        "free_radius": 2.5,
        "plate_thickness": 0.625,
        "elastic_modulus": 10_000_000.0,
        "poisson_ratio": 0.30,
        "yield_strength": 62_000.0,
    }
    appendix_simply = flat_circular_plate_reference(
        **appendix_common, boundary_condition="simply_supported"
    )
    appendix_fixed = flat_circular_plate_reference(
        **appendix_common, boundary_condition="fixed"
    )

    short_lateral = _smooth_case(
        external_pressure_mpa=1.0,
        unsupported_length_mm=300.0,
        load_case="lateral_only",
    )
    short_hydrostatic = _smooth_case(
        external_pressure_mpa=1.0,
        unsupported_length_mm=300.0,
    )
    moderate = _smooth_case()
    moderate_nu_0316 = _smooth_case(poisson_ratio=0.316)
    long = _smooth_case(wall_thickness_mm=25.0, unsupported_length_mm=11_000.0)
    migrated_long = _smooth_case(
        shell_mid_surface_radius_mm=1010.0,
        wall_thickness_mm=20.0,
        unsupported_length_mm=100_000.0,
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        yield_strength_mpa=276.0,
    )

    underpressure_example_1_buckling = roark_case20_reference(
        elastic_modulus_psi=10.3e6,
        poisson_ratio=0.33,
        mean_radius_in=3.0 + 0.470 / 2.0,
        wall_thickness_in=0.470,
        unsupported_length_in=24.0,
    )
    underpressure_example_4_buckling = roark_case20_reference(
        elastic_modulus_psi=0.41e6,
        poisson_ratio=0.4,
        mean_radius_in=2.5 + 0.240 / 2.0,
        wall_thickness_in=0.240,
        unsupported_length_in=10.0,
    )
    roark_matrix = {
        str(length): roark_case20_reference(
            elastic_modulus_psi=10.0e6,
            poisson_ratio=0.3,
            mean_radius_in=5.0,
            wall_thickness_in=0.25,
            unsupported_length_in=length,
        )
        for length in (5.0, 20.0, 100.0, 110.0)
    }

    published_values = {
        "underpressure_4_0_example_2_manual_display_failure_ksi": 9.038,
        "repo_four_decimal_manual_traceable_goldens_ksi": {
            "tube_example_1_failure": 9.0401,
            "plate_example_2_failure": 9.0384,
        },
        "underpressure_appendix_e_plate_stresses_psi": {
            "simply_supported_radial": 19_800.0,
            "simply_supported_tangential": 19_800.0,
            "fixed_radial": 12_000.0,
            "fixed_tangential": 7_800.0,
        },
        "underpressure_4_0_example_1_invalid_thin_buckling_psi": 10_632.0,
        "underpressure_4_0_example_4_valid_thin_buckling_psi": 266.60,
        "underpressure_4_0_hemisphere_manual_display_psi": {
            "stress_at_1000_psi": 4_544.4,
            "shell_failure": 7_701.8,
            "invalid_thin_wall_buckling": 64_240.0,
        },
        "underpressure_4_60_capture": {
            "status": "open_human_operated_item",
            "accepted_as_4_60_evidence": False,
        },
    }
    calculated_values = {
        "tube": {
            "underpressure_example_1_in_ksi_and_in": tube_example_1,
            "worked_example_in_mpa_and_mm": tube_worked,
            "cli_sizing_zero_margin_thickness_in": tube_sizing_thickness_in,
            "cli_sizing_zero_margin_thickness_mm": (
                tube_sizing_thickness_in * INCH_TO_MM
            ),
        },
        "hemisphere": {
            "underpressure_manual_in_psi_and_in": hemisphere_manual,
            "released_cli_in_mpa_and_mm": hemisphere_cli,
        },
        "plate": {
            "underpressure_example_2_in_ksi_and_in": plate_example_2,
            "appendix_e_simply_supported_in_psi_and_in": appendix_simply,
            "appendix_e_fixed_in_psi_and_in": appendix_fixed,
        },
        "smooth_cylinder": {
            "short_lateral": short_lateral,
            "short_hydrostatic": short_hydrostatic,
            "moderate": moderate,
            "moderate_nu_0_316": moderate_nu_0316,
            "long": long,
            "adapter_mid_surface_migrated_long": migrated_long,
            "underpressure_example_1_roark_even_though_invalid": (
                underpressure_example_1_buckling
            ),
            "underpressure_example_4_roark": underpressure_example_4_buckling,
            "roark_case20_length_matrix": roark_matrix,
        },
    }
    goldens = published_values["repo_four_decimal_manual_traceable_goldens_ksi"]
    appendix_displays = published_values["underpressure_appendix_e_plate_stresses_psi"]
    comparisons = {
        "tube_example_1_failure_minus_repo_golden_ksi": (
            tube_example_1["theoretical_failure_pressure"]
            - goldens["tube_example_1_failure"]
        ),
        "plate_example_2_failure_minus_repo_golden_ksi": (
            plate_example_2["theoretical_failure_pressure"]
            - goldens["plate_example_2_failure"]
        ),
        "plate_example_2_failure_minus_manual_display_ksi": (
            plate_example_2["theoretical_failure_pressure"]
            - published_values[
                "underpressure_4_0_example_2_manual_display_failure_ksi"
            ]
        ),
        "appendix_e_minus_display_psi": {
            "simply_supported_radial": (
                appendix_simply["maximum_radial_bending_stress"]
                - appendix_displays["simply_supported_radial"]
            ),
            "simply_supported_tangential": (
                appendix_simply["maximum_tangential_bending_stress"]
                - appendix_displays["simply_supported_tangential"]
            ),
            "fixed_radial": (
                appendix_fixed["maximum_radial_bending_stress"]
                - appendix_displays["fixed_radial"]
            ),
            "fixed_tangential": (
                appendix_fixed["maximum_tangential_bending_stress"]
                - appendix_displays["fixed_tangential"]
            ),
        },
        "invalid_example_1_roark_difference_psi": (
            underpressure_example_1_buckling["probable_minimum_pressure_psi"]
            - published_values[
                "underpressure_4_0_example_1_invalid_thin_buckling_psi"
            ]
        ),
        "valid_example_4_roark_difference_psi": (
            underpressure_example_4_buckling["probable_minimum_pressure_psi"]
            - published_values[
                "underpressure_4_0_example_4_valid_thin_buckling_psi"
            ]
        ),
        "hemisphere_manual_minus_display_psi": {
            "stress_at_1000_psi": (
                hemisphere_manual["governing_von_mises_stress"]
                - published_values["underpressure_4_0_hemisphere_manual_display_psi"][
                    "stress_at_1000_psi"
                ]
            ),
            "shell_failure": (
                hemisphere_manual["theoretical_yield_failure_pressure"]
                - published_values["underpressure_4_0_hemisphere_manual_display_psi"][
                    "shell_failure"
                ]
            ),
            "invalid_thin_wall_buckling": (
                hemisphere_manual["underpressure_probable_minimum_pressure"]
                - published_values["underpressure_4_0_hemisphere_manual_display_psi"][
                    "invalid_thin_wall_buckling"
                ]
            ),
        },
    }
    return {
        "classification": {
            "evidence_role": "independent_equation_and_manual_software_parity_audit",
            "not": [
                "physical_validation",
                "calibration",
                "allowable_pressure",
                "design_approval",
                "underpressure_4_60_capture",
            ],
        },
        "sources": {
            "underpressure_manual": UNDERPRESSURE_MANUAL,
            "nasa_sp_8007_rev2": NASA_SP_8007_REV2,
            "nasa_sp_8032": NASA_SP_8032,
            "roark": {
                "edition": "6th",
                "tube": "Tables 28 and 32",
                "hemisphere": "Tables 28 and 32 for stress; Table 35 case 22 for buckling",
                "plate": "Table 24 cases 10a-10b, p. 429",
                "smooth_overlap": "Table 35 case 20",
            },
        },
        "source_inputs": {
            "tube_example_1": tube_example_1_inputs,
            "tube_worked": tube_worked_inputs,
            "tube_cli_sizing": tube_sizing_inputs,
            "hemisphere_manual": hemisphere_manual_inputs,
            "hemisphere_cli": hemisphere_cli_inputs,
            "plate_example_2": plate_example_2_inputs,
            "appendix_e": appendix_common,
        },
        "published_values": published_values,
        "calculated_values": calculated_values,
        "tolerances": {
            "independent_vs_production_relative": REFERENCE_RELATIVE_TOLERANCE,
            "independent_vs_production_absolute": REFERENCE_ABSOLUTE_TOLERANCE,
            "published_half_displayed_digit": PUBLISHED_TOLERANCES,
        },
        "comparisons": comparisons,
    }


def main() -> None:
    print(json.dumps(build_evidence(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
