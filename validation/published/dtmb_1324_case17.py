"""Run DTMB Report 1324 rectangular-ring cases through the public model.

Execute from the ``pv-calc`` directory:

    uv run python validation/published/dtmb_1324_case17.py

Every pressure is an equation comparison, not a calibration or acceptance
criterion.  The script raises on numerical, mode, section-mapping, or
convergence drift before printing deterministic JSON.
"""

from __future__ import annotations

import json
import math
import sys
from dataclasses import asdict
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[2]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pv_calc.pressure_vessel import (  # noqa: E402
    RingShellResult,
    ring_stiffened_shell_external_pressure,
)


INCH_TO_MM = 25.4
PSI_TO_MPA = 0.006894757293168361
REPORTED_ID_IN = 8.118
SHELL_THICKNESS_IN = 0.035
RING_SPACING_IN = 1.152
RING_WIDTH_IN = 0.086
RING_HEIGHT_IN = 0.169
YOUNGS_MODULUS_PSI = 30_000_000.0
POISSON_RATIO = 0.3
YIELD_STRENGTH_PSI = 85_000.0
PRESSURE_TOLERANCE_PSI = 1.0e-5

# Source values are exactly the displayed DTMB Table 2 entries.  This
# production-coupled regression is independently cross-checked by
# validation/ring_shell_reference.py.
DTMB_TABLE_2_CASES = (
    (17, 2.40, 428, 3, 473, 3, 538.0498670238468, 403.5374002678851, 3),
    (21, 2.96, 404, 3, 422, 3, 450.231290, 337.673467, 2),
    (23, 3.25, 367, 2, 412, 3, 379.260498, 284.445374, 2),
    (25, 3.53, 305, 2, 401, 3, 332.941745, 249.706309, 2),
    (26, 3.67, 281, 2, 398, 3, 315.958153, 236.968615, 2),
    (27, 3.81, 262, 2, 394, 3, 302.000355, 226.500267, 2),
    (28, 3.96, 246, 2, 391, 3, 290.474668, 217.856001, 2),
    (29, 4.10, 233, 2, 383, 2, 280.915571, 210.686678, 2),
    (31, 4.38, 212, 2, 329, 2, 266.302759, 199.727069, 2),
    (33, 4.66, 197, 2, 281, 2, 256.031046, 192.023284, 2),
)

EXPECTED_PRIMARY_IDEAL_WITHOUT_TORSION_PSI = 536.5437225615963
EXPECTED_PRIMARY_ADJUSTED_WITHOUT_TORSION_PSI = 402.4077919211972
EXPECTED_PRIMARY_IDEAL_PSI = DTMB_TABLE_2_CASES[0][6]
EXPECTED_PRIMARY_ADJUSTED_PSI = DTMB_TABLE_2_CASES[0][7]
EXPECTED_PRIMARY_AXIAL_HALF_WAVES = 1
EXPECTED_PRIMARY_CIRCUMFERENTIAL_LOBES = 3


def percent_difference(value: float, reference: float) -> float:
    return 100.0 * (value - reference) / reference


def solve_case(frame_spaces: int, *, external_pressure_psi: float = 1.0) -> RingShellResult:
    return ring_stiffened_shell_external_pressure(
        external_pressure_mpa=external_pressure_psi * PSI_TO_MPA,
        shell_mid_surface_radius_mm=(
            REPORTED_ID_IN * INCH_TO_MM / 2.0
            + SHELL_THICKNESS_IN * INCH_TO_MM / 2.0
        ),
        wall_thickness_mm=SHELL_THICKNESS_IN * INCH_TO_MM,
        unsupported_length_mm=frame_spaces * RING_SPACING_IN * INCH_TO_MM,
        ring_spacing_mm=RING_SPACING_IN * INCH_TO_MM,
        ring_axial_width_mm=RING_WIDTH_IN * INCH_TO_MM,
        ring_radial_height_mm=RING_HEIGHT_IN * INCH_TO_MM,
        ring_location="external",
        elastic_modulus_mpa=YOUNGS_MODULUS_PSI * PSI_TO_MPA,
        poisson_ratio=POISSON_RATIO,
        yield_strength_mpa=YIELD_STRENGTH_PSI * PSI_TO_MPA,
    )


def _assert_pressure(actual_mpa: float | None, expected_psi: float, label: str) -> None:
    if actual_mpa is None or not math.isclose(
        actual_mpa / PSI_TO_MPA,
        expected_psi,
        rel_tol=0.0,
        abs_tol=PRESSURE_TOLERANCE_PSI,
    ):
        raise AssertionError(
            f"{label} drift: actual={actual_mpa!r} MPa, expected={expected_psi!r} psi"
        )


def build_results() -> dict[str, Any]:
    case_records: list[dict[str, Any]] = []
    primary: RingShellResult | None = None
    for (
        spaces,
        published_length_diameter,
        kendrick_psi,
        kendrick_n,
        experiment_psi,
        experiment_n,
        expected_ideal_psi,
        expected_adjusted_psi,
        expected_model_n,
    ) in DTMB_TABLE_2_CASES:
        result = solve_case(spaces, external_pressure_psi=experiment_psi)
        global_result = result.global_with_ring_torsion
        if not global_result.converged:
            raise AssertionError(f"{spaces}-space mode search did not converge")
        _assert_pressure(global_result.ideal_critical_pressure_mpa, expected_ideal_psi, f"{spaces} ideal")
        _assert_pressure(
            global_result.adjusted_critical_pressure_mpa,
            expected_adjusted_psi,
            f"{spaces} adjusted",
        )
        if (
            global_result.critical_axial_half_waves_m,
            global_result.critical_circumferential_lobes_n,
        ) != (1, expected_model_n):
            raise AssertionError(f"{spaces}-space governing-mode drift")
        case_records.append(
            {
                "frame_spaces": spaces,
                "published_length_over_diameter": published_length_diameter,
                "published_kendrick_pressure_psi": kendrick_psi,
                "published_kendrick_lobes_n": kendrick_n,
                "published_experiment_pressure_psi": experiment_psi,
                "published_experiment_lobes_n": experiment_n,
                "model_ideal_pressure_psi": global_result.ideal_critical_pressure_mpa / PSI_TO_MPA,
                "model_adjusted_pressure_psi": global_result.adjusted_critical_pressure_mpa / PSI_TO_MPA,
                "model_axial_half_waves_m": global_result.critical_axial_half_waves_m,
                "model_circumferential_lobes_n": global_result.critical_circumferential_lobes_n,
                "adjusted_difference_vs_kendrick_percent": percent_difference(
                    global_result.adjusted_critical_pressure_mpa / PSI_TO_MPA,
                    kendrick_psi,
                ),
                "adjusted_difference_vs_experiment_percent": percent_difference(
                    global_result.adjusted_critical_pressure_mpa / PSI_TO_MPA,
                    experiment_psi,
                ),
                "mode_search_termination_reason": global_result.termination_reason,
                "mode_search_bounds": [
                    global_result.evaluated_axial_half_waves,
                    global_result.evaluated_circumferential_lobes,
                ],
            }
        )
        if spaces == 17:
            primary = result

    if primary is None:
        raise AssertionError("missing primary DTMB case")
    no_torsion = primary.global_without_ring_torsion
    _assert_pressure(
        no_torsion.ideal_critical_pressure_mpa,
        EXPECTED_PRIMARY_IDEAL_WITHOUT_TORSION_PSI,
        "case 17 no-torsion ideal",
    )
    _assert_pressure(
        no_torsion.adjusted_critical_pressure_mpa,
        EXPECTED_PRIMARY_ADJUSTED_WITHOUT_TORSION_PSI,
        "case 17 no-torsion adjusted",
    )
    return {
        "benchmark": "DTMB Report 1324 Figure 2 and Table 2 rectangular-ring cases",
        "source_record": "https://dome.mit.edu/handle/1721.3/48982",
        "source_pdf_sha256": "975aaf2ef7f4b0adde9cd15dd8dc5ea378e91e097d5f145d60923aeeede728a2",
        "public_geometry_path": "solid_rectangle",
        "radius_convention": primary.radius_convention,
        "section_properties": {
            "area_mm2": primary.ring_area_mm2,
            "centroid_from_shell_surface_mm": primary.ring_centroid_from_shell_surface_mm,
            "centroidal_inertia_mm4": primary.ring_centroidal_inertia_mm4,
            "saint_venant_torsional_constant_mm4": primary.ring_torsional_constant_mm4,
            "eccentricity_from_shell_mid_surface_mm": (
                primary.ring_eccentricity_from_shell_mid_surface_mm
            ),
        },
        "case17_torsion_isolation": {
            "ideal_without_torsion_psi": no_torsion.ideal_critical_pressure_mpa / PSI_TO_MPA,
            "adjusted_without_torsion_psi": no_torsion.adjusted_critical_pressure_mpa / PSI_TO_MPA,
            "ideal_with_torsion_psi": primary.global_with_ring_torsion.ideal_critical_pressure_mpa / PSI_TO_MPA,
            "adjusted_with_torsion_psi": primary.global_with_ring_torsion.adjusted_critical_pressure_mpa / PSI_TO_MPA,
            "ideal_torsion_effect_psi": primary.torsion_ideal_pressure_effect_mpa / PSI_TO_MPA,
            "adjusted_torsion_effect_psi": primary.torsion_adjusted_pressure_effect_mpa / PSI_TO_MPA,
            "governing_mode_changed": primary.torsion_changes_governing_mode,
        },
        "published_cases": case_records,
        "mode_dispositions": [asdict(item) for item in primary.mode_dispositions],
        "regression_status": "passed",
    }


def main() -> None:
    print(json.dumps(build_results(), indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
