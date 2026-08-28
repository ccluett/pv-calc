"""Independent standard-library reference for hemisphere membrane displacement.

This module imports no production calculation, adapter, fixture, expected
output, or section helper.  It transcribes one cited source equation directly:
NASA Technical Memorandum 4579 (W. L. Ko, *Thermocryogenic Buckling and Stress
Analyses of a Partially Filled Cryogenic Tank Subjected to Cylindrical Strip
Heating*, Dryden Flight Research Center, 1994), Eq. (5), printed p. 6, which
states the spherical-shell membrane stress ``sigma_theta = sigma_phi =
p R / (2 t)`` and the radial displacement ``p R^2 (1 - nu) / (2 E t)`` in one
equation and applies both to the hemispherical bulkheads of the analyzed
vessel.  Ko's ref. 1 is Timoshenko and Woinowsky-Krieger, *Theory of Plates and
Shells*, 1959, pp. 481-485.

The decision record behind it, including why the thick-sphere branch is
withheld, is ``validation/sources/hemisphere_scalar_displacement.md``.

It is a separate module from ``non_ring_reference.py`` for the reason recorded
there: that file's SHA-256 is ``manifest.reference_sha256`` in the committed
P5-03 FEA summaries.  It is separate from
``tube_displacement_reference.py`` because that module transcribes the two
cylinder sources and states so in its name and docstring.

Run from the ``pv-calc`` directory with::

    uv run python validation/hemisphere_displacement_reference.py
"""

from __future__ import annotations

import json
from typing import Any


# The same limits ``non_ring_reference.py`` sets, restated here so this module
# stays free of cross-module imports.  They were fixed before any comparison
# against production was run.
REFERENCE_RELATIVE_TOLERANCE = 1.0e-9
REFERENCE_ABSOLUTE_TOLERANCE = 1.0e-10

NASA_TM_4579 = {
    "title": (
        "NASA Technical Memorandum 4579, Thermocryogenic Buckling and Stress "
        "Analyses of a Partially Filled Cryogenic Tank Subjected to Cylindrical "
        "Strip Heating"
    ),
    "authors": "W. L. Ko",
    "edition_revision": "Dryden Flight Research Center, 1994",
    "url": "https://ntrs.nasa.gov/api/citations/19950011002/downloads/19950011002.pdf",
    "sha256": "dafa8fee4428e30bc8cef2225c5e74e19226b2b6e3a2bdbcea232831a8b38e68",
    "retrieved_utc_date": "2026-07-31",
    "equation": "Eq. (5), printed p. 6; ref. 1 is Timoshenko and Woinowsky-Krieger, 1959, pp. 481-485",
}

THIN_BRANCH_MEAN_RADIUS_RATIO = 10.0


def spherical_membrane_reference(
    *,
    external_pressure: float,
    mean_radius: float,
    wall_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
) -> dict[str, float]:
    """NASA TM-4579 Eq. (5) in any consistent units.

    Pressure, modulus, and stress share one unit; radius and thickness share
    another.  Ko states the equation for an internal pressure, which produces a
    tensile membrane stress and an outward displacement; it is odd in the
    pressure, so an external pressure with the interior at zero gauge flips the
    sign of both.  Radial displacement is positive outward, so the returned
    value is negative.

    Both halves of the source equation are transcribed, together with the
    consistency the source asserts by stating them on one line: the
    circumferential strain implied by the transcribed displacement equals the
    strain the transcribed membrane stress produces under the isotropic biaxial
    state, so Eq. (5) is one membrane state and not two unrelated formulas.
    """
    membrane_stress = -external_pressure * mean_radius / (2.0 * wall_thickness)
    radial_displacement = (
        -external_pressure
        * mean_radius
        * mean_radius
        * (1.0 - poisson_ratio)
        / (2.0 * elastic_modulus * wall_thickness)
    )
    return {
        "membrane_stress": membrane_stress,
        "radial_displacement": radial_displacement,
        "circumferential_strain": radial_displacement / mean_radius,
        "hookean_circumferential_strain": (
            membrane_stress - poisson_ratio * membrane_stress
        )
        / elastic_modulus,
    }


def hemispherical_head_displacement_reference(
    *,
    external_pressure: float,
    internal_radius: float,
    wall_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
    force_thick: bool = False,
) -> dict[str, Any]:
    """Branch the reference the way the released hemisphere model branches.

    The thin branch is used only above ``mean radius / thickness = 10`` and
    reports one displacement at the median surface.  The thick branch is used
    at or below it, or when ``force_thick`` is set, and reports none: NASA
    TM-4579 Eq. (5) is a thin-shell membrane result, and no consulted source
    states a thick-sphere radial displacement.
    """
    mean_radius = internal_radius + wall_thickness / 2.0
    radius_ratio = mean_radius / wall_thickness
    branch = (
        "thick"
        if force_thick or radius_ratio <= THIN_BRANCH_MEAN_RADIUS_RATIO
        else "thin"
    )

    if branch == "thin":
        membrane = spherical_membrane_reference(
            external_pressure=external_pressure,
            mean_radius=mean_radius,
            wall_thickness=wall_thickness,
            elastic_modulus=elastic_modulus,
            poisson_ratio=poisson_ratio,
        )
        surfaces = [
            {
                "radius": mean_radius,
                "radius_convention": "mean",
                "radial_displacement": membrane["radial_displacement"],
            }
        ]
        source = "NASA TM-4579 Eq. (5)"
    else:
        surfaces = [
            {
                "radius": internal_radius,
                "radius_convention": "internal",
                "radial_displacement": None,
            },
            {
                "radius": internal_radius + wall_thickness,
                "radius_convention": "external",
                "radial_displacement": None,
            },
        ]
        source = None

    return {
        "branch": branch,
        "mean_radius": mean_radius,
        "external_radius": internal_radius + wall_thickness,
        "mean_radius_over_thickness": radius_ratio,
        "surfaces": surfaces,
        "source": source,
    }


def cylinder_to_sphere_ratio_reference(*, poisson_ratio: float) -> float:
    """NASA TM-4579 Eq. (6), the ratio the source publishes itself.

    Dividing Eq. (4) by Eq. (5) leaves ``(2 - nu) / (1 - nu)``, free of
    pressure, radius, thickness, and modulus.  Ko evaluates it at ``nu = 0.28``
    in his Eq. (7); the printed digits of that evaluation are not relied on
    here, only the closed form.  The released tube and hemisphere models take
    their thin displacements from two different sources, DTMB 1497 Eq. [5] and
    this one, so their ratio at one geometry reproducing this closed form is a
    check that the two transcriptions are mutually consistent.
    """
    return (2.0 - poisson_ratio) / (1.0 - poisson_ratio)


def build_evidence() -> dict[str, Any]:
    """Build the checked independent hemisphere-displacement evidence."""
    released_inputs = {
        "external_pressure": 6.0,
        "internal_radius": 100.0,
        "wall_thickness": 100.0 / 39.5,
        "elastic_modulus": 68_900.0,
        "poisson_ratio": 0.33,
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
            "thin_branch": NASA_TM_4579,
            "thick_branch": None,
            "decision_record": "validation/sources/hemisphere_scalar_displacement.md",
        },
        "conventions": {
            "radial_displacement": "positive outward; external pressure gives a negative value",
            "thin_branch_surface": "median surface",
            "thick_branch_surfaces": "withheld; no source states a thick-sphere displacement",
            "meridional_location": (
                "away from the equator; a restrained equator suppresses the displacement "
                "locally and the released value is not the equator's radial closure"
            ),
            "excluded": [
                "equator boundary layer and junction response",
                "displacement fields",
                "thick-sphere branch",
                "nonlinear and post-buckling deformation",
                "ring-stiffened service displacement",
            ],
        },
        "source_inputs": {
            "released_example": released_inputs,
            "transition_thick": transition_thick_inputs,
            "transition_thin": transition_thin_inputs,
        },
        "calculated_values": {
            "released_example": hemispherical_head_displacement_reference(
                **released_inputs
            ),
            "released_example_forced_thick": hemispherical_head_displacement_reference(
                **released_inputs, force_thick=True
            ),
            "transition_thick": hemispherical_head_displacement_reference(
                **transition_thick_inputs
            ),
            "transition_thin": hemispherical_head_displacement_reference(
                **transition_thin_inputs
            ),
            "cylinder_over_sphere_at_nu_0_28": cylinder_to_sphere_ratio_reference(
                poisson_ratio=0.28
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
