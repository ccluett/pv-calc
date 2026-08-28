from __future__ import annotations

import math

import pytest

from pv_calc.ring_section import (
    rectangular_ring_section_properties,
    rectangular_saint_venant_torsional_constant_mm4,
)


def test_dtmb_rectangular_ring_properties_match_independent_values():
    section = rectangular_ring_section_properties(
        axial_width_mm=0.086 * 25.4,
        radial_height_mm=0.169 * 25.4,
    )

    assert section["ring_section_type"] == "solid_rectangle"
    assert section["ring_area_mm2"] == pytest.approx(9.37675544)
    assert section["ring_centroid_from_shell_surface_mm"] == pytest.approx(2.1463)
    assert section["ring_centroidal_inertia_mm4"] == pytest.approx(
        14.398332070043859
    )
    assert section["ring_torsional_constant_mm4"] == pytest.approx(
        10.150644877245812,
        rel=1e-13,
    )


def test_square_rectangle_torsion_matches_elasticity_series_constant():
    # Independent published square-section coefficient: J/a^4 =
    # 0.140577014955... for Saint-Venant torsion.
    result = rectangular_saint_venant_torsional_constant_mm4(
        axial_width_mm=10.0,
        radial_height_mm=10.0,
    )
    assert result == pytest.approx(0.14057701495515366 * 10.0**4, rel=1e-13)


def test_rectangle_torsion_is_invariant_to_dimension_order():
    first = rectangular_saint_venant_torsional_constant_mm4(
        axial_width_mm=2.0,
        radial_height_mm=20.0,
    )
    rotated = rectangular_saint_venant_torsional_constant_mm4(
        axial_width_mm=20.0,
        radial_height_mm=2.0,
    )
    assert first == pytest.approx(rotated)


@pytest.mark.parametrize(
    ("axial_width_mm", "radial_height_mm"),
    [
        (0.0, 1.0),
        (1.0, -1.0),
        (math.inf, 1.0),
        (1.0, math.nan),
        (True, 1.0),
    ],
)
def test_rectangular_ring_rejects_nonphysical_dimensions(
    axial_width_mm: float,
    radial_height_mm: float,
):
    expected = (
        "must be numeric"
        if isinstance(axial_width_mm, bool) or isinstance(radial_height_mm, bool)
        else "finite and positive"
    )
    with pytest.raises(ValueError, match=expected):
        rectangular_ring_section_properties(
            axial_width_mm=axial_width_mm,
            radial_height_mm=radial_height_mm,
        )


def test_rectangular_ring_properties_use_one_non_overlapping_section():
    section = rectangular_ring_section_properties(
        axial_width_mm=20,
        radial_height_mm=30,
    )
    assert section["ring_area_mm2"] == pytest.approx(600.0)
    assert section["ring_centroid_from_shell_surface_mm"] == pytest.approx(15.0)
    assert section["ring_centroidal_inertia_mm4"] == pytest.approx(45_000.0)
