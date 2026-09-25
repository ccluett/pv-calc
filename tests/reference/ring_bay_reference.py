"""Independent periodic-bay beam-column reference for the ring-stiffened shell.

This module uses only the Python standard library and imports no pv_calc
code. It solves the axisymmetric problem of Pulos and Salerno (DTMB Report
1497) in the form Renzi documents for DAPS4 (IHTR 2944, 2008, Eqs. 43-55)
without that report's closed-form F-functions: the half bay's governing
equation is solved from its characteristic roots and the ring equilibrium as a
3x3 linear system. It shares with production only the governing equation, the
load terms, and the ring equilibrium those equations state.

Governing equation, Renzi Eq. 43, isotropic, x from mid-bay, w positive
outward: D w'''' + N w'' + (E t / R^2) w = -p (1 - nu alpha^2 / 2), with
N = p R alpha^2 / 2 and alpha = R_o / R. At the ring face x = L_s / 2 the slope
is zero and w equals the ring's deflection; the ring with the shell strip
under it carries the pressure on its faying width, p b (1 - nu alpha / 2), and
the shear of both adjoining bays, with A_eff = A_f (R / R_cg)^2 (Renzi Eq. 7).
Surface stresses: axial p R alpha^2 / (2 t) plus bending -E t w'' / (2 (1 - nu^2))
at the outer fibre; hoop E w / R + nu times the axial membrane stress plus nu
times the axial bending stress. Tension positive. The collapse helpers solve
first yield at the outer surface at mid-bay by bisection and transcribe
Lunchick's reserve factor, Renzi Eq. 66.
"""

from __future__ import annotations

import cmath
import math
from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class BayCase:
    """One periodic bay; the ring enters through its area, centroid radius, and
    faying width, so any section can be described."""

    case_id: str
    shell_mid_surface_radius: float
    wall_thickness: float
    ring_spacing: float
    ring_faying_width: float
    ring_area: float
    ring_centroid_radius: float
    elastic_modulus: float
    poisson_ratio: float


def rectangular_ring_case(
    case_id: str,
    *,
    shell_mid_surface_radius: float,
    wall_thickness: float,
    ring_spacing: float,
    ring_axial_width: float,
    ring_radial_height: float,
    ring_location: Literal["internal", "external"],
    elastic_modulus: float,
    poisson_ratio: float,
) -> BayCase:
    """A solid rectangular ring whose full width bears on the shell."""
    sign = 1.0 if ring_location == "external" else -1.0
    return BayCase(
        case_id=case_id,
        shell_mid_surface_radius=shell_mid_surface_radius,
        wall_thickness=wall_thickness,
        ring_spacing=ring_spacing,
        ring_faying_width=ring_axial_width,
        ring_area=ring_axial_width * ring_radial_height,
        ring_centroid_radius=(
            shell_mid_surface_radius + sign * 0.5 * (wall_thickness + ring_radial_height)
        ),
        elastic_modulus=elastic_modulus,
        poisson_ratio=poisson_ratio,
    )


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


def direct_solution(case: BayCase, pressure: float) -> dict[str, float]:
    """Stresses and deflections of the periodic bay at one external pressure."""
    radius = case.shell_mid_surface_radius
    thickness = case.wall_thickness
    modulus = case.elastic_modulus
    nu = case.poisson_ratio
    width = case.ring_faying_width
    effective_area = case.ring_area * (radius / case.ring_centroid_radius) ** 2
    alpha = (radius + 0.5 * thickness) / radius
    rigidity = modulus * thickness**3 / (12.0 * (1.0 - nu**2))
    foundation = modulus * thickness / radius**2
    axial_load = pressure * radius * alpha**2 / 2.0
    load = pressure * (1.0 - nu * alpha**2 / 2.0)
    half_bay = 0.5 * (case.ring_spacing - width)
    gamma = axial_load / (2.0 * math.sqrt(rigidity * foundation))
    if not gamma < 1.0:
        raise ValueError("the beam-column solution needs gamma < 1")

    root = cmath.sqrt((-axial_load + cmath.sqrt(complex(axial_load**2 - 4.0 * rigidity * foundation)))
                      / (2.0 * rigidity))
    decay, wave = abs(root.real), abs(root.imag)

    def basis(x: float) -> tuple[tuple[float, float], ...]:
        """Values and first three derivatives of cosh(px)cos(sx) and sinh(px)sin(sx)."""
        ch, sh = math.cosh(decay * x), math.sinh(decay * x)
        co, si = math.cos(wave * x), math.sin(wave * x)
        p2_s2 = decay**2 - wave**2
        cubic_p = decay**3 - 3.0 * decay * wave**2
        cubic_s = wave**3 - 3.0 * decay**2 * wave
        return (
            (ch * co, sh * si),
            (decay * sh * co - wave * ch * si, decay * ch * si + wave * sh * co),
            (p2_s2 * ch * co - 2.0 * decay * wave * sh * si,
             p2_s2 * sh * si + 2.0 * decay * wave * ch * co),
            (cubic_p * sh * co + cubic_s * ch * si, cubic_p * ch * si - cubic_s * sh * co),
        )

    particular = -load / foundation
    (value_1, value_2), (slope_1, slope_2), _, (third_1, third_2) = basis(half_bay)
    # Unknowns c1, c2 and the ring deflection w_f: zero slope at the ring face,
    # continuity there, and ring equilibrium against both bays' shear.
    c1, c2, ring_deflection = _solve_3x3(
        [
            [slope_1, slope_2, 0.0],
            [value_1, value_2, -1.0],
            [-2.0 * rigidity * third_1, -2.0 * rigidity * third_2,
             modulus * (effective_area + width * thickness) / radius**2],
        ],
        [0.0, -particular, -pressure * width * (1.0 - nu * alpha / 2.0)],
    )
    (mid_1, mid_2), _, (mid_curv_1, mid_curv_2), _ = basis(0.0)
    _, _, (face_curv_1, face_curv_2), _ = basis(half_bay)
    midbay_deflection = particular + c1 * mid_1 + c2 * mid_2
    axial_membrane = -pressure * radius * alpha**2 / (2.0 * thickness)

    def surface(deflection: float, curvature: float) -> dict[str, float]:
        bending = -modulus * thickness * curvature / (2.0 * (1.0 - nu**2))
        hoop_membrane = modulus * deflection / radius + nu * axial_membrane
        return {
            "axial_outer": axial_membrane + bending,
            "axial_inner": axial_membrane - bending,
            "hoop_outer": hoop_membrane + nu * bending,
            "hoop_inner": hoop_membrane - nu * bending,
            "axial_membrane": axial_membrane,
            "hoop_membrane": hoop_membrane,
        }

    midbay = surface(midbay_deflection, c1 * mid_curv_1 + c2 * mid_curv_2)
    frame = surface(ring_deflection, c1 * face_curv_1 + c2 * face_curv_2)
    return {
        "gamma": gamma,
        "midbay_deflection": midbay_deflection,
        "frame_deflection": ring_deflection,
        "ring_hoop": modulus * ring_deflection / radius,
        **{f"midbay_{key}": value for key, value in midbay.items()},
        **{f"frame_{key}": value for key, value in frame.items()},
    }


def von_mises(axial: float, hoop: float) -> float:
    """Plane-stress von Mises, radial stress omitted as DAPS4 prints it."""
    return math.sqrt(axial * axial - axial * hoop + hoop * hoop)


def outer_midbay_yield_pressure(case: BayCase, yield_strength: float) -> float:
    """Pressure at which the outer-surface mid-bay von Mises stress reaches yield."""

    def excess(pressure: float) -> float:
        state = direct_solution(case, pressure)
        return von_mises(state["midbay_axial_outer"], state["midbay_hoop_outer"]) - yield_strength

    lower, upper = 0.0, 1.0
    while excess(upper) < 0.0:
        lower, upper = upper, 2.0 * upper
    for _ in range(200):
        middle = 0.5 * (lower + upper)
        if excess(middle) < 0.0:
            lower = middle
        else:
            upper = middle
    return 0.5 * (lower + upper)


def lunchick_reserve_factor(case: BayCase, pressure: float) -> float:
    """Renzi IHTR 2944 Eq. 66, Lunchick's phi3, from the mid-bay stresses at a pressure."""
    state = direct_solution(case, pressure)
    nu = case.poisson_ratio
    axial = state["midbay_axial_membrane"]
    hoop = state["midbay_hoop_membrane"]
    hoop_bending = state["midbay_hoop_outer"] - hoop
    ratio = axial / hoop
    b_phi = hoop_bending / (6.0 * hoop)
    b_x = b_phi / (nu * ratio)
    theta_1 = b_phi**2 - b_x * b_phi * ratio + b_x**2 * ratio**2
    theta_2 = b_phi - 0.5 * (b_phi + b_x) * ratio + b_x * ratio**2
    theta_4 = 1.0 - ratio + ratio**2
    phi_1, phi_2 = theta_1 / theta_4, theta_2 / theta_4
    return math.sqrt(
        (1.0 + 36.0 * phi_1 + 12.0 * phi_2)
        / (1.0 + 8.0 * phi_1 + 4.0 * math.sqrt(4.0 * phi_1**2 + phi_2**2))
    )
