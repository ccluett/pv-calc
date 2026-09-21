"""Reproduce a pinned external DAPS4 release and compare DTMB support models.

Download and unpack DAPS4e.6.zip from https://sourceforge.net/projects/daps4/files/.
This runner needs gfortran; neither it nor DAPS4 is a pv-calc dependency.

    uv run python validation/daps4_ring_crosscheck.py \
        --release /path/to/DAPS4e.6 --work-directory /tmp/daps-crosscheck \
        --output validation/results/daps4_ring_crosscheck.json

Only elastic GENERAL INSTABILITY pressure and mode are compared. No other
DAPS4 failure mode, design factor, or allowable pressure is qualified here.
The specified-restraint probes retain failures separately from the required
simply-supported/clamped reproduction checks.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from typing import Any


SOURCE_DIRECTORY = Path("Source Code/Fortran/GFortran")
FIXTURE_DIRECTORY = Path("Validation Problems/DTMB Models/1324/Rev E.2")
SOURCE_HASHES = {
    "BLAS.for": "5c1ccd9e3f06226d6d93b36024aa670eae1561b9fa3d988d7793bfb203f2671c",
    "DAPS4e.for": "ab25f070f5bcdad21071c0760be12b6161df8cd86297283cebbbc9f3529a8723",
    "LAPACK.for": "0ebc1949c0e442873786c77a5ceb4b4ff9821edc69955f950c722a72de876d74",
    "Source2.for": "1b8cb561b557338273b8c7b988b23e8705156062509550be7e7553033bc9c7fa",
    "Source3.for": "adf12d5edd652cd377f4c299f446a818e40ce56226167946fc35141a485ecc61",
    "Source4.for": "0db457e7fbcb7625d2dfccd96f56ec167674cc931bcb05ca370a274f194c69c8",
    "Source5.for": "18bc3e86d95837c0a3a08f3e4b0d2a560c1567229619b09305e69459f8e6acc5",
    "Source6.for": "f5d7d1fda429e9404d88fb985116f973101eab48da4c6a606334211d08fbeebf",
}
FIXTURE_HASHES = {
    "daps4inp.SS.dp4": "6784de37db3ca4c692d161972664e94bb383e96122e44eadc779f9ebb6fb5f25",
    "daps4out.SS.txt": "9255dd8338660ff041b9845bd0b6bece1f19c55fe9cab9edd71719beb806805c",
    "daps4inp.CL.dp4": "ac786659db453ccbb8022323dba64e0a00f45e6105e5e3ec268ffe40858c8b0f",
    "daps4out.CL.txt": "979ffc662315e2229499d8859c661ecc1feb83a3730cb2c5da7030c90272e830",
    "daps4inp.Jer = 0.dp4": "cc20005e1930e805bad3612c2d07de04f9fdc83a9cc032d023af36cb5ac0eadc",
    "daps4out.Jer = 0.txt": "5aaea1952135abe43997ab1b8642b015e4cfbc69057b7a7c190c310b18c42142",
    "daps4inp.Jer = IXer.dp4": "02cc4d005431af16b45900ff455997e46498859448733eb3eabb6b81f9c5ad81",
    "daps4out.Jer = IXer.txt": "694c1d9c937df5f66a4b461ec35bcfc13c3e56ab589a20c30431be0efd40993a",
}
GENERAL_INSTABILITY = re.compile(
    r"GENERAL INSTABILITY[^\n]*:\s*"
    r"ELASTIC BUCKLING PRESSURE\s*=\s*([\d.E+-]+) PSI\s+MODE\s*=\s*(\d+)"
)


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def verified_files(release: Path) -> list[dict[str, str]]:
    records = []
    for directory, hashes in (
        (SOURCE_DIRECTORY, SOURCE_HASHES), (FIXTURE_DIRECTORY, FIXTURE_HASHES)
    ):
        for name, expected in hashes.items():
            member = directory / name
            actual = sha256((release / member).read_bytes())
            if actual != expected:
                raise ValueError(f"Unrecognized DAPS4 source/fixture: {member}")
            records.append({"member": member.as_posix(), "sha256": actual})
    return records


def global_results(output: str) -> list[dict[str, float | int]]:
    return [
        {"ideal_pressure_psi": float(pressure), "circumferential_lobes_n": int(mode)}
        for pressure, mode in GENERAL_INSTABILITY.findall(output)
    ]


def run_case(executable: Path, directory: Path, input_bytes: bytes) -> dict[str, Any]:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "daps4inp.dp4").write_bytes(input_bytes)
    # Prevent a failed run from accidentally parsing a previous result.
    output_path = directory / "daps4out.txt"
    output_path.unlink(missing_ok=True)
    run = subprocess.run(
        [str(executable)], cwd=directory, capture_output=True, timeout=30,
        check=True,
    )
    (directory / "stdout.txt").write_bytes(run.stdout)
    (directory / "stderr.txt").write_bytes(run.stderr)
    output_bytes = output_path.read_bytes()
    output = output_bytes.decode("ascii")
    results = global_results(output)
    if not results:
        raise ValueError(f"No global elastic results: {directory}")
    revision = re.search(r"Revision[^\n]+", output)
    return {
        "results": results,
        "input_sha256": sha256(input_bytes),
        # DAPS outputs include a timestamp; this identifies this run only.
        "raw_output_sha256": sha256(output_bytes),
        "reported_revision": revision[0].strip() if revision else None,
        "stderr": run.stderr.decode("ascii").strip(),
        "solver_notices": sorted({
            line.strip() for line in output.splitlines()
            if any(word in line for word in ("WARNING", "CAUTION", "ERROR"))
        }),
    }


def table_2_input(spaces: int, boundary_option: int, preload_psi: float) -> bytes:
    # DAPS4 field definitions: NCURVE=4 elastic; NDESIGN=0 simply supported,
    # -2 clamped; INTERN=1 external rings. The geometry line is L, OD, ID, T,
    # RHO, RHOF, ARM, ENDB. Zero OD means derive it from the supplied ID.
    lines = [
        f"1 4 {boundary_option} 0 0 1 0 2 18",
        f"DTMB 1324 Table 2: {spaces} spaces, boundary option {boundary_option}",
        "3.E+7 0.E+0 0.E+0 0.E+0 0.E+0 3.E-1 0.E+0 0.E+0",
        f"{preload_psi:.1f} 0.0 0.0 0.0 0",
        "8.5000E+4 0.E+0 0.E+0 0.E+0 0.E+0 0.E+0",
        f"{spaces*1.152:.9f} 0.0 8.118 0.035 0.283 0.0 0.0 0.0",
        "-1.0 1.152 0.0 0.0 0.0 0.0 0.0 0.0 0.0 0.0",
        "0.E+0 0.E+0 8.6E-2 1.69E-1 0.E+0 0.E+0",
        "1.E+0 1.E+0 1.E+0 1.E+0 1.E+0 1.E+0 1.E+0 1.E+0 1.E+0",
        "*end",
    ]
    return ("\n".join(lines) + "\n").encode("ascii")


def build_results(release: Path, work: Path, compiler: str) -> dict[str, Any]:
    provenance = verified_files(release)
    compiler_path = shutil.which(compiler)
    if compiler_path is None:
        raise RuntimeError(f"Fortran compiler not found: {compiler}")
    version = subprocess.run(
        [compiler_path, "--version"], capture_output=True, text=True, check=True
    ).stdout.splitlines()[0]
    work.mkdir(parents=True, exist_ok=True)
    executable = work / "daps4e6"
    flags = ["-O2", "-std=legacy", "-fallow-argument-mismatch", "-ffixed-line-length-none"]
    build = subprocess.run(
        [compiler_path, *flags,
         *[str(release / SOURCE_DIRECTORY / name) for name in SOURCE_HASHES],
         "-o", str(executable)],
        cwd=work, capture_output=True, timeout=120,
    )
    (work / "build.log").write_bytes(build.stdout + build.stderr)
    build.check_returncode()

    controls = []
    for label in ("SS", "CL"):
        fixtures = release / FIXTURE_DIRECTORY
        expected = global_results((fixtures / f"daps4out.{label}.txt").read_text())
        actual = run_case(
            executable, work / f"archived-{label}",
            (fixtures / f"daps4inp.{label}.dp4").read_bytes(),
        )
        if len(expected) != 8 or actual["results"] != expected:
            raise AssertionError(f"Archived {label} global-result reproduction failed")
        controls.append({
            "fixture": label, "reported_precision_match": True,
            "expected_results": expected, **actual,
        })

    # Unlike the required SS/CL controls, these probes may fail. Preserve the
    # failure as evidence; do not treat a finite sentinel or a forced support
    # substitution as a successfully qualified elastic-restraint calculation.
    restraint_audit = []
    for label in ("Jer = 0", "Jer = IXer"):
        fixtures = release / FIXTURE_DIRECTORY
        expected = global_results((fixtures / f"daps4out.{label}.txt").read_text())
        actual = run_case(
            executable, work / f"archived-{label}",
            (fixtures / f"daps4inp.{label}.dp4").read_bytes(),
        )
        if len(expected) != 8 or len(actual["results"]) != 8:
            raise AssertionError(f"Unexpected number of archived restraint results: {label}")
        matches = [a == e for a, e in zip(actual["results"], expected)]
        restraint_audit.append({
            "fixture": label,
            "reported_precision_match": all(matches),
            "matching_rows": sum(matches),
            "sentinel_rows": sum(
                row["ideal_pressure_psi"] >= 1.0e10 for row in actual["results"]
            ),
            "disposition": "not qualified; diagnostic probe only",
            "expected_results": expected, **actual,
        })

    records = []
    for spaces in (17, 21, 23, 25, 26, 27, 28, 29, 31, 33):
        record: dict[str, Any] = {"frame_spaces": spaces}
        for label, option in (("simply_supported", 0), ("clamped", -2)):
            primary = run_case(
                executable, work / f"{label}-{spaces}-p500",
                table_2_input(spaces, option, 500),
            )
            scaling = run_case(
                executable, work / f"{label}-{spaces}-p1",
                table_2_input(spaces, option, 1),
            )
            if len(primary["results"]) != 1 or primary["results"] != scaling["results"]:
                raise AssertionError(f"Global-pressure reference-load dependence: {label} {spaces}")
            record[label] = {
                **primary["results"][0],
                "preload_invariance_1_vs_500_psi": True,
                "primary_run": primary, "scaling_check_run": scaling,
            }
        records.append(record)

    return {
        "schema_version": "1.1.0",
        "scope": "independent global elastic theory comparison, not NASA-equation parity or housing capacity validation",
        "release_url": "https://sourceforge.net/projects/daps4/files/DAPS4e.6.zip/download",
        "release_member_hashes": provenance,
        "compiler": version,
        "compiler_flags": flags,
        "archived_controls": controls,
        "specified_restraint_audit": restraint_audit,
        "table_2": records,
        "cautions": [
            "Archived controls contain repeated geometries under idealized support options; 16 outputs are not 16 independent experiments.",
            "The Table 1 fixture lengths are consistent with rounded published L/D times the shell OD; DAPS4 further rounds the global-analysis length to an integer pitch multiple.",
            "Specified-restraint probes do not reproduce all archived outputs; they are excluded from validation and fixture-stiffness calibration.",
            "Only global elastic pressure and lobe count were audited; other DAPS4 outputs are outside this comparison.",
            "The DAPS4 ring-frame-instability output changes with the reference pressure in these runs; it is not used or qualified.",
            "DAPS4 prints finite precision and run timestamps; raw-output hashes identify this execution, not a portable numerical golden.",
            "Some runs report floating-point underflow/denormal flags; stderr is retained. Normal termination and archived global reproduction were checked.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--release", required=True, type=Path)
    parser.add_argument("--work-directory", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compiler", default="gfortran")
    args = parser.parse_args()
    results = build_results(args.release.resolve(), args.work_directory.resolve(), args.compiler)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(results, indent=2, sort_keys=True) + "\n")
    print(f"Reproduced 16 archived outputs; compared 20 support cases and 20 load-scaling checks: {args.output}")
    print("Specified-restraint audit (not qualified): " + ", ".join(
        f"{row['fixture']}: {row['matching_rows']}/8 match"
        for row in results["specified_restraint_audit"]
    ))


if __name__ == "__main__":
    main()
