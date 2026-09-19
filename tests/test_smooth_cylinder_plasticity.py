"""NASA Eq. 30-32 inelastic correction: moduli, factors, and the bracketed solve.

The equations are transcribed here independently of ``pv_calc``: the tangent
modulus is checked by numerical differentiation rather than by the closed form
the kernel uses, and the three plasticity factors are written out from
NASA/SP-8007-2020/REV 2 p. 29 rather than imported. Agreement between the two
transcriptions is equation evidence only; it is not physical validation of the
correction or of any assumed material curve.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from _cli_helpers import _error_payload

from pv_calc.api import calculate
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.presentation import assess_response
from pv_calc.pressure_vessel import (
    SMOOTH_CYLINDER_MORE_THAN_TWO_WAVE_COEFFICIENT,
    ramberg_osgood_moduli,
    smooth_cylinder_external_pressure_buckling,
    smooth_cylinder_plasticity_factor,
    solve_inelastic_critical_pressure,
)

TITANIUM = {"elastic_modulus_mpa": 113800.0, "ramberg_osgood_n": 21.0,
            "compressive_proof_stress_mpa": 827.0}
ALUMINIUM = {"elastic_modulus_mpa": 68900.0, "ramberg_osgood_n": 28.0,
             "compressive_proof_stress_mpa": 241.0}


def _reference_strain(stress: float, *, e: float, n: float, s0: float) -> float:
    """MIL-HDBK-5J compressive Ramberg-Osgood curve, written out directly."""
    return stress / e + 0.002 * (stress / s0) ** n


def _reference_factors(secant: float, tangent: float, e: float) -> dict[str, float]:
    """NASA Eqs. 30, 31 and 32 transcribed from the printed source."""
    k = tangent / secant
    return {
        "eq30": (secant / e) * (0.5 + 0.5 * math.sqrt(0.25 + 0.75 * k)),
        "eq31": (secant / e) * math.sqrt(math.sqrt(k) * (0.25 + 0.75 * k)),
        "eq32": (secant / e) * (0.25 + 0.75 * k),
    }


@pytest.mark.parametrize("material", [TITANIUM, ALUMINIUM], ids=["Ti", "Al"])
@pytest.mark.parametrize("fraction", [0.2, 0.5, 0.8, 0.95, 1.0, 1.05])
def test_moduli_match_an_independent_curve_and_its_numerical_derivative(
    material: dict[str, float], fraction: float,
) -> None:
    e = material["elastic_modulus_mpa"]
    n = material["ramberg_osgood_n"]
    s0 = material["compressive_proof_stress_mpa"]
    stress = fraction * s0
    secant, tangent = ramberg_osgood_moduli(stress, **material)

    strain = _reference_strain(stress, e=e, n=n, s0=s0)
    assert secant == pytest.approx(stress / strain, rel=1e-12)

    step = stress * 1e-6
    slope = (
        _reference_strain(stress + step, e=e, n=n, s0=s0)
        - _reference_strain(stress - step, e=e, n=n, s0=s0)
    ) / (2.0 * step)
    assert tangent == pytest.approx(1.0 / slope, rel=1e-6)
    assert 0.0 < tangent <= secant <= e


def test_the_proof_stress_reproduces_two_tenths_percent_plastic_strain() -> None:
    for material in (TITANIUM, ALUMINIUM):
        s0 = material["compressive_proof_stress_mpa"]
        secant, _ = ramberg_osgood_moduli(s0, **material)
        plastic = s0 / secant - s0 / material["elastic_modulus_mpa"]
        assert plastic == pytest.approx(0.002, rel=1e-12)


def test_zero_stress_is_fully_elastic_in_both_moduli_and_every_factor() -> None:
    secant, tangent = ramberg_osgood_moduli(0.0, **TITANIUM)
    assert secant == tangent == TITANIUM["elastic_modulus_mpa"]
    for gamma_z in (1.0, 50.0, 500.0):
        eta, _ = smooth_cylinder_plasticity_factor(
            0.0, gamma_z=gamma_z, more_than_two_wave_boundary=1000.0, **TITANIUM
        )
        assert eta == pytest.approx(1.0, rel=1e-15)


@pytest.mark.parametrize(
    ("gamma_z", "boundary", "expected"),
    [
        (4.0, 1000.0, "eq30"),
        (5.0, 1000.0, "eq30"),
        (100.0, 1000.0, "eq31"),
        (500.0, 1000.0, "eq31"),
        (1000.0, 1000.0, "eq31"),
        (1001.0, 1000.0, "eq32"),
    ],
)
def test_each_domain_selects_its_printed_equation(
    gamma_z: float, boundary: float, expected: str,
) -> None:
    stress = 0.95 * TITANIUM["compressive_proof_stress_mpa"]
    secant, tangent = ramberg_osgood_moduli(stress, **TITANIUM)
    reference = _reference_factors(secant, tangent, TITANIUM["elastic_modulus_mpa"])
    eta, _ = smooth_cylinder_plasticity_factor(
        stress, gamma_z=gamma_z, more_than_two_wave_boundary=boundary, **TITANIUM
    )
    assert eta == pytest.approx(reference[expected], rel=1e-12)


@pytest.mark.parametrize("field", ["gamma_z", "more_than_two_wave_boundary"])
@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, -math.inf, math.nan])
def test_the_factor_rejects_invalid_regime_inputs(field: str, value: float) -> None:
    regime = {"gamma_z": 200.0, "more_than_two_wave_boundary": 1000.0}
    regime[field] = value
    with pytest.raises(ValueError, match=rf"{field} must be finite and positive"):
        smooth_cylinder_plasticity_factor(
            0.95 * TITANIUM["compressive_proof_stress_mpa"],
            **regime,
            **TITANIUM,
        )


def test_the_unsupplied_band_interpolates_linearly_and_meets_both_endpoints() -> None:
    stress = 0.95 * TITANIUM["compressive_proof_stress_mpa"]
    secant, tangent = ramberg_osgood_moduli(stress, **TITANIUM)
    reference = _reference_factors(secant, tangent, TITANIUM["elastic_modulus_mpa"])

    def eta(gamma_z: float) -> float:
        value, _ = smooth_cylinder_plasticity_factor(
            stress, gamma_z=gamma_z, more_than_two_wave_boundary=1.0e9, **TITANIUM
        )
        return value

    # NASA states no factor for 5 < gamma*Z < 100 and directs interpolation
    # between Eq. 30 and Eq. 31; the band must join both endpoints exactly.
    assert eta(5.0) == pytest.approx(reference["eq30"], rel=1e-12)
    assert eta(100.0) == pytest.approx(reference["eq31"], rel=1e-12)
    for gamma_z in (5.0, 25.0, 52.5, 80.0, 100.0):
        weight = (gamma_z - 5.0) / 95.0
        expected = (1.0 - weight) * reference["eq30"] + weight * reference["eq31"]
        assert eta(gamma_z) == pytest.approx(expected, rel=1e-12)


def test_the_factor_falls_monotonically_as_stress_rises() -> None:
    previous = 1.1
    for fraction in (0.0, 0.5, 0.8, 0.9, 0.95, 1.0, 1.05, 1.1):
        eta, _ = smooth_cylinder_plasticity_factor(
            fraction * TITANIUM["compressive_proof_stress_mpa"],
            gamma_z=200.0, more_than_two_wave_boundary=1.0e9, **TITANIUM,
        )
        assert 0.0 < eta < previous
        previous = eta


@pytest.mark.parametrize(
    ("material", "expected"),
    [(TITANIUM, 602.045684), (ALUMINIUM, 183.441496)],
    ids=["Ti", "Al"],
)
def test_the_historical_curve_limits_are_at_0p99_tangent_modulus(
    material: dict[str, float], expected: float,
) -> None:
    """Recover the limits stored as reference-only bundled material data.

    This check independently preserves the curve derivation while the material
    qualification status prevents its product-form assumptions from widening.
    """
    e = material["elastic_modulus_mpa"]
    low, high = 1.0e-6, material["compressive_proof_stress_mpa"]
    for _ in range(200):
        middle = (low + high) / 2.0
        _, tangent = ramberg_osgood_moduli(middle, **material)
        if tangent / e > 0.99:
            low = middle
        else:
            high = middle
    assert (low + high) / 2.0 == pytest.approx(expected, abs=5.0e-7)


@pytest.mark.parametrize("gamma_z", [1.0, 5.0, 40.0, 100.0, 400.0, 4000.0])
def test_the_solver_returns_a_bracketed_root_in_every_domain(gamma_z: float) -> None:
    elastic = 200.0
    ratio = 12.0
    root, basis = solve_inelastic_critical_pressure(
        elastic_critical_pressure_mpa=elastic, radius_over_thickness=ratio,
        gamma_z=gamma_z, more_than_two_wave_boundary=1000.0, **TITANIUM,
    )
    assert 0.0 < root <= elastic
    assert basis.startswith("NASA Eq")
    eta, _ = smooth_cylinder_plasticity_factor(
        root * ratio, gamma_z=gamma_z, more_than_two_wave_boundary=1000.0, **TITANIUM
    )
    # The residual p - p_elastic*eta(p*r/t) is zero at the returned root.
    assert root - elastic * eta == pytest.approx(0.0, abs=1e-9 * elastic)


def test_a_wholly_elastic_case_short_circuits_without_bisecting() -> None:
    root, _ = solve_inelastic_critical_pressure(
        elastic_critical_pressure_mpa=1.0e-6, radius_over_thickness=1.0,
        gamma_z=200.0, more_than_two_wave_boundary=1000.0, **TITANIUM,
    )
    assert root == 1.0e-6


def test_the_solver_rejects_nan_gamma_instead_of_returning_the_elastic_endpoint() -> None:
    with pytest.raises(ValueError, match="gamma_z must be finite and positive"):
        solve_inelastic_critical_pressure(
            elastic_critical_pressure_mpa=100.0,
            radius_over_thickness=20.0,
            gamma_z=math.nan,
            more_than_two_wave_boundary=1000.0,
            **ALUMINIUM,
        )


def test_a_severe_correction_still_lands_inside_the_bracket() -> None:
    """A critical stress far past the proof stress drives eta well below one."""
    elastic = 400.0
    ratio = 4.0
    root, _ = solve_inelastic_critical_pressure(
        elastic_critical_pressure_mpa=elastic, radius_over_thickness=ratio,
        gamma_z=200.0, more_than_two_wave_boundary=1000.0, **TITANIUM,
    )
    assert 0.0 < root < 0.5 * elastic
    eta, _ = smooth_cylinder_plasticity_factor(
        root * ratio, gamma_z=200.0, more_than_two_wave_boundary=1000.0, **TITANIUM
    )
    assert root == pytest.approx(elastic * eta, rel=1e-9)


def _kernel(**overrides):
    arguments = {
        "external_pressure_mpa": 92.35134,
        "unsupported_length_mm": 609.6,
        "elastic_modulus_mpa": 113800.0,
        "poisson_ratio": 0.34,
        "load_case": "hydrostatic_closed_end",
        "yield_strength_mpa": 827.0,
    }
    arguments.update(overrides)
    return smooth_cylinder_external_pressure_buckling(**arguments)


def _at_ratio(outside_diameter_mm: float, ratio: float) -> dict[str, float]:
    """Geometry for a mid-surface radius / thickness ratio at a fixed OD."""
    thickness = outside_diameter_mm / (2.0 * ratio + 1.0)
    return {
        "shell_mid_surface_radius_mm": (outside_diameter_mm - thickness) / 2.0,
        "wall_thickness_mm": thickness,
    }


@pytest.mark.parametrize(
    ("outside_diameter_in", "elastic", "corrected"),
    [(12.0, 63.685457, 62.716193), (16.0, 86.908397, 72.966922)],
)
def test_two_preserved_equation_checks_at_ratio_ten_and_a_twentieth(
    outside_diameter_in: float, elastic: float, corrected: float,
) -> None:
    """Both roots need the Eq. 30/31 interpolation; neither is validation.

    These are equation checks against values derived separately from this
    implementation. They fix the correction's arithmetic, not its accuracy.
    """
    geometry = _at_ratio(outside_diameter_in * 25.4, 10.05)
    elastic_only = _kernel(**geometry, proportional_limit_mpa=602.0)
    assert elastic_only.capacity_status == "released_pending_plasticity"
    assert elastic_only.correlated_critical_pressure_mpa == pytest.approx(elastic, abs=5e-7)
    assert elastic_only.margin is None

    with_curve = _kernel(**geometry, ramberg_osgood_n=21.0,
                         compressive_proof_stress_mpa=827.0)
    assert with_curve.capacity_status == "released"
    assert with_curve.correlated_critical_pressure_mpa == pytest.approx(corrected, abs=5e-7)
    assert with_curve.margin is not None
    assert "NASA Eqs. 30-31 interpolated in Z" in with_curve.source_equations
    # The reported critical stress is the one the moduli were read at.
    assert with_curve.correlated_critical_circumferential_stress_mpa == pytest.approx(
        with_curve.correlated_critical_pressure_mpa
        * with_curve.shell_mid_surface_radius_over_thickness,
        rel=1e-12,
    )
    selected = next(item for item in with_curve.candidates if item.applicable)
    assert with_curve.critical_buckling_coefficient == pytest.approx(
        selected.critical_buckling_coefficient * with_curve.plasticity_factor,
        rel=1e-12,
    )
    assert with_curve.ideal_critical_pressure_mpa == selected.ideal_critical_pressure_mpa
    secant, tangent = ramberg_osgood_moduli(
        with_curve.correlated_critical_circumferential_stress_mpa,
        **TITANIUM,
    )
    assert with_curve.secant_modulus_at_critical_stress_mpa == pytest.approx(secant)
    assert with_curve.tangent_modulus_at_critical_stress_mpa == pytest.approx(tangent)


def test_the_solved_root_satisfies_its_own_residual() -> None:
    for outside_diameter_in in (12.0, 16.0):
        geometry = _at_ratio(outside_diameter_in * 25.4, 10.05)
        result = _kernel(**geometry, ramberg_osgood_n=21.0,
                         compressive_proof_stress_mpa=827.0)
        selected = next(item for item in result.candidates if item.applicable)
        elastic = selected.correlated_critical_pressure_mpa
        assert elastic is not None
        root = result.correlated_critical_pressure_mpa
        assert root is not None
        eta, _ = smooth_cylinder_plasticity_factor(
            root * result.shell_mid_surface_radius_over_thickness,
            elastic_modulus_mpa=113800.0, ramberg_osgood_n=21.0,
            compressive_proof_stress_mpa=827.0, gamma_z=selected.gamma_z,
            more_than_two_wave_boundary=(
                SMOOTH_CYLINDER_MORE_THAN_TWO_WAVE_COEFFICIENT
                * result.geometry_mode_parameter**2
            ),
        )
        assert root == pytest.approx(elastic * eta, rel=1e-12)
        assert 0.0 < root <= elastic
        assert result.plasticity_factor == pytest.approx(root / elastic, rel=1e-12)


def test_the_correction_is_continuous_through_the_proportional_limit() -> None:
    """No step where the elastic-only path would have changed status."""
    diameter = 16.0 * 25.4
    previous = None
    for ratio in [10.05 + 0.01 * step for step in range(0, 60)]:
        result = _kernel(**_at_ratio(diameter, ratio), ramberg_osgood_n=21.0,
                         compressive_proof_stress_mpa=827.0)
        assert result.capacity_status == "released"
        pressure = result.correlated_critical_pressure_mpa
        assert pressure is not None
        if previous is not None:
            assert abs(pressure - previous) < 0.5
        previous = pressure


@pytest.mark.parametrize(
    "overrides",
    [
        {"ramberg_osgood_n": 21.0},
        {"compressive_proof_stress_mpa": 827.0},
    ],
)
def test_half_a_curve_is_rejected(overrides: dict[str, float]) -> None:
    with pytest.raises(ValueError, match="supplied together"):
        _kernel(**_at_ratio(304.8, 10.05), **overrides)


@pytest.mark.parametrize(
    ("overrides", "match"),
    [
        ({"ramberg_osgood_n": 1.0, "compressive_proof_stress_mpa": 827.0}, "> 1"),
        ({"ramberg_osgood_n": 0.5, "compressive_proof_stress_mpa": 827.0}, "> 1"),
        ({"ramberg_osgood_n": math.nan, "compressive_proof_stress_mpa": 827.0},
         "finite and positive"),
        ({"ramberg_osgood_n": 21.0, "compressive_proof_stress_mpa": 0.0},
         "finite and positive"),
        ({"ramberg_osgood_n": 21.0, "compressive_proof_stress_mpa": math.inf},
         "finite and positive"),
        ({"ramberg_osgood_n": True, "compressive_proof_stress_mpa": 827.0}, "numeric"),
    ],
)
def test_invalid_curve_inputs_are_rejected(
    overrides: dict[str, object], match: str,
) -> None:
    with pytest.raises(ValueError, match=match):
        _kernel(**_at_ratio(304.8, 10.05), **overrides)


def test_a_high_n_curve_survives_the_large_elastic_trial_stress() -> None:
    material = {
        "elastic_modulus_mpa": 68_900.0,
        "ramberg_osgood_n": 59.0,
        "compressive_proof_stress_mpa": 241.0,
    }
    trial_eta, _ = smooth_cylinder_plasticity_factor(
        10_000_000.0,
        gamma_z=200.0,
        more_than_two_wave_boundary=1000.0,
        **material,
    )
    assert math.isfinite(trial_eta) and 0.0 <= trial_eta < 1.0e-100

    elastic = 1_000_000.0
    ratio = 100.0
    root, _ = solve_inelastic_critical_pressure(
        elastic_critical_pressure_mpa=elastic,
        radius_over_thickness=ratio,
        gamma_z=200.0,
        more_than_two_wave_boundary=1000.0,
        **material,
    )
    eta, _ = smooth_cylinder_plasticity_factor(
        root * ratio,
        gamma_z=200.0,
        more_than_two_wave_boundary=1000.0,
        **material,
    )
    assert math.isfinite(root) and root > 0.0
    assert root == pytest.approx(elastic * eta, rel=1.0e-10)


def test_compressive_proof_stress_is_not_bounded_by_tensile_yield() -> None:
    result = _kernel(
        **_at_ratio(304.8, 10.05),
        yield_strength_mpa=500.0,
        ramberg_osgood_n=21.0,
        compressive_proof_stress_mpa=827.0,
    )
    assert result.capacity_status == "released"
    assert result.compressive_proof_stress_mpa == 827.0


def test_a_geometry_gate_still_withholds_a_corrected_capacity() -> None:
    result = _kernel(**_at_ratio(304.8, 8.0), ramberg_osgood_n=21.0,
                     compressive_proof_stress_mpa=827.0)
    assert result.capacity_status == "withheld_applicability"
    assert result.correlated_critical_pressure_mpa is None
    assert result.margin is None
    assert result.plasticity_factor is None
    assert result.secant_modulus_at_critical_stress_mpa is None
    assert result.tangent_modulus_at_critical_stress_mpa is None
    assert any("must be > 10" in item for item in result.validity_violations)


# --- integration -----------------------------------------------------------

HOUSING_GEOMETRY = {
    "external_pressure": {"value": 92.35134, "unit": "MPa"},
    "wall_thickness": {"value": 304.8 / 21.1, "unit": "mm"},
    "unsupported_length": {"value": 609.6, "unit": "mm"},
}
EXPLICIT_TITANIUM_CURVE = {
    "type": "explicit",
    "name": "Titanium with an explicit compressive curve",
    "properties": {
        "failure_category": "ductile_metal",
        "yield_strength": {"value": 827.0, "unit": "MPa"},
        "elastic_modulus": {"value": 113800.0, "unit": "MPa"},
        "poisson_ratio": 0.34,
        "ramberg_osgood_n": 21.0,
        "compressive_proof_stress": {"value": 827.0, "unit": "MPa"},
    },
}


def _smooth_request(material: dict) -> dict:
    wall = 304.8 / 21.1
    return {
        "schema_version": CALC_SCHEMA_VERSION, "model": "smooth-buckling",
        "material": material,
        "inputs": {**HOUSING_GEOMETRY, "load_case": "hydrostatic_closed_end",
                   "shell_mid_surface_radius": {"value": (304.8 - wall) / 2.0, "unit": "mm"}},
    }


def test_generic_titanium_returns_a_reference_estimate_until_curve_is_qualified() -> None:
    named = calculate(_smooth_request({"type": "named", "name": "Ti-6Al-4V"}))
    explicit = calculate(_smooth_request(EXPLICIT_TITANIUM_CURVE))
    named_result = named["result"]
    assert named_result["capacity_status"] == "released_unqualified_material"
    assert named_result["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        62.7161928406424, abs=5e-7
    )
    assert named_result["proportional_limit_mpa"]["value"] == 602.0
    assert named_result["margin"] is not None
    assert named_result["plasticity_factor"] == pytest.approx(0.984780, abs=1e-6)
    assert named_result["ramberg_osgood_n"] == 21.0
    assert named_result["buckling_data_qualification"] == "reference_only"
    assert assess_response(named)["status"] == "fail"
    assert named["material"]["data_qualification"]["buckling"]["status"] == (
        "reference_only"
    )
    assert "MIL-HDBK-5J" in named["material"]["property_sources"][
        "compressive_stress_strain"
    ]
    assert any(
        "reference-only" in reason
        for reason in named_result["release_gate_violations"]
    )
    elastic_candidate = next(
        candidate for candidate in named_result["candidates"] if candidate["applicable"]
    )
    assert elastic_candidate["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        63.685456731934785, abs=5e-7
    )

    explicit_result = explicit["result"]
    assert explicit_result["capacity_status"] == "released"
    assert explicit_result["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        62.7161928406424, abs=5e-7
    )
    assert explicit_result["margin"] is not None
    assert explicit_result["plasticity_factor"] == pytest.approx(0.984780, abs=1e-6)


def test_generic_aluminium_curve_stays_a_non_acceptance_reference_estimate() -> None:
    inputs = {
        "external_pressure": {"value": 20.0, "unit": "MPa"},
        "shell_mid_surface_radius": {"value": 100.5, "unit": "mm"},
        "wall_thickness": {"value": 10.0, "unit": "mm"},
        "unsupported_length": {"value": 700.0, "unit": "mm"},
        "load_case": "hydrostatic_closed_end",
    }
    named = calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "smooth-buckling",
        "material": {"type": "named", "name": "Al-6061-T6"},
        "inputs": inputs,
    })
    assert named["result"]["capacity_status"] == "released_unqualified_material"
    assert named["result"]["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        20.038967943932864, abs=5e-7
    )
    assert named["result"]["proportional_limit_mpa"]["value"] == 183.4
    assert named["result"]["buckling_data_qualification"] == "reference_only"
    assert assess_response(named)["status"] == "indeterminate"

    qualified = calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "smooth-buckling",
        "material": {
            "type": "explicit",
            "name": "Test 6061-T6 extrusion in qualified LT compression",
            "provenance": (
                "Test fixture scoped to a 6061-T6 extrusion and LT compression; "
                "not a generic alloy record."
            ),
            "properties": {
                "failure_category": "ductile_metal",
                "yield_strength": {"value": 241.0, "unit": "MPa"},
                "elastic_modulus": {"value": 68900.0, "unit": "MPa"},
                "poisson_ratio": 0.33,
                "ramberg_osgood_n": 28.0,
                "compressive_proof_stress": {"value": 241.0, "unit": "MPa"},
            },
        },
        "inputs": inputs,
    })
    assert qualified["result"]["capacity_status"] == "released"
    assert qualified["result"]["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        20.038967943932864, abs=5e-7
    )
    assert assess_response(qualified)["status"] == "pass"


def test_explicit_reference_only_curve_cannot_pass_acceptance() -> None:
    material = {
        **EXPLICIT_TITANIUM_CURVE,
        "buckling_data_qualification": "reference_only",
    }
    response = calculate(_smooth_request(material))
    assert response["result"]["capacity_status"] == "released_unqualified_material"
    assert response["result"]["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        62.7161928406424, abs=5e-7
    )
    assert assess_response(response)["status"] == "fail"


def test_illustrative_titanium_example_cannot_pass_with_a_positive_margin() -> None:
    example = Path(__file__).resolve().parents[1] / "examples" / "smooth_buckling_inelastic_titanium.json"
    request = json.loads(example.read_text(encoding="utf-8"))
    request["inputs"]["external_pressure"] = {"value": 60.0, "unit": "MPa"}
    response = calculate(request)
    assert response["result"]["margin"] > 0
    assert response["result"]["capacity_status"] == "released_unqualified_material"
    assert assess_response(response)["status"] == "indeterminate"


def test_reference_only_reason_survives_pending_plasticity_precedence() -> None:
    material = {
        "type": "explicit",
        "name": "Reference-only titanium proportional limit",
        "buckling_data_qualification": "reference_only",
        "properties": {
            "failure_category": "ductile_metal",
            "yield_strength": {"value": 827.0, "unit": "MPa"},
            "elastic_modulus": {"value": 113800.0, "unit": "MPa"},
            "poisson_ratio": 0.34,
            "proportional_limit": {"value": 602.0, "unit": "MPa"},
        },
    }
    response = calculate(_smooth_request(material))

    result = response["result"]
    assert result["capacity_status"] == "released_pending_plasticity"
    assert any(
        "reference-only" in reason
        for reason in result["release_gate_violations"]
    )
    check = assess_response(response)["checks"][0]
    assert check["status"] == "fail"
    assert any("reference-only" in reason for reason in check["reasons"])


def test_the_composed_cylinder_reports_the_corrected_buckling_capacity() -> None:
    wall = 304.8 / 21.1
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION, "model": "cylinder",
        "material": EXPLICIT_TITANIUM_CURVE,
        "inputs": {**HOUSING_GEOMETRY,
                   "internal_radius": {"value": 304.8 / 2.0 - wall, "unit": "mm"}},
    })
    buckling = response["components"]["smooth_buckling"]["result"]
    assert buckling["capacity_status"] == "released"
    check = next(item for item in response["assessment"]["checks"]
                 if item["id"] == "smooth_cylinder_buckling")
    assert check["capacity"]["value"] == pytest.approx(62.7161928406424, abs=5e-7)
    assert check["margin"] is not None
    assert check["status"] == "fail"


def test_the_cli_releases_the_same_corrected_capacity() -> None:
    import json as _json

    from typer.testing import CliRunner

    from pv_calc.cli import app

    wall = 304.8 / 21.1
    result = CliRunner().invoke(app, [
        "smooth-buckling",
        "--external-pressure", "92.35134 MPa",
        "--shell-mid-surface-radius", f"{(304.8 - wall) / 2.0} mm",
        "--wall-thickness", f"{wall} mm",
        "--unsupported-length", "609.6 mm",
        "--load-case", "hydrostatic_closed_end",
        "--failure-category", "ductile_metal",
        "--yield-strength", "827 MPa",
        "--elastic-modulus", "113800 MPa",
        "--poisson-ratio", "0.34",
        "--ramberg-osgood-n", "21",
        "--compressive-proof-stress", "827 MPa",
        "--json",
    ])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.stdout)
    assert payload["result"]["capacity_status"] == "released"
    assert payload["result"]["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        62.7161928406424, abs=5e-7
    )


def test_a_record_without_a_curve_keeps_the_elastic_only_behaviour() -> None:
    """SS-316-316L stores neither a curve nor a proportional limit."""
    response = calculate(_smooth_request({"type": "named", "name": "SS-316-316L"}))
    result = response["result"]
    assert result["capacity_status"] == "withheld_applicability"
    assert result["correlated_critical_pressure_mpa"]["value"] is None
    assert result["plasticity_factor"] is None
    assert result["ramberg_osgood_n"] is None


def test_inelastic_sizing_brackets_the_first_passing_wall() -> None:
    """Exercise sizing where the correction materially controls the root."""
    external_radius_mm = 254.0 / 2.0
    pressure = 40.0
    material = {
        "type": "explicit",
        "name": "compact inelastic sizing regression",
        "properties": {
            "failure_category": "ductile_metal",
            "yield_strength": {"value": 5_000.0, "unit": "MPa"},
            "elastic_modulus": {"value": 113_800.0, "unit": "MPa"},
            "poisson_ratio": 0.34,
            "ramberg_osgood_n": 5.0,
            "compressive_proof_stress": {"value": 500.0, "unit": "MPa"},
        },
    }
    request = {
        "schema_version": CALC_SCHEMA_VERSION, "model": "smooth-buckling",
        "operation": "size", "material": material,
        "inputs": {
            "external_pressure": {"value": pressure, "unit": "MPa"},
            "external_radius": {"value": external_radius_mm, "unit": "mm"},
            "unsupported_length": {"value": 200.0, "unit": "mm"},
            "minimum_margin": 0.0,
            "wall_thickness_bounds": {"lower": {"value": 1.0, "unit": "mm"},
                                      "upper": {"value": 11.0, "unit": "mm"}},
        },
    }
    response = calculate(request)
    selected = response["sizing"]["selected_wall_thickness"]["value"]

    def buckling(thickness_mm: float):
        return smooth_cylinder_external_pressure_buckling(
            external_pressure_mpa=pressure,
            shell_mid_surface_radius_mm=external_radius_mm - thickness_mm / 2.0,
            wall_thickness_mm=thickness_mm, unsupported_length_mm=200.0,
            elastic_modulus_mpa=113800.0, poisson_ratio=0.34,
            load_case="hydrostatic_closed_end", yield_strength_mpa=5_000.0,
            ramberg_osgood_n=5.0, compressive_proof_stress_mpa=500.0,
        )

    below, at, above = (
        buckling(selected - 1.0e-4),
        buckling(selected),
        buckling(selected + 1.0e-4),
    )
    assert 8.0 < selected < 10.0
    assert below.margin is not None and below.margin < 0.0
    assert at.margin is not None and at.margin >= 0.0
    assert above.margin is not None and above.margin > 0.0
    assert at.plasticity_factor is not None and at.plasticity_factor < 0.55
    assert (
        below.correlated_critical_pressure_mpa
        < at.correlated_critical_pressure_mpa
        < above.correlated_critical_pressure_mpa
    )
    assert below.plasticity_factor > at.plasticity_factor > above.plasticity_factor


def test_ring_shell_curve_corrects_its_bay_and_leaves_global_modes_unchanged() -> None:
    base_properties = {
        "failure_category": "ductile_metal",
        "yield_strength": {"value": 827.0, "unit": "MPa"},
        "elastic_modulus": {"value": 113800.0, "unit": "MPa"},
        "poisson_ratio": 0.34,
        "proportional_limit": {"value": 602.0, "unit": "MPa"},
    }
    curve = {"ramberg_osgood_n": 21.0,
             "compressive_proof_stress": {"value": 827.0, "unit": "MPa"}}

    def ring_shell(properties: dict) -> dict:
        return calculate({
            "schema_version": CALC_SCHEMA_VERSION, "model": "ring-shell",
            "material": {"type": "explicit", "name": "x", "properties": properties},
            "inputs": {"external_pressure": {"value": 5.0, "unit": "MPa"},
                       "shell_mid_surface_radius": {"value": 100.0, "unit": "mm"},
                       "wall_thickness": {"value": 4.0, "unit": "mm"},
                       "unsupported_length": {"value": 600.0, "unit": "mm"},
                       "ring_spacing": {"value": 100.0, "unit": "mm"},
                       "ring_axial_width": {"value": 6.0, "unit": "mm"},
                       "ring_radial_height": {"value": 10.0, "unit": "mm"},
                       "ring_location": "internal"},
        })["result"]

    without = ring_shell(base_properties)
    with_curve = ring_shell({**base_properties, **curve})
    bay = calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "smooth-buckling",
        "material": {
            "type": "explicit",
            "name": "x",
            "properties": {**base_properties, **curve},
        },
        "inputs": {
            "external_pressure": {"value": 5.0, "unit": "MPa"},
            "shell_mid_surface_radius": {"value": 100.0, "unit": "mm"},
            "wall_thickness": {"value": 4.0, "unit": "mm"},
            "unsupported_length": {"value": 100.0, "unit": "mm"},
            "load_case": "hydrostatic_closed_end",
        },
    })["result"]

    assert with_curve["inter_ring_shell_buckling"] == bay
    assert without["inter_ring_shell_buckling"]["capacity_status"] == (
        "released_pending_plasticity"
    )
    assert bay["capacity_status"] == "released"
    assert (
        bay["correlated_critical_pressure_mpa"]["value"]
        < without["inter_ring_shell_buckling"]["correlated_critical_pressure_mpa"]["value"]
    )
    for key in ("global_without_ring_torsion", "global_with_ring_torsion"):
        assert with_curve[key] == without[key]
    assert with_curve["advisory_governing_mode"] == without["advisory_governing_mode"]
    assert with_curve["advisory_governing_pressure_mpa"] == (
        without["advisory_governing_pressure_mpa"]
    )


def test_the_correction_is_not_a_strength_limit() -> None:
    """A short thick shell can still correct to a stress above the material's.

    NASA Eqs. 30-32 reduce an elastic instability pressure through the secant
    and tangent moduli. They impose no squash load, so a corrected critical
    stress above the material strength is a signal that instability is not the
    governing mode, not a defect in the correction. The shell stress check is
    what catches that, and the composed cylinder runs both.
    """
    result = _kernel(
        external_pressure_mpa=1.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=8.0,
        unsupported_length_mm=20.0,
        ramberg_osgood_n=21.0,
        compressive_proof_stress_mpa=827.0,
    )
    elastic = next(item for item in result.candidates if item.applicable)
    assert elastic.correlated_critical_circumferential_stress_mpa > 30_000.0
    corrected = result.correlated_critical_circumferential_stress_mpa
    assert corrected is not None
    # Reduced by more than an order of magnitude, and still above the anchor.
    assert corrected < 0.05 * elastic.correlated_critical_circumferential_stress_mpa
    assert corrected > 827.0
    assert result.capacity_status == "released"


@pytest.mark.parametrize(
    ("unsupported_length_mm", "equation"),
    [
        (20.0, "NASA Eq. 30"),
        (150.0, "NASA Eqs. 30-31 interpolated in Z"),
        (600.0, "NASA Eq. 31"),
        (3000.0, "NASA Eq. 32"),
    ],
)
def test_each_elastic_regime_selects_the_matching_plasticity_equation(
    unsupported_length_mm: float, equation: str,
) -> None:
    """The gamma*Z domains of Eqs. 30-32 must line up with the elastic branches.

    Eq. 32 belongs above 11.8*(r/t)^2*(1-v^2), which is exactly where the long
    branch takes over and gamma changes from 0.5625 to 0.90, so the two domain
    partitions have to agree for the correction to be read at the right gamma.
    """
    result = _kernel(
        external_pressure_mpa=1.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=8.0,
        unsupported_length_mm=unsupported_length_mm,
        ramberg_osgood_n=21.0,
        compressive_proof_stress_mpa=827.0,
    )
    assert result.capacity_status == "released"
    assert equation in result.source_equations
    if equation == "NASA Eq. 32":
        assert result.regime == "long"
    else:
        assert result.regime in {"short", "moderate"}


@pytest.mark.parametrize("command", ["smooth-buckling", "cylinder"])
def test_the_cli_accepts_an_explicit_compressive_curve(command: str) -> None:
    import json as _json

    from typer.testing import CliRunner

    from pv_calc.cli import app

    wall = 304.8 / 21.1
    radius = (
        ["--internal-radius", f"{304.8 / 2.0 - wall} mm"]
        if command == "cylinder"
        else ["--shell-mid-surface-radius", f"{(304.8 - wall) / 2.0} mm",
              "--load-case", "hydrostatic_closed_end"]
    )
    material = [
        "--failure-category", "ductile_metal", "--yield-strength", "827 MPa",
        "--elastic-modulus", "113800 MPa", "--poisson-ratio", "0.34",
    ]
    geometry = [
        "--external-pressure", "92.35134 MPa", "--wall-thickness", f"{wall} mm",
        "--unsupported-length", "609.6 mm", *radius, *material,
    ]
    runner = CliRunner()
    with_curve = runner.invoke(app, [
        command, *geometry, "--ramberg-osgood-n", "21",
        "--compressive-proof-stress", "827 MPa", "--json",
    ])
    assert with_curve.exit_code == 0, with_curve.output
    payload = _json.loads(with_curve.stdout)
    result = (
        payload["components"]["smooth_buckling"]["result"]
        if command == "cylinder" else payload["result"]
    )
    assert result["capacity_status"] == "released"
    assert result["correlated_critical_pressure_mpa"]["value"] == pytest.approx(
        62.7161928406424, abs=5e-7
    )

    # Half a curve is a request error, not a silently ignored option.
    half = runner.invoke(app, [command, *geometry, "--ramberg-osgood-n", "21", "--json"])
    error = _error_payload(half)["error"]
    assert error["code"] == "invalid_request"
    assert "must be given together" in error["message"]
