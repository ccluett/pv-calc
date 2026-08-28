"""Inventory mapping non-ring evidence cases to repository artifacts.

Split out of ``non_ring_reference.py`` so that moving a test or example
changes only this file, never the pinned hash of the reference
implementation the FEA summaries record as ``reference_sha256``.

Artifact paths are relative to the ``pv-calc`` directory. Worked-fixture
and manual-display cases map to the tests that re-verify their values
against the independent reference.
"""

from __future__ import annotations


NON_RING_COVERAGE_INVENTORY = [
    {
        "case_id": "tube_underpressure_example_1_failure",
        "artifacts": [
            "tests/test_tube_stress.py",
            "tests/test_cli_forward.py",
            "examples/tube_9_0401_ksi.json",
        ],
        "provenance": "independent_equation_plus_manual_display",
    },
    {
        "case_id": "tube_lame_intermediates",
        "artifacts": ["tests/test_tube_stress.py"],
        "provenance": "independent_equation",
    },
    {
        "case_id": "tube_thin_mean_radius_and_branch_boundary",
        "artifacts": ["tests/test_tube_stress.py"],
        "provenance": "independent_equation",
    },
    {
        "case_id": "tube_cli_sizing_golden",
        "artifacts": ["tests/test_cli_sizing.py"],
        "provenance": "independent_equation",
    },
    {
        "case_id": "tube_worked_component_stresses",
        "artifacts": ["tests/test_independent_reference_parity.py"],
        "provenance": "independent_equation",
    },
    {
        "case_id": "tube_radial_displacement_and_axial_strain",
        "artifacts": [
            "validation/tube_displacement_reference.py",
            "validation/sources/tube_scalar_displacement.md",
            "tests/test_tube_stress.py",
            "tests/test_independent_reference_parity.py",
            "tests/test_cli_forward.py",
        ],
        "provenance": "independent_equation",
    },
    {
        "case_id": "hemisphere_membrane_radial_displacement",
        "artifacts": [
            "validation/hemisphere_displacement_reference.py",
            "validation/sources/hemisphere_scalar_displacement.md",
            "tests/test_hemisphere.py",
            "tests/test_independent_reference_parity.py",
            "tests/test_cli_forward.py",
        ],
        "provenance": "independent_equation",
    },
    {
        "case_id": "hemisphere_underpressure_manual_example",
        "artifacts": [
            "tests/test_independent_reference_parity.py",
            "validation/published/underpressure_hemisphere_example.md",
        ],
        "provenance": "independent_equation_plus_accepted_manual_4_0_display",
    },
    {
        "case_id": "hemisphere_cli_and_release_gates",
        "artifacts": [
            "tests/test_independent_reference_parity.py",
            "tests/test_cli_forward.py",
            "examples/hemisphere_subsea_screen.json",
        ],
        "provenance": "independent_equation",
    },
    {
        "case_id": "plate_underpressure_example_2_failure",
        "artifacts": [
            "tests/test_flat_circular_plate.py",
            "tests/test_cli_forward.py",
            "examples/plate_9_0384_ksi.json",
            "validation/published/underpressure_example2_flat_plate.md",
        ],
        "provenance": "independent_equation_plus_manual_display",
    },
    {
        "case_id": "plate_appendix_e_fixed_and_simply_supported",
        "artifacts": ["tests/test_flat_circular_plate.py"],
        "provenance": "independent_equation_plus_manual_display",
    },
    {
        "case_id": "plate_deflection_shear_and_validity_boundaries",
        "artifacts": ["tests/test_flat_circular_plate.py"],
        "provenance": "independent_equation",
    },
    {
        "case_id": "plate_fixed_worked_example",
        "artifacts": ["tests/test_independent_reference_parity.py"],
        "provenance": "independent_equation",
    },
    {
        "case_id": "smooth_short_lateral_and_hydrostatic",
        "artifacts": [
            "tests/test_smooth_cylinder_buckling.py",
            "examples/smooth_buckling_short_nasa.json",
        ],
        "provenance": "independent_equation",
    },
    {
        "case_id": "smooth_moderate_and_eq25",
        "artifacts": [
            "tests/test_smooth_cylinder_buckling.py",
            "examples/smooth_buckling_moderate_nasa.json",
        ],
        "provenance": "independent_equation",
    },
    {
        "case_id": "smooth_long_and_mid_surface_migration",
        "artifacts": [
            "tests/test_smooth_cylinder_buckling.py",
            "tests/test_independent_reference_parity.py",
            "examples/smooth_buckling_long_nasa.json",
        ],
        "provenance": "independent_equation",
    },
    {
        "case_id": "smooth_gap_overlap_and_applicability_boundaries",
        "artifacts": ["tests/test_smooth_cylinder_buckling.py"],
        "provenance": "independent_equation",
    },
    {
        "case_id": "smooth_underpressure_example_1_invalid_manual_parity",
        "artifacts": ["tests/test_independent_reference_parity.py"],
        "provenance": "independent_equation_plus_accepted_manual_4_0_display",
    },
    {
        "case_id": "smooth_underpressure_example_4_valid_overlap",
        "artifacts": [
            "tests/fixtures/software_parity/underpressure_example4_tube_buckling.yaml",
            "validation/published/underpressure_example4_smooth_buckling.md",
            "tests/test_smooth_cylinder_buckling.py",
            "tests/test_independent_reference_parity.py",
        ],
        "provenance": "independent_equation_plus_manual_display",
    },
    {
        "case_id": "smooth_roark_case20_regime_matrix",
        "artifacts": [
            "tests/fixtures/software_parity/roark_table35_case20_overlap.yaml",
            "tests/test_smooth_cylinder_buckling.py",
            "tests/test_independent_reference_parity.py",
        ],
        "provenance": "independent_equation",
    },
]
