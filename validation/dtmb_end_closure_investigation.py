"""DTMB 1324 Table 1 comparison with explicit span and support qualifications.

    uv run python validation/dtmb_end_closure_investigation.py \
        --output validation/results/dtmb_end_closure_investigation.json

The primary report does not supply exact spans for these cases; the archived
DAPS4 lengths are used as reconstructed inputs.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
import json
import math
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from pv_calc.pressure_vessel import ring_stiffened_shell_external_pressure  # noqa: E402
from validation.published.dtmb_1324_case17 import INCH_TO_MM, PSI_TO_MPA  # noqa: E402
from validation.ring_shell_investigation import percent, scan, stiffness  # noqa: E402
from validation.ring_shell_reference import (  # noqa: E402
    DTMB_TABLE_2_PUBLISHED,
    _mode_pressure,
    dtmb_case,
)


# Primary: DTMB 1324 Table 1, printed p. 6, visually transcribed.
# Each observed pair is (Southwell pressure in psi, circumferential lobes).
# DAPS length and row index are separate secondary-source fields.
CASES = (
    {"specimen": "6", "spaces": 14, "published_ld": 1.91,
     "kendrick": (499, 3), "kaminsky": (910, 3),
     "observed": {"I": (504, 3), "II": (576, 3), "III": (576, 3), "V": (700, 3)},
     "daps_length_in": 15.639, "daps_index": 6},
    {"specimen": "2-A", "spaces": 25, "published_ld": 3.36,
     "kendrick": (317, 2), "kaminsky": (575, 3),
     "observed": {"I": (339, 2), "II": (365, 2), "III": (394, 3),
                  "IV": (398, 3), "V": (409, 3)},
     "daps_length_in": 27.512, "daps_index": 0},
    {"specimen": "3-A", "spaces": 31, "published_ld": 4.31,
     "kendrick": (216, 2), "kaminsky": (551, 3),
     "observed": {"I": (229, 2), "II": (246, 2), "III": (298, 2),
                  "IV": (315, 2), "V": (378, 2)},
     "daps_length_in": 35.29, "daps_index": 2},
    {"specimen": "4-A", "spaces": 37, "published_ld": 5.16,
     "kendrick": (180, 2), "kaminsky": (494, 2),
     "observed": {"I": (178, 2), "II": (189, 2), "III": (231, 2),
                  "IV": (228, 2), "V": (289, 2)},
     "daps_length_in": 42.25, "daps_index": 4},
)


def calculate(length_in: float) -> dict[str, Any]:
    case = replace(dtmb_case(17), unsupported_length=length_in)
    ideal, m, n = scan(case)
    public = ring_stiffened_shell_external_pressure(
        external_pressure_mpa=PSI_TO_MPA,
        shell_mid_surface_radius_mm=case.shell_mid_surface_radius * INCH_TO_MM,
        wall_thickness_mm=case.wall_thickness * INCH_TO_MM,
        unsupported_length_mm=length_in * INCH_TO_MM,
        ring_spacing_mm=case.ring_spacing * INCH_TO_MM,
        ring_axial_width_mm=case.ring_axial_width * INCH_TO_MM,
        ring_radial_height_mm=case.ring_radial_height * INCH_TO_MM,
        ring_location=case.ring_location,
        elastic_modulus_mpa=case.elastic_modulus * PSI_TO_MPA,
        poisson_ratio=case.poisson_ratio,
        yield_strength_mpa=85_000 * PSI_TO_MPA,
    )
    global_result = public.global_with_ring_torsion
    assert global_result.converged
    assert public.boundary_condition == "simply_supported"
    assert public.load_case == "hydrostatic_closed_end"
    assert (global_result.critical_axial_half_waves_m,
            global_result.critical_circumferential_lobes_n) == (m, n)
    assert math.isclose(global_result.ideal_critical_pressure_mpa / PSI_TO_MPA,
                        ideal, rel_tol=1e-11)
    assert math.isclose(global_result.adjusted_critical_pressure_mpa / PSI_TO_MPA,
                        0.75 * ideal, rel_tol=1e-11)
    return {"length_in": length_in, "ideal_pressure_psi": ideal,
            "adjusted_pressure_psi": 0.75 * ideal, "mode": [m, n]}


def axisymmetric_diagnostic(length_in: float) -> dict[str, Any]:
    case = replace(dtmb_case(17), unsupported_length=length_in)
    constants = stiffness(case)
    p, m = min((_mode_pressure(case, constants, m, 0), m) for m in range(1, 513))
    assert m < 512
    # Independently reduce the n=0 matrix to a two-variable system. This
    # verifies the diagnostic branch algebra; it does not qualify a discrete
    # ring or imperfection-sensitive axisymmetric capacity method.
    a = math.pi * m / length_in
    r = case.shell_mid_surface_radius
    membrane = constants.extensional_y - constants.extensional_xy**2/constants.extensional_x
    reduced = 2/r * (constants.bending_x*a*a + membrane/(r*r*a*a))
    assert math.isclose(p, reduced, rel_tol=1e-12)
    return {"ideal_pressure_psi": p, "mode": [m, 0],
            "scope": "diagnostic smeared n=0 branch, excluded from production and not a qualified capacity"}


def build_results() -> dict[str, Any]:
    daps_path = REPO_ROOT / "validation/results/daps4_ring_crosscheck.json"
    daps = json.loads(daps_path.read_text())
    controls = {row["fixture"]: row for row in daps["archived_controls"]}
    assert controls["SS"]["reported_precision_match"]
    assert controls["CL"]["reported_precision_match"]
    rows = []
    for source in CASES:
        length = source["daps_length_in"]
        ld = source["published_ld"]
        calculation = calculate(length)
        assert abs(length - ld*8.188) < 0.0005
        variations = []
        for diameter_label, diameter in (("ID", 8.118), ("mid_surface", 8.153), ("OD", 8.188)):
            for offset in (-0.005, 0.0, 0.005):
                result = calculate((ld + offset)*diameter)
                variations.append({
                    "interpretation": diameter_label,
                    "ld_rounding_offset": offset,
                    "pressure_change_percent": percent(
                        result["ideal_pressure_psi"], calculation["ideal_pressure_psi"]
                    ), **result,
                })
        # Fig. 2 supplies 0.959-in end bays, but this interpretation does not
        # reconcile all Table 1 space counts with its reported L/D column.
        drawing_length = (source["spaces"] - 2)*1.152 + 2*0.959
        drawing_variant = calculate(drawing_length)
        drawing_variant["interpretation"] = "nominal space count with two Fig. 2 end bays; not an established exact span"
        index = source["daps_index"]
        daps_rounded_length = math.floor(length/1.152 + 0.5)*1.152
        observations = []
        for label, (pressure, lobes) in source["observed"].items():
            observations.append({
                "closure_case": label, "southwell_pressure_psi": pressure,
                "circumferential_lobes_n": lobes,
                "adjusted_model_vs_estimate_percent": percent(calculation["adjusted_pressure_psi"], pressure),
                "ideal_model_vs_estimate_percent": percent(calculation["ideal_pressure_psi"], pressure),
                "lobes_match_model": lobes == calculation["mode"][1],
            })
        axisymmetric = axisymmetric_diagnostic(length)
        axisymmetric["ratio_to_lobar_ideal"] = axisymmetric["ideal_pressure_psi"]/calculation["ideal_pressure_psi"]
        rows.append({
            "specimen": source["specimen"],
            "primary_frame_spaces": source["spaces"],
            "primary_rounded_length_over_diameter": ld,
            "span_status": "reconstructed, not measured or fully reconciled with primary drawing",
            "kendrick_psi_and_lobes": source["kendrick"],
            "kaminsky_clamped_psi_and_lobes": source["kaminsky"],
            "calculation": calculation,
            "observations": observations,
            "length_interpretation_sensitivity": variations,
            "nominal_end_bay_variant": drawing_variant,
            "axisymmetric_diagnostic": axisymmetric,
            "daps_archived_comparison": {
                "fixture_input_length_in": length,
                "effective_global_length_in": daps_rounded_length,
                "simply_supported": controls["SS"]["results"][index],
                "clamped": controls["CL"]["results"][index],
                "nasa_at_daps_effective_length": calculate(daps_rounded_length),
                "scope": "software controls; different theory and effective length, not source-exact fixture simulation",
            },
        })

    table_2_axisymmetric = []
    for spaces, *_ in DTMB_TABLE_2_PUBLISHED:
        c = calculate(spaces*1.152)
        n0 = axisymmetric_diagnostic(spaces*1.152)
        table_2_axisymmetric.append({
            "frame_spaces": spaces, **n0,
            "ratio_to_lobar_ideal": n0["ideal_pressure_psi"]/c["ideal_pressure_psi"],
        })

    return {
        "schema_version": "1.0.0",
        "scope": "numerically verified diagnostic comparison; not a calibrated model or source-exact validation fixture",
        "primary_source": {
            "url": "https://dome.mit.edu/handle/1721.3/48982",
            "sha256": "975aaf2ef7f4b0adde9cd15dd8dc5ea378e91e097d5f145d60923aeeede728a2",
            "locations": "Fig. 2, Fig. 3, Table 1, printed pp. 1-6",
            "measurement": "Southwell estimates, not repeated destructive collapses",
            "specimen_3A_rotated_case_II": {"pressure_psi": 238, "lobes_n": 2,
                "note": "90-degree rotation of endplates; separate observation, not substituted for 246 psi"},
        },
        "secondary_geometry_source": {
            "release": daps["release_url"],
            "fixture": "Validation Problems/DTMB Models/1324/Rev E.2/daps4inp.SS.dp4",
            "sha256": "6784de37db3ca4c692d161972664e94bb383e96122e44eadc779f9ebb6fb5f25",
            "interpretation": "lengths agree with the primary rounded L/D multiplied by 8.188-in shell OD to displayed input precision",
        },
        "cases": rows,
        "table_2_axisymmetric_diagnostic": table_2_axisymmetric,
        "cautions": [
            "No plate rotational stiffness, contact, tank-head stiffness, or continuing shell is represented by the production boundary condition.",
            "Changing the experimental closure does not change the model input; its prediction stays fixed for each reconstructed specimen.",
            "The end-bay interpretation is not reconciled with the Table 1 counts, particularly the 2/2-A row; no exact-length experimental golden is asserted.",
            "Axisymmetric diagnostic uses the same smeared theory; its short axial wavelengths require separate discrete-ring applicability assessment.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    results = build_results()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"Verified production/reference parity and span sensitivity for four closure specimens: {args.output}")
    for row in results["cases"]:
        case_i = row["observations"][0]
        c = row["calculation"]
        print(f"{row['specimen']}: ideal {c['ideal_pressure_psi']:.1f}, adjusted {c['adjusted_pressure_psi']:.1f} psi; "
              f"Case I {case_i['southwell_pressure_psi']} psi; adjusted difference "
              f"{case_i['adjusted_model_vs_estimate_percent']:+.1f}%")


if __name__ == "__main__":
    main()
