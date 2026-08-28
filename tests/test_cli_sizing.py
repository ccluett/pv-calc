"""The inverse sizing operations: tube size, smooth-buckling size, plate size."""

from __future__ import annotations

import json
import math
from dataclasses import replace
from typing import Any

import pytest

from pv_calc import sizing
from pv_calc.cli import app
from pv_calc.contracts import CALC_SCHEMA_VERSION
from pv_calc.errors import CalcCliError
from pv_calc.pressure_vessel import (
    closed_end_tube_stress,
    flat_circular_plate,
    smooth_cylinder_external_pressure_buckling,
)

from _cli_helpers import (
    EXAMPLES,
    MATERIALS_FILE,
    _error_payload,
    runner,
)


def test_tube_size_verifies_branch_boundary_and_returns_complete_forward_contract() -> None:
    material_args = [
        "--yield-strength",
        "62 ksi",
        "--failure-category",
        "ductile_metal",
        "--material-provenance",
        "test sizing property record",
    ]
    sizing_args = [
        "tube",
        "size",
        "--external-pressure",
        "7 ksi",
        "--internal-radius",
        "3 in",
        "--wall-thickness-lower",
        "0.1 in",
        "--wall-thickness-upper",
        "0.5 in",
    ]
    result = runner.invoke(app, [*sizing_args, *material_args, "--json"])

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    sizing = payload["sizing"]
    selected_mm = sizing["selected_wall_thickness"]["value"]
    assert payload["operation"] == "size"
    assert sizing["declared_check_set"] == ["cylindrical_shell_stress"]
    assert sizing["target_minimum_margin"] == 0.0
    assert sizing["selected_minimum_margin"] >= 0.0
    assert sizing["selected_check_margins"] == {
        "cylindrical_shell_stress": sizing["selected_minimum_margin"]
    }
    assert sizing["operation_version"] == "2.1.0"
    assert sizing["algorithm"] == "known_branch_partition_and_bisection"
    assert selected_mm == pytest.approx(7.83358455, abs=2e-8)
    assert payload["result"]["branch"] == "thin"
    assert payload["result"]["wall_thickness_mm"] == sizing["selected_wall_thickness"]
    assert sizing["verified_bracket"]["lower"]["minimum_margin"] < 0.0
    assert sizing["verified_bracket"]["upper"]["minimum_margin"] >= 0.0
    assert sizing["verified_bracket"]["lower"]["branch"] == "thin"
    assert sizing["verified_bracket"]["upper"]["branch"] == "thin"
    assert sizing["branch_changes"][0]["from_state"] == "thin"
    assert sizing["branch_changes"][0]["to_state"] == "thick"
    assert sizing["branch_changes"][0]["margin_jump"] < 0.0
    assert sizing["governing_location_changes"][0]["from_state"] == "mean"
    assert sizing["governing_location_changes"][0]["to_state"] == "internal"
    # monotonic_segments was dropped from the sizing response in dd67690 (2026-07-29).
    assert "monotonic_segments" not in sizing
    assert sizing["evaluation_count"] < 64

    forward = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure",
            "7 ksi",
            "--internal-radius",
            "3 in",
            "--wall-thickness",
            f"{selected_mm:.17g} mm",
            *material_args,
            "--json",
        ],
    )
    assert forward.exit_code == 0, forward.output
    forward_payload = json.loads(forward.stdout)
    assert {key: payload[key] for key in forward_payload} == forward_payload

    # This target is within 5e-11 of the limiting thin-branch margin.
    near_transition_target = 0.02273476252
    near_transition = runner.invoke(
        app,
        [
            *sizing_args,
            "--minimum-margin",
            str(near_transition_target),
            *material_args,
            "--json",
        ],
    )
    assert near_transition.exit_code == 0, near_transition.output
    near_transition_payload = json.loads(near_transition.stdout)
    assert near_transition_payload["result"]["branch"] == "thin"
    assert (
        near_transition_payload["sizing"]["selected_minimum_margin"]
        >= near_transition_target
    )


def test_committed_tube_size_example_runs() -> None:
    result = runner.invoke(
        app,
        ["tube", "size", "--input", str(EXAMPLES / "tube_size_7_ksi.json"), "--json"],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["operation"] == "size"
    assert payload["sizing"]["target_minimum_margin"] == 0.1
    assert payload["sizing"]["selected_minimum_margin"] >= 0.1


def test_tube_size_cli_elastic_options_match_json_and_release_displacement() -> None:
    # The sizing JSON schema accepts the optional elastic properties, so the
    # option surface must too, and both spellings must produce one response.
    cli = runner.invoke(
        app,
        [
            "tube",
            "size",
            "--external-pressure",
            "7 ksi",
            "--internal-radius",
            "3 in",
            "--wall-thickness-lower",
            "0.1 in",
            "--wall-thickness-upper",
            "0.5 in",
            "--yield-strength",
            "62 ksi",
            "--failure-category",
            "ductile_metal",
            "--elastic-modulus",
            "10000 ksi",
            "--poisson-ratio",
            "0.33",
            "--json",
        ],
    )
    assert cli.exit_code == 0, cli.output
    cli_payload = json.loads(cli.stdout)
    assert cli_payload["result"]["displacement_status"] == "released"
    assert (
        cli_payload["result"]["stress_states"][0]["radial_displacement_mm"]["value"]
        < 0.0
    )

    request = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "tube",
        "operation": "size",
        "inputs": {
            "external_pressure": {"unit": "ksi", "value": 7.0},
            "force_thick": False,
            "internal_radius": {"unit": "inch", "value": 3.0},
            "minimum_margin": 0.0,
            "wall_thickness_bounds": {
                "lower": {"unit": "inch", "value": 0.1},
                "upper": {"unit": "inch", "value": 0.5},
            },
        },
        "material": {
            "type": "explicit",
            "properties": {
                "yield_strength": {"unit": "ksi", "value": 62.0},
                "failure_category": "ductile_metal",
                "elastic_modulus": {"unit": "ksi", "value": 10000.0},
                "poisson_ratio": 0.33,
            },
        },
    }
    via_json = runner.invoke(
        app, ["tube", "size", "--input", "-", "--json"], input=json.dumps(request)
    )
    assert via_json.exit_code == 0, via_json.output
    assert json.loads(via_json.stdout) == cli_payload


def test_tube_size_rejects_elastic_options_beside_input_file() -> None:
    result = runner.invoke(
        app,
        [
            "tube",
            "size",
            "--input",
            str(EXAMPLES / "tube_size_7_ksi.json"),
            "--elastic-modulus",
            "10000 ksi",
            "--json",
        ],
    )
    assert result.exit_code == 2
    assert json.loads(result.stderr)["error"]["code"] == "input_source_conflict"


def test_tube_size_json_target_can_select_the_post_boundary_thick_root() -> None:
    request = {
        "schema_version": CALC_SCHEMA_VERSION,
        "model": "tube",
        "operation": "size",
        "inputs": {
            "external_pressure": {"value": 7, "unit": "ksi"},
            "internal_radius": {"value": 3, "unit": "in"},
            "wall_thickness_bounds": {
                "lower": {"value": 0.1, "unit": "in"},
                "upper": {"value": 0.5, "unit": "in"},
            },
            "minimum_margin": 0.1,
            "force_thick": False,
        },
        "material": {
            "type": "explicit",
            "provenance": "test sizing property record",
            "properties": {
                "yield_strength": {"value": 62, "unit": "ksi"},
                "failure_category": "ductile_metal",
            },
        },
    }

    result = runner.invoke(
        app,
        ["tube", "size", "--input", "-", "--json"],
        input=json.dumps(request),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["sizing"]["target_minimum_margin"] == 0.1
    assert payload["sizing"]["selected_minimum_margin"] >= 0.1
    assert payload["result"]["branch"] == "thick"
    assert payload["sizing"]["verified_bracket"]["lower"]["minimum_margin"] < 0.1
    assert payload["sizing"]["verified_bracket"]["upper"]["minimum_margin"] >= 0.1
    assert payload["sizing"]["branch_changes"][0]["margin_jump"] < 0.0


def test_tube_size_preserves_thin_root_at_float_rounded_branch_boundary() -> None:
    result = runner.invoke(
        app,
        [
            "tube",
            "size",
            "--external-pressure",
            "10 MPa",
            "--internal-radius",
            "100 mm",
            "--wall-thickness-lower",
            "1 mm",
            "--wall-thickness-upper",
            "20 mm",
            "--minimum-margin",
            "0.1547005383791",
            "--yield-strength",
            "100 MPa",
            "--failure-category",
            "ductile_metal",
            "--material-provenance",
            "test sizing property record",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["result"]["branch"] == "thin"
    assert payload["result"]["wall_thickness_mm"]["value"] < 100.0 / 9.5
    assert payload["sizing"]["branch_changes"][0]["margin_jump"] < 0.0


def test_tube_size_reports_observed_same_branch_margin_decrease(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calculate = sizing._calculate_tube_result

    def nonmonotonic_result(**kwargs):
        result = calculate(**kwargs)
        thickness = kwargs["wall_thickness_mm"]
        margin = -10.0 if thickness == 10.0 else thickness - 5.0
        return replace(result, margin=margin)

    monkeypatch.setattr(sizing, "_calculate_tube_result", nonmonotonic_result)
    result = runner.invoke(
        app,
        [
            "tube",
            "size",
            "--external-pressure",
            "10 MPa",
            "--internal-radius",
            "100 mm",
            "--wall-thickness-lower",
            "1 mm",
            "--wall-thickness-upper",
            "19 mm",
            "--yield-strength",
            "100 MPa",
            "--failure-category",
            "ductile_metal",
            "--force-thick",
            "--json",
        ],
    )

    payload = _error_payload(result)
    assert payload["error"]["code"] == "no_reliable_solution"
    assert "margin decreased" in payload["error"]["message"]


def test_tube_size_returns_lower_bound_when_it_already_meets_target() -> None:
    result = runner.invoke(
        app,
        [
            "tube",
            "size",
            "--external-pressure",
            "1 ksi",
            "--internal-radius",
            "3 in",
            "--wall-thickness-lower",
            "0.1 in",
            "--wall-thickness-upper",
            "0.5 in",
            "--yield-strength",
            "62 ksi",
            "--failure-category",
            "ductile_metal",
            "--material-provenance",
            "test sizing property record",
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    sizing = json.loads(result.stdout)["sizing"]
    assert sizing["solution_type"] == "lower_bound"
    assert sizing["selected_wall_thickness"] == sizing["bounds"]["lower"]
    assert sizing["verified_bracket"] is None


def test_tube_size_has_structured_failures_for_unreliable_solution_and_bad_bounds() -> None:
    common = [
        "tube",
        "size",
        "--external-pressure",
        "8 ksi",
        "--internal-radius",
        "3 in",
        "--yield-strength",
        "62 ksi",
        "--failure-category",
        "ductile_metal",
        "--material-provenance",
        "test sizing property record",
        "--json",
    ]
    no_solution = runner.invoke(
        app,
        [
            *common,
            "--wall-thickness-lower",
            "0.1 in",
            "--wall-thickness-upper",
            "0.2 in",
        ],
    )
    no_solution_payload = _error_payload(no_solution)
    assert no_solution_payload["error"]["code"] == "no_reliable_solution"
    diagnostics = no_solution_payload["error"]["details"][0]
    assert diagnostics["declared_check_set"] == ["cylindrical_shell_stress"]
    assert diagnostics["upper_evaluation"]["minimum_margin"] < 0.0

    bad_bounds = runner.invoke(
        app,
        [
            *common,
            "--wall-thickness-lower",
            "0.5 in",
            "--wall-thickness-upper",
            "0.1 in",
        ],
    )
    assert _error_payload(bad_bounds)["error"]["code"] == "invalid_bounds"

    unitless_bound = runner.invoke(
        app,
        [
            *common,
            "--wall-thickness-lower",
            "0.1",
            "--wall-thickness-upper",
            "0.5 in",
        ],
    )
    assert _error_payload(unitless_bound)["error"]["code"] == "invalid_quantity"

    overflowing_bound = runner.invoke(
        app,
        [
            *common,
            "--wall-thickness-lower",
            "0.1 in",
            "--wall-thickness-upper",
            "1e308 mile",
        ],
    )
    overflowing_payload = _error_payload(overflowing_bound)
    assert overflowing_payload["error"]["code"] == "invalid_quantity"
    assert "finite value" in overflowing_payload["error"]["message"]

    negative_margin = runner.invoke(
        app,
        [
            *common,
            "--wall-thickness-lower",
            "0.1 in",
            "--wall-thickness-upper",
            "0.5 in",
            "--minimum-margin",
            "-0.01",
        ],
    )
    assert _error_payload(negative_margin)["error"]["code"] == "invalid_request"


# One elastic material with a source-traceable proportional limit, which the
# buckling model requires before it releases any capacity.
CYLINDER_SIZE_MATERIAL = [
    "--yield-strength",
    "250 MPa",
    "--proportional-limit",
    "200 MPa",
    "--elastic-modulus",
    "70000 MPa",
    "--poisson-ratio",
    "0.3",
    "--failure-category",
    "ductile_metal",
    "--material-provenance",
    "test cylinder sizing property record",
]


def _cylinder_size_args(
    *,
    external_pressure: str,
    internal_radius: str,
    unsupported_length: str,
    lower: str,
    upper: str,
    minimum_margin: str | None = None,
    material: list[str] | None = None,
) -> list[str]:
    return [
        "smooth-buckling",
        "size",
        "--external-pressure",
        external_pressure,
        "--internal-radius",
        internal_radius,
        "--unsupported-length",
        unsupported_length,
        "--wall-thickness-lower",
        lower,
        "--wall-thickness-upper",
        upper,
        *(("--minimum-margin", minimum_margin) if minimum_margin is not None else ()),
        *(CYLINDER_SIZE_MATERIAL if material is None else material),
        "--json",
    ]


def _forward_cylinder_responses(
    *,
    external_pressure: str,
    internal_radius_mm: float,
    unsupported_length: str,
    wall_thickness_mm: float,
) -> dict[str, dict[str, Any]]:
    """Both forward responses at one wall thickness, from single-point runs."""
    thickness = f"{wall_thickness_mm:.17g} mm"
    # The tube command has no --proportional-limit: its model never reads one,
    # so the shared option list cannot be reused for this half.
    tube = runner.invoke(
        app,
        [
            "tube",
            "--external-pressure",
            external_pressure,
            "--internal-radius",
            f"{internal_radius_mm:.17g} mm",
            "--wall-thickness",
            thickness,
            "--yield-strength",
            "250 MPa",
            "--elastic-modulus",
            "70000 MPa",
            "--poisson-ratio",
            "0.3",
            "--failure-category",
            "ductile_metal",
            "--material-provenance",
            "test cylinder sizing property record",
            "--json",
        ],
    )
    assert tube.exit_code == 0, tube.output
    buckling = runner.invoke(
        app,
        [
            "smooth-buckling",
            "--external-pressure",
            external_pressure,
            "--shell-mid-surface-radius",
            f"{internal_radius_mm + 0.5 * wall_thickness_mm:.17g} mm",
            "--wall-thickness",
            thickness,
            "--unsupported-length",
            unsupported_length,
            "--load-case",
            "hydrostatic_closed_end",
            *CYLINDER_SIZE_MATERIAL,
            "--json",
        ],
    )
    assert buckling.exit_code == 0, buckling.output
    return {
        "smooth-buckling": json.loads(buckling.stdout),
        "tube": json.loads(tube.stdout),
    }


def test_cylinder_size_selection_and_bracket_match_independent_forward_runs() -> None:
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="2 MPa",
            internal_radius="100 mm",
            unsupported_length="700 mm",
            lower="2 mm",
            upper="9 mm",
            minimum_margin="0.25",
        ),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    sizing = payload["sizing"]
    assert payload["model"] == "smooth-buckling"
    assert payload["operation"] == "size"
    assert sizing["operation_version"] == "2.1.0"
    assert sizing["algorithm"] == "known_branch_partition_and_bisection"
    assert sizing["solution_type"] == "interior_root"
    assert sizing["declared_check_set"] == [
        "cylindrical_shell_stress",
        "smooth_cylinder_buckling",
    ]
    # Buckling governs this selection, and by the release gate it governs every
    # released thickness: see the invariant test below.
    assert sizing["selected_governing_check"] == "smooth_cylinder_buckling"
    assert sizing["selected_minimum_margin"] >= 0.25

    selected_mm = sizing["selected_wall_thickness"]["value"]
    assert sizing["selected_shell_mid_surface_radius"]["value"] == (
        100.0 + 0.5 * selected_mm
    )
    forward = _forward_cylinder_responses(
        external_pressure="2 MPa",
        internal_radius_mm=100.0,
        unsupported_length="700 mm",
        wall_thickness_mm=selected_mm,
    )
    assert payload["selected_results"] == forward
    assert sizing["selected_check_margins"] == {
        "cylindrical_shell_stress": forward["tube"]["result"]["margin"],
        "smooth_cylinder_buckling": forward["smooth-buckling"]["result"]["margin"],
    }

    # The reported bracket is a fail/pass pair, verified the same way.
    bracket = sizing["verified_bracket"]
    assert bracket["lower"]["minimum_margin"] < 0.25 <= bracket["upper"]["minimum_margin"]
    assert bracket["upper"]["wall_thickness"] == sizing["selected_wall_thickness"]
    for end in ("lower", "upper"):
        end_forward = _forward_cylinder_responses(
            external_pressure="2 MPa",
            internal_radius_mm=100.0,
            unsupported_length="700 mm",
            wall_thickness_mm=bracket[end]["wall_thickness"]["value"],
        )
        assert bracket[end]["check_margins"] == {
            "cylindrical_shell_stress": end_forward["tube"]["result"]["margin"],
            "smooth_cylinder_buckling": (
                end_forward["smooth-buckling"]["result"]["margin"]
            ),
        }
        assert bracket[end]["tube_branch"] == end_forward["tube"]["result"]["branch"]
        assert bracket[end]["buckling_regime"] == (
            end_forward["smooth-buckling"]["result"]["regime"]
        )


def test_cylinder_size_returns_lower_bound_when_it_already_meets_target() -> None:
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="0.5 MPa",
            internal_radius="100 mm",
            unsupported_length="700 mm",
            lower="6 mm",
            upper="9 mm",
        ),
    )

    assert result.exit_code == 0, result.output
    sizing = json.loads(result.stdout)["sizing"]
    assert sizing["solution_type"] == "lower_bound"
    assert sizing["selected_wall_thickness"] == sizing["bounds"]["lower"]
    assert sizing["verified_bracket"] is None
    assert sizing["bisection_iterations"] == 0


# The gamma*Z = 100 boundary, where the released capacity switches from NASA
# Eq. 24 to the Eqs. 20/22 minimization and jumps upward, so a target can sit
# above where the moderate branch ends and below where the short branch starts.
# An internal radius of 100 mm and an unsupported length of 400 mm put that
# boundary at this thickness, and the pressure is the one whose moderate margin
# there is exactly 0.20. The correlated critical stress at the boundary is
# 279.5 MPa on the moderate side and 298.4 MPa on the short side selected, so
# the shared 200 MPa proportional limit would withhold the capacity instead of
# releasing it.
CYLINDER_REGIME_BOUNDARY_MATERIAL = [
    "--yield-strength",
    "700 MPa",
    "--proportional-limit",
    "690 MPa",
    "--elastic-modulus",
    "70000 MPa",
    "--poisson-ratio",
    "0.3",
    "--failure-category",
    "ductile_metal",
    "--material-provenance",
    "test cylinder sizing property record",
]
CYLINDER_REGIME_BOUNDARY_PRESSURE = "18.44287160741702 MPa"


def test_cylinder_size_selects_the_branch_that_opens_at_a_regime_boundary() -> None:
    """A target inside the capacity jump is met by the branch above it.

    No thickness brackets such a target: the moderate branch ends below it and
    the short branch starts above it. The first thickness of the short branch
    is then the smallest that meets it, and every thickness below was already
    proved failing.
    """
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure=CYLINDER_REGIME_BOUNDARY_PRESSURE,
            internal_radius="100 mm",
            unsupported_length="400 mm",
            lower="4 mm",
            upper="10 mm",
            minimum_margin="0.25",
            material=CYLINDER_REGIME_BOUNDARY_MATERIAL,
        ),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    sizing = payload["sizing"]
    assert sizing["solution_type"] == "branch_start"
    assert sizing["verified_bracket"] is None
    assert sizing["bisection_iterations"] == 0

    # The selection is the first thickness of the short branch, and the last
    # thickness of the moderate branch below it is one float away and short of
    # the target, so nothing smaller meets it.
    (regime_change,) = sizing["buckling_regime_changes"]
    assert (regime_change["from_state"], regime_change["to_state"]) == (
        "moderate",
        "short",
    )
    selected_mm = sizing["selected_wall_thickness"]["value"]
    assert selected_mm == regime_change["upper"]["wall_thickness"]["value"]
    assert math.nextafter(
        regime_change["lower"]["wall_thickness"]["value"], math.inf
    ) == selected_mm
    assert regime_change["lower"]["minimum_margin"] < 0.25
    assert sizing["selected_minimum_margin"] == (
        regime_change["upper"]["minimum_margin"]
    )
    assert sizing["selected_minimum_margin"] >= 0.25
    assert payload["selected_results"]["smooth-buckling"]["result"]["regime"] == "short"

    # A target the moderate branch does reach is still bisected on that branch,
    # below the boundary: the branch above is only taken once every branch under
    # it has been given its own chance to bracket the target.
    below = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure=CYLINDER_REGIME_BOUNDARY_PRESSURE,
            internal_radius="100 mm",
            unsupported_length="400 mm",
            lower="4 mm",
            upper="10 mm",
            minimum_margin="0.199",
            material=CYLINDER_REGIME_BOUNDARY_MATERIAL,
        ),
    )

    assert below.exit_code == 0, below.output
    below_sizing = json.loads(below.stdout)["sizing"]
    assert below_sizing["solution_type"] == "interior_root"
    assert below_sizing["selected_wall_thickness"]["value"] < selected_mm


def test_released_buckling_capacity_always_governs_over_tube_yielding() -> None:
    """The yield-governed case this operation could report does not exist.

    Releasing a smooth-cylinder capacity requires the correlated critical
    circumferential stress to be at or below the proportional limit, which the
    kernel requires to be at or below the yield strength. Yielding governs only
    when that same stress is above ``2 / sqrt(3)`` times the yield strength,
    because the closed-end thin-wall von Mises stress is ``sqrt(3) / 2`` times
    the hoop stress and both checks read one hoop stress at one ``r/t``. The two
    conditions cannot hold together, so the buckling margin is the smaller one
    at every released thickness. This test states the inequality and then walks
    a released band to show it.
    """
    yield_strength_mpa = 250.0
    proportional_limit_mpa = 200.0
    for thickness_mm in (2.0, 3.5, 5.0, 6.5, 8.0, 9.3):
        tube = closed_end_tube_stress(
            external_pressure_mpa=2.0,
            internal_radius_mm=100.0,
            wall_thickness_mm=thickness_mm,
            strength_mpa=yield_strength_mpa,
            material_failure_category="ductile_metal",
        )
        buckling = smooth_cylinder_external_pressure_buckling(
            external_pressure_mpa=2.0,
            shell_mid_surface_radius_mm=100.0 + 0.5 * thickness_mm,
            wall_thickness_mm=thickness_mm,
            unsupported_length_mm=700.0,
            elastic_modulus_mpa=70000.0,
            poisson_ratio=0.3,
            yield_strength_mpa=yield_strength_mpa,
            load_case="hydrostatic_closed_end",
            proportional_limit_mpa=proportional_limit_mpa,
        )
        assert buckling.capacity_status == "released"
        critical_stress = buckling.correlated_critical_circumferential_stress_mpa
        assert critical_stress <= proportional_limit_mpa <= yield_strength_mpa
        assert critical_stress < 2.0 / math.sqrt(3.0) * yield_strength_mpa
        assert buckling.margin <= tube.margin
        # A released capacity also forces the thin tube branch: both models put
        # their own limit at a mean-radius to thickness ratio of 10.
        assert tube.branch == "thin"

    # The operation reports the governing check rather than assuming it, and it
    # never changes across a released band.
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="2 MPa",
            internal_radius="100 mm",
            unsupported_length="700 mm",
            lower="2 mm",
            upper="9.3 mm",
            minimum_margin="4.0",
        ),
    )
    assert result.exit_code == 0, result.output
    sizing = json.loads(result.stdout)["sizing"]
    assert sizing["governing_check_changes"] == []
    assert sizing["selected_governing_check"] == "smooth_cylinder_buckling"


def test_cylinder_size_refuses_bounds_that_span_a_withheld_regime() -> None:
    """Bounds spanning the moderate/long overlap have no reliable solution.

    The governing check cannot change across these bounds, but the buckling
    regime can, and NASA releases no capacity in the band between the moderate
    and long regions. The derived boundary in thickness space is the evidence:
    it is not a constant, it is solved for.
    """
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="5 MPa",
            internal_radius="100 mm",
            unsupported_length="2000 mm",
            lower="3 mm",
            upper="10 mm",
        ),
    )

    payload = _error_payload(result)
    assert payload["error"]["code"] == "no_reliable_solution"
    assert "withheld" in payload["error"]["message"]
    diagnostics = payload["error"]["details"][0]
    assert diagnostics["capacity_status"] == "withheld_correlation_overlap"
    assert diagnostics["buckling_regime"] == "moderate_long_correlation_overlap"
    inside = {
        boundary["boundary"]: boundary["wall_thickness"]["value"]
        for boundary in diagnostics["derived_branch_partition"]
        if boundary["inside_bounds"]
    }
    assert set(inside) == {
        "long_regime_oval_wave_limit",
        "moderate_regime_more_than_two_wave_limit",
    }

    # Each derived boundary is the last thickness before the regime it bounds,
    # checked against independent forward evaluations one float apart.
    def regime(wall_thickness_mm: float) -> str:
        return smooth_cylinder_external_pressure_buckling(
            external_pressure_mpa=5.0,
            shell_mid_surface_radius_mm=100.0 + 0.5 * wall_thickness_mm,
            wall_thickness_mm=wall_thickness_mm,
            unsupported_length_mm=2000.0,
            elastic_modulus_mpa=70000.0,
            poisson_ratio=0.3,
            yield_strength_mpa=250.0,
            load_case="hydrostatic_closed_end",
            proportional_limit_mpa=200.0,
        ).regime

    assert regime(inside["long_regime_oval_wave_limit"]) == "moderate"
    assert regime(math.nextafter(inside["long_regime_oval_wave_limit"], math.inf)) == (
        "moderate_long_correlation_overlap"
    )
    assert regime(inside["moderate_regime_more_than_two_wave_limit"]) == (
        "moderate_long_correlation_overlap"
    )
    assert regime(
        math.nextafter(inside["moderate_regime_more_than_two_wave_limit"], math.inf)
    ) == "long"

    # Bounds inside the long region alone do have a solution.
    inside_long = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="5 MPa",
            internal_radius="100 mm",
            unsupported_length="2000 mm",
            lower="5.6 mm",
            upper="10 mm",
        ),
    )
    assert inside_long.exit_code == 0, inside_long.output
    long_sizing = json.loads(inside_long.stdout)["sizing"]
    assert long_sizing["verified_bracket"]["upper"]["buckling_regime"] == "long"
    assert long_sizing["selected_minimum_margin"] >= 0.0


def test_cylinder_size_lower_bound_wins_before_a_withheld_regime_is_probed() -> None:
    """A passing lower bound is the whole answer even across the overlap band.

    The same bounds span the withheld moderate/long overlap as in the
    refusal test above, but at this pressure the lower bound already meets
    every target, so the search selects it without evaluating any thickness
    the model withholds.
    """
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="0.2 MPa",
            internal_radius="100 mm",
            unsupported_length="2000 mm",
            lower="3 mm",
            upper="10 mm",
        ),
    )

    assert result.exit_code == 0, result.output
    sizing = json.loads(result.stdout)["sizing"]
    assert sizing["solution_type"] == "lower_bound"
    assert sizing["selected_wall_thickness"] == sizing["bounds"]["lower"]
    assert sizing["verified_bracket"] is None
    assert sizing["evaluation_count"] == 1


def test_cylinder_size_without_a_proportional_limit_has_no_reliable_solution() -> None:
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="2 MPa",
            internal_radius="100 mm",
            unsupported_length="700 mm",
            lower="2 mm",
            upper="9 mm",
            material=[
                "--yield-strength",
                "250 MPa",
                "--elastic-modulus",
                "70000 MPa",
                "--poisson-ratio",
                "0.3",
                "--failure-category",
                "ductile_metal",
            ],
        ),
    )

    payload = _error_payload(result)
    assert payload["error"]["code"] == "no_reliable_solution"
    diagnostics = payload["error"]["details"][0]
    assert diagnostics["capacity_status"] == "withheld_applicability"
    assert diagnostics["wall_thickness"] == {"unit": "mm", "value": 2.0}
    assert any(
        "proportional_limit_mpa is required" in reason
        for reason in diagnostics["withheld_reasons"]
    )

    # A committed database record that stores no proportional limit is
    # stress-only, so a named material reaches the same withholding through
    # the same path.
    named = runner.invoke(
        app,
        [
            "smooth-buckling",
            "size",
            "--external-pressure",
            "2 MPa",
            "--internal-radius",
            "100 mm",
            "--unsupported-length",
            "700 mm",
            "--wall-thickness-lower",
            "2 mm",
            "--wall-thickness-upper",
            "9 mm",
            "--material",
            "SS-316-316L",
            "--materials-file",
            str(MATERIALS_FILE),
            "--json",
        ],
    )
    named_payload = _error_payload(named)
    assert named_payload["error"]["code"] == "no_reliable_solution"
    assert any(
        "proportional_limit_mpa is required" in reason
        for reason in named_payload["error"]["details"][0]["withheld_reasons"]
    )


def test_cylinder_size_names_a_capacity_that_is_pending_plasticity() -> None:
    """An elastic upper bound is not a sizing capacity, and the refusal says so.

    Sizing stays strict, but this state fills neither ``validity_violations``
    nor ``release_gate_violations``, so calling it withheld with no reason at
    all would be the one refusal a caller could not act on.
    """
    result = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="2 MPa",
            internal_radius="100 mm",
            unsupported_length="150 mm",
            lower="2 mm",
            upper="9 mm",
            minimum_margin="0.25",
        ),
    )

    payload = _error_payload(result)
    assert payload["error"]["code"] == "no_reliable_solution"
    assert "pending plasticity validation" in payload["error"]["message"]
    diagnostics = payload["error"]["details"][0]
    assert diagnostics["capacity_status"] == "released_pending_plasticity"
    assert diagnostics["buckling_regime"] == "short"
    assert any(
        "elastic upper bound pending validation" in reason
        for reason in diagnostics["withheld_reasons"]
    )


def test_cylinder_size_has_structured_failures_for_no_solution_and_bad_bounds() -> None:
    no_solution = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="2 MPa",
            internal_radius="100 mm",
            unsupported_length="700 mm",
            lower="2 mm",
            upper="3 mm",
        ),
    )
    payload = _error_payload(no_solution)
    assert payload["error"]["code"] == "no_reliable_solution"
    assert "bracket" in payload["error"]["message"]
    diagnostics = payload["error"]["details"][0]
    assert diagnostics["declared_check_set"] == [
        "cylindrical_shell_stress",
        "smooth_cylinder_buckling",
    ]
    assert diagnostics["lower_evaluation"]["minimum_margin"] < 0.0
    assert diagnostics["upper_evaluation"]["minimum_margin"] < 0.0
    assert diagnostics["governing_check_changes"] == []
    for end, thickness_mm in (("lower", 2.0), ("upper", 3.0)):
        forward = _forward_cylinder_responses(
            external_pressure="2 MPa",
            internal_radius_mm=100.0,
            unsupported_length="700 mm",
            wall_thickness_mm=thickness_mm,
        )
        assert diagnostics[f"{end}_evaluation"]["check_margins"] == {
            "cylindrical_shell_stress": forward["tube"]["result"]["margin"],
            "smooth_cylinder_buckling": forward["smooth-buckling"]["result"]["margin"],
        }

    bad_bounds = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="2 MPa",
            internal_radius="100 mm",
            unsupported_length="700 mm",
            lower="9 mm",
            upper="2 mm",
        ),
    )
    assert _error_payload(bad_bounds)["error"]["code"] == "invalid_bounds"

    negative_margin = runner.invoke(
        app,
        _cylinder_size_args(
            external_pressure="2 MPa",
            internal_radius="100 mm",
            unsupported_length="700 mm",
            lower="2 mm",
            upper="9 mm",
            minimum_margin="-0.01",
        ),
    )
    assert _error_payload(negative_margin)["error"]["code"] == "invalid_request"


def test_committed_cylinder_size_example_runs() -> None:
    result = runner.invoke(
        app,
        [
            "smooth-buckling",
            "size",
            "--input",
            str(EXAMPLES / "smooth_buckling_size_moderate.json"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["operation"] == "size"
    assert payload["sizing"]["target_minimum_margin"] == 0.25
    assert payload["sizing"]["selected_minimum_margin"] >= 0.25
    assert set(payload["selected_results"]) == {"smooth-buckling", "tube"}


# One elastic material with no proportional limit: the plate model reads none.
PLATE_SIZE_MATERIAL = [
    "--yield-strength",
    "250 MPa",
    "--elastic-modulus",
    "70000 MPa",
    "--poisson-ratio",
    "0.3",
    "--failure-category",
    "ductile_metal",
    "--material-provenance",
    "test plate sizing property record",
]


def _plate_size_args(
    *,
    lower: str,
    upper: str,
    boundary_condition: str = "fixed",
    external_pressure: str = "2 MPa",
    free_radius: str = "100 mm",
    minimum_margin: str | None = None,
    maximum_deflection: str | None = None,
    material: list[str] | None = None,
) -> list[str]:
    return [
        "plate",
        "size",
        "--external-pressure",
        external_pressure,
        "--free-radius",
        free_radius,
        "--boundary-condition",
        boundary_condition,
        "--plate-thickness-lower",
        lower,
        "--plate-thickness-upper",
        upper,
        *(("--minimum-margin", minimum_margin) if minimum_margin is not None else ()),
        *(
            ("--maximum-deflection", maximum_deflection)
            if maximum_deflection is not None
            else ()
        ),
        *(PLATE_SIZE_MATERIAL if material is None else material),
        "--json",
    ]


def _forward_plate_result(
    *,
    plate_thickness_mm: float,
    boundary_condition: str = "fixed",
    external_pressure: str = "2 MPa",
    free_radius: str = "100 mm",
) -> dict[str, Any]:
    """The forward plate response at one thickness, from a single-point run."""
    forward = runner.invoke(
        app,
        [
            "plate",
            "--external-pressure",
            external_pressure,
            "--free-radius",
            free_radius,
            "--plate-thickness",
            f"{plate_thickness_mm:.17g} mm",
            "--boundary-condition",
            boundary_condition,
            *PLATE_SIZE_MATERIAL,
            "--json",
        ],
    )
    assert forward.exit_code == 0, forward.output
    return json.loads(forward.stdout)


def test_plate_size_bending_governed_matches_independent_forward_runs() -> None:
    """No deflection limit: bending alone decides, and its own floor alone gates.

    The upper bound sits at ``D_free/t = 16.67``, below the fixed-edge
    centre-deflection floor of 20 and above the bending floor of 10, so this
    also shows that the unneeded output's stricter floor decides nothing.
    """
    result = runner.invoke(
        app,
        _plate_size_args(lower="6 mm", upper="12 mm", minimum_margin="0.25"),
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    sizing = payload["sizing"]
    assert payload["model"] == "plate"
    assert payload["operation"] == "size"
    assert sizing["operation_version"] == "1.1.0"
    assert sizing["solution_type"] == "interior_root"
    assert sizing["declared_check_set"] == ["flat_endcap_bending"]
    assert sizing["check_targets"] == {"flat_endcap_bending": 0.25}
    assert sizing["maximum_deflection"] is None
    assert sizing["selected_governing_check"] == "flat_endcap_bending"
    assert sizing["selected_minimum_target_slack"] >= 0.0

    selected_mm = sizing["selected_plate_thickness"]["value"]
    forward = _forward_plate_result(plate_thickness_mm=selected_mm)
    assert payload["result"] == forward["result"]
    assert sizing["selected_check_margins"] == {
        "flat_endcap_bending": forward["result"]["margin"]
    }
    # The upper bound's deflection is withheld and was not needed.
    withheld = _forward_plate_result(plate_thickness_mm=12.0)
    assert withheld["result"]["deflection_status"] == "withheld_applicability"
    assert withheld["result"]["validity_violations"] == []

    bracket = sizing["verified_bracket"]
    assert bracket["upper"]["plate_thickness"] == sizing["selected_plate_thickness"]
    assert bracket["lower"]["minimum_target_slack"] < 0.0 <= (
        bracket["upper"]["minimum_target_slack"]
    )
    for end in ("lower", "upper"):
        end_forward = _forward_plate_result(
            plate_thickness_mm=bracket[end]["plate_thickness"]["value"]
        )
        assert bracket[end]["check_margins"] == {
            "flat_endcap_bending": end_forward["result"]["margin"]
        }
        assert bracket[end]["free_diameter_over_thickness"] == (
            end_forward["result"]["free_diameter_over_thickness"]
        )


def test_plate_size_deflection_governed_matches_independent_forward_runs() -> None:
    """A limit the bending target cannot reach on its own moves the selection."""
    bending_only = runner.invoke(
        app,
        _plate_size_args(lower="6 mm", upper="9.5 mm", minimum_margin="0.25"),
    )
    assert bending_only.exit_code == 0, bending_only.output
    bending_mm = json.loads(bending_only.stdout)["sizing"]["selected_plate_thickness"][
        "value"
    ]

    result = runner.invoke(
        app,
        _plate_size_args(
            lower="6 mm",
            upper="9.5 mm",
            minimum_margin="0.25",
            maximum_deflection="0.6 mm",
        ),
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    sizing = payload["sizing"]
    assert sizing["declared_check_set"] == ["flat_endcap_bending", "center_deflection"]
    # The deflection limit is a limit, not a margin, so its target is zero
    # while the bending target is the caller's.
    assert sizing["check_targets"] == {
        "flat_endcap_bending": 0.25,
        "center_deflection": 0.0,
    }
    assert sizing["maximum_deflection"] == {"unit": "mm", "value": 0.6}
    assert sizing["selected_governing_check"] == "center_deflection"

    selected_mm = sizing["selected_plate_thickness"]["value"]
    assert selected_mm > bending_mm
    forward = _forward_plate_result(plate_thickness_mm=selected_mm)
    assert payload["result"] == forward["result"]
    assert forward["result"]["deflection_status"] == "released"
    released_mm = forward["result"]["released_maximum_deflection_mm"]["value"]
    assert released_mm <= 0.6
    assert sizing["selected_check_margins"] == {
        "flat_endcap_bending": forward["result"]["margin"],
        "center_deflection": 0.6 / released_mm - 1.0,
    }

    bracket = sizing["verified_bracket"]
    assert bracket["lower"]["minimum_target_slack"] < 0.0 <= (
        bracket["upper"]["minimum_target_slack"]
    )
    lower_forward = _forward_plate_result(
        plate_thickness_mm=bracket["lower"]["plate_thickness"]["value"]
    )
    assert (
        lower_forward["result"]["released_maximum_deflection_mm"]["value"] > 0.6
    )


def test_plate_size_reports_a_governing_constraint_change() -> None:
    """Bending goes as t^2 and deflection as t^3, so which binds can change."""
    result = runner.invoke(
        app,
        _plate_size_args(lower="7 mm", upper="9 mm", maximum_deflection="1.0 mm"),
    )

    assert result.exit_code == 0, result.output
    sizing = json.loads(result.stdout)["sizing"]
    changes = sizing["governing_check_changes"]
    assert [(change["from_state"], change["to_state"]) for change in changes] == [
        ("center_deflection", "flat_endcap_bending")
    ]
    change = changes[0]
    assert change["lower"]["plate_thickness"]["value"] < (
        change["upper"]["plate_thickness"]["value"]
    )
    # Continuous margins, so the change is a crossing rather than a jump: the
    # slack rises through it, as it does everywhere in the released band.
    assert change["target_slack_jump"] > 0.0
    assert sizing["selected_governing_check"] == "center_deflection"


def test_plate_size_refuses_a_thickness_whose_needed_output_is_withheld() -> None:
    """Each floor is per output and per edge, and both move with thickness."""
    # The same bounds that solved above, now with a deflection limit: the
    # upper bound is past the fixed-edge centre-deflection floor of 20.
    deflection_floor = runner.invoke(
        app,
        _plate_size_args(
            lower="6 mm",
            upper="12 mm",
            minimum_margin="0.25",
            maximum_deflection="0.6 mm",
        ),
    )
    payload = _error_payload(deflection_floor)
    assert payload["error"]["code"] == "no_reliable_solution"
    assert "withholds a needed output" in payload["error"]["message"]
    diagnostics = payload["error"]["details"][0]
    assert diagnostics["plate_thickness"] == {"unit": "mm", "value": 12.0}
    assert diagnostics["withheld_outputs"] == ["center_deflection"]
    assert diagnostics["deflection_minimum_free_diameter_over_thickness"] == 20.0
    assert diagnostics["free_diameter_over_thickness"] < 20.0
    assert any(
        "center-deflection evidence floor" in reason
        for reason in diagnostics["withheld_reasons"]
    )

    # A simply-supported plate has a deflection floor of 10, so the same
    # request over the same ratios is answerable for that edge.
    simply_supported = runner.invoke(
        app,
        _plate_size_args(
            lower="12 mm",
            upper="16 mm",
            boundary_condition="simply_supported",
            maximum_deflection="0.6 mm",
        ),
    )
    assert simply_supported.exit_code == 0, simply_supported.output
    supported_sizing = json.loads(simply_supported.stdout)["sizing"]
    assert supported_sizing["boundary_condition"] == "simply_supported"
    assert supported_sizing["selected_governing_check"] == "center_deflection"

    # Too thick for the bending floor, which is an upper limit on thickness.
    bending_floor = runner.invoke(app, _plate_size_args(lower="21 mm", upper="25 mm"))
    bending_payload = _error_payload(bending_floor)
    assert bending_payload["error"]["code"] == "no_reliable_solution"
    bending_diagnostics = bending_payload["error"]["details"][0]
    assert bending_diagnostics["withheld_outputs"] == ["flat_endcap_bending"]
    assert bending_diagnostics["free_diameter_over_thickness"] < 10.0

    # Too thin for the small-deflection gate, which is a lower limit, so the
    # released band is bounded on both sides and neither end is a constant.
    small_deflection = runner.invoke(
        app,
        _plate_size_args(lower="4 mm", upper="9.5 mm", minimum_margin="0.25"),
    )
    thin_payload = _error_payload(small_deflection)
    assert thin_payload["error"]["code"] == "no_reliable_solution"
    thin_diagnostics = thin_payload["error"]["details"][0]
    assert thin_diagnostics["withheld_outputs"] == ["flat_endcap_bending"]
    assert thin_diagnostics["shear_corrected_deflection_estimate_over_thickness"] > 0.5
    assert any(
        "small-deflection limit" in reason
        for reason in thin_diagnostics["withheld_reasons"]
    )

    # A Poisson ratio outside the swept evidence band withholds both outputs
    # at every thickness, so the first evaluation refuses.
    outside_band = runner.invoke(
        app,
        _plate_size_args(
            lower="6 mm",
            upper="9.5 mm",
            material=[
                "--yield-strength",
                "250 MPa",
                "--elastic-modulus",
                "70000 MPa",
                "--poisson-ratio",
                "0.4",
                "--failure-category",
                "ductile_metal",
            ],
        ),
    )
    band_payload = _error_payload(outside_band)
    assert band_payload["error"]["code"] == "no_reliable_solution"
    assert any(
        "swept evidence band" in reason
        for reason in band_payload["error"]["details"][0]["withheld_reasons"]
    )


def test_plate_size_has_structured_failures_for_no_solution_and_bad_bounds() -> None:
    no_solution = runner.invoke(
        app,
        _plate_size_args(lower="6 mm", upper="8 mm", minimum_margin="0.25"),
    )
    payload = _error_payload(no_solution)
    assert payload["error"]["code"] == "no_reliable_solution"
    assert "bracket" in payload["error"]["message"]
    diagnostics = payload["error"]["details"][0]
    assert diagnostics["variable"] == "plate_thickness"
    assert diagnostics["declared_check_set"] == ["flat_endcap_bending"]
    assert diagnostics["governing_check_changes"] == []
    for end, thickness_mm in (("lower", 6.0), ("upper", 8.0)):
        forward = _forward_plate_result(plate_thickness_mm=thickness_mm)
        assert diagnostics[f"{end}_evaluation"]["check_margins"] == {
            "flat_endcap_bending": forward["result"]["margin"]
        }
        assert diagnostics[f"{end}_evaluation"]["minimum_target_slack"] < 0.0

    bad_bounds = runner.invoke(app, _plate_size_args(lower="9 mm", upper="6 mm"))
    bad_payload = _error_payload(bad_bounds)
    assert bad_payload["error"]["code"] == "invalid_bounds"
    assert "plate-thickness bounds" in bad_payload["error"]["message"]

    negative_margin = runner.invoke(
        app,
        _plate_size_args(lower="6 mm", upper="9.5 mm", minimum_margin="-0.01"),
    )
    assert _error_payload(negative_margin)["error"]["code"] == "invalid_request"

    negative_deflection = runner.invoke(
        app,
        _plate_size_args(
            lower="6 mm",
            upper="9.5 mm",
            maximum_deflection="-0.6 mm",
        ),
    )
    negative_payload = _error_payload(negative_deflection)
    assert negative_payload["error"]["code"] == "invalid_request"
    assert "maximum_deflection must be positive" in negative_payload["error"]["message"]

    stress_only = runner.invoke(
        app,
        _plate_size_args(
            lower="6 mm",
            upper="9.5 mm",
            material=[
                "--yield-strength",
                "250 MPa",
                "--failure-category",
                "ductile_metal",
            ],
        ),
    )
    assert _error_payload(stress_only)["error"]["code"] == "invalid_request"


@pytest.mark.parametrize(
    ("released_deflection", "maximum_deflection", "message"),
    [
        (0.0, 1.0, "released plate deflection must be finite and positive"),
        (
            math.nextafter(0.0, 1.0),
            1.0e308,
            "plate deflection margin cannot be represented as a finite number",
        ),
    ],
)
def test_plate_size_rejects_unrepresentable_deflection_margins(
    released_deflection: float,
    maximum_deflection: float,
    message: str,
) -> None:
    result = flat_circular_plate(
        external_pressure_mpa=2.0,
        free_radius_mm=100.0,
        plate_thickness_mm=8.0,
        elastic_modulus_mpa=70_000.0,
        poisson_ratio=0.3,
        strength_mpa=250.0,
        material_failure_category="ductile_metal",
        boundary_condition="fixed",
    )
    result = replace(
        result,
        deflection_status="released",
        released_maximum_deflection_mm=released_deflection,
    )

    with pytest.raises(CalcCliError, match=message) as caught:
        sizing._plate_sizing_sample(
            result,
            maximum_deflection_mm=maximum_deflection,
            check_targets={
                "flat_endcap_bending": 0.0,
                "center_deflection": 0.0,
            },
        )

    assert caught.value.code == "unevaluable_model"


def test_plate_size_returns_lower_bound_when_it_already_meets_target() -> None:
    result = runner.invoke(
        app,
        _plate_size_args(lower="9.5 mm", upper="10 mm", minimum_margin="0.25"),
    )

    assert result.exit_code == 0, result.output
    sizing = json.loads(result.stdout)["sizing"]
    assert sizing["solution_type"] == "lower_bound"
    assert sizing["selected_plate_thickness"] == sizing["bounds"]["lower"]
    assert sizing["verified_bracket"] is None
    assert sizing["bisection_iterations"] == 0


def test_committed_plate_size_example_runs() -> None:
    result = runner.invoke(
        app,
        [
            "plate",
            "size",
            "--input",
            str(EXAMPLES / "plate_size_deflection_limited.json"),
            "--json",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = json.loads(result.stdout)
    assert payload["operation"] == "size"
    assert payload["sizing"]["check_targets"] == {
        "flat_endcap_bending": 0.25,
        "center_deflection": 0.0,
    }
    assert payload["sizing"]["selected_minimum_target_slack"] >= 0.0
    assert payload["result"]["deflection_status"] == "released"
