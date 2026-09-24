from __future__ import annotations

import math

import pytest

from pv_calc.api import calculate
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.presentation import render_text, summarize_response
from pv_calc.pressure_vessel import (
    RingShellResult,
    SmoothCylinderBucklingResult,
    ring_stiffened_shell_external_pressure,
    smooth_cylinder_external_pressure_buckling,
    smooth_cylinder_plasticity_factor,
)


INCH_TO_MM = 25.4
PSI_TO_MPA = 0.006894757293168361
DTMB_YIELD_MPA = 85_000.0 * PSI_TO_MPA


def _dtmb_case(
    frame_spaces: int,
    yield_strength_mpa: float = DTMB_YIELD_MPA,
    proportional_limit_mpa: float | None = None,
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
        proportional_limit_mpa=proportional_limit_mpa,
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


def test_global_search_excludes_axial_half_waves_shorter_than_two_ring_spacings():
    # Deep rings on a thin shell. Unscreened, the smeared search kept falling
    # with m to (42, 2): an 11.9 mm half-wave against a 20 mm ring spacing,
    # an axial-compression wave resting on ring hoop area smeared under it,
    # which no discrete ring can supply there. At one spacing per half-wave
    # (m = 25, 29.0 MPa ideal) that branch is still below the m = 1 mode, so
    # the screen asks for two: m <= 500 / (2 * 20) = 12. The global mode is
    # then the m = 1 lobar mode, and the inter-ring bay, which is what those
    # short waves really are, governs far below it.
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
    assert search.mode_domain == "1<=m<=maximum_axial_half_waves_m,n>=2"
    assert search.minimum_ring_spacings_per_axial_half_wave == 2.0
    assert search.maximum_axial_half_waves_m == 12
    assert search.evaluated_axial_half_waves == 12
    assert (search.critical_axial_half_waves_m, search.critical_circumferential_lobes_n) == (1, 2)
    assert search.ideal_critical_pressure_mpa == pytest.approx(37.619761422245475, rel=1e-12)
    assert search.iterations[-1].frontier_above_governing is True
    assert result.advisory_governing_mode == "inter_ring_smooth_shell"
    assert result.advisory_governing_pressure_mpa < 0.2 * search.adjusted_critical_pressure_mpa


@pytest.mark.parametrize(
    ("frame_spaces", "maximum_m"),
    [(17, 8), (26, 13), (28, 14), (29, 14), (33, 16)],
)
def test_admissible_half_waves_count_whole_pairs_of_ring_spacings(frame_spaces, maximum_m):
    # An exact multiple of two spacings (26 and 28 spaces) counts in full
    # despite rounding in the lengths; an odd spacing left over does not.
    search = _dtmb_case(frame_spaces).global_with_ring_torsion

    assert search.maximum_axial_half_waves_m == maximum_m
    assert search.evaluated_axial_half_waves == maximum_m


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
    # Below two spacings the only global mode left is m = 1, which is kept.
    assert result.global_with_ring_torsion.maximum_axial_half_waves_m == 1
    assert result.global_with_ring_torsion.critical_axial_half_waves_m == 1


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
    assert dispositions["physical_end_restraint"] == "external_blocker"
    assert any("freely warping" in item.basis for item in result.mode_dispositions
               if item.mode == "physical_end_restraint")
    assert any("warp freely" in item or "free to warp" in item for item in result.boundary_assumptions)
    assert any("0.75 factor recommended by NASA" in note for note in result.notes)
    scope = next(note for note in result.notes if note.startswith("Global buckling is elastic"))
    for gap in ("Interframe collapse", "ring tripping", "ring spacing"):
        assert gap in scope


def test_inter_ring_bay_enters_the_minimum_without_a_proportional_limit():
    # The only difference between these runs is the optional proportional limit,
    # which every bundled material record omits. Without it the smooth kernel
    # withholds the bay, but the ring model still compares the bay's elastic
    # pressure, screened like the global mode, so the governing pressure does
    # not jump to the global mode 38 times higher.
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
    no_limit = ring_stiffened_shell_external_pressure(
        **{**geometry, "yield_strength_mpa": None}
    )

    assert compared.inter_ring_shell_buckling.capacity_status == "released"
    assert withheld.inter_ring_shell_buckling.capacity_status == "withheld_applicability"
    for result in (compared, withheld, no_limit):
        assert result.advisory_candidate_modes == (
            "global_eq64_with_eq91_ring_torsion",
            "inter_ring_smooth_shell",
        )
        assert result.advisory_governing_mode == "inter_ring_smooth_shell"
        assert result.advisory_governing_pressure_mpa == pytest.approx(0.2465562230804379)
        assert (
            38.0 * result.advisory_governing_pressure_mpa
            < result.global_with_ring_torsion.adjusted_critical_pressure_mpa
        )
    # Only the proportional limit shows the bay's stress is elastic. Below
    # yield without one, or with no limit at all, the label is undetermined,
    # so supplying less material data never gives a cleaner label.
    assert compared.advisory_governing_status == "advisory"
    assert withheld.advisory_governing_status == "advisory_plasticity_undetermined"
    assert no_limit.advisory_governing_status == "advisory_plasticity_undetermined"


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
    # Nothing else in this geometry objects: the mode search converges and no
    # validity gate fires. Only the implied shell stress says the global
    # pressure is unreachable.
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
    # The pressure is still compared; the model releases nothing either way.
    # The inter-ring bay's elastic bound, also above yield, is lower.
    assert result.advisory_candidate_modes == (
        "global_eq64_with_eq91_ring_torsion",
        "inter_ring_smooth_shell",
    )
    assert result.advisory_governing_mode == "inter_ring_smooth_shell"
    assert result.advisory_governing_pressure_mpa == pytest.approx(15.143474789029423)
    assert result.advisory_governing_status == "advisory_pending_plasticity"
    assert any("because NASA provides no plasticity correction" in note for note in result.notes)


def test_global_capacity_at_the_material_limit_stays_unflagged():
    # The screen is a strict `stress > limit`, so equality is the last unflagged
    # case. These runs move the proportional limit onto and just under the
    # global stress of DTMB case 17 to pin which side of the comparison it sits
    # on. With the yield strength alone, a stress below yield stays undetermined.
    yield_only = _dtmb_case(17)
    stress = yield_only.global_critical_circumferential_membrane_stress_mpa
    at_limit = _dtmb_case(17, proportional_limit_mpa=stress)
    just_under = _dtmb_case(17, proportional_limit_mpa=stress * (1.0 - 1e-12))

    assert yield_only.global_elastic_applicability == "within"
    assert yield_only.advisory_governing_status == "advisory_plasticity_undetermined"
    assert at_limit.global_elastic_applicability == "within"
    assert at_limit.advisory_governing_mode == "global_eq64_with_eq91_ring_torsion"
    assert at_limit.advisory_governing_status == "advisory"
    assert not any(
        "because NASA provides no plasticity correction" in note for note in at_limit.notes
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
    # pressure. Without the proportional limit the bay's elastic pressure is
    # screened against yield instead, so both runs report the same bound.
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
    assert screened.inter_ring_shell_buckling.margin is None
    assert screened.advisory_candidate_modes == (
        "global_eq64_with_eq91_ring_torsion",
        "inter_ring_smooth_shell",
    )
    assert screened.advisory_governing_mode == "inter_ring_smooth_shell"
    assert screened.advisory_governing_pressure_mpa == pytest.approx(42.567981637437406)
    assert screened.advisory_margin == pytest.approx(3.2567981637437406)
    assert screened.advisory_governing_status == "advisory_pending_plasticity"

    assert unscreened.inter_ring_shell_buckling.capacity_status == "withheld_applicability"
    assert unscreened.advisory_governing_mode == "inter_ring_smooth_shell"
    assert unscreened.advisory_governing_pressure_mpa == screened.advisory_governing_pressure_mpa
    assert unscreened.advisory_governing_status == "advisory_pending_plasticity"


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
        "because NASA provides no plasticity correction" in note for note in result.notes
    )
    assert any(
        "NASA inelastic corrections are not implemented for the smeared orthotropic mode"
        in violation
        for violation in result.validity_violations
    )


# R/t = 20 puts the NASA moderate/long overlap at 15.8 R <= spacing <= 20.0 R
# for nu = 0.3, so a 1790 mm spacing is inside it with room on both sides.
OVERLAP_BAY = dict(
    external_pressure_mpa=0.01,
    shell_mid_surface_radius_mm=100.0,
    wall_thickness_mm=5.0,
    unsupported_length_mm=3 * 1790.0,
    ring_spacing_mm=1790.0,
    ring_axial_width_mm=20.0,
    ring_radial_height_mm=60.0,
    ring_location="external",
    elastic_modulus_mpa=110_000.0,
    poisson_ratio=0.3,
    yield_strength_mpa=880.0,
)


@pytest.mark.parametrize(
    "material",
    [
        {},
        {"proportional_limit_mpa": 800.0},
        {"ramberg_osgood_n": 20.0, "compressive_proof_stress_mpa": 880.0},
    ],
    ids=["no_limit", "proportional_limit", "compressive_curve"],
)
def test_inter_ring_bay_in_the_correlation_overlap_forms_no_minimum(material):
    # NASA gives no rule inside the overlap, so the bay is withheld on every
    # material path. A minimum over the global mode alone would report the
    # global pressure as the lowest one although both bay candidates lie far
    # below it; the lowest pressure is not established instead.
    result = ring_stiffened_shell_external_pressure(**OVERLAP_BAY, **material)
    bay = result.inter_ring_shell_buckling
    candidates = {item.regime: item for item in bay.candidates}

    assert bay.regime == "moderate_long_correlation_overlap"
    assert bay.capacity_status == "withheld_correlation_overlap"
    assert candidates["moderate"].applicable and candidates["long"].applicable
    global_pressure = result.global_with_ring_torsion.adjusted_critical_pressure_mpa
    assert global_pressure is not None
    assert global_pressure > 10.0 * max(
        candidates["moderate"].correlated_critical_pressure_mpa,
        candidates["long"].correlated_critical_pressure_mpa,
    )

    assert result.capacity_status == "advisory"
    assert result.advisory_candidate_modes == ()
    assert result.advisory_governing_mode is None
    assert result.advisory_governing_pressure_mpa is None
    assert result.advisory_governing_status is None
    assert result.advisory_margin is None
    assert any(
        "lowest buckling pressure is not established" in note
        and "withheld_correlation_overlap" in note
        for note in result.notes
    )
    # The yield pressures do not depend on the bay's buckling correlation.
    assert result.shell_yield_between_rings_pressure_mpa is not None
    assert result.ring_yield_pressure_mpa is not None


def test_text_report_says_the_lowest_pressure_is_not_established():
    geometry = {
        name: {"value": OVERLAP_BAY[f"{name}_mm"], "unit": "mm"}
        for name in (
            "shell_mid_surface_radius", "wall_thickness", "unsupported_length",
            "ring_spacing", "ring_axial_width", "ring_radial_height",
        )
    }
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "ring-shell",
        "inputs": {
            "external_pressure": {"value": 0.01, "unit": "MPa"},
            **geometry,
            "ring_location": "external",
        },
        "material": {"type": "explicit", "name": "Overlap test metal", "properties": {
            "failure_category": "ductile_metal",
            "elastic_modulus": {"value": 110_000.0, "unit": "MPa"},
            "poisson_ratio": 0.3,
            "yield_strength": {"value": 880.0, "unit": "MPa"},
        }},
    })

    summary = summarize_response(response)
    assert summary["ring_buckling"]["advisory_governing_pressure_mpa"] == {
        "value": None, "unit": "MPa",
    }
    assert summary["ring_buckling"]["inter_ring_capacity_status"] == (
        "withheld_correlation_overlap"
    )
    text = render_text(response)
    assert (
        "Lowest buckling pressure: not established (inter-ring bay "
        "withheld_correlation_overlap)"
    ) in text
    assert "Shell mean hoop yield at mid-bay (Pc5):" in text


TITANIUM = dict(elastic_modulus_mpa=113_800.0, poisson_ratio=0.34, yield_strength_mpa=827.0)
TITANIUM_CURVE = dict(ramberg_osgood_n=21.0, compressive_proof_stress_mpa=827.0)


def _titanium_rings(**overrides) -> RingShellResult:
    """An invented internal-ring titanium shell whose short bays yield before they buckle."""
    inputs = dict(
        external_pressure_mpa=40.0,
        shell_mid_surface_radius_mm=150.0,
        wall_thickness_mm=6.0,
        unsupported_length_mm=1200.0,
        ring_spacing_mm=60.0,
        ring_axial_width_mm=8.0,
        ring_radial_height_mm=20.0,
        ring_location="internal",
        **TITANIUM,
    )
    inputs.update(overrides)
    return ring_stiffened_shell_external_pressure(**inputs)


def _unstiffened_bay(**overrides) -> SmoothCylinderBucklingResult:
    """The same 60 mm bay as a smooth cylinder, whose stresses are p*r/t."""
    inputs = dict(
        external_pressure_mpa=40.0,
        shell_mid_surface_radius_mm=150.0,
        wall_thickness_mm=6.0,
        unsupported_length_mm=60.0,
        load_case="hydrostatic_closed_end",
        **TITANIUM,
    )
    inputs.update(overrides)
    return smooth_cylinder_external_pressure_buckling(**inputs)


def test_inter_ring_plasticity_is_evaluated_at_the_mid_bay_hoop_stress():
    # NASA reads its plasticity factor at the circumferential stress of the
    # buckling shell. Between rings that is the periodic bay's mid-bay hoop
    # membrane stress, here 0.770 p*r/t, so the corrected bay pressure solves
    # p = p_elastic * eta(k p) with that k. Reading eta at p*r/t overstated
    # the plasticity and understated the bay pressure by 21%.
    result = _titanium_rings(**TITANIUM_CURVE)
    bay = result.inter_ring_shell_buckling
    assert result.axisymmetric_stress is not None
    ratio = result.axisymmetric_stress.midbay_shell_hoop_stress_per_unit_pressure
    elastic = next(item for item in bay.candidates if item.regime == bay.regime)
    pressure = bay.correlated_critical_pressure_mpa

    assert bay.circumferential_stress_basis == "ring_stiffened_mid_bay_hoop_membrane"
    assert bay.circumferential_stress_per_unit_pressure == ratio
    assert ratio == pytest.approx(0.770 * 150.0 / 6.0, rel=1e-3)
    assert pressure is not None and elastic.correlated_critical_pressure_mpa is not None
    eta, _ = smooth_cylinder_plasticity_factor(
        ratio * pressure,
        elastic_modulus_mpa=113_800.0,
        **TITANIUM_CURVE,
        gamma_z=elastic.gamma_z,
        more_than_two_wave_boundary=bay.moderate_long_boundary_parameter,
    )
    assert pressure == pytest.approx(elastic.correlated_critical_pressure_mpa * eta, rel=1e-9)
    assert bay.correlated_critical_circumferential_stress_mpa == pytest.approx(ratio * pressure)
    assert bay.working_circumferential_membrane_stress_mpa == pytest.approx(40.0 * ratio)
    assert any("mid-bay hoop membrane stress" in note for note in bay.notes)

    unstiffened = _unstiffened_bay(**TITANIUM_CURVE)
    assert unstiffened.circumferential_stress_basis == "unstiffened_membrane_p_r_over_t"
    assert unstiffened.circumferential_stress_per_unit_pressure == 150.0 / 6.0
    assert not any("mid-bay hoop membrane stress" in note for note in unstiffened.notes)
    assert unstiffened.correlated_critical_pressure_mpa is not None
    assert pressure / unstiffened.correlated_critical_pressure_mpa == pytest.approx(
        1.269, rel=1e-3
    )
    # The corrected bay no longer governs so far below the global mode.
    assert result.advisory_governing_mode == "inter_ring_smooth_shell"
    assert result.advisory_governing_pressure_mpa == pressure


def test_the_corrected_bay_pressure_rises_with_the_curve_proof_stress():
    pressures = [
        _titanium_rings(
            ramberg_osgood_n=21.0, compressive_proof_stress_mpa=proof_stress
        ).inter_ring_shell_buckling.correlated_critical_pressure_mpa
        for proof_stress in (650.0, 750.0, 827.0, 950.0)
    ]

    assert all(
        lower is not None and higher is not None and lower < higher
        for lower, higher in zip(pressures, pressures[1:])
    )


def test_a_bay_whose_mid_bay_stress_exceeds_p_r_over_t_corrects_lower():
    # Past the ring's first half-wave of influence the bay deflection
    # overshoots the free shell's (G < 0), so the mid-bay hoop stress is 2%
    # above p*r/t and the corrected pressure falls below what p*r/t gave. The
    # correction follows the bay's stress; it is not a blanket increase.
    common = dict(
        external_pressure_mpa=10.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=5.0,
        **TITANIUM,
        **TITANIUM_CURVE,
    )
    result = ring_stiffened_shell_external_pressure(
        unsupported_length_mm=1100.0,
        ring_spacing_mm=110.0,
        ring_axial_width_mm=5.0,
        ring_radial_height_mm=15.0,
        ring_location="internal",
        **common,
    )
    unstiffened = smooth_cylinder_external_pressure_buckling(
        unsupported_length_mm=110.0, load_case="hydrostatic_closed_end", **common
    )
    bay = result.inter_ring_shell_buckling

    assert result.axisymmetric_stress is not None
    assert result.axisymmetric_stress.g_function < 0.0
    assert bay.circumferential_stress_per_unit_pressure == pytest.approx(
        1.0206 * 100.0 / 5.0, rel=1e-4
    )
    assert bay.correlated_critical_pressure_mpa is not None
    assert unstiffened.correlated_critical_pressure_mpa is not None
    assert bay.correlated_critical_pressure_mpa < unstiffened.correlated_critical_pressure_mpa


def test_without_a_curve_the_bay_pressure_is_unchanged_but_its_label_reads_the_bay_stress():
    # DTMB case 17: the bay's mid-bay hoop stress is 0.923 p*r/t. A
    # proportional limit between the two stresses at the bay's elastic
    # pressure used to mark the bay an elastic upper bound; its own stress is
    # within the limit, so it is released. The pressure is unchanged.
    limit = 76_000.0 * PSI_TO_MPA
    bay = _dtmb_case(17, proportional_limit_mpa=limit).inter_ring_shell_buckling
    unstiffened = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=1.0 * PSI_TO_MPA,
        shell_mid_surface_radius_mm=4.0765 * INCH_TO_MM,
        wall_thickness_mm=0.035 * INCH_TO_MM,
        unsupported_length_mm=1.152 * INCH_TO_MM,
        elastic_modulus_mpa=30_000_000.0 * PSI_TO_MPA,
        poisson_ratio=0.3,
        yield_strength_mpa=DTMB_YIELD_MPA,
        proportional_limit_mpa=limit,
        load_case="hydrostatic_closed_end",
    )

    assert bay.correlated_critical_pressure_mpa == unstiffened.correlated_critical_pressure_mpa
    assert unstiffened.capacity_status == "released_pending_plasticity"
    assert bay.capacity_status == "released"
    assert bay.correlated_critical_circumferential_stress_mpa is not None
    assert unstiffened.correlated_critical_circumferential_stress_mpa is not None
    assert (
        bay.correlated_critical_circumferential_stress_mpa
        < limit
        < unstiffened.correlated_critical_circumferential_stress_mpa
    )
