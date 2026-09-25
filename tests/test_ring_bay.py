"""Beam-column periodic-bay stresses and Lunchick axisymmetric collapse of the ring model.

Production transcribes Renzi's closed form (IHTR 2944, Eqs. 7 and 43-66). The
independent reference in tests/reference/ring_bay_reference.py solves the same
governing equation from its characteristic roots instead, and DAPS4's own
published example output checks both.
"""

from __future__ import annotations

import math
from pathlib import Path

import pytest
import yaml

from reference.ring_bay_reference import (
    BayCase,
    direct_solution,
    lunchick_reserve_factor,
    outer_midbay_yield_pressure,
    rectangular_ring_case,
)

from pv_calc.api import calculate
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.presentation import render_text, summarize_response
from pv_calc.pressure_vessel import (
    RingBeamColumnBayResult,
    ring_bay_axisymmetric_collapse,
    ring_bay_beam_column_stress,
    ring_stiffened_shell_external_pressure,
)


INCH_TO_MM = 25.4
PSI_TO_MPA = 0.006894757293168361
FIXTURE = Path(__file__).parent / "fixtures" / "software_parity" / "daps4_ihtr2944_case2.yaml"


def _kernel_inputs(case: BayCase) -> dict[str, float]:
    return dict(
        shell_mid_surface_radius_mm=case.shell_mid_surface_radius,
        wall_thickness_mm=case.wall_thickness,
        ring_spacing_mm=case.ring_spacing,
        ring_faying_width_mm=case.ring_faying_width,
        ring_area_mm2=case.ring_area,
        ring_centroid_radius_mm=case.ring_centroid_radius,
        elastic_modulus_mpa=case.elastic_modulus,
        poisson_ratio=case.poisson_ratio,
    )


def _stress_inputs(case: BayCase) -> dict[str, float]:
    # The reference, like DAPS4, gives the ring hoop stress at R.
    return {**_kernel_inputs(case), "ring_stress_radius_mm": case.shell_mid_surface_radius}


def _daps4_case2() -> tuple[dict, dict[str, float]]:
    fixture = yaml.safe_load(FIXTURE.read_text(encoding="utf-8"))
    source = fixture["source_inputs"]
    thickness = source["shell_thickness"]["value"]
    inputs = dict(
        shell_mid_surface_radius_mm=(source["outside_diameter"]["value"] / 2.0 - thickness / 2.0)
        * INCH_TO_MM,
        wall_thickness_mm=thickness * INCH_TO_MM,
        ring_spacing_mm=source["ring_spacing"]["value"] * INCH_TO_MM,
        ring_faying_width_mm=source["ring_web_width_at_shell"]["value"] * INCH_TO_MM,
        ring_area_mm2=source["ring_area"]["value"] * INCH_TO_MM**2,
        ring_centroid_radius_mm=source["ring_centroid_radius"]["value"] * INCH_TO_MM,
        elastic_modulus_mpa=source["elastic_modulus"]["value"] * PSI_TO_MPA,
        poisson_ratio=source["poisson_ratio"],
    )
    return fixture, inputs


def _printed_stations(result: RingBeamColumnBayResult) -> dict[str, dict[str, float]]:
    stations = {}
    for name in ("midbay", "frame"):
        station = getattr(result, name)
        stations[name] = {
            "axial_outer_psi": station.axial_outer_mpa / PSI_TO_MPA,
            "axial_inner_psi": station.axial_inner_mpa / PSI_TO_MPA,
            "hoop_outer_psi": station.hoop_outer_mpa / PSI_TO_MPA,
            "hoop_inner_psi": station.hoop_inner_mpa / PSI_TO_MPA,
            "von_mises_outer_psi": station.von_mises_outer_mpa / PSI_TO_MPA,
            "von_mises_inner_psi": station.von_mises_inner_mpa / PSI_TO_MPA,
            "von_mises_membrane_psi": station.von_mises_membrane_mpa / PSI_TO_MPA,
            "radial_deflection_in": station.radial_deflection_mm / INCH_TO_MM,
        }
    return stations


def test_daps4_case2_stresses_match_the_published_program_output():
    # DAPS4's sample output for an internally T-ringed Sch. 10 pipe at
    # 1000 psi (IHTR 2944, p. 48). Every printed stress, both deflections, and
    # the ring hoop stress reproduce at the printed precision.
    fixture, inputs = _daps4_case2()
    printed = fixture["printed_output"]
    precision = fixture["printed_precision"]
    # DAPS4 prints the ring hoop stress at the mean radius R (Eq. 55).
    result = ring_bay_beam_column_stress(
        pressure_mpa=1000.0 * PSI_TO_MPA,
        ring_stress_radius_mm=inputs["shell_mid_surface_radius_mm"],
        **inputs,
    )
    stations = _printed_stations(result)

    for name in ("midbay", "frame"):
        for key, value in printed[name].items():
            tolerance = (
                precision["deflection_in"] if key.endswith("_in") else precision["stress_psi"]
            )
            assert stations[name][key] == pytest.approx(value, abs=tolerance), (name, key)
    assert result.ring_hoop_stress_mpa / PSI_TO_MPA == pytest.approx(
        printed["ring_hoop_stress_psi"], abs=precision["stress_psi"]
    )
    assert result.stress_sign_convention == "tension_positive"
    assert result.load_radius_convention == "hoop_at_mid_surface_axial_from_outer_surface"


def test_daps4_case2_axisymmetric_collapse_matches_the_published_output():
    fixture, inputs = _daps4_case2()
    printed = fixture["printed_output"]
    precision = fixture["printed_precision"]
    collapse = ring_bay_axisymmetric_collapse(
        yield_strength_mpa=fixture["source_inputs"]["yield_stress"]["value"] * PSI_TO_MPA,
        **inputs,
    )

    assert collapse.status == "advisory"
    assert collapse.outer_midbay_bending_compressive is True
    assert collapse.collapse_pressure_mpa is not None
    assert collapse.collapse_pressure_mpa / PSI_TO_MPA == pytest.approx(
        printed["axisymmetric_collapse_pressure_psi"], abs=precision["pressure_psi"]
    )
    assert collapse.plastic_reserve_factor_phi3 == pytest.approx(
        printed["plastic_reserve_factor"], abs=precision["reserve_factor"]
    )


PARITY_CASES = (
    rectangular_ring_case("external_short_bay", shell_mid_surface_radius=100.0, wall_thickness=5.0,
                          ring_spacing=20.0, ring_axial_width=4.0, ring_radial_height=12.0,
                          ring_location="external", elastic_modulus=113_800.0, poisson_ratio=0.34),
    rectangular_ring_case("internal_moderate_bay", shell_mid_surface_radius=150.0, wall_thickness=6.0,
                          ring_spacing=60.0, ring_axial_width=8.0, ring_radial_height=20.0,
                          ring_location="internal", elastic_modulus=113_800.0, poisson_ratio=0.34),
    rectangular_ring_case("internal_long_bay", shell_mid_surface_radius=250.0, wall_thickness=5.0,
                          ring_spacing=320.0, ring_axial_width=10.0, ring_radial_height=30.0,
                          ring_location="internal", elastic_modulus=200_000.0, poisson_ratio=0.3),
    rectangular_ring_case("external_thin_shell", shell_mid_surface_radius=1000.0, wall_thickness=4.0,
                          ring_spacing=400.0, ring_axial_width=10.0, ring_radial_height=60.0,
                          ring_location="external", elastic_modulus=200_000.0, poisson_ratio=0.3),
    BayCase("daps4_case2_t_ring", 9.875 * INCH_TO_MM, 0.25 * INCH_TO_MM, 2.75 * INCH_TO_MM,
            0.1 * INCH_TO_MM, 0.07 * INCH_TO_MM**2, 9.443 * INCH_TO_MM, 30e6 * PSI_TO_MPA, 0.29),
)


def _gamma_one_pressure(case: BayCase) -> float:
    radius, thickness = case.shell_mid_surface_radius, case.wall_thickness
    rigidity = case.elastic_modulus * thickness**3 / (12.0 * (1.0 - case.poisson_ratio**2))
    alpha = (radius + 0.5 * thickness) / radius
    return 4.0 * math.sqrt(rigidity * case.elastic_modulus * thickness) / (radius * alpha) ** 2


def test_parity_cases_span_bay_length_and_ring_side():
    thetas = [
        ring_bay_beam_column_stress(pressure_mpa=0.0, **_stress_inputs(case)).bay_parameter_theta
        for case in PARITY_CASES
    ]
    assert min(thetas) < 1.0
    assert max(thetas) > 10.0


@pytest.mark.parametrize("case", PARITY_CASES, ids=lambda case: case.case_id)
@pytest.mark.parametrize("gamma_fraction", [0.0, 0.3, 0.9])
def test_closed_form_matches_the_direct_solution(case: BayCase, gamma_fraction: float):
    pressure = gamma_fraction * _gamma_one_pressure(case)
    production = ring_bay_beam_column_stress(pressure_mpa=pressure, **_stress_inputs(case))
    if pressure == 0.0:
        assert production.midbay.von_mises_outer_mpa == 0.0
        return
    independent = direct_solution(case, pressure)
    stress_scale = pressure * case.shell_mid_surface_radius / case.wall_thickness
    deflection_scale = stress_scale * case.shell_mid_surface_radius / case.elastic_modulus

    assert production.pressure_parameter_gamma == pytest.approx(independent["gamma"], rel=1e-12)
    for station in ("midbay", "frame"):
        values = getattr(production, station)
        for key in ("axial_outer", "axial_inner", "hoop_outer", "hoop_inner", "hoop_membrane"):
            assert getattr(values, f"{key}_mpa") == pytest.approx(
                independent[f"{station}_{key}"], rel=0.0, abs=1e-10 * stress_scale
            ), (station, key)
    assert production.midbay.radial_deflection_mm == pytest.approx(
        independent["midbay_deflection"], rel=0.0, abs=1e-10 * deflection_scale
    )
    assert production.frame.radial_deflection_mm == pytest.approx(
        independent["frame_deflection"], rel=0.0, abs=1e-10 * deflection_scale
    )
    assert production.ring_hoop_stress_mpa == pytest.approx(
        independent["ring_hoop"], rel=0.0, abs=1e-10 * stress_scale
    )


@pytest.mark.parametrize("case", PARITY_CASES[:4], ids=lambda case: case.case_id)
def test_collapse_matches_the_independent_reference(case: BayCase):
    yield_strength = 827.0 if case.elastic_modulus < 150_000.0 else 300.0
    production = ring_bay_axisymmetric_collapse(
        yield_strength_mpa=yield_strength, **_kernel_inputs(case)
    )
    first_yield = outer_midbay_yield_pressure(case, yield_strength)
    assert production.first_yield_pressure_mpa == pytest.approx(first_yield, rel=1e-9)
    assert production.plastic_reserve_factor_phi3 == pytest.approx(
        lunchick_reserve_factor(case, first_yield), rel=1e-9
    )
    at_yield = ring_bay_beam_column_stress(
        pressure_mpa=production.first_yield_pressure_mpa, **_stress_inputs(case)
    )
    assert at_yield.midbay.von_mises_outer_mpa == pytest.approx(yield_strength, rel=1e-9)


@pytest.mark.parametrize("ring_location", ["external", "internal"])
@pytest.mark.parametrize("radius_over_thickness", [100.0, 1000.0, 10000.0])
def test_low_pressure_thin_shell_recovers_the_pc5_mid_bay_hoop_stress(
    ring_location, radius_over_thickness
):
    # With gamma near 0 and R_o / R near 1 the beam-column bay reduces to the
    # PD 5500 closed form behind Pc5. External rings use the same effective
    # area in both; for internal rings Renzi's A_f (R/R_cg)^2 differs from
    # DTMB 1639's A_f R/R_c, by at most about 0.1% of the stress here.
    radius = 1000.0
    thickness = radius / radius_over_thickness
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=1e-6,
        shell_mid_surface_radius_mm=radius,
        wall_thickness_mm=thickness,
        unsupported_length_mm=400.0 * thickness,
        ring_spacing_mm=40.0 * thickness,
        ring_axial_width_mm=2.0 * thickness,
        ring_radial_height_mm=8.0 * thickness,
        ring_location=ring_location,
        elastic_modulus_mpa=200_000.0,
        poisson_ratio=0.3,
    )
    assert result.beam_column_bay is not None and result.axisymmetric_stress is not None
    tolerance = 1e-4 if ring_location == "external" else 1e-3
    assert -result.beam_column_bay.midbay.hoop_membrane_mpa / 1e-6 == pytest.approx(
        result.axisymmetric_stress.midbay_shell_hoop_stress_per_unit_pressure, rel=tolerance
    )


def _thin_shell(**overrides) -> dict:
    inputs = dict(
        shell_mid_surface_radius_mm=1000.0,
        wall_thickness_mm=1.0,
        unsupported_length_mm=400.0,
        ring_spacing_mm=40.0,
        ring_axial_width_mm=2.0,
        ring_radial_height_mm=20.0,
        ring_location="external",
        elastic_modulus_mpa=200_000.0,
        poisson_ratio=0.3,
    )
    inputs.update(overrides)
    return inputs


def test_collapse_is_withheld_when_gamma_reaches_one_before_first_yield():
    # A very thin, very strong shell: the axial load reaches the closed form's
    # gamma = 1 limit before the outer surface at mid-bay yields.
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=0.01, yield_strength_mpa=5_000.0, **_thin_shell()
    )
    collapse = result.axisymmetric_collapse

    assert collapse is not None
    assert collapse.status == "withheld_beam_column_limit"
    assert collapse.collapse_pressure_mpa is None
    assert collapse.first_yield_pressure_mpa is None
    assert "axisymmetric_collapse_lunchick" not in result.advisory_candidate_modes
    assert result.beam_column_bay is not None


def test_bay_stresses_are_withheld_at_or_beyond_the_gamma_limit():
    inputs = _thin_shell()
    limit = ring_bay_axisymmetric_collapse(
        yield_strength_mpa=5_000.0,
        shell_mid_surface_radius_mm=inputs["shell_mid_surface_radius_mm"],
        wall_thickness_mm=inputs["wall_thickness_mm"],
        ring_spacing_mm=inputs["ring_spacing_mm"],
        ring_faying_width_mm=inputs["ring_axial_width_mm"],
        ring_area_mm2=40.0,
        ring_centroid_radius_mm=1010.5,
        elastic_modulus_mpa=inputs["elastic_modulus_mpa"],
        poisson_ratio=inputs["poisson_ratio"],
    ).beam_column_limit_pressure_mpa
    result = ring_stiffened_shell_external_pressure(external_pressure_mpa=limit, **inputs)

    assert result.beam_column_bay is None
    assert any("gamma reaches 1" in note for note in result.notes)
    with pytest.raises(ValueError, match="gamma < 1"):
        ring_bay_beam_column_stress(
            pressure_mpa=limit * (1.0 + 1e-9),
            shell_mid_surface_radius_mm=1000.0,
            wall_thickness_mm=1.0,
            ring_spacing_mm=40.0,
            ring_faying_width_mm=2.0,
            ring_area_mm2=40.0,
            ring_centroid_radius_mm=1010.5,
            elastic_modulus_mpa=200_000.0,
            poisson_ratio=0.3,
            ring_stress_radius_mm=1000.5,
        )


def test_a_long_bay_reverses_the_mid_bay_bending_and_is_flagged():
    # theta = 11: the mid-bay bending relieves the outer surface, outside
    # Lunchick's derivation, and phi3 falls just below 1.
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=5.0,
        shell_mid_surface_radius_mm=250.0,
        wall_thickness_mm=5.0,
        unsupported_length_mm=1600.0,
        ring_spacing_mm=320.0,
        ring_axial_width_mm=10.0,
        ring_radial_height_mm=30.0,
        ring_location="internal",
        elastic_modulus_mpa=200_000.0,
        poisson_ratio=0.3,
        yield_strength_mpa=690.0,
    )
    collapse = result.axisymmetric_collapse

    assert result.beam_column_bay is not None
    assert result.beam_column_bay.bay_parameter_theta > 10.0
    assert collapse is not None and collapse.plastic_reserve_factor_phi3 is not None
    assert collapse.outer_midbay_bending_compressive is False
    assert 0.98 < collapse.plastic_reserve_factor_phi3 < 1.0
    assert any("relieves the outer surface" in note for note in result.notes)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"ring_faying_width_mm": 40.0}, "less than ring_spacing_mm"),
        ({"ring_area_mm2": 0.0}, "ring_area_mm2"),
        ({"poisson_ratio": 0.5}, "poisson_ratio"),
        ({"ring_stress_radius_mm": 0.0}, "ring_stress_radius_mm"),
    ],
)
def test_the_kernel_rejects_invalid_inputs(overrides, message):
    inputs = dict(
        pressure_mpa=1.0,
        shell_mid_surface_radius_mm=100.0,
        wall_thickness_mm=5.0,
        ring_spacing_mm=40.0,
        ring_faying_width_mm=4.0,
        ring_area_mm2=48.0,
        ring_centroid_radius_mm=108.5,
        elastic_modulus_mpa=113_800.0,
        poisson_ratio=0.34,
        ring_stress_radius_mm=102.5,
    )
    inputs.update(overrides)
    with pytest.raises(ValueError, match=message):
        ring_bay_beam_column_stress(**inputs)


def test_the_bay_ring_stress_is_at_the_ring_smallest_radius():
    # A ring section translates radially, so its hoop stress E w / r is
    # largest at its smallest radius: here an internal ring's free edge at
    # 127 mm, 18% above DAPS4's printed value at the shell radius.
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=40.0,
        shell_mid_surface_radius_mm=150.0,
        wall_thickness_mm=6.0,
        unsupported_length_mm=1200.0,
        ring_spacing_mm=60.0,
        ring_axial_width_mm=8.0,
        ring_radial_height_mm=20.0,
        ring_location="internal",
        elastic_modulus_mpa=113_800.0,
        poisson_ratio=0.34,
        yield_strength_mpa=827.0,
    )
    bay = result.beam_column_bay
    assert bay is not None
    ring_deflection = bay.frame.radial_deflection_mm

    assert bay.ring_hoop_stress_mpa == pytest.approx(113_800.0 * ring_deflection / 127.0, rel=1e-12)
    assert bay.ring_hoop_stress_mpa == pytest.approx(-609.92, abs=0.01)


def test_the_ring_model_reports_collapse_with_its_disposition():
    result = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=40.0,
        shell_mid_surface_radius_mm=150.0,
        wall_thickness_mm=6.0,
        unsupported_length_mm=1200.0,
        ring_spacing_mm=60.0,
        ring_axial_width_mm=8.0,
        ring_radial_height_mm=20.0,
        ring_location="internal",
        elastic_modulus_mpa=113_800.0,
        poisson_ratio=0.34,
        yield_strength_mpa=827.0,
    )
    dispositions = {item.mode: item.disposition for item in result.mode_dispositions}
    collapse = result.axisymmetric_collapse

    assert dispositions["axisymmetric_collapse"] == "implemented_advisory"
    assert collapse is not None and collapse.collapse_pressure_mpa is not None
    assert 1.0 < collapse.plastic_reserve_factor_phi3 < 1.5
    assert collapse.collapse_pressure_mpa == pytest.approx(
        collapse.plastic_reserve_factor_phi3 * collapse.first_yield_pressure_mpa
    )
    assert "axisymmetric_collapse_lunchick" in result.advisory_candidate_modes
    assert any("Lunchick's plastic reserve" in note for note in result.notes)
    # The applied-pressure bay stresses come from the same kernel.
    bay = result.beam_column_bay
    assert bay is not None
    assert bay.pressure_mpa == 40.0
    assert bay.frame.von_mises_inner_mpa > bay.midbay.von_mises_outer_mpa


def test_json_summary_and_text_carry_the_bay_stresses_and_collapse():
    response = calculate({
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "ring-shell",
        "inputs": {
            "external_pressure": {"value": 40.0, "unit": "MPa"},
            "shell_mid_surface_radius": {"value": 150.0, "unit": "mm"},
            "wall_thickness": {"value": 6.0, "unit": "mm"},
            "unsupported_length": {"value": 1200.0, "unit": "mm"},
            "ring_spacing": {"value": 60.0, "unit": "mm"},
            "ring_axial_width": {"value": 8.0, "unit": "mm"},
            "ring_radial_height": {"value": 20.0, "unit": "mm"},
            "ring_location": "internal",
        },
        "material": {"type": "explicit", "name": "Invented titanium", "properties": {
            "failure_category": "ductile_metal",
            "elastic_modulus": {"value": 113_800.0, "unit": "MPa"},
            "poisson_ratio": 0.34,
            "yield_strength": {"value": 827.0, "unit": "MPa"},
        }},
    })
    result = response["result"]

    assert result["beam_column_bay"]["midbay"]["von_mises_outer_mpa"]["unit"] == "MPa"
    assert result["beam_column_bay"]["frame"]["radial_deflection_mm"]["unit"] == "mm"
    assert result["axisymmetric_collapse"]["collapse_pressure_mpa"]["unit"] == "MPa"
    summary = summarize_response(response)
    assert summary["ring_collapse"]["status"] == "advisory"
    assert summary["ring_bay_stress"]["frame_von_mises_inner_mpa"]["unit"] == "MPa"
    text = render_text(response)
    assert "Axisymmetric collapse (Lunchick, perfect shell): " in text
    assert "Bay surface von Mises at the applied pressure: mid-bay outer " in text
