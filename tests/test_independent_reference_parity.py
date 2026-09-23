from __future__ import annotations

import ast
import math
from pathlib import Path

import pytest
import yaml

from pv_calc.pressure_vessel import (
    RING_SHELL_MODEL_ID,
    RING_SHELL_MODEL_VERSION,
    RingShellResult,
    closed_end_tube_stress,
    flat_circular_plate,
    hemispherical_head_external_pressure,
    ring_stiffened_shell_external_pressure,
    smooth_cylinder_external_pressure_buckling,
)
from reference.non_ring_reference import (
    PUBLISHED_TOLERANCES,
    REFERENCE_ABSOLUTE_TOLERANCE,
    REFERENCE_RELATIVE_TOLERANCE,
    closed_end_tube_reference,
    flat_circular_plate_reference,
    hemispherical_head_reference,
    length_for_z,
    roark_case20_reference,
    smooth_cylinder_reference,
)
from reference.hemisphere_displacement_reference import (
    hemispherical_head_displacement_reference,
)
from reference.tube_displacement_reference import (
    closed_end_tube_displacement_reference,
)
from reference.ring_shell_reference import (
    CONVERGENCE_TRAP_CASES,
    DTMB_LENGTH_DIAMETER_ABSOLUTE_TOLERANCE,
    DTMB_TABLE_2_PUBLISHED,
    RingCase,
    dtmb_case,
    solve_case,
)
from reference.ring_yield_reference import (
    JMSE_2020_AREA_RULE,
    JMSE_2020_PRINTED_PRECISION_MPA,
    JMSE_2020_PUBLISHED_PC5_MPA,
    JMSE_2020_WORKED_EXAMPLE,
    PARITY_CASES as RING_YIELD_PARITY_CASES,
    YieldCase,
    direct_solution as ring_yield_direct_solution,
    printed_form as ring_yield_printed_form,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _run_from_the_package_root(monkeypatch: pytest.MonkeyPatch) -> None:
    # Fixtures and reference modules are addressed by package-relative path
    # throughout this module.
    monkeypatch.chdir(PACKAGE_ROOT)



INCH_TO_MM = 25.4
PSI_TO_MPA = 0.006894757293168361
KSI_TO_MPA = 1_000.0 * PSI_TO_MPA
PRESSURE_RELATIVE_TOLERANCE = 1.0e-11
PRESSURE_ABSOLUTE_TOLERANCE = 1.0e-10


def _production_case(case: RingCase) -> RingShellResult:
    length_scale = INCH_TO_MM if case.length_unit == "in" else 1.0
    pressure_scale = PSI_TO_MPA if case.pressure_unit == "psi" else 1.0
    return ring_stiffened_shell_external_pressure(
        external_pressure_mpa=pressure_scale,
        shell_mid_surface_radius_mm=case.shell_mid_surface_radius * length_scale,
        wall_thickness_mm=case.wall_thickness * length_scale,
        unsupported_length_mm=case.unsupported_length * length_scale,
        ring_spacing_mm=case.ring_spacing * length_scale,
        ring_axial_width_mm=case.ring_axial_width * length_scale,
        ring_radial_height_mm=case.ring_radial_height * length_scale,
        ring_location=case.ring_location,
        elastic_modulus_mpa=case.elastic_modulus * pressure_scale,
        poisson_ratio=case.poisson_ratio,
        yield_strength_mpa=1_000_000.0 * pressure_scale,
    )


def _assert_mode_parity(case: RingCase) -> None:
    reference = solve_case(case)
    production = _production_case(case)
    pressure_scale = PSI_TO_MPA if case.pressure_unit == "psi" else 1.0

    for independent, released in (
        (reference.without_ring_torsion, production.global_without_ring_torsion),
        (reference.with_ring_torsion, production.global_with_ring_torsion),
    ):
        assert released.converged is True
        assert released.ideal_critical_pressure_mpa / pressure_scale == pytest.approx(
            independent.ideal_critical_pressure,
            rel=PRESSURE_RELATIVE_TOLERANCE,
            abs=PRESSURE_ABSOLUTE_TOLERANCE,
        )
        assert released.adjusted_critical_pressure_mpa / pressure_scale == pytest.approx(
            independent.adjusted_critical_pressure,
            rel=PRESSURE_RELATIVE_TOLERANCE,
            abs=PRESSURE_ABSOLUTE_TOLERANCE,
        )
        assert (
            released.critical_axial_half_waves_m,
            released.critical_circumferential_lobes_n,
        ) == (
            independent.axial_half_waves_m,
            independent.circumferential_lobes_n,
        )


@pytest.mark.parametrize(
    "reference",
    [
        "tests/reference/ring_shell_reference.py",
        "tests/reference/ring_yield_reference.py",
    ],
)
def test_independent_reference_has_no_production_imports(reference: str) -> None:
    reference_path = Path(reference)
    tree = ast.parse(reference_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(
        module == "pv_calc" or module.startswith("pv_calc.")
        for module in imported_modules
    )


@pytest.mark.parametrize(
    "reference",
    [
        "tests/reference/non_ring_reference.py",
        "tests/reference/tube_displacement_reference.py",
        "tests/reference/hemisphere_displacement_reference.py",
    ],
)
def test_non_ring_independent_reference_has_no_production_or_fixture_imports(
    reference: str,
) -> None:
    reference_path = Path(reference)
    tree = ast.parse(reference_path.read_text(encoding="utf-8"))
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    imported_modules.update(
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    )
    assert not any(
        module == "pv_calc" or module.startswith("pv_calc.")
        for module in imported_modules
    )
    assert "yaml" not in imported_modules


def _assert_reference_close(actual: float, independent: float) -> None:
    assert actual == pytest.approx(
        independent,
        rel=REFERENCE_RELATIVE_TOLERANCE,
        abs=REFERENCE_ABSOLUTE_TOLERANCE,
    )


def _assert_optional_reference_close(
    actual: float | None,
    independent: float | None,
    *,
    rel: float = REFERENCE_RELATIVE_TOLERANCE,
) -> None:
    if independent is None:
        assert actual is None
    else:
        assert actual == pytest.approx(
            independent,
            rel=rel,
            abs=REFERENCE_ABSOLUTE_TOLERANCE,
        )


def _assert_tube_parity(
    *,
    pressure_mpa: float,
    internal_radius_mm: float,
    wall_thickness_mm: float,
    yield_strength_mpa: float,
    force_thick: bool = False,
) -> None:
    independent = closed_end_tube_reference(
        external_pressure=pressure_mpa,
        internal_radius=internal_radius_mm,
        wall_thickness=wall_thickness_mm,
        yield_strength=yield_strength_mpa,
    )
    released = closed_end_tube_stress(
        external_pressure_mpa=pressure_mpa,
        internal_radius_mm=internal_radius_mm,
        wall_thickness_mm=wall_thickness_mm,
        strength_mpa=yield_strength_mpa,
        material_failure_category="ductile_metal",
        force_thick=force_thick,
    )
    for actual, key in (
        (released.external_radius_mm, "external_radius"),
        (released.mean_radius_mm, "mean_radius"),
        (released.mean_radius_over_thickness, "mean_radius_over_thickness"),
        (released.governing_radius_mm, "governing_radius"),
        (released.governing_stress_mpa, "governing_von_mises_stress"),
        (released.theoretical_failure_pressure_mpa, "theoretical_failure_pressure"),
        (released.margin, "margin"),
    ):
        _assert_reference_close(actual, independent[key])
    assert len(released.stress_states) == len(independent["stress_states"])
    for actual, expected in zip(
        released.stress_states,
        independent["stress_states"],
        strict=True,
    ):
        assert actual.radius_convention == expected["radius_convention"]
        for value, key in (
            (actual.radius_mm, "radius"),
            (actual.radial_stress_mpa, "radial_stress"),
            (actual.hoop_stress_mpa, "hoop_stress"),
            (actual.axial_stress_mpa, "axial_stress"),
            (actual.von_mises_stress_mpa, "von_mises_stress"),
        ):
            _assert_reference_close(value, expected[key])


@pytest.mark.parametrize(
    ("pressure", "radius", "thickness", "yield_strength", "force_thick"),
    [
        (1_000.0 * PSI_TO_MPA, 3.0 * INCH_TO_MM, 0.470 * INCH_TO_MM, 62.0 * KSI_TO_MPA, False),
        (12.0, 30.0, 10.0, 300.0, False),
        (2.0, 100.0, 5.0, 276.0, False),
        (2.0, 100.0, 5.0, 276.0, True),
        (1.0, 9.5, 1.0, 100.0, False),
        (1.0, 9.500001, 1.0, 100.0, False),
        (22.6243125, 55.0, 22.0, 276.0, False),
    ],
)
def test_all_tube_goldens_and_branch_cases_match_independent_reference(
    pressure: float,
    radius: float,
    thickness: float,
    yield_strength: float,
    force_thick: bool,
) -> None:
    _assert_tube_parity(
        pressure_mpa=pressure,
        internal_radius_mm=radius,
        wall_thickness_mm=thickness,
        yield_strength_mpa=yield_strength,
        force_thick=force_thick,
    )


@pytest.mark.parametrize(
    ("pressure", "radius", "thickness", "poisson", "force_thick"),
    [
        # Thin and thick geometries, the compatibility force_thick option,
        # and both sides of the former r_m/t = 10 stress switch.
        (2.0, 100.0, 5.0, 0.33, False),
        (22.6243125, 55.0, 22.0, 0.33, False),
        (2.0, 100.0, 5.0, 0.33, True),
        (1.0, 9.5, 1.0, 0.33, False),
        (1.0, 9.500001, 1.0, 0.33, False),
        # the ends of the accepted Poisson range, where the (1 - 2*nu) axial
        # term is largest and smallest
        (5.0, 200.0, 4.0, 0.05, False),
        (5.0, 200.0, 4.0, 0.45, False),
    ],
)
def test_tube_displacement_matches_the_independent_source_transcription(
    pressure: float,
    radius: float,
    thickness: float,
    poisson: float,
    force_thick: bool,
) -> None:
    modulus = 68_900.0
    gauge_length = 500.0
    independent = closed_end_tube_displacement_reference(
        external_pressure=pressure,
        internal_radius=radius,
        wall_thickness=thickness,
        elastic_modulus=modulus,
        poisson_ratio=poisson,
        axial_length=gauge_length,
    )
    released = closed_end_tube_stress(
        external_pressure_mpa=pressure,
        internal_radius_mm=radius,
        wall_thickness_mm=thickness,
        strength_mpa=276.0,
        material_failure_category="ductile_metal",
        elastic_modulus_mpa=modulus,
        poisson_ratio=poisson,
        axial_length_mm=gauge_length,
        force_thick=force_thick,
    )

    assert released.displacement_status == "released"
    _assert_reference_close(released.axial_strain, independent["axial_strain"])
    _assert_reference_close(
        released.axial_length_change_mm, independent["axial_length_change"]
    )
    assert len(released.stress_states) == len(independent["surfaces"])
    for state, surface in zip(
        released.stress_states, independent["surfaces"], strict=True
    ):
        assert state.radius_convention == surface["radius_convention"]
        _assert_reference_close(state.radius_mm, surface["radius"])
        _assert_reference_close(
            state.radial_displacement_mm, surface["radial_displacement"]
        )


@pytest.mark.parametrize(
    ("pressure", "radius", "thickness", "poisson", "force_thick"),
    [
        # The released hemisphere example, then both sides of the former
        # r_m/t = 10 stress switch, the compatibility option, and both ends of the accepted
        # Poisson range.
        (6.0, 100.0, 100.0 / 39.5, 0.33, False),
        (1.0, 9.5, 1.0, 0.33, False),
        (1.0, 9.500001, 1.0, 0.33, False),
        (6.0, 100.0, 100.0 / 39.5, 0.33, True),
        (2.0, 200.0, 4.0, 0.05, False),
        (2.0, 200.0, 4.0, 0.45, False),
    ],
)
def test_hemisphere_displacement_matches_the_independent_closed_form(
    pressure: float,
    radius: float,
    thickness: float,
    poisson: float,
    force_thick: bool,
) -> None:
    modulus = 68_900.0
    independent = hemispherical_head_displacement_reference(
        external_pressure=pressure,
        internal_radius=radius,
        wall_thickness=thickness,
        elastic_modulus=modulus,
        poisson_ratio=poisson,
    )
    released = hemispherical_head_external_pressure(
        external_pressure_mpa=pressure,
        internal_radius_mm=radius,
        wall_thickness_mm=thickness,
        elastic_modulus_mpa=modulus,
        poisson_ratio=poisson,
        strength_mpa=276.0,
        material_failure_category="ductile_metal",
        force_thick=force_thick,
    )

    assert released.displacement_status == "released"
    for state, surface in zip(
        released.stress_states, independent["surfaces"], strict=True
    ):
        assert state.radius_convention == surface["radius_convention"]
        _assert_reference_close(state.radius_mm, surface["radius"])
        _assert_reference_close(
            state.radial_displacement_mm, surface["radial_displacement"]
        )


def _assert_hemisphere_parity(
    *,
    pressure_mpa: float,
    internal_radius_mm: float,
    wall_thickness_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    yield_strength_mpa: float,
    proportional_limit_mpa: float | None,
    force_thick: bool = False,
) -> None:
    independent = hemispherical_head_reference(
        external_pressure=pressure_mpa,
        internal_radius=internal_radius_mm,
        wall_thickness=wall_thickness_mm,
        elastic_modulus=elastic_modulus_mpa,
        poisson_ratio=poisson_ratio,
        yield_strength=yield_strength_mpa,
        proportional_limit=proportional_limit_mpa,
    )
    released = hemispherical_head_external_pressure(
        external_pressure_mpa=pressure_mpa,
        internal_radius_mm=internal_radius_mm,
        wall_thickness_mm=wall_thickness_mm,
        elastic_modulus_mpa=elastic_modulus_mpa,
        poisson_ratio=poisson_ratio,
        strength_mpa=yield_strength_mpa,
        proportional_limit_mpa=proportional_limit_mpa,
        material_failure_category="ductile_metal",
        force_thick=force_thick,
    )
    assert released.buckling_capacity_status == independent[
        "buckling_capacity_status"
    ]
    assert len(released.buckling_validity_violations) == len(
        independent["buckling_validity_violations"]
    )
    for actual, key in (
        (released.external_radius_mm, "external_radius"),
        (released.mean_radius_mm, "mean_radius"),
        (released.mean_radius_over_thickness, "mean_radius_over_thickness"),
        (released.governing_radius_mm, "governing_radius"),
        (released.governing_stress_mpa, "governing_von_mises_stress"),
        (
            released.theoretical_stress_failure_pressure_mpa,
            "theoretical_yield_failure_pressure",
        ),
        (released.stress_margin, "yield_margin"),
        (released.classical_critical_pressure_mpa, "classical_critical_pressure"),
        (released.nasa_geometry_parameter_lambda, "nasa_geometry_parameter_lambda"),
        (
            released.roark_probable_minimum_pressure_mpa,
            "underpressure_probable_minimum_pressure",
        ),
    ):
        _assert_reference_close(actual, independent[key])
    for actual, key in (
        (released.nasa_correlation_factor, "nasa_correlation_factor"),
        (released.nasa_candidate_design_pressure_mpa, "nasa_candidate_design_pressure"),
        (
            released.nasa_candidate_critical_membrane_stress_mpa,
            "nasa_candidate_critical_membrane_stress",
        ),
        (released.released_buckling_pressure_mpa, "released_buckling_pressure"),
        (
            released.released_buckling_critical_membrane_stress_mpa,
            "released_buckling_critical_membrane_stress",
        ),
        (released.buckling_margin, "buckling_margin"),
    ):
        _assert_optional_reference_close(actual, independent[key])
    assert len(released.stress_states) == len(independent["stress_states"])
    for actual, expected in zip(
        released.stress_states,
        independent["stress_states"],
        strict=True,
    ):
        assert actual.radius_convention == expected["radius_convention"]
        for value, key in (
            (actual.radius_mm, "radius"),
            (actual.radial_stress_mpa, "radial_stress"),
            (actual.meridional_stress_mpa, "meridional_stress"),
            (actual.hoop_stress_mpa, "hoop_stress"),
            (actual.von_mises_stress_mpa, "von_mises_stress"),
        ):
            _assert_reference_close(value, expected[key])


@pytest.mark.parametrize(
    (
        "pressure",
        "radius",
        "thickness",
        "elastic_modulus",
        "poisson_ratio",
        "yield_strength",
        "proportional_limit",
        "force_thick",
    ),
    [
        (
            1_000.0 * PSI_TO_MPA,
            1.75 * INCH_TO_MM,
            0.25 * INCH_TO_MM,
            9_900_000.0 * PSI_TO_MPA,
            0.33,
            35_000.0 * PSI_TO_MPA,
            None,
            False,
        ),
        (6.0, 100.0, 100.0 / 39.5, 68_900.0, 0.33, 276.0, 200.0, False),
        (1.0, 9.5, 1.0, 70_000.0, 0.30, 300.0, 250.0, False),
        (
            1.0,
            math.nextafter(9.5, math.inf),
            1.0,
            70_000.0,
            0.30,
            300.0,
            250.0,
            False,
        ),
        (6.0, 100.0, 100.0 / 39.5, 68_900.0, 0.33, 276.0, 200.0, True),
    ],
)
def test_hemisphere_goldens_branches_and_release_cases_match_independent_reference(
    pressure: float,
    radius: float,
    thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
    yield_strength: float,
    proportional_limit: float | None,
    force_thick: bool,
) -> None:
    _assert_hemisphere_parity(
        pressure_mpa=pressure,
        internal_radius_mm=radius,
        wall_thickness_mm=thickness,
        elastic_modulus_mpa=elastic_modulus,
        poisson_ratio=poisson_ratio,
        yield_strength_mpa=yield_strength,
        proportional_limit_mpa=proportional_limit,
        force_thick=force_thick,
    )


def test_hemisphere_proportional_limit_gate_matches_independent_reference() -> None:
    inputs = {
        "pressure_mpa": 6.0,
        "internal_radius_mm": 100.0,
        "wall_thickness_mm": 100.0 / 39.5,
        "elastic_modulus_mpa": 68_900.0,
        "poisson_ratio": 0.33,
        "yield_strength_mpa": 276.0,
    }
    baseline = hemispherical_head_reference(
        external_pressure=inputs["pressure_mpa"],
        internal_radius=inputs["internal_radius_mm"],
        wall_thickness=inputs["wall_thickness_mm"],
        elastic_modulus=inputs["elastic_modulus_mpa"],
        poisson_ratio=inputs["poisson_ratio"],
        yield_strength=inputs["yield_strength_mpa"],
        proportional_limit=200.0,
    )
    critical_stress = baseline["nasa_candidate_critical_membrane_stress"]
    assert critical_stress is not None
    _assert_hemisphere_parity(**inputs, proportional_limit_mpa=None)
    _assert_hemisphere_parity(
        **inputs,
        proportional_limit_mpa=critical_stress,
    )
    _assert_hemisphere_parity(
        **inputs,
        proportional_limit_mpa=math.nextafter(critical_stress, 0.0),
    )


def _assert_plate_parity(
    *,
    pressure_mpa: float,
    radius_mm: float,
    thickness_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    yield_strength_mpa: float,
    boundary_condition: str,
) -> None:
    independent = flat_circular_plate_reference(
        external_pressure=pressure_mpa,
        free_radius=radius_mm,
        plate_thickness=thickness_mm,
        elastic_modulus=elastic_modulus_mpa,
        poisson_ratio=poisson_ratio,
        yield_strength=yield_strength_mpa,
        boundary_condition=boundary_condition,  # type: ignore[arg-type]
    )
    released = flat_circular_plate(
        external_pressure_mpa=pressure_mpa,
        free_radius_mm=radius_mm,
        plate_thickness_mm=thickness_mm,
        elastic_modulus_mpa=elastic_modulus_mpa,
        poisson_ratio=poisson_ratio,
        strength_mpa=yield_strength_mpa,
        material_failure_category="ductile_metal",
        boundary_condition=boundary_condition,  # type: ignore[arg-type]
    )
    assert released.source_equation_case == independent["source_equation_case"]
    assert released.maximum_radial_stress_location == independent[
        "maximum_radial_stress_location"
    ]
    assert [item.replace("_mm", "") for item in released.validity_violations] == (
        independent["validity_violations"]
    )
    assert [
        item.replace("_mm", "") for item in released.deflection_validity_violations
    ] == independent["deflection_validity_violations"]
    for value, key in (
        (released.bending_status, "bending_status"),
        (released.deflection_status, "deflection_status"),
        (
            released.bending_minimum_free_diameter_over_thickness,
            "bending_minimum_free_diameter_over_thickness",
        ),
        (
            released.deflection_minimum_free_diameter_over_thickness,
            "deflection_minimum_free_diameter_over_thickness",
        ),
        (released.poisson_ratio_evidence_band, "poisson_ratio_evidence_band"),
    ):
        assert value == independent[key]
    _assert_optional_reference_close(released.margin, independent["margin"])
    _assert_optional_reference_close(
        released.released_maximum_deflection_mm,
        independent["released_maximum_deflection"],
    )
    for actual, key in (
        (released.free_diameter_mm, "free_diameter"),
        (released.free_diameter_over_thickness, "free_diameter_over_thickness"),
        (released.flexural_rigidity_n_mm, "flexural_rigidity"),
        (released.radial_bending_stress_coefficient, "radial_bending_stress_coefficient"),
        (released.tangential_bending_stress_coefficient, "tangential_bending_stress_coefficient"),
        (released.maximum_radial_bending_stress_mpa, "maximum_radial_bending_stress"),
        (released.maximum_tangential_bending_stress_mpa, "maximum_tangential_bending_stress"),
        (released.governing_bending_stress_mpa, "governing_bending_stress"),
        (released.transverse_shear_stress_mpa, "transverse_shear_stress"),
        (released.maximum_deflection_mm, "maximum_deflection"),
        (released.maximum_deflection_over_thickness, "maximum_deflection_over_thickness"),
        (
            released.shear_corrected_deflection_estimate_mm,
            "shear_corrected_deflection_estimate",
        ),
        (
            released.shear_corrected_deflection_estimate_over_thickness,
            "shear_corrected_deflection_estimate_over_thickness",
        ),
        (released.theoretical_radial_failure_pressure_mpa, "theoretical_radial_failure_pressure"),
        (released.theoretical_tangential_failure_pressure_mpa, "theoretical_tangential_failure_pressure"),
        (released.theoretical_failure_pressure_mpa, "theoretical_failure_pressure"),
    ):
        _assert_reference_close(actual, independent[key])


@pytest.mark.parametrize(
    (
        "pressure",
        "radius",
        "thickness",
        "elastic_modulus",
        "poisson_ratio",
        "yield_strength",
        "boundary",
    ),
    [
        (4_500.0 * PSI_TO_MPA, 3.0 * INCH_TO_MM, 1.280 * INCH_TO_MM, 10_300_000.0 * PSI_TO_MPA, 0.33, 62.0 * KSI_TO_MPA, "simply_supported"),
        (1_000.0 * PSI_TO_MPA, 2.5 * INCH_TO_MM, 0.625 * INCH_TO_MM, 10_000_000.0 * PSI_TO_MPA, 0.30, 62.0 * KSI_TO_MPA, "simply_supported"),
        (1_000.0 * PSI_TO_MPA, 2.5 * INCH_TO_MM, 0.625 * INCH_TO_MM, 10_000_000.0 * PSI_TO_MPA, 0.30, 62.0 * KSI_TO_MPA, "fixed"),
        (2.0, 50.0, 10.0, 70_000.0, 0.30, 300.0, "simply_supported"),
        (2.0, 50.0, 10.0, 70_000.0, 0.30, 300.0, "fixed"),
        (1.0, 50.0, 25.0, 70_000.0, 0.30, 300.0, "fixed"),
        (1.0, 50.0, 25.0001, 70_000.0, 0.30, 300.0, "fixed"),
        (10.0, 50.0, 10.0, 1_000.0, 0.30, 300.0, "fixed"),
        (22.6243125, 55.0, 27.5, 68_900.0, 0.33, 276.0, "fixed"),
        # The worked fixed-edge case at the D_free/t = 10 bending floor
        # (sigma_r = 0.75 * p * (a/t)^2 = 243.75 MPa).
        (13.0, 55.0, 11.0, 68_900.0, 0.33, 276.0, "fixed"),
        # Either side of the shear-corrected small-deflection gate, where the
        # raw Kirchhoff deflection is still under t/2 (w/t = 0.499 and 0.492):
        # the estimate crosses t/2 between the two pressures.
        (0.3348190750059909, 50.0, 2.5, 70_000.0, 0.35, 300.0, "simply_supported"),
        (0.33, 50.0, 2.5, 70_000.0, 0.35, 300.0, "simply_supported"),
        # Binary-exact fixed-edge stress is 0.75*1*(50/5)^2 = 75 MPa, so the
        # deflection is released only at a supplied strength of at least 75 MPa.
        (1.0, 50.0, 5.0, 70_000.0, 0.30, math.nextafter(75.0, 0.0), "fixed"),
        (1.0, 50.0, 5.0, 70_000.0, 0.30, 75.0, "fixed"),
        (1.0, 50.0, 5.0, 70_000.0, 0.30, math.nextafter(75.0, math.inf), "fixed"),
        # Geometry remains the primary status when material also fails.
        (1.0, 50.0, 5.0, 70_000.0, 0.45, 50.0, "fixed"),
    ],
)
def test_all_plate_goldens_and_validity_boundaries_match_independent_reference(
    pressure: float,
    radius: float,
    thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
    yield_strength: float,
    boundary: str,
) -> None:
    _assert_plate_parity(
        pressure_mpa=pressure,
        radius_mm=radius,
        thickness_mm=thickness,
        elastic_modulus_mpa=elastic_modulus,
        poisson_ratio=poisson_ratio,
        yield_strength_mpa=yield_strength,
        boundary_condition=boundary,
    )


def _assert_smooth_parity(inputs: dict[str, object]) -> None:
    independent = smooth_cylinder_reference(**inputs)  # type: ignore[arg-type]
    released = smooth_cylinder_external_pressure_buckling(**inputs)  # type: ignore[arg-type]
    assert released.regime == independent["regime"]
    assert released.capacity_status == independent["capacity_status"]
    assert bool(released.validity_violations) is bool(
        independent["validity_violations"]
    )
    for actual, key in (
        (released.shell_mid_surface_radius_over_thickness, "shell_mid_surface_radius_over_thickness"),
        (released.unsupported_length_over_radius, "unsupported_length_over_radius"),
        (released.flexural_rigidity_n_mm, "flexural_rigidity_n_mm"),
        (released.curvature_parameter_z, "curvature_parameter_z"),
        (released.geometry_mode_parameter, "geometry_mode_parameter"),
        (released.circumferential_line_load_n_per_mm, "circumferential_line_load_n_per_mm"),
        (released.axial_line_load_n_per_mm, "axial_line_load_n_per_mm"),
        (released.moderate_long_boundary_parameter, "moderate_long_boundary_parameter"),
        (released.moderate_long_overlap_start_z, "moderate_long_overlap_start_z"),
        (released.moderate_long_overlap_end_z, "moderate_long_overlap_end_z"),
    ):
        _assert_reference_close(actual, independent[key])
    for actual, key in (
        (released.correlation_factor_gamma, "correlation_factor_gamma"),
        (released.sqrt_correlation_factor, "sqrt_correlation_factor"),
        (released.critical_buckling_coefficient, "critical_buckling_coefficient"),
        (released.critical_aspect_ratio_beta, "critical_aspect_ratio_beta"),
        (released.continuous_circumferential_wave_count, "continuous_circumferential_wave_count"),
        (released.ideal_critical_pressure_mpa, "ideal_critical_pressure_mpa"),
        (released.correlated_critical_pressure_mpa, "correlated_critical_pressure_mpa"),
    ):
        _assert_optional_reference_close(
            actual,
            independent[key],
            rel=1.0e-8 if "beta" in key or "wave_count" in key else REFERENCE_RELATIVE_TOLERANCE,
        )
    _assert_optional_reference_close(released.margin, independent["margin"])
    assert released.circumferential_wave_count_n == independent[
        "circumferential_wave_count_n"
    ]
    for actual, expected in zip(
        released.candidates,
        independent["candidates"],
        strict=True,
    ):
        assert actual.regime == expected["regime"]
        assert actual.applicable is expected["applicable"]
        assert actual.correlation_factor_gamma == expected["gamma"]
        for value, key in (
            (actual.critical_buckling_coefficient, "critical_buckling_coefficient"),
            (actual.ideal_critical_pressure_mpa, "ideal_critical_pressure_mpa"),
            (actual.correlated_critical_pressure_mpa, "correlated_critical_pressure_mpa"),
            (actual.eq25_simplified_critical_pressure_mpa, "eq25_simplified_critical_pressure_mpa"),
        ):
            _assert_optional_reference_close(value, expected.get(key))
        _assert_optional_reference_close(
            actual.critical_aspect_ratio_beta,
            expected["critical_aspect_ratio_beta"],
            rel=1.0e-8,
        )


def _base_smooth_inputs(**changes: object) -> dict[str, object]:
    inputs: dict[str, object] = {
        "external_pressure_mpa": 0.01,
        "shell_mid_surface_radius_mm": 500.0,
        "wall_thickness_mm": 5.0,
        "unsupported_length_mm": 1800.0,
        "elastic_modulus_mpa": 70_000.0,
        "poisson_ratio": 0.3,
        "yield_strength_mpa": 250.0,
        "load_case": "hydrostatic_closed_end",
        "proportional_limit_mpa": 200.0,
    }
    inputs.update(changes)
    return inputs


@pytest.mark.parametrize(
    "inputs",
    [
        _base_smooth_inputs(external_pressure_mpa=1.0, unsupported_length_mm=300.0, load_case="lateral_only"),
        _base_smooth_inputs(external_pressure_mpa=1.0, unsupported_length_mm=300.0),
        _base_smooth_inputs(),
        _base_smooth_inputs(load_case="lateral_only"),
        _base_smooth_inputs(poisson_ratio=0.316),
        _base_smooth_inputs(wall_thickness_mm=25.0, unsupported_length_mm=11_000.0),
        _base_smooth_inputs(wall_thickness_mm=25.0, unsupported_length_mm=9_000.0),
        _base_smooth_inputs(shell_mid_surface_radius_mm=1010.0, wall_thickness_mm=20.0, unsupported_length_mm=100_000.0, elastic_modulus_mpa=68_900.0, poisson_ratio=0.33, yield_strength_mpa=276.0),
    ],
)
def test_smooth_released_examples_and_golden_regimes_match_independent_reference(
    inputs: dict[str, object],
) -> None:
    _assert_smooth_parity(inputs)


def test_smooth_branch_and_applicability_boundaries_match_independent_reference() -> None:
    radius = 500.0
    poisson = 0.3
    for z in (
        100.0 * (1.0 - 1.0e-10),
        100.0 * (1.0 + 1.0e-10),
        (100.0 / 0.5625) * (1.0 + 1.0e-10),
    ):
        _assert_smooth_parity(
            _base_smooth_inputs(
                unsupported_length_mm=length_for_z(
                    z,
                    radius=radius,
                    thickness=5.0,
                    poisson_ratio=poisson,
                )
            )
        )

    overlap_reference = smooth_cylinder_reference(
        **_base_smooth_inputs(wall_thickness_mm=25.0, unsupported_length_mm=9_000.0)  # type: ignore[arg-type]
    )
    for z in (
        overlap_reference["moderate_long_overlap_start_z"] * (1.0 - 1.0e-10),
        (
            overlap_reference["moderate_long_overlap_start_z"]
            + overlap_reference["moderate_long_overlap_end_z"]
        )
        / 2.0,
        overlap_reference["moderate_long_overlap_end_z"] * (1.0 + 1.0e-10),
    ):
        _assert_smooth_parity(
            _base_smooth_inputs(
                wall_thickness_mm=25.0,
                unsupported_length_mm=length_for_z(
                    z,
                    radius=radius,
                    thickness=25.0,
                    poisson_ratio=poisson,
                ),
            )
        )

    target_z = 200.0
    thickness = 50.0
    _assert_smooth_parity(
        _base_smooth_inputs(
            wall_thickness_mm=thickness,
            unsupported_length_mm=length_for_z(
                target_z,
                radius=radius,
                thickness=thickness,
                poisson_ratio=poisson,
            ),
            yield_strength_mpa=1.0e12,
            proportional_limit_mpa=1.0e12,
        )
    )

    above_ten_radius = math.nextafter(radius, math.inf)
    _assert_smooth_parity(
        _base_smooth_inputs(
            shell_mid_surface_radius_mm=above_ten_radius,
            wall_thickness_mm=thickness,
            unsupported_length_mm=length_for_z(
                target_z,
                radius=above_ten_radius,
                thickness=thickness,
                poisson_ratio=poisson,
            ),
            yield_strength_mpa=1.0e12,
            proportional_limit_mpa=1.0e12,
        )
    )
    _assert_smooth_parity(
        _base_smooth_inputs(
            wall_thickness_mm=0.05,
            unsupported_length_mm=length_for_z(
                target_z,
                radius=radius,
                thickness=0.05,
                poisson_ratio=poisson,
            ),
            yield_strength_mpa=1.0e12,
            proportional_limit_mpa=1.0e12,
        )
    )

    short_regime_z = 100.0 / 0.90
    for load_case in ("lateral_only", "hydrostatic_closed_end"):
        _assert_smooth_parity(
            _base_smooth_inputs(
                unsupported_length_mm=length_for_z(
                    short_regime_z,
                    radius=radius,
                    thickness=5.0,
                    poisson_ratio=poisson,
                ),
                load_case=load_case,
            )
        )


def test_smooth_short_moderate_boundary_matches_independent_reference() -> None:
    # The Eq. 23 approximation step is pinned in
    # tests/test_smooth_cylinder_buckling.py; this checks reference parity at
    # the same gamma*Z = 100 boundary geometry, which both branches now release.
    radius = 500.0
    thickness = 5.0
    poisson = 0.3
    boundary_z = 100.0 / 0.5625
    length = length_for_z(
        boundary_z, radius=radius, thickness=thickness, poisson_ratio=poisson
    )
    for load_case in ("lateral_only", "hydrostatic_closed_end"):
        inputs = _base_smooth_inputs(
            unsupported_length_mm=length, load_case=load_case
        )
        _assert_smooth_parity(inputs)
        independent = smooth_cylinder_reference(**inputs)  # type: ignore[arg-type]
        assert independent["capacity_status"] == "released"


def test_smooth_proportional_limit_gates_match_independent_reference() -> None:
    baseline = smooth_cylinder_reference(**_base_smooth_inputs())  # type: ignore[arg-type]
    elastic_limit = baseline["candidates"][1][
        "correlated_critical_circumferential_stress_mpa"
    ]
    assert elastic_limit is not None
    _assert_smooth_parity(
        _base_smooth_inputs(yield_strength_mpa=1.0e12, proportional_limit_mpa=None)
    )
    _assert_smooth_parity(_base_smooth_inputs(proportional_limit_mpa=elastic_limit))
    _assert_smooth_parity(
        _base_smooth_inputs(
            proportional_limit_mpa=math.nextafter(elastic_limit, 0.0)
        )
    )


def test_manual_and_roark_software_goldens_match_independent_transcriptions() -> None:
    # UnderPressure 4.0 manual examples in the manual's ksi, psi, and inches.
    tolerances = PUBLISHED_TOLERANCES
    tube_example_1 = closed_end_tube_reference(
        external_pressure=1.0,
        internal_radius=3.0,
        wall_thickness=0.470,
        yield_strength=62.0,
    )
    assert tube_example_1["theoretical_failure_pressure"] == pytest.approx(
        9.0401, abs=tolerances["repo_four_decimal_golden_ksi"]
    )
    plate_example_2 = flat_circular_plate_reference(
        external_pressure=4.5,
        free_radius=3.0,
        plate_thickness=1.280,
        elastic_modulus=10_300.0,
        poisson_ratio=0.33,
        yield_strength=62.0,
        boundary_condition="simply_supported",
    )
    assert plate_example_2["theoretical_failure_pressure"] == pytest.approx(
        9.0384, abs=tolerances["repo_four_decimal_golden_ksi"]
    )
    assert plate_example_2["theoretical_failure_pressure"] == pytest.approx(
        9.038, abs=tolerances["manual_display_example_2_failure_ksi"]
    )
    for boundary, radial_display, tangential_display in (
        ("simply_supported", 19_800.0, 19_800.0),
        ("fixed", 12_000.0, 7_800.0),
    ):
        appendix_e = flat_circular_plate_reference(
            external_pressure=1_000.0,
            free_radius=2.5,
            plate_thickness=0.625,
            elastic_modulus=10_000_000.0,
            poisson_ratio=0.30,
            yield_strength=62_000.0,
            boundary_condition=boundary,  # type: ignore[arg-type]
        )
        assert appendix_e["maximum_radial_bending_stress"] == pytest.approx(
            radial_display, abs=tolerances["manual_display_whole_psi"]
        )
        assert appendix_e["maximum_tangential_bending_stress"] == pytest.approx(
            tangential_display, abs=tolerances["manual_display_whole_psi"]
        )

    hemisphere = hemispherical_head_reference(
        external_pressure=1_000.0,
        internal_radius=1.75,
        wall_thickness=0.25,
        elastic_modulus=9_900_000.0,
        poisson_ratio=0.33,
        yield_strength=35_000.0,
    )
    assert hemisphere["governing_von_mises_stress"] == pytest.approx(
        4_544.4, abs=tolerances["manual_display_one_decimal_psi"]
    )
    assert hemisphere["theoretical_yield_failure_pressure"] == pytest.approx(
        7_701.8, abs=tolerances["manual_display_one_decimal_psi"]
    )
    # The manual displays thin-wall buckling for this r_m/t = 7.5 head too.
    assert hemisphere["underpressure_probable_minimum_pressure"] == pytest.approx(
        64_240.0, abs=tolerances["manual_display_whole_psi"]
    )
    assert hemisphere["mean_radius_over_thickness"] == 7.5
    assert hemisphere["buckling_capacity_status"] == "withheld_applicability"

    # Example 1 is outside the thin-wall range, but the manual still displays
    # its Roark case 20 buckling pressure.
    example_1 = roark_case20_reference(
        elastic_modulus_psi=10.3e6,
        poisson_ratio=0.33,
        mean_radius_in=3.0 + 0.470 / 2.0,
        wall_thickness_in=0.470,
        unsupported_length_in=24.0,
    )
    assert example_1["probable_minimum_pressure_psi"] == pytest.approx(
        10_632.0, abs=tolerances["manual_display_whole_psi"]
    )
    assert example_1["governing_circumferential_nodes"] == 2
    example_4 = roark_case20_reference(
        elastic_modulus_psi=0.41e6,
        poisson_ratio=0.4,
        mean_radius_in=2.5 + 0.240 / 2.0,
        wall_thickness_in=0.240,
        unsupported_length_in=10.0,
    )
    assert example_4["probable_minimum_pressure_psi"] == pytest.approx(
        266.60, abs=tolerances["manual_display_two_decimal_psi"]
    )
    assert example_4["governing_circumferential_nodes"] == 3

    fixture = yaml.safe_load(
        Path("tests/fixtures/software_parity/roark_table35_case20_overlap.yaml").read_text(
            encoding="utf-8"
        )
    )
    common = fixture["common_inputs"]
    for case in fixture["cases"]:
        independent = roark_case20_reference(
            elastic_modulus_psi=common["elastic_modulus"]["value"] * 1.0e6,
            poisson_ratio=common["poisson_ratio"],
            mean_radius_in=common["shell_mean_radius"]["value"],
            wall_thickness_in=common["wall_thickness"]["value"],
            unsupported_length_in=case["unsupported_length"]["value"],
        )
        _assert_reference_close(
            independent["probable_minimum_pressure_psi"],
            case["roark_probable_minimum_pressure_psi"],
        )
        assert independent["governing_circumferential_nodes"] == case[
            "roark_governing_nodes"
        ]


def test_tube_sizing_target_matches_exact_bore_yield() -> None:
    pressure = 7.0 * KSI_TO_MPA
    strength = 62.0 * KSI_TO_MPA
    internal_radius = 3.0 * INCH_TO_MM
    # Bore traction is zero, closed-end equilibrium fixes sigma_z, and
    # sigma_theta(a)=2*sigma_z, giving sigma_VM(a)=sqrt(3)*p*b^2/(b^2-a^2).
    exact_mm = internal_radius * (
        math.sqrt(strength / (strength - math.sqrt(3.0) * pressure)) - 1.0
    )
    assert exact_mm == pytest.approx(8.75844529201894, abs=2.0e-8)
    _assert_tube_parity(
        pressure_mpa=pressure,
        internal_radius_mm=internal_radius,
        wall_thickness_mm=exact_mm,
        yield_strength_mpa=strength,
    )
    at_exact = closed_end_tube_stress(
        external_pressure_mpa=pressure,
        internal_radius_mm=internal_radius,
        wall_thickness_mm=exact_mm,
        material_failure_category="ductile_metal",
        strength_mpa=strength,
    )
    _assert_reference_close(at_exact.governing_stress_mpa, strength)
    _assert_reference_close(at_exact.margin, 0.0)


def test_software_parity_fixture_nasa_values_match_independent_reference() -> None:
    fixture = yaml.safe_load(
        Path(
            "tests/fixtures/software_parity/underpressure_example4_tube_buckling.yaml"
        ).read_text(encoding="utf-8")
    )
    inputs = fixture["source_inputs"]
    material = inputs["material"]
    thickness_in = inputs["wall_thickness"]["value"]
    radius_in = inputs["tube_internal_diameter"]["value"] / 2.0 + thickness_in / 2.0
    roark = roark_case20_reference(
        elastic_modulus_psi=material["elastic_modulus"]["value"] * 1.0e6,
        poisson_ratio=material["poisson_ratio"]["value"],
        mean_radius_in=radius_in,
        wall_thickness_in=thickness_in,
        unsupported_length_in=inputs["tube_length"]["value"],
    )
    assert roark["governing_circumferential_nodes"] == (
        fixture["displayed_source_result"]["circumferential_nodes"]
    )
    _assert_reference_close(
        roark["probable_minimum_pressure_psi"],
        fixture["independent_roark_case20"]["probable_minimum_pressure_psi"],
    )
    assert roark["probable_minimum_pressure_psi"] == pytest.approx(
        fixture["displayed_source_result"]["value"], abs=0.01
    )
    example_4_inputs = _base_smooth_inputs(
        external_pressure_mpa=PSI_TO_MPA,
        shell_mid_surface_radius_mm=radius_in * INCH_TO_MM,
        wall_thickness_mm=thickness_in * INCH_TO_MM,
        unsupported_length_mm=inputs["tube_length"]["value"] * INCH_TO_MM,
        elastic_modulus_mpa=material["elastic_modulus"]["value"] * 1.0e6 * PSI_TO_MPA,
        poisson_ratio=material["poisson_ratio"]["value"],
        yield_strength_mpa=material["working_strength"]["value"] * KSI_TO_MPA,
        proportional_limit_mpa=None,
    )
    _assert_smooth_parity(example_4_inputs)
    independent = smooth_cylinder_reference(**example_4_inputs)  # type: ignore[arg-type]
    nasa = fixture["pv_calc_nasa_comparison"]
    _assert_reference_close(
        independent["curvature_parameter_z"], nasa["curvature_parameter_z"]
    )
    moderate = independent["candidates"][1]
    _assert_reference_close(
        moderate["ideal_critical_pressure_mpa"] / PSI_TO_MPA,
        nasa["printed_eq24_ideal_pressure_psi"],
    )
    _assert_reference_close(
        moderate["correlated_critical_pressure_mpa"] / PSI_TO_MPA,
        nasa["recommended_eq24_pressure_psi"],
    )
    assert independent["capacity_status"] == nasa["capacity_status"]

    fixture = yaml.safe_load(
        Path(
            "tests/fixtures/software_parity/roark_table35_case20_overlap.yaml"
        ).read_text(encoding="utf-8")
    )
    common = fixture["common_inputs"]
    for case in fixture["cases"]:
        matrix_inputs = _base_smooth_inputs(
            external_pressure_mpa=PSI_TO_MPA,
            shell_mid_surface_radius_mm=(
                common["shell_mean_radius"]["value"] * INCH_TO_MM
            ),
            wall_thickness_mm=common["wall_thickness"]["value"] * INCH_TO_MM,
            unsupported_length_mm=case["unsupported_length"]["value"] * INCH_TO_MM,
            elastic_modulus_mpa=(
                common["elastic_modulus"]["value"] * 1.0e6 * PSI_TO_MPA
            ),
            poisson_ratio=common["poisson_ratio"],
            yield_strength_mpa=1.0e9,
            proportional_limit_mpa=1.0e9,
        )
        _assert_smooth_parity(matrix_inputs)
        independent = smooth_cylinder_reference(**matrix_inputs)  # type: ignore[arg-type]
        assert independent["regime"] == case["nasa_regime"]
        assert independent["capacity_status"] == case["nasa_capacity_status"]
        comparator = next(
            candidate
            for candidate in independent["candidates"]
            if candidate["regime"] == case["nasa_comparator_regime"]
        )
        comparator_mpa = (
            comparator["ideal_critical_pressure_mpa"]
            if case["nasa_comparator_pressure_kind"] == "ideal_theoretical"
            else comparator["correlated_critical_pressure_mpa"]
        )
        _assert_reference_close(
            comparator_mpa / PSI_TO_MPA, case["nasa_comparator_pressure_psi"]
        )


def test_independent_rectangle_and_case17_torsion_trace_match_production() -> None:
    case = dtmb_case(17)
    reference = solve_case(case)
    production = _production_case(case)
    inch4_to_mm4 = INCH_TO_MM**4

    assert production.model_id == RING_SHELL_MODEL_ID
    assert production.model_version == RING_SHELL_MODEL_VERSION
    assert production.ring_area_mm2 / INCH_TO_MM**2 == pytest.approx(
        reference.rectangle.area,
        rel=1.0e-12,
    )
    assert production.ring_centroidal_inertia_mm4 / inch4_to_mm4 == pytest.approx(
        reference.rectangle.centroidal_inertia,
        rel=1.0e-12,
    )
    assert production.ring_torsional_constant_mm4 / inch4_to_mm4 == pytest.approx(
        reference.rectangle.saint_venant_torsional_constant,
        rel=1.0e-12,
    )
    assert production.torsion_ideal_pressure_effect_mpa / PSI_TO_MPA == pytest.approx(
        reference.torsion_ideal_pressure_increment,
        rel=PRESSURE_RELATIVE_TOLERANCE,
        abs=PRESSURE_ABSOLUTE_TOLERANCE,
    )
    assert production.torsion_adjusted_pressure_effect_mpa / PSI_TO_MPA == pytest.approx(
        reference.torsion_adjusted_pressure_increment,
        rel=PRESSURE_RELATIVE_TOLERANCE,
        abs=PRESSURE_ABSOLUTE_TOLERANCE,
    )
    assert production.torsion_changes_governing_mode is reference.torsion_changes_governing_mode
    _assert_mode_parity(case)


@pytest.mark.parametrize(
    "frame_spaces",
    [row[0] for row in DTMB_TABLE_2_PUBLISHED],
)
def test_independent_reference_covers_all_dtmb_geometries_and_modes(
    frame_spaces: int,
) -> None:
    _assert_mode_parity(dtmb_case(frame_spaces))


@pytest.mark.parametrize("case", CONVERGENCE_TRAP_CASES, ids=lambda case: case.case_id)
def test_independent_exhaustive_scan_reproduces_committed_convergence_traps(
    case: RingCase,
) -> None:
    _assert_mode_parity(case)


def test_dtmb_cases_match_the_published_length_over_diameter() -> None:
    for frame_spaces, published_length_over_diameter, *_ in DTMB_TABLE_2_PUBLISHED:
        case = dtmb_case(frame_spaces)
        # DTMB reports two decimals and labels 1.152 in as a typical spacing.
        assert case.unsupported_length / (
            2.0 * case.shell_mid_surface_radius
        ) == pytest.approx(
            published_length_over_diameter,
            abs=DTMB_LENGTH_DIAMETER_ABSOLUTE_TOLERANCE,
        )


# The two ring-yield reference routes and production use different numerics
# (direct hyperbolics, a scaled 3x3 solve, and exp(-x)-scaled closed forms),
# so agreement is to rounding, not bit-for-bit.
RING_YIELD_RELATIVE_TOLERANCE = 1.0e-12


def _ring_yield_production(case: YieldCase) -> RingShellResult:
    return ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1.0,
        shell_mid_surface_radius_mm=case.shell_mid_surface_radius,
        wall_thickness_mm=case.wall_thickness,
        unsupported_length_mm=10.0 * case.ring_spacing,
        ring_spacing_mm=case.ring_spacing,
        ring_axial_width_mm=case.ring_axial_width,
        ring_radial_height_mm=case.ring_radial_height,
        ring_location=case.ring_location,
        elastic_modulus_mpa=200_000.0,
        poisson_ratio=case.poisson_ratio,
        yield_strength_mpa=case.yield_strength,
    )


def test_ring_yield_parity_cases_span_location_and_bay_length() -> None:
    bay_parameters = [
        ring_yield_printed_form(case)["clear_bay_parameter"]
        for case in RING_YIELD_PARITY_CASES
    ]
    assert {case.ring_location for case in RING_YIELD_PARITY_CASES} == {"internal", "external"}
    # From a bay much shorter than the shell decay length to a very long one.
    assert min(bay_parameters) < 0.5
    assert max(bay_parameters) > 30.0


@pytest.mark.parametrize("case", RING_YIELD_PARITY_CASES, ids=lambda case: case.case_id)
def test_ring_yield_matches_the_independent_printed_form(case: YieldCase) -> None:
    independent = ring_yield_printed_form(case)
    production = _ring_yield_production(case)
    stress = production.axisymmetric_stress

    assert stress is not None
    for actual, key in (
        (stress.clear_bay_mm, "clear_bay"),
        (stress.clear_bay_parameter, "clear_bay_parameter"),
        (stress.n_function, "n_function"),
        (stress.effective_ring_area_mm2, "effective_ring_area"),
        (stress.frame_parameter_gamma, "gamma"),
        (stress.midbay_shell_hoop_stress_per_unit_pressure, "shell_hoop_stress_per_unit_pressure"),
        (stress.ring_hoop_stress_per_unit_pressure, "ring_hoop_stress_per_unit_pressure"),
        (production.shell_yield_between_rings_pressure_mpa, "shell_yield_pressure"),
        (production.ring_yield_pressure_mpa, "ring_yield_pressure"),
    ):
        assert actual == pytest.approx(independent[key], rel=RING_YIELD_RELATIVE_TOLERANCE), key
    # G changes sign in long bays, so it is compared absolutely.
    assert stress.g_function == pytest.approx(
        independent["g_function"], rel=0.0, abs=RING_YIELD_RELATIVE_TOLERANCE
    )


@pytest.mark.parametrize("case", RING_YIELD_PARITY_CASES, ids=lambda case: case.case_id)
def test_ring_yield_printed_form_matches_the_direct_bay_solution(case: YieldCase) -> None:
    # The printed closed form and the direct half-bay solution share only the
    # governing equation, so this checks the closed-form algebra, including
    # the ring stress, which has no published check.
    printed = ring_yield_printed_form(case)
    direct = ring_yield_direct_solution(case)
    for key in ("shell_hoop_stress_per_unit_pressure", "ring_hoop_stress_per_unit_pressure"):
        assert printed[key] == pytest.approx(direct[key], rel=RING_YIELD_RELATIVE_TOLERANCE), key


def test_jmse_2020_worked_example_mean_hoop_yield_pressure() -> None:
    # JMSE 8 (2020) 515 prints Pc5 = 14.95 MPa for an internal 6.35 mm square
    # ring. With the example's own flange-tip radius in the modified ring area,
    # the reference reproduces it at the printed precision. The bay is long
    # (beta*L = 8.3), so the ring moves Pc5 by only about 0.5% here; the parity
    # cases above cover short bays.
    reference = ring_yield_printed_form(JMSE_2020_WORKED_EXAMPLE, JMSE_2020_AREA_RULE)
    assert reference["shell_yield_pressure"] == pytest.approx(
        JMSE_2020_PUBLISHED_PC5_MPA, abs=JMSE_2020_PRINTED_PRECISION_MPA
    )

    # Production uses DTMB 1639's internal-ring area A_f (R/R_c), not the
    # example's A_f (R/R_f)^2, which moves Pc5 by +0.06% here.
    production = _ring_yield_production(JMSE_2020_WORKED_EXAMPLE)
    assert production.shell_yield_between_rings_pressure_mpa == pytest.approx(
        14.959541298679, rel=1.0e-12
    )
    assert production.shell_yield_between_rings_pressure_mpa == pytest.approx(
        JMSE_2020_PUBLISHED_PC5_MPA, rel=1.0e-3
    )
