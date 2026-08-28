"""Shared fixtures for the pv-calc CLI tests, which are split by module."""

from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path
from typing import Any

from typer.testing import CliRunner


PV_CALC_ROOT = Path(__file__).resolve().parents[1]
EXAMPLES = PV_CALC_ROOT / "examples"
MATERIALS_FILE = PV_CALC_ROOT / "materials.yaml"
# TERM=dumb makes Rich render help as plain text. Rich otherwise detects CI as
# a styled terminal and splits option names with escape sequences, which breaks
# the substring assertions on --help output in test_cli_errors.py.
runner = CliRunner(env={"TERM": "dumb"})


def _json_result(result) -> dict[str, Any]:
    return json.loads(json.dumps(asdict(result)))


def _without_quantity_wrappers(value: Any) -> Any:
    if isinstance(value, dict):
        if set(value) == {"unit", "value"}:
            return _without_quantity_wrappers(value["value"])
        return {key: _without_quantity_wrappers(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_without_quantity_wrappers(item) for item in value]
    return value


def _error_payload(result) -> dict[str, Any]:
    assert result.exit_code != 0
    return json.loads(result.stderr)


SWEEP_FORWARD_EXAMPLES = {
    "tube": "tube_9_0401_ksi.json",
    "plate": "plate_9_0384_ksi.json",
    "hemisphere": "hemisphere_subsea_screen.json",
    "smooth-buckling": "smooth_buckling_moderate_nasa.json",
    "ring-shell": "ring_shell_dtmb_17_spaces.json",
}


