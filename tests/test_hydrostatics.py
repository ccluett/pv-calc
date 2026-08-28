from __future__ import annotations

import math

import pytest

from pv_calc.hydrostatics import (
    HYDROSTATIC_PRESSURE_MODEL_ID,
    HYDROSTATIC_PRESSURE_MODEL_VERSION,
    SUBMERGED_MASS_MODEL_ID,
    SUBMERGED_MASS_MODEL_VERSION,
    external_pressure_from_depth,
    submerged_mass_and_buoyancy,
)


# Depth, density, gravity, and factor chosen so rho*g*h is exactly 1 MPa and every
# scaled expectation below is representable.
def _pressure(
    *,
    depth_m: float = 100.0,
    fluid_density_kg_per_m3: float = 1000.0,
    gravity_m_per_s2: float = 10.0,
    design_factor: float = 1.5,
):
    return external_pressure_from_depth(
        depth_m=depth_m,
        fluid_density_kg_per_m3=fluid_density_kg_per_m3,
        gravity_m_per_s2=gravity_m_per_s2,
        design_factor=design_factor,
    )


def test_service_pressure_is_the_density_gravity_depth_product():
    # Lautrup Eq. (4-3): p - p0 = rho0*g0*h, the pressure rise from the surface
    # down to depth h. 1000 kg/m3 * 10 m/s2 * 100 m = 1 MPa.
    result = _pressure()

    assert result.service_external_pressure_mpa == 1.0
    assert result.design_external_pressure_mpa == 1.5


@pytest.mark.parametrize(
    "field",
    ["depth_m", "fluid_density_kg_per_m3", "gravity_m_per_s2", "design_factor"],
)
def test_pressure_is_linear_in_each_input(field: str):
    # Doubling by a power of two is exact in binary floating point, so linearity
    # in depth, density, gravity, and factor is asserted without a tolerance.
    baseline = _pressure()
    doubled = _pressure(**{field: getattr(baseline, field) * 2.0})

    assert doubled.design_external_pressure_mpa == 2.0 * baseline.design_external_pressure_mpa
    if field == "design_factor":
        assert doubled.service_external_pressure_mpa == baseline.service_external_pressure_mpa
    else:
        assert (
            doubled.service_external_pressure_mpa
            == 2.0 * baseline.service_external_pressure_mpa
        )


def test_zero_depth_has_no_differential_pressure():
    # At the surface, h = 0 in Eq. (4-3), so interior and exterior sit at the same
    # reference and the differential across the wall vanishes at any design factor.
    result = _pressure(depth_m=0.0, design_factor=3.0)

    assert result.service_external_pressure_mpa == 0.0
    assert result.design_external_pressure_mpa == 0.0


def test_unit_design_factor_leaves_the_service_pressure_unscaled():
    result = _pressure(design_factor=1.0)

    assert result.design_external_pressure_mpa == result.service_external_pressure_mpa == 1.0


@pytest.mark.parametrize(
    "depth_m, design_factor",
    [
        (0.0, 1.5),
        (0.1, 1.0),
        (100.0, 1.25),
        (500.0, 1.5),
        (1500.0, 1.5),
        (3000.0, 1.5),
        (6000.0, 1.75),
        (11000.0, 3.0),
    ],
)
def test_design_pressure_matches_the_literal_left_to_right_expression(
    depth_m: float, design_factor: float
):
    # The parent repository computed this product inline with these two constants
    # before the kernel existed; committed evidence and design fixtures pin the
    # doubles it produced, so the match is bit-for-bit.
    result = external_pressure_from_depth(
        depth_m=depth_m,
        fluid_density_kg_per_m3=1025.0,
        gravity_m_per_s2=9.81,
        design_factor=design_factor,
    )

    assert result.design_external_pressure_mpa == (
        1025.0 * 9.81 * depth_m * design_factor / 1_000_000.0
    )
    assert result.service_external_pressure_mpa == 1025.0 * 9.81 * depth_m / 1_000_000.0


def test_design_pressure_is_not_the_service_pressure_scaled_afterwards():
    # Floating-point multiplication is not associative. At 100 m and a 1.25 factor
    # the single product ends ...0625 while scaling the depth pressure afterwards
    # ends ...06250000000001, so the evaluation order is part of the contract.
    result = external_pressure_from_depth(
        depth_m=100.0,
        fluid_density_kg_per_m3=1025.0,
        gravity_m_per_s2=9.81,
        design_factor=1.25,
    )

    assert result.design_external_pressure_mpa == 1.25690625
    assert result.design_external_pressure_mpa != result.service_external_pressure_mpa * 1.25


def test_pressure_result_carries_its_model_identity_and_convention():
    result = _pressure()

    assert result.model_id == HYDROSTATIC_PRESSURE_MODEL_ID
    assert result.model_version == HYDROSTATIC_PRESSURE_MODEL_VERSION
    assert "Eq. (4-3)" in result.source_reference
    assert (
        result.pressure_reference_convention
        == "differential_across_wall_interior_at_zero_gauge"
    )
    assert result.depth_m == 100.0
    assert result.fluid_density_kg_per_m3 == 1000.0
    assert result.gravity_m_per_s2 == 10.0
    assert result.design_factor == 1.5
    assert any("interior held" in note for note in result.notes)
    assert any("depth-varying density profiles" in note for note in result.notes)


@pytest.mark.parametrize("value", [-1.0, math.inf, math.nan, True, None])
def test_rejects_nonphysical_depth(value: object):
    expected = (
        "must be numeric"
        if value is None or isinstance(value, bool)
        else "must be finite and non-negative"
    )
    with pytest.raises(ValueError, match=f"depth_m {expected}"):
        _pressure(depth_m=value)


@pytest.mark.parametrize(
    "field", ["fluid_density_kg_per_m3", "gravity_m_per_s2", "design_factor"]
)
@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan, True, None])
def test_rejects_nonpositive_pressure_inputs(field: str, value: object):
    expected = (
        "must be numeric"
        if value is None or isinstance(value, bool)
        else "must be finite and positive"
    )
    with pytest.raises(ValueError, match=f"{field} {expected}"):
        _pressure(**{field: value})


# Exact binary volumes, densities, and gravity, so every expected value below is
# representable and can be asserted with ``==`` rather than a tolerance.
def _result(*, solid_volume_m3: float, material_density_kg_per_m3: float):
    return submerged_mass_and_buoyancy(
        solid_volume_m3=solid_volume_m3,
        displaced_volume_m3=1.5,
        material_density_kg_per_m3=material_density_kg_per_m3,
        fluid_density_kg_per_m3=1000.0,
        gravity_m_per_s2=10.0,
    )


def test_body_heavier_than_the_fluid_has_positive_net_submerged_mass():
    # Archimedes Book I Prop. 7: weighed in the fluid, the solid is lighter than
    # its true weight by the weight of the fluid displaced.
    result = _result(solid_volume_m3=0.25, material_density_kg_per_m3=8000.0)

    assert result.structural_air_mass_kg == 2000.0
    assert result.displaced_fluid_mass_kg == 1500.0
    assert result.net_submerged_mass_kg == 500.0
    assert result.buoyant_force_n == 15000.0


def test_matched_masses_are_exactly_neutrally_buoyant():
    # Lautrup Eq. (5-8): a body hovers when its mass equals the displaced mass.
    result = submerged_mass_and_buoyancy(
        solid_volume_m3=0.5,
        displaced_volume_m3=2.0,
        material_density_kg_per_m3=2000.0,
        fluid_density_kg_per_m3=500.0,
        gravity_m_per_s2=10.0,
    )

    assert result.structural_air_mass_kg == result.displaced_fluid_mass_kg == 1000.0
    assert result.net_submerged_mass_kg == 0.0
    assert result.buoyant_force_n == 10000.0


def test_body_lighter_than_the_fluid_has_negative_net_submerged_mass():
    # Archimedes Book I Prop. 6: held under, the lighter solid is driven upwards
    # by the difference between its weight and the weight of the fluid displaced.
    result = _result(solid_volume_m3=0.25, material_density_kg_per_m3=1000.0)

    assert result.structural_air_mass_kg == 250.0
    assert result.displaced_fluid_mass_kg == 1500.0
    assert result.net_submerged_mass_kg == -1250.0
    assert result.buoyant_force_n == 15000.0


def test_apparent_weight_equals_structural_weight_minus_buoyancy():
    # Lautrup Eq. (5-7) resolved into masses: (M_body - M_fluid) * g.
    result = submerged_mass_and_buoyancy(
        solid_volume_m3=2.964230898738728e-3,
        displaced_volume_m3=5.625159876329283e-3,
        material_density_kg_per_m3=2700.0,
        fluid_density_kg_per_m3=1025.0,
        gravity_m_per_s2=9.81,
    )

    structural_weight_n = result.structural_air_mass_kg * result.gravity_m_per_s2
    assert result.net_submerged_mass_kg * result.gravity_m_per_s2 == pytest.approx(
        structural_weight_n - result.buoyant_force_n,
        rel=1e-15,
    )
    assert result.buoyant_force_n == pytest.approx(
        1025.0 * 5.625159876329283e-3 * 9.81,
        rel=1e-15,
    )


def test_result_carries_its_model_identity_and_conventions():
    result = _result(solid_volume_m3=0.25, material_density_kg_per_m3=8000.0)

    assert result.model_id == SUBMERGED_MASS_MODEL_ID
    assert result.model_version == SUBMERGED_MASS_MODEL_VERSION
    assert "On Floating Bodies" in result.source_reference
    assert result.submergence_condition == "fully_submerged_rigid_non_flooded"
    assert result.net_mass_sign_convention == "positive_heavier_than_displaced_fluid"
    assert result.buoyant_force_direction == "opposes_gravity"
    assert result.solid_volume_m3 == 0.25
    assert result.displaced_volume_m3 == 1.5
    assert result.material_density_kg_per_m3 == 8000.0
    assert result.fluid_density_kg_per_m3 == 1000.0
    assert result.gravity_m_per_s2 == 10.0
    assert any("negative is buoyant" in note for note in result.notes)


def test_closed_body_rejects_solid_volume_above_displaced_volume():
    with pytest.raises(
        ValueError,
        match="solid_volume_m3 must not exceed displaced_volume_m3",
    ):
        submerged_mass_and_buoyancy(
            solid_volume_m3=2.0,
            displaced_volume_m3=1.0,
            material_density_kg_per_m3=1000.0,
            fluid_density_kg_per_m3=1000.0,
            gravity_m_per_s2=10.0,
        )


def test_closed_body_accepts_one_bit_unit_conversion_rounding_at_equal_volume():
    result = submerged_mass_and_buoyancy(
        solid_volume_m3=0.0010000000000000002,
        displaced_volume_m3=0.001,
        material_density_kg_per_m3=1000.0,
        fluid_density_kg_per_m3=1000.0,
        gravity_m_per_s2=10.0,
    )

    assert result.net_submerged_mass_kg == pytest.approx(0.0, abs=1.0e-15)


def test_rejects_nonfinite_derived_hydrostatic_results():
    with pytest.raises(ValueError, match="calculated external pressures must be finite"):
        external_pressure_from_depth(
            depth_m=1.0e308,
            fluid_density_kg_per_m3=1.0e308,
            gravity_m_per_s2=1.0,
            design_factor=1.0,
        )


def test_rejects_nonfinite_derived_mass_results():
    with pytest.raises(ValueError, match="calculated mass and buoyancy values must be finite"):
        submerged_mass_and_buoyancy(
            solid_volume_m3=1.0e308,
            displaced_volume_m3=1.0e308,
            material_density_kg_per_m3=1.0e308,
            fluid_density_kg_per_m3=1.0,
            gravity_m_per_s2=1.0,
        )


@pytest.mark.parametrize(
    "field",
    [
        "solid_volume_m3",
        "displaced_volume_m3",
        "material_density_kg_per_m3",
        "fluid_density_kg_per_m3",
        "gravity_m_per_s2",
    ],
)
@pytest.mark.parametrize("value", [0.0, -1.0, math.inf, math.nan, True, None])
def test_rejects_nonphysical_inputs(field: str, value: object):
    request = {
        "solid_volume_m3": 0.25,
        "displaced_volume_m3": 1.5,
        "material_density_kg_per_m3": 8000.0,
        "fluid_density_kg_per_m3": 1000.0,
        "gravity_m_per_s2": 10.0,
        field: value,
    }
    expected = (
        "must be numeric"
        if value is None or isinstance(value, bool)
        else "must be finite and positive"
    )
    with pytest.raises(ValueError, match=f"{field} {expected}"):
        submerged_mass_and_buoyancy(**request)
