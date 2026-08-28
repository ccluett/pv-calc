from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from pv_calc.pressure_vessel import (
    SMOOTH_CYLINDER_MODERATE_GAMMA,
    smooth_cylinder_external_pressure_buckling,
)
from pv_calc.units import Q_, magnitude


FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _kernel(
    *,
    radius: float = 500.0,
    thickness: float = 5.0,
    length: float = 1800.0,
    pressure: float = 0.01,
    elastic_modulus: float = 70_000.0,
    poisson_ratio: float = 0.3,
    yield_strength: float = 250.0,
    proportional_limit: float | None = 200.0,
    load_case: str = "hydrostatic_closed_end",
):
    return smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=pressure,
        shell_mid_surface_radius_mm=radius,
        wall_thickness_mm=thickness,
        unsupported_length_mm=length,
        elastic_modulus_mpa=elastic_modulus,
        poisson_ratio=poisson_ratio,
        yield_strength_mpa=yield_strength,
        load_case=load_case,  # type: ignore[arg-type]
        proportional_limit_mpa=proportional_limit,
    )


def _length_for_z(z: float, *, radius: float, thickness: float, poisson_ratio: float) -> float:
    return math.sqrt(z * radius * thickness / math.sqrt(1.0 - poisson_ratio**2))


@pytest.mark.parametrize(
    ("load_case", "expected_k", "expected_beta", "expected_pressure", "expected_axial"),
    [
        (
            "lateral_only",
            6.286941901579239,
            1.7063331899914709,
            1.3537046232398835,
            0.0,
        ),
        (
            "hydrostatic_closed_end",
            5.324455415160412,
            1.6205758021789378,
            1.1992415549616456,
            250.0,
        ),
    ],
)
def test_short_equations_and_load_definitions_are_independently_traceable(
    load_case,
    expected_k,
    expected_beta,
    expected_pressure,
    expected_axial,
):
    result = _kernel(length=300.0, pressure=1.0, load_case=load_case)
    candidate = result.candidates[0]

    assert result.unsupported_length_over_radius == pytest.approx(0.6)
    assert result.curvature_parameter_z == pytest.approx(34.34181125101004)
    assert result.circumferential_line_load_n_per_mm == pytest.approx(500.0)
    assert result.axial_line_load_n_per_mm == pytest.approx(expected_axial)
    assert result.line_load_sign_convention == "positive_compression_magnitude"
    assert result.regime == "short"
    assert result.capacity_status == "released"
    assert result.correlated_critical_pressure_mpa is not None
    assert candidate.correlation_factor_gamma == pytest.approx(0.5625)
    assert candidate.critical_buckling_coefficient == pytest.approx(expected_k)
    assert candidate.critical_aspect_ratio_beta == pytest.approx(expected_beta)
    assert candidate.ideal_critical_pressure_mpa == pytest.approx(expected_pressure)
    assert result.release_gate_violations == ()


def test_moderate_printed_eq24_is_released_for_both_pressure_load_cases():
    lateral = _kernel(load_case="lateral_only")
    hydrostatic = _kernel(load_case="hydrostatic_closed_end")

    for result in (lateral, hydrostatic):
        assert result.regime == "moderate"
        assert result.capacity_status == "released"
        assert result.curvature_parameter_z == pytest.approx(1236.3052050363615)
        assert result.correlation_factor_gamma == pytest.approx(0.5625)
        assert result.sqrt_correlation_factor == pytest.approx(0.75)
        assert result.critical_buckling_coefficient == pytest.approx(27.425682976803374)
        assert result.correlated_critical_pressure_mpa == pytest.approx(0.1338264239601989)
        assert result.source_equations == ("NASA Eq. 23", "NASA Eq. 24", "NASA Eq. 28")

    assert lateral.correlated_critical_pressure_mpa == pytest.approx(
        hydrostatic.correlated_critical_pressure_mpa
    )
    assert lateral.critical_aspect_ratio_beta == pytest.approx(4.462557524401072)
    assert hydrostatic.critical_aspect_ratio_beta == pytest.approx(4.4421586057229955)


def test_eq25_is_a_traceable_rounded_comparator_without_a_nu_branch_jump():
    result = _kernel(poisson_ratio=0.316)
    candidate = result.candidates[1]

    assert result.regime == "moderate"
    assert candidate.source_equations == (
        "NASA Eq. 23",
        "NASA Eq. 24",
        "NASA Eq. 25",
        "NASA Eq. 28",
    )
    assert result.correlated_critical_pressure_mpa == pytest.approx(0.13492391182371495)
    assert candidate.eq25_simplified_critical_pressure_mpa == pytest.approx(
        0.13504166666666666
    )
    assert candidate.eq25_simplified_critical_pressure_mpa != pytest.approx(
        result.correlated_critical_pressure_mpa,
        rel=1.0e-5,
    )


def test_long_oval_eq27_is_released_only_beyond_the_factor_overlap():
    result = _kernel(thickness=25.0, length=11_000.0)

    assert result.regime == "long"
    assert result.capacity_status == "released"
    assert result.correlation_factor_gamma == pytest.approx(0.9)
    assert result.circumferential_wave_count_n == 2
    assert result.continuous_circumferential_wave_count == 2.0
    assert result.critical_aspect_ratio_beta is None
    assert result.correlated_critical_pressure_mpa == pytest.approx(2.1634615384615383)
    assert result.source_equations == ("NASA Eq. 26", "NASA Eq. 27", "NASA Eq. 29")


def test_short_moderate_and_moderate_long_boundaries_are_explicitly_gated():
    radius = 500.0
    thickness = 5.0
    poisson_ratio = 0.3
    short_gamma_z_limit = 100.0
    moderate_start_z = short_gamma_z_limit / SMOOTH_CYLINDER_MODERATE_GAMMA

    # Mid-regime control: Z = 100 sits at gamma*Z = 56.25, inside short.
    mid_short = _kernel(
        length=_length_for_z(
            short_gamma_z_limit * (1.0 - 1.0e-10),
            radius=radius,
            thickness=thickness,
            poisson_ratio=poisson_ratio,
        )
    )
    just_below_moderate = _kernel(
        length=_length_for_z(
            moderate_start_z * (1.0 - 1.0e-10),
            radius=radius,
            thickness=thickness,
            poisson_ratio=poisson_ratio,
        )
    )
    just_moderate = _kernel(
        length=_length_for_z(
            moderate_start_z * (1.0 + 1.0e-10),
            radius=radius,
            thickness=thickness,
            poisson_ratio=poisson_ratio,
        )
    )
    assert mid_short.regime == "short"
    assert mid_short.capacity_status == "released"
    assert just_below_moderate.regime == "short"
    assert just_below_moderate.capacity_status == "released"
    assert just_moderate.regime == "moderate"
    assert just_moderate.capacity_status == "released"

    radius = 500.0
    thickness = 25.0
    reference = _kernel(radius=radius, thickness=thickness, length=9000.0)
    overlap_start = reference.moderate_long_overlap_start_z
    overlap_end = reference.moderate_long_overlap_end_z
    before_overlap = _kernel(
        radius=radius,
        thickness=thickness,
        length=_length_for_z(
            overlap_start * (1.0 - 1.0e-10),
            radius=radius,
            thickness=thickness,
            poisson_ratio=poisson_ratio,
        ),
    )
    overlap = _kernel(
        radius=radius,
        thickness=thickness,
        length=_length_for_z(
            (overlap_start + overlap_end) / 2.0,
            radius=radius,
            thickness=thickness,
            poisson_ratio=poisson_ratio,
        ),
    )
    after_overlap = _kernel(
        radius=radius,
        thickness=thickness,
        length=_length_for_z(
            overlap_end * (1.0 + 1.0e-10),
            radius=radius,
            thickness=thickness,
            poisson_ratio=poisson_ratio,
        ),
    )
    assert before_overlap.regime == "moderate"
    assert overlap.regime == "moderate_long_correlation_overlap"
    assert overlap.capacity_status == "withheld_correlation_overlap"
    assert overlap.correlated_critical_pressure_mpa is None
    assert overlap.candidates[1].applicable is True
    assert overlap.candidates[2].applicable is True
    assert after_overlap.regime == "long"


@pytest.mark.parametrize(
    ("load_case", "expected_exact_pressure", "expected_drop"),
    [
        ("lateral_only", 0.4034234742246888, 0.125208),
        ("hydrostatic_closed_end", 0.3768160035417955, 0.063438),
    ],
)
def test_source_approximations_do_not_claim_false_continuity(
    load_case,
    expected_exact_pressure,
    expected_drop,
):
    radius = 500.0
    thickness = 5.0
    z = 100.0 / SMOOTH_CYLINDER_MODERATE_GAMMA
    length = _length_for_z(
        z,
        radius=radius,
        thickness=thickness,
        poisson_ratio=0.3,
    )
    result = _kernel(length=length, load_case=load_case)
    moderate = result.candidates[1]
    beta_squared = moderate.critical_aspect_ratio_beta**2
    y = 1.0 + beta_squared
    c = 12.0 * 100.0**2 / math.pi**4
    exact_k = (y**2 + c / y**2) / (
        beta_squared if load_case == "lateral_only" else beta_squared + 0.5
    )
    exact_pressure = (
        exact_k
        * math.pi**2
        * result.flexural_rigidity_n_mm
        / (radius * length**2)
    )
    assert result.capacity_status == "released"
    assert result.correlated_critical_pressure_mpa == pytest.approx(exact_pressure)
    assert exact_pressure == pytest.approx(expected_exact_pressure)
    assert moderate.correlated_critical_pressure_mpa == pytest.approx(0.3529116420626633)
    assert 1.0 - moderate.correlated_critical_pressure_mpa / exact_pressure == pytest.approx(
        expected_drop,
        abs=1.0e-6,
    )

    overlap = _kernel(thickness=25.0, length=9000.0)
    moderate_overlap = overlap.candidates[1].correlated_critical_pressure_mpa
    long_overlap = overlap.candidates[2].correlated_critical_pressure_mpa
    assert overlap.capacity_status == "withheld_correlation_overlap"
    assert moderate_overlap is not None and long_overlap is not None
    assert long_overlap / moderate_overlap - 1.0 > 0.20


def test_source_based_thin_tube_and_proportional_limit_gates():
    target_z = 200.0
    radius = 500.0
    thickness = 50.0
    length = _length_for_z(
        target_z,
        radius=radius,
        thickness=thickness,
        poisson_ratio=0.3,
    )
    at_ten = _kernel(
        radius=radius,
        thickness=thickness,
        length=length,
        yield_strength=1.0e12,
        proportional_limit=1.0e12,
    )
    above_ten_radius = math.nextafter(radius, math.inf)
    above_ten = _kernel(
        radius=above_ten_radius,
        thickness=thickness,
        length=_length_for_z(
            target_z,
            radius=above_ten_radius,
            thickness=thickness,
            poisson_ratio=0.3,
        ),
        yield_strength=1.0e12,
        proportional_limit=1.0e12,
    )
    very_thin = _kernel(
        radius=500.0,
        thickness=0.05,
        length=_length_for_z(
            target_z,
            radius=500.0,
            thickness=0.05,
            poisson_ratio=0.3,
        ),
        yield_strength=1.0e12,
        proportional_limit=1.0e12,
    )
    assert at_ten.capacity_status == "withheld_applicability"
    assert any("must be > 10" in item for item in at_ten.validity_violations)
    assert above_ten.capacity_status == "released"
    assert very_thin.shell_mid_surface_radius_over_thickness == pytest.approx(10_000.0)
    assert very_thin.capacity_status == "released"

    baseline = _kernel()
    elastic_limit = baseline.candidates[1].correlated_critical_circumferential_stress_mpa
    assert elastic_limit is not None
    missing_limit = _kernel(yield_strength=1.0e12, proportional_limit=None)
    at_limit = _kernel(yield_strength=250.0, proportional_limit=elastic_limit)
    below_limit = _kernel(
        yield_strength=250.0,
        proportional_limit=math.nextafter(elastic_limit, 0.0),
    )
    assert missing_limit.capacity_status == "withheld_applicability"
    assert any(
        "proportional_limit_mpa is required" in item
        for item in missing_limit.validity_violations
    )
    assert at_limit.capacity_status == "released"
    assert below_limit.capacity_status == "released_pending_plasticity"
    assert below_limit.correlated_critical_pressure_mpa is not None
    assert any("exceeds the supplied proportional limit" in item for item in below_limit.notes)

    # Withheld on another gate, the exceedance is one more violation, and the
    # record carries no note claiming a pending release it never made.
    withheld_and_exceeding = _kernel(radius=50.0, proportional_limit=1.0)
    assert withheld_and_exceeding.capacity_status == "withheld_applicability"
    assert any("must be > 10" in item for item in withheld_and_exceeding.validity_violations)
    assert any(
        "exceeds the supplied proportional limit" in item
        for item in withheld_and_exceeding.validity_violations
    )
    assert withheld_and_exceeding.correlated_critical_pressure_mpa is None
    assert not any("pending validation" in item for item in withheld_and_exceeding.notes)

    with pytest.raises(ValueError, match="must be <= yield_strength_mpa"):
        _kernel(yield_strength=250.0, proportional_limit=250.0001)


def test_software_parity_fixture_is_a_valid_roark_and_nasa_overlap_case():
    fixture = yaml.safe_load(
        (
            FIXTURES / "software_parity/underpressure_example4_tube_buckling.yaml"
        ).read_text()
    )
    inputs = fixture["source_inputs"]
    material = inputs["material"]
    thickness_in = inputs["wall_thickness"]["value"]
    radius_in = inputs["tube_internal_diameter"]["value"] / 2.0 + thickness_in / 2.0
    length_in = inputs["tube_length"]["value"]
    assert radius_in / thickness_in == pytest.approx(
        fixture["source_validity"]["geometry_mean_radius_over_wall_thickness"]
    )

    result = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=magnitude(Q_(1.0, "psi"), "MPa"),
        shell_mid_surface_radius_mm=magnitude(Q_(radius_in, "in"), "mm"),
        wall_thickness_mm=magnitude(Q_(thickness_in, "in"), "mm"),
        unsupported_length_mm=magnitude(Q_(length_in, "in"), "mm"),
        elastic_modulus_mpa=magnitude(
            Q_(material["elastic_modulus"]["value"], material["elastic_modulus"]["unit"]),
            "MPa",
        ),
        poisson_ratio=material["poisson_ratio"]["value"],
        yield_strength_mpa=magnitude(
            Q_(material["working_strength"]["value"], material["working_strength"]["unit"]),
            "MPa",
        ),
        load_case="hydrostatic_closed_end",
    )
    moderate = result.candidates[1]
    ideal_psi = magnitude(Q_(moderate.ideal_critical_pressure_mpa, "MPa"), "psi")
    assert result.curvature_parameter_z == pytest.approx(
        fixture["pv_calc_nasa_comparison"]["curvature_parameter_z"]
    )
    assert ideal_psi == pytest.approx(
        fixture["pv_calc_nasa_comparison"]["printed_eq24_ideal_pressure_psi"]
    )
    assert result.capacity_status == fixture["pv_calc_nasa_comparison"]["capacity_status"]
    assert abs(ideal_psi / fixture["displayed_source_result"]["value"] - 1.0) < 0.003
    # The kernel's own Roark case-20 candidate is the fixture's independent
    # transcription, and reproduces the displayed 266.60 psi at three nodes.
    roark = fixture["independent_roark_case20"]
    assert result.roark_probable_minimum_factor == roark["probable_minimum_factor"]
    assert magnitude(
        Q_(result.roark_probable_minimum_pressure_mpa, "MPa"), "psi"
    ) == pytest.approx(roark["probable_minimum_pressure_psi"], rel=1.0e-12)
    assert result.roark_probable_minimum_lobes_n == roark["governing_circumferential_nodes"]
    displayed = fixture["displayed_source_result"]
    assert magnitude(
        Q_(result.roark_probable_minimum_pressure_mpa, "MPa"), displayed["unit"]
    ) == pytest.approx(displayed["value"], abs=0.005)
    assert result.roark_probable_minimum_lobes_n == displayed["circumferential_nodes"]


@pytest.mark.parametrize(
    ("label", "elastic_modulus_psi", "poisson_ratio", "mean_radius_in", "wall_in", "length_in",
     "displayed_psi", "half_last_digit_psi", "displayed_lobes"),
    [
        # Example 1, 6061-T6: "Thin Wall Buckling at 81.941 Ksi by 2 nodes" (printed p. 16).
        ("example_1_6061", 9.9e6, 0.33, 3.515, 1.03, 24.0, 81_941.0, 0.5, 2),
        # Example 1, 7075-T6: "Thin Wall Buckling at 10.632 Ksi by 2 nodes" (printed p. 17).
        ("example_1_7075", 10.3e6, 0.33, 3.235, 0.47, 24.0, 10_632.0, 0.5, 2),
        # Report sample, PVC: "Thin Wall Buckling at 2.4984 Ksi by 2 nodes" (printed p. 76).
        ("report_sample_pvc", 0.35e6, 0.36, 1.9845, 0.531, 10.0, 2_498.4, 0.05, 2),
    ],
)
def test_published_thin_wall_buckling_displays_are_the_roark_case20_probable_minimum(
    label, elastic_modulus_psi, poisson_ratio, mean_radius_in, wall_in, length_in,
    displayed_psi, half_last_digit_psi, displayed_lobes,
):
    """The comparison software prints these three thick tubes' buckling values
    without a validity warning being asserted here; the kernel reports the same
    numbers as a software-parity candidate and withholds capacity, because
    every one of them is at or below the r/t = 10 thin-shell gate.

    tests/fixtures/software_parity/ records which tool the displays come from."""
    result = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=magnitude(Q_(1.0, "psi"), "MPa"),
        shell_mid_surface_radius_mm=magnitude(Q_(mean_radius_in, "in"), "mm"),
        wall_thickness_mm=magnitude(Q_(wall_in, "in"), "mm"),
        unsupported_length_mm=magnitude(Q_(length_in, "in"), "mm"),
        elastic_modulus_mpa=magnitude(Q_(elastic_modulus_psi, "psi"), "MPa"),
        poisson_ratio=poisson_ratio,
        load_case="hydrostatic_closed_end",
    )
    assert magnitude(
        Q_(result.roark_probable_minimum_pressure_mpa, "MPa"), "psi"
    ) == pytest.approx(displayed_psi, abs=half_last_digit_psi)
    assert result.roark_probable_minimum_lobes_n == displayed_lobes
    assert result.capacity_status == "withheld_applicability"
    assert result.correlated_critical_pressure_mpa is None
    assert result.margin is None


def test_roark_table35_matrix_spans_short_moderate_overlap_and_long():
    fixture = yaml.safe_load(
        (FIXTURES / "software_parity/roark_table35_case20_overlap.yaml").read_text()
    )
    common = fixture["common_inputs"]
    radius_in = common["shell_mean_radius"]["value"]
    thickness_in = common["wall_thickness"]["value"]
    e_psi = common["elastic_modulus"]["value"] * 1.0e6
    for case in fixture["cases"]:
        length_in = case["unsupported_length"]["value"]
        result = smooth_cylinder_external_pressure_buckling(
            external_pressure_mpa=magnitude(Q_(1.0, "psi"), "MPa"),
            shell_mid_surface_radius_mm=magnitude(Q_(radius_in, "in"), "mm"),
            wall_thickness_mm=magnitude(Q_(thickness_in, "in"), "mm"),
            unsupported_length_mm=magnitude(Q_(length_in, "in"), "mm"),
            elastic_modulus_mpa=magnitude(Q_(e_psi, "psi"), "MPa"),
            poisson_ratio=common["poisson_ratio"],
            yield_strength_mpa=1.0e9,
            load_case="hydrostatic_closed_end",
            proportional_limit_mpa=1.0e9,
        )
        assert result.regime == case["nasa_regime"]
        assert result.capacity_status == case["nasa_capacity_status"]
        comparator = next(
            candidate
            for candidate in result.candidates
            if candidate.regime == case["nasa_comparator_regime"]
        )
        comparator_mpa = (
            comparator.ideal_critical_pressure_mpa
            if case["nasa_comparator_pressure_kind"] == "ideal_theoretical"
            else comparator.correlated_critical_pressure_mpa
        )
        assert comparator_mpa is not None
        assert magnitude(Q_(comparator_mpa, "MPa"), "psi") == pytest.approx(
            case["nasa_comparator_pressure_psi"]
        )


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"load_case": "other"}, "load_case"),
        ({"pressure": 0.0}, "external_pressure_mpa"),
        ({"poisson_ratio": 0.5}, "poisson_ratio"),
    ],
)
def test_kernel_rejects_invalid_contract_values(changes, message):
    with pytest.raises(ValueError, match=message):
        _kernel(**changes)


def test_elastic_applicability_screens_the_applied_stress_against_the_release_limit():
    # The release gate compares the *correlated critical* membrane stress with the
    # proportional limit, and that stress is the critical pressure times r/t. Running
    # the same comparison against the applied pressure therefore answers, with no
    # buckling result at all, whether a released capacity could ever reach the applied
    # pressure at this radius and thickness.
    r, t, limit = 500.0, 5.0, 200.0
    within = _kernel(radius=r, thickness=t, pressure=1.0, proportional_limit=limit)
    assert within.working_circumferential_membrane_stress_mpa == pytest.approx(
        1.0 * r / t
    )
    assert within.elastic_applicability == "within"
    assert within.elastic_applicability_limit_mpa == limit
    assert within.elastic_applicability_limit_basis == "proportional_limit"

    # p*r/t = 250 MPa against a 200 MPa limit. The screen does not withhold the
    # result; it states that a released capacity here is necessarily below the
    # applied pressure, because the gate caps any released p_cr at limit*t/r.
    exceeded = _kernel(radius=r, thickness=t, pressure=2.5, proportional_limit=limit)
    assert exceeded.working_circumferential_membrane_stress_mpa == pytest.approx(250.0)
    assert exceeded.elastic_applicability == "exceeded"
    assert limit * t / r < exceeded.external_pressure_mpa

    released_somewhere = False
    for length in (200.0, 1800.0, 20_000.0):
        swept = _kernel(
            radius=r, thickness=t, length=length, pressure=2.5, proportional_limit=limit
        )
        assert swept.elastic_applicability == "exceeded"
        if swept.capacity_status == "released":
            released_somewhere = True
            assert swept.margin is not None and swept.margin < 0.0
    assert released_somewhere, "the sweep must exercise the released branch it constrains"


def test_elastic_applicability_boundary_matches_the_release_gate_comparison():
    # The plasticity check triggers on `stress > proportional_limit`, so the screen
    # uses the same strict comparison and equality stays applicable.
    equal = _kernel(radius=500.0, thickness=5.0, pressure=2.0, proportional_limit=200.0)
    assert equal.working_circumferential_membrane_stress_mpa == pytest.approx(200.0)
    assert equal.elastic_applicability == "within"


def test_elastic_applicability_falls_back_to_yield_and_reports_which_limit_it_used():
    # Yield bounds the proportional limit from above, so an exceedance measured
    # against yield is an exceedance against every admissible proportional limit.
    fallback = _kernel(pressure=2.5, yield_strength=200.0, proportional_limit=None)
    assert fallback.elastic_applicability_limit_basis == "yield_strength"
    assert fallback.elastic_applicability_limit_mpa == 200.0
    assert fallback.working_circumferential_membrane_stress_mpa == pytest.approx(250.0)
    assert fallback.elastic_applicability == "exceeded"

    undetermined = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=2.5,
        shell_mid_surface_radius_mm=500.0,
        wall_thickness_mm=5.0,
        unsupported_length_mm=1800.0,
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.3,
        load_case="hydrostatic_closed_end",
    )
    assert undetermined.elastic_applicability_limit_basis == "unavailable"
    assert undetermined.elastic_applicability_limit_mpa is None
    assert undetermined.elastic_applicability == "undetermined"
    assert undetermined.working_circumferential_membrane_stress_mpa == pytest.approx(
        250.0
    )
