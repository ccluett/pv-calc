"""Independent standard-library reference for closed-end tube displacement.

This module imports no production calculation, adapter, fixture, expected
output, or section helper.  It transcribes Boresi and Schmidt, *Advanced
Mechanics of Materials*, 6th ed., 2003, Eq. (11.24), printed p. 396, for the
radial displacement of a closed cylinder, and Eq. (11.15), printed p. 394, for
its axial strain, both at sections far removed from the end-cap junction.
"""

from __future__ import annotations

from typing import Any


BORESI_SCHMIDT = {
    "title": "Advanced Mechanics of Materials",
    "authors": "A. P. Boresi and R. J. Schmidt",
    "edition_revision": "6th edition, John Wiley & Sons, 2003",
    "printed_reference": True,
    "chapter": "Chapter 11, The Thick-Wall Cylinder",
}


def thick_cylinder_displacement_reference(
    *,
    external_pressure: float,
    internal_radius: float,
    external_radius: float,
    radius: float,
    elastic_modulus: float,
    poisson_ratio: float,
) -> dict[str, float]:
    """Boresi and Schmidt closed-cylinder displacement in consistent units.

    Written with the source's general ``p_1``/``p_2`` pressures so the
    substitution of an internal gauge pressure of zero stays visible, and with
    no temperature change and no separately applied axial load.
    """
    internal_pressure = 0.0
    external_pressure_term = external_pressure
    area_term = external_radius**2 - internal_radius**2
    uniform = (
        internal_pressure * internal_radius**2
        - external_pressure_term * external_radius**2
    )
    varying = (
        internal_radius**2
        * external_radius**2
        * (internal_pressure - external_pressure_term)
    )
    radial_displacement = (
        radius
        / (elastic_modulus * area_term)
        * (
            (1.0 - 2.0 * poisson_ratio) * uniform
            + (1.0 + poisson_ratio) * varying / radius**2
        )
    )
    axial_strain = (1.0 - 2.0 * poisson_ratio) * uniform / (elastic_modulus * area_term)
    return {
        "radial_displacement": radial_displacement,
        "axial_strain": axial_strain,
    }


def closed_end_tube_displacement_reference(
    *,
    external_pressure: float,
    internal_radius: float,
    wall_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
    axial_length: float | None = None,
) -> dict[str, Any]:
    """Evaluate the closed cylinder at its internal and external surfaces.

    Radial displacement is positive outward, so external pressure returns a
    negative value, and axial strain is positive in extension and uniform
    through the wall.
    """
    external_radius = internal_radius + wall_thickness
    surfaces = []
    for radius, convention in (
        (internal_radius, "internal"),
        (external_radius, "external"),
    ):
        thick = thick_cylinder_displacement_reference(
            external_pressure=external_pressure,
            internal_radius=internal_radius,
            external_radius=external_radius,
            radius=radius,
            elastic_modulus=elastic_modulus,
            poisson_ratio=poisson_ratio,
        )
        surfaces.append(
            {
                "radius": radius,
                "radius_convention": convention,
                "radial_displacement": thick["radial_displacement"],
            }
        )
    axial_strain = thick["axial_strain"]
    return {
        "surfaces": surfaces,
        "axial_strain": axial_strain,
        "axial_length_change": (
            axial_strain * axial_length if axial_length is not None else None
        ),
        "source": "Boresi and Schmidt Eqs. (11.24) and (11.15)",
    }
