"""An elastic formula value beyond a known material limit is not a service result."""

import pytest

from pv_calc.pressure_vessel import (
    closed_end_tube_stress,
    flat_circular_plate,
    hemispherical_head_external_pressure,
    smooth_cylinder_external_pressure_buckling,
)


def test_pending_buckling_estimate_has_no_usable_margin():
    result = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=30.0,
        shell_mid_surface_radius_mm=105.0,
        wall_thickness_mm=10.0,
        unsupported_length_mm=300.0,
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        yield_strength_mpa=241.0,
        proportional_limit_mpa=183.4,
        load_case="hydrostatic_closed_end",
    )
    assert result.capacity_status == "released_pending_plasticity"
    assert result.elastic_applicability == "exceeded"
    assert result.correlated_critical_pressure_mpa == pytest.approx(52.06001596)
    assert result.margin is None
    assert any("elastic upper bound" in note for note in result.notes)


@pytest.mark.parametrize("model", ["tube", "hemisphere", "plate"])
def test_material_failure_labels_retained_elastic_deformation(model):
    common = dict(
        external_pressure_mpa=1.0,
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        strength_mpa=241.0,
        material_failure_category="ductile_metal",
    )
    if model == "tube":
        common["external_pressure_mpa"] = 26.0
        result = closed_end_tube_stress(
            **common, internal_radius_mm=100.0, wall_thickness_mm=10.0
        )
    elif model == "hemisphere":
        common["external_pressure_mpa"] = 43.0
        result = hemispherical_head_external_pressure(
            **common, internal_radius_mm=100.0, wall_thickness_mm=10.0
        )
    else:
        result = flat_circular_plate(
            **common, free_radius_mm=100.0, plate_thickness_mm=5.0,
            boundary_condition="fixed",
        )
        assert result.margin < 0.0
        assert result.deflection_status == "elastic_estimate_material_limit"
        assert result.maximum_deflection_mm > 0.0
        assert result.released_maximum_deflection_mm is None
        assert any("material strength" in reason for reason in result.deflection_validity_violations)
        return

    assert result.governing_stress_mpa > result.strength_mpa
    assert result.displacement_status == "elastic_estimate_material_limit"
    assert all(state.radial_displacement_mm < 0.0 for state in result.stress_states)
    assert any("material strength" in reason for reason in result.displacement_validity_violations)


def test_plate_deformation_at_material_limit_stays_released():
    result = flat_circular_plate(
        external_pressure_mpa=1.0,
        free_radius_mm=100.0,
        plate_thickness_mm=5.0,
        elastic_modulus_mpa=68_900.0,
        poisson_ratio=0.33,
        strength_mpa=300.0,
        material_failure_category="ductile_metal",
        boundary_condition="fixed",
    )
    assert result.margin == 0.0
    assert result.deflection_status == "released"
    assert result.released_maximum_deflection_mm == result.maximum_deflection_mm
