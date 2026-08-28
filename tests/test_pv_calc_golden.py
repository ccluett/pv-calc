"""Snapshot of every pv-calc example response, matched exactly at 12 digits.

Regenerate the committed baseline from pv-calc/ with
``uv run python tests/test_pv_calc_golden.py`` when a change is meant
to alter the pv-calc output contract; the baseline's own diff is then the
reviewable artifact.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from typer.testing import CliRunner

from pv_calc.cli import app


PV_CALC_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = PV_CALC_ROOT / "examples"
BASELINE = Path(__file__).resolve().parent / "fixtures" / "pv_calc_golden.json"
# There is no default material database, so an example that names materials
# needs one passed, and the committed examples name only the shipped
# pv-calc database at the package root. The option is inert for every example
# that carries explicit property records, which is why it can be passed
# unconditionally.
MATERIALS_FILE = PV_CALC_ROOT / "materials.yaml"
MATERIALS_FILE_LABEL = "materials.yaml"


def _rounded(value: Any) -> Any:
    """Round every float to 12 significant digits.

    A bit-exact snapshot is not portable: ``pow`` and friends differ in the
    last unit in the last place between platform math libraries, so the
    ring-shell mode search lands one ulp apart on arm64 macOS and x86-64
    Linux. Twelve digits is far below the 1e-9 relative tolerance the
    validation suite already treats as agreement, so any real change to a
    released number still fails the snapshot.
    """
    if isinstance(value, float):
        return float(f"{value:.12g}")
    if isinstance(value, dict):
        return {key: _rounded(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_rounded(item) for item in value]
    return value


def _portable(value: Any) -> Any:
    """Replace the absolute materials-file path with its committed relative form.

    A named material's response echoes the database path it was given, and this
    suite also runs from an export at an arbitrary location, so the absolute
    path would make the baseline depend on the checkout directory.
    """
    if isinstance(value, str) and value == str(MATERIALS_FILE):
        return MATERIALS_FILE_LABEL
    if isinstance(value, dict):
        return {key: _portable(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_portable(item) for item in value]
    return value


def _run(example: Path) -> dict[str, Any]:
    request = json.loads(example.read_text(encoding="utf-8"))
    argv = [request["model"]]
    if "operation" in request:
        argv.append(request["operation"])
    argv += ["--input", str(example), "--materials-file", str(MATERIALS_FILE), "--json"]
    result = CliRunner().invoke(app, argv)
    assert result.exit_code == 0, f"{example.name}: {result.stdout}{result.stderr}"
    return _rounded(_portable(json.loads(result.stdout)))


def _capture() -> dict[str, Any]:
    return {example.name: _run(example) for example in sorted(EXAMPLES.glob("*.json"))}


def test_pv_calc_example_responses_match_baseline() -> None:
    assert _capture() == json.loads(BASELINE.read_text(encoding="utf-8"))


if __name__ == "__main__":
    BASELINE.write_text(
        json.dumps(_capture(), indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(f"wrote {BASELINE.relative_to(PV_CALC_ROOT)}")
