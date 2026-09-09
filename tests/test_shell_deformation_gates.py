"""Shell deformation screens preserve formula values without releasing them."""

import json

import pytest

from pv_calc.cli import app
from pv_calc.pressure_vessel import (
    closed_end_tube_stress,
    hemispherical_head_external_pressure,
)

from _cli_helpers import MATERIALS_FILE, runner


MODELS = [closed_end_tube_stress, hemispherical_head_external_pressure]


@pytest.mark.parametrize(
    ("model", "radius", "pressure", "expected_displacement"),
    [("tube", 500, 0.01414, -1.060597185809115),
     ("hemisphere", 1000, 0.009, -1.06267293293159)],
)
def test_named_acrylic_displacement_exceeding_wall_is_not_released(
    model, radius, pressure, expected_displacement,
):
    response = runner.invoke(
        app,
        [model, "--internal-radius", f"{radius} mm", "--wall-thickness", "1 mm",
         "--external-pressure", f"{pressure} MPa", "--material", "Acrylic-PMMA",
         "--materials-file", str(MATERIALS_FILE), "--json"],
    )
    assert response.exit_code == 0, response.output
    result = json.loads(response.stdout)["result"]
    assert result["governing_stress_mpa"]["value"] < result["strength_mpa"]["value"]
    assert result["stress_states"][0]["radial_displacement_mm"]["value"] == pytest.approx(
        expected_displacement,
    )
    assert result["maximum_radial_displacement_over_thickness"] == pytest.approx(
        abs(expected_displacement),
    )
    assert result["maximum_absolute_strain"] < 0.01
    assert result["displacement_status"] == "withheld_applicability"
    assert any("wall thickness" in reason for reason in result["displacement_validity_violations"])


@pytest.mark.parametrize("model", MODELS, ids=["tube", "hemisphere"])
@pytest.mark.parametrize("screen", ["displacement", "strain"])
def test_shell_deformation_screens_include_equality_and_exclude_just_above(model, screen):
    # Binary-exact Poisson ratio and integer Lamé constants make the selected
    # boundary exactly representable, so this checks > rather than rounding.
    tube = model is closed_end_tube_stress
    if screen == "displacement":
        radius = 128.0
        pressure = 257.0 if tube else 129.0**3 - 128.0**3
        modulus = 224.0 * 129.0**2 if tube else 144.0 * 129.0**3
        diagnostic = "maximum_radial_displacement_over_thickness"
        threshold = 1.0
        reason_text = "wall thickness"
    else:
        radius = 1.0
        pressure = 3.0 if tube else 7.0
        modulus = 700.0 if tube else 900.0
        diagnostic = "maximum_absolute_strain"
        threshold = 0.01
        reason_text = "0.01"

    inputs = dict(
        internal_radius_mm=radius, wall_thickness_mm=1.0,
        elastic_modulus_mpa=modulus, poisson_ratio=0.25,
        strength_mpa=1.0e12, material_failure_category="ductile_metal",
    )
    boundary = model(**inputs, external_pressure_mpa=pressure)
    assert getattr(boundary, diagnostic) == threshold
    assert boundary.displacement_status == "released"
    assert boundary.displacement_validity_violations == ()

    below = model(**inputs, external_pressure_mpa=pressure * (1.0 - 1.0e-8))
    assert below.displacement_status == "released"
    for force_thick in (False, True):
        above = model(
            **inputs, external_pressure_mpa=pressure * (1.0 + 1.0e-8),
            force_thick=force_thick,
        )
        assert above.displacement_status == "withheld_applicability"
        assert any(reason_text in reason for reason in above.displacement_validity_violations)
        assert all(state.radial_displacement_mm < 0.0 for state in above.stress_states)
        if screen == "strain":
            assert above.maximum_radial_displacement_over_thickness < 1.0
        else:
            assert above.maximum_absolute_strain < 0.01


@pytest.mark.parametrize("model", MODELS, ids=["tube", "hemisphere"])
def test_shell_deformation_diagnostics_recover_all_three_principal_strains(model):
    modulus, poisson = 100.0, 0.49
    tube = model is closed_end_tube_stress
    result = model(
        external_pressure_mpa=1.0, internal_radius_mm=1.0, wall_thickness_mm=1.0,
        elastic_modulus_mpa=modulus, poisson_ratio=poisson,
        strength_mpa=0.1, material_failure_category="ductile_metal",
        **({"axial_length_mm": 10.0} if tube else {}),
    )
    # Stresses are principal in spherical/cylindrical coordinates, so 3D
    # Hooke's law needs no rotation or eigenvalue solver. For the sphere, near
    # incompressibility makes radial strain govern; u/r alone misses the gate.
    strains = [
        (principal - poisson * (sum(state.principal_stresses_mpa) - principal)) / modulus
        for state in result.stress_states
        for principal in state.principal_stresses_mpa
    ]
    assert result.maximum_absolute_strain == pytest.approx(max(abs(value) for value in strains))
    if not tube:
        assert result.maximum_absolute_strain > 0.01 > max(
            abs(state.radial_displacement_mm / state.radius_mm) for state in result.stress_states
        )
    assert result.maximum_radial_displacement_over_thickness == pytest.approx(
        max(abs(state.radial_displacement_mm) for state in result.stress_states)
        / result.wall_thickness_mm,
    )
    assert result.displacement_status == "withheld_applicability"
    assert any("0.01" in reason for reason in result.displacement_validity_violations)
    assert any("material strength" in reason for reason in result.displacement_validity_violations)
    margin = result.margin if tube else result.stress_margin
    assert margin < 0.0
    if tube:
        assert result.axial_strain is not None
        assert result.axial_length_change_mm == pytest.approx(10.0 * result.axial_strain)


@pytest.mark.parametrize(
    "elastic_properties", [{}, {"elastic_modulus_mpa": 2758.0}, {"poisson_ratio": 0.35}],
)
def test_tube_missing_elastic_properties_has_no_deformation_diagnostics(elastic_properties):
    result = closed_end_tube_stress(
        external_pressure_mpa=0.01414, internal_radius_mm=500.0, wall_thickness_mm=1.0,
        strength_mpa=10.3, material_failure_category="plastic", **elastic_properties,
    )
    assert result.displacement_status == "withheld_missing_elastic_properties"
    assert result.maximum_radial_displacement_over_thickness is None
    assert result.maximum_absolute_strain is None
    assert all(state.radial_displacement_mm is None for state in result.stress_states)
