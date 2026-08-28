from __future__ import annotations

import math

import pytest

from pv_calc.pressure_vessel import (
    RingShellResult,
    ring_stiffened_shell_external_pressure,
)


INCH_TO_MM = 25.4
PSI_TO_MPA = 0.006894757293168361
DTMB_YIELD_MPA = 85_000.0 * PSI_TO_MPA


def _dtmb_case(
    frame_spaces: int,
    yield_strength_mpa: float = DTMB_YIELD_MPA,
) -> RingShellResult:
    return ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1.0 * PSI_TO_MPA,
        shell_mid_surface_radius_mm=4.0765 * INCH_TO_MM,
        wall_thickness_mm=0.035 * INCH_TO_MM,
        unsupported_length_mm=frame_spaces * 1.152 * INCH_TO_MM,
        ring_spacing_mm=1.152 * INCH_TO_MM,
        ring_axial_width_mm=0.086 * INCH_TO_MM,
        ring_radial_height_mm=0.169 * INCH_TO_MM,
        ring_location="external",
        elastic_modulus_mpa=30_000_000.0 * PSI_TO_MPA,
        poisson_ratio=0.3,
        yield_strength_mpa=yield_strength_mpa,
    )


def test_dtmb_case17_preserves_mid_surface_migration_and_isolates_torsion():
    result = _dtmb_case(17)
    without = result.global_without_ring_torsion
    with_torsion = result.global_with_ring_torsion

    assert result.capacity_status == "advisory"
    assert result.radius_convention == "shell_mid_surface"
    assert result.ring_section_type == "solid_rectangle"
    assert result.ring_area_mm2 == pytest.approx(9.37675544)
    assert result.ring_centroidal_inertia_mm4 == pytest.approx(14.398332070043855)
    assert result.ring_torsional_constant_mm4 == pytest.approx(
        10.150644877245885,
        rel=1e-13,
    )
    assert result.ring_eccentricity_from_shell_mid_surface_mm == pytest.approx(2.5908)

    assert without.converged is True
    assert without.ideal_critical_pressure_mpa / PSI_TO_MPA == pytest.approx(
        536.5437225615963,
        abs=1e-9,
    )
    assert without.adjusted_critical_pressure_mpa / PSI_TO_MPA == pytest.approx(
        402.4077919211972,
        abs=1e-9,
    )
    assert (
        without.critical_axial_half_waves_m,
        without.critical_circumferential_lobes_n,
    ) == (1, 3)

    assert with_torsion.converged is True
    assert with_torsion.ideal_critical_pressure_mpa / PSI_TO_MPA == pytest.approx(
        538.0498670238468,
        abs=1e-9,
    )
    assert with_torsion.adjusted_critical_pressure_mpa / PSI_TO_MPA == pytest.approx(
        403.5374002678851,
        abs=1e-9,
    )
    assert (
        with_torsion.critical_axial_half_waves_m,
        with_torsion.critical_circumferential_lobes_n,
    ) == (1, 3)
    assert result.torsion_ideal_pressure_effect_mpa / PSI_TO_MPA == pytest.approx(
        1.5061444622505,
        abs=1e-9,
    )
    assert result.torsion_adjusted_pressure_effect_mpa / PSI_TO_MPA == pytest.approx(
        1.129608346688,
        abs=1e-9,
    )
    assert result.torsion_changes_governing_mode is False


@pytest.mark.parametrize(
    ("frame_spaces", "ideal_psi", "adjusted_psi", "lobes"),
    [
        (17, 538.0498670238468, 403.5374002678851, 3),
        (23, 379.260498, 284.445374, 2),
        (29, 280.915571, 210.686678, 2),
        (33, 256.031046, 192.023284, 2),
    ],
)
def test_dtmb_published_geometry_cases_span_length_and_lobe_count(
    frame_spaces: int,
    ideal_psi: float,
    adjusted_psi: float,
    lobes: int,
):
    result = _dtmb_case(frame_spaces).global_with_ring_torsion

    assert result.converged is True
    assert result.ideal_critical_pressure_mpa / PSI_TO_MPA == pytest.approx(
        ideal_psi,
        abs=1e-6,
    )
    assert result.adjusted_critical_pressure_mpa / PSI_TO_MPA == pytest.approx(
        adjusted_psi,
        abs=1e-6,
    )
    assert result.critical_axial_half_waves_m == 1
    assert result.critical_circumferential_lobes_n == lobes


def test_expanding_search_converges_on_an_axial_mode_far_above_the_initial_bound():
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=1.0,
        unsupported_length_mm=500.0,
        ring_spacing_mm=20.0,
        ring_axial_width_mm=2.0,
        ring_radial_height_mm=20.0,
        ring_location="external",
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.33,
        yield_strength_mpa=1_000.0,
    )
    search = result.global_with_ring_torsion

    assert search.converged is True
    assert search.termination_reason == "stable_interior_governing_mode"
    assert search.ideal_critical_pressure_mpa == pytest.approx(19.4498805173, abs=1e-9)
    assert (search.critical_axial_half_waves_m, search.critical_circumferential_lobes_n) == (42, 2)
    assert search.evaluated_axial_half_waves >= 100
    assert len(search.iterations) >= 3
    assert search.iterations[-1].frontier_above_governing is True


def test_expanding_search_finds_circumferential_mode_beyond_initial_bound():
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=0.001,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=0.2,
        unsupported_length_mm=100.0,
        ring_spacing_mm=20.0,
        ring_axial_width_mm=1.0,
        ring_radial_height_mm=0.5,
        ring_location="external",
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.33,
        yield_strength_mpa=1_000.0,
    )
    search = result.global_with_ring_torsion

    assert search.converged is True
    assert search.ideal_critical_pressure_mpa == pytest.approx(0.0369489738764, abs=1e-12)
    assert (search.critical_axial_half_waves_m, search.critical_circumferential_lobes_n) == (1, 10)


def test_mode_search_limit_withholds_pressure_and_returns_evidence():
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=1.0,
        unsupported_length_mm=500.0,
        ring_spacing_mm=20.0,
        ring_axial_width_mm=2.0,
        ring_radial_height_mm=20.0,
        ring_location="external",
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.33,
        yield_strength_mpa=1_000.0,
        max_mode_evaluations=100,
    )

    assert result.capacity_status == "withheld_nonconvergence"
    assert result.global_with_ring_torsion.converged is False
    assert result.global_with_ring_torsion.termination_reason == "mode_evaluation_limit"
    assert result.global_with_ring_torsion.ideal_critical_pressure_mpa is None
    assert result.advisory_governing_pressure_mpa is None


@pytest.mark.parametrize(
    "max_mode_evaluations",
    [0, True, 1.5, math.nan, math.inf],
)
def test_mode_search_limit_must_be_a_positive_integer(max_mode_evaluations):
    with pytest.raises(ValueError, match="must be a positive integer"):
        ring_stiffened_shell_external_pressure(
            external_pressure_mpa=1.0,
            shell_mid_surface_radius_mm=100.0,
            wall_thickness_mm=1.0,
            unsupported_length_mm=500.0,
            ring_spacing_mm=20.0,
            ring_axial_width_mm=2.0,
            ring_radial_height_mm=20.0,
            ring_location="external",
            elastic_modulus_mpa=70_000.0,
            poisson_ratio=0.33,
            yield_strength_mpa=1_000.0,
            max_mode_evaluations=max_mode_evaluations,
        )


def test_no_positive_lower_thickness_radius_gate_excludes_dtmb():
    result = _dtmb_case(17)

    assert result.wall_thickness_mm / result.shell_mid_surface_radius_mm < 0.015
    assert result.validity_violations == ()


def test_internal_rectangle_must_preserve_positive_clear_bore():
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=1.0,
        unsupported_length_mm=200.0,
        ring_spacing_mm=20.0,
        ring_axial_width_mm=2.0,
        ring_radial_height_mm=150.0,
        ring_location="internal",
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.33,
        yield_strength_mpa=1_000.0,
    )

    assert result.capacity_status == "withheld_invalid_applicability"
    assert result.advisory_governing_pressure_mpa is None
    assert any("positive clear bore" in item for item in result.validity_violations)


def test_ring_spacing_beyond_the_shell_length_is_withheld():
    # The DTMB case with its two lengths transposed: no bay fits in the span.
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1.0 * PSI_TO_MPA,
        shell_mid_surface_radius_mm=4.0765 * INCH_TO_MM,
        wall_thickness_mm=0.035 * INCH_TO_MM,
        unsupported_length_mm=1.152 * INCH_TO_MM,
        ring_spacing_mm=17 * 1.152 * INCH_TO_MM,
        ring_axial_width_mm=0.086 * INCH_TO_MM,
        ring_radial_height_mm=0.169 * INCH_TO_MM,
        ring_location="external",
        elastic_modulus_mpa=30_000_000.0 * PSI_TO_MPA,
        poisson_ratio=0.3,
        yield_strength_mpa=85_000.0 * PSI_TO_MPA,
    )

    assert result.capacity_status == "withheld_invalid_applicability"
    assert result.advisory_governing_pressure_mpa is None
    assert any("at least one ring bay" in item for item in result.validity_violations)


def test_one_bay_spanning_the_whole_length_stays_released():
    # The gate is `spacing > length`, so equality is the last released case:
    # exactly one bay filling the span. It pins which side of the boundary
    # the comparison sits on.
    spacing_mm = 1.152 * INCH_TO_MM
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1.0 * PSI_TO_MPA,
        shell_mid_surface_radius_mm=4.0765 * INCH_TO_MM,
        wall_thickness_mm=0.035 * INCH_TO_MM,
        unsupported_length_mm=spacing_mm,
        ring_spacing_mm=spacing_mm,
        ring_axial_width_mm=0.086 * INCH_TO_MM,
        ring_radial_height_mm=0.169 * INCH_TO_MM,
        ring_location="external",
        elastic_modulus_mpa=30_000_000.0 * PSI_TO_MPA,
        poisson_ratio=0.3,
        yield_strength_mpa=85_000.0 * PSI_TO_MPA,
    )

    assert not result.validity_violations
    assert result.capacity_status == "advisory"
    assert result.advisory_governing_pressure_mpa is not None


def test_completeness_dispositions_are_machine_readable():
    result = _dtmb_case(17)
    dispositions = {item.mode: item.disposition for item in result.mode_dispositions}

    assert dispositions["global_ring_stiffened_shell_eq64_eq91"] == "implemented_advisory"
    assert dispositions["inter_ring_shell_buckling"] == "implemented_advisory"
    assert dispositions["separate_frame_inertia_rule"] == "not_applicable"
    assert dispositions["web_and_flange_local_slenderness"] == "not_applicable"
    assert dispositions["classification_inter_stiffener_strength"] == "not_applicable"
    assert dispositions["long_cylinder_global_eq66_transition"] == "external_blocker"
    assert dispositions["local_global_interaction"] == "external_blocker"


def test_advisory_candidate_modes_separate_a_withheld_inter_ring_from_a_compared_one():
    # advisory_governing_mode alone cannot carry this distinction: it names the
    # cheapest candidate that produced a pressure, so an inter-ring result
    # withheld for want of a number and one that simply lost both leave the
    # global mode named. The only difference between these two runs is the
    # optional proportional limit, which every bundled material record omits.
    geometry = dict(
        external_pressure_mpa=0.05,
        shell_mid_surface_radius_mm=497.5,
        wall_thickness_mm=5.0,
        unsupported_length_mm=5000.0,
        ring_spacing_mm=1000.0,
        ring_axial_width_mm=20.0,
        ring_radial_height_mm=100.0,
        ring_location="external",
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.33,
        yield_strength_mpa=1_000.0,
    )
    compared = ring_stiffened_shell_external_pressure(
        proportional_limit_mpa=200.0, **geometry
    )
    withheld = ring_stiffened_shell_external_pressure(
        proportional_limit_mpa=None, **geometry
    )

    assert compared.inter_ring_shell_buckling.capacity_status == "released"
    assert compared.advisory_candidate_modes == (
        "global_eq64_with_eq91_ring_torsion",
        "inter_ring_smooth_shell",
    )
    assert compared.advisory_governing_mode == "inter_ring_smooth_shell"

    assert withheld.inter_ring_shell_buckling.capacity_status == "withheld_applicability"
    assert withheld.advisory_candidate_modes == ("global_eq64_with_eq91_ring_torsion",)
    assert withheld.advisory_governing_mode == "global_eq64_with_eq91_ring_torsion"

    # The margin the two runs publish differs by a factor the governing-mode
    # string does not explain, which is what the candidate list is there for.
    assert withheld.advisory_margin > 40.0 * compared.advisory_margin


def _over_limit_case(**overrides) -> RingShellResult:
    geometry = dict(
        external_pressure_mpa=10.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=5.0,
        unsupported_length_mm=600.0,
        ring_spacing_mm=200.0,
        ring_axial_width_mm=10.0,
        ring_radial_height_mm=20.0,
        ring_location="external",
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.33,
        yield_strength_mpa=250.0,
    )
    geometry.update(overrides)
    return ring_stiffened_shell_external_pressure(**geometry)


def test_global_capacity_above_the_material_limit_is_published_as_an_elastic_bound():
    # Nothing else in this geometry objects: the mode search converges, no
    # validity gate fires, and the inter-ring bay has no proportional limit to
    # screen. Only the implied shell stress says the pressure is unreachable.
    result = _over_limit_case()

    assert result.capacity_status == "advisory"
    assert result.validity_violations == ()
    assert result.global_with_ring_torsion.adjusted_critical_pressure_mpa == pytest.approx(
        37.262265529490506
    )
    assert result.global_critical_circumferential_membrane_stress_mpa == pytest.approx(
        745.2453105898101
    )
    assert result.elastic_applicability_limit_mpa == 250.0
    assert result.elastic_applicability_limit_basis == "yield_strength"
    assert result.global_elastic_applicability == "exceeded"
    # The pressure is still published; the model releases nothing either way.
    assert result.advisory_governing_mode == "global_eq64_with_eq91_ring_torsion"
    assert result.advisory_governing_pressure_mpa == pytest.approx(37.262265529490506)
    assert result.advisory_governing_status == "advisory_pending_plasticity"
    assert any("elastic upper bound pending validation" in note for note in result.notes)


def test_global_capacity_at_the_material_limit_stays_unflagged():
    # The screen is a strict `stress > limit`, so equality is the last unflagged
    # case. DTMB case 17 sits well inside it; these two runs move the limit onto
    # and just under the stress to pin which side of the comparison it sits on.
    stress = _dtmb_case(17).global_critical_circumferential_membrane_stress_mpa
    at_limit = _dtmb_case(17, yield_strength_mpa=stress)
    just_under = _dtmb_case(17, yield_strength_mpa=stress * (1.0 - 1e-12))

    assert at_limit.global_elastic_applicability == "within"
    assert at_limit.advisory_governing_status == "advisory"
    assert not any(
        "elastic upper bound pending validation" in note for note in at_limit.notes
    )
    assert just_under.global_elastic_applicability == "exceeded"
    assert just_under.advisory_governing_status == "advisory_pending_plasticity"


def test_no_material_limit_leaves_the_global_screen_undetermined():
    result = _over_limit_case(yield_strength_mpa=None)

    assert result.elastic_applicability_limit_mpa is None
    assert result.elastic_applicability_limit_basis == "unavailable"
    assert result.global_elastic_applicability == "undetermined"
    assert result.advisory_governing_status == "advisory_plasticity_undetermined"


def test_pending_plasticity_inter_ring_bound_governs_the_advisory_minimum():
    # A released_pending_plasticity inter-ring result is an elastic upper bound,
    # so it is a valid minimand: dropping it could only raise the reported
    # pressure. Supplying the proportional limit must therefore never make the
    # advisory number rosier than withholding it.
    screened = _over_limit_case(
        elastic_modulus_mpa=200_000.0,
        poisson_ratio=0.3,
        proportional_limit_mpa=150.0,
    )
    unscreened = _over_limit_case(
        elastic_modulus_mpa=200_000.0,
        poisson_ratio=0.3,
    )

    assert screened.inter_ring_shell_buckling.capacity_status == "released_pending_plasticity"
    assert screened.advisory_candidate_modes == (
        "global_eq64_with_eq91_ring_torsion",
        "inter_ring_smooth_shell",
    )
    assert screened.advisory_governing_mode == "inter_ring_smooth_shell"
    assert screened.advisory_governing_pressure_mpa == pytest.approx(42.567981637437406)
    assert screened.advisory_margin == pytest.approx(3.2567981637437406)
    assert screened.advisory_governing_status == "advisory_pending_plasticity"

    assert unscreened.inter_ring_shell_buckling.capacity_status == "withheld_applicability"
    assert unscreened.advisory_governing_pressure_mpa == pytest.approx(106.68713690205723)
    assert (
        screened.advisory_governing_pressure_mpa
        < unscreened.advisory_governing_pressure_mpa
    )


def test_withheld_record_reports_the_exceedance_as_a_violation_not_a_pending_note():
    # A wall this thick fails the r/t > 10 gate, so every advisory pressure is
    # withheld. The screen's comparison stays published as a fact, but there is
    # no advisory pressure for a pending-validation note to describe: as in the
    # smooth kernel, the exceedance becomes one more violation on the withheld
    # record instead.
    result = _over_limit_case(wall_thickness_mm=15.0)

    assert result.capacity_status == "withheld_invalid_applicability"
    assert result.global_elastic_applicability == "exceeded"
    assert result.advisory_governing_status is None
    assert result.advisory_governing_pressure_mpa is None
    assert not any(
        "elastic upper bound pending validation" in note for note in result.notes
    )
    assert any(
        "NASA inelastic corrections are not implemented for the smeared orthotropic mode"
        in violation
        for violation in result.validity_violations
    )
