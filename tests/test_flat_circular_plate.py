from __future__ import annotations

import pytest

from pv_calc.pressure_vessel import flat_circular_plate


PSI_TO_MPA = 0.006894757293168361
INCH_TO_MM = 25.4
SMALL_DEFLECTION_VIOLATION = (
    "shear_corrected_deflection_estimate_mm exceeds plate_thickness_mm / 2, "
    "the small-deflection limit"
)


def test_simply_supported_plate_failure_pressure_matches_the_published_example() -> None:
    result = flat_circular_plate(
        external_pressure_mpa=4_500.0 * PSI_TO_MPA,
        free_radius_mm=3.0 * INCH_TO_MM,
        plate_thickness_mm=1.280 * INCH_TO_MM,
        elastic_modulus_mpa=10_300_000.0 * PSI_TO_MPA,
        poisson_ratio=0.33,
        strength_mpa=62_000.0 * PSI_TO_MPA,
        material_failure_category="ductile_metal",
        boundary_condition="simply_supported",
    )

    # Independent manual value:
    # 62 ksi / ([3(3 + 0.33)/8] * [3 in / 1.280 in]^2)
    # = 9.038442887 ksi, reported to four decimals as 9.0384 ksi.
    assert result.theoretical_failure_pressure_mpa / PSI_TO_MPA / 1_000.0 == pytest.approx(
        9.0384, abs=0.00005
    )
    assert result.maximum_radial_bending_stress_mpa == pytest.approx(
        result.maximum_tangential_bending_stress_mpa
    )
    assert result.maximum_radial_stress_location == "center"
    assert result.source_equation_case == "Roark Table 24 case 10a"
    assert result.free_diameter_over_thickness == pytest.approx(6.0 / 1.280)
    assert not result.validity_violations
    # No outside radius: the seat values are absent, not zero.
    assert result.outside_radius_mm is None
    assert result.seat_bearing_stress_mpa is None
    assert result.theoretical_seat_failure_pressure_mpa is None
    assert result.seat_margin is None


def test_plate_seat_failure_pressure_and_bending_are_independent() -> None:
    inputs = {
        "external_pressure_mpa": 4_500.0 * PSI_TO_MPA,
        "free_radius_mm": 3.0 * INCH_TO_MM,
        "plate_thickness_mm": 1.280 * INCH_TO_MM,
        "elastic_modulus_mpa": 10_300_000.0 * PSI_TO_MPA,
        "poisson_ratio": 0.33,
        "strength_mpa": 62_000.0 * PSI_TO_MPA,
        "material_failure_category": "ductile_metal",
        "boundary_condition": "simply_supported",
    }
    without_seat = flat_circular_plate(**inputs)
    # Manual plate outside diameter 6.94 in, equal to the Example 1 tube O.D.
    result = flat_circular_plate(**inputs, outside_radius_mm=3.47 * INCH_TO_MM)

    # Independent manual value: 62 ksi * (6.94^2 - 6.00^2) / 6.94^2 = 15.658 ksi,
    # displayed as 15,658 psi; the seat stress itself is p * 6.94^2 / (6.94^2 - 6^2).
    seat_stress_psi = 4_500.0 * 6.94**2 / (6.94**2 - 6.0**2)
    assert result.seat_bearing_stress_mpa / PSI_TO_MPA == pytest.approx(seat_stress_psi)
    assert result.theoretical_seat_failure_pressure_mpa / PSI_TO_MPA == pytest.approx(
        15_658.0, abs=0.5
    )
    assert result.seat_margin == pytest.approx(62_000.0 / seat_stress_psi - 1.0)
    assert result.outside_radius_mm == pytest.approx(3.47 * INCH_TO_MM)
    # The seat is report-only: every bending, deflection, and shear value is unchanged.
    assert result.margin == without_seat.margin
    assert result.theoretical_failure_pressure_mpa == without_seat.theoretical_failure_pressure_mpa
    assert result.maximum_deflection_mm == without_seat.maximum_deflection_mm
    assert result.transverse_shear_stress_mpa == without_seat.transverse_shear_stress_mpa
    assert result.validity_violations == without_seat.validity_violations

    with pytest.raises(ValueError, match="outside_radius_mm must exceed free_radius_mm"):
        flat_circular_plate(**inputs, outside_radius_mm=3.0 * INCH_TO_MM)


@pytest.mark.parametrize(
    (
        "boundary_condition",
        "source_equation_case",
        "radial_stress_psi",
        "tangential_stress_psi",
        "radial_location",
    ),
    [
        ("simply_supported", "Roark Table 24 case 10a", 19_800.0, 19_800.0, "center"),
        ("fixed", "Roark Table 24 case 10b", 12_000.0, 7_800.0, "free_diameter"),
    ],
)
def test_published_appendix_e_plate_surface_stresses(
    boundary_condition,
    source_equation_case,
    radial_stress_psi,
    tangential_stress_psi,
    radial_location,
) -> None:
    result = flat_circular_plate(
        external_pressure_mpa=1_000.0 * PSI_TO_MPA,
        free_radius_mm=2.5 * INCH_TO_MM,
        plate_thickness_mm=0.625 * INCH_TO_MM,
        elastic_modulus_mpa=10_000_000.0 * PSI_TO_MPA,
        poisson_ratio=0.30,
        strength_mpa=62_000.0 * PSI_TO_MPA,
        material_failure_category="ductile_metal",
        boundary_condition=boundary_condition,
    )

    assert result.maximum_radial_bending_stress_mpa / PSI_TO_MPA == pytest.approx(radial_stress_psi)
    assert result.source_equation_case == source_equation_case
    assert result.maximum_tangential_bending_stress_mpa / PSI_TO_MPA == pytest.approx(
        tangential_stress_psi
    )
    assert result.maximum_radial_stress_location == radial_location


def test_plate_deflection_and_transverse_shear_match_independent_equations() -> None:
    pressure = 2.0
    radius = 50.0
    thickness = 10.0
    elastic_modulus = 70_000.0
    poisson_ratio = 0.30
    common = {
        "external_pressure_mpa": pressure,
        "free_radius_mm": radius,
        "plate_thickness_mm": thickness,
        "elastic_modulus_mpa": elastic_modulus,
        "poisson_ratio": poisson_ratio,
        "strength_mpa": 300.0,
        "material_failure_category": "ductile_metal",
    }
    fixed = flat_circular_plate(**common, boundary_condition="fixed")
    simply_supported = flat_circular_plate(**common, boundary_condition="simply_supported")

    rigidity = elastic_modulus * thickness**3 / (12.0 * (1.0 - poisson_ratio**2))
    expected_fixed_deflection = pressure * radius**4 / (64.0 * rigidity)
    expected_simply_supported_deflection = expected_fixed_deflection * (
        (5.0 + poisson_ratio) / (1.0 + poisson_ratio)
    )
    expected_shear = pressure * (2.0 * radius) / (4.0 * thickness)

    assert fixed.flexural_rigidity_n_mm == pytest.approx(rigidity)
    assert fixed.maximum_deflection_mm == pytest.approx(expected_fixed_deflection)
    assert simply_supported.maximum_deflection_mm == pytest.approx(
        expected_simply_supported_deflection
    )
    assert fixed.transverse_shear_stress_mpa == pytest.approx(expected_shear)
    assert simply_supported.transverse_shear_stress_mpa == pytest.approx(expected_shear)
    assert fixed.transverse_shear_location == "free_diameter"
    assert simply_supported.transverse_shear_location == "free_diameter"


def test_plate_validity_envelope_is_reported_by_typed_result() -> None:
    common = {
        "external_pressure_mpa": 1.0,
        "free_radius_mm": 50.0,
        "elastic_modulus_mpa": 70_000.0,
        "poisson_ratio": 0.30,
        "strength_mpa": 300.0,
        "material_failure_category": "ductile_metal",
        "boundary_condition": "fixed",
    }
    # The fixed-edge bending floor is D_free/t = 10, so a 50 mm free radius
    # releases bending at 10 mm thickness and withholds it just above.
    at_diameter_limit = flat_circular_plate(**common, plate_thickness_mm=10.0)
    below_diameter_limit = flat_circular_plate(**common, plate_thickness_mm=10.0001)
    large_deflection = flat_circular_plate(
        **{**common, "external_pressure_mpa": 10.0, "elastic_modulus_mpa": 1_000.0},
        plate_thickness_mm=10.0,
    )

    assert not at_diameter_limit.validity_violations
    assert at_diameter_limit.bending_status == "released"
    assert at_diameter_limit.margin == pytest.approx(
        300.0 / at_diameter_limit.governing_bending_stress_mpa - 1.0
    )
    assert below_diameter_limit.validity_violations == (
        "free_diameter_mm / plate_thickness_mm is below 10.0, "
        "the fixed bending-stress evidence floor",
    )
    # A violation withholds the margin, the verdict, while the Kirchhoff
    # stresses and theoretical failure pressures stay published as such.
    assert below_diameter_limit.bending_status == "withheld_applicability"
    assert below_diameter_limit.margin is None
    assert below_diameter_limit.governing_bending_stress_mpa > 0.0
    assert below_diameter_limit.theoretical_failure_pressure_mpa > 0.0
    assert SMALL_DEFLECTION_VIOLATION in large_deflection.validity_violations
    assert large_deflection.margin is None


def test_bending_and_deflection_carry_separate_evidence_floors() -> None:
    # Swept CAX8R evidence: at D_free/t = 4 the mesh-converged result stays
    # within a few percent of a simply-supported plate's Kirchhoff center
    # stress but exceeds its Kirchhoff center deflection by roughly a
    # quarter, so the two outputs are released independently.
    common = {
        "external_pressure_mpa": 1.0,
        "free_radius_mm": 50.0,
        "elastic_modulus_mpa": 70_000.0,
        "poisson_ratio": 0.30,
        "strength_mpa": 300.0,
        "material_failure_category": "ductile_metal",
    }
    thick = flat_circular_plate(
        **common, plate_thickness_mm=25.0, boundary_condition="simply_supported"
    )
    assert thick.bending_minimum_free_diameter_over_thickness == 4.0
    assert thick.deflection_minimum_free_diameter_over_thickness == 10.0
    # Bending released, deflection withheld, at one geometry.
    assert not thick.validity_violations
    assert thick.deflection_status == "withheld_applicability"
    assert thick.released_maximum_deflection_mm is None
    assert thick.maximum_deflection_mm > 0.0
    assert thick.deflection_validity_violations == (
        "free_diameter_mm / plate_thickness_mm is below 10.0, "
        "the simply_supported center-deflection evidence floor",
    )

    thin = flat_circular_plate(
        **common, plate_thickness_mm=10.0, boundary_condition="simply_supported"
    )
    assert thin.deflection_status == "released"
    assert thin.released_maximum_deflection_mm == thin.maximum_deflection_mm
    assert thin.deflection_validity_violations == ()

    # The simply-supported bending floor sits at D_free/t = 4: released at
    # the floor (the thick case above), withheld just below it.
    below_bending_floor = flat_circular_plate(
        **common, plate_thickness_mm=25.0001, boundary_condition="simply_supported"
    )
    assert below_bending_floor.validity_violations == (
        "free_diameter_mm / plate_thickness_mm is below 4.0, "
        "the simply_supported bending-stress evidence floor",
    )

    # A fixed edge carries the stricter floors from the same evidence.
    fixed = flat_circular_plate(
        **common, plate_thickness_mm=10.0, boundary_condition="fixed"
    )
    assert fixed.bending_minimum_free_diameter_over_thickness == 10.0
    assert fixed.deflection_minimum_free_diameter_over_thickness == 20.0
    assert not fixed.validity_violations
    assert fixed.deflection_status == "withheld_applicability"

    # And its deflection floor sits at D_free/t = 20: released at the floor,
    # withheld just below it.
    fixed_at_deflection_floor = flat_circular_plate(
        **common, plate_thickness_mm=5.0, boundary_condition="fixed"
    )
    assert fixed_at_deflection_floor.deflection_status == "released"
    fixed_below_deflection_floor = flat_circular_plate(
        **common, plate_thickness_mm=5.0001, boundary_condition="fixed"
    )
    assert fixed_below_deflection_floor.deflection_status == "withheld_applicability"


def test_large_deflection_violation_withholds_the_deflection_itself() -> None:
    # An above-limit deflection is invalid output, not merely a gate on the
    # stress result: it must never be published as released.
    result = flat_circular_plate(
        external_pressure_mpa=10.0,
        free_radius_mm=50.0,
        plate_thickness_mm=5.0,
        elastic_modulus_mpa=1_000.0,
        poisson_ratio=0.30,
        strength_mpa=300.0,
        material_failure_category="ductile_metal",
        boundary_condition="fixed",
    )
    assert result.free_diameter_over_thickness == 20.0
    assert result.shear_corrected_deflection_estimate_over_thickness > 0.5
    assert SMALL_DEFLECTION_VIOLATION in result.validity_violations
    assert result.deflection_status == "withheld_applicability"
    assert result.released_maximum_deflection_mm is None
    assert SMALL_DEFLECTION_VIOLATION in result.deflection_validity_violations


@pytest.mark.parametrize(
    ("ratio", "poisson_ratio", "increment_fraction"),
    [
        # Thinnest solved simply-supported case (D_free/t = 40, nu = 0.35):
        # sweep Mindlin increment 0.31057% of Kirchhoff.
        (40.0, 0.35, 0.0031056793673616104),
        # Thick solved case (D_free/t = 6, nu = 0.05), where the increment is
        # 7.78% of Kirchhoff and the gate would trip well before the raw
        # Kirchhoff deflection reaches the limit.
        (6.0, 0.05, 0.07781830814660416),
    ],
)
def test_small_deflection_gate_reads_the_shear_corrected_estimate(
    ratio: float,
    poisson_ratio: float,
    increment_fraction: float,
) -> None:
    # The swept evidence puts the mesh-converged three-dimensional deflection
    # above the Kirchhoff deflection at every solved case and below the
    # shear-corrected estimate at every solved case, so the w <= t/2 limit is
    # compared against that estimate.
    thickness_mm = 2.0 * 50.0 / ratio
    common = {
        "free_radius_mm": 50.0,
        "plate_thickness_mm": thickness_mm,
        "elastic_modulus_mpa": 70_000.0,
        "poisson_ratio": poisson_ratio,
        "strength_mpa": 300.0,
        "material_failure_category": "ductile_metal",
        "boundary_condition": "simply_supported",
    }
    unit = flat_circular_plate(external_pressure_mpa=1.0, **common)
    assert unit.free_diameter_over_thickness == pytest.approx(ratio, rel=1.0e-12)
    assert (
        unit.shear_corrected_deflection_estimate_mm / unit.maximum_deflection_mm - 1.0
    ) == pytest.approx(increment_fraction, rel=1.0e-12)

    # Every deflection here is linear in pressure, so one solve locates the gate.
    limit_pressure = 0.5 / unit.shear_corrected_deflection_estimate_over_thickness
    at_limit = flat_circular_plate(
        external_pressure_mpa=limit_pressure * 0.999, **common
    )
    above_limit = flat_circular_plate(
        external_pressure_mpa=limit_pressure * 1.001, **common
    )
    assert at_limit.shear_corrected_deflection_estimate_over_thickness == pytest.approx(
        0.5, rel=2.0e-3
    )
    assert at_limit.shear_corrected_deflection_estimate_over_thickness < 0.5
    assert not at_limit.validity_violations
    assert not any(
        "small-deflection limit" in violation
        for violation in at_limit.deflection_validity_violations
    )

    assert above_limit.shear_corrected_deflection_estimate_over_thickness > 0.5
    # The raw Kirchhoff deflection is still under the limit here, so this is
    # exactly the interval the shear-corrected estimate recovers.
    assert above_limit.maximum_deflection_over_thickness < 0.5
    assert SMALL_DEFLECTION_VIOLATION in above_limit.validity_violations
    assert SMALL_DEFLECTION_VIOLATION in above_limit.deflection_validity_violations
    assert above_limit.deflection_status == "withheld_applicability"


def test_poisson_ratio_outside_evidence_band_withholds_both_outputs() -> None:
    common = {
        "external_pressure_mpa": 1.0,
        "free_radius_mm": 50.0,
        "plate_thickness_mm": 100.0 / 14.0,
        "elastic_modulus_mpa": 70_000.0,
        "strength_mpa": 300.0,
        "material_failure_category": "ductile_metal",
        "boundary_condition": "simply_supported",
    }
    for poisson in (0.35, 0.05):
        in_band = flat_circular_plate(**common, poisson_ratio=poisson)
        assert not in_band.validity_violations
        assert in_band.deflection_status == "released"
        assert in_band.poisson_ratio_evidence_band == (0.05, 0.35)

    for poisson in (0.45, 0.04):
        out_of_band = flat_circular_plate(**common, poisson_ratio=poisson)
        band_violation = (
            "poisson_ratio is outside the swept evidence band "
            "0.05 <= poisson_ratio <= 0.35"
        )
        assert band_violation in out_of_band.validity_violations
        assert out_of_band.bending_status == "withheld_applicability"
        assert out_of_band.margin is None
        assert band_violation in out_of_band.deflection_validity_violations
        assert out_of_band.deflection_status == "withheld_applicability"
        assert out_of_band.released_maximum_deflection_mm is None


def test_plate_boundary_condition_has_no_default_and_rejects_unknown_values() -> None:
    inputs = {
        "external_pressure_mpa": 1.0,
        "free_radius_mm": 50.0,
        "plate_thickness_mm": 10.0,
        "elastic_modulus_mpa": 70_000.0,
        "poisson_ratio": 0.30,
        "strength_mpa": 300.0,
        "material_failure_category": "ductile_metal",
    }
    with pytest.raises(TypeError, match="boundary_condition"):
        flat_circular_plate(**inputs)
    with pytest.raises(ValueError, match="must be fixed or simply_supported"):
        flat_circular_plate(**inputs, boundary_condition="unknown")


def test_brittle_plate_bends_against_tensile_and_seats_against_compressive_strength() -> None:
    """A brittle window: 5.00 in free diameter, 0.625 in thick, at 1,000 psi.

    The comparison software's Appendix E gives 19,800 psi surface stress for
    that plate at nu = 0.30; validation/published/ records which tool that is.
    The 5 ksi tensile and 210 ksi compressive ultimate strengths are an
    illustrative brittle pair, chosen only so the two criteria are told apart.
    """
    inputs = {
        "external_pressure_mpa": 1_000.0 * PSI_TO_MPA,
        "free_radius_mm": 2.5 * INCH_TO_MM,
        "plate_thickness_mm": 0.625 * INCH_TO_MM,
        "elastic_modulus_mpa": 11_900_000.0 * PSI_TO_MPA,
        "poisson_ratio": 0.30,
        "boundary_condition": "simply_supported",
        "outside_radius_mm": 3.0 * INCH_TO_MM,
    }
    result = flat_circular_plate(
        **inputs,
        material_failure_category="brittle",
        strength_mpa=5_000.0 * PSI_TO_MPA,
        compressive_strength_mpa=210_000.0 * PSI_TO_MPA,
    )

    assert result.failure_criterion == "surface_bending_stress_vs_ultimate_tensile_strength"
    assert result.governing_bending_stress_mpa / PSI_TO_MPA == pytest.approx(19_800.0)
    assert result.theoretical_failure_pressure_mpa / PSI_TO_MPA == pytest.approx(
        1_000.0 * 5_000.0 / 19_800.0
    )
    seat_psi = 1_000.0 * 3.0**2 / (3.0**2 - 2.5**2)
    assert result.seat_bearing_stress_mpa / PSI_TO_MPA == pytest.approx(seat_psi)
    assert result.seat_margin == pytest.approx(210_000.0 / seat_psi - 1.0)
    assert result.compressive_strength_mpa == pytest.approx(210_000.0 * PSI_TO_MPA)
    assert any("convex face" in note for note in result.notes)

    with pytest.raises(ValueError, match="compressive_strength_mpa is required for brittle"):
        flat_circular_plate(
            **inputs, material_failure_category="brittle", strength_mpa=5_000.0 * PSI_TO_MPA
        )
    with pytest.raises(ValueError, match="applies only to brittle"):
        flat_circular_plate(
            **inputs,
            material_failure_category="ductile_metal",
            strength_mpa=300.0,
            compressive_strength_mpa=300.0,
        )


def test_plastic_plate_compares_bending_and_seat_to_the_working_strength() -> None:
    inputs = {
        "external_pressure_mpa": 0.5,
        "free_radius_mm": 50.0,
        "plate_thickness_mm": 8.0,
        "elastic_modulus_mpa": 2_800.0,
        "poisson_ratio": 0.35,
        "boundary_condition": "fixed",
        "outside_radius_mm": 60.0,
    }
    plastic = flat_circular_plate(**inputs, material_failure_category="plastic", strength_mpa=20.0)
    ductile = flat_circular_plate(
        **inputs, material_failure_category="ductile_metal", strength_mpa=20.0
    )

    assert plastic.failure_criterion == "surface_bending_stress_vs_working_strength"
    assert plastic.compressive_strength_mpa is None
    # Same strength, same comparison: only the criterion label and the note differ.
    assert plastic.margin == ductile.margin
    assert plastic.seat_margin == ductile.seat_margin
    assert any("creep" in note for note in plastic.notes)
