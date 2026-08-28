from __future__ import annotations

import math

import pytest

from pv_calc.pressure_vessel import (
    HEMISPHERE_MODEL_ID,
    HEMISPHERE_MODEL_VERSION,
    closed_end_tube_stress,
    hemispherical_head_external_pressure,
)


PSI_TO_MPA = 0.006894757293168361
INCH_TO_MM = 25.4


def _released_case(**changes):
    inputs = {
        "external_pressure_mpa": 6.0,
        "internal_radius_mm": 100.0,
        "wall_thickness_mm": 100.0 / 39.5,
        "elastic_modulus_mpa": 68_900.0,
        "poisson_ratio": 0.33,
        "strength_mpa": 276.0,
        "proportional_limit_mpa": 200.0,
        "material_failure_category": "ductile_metal",
    }
    inputs.update(changes)
    return hemispherical_head_external_pressure(**inputs)


def test_thin_hemisphere_reports_biaxial_von_mises_and_released_nasa_capacity() -> None:
    result = _released_case()

    assert result.model_id == HEMISPHERE_MODEL_ID
    assert result.model_version == HEMISPHERE_MODEL_VERSION
    assert result.branch == "thin"
    assert result.mean_radius_over_thickness == 40.0
    assert len(result.stress_states) == 1
    state = result.stress_states[0]
    assert state.radial_stress_mpa == 0.0
    assert state.meridional_stress_mpa == -120.0
    assert state.hoop_stress_mpa == -120.0
    assert state.von_mises_stress_mpa == 120.0
    assert result.theoretical_stress_failure_pressure_mpa == pytest.approx(13.8)
    assert result.stress_margin == pytest.approx(1.3)

    expected_classical = (
        2.0 * 68_900.0 / math.sqrt(3.0 * (1.0 - 0.33**2)) / 40.0**2
    )
    expected_lambda = (12.0 * (1.0 - 0.33**2)) ** 0.25 * math.sqrt(40.0) * math.sqrt(2.0)
    expected_factor = 0.14 + 3.2 / expected_lambda**2
    assert result.classical_critical_pressure_mpa == pytest.approx(expected_classical)
    assert result.nasa_geometry_parameter_lambda == pytest.approx(expected_lambda)
    assert result.nasa_correlation_factor == pytest.approx(expected_factor)
    assert result.released_buckling_pressure_mpa == pytest.approx(
        expected_factor * expected_classical
    )
    assert result.buckling_capacity_status == "released"
    assert result.buckling_validity_violations == ()


def test_thin_hemisphere_releases_the_membrane_displacement_at_the_median_surface() -> None:
    """NASA TM-4579 Eq. (5), signed for external pressure and positive outward.

    The source states the displacement on the same line as the membrane stress
    this branch already reports, so the released value is checked both against
    the literal equation and against that stress through the biaxial Hooke's
    law the two share.
    """
    result = _released_case()
    state = result.stress_states[0]
    mean_radius = 100.0 + 0.5 * (100.0 / 39.5)
    thickness = 100.0 / 39.5

    assert result.displacement_status == "released"
    assert result.displacement_validity_violations == ()
    assert result.displacement_source_reference is not None
    assert "NASA Technical Memorandum 4579" in result.displacement_source_reference
    assert state.radius_convention == "mean"
    assert state.radial_displacement_mm == pytest.approx(
        -6.0 * mean_radius**2 * (1.0 - 0.33) / (2.0 * 68_900.0 * thickness),
        rel=1.0e-12,
    )
    # The same value is the median radius times the circumferential strain of
    # the reported equal-biaxial membrane stress.
    assert state.radial_displacement_mm == pytest.approx(
        mean_radius * state.hoop_stress_mpa * (1.0 - 0.33) / 68_900.0,
        rel=1.0e-12,
    )
    assert state.radial_displacement_mm < 0.0


def test_hemisphere_displacement_scales_with_pressure_thickness_and_poisson() -> None:
    """Eq. (5) is linear in pressure, grows as the wall thins, and carries (1 - nu)."""
    base = _released_case()
    doubled_pressure = _released_case(external_pressure_mpa=12.0)
    assert doubled_pressure.stress_states[0].radial_displacement_mm == pytest.approx(
        2.0 * base.stress_states[0].radial_displacement_mm, rel=1.0e-12
    )

    thinner = _released_case(wall_thickness_mm=100.0 / 79.0)
    assert thinner.branch == "thin"
    assert thinner.stress_states[0].radial_displacement_mm < (
        base.stress_states[0].radial_displacement_mm
    )

    nearly_incompressible = _released_case(poisson_ratio=0.499)
    assert nearly_incompressible.stress_states[0].radial_displacement_mm == pytest.approx(
        base.stress_states[0].radial_displacement_mm * (1.0 - 0.499) / (1.0 - 0.33),
        rel=1.0e-12,
    )


def test_thick_hemisphere_withholds_displacement_with_its_reason() -> None:
    result = _released_case(force_thick=True)

    assert result.branch == "thick"
    assert result.displacement_status == "withheld_missing_thick_branch_source"
    assert result.displacement_source_reference is None
    assert result.displacement_validity_violations == (
        "the released displacement equation is a thin-shell membrane result; no consulted "
        "primary source states a radial displacement for the thick-sphere branch, and none is "
        "derived here",
    )
    assert [state.radius_convention for state in result.stress_states] == [
        "internal",
        "external",
    ]
    assert all(state.radial_displacement_mm is None for state in result.stress_states)


def test_thick_hemisphere_reproduces_the_published_stress_and_invalid_buckling() -> None:
    result = hemispherical_head_external_pressure(
        external_pressure_mpa=1_000.0 * PSI_TO_MPA,
        internal_radius_mm=1.75 * INCH_TO_MM,
        wall_thickness_mm=0.25 * INCH_TO_MM,
        elastic_modulus_mpa=9_900_000.0 * PSI_TO_MPA,
        poisson_ratio=0.33,
        strength_mpa=35_000.0 * PSI_TO_MPA,
        material_failure_category="ductile_metal",
    )

    assert result.branch == "thick"
    assert result.mean_radius_over_thickness == pytest.approx(7.5)
    assert result.governing_stress_mpa / PSI_TO_MPA == pytest.approx(
        4_544.4,
        abs=0.05,
    )
    assert result.theoretical_stress_failure_pressure_mpa / PSI_TO_MPA == pytest.approx(
        7_701.8,
        abs=0.05,
    )
    assert result.roark_probable_minimum_pressure_mpa / PSI_TO_MPA == pytest.approx(
        64_240.0,
        abs=0.5,
    )
    assert result.buckling_capacity_status == "withheld_applicability"
    assert result.released_buckling_pressure_mpa is None
    assert result.buckling_margin is None
    assert any(
        "must be > 10" in violation
        for violation in result.buckling_validity_violations
    )
    assert result.displacement_status == "withheld_missing_thick_branch_source"


def test_hemisphere_seat_is_the_pressure_load_over_the_equator_annulus() -> None:
    result = hemispherical_head_external_pressure(
        external_pressure_mpa=1_000.0 * PSI_TO_MPA,
        internal_radius_mm=1.75 * INCH_TO_MM,
        wall_thickness_mm=0.25 * INCH_TO_MM,
        elastic_modulus_mpa=9_900_000.0 * PSI_TO_MPA,
        poisson_ratio=0.33,
        strength_mpa=35_000.0 * PSI_TO_MPA,
        material_failure_category="ductile_metal",
    )

    # p * R_o^2 / (R_o^2 - R_i^2) = 1000 * 4 / (4 - 3.0625) psi, a positive magnitude
    # equal to the closed-end Lame axial stress on the same radii.
    seat_psi = 1_000.0 * 2.0**2 / (2.0**2 - 1.75**2)
    assert result.seat_bearing_stress_mpa / PSI_TO_MPA == pytest.approx(seat_psi)
    assert result.seat_bearing_stress_mpa == pytest.approx(
        -closed_end_tube_stress(
            external_pressure_mpa=1_000.0 * PSI_TO_MPA,
            internal_radius_mm=1.75 * INCH_TO_MM,
            wall_thickness_mm=0.25 * INCH_TO_MM,
            strength_mpa=35_000.0 * PSI_TO_MPA,
            material_failure_category="ductile_metal",
            force_thick=True,
        ).stress_states[0].axial_stress_mpa
    )
    assert result.seat_margin == pytest.approx(35_000.0 / seat_psi - 1.0)
    assert result.theoretical_seat_failure_pressure_mpa / PSI_TO_MPA == pytest.approx(
        35_000.0 / seat_psi * 1_000.0
    )
    # The seat does not enter the shell stress margin.
    assert result.stress_margin == pytest.approx(
        35_000.0 / (result.governing_stress_mpa / PSI_TO_MPA) - 1.0
    )


def test_hemisphere_elastic_gate_releases_at_and_withholds_below_proportional_limit() -> None:
    baseline = _released_case()
    critical_stress = baseline.nasa_candidate_critical_membrane_stress_mpa
    assert critical_stress is not None

    at_limit = _released_case(proportional_limit_mpa=critical_stress)
    below_limit = _released_case(
        proportional_limit_mpa=math.nextafter(critical_stress, 0.0)
    )
    missing = _released_case(proportional_limit_mpa=None)

    assert at_limit.buckling_capacity_status == "released"
    assert below_limit.buckling_capacity_status == "withheld_applicability"
    assert missing.buckling_capacity_status == "withheld_applicability"
    assert below_limit.released_buckling_pressure_mpa is None
    assert missing.released_buckling_pressure_mpa is None


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"external_pressure_mpa": 0.0}, "external_pressure_mpa must be finite and positive"),
        ({"poisson_ratio": 0.5}, "poisson_ratio must be finite and between 0 and 0.5"),
        (
            {"proportional_limit_mpa": 300.0},
            "proportional_limit_mpa must be <= strength_mpa",
        ),
        (
            {"material_failure_category": "ceramic"},
            "material_failure_category must be one of",
        ),
    ],
)
def test_hemisphere_rejects_unevaluable_inputs(changes, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        _released_case(**changes)


def test_hemisphere_categories_select_the_criterion_and_share_the_seat_strength() -> None:
    plastic = _released_case(material_failure_category="plastic", proportional_limit_mpa=None)
    brittle = _released_case(material_failure_category="brittle", strength_mpa=1_000.0)
    ductile = _released_case()

    assert plastic.failure_criterion == "maximum_hoop_stress_vs_working_strength"
    assert brittle.failure_criterion == "maximum_hoop_stress_vs_ultimate_compressive_strength"
    assert ductile.failure_criterion == "von_mises_stress_vs_yield_strength"
    # Thin branch: |hoop| equals the biaxial von Mises stress, so the plastic
    # margin equals the ductile one at the same strength.
    assert plastic.governing_stress_mpa == pytest.approx(ductile.governing_stress_mpa)
    assert plastic.stress_margin == pytest.approx(ductile.stress_margin)
    # The seat reads the same strength the shell criterion does.
    assert brittle.seat_margin == pytest.approx(1_000.0 / brittle.seat_bearing_stress_mpa - 1.0)
    # Buckling never reads the strength; the plastic case merely lacks the
    # proportional limit needed to release it.
    assert brittle.released_buckling_pressure_mpa == ductile.released_buckling_pressure_mpa
    assert plastic.buckling_capacity_status == "withheld_applicability"
    # A proportional limit above the working strength is legitimate for a plastic.
    assert _released_case(
        material_failure_category="plastic", strength_mpa=20.0, proportional_limit_mpa=30.0
    ).stress_margin < 0.0
