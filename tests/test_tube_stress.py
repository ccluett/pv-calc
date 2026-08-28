from __future__ import annotations

import math
from dataclasses import replace

import pytest

from pv_calc.pressure_vessel import (
    TUBE_DISPLACEMENT_EXCEEDS_THICKNESS,
    TUBE_DISPLACEMENT_MISSING_MODULUS,
    TUBE_DISPLACEMENT_MISSING_POISSON,
    TUBE_THIN_WALL_MEAN_RADIUS_RATIO,
    closed_end_tube_stress,
)


PSI_TO_MPA = 0.006894757293168361
INCH_TO_MM = 25.4

# One thin-branch and one thick-branch geometry, both closed-end under
# external pressure, reused by the displacement tests below.
THIN_GEOMETRY = {"internal_radius_mm": 100.0, "wall_thickness_mm": 5.0}
THICK_GEOMETRY = {"internal_radius_mm": 55.0, "wall_thickness_mm": 22.0}
ELASTIC = {"elastic_modulus_mpa": 68_900.0, "poisson_ratio": 0.33}


def test_thick_tube_failure_pressure_matches_the_published_worked_example() -> None:
    result = closed_end_tube_stress(
        external_pressure_mpa=1_000.0 * PSI_TO_MPA,
        internal_radius_mm=3.0 * INCH_TO_MM,
        wall_thickness_mm=0.470 * INCH_TO_MM,
        strength_mpa=62_000.0 * PSI_TO_MPA,
        material_failure_category="ductile_metal",
    )

    assert result.branch == "thick"
    assert result.mean_radius_over_thickness < TUBE_THIN_WALL_MEAN_RADIUS_RATIO
    assert result.governing_radius_mm == pytest.approx(result.internal_radius_mm)
    assert result.theoretical_failure_pressure_mpa / PSI_TO_MPA / 1_000.0 == pytest.approx(
        9.0401, abs=0.00005
    )
    assert result.failure_criterion == "von_mises_stress_vs_yield_strength"
    assert result.governing_stress_mpa == max(
        state.von_mises_stress_mpa for state in result.stress_states
    )


def test_plastic_tube_failure_pressure_is_governed_by_hoop_stress() -> None:
    """The manual's PVC report (printed p. 76): 3.438 in I.D., 0.531 in wall.

    At 100 psi it displays a maximum hoop stress of -480.42 psi and, against
    the 6 ksi ultimate strength it evaluated, shell failure at 1.2489 ksi; the
    equivalent stress column reads N/A because a plastic is compared on hoop
    stress alone (Appendix C criterion C).
    """
    result = closed_end_tube_stress(
        external_pressure_mpa=100.0 * PSI_TO_MPA,
        internal_radius_mm=1.719 * INCH_TO_MM,
        wall_thickness_mm=0.531 * INCH_TO_MM,
        material_failure_category="plastic",
        strength_mpa=6_000.0 * PSI_TO_MPA,
    )

    assert result.branch == "thick"
    assert result.failure_criterion == "maximum_hoop_stress_vs_working_strength"
    assert result.governing_radius_mm == pytest.approx(result.internal_radius_mm)
    assert result.governing_stress_mpa / PSI_TO_MPA == pytest.approx(480.42, abs=0.005)
    assert result.theoretical_failure_pressure_mpa / PSI_TO_MPA / 1_000.0 == pytest.approx(
        1.2489, abs=0.00005
    )
    assert result.margin == pytest.approx(6_000.0 / 480.42 - 1.0, rel=1.0e-4)
    assert any("creep" in note for note in result.notes)


def test_brittle_tube_compares_hoop_stress_to_the_supplied_compressive_strength() -> None:
    inputs = {
        "external_pressure_mpa": 10.0,
        "internal_radius_mm": 100.0,
        "wall_thickness_mm": 5.0,
    }
    brittle = closed_end_tube_stress(
        **inputs, material_failure_category="brittle", strength_mpa=1_400.0
    )
    ductile = closed_end_tube_stress(
        **inputs, material_failure_category="ductile_metal", strength_mpa=1_400.0
    )

    assert brittle.failure_criterion == "maximum_hoop_stress_vs_ultimate_compressive_strength"
    assert brittle.governing_stress_mpa == pytest.approx(
        abs(brittle.stress_states[0].hoop_stress_mpa)
    )
    # Every stress state is identical; only the comparison differs, and on the
    # thin branch |hoop| exceeds von Mises, so the brittle margin is the smaller.
    assert brittle.stress_states == ductile.stress_states
    assert brittle.margin < ductile.margin
    assert any("compression" in note for note in brittle.notes)
    assert not any("compression" in note or "creep" in note for note in ductile.notes)


def test_lame_stresses_match_independent_closed_end_equations() -> None:
    pressure = 12.0
    internal_radius = 30.0
    thickness = 10.0
    external_radius = internal_radius + thickness
    denominator = external_radius**2 - internal_radius**2
    expected_axial = -pressure * external_radius**2 / denominator
    expected_inner_hoop = 2.0 * expected_axial
    expected_inner_vm = math.sqrt(3.0) * abs(expected_axial)

    result = closed_end_tube_stress(
        external_pressure_mpa=pressure,
        internal_radius_mm=internal_radius,
        wall_thickness_mm=thickness,
        strength_mpa=300.0,
        material_failure_category="ductile_metal",
    )
    inner, outer = result.stress_states

    assert inner.radial_stress_mpa == pytest.approx(0.0, abs=1e-12)
    assert inner.hoop_stress_mpa == pytest.approx(expected_inner_hoop)
    assert inner.axial_stress_mpa == pytest.approx(expected_axial)
    assert inner.von_mises_stress_mpa == pytest.approx(expected_inner_vm)
    assert outer.radial_stress_mpa == pytest.approx(-pressure)
    assert result.governing_stress_mpa == pytest.approx(expected_inner_vm)


def test_thin_branch_uses_mean_radius_and_force_thick_is_available() -> None:
    inputs = {
        "external_pressure_mpa": 2.0,
        "internal_radius_mm": 100.0,
        "wall_thickness_mm": 5.0,
        "strength_mpa": 276.0,
        "material_failure_category": "ductile_metal",
    }
    thin = closed_end_tube_stress(**inputs)
    thick = closed_end_tube_stress(**inputs, force_thick=True)

    assert thin.branch == "thin"
    assert thin.stress_states[0].radius_convention == "mean"
    assert thin.stress_states[0].hoop_stress_mpa == pytest.approx(-2.0 * 102.5 / 5.0)
    assert thin.stress_states[0].axial_stress_mpa == pytest.approx(-2.0 * 102.5 / 10.0)
    assert thick.branch == "thick"
    assert {state.radius_convention for state in thick.stress_states} == {"internal", "external"}


def test_branch_boundary_and_unsupported_material_are_explicit() -> None:
    at_threshold = closed_end_tube_stress(
        external_pressure_mpa=1.0,
        internal_radius_mm=9.5,
        wall_thickness_mm=1.0,
        strength_mpa=100.0,
        material_failure_category="ductile_metal",
    )
    assert at_threshold.mean_radius_over_thickness == pytest.approx(10.0)
    assert at_threshold.branch == "thick"
    just_above_threshold = closed_end_tube_stress(
        external_pressure_mpa=1.0,
        internal_radius_mm=9.500001,
        wall_thickness_mm=1.0,
        strength_mpa=100.0,
        material_failure_category="ductile_metal",
    )
    assert just_above_threshold.branch == "thin"
    assert (
        at_threshold.governing_stress_mpa
        / (math.sqrt(3.0) * 5.0)
        == pytest.approx(1.1025)
    )
    assert any("branch switch is discrete" in note for note in at_threshold.notes)

    with pytest.raises(ValueError, match="material_failure_category must be one of"):
        closed_end_tube_stress(
            external_pressure_mpa=1.0,
            internal_radius_mm=9.5,
            wall_thickness_mm=1.0,
            strength_mpa=100.0,
            material_failure_category="ceramic",  # type: ignore[arg-type]
        )


def test_displacement_is_withheld_with_a_reason_and_changes_no_stress() -> None:
    stress_only = closed_end_tube_stress(
        external_pressure_mpa=2.0,
        strength_mpa=276.0,
        material_failure_category="ductile_metal",
        **THIN_GEOMETRY,
    )

    assert stress_only.displacement_status == "withheld_missing_elastic_properties"
    assert stress_only.displacement_validity_violations == (
        TUBE_DISPLACEMENT_MISSING_MODULUS,
        TUBE_DISPLACEMENT_MISSING_POISSON,
    )
    assert stress_only.elastic_modulus_mpa is None
    assert stress_only.poisson_ratio is None
    assert stress_only.axial_strain is None
    assert stress_only.axial_length_change_mm is None
    assert stress_only.stress_states[0].radial_displacement_mm is None

    # One property alone still withholds, and names only the missing one.
    modulus_only = closed_end_tube_stress(
        external_pressure_mpa=2.0,
        strength_mpa=276.0,
        material_failure_category="ductile_metal",
        elastic_modulus_mpa=68_900.0,
        **THIN_GEOMETRY,
    )
    assert modulus_only.displacement_validity_violations == (
        TUBE_DISPLACEMENT_MISSING_POISSON,
    )
    assert modulus_only.axial_strain is None

    # Supplying both leaves every stress quantity bit-identical.
    with_elasticity = closed_end_tube_stress(
        external_pressure_mpa=2.0,
        strength_mpa=276.0,
        material_failure_category="ductile_metal",
        **THIN_GEOMETRY,
        **ELASTIC,
    )
    assert with_elasticity.displacement_status == "released"
    assert with_elasticity.displacement_validity_violations == ()
    assert [
        replace(state, radial_displacement_mm=None)
        for state in with_elasticity.stress_states
    ] == list(stress_only.stress_states)
    assert (
        with_elasticity.governing_stress_mpa
        == stress_only.governing_stress_mpa
    )
    assert with_elasticity.margin == stress_only.margin
    assert (
        with_elasticity.theoretical_failure_pressure_mpa
        == stress_only.theoretical_failure_pressure_mpa
    )


def test_thin_displacement_is_withheld_past_the_source_limit() -> None:
    result = closed_end_tube_stress(
        external_pressure_mpa=25.0,
        internal_radius_mm=99.5,
        wall_thickness_mm=1.0,
        strength_mpa=3000.0,
        material_failure_category="ductile_metal",
        elastic_modulus_mpa=200_000.0,
        poisson_ratio=0.3,
        axial_length_mm=500.0,
    )

    assert result.branch == "thin"
    assert result.margin > 0.0
    assert result.displacement_status == "withheld_applicability"
    assert result.displacement_validity_violations == (
        TUBE_DISPLACEMENT_EXCEEDS_THICKNESS,
    )
    assert result.stress_states[0].radial_displacement_mm is None
    assert result.axial_strain is None
    assert result.axial_length_change_mm is None


def test_thin_displacement_source_limit_is_strictly_greater_than_thickness() -> None:
    # These values make the production equation u = -p mm exactly, avoiding a
    # rounded constructed boundary. DTMB's wording is "exceeds", so equality
    # is released and the next representable pressure is withheld.
    common = {
        "internal_radius_mm": 15.5,
        "wall_thickness_mm": 1.0,
        "strength_mpa": 1_000.0,
        "material_failure_category": "ductile_metal",
        "elastic_modulus_mpa": 224.0,
        "poisson_ratio": 0.25,
    }

    below = closed_end_tube_stress(
        external_pressure_mpa=math.nextafter(1.0, 0.0), **common
    )
    at_limit = closed_end_tube_stress(external_pressure_mpa=1.0, **common)
    above = closed_end_tube_stress(
        external_pressure_mpa=math.nextafter(1.0, math.inf), **common
    )

    assert below.displacement_status == "released"
    assert below.stress_states[0].radial_displacement_mm is not None
    assert at_limit.displacement_status == "released"
    assert at_limit.stress_states[0].radial_displacement_mm == -1.0
    assert above.displacement_status == "withheld_applicability"
    assert above.stress_states[0].radial_displacement_mm is None


@pytest.mark.parametrize("geometry", [THIN_GEOMETRY, THICK_GEOMETRY])
def test_external_pressure_moves_the_wall_inward_and_shortens_the_tube(
    geometry: dict[str, float],
) -> None:
    result = closed_end_tube_stress(
        external_pressure_mpa=2.0,
        strength_mpa=276.0,
        material_failure_category="ductile_metal",
        axial_length_mm=500.0,
        **geometry,
        **ELASTIC,
    )

    assert result.displacement_status == "released"
    for state in result.stress_states:
        assert state.radial_displacement_mm is not None
        assert state.radial_displacement_mm < 0.0
        # Small deformation: the inward movement is far below the wall itself.
        assert abs(state.radial_displacement_mm) < result.wall_thickness_mm
    assert result.axial_strain is not None and result.axial_strain < 0.0
    assert result.axial_length_change_mm == result.axial_strain * 500.0
    assert result.axial_length_change_mm < 0.0


@pytest.mark.parametrize(
    ("geometry", "expected_branch"),
    [(THIN_GEOMETRY, "thin"), (THICK_GEOMETRY, "thick")],
)
def test_displacement_matches_the_transcribed_branch_equations(
    geometry: dict[str, float],
    expected_branch: str,
) -> None:
    pressure = 2.0
    modulus = ELASTIC["elastic_modulus_mpa"]
    poisson = ELASTIC["poisson_ratio"]
    internal_radius = geometry["internal_radius_mm"]
    thickness = geometry["wall_thickness_mm"]
    external_radius = internal_radius + thickness
    mean_radius = internal_radius + thickness / 2.0

    result = closed_end_tube_stress(
        external_pressure_mpa=pressure,
        strength_mpa=276.0,
        material_failure_category="ductile_metal",
        **geometry,
        **ELASTIC,
    )
    assert result.branch == expected_branch

    if expected_branch == "thin":
        # DTMB 1497 Eq. [5] at the median surface, and Eq. [A7] with
        # N_x = -p*R/2 and N_phi = -p*R.
        assert result.stress_states[0].radial_displacement_mm == pytest.approx(
            -pressure * mean_radius**2 * (1.0 - poisson / 2.0) / (modulus * thickness)
        )
        assert result.axial_strain == pytest.approx(
            -pressure * mean_radius * (1.0 - 2.0 * poisson) / (2.0 * modulus * thickness)
        )
    else:
        # Boresi and Schmidt Eqs. (11.24) and (11.15) with p_1 = 0 and P = 0.
        area_term = external_radius**2 - internal_radius**2
        for state in result.stress_states:
            radius = state.radius_mm
            assert state.radial_displacement_mm == pytest.approx(
                -pressure
                * radius
                * (
                    (1.0 - 2.0 * poisson) * external_radius**2
                    + (1.0 + poisson) * internal_radius**2 * external_radius**2 / radius**2
                )
                / (modulus * area_term)
            )
        assert result.axial_strain == pytest.approx(
            -(1.0 - 2.0 * poisson) * pressure * external_radius**2 / (modulus * area_term)
        )


@pytest.mark.parametrize("geometry", [THIN_GEOMETRY, THICK_GEOMETRY])
def test_displacement_scales_linearly_with_pressure_and_inversely_with_modulus(
    geometry: dict[str, float],
) -> None:
    def evaluate(pressure: float, modulus: float):
        return closed_end_tube_stress(
            external_pressure_mpa=pressure,
            strength_mpa=276.0,
            material_failure_category="ductile_metal",
            elastic_modulus_mpa=modulus,
            poisson_ratio=ELASTIC["poisson_ratio"],
            axial_length_mm=500.0,
            **geometry,
        )

    base = evaluate(2.0, 68_900.0)
    triple_pressure = evaluate(6.0, 68_900.0)
    quarter_modulus = evaluate(2.0, 68_900.0 / 4.0)

    assert triple_pressure.axial_strain == pytest.approx(3.0 * base.axial_strain)
    assert triple_pressure.axial_length_change_mm == pytest.approx(
        3.0 * base.axial_length_change_mm
    )
    assert quarter_modulus.axial_strain == pytest.approx(4.0 * base.axial_strain)
    for scaled, factor in ((triple_pressure, 3.0), (quarter_modulus, 4.0)):
        for state, base_state in zip(scaled.stress_states, base.stress_states, strict=True):
            assert state.radial_displacement_mm == pytest.approx(
                factor * base_state.radial_displacement_mm
            )


@pytest.mark.parametrize("radius_ratio", [10.0, 20.0, 100.0])
def test_the_two_branches_agree_to_the_thin_wall_approximation_error(
    radius_ratio: float,
) -> None:
    """Both branches at one geometry, compared at the accuracy thin-wall has.

    ``force_thick`` evaluates the same tube on the other branch, so the only
    difference is the idealization. Dividing the two transcribed closed forms
    leaves ratios free of the Poisson ratio: ``b^2 / r_m^2`` for the axial
    strain and ``a b^2 / r_m^3`` for the internal-surface displacement. At the
    released ``r_m/t = 10`` switch those are 1.1025 -- the same 10.25% step the
    result already documents for the equivalent stress -- and 1.047375.
    """
    thickness = 1.0
    mean_radius = radius_ratio * thickness
    internal_radius = mean_radius - thickness / 2.0
    external_radius = mean_radius + thickness / 2.0
    inputs = {
        "external_pressure_mpa": 1.0,
        "internal_radius_mm": internal_radius,
        "wall_thickness_mm": thickness,
        "strength_mpa": 276.0,
        "material_failure_category": "ductile_metal",
        **ELASTIC,
    }
    # r_m/t = 10 is on the thick side of the released switch, so the thin
    # branch has to be reached from just above it.
    thin = closed_end_tube_stress(
        **{**inputs, "internal_radius_mm": internal_radius * (1.0 + 1.0e-12)}
    )
    thick = closed_end_tube_stress(**inputs, force_thick=True)
    assert thin.branch == "thin"
    assert thick.branch == "thick"

    thin_state = thin.stress_states[0]
    internal_state, external_state = thick.stress_states
    assert thin_state.radius_convention == "mean"
    assert internal_state.radius_convention == "internal"

    assert thick.axial_strain / thin.axial_strain == pytest.approx(
        external_radius**2 / mean_radius**2, rel=1.0e-9
    )
    assert internal_state.radial_displacement_mm / thin_state.radial_displacement_mm == (
        pytest.approx(internal_radius * external_radius**2 / mean_radius**3, rel=1.0e-9)
    )
    # The thin value is bracketed by the two thick surface values, and the
    # whole spread closes like the wall thins.
    assert (
        internal_state.radial_displacement_mm
        < thin_state.radial_displacement_mm
        < external_state.radial_displacement_mm
    )
    thinness = thickness / mean_radius
    assert abs(
        internal_state.radial_displacement_mm / thin_state.radial_displacement_mm - 1.0
    ) < thinness
    assert abs(thick.axial_strain / thin.axial_strain - 1.0) < 1.5 * thinness
