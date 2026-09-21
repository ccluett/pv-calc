"""Diagnose the DTMB ring-shell discrepancies without changing the model.

    uv run python validation/ring_shell_investigation.py --output /tmp/ring.json

Optional figure (matplotlib is a development-only dependency):

    uv run --with matplotlib python validation/ring_shell_investigation.py \
        --output /tmp/ring.json --plot /tmp/ring.png

The existing independent reference supplies the NASA modal equations. This
diagnostic separates ideal theory, the 0.75 adjustment, and published evidence.
"""

from __future__ import annotations

import argparse
from dataclasses import replace
from decimal import Decimal, localcontext
import json
import math
from pathlib import Path
import sys
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from validation.published.dtmb_1324_case17 import (  # noqa: E402
    PSI_TO_MPA,
    solve_case as production_case,
)
from validation.ring_shell_reference import (  # noqa: E402
    DTMB_TABLE_2_PUBLISHED,
    OrthotropicStiffnesses,
    RingCase,
    _exhaustive_mode_scan,
    _mode_pressure,
    _orthotropic_stiffnesses,
    dtmb_case,
    rectangular_section_properties,
)


def percent(value: float, reference: float) -> float:
    return 100.0 * (value / reference - 1.0)


def stiffness(case: RingCase, *, torsion: bool = True) -> OrthotropicStiffnesses:
    rectangle = rectangular_section_properties(
        case.ring_axial_width, case.ring_radial_height
    )
    return _orthotropic_stiffnesses(
        case, rectangle, include_ring_torsion=torsion
    )


def scan(case: RingCase) -> tuple[float, int, int]:
    rectangle = rectangular_section_properties(
        case.ring_axial_width, case.ring_radial_height
    )
    result = _exhaustive_mode_scan(case, rectangle, include_ring_torsion=True)
    return (
        result.ideal_critical_pressure,
        result.axial_half_waves_m,
        result.circumferential_lobes_n,
    )


def decimal_schur_pressure(
    case: RingCase, constants: OrthotropicStiffnesses, m: int, n: int
) -> float:
    """50-digit Schur complement instead of the floating-point determinant.

    Constants and pi start with the same double-precision inputs; the purpose
    is to isolate cancellation in matrix assembly/elimination, not claim an
    independent transcription or higher-accuracy geometry.
    """
    with localcontext() as context:
        context.prec = 50
        def d(value: Any) -> Decimal:
            return Decimal(str(value))
        r = d(case.shell_mid_surface_radius)
        a = d(m) * d(math.pi) / d(case.unsupported_length)
        b = d(n) / r
        ex, ey, exy, g = map(d, (
            constants.extensional_x, constants.extensional_y,
            constants.extensional_xy, constants.shear_xy,
        ))
        dx, dy, dxy, cy = map(d, (
            constants.bending_x, constants.bending_y,
            constants.bending_xy, constants.coupling_y,
        ))
        a11 = ex * a**2 + g * b**2
        a22 = ey * b**2 + g * a**2
        a12 = (exy + g) * a * b
        a13 = exy * a / r
        a23 = ey * b / r + cy * b**3
        a33 = dx*a**4 + dxy*a**2*b**2 + dy*b**4 + ey/r**2 + 2*cy*b**2/r
        schur = a33 - (
            a22*a13**2 - 2*a12*a13*a23 + a11*a23**2
        ) / (a11*a22 - a12**2)
        return float(r * schur / (d(n)**2 + d("0.5")*(a*r)**2))


def crossing() -> dict[str, float]:
    case = dtmb_case(17)
    constants = stiffness(case)

    def residual(spaces: float) -> float:
        variant = replace(case, unsupported_length=spaces * case.ring_spacing)
        return _mode_pressure(variant, constants, 1, 2) - _mode_pressure(
            variant, constants, 1, 3
        )

    lower, upper = 19.0, 20.0
    assert residual(lower) > 0.0 > residual(upper)
    for _ in range(48):
        middle = 0.5 * (lower + upper)
        if residual(middle) > 0.0:
            lower = middle
        else:
            upper = middle
    spaces = 0.5 * (lower + upper)
    variant = replace(case, unsupported_length=spaces * case.ring_spacing)
    pressure = _mode_pressure(variant, constants, 1, 2)
    # Check the other axial and circumferential modes at the crossing too.
    minimum, m, n = scan(variant)
    assert m == 1 and n in (2, 3)
    assert math.isclose(pressure, minimum, rel_tol=1e-10)
    return {
        "frame_spaces": spaces,
        "length_in": variant.unsupported_length,
        "ideal_pressure_psi": pressure,
        "adjusted_pressure_psi": 0.75 * pressure,
    }


def sensitivity() -> list[dict[str, Any]]:
    records = []
    for spaces in (17, 21, 29, 33):
        case = dtmb_case(spaces)
        baseline, _, _ = scan(case)
        variants = {
            "use_inner_radius": replace(
                case, shell_mid_surface_radius=case.shell_mid_surface_radius
                - case.wall_thickness / 2
            ),
            "use_outer_radius": replace(
                case, shell_mid_surface_radius=case.shell_mid_surface_radius
                + case.wall_thickness / 2
            ),
            "one_fewer_frame_space": replace(
                case, unsupported_length=case.unsupported_length-case.ring_spacing
            ),
            "one_more_frame_space": replace(
                case, unsupported_length=case.unsupported_length+case.ring_spacing
            ),
        }
        for field in (
            "wall_thickness", "ring_axial_width", "ring_radial_height",
            "elastic_modulus",
        ):
            for sign in (-1, 1):
                variants[f"{field}_{sign:+d}_percent"] = replace(
                    case, **{field: getattr(case, field) * (1 + sign * 0.01)}
                )
        for label, variant in variants.items():
            pressure, m, n = scan(variant)
            records.append({
                "frame_spaces": spaces,
                "perturbation": label,
                "ideal_pressure_psi": pressure,
                "change_percent": percent(pressure, baseline),
                "mode": [m, n],
            })
    return records


def build_results() -> dict[str, Any]:
    records = []
    for spaces, ld, kendrick, kendrick_n, experiment, experiment_n in DTMB_TABLE_2_PUBLISHED:
        case = dtmb_case(spaces)
        constants = stiffness(case)
        ideal, m, n = scan(case)
        public = production_case(spaces).global_with_ring_torsion
        assert public.converged
        assert (public.critical_axial_half_waves_m,
                public.critical_circumferential_lobes_n) == (m, n)
        assert math.isclose(
            public.ideal_critical_pressure_mpa / PSI_TO_MPA, ideal, rel_tol=1e-11
        )
        assert math.isclose(
            public.adjusted_critical_pressure_mpa / PSI_TO_MPA,
            0.75 * ideal, rel_tol=1e-11,
        )
        high_precision = decimal_schur_pressure(case, constants, m, n)
        assert math.isclose(high_precision, ideal, rel_tol=1e-10)
        without_torsion = _mode_pressure(case, stiffness(case, torsion=False), m, n)
        n2 = _mode_pressure(case, constants, 1, 2)
        n3 = _mode_pressure(case, constants, 1, 3)
        records.append({
            "frame_spaces": spaces,
            "published_length_over_diameter": ld,
            "kendrick_pressure_psi": kendrick,
            "kendrick_lobes": kendrick_n,
            "southwell_experimental_pressure_psi": experiment,
            "experimental_lobes": experiment_n,
            "ideal_pressure_psi": ideal,
            "adjusted_pressure_psi": 0.75 * ideal,
            "model_mode": [m, n],
            "ideal_vs_kendrick_percent": percent(ideal, kendrick),
            "ideal_vs_experiment_percent": percent(ideal, experiment),
            "adjusted_vs_kendrick_percent": percent(0.75*ideal, kendrick),
            "adjusted_vs_experiment_percent": percent(0.75*ideal, experiment),
            "m1_n2_ideal_pressure_psi": n2,
            "m1_n3_ideal_pressure_psi": n3,
            "m1_n3_adjusted_pressure_psi": 0.75*n3,
            "torsion_increment_percent_at_governing_mode": percent(ideal, without_torsion),
            "decimal_schur_vs_float_relative_difference": (high_precision / ideal - 1.0),
            "lateral_only_pressure_at_same_mode_psi": ideal * (
                n**2 + 0.5*(m*math.pi*case.shell_mid_surface_radius/case.unsupported_length)**2
            ) / n**2,
        })

    case = dtmb_case(17)
    constants = stiffness(case)
    effective_bending = constants.bending_y - constants.coupling_y**2/constants.extensional_y
    eq64_limit = 4 * effective_bending / case.shell_mid_surface_radius**3
    eq66 = 3 * effective_bending / case.shell_mid_surface_radius**3
    remote_case = replace(case, unsupported_length=1_000_000*case.shell_mid_surface_radius)
    numerical_limit = decimal_schur_pressure(remote_case, constants, 1, 2)
    assert math.isclose(eq64_limit, numerical_limit, rel_tol=1e-9)
    assert math.isclose(0.75*eq64_limit, eq66, rel_tol=1e-14)

    # DTMB Table 1, printed p. 6. These are different end conditions on
    # the same specimens, not extra applications of the Table 2 length map.
    support_tests = []
    for name, kendrick, case_i, case_v, ni, nv in (
        ("6", 499, 504, 700, 3, 3),
        ("2-A", 317, 339, 409, 2, 3),
        ("3-A", 216, 229, 378, 2, 2),
        ("4-A", 180, 178, 289, 2, 2),
    ):
        support_tests.append({
            "specimen": name,
            "kendrick_pressure_psi": kendrick,
            "case_I_pressure_psi": case_i,
            "case_V_pressure_psi": case_v,
            "case_I_lobes": ni,
            "case_V_lobes": nv,
            "case_V_increase_over_case_I_percent": percent(case_v, case_i),
        })

    mode_crossing = crossing()
    curve = []
    sample_spaces = sorted(
        [17.0 + index / 4.0 for index in range(65)]
        + [mode_crossing["frame_spaces"]]
    )
    for spaces in sample_spaces:
        variant = replace(case, unsupported_length=spaces*case.ring_spacing)
        n2 = _mode_pressure(variant, constants, 1, 2)
        n3 = _mode_pressure(variant, constants, 1, 3)
        curve.append({"frame_spaces": spaces, "m1_n2_psi": n2, "m1_n3_psi": n3})

    return {
        "schema_version": "1.0.0",
        "purpose": "diagnostic investigation, no calibration or production method change",
        "source_experiment": {
            "specimen": "DTMB 1324 cylinder 4-A",
            "number_of_physical_cylinders_in_table_2": 1,
            "number_of_support_configurations": 10,
            "measurement": "Southwell nondestructive estimate of elastic buckling pressure",
            "pdf_sha256": "975aaf2ef7f4b0adde9cd15dd8dc5ea378e91e097d5f145d60923aeeede728a2",
        },
        "mode_scan": {"m": [1, 128], "n": [2, 64]},
        "table_2": records,
        "n2_n3_crossing": mode_crossing,
        "long_cylinder_diagnostic": {
            "effective_circumferential_bending_lbf_in": effective_bending,
            "eq64_n2_ideal_limit_psi": eq64_limit,
            "eq64_n2_ideal_limit_numerical_psi": numerical_limit,
            "eq66_ideal_pressure_psi": eq66,
            "adjusted_eq64_limit_psi": 0.75*eq64_limit,
            "eq64_over_eq66": eq64_limit / eq66,
            "scope": "asymptotic check only; not a finite-length transition selector",
        },
        "table_1_support_sensitivity": support_tests,
        "controlled_input_perturbations": sensitivity(),
        "perturbation_scope": "diagnostics, not manufacturing tolerances or uncertainty bounds",
        "m1_mode_curves": curve,
    }


def plot_results(results: dict[str, Any], output: Path) -> None:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    rows = results["table_2"]
    curves = results["m1_mode_curves"]
    x = [row["frame_spaces"] for row in rows]
    cx = [row["frame_spaces"] for row in curves]
    plt.rcParams.update({"font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "svg.hashsalt": "dtmb1324"})
    fig, axes = plt.subplots(2, 1, figsize=(10, 8), sharex=True,
                             gridspec_kw={"height_ratios": [3, 1.3]})
    ax = axes[0]
    ax.plot(x, [r["southwell_experimental_pressure_psi"] for r in rows],
            "o-", color="#172b4d", label="DTMB experiment (Southwell estimate)")
    ax.plot(x, [r["kendrick_pressure_psi"] for r in rows],
            "s--", color="#707780", label="DTMB Kendrick Part III")
    minimum = [min(r["m1_n2_psi"], r["m1_n3_psi"]) for r in curves]
    ax.plot(cx, minimum, "-", color="#147d92", label="pv-calc ideal, minimum mode")
    ax.plot(x, [r["ideal_pressure_psi"] for r in rows], "^", color="#147d92")
    ax.plot(cx, [0.75*p for p in minimum], "-", color="#c46716", label="pv-calc after 0.75")
    ax.plot(x, [r["adjusted_pressure_psi"] for r in rows], "D", color="#c46716")
    ax.plot(cx, [0.75*r["m1_n3_psi"] for r in curves],
            ":", color="#c46716", alpha=0.65, label="Three-lobe branch after 0.75 (diagnostic)")
    ax.set(ylabel="Pressure (psi)", ylim=(170, 565))
    ax.grid(axis="y", alpha=0.2)
    ax.legend(loc="upper right", frameon=False, fontsize=9)
    ax.set_title("Pressure agreement and mode agreement are separate checks", loc="left", pad=15)
    lower = axes[1]
    lower.plot(x, [r["experimental_lobes"] for r in rows], "o-", color="#172b4d", label="Experiment")
    lower.plot(x, [r["kendrick_lobes"] for r in rows], "s--", color="#707780", label="Kendrick")
    crossing_spaces = results["n2_n3_crossing"]["frame_spaces"]
    lower.plot([17, crossing_spaces, crossing_spaces, 33], [3, 3, 2, 2],
               "-", color="#147d92", label="pv-calc")
    lower.plot(x, [r["model_mode"][1] for r in rows], "^", color="#147d92")
    lower.axvline(crossing_spaces, color="#147d92", linestyle=":", alpha=0.6)
    lower.text(24.0, 2.43, "pv-calc crossing:\n19.585 frame spaces", color="#147d92", fontsize=9)
    lower.set(xlabel="Frame spaces between internal supports", ylabel="Circumferential lobes",
              yticks=[2, 3], ylim=(1.85, 3.4), xticks=x, xlim=(16.5, 33.5))
    lower.grid(axis="y", alpha=0.2)
    lower.legend(loc="upper right", ncol=3, frameon=False, fontsize=9)
    fig.suptitle("DTMB 1324: ten support configurations of one cylinder", x=0.08,
                 ha="left", fontsize=15, fontweight="bold")
    fig.text(0.08, 0.022, "Source: DTMB 1324, Fig. 2 and Table 2; NASA SP-8007 Rev. 2, Eqs. 64/65 and 82-91.\n"
             "Lines between published points are guides. No pressure factor changes the selected lobe count.",
             fontsize=9, color="#4c5664")
    fig.subplots_adjust(left=0.08, right=0.98, top=0.9, bottom=0.13, hspace=0.18)
    output.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(output, dpi=180, metadata={"Date": None} if output.suffix == ".svg" else None)
    plt.close(fig)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--plot", type=Path)
    args = parser.parse_args()
    results = build_results()
    encoded = json.dumps(results, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(encoded, encoding="utf-8")
        print(f"Verified diagnostic results: {args.output}")
    else:
        print(encoded, end="")
    if args.plot:
        plot_results(results, args.plot)
        print(f"Figure: {args.plot}")


if __name__ == "__main__":
    main()
