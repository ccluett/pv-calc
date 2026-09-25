"""Independent periodic-bay yield reference for the ring-stiffened shell.

This module uses only the Python standard library and imports no pv_calc
code. It gives two routes to the elastic axisymmetric stresses of a shell bay
between identical, uniformly spaced rings under closed-end external pressure:

* ``printed_form`` transcribes Wilson's closed form as printed by Morandi
  (1994, University of Glasgow PhD thesis, pp. 48-49, Eqs. 48-53), the form
  PD 5500 uses for Pc5, with the effective ring area selected by name.
* ``direct_solution`` solves the half-bay beam-on-elastic-foundation problem
  and the ring equilibrium as a 3x3 linear system, without the printed N, G,
  or gamma.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal


AreaRule = Literal["dtmb_1639", "flange_tip_squared"]


@dataclass(frozen=True)
class YieldCase:
    case_id: str
    shell_mid_surface_radius: float
    wall_thickness: float
    ring_spacing: float
    ring_axial_width: float
    ring_radial_height: float
    ring_location: Literal["internal", "external"]
    poisson_ratio: float
    yield_strength: float


def ring_radius(
    case: YieldCase, where: Literal["centroid", "flange_tip", "innermost"]
) -> float:
    """Ring centroid radius R_c, the radius of the ring edge away from the shell,
    or the ring's smallest radius: the free edge of an internal ring and the
    base of an external one."""
    if where == "innermost":
        if case.ring_location == "external":
            return case.shell_mid_surface_radius + 0.5 * case.wall_thickness
        return (
            case.shell_mid_surface_radius
            - 0.5 * case.wall_thickness
            - case.ring_radial_height
        )
    offset = 0.5 * case.wall_thickness + (
        0.5 * case.ring_radial_height if where == "centroid" else case.ring_radial_height
    )
    if case.ring_location == "external":
        return case.shell_mid_surface_radius + offset
    return case.shell_mid_surface_radius - offset


def effective_ring_area(case: YieldCase, rule: AreaRule) -> float:
    """Modified ring area A_e seen by the shell at its mid-surface radius R.

    ``dtmb_1639``: DTMB Report 1639 Eq. (9), A_f (R/R_c) for an internal ring
    and A_f (R/R_c)^2 for an external ring. ``flange_tip_squared``: the
    JMSE 2020 worked example's A_f (R/R_f)^2 with R_f at the ring edge.
    """
    area = case.ring_axial_width * case.ring_radial_height
    radius = case.shell_mid_surface_radius
    if rule == "dtmb_1639":
        exponent = 2 if case.ring_location == "external" else 1
        return area * (radius / ring_radius(case, "centroid")) ** exponent
    return area * (radius / ring_radius(case, "flange_tip")) ** 2


def printed_form(case: YieldCase, rule: AreaRule = "dtmb_1639") -> dict[str, float]:
    """Transcribe Wilson's mid-bay hoop stress and ring stress per unit pressure.

    beta = [3 (1 - nu^2)]^(1/4) / sqrt(R t), L = pitch - faying width,
    N = (cosh bL - cos bL) / (sinh bL + sin bL),
    G = 2 [sinh(bL/2) cos(bL/2) + cosh(bL/2) sin(bL/2)] / (sinh bL + sin bL),
    gamma = A_e (1 - nu/2) / (A_e + b t + 2 N t / beta),
    mid-bay shell hoop stress / p = (R / t) (1 - gamma G),
    ring hoop stress / p at the centroid radius
        = R^2 (1 - nu/2) / (t R_c [1 + A_e / (b t + 2 N t / beta)]),
    and at the ring's smallest radius with that radius in place of R_c,
    since the section translates radially as a whole.
    """
    radius = case.shell_mid_surface_radius
    thickness = case.wall_thickness
    nu = case.poisson_ratio
    faying_width = case.ring_axial_width
    clear_bay = case.ring_spacing - faying_width
    beta = (3.0 * (1.0 - nu**2)) ** 0.25 / math.sqrt(radius * thickness)
    bl = beta * clear_bay
    denominator = math.sinh(bl) + math.sin(bl)
    n_function = (math.cosh(bl) - math.cos(bl)) / denominator
    g_function = (
        2.0
        * (
            math.sinh(bl / 2.0) * math.cos(bl / 2.0)
            + math.cosh(bl / 2.0) * math.sin(bl / 2.0)
        )
        / denominator
    )
    modified_area = effective_ring_area(case, rule)
    attached_area = faying_width * thickness + 2.0 * n_function * thickness / beta
    gamma = modified_area * (1.0 - nu / 2.0) / (modified_area + attached_area)
    shell_per_pressure = radius / thickness * (1.0 - gamma * g_function)
    ring_per_pressure = (
        radius**2
        * (1.0 - nu / 2.0)
        / (thickness * ring_radius(case, "centroid"))
        / (1.0 + modified_area / attached_area)
    )
    ring_innermost_per_pressure = (
        radius**2
        * (1.0 - nu / 2.0)
        / (thickness * ring_radius(case, "innermost"))
        / (1.0 + modified_area / attached_area)
    )
    return {
        "clear_bay": clear_bay,
        "clear_bay_parameter": bl,
        "n_function": n_function,
        "g_function": g_function,
        "effective_ring_area": modified_area,
        "gamma": gamma,
        "shell_hoop_stress_per_unit_pressure": shell_per_pressure,
        "ring_hoop_stress_per_unit_pressure": ring_per_pressure,
        "ring_innermost_hoop_stress_per_unit_pressure": ring_innermost_per_pressure,
        "shell_yield_pressure": case.yield_strength / shell_per_pressure,
        "ring_yield_pressure": case.yield_strength / ring_per_pressure,
        "ring_first_yield_pressure": case.yield_strength / ring_innermost_per_pressure,
    }


def _solve_3x3(matrix: list[list[float]], rhs: list[float]) -> list[float]:
    """Gaussian elimination with partial pivoting."""
    rows = [row[:] + [value] for row, value in zip(matrix, rhs)]
    for column in range(3):
        pivot = max(range(column, 3), key=lambda index: abs(rows[index][column]))
        rows[column], rows[pivot] = rows[pivot], rows[column]
        for index in range(column + 1, 3):
            factor = rows[index][column] / rows[column][column]
            for position in range(column, 4):
                rows[index][position] -= factor * rows[column][position]
    solution = [0.0, 0.0, 0.0]
    for index in (2, 1, 0):
        known = sum(rows[index][position] * solution[position] for position in range(index + 1, 3))
        solution[index] = (rows[index][3] - known) / rows[index][index]
    return solution


def direct_solution(case: YieldCase, rule: AreaRule = "dtmb_1639") -> dict[str, float]:
    """Solve the periodic half bay directly, per unit free-shell deflection.

    With y = beta x from mid-bay and u = w / w_free, where
    w_free = p R^2 (1 - nu/2) / (E t) is the radial deflection of a shell
    without rings, D w'''' + (E t / R^2) w = p (1 - nu/2) becomes
    u'''' + 4 u = 4 and has the even solution u = 1 + c1 cosh y cos y +
    c2 sinh y sin y. At the ring face y = h = beta L / 2 the slope is zero and
    u equals the ring deflection rho. The ring with the shell strip under it
    carries the pressure on its faying width and the shear of both bays:
    (A_e + b t) rho = b t + 2 t integral_0^(L/2) (1 - u) dx.
    Every hyperbolic term is divided by cosh h so long bays stay well scaled.
    """
    radius = case.shell_mid_surface_radius
    thickness = case.wall_thickness
    nu = case.poisson_ratio
    faying_width = case.ring_axial_width
    beta = (3.0 * (1.0 - nu**2)) ** 0.25 / math.sqrt(radius * thickness)
    half = beta * (case.ring_spacing - faying_width) / 2.0
    tanh_h = math.tanh(half)
    cos_h, sin_h = math.cos(half), math.sin(half)
    # Basis values, slopes (d/dy), and integrals over 0..h, each divided by cosh h.
    f1, f2 = cos_h, tanh_h * sin_h
    f1_slope = tanh_h * cos_h - sin_h
    f2_slope = sin_h + tanh_h * cos_h
    f1_integral = (tanh_h * cos_h + sin_h) / 2.0
    f2_integral = (sin_h - tanh_h * cos_h) / 2.0
    modified_area = effective_ring_area(case, rule)
    # Unknowns: s1 = c1 cosh h, s2 = c2 cosh h, and rho.
    matrix = [
        [f1_slope, f2_slope, 0.0],
        [f1, f2, -1.0],
        [
            2.0 * thickness / beta * f1_integral,
            2.0 * thickness / beta * f2_integral,
            modified_area + faying_width * thickness,
        ],
    ]
    s1, _s2, rho = _solve_3x3(matrix, [0.0, -1.0, faying_width * thickness])
    midbay_deflection = 1.0 + s1 / math.cosh(half)
    shell_per_pressure = radius / thickness * (
        (1.0 - nu / 2.0) * midbay_deflection + nu / 2.0
    )
    ring_per_pressure = (
        radius / thickness
        * (radius / ring_radius(case, "centroid"))
        * (1.0 - nu / 2.0)
        * rho
    )
    ring_innermost_per_pressure = (
        radius / thickness
        * (radius / ring_radius(case, "innermost"))
        * (1.0 - nu / 2.0)
        * rho
    )
    return {
        "shell_hoop_stress_per_unit_pressure": shell_per_pressure,
        "ring_hoop_stress_per_unit_pressure": ring_per_pressure,
        "ring_innermost_hoop_stress_per_unit_pressure": ring_innermost_per_pressure,
    }


# Lengths and stresses in each case share one unit system (inches and psi for
# the DTMB geometries, mm and MPa otherwise). Stresses per unit pressure are
# ratios; the yield strengths only scale the yield pressures.
PARITY_CASES = (
    # External rings.
    YieldCase("dtmb_1324_cylinder_4a", 8.118 / 2.0 + 0.035 / 2.0, 0.035, 1.152, 0.086, 0.169,
              "external", 0.3, 85_000.0),
    YieldCase("dtmb_1255_br7m_geometry", (27.110 - 0.2110) / 2.0, 0.2110, 2.570, 0.330, 1.225,
              "external", 0.3, 80_000.0),
    YieldCase("external_very_short_bay", 100.0, 1.0, 3.0, 1.0, 8.0, "external", 0.33, 250.0),
    YieldCase("external_long_bay", 299.06 + 4.978 / 2.0, 4.978, 1215.59, 5.03, 33.528,
              "external", 0.3, 310.96),
    # Internal rings.
    YieldCase("jmse_2020_worked_example", 97.175, 6.35, 168.0, 6.35, 6.35, "internal", 0.33, 230.0),
    YieldCase("internal_short_bay", 604.3, 4.48, 110.0, 12.0, 30.0, "internal", 0.3, 329.2),
    YieldCase("internal_deep_ring_short_bay", 50.0, 2.0, 12.0, 3.0, 10.0, "internal", 0.3, 500.0),
)

JMSE_2020_WORKED_EXAMPLE = PARITY_CASES[4]
# JMSE 8 (2020) 515, worked example: mean hoop yield pressure at mid-bay, MPa,
# printed to two decimals; the example uses the flange-tip radius in A_e.
JMSE_2020_PUBLISHED_PC5_MPA = 14.95
JMSE_2020_AREA_RULE: AreaRule = "flange_tip_squared"
JMSE_2020_PRINTED_PRECISION_MPA = 0.005
