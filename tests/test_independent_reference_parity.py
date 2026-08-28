from __future__ import annotations

import ast
import hashlib
import json
import math
from pathlib import Path

import pytest
import yaml

from pv_calc.pressure_vessel import (
    FLAT_CIRCULAR_PLATE_BENDING_MINIMUM_RATIO,
    FLAT_CIRCULAR_PLATE_DEFLECTION_MINIMUM_RATIO,
    FLAT_CIRCULAR_PLATE_POISSON_EVIDENCE_BAND,
    FLAT_CIRCULAR_PLATE_MODEL_ID,
    FLAT_CIRCULAR_PLATE_MODEL_VERSION,
    HEMISPHERE_MODEL_ID,
    HEMISPHERE_MODEL_VERSION,
    RING_SHELL_MODEL_ID,
    RING_SHELL_MODEL_VERSION,
    SMOOTH_CYLINDER_BUCKLING_MODEL_ID,
    SMOOTH_CYLINDER_BUCKLING_MODEL_VERSION,
    TUBE_STRESS_MODEL_ID,
    TUBE_STRESS_MODEL_VERSION,
    RingShellResult,
    closed_end_tube_stress,
    flat_circular_plate,
    hemispherical_head_external_pressure,
    ring_stiffened_shell_external_pressure,
    smooth_cylinder_external_pressure_buckling,
)
from pv_calc.hydrostatics import (
    HYDROSTATIC_PRESSURE_MODEL_ID,
    HYDROSTATIC_PRESSURE_MODEL_VERSION,
    SUBMERGED_MASS_MODEL_ID,
    SUBMERGED_MASS_MODEL_VERSION,
)
from validation.coverage_inventory import NON_RING_COVERAGE_INVENTORY
from validation.non_ring_reference import (
    REFERENCE_ABSOLUTE_TOLERANCE,
    REFERENCE_RELATIVE_TOLERANCE,
    build_evidence as build_non_ring_evidence,
    closed_end_tube_reference,
    flat_circular_plate_reference,
    hemispherical_head_reference,
    length_for_z,
    roark_case20_reference,
    smooth_cylinder_reference,
)
from validation.hemisphere_displacement_reference import (
    cylinder_to_sphere_ratio_reference,
    hemispherical_head_displacement_reference,
    spherical_membrane_reference,
)
from validation.tube_displacement_reference import (
    branch_agreement_reference,
    closed_end_tube_displacement_reference,
)
from validation.ring_shell_reference import (
    CONVERGENCE_TRAP_CASES,
    DTMB_LENGTH_DIAMETER_ABSOLUTE_TOLERANCE,
    DTMB_TABLE_2_PUBLISHED,
    RingCase,
    dtmb_case,
    solve_case,
)


PACKAGE_ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(autouse=True)
def _run_from_the_package_root(monkeypatch: pytest.MonkeyPatch) -> None:
    # The validation artefacts, fixtures, and evidence matrix are addressed
    # by package-relative path throughout this module.
    monkeypatch.chdir(PACKAGE_ROOT)



INCH_TO_MM = 25.4
PSI_TO_MPA = 0.006894757293168361
KSI_TO_MPA = 1_000.0 * PSI_TO_MPA
PRESSURE_RELATIVE_TOLERANCE = 1.0e-11
PRESSURE_ABSOLUTE_TOLERANCE = 1.0e-10
REQUIRED_EVIDENCE_CATEGORIES = {
    "independent_equation",
    "software_parity",
    "published_theory",
    "experiment",
    "fea",
}


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


def test_independent_reference_has_no_production_imports() -> None:
    reference_path = Path("validation/ring_shell_reference.py")
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
        "validation/non_ring_reference.py",
        "validation/tube_displacement_reference.py",
        "validation/hemisphere_displacement_reference.py",
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


def test_non_ring_inventory_covers_every_golden_and_released_example() -> None:
    evidence = build_non_ring_evidence()
    inventory = NON_RING_COVERAGE_INVENTORY
    expected_case_ids = {
        "tube_underpressure_example_1_failure",
        "tube_lame_intermediates",
        "tube_thin_mean_radius_and_branch_boundary",
        "tube_cli_sizing_golden",
        "tube_worked_component_stresses",
        "tube_radial_displacement_and_axial_strain",
        "hemisphere_membrane_radial_displacement",
        "hemisphere_underpressure_manual_example",
        "hemisphere_cli_and_release_gates",
        "plate_underpressure_example_2_failure",
        "plate_appendix_e_fixed_and_simply_supported",
        "plate_deflection_shear_and_validity_boundaries",
        "plate_fixed_worked_example",
        "smooth_short_lateral_and_hydrostatic",
        "smooth_moderate_and_eq25",
        "smooth_long_and_mid_surface_migration",
        "smooth_gap_overlap_and_applicability_boundaries",
        "smooth_underpressure_example_1_invalid_manual_parity",
        "smooth_underpressure_example_4_valid_overlap",
        "smooth_roark_case20_regime_matrix",
    }
    case_ids = [item["case_id"] for item in inventory]
    assert len(case_ids) == len(set(case_ids))
    assert set(case_ids) == expected_case_ids
    for item in inventory:
        assert item["provenance"] in {
            "independent_equation",
            "independent_equation_plus_manual_display",
            "independent_equation_plus_accepted_manual_4_0_display",
        }
        for artifact in item["artifacts"]:
            assert Path(artifact).exists(), artifact
    assert evidence["published_values"]["underpressure_4_60_capture"] == {
        "status": "open_human_operated_item",
        "accepted_as_4_60_evidence": False,
    }
    assert {
        "source_inputs",
        "published_values",
        "calculated_values",
        "tolerances",
        "comparisons",
    } <= evidence.keys()


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
        force_thick=force_thick,
    )
    released = closed_end_tube_stress(
        external_pressure_mpa=pressure_mpa,
        internal_radius_mm=internal_radius_mm,
        wall_thickness_mm=wall_thickness_mm,
        strength_mpa=yield_strength_mpa,
        material_failure_category="ductile_metal",
        force_thick=force_thick,
    )
    assert released.branch == independent["branch"]
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
        # thin branch, thick branch, the force_thick override, and both sides
        # of the released r_m/t = 10 switch
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
        force_thick=force_thick,
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
    assert released.branch == independent["branch"]
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


def test_tube_displacement_branches_converge_at_the_released_switch() -> None:
    """The thin/thick gap at r_m/t = 10 is the thin-wall error, not drift.

    Two of the branch ratios drop the Poisson ratio entirely, so the
    independent module states them in closed form and production has to
    reproduce them: 1.1025 for the axial strain, the same 10.25% step already
    documented for the equivalent stress, and 1.047375 for the internal-surface
    radial displacement.
    """
    inputs = {
        "external_pressure_mpa": 1.0,
        "wall_thickness_mm": 1.0,
        "strength_mpa": 276.0,
        "material_failure_category": "ductile_metal",
        "elastic_modulus_mpa": 68_900.0,
        "poisson_ratio": 0.33,
    }
    previous_gap = None
    for radius_ratio in (10.0, 20.0, 50.0, 100.0):
        internal_radius = radius_ratio - 0.5
        expected = branch_agreement_reference(
            internal_radius=internal_radius,
            wall_thickness=1.0,
        )
        thick = closed_end_tube_stress(
            **inputs, internal_radius_mm=internal_radius, force_thick=True
        )
        thin = closed_end_tube_stress(
            **inputs, internal_radius_mm=internal_radius * (1.0 + 1.0e-12)
        )
        assert (thick.branch, thin.branch) == ("thick", "thin")

        strain_ratio = thick.axial_strain / thin.axial_strain
        displacement_ratio = (
            thick.stress_states[0].radial_displacement_mm
            / thin.stress_states[0].radial_displacement_mm
        )
        _assert_reference_close(
            strain_ratio, expected["axial_strain_thick_over_thin"]
        )
        _assert_reference_close(
            displacement_ratio,
            expected["internal_surface_displacement_thick_over_thin"],
        )
        gap = abs(strain_ratio - 1.0)
        if previous_gap is not None:
            assert gap < previous_gap
        previous_gap = gap

    assert previous_gap < 0.011


@pytest.mark.parametrize(
    ("pressure", "radius", "thickness", "poisson", "force_thick"),
    [
        # The released hemisphere example, then both sides of the r_m/t = 10
        # switch, the forced-thick override, and both ends of the accepted
        # Poisson range.
        (6.0, 100.0, 100.0 / 39.5, 0.33, False),
        (1.0, 9.5, 1.0, 0.33, False),
        (1.0, 9.500001, 1.0, 0.33, False),
        (6.0, 100.0, 100.0 / 39.5, 0.33, True),
        (2.0, 200.0, 4.0, 0.05, False),
        (2.0, 200.0, 4.0, 0.45, False),
    ],
)
def test_hemisphere_displacement_matches_the_independent_source_transcription(
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
        force_thick=force_thick,
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

    assert released.branch == independent["branch"]
    assert released.displacement_status == (
        "released" if independent["source"] else "withheld_missing_thick_branch_source"
    )
    assert len(released.stress_states) == len(independent["surfaces"])
    for state, surface in zip(
        released.stress_states, independent["surfaces"], strict=True
    ):
        assert state.radius_convention == surface["radius_convention"]
        _assert_reference_close(state.radius_mm, surface["radius"])
        _assert_optional_reference_close(
            state.radial_displacement_mm, surface["radial_displacement"]
        )

    if released.branch == "thin":
        # Eq. (5) states the membrane stress and the displacement on one line.
        # Production has to reproduce that stress, and the transcribed
        # displacement has to be the strain that stress produces.
        membrane = spherical_membrane_reference(
            external_pressure=pressure,
            mean_radius=independent["mean_radius"],
            wall_thickness=thickness,
            elastic_modulus=modulus,
            poisson_ratio=poisson,
        )
        _assert_reference_close(
            released.stress_states[0].hoop_stress_mpa, membrane["membrane_stress"]
        )
        _assert_reference_close(
            membrane["circumferential_strain"],
            membrane["hookean_circumferential_strain"],
        )


def test_hemisphere_and_tube_thin_displacements_reproduce_the_published_ratio() -> None:
    """NASA TM-4579 Eq. (6) links two independently sourced released values.

    The tube's thin displacement comes from DTMB 1497 Eq. [5] and the
    hemisphere's from NASA TM-4579 Eq. (5). Ko publishes their ratio himself as
    ``(2 - nu)/(1 - nu)``, free of pressure, radius, thickness, and modulus, so
    at one shared geometry the two transcriptions have to reproduce it.
    """
    shared = {
        "external_pressure_mpa": 6.0,
        "internal_radius_mm": 100.0,
        "wall_thickness_mm": 100.0 / 39.5,
        "strength_mpa": 276.0,
        "material_failure_category": "ductile_metal",
    }
    for poisson in (0.05, 0.28, 0.45):
        tube = closed_end_tube_stress(
            **shared, elastic_modulus_mpa=68_900.0, poisson_ratio=poisson
        )
        hemisphere = hemispherical_head_external_pressure(
            **shared, elastic_modulus_mpa=68_900.0, poisson_ratio=poisson
        )
        assert (tube.branch, hemisphere.branch) == ("thin", "thin")
        _assert_reference_close(
            tube.stress_states[0].radius_mm, hemisphere.stress_states[0].radius_mm
        )
        _assert_reference_close(
            tube.stress_states[0].radial_displacement_mm
            / hemisphere.stress_states[0].radial_displacement_mm,
            cylinder_to_sphere_ratio_reference(poisson_ratio=poisson),
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
        force_thick=force_thick,
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
    assert released.branch == independent["branch"]
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
    assert released.deflection_status == independent["deflection_status"]
    assert (released.released_maximum_deflection_mm is None) == (
        independent["released_maximum_deflection"] is None
    )
    # The reference computes the Kirchhoff margin unconditionally; production
    # withholds it, as the verdict, wherever the bending validity is violated.
    if released.validity_violations:
        assert released.bending_status == "withheld_applicability"
        assert released.margin is None
    else:
        assert released.bending_status == "released"
        _assert_reference_close(released.margin, independent["margin"])
    assert (
        released.bending_minimum_free_diameter_over_thickness
        == independent["bending_minimum_free_diameter_over_thickness"]
    )
    assert (
        released.deflection_minimum_free_diameter_over_thickness
        == independent["deflection_minimum_free_diameter_over_thickness"]
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
        (released.margin, "margin"),
    ):
        _assert_optional_reference_close(
            actual,
            independent[key],
            rel=1.0e-8 if "beta" in key or "wave_count" in key else REFERENCE_RELATIVE_TOLERANCE,
        )
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
    evidence = build_non_ring_evidence()
    tolerances = evidence["tolerances"]["published_half_displayed_digit"]
    published = evidence["published_values"]
    goldens = published["repo_four_decimal_manual_traceable_goldens_ksi"]
    tube = evidence["calculated_values"]["tube"]
    plate = evidence["calculated_values"]["plate"]

    assert tube["underpressure_example_1_in_ksi_and_in"][
        "theoretical_failure_pressure"
    ] == pytest.approx(
        goldens["tube_example_1_failure"],
        abs=tolerances["repo_four_decimal_golden_ksi"],
    )
    example_2 = plate["underpressure_example_2_in_ksi_and_in"]
    assert example_2["theoretical_failure_pressure"] == pytest.approx(
        goldens["plate_example_2_failure"],
        abs=tolerances["repo_four_decimal_golden_ksi"],
    )
    assert example_2["theoretical_failure_pressure"] == pytest.approx(
        published["underpressure_4_0_example_2_manual_display_failure_ksi"],
        abs=tolerances["manual_display_example_2_failure_ksi"],
    )
    displays = published["underpressure_appendix_e_plate_stresses_psi"]
    simply = plate["appendix_e_simply_supported_in_psi_and_in"]
    fixed = plate["appendix_e_fixed_in_psi_and_in"]
    for actual, display in (
        (simply["maximum_radial_bending_stress"], displays["simply_supported_radial"]),
        (
            simply["maximum_tangential_bending_stress"],
            displays["simply_supported_tangential"],
        ),
        (fixed["maximum_radial_bending_stress"], displays["fixed_radial"]),
        (fixed["maximum_tangential_bending_stress"], displays["fixed_tangential"]),
    ):
        assert actual == pytest.approx(
            display, abs=tolerances["manual_display_whole_psi"]
        )

    hemisphere = evidence["calculated_values"]["hemisphere"][
        "underpressure_manual_in_psi_and_in"
    ]
    hemisphere_displays = published[
        "underpressure_4_0_hemisphere_manual_display_psi"
    ]
    assert hemisphere["governing_von_mises_stress"] == pytest.approx(
        hemisphere_displays["stress_at_1000_psi"],
        abs=tolerances["manual_display_one_decimal_psi"],
    )
    assert hemisphere["theoretical_yield_failure_pressure"] == pytest.approx(
        hemisphere_displays["shell_failure"],
        abs=tolerances["manual_display_one_decimal_psi"],
    )
    assert hemisphere["underpressure_probable_minimum_pressure"] == pytest.approx(
        hemisphere_displays["invalid_thin_wall_buckling"],
        abs=tolerances["manual_display_whole_psi"],
    )
    assert hemisphere["mean_radius_over_thickness"] == 7.5
    assert hemisphere["buckling_capacity_status"] == "withheld_applicability"

    smooth = evidence["calculated_values"]["smooth_cylinder"]
    invalid = smooth["underpressure_example_1_roark_even_though_invalid"]
    assert invalid["probable_minimum_pressure_psi"] == pytest.approx(
        published["underpressure_4_0_example_1_invalid_thin_buckling_psi"],
        abs=tolerances["manual_display_whole_psi"],
    )
    assert invalid["governing_circumferential_nodes"] == 2
    valid = smooth["underpressure_example_4_roark"]
    assert valid["probable_minimum_pressure_psi"] == pytest.approx(
        published["underpressure_4_0_example_4_valid_thin_buckling_psi"],
        abs=tolerances["manual_display_two_decimal_psi"],
    )
    assert valid["governing_circumferential_nodes"] == 3

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


def test_cli_tube_sizing_golden_matches_independent_zero_margin_solve() -> None:
    evidence = build_non_ring_evidence()
    independent_mm = evidence["calculated_values"]["tube"][
        "cli_sizing_zero_margin_thickness_mm"
    ]
    assert independent_mm == pytest.approx(7.83358455, abs=2.0e-8)


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


def test_reference_output_separates_inputs_published_calculated_and_comparisons() -> None:
    from validation.ring_shell_reference import build_evidence

    evidence = build_evidence()
    assert {
        "source_inputs",
        "published_values",
        "calculated_values",
        "tolerances",
        "comparisons",
    } <= evidence.keys()
    assert evidence["classification"]["not"] == [
        "calibration",
        "allowable_pressure",
        "design_approval",
    ]
    calculated_by_frame_spaces = {
        item["frame_spaces"]: item
        for item in evidence["calculated_values"]["dtmb_all_table_2_geometries"]
    }
    for frame_spaces, published_length_over_diameter, *_ in DTMB_TABLE_2_PUBLISHED:
        case = dtmb_case(frame_spaces)
        calculated_length_over_diameter = case.unsupported_length / (
            2.0 * case.shell_mid_surface_radius
        )
        assert calculated_by_frame_spaces[frame_spaces]["length_over_diameter"] == (
            calculated_length_over_diameter
        )
        # DTMB reports two decimals and labels 1.152 in as a typical spacing.
        assert calculated_length_over_diameter == pytest.approx(
            published_length_over_diameter,
            abs=DTMB_LENGTH_DIAMETER_ABSOLUTE_TOLERANCE,
        )


def test_validation_matrix_covers_released_models_versions_and_evidence_paths() -> None:
    matrix_path = Path("validation/evidence_matrix.yaml")
    matrix = yaml.safe_load(matrix_path.read_text(encoding="utf-8"))
    models = matrix["models"]
    expected_models = {
        TUBE_STRESS_MODEL_ID: (TUBE_STRESS_MODEL_VERSION, "verified_equation"),
        FLAT_CIRCULAR_PLATE_MODEL_ID: (
            FLAT_CIRCULAR_PLATE_MODEL_VERSION,
            "verified_equation",
        ),
        HEMISPHERE_MODEL_ID: (
            HEMISPHERE_MODEL_VERSION,
            "verified_equation",
        ),
        SMOOTH_CYLINDER_BUCKLING_MODEL_ID: (
            SMOOTH_CYLINDER_BUCKLING_MODEL_VERSION,
            "verified_equation",
        ),
        RING_SHELL_MODEL_ID: (RING_SHELL_MODEL_VERSION, "benchmark_compared"),
        SUBMERGED_MASS_MODEL_ID: (
            SUBMERGED_MASS_MODEL_VERSION,
            "verified_equation",
        ),
        HYDROSTATIC_PRESSURE_MODEL_ID: (
            HYDROSTATIC_PRESSURE_MODEL_VERSION,
            "verified_equation",
        ),
    }

    model_ids = [model["model_id"] for model in models]
    assert len(model_ids) == len(set(model_ids))
    assert set(model_ids) == expected_models.keys()
    for model in models:
        assert set(model) == {
            "model_id",
            "model_version",
            "maturity",
            "completeness",
            "evidence",
            "important_limitations",
        }
        expected_version, expected_maturity = expected_models[model["model_id"]]
        assert model["model_version"] == expected_version
        assert model["maturity"] == expected_maturity
        assert model["completeness"] == "partial"
        assert model["important_limitations"]
        evidence_categories = [item["category"] for item in model["evidence"]]
        assert len(evidence_categories) == len(set(evidence_categories))
        assert set(evidence_categories) == REQUIRED_EVIDENCE_CATEGORIES
        for item in model["evidence"]:
            assert set(item) == {"category", "source", "status"}
            assert item["status"]
            source = item["source"]
            if not source.startswith(("https://", "http://")):
                assert Path(source.split("#", maxsplit=1)[0]).exists(), source


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# Committed FEA results pinned against silent drift.  A regenerated summary
# must reproduce these solver numbers; runtime and host observations may vary.
TUBE_PLATE_FINEST_FEA = {
    "tube_inner_hoop_psi": -7918.309746586335,
    "tube_outer_hoop_psi": -6918.591919770731,
    "simply_supported_deflection_mm": 0.1287088,
    "simply_supported_center_stress_mpa": 62.09396544358373,
    "fixed_deflection_mm": 0.03569778,
    "fixed_center_stress_mpa": 24.981550573478202,
}
FEA_PINNED_RELATIVE_TOLERANCE = 1.0e-6


# Predeclared before the comparisons ran.  Every acceptance boolean below is
# recomputed from these, so they are pinned here rather than read back out of
# the artifact that they judge.
TUBE_PLATE_FEA_TOLERANCES = {
    "support_reaction_vs_applied_fraction": 0.005,
    "tube_finest_mesh_component_change": 0.005,
    "tube_analytical_component_relative_error": 0.01,
    "plate_finest_mesh_deflection_change": 0.01,
    "plate_finest_mesh_center_stress_change": 0.02,
    "plate_analytical_deflection_relative_error": 0.05,
    "plate_analytical_center_stress_relative_error": 0.05,
}


def test_tube_plate_compact_fea_evidence_is_traceable_and_retains_disagreement() -> None:
    summary = json.loads(
        Path("validation/fea/results/tube_plate_fea_summary.json").read_text(encoding="utf-8")
    )
    assert summary["schema_version"] == "1.2.0"
    assert summary["classification"]["evidence_role"] == (
        "idealized_linear_elastic_fea_equation_comparison"
    )
    assert "calibration" in summary["classification"]["not"]
    # P5-03 takes every analytical target from the independent reference, so
    # the reference is a code input to the committed comparison and is hashed
    # alongside the runner and the pinned container recipe.  No production
    # code is executed by the runner; production-versus-reference parity for
    # the same tube and plate points lives in ordinary live tests.
    assert summary["manifest"] == {
        "runner_sha256": _sha256_file(Path("validation/fea/run_fea.py")),
        "dockerfile_sha256": _sha256_file(
            Path("validation/fea/toolchain/Dockerfile")
        ),
        "reference_sha256": _sha256_file(Path("validation/non_ring_reference.py")),
    }
    assert summary["toolchain"]["calculix_version"] == "2.20"
    assert "gmsh_version" not in summary["toolchain"]
    # Acceptance limits and source inputs come from pinned tables, never from
    # the artifact being judged; the closed-end traction is re-derived from
    # the annular force balance.
    assert summary["tolerances"] == TUBE_PLATE_FEA_TOLERANCES
    assert summary["source_inputs"] == {
        "tube": {
            "source_case": (
                "UnderPressure 4.0 Example 1 committed analytical example"
            ),
            "units": "inch_lbf_psi",
            "geometry": {
                "internal_radius_in": 3.0,
                "wall_thickness_in": 0.470,
                "modeled_length_in": 4.0,
            },
            "load": {
                "external_pressure_psi": 1_000.0,
                "closed_end_axial_traction_psi": pytest.approx(
                    1_000.0 * 3.47**2 / (3.47**2 - 3.0**2), rel=1.0e-12
                ),
            },
            "material": {
                "elastic_modulus_psi": 10_300_000.0,
                "poisson_ratio": 0.33,
            },
        },
        "plates": {
            "source_case": (
                "committed synthetic fixed/simply-supported plate equation case"
            ),
            "units": "mm_n_mpa",
            "geometry": {"free_radius_mm": 50.0, "plate_thickness_mm": 10.0},
            "load": {"uniform_pressure_mpa": 2.0},
            "material": {"elastic_modulus_mpa": 70_000.0, "poisson_ratio": 0.30},
        },
    }
    tube_meshes = summary["meshes"]["tube"]
    simply_meshes = summary["meshes"]["simply_supported"]
    fixed_meshes = summary["meshes"]["fixed"]
    assert len(tube_meshes) == 3
    assert len(simply_meshes) == 3
    assert len(fixed_meshes) == 3

    finest_tube = tube_meshes[-1]["surface_stresses"]
    assert finest_tube["inner_surface"]["hoop_stress_psi"] == pytest.approx(
        TUBE_PLATE_FINEST_FEA["tube_inner_hoop_psi"], rel=FEA_PINNED_RELATIVE_TOLERANCE
    )
    assert finest_tube["outer_surface"]["hoop_stress_psi"] == pytest.approx(
        TUBE_PLATE_FINEST_FEA["tube_outer_hoop_psi"], rel=FEA_PINNED_RELATIVE_TOLERANCE
    )
    assert simply_meshes[-1]["center_deflection_mm"] == pytest.approx(
        TUBE_PLATE_FINEST_FEA["simply_supported_deflection_mm"],
        rel=FEA_PINNED_RELATIVE_TOLERANCE,
    )
    assert simply_meshes[-1]["center_top_surface"][
        "mean_in_plane_bending_stress_mpa"
    ] == pytest.approx(
        TUBE_PLATE_FINEST_FEA["simply_supported_center_stress_mpa"],
        rel=FEA_PINNED_RELATIVE_TOLERANCE,
    )
    assert fixed_meshes[-1]["center_deflection_mm"] == pytest.approx(
        TUBE_PLATE_FINEST_FEA["fixed_deflection_mm"], rel=FEA_PINNED_RELATIVE_TOLERANCE
    )
    assert fixed_meshes[-1]["center_top_surface"][
        "mean_in_plane_bending_stress_mpa"
    ] == pytest.approx(
        TUBE_PLATE_FINEST_FEA["fixed_center_stress_mpa"],
        rel=FEA_PINNED_RELATIVE_TOLERANCE,
    )

    # The stored analytical targets are exactly the compared values, rebuilt
    # from the live independent reference; yield-dependent outputs are not
    # comparison targets and must not be mirrored into this artifact.
    tube_reference = closed_end_tube_reference(
        external_pressure=1_000.0,
        internal_radius=3.0,
        wall_thickness=0.470,
        yield_strength=62_000.0,
    )
    assert summary["independent_calculations"]["tube"] == {
        "branch": tube_reference["branch"],
        "source": tube_reference["source"],
        "stress_states": [
            {
                "radius": state["radius"],
                "radius_convention": state["radius_convention"],
                "radial_stress": state["radial_stress"],
                "hoop_stress": state["hoop_stress"],
                "axial_stress": state["axial_stress"],
            }
            for state in tube_reference["stress_states"]
        ],
    }
    plate_targets = {
        boundary: flat_circular_plate_reference(
            external_pressure=2.0,
            free_radius=50.0,
            plate_thickness=10.0,
            elastic_modulus=70_000.0,
            poisson_ratio=0.30,
            yield_strength=300.0,
            boundary_condition=boundary,  # type: ignore[arg-type]
        )
        for boundary in ("simply_supported", "fixed")
    }
    assert summary["independent_calculations"]["plates"] == {
        boundary: {
            "source_equation_case": target["source_equation_case"],
            "maximum_deflection": target["maximum_deflection"],
            "maximum_tangential_bending_stress": target[
                "maximum_tangential_bending_stress"
            ],
        }
        for boundary, target in plate_targets.items()
    }

    # Reconstruct the whole stored comparison block — per-mesh errors against
    # the live reference and the finest-mesh convergence changes — from the
    # raw solver records, so a stale or hand-edited derived block cannot hide
    # behind the raw data.
    reconstructed_tube = []
    for mesh in tube_meshes:
        locations = {}
        for location, state in zip(
            ("inner_surface", "outer_surface"),
            tube_reference["stress_states"],
            strict=True,
        ):
            fea_state = mesh["surface_stresses"][location]
            locations[location] = {
                "radial_absolute_error_fraction_of_pressure": (
                    abs(fea_state["radial_stress_psi"]) / 1_000.0
                    if state["radial_stress"] == 0.0
                    else abs(
                        fea_state["radial_stress_psi"] / state["radial_stress"]
                        - 1.0
                    )
                ),
                "hoop_relative_error": abs(
                    fea_state["hoop_stress_psi"] / state["hoop_stress"] - 1.0
                ),
                "axial_relative_error": abs(
                    fea_state["axial_stress_psi"] / state["axial_stress"] - 1.0
                ),
            }
        reconstructed_tube.append({"mesh_id": mesh["mesh_id"], "locations": locations})
    assert summary["comparisons"]["tube"] == reconstructed_tube

    reconstructed_plates = {
        boundary: [
            {
                "mesh_id": mesh["mesh_id"],
                "center_deflection_relative_error": abs(
                    mesh["center_deflection_mm"]
                    / plate_targets[boundary]["maximum_deflection"]
                    - 1.0
                ),
                "center_bending_stress_relative_error": abs(
                    mesh["center_top_surface"]["mean_in_plane_bending_stress_mpa"]
                    / plate_targets[boundary]["maximum_tangential_bending_stress"]
                    - 1.0
                ),
            }
            for mesh in meshes
        ]
        for boundary, meshes in (
            ("simply_supported", simply_meshes),
            ("fixed", fixed_meshes),
        )
    }
    assert summary["comparisons"]["plates"] == reconstructed_plates

    def finest_change(values: list[float]) -> float:
        return abs(values[-1] / values[-2] - 1.0)

    reconstructed_convergence = {
        "tube": {
            location: {
                component: finest_change(
                    [
                        mesh["surface_stresses"][location][component]
                        for mesh in tube_meshes
                    ]
                )
                for component in (
                    "radial_stress_psi",
                    "hoop_stress_psi",
                    "axial_stress_psi",
                )
                if not (
                    location == "inner_surface" and component == "radial_stress_psi"
                )
            }
            for location in ("inner_surface", "outer_surface")
        },
        "plates": {
            boundary: {
                "center_deflection_change": finest_change(
                    [mesh["center_deflection_mm"] for mesh in meshes]
                ),
                "center_bending_stress_change": finest_change(
                    [
                        mesh["center_top_surface"][
                            "mean_in_plane_bending_stress_mpa"
                        ]
                        for mesh in meshes
                    ]
                ),
            }
            for boundary, meshes in (
                ("simply_supported", simply_meshes),
                ("fixed", fixed_meshes),
            )
        },
    }
    assert summary["comparisons"]["finest_mesh_change"] == reconstructed_convergence

    # Pinned headline errors: the simply-supported deflection sits inside the
    # 5% budget under the whole-face support, the fixed deflection stays a
    # retained failure.
    simply_deflection_error = reconstructed_plates["simply_supported"][-1][
        "center_deflection_relative_error"
    ]
    fixed_deflection_error = reconstructed_plates["fixed"][-1][
        "center_deflection_relative_error"
    ]
    assert simply_deflection_error == pytest.approx(0.036146, abs=1.0e-5)
    assert fixed_deflection_error == pytest.approx(0.171619, abs=1.0e-5)

    # The discriminating force-balance check compares the tube's unloaded
    # bottom-support reaction resultant against the analytic applied
    # resultant.  Both plate boundary conditions restrain the whole cut face,
    # which includes a pressure-loaded corner node, so the plates carry the
    # corner flag and their global equilibrium residuals instead.
    for mesh in tube_meshes:
        assert mesh["support_reaction_vs_applied_fraction"] <= (
            TUBE_PLATE_FEA_TOLERANCES["support_reaction_vs_applied_fraction"]
        )
    for mesh in (*simply_meshes, *fixed_meshes):
        assert mesh["support_set_includes_pressure_loaded_corner"] is True
        assert mesh["global_equilibrium_residual_fraction"] <= 1.0e-6

    # Every stored acceptance boolean re-derived from the reconstructed
    # errors and the pinned tolerances.
    acceptance = summary["acceptance_evaluation"]
    assert acceptance["tube"] == {
        "finest_mesh_change_pass": all(
            value <= TUBE_PLATE_FEA_TOLERANCES["tube_finest_mesh_component_change"]
            for location in reconstructed_convergence["tube"].values()
            for value in location.values()
        ),
        "analytical_agreement_pass": all(
            value <= TUBE_PLATE_FEA_TOLERANCES["tube_analytical_component_relative_error"]
            for comparison in reconstructed_tube
            for location in comparison["locations"].values()
            for value in location.values()
        ),
        "force_balance_pass": all(
            mesh["support_reaction_vs_applied_fraction"]
            <= TUBE_PLATE_FEA_TOLERANCES["support_reaction_vs_applied_fraction"]
            for mesh in tube_meshes
        ),
    }
    assert all(acceptance["tube"].values())
    for boundary in ("simply_supported", "fixed"):
        convergence = reconstructed_convergence["plates"][boundary]
        finest_errors = reconstructed_plates[boundary][-1]
        assert acceptance["plates"][boundary] == {
            "finest_mesh_deflection_change_pass": (
                convergence["center_deflection_change"]
                <= TUBE_PLATE_FEA_TOLERANCES["plate_finest_mesh_deflection_change"]
            ),
            "finest_mesh_stress_change_pass": (
                convergence["center_bending_stress_change"]
                <= TUBE_PLATE_FEA_TOLERANCES["plate_finest_mesh_center_stress_change"]
            ),
            "analytical_deflection_agreement_pass": (
                finest_errors["center_deflection_relative_error"]
                <= TUBE_PLATE_FEA_TOLERANCES["plate_analytical_deflection_relative_error"]
            ),
            "analytical_stress_agreement_pass": (
                finest_errors["center_bending_stress_relative_error"]
                <= TUBE_PLATE_FEA_TOLERANCES["plate_analytical_center_stress_relative_error"]
            ),
        }
    assert all(acceptance["plates"]["simply_supported"].values())
    assert acceptance["plates"]["fixed"] == {
        "analytical_deflection_agreement_pass": False,
        "analytical_stress_agreement_pass": True,
        "finest_mesh_deflection_change_pass": True,
        "finest_mesh_stress_change_pass": True,
    }
    assert acceptance["all_predeclared_checks_pass"] == (
        all(acceptance["tube"].values())
        and all(
            all(boundary_checks.values())
            for boundary_checks in acceptance["plates"].values()
        )
    )
    assert acceptance["all_predeclared_checks_pass"] is False


# Mesh-converged finest-mesh sweep results pinned against silent drift:
# (boundary, D_free/t, nu) -> (center deflection mm, center stress MPa,
# fixed-edge moment-resultant stress MPa or None).
PLATE_SWEEP_PINNED_FINEST_FEA = {
    ("fixed", 4.0, 0.30): (0.004064516, 4.565804955173373, 5.603768744965592),
    ("fixed", 10.0, 0.30): (0.03569778, 24.981550573478202, 37.13383491306462),
    ("fixed", 10.0, 0.35): (0.03468464, 25.979836737233917, 37.09052342904885),
    ("fixed", 20.0, 0.30): (0.2536582, 98.03672377016498, 149.58945250683752),
    ("fixed", 20.0, 0.35): (0.2448063, 101.7763498360931, 149.59776798655767),
    ("simply_supported", 4.0, 0.30): (0.00974158, 10.131526140033086, None),
    ("simply_supported", 10.0, 0.30): (0.1287088, 62.09396544358373, None),
    ("simply_supported", 10.0, 0.35): (0.1209616, 63.03187316708864, None),
    ("simply_supported", 20.0, 0.30): (1.002609, 247.74121640021988, None),
    ("simply_supported", 20.0, 0.35): (0.9403789, 251.48498409100918, None),
}

PLATE_SWEEP_FREE_RADIUS_MM = 50.0
PLATE_SWEEP_PRESSURE_MPA = 2.0
PLATE_SWEEP_ELASTIC_MODULUS_MPA = 70_000.0
# Predeclared before the sweep ran.  Every acceptance boolean below is
# recomputed from these, so they are pinned here rather than read back out of
# the artifact that they judge.
PLATE_SWEEP_TOLERANCES = {
    "plate_finest_mesh_deflection_change": 0.01,
    "plate_finest_mesh_center_stress_change": 0.02,
    "plate_finest_mesh_edge_stress_change": 0.02,
    "kirchhoff_agreement_budget": 0.05,
}
PLATE_SWEEP_MESH_LADDER = [
    {"radial_elements": 8, "thickness_elements": 2},
    {"radial_elements": 16, "thickness_elements": 4},
    {"radial_elements": 32, "thickness_elements": 8},
]
PLATE_SWEEP_DEEP_MESHES = [
    {"mesh_id": "D1", "radial_elements": 128, "thickness_elements": 32},
    {"mesh_id": "D2", "radial_elements": 256, "thickness_elements": 64},
]
# Per (boundary, output): quantities whose Kirchhoff budget booleans gate that
# output's floor, as (fea key in the mesh/entry records, kirchhoff key).
PLATE_SWEEP_QUANTITIES = {
    "simply_supported": [
        ("center_deflection_mm", "center_deflection_mm", "deflection"),
        (
            "center_bending_stress_mpa",
            "center_tangential_bending_stress_mpa",
            "bending",
        ),
    ],
    "fixed": [
        ("center_deflection_mm", "center_deflection_mm", "deflection"),
        (
            "center_bending_stress_mpa",
            "center_tangential_bending_stress_mpa",
            "bending",
        ),
        ("edge_bending_stress_mpa", "edge_radial_bending_stress_mpa", "bending"),
    ],
}


def _plate_mesh_value(mesh: dict, quantity: str) -> float:
    if quantity == "center_bending_stress_mpa":
        return mesh["center_top_surface"]["mean_in_plane_bending_stress_mpa"]
    return mesh[quantity]


def test_plate_sweep_grounds_the_released_validity_envelope() -> None:
    summary = json.loads(
        Path(
            "validation/fea/results/plate_sweep_fea_summary.json"
        ).read_text(encoding="utf-8")
    )
    assert summary["classification"]["evidence_role"] == (
        "idealized_linear_elastic_fea_equation_comparison"
    )
    assert "calibration" in summary["classification"]["not"]
    # The manifest identifies every code input to the committed thresholds:
    # the runner, the pinned container recipe, and the independent reference
    # that supplies the Kirchhoff targets.  The sweep calls no production
    # code, so the calculation source is not an input.
    assert summary["manifest"] == {
        "runner_sha256": _sha256_file(Path("validation/fea/run_fea.py")),
        "dockerfile_sha256": _sha256_file(
            Path("validation/fea/toolchain/Dockerfile")
        ),
        "reference_sha256": _sha256_file(Path("validation/non_ring_reference.py")),
    }
    assert summary["toolchain"]["calculix_version"] == "2.20"
    assert summary["schema_version"] == "3.0.0"
    # The constants every reconstruction below is built from.
    assert summary["source_inputs"]["held_constant"] == {
        "free_radius_mm": PLATE_SWEEP_FREE_RADIUS_MM,
        "uniform_pressure_mpa": PLATE_SWEEP_PRESSURE_MPA,
        "elastic_modulus_mpa": PLATE_SWEEP_ELASTIC_MODULUS_MPA,
    }
    assert summary["source_inputs"]["mesh_ladder"] == PLATE_SWEEP_MESH_LADDER
    # Acceptance limits come from the predeclared table, never from the
    # artifact being judged; the artifact must agree with it.
    assert summary["tolerances"] == PLATE_SWEEP_TOLERANCES

    cases = {
        (
            float(case["free_diameter_over_thickness"]),
            float(case["poisson_ratio"]),
        ): case
        for case in summary["cases"]
    }
    ratio_grid = sorted({key[0] for key in cases})
    poisson_grid = sorted({key[1] for key in cases})
    assert ratio_grid == [4.0, 6.0, 10.0, 14.0, 20.0, 30.0, 40.0]
    assert poisson_grid == [0.05, 0.30, 0.35]
    assert summary["source_inputs"]["swept"] == {
        "free_diameter_over_thickness": ratio_grid,
        "poisson_ratio": poisson_grid,
    }
    assert len(cases) == len(ratio_grid) * len(poisson_grid)

    # Raw finest-mesh solver values pinned against silent drift.
    for (boundary, ratio, poisson), pinned in PLATE_SWEEP_PINNED_FINEST_FEA.items():
        fea = cases[(ratio, poisson)]["boundaries"][boundary]["finest_mesh_fea"]
        deflection, center_stress, edge_stress = pinned
        assert fea["center_deflection_mm"] == pytest.approx(
            deflection, rel=FEA_PINNED_RELATIVE_TOLERANCE
        )
        assert fea["center_bending_stress_mpa"] == pytest.approx(
            center_stress, rel=FEA_PINNED_RELATIVE_TOLERANCE
        )
        if edge_stress is not None:
            assert fea["edge_bending_stress_mpa"] == pytest.approx(
                edge_stress, rel=FEA_PINNED_RELATIVE_TOLERANCE
            )

    # Reconstruct every derived quantity from the per-mesh solver records and
    # the live independent reference, assert the stored fields match the
    # reconstruction, and collect what the floor derivation needs.  What is
    # left unreconstructed is only what cannot be: raw solver output, content
    # hashes, and host-specific observations such as runtimes.
    tolerances = PLATE_SWEEP_TOLERANCES
    budget = tolerances["kirchhoff_agreement_budget"]
    recomputed_budget_flags: dict[tuple[str, str, float, float], bool] = {}
    recomputed_errors: dict[tuple[str, str, float, float], float] = {}
    estimate_residuals: dict[tuple[str, float, float], float] = {}
    kirchhoff_targets: dict[tuple[str, float, float], dict[str, float]] = {}
    for (ratio, poisson), case in sorted(cases.items()):
        thickness = float(case["plate_thickness_mm"])
        assert thickness == pytest.approx(
            2.0 * PLATE_SWEEP_FREE_RADIUS_MM / ratio, rel=1.0e-12
        )
        assert case["thickness_over_free_radius"] == pytest.approx(
            thickness / PLATE_SWEEP_FREE_RADIUS_MM, rel=1.0e-12
        )
        shear_modulus = PLATE_SWEEP_ELASTIC_MODULUS_MPA / (2.0 * (1.0 + poisson))
        increment = (
            PLATE_SWEEP_PRESSURE_MPA * PLATE_SWEEP_FREE_RADIUS_MM**2
        ) / (4.0 * (5.0 / 6.0) * shear_modulus * thickness)
        assert case["mindlin_shear_increment_mm"] == pytest.approx(
            increment, rel=1.0e-12
        )
        for boundary in ("fixed", "simply_supported"):
            entry = case["boundaries"][boundary]
            meshes = entry["meshes"]
            assert [mesh["mesh_id"] for mesh in meshes] == ["M1", "M2", "M3"]
            # Every case ran the one committed mesh ladder, with the node
            # and element counts that ladder implies for a CAX8R grid.
            assert [
                {
                    "radial_elements": mesh["radial_elements"],
                    "thickness_elements": mesh["thickness_elements"],
                }
                for mesh in meshes
            ] == PLATE_SWEEP_MESH_LADDER
            applied_force = (
                math.pi * PLATE_SWEEP_FREE_RADIUS_MM**2 * PLATE_SWEEP_PRESSURE_MPA
            )
            for mesh in meshes:
                _assert_plate_mesh_row_consistent(
                    mesh,
                    boundary=boundary,
                    thickness=thickness,
                    applied_force=applied_force,
                )
            finest, previous = meshes[-1], meshes[-2]
            # The reported finest-mesh values are the finest mesh records.
            expected_finest_fea = {
                quantity: _plate_mesh_value(finest, quantity)
                for quantity, _, _ in PLATE_SWEEP_QUANTITIES[boundary]
            }
            assert entry["finest_mesh_fea"] == expected_finest_fea
            # Kirchhoff targets from the live reference; convergence changes,
            # headline errors, and every check boolean re-derived per
            # quantity from the raw mesh records.
            reference = flat_circular_plate_reference(
                external_pressure=PLATE_SWEEP_PRESSURE_MPA,
                free_radius=PLATE_SWEEP_FREE_RADIUS_MM,
                plate_thickness=thickness,
                elastic_modulus=PLATE_SWEEP_ELASTIC_MODULUS_MPA,
                poisson_ratio=poisson,
                yield_strength=300.0,
                boundary_condition=boundary,  # type: ignore[arg-type]
            )
            expected_kirchhoff = {
                "center_deflection_mm": reference["maximum_deflection"],
                "center_tangential_bending_stress_mpa": reference[
                    "maximum_tangential_bending_stress"
                ],
                "source_equation_case": reference["source_equation_case"],
                "maximum_deflection_over_thickness": (
                    reference["maximum_deflection"] / thickness
                ),
            }
            if boundary == "fixed":
                expected_kirchhoff["edge_radial_bending_stress_mpa"] = reference[
                    "maximum_radial_bending_stress"
                ]
            assert entry["kirchhoff"] == expected_kirchhoff
            kirchhoff_targets[(boundary, ratio, poisson)] = expected_kirchhoff
            change_keys = {
                "center_deflection_mm": (
                    "center_deflection_change",
                    "plate_finest_mesh_deflection_change",
                    "finest_mesh_deflection_change_pass",
                    "fea_minus_kirchhoff_deflection_fraction",
                    "kirchhoff_deflection_within_budget",
                ),
                "center_bending_stress_mpa": (
                    "center_bending_stress_change",
                    "plate_finest_mesh_center_stress_change",
                    "finest_mesh_center_stress_change_pass",
                    "fea_minus_kirchhoff_center_stress_fraction",
                    "kirchhoff_center_stress_within_budget",
                ),
                "edge_bending_stress_mpa": (
                    "edge_bending_stress_change",
                    "plate_finest_mesh_edge_stress_change",
                    "finest_mesh_edge_stress_change_pass",
                    "fea_minus_kirchhoff_edge_stress_fraction",
                    "kirchhoff_edge_stress_within_budget",
                ),
            }
            bending_within = True
            for quantity, kirchhoff_key, output in PLATE_SWEEP_QUANTITIES[boundary]:
                (
                    change_key,
                    tolerance_key,
                    change_check_key,
                    error_key,
                    budget_check_key,
                ) = change_keys[quantity]
                fine = _plate_mesh_value(finest, quantity)
                coarse = _plate_mesh_value(previous, quantity)
                change = abs(fine / coarse - 1.0)
                assert entry["finest_mesh_change"][change_key] == pytest.approx(
                    change, abs=1.0e-15
                )
                assert entry["checks"][change_check_key] == (
                    change <= tolerances[tolerance_key]
                )
                # With the whole-edge support realization every compared
                # quantity meets its convergence tolerance at every case.
                assert entry["checks"][change_check_key] is True
                target = expected_kirchhoff[kirchhoff_key]
                error = fine / target - 1.0
                assert entry[error_key] == pytest.approx(error, abs=1.0e-12)
                recomputed_errors[(boundary, quantity, ratio, poisson)] = abs(error)
                within = abs(error) <= budget
                assert entry["checks"][budget_check_key] == within
                if output == "bending":
                    bending_within = bending_within and within
                else:
                    recomputed_budget_flags[
                        ("deflection", boundary, ratio, poisson)
                    ] = within
            recomputed_budget_flags[("bending", boundary, ratio, poisson)] = (
                bending_within
            )
            # The shear-corrected estimate block, re-derived from first
            # principles and the raw finest-mesh deflection.
            kirchhoff_deflection = expected_kirchhoff["center_deflection_mm"]
            predicted = kirchhoff_deflection + increment
            fea_deflection = _plate_mesh_value(finest, "center_deflection_mm")
            assert entry["shear_corrected"] == {
                "predicted_center_deflection_mm": pytest.approx(
                    predicted, rel=1.0e-12
                ),
                "predicted_increment_fraction_of_kirchhoff": pytest.approx(
                    increment / kirchhoff_deflection, rel=1.0e-12
                ),
                "fea_minus_predicted_fraction": pytest.approx(
                    fea_deflection / predicted - 1.0, abs=1.0e-12
                ),
            }
            estimate_residuals[(boundary, ratio, poisson)] = (
                fea_deflection / predicted - 1.0
            )

    # Floors re-derived from the recomputed budget flags alone, and the
    # production constants must equal the stored band floors.
    production_floors = {
        "bending": FLAT_CIRCULAR_PLATE_BENDING_MINIMUM_RATIO,
        "deflection": FLAT_CIRCULAR_PLATE_DEFLECTION_MINIMUM_RATIO,
    }
    for boundary in ("fixed", "simply_supported"):
        for output, production in production_floors.items():
            stored = summary["derived_validity_floors"][boundary][output]
            per_poisson: dict[str, float | None] = {}
            for poisson in poisson_grid:
                floor = None
                for index, candidate in enumerate(ratio_grid):
                    if all(
                        recomputed_budget_flags[(output, boundary, ratio, poisson)]
                        for ratio in ratio_grid[index:]
                    ):
                        floor = candidate
                        break
                per_poisson[f"{poisson:g}"] = floor
            assert stored["per_poisson"] == per_poisson
            band_values = list(per_poisson.values())
            band_floor = (
                None
                if any(value is None for value in band_values)
                else max(value for value in band_values if value is not None)
            )
            assert stored["band_floor"] == band_floor
            assert production[boundary] == band_floor
    assert summary["source_inputs"]["poisson_evidence_band"] == list(
        FLAT_CIRCULAR_PLATE_POISSON_EVIDENCE_BAND
    )
    assert min(poisson_grid) == FLAT_CIRCULAR_PLATE_POISSON_EVIDENCE_BAND[0]
    assert max(poisson_grid) == FLAT_CIRCULAR_PLATE_POISSON_EVIDENCE_BAND[1]

    # Releasing the continuous ratio range above each floor relies on the
    # model-form error decreasing monotonically with thinness — the premise
    # code and docs state.  Assert it over the reconstructed absolute errors:
    # every compared quantity, at every solved Poisson value, across the
    # whole solved ratio range.
    for boundary in ("fixed", "simply_supported"):
        for quantity, _, _ in PLATE_SWEEP_QUANTITIES[boundary]:
            for poisson in poisson_grid:
                errors = [
                    recomputed_errors[(boundary, quantity, ratio, poisson)]
                    for ratio in ratio_grid
                ]
                assert all(
                    thicker >= thinner
                    for thicker, thinner in zip(errors, errors[1:], strict=False)
                ), (boundary, quantity, poisson, errors)

    # The shear-corrected estimate summary, re-derived from the per-case
    # residuals.  Production's small-deflection gate reads this estimate, and
    # its stated justification is that the estimate exceeded the solved
    # deflection at every case — assert exactly that.
    for boundary in ("fixed", "simply_supported"):
        residuals = [
            estimate_residuals[(boundary, ratio, poisson)]
            for ratio in ratio_grid
            for poisson in poisson_grid
        ]
        stored = summary["shear_corrected_estimate"][boundary]
        assert stored == {
            "exceeds_finest_mesh_deflection_at_every_solved_case": all(
                residual < 0.0 for residual in residuals
            ),
            "residual_closest_to_zero": pytest.approx(
                max(residuals), abs=1.0e-12
            ),
            "residual_farthest_from_zero": pytest.approx(
                min(residuals), abs=1.0e-12
            ),
        }
        assert stored["exceeds_finest_mesh_deflection_at_every_solved_case"] is True

    # Deep-mesh sensitivity: the decision-bearing primary readings re-solved at
    # four and eight times the finest primary mesh.  Reconstruct every
    # derived value from the raw deep-mesh records; the decision-bearing
    # facts are that the deep values still meet the same convergence
    # tolerances, that no within-budget boolean changes, and that the
    # shear-corrected estimate still exceeds the deepest solved deflection.
    sensitivity = summary["deep_mesh_sensitivity"]
    assert sensitivity["deep_meshes"] == PLATE_SWEEP_DEEP_MESHES
    assert {
        (
            point["boundary_condition"],
            point["free_diameter_over_thickness"],
            point["poisson_ratio"],
        )
        for point in sensitivity["points"]
    } == {
        ("simply_supported", 4.0, 0.05),
        ("simply_supported", 6.0, 0.35),
        ("simply_supported", 10.0, 0.35),
        ("simply_supported", 40.0, 0.05),
        ("fixed", 6.0, 0.35),
        ("fixed", 10.0, 0.35),
        ("fixed", 14.0, 0.35),
        ("fixed", 20.0, 0.35),
        ("fixed", 40.0, 0.05),
    }
    all_deep_changes = []
    all_decisions_unchanged = []
    all_estimate_exceeds = []
    drifts = []
    for point in sensitivity["points"]:
        boundary = point["boundary_condition"]
        ratio = point["free_diameter_over_thickness"]
        poisson = point["poisson_ratio"]
        case_entry = cases[(ratio, poisson)]["boundaries"][boundary]
        thickness = float(cases[(ratio, poisson)]["plate_thickness_mm"])
        deep = point["meshes"]
        assert [
            {
                "mesh_id": mesh["mesh_id"],
                "radial_elements": mesh["radial_elements"],
                "thickness_elements": mesh["thickness_elements"],
            }
            for mesh in deep
        ] == PLATE_SWEEP_DEEP_MESHES
        applied_force = (
            math.pi * PLATE_SWEEP_FREE_RADIUS_MM**2 * PLATE_SWEEP_PRESSURE_MPA
        )
        for mesh in deep:
            _assert_plate_mesh_row_consistent(
                mesh,
                boundary=boundary,
                thickness=thickness,
                applied_force=applied_force,
            )
        targets = kirchhoff_targets[(boundary, ratio, poisson)]
        change_tolerance_keys = {
            "center_deflection_mm": "plate_finest_mesh_deflection_change",
            "center_bending_stress_mpa": "plate_finest_mesh_center_stress_change",
            "edge_bending_stress_mpa": "plate_finest_mesh_edge_stress_change",
        }
        for quantity, kirchhoff_key, _ in PLATE_SWEEP_QUANTITIES[boundary]:
            stored = point["quantities"][quantity]
            primary_value = case_entry["finest_mesh_fea"][quantity]
            deep_values = [_plate_mesh_value(mesh, quantity) for mesh in deep]
            target = targets[kirchhoff_key]
            deepest = deep_values[-1]
            deep_change = abs(deepest / deep_values[-2] - 1.0)
            assert stored == {
                "primary_finest": primary_value,
                "deepest": deepest,
                "deepest_change": pytest.approx(deep_change, abs=1.0e-15),
                "deepest_change_pass": (
                    deep_change
                    <= tolerances[change_tolerance_keys[quantity]]
                ),
                "primary_to_deepest_drift": pytest.approx(
                    abs(deepest / primary_value - 1.0), abs=1.0e-15
                ),
                "fea_minus_kirchhoff_fraction_at_deepest": pytest.approx(
                    deepest / target - 1.0, abs=1.0e-12
                ),
                "within_budget_at_deepest": (
                    abs(deepest / target - 1.0) <= budget
                ),
                "within_budget_at_primary": (
                    abs(primary_value / target - 1.0) <= budget
                ),
            }
            all_deep_changes.append(stored["deepest_change_pass"])
            drifts.append(stored["primary_to_deepest_drift"])
        decisions_unchanged = all(
            point["quantities"][quantity]["within_budget_at_deepest"]
            == point["quantities"][quantity]["within_budget_at_primary"]
            for quantity, _, _ in PLATE_SWEEP_QUANTITIES[boundary]
        )
        assert point["budget_decisions_unchanged_at_deepest"] == decisions_unchanged
        all_decisions_unchanged.append(decisions_unchanged)
        estimate_exceeds = (
            case_entry["shear_corrected"]["predicted_center_deflection_mm"]
            >= point["quantities"]["center_deflection_mm"]["deepest"]
        )
        assert (
            point["shear_corrected_estimate_exceeds_deepest_deflection"]
            == estimate_exceeds
        )
        all_estimate_exceeds.append(estimate_exceeds)
    assert sensitivity["all_deepest_changes_pass"] == all(all_deep_changes)
    assert sensitivity["all_deepest_changes_pass"] is True
    assert sensitivity["all_budget_decisions_unchanged"] == all(
        all_decisions_unchanged
    )
    assert sensitivity["all_budget_decisions_unchanged"] is True
    assert sensitivity[
        "shear_corrected_estimate_exceeds_deepest_deflection_at_every_point"
    ] == all(all_estimate_exceeds)
    assert sensitivity[
        "shear_corrected_estimate_exceeds_deepest_deflection_at_every_point"
    ] is True
    assert sensitivity["maximum_primary_to_deepest_drift"] == pytest.approx(
        max(drifts), abs=1.0e-15
    )

    # The (D_free/t = 10, nu = 0.30) sweep point is the committed P5-03 plate
    # case: the two evidence files must share identical decks and identical
    # solver output, so they cannot drift apart.
    tube_plate = json.loads(
        Path("validation/fea/results/tube_plate_fea_summary.json").read_text(encoding="utf-8")
    )
    for boundary in ("fixed", "simply_supported"):
        for sweep_mesh, tube_plate_mesh in zip(
            cases[(10.0, 0.30)]["boundaries"][boundary]["meshes"],
            tube_plate["meshes"][boundary],
            strict=True,
        ):
            assert sweep_mesh["input_sha256"] == tube_plate_mesh["input_sha256"]
            assert sweep_mesh["dat_sha256"] == tube_plate_mesh["dat_sha256"]

    # The margin-governing fixed-edge stress is conservative at the floor:
    # Kirchhoff over-predicts the convergent reaction-moment resultant.
    for poisson in poisson_grid:
        floor_entry = cases[(10.0, poisson)]["boundaries"]["fixed"]
        assert floor_entry["fea_minus_kirchhoff_edge_stress_fraction"] < 0.0

    # Predeclared budget checks that failed are retained rather than tuned
    # away: both floors' last-outside ratios stay committed as failures.  The
    # fixed bending comparison at D_free/t = 6 is inside the budget at
    # nu = 0.05 — its per-Poisson floor there is 6 — and the band floor of 10
    # comes from the failures at nu >= 0.30.
    for poisson in poisson_grid:
        assert recomputed_budget_flags[
            ("deflection", "simply_supported", 6.0, poisson)
        ] is False
        assert recomputed_budget_flags[
            ("deflection", "fixed", 14.0, poisson)
        ] is False
    for poisson in (0.30, 0.35):
        assert recomputed_budget_flags[("bending", "fixed", 6.0, poisson)] is False
    assert recomputed_budget_flags[("bending", "fixed", 6.0, 0.05)] is True


def _assert_plate_mesh_row_consistent(
    mesh: dict,
    *,
    boundary: str,
    thickness: float,
    applied_force: float,
) -> None:
    """Re-derive every derivable field of one raw plate mesh record."""

    assert mesh["element_type"] == "CAX8R"
    assert mesh["applied_transverse_force_n"] == pytest.approx(
        applied_force, rel=1.0e-12
    )
    radial, through = mesh["radial_elements"], mesh["thickness_elements"]
    assert mesh["elements"] == radial * through
    # Eight-node quadrilaterals: a full node grid less the suppressed
    # element centers.
    assert mesh["nodes"] == (2 * radial + 1) * (2 * through + 1) - (radial * through)
    # The compared center stress is a combination of the two stored surface
    # components.
    surface = mesh["center_top_surface"]
    assert surface["mean_in_plane_bending_stress_mpa"] == pytest.approx(
        (
            abs(surface["radial_bending_stress_mpa"])
            + abs(surface["hoop_bending_stress_mpa"])
        )
        / 2.0,
        rel=1.0e-12,
    )
    # Both boundary conditions restrain the whole cut face, which includes a
    # pressure-loaded corner node, so no clean reaction-vs-applied check
    # exists; the solver self-consistency check is the global equilibrium
    # residual.
    assert mesh["support_set_includes_pressure_loaded_corner"] is True
    assert mesh["global_equilibrium_residual_fraction"] <= 1.0e-6
    if boundary == "fixed":
        # The edge stress is a pure unit conversion of the stored
        # reaction-moment resultant.
        per_length = mesh["edge_radial_reaction_moment_full_circle_n_mm"] / (
            2.0 * math.pi * PLATE_SWEEP_FREE_RADIUS_MM
        )
        assert mesh["edge_bending_moment_n_mm_per_mm"] == pytest.approx(
            per_length, rel=1.0e-12
        )
        assert mesh["edge_bending_stress_mpa"] == pytest.approx(
            6.0 * abs(per_length) / thickness**2, rel=1.0e-12
        )
    else:
        assert "edge_bending_stress_mpa" not in mesh


RING_PINNED_EIGENVALUES_PSI = {
    "17": (546.0135, 459.4706, 460.8971),
    "33": (286.6654, 256.9971, 257.5255),
}
RING_PINNED_SERIES = {
    17: (460.8971, 1, 3),
    21: (433.6536, 1, 3),
    23: (428.3907, 1, 3),
    25: (390.5252, 1, 2),
    26: (362.4451, 1, 2),
    27: (338.9346, 1, 2),
    28: (319.1777, 1, 2),
    29: (302.5152, 1, 2),
    31: (276.44, 1, 2),
    33: (257.5255, 1, 2),
}


def test_ring_eigenvalue_compact_fea_evidence_is_partial_and_uncalibrated() -> None:
    summary = json.loads(
        Path("validation/fea/results/ring_shell_eigenvalue_fea_summary.json").read_text(encoding="utf-8")
    )
    assert summary["schema_version"] == "1.2.0"
    assert summary["classification"]["evidence_role"] == (
        "idealized_linear_eigenvalue_fea_equation_comparison"
    )
    assert "calibration" in summary["classification"]["not"]
    # P5-04 compares against the independent ring reference only, so the
    # reference is a code input and is hashed with the runner and the pinned
    # container recipe.  No production code is executed by the runner;
    # production-versus-reference parity for the DTMB geometries lives in
    # ordinary live tests.
    assert summary["manifest"] == {
        "runner_sha256": _sha256_file(Path("validation/fea/run_fea.py")),
        "dockerfile_sha256": _sha256_file(
            Path("validation/fea/toolchain/Dockerfile")
        ),
        "ring_reference_sha256": _sha256_file(
            Path("validation/ring_shell_reference.py")
        ),
    }
    assert summary["status"]["p5_04_complete"] is False
    assert summary["status"]["RS-EIG-SERIES"] == (
        "executed_at_finest_primary_mesh"
    )
    assert summary["status"]["RS-EIG-17-J0"].startswith("blocked:")
    assert summary["status"]["RS-GNL-17"].startswith("blocked:")
    assert summary["status"]["RS-GNL-33"].startswith("blocked:")
    for frame_spaces, expected_mode in (("17", (1, 3)), ("33", (1, 2))):
        case = summary["cases"][frame_spaces]
        assert len(case["meshes"]) == 3
        assert case["convergence"]["declared_checks_pass"] is True
        assert tuple(case["convergence"]["finest_mode"][:2]) == expected_mode
        for mesh, pinned in zip(
            case["meshes"],
            RING_PINNED_EIGENVALUES_PSI[frame_spaces],
            strict=True,
        ):
            assert mesh["governing_global_mode"][
                "eigenvalue_pressure_psi"
            ] == pytest.approx(pinned, rel=FEA_PINNED_RELATIVE_TOLERANCE)
            assert mesh["solver_warning_count"] == 0
            assert mesh["unit_static_pressure_orientation"] == "inward"
            assert mesh["end_axial_force_error_fraction"] <= 0.005
            applied = mesh["applied_closed_end_force_lbf"]
            assert (
                max(
                    abs(mesh["left_end_axial_force_lbf"] - applied),
                    abs(mesh["right_end_axial_force_lbf"] + applied),
                )
                / applied
            ) == pytest.approx(mesh["end_axial_force_error_fraction"], rel=1.0e-9)

        # Recompute the headline comparison from the pinned finest eigenvalue
        # and a live independent equation solve.
        live_equation = solve_case(
            dtmb_case(int(frame_spaces))
        ).with_ring_torsion.ideal_critical_pressure
        comparison = case["comparison"]
        assert comparison["independent_equation_ideal_pressure_psi"] == pytest.approx(
            live_equation, rel=1.0e-9
        )
        finest = case["meshes"][-1]["governing_global_mode"][
            "eigenvalue_pressure_psi"
        ]
        assert comparison["fea_minus_independent_percent"] == pytest.approx(
            100.0 * (finest - live_equation) / live_equation, rel=1.0e-9
        )
    assert summary["cases"]["17"]["comparison"][
        "fea_minus_independent_percent"
    ] == pytest.approx(-14.339, abs=0.001)
    assert summary["cases"]["33"]["comparison"][
        "fea_minus_independent_percent"
    ] == pytest.approx(0.584, abs=0.001)

    assert [item["frame_spaces"] for item in summary["series"]] == [
        row[0] for row in DTMB_TABLE_2_PUBLISHED
    ]
    for row in summary["series"]:
        pinned_psi, pinned_m, pinned_n = RING_PINNED_SERIES[row["frame_spaces"]]
        assert len(row["dat_sha256"]) == 64
        assert row["solver_warning_count"] == 0
        assert row["end_axial_force_error_fraction"] <= 0.005
        assert row["fea_ideal_pressure_psi"] == pytest.approx(
            pinned_psi, rel=FEA_PINNED_RELATIVE_TOLERANCE
        )
        assert row["fea_axial_half_waves_m"] == pinned_m
        assert row["fea_circumferential_lobes_n"] == pinned_n
        live_equation = solve_case(
            dtmb_case(row["frame_spaces"])
        ).with_ring_torsion.ideal_critical_pressure
        assert row["independent_ideal_pressure_psi"] == pytest.approx(
            live_equation, rel=1.0e-9
        )
        assert row["fea_minus_independent_percent"] == pytest.approx(
            100.0 * (row["fea_ideal_pressure_psi"] - live_equation) / live_equation,
            rel=1.0e-6,
        )
        assert row["mode_families_match"] is (
            (pinned_m, pinned_n)
            == (
                row["independent_axial_half_waves_m"],
                row["independent_circumferential_lobes_n"],
            )
        )


def test_fea_directory_contains_no_heavy_solver_databases() -> None:
    prohibited_suffixes = {".12d", ".cvg", ".dat", ".frd", ".sta"}
    leaked = [
        path
        for path in Path("validation/fea").rglob("*")
        if path.is_file() and path.suffix in prohibited_suffixes
    ]
    assert leaked == []


def test_evidence_matrix_pins_executed_fea_and_advisory_ring_status() -> None:
    matrix = yaml.safe_load(
        Path("validation/evidence_matrix.yaml").read_text(encoding="utf-8")
    )
    by_model = {model["model_id"]: model for model in matrix["models"]}
    tube_evidence = {
        item["category"]: item
        for item in by_model[TUBE_STRESS_MODEL_ID]["evidence"]
    }
    plate_evidence = {
        item["category"]: item
        for item in by_model[FLAT_CIRCULAR_PLATE_MODEL_ID]["evidence"]
    }
    assert tube_evidence["fea"]["status"].startswith(
        "three meshes converged, all checks pass"
    )
    # The executed tube FEA compared the stress field only; the displacement
    # quantities released later have no FEA comparison behind them.
    assert "no displacement comparison" in tube_evidence["fea"]["status"]
    assert plate_evidence["fea"]["source"] == (
        "validation/fea/results/plate_sweep_fea_summary.json"
    )
    assert "144 solves" in plate_evidence["fea"]["status"]
    assert "reaction-moment resultant" in plate_evidence["fea"]["status"]
    assert "mesh-converged" in plate_evidence["fea"]["status"]
    ring_evidence = {
        item["category"]: item
        for item in by_model[RING_SHELL_MODEL_ID]["evidence"]
    }
    assert ring_evidence["fea"]["status"] == (
        "eigenvalue cases executed and converged, nonlinear open"
    )
    assert by_model[RING_SHELL_MODEL_ID]["maturity"] == "benchmark_compared"
    assert by_model[RING_SHELL_MODEL_ID]["completeness"] == "partial"
