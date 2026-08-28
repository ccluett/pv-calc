"""Opt-in CalculiX validation runner.

This is deliberately a case-specific runner, not an FEA abstraction layer.
It generates inspectable text decks in a temporary directory and keeps all
solver tooling outside PV-Gen's runtime dependencies.
"""

from __future__ import annotations

import argparse
import cmath
from collections import defaultdict
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Literal


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
IMAGE = "pv-gen-fea:ccx2.20"
DOCKERFILE = "validation/fea/toolchain/Dockerfile"
DOCKER_BUILD_HINT = f"docker build --tag {IMAGE} validation/fea/toolchain"

if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from validation.non_ring_reference import (  # noqa: E402
    closed_end_tube_reference,
    flat_circular_plate_reference,
)
from validation.ring_shell_reference import (  # noqa: E402
    DTMB_TABLE_2_PUBLISHED,
    dtmb_case,
    solve_case as solve_ring_reference,
)


class ToolchainUnavailable(RuntimeError):
    pass


def _run(
    command: list[str],
    *,
    cwd: Path | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=cwd,
        check=check,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )


def check_toolchain() -> dict[str, str | int]:
    docker = shutil.which("docker")
    if docker is None:
        raise ToolchainUnavailable(
            "Docker is unavailable. Install/start Docker, then build the pinned image with: "
            f"{DOCKER_BUILD_HINT}"
        )
    daemon = _run([docker, "info", "--format", "{{.ServerVersion}}"], check=False)
    if daemon.returncode != 0:
        raise ToolchainUnavailable(
            "Docker is installed but its daemon is unavailable. Start Docker Desktop and retry. "
            f"Diagnostic: {daemon.stdout.strip()}"
        )
    image_listing = _run(
        [
            docker,
            "image",
            "ls",
            "--filter",
            f"reference={IMAGE}",
            "--no-trunc",
            "--format",
            "{{.ID}}",
        ],
        check=False,
    )
    image_ids = [line for line in image_listing.stdout.splitlines() if line]
    if image_listing.returncode != 0 or len(image_ids) != 1:
        raise ToolchainUnavailable(
            f"Pinned FEA image {IMAGE!r} is absent. Build it with: {DOCKER_BUILD_HINT}"
        )
    inspection = _run(
        [
            docker,
            "image",
            "inspect",
            image_ids[0],
            "--format",
            "{{.Id}} {{.Size}} {{.Architecture}}",
        ],
        check=False,
    )
    if inspection.returncode != 0:
        raise ToolchainUnavailable(
            f"Pinned FEA image {IMAGE!r} was listed but could not be inspected. "
            f"Diagnostic: {inspection.stdout.strip()}"
        )
    # ccx -v exits nonzero by design, so success is judged by the banner text.
    version = _run(
        [docker, "run", "--rm", IMAGE, "sh", "-lc", "ccx -v || true"],
        check=False,
    )
    if version.returncode != 0 or "Version 2.20" not in version.stdout:
        raise ToolchainUnavailable(
            "Pinned image does not expose the required ccx 2.20 executable. "
            f"Diagnostic: {version.stdout.strip()}"
        )
    image_id, image_size, architecture = inspection.stdout.strip().split()
    return {
        "docker_server_version": daemon.stdout.strip(),
        "image": IMAGE,
        "image_id": image_id,
        "image_content_size_bytes": int(image_size),
        "architecture": architecture,
        "calculix_version": "2.20",
    }


def _wrapped_ids(ids: Iterable[int]) -> str:
    values = list(ids)
    return "\n".join(
        ",".join(str(value) for value in values[index : index + 16])
        for index in range(0, len(values), 16)
    )


def _structured_q8_mesh(
    *,
    radial_min: float,
    radial_max: float,
    axial_min: float,
    axial_max: float,
    radial_elements: int,
    axial_elements: int,
) -> tuple[dict[tuple[int, int], int], list[str], list[tuple[int, tuple[int, ...], int, int]]]:
    node_ids: dict[tuple[int, int], int] = {}
    nodes: list[str] = []
    for axial_index in range(2 * axial_elements + 1):
        for radial_index in range(2 * radial_elements + 1):
            if radial_index % 2 == 1 and axial_index % 2 == 1:
                continue
            node_id = len(node_ids) + 1
            node_ids[(radial_index, axial_index)] = node_id
            radius = radial_min + (radial_max - radial_min) * radial_index / (
                2 * radial_elements
            )
            axial = axial_min + (axial_max - axial_min) * axial_index / (
                2 * axial_elements
            )
            nodes.append(f"{node_id},{radius:.16g},{axial:.16g},0")

    elements: list[tuple[int, tuple[int, ...], int, int]] = []
    for axial_element in range(axial_elements):
        for radial_element in range(radial_elements):
            radial_index = 2 * radial_element
            axial_index = 2 * axial_element
            connectivity = (
                node_ids[(radial_index, axial_index)],
                node_ids[(radial_index + 2, axial_index)],
                node_ids[(radial_index + 2, axial_index + 2)],
                node_ids[(radial_index, axial_index + 2)],
                node_ids[(radial_index + 1, axial_index)],
                node_ids[(radial_index + 2, axial_index + 1)],
                node_ids[(radial_index + 1, axial_index + 2)],
                node_ids[(radial_index, axial_index + 1)],
            )
            elements.append(
                (len(elements) + 1, connectivity, radial_element, axial_element)
            )
    return node_ids, nodes, elements


def tube_deck(*, radial_elements: int, axial_elements: int) -> tuple[str, dict[str, float | int]]:
    internal_radius = 3.0
    wall_thickness = 0.470
    external_radius = internal_radius + wall_thickness
    length = 4.0
    pressure = 1_000.0
    elastic_modulus = 10_300_000.0
    poisson_ratio = 0.33
    axial_stress = pressure * external_radius**2 / (
        external_radius**2 - internal_radius**2
    )
    node_ids, nodes, elements = _structured_q8_mesh(
        radial_min=internal_radius,
        radial_max=external_radius,
        axial_min=0.0,
        axial_max=length,
        radial_elements=radial_elements,
        axial_elements=axial_elements,
    )
    outer_elements = [item[0] for item in elements if item[2] == radial_elements - 1]
    top_elements = [item[0] for item in elements if item[3] == axial_elements - 1]
    middle_axial = axial_elements // 2
    middle_elements = [item[0] for item in elements if item[3] == middle_axial]
    bottom_nodes = [
        node_id for (radial_index, axial_index), node_id in node_ids.items() if axial_index == 0
    ]
    all_nodes = list(node_ids.values())
    lines = [
        "** P5-03 closed-end thick tube; inch, lbf, psi",
        "*NODE,NSET=NALL",
        *nodes,
        "*ELEMENT,TYPE=CAX8R,ELSET=EALL",
        *(f"{element_id}," + ",".join(str(node) for node in connectivity) for element_id, connectivity, _, _ in elements),
        "*ELSET,ELSET=EOUT",
        _wrapped_ids(outer_elements),
        "*ELSET,ELSET=ETOP",
        _wrapped_ids(top_elements),
        "*ELSET,ELSET=EMID",
        _wrapped_ids(middle_elements),
        "*NSET,NSET=NBOTTOM",
        _wrapped_ids(bottom_nodes),
        "*MATERIAL,NAME=MAT",
        "*ELASTIC",
        f"{elastic_modulus:.16g},{poisson_ratio:.16g}",
        "*SOLID SECTION,ELSET=EALL,MATERIAL=MAT",
        "*BOUNDARY",
        "NBOTTOM,2,2,0",
        "*STEP",
        "*STATIC",
        "*DLOAD",
        f"EOUT,P2,{pressure:.16g}",
        f"ETOP,P3,{axial_stress:.16g}",
        "*EL PRINT,ELSET=EMID",
        "S",
        "*NODE PRINT,NSET=NBOTTOM",
        "RF",
        "*NODE PRINT,NSET=NALL,TOTALS=ONLY",
        "RF",
        "*EL FILE,ELSET=EALL",
        "S",
        "*NODE FILE,NSET=NALL",
        "U,RF",
        "*END STEP",
        "",
    ]
    return "\n".join(lines), {
        "radial_elements": radial_elements,
        "axial_elements": axial_elements,
        "nodes": len(all_nodes),
        "elements": len(elements),
        "internal_radius_in": internal_radius,
        "external_radius_in": external_radius,
        "length_in": length,
        "pressure_psi": pressure,
        "closed_end_axial_stress_psi": axial_stress,
    }


PLATE_FREE_RADIUS_MM = 50.0
PLATE_THICKNESS_MM = 10.0
PLATE_PRESSURE_MPA = 2.0
PLATE_ELASTIC_MODULUS_MPA = 70_000.0
PLATE_POISSON_RATIO = 0.30


def plate_deck(
    *,
    boundary_condition: Literal["fixed", "simply_supported"],
    radial_elements: int,
    thickness_elements: int,
    free_radius: float = PLATE_FREE_RADIUS_MM,
    plate_thickness: float = PLATE_THICKNESS_MM,
    poisson_ratio: float = PLATE_POISSON_RATIO,
) -> tuple[str, dict[str, object]]:
    radius = free_radius
    thickness = plate_thickness
    pressure = PLATE_PRESSURE_MPA
    elastic_modulus = PLATE_ELASTIC_MODULUS_MPA
    node_ids, nodes, elements = _structured_q8_mesh(
        radial_min=0.0,
        radial_max=radius,
        axial_min=-thickness / 2.0,
        axial_max=thickness / 2.0,
        radial_elements=radial_elements,
        axial_elements=thickness_elements,
    )
    top_elements = [
        item[0] for item in elements if item[3] == thickness_elements - 1
    ]
    center_elements = [item[0] for item in elements if item[2] == 0]
    axis_nodes = [
        node_id
        for (radial_index, _), node_id in node_ids.items()
        if radial_index == 0
    ]
    edge_nodes = [
        node_id
        for (radial_index, _), node_id in node_ids.items()
        if radial_index == 2 * radial_elements
    ]
    # Mid-plane offsets of the edge nodes, for the clamped-edge reaction
    # moment.  The mesh spans -t/2 to +t/2 axially, so the axial coordinate
    # is already the lever arm about the plate mid-plane.
    edge_node_axial = {
        node_id: -thickness / 2.0
        + thickness * axial_index / (2.0 * thickness_elements)
        for (radial_index, axial_index), node_id in node_ids.items()
        if radial_index == 2 * radial_elements
    }
    edge_mid_node = node_ids[(2 * radial_elements, thickness_elements)]
    center_mid_node = node_ids[(0, thickness_elements)]
    boundary_lines = ["NAXIS,1,1,0"]
    equation_lines: list[str] = []
    if boundary_condition == "fixed":
        # The production model declares a fixed edge that prevents radial
        # rotation and transverse deflection while allowing radial
        # displacement (UnderPressure 4.0 Appendix B).  The cylindrical cut
        # face therefore fixes the axial component pointwise (w = 0) and
        # couples every face node's radial component to the mid-plane face
        # node, which removes cross-section rotation and warping while
        # leaving the uniform radial slide free.  Fixing the radial
        # component pointwise instead would additionally suppress the
        # Poisson-driven through-thickness radial strain at the clamp, a
        # stiffer restraint than the one production declares.
        boundary_lines.append("NEDGE,2,2,0")
        support_set = "NEDGE"
        for node_id in edge_node_axial:
            if node_id == edge_mid_node:
                continue
            equation_lines.extend(
                [
                    "*EQUATION",
                    "2",
                    f"{node_id},1,1,{edge_mid_node},1,-1",
                ]
            )
    else:
        # The production model declares a simply-supported edge that prevents
        # transverse deflection while allowing radial rotation and
        # displacement (UnderPressure 4.0 Appendix B).  In the continuum the
        # edge is the whole cylindrical cut face, so the axial component is
        # fixed pointwise through the thickness (w = 0) and both radial
        # components stay free: the section rotates through unconstrained
        # through-thickness radial displacement.  Supporting only the
        # mid-plane node instead idealizes the seat as a zero-width knife-edge
        # line, whose compliance is singular in the three-dimensional
        # continuum — the center deflection then grows without bound under
        # mesh refinement — so that realization is not used.
        boundary_lines.append("NEDGE,2,2,0")
        support_set = "NEDGE"
    lines = [
        f"** P5-03 {boundary_condition} circular plate; mm, N, MPa",
        "*NODE,NSET=NALL",
        *nodes,
        "*ELEMENT,TYPE=CAX8R,ELSET=EALL",
        *(f"{element_id}," + ",".join(str(node) for node in connectivity) for element_id, connectivity, _, _ in elements),
        "*ELSET,ELSET=ETOP",
        _wrapped_ids(top_elements),
        "*ELSET,ELSET=ECENTER",
        _wrapped_ids(center_elements),
        "*NSET,NSET=NAXIS",
        _wrapped_ids(axis_nodes),
        "*NSET,NSET=NEDGE",
        _wrapped_ids(edge_nodes),
        "*NSET,NSET=NCENTER",
        str(center_mid_node),
        "*MATERIAL,NAME=MAT",
        "*ELASTIC",
        f"{elastic_modulus:.16g},{poisson_ratio:.16g}",
        "*SOLID SECTION,ELSET=EALL,MATERIAL=MAT",
        *equation_lines,
        "*BOUNDARY",
        *boundary_lines,
        "*STEP",
        "*STATIC",
        "*DLOAD",
        f"ETOP,P3,{pressure:.16g}",
        "*EL PRINT,ELSET=ECENTER",
        "S",
        "*NODE PRINT,NSET=NCENTER",
        "U",
        f"*NODE PRINT,NSET={support_set}",
        "RF",
        "*NODE PRINT,NSET=NALL,TOTALS=ONLY",
        "RF",
        "*EL FILE,ELSET=EALL",
        "S",
        "*NODE FILE,NSET=NALL",
        "U,RF",
        "*END STEP",
        "",
    ]
    return "\n".join(lines), {
        "boundary_condition": boundary_condition,
        "support_set": support_set,
        "radial_elements": radial_elements,
        "thickness_elements": thickness_elements,
        "nodes": len(node_ids),
        "elements": len(elements),
        "free_radius_mm": radius,
        "plate_thickness_mm": thickness,
        "pressure_mpa": pressure,
        "elastic_modulus_mpa": elastic_modulus,
        "poisson_ratio": poisson_ratio,
        "center_mid_node": center_mid_node,
        "edge_node_axial_mm": edge_node_axial,
    }


def ring_shell_deck(
    *,
    frame_spaces: int,
    circumferential_elements: int,
    axial_elements_per_bay: int,
    requested_modes: int = 12,
) -> tuple[str, dict[str, object], dict[int, tuple[float, float, float]]]:
    """Generate one discrete-ring DTMB shell eigenvalue deck.

    The S8R shell and B32 rings share every ring-plane node.  The B32
    reference line remains on the shell mid-surface; ``OFFSET2`` places the
    physical rectangle centroid outside it.
    """

    case = dtmb_case(frame_spaces)
    if circumferential_elements % 4:
        raise ValueError("circumferential element count must be divisible by four")
    if axial_elements_per_bay < 1:
        raise ValueError("axial elements per bay must be positive")

    axial_elements = frame_spaces * axial_elements_per_bay
    theta_half_count = 2 * circumferential_elements
    axial_half_count = 2 * axial_elements
    node_ids: dict[tuple[int, int], int] = {}
    coordinates: dict[int, tuple[float, float, float]] = {}
    node_lines: list[str] = []
    radius = case.shell_mid_surface_radius
    for axial_half_index in range(axial_half_count + 1):
        for theta_half_index in range(theta_half_count):
            if theta_half_index % 2 == 1 and axial_half_index % 2 == 1:
                continue
            node_id = len(node_ids) + 1
            theta = 2.0 * math.pi * theta_half_index / theta_half_count
            axial = (
                case.unsupported_length * axial_half_index / axial_half_count
            )
            radial_x = radius * math.cos(theta)
            radial_y = radius * math.sin(theta)
            coordinate = (
                0.0 if abs(radial_x) < 1.0e-14 else radial_x,
                0.0 if abs(radial_y) < 1.0e-14 else radial_y,
                axial,
            )
            node_ids[(theta_half_index, axial_half_index)] = node_id
            coordinates[node_id] = coordinate
            node_lines.append(
                f"{node_id},{coordinate[0]:.16g},{coordinate[1]:.16g},{coordinate[2]:.16g}"
            )

    shell_elements: list[tuple[int, tuple[int, ...]]] = []
    for axial_index in range(axial_elements):
        axial_half_index = 2 * axial_index
        for theta_index in range(circumferential_elements):
            theta_half_index = 2 * theta_index

            def node(theta_offset: int, axial_offset: int) -> int:
                return node_ids[
                    (
                        (theta_half_index + theta_offset) % theta_half_count,
                        axial_half_index + axial_offset,
                    )
                ]

            connectivity = (
                node(0, 0),
                node(2, 0),
                node(2, 2),
                node(0, 2),
                node(1, 0),
                node(2, 1),
                node(1, 2),
                node(0, 1),
            )
            shell_elements.append((len(shell_elements) + 1, connectivity))

    ring_elements: list[tuple[int, tuple[int, int, int]]] = []
    next_element = len(shell_elements) + 1
    for ring_plane in range(frame_spaces + 1):
        axial_half_index = 2 * ring_plane * axial_elements_per_bay
        for theta_index in range(circumferential_elements):
            theta_half_index = 2 * theta_index
            connectivity = (
                node_ids[(theta_half_index, axial_half_index)],
                node_ids[((theta_half_index + 1) % theta_half_count, axial_half_index)],
                node_ids[((theta_half_index + 2) % theta_half_count, axial_half_index)],
            )
            ring_elements.append((next_element, connectivity))
            next_element += 1

    left_nodes = [node_ids[(index, 0)] for index in range(theta_half_count)]
    right_nodes = [
        node_ids[(index, axial_half_count)] for index in range(theta_half_count)
    ]
    radial_x_nodes: list[int] = []
    radial_y_nodes: list[int] = []
    radial_equations: list[str] = []
    for axial_half_index in (0, axial_half_count):
        for theta_half_index in range(theta_half_count):
            node_id = node_ids[(theta_half_index, axial_half_index)]
            theta = 2.0 * math.pi * theta_half_index / theta_half_count
            cosine = math.cos(theta)
            sine = math.sin(theta)
            if abs(sine) < 1.0e-12:
                radial_x_nodes.append(node_id)
            elif abs(cosine) < 1.0e-12:
                radial_y_nodes.append(node_id)
            else:
                radial_equations.extend(
                    [
                        "*EQUATION",
                        "2",
                        f"{node_id},1,{cosine:.16g},{node_id},2,{sine:.16g}",
                    ]
                )

    end_force = math.pi * radius**2
    end_load_lines: list[str] = []
    for theta_half_index in range(theta_half_count):
        weight = (
            1.0 / (3.0 * circumferential_elements)
            if theta_half_index % 2 == 0
            else 2.0 / (3.0 * circumferential_elements)
        )
        end_load_lines.append(
            f"{node_ids[(theta_half_index, 0)]},3,{weight * end_force:.16g}"
        )
        end_load_lines.append(
            f"{node_ids[(theta_half_index, axial_half_count)]},3,{-weight * end_force:.16g}"
        )

    offset_distance = (
        case.wall_thickness / 2.0 + case.ring_radial_height / 2.0
    )
    offset2 = -offset_distance / case.ring_radial_height
    shell_ids = [item[0] for item in shell_elements]
    ring_ids = [item[0] for item in ring_elements]
    reference_node = node_ids[(0, 0)]
    model_lines = [
        f"** {frame_spaces}-space DTMB discrete-ring ideal eigenvalue model",
        "** inch, lbf, psi; negative shell-normal traction gives external pressure",
        "*NODE,NSET=NALL",
        *node_lines,
        "*ELEMENT,TYPE=S8R,ELSET=ESHELL",
        *(
            f"{element_id}," + ",".join(str(value) for value in connectivity)
            for element_id, connectivity in shell_elements
        ),
        "*ELEMENT,TYPE=B32R,ELSET=ERING",
        *(
            f"{element_id}," + ",".join(str(value) for value in connectivity)
            for element_id, connectivity in ring_elements
        ),
        "*ELSET,ELSET=ESHELL_ALL",
        _wrapped_ids(shell_ids),
        "*ELSET,ELSET=ERING_ALL",
        _wrapped_ids(ring_ids),
        "*NSET,NSET=NSHELL",
        _wrapped_ids(node_ids.values()),
        "*NSET,NSET=NLEFT",
        _wrapped_ids(left_nodes),
        "*NSET,NSET=NRIGHT",
        _wrapped_ids(right_nodes),
        "*NSET,NSET=NRADX",
        _wrapped_ids(radial_x_nodes),
        "*NSET,NSET=NRADY",
        _wrapped_ids(radial_y_nodes),
        "*NSET,NSET=NREFERENCE",
        str(reference_node),
        "*MATERIAL,NAME=MAT",
        "*ELASTIC",
        f"{case.elastic_modulus:.16g},{case.poisson_ratio:.16g}",
        "*SHELL SECTION,ELSET=ESHELL,MATERIAL=MAT",
        f"{case.wall_thickness:.16g}",
        (
            "*BEAM SECTION,ELSET=ERING,MATERIAL=MAT,SECTION=RECT,"
            f"OFFSET2={offset2:.16g}"
        ),
        f"{case.ring_axial_width:.16g},{case.ring_radial_height:.16g}",
        "0,0,1",
        *radial_equations,
        "*BOUNDARY",
        "NRADX,1,1,0",
        "NRADY,2,2,0",
        "NREFERENCE,2,3,0",
    ]
    load_lines = [
        "*DLOAD",
        "ESHELL,P,-1",
        "*CLOAD",
        *end_load_lines,
    ]
    lines = [
        *model_lines,
        "*STEP",
        "*STATIC",
        *load_lines,
        "*NODE PRINT,NSET=NALL,TOTALS=ONLY",
        "RF",
        "*NODE PRINT,NSET=NLEFT,TOTALS=ONLY",
        "RF",
        "*NODE PRINT,NSET=NRIGHT,TOTALS=ONLY",
        "RF",
        "*NODE FILE,NSET=NSHELL",
        "U",
        "*END STEP",
        "*STEP",
        "*BUCKLE,SOLVER=SPOOLES",
        f"{requested_modes},0.001",
        *load_lines,
        "*NODE PRINT,NSET=NSHELL",
        "U",
        "*EL PRINT,ELSET=ESHELL_ALL,TOTALS=ONLY",
        "ELSE",
        "*EL PRINT,ELSET=ERING_ALL,TOTALS=ONLY",
        "ELSE",
        "*NODE FILE,NSET=NSHELL",
        "U",
        "*END STEP",
        "",
    ]
    return "\n".join(lines), {
        "frame_spaces": frame_spaces,
        "circumferential_elements": circumferential_elements,
        "axial_elements_per_bay": axial_elements_per_bay,
        "axial_elements": axial_elements,
        "original_nodes": len(node_ids),
        "shell_elements": len(shell_elements),
        "ring_elements": len(ring_elements),
        "total_elements": len(shell_elements) + len(ring_elements),
        "shell_element_type": "S8R",
        "ring_element_type": "B32R",
        "ring_count": frame_spaces + 1,
        "shell_mid_surface_radius_in": radius,
        "unsupported_length_in": case.unsupported_length,
        "ring_spacing_in": case.ring_spacing,
        "ring_reference_offset2": offset2,
        "ring_centroid_offset_in": offset_distance,
        "unit_pressure_psi": 1.0,
        "closed_end_force_each_lbf": end_force,
        "requested_modes": requested_modes,
        "reference_node": reference_node,
    }, coordinates


def _run_ccx(deck: str, *, job_name: str, keep_directory: Path | None = None) -> tuple[Path, str]:
    if keep_directory is None:
        work_directory = Path(tempfile.mkdtemp(prefix="pv-gen-fea-"))
    else:
        work_directory = keep_directory.resolve()
        work_directory.mkdir(parents=True, exist_ok=True)
    deck_path = work_directory / f"{job_name}.inp"
    deck_path.write_text(deck, encoding="utf-8")
    docker = shutil.which("docker")
    assert docker is not None
    command = [
        docker,
        "run",
        "--rm",
        "--user",
        f"{os.getuid()}:{os.getgid()}",
        "--volume",
        f"{work_directory}:/work",
        "--workdir",
        "/work",
        IMAGE,
        "ccx",
        job_name,
    ]
    completed = _run(command, check=False)
    (work_directory / f"{job_name}.stdout.txt").write_text(
        completed.stdout,
        encoding="utf-8",
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"CalculiX failed for {job_name} with exit {completed.returncode}; "
            f"artifacts retained at {work_directory}\n{completed.stdout}"
        )
    return work_directory, completed.stdout


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _dat_stresses(path: Path, set_name: str) -> dict[int, list[tuple[float, ...]]]:
    rows: dict[int, list[tuple[float, ...]]] = {}
    active = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.lstrip().startswith("stresses "):
            active = f"set {set_name} " in line
            continue
        if active and line.lstrip().startswith(("displacements ", "forces ")):
            break
        fields = line.split()
        if not active or len(fields) != 8:
            continue
        try:
            element = int(fields[0])
            int(fields[1])
            values = tuple(float(value) for value in fields[2:])
        except ValueError:
            continue
        rows.setdefault(element, []).append(values)
    if not rows:
        raise RuntimeError(f"no stress rows for set {set_name} in {path}")
    return rows


def _dat_nodal_vectors(
    path: Path,
    *,
    heading: str,
    set_name: str,
) -> dict[int, tuple[float, float, float]]:
    rows: dict[int, tuple[float, float, float]] = {}
    active = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.lstrip()
        if stripped.startswith(("stresses ", "displacements ", "forces ")):
            active = stripped.startswith(heading) and f"set {set_name} " in line
            continue
        fields = line.split()
        if not active or len(fields) != 4:
            continue
        try:
            node = int(fields[0])
            values = tuple(float(value) for value in fields[1:])
        except ValueError:
            continue
        rows[node] = values  # type: ignore[assignment]
    if not rows:
        raise RuntimeError(f"no {heading.strip()} rows for set {set_name} in {path}")
    return rows


def _dat_total_vector(path: Path, set_name: str) -> tuple[float, float, float]:
    """Read a CalculiX ``TOTALS=ONLY`` node-force vector."""

    active = False
    for line in path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if stripped.startswith("total force "):
            active = f"set {set_name} " in line
            continue
        fields = stripped.split()
        if not active or len(fields) != 3:
            continue
        try:
            return tuple(float(value) for value in fields)  # type: ignore[return-value]
        except ValueError:
            continue
    raise RuntimeError(f"no total force vector for set {set_name} in {path}")


def _dat_buckling_factors(path: Path) -> list[float]:
    factors: list[float] = []
    active = False
    for line in path.read_text(encoding="utf-8").splitlines():
        if "B U C K L I N G   F A C T O R   O U T P U T" in line:
            active = True
            continue
        if active and "E I G E N V A L U E" in line:
            break
        fields = line.split()
        if not active or len(fields) != 2:
            continue
        try:
            mode_number = int(fields[0])
            factor = float(fields[1])
        except ValueError:
            continue
        if mode_number != len(factors) + 1:
            raise RuntimeError(f"non-sequential buckling factors in {path}")
        factors.append(factor)
    if not factors:
        raise RuntimeError(f"no buckling factors in {path}")
    return factors


def _dat_displacement_blocks(
    path: Path,
    set_name: str,
) -> tuple[
    dict[int, tuple[float, float, float]],
    dict[int, dict[int, tuple[float, float, float]]],
]:
    """Return the unit-static displacement and each printed eigenvector."""

    static: dict[int, tuple[float, float, float]] = {}
    eigenvectors: dict[int, dict[int, tuple[float, float, float]]] = {}
    current_mode: int | None = None
    target: dict[int, tuple[float, float, float]] | None = None
    heading_pattern = re.compile(r"E I G E N V A L U E\s+N U M B E R\s+(\d+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = heading_pattern.search(line)
        if match:
            current_mode = int(match.group(1))
            target = None
            continue
        stripped = line.lstrip()
        if stripped.startswith("displacements "):
            if f"set {set_name} " not in line:
                target = None
            elif current_mode is None:
                target = static
            else:
                target = eigenvectors.setdefault(current_mode, {})
            continue
        if stripped.startswith(("total force ", "stresses ")):
            target = None
            continue
        fields = line.split()
        if target is None or len(fields) != 4:
            continue
        try:
            node = int(fields[0])
            vector = tuple(float(value) for value in fields[1:])
        except ValueError:
            continue
        target[node] = vector  # type: ignore[assignment]
    if not static:
        raise RuntimeError(f"no unit-static displacements for {set_name} in {path}")
    if not eigenvectors:
        raise RuntimeError(f"no eigenvectors for {set_name} in {path}")
    return static, eigenvectors


def _ring_mode_count(
    displacements: dict[int, tuple[float, float, float]],
    coordinates: dict[int, tuple[float, float, float]],
    *,
    unsupported_length: float,
) -> dict[str, object]:
    """Count lobes and axial half-waves from shell-normal displacements."""

    radial_by_axial: dict[float, list[tuple[float, float]]] = defaultdict(list)
    for node, displacement in displacements.items():
        if node not in coordinates:
            continue
        x, y, axial = coordinates[node]
        radius = math.hypot(x, y)
        radial_displacement = (
            x * displacement[0] + y * displacement[1]
        ) / radius
        radial_by_axial[round(axial, 12)].append(
            (math.atan2(y, x), radial_displacement)
        )
    if len(radial_by_axial) < 3:
        raise RuntimeError("insufficient axial stations for independent mode count")

    minimum_station_samples = min(len(values) for values in radial_by_axial.values())
    maximum_lobes = min(12, minimum_station_samples // 2 - 1)
    angular_coefficients: dict[int, list[tuple[float, complex]]] = {}
    angular_energy: dict[int, float] = {}
    for lobes in range(maximum_lobes + 1):
        coefficients: list[tuple[float, complex]] = []
        for axial, values in sorted(radial_by_axial.items()):
            coefficient = sum(
                displacement * cmath.exp(-1j * lobes * angle)
                for angle, displacement in values
            ) / len(values)
            coefficients.append((axial, coefficient))
        angular_coefficients[lobes] = coefficients
        angular_energy[lobes] = sum(abs(value) ** 2 for _, value in coefficients)
    lobes = max(range(1, maximum_lobes + 1), key=angular_energy.__getitem__)
    coefficients = angular_coefficients[lobes]

    maximum_half_waves = min(12, len(coefficients) - 2)
    axial_fit: dict[int, float] = {}
    coefficient_energy = sum(abs(value) ** 2 for _, value in coefficients)
    for half_waves in range(1, maximum_half_waves + 1):
        shape = [
            math.sin(half_waves * math.pi * axial / unsupported_length)
            for axial, _ in coefficients
        ]
        shape_energy = sum(value**2 for value in shape)
        projection = sum(
            coefficient * value
            for (_, coefficient), value in zip(coefficients, shape, strict=True)
        )
        axial_fit[half_waves] = (
            abs(projection) ** 2 / (shape_energy * coefficient_energy)
            if shape_energy and coefficient_energy
            else 0.0
        )
    half_waves = max(axial_fit, key=axial_fit.__getitem__)
    total_angular_energy = sum(angular_energy.values())
    endpoint_amplitude = max(
        abs(angular_coefficients[lobes][0][1]),
        abs(angular_coefficients[lobes][-1][1]),
    )
    maximum_amplitude = max(abs(value) for _, value in coefficients)
    endpoint_fraction = (
        endpoint_amplitude / maximum_amplitude if maximum_amplitude else 0.0
    )
    fit = axial_fit[half_waves]
    classification = (
        "global_sinusoidal"
        if lobes >= 2 and fit >= 0.80 and endpoint_fraction <= 0.05
        else "other_or_local"
    )
    return {
        "axial_half_waves_m": half_waves,
        "circumferential_lobes_n": lobes,
        "dominant_angular_energy_fraction": (
            angular_energy[lobes] / total_angular_energy
            if total_angular_energy
            else 0.0
        ),
        "axial_sine_fit_fraction": fit,
        "end_radial_amplitude_fraction": endpoint_fraction,
        "classification": classification,
        "method": (
            "DFT of shell-normal displacement at every axial station, followed "
            "by complex least-squares projection onto sin(m*pi*x/L)"
        ),
    }


def _dat_modal_internal_energies(
    path: Path,
) -> dict[int, dict[str, float]]:
    energies: dict[int, dict[str, float]] = {}
    current_mode: int | None = None
    pending_set: str | None = None
    heading_pattern = re.compile(r"E I G E N V A L U E\s+N U M B E R\s+(\d+)")
    for line in path.read_text(encoding="utf-8").splitlines():
        match = heading_pattern.search(line)
        if match:
            current_mode = int(match.group(1))
            pending_set = None
            continue
        stripped = line.strip()
        if stripped.startswith("total internal energy for set "):
            fields = stripped.split()
            pending_set = fields[5] if current_mode is not None else None
            continue
        if pending_set is None or current_mode is None:
            continue
        try:
            value = float(stripped)
        except ValueError:
            continue
        energies.setdefault(current_mode, {})[pending_set] = value
        pending_set = None
    if not energies:
        raise RuntimeError(f"no modal internal-energy partitions in {path}")
    return energies


def _line_extrapolate(value_minus: float, value_plus: float, target: float) -> float:
    gauss = 1.0 / math.sqrt(3.0)
    return value_minus + (value_plus - value_minus) * (
        (target + gauss) / (2.0 * gauss)
    )


def _tube_surface_stresses(
    rows: dict[int, list[tuple[float, ...]]],
    *,
    radial_elements: int,
    axial_elements: int,
) -> dict[str, dict[str, float]]:
    middle_axial = axial_elements // 2
    inner_element = middle_axial * radial_elements + 1
    outer_element = middle_axial * radial_elements + radial_elements

    def extrapolate(element: int, target: float) -> dict[str, float]:
        values = rows[element]
        if len(values) != 8:
            raise RuntimeError(f"expected eight CAX8R integration rows for element {element}")
        minus = [sum(values[index][component] for index in (0, 2, 4, 6)) / 4.0 for component in range(3)]
        plus = [sum(values[index][component] for index in (1, 3, 5, 7)) / 4.0 for component in range(3)]
        result = [_line_extrapolate(a, b, target) for a, b in zip(minus, plus, strict=True)]
        return {
            "radial_stress_psi": result[0],
            "axial_stress_psi": result[1],
            "hoop_stress_psi": result[2],
        }

    return {
        "inner_surface": extrapolate(inner_element, -1.0),
        "outer_surface": extrapolate(outer_element, 1.0),
    }


def _bilinear_gauss_extrapolate(
    values: tuple[float, float, float, float],
    *,
    target_x: float,
    target_y: float,
) -> float:
    gauss = 1.0 / math.sqrt(3.0)
    x_minus = (gauss - target_x) / (2.0 * gauss)
    x_plus = (gauss + target_x) / (2.0 * gauss)
    y_minus = (gauss - target_y) / (2.0 * gauss)
    y_plus = (gauss + target_y) / (2.0 * gauss)
    minus_minus, plus_minus, minus_plus, plus_plus = values
    return (
        x_minus * y_minus * minus_minus
        + x_plus * y_minus * plus_minus
        + x_minus * y_plus * minus_plus
        + x_plus * y_plus * plus_plus
    )


def _plate_center_surface_stress(
    rows: dict[int, list[tuple[float, ...]]],
    *,
    radial_elements: int,
    thickness_elements: int,
) -> dict[str, float]:
    top_center_element = (thickness_elements - 1) * radial_elements + 1
    values = rows[top_center_element]
    if len(values) != 8:
        raise RuntimeError(
            f"expected eight CAX8R integration rows for element {top_center_element}"
        )

    def component_at_surface(component: int) -> float:
        # CAX8R expands to a two-degree sector.  Pairs (1,5), (2,6),
        # (3,7), and (4,8) are duplicate circumferential stations at the
        # four radial/thickness Gauss locations.
        gauss_values = (
            (values[0][component] + values[4][component]) / 2.0,
            (values[1][component] + values[5][component]) / 2.0,
            (values[2][component] + values[6][component]) / 2.0,
            (values[3][component] + values[7][component]) / 2.0,
        )
        return _bilinear_gauss_extrapolate(
            gauss_values,
            target_x=-1.0,
            target_y=1.0,
        )

    radial = component_at_surface(0)
    hoop = component_at_surface(2)
    return {
        "radial_bending_stress_mpa": radial,
        "hoop_bending_stress_mpa": hoop,
        "mean_in_plane_bending_stress_mpa": (abs(radial) + abs(hoop)) / 2.0,
    }


def _relative_error(actual: float, expected: float) -> float:
    return abs(actual / expected - 1.0)


def _runtime_seconds(stdout: str) -> float:
    for line in stdout.splitlines():
        if line.startswith("Total CalculiX Time:"):
            return float(line.split(":", maxsplit=1)[1].strip())
    raise RuntimeError("CalculiX runtime was not found in stdout")


PLATE_MESH_LADDER = ((8, 2), (16, 4), (32, 8))


def _run_plate_mesh(
    *,
    boundary: Literal["fixed", "simply_supported"],
    free_radius: float,
    plate_thickness: float,
    radial_elements: int,
    thickness_elements: int,
    mesh_id: str,
    job_name: str,
    work_directory: Path,
    poisson_ratio: float = PLATE_POISSON_RATIO,
) -> dict[str, object]:
    """Solve one axisymmetric plate mesh and read its center response."""

    deck, metadata = plate_deck(
        boundary_condition=boundary,
        radial_elements=radial_elements,
        thickness_elements=thickness_elements,
        free_radius=free_radius,
        plate_thickness=plate_thickness,
        poisson_ratio=poisson_ratio,
    )
    job_directory = work_directory / job_name
    _, stdout = _run_ccx(deck, job_name=job_name, keep_directory=job_directory)
    dat_path = job_directory / f"{job_name}.dat"
    center_surface = _plate_center_surface_stress(
        _dat_stresses(dat_path, "ECENTER"),
        radial_elements=radial_elements,
        thickness_elements=thickness_elements,
    )
    displacement = _dat_nodal_vectors(
        dat_path,
        heading="displacements ",
        set_name="NCENTER",
    )
    center_node = int(metadata["center_mid_node"])
    reactions = _dat_nodal_vectors(
        dat_path,
        heading="forces ",
        set_name=str(metadata["support_set"]),
    )
    support_axial_force = 180.0 * sum(value[1] for value in reactions.values())
    applied_force = math.pi * float(metadata["free_radius_mm"]) ** 2 * float(
        metadata["pressure_mpa"]
    )
    row: dict[str, object] = {
        "mesh_id": mesh_id,
        "radial_elements": metadata["radial_elements"],
        "thickness_elements": metadata["thickness_elements"],
        "nodes": metadata["nodes"],
        "elements": metadata["elements"],
        "element_type": "CAX8R",
        "center_deflection_mm": abs(displacement[center_node][1]),
        "center_top_surface": center_surface,
        "support_set_axial_force_n": support_axial_force,
        "applied_transverse_force_n": applied_force,
        "global_equilibrium_residual_fraction": (
            abs(180.0 * _dat_total_vector(dat_path, "NALL")[1]) / applied_force
        ),
        "runtime_seconds": _runtime_seconds(stdout),
        "input_sha256": _sha256(job_directory / f"{job_name}.inp"),
        "dat_sha256": _sha256(dat_path),
    }
    # Both boundary conditions restrain the whole cylindrical cut face, which
    # includes the pressure-loaded top-corner node.  Its consistent load
    # share appears in the printed nodal forces, so no clean
    # reaction-vs-applied check exists; the recorded global equilibrium
    # residual is the solver self-consistency check instead.
    row["support_set_includes_pressure_loaded_corner"] = True
    if boundary == "fixed":
        # Governing fixed-edge quantity.  The pointwise three-dimensional
        # stress at the ideal sharp clamped corner is singular and does not
        # converge under refinement, so the released Kirchhoff edge stress
        # 0.75*p*(a/t)^2 = 6*M_edge/t^2 is compared through its section
        # moment resultant instead: the first moment of the clamped-face
        # radial nodal reactions about the plate mid-plane.  The applied
        # pressure loads the top face axially only, so the radial reactions
        # are pure constraint forces and the moment is an equilibrium
        # quantity that converges.
        edge_axial = metadata["edge_node_axial_mm"]
        edge_moment_full_circle = 180.0 * sum(
            reactions[node][0] * lever for node, lever in edge_axial.items()  # type: ignore[union-attr]
        )
        edge_moment_per_length = edge_moment_full_circle / (
            2.0 * math.pi * free_radius
        )
        row["edge_radial_reaction_moment_full_circle_n_mm"] = edge_moment_full_circle
        row["edge_bending_moment_n_mm_per_mm"] = edge_moment_per_length
        row["edge_bending_stress_mpa"] = (
            6.0 * abs(edge_moment_per_length) / plate_thickness**2
        )
    return row


def _run_p5_03_meshes(work_directory: Path) -> dict[str, object]:
    toolchain = check_toolchain()
    work_directory.mkdir(parents=True, exist_ok=True)
    tube_meshes: list[dict[str, object]] = []
    for index, (radial_elements, axial_elements) in enumerate(
        ((4, 8), (8, 16), (16, 32)),
        start=1,
    ):
        deck, metadata = tube_deck(
            radial_elements=radial_elements,
            axial_elements=axial_elements,
        )
        job_name = f"tube_m{index}"
        job_directory = work_directory / job_name
        _, stdout = _run_ccx(deck, job_name=job_name, keep_directory=job_directory)
        dat_path = job_directory / f"{job_name}.dat"
        surface_stresses = _tube_surface_stresses(
            _dat_stresses(dat_path, "EMID"),
            radial_elements=radial_elements,
            axial_elements=axial_elements,
        )
        reactions = _dat_nodal_vectors(
            dat_path,
            heading="forces ",
            set_name="NBOTTOM",
        )
        # The bottom constraint plane carries no axial share of the pressure
        # loads, so its axial reaction resultant must equal the analytically
        # applied closed-end force.  This is the discriminating force-balance
        # check; the NALL residual is only a solver equilibrium identity.
        bottom_axial_reaction = 180.0 * sum(
            value[1] for value in reactions.values()
        )
        applied_axial_force = math.pi * float(metadata["external_radius_in"]) ** 2 * float(
            metadata["pressure_psi"]
        )
        tube_axial_traction = float(metadata["closed_end_axial_stress_psi"])
        tube_meshes.append(
            {
                "mesh_id": f"M{index}",
                "radial_elements": metadata["radial_elements"],
                "axial_elements": metadata["axial_elements"],
                "nodes": metadata["nodes"],
                "elements": metadata["elements"],
                "element_type": "CAX8R",
                "surface_stresses": surface_stresses,
                "bottom_axial_reaction_lbf": bottom_axial_reaction,
                "applied_closed_end_force_lbf": applied_axial_force,
                "support_reaction_vs_applied_fraction": _relative_error(
                    abs(bottom_axial_reaction), applied_axial_force
                ),
                "global_equilibrium_residual_fraction": (
                    abs(180.0 * _dat_total_vector(dat_path, "NALL")[1])
                    / applied_axial_force
                ),
                "runtime_seconds": _runtime_seconds(stdout),
                "input_sha256": _sha256(job_directory / f"{job_name}.inp"),
                "dat_sha256": _sha256(dat_path),
            }
        )

    plate_meshes: dict[str, list[dict[str, object]]] = {}
    for boundary in ("simply_supported", "fixed"):
        plate_meshes[boundary] = [
            _run_plate_mesh(
                boundary=boundary,  # type: ignore[arg-type]
                free_radius=PLATE_FREE_RADIUS_MM,
                plate_thickness=PLATE_THICKNESS_MM,
                radial_elements=radial_elements,
                thickness_elements=thickness_elements,
                mesh_id=f"M{index}",
                job_name=f"plate_{boundary}_m{index}",
                work_directory=work_directory,
            )
            for index, (radial_elements, thickness_elements) in enumerate(
                PLATE_MESH_LADDER,
                start=1,
            )
        ]

    tube_reference = closed_end_tube_reference(
        external_pressure=1_000.0,
        internal_radius=3.0,
        wall_thickness=0.470,
        yield_strength=62_000.0,
    )
    # This evidence compares the solver against the independent reference
    # only.  Production-versus-reference parity for the same tube and plate
    # points lives in ordinary live tests, so production code is not an input
    # to this artifact.  Only the reference values the FEA comparison reads
    # are stored; yield-dependent outputs, margins, and applicability fields
    # are not comparison targets and are not mirrored here.
    tube_targets = {
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
    independent_plates: dict[str, dict[str, object]] = {}
    for boundary in ("simply_supported", "fixed"):
        reference = flat_circular_plate_reference(
            external_pressure=2.0,
            free_radius=50.0,
            plate_thickness=10.0,
            elastic_modulus=70_000.0,
            poisson_ratio=0.30,
            yield_strength=300.0,
            boundary_condition=boundary,  # type: ignore[arg-type]
        )
        independent_plates[boundary] = {
            "source_equation_case": reference["source_equation_case"],
            "maximum_deflection": reference["maximum_deflection"],
            "maximum_tangential_bending_stress": reference[
                "maximum_tangential_bending_stress"
            ],
        }

    tube_comparisons: list[dict[str, object]] = []
    for mesh in tube_meshes:
        locations: dict[str, dict[str, float]] = {}
        for location, state in zip(
            ("inner_surface", "outer_surface"),
            tube_reference["stress_states"],
            strict=True,
        ):
            fea_state = mesh["surface_stresses"][location]  # type: ignore[index]
            locations[location] = {
                "radial_absolute_error_fraction_of_pressure": (
                    abs(fea_state["radial_stress_psi"]) / 1_000.0
                    if state["radial_stress"] == 0.0
                    else _relative_error(
                        fea_state["radial_stress_psi"], state["radial_stress"]
                    )
                ),
                "hoop_relative_error": _relative_error(
                    fea_state["hoop_stress_psi"], state["hoop_stress"]
                ),
                "axial_relative_error": _relative_error(
                    fea_state["axial_stress_psi"], state["axial_stress"]
                ),
            }
        tube_comparisons.append({"mesh_id": mesh["mesh_id"], "locations": locations})

    plate_comparisons: dict[str, list[dict[str, float | str]]] = {}
    for boundary, meshes in plate_meshes.items():
        reference = independent_plates[boundary]
        plate_comparisons[boundary] = [
            {
                "mesh_id": str(mesh["mesh_id"]),
                "center_deflection_relative_error": _relative_error(
                    float(mesh["center_deflection_mm"]),
                    float(reference["maximum_deflection"]),
                ),
                "center_bending_stress_relative_error": _relative_error(
                    float(
                        mesh["center_top_surface"]["mean_in_plane_bending_stress_mpa"]  # type: ignore[index]
                    ),
                    float(reference["maximum_tangential_bending_stress"]),
                ),
            }
            for mesh in meshes
        ]

    def finest_change(values: list[float]) -> float:
        return _relative_error(values[-1], values[-2])

    convergence = {
        "tube": {
            location: {
                component: finest_change(
                    [
                        float(mesh["surface_stresses"][location][component])  # type: ignore[index]
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
                    [float(mesh["center_deflection_mm"]) for mesh in meshes]
                ),
                "center_bending_stress_change": finest_change(
                    [
                        float(
                            mesh["center_top_surface"]["mean_in_plane_bending_stress_mpa"]  # type: ignore[index]
                        )
                        for mesh in meshes
                    ]
                ),
            }
            for boundary, meshes in plate_meshes.items()
        },
    }
    tolerances = {
        "support_reaction_vs_applied_fraction": 0.005,
        "tube_finest_mesh_component_change": 0.005,
        "tube_analytical_component_relative_error": 0.01,
        "plate_finest_mesh_deflection_change": 0.01,
        "plate_finest_mesh_center_stress_change": 0.02,
        "plate_analytical_deflection_relative_error": 0.05,
        "plate_analytical_center_stress_relative_error": 0.05,
    }
    tube_acceptance = {
        "finest_mesh_change_pass": all(
            value <= tolerances["tube_finest_mesh_component_change"]
            for location in convergence["tube"].values()
            for value in location.values()
        ),
        "analytical_agreement_pass": all(
            value <= tolerances["tube_analytical_component_relative_error"]
            for comparison in tube_comparisons
            for location in comparison["locations"].values()
            for value in location.values()
        ),
        "force_balance_pass": all(
            float(mesh["support_reaction_vs_applied_fraction"])
            <= tolerances["support_reaction_vs_applied_fraction"]
            for mesh in tube_meshes
        ),
    }
    plate_acceptance: dict[str, dict[str, bool]] = {}
    for boundary in plate_meshes:
        plate_acceptance[boundary] = {
            "finest_mesh_deflection_change_pass": (
                convergence["plates"][boundary]["center_deflection_change"]
                <= tolerances["plate_finest_mesh_deflection_change"]
            ),
            "finest_mesh_stress_change_pass": (
                convergence["plates"][boundary]["center_bending_stress_change"]
                <= tolerances["plate_finest_mesh_center_stress_change"]
            ),
            "analytical_deflection_agreement_pass": (
                plate_comparisons[boundary][-1][
                    "center_deflection_relative_error"
                ]
                <= tolerances["plate_analytical_deflection_relative_error"]
            ),
            "analytical_stress_agreement_pass": (
                plate_comparisons[boundary][-1][
                    "center_bending_stress_relative_error"
                ]
                <= tolerances["plate_analytical_center_stress_relative_error"]
            ),
        }
    return {
        "schema_version": "1.2.0",
        "classification": {
            "evidence_role": "idealized_linear_elastic_fea_equation_comparison",
            "not": [
                "calibration",
                "allowable_pressure",
                "certification",
                "physical_validation",
                "design_approval",
            ],
        },
        "rerun_command": (
            "uv run python validation/fea/run_fea.py p5-03 "
            "--work-directory /tmp/pv-gen-p5-03 --output /tmp/p5_03_summary.json"
        ),
        "toolchain": toolchain,
        "tolerances": tolerances,
        "source_inputs": {
            "tube": {
                "source_case": "UnderPressure 4.0 Example 1 committed analytical example",
                "units": "inch_lbf_psi",
                "geometry": {
                    "internal_radius_in": 3.0,
                    "wall_thickness_in": 0.470,
                    "modeled_length_in": 4.0,
                },
                "load": {
                    "external_pressure_psi": 1_000.0,
                    "closed_end_axial_traction_psi": tube_axial_traction,
                },
                "material": {"elastic_modulus_psi": 10_300_000.0, "poisson_ratio": 0.33},
            },
            "plates": {
                "source_case": "committed synthetic fixed/simply-supported plate equation case",
                "units": "mm_n_mpa",
                "geometry": {"free_radius_mm": 50.0, "plate_thickness_mm": 10.0},
                "load": {"uniform_pressure_mpa": 2.0},
                "material": {"elastic_modulus_mpa": 70_000.0, "poisson_ratio": 0.30},
            },
        },
        "independent_calculations": {
            "tube": tube_targets,
            "plates": independent_plates,
        },
        "meshes": {
            "tube": tube_meshes,
            "simply_supported": plate_meshes["simply_supported"],
            "fixed": plate_meshes["fixed"],
        },
        "comparisons": {
            "tube": tube_comparisons,
            "plates": plate_comparisons,
            "finest_mesh_change": convergence,
        },
        "acceptance_evaluation": {
            "tube": tube_acceptance,
            "plates": plate_acceptance,
            "plate_force_balance_note": (
                "Both plate boundary conditions restrain the whole cut face, "
                "which includes pressure-loaded corner nodes whose consistent "
                "load share appears in the printed nodal forces, so no "
                "reaction-vs-applied acceptance check applies to the plates; "
                "the raw support_set_axial_force_n and the global equilibrium "
                "residual are retained."
            ),
            "all_predeclared_checks_pass": (
                all(tube_acceptance.values())
                and all(
                    all(boundary_checks.values())
                    for boundary_checks in plate_acceptance.values()
                )
            ),
            "disposition": (
                "Retain every comparison. A failed analytical-agreement check is "
                "a model-form disagreement, not a reason to alter inputs or tolerances."
            ),
        },
        # The code inputs to this evidence: the runner, the pinned container
        # recipe, and the independent reference that supplies every
        # analytical target.  No production code is executed here.
        "manifest": {
            "runner_sha256": _sha256(Path(__file__)),
            "dockerfile_sha256": _sha256(REPOSITORY_ROOT / DOCKERFILE),
            "reference_sha256": _sha256(
                REPOSITORY_ROOT / "validation" / "non_ring_reference.py"
            ),
        },
    }


# Swept free-diameter/thickness ratios and Poisson ratios.  The ratio points
# bracket the 5% Kirchhoff agreement budget for both boundary conditions, and
# the Poisson points bound the released evidence band, so every released
# floor is read off solved cases.
PLATE_SWEEP_DIAMETER_THICKNESS_RATIOS = (4.0, 6.0, 10.0, 14.0, 20.0, 30.0, 40.0)
PLATE_SWEEP_POISSON_RATIOS = (0.05, 0.30, 0.35)
PLATE_SWEEP_POISSON_EVIDENCE_BAND = (0.05, 0.35)

# Predeclared before the sweep ran.  A failure is retained and reported, not
# tuned away, exactly as for the P5-03 plate comparisons these extend.
PLATE_SWEEP_TOLERANCES = {
    "plate_finest_mesh_deflection_change": 0.01,
    "plate_finest_mesh_center_stress_change": 0.02,
    "plate_finest_mesh_edge_stress_change": 0.02,
    "kirchhoff_agreement_budget": 0.05,
}

MINDLIN_SHEAR_CORRECTION_FACTOR = 5.0 / 6.0

# Two deep meshes at four and eight times the primary finest mesh, solved at
# a compact set of sweep points.  The primary ladder's own convergence checks
# pass at every case; this study additionally demonstrates that the M3 values
# the floors are read from are mesh-stable, so a floor decision cannot hinge
# on residual discretization drift.  The points are the last ratio outside
# and the first ratio inside the 5% budget for the fixed outputs and the
# simply-supported deflection at their worst solved Poisson value, the
# thickest solved simply-supported case at the low band edge, and — because
# the shear-corrected estimate's margin over the solved deflection shrinks
# toward zero with thinness — the thinnest, low-Poisson case for both
# edges, where a deep mesh could most plausibly overturn that margin.
PLATE_DEEP_MESHES = (("D1", 128, 32), ("D2", 256, 64))
PLATE_DEEP_SENSITIVITY_POINTS = (
    ("simply_supported", 4.0, 0.05),
    ("simply_supported", 6.0, 0.35),
    ("simply_supported", 10.0, 0.35),
    ("simply_supported", 40.0, 0.05),
    ("fixed", 6.0, 0.35),
    ("fixed", 10.0, 0.35),
    ("fixed", 14.0, 0.35),
    ("fixed", 20.0, 0.35),
    ("fixed", 40.0, 0.05),
)


def _mindlin_shear_deflection_increment(
    *,
    pressure: float,
    free_radius: float,
    plate_thickness: float,
    elastic_modulus: float,
    poisson_ratio: float,
) -> float:
    """First-order shear-deformation center-deflection increment.

    ``q a^2 / (4 kappa G t)`` with ``kappa = 5/6``, the increment already
    recorded in ``validation/fea/README.md`` as the candidate explanation for
    the P5-03 fixed-plate deflection disagreement.  It is boundary-condition
    independent, so the same value is added to both Kirchhoff deflections.
    """

    shear_modulus = elastic_modulus / (2.0 * (1.0 + poisson_ratio))
    return (pressure * free_radius**2) / (
        4.0 * MINDLIN_SHEAR_CORRECTION_FACTOR * shear_modulus * plate_thickness
    )


def _sweep_case(
    *,
    ratio: float,
    poisson_ratio: float,
    work_directory: Path,
    budget: float,
) -> dict[str, object]:
    """Solve one (D_free/t, nu) sweep case over both boundary conditions."""

    thickness = 2.0 * PLATE_FREE_RADIUS_MM / ratio
    shear_increment = _mindlin_shear_deflection_increment(
        pressure=PLATE_PRESSURE_MPA,
        free_radius=PLATE_FREE_RADIUS_MM,
        plate_thickness=thickness,
        elastic_modulus=PLATE_ELASTIC_MODULUS_MPA,
        poisson_ratio=poisson_ratio,
    )
    label = f"r{ratio:g}_nu{poisson_ratio:g}".replace(".", "p")
    boundaries: dict[str, object] = {}
    for boundary in ("simply_supported", "fixed"):
        meshes = [
            _run_plate_mesh(
                boundary=boundary,  # type: ignore[arg-type]
                free_radius=PLATE_FREE_RADIUS_MM,
                plate_thickness=thickness,
                radial_elements=radial_elements,
                thickness_elements=thickness_elements,
                mesh_id=f"M{index}",
                job_name=f"sweep_{label}_{boundary}_m{index}",
                work_directory=work_directory,
                poisson_ratio=poisson_ratio,
            )
            for index, (radial_elements, thickness_elements) in enumerate(
                PLATE_MESH_LADDER,
                start=1,
            )
        ]
        reference = flat_circular_plate_reference(
            external_pressure=PLATE_PRESSURE_MPA,
            free_radius=PLATE_FREE_RADIUS_MM,
            plate_thickness=thickness,
            elastic_modulus=PLATE_ELASTIC_MODULUS_MPA,
            poisson_ratio=poisson_ratio,
            yield_strength=300.0,
            boundary_condition=boundary,  # type: ignore[arg-type]
        )
        kirchhoff_deflection = float(reference["maximum_deflection"])
        kirchhoff_center_stress = float(
            reference["maximum_tangential_bending_stress"]
        )
        finest = meshes[-1]
        previous = meshes[-2]
        fea_deflection = float(finest["center_deflection_mm"])
        fea_center_stress = float(
            finest["center_top_surface"][  # type: ignore[index]
                "mean_in_plane_bending_stress_mpa"
            ]
        )
        deflection_change = _relative_error(
            fea_deflection, float(previous["center_deflection_mm"])
        )
        center_stress_change = _relative_error(
            fea_center_stress,
            float(
                previous["center_top_surface"][  # type: ignore[index]
                    "mean_in_plane_bending_stress_mpa"
                ]
            ),
        )
        shear_corrected = kirchhoff_deflection + shear_increment
        checks: dict[str, bool] = {
            "finest_mesh_deflection_change_pass": (
                deflection_change
                <= PLATE_SWEEP_TOLERANCES["plate_finest_mesh_deflection_change"]
            ),
            "finest_mesh_center_stress_change_pass": (
                center_stress_change
                <= PLATE_SWEEP_TOLERANCES["plate_finest_mesh_center_stress_change"]
            ),
            "kirchhoff_deflection_within_budget": (
                _relative_error(fea_deflection, kirchhoff_deflection) <= budget
            ),
            "kirchhoff_center_stress_within_budget": (
                _relative_error(fea_center_stress, kirchhoff_center_stress)
                <= budget
            ),
        }
        entry: dict[str, Any] = {
            "meshes": meshes,
            "finest_mesh_change": {
                "center_deflection_change": deflection_change,
                "center_bending_stress_change": center_stress_change,
            },
            "kirchhoff": {
                "center_deflection_mm": kirchhoff_deflection,
                "center_tangential_bending_stress_mpa": kirchhoff_center_stress,
                "source_equation_case": reference["source_equation_case"],
                "maximum_deflection_over_thickness": (
                    kirchhoff_deflection / thickness
                ),
            },
            "finest_mesh_fea": {
                "center_deflection_mm": fea_deflection,
                "center_bending_stress_mpa": fea_center_stress,
            },
            # Signed, so the direction of the disagreement stays visible: a
            # positive value means the equation under-predicts.
            "fea_minus_kirchhoff_deflection_fraction": (
                fea_deflection / kirchhoff_deflection - 1.0
            ),
            "fea_minus_kirchhoff_center_stress_fraction": (
                fea_center_stress / kirchhoff_center_stress - 1.0
            ),
            "shear_corrected": {
                "predicted_center_deflection_mm": shear_corrected,
                "predicted_increment_fraction_of_kirchhoff": (
                    shear_increment / kirchhoff_deflection
                ),
                "fea_minus_predicted_fraction": (
                    fea_deflection / shear_corrected - 1.0
                ),
            },
        }
        if boundary == "fixed":
            # The quantity that actually sets the fixed-edge margin is the
            # Kirchhoff edge radial stress 0.75*p*(a/t)^2 = 6*M_edge/t^2, so
            # it is compared through the convergent clamped-face
            # reaction-moment resultant rather than the singular pointwise
            # corner stress.
            kirchhoff_edge_stress = float(
                reference["maximum_radial_bending_stress"]
            )
            fea_edge_stress = float(finest["edge_bending_stress_mpa"])
            edge_stress_change = _relative_error(
                fea_edge_stress, float(previous["edge_bending_stress_mpa"])
            )
            entry["kirchhoff"]["edge_radial_bending_stress_mpa"] = (
                kirchhoff_edge_stress
            )
            entry["finest_mesh_fea"]["edge_bending_stress_mpa"] = fea_edge_stress
            entry["finest_mesh_change"]["edge_bending_stress_change"] = (
                edge_stress_change
            )
            entry["fea_minus_kirchhoff_edge_stress_fraction"] = (
                fea_edge_stress / kirchhoff_edge_stress - 1.0
            )
            checks["finest_mesh_edge_stress_change_pass"] = (
                edge_stress_change
                <= PLATE_SWEEP_TOLERANCES["plate_finest_mesh_edge_stress_change"]
            )
            checks["kirchhoff_edge_stress_within_budget"] = (
                _relative_error(fea_edge_stress, kirchhoff_edge_stress) <= budget
            )
        entry["checks"] = checks
        boundaries[boundary] = entry
    return {
        "free_diameter_over_thickness": ratio,
        "poisson_ratio": poisson_ratio,
        "plate_thickness_mm": thickness,
        "thickness_over_free_radius": thickness / PLATE_FREE_RADIUS_MM,
        "mindlin_shear_increment_mm": shear_increment,
        "boundaries": boundaries,
    }


def _plate_mesh_quantity(mesh: dict[str, object], quantity: str) -> float:
    if quantity == "center_bending_stress_mpa":
        return float(
            mesh["center_top_surface"]["mean_in_plane_bending_stress_mpa"]  # type: ignore[index]
        )
    if quantity == "center_deflection_mm":
        return float(mesh["center_deflection_mm"])  # type: ignore[arg-type]
    return float(mesh["edge_bending_stress_mpa"])  # type: ignore[arg-type]


def _deep_mesh_sensitivity(
    *,
    case_for: Any,
    work_directory: Path,
    budget: float,
) -> dict[str, object]:
    """Deep-mesh stability of the decision-bearing primary-ladder readings.

    Every compared quantity is re-solved at four and eight times the primary
    finest mesh, the same convergence tolerances are applied one more ladder
    step down, and the within-budget decision is re-taken at the deepest
    mesh.  A floor is only as good as the mesh stability of the errors it is
    read from, so the decision-bearing fact here is that no within-budget
    boolean changes at the deepest mesh.
    """

    points: list[dict[str, object]] = []
    for boundary, ratio, poisson_ratio in PLATE_DEEP_SENSITIVITY_POINTS:
        case = case_for(ratio, poisson_ratio)
        entry = case["boundaries"][boundary]
        thickness = float(case["plate_thickness_mm"])
        label = f"deep_r{ratio:g}_nu{poisson_ratio:g}".replace(".", "p")
        deep = [
            _run_plate_mesh(
                boundary=boundary,  # type: ignore[arg-type]
                free_radius=PLATE_FREE_RADIUS_MM,
                plate_thickness=thickness,
                radial_elements=radial,
                thickness_elements=through,
                mesh_id=mesh_id,
                job_name=f"{label}_{boundary}_{mesh_id.lower()}",
                work_directory=work_directory,
                poisson_ratio=poisson_ratio,
            )
            for mesh_id, radial, through in PLATE_DEEP_MESHES
        ]
        specs = [
            (
                "center_deflection_mm",
                "center_deflection_mm",
                "plate_finest_mesh_deflection_change",
            ),
            (
                "center_bending_stress_mpa",
                "center_tangential_bending_stress_mpa",
                "plate_finest_mesh_center_stress_change",
            ),
        ]
        if boundary == "fixed":
            specs.append(
                (
                    "edge_bending_stress_mpa",
                    "edge_radial_bending_stress_mpa",
                    "plate_finest_mesh_edge_stress_change",
                )
            )
        per_quantity: dict[str, dict[str, object]] = {}
        for quantity, kirchhoff_key, tolerance_key in specs:
            primary_value = float(entry["finest_mesh_fea"][quantity])
            deep_values = [_plate_mesh_quantity(mesh, quantity) for mesh in deep]
            target = float(entry["kirchhoff"][kirchhoff_key])
            deepest = deep_values[-1]
            per_quantity[quantity] = {
                "primary_finest": primary_value,
                "deepest": deepest,
                "deepest_change": _relative_error(deepest, deep_values[-2]),
                "deepest_change_pass": (
                    _relative_error(deepest, deep_values[-2])
                    <= PLATE_SWEEP_TOLERANCES[tolerance_key]
                ),
                "primary_to_deepest_drift": _relative_error(deepest, primary_value),
                "fea_minus_kirchhoff_fraction_at_deepest": deepest / target - 1.0,
                "within_budget_at_deepest": (
                    _relative_error(deepest, target) <= budget
                ),
                "within_budget_at_primary": (
                    _relative_error(primary_value, target) <= budget
                ),
            }
        points.append(
            {
                "boundary_condition": boundary,
                "free_diameter_over_thickness": ratio,
                "poisson_ratio": poisson_ratio,
                "meshes": deep,
                "quantities": per_quantity,
                "budget_decisions_unchanged_at_deepest": all(
                    quantity["within_budget_at_deepest"]
                    == quantity["within_budget_at_primary"]
                    for quantity in per_quantity.values()
                ),
                "shear_corrected_estimate_exceeds_deepest_deflection": (
                    float(
                        entry["shear_corrected"]["predicted_center_deflection_mm"]
                    )
                    >= float(per_quantity["center_deflection_mm"]["deepest"])
                ),
            }
        )
    return {
        "deep_meshes": [
            {
                "mesh_id": mesh_id,
                "radial_elements": radial,
                "thickness_elements": through,
            }
            for mesh_id, radial, through in PLATE_DEEP_MESHES
        ],
        "points": points,
        "all_deepest_changes_pass": all(
            quantity["deepest_change_pass"]
            for point in points
            for quantity in point["quantities"].values()  # type: ignore[union-attr]
        ),
        "all_budget_decisions_unchanged": all(
            point["budget_decisions_unchanged_at_deepest"] for point in points
        ),
        "shear_corrected_estimate_exceeds_deepest_deflection_at_every_point": all(
            point["shear_corrected_estimate_exceeds_deepest_deflection"]
            for point in points
        ),
        "maximum_primary_to_deepest_drift": max(
            quantity["primary_to_deepest_drift"]
            for point in points
            for quantity in point["quantities"].values()  # type: ignore[union-attr]
        ),
    }


def _run_plate_sweep_meshes(work_directory: Path) -> dict[str, object]:
    """Sweep plate slenderness and Poisson ratio at a fixed free radius.

    Both compared models are linear, so every reported relative error is
    independent of the applied pressure magnitude.  The sweep therefore
    isolates Kirchhoff-versus-three-dimensional model form and says nothing
    about large-deflection behaviour.
    """

    toolchain = check_toolchain()
    work_directory.mkdir(parents=True, exist_ok=True)
    budget = PLATE_SWEEP_TOLERANCES["kirchhoff_agreement_budget"]
    cases = [
        _sweep_case(
            ratio=ratio,
            poisson_ratio=poisson_ratio,
            work_directory=work_directory,
            budget=budget,
        )
        for poisson_ratio in PLATE_SWEEP_POISSON_RATIOS
        for ratio in PLATE_SWEEP_DIAMETER_THICKNESS_RATIOS
    ]

    def case_for(ratio: float, poisson_ratio: float) -> dict[str, Any]:
        return next(
            item
            for item in cases
            if item["free_diameter_over_thickness"] == ratio
            and item["poisson_ratio"] == poisson_ratio
        )

    def within_budget(boundary: str, output: str, checks: dict[str, Any]) -> bool:
        if output == "deflection":
            return bool(checks["kirchhoff_deflection_within_budget"])
        # The bending release covers every published bending stress: the
        # center stress for both edges plus, for the fixed edge, the
        # margin-governing edge stress.
        if boundary == "fixed":
            return bool(checks["kirchhoff_center_stress_within_budget"]) and bool(
                checks["kirchhoff_edge_stress_within_budget"]
            )
        return bool(checks["kirchhoff_center_stress_within_budget"])

    # Each floor is the coarsest solved ratio from which every thinner solved
    # ratio also stays inside the budget, held at every solved Poisson value,
    # so the band floor is valid across the released Poisson band.  Floors sit
    # on solved ratios; releasing the continuous range above a floor relies on
    # the monotone decrease of the model-form error with thinness that the
    # solved points demonstrate.
    floors: dict[str, object] = {}
    for boundary in ("simply_supported", "fixed"):
        outputs: dict[str, object] = {}
        for output in ("bending", "deflection"):
            per_poisson: dict[str, float | None] = {}
            for poisson_ratio in PLATE_SWEEP_POISSON_RATIOS:
                flags = [
                    within_budget(
                        boundary,
                        output,
                        case_for(ratio, poisson_ratio)["boundaries"][boundary][
                            "checks"
                        ],
                    )
                    for ratio in PLATE_SWEEP_DIAMETER_THICKNESS_RATIOS
                ]
                floor: float | None = None
                for index in range(len(flags)):
                    if all(flags[index:]):
                        floor = PLATE_SWEEP_DIAMETER_THICKNESS_RATIOS[index]
                        break
                per_poisson[f"{poisson_ratio:g}"] = floor
            band_values = list(per_poisson.values())
            outputs[output] = {
                "per_poisson": per_poisson,
                "band_floor": (
                    None
                    if any(value is None for value in band_values)
                    else max(value for value in band_values if value is not None)
                ),
            }
        floors[boundary] = outputs

    # The shear-corrected estimate feeds production's small-deflection
    # applicability gate, so record how it compares against the solved
    # deflection at every case.  A negative residual means the estimate
    # exceeds the solved deflection.  This is a measured fact about the
    # solved cases, not a claimed mathematical bound.
    estimate_summary: dict[str, object] = {}
    for boundary in ("simply_supported", "fixed"):
        residuals = [
            float(
                case_for(ratio, poisson_ratio)["boundaries"][boundary][
                    "shear_corrected"
                ]["fea_minus_predicted_fraction"]
            )
            for ratio in PLATE_SWEEP_DIAMETER_THICKNESS_RATIOS
            for poisson_ratio in PLATE_SWEEP_POISSON_RATIOS
        ]
        estimate_summary[boundary] = {
            "exceeds_finest_mesh_deflection_at_every_solved_case": all(
                residual < 0.0 for residual in residuals
            ),
            "residual_closest_to_zero": max(residuals),
            "residual_farthest_from_zero": min(residuals),
        }

    sensitivity = _deep_mesh_sensitivity(
        case_for=case_for, work_directory=work_directory, budget=budget
    )

    return {
        "schema_version": "3.0.0",
        "classification": {
            "evidence_role": "idealized_linear_elastic_fea_equation_comparison",
            "not": [
                "calibration",
                "allowable_pressure",
                "certification",
                "physical_validation",
                "design_approval",
            ],
        },
        "purpose": (
            "Extend the P5-03 plate comparison across free-diameter/thickness "
            "ratio and Poisson ratio so the released validity envelope is "
            "read from solved, mesh-converged evidence instead of an "
            "unsourced constant, with the fixed-edge margin-governing stress "
            "compared through its convergent reaction-moment resultant."
        ),
        "rerun_command": (
            "uv run python validation/fea/run_fea.py p5-03-plate-sweep "
            "--work-directory /tmp/pv-gen-plate-sweep "
            "--output /tmp/p5_03_plate_sweep_summary.json"
        ),
        "toolchain": toolchain,
        "tolerances": PLATE_SWEEP_TOLERANCES,
        "source_inputs": {
            "held_constant": {
                "free_radius_mm": PLATE_FREE_RADIUS_MM,
                "uniform_pressure_mpa": PLATE_PRESSURE_MPA,
                "elastic_modulus_mpa": PLATE_ELASTIC_MODULUS_MPA,
            },
            "swept": {
                "free_diameter_over_thickness": list(
                    PLATE_SWEEP_DIAMETER_THICKNESS_RATIOS
                ),
                "poisson_ratio": list(PLATE_SWEEP_POISSON_RATIOS),
            },
            "poisson_evidence_band": list(PLATE_SWEEP_POISSON_EVIDENCE_BAND),
            "linearity_note": (
                "Both compared models are linear, so every reported relative "
                "error is independent of the applied pressure magnitude."
            ),
            "mesh_ladder": [
                {"radial_elements": radial, "thickness_elements": through}
                for radial, through in PLATE_MESH_LADDER
            ],
        },
        "cases": cases,
        "derived_validity_floors": floors,
        "shear_corrected_estimate": estimate_summary,
        "deep_mesh_sensitivity": sensitivity,
        "disposition": (
            "Retain every comparison. A failed check is a model-form "
            "disagreement, not a reason to alter inputs or tolerances."
        ),
        "manifest": {
            "runner_sha256": _sha256(Path(__file__)),
            "dockerfile_sha256": _sha256(REPOSITORY_ROOT / DOCKERFILE),
            "reference_sha256": _sha256(
                REPOSITORY_ROOT / "validation" / "non_ring_reference.py"
            ),
        },
    }


RING_MESH_SEQUENCE = (
    ("M1", 48, 1),
    ("M2", 64, 2),
    ("M3", 80, 3),
)


def _run_ring_mesh(
    *,
    frame_spaces: int,
    mesh_id: str,
    circumferential_elements: int,
    axial_elements_per_bay: int,
    work_directory: Path,
    requested_modes: int = 12,
) -> dict[str, object]:
    deck, metadata, coordinates = ring_shell_deck(
        frame_spaces=frame_spaces,
        circumferential_elements=circumferential_elements,
        axial_elements_per_bay=axial_elements_per_bay,
        requested_modes=requested_modes,
    )
    job_name = f"ring_{frame_spaces}_{mesh_id.lower()}"
    job_directory = work_directory / job_name
    _, stdout = _run_ccx(deck, job_name=job_name, keep_directory=job_directory)
    dat_path = job_directory / f"{job_name}.dat"
    factors = _dat_buckling_factors(dat_path)
    static_displacements, eigenvectors = _dat_displacement_blocks(
        dat_path, "NSHELL"
    )
    energies = _dat_modal_internal_energies(dat_path)
    if len(factors) != int(metadata["requested_modes"]):
        raise RuntimeError(
            f"{job_name} returned {len(factors)} of "
            f"{metadata['requested_modes']} requested modes"
        )

    modes: list[dict[str, object]] = []
    for mode_number, factor in enumerate(factors, start=1):
        if mode_number not in eigenvectors or mode_number not in energies:
            raise RuntimeError(f"{job_name} is missing mode {mode_number} output")
        mode_count = _ring_mode_count(
            eigenvectors[mode_number],
            coordinates,
            unsupported_length=float(metadata["unsupported_length_in"]),
        )
        shell_energy = energies[mode_number]["ESHELL_ALL"]
        ring_energy = energies[mode_number]["ERING_ALL"]
        total_energy = shell_energy + ring_energy
        modes.append(
            {
                "mode_number": mode_number,
                "eigenvalue_pressure_psi": factor,
                **mode_count,
                "strain_energy": {
                    "shell_lbf_in": shell_energy,
                    "rings_lbf_in": ring_energy,
                    "shell_fraction": shell_energy / total_energy,
                    "ring_fraction": ring_energy / total_energy,
                },
            }
        )
    global_modes = [
        mode
        for mode in modes
        if mode["classification"] == "global_sinusoidal"
        and int(mode["circumferential_lobes_n"]) >= 2
    ]
    if not global_modes:
        raise RuntimeError(f"{job_name} produced no independently classified global mode")
    governing = global_modes[0]

    target_coordinate = (
        float(metadata["shell_mid_surface_radius_in"]),
        0.0,
        float(metadata["unsupported_length_in"]) / 2.0,
    )
    probe_node = min(
        coordinates,
        key=lambda node: sum(
            (actual - target) ** 2
            for actual, target in zip(
                coordinates[node], target_coordinate, strict=True
            )
        ),
    )
    probe_x, probe_y, _ = coordinates[probe_node]
    probe_displacement = static_displacements[probe_node]
    unit_static_radial_displacement = (
        probe_x * probe_displacement[0] + probe_y * probe_displacement[1]
    ) / math.hypot(probe_x, probe_y)
    residual = _dat_total_vector(dat_path, "NALL")
    applied_absolute_force = (
        2.0
        * math.pi
        * float(metadata["shell_mid_surface_radius_in"])
        * float(metadata["unsupported_length_in"])
        + 2.0 * float(metadata["closed_end_force_each_lbf"])
    )
    residual_norm = math.sqrt(sum(value**2 for value in residual))
    # The end node sets carry the applied closed-end loads and only radial
    # constraints, so their axial resultants must equal the analytic closed-end
    # force with opposite signs.  This is the discriminating load-application
    # check; the NALL residual is only a solver equilibrium identity.
    closed_end_force = float(metadata["closed_end_force_each_lbf"])
    left_axial = _dat_total_vector(dat_path, "NLEFT")[2]
    right_axial = _dat_total_vector(dat_path, "NRIGHT")[2]
    end_axial_force_error_fraction = (
        max(
            abs(left_axial - closed_end_force),
            abs(right_axial + closed_end_force),
        )
        / closed_end_force
    )
    input_path = job_directory / f"{job_name}.inp"
    stdout_path = job_directory / f"{job_name}.stdout.txt"
    return {
        "mesh_id": mesh_id,
        "circumferential_elements": metadata["circumferential_elements"],
        "axial_elements_per_bay": metadata["axial_elements_per_bay"],
        "axial_elements": metadata["axial_elements"],
        "original_nodes": metadata["original_nodes"],
        "shell_element_type": metadata["shell_element_type"],
        "shell_elements": metadata["shell_elements"],
        "ring_element_type": metadata["ring_element_type"],
        "ring_elements": metadata["ring_elements"],
        "ring_count": metadata["ring_count"],
        "ring_centroid_offset_in": metadata["ring_centroid_offset_in"],
        "ring_reference_offset2": metadata["ring_reference_offset2"],
        "force_residual_fraction_of_absolute_applied_load": (
            residual_norm / applied_absolute_force
        ),
        "applied_closed_end_force_lbf": closed_end_force,
        "left_end_axial_force_lbf": left_axial,
        "right_end_axial_force_lbf": right_axial,
        "end_axial_force_error_fraction": end_axial_force_error_fraction,
        "unit_static_midspan_shell_radial_displacement_in": (
            unit_static_radial_displacement
        ),
        "unit_static_pressure_orientation": (
            "inward" if unit_static_radial_displacement < 0.0 else "outward"
        ),
        "governing_global_mode": governing,
        "runtime_seconds": _runtime_seconds(stdout),
        "solver_warning_count": stdout.count("*WARNING"),
        "input_sha256": _sha256(input_path),
        "dat_sha256": _sha256(dat_path),
        "stdout_sha256": _sha256(stdout_path),
    }


def _ring_reference_record(frame_spaces: int) -> dict[str, object]:
    # The FEA is compared against the independent reference only.
    # Production-versus-reference parity for the same DTMB geometries lives
    # in ordinary live tests, so production code is not an input here.
    independent = solve_ring_reference(dtmb_case(frame_spaces))
    published_row = next(
        row for row in DTMB_TABLE_2_PUBLISHED if row[0] == frame_spaces
    )
    return {
        "independent_equation": {
            "without_ring_torsion_ideal_pressure_psi": (
                independent.without_ring_torsion.ideal_critical_pressure
            ),
            "with_ring_torsion_ideal_pressure_psi": (
                independent.with_ring_torsion.ideal_critical_pressure
            ),
            "nasa_0p75_adjusted_pressure_psi": (
                independent.with_ring_torsion.adjusted_critical_pressure
            ),
            "axial_half_waves_m": (
                independent.with_ring_torsion.axial_half_waves_m
            ),
            "circumferential_lobes_n": (
                independent.with_ring_torsion.circumferential_lobes_n
            ),
            "rectangle_area_in2": independent.rectangle.area,
            "rectangle_centroidal_inertia_in4": (
                independent.rectangle.centroidal_inertia
            ),
            "rectangle_saint_venant_j_in4": (
                independent.rectangle.saint_venant_torsional_constant
            ),
        },
        "published_benchmark_context": {
            "kendrick_part_iii_pressure_psi": published_row[2],
            "kendrick_part_iii_lobes_n": published_row[3],
            "experiment_pressure_psi": published_row[4],
            "experiment_lobes_n": published_row[5],
            "comparison_only_not_calibration": True,
        },
    }


def _run_ring_case(frame_spaces: int, work_directory: Path) -> dict[str, object]:
    meshes = [
        _run_ring_mesh(
            frame_spaces=frame_spaces,
            mesh_id=mesh_id,
            circumferential_elements=circumferential_elements,
            axial_elements_per_bay=axial_elements_per_bay,
            work_directory=work_directory,
        )
        for mesh_id, circumferential_elements, axial_elements_per_bay in (
            RING_MESH_SEQUENCE
        )
    ]
    reference = _ring_reference_record(frame_spaces)
    independent = reference["independent_equation"]
    governing = [mesh["governing_global_mode"] for mesh in meshes]
    pressure_change = _relative_error(
        float(governing[-1]["eigenvalue_pressure_psi"]),
        float(governing[-2]["eigenvalue_pressure_psi"]),
    )
    energy_partition_change = abs(
        float(governing[-1]["strain_energy"]["ring_fraction"])
        - float(governing[-2]["strain_energy"]["ring_fraction"])
    )
    finest_mode = (
        int(governing[-1]["axial_half_waves_m"]),
        int(governing[-1]["circumferential_lobes_n"]),
        governing[-1]["classification"],
    )
    penultimate_mode = (
        int(governing[-2]["axial_half_waves_m"]),
        int(governing[-2]["circumferential_lobes_n"]),
        governing[-2]["classification"],
    )
    convergence = {
        "finest_eigenvalue_change_fraction": pressure_change,
        "eigenvalue_change_limit_fraction": 0.02,
        "finest_mode": list(finest_mode),
        "penultimate_mode": list(penultimate_mode),
        "mode_unchanged": finest_mode == penultimate_mode,
        "ring_energy_fraction_change": energy_partition_change,
        "energy_partition_change_limit": 0.02,
        "all_end_axial_forces_match_closed_end_load": all(
            float(mesh["end_axial_force_error_fraction"]) <= 0.005
            for mesh in meshes
        ),
        "all_static_pressure_orientation_checks_inward": all(
            mesh["unit_static_pressure_orientation"] == "inward"
            for mesh in meshes
        ),
    }
    convergence["declared_checks_pass"] = (
        pressure_change <= 0.02
        and finest_mode == penultimate_mode
        and energy_partition_change <= 0.02
        and convergence["all_end_axial_forces_match_closed_end_load"]
        and convergence["all_static_pressure_orientation_checks_inward"]
    )
    finest_pressure = float(governing[-1]["eigenvalue_pressure_psi"])
    independent_pressure = float(
        independent["with_ring_torsion_ideal_pressure_psi"]
    )
    return {
        "case_id": f"RS-EIG-{frame_spaces}",
        "classification": "ideal_perfect_geometry_linear_eigenvalue_evidence",
        "meshes": meshes,
        "convergence": convergence,
        "reference_and_context": reference,
        "comparison": {
            "finest_fea_ideal_pressure_psi": finest_pressure,
            "independent_equation_ideal_pressure_psi": independent_pressure,
            "fea_minus_independent_percent": (
                100.0 * (finest_pressure - independent_pressure) / independent_pressure
            ),
            "nasa_0p75_value_kept_separate_psi": independent[
                "nasa_0p75_adjusted_pressure_psi"
            ],
            "fea_mode": {
                "axial_half_waves_m": finest_mode[0],
                "circumferential_lobes_n": finest_mode[1],
            },
            "independent_equation_mode": {
                "axial_half_waves_m": independent["axial_half_waves_m"],
                "circumferential_lobes_n": independent[
                    "circumferential_lobes_n"
                ],
            },
        },
    }


def _run_p5_04_meshes(
    work_directory: Path,
    *,
    include_series: bool,
) -> dict[str, object]:
    toolchain = check_toolchain()
    work_directory.mkdir(parents=True, exist_ok=True)
    primary_cases = {
        str(frame_spaces): _run_ring_case(
            frame_spaces, work_directory / f"case_{frame_spaces}"
        )
        for frame_spaces in (17, 33)
    }
    series: list[dict[str, object]] = []
    if include_series:
        for frame_spaces, *_ in DTMB_TABLE_2_PUBLISHED:
            if frame_spaces in (17, 33):
                case = primary_cases[str(frame_spaces)]
                mesh = case["meshes"][-1]
            else:
                mesh = _run_ring_mesh(
                    frame_spaces=frame_spaces,
                    mesh_id="M3",
                    circumferential_elements=RING_MESH_SEQUENCE[-1][1],
                    axial_elements_per_bay=RING_MESH_SEQUENCE[-1][2],
                    work_directory=work_directory / "series",
                    requested_modes=4,
                )
            reference = _ring_reference_record(frame_spaces)
            governing = mesh["governing_global_mode"]
            equation_pressure = float(
                reference["independent_equation"][
                    "with_ring_torsion_ideal_pressure_psi"
                ]
            )
            fea_pressure = float(governing["eigenvalue_pressure_psi"])
            series.append(
                {
                    "frame_spaces": frame_spaces,
                    "mesh_id": mesh["mesh_id"],
                    "input_sha256": mesh["input_sha256"],
                    "dat_sha256": mesh["dat_sha256"],
                    "runtime_seconds": mesh["runtime_seconds"],
                    "solver_warning_count": mesh["solver_warning_count"],
                    "end_axial_force_error_fraction": mesh[
                        "end_axial_force_error_fraction"
                    ],
                    "fea_ideal_pressure_psi": fea_pressure,
                    "fea_axial_half_waves_m": governing["axial_half_waves_m"],
                    "fea_circumferential_lobes_n": governing[
                        "circumferential_lobes_n"
                    ],
                    "independent_ideal_pressure_psi": equation_pressure,
                    "independent_axial_half_waves_m": reference[
                        "independent_equation"
                    ]["axial_half_waves_m"],
                    "independent_circumferential_lobes_n": reference[
                        "independent_equation"
                    ]["circumferential_lobes_n"],
                    # When the governing FEA mode family differs from the
                    # equation's, this percent compares pressures of two
                    # different mode shapes.
                    "mode_families_match": (
                        int(governing["axial_half_waves_m"])
                        == int(
                            reference["independent_equation"]["axial_half_waves_m"]
                        )
                        and int(governing["circumferential_lobes_n"])
                        == int(
                            reference["independent_equation"][
                                "circumferential_lobes_n"
                            ]
                        )
                    ),
                    "fea_minus_independent_percent": (
                        100.0
                        * (fea_pressure - equation_pressure)
                        / equation_pressure
                    ),
                }
            )
    return {
        "schema_version": "1.2.0",
        "classification": {
            "evidence_role": "idealized_linear_eigenvalue_fea_equation_comparison",
            "not": [
                "calibration",
                "allowable_pressure",
                "certification",
                "physical_validation",
                "design_approval",
            ],
        },
        "rerun_command": (
            "uv run python validation/fea/run_fea.py p5-04 "
            + ("--include-series " if include_series else "")
            + "--work-directory /tmp/pv-gen-p5-04 "
            "--output /tmp/p5_04_summary.json"
        ),
        "toolchain": toolchain,
        "cases": primary_cases,
        "series": series,
        "status": {
            "RS-EIG-17": "executed_three_mesh_evidence",
            "RS-EIG-33": "executed_three_mesh_evidence",
            "RS-EIG-SERIES": (
                "executed_at_finest_primary_mesh" if include_series else "not_run"
            ),
            "RS-EIG-17-J0": (
                "blocked: CalculiX 2.20 native rectangle beams do not expose an "
                "independent J=0 override while preserving A and I; GENERAL is "
                "limited to user element U1, which is outside this validation scope"
            ),
            "refined_ring_representation": (
                "not_run: the required separate shell/continuum ring model with at "
                "least four elements across ring width remains open"
            ),
            "RS-GNL-17": (
                "blocked: selected CalculiX 2.20 toolchain has no documented "
                "arc-length/Riks continuation through a limit point"
            ),
            "RS-GNL-33": (
                "blocked: selected CalculiX 2.20 toolchain has no documented "
                "arc-length/Riks continuation through a limit point"
            ),
            "p5_04_complete": False,
        },
        "known_numerical_limit": (
            "CalculiX does not report a separate artificial/hourglass-energy "
            "channel for these S8R/B32R modes; modal shell/ring strain-energy "
            "partition is recorded, but the specification's quantitative "
            "artificial-energy check remains open."
        ),
        # The code inputs to this evidence: the runner, the pinned container
        # recipe, and the independent ring reference that supplies every
        # equation target and published DTMB value.  No production code is
        # executed here.
        "manifest": {
            "runner_sha256": _sha256(Path(__file__)),
            "dockerfile_sha256": _sha256(REPOSITORY_ROOT / DOCKERFILE),
            "ring_reference_sha256": _sha256(
                REPOSITORY_ROOT / "validation" / "ring_shell_reference.py"
            ),
        },
    }


def run_p5_03(work_directory: Path, output: Path) -> None:
    summary = _run_p5_03_meshes(work_directory)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_plate_sweep(work_directory: Path, output: Path) -> None:
    summary = _run_plate_sweep_meshes(work_directory)
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def run_p5_04(work_directory: Path, output: Path, *, include_series: bool) -> None:
    summary = _run_p5_04_meshes(
        work_directory,
        include_series=include_series,
    )
    output.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("check", help="verify Docker and pinned solver versions")
    p5_03 = subparsers.add_parser("p5-03", help="run all P5-03 meshes and write a summary")
    p5_03.add_argument("--work-directory", type=Path, required=True)
    p5_03.add_argument("--output", type=Path, required=True)
    plate_sweep = subparsers.add_parser(
        "p5-03-plate-sweep",
        help="sweep plate free-diameter/thickness ratio for the validity envelope",
    )
    plate_sweep.add_argument("--work-directory", type=Path, required=True)
    plate_sweep.add_argument("--output", type=Path, required=True)
    p5_04 = subparsers.add_parser(
        "p5-04", help="run ideal DTMB ring-shell eigenvalue meshes"
    )
    p5_04.add_argument("--work-directory", type=Path, required=True)
    p5_04.add_argument("--output", type=Path, required=True)
    p5_04.add_argument("--include-series", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.command == "check":
            print(json.dumps(check_toolchain(), indent=2, sort_keys=True))
        elif arguments.command == "p5-03":
            run_p5_03(arguments.work_directory, arguments.output)
        elif arguments.command == "p5-03-plate-sweep":
            run_plate_sweep(arguments.work_directory, arguments.output)
        else:
            run_p5_04(
                arguments.work_directory,
                arguments.output,
                include_series=arguments.include_series,
            )
    except ToolchainUnavailable as exc:
        print(f"FEA toolchain unavailable: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
