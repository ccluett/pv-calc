"""Independent NASA Eq. 64/65 and 82-91 ring-shell reference calculation.

This module intentionally uses only the Python standard library.  It does not
import pv_calc calculations, section helpers, adapters, or regression
outputs.  The fixed exhaustive mode bounds are deliberately simple and cover
the modest DTMB and convergence-trap domain represented here.  The axial
half-wave count also obeys pv-calc's smeared-mode screen, which is a project
rule rather than a NASA equation: a global half-wave is longer than one ring
spacing, and m = 1 is always admitted.

Sources: NASA/SP-8007-2020/REV 2, printed pp. 35, 37, and 40-42, Eqs. 54-59,
64-65, and 82-91; NASA/TP-2011-216882, Appendix A, printed p. 100, Eq. A16;
DTMB Report 1324 (1959), Figure 2 and Table 2.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


NASA_EQ64_ADJUSTMENT_FACTOR = 0.75
EXHAUSTIVE_MAX_AXIAL_HALF_WAVES = 128
EXHAUSTIVE_MAX_CIRCUMFERENTIAL_LOBES = 64
DTMB_LENGTH_DIAMETER_ABSOLUTE_TOLERANCE = 1.0e-2


@dataclass(frozen=True)
class RingCase:
    case_id: str
    length_unit: Literal["in", "mm"]
    pressure_unit: Literal["psi", "MPa"]
    shell_mid_surface_radius: float
    wall_thickness: float
    unsupported_length: float
    ring_spacing: float
    ring_axial_width: float
    ring_radial_height: float
    ring_location: Literal["internal", "external"]
    elastic_modulus: float
    poisson_ratio: float


@dataclass(frozen=True)
class RectangleProperties:
    area: float
    centroid_from_shell_surface: float
    centroidal_inertia: float
    saint_venant_torsional_constant: float


@dataclass(frozen=True)
class OrthotropicStiffnesses:
    extensional_x: float
    extensional_y: float
    extensional_xy: float
    shear_xy: float
    bending_x: float
    bending_y: float
    bending_xy: float
    coupling_x: float
    coupling_y: float
    coupling_xy: float
    shear_coupling_xy: float
    ring_eccentricity: float
    ring_torsion_increment: float


@dataclass(frozen=True)
class ModeResult:
    ideal_critical_pressure: float
    adjusted_critical_pressure: float
    axial_half_waves_m: int
    circumferential_lobes_n: int


@dataclass(frozen=True)
class CaseResult:
    case: RingCase
    rectangle: RectangleProperties
    without_ring_torsion: ModeResult
    with_ring_torsion: ModeResult
    torsion_ideal_pressure_increment: float
    torsion_adjusted_pressure_increment: float
    torsion_changes_governing_mode: bool


def rectangular_section_properties(
    axial_width: float,
    radial_height: float,
    *,
    series_tolerance: float = 1.0e-16,
    maximum_series_terms: int = 100_000,
) -> RectangleProperties:
    """Transcribe rectangle A, I, and isotropic NASA/TP Eq. A16 J.

    NASA/TP-2011-216882 Appendix A Eq. A16, printed p. 100, reduces
    for an isotropic rectangle to the odd-integer Saint-Venant series used
    below.  The series is evaluated directly rather than using production's
    optimized zeta/correction implementation.
    """

    if axial_width <= 0.0 or radial_height <= 0.0:
        raise ValueError("rectangle dimensions must be positive")
    longer = max(axial_width, radial_height)
    shorter = min(axial_width, radial_height)
    odd_series = 0.0
    for odd_integer in range(1, 2 * maximum_series_terms, 2):
        term = math.tanh(
            odd_integer * math.pi * longer / (2.0 * shorter)
        ) / odd_integer**5
        odd_series += term
        if term < series_tolerance:
            break
    else:
        raise RuntimeError("NASA/TP Eq. A16 rectangle torsion series did not converge")

    torsion_constant = (
        longer
        * shorter**3
        / 3.0
        * (
            1.0
            - 192.0
            * shorter
            / (math.pi**5 * longer)
            * odd_series
        )
    )
    return RectangleProperties(
        area=axial_width * radial_height,
        centroid_from_shell_surface=0.5 * radial_height,
        centroidal_inertia=axial_width * radial_height**3 / 12.0,
        saint_venant_torsional_constant=torsion_constant,
    )


def _orthotropic_stiffnesses(
    case: RingCase,
    rectangle: RectangleProperties,
    *,
    include_ring_torsion: bool,
) -> OrthotropicStiffnesses:
    """Transcribe the ring-only specialization of NASA Eqs. 82-91."""

    elastic_modulus = case.elastic_modulus
    thickness = case.wall_thickness
    poisson_ratio = case.poisson_ratio
    spacing = case.ring_spacing
    ring_sign = 1.0 if case.ring_location == "external" else -1.0
    eccentricity = ring_sign * (
        0.5 * thickness + rectangle.centroid_from_shell_surface
    )
    ring_shear_modulus = elastic_modulus / (2.0 * (1.0 + poisson_ratio))
    ring_torsion_increment = (
        ring_shear_modulus
        * rectangle.saint_venant_torsional_constant
        / spacing
        if include_ring_torsion
        else 0.0
    )

    shell_extensional = elastic_modulus * thickness / (1.0 - poisson_ratio**2)
    shell_bending = (
        elastic_modulus
        * thickness**3
        / (12.0 * (1.0 - poisson_ratio**2))
    )
    return OrthotropicStiffnesses(
        extensional_x=shell_extensional,
        extensional_y=(
            shell_extensional + elastic_modulus * rectangle.area / spacing
        ),
        extensional_xy=(
            poisson_ratio
            * elastic_modulus
            * thickness
            / (1.0 - poisson_ratio**2)
        ),
        shear_xy=elastic_modulus * thickness / (2.0 * (1.0 + poisson_ratio)),
        bending_x=shell_bending,
        bending_y=(
            shell_bending
            + elastic_modulus * rectangle.centroidal_inertia / spacing
            + eccentricity**2 * elastic_modulus * rectangle.area / spacing
        ),
        bending_xy=(
            poisson_ratio
            * elastic_modulus
            * thickness**3
            / (6.0 * (1.0 - poisson_ratio**2))
            + elastic_modulus * thickness**3 / (6.0 * (1.0 + poisson_ratio))
            + ring_torsion_increment
        ),
        coupling_x=0.0,
        coupling_y=eccentricity * elastic_modulus * rectangle.area / spacing,
        coupling_xy=0.0,
        shear_coupling_xy=0.0,
        ring_eccentricity=eccentricity,
        ring_torsion_increment=ring_torsion_increment,
    )


def _determinant_3x3(matrix: tuple[tuple[float, float, float], ...]) -> float:
    (a, b, c), (d, e, f), (g, h, i) = matrix
    return a * (e * i - f * h) - b * (d * i - f * g) + c * (d * h - e * g)


def _mode_pressure(
    case: RingCase,
    stiffness: OrthotropicStiffnesses,
    axial_half_waves_m: int,
    circumferential_lobes_n: int,
) -> float:
    """Transcribe NASA Eqs. 54-59, Eq. 64, and hydrostatic Eq. 65."""

    radius = case.shell_mid_surface_radius
    axial_wave_number = axial_half_waves_m * math.pi / case.unsupported_length
    circumferential_wave_number = circumferential_lobes_n / radius

    a11 = (
        stiffness.extensional_x * axial_wave_number**2
        + stiffness.shear_xy * circumferential_wave_number**2
    )
    a22 = (
        stiffness.extensional_y * circumferential_wave_number**2
        + stiffness.shear_xy * axial_wave_number**2
    )
    a33 = (
        stiffness.bending_x * axial_wave_number**4
        + stiffness.bending_xy
        * axial_wave_number**2
        * circumferential_wave_number**2
        + stiffness.bending_y * circumferential_wave_number**4
        + stiffness.extensional_y / radius**2
        + 2.0
        * stiffness.coupling_y
        * circumferential_wave_number**2
        / radius
        + 2.0 * stiffness.coupling_xy * axial_wave_number**2 / radius
    )
    a12 = (
        (stiffness.extensional_xy + stiffness.shear_xy)
        * axial_wave_number
        * circumferential_wave_number
    )
    a13 = (
        stiffness.extensional_xy * axial_wave_number / radius
        + stiffness.coupling_x * axial_wave_number**3
        + (stiffness.coupling_xy + 2.0 * stiffness.shear_coupling_xy)
        * axial_wave_number
        * circumferential_wave_number**2
    )
    a23 = (
        (stiffness.coupling_xy + 2.0 * stiffness.shear_coupling_xy)
        * axial_wave_number**2
        * circumferential_wave_number
        + stiffness.extensional_y * circumferential_wave_number / radius
        + stiffness.coupling_y * circumferential_wave_number**3
    )

    determinant_2x2 = a11 * a22 - a12**2
    if determinant_2x2 <= 0.0:
        raise ArithmeticError("non-positive Eq. 64 in-plane determinant")
    determinant_3x3 = _determinant_3x3(
        (
            (a11, a12, a13),
            (a12, a22, a23),
            (a13, a23, a33),
        )
    )
    hydrostatic_denominator = circumferential_lobes_n**2 + 0.5 * (
        axial_half_waves_m * math.pi * radius / case.unsupported_length
    ) ** 2
    pressure = (
        radius
        / hydrostatic_denominator
        * determinant_3x3
        / determinant_2x2
    )
    if not math.isfinite(pressure) or pressure <= 0.0:
        raise ArithmeticError("non-positive Eq. 64/65 modal pressure")
    return pressure


def admissible_axial_half_waves(case: RingCase) -> int:
    """Largest m whose half-wave L/m is longer than one ring spacing, at least 1.

    The relative allowance keeps a length that is an exact multiple of the
    spacing, rounded in its last digit, from admitting the one-spacing wave.
    """
    count = 1
    while (count + 1) * case.ring_spacing < case.unsupported_length * (1.0 - 1.0e-12):
        count += 1
    return count


def _exhaustive_mode_scan(
    case: RingCase,
    rectangle: RectangleProperties,
    *,
    include_ring_torsion: bool,
    max_axial_half_waves: int = EXHAUSTIVE_MAX_AXIAL_HALF_WAVES,
    max_circumferential_lobes: int = EXHAUSTIVE_MAX_CIRCUMFERENTIAL_LOBES,
) -> ModeResult:
    stiffness = _orthotropic_stiffnesses(
        case,
        rectangle,
        include_ring_torsion=include_ring_torsion,
    )
    admissible = admissible_axial_half_waves(case)
    axial_limit = min(max_axial_half_waves, admissible)
    candidates = (
        (
            _mode_pressure(case, stiffness, axial_half_waves, lobes),
            axial_half_waves,
            lobes,
        )
        for axial_half_waves in range(1, axial_limit + 1)
        for lobes in range(2, max_circumferential_lobes + 1)
    )
    pressure, axial_half_waves, lobes = min(candidates)
    # The screen's own limit is a real edge of the domain; only the fixed
    # scan bounds would leave a lower mode unexamined.
    if (
        axial_half_waves == max_axial_half_waves < admissible
        or lobes == max_circumferential_lobes
    ):
        raise RuntimeError("governing reference mode lies on an exhaustive upper bound")
    return ModeResult(
        ideal_critical_pressure=pressure,
        adjusted_critical_pressure=pressure * NASA_EQ64_ADJUSTMENT_FACTOR,
        axial_half_waves_m=axial_half_waves,
        circumferential_lobes_n=lobes,
    )


def solve_case(case: RingCase) -> CaseResult:
    rectangle = rectangular_section_properties(
        case.ring_axial_width,
        case.ring_radial_height,
    )
    without_torsion = _exhaustive_mode_scan(
        case,
        rectangle,
        include_ring_torsion=False,
    )
    with_torsion = _exhaustive_mode_scan(
        case,
        rectangle,
        include_ring_torsion=True,
    )
    return CaseResult(
        case=case,
        rectangle=rectangle,
        without_ring_torsion=without_torsion,
        with_ring_torsion=with_torsion,
        torsion_ideal_pressure_increment=(
            with_torsion.ideal_critical_pressure
            - without_torsion.ideal_critical_pressure
        ),
        torsion_adjusted_pressure_increment=(
            with_torsion.adjusted_critical_pressure
            - without_torsion.adjusted_critical_pressure
        ),
        torsion_changes_governing_mode=(
            with_torsion.axial_half_waves_m,
            with_torsion.circumferential_lobes_n,
        )
        != (
            without_torsion.axial_half_waves_m,
            without_torsion.circumferential_lobes_n,
        ),
    )


# DTMB Report 1324 Table 2: frame spaces, L/D, Kendrick Part III pressure (psi)
# and lobes, experimental pressure (psi) and lobes.
DTMB_TABLE_2_PUBLISHED = (
    (17, 2.40, 428, 3, 473, 3),
    (21, 2.96, 404, 3, 422, 3),
    (23, 3.25, 367, 2, 412, 3),
    (25, 3.53, 305, 2, 401, 3),
    (26, 3.67, 281, 2, 398, 3),
    (27, 3.81, 262, 2, 394, 3),
    (28, 3.96, 246, 2, 391, 3),
    (29, 4.10, 233, 2, 383, 2),
    (31, 4.38, 212, 2, 329, 2),
    (33, 4.66, 197, 2, 281, 2),
)


def dtmb_case(frame_spaces: int) -> RingCase:
    return RingCase(
        case_id=f"dtmb_1324_{frame_spaces}_spaces",
        length_unit="in",
        pressure_unit="psi",
        shell_mid_surface_radius=8.118 / 2.0 + 0.035 / 2.0,
        wall_thickness=0.035,
        unsupported_length=frame_spaces * 1.152,
        ring_spacing=1.152,
        ring_axial_width=0.086,
        ring_radial_height=0.169,
        ring_location="external",
        elastic_modulus=30_000_000.0,
        poisson_ratio=0.3,
    )


CONVERGENCE_TRAP_CASES = (
    # Unscreened, the smeared search governed at (42, 2), an axial half-wave
    # shorter than the ring spacing; the screen leaves m <= 24.
    RingCase(
        case_id="committed_sub_spacing_axial_mode",
        length_unit="mm",
        pressure_unit="MPa",
        shell_mid_surface_radius=100.0,
        wall_thickness=1.0,
        unsupported_length=500.0,
        ring_spacing=20.0,
        ring_axial_width=2.0,
        ring_radial_height=20.0,
        ring_location="external",
        elastic_modulus=70_000.0,
        poisson_ratio=0.33,
    ),
    RingCase(
        case_id="committed_circumferential_mode_trap",
        length_unit="mm",
        pressure_unit="MPa",
        shell_mid_surface_radius=100.0,
        wall_thickness=0.2,
        unsupported_length=100.0,
        ring_spacing=20.0,
        ring_axial_width=1.0,
        ring_radial_height=0.5,
        ring_location="external",
        elastic_modulus=70_000.0,
        poisson_ratio=0.33,
    ),
)
