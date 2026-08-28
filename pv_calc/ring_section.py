from __future__ import annotations

import math


_ODD_RECIPROCAL_FIFTH_SUM = 1.0045237627951398


def _positive_finite(value: float, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def rectangular_saint_venant_torsional_constant_mm4(
    *,
    axial_width_mm: float,
    radial_height_mm: float,
) -> float:
    """Return the exact Saint-Venant ``J`` series for a solid rectangle.

    NASA/TP-2011-216882 Eq. A16 is symmetric in the two rectangle dimensions
    after the longer dimension is called ``h`` and the shorter dimension is
    called ``t``.  For an isotropic material, its modulus ratios reduce to
    unity and only odd series terms remain.  The odd reciprocal-fifth-power
    sum is evaluated from ``(31/32) * zeta(5)`` and only the rapidly decaying
    ``tanh(x) - 1`` correction is accumulated numerically.
    """

    axial_width_mm = _positive_finite(axial_width_mm, "axial_width_mm")
    radial_height_mm = _positive_finite(radial_height_mm, "radial_height_mm")
    longer_mm = max(axial_width_mm, radial_height_mm)
    shorter_mm = min(axial_width_mm, radial_height_mm)
    odd_sum = _ODD_RECIPROCAL_FIFTH_SUM
    for index in range(1, 202, 2):
        hyperbolic_tangent = math.tanh(
            index * math.pi * longer_mm / (2.0 * shorter_mm)
        )
        odd_sum += (hyperbolic_tangent - 1.0) / index**5
        if hyperbolic_tangent == 1.0:
            break
    correction = 1.0 - (
        192.0 * shorter_mm / (math.pi**5 * longer_mm) * odd_sum
    )
    return longer_mm * shorter_mm**3 * correction / 3.0


def rectangular_ring_section_properties(
    *,
    axial_width_mm: float,
    radial_height_mm: float,
) -> dict[str, float | str]:
    """Properties of the one supported, non-overlapping physical ring."""

    axial_width_mm = _positive_finite(axial_width_mm, "axial_width_mm")
    radial_height_mm = _positive_finite(radial_height_mm, "radial_height_mm")
    return {
        "ring_section_type": "solid_rectangle",
        "ring_axial_width_mm": axial_width_mm,
        "ring_radial_height_mm": radial_height_mm,
        "ring_area_mm2": axial_width_mm * radial_height_mm,
        "ring_centroid_from_shell_surface_mm": 0.5 * radial_height_mm,
        "ring_centroidal_inertia_mm4": (
            axial_width_mm * radial_height_mm**3 / 12.0
        ),
        "ring_torsional_constant_mm4": (
            rectangular_saint_venant_torsional_constant_mm4(
                axial_width_mm=axial_width_mm,
                radial_height_mm=radial_height_mm,
            )
        ),
    }
