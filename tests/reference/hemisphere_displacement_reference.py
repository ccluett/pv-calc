"""Independent standard-library reference for hemispherical-head displacement.

This module imports no production calculation, adapter, fixture, expected
output, or section helper.  It uses the classical hollow-sphere solution
(Timoshenko and Goodier, *Theory of Elasticity*, 3rd ed., 1970): spherical
symmetry reduces equilibrium to ``d/dr[(1/r^2) d(r^2 u)/dr] = 0``, so
``u = C1*r + C2/r^2``, with the constants fixed by the surface tractions.
Production instead derives the displacement from its Lamé stresses through
Hooke's law.
"""

from __future__ import annotations

from typing import Any


def hemispherical_head_displacement_reference(
    *,
    external_pressure: float,
    internal_radius: float,
    wall_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
) -> dict[str, Any]:
    """Radial displacement at the internal and external surfaces.

    Units are consistent and displacement is positive outward, so external
    pressure returns negative values.  Zero radial stress at the bore ``a``
    and ``-p`` at the outer surface ``b`` give
    ``u(r) = -p b^3 / (E (b^3 - a^3)) * ((1 - 2 nu) r + (1 + nu) a^3 / (2 r^2))``.
    """
    inner = internal_radius
    outer = internal_radius + wall_thickness
    scale = -external_pressure * outer**3 / (elastic_modulus * (outer**3 - inner**3))
    return {
        "surfaces": [
            {
                "radius": radius,
                "radius_convention": convention,
                "radial_displacement": scale
                * (
                    (1.0 - 2.0 * poisson_ratio) * radius
                    + (1.0 + poisson_ratio) * inner**3 / (2.0 * radius**2)
                ),
            }
            for radius, convention in ((inner, "internal"), (outer, "external"))
        ],
        "source": "Timoshenko and Goodier hollow sphere, u = C1*r + C2/r^2",
    }
