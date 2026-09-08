"""Physical regressions for the exact tube and spherical stress paths."""

from __future__ import annotations

import math

import pytest

from pv_calc.pressure_vessel import (
    closed_end_tube_stress,
    hemispherical_head_external_pressure,
)


def test_default_tube_detects_yield_missed_by_the_former_membrane_approximation() -> None:
    result = closed_end_tube_stress(
        external_pressure_mpa=26.0,
        internal_radius_mm=100.0,
        wall_thickness_mm=10.0,
        material_failure_category="ductile_metal",
        strength_mpa=241.0,
    )

    assert result.governing_radius_mm == 100.0
    assert result.governing_stress_mpa == pytest.approx(259.4777067)
    assert result.margin == pytest.approx(-0.07121119999)


def test_default_hemisphere_detects_yield_missed_by_the_former_membrane_approximation() -> None:
    result = hemispherical_head_external_pressure(
        external_pressure_mpa=43.0,
        internal_radius_mm=100.0,
        wall_thickness_mm=10.0,
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        material_failure_category="ductile_metal",
        strength_mpa=241.0,
    )

    assert result.governing_radius_mm == 100.0
    assert result.governing_stress_mpa == pytest.approx(259.3640483)
    assert result.stress_margin == pytest.approx(-0.07080413462)


@pytest.mark.parametrize("radius_ratio", [2.0, 10.0, 10.5, 40.0, 1000.0])
def test_tube_stresses_balance_surface_traction_and_closed_end_pressure(
    radius_ratio: float,
) -> None:
    pressure = 1.0
    thickness = 2.0
    inner_radius = (radius_ratio - 0.5) * thickness
    outer_radius = inner_radius + thickness
    result = closed_end_tube_stress(
        external_pressure_mpa=pressure,
        internal_radius_mm=inner_radius,
        wall_thickness_mm=thickness,
        material_failure_category="ductile_metal",
        strength_mpa=2000.0,
    )
    inner, outer = result.stress_states

    assert inner.radial_stress_mpa == pytest.approx(0.0, abs=1.0e-10)
    assert outer.radial_stress_mpa == pytest.approx(-pressure, abs=1.0e-10)
    # The wall's axial force balances pressure over the entire end-cap disk.
    wall_area = math.pi * (outer_radius**2 - inner_radius**2)
    assert inner.axial_stress_mpa == outer.axial_stress_mpa
    assert inner.axial_stress_mpa * wall_area == pytest.approx(
        -pressure * math.pi * outer_radius**2
    )
    # Integrate the Lamé hoop field, recovered from its two reported surface
    # values, across a diametral cut. Each wall must carry p*b per unit length.
    inverse_square_difference = 1.0 / inner_radius**2 - 1.0 / outer_radius**2
    hoop_b = (inner.hoop_stress_mpa - outer.hoop_stress_mpa) / inverse_square_difference
    hoop_a = inner.hoop_stress_mpa - hoop_b / inner_radius**2
    cut_force = hoop_a * thickness + hoop_b * (1.0 / inner_radius - 1.0 / outer_radius)
    assert cut_force == pytest.approx(-pressure * outer_radius, rel=1.0e-10)


@pytest.mark.parametrize("radius_ratio", [2.0, 10.0, 10.5, 40.0, 1000.0])
def test_hemisphere_stresses_balance_surface_traction_and_equatorial_force(
    radius_ratio: float,
) -> None:
    pressure = 1.0
    thickness = 2.0
    inner_radius = (radius_ratio - 0.5) * thickness
    outer_radius = inner_radius + thickness
    result = hemispherical_head_external_pressure(
        external_pressure_mpa=pressure,
        internal_radius_mm=inner_radius,
        wall_thickness_mm=thickness,
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        material_failure_category="ductile_metal",
        strength_mpa=2000.0,
    )
    inner, outer = result.stress_states

    assert inner.radial_stress_mpa == pytest.approx(0.0, abs=1.0e-10)
    assert outer.radial_stress_mpa == pytest.approx(-pressure, abs=1.0e-10)
    assert inner.meridional_stress_mpa == inner.hoop_stress_mpa
    assert outer.meridional_stress_mpa == outer.hoop_stress_mpa
    # Recover sigma_theta = A + C/r^3 from the reported surfaces, then
    # integrate 2*pi*r*sigma_theta over the equatorial annulus. The force
    # balances the pressure projected onto the external-radius disk.
    inverse_cube_difference = 1.0 / inner_radius**3 - 1.0 / outer_radius**3
    hoop_c = (inner.hoop_stress_mpa - outer.hoop_stress_mpa) / inverse_cube_difference
    hoop_a = inner.hoop_stress_mpa - hoop_c / inner_radius**3
    equator_force = math.pi * hoop_a * (outer_radius**2 - inner_radius**2) + (
        2.0 * math.pi * hoop_c * (1.0 / inner_radius - 1.0 / outer_radius)
    )
    assert equator_force == pytest.approx(-pressure * math.pi * outer_radius**2, rel=1.0e-10)


@pytest.mark.parametrize("poisson", [0.05, 0.33, 0.499])
@pytest.mark.parametrize("radius_ratio", [2.0, 40.0])
def test_spherical_displacement_radial_derivative_recovers_pressure_tractions(
    poisson: float,
    radius_ratio: float,
) -> None:
    pressure = 1.0
    modulus = 68_900.0
    inner_radius = radius_ratio - 0.5
    outer_radius = inner_radius + 1.0
    result = hemispherical_head_external_pressure(
        external_pressure_mpa=pressure,
        internal_radius_mm=inner_radius,
        wall_thickness_mm=1.0,
        elastic_modulus_mpa=modulus,
        poisson_ratio=poisson,
        material_failure_category="ductile_metal",
        strength_mpa=276.0,
    )
    inner, outer = result.stress_states
    assert inner.radial_displacement_mm is not None
    assert outer.radial_displacement_mm is not None
    # Any spherically symmetric elastic solution has u = c1*r + c2/r^2.
    # Recover those constants from displacement alone, differentiate it,
    # and apply 3D elasticity to check the independent radial stress component.
    c2 = (inner.radial_displacement_mm / inner_radius - outer.radial_displacement_mm / outer_radius) / (
        1.0 / inner_radius**3 - 1.0 / outer_radius**3
    )
    c1 = inner.radial_displacement_mm / inner_radius - c2 / inner_radius**3
    shear_modulus = modulus / (2.0 * (1.0 + poisson))
    lame_lambda = modulus * poisson / ((1.0 + poisson) * (1.0 - 2.0 * poisson))
    for radius, traction in ((inner_radius, 0.0), (outer_radius, -pressure)):
        radial_strain = c1 - 2.0 * c2 / radius**3
        volume_strain = 3.0 * c1
        radial_stress = 2.0 * shear_modulus * radial_strain + lame_lambda * volume_strain
        assert radial_stress == pytest.approx(traction, abs=1.0e-9)


def test_hemisphere_stress_and_displacement_are_continuous_at_former_stress_switch() -> None:
    results = [
        hemispherical_head_external_pressure(
            external_pressure_mpa=1.0,
            internal_radius_mm=radius,
            wall_thickness_mm=1.0,
            elastic_modulus_mpa=68_900.0,
            poisson_ratio=0.33,
            material_failure_category="ductile_metal",
            strength_mpa=276.0,
        )
        for radius in (9.5 - 1.0e-8, 9.5, 9.5 + 1.0e-8)
    ]
    for result in results:
        assert result.branch == "thick"
        assert result.governing_stress_mpa == pytest.approx(
            results[1].governing_stress_mpa, rel=2.0e-9
        )
        for state, middle_state in zip(result.stress_states, results[1].stress_states, strict=True):
            assert state.radial_displacement_mm == pytest.approx(
                middle_state.radial_displacement_mm, rel=3.0e-9
            )


@pytest.mark.parametrize("radius_ratio", [20.0, 100.0, 10_000.0])
def test_exact_spherical_stress_and_displacement_approach_the_membrane_limit(
    radius_ratio: float,
) -> None:
    # Keeping p*R/t fixed keeps the elastic demand fixed in this limit.
    pressure = 1.0 / radius_ratio
    poisson = 0.33
    modulus = 68_900.0
    result = hemispherical_head_external_pressure(
        external_pressure_mpa=pressure,
        internal_radius_mm=radius_ratio - 0.5,
        wall_thickness_mm=1.0,
        elastic_modulus_mpa=modulus,
        poisson_ratio=poisson,
        material_failure_category="ductile_metal",
        strength_mpa=276.0,
    )
    membrane_stress = pressure * radius_ratio / 2.0
    membrane_displacement = -pressure * radius_ratio**2 * (1.0 - poisson) / (2.0 * modulus)
    assert abs(result.governing_stress_mpa / membrane_stress - 1.0) < 2.0 / radius_ratio
    for state in result.stress_states:
        assert abs(state.radial_displacement_mm / membrane_displacement - 1.0) < 1.5 / radius_ratio
