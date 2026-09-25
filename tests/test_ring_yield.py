"""Shell and ring mean hoop yield pressures of the ring-stiffened shell model."""

from __future__ import annotations

import pytest

from pv_calc.api import calculate
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.presentation import render_text, summarize_response
from pv_calc.pressure_vessel import (
    RING_SHELL_YIELD_NOTE,
    RingShellResult,
    ring_stiffened_shell_external_pressure,
)


GEOMETRY = dict(
    shell_mid_surface_radius_mm=274.5,
    wall_thickness_mm=2.38,
    unsupported_length_mm=950.0,
    ring_spacing_mm=100.0,
    ring_axial_width_mm=3.88,
    ring_radial_height_mm=25.0,
    ring_location="external",
)


def _case(**overrides) -> RingShellResult:
    """A thin steel shell with external flat-bar rings and long bays."""
    inputs = dict(
        external_pressure_mpa=1.0,
        elastic_modulus_mpa=218_800.0,
        poisson_ratio=0.3,
        yield_strength_mpa=288.3,
        **GEOMETRY,
    )
    inputs.update(overrides)
    return ring_stiffened_shell_external_pressure(**inputs)


def _response(yield_strength_mpa: float | None) -> dict:
    properties = {
        "failure_category": "ductile_metal",
        "elastic_modulus": {"value": 218_800.0, "unit": "MPa"},
        "poisson_ratio": 0.3,
    }
    if yield_strength_mpa is not None:
        properties["yield_strength"] = {"value": yield_strength_mpa, "unit": "MPa"}
    return calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "ring-shell",
        "inputs": {
            "external_pressure": {"value": 1.0, "unit": "MPa"},
            "shell_mid_surface_radius": {"value": 274.5, "unit": "mm"},
            "wall_thickness": {"value": 2.38, "unit": "mm"},
            "unsupported_length": {"value": 950.0, "unit": "mm"},
            "ring_spacing": {"value": 100.0, "unit": "mm"},
            "ring_axial_width": {"value": 3.88, "unit": "mm"},
            "ring_radial_height": {"value": 25.0, "unit": "mm"},
            "ring_location": "external",
        },
        "material": {"type": "explicit", "name": "Test steel", "properties": properties},
    })


def test_yield_pressures_are_reported_beside_the_buckling_minimum():
    result = _case()

    assert result.shell_yield_between_rings_pressure_mpa == pytest.approx(
        2.486631095097233, rel=1e-12
    )
    assert result.ring_yield_pressure_mpa == pytest.approx(5.66939427151082, rel=1e-12)
    # Pc5 is below every mode pressure here. The lowest is axisymmetric
    # collapse, which carries Lunchick's plastic reserve above first yield.
    assert result.advisory_candidate_modes == (
        "global_eq64_with_eq91_ring_torsion",
        "inter_ring_smooth_shell",
        "axisymmetric_collapse_lunchick",
    )
    assert result.advisory_governing_mode == "axisymmetric_collapse_lunchick"
    assert result.shell_yield_between_rings_pressure_mpa < result.advisory_governing_pressure_mpa
    assert RING_SHELL_YIELD_NOTE in result.notes


def test_without_a_yield_strength_the_yield_pressures_are_null():
    result = _case(yield_strength_mpa=None)

    assert result.shell_yield_between_rings_pressure_mpa is None
    assert result.ring_yield_pressure_mpa is None
    # The elastic solution needs no yield strength and is still reported.
    assert result.axisymmetric_stress == _case().axisymmetric_stress
    assert RING_SHELL_YIELD_NOTE not in result.notes


def test_internal_and_external_rings_use_their_own_area_rule():
    external = _case().axisymmetric_stress
    internal = _case(ring_location="internal").axisymmetric_stress
    area = 3.88 * 25.0
    centroid_offset = 0.5 * (2.38 + 25.0)

    assert external is not None and internal is not None
    assert external.effective_ring_area_mm2 == pytest.approx(
        area * (274.5 / (274.5 + centroid_offset)) ** 2
    )
    assert internal.effective_ring_area_mm2 == pytest.approx(
        area * 274.5 / (274.5 - centroid_offset)
    )
    # The bay itself does not depend on the ring's side.
    assert external.clear_bay_mm == internal.clear_bay_mm == pytest.approx(100.0 - 3.88)
    assert external.n_function == internal.n_function
    assert external.g_function == internal.g_function


def test_yield_pressures_are_linear_elastic_mean_hoop_yield():
    base = _case()
    stress = base.axisymmetric_stress

    assert stress is not None
    # E cancels, and the applied pressure does not enter.
    assert _case(elastic_modulus_mpa=2.0 * 218_800.0).shell_yield_between_rings_pressure_mpa == (
        pytest.approx(base.shell_yield_between_rings_pressure_mpa, rel=1e-14)
    )
    assert _case(external_pressure_mpa=0.0).ring_yield_pressure_mpa == base.ring_yield_pressure_mpa
    # At each yield pressure the mean hoop stress equals the yield strength.
    assert base.shell_yield_between_rings_pressure_mpa * (
        stress.midbay_shell_hoop_stress_per_unit_pressure
    ) == pytest.approx(288.3)
    assert base.ring_yield_pressure_mpa * stress.ring_hoop_stress_per_unit_pressure == (
        pytest.approx(288.3)
    )


@pytest.mark.parametrize(
    ("ring_location", "location", "smallest_radius_mm"),
    [
        ("internal", "internal_ring_free_edge", 274.5 - 2.38 / 2.0 - 25.0),
        ("external", "external_ring_base_at_shell", 274.5 + 2.38 / 2.0),
    ],
)
def test_ring_first_yield_is_at_the_smallest_radius_of_the_translating_ring(
    ring_location, location, smallest_radius_mm
):
    # Each ring section translates radially as a whole, so its hoop stress
    # E w_ring / r is largest at its smallest radius: the free edge of an
    # internal ring, but the base of an external one, whose free edge yields
    # last. Ring first yield scales from the centroid value by that ratio.
    result = _case(ring_location=ring_location)
    stress = result.axisymmetric_stress
    centroid_radius_mm = 274.5 + (1.0 if ring_location == "external" else -1.0) * 0.5 * (
        2.38 + 25.0
    )

    assert stress is not None
    assert stress.ring_maximum_hoop_stress_location == location
    assert stress.ring_maximum_hoop_stress_radius_mm == pytest.approx(smallest_radius_mm)
    assert stress.ring_maximum_hoop_stress_per_unit_pressure == pytest.approx(
        stress.ring_hoop_stress_per_unit_pressure * centroid_radius_mm / smallest_radius_mm,
        rel=1e-14,
    )
    assert result.ring_first_yield_pressure_mpa == pytest.approx(
        result.ring_yield_pressure_mpa * smallest_radius_mm / centroid_radius_mm, rel=1e-14
    )
    assert result.ring_first_yield_pressure_mpa < result.ring_yield_pressure_mpa
    assert result.ring_first_yield_pressure_mpa * (
        stress.ring_maximum_hoop_stress_per_unit_pressure
    ) == pytest.approx(288.3)
    assert _case(ring_location=ring_location, yield_strength_mpa=None).ring_first_yield_pressure_mpa is None


@pytest.mark.parametrize(
    "overrides",
    [{"wall_thickness_mm": 30.0}, {"ring_axial_width_mm": 120.0}],
    ids=["thick_wall", "overlapping_rings"],
)
def test_invalid_geometry_reports_no_yield_pressures(overrides):
    result = _case(**overrides)

    assert result.capacity_status == "withheld_invalid_applicability"
    assert result.axisymmetric_stress is None
    assert result.shell_yield_between_rings_pressure_mpa is None
    assert result.ring_yield_pressure_mpa is None
    assert result.ring_first_yield_pressure_mpa is None


def test_json_summary_and_text_report_the_yield_pressures():
    response = _response(288.3)
    result = response["result"]

    assert response["calculation_source"]["model_version"] == "6.0.0"
    assert result["shell_yield_between_rings_pressure_mpa"] == {
        "value": pytest.approx(2.486631095097233, rel=1e-12), "unit": "MPa",
    }
    assert result["axisymmetric_stress"]["clear_bay_mm"] == {
        "value": pytest.approx(96.12), "unit": "mm",
    }
    assert result["axisymmetric_stress"]["effective_ring_area_mm2"]["unit"] == "mm^2"

    summary = summarize_response(response)
    assert summary["assessment"]["status"] == "indeterminate"
    assert summary["ring_yield"]["ring_yield_pressure_mpa"]["unit"] == "MPa"
    text = render_text(response)
    assert (
        "Lowest buckling or collapse pressure: 2.73537 MPa (axisymmetric collapse, Lunchick)"
    ) in text
    assert "Axisymmetric collapse (Lunchick, perfect shell): 2.73537 MPa" in text
    assert "Shell mean hoop yield at mid-bay (Pc5): 2.48663 MPa" in text
    assert "Ring mean hoop yield: 5.66939 MPa" in text
    first_yield = 5.66939427151082 * (274.5 + 1.19) / (274.5 + 13.69)
    assert summary["ring_yield"]["ring_first_yield_pressure_mpa"]["value"] == pytest.approx(
        first_yield, rel=1e-12
    )
    assert summary["ring_yield"]["ring_maximum_hoop_stress_location"] == (
        "external_ring_base_at_shell"
    )
    assert f"Ring first yield (ring base at the shell): {first_yield:.6g} MPa" in text

    without_yield = render_text(_response(None))
    assert "Mean hoop yield: not evaluated without a yield strength" in without_yield
