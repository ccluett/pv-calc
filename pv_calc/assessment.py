"""Assess existing calculation results without rerunning engineering kernels.

Cylinder composition and response assessment share the same decision rules.
Rendering consumes these assessments and adds no acceptance policy.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from copy import deepcopy
from dataclasses import dataclass
from typing import Any, Literal

from pv_calc.contracts import QuantityInput, _to_unit
from pv_calc.errors import CalcCliError
from pv_calc.pressure_vessel import (
    BUCKLING_ELASTIC_UPPER_BOUND_FAILURE_REASON,
    BUCKLING_ELASTIC_UPPER_BOUND_STATUSES,
)


ASSESSMENT_SCOPE = "Only the listed calculation checks and supplied criteria are assessed."


@dataclass(frozen=True)
class _CheckDecision:
    status: Literal["pass", "fail", "indeterminate"]
    eligible: bool
    upper_bound_failure: bool = False


def check_decision(
    *,
    demand: float | None,
    capacity: float | None,
    applicability: str,
    required_margin: float,
    upper_bound: float | None = None,
    eligible: bool = True,
    status_at_target: str | None = None,
) -> _CheckDecision:
    """Apply the acceptance rules to a demand and capacity in a common unit.

    A producer's decision may be retained only at the same target. This keeps
    native and sizing decisions stable where division and multiplication round
    differently; every new target uses the direct capacity-demand comparison.
    """
    eligible = (
        eligible and applicability == "released"
        and demand is not None and demand >= 0.0
        and capacity is not None and capacity > 0.0
    )
    if eligible:
        assert demand is not None and capacity is not None
        status: Literal["pass", "fail"]
        if status_at_target == "pass":
            status = "pass"
        elif status_at_target == "fail":
            status = "fail"
        else:
            status = "pass" if demand * (1.0 + required_margin) <= capacity else "fail"
        return _CheckDecision(status, True)
    upper_bound_failure = (
        applicability in BUCKLING_ELASTIC_UPPER_BOUND_STATUSES
        and demand is not None and demand >= 0.0
        and upper_bound is not None and upper_bound >= 0.0
        and upper_bound < demand * (1.0 + required_margin)
    )
    return _CheckDecision(
        "fail" if upper_bound_failure else "indeterminate", False, upper_bound_failure,
    )


def summarize_checks(checks: Sequence[dict[str, Any]]) -> dict[str, Any]:
    """Combine evaluated checks; incomplete coverage has no governing check."""
    statuses = [check["status"] for check in checks]
    status = (
        "fail" if "fail" in statuses
        else "indeterminate" if not checks or "indeterminate" in statuses else "pass"
    )
    complete = bool(checks) and all(
        check["status"] != "indeterminate" and check["applicability"] == "released"
        and check.get("eligible", True)
        for check in checks
    )
    candidates = [check for check in checks if _number(check.get("margin")) is not None]
    governing = min(
        candidates, key=lambda check: check["margin"] - check["required_margin"],
    )["id"] if candidates and complete else None
    return {
        "status": status,
        "governing_check": governing,
        "required_check_coverage": {
            "required": [check["id"] for check in checks],
            "evaluated": [check["id"] for check in checks if check["status"] != "indeterminate"],
            "indeterminate": [check["id"] for check in checks if check["status"] == "indeterminate"],
            "complete": complete,
        },
    }


def _number(value: Any) -> float | None:
    if isinstance(value, dict):
        value = value.get("value")
    if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
        return float(value)
    return None


def _quantity(value: Any, unit: str = "MPa") -> dict[str, Any]:
    return {"value": _number(value), "unit": value.get("unit", unit) if isinstance(value, dict) else unit}


def _check(
    name: str, demand: Any, capacity: Any, margin: Any,
    applicability: str = "released", reasons: Sequence[str] = (),
    upper_bound: Any = None,
) -> dict[str, Any]:
    released = applicability == "released"
    check = {
        "id": name,
        "demand": _quantity(demand),
        "capacity": _quantity(capacity if released else None,
                              capacity.get("unit", "MPa") if isinstance(capacity, dict) else "MPa"),
        "margin": _number(margin) if released else None,
        "required_margin": 0.0,
        "applicability": applicability,
        "reasons": list(dict.fromkeys(reasons)),
    }
    if _number(upper_bound) is not None:
        check["upper_bound"] = _quantity(
            upper_bound,
            upper_bound.get("unit", "MPa") if isinstance(upper_bound, dict) else "MPa",
        )
    return check


def _smooth_buckling_elastic_upper_bound(result: dict[str, Any]) -> Any:
    if result.get("capacity_status") not in BUCKLING_ELASTIC_UPPER_BOUND_STATUSES:
        return None
    candidates = [
        candidate.get("correlated_critical_pressure_mpa")
        for candidate in result.get("candidates", [])
        if candidate.get("applicable")
        and _number(candidate.get("correlated_critical_pressure_mpa")) is not None
    ]
    return candidates[0] if len(candidates) == 1 else None


def _result_checks(payload: dict[str, Any]) -> list[dict[str, Any]]:
    if "assessment" in payload and "checks" in payload["assessment"]:
        return deepcopy(payload["assessment"]["checks"])
    if "selected_results" in payload:
        return [check for child in payload["selected_results"].values() for check in _result_checks(child)]
    result = payload.get("result", {})
    model = payload.get("model")
    pressure = result.get("external_pressure_mpa")
    strength = result.get("strength_mpa")
    if model == "tube":
        return [_check("cylindrical_shell_stress", result.get("governing_stress_mpa"), strength, result.get("margin"))]
    if model == "smooth-buckling":
        return [_check(
            "smooth_cylinder_buckling", pressure, result.get("correlated_critical_pressure_mpa"), result.get("margin"),
            applicability=result.get("capacity_status", "unavailable"),
            reasons=[
                *result.get("validity_violations", []),
                *result.get("release_gate_violations", []),
            ],
            upper_bound=_smooth_buckling_elastic_upper_bound(result),
        )]
    if model == "hemisphere":
        return [
            _check("hemisphere_stress", result.get("governing_stress_mpa"), strength, result.get("stress_margin")),
            _check("seat_bearing", result.get("seat_bearing_stress_mpa"), strength, result.get("seat_margin")),
            _check("hemisphere_buckling", pressure, result.get("released_buckling_pressure_mpa"), result.get("buckling_margin"),
                   applicability=result.get("buckling_capacity_status", "unavailable"),
                   reasons=result.get("buckling_validity_violations", []),
                   upper_bound=(
                       result.get("released_buckling_pressure_mpa")
                       if result.get("buckling_capacity_status")
                       == "released_unqualified_material"
                       else None
                   )),
        ]
    if model == "plate":
        checks = [_check(
            "flat_endcap_bending", result.get("governing_bending_stress_mpa"), strength, result.get("margin"),
            result.get("bending_status", "unavailable"), result.get("validity_violations", []),
        )]
        if _number(result.get("outside_radius_mm")) is not None:
            seat_strength = result.get("compressive_strength_mpa")
            if _number(seat_strength) is None:
                seat_strength = strength
            checks.append(_check("seat_bearing", result.get("seat_bearing_stress_mpa"), seat_strength, result.get("seat_margin")))
        maximum_deflection = payload.get("sizing", {}).get("maximum_deflection")
        if maximum_deflection is not None:
            checks.append(_check(
                "center_deflection", result.get("released_maximum_deflection_mm"), maximum_deflection,
                payload["sizing"].get("selected_check_margins", {}).get("center_deflection"),
                result.get("deflection_status", "unavailable"), result.get("deflection_validity_violations", []),
            ))
        return checks
    if model == "ring-shell":
        inter_ring_result = result.get("inter_ring_shell_buckling", {})
        inter_ring_status = inter_ring_result.get("capacity_status", "unavailable")
        parent_violations = result.get("validity_violations", [])
        if parent_violations:
            inter_ring_status = result.get(
                "capacity_status", "withheld_invalid_applicability"
            )
        elif inter_ring_status == "released":
            inter_ring_status = "advisory"
        elif inter_ring_status == "released_unqualified_material":
            inter_ring_status = "advisory_unqualified_material"
        elif inter_ring_status == "released_pending_plasticity":
            inter_ring_status = "advisory_pending_plasticity"
        inter_ring = _check(
            "inter_ring_shell_buckling",
            pressure,
            inter_ring_result.get("correlated_critical_pressure_mpa"),
            inter_ring_result.get("margin"),
            inter_ring_status,
            [
                *parent_violations,
                *inter_ring_result.get("validity_violations", []),
                *inter_ring_result.get("release_gate_violations", []),
                "Inter-ring buckling is advisory: ideal circular support at each ring "
                "center line is assumed; ring stiffness and attachment are not checked "
                "for that support.",
            ],
        )
        return [
            _check("ring_shell_global_buckling", pressure, None, None,
                   result.get("capacity_status", "unavailable"),
                   [*result.get("validity_violations", []), "Global ring-shell buckling is advisory: the long-cylinder transition and local failure modes are not covered."]),
            inter_ring,
        ]
    return []


def batch_entries(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
    if "sweep" in payload:
        points = list(payload["sweep"].get("points", []))
        conversion = payload["sweep"].get("depth_to_pressure")
        if not conversion:
            return points
        # Depth sweeps store shared load inputs beside the points in detailed
        # output. Carry them into each assessment so it can stand alone.
        entries = []
        for point in points:
            loading = {
                "input_mode": "depth",
                "depth": _quantity(_to_unit(QuantityInput.model_validate(point["depth"]), "m", "sweep.points.depth"), "m"),
                "pressure_reference": conversion["pressure_reference_convention"],
                **{key: conversion[key] for key in ("fluid_density", "gravity", "design_factor")},
                **{key: point[key] for key in ("service_external_pressure", "design_external_pressure")},
            }
            entries.append({**point, "response": {**point["response"], "loading": deepcopy(loading)}})
        return entries
    if "comparison" in payload:
        return list(payload["comparison"].get("entries", []))
    if "entries" in payload.get("assessment", {}):
        return [{**entry.get("context", {}), "response": {
                    "model": payload.get("model"), "assessment": entry,
                    **({"loading": entry["loading"]} if "loading" in entry else {}),
                }}
                for entry in payload["assessment"]["entries"]]
    return None


def entry_context(entry: dict[str, Any], index: int) -> dict[str, Any]:
    return {"index": index, **deepcopy({
        key: value for key, value in entry.items()
        if key not in {"response", "mass_properties", "structural_mass", "selected_geometry"}
    })}


def assess_response(
    payload: dict[str, Any], required_checks: Sequence[str] | None = None,
    minimum_margin: float = 0.0,
) -> dict[str, Any]:
    """Assess released checks against criteria; missing checks stay indeterminate.

    A known failing required check takes precedence over unavailable required
    checks. A non-released elastic upper bound may establish failure but never
    passage. Zero demand can pass a released finite capacity with a null margin.
    Existing sizing/assembly criteria remain in force when a lower structural
    margin is supplied; center deflection retains its explicit limit. A name
    absent from the response becomes an explicit unavailable check.
    """
    if _number(minimum_margin) is None or minimum_margin < 0:
        raise CalcCliError("invalid_request", "minimum_margin must be finite and nonnegative")
    if isinstance(required_checks, str) or (required_checks is not None and (
        not required_checks or any(not isinstance(name, str) or not name.strip() for name in required_checks)
    )):
        raise CalcCliError("invalid_request", "required_checks must be a non-empty sequence of check names")
    batch = batch_entries(payload)
    if batch is not None:
        assessments = []
        for index, entry in enumerate(batch):
            response = entry.get("response", {})
            assessment = assess_response(response, required_checks, minimum_margin)
            assessment["context"] = entry_context(entry, index)
            if "loading" in response:
                assessment["loading"] = deepcopy(response["loading"])
            assessments.append(assessment)
        statuses = [item["status"] for item in assessments]
        return {"status": "fail" if "fail" in statuses else "indeterminate" if not statuses or "indeterminate" in statuses else "pass",
                "scope": ASSESSMENT_SCOPE, "entries": assessments}
    sizing = payload.get("sizing", {})
    declared = sizing.get("declared_check_set")
    available = {check["id"]: check for check in _result_checks(payload)}
    required = list(dict.fromkeys(required_checks if required_checks is not None else declared or list(available)))
    check_targets = sizing.get("check_targets", {})
    checks: list[dict[str, Any]] = []
    for name in required:
        check = available.get(name, _check(name, None, None, None, "unavailable", ["Requested check is absent from this response."]))
        original_target = check.get("required_margin", 0.0)
        declared_target = check_targets.get(name, sizing.get("target_minimum_margin", original_target))
        structural_target = 0.0 if name.rsplit(".", 1)[-1] == "center_deflection" else minimum_margin
        target = max(structural_target, original_target, declared_target)
        check["required_margin"] = target
        demand, capacity = _number(check.get("demand")), _number(check.get("capacity"))
        upper_bound = _number(check.get("upper_bound"))
        released = check.get("applicability") == "released"
        status_at_target = None
        selected_margin = _number(sizing.get("selected_check_margins", {}).get(name))
        if check.get("status") in {"pass", "fail"} and target == original_target:
            status_at_target = check["status"]
        elif selected_margin is not None and target == declared_target:
            status_at_target = "pass" if selected_margin >= target else "fail"
        decision = check_decision(
            demand=demand, capacity=capacity,
            applicability=check.get("applicability", "unavailable"),
            required_margin=target, upper_bound=upper_bound,
            eligible=check.get("eligible", True), status_at_target=status_at_target,
        )
        check["eligible"] = decision.eligible
        check["status"] = decision.status
        reasons = list(check.get("reasons", []))
        if decision.eligible:
            margin = _number(check.get("margin"))
            if demand == 0 and margin is None:
                reasons.append("Zero demand; margin ratio is undefined, and the released capacity meets the criterion.")
        else:
            if not released:
                check["capacity"] = _quantity(None, check.get("capacity", {}).get("unit", "MPa"))
                check["margin"] = None
            if decision.upper_bound_failure:
                reasons.append(BUCKLING_ELASTIC_UPPER_BOUND_FAILURE_REASON)
            elif not reasons:
                reasons.append("A released demand and capacity are required to assess this check.")
        check["reasons"] = list(dict.fromkeys(reasons))
        checks.append(check)
    return {
        **summarize_checks(checks), "checks": checks,
        "scope": payload.get("assessment", {}).get("scope", ASSESSMENT_SCOPE),
        "omissions": payload.get("assessment", {}).get("omissions", []),
    }
