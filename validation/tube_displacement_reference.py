"""Independent standard-library reference for closed-end tube displacement.

This module imports no production calculation, adapter, fixture, expected
output, or section helper.  It transcribes the two cited source equations
directly:

* thin branch — DTMB Report 1497 (Pulos and Salerno, September 1961), Eq. [5],
  printed p. 2, for the median-surface radial displacement of a long
  unstiffened cylindrical shell under external hydrostatic pressure, with the
  two-dimensional Hooke's law Eq. [A7], the resultant relation Eq. [A9], the
  axisymmetric strain relation Eq. [A10], and the stated load case
  ``P_r = -p`` and ``N_x = -p R / 2``, printed p. 43;
* thick branch — Boresi and Schmidt, *Advanced Mechanics of Materials*, 6th
  ed., 2003, Eq. (11.24), printed p. 396, for the radial displacement of a
  closed cylinder, and Eq. (11.15), printed p. 394, for its axial strain, both
  at sections far removed from the end-cap junction.

The decision record behind both is
``validation/sources/tube_scalar_displacement.md``.

It is a separate module from ``non_ring_reference.py`` because that file's
SHA-256 is recorded as ``manifest.reference_sha256`` in the committed P5-03
FEA summaries, which no rerun is available to restore.

Run from the ``pv-calc`` directory with::

    uv run python validation/tube_displacement_reference.py
"""

from __future__ import annotations

import json
import math
from typing import Any


# The same limits ``non_ring_reference.py`` sets, restated here so this module
# stays free of cross-module imports.  They were fixed before any comparison
# against production was run.
REFERENCE_RELATIVE_TOLERANCE = 1.0e-9
REFERENCE_ABSOLUTE_TOLERANCE = 1.0e-10

DTMB_1497 = {
    "title": (
        "DTMB Report 1497, Axisymmetric Elastic Deformations and Stresses in a "
        "Ring-Stiffened, Perfectly Circular Cylindrical Shell under External "
        "Hydrostatic Pressure"
    ),
    "authors": "J. G. Pulos and V. L. Salerno",
    "edition_revision": "September 1961",
    "url": "https://dome.mit.edu/handle/1721.3/48806",
    "sha256": "10234c9a5d2651e603749782ae3fe93352af674d9a12da3cdd3c913e14795835",
    "retrieved_utc_date": "2026-07-30",
}
BORESI_SCHMIDT = {
    "title": "Advanced Mechanics of Materials",
    "authors": "A. P. Boresi and R. J. Schmidt",
    "edition_revision": "6th edition, John Wiley & Sons, 2003",
    "printed_reference": True,
    "chapter": "Chapter 11, The Thick-Wall Cylinder",
}

THIN_BRANCH_MEAN_RADIUS_RATIO = 10.0


def thin_shell_displacement_reference(
    *,
    external_pressure: float,
    median_radius: float,
    wall_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
) -> dict[str, float]:
    """DTMB 1497 membrane displacement in any consistent units.

    Pressure, modulus, and stress share one unit; radius and thickness share
    another. Radial displacement is positive outward, so external pressure
    returns a negative value, and axial strain is positive in extension.

    The axial strain is built from the report's own resultants rather than
    from a rearranged closed form: Eq. [5] gives ``w_p``, Eq. [A10] turns it
    into the circumferential strain, Eq. [A9] turns that into ``N_phi``, and
    Eq. [A7] combines ``N_phi`` with the stated ``N_x = -p R / 2``.
    """
    stiffness = elastic_modulus * wall_thickness
    radial_displacement = (
        -external_pressure
        * median_radius
        * median_radius
        * (1.0 - poisson_ratio / 2.0)
        / stiffness
    )
    circumferential_strain = radial_displacement / median_radius
    axial_resultant = -external_pressure * median_radius / 2.0
    circumferential_resultant = (
        stiffness * circumferential_strain + poisson_ratio * axial_resultant
    )
    axial_strain = (
        axial_resultant - poisson_ratio * circumferential_resultant
    ) / stiffness
    return {
        "radial_displacement": radial_displacement,
        "axial_strain": axial_strain,
        "circumferential_resultant": circumferential_resultant,
        "axial_resultant": axial_resultant,
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
    force_thick: bool = False,
) -> dict[str, Any]:
    """Branch the two references the way the released tube model branches.

    The thin branch is used only above ``median radius / thickness = 10``, and
    reports one displacement at the median surface; the thick branch is used at
    or below it, or when ``force_thick`` is set, and reports one displacement
    at each of the internal and external surfaces.
    """
    external_radius = internal_radius + wall_thickness
    median_radius = internal_radius + wall_thickness / 2.0
    radius_ratio = median_radius / wall_thickness
    branch = (
        "thick"
        if force_thick or radius_ratio <= THIN_BRANCH_MEAN_RADIUS_RATIO
        else "thin"
    )

    if branch == "thin":
        thin = thin_shell_displacement_reference(
            external_pressure=external_pressure,
            median_radius=median_radius,
            wall_thickness=wall_thickness,
            elastic_modulus=elastic_modulus,
            poisson_ratio=poisson_ratio,
        )
        axial_strain = thin["axial_strain"]
        surfaces = [
            {
                "radius": median_radius,
                "radius_convention": "mean",
                "radial_displacement": thin["radial_displacement"],
            }
        ]
        source = "DTMB 1497 Eq. [5] with Eqs. [A7], [A9], and [A10]"
    else:
        surfaces = []
        axial_strain = math.nan
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
            axial_strain = thick["axial_strain"]
            surfaces.append(
                {
                    "radius": radius,
                    "radius_convention": convention,
                    "radial_displacement": thick["radial_displacement"],
                }
            )
        source = "Boresi and Schmidt Eqs. (11.24) and (11.15)"

    return {
        "branch": branch,
        "median_radius": median_radius,
        "external_radius": external_radius,
        "mean_radius_over_thickness": radius_ratio,
        "surfaces": surfaces,
        "axial_strain": axial_strain,
        "axial_length_change": (
            axial_strain * axial_length if axial_length is not None else None
        ),
        "source": source,
    }


def branch_agreement_reference(
    *,
    internal_radius: float,
    wall_thickness: float,
) -> dict[str, float]:
    """Exact thick/thin ratios at one geometry, independent of Poisson ratio.

    Dividing the two transcribed closed forms leaves ``b^2 / r_m^2`` for the
    axial strain and ``a b^2 / r_m^3`` for the internal-surface radial
    displacement, because the ``(2 - nu)`` factor common to both displacement
    forms cancels. Both tend to 1 as the wall thins.
    """
    external_radius = internal_radius + wall_thickness
    median_radius = internal_radius + wall_thickness / 2.0
    return {
        "axial_strain_thick_over_thin": external_radius**2 / median_radius**2,
        "internal_surface_displacement_thick_over_thin": (
            internal_radius * external_radius**2 / median_radius**3
        ),
    }


def build_evidence() -> dict[str, Any]:
    """Build the checked independent tube-displacement evidence."""
    thin_inputs = {
        "external_pressure": 2.0,
        "internal_radius": 100.0,
        "wall_thickness": 5.0,
        "elastic_modulus": 68_900.0,
        "poisson_ratio": 0.33,
        "axial_length": 500.0,
    }
    thick_inputs = {
        "external_pressure": 22.6243125,
        "internal_radius": 55.0,
        "wall_thickness": 22.0,
        "elastic_modulus": 68_900.0,
        "poisson_ratio": 0.33,
        "axial_length": 400.0,
    }
    # The released branch switch sits at mean radius / thickness = 10, where
    # the thick branch is taken; the thin branch starts just above it.
    transition_thick_inputs = {
        "external_pressure": 1.0,
        "internal_radius": 9.5,
        "wall_thickness": 1.0,
        "elastic_modulus": 68_900.0,
        "poisson_ratio": 0.33,
    }
    transition_thin_inputs = dict(transition_thick_inputs, internal_radius=9.500001)

    return {
        "sources": {
            "thin_branch": DTMB_1497,
            "thick_branch": BORESI_SCHMIDT,
            "decision_record": "validation/sources/tube_scalar_displacement.md",
        },
        "conventions": {
            "radial_displacement": "positive outward; external pressure gives a negative value",
            "axial_strain": "positive in extension; uniform through the wall and along the tube",
            "thin_branch_surface": "median surface",
            "thick_branch_surfaces": ["internal", "external"],
            "excluded": [
                "tube/endcap junction effects",
                "local restraint at closures",
                "ovalization and initial out-of-roundness",
                "instability",
                "plasticity",
                "ring-frame restraint",
            ],
        },
        "source_inputs": {
            "thin": thin_inputs,
            "thick": thick_inputs,
            "transition_thick": transition_thick_inputs,
            "transition_thin": transition_thin_inputs,
        },
        "calculated_values": {
            "thin": closed_end_tube_displacement_reference(**thin_inputs),
            "thick": closed_end_tube_displacement_reference(**thick_inputs),
            "transition_thick": closed_end_tube_displacement_reference(
                **transition_thick_inputs
            ),
            "transition_thin": closed_end_tube_displacement_reference(
                **transition_thin_inputs
            ),
            "transition_ratios": branch_agreement_reference(
                internal_radius=transition_thick_inputs["internal_radius"],
                wall_thickness=transition_thick_inputs["wall_thickness"],
            ),
        },
        "tolerances": {
            "independent_vs_production_relative": REFERENCE_RELATIVE_TOLERANCE,
            "independent_vs_production_absolute": REFERENCE_ABSOLUTE_TOLERANCE,
        },
    }


def main() -> None:
    print(json.dumps(build_evidence(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
