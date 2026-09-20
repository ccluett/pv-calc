"""Reproduce the failed CalculiX pressure-buckling procedure qualification."""

from __future__ import annotations

import argparse
import cmath
import json
import math
from pathlib import Path
import re
import sys
from typing import Any


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from validation.fea.run_fea import (  # noqa: E402
    DOCKERFILE,
    _run_ccx,
    _sha256,
    check_toolchain,
)


RADIUS_MM = 2540.0
SECTION_MM = 25.4
ELASTIC_MODULUS_MPA = 206_800.0
DENSITY_TONNE_PER_MM3 = 7.85e-9
REFERENCE_PRESSURE_MPA = 0.05171

# The direct pressures are secant estimates from their signed brackets. They
# are fixed here so reruns reproduce the retained decks and directly check that
# each estimate is near a native tangent-eigenvalue zero.
CASES = (
    ("M32-mean", (32, 2, 2), "outer_lower", (0.08, 0.084), 0.0835340359906297),
    ("M48-mean", (48, 3, 3), "outer_lower", (0.0, 0.0517), 0.04998653210742279),
    ("M48-point", (48, 3, 3), "point", (0.0, 0.0517), 0.0499861323125939),
    ("M64-mean", (64, 4, 4), "outer_lower", (0.0, 0.0517), 0.044304337282652644),
    ("M96-mean", (96, 4, 4), "outer_lower", (0.04, 0.044), 0.0421621748773),
    ("M128-mean", (128, 4, 4), "outer_lower", (0.04, 0.044), 0.0417898891961),
)


def _wrapped(ids: list[int]) -> list[str]:
    return [
        ",".join(map(str, ids[index : index + 16]))
        for index in range(0, len(ids), 16)
    ]


def _equation(terms: list[tuple[int, int, float]]) -> list[str]:
    fields: list[str] = []
    for node, dof, coefficient in terms:
        fields += [str(node), str(dof), f"{coefficient:.12g}"]
    return [
        "*EQUATION",
        str(len(terms)),
        *(
            ",".join(fields[index : index + 12])
            for index in range(0, len(fields), 12)
        ),
    ]


def _element_lines(element: int, nodes: tuple[int, ...]) -> list[str]:
    fields = [str(element), *map(str, nodes)]
    return [",".join(fields[:16]) + ",", ",".join(fields[16:])]


def _deck(
    *, pressure: float, mesh: tuple[int, int, int], gauge: str
) -> tuple[str, dict[int, tuple[float, float, float]]]:
    circumferential, radial, width = mesh
    nr, nt, nz = 2 * radial, 2 * circumferential, 2 * width
    inner = RADIUS_MM - SECTION_MM / 2.0
    zmin = -SECTION_MM / 2.0
    node_ids: dict[tuple[int, int, int], int] = {}
    coordinates: dict[int, tuple[float, float, float]] = {}
    node_lines: list[str] = []
    for k in range(nz + 1):
        for j in range(nt):
            for i in range(nr + 1):
                if i % 2 + j % 2 + k % 2 >= 2:
                    continue
                node_id = len(node_ids) + 1
                radius = inner + SECTION_MM * i / nr
                theta = 2.0 * math.pi * j / nt
                raw_xyz = (
                    radius * math.cos(theta),
                    radius * math.sin(theta),
                    zmin + SECTION_MM * k / nz,
                )
                xyz = (
                    0.0 if abs(raw_xyz[0]) < 1.0e-12 else raw_xyz[0],
                    0.0 if abs(raw_xyz[1]) < 1.0e-12 else raw_xyz[1],
                    0.0 if abs(raw_xyz[2]) < 1.0e-12 else raw_xyz[2],
                )
                node_ids[(i, j, k)] = node_id
                coordinates[node_id] = xyz
                node_lines.append(
                    f"{node_id},{xyz[0]:.16g},{xyz[1]:.16g},{xyz[2]:.16g}"
                )

    def node(i: int, j: int, k: int) -> int:
        return node_ids[(i, j % nt, k)]

    elements: list[tuple[int, tuple[int, ...], int]] = []
    for element_k in range(width):
        k = 2 * element_k
        for element_j in range(circumferential):
            j = 2 * element_j
            for element_i in range(radial):
                i = 2 * element_i
                nodes = (
                    node(i, j, k),
                    node(i + 2, j, k),
                    node(i + 2, j + 2, k),
                    node(i, j + 2, k),
                    node(i, j, k + 2),
                    node(i + 2, j, k + 2),
                    node(i + 2, j + 2, k + 2),
                    node(i, j + 2, k + 2),
                    node(i + 1, j, k),
                    node(i + 2, j + 1, k),
                    node(i + 1, j + 2, k),
                    node(i, j + 1, k),
                    node(i + 1, j, k + 2),
                    node(i + 2, j + 1, k + 2),
                    node(i + 1, j + 2, k + 2),
                    node(i, j + 1, k + 2),
                    node(i, j, k + 1),
                    node(i + 2, j, k + 1),
                    node(i + 2, j + 2, k + 1),
                    node(i, j + 2, k + 1),
                )
                elements.append((len(elements) + 1, nodes, element_i))

    outer_elements = [
        element for element, _, radial_index in elements if radial_index == radial - 1
    ]
    gauge_i, gauge_k = nr, 0
    gauge_nodes = [node(gauge_i, j, gauge_k) for j in range(nt)]
    probe_nodes = [node(nr, j, 0) for j in range(nt)]
    count = len(gauge_nodes)
    mean_x = [(node_id, 1, 1.0 / count) for node_id in gauge_nodes]
    mean_y = [(node_id, 2, 1.0 / count) for node_id in gauge_nodes]
    rotation: list[tuple[int, int, float]] = []
    for node_id in gauge_nodes:
        x, y, _ = coordinates[node_id]
        theta = math.atan2(y, x)
        coefficient_x = -math.sin(theta) / count
        coefficient_y = math.cos(theta) / count
        if abs(coefficient_x) > 1.0e-14:
            rotation.append((node_id, 1, coefficient_x))
        if abs(coefficient_y) > 1.0e-14:
            rotation.append((node_id, 2, coefficient_y))
    rotation.sort(
        key=lambda term: (
            0
            if term[:2] == (node(gauge_i, nt // 4, gauge_k), 1)
            else 1
        )
    )
    constraints = (
        [*_equation(mean_x), *_equation(mean_y), *_equation(rotation)]
        if gauge != "point"
        else []
    )
    boundary = ["NALL,3,3,0"]
    if gauge == "point":
        boundary.extend(
            [
                f"{node(nr, 0, 0)},1,2,0",
                f"{node(nr, nt // 2, 0)},2,2,0",
            ]
        )

    lines = [
        "** Full 3D ring; mm, N, s, MPa",
        "*NODE,NSET=NALL",
        *node_lines,
        "*ELEMENT,TYPE=C3D20,ELSET=EALL",
        *(
            line
            for element, nodes, _ in elements
            for line in _element_lines(element, nodes)
        ),
        "*ELSET,ELSET=EOUT",
        *_wrapped(outer_elements),
        "*NSET,NSET=NPROBE",
        *_wrapped(probe_nodes),
        "*MATERIAL,NAME=MAT",
        "*ELASTIC",
        f"{ELASTIC_MODULUS_MPA},0.0",
        "*DENSITY",
        f"{DENSITY_TONNE_PER_MM3}",
        "*SOLID SECTION,ELSET=EALL,MATERIAL=MAT",
        *constraints,
        "*BOUNDARY",
        *boundary,
        "*STEP,NLGEOM,INC=100",
        "*STATIC",
        "0.1,1.0,1e-06,0.1",
        "*DLOAD",
        f"EOUT,P4,{pressure:.16g}",
        "*NODE PRINT,NSET=NALL,TOTALS=ONLY",
        "RF",
        "*END STEP",
        "*STEP,PERTURBATION",
        "*FREQUENCY,SOLVER=SPOOLES",
        "8",
        "*DLOAD",
        f"EOUT,P4,{pressure:.16g}",
        "*NODE PRINT,NSET=NPROBE",
        "U",
        "*END STEP",
        "",
    ]
    return "\n".join(lines), {
        node_id: coordinates[node_id] for node_id in probe_nodes
    }


def _eigenvalues(path: Path) -> list[float]:
    values: list[float] = []
    active = False
    started = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if "E I G E N V A L U E   O U T P U T" in line:
            active = True
            continue
        if active and started and not line.strip():
            break
        fields = line.split()
        if not active or len(fields) < 5:
            continue
        try:
            mode = int(fields[0])
            eigenvalue = float(fields[1])
        except ValueError:
            continue
        if mode == len(values) + 1:
            values.append(eigenvalue)
            started = True
            if len(values) == 8:
                break
    if len(values) != 8 or any(not math.isfinite(value) for value in values):
        raise RuntimeError(f"expected eight finite eigenvalues in {path}: {values}")
    if any(values[index] > values[index + 1] for index in range(7)):
        raise RuntimeError(f"eigenvalues are not ascending in {path}: {values}")
    return values


def _eigenvectors(path: Path) -> dict[int, dict[int, tuple[float, float, float]]]:
    result: dict[int, dict[int, tuple[float, float, float]]] = {}
    mode: int | None = None
    active = False
    pattern = re.compile(r"E I G E N V A L U E\s+N U M B E R\s+(\d+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = pattern.search(line)
        if match:
            mode = int(match.group(1))
            active = False
            continue
        if line.lstrip().startswith("displacements "):
            active = mode is not None and "set NPROBE " in line
            continue
        fields = line.split()
        if not active or mode is None or len(fields) != 4:
            continue
        try:
            result.setdefault(mode, {})[int(fields[0])] = (
                float(fields[1]),
                float(fields[2]),
                float(fields[3]),
            )
        except ValueError:
            continue
    return result


def _mode_shape(
    displacements: dict[int, tuple[float, float, float]],
    coordinates: dict[int, tuple[float, float, float]],
) -> dict[str, float | int]:
    count = len(displacements)
    translation_x = sum(value[0] for value in displacements.values()) / count
    translation_y = sum(value[1] for value in displacements.values()) / count
    rotation = sum(
        -coordinates[node][1] * (value[0] - translation_x)
        + coordinates[node][0] * (value[1] - translation_y)
        for node, value in displacements.items()
    ) / sum(
        coordinates[node][0] ** 2 + coordinates[node][1] ** 2
        for node in displacements
    )
    radial: list[tuple[float, float]] = []
    for node, displacement in displacements.items():
        x, y, _ = coordinates[node]
        radius = math.hypot(x, y)
        ux = displacement[0] - translation_x + rotation * y
        uy = displacement[1] - translation_y - rotation * x
        radial.append((math.atan2(y, x), (x * ux + y * uy) / radius))
    energies: dict[int, float] = {}
    for lobes in range(7):
        coefficient = sum(
            value * cmath.exp(-1j * lobes * theta) for theta, value in radial
        ) / len(radial)
        energies[lobes] = abs(coefficient) ** 2
    lobes = max(range(1, 7), key=energies.__getitem__)
    return {
        "circumferential_lobes": lobes,
        "dominant_radial_energy_fraction": energies[lobes] / sum(energies.values()),
    }


def _job_name(pressure: float, mesh: tuple[int, int, int], gauge: str) -> str:
    label = str(pressure).replace(".", "p")
    return f"ring_p{label}_c{mesh[0]}_r{mesh[1]}_w{mesh[2]}_{gauge}"


def _read_evaluation(
    directory: Path,
    *,
    pressure: float,
    mesh: tuple[int, int, int],
    gauge: str,
    coordinates: dict[int, tuple[float, float, float]],
) -> dict[str, Any]:
    job = _job_name(pressure, mesh, gauge)
    input_path = directory / f"{job}.inp"
    dat_path = directory / f"{job}.dat"
    stdout_path = directory / f"{job}.stdout.txt"
    values = _eigenvalues(dat_path)
    vectors = _eigenvectors(dat_path)
    if any(set(vectors.get(mode, {})) != set(coordinates) for mode in (1, 2)):
        raise RuntimeError(f"incomplete probe displacements in {dat_path}")
    return {
        "pressure_mpa": pressure,
        "first_two_eigenvalues": values[:2],
        "first_two_modes": [
            _mode_shape(vectors[mode], coordinates) for mode in (1, 2)
        ],
        "solver_warning_count": stdout_path.read_text(
            encoding="utf-8"
        ).count("*WARNING"),
        "input_sha256": _sha256(input_path),
        "dat_sha256": _sha256(dat_path),
        "stdout_sha256": _sha256(stdout_path),
    }


def _run_evaluation(
    work_directory: Path,
    *,
    pressure: float,
    mesh: tuple[int, int, int],
    gauge: str,
) -> dict[str, Any]:
    deck, coordinates = _deck(pressure=pressure, mesh=mesh, gauge=gauge)
    job = _job_name(pressure, mesh, gauge)
    directory, _ = _run_ccx(
        deck, job_name=job, keep_directory=work_directory / job
    )
    return _read_evaluation(
        directory,
        pressure=pressure,
        mesh=mesh,
        gauge=gauge,
        coordinates=coordinates,
    )


def _zero_from_direct(
    bracket: list[dict[str, Any]], direct: dict[str, Any]
) -> float:
    direct_pressure = float(direct["pressure_mpa"])
    direct_value = float(list(direct["first_two_eigenvalues"])[0])
    if direct_value == 0.0:
        return direct_pressure
    opposite = next(
        point
        for point in bracket
        if float(list(point["first_two_eigenvalues"])[0]) * direct_value < 0.0
    )
    opposite_pressure = float(opposite["pressure_mpa"])
    opposite_value = float(list(opposite["first_two_eigenvalues"])[0])
    return direct_pressure - direct_value * (
        opposite_pressure - direct_pressure
    ) / (opposite_value - direct_value)


def _summarize(
    cases: list[dict[str, Any]], toolchain: dict[str, str | int]
) -> dict[str, Any]:
    by_id = {str(case["case_id"]): case for case in cases}
    roots = {
        case_id: float(case["interpolated_zero_pressure_mpa"])
        for case_id, case in by_id.items()
    }
    finest_change = abs(roots["M128-mean"] - roots["M96-mean"]) / abs(
        roots["M128-mean"]
    )
    reference_error = abs(
        roots["M128-mean"] - REFERENCE_PRESSURE_MPA
    ) / REFERENCE_PRESSURE_MPA
    crossing_difference = abs(
        roots["M48-point"] - roots["M48-mean"]
    ) / abs(roots["M48-mean"])
    evaluations = [
        evaluation
        for case in cases
        for evaluation in [*list(case["bracket"]), case["direct_check"]]
    ]
    modes_are_n2 = all(
        all(
            int(mode["circumferential_lobes"]) == 2
            for mode in list(evaluation["first_two_modes"])
        )
        for evaluation in evaluations
    )
    warnings_are_zero = all(
        int(evaluation["solver_warning_count"]) == 0
        for evaluation in evaluations
    )
    numeric_checks_pass = all(
        (
            finest_change <= 0.02,
            reference_error <= 0.05,
            crossing_difference <= 0.005,
            modes_are_n2,
            warnings_are_zero,
        )
    )
    return {
        "schema_version": "1.0.0",
        "classification": "numerical_procedure_qualification",
        "rerun_command": (
            "uv run python validation/fea/pressure_ring_qualification.py "
            "--work-directory /tmp/pv-calc-pressure-ring "
            "--output /tmp/pressure_ring_qualification.json"
        ),
        "reference": {
            "source": (
                "https://docs.software.vt.edu/abaqusv2025/English/"
                "SIMACAEBMKRefMap/simabmk-c-ringbuckling.htm"
            ),
            "mean_radius_mm": RADIUS_MM,
            "square_section_mm": SECTION_MM,
            "elastic_modulus_mpa": ELASTIC_MODULUS_MPA,
            "poisson_ratio": 0.0,
            "critical_pressure_mpa_approx": REFERENCE_PRESSURE_MPA,
            "governing_circumferential_lobes": 2,
        },
        "procedure": {
            "element": "C3D20",
            "steps": ["STATIC,NLGEOM", "FREQUENCY,PERTURBATION"],
            "pressure_surface": "outer radial face",
            "out_of_plane_condition": "Uz=0 at every node",
            "density_tonne_per_mm3": DENSITY_TONNE_PER_MM3,
        },
        "acceptance_limits": {
            "finest_mesh_change_fraction": 0.02,
            "reference_pressure_error_fraction": 0.05,
            "minimum_crossing_gauge_difference_fraction": 0.005,
            "required_first_physical_lobes": 2,
        },
        "cases": cases,
        "checks": {
            "finest_mesh_change_fraction": finest_change,
            "finest_mesh_change_passes": finest_change <= 0.02,
            "finest_reference_pressure_error_fraction": reference_error,
            "reference_pressure_error_passes": reference_error <= 0.05,
            "minimum_crossing_gauge_difference_fraction": crossing_difference,
            "minimum_crossing_gauge_difference_passes": crossing_difference <= 0.005,
            "all_retained_first_two_modes_are_n2": modes_are_n2,
            "all_solver_warning_counts_are_zero": warnings_are_zero,
            "numeric_checks_pass": numeric_checks_pass,
        },
        "disposition": (
            "numeric checks pass; independent procedure review required"
            if numeric_checks_pass
            else "not qualified: one or more numeric checks failed"
        ),
        "toolchain": toolchain,
        "manifest": {
            "runner_sha256": _sha256(Path(__file__)),
            "shared_runner_sha256": _sha256(
                REPOSITORY_ROOT / "validation" / "fea" / "run_fea.py"
            ),
            "dockerfile_sha256": _sha256(REPOSITORY_ROOT / DOCKERFILE),
        },
    }


def run(work_directory: Path, output: Path) -> None:
    toolchain = check_toolchain()
    cases: list[dict[str, Any]] = []
    for case_id, mesh, gauge, pressure_bracket, direct_pressure in CASES:
        bracket = [
            _run_evaluation(
                work_directory,
                pressure=float(pressure),
                mesh=mesh,
                gauge=gauge,
            )
            for pressure in pressure_bracket
        ]
        direct = _run_evaluation(
            work_directory,
            pressure=direct_pressure,
            mesh=mesh,
            gauge=gauge,
        )
        low_value = float(list(bracket[0]["first_two_eigenvalues"])[0])
        high_value = float(list(bracket[1]["first_two_eigenvalues"])[0])
        if low_value <= 0.0 or high_value >= 0.0:
            raise RuntimeError(
                f"{case_id} does not retain a signed zero bracket"
            )
        cases.append(
            {
                "case_id": case_id,
                "circumferential_elements": mesh[0],
                "radial_elements": mesh[1],
                "axial_elements": mesh[2],
                "rigid_motion_gauge": gauge,
                "bracket": bracket,
                "direct_check": direct,
                "interpolated_zero_pressure_mpa": _zero_from_direct(
                    bracket, direct
                ),
            }
        )
    summary = _summarize(cases, toolchain)
    output.write_text(
        json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    run(arguments.work_directory, arguments.output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
