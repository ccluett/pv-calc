from __future__ import annotations

import pytest

from validation.published.dtmb_1324_case17 import (
    EXPECTED_PRIMARY_ADJUSTED_PSI,
    EXPECTED_PRIMARY_AXIAL_HALF_WAVES,
    EXPECTED_PRIMARY_CIRCUMFERENTIAL_LOBES,
    EXPECTED_PRIMARY_IDEAL_PSI,
    solve_case,
)


def test_dtmb_case17_primary_pressure_and_mode_regression() -> None:
    result = solve_case(17)
    global_result = result.global_with_ring_torsion

    assert global_result.ideal_critical_pressure_mpa / 0.006894757293168361 == pytest.approx(
        EXPECTED_PRIMARY_IDEAL_PSI,
        abs=1e-6,
    )
    assert global_result.adjusted_critical_pressure_mpa / 0.006894757293168361 == pytest.approx(
        EXPECTED_PRIMARY_ADJUSTED_PSI, abs=1e-6
    )
    assert global_result.critical_axial_half_waves_m == EXPECTED_PRIMARY_AXIAL_HALF_WAVES
    assert global_result.critical_circumferential_lobes_n == EXPECTED_PRIMARY_CIRCUMFERENTIAL_LOBES
    assert result.capacity_status == "advisory"
