"""Concise views of calculation responses, preserving per-check applicability.

These functions consume the public JSON-shaped response and never rerun a
kernel. Detailed responses remain the provenance record. An assessment is
limited to explicitly listed calculation checks, not overall vessel safety.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from pv_calc.contracts import QuantityInput, _to_unit
from pv_calc.errors import CalcCliError


ASSESSMENT_SCOPE = "Only the listed calculation checks and supplied criteria are assessed."
CSV_FIELDS = (
    "index", "model", "operation", "material", "axis", "axis_value", "axis_unit",
    "outcome", "message", "depth_m", "design_factor", "service_external_pressure_mpa",
    "design_external_pressure_mpa", "fluid_density_kg_per_m3", "gravity_m_per_s2",
    "assessment", "scope", "omissions", "check", "status", "eligible", "demand", "demand_unit",
    "capacity", "capacity_unit", "margin", "required_margin", "applicability",
    "reasons", "wall_thickness_mm", "plate_thickness_mm", "structural_air_mass_kg",
    "net_submerged_mass_kg",
)


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
) -> dict[str, Any]:
    released = applicability == "released"
    return {
        "id": name,
        "demand": _quantity(demand),
        "capacity": _quantity(capacity if released else None,
                              capacity.get("unit", "MPa") if isinstance(capacity, dict) else "MPa"),
        "margin": _number(margin) if released else None,
        "required_margin": 0.0,
        "applicability": applicability,
        "reasons": list(dict.fromkeys(reasons)),
    }


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
            result.get("capacity_status", "unavailable"),
            [*result.get("validity_violations", []), *result.get("release_gate_violations", [])],
        )]
    if model == "hemisphere":
        return [
            _check("hemisphere_stress", result.get("governing_stress_mpa"), strength, result.get("stress_margin")),
            _check("seat_bearing", result.get("seat_bearing_stress_mpa"), strength, result.get("seat_margin")),
            _check("hemisphere_buckling", pressure, result.get("released_buckling_pressure_mpa"), result.get("buckling_margin"),
                   result.get("buckling_capacity_status", "unavailable"), result.get("buckling_validity_violations", [])),
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
        inter_ring = _result_checks({"model": "smooth-buckling", "result": result.get("inter_ring_shell_buckling", {})})[0]
        inter_ring["id"] = "inter_ring_shell_buckling"
        return [
            _check("ring_shell_global_buckling", pressure, None, None,
                   result.get("capacity_status", "unavailable"),
                   [*result.get("validity_violations", []), "Global ring-shell results are advisory; no released global capacity is available."]),
            inter_ring,
        ]
    return []


def _batch_entries(payload: dict[str, Any]) -> list[dict[str, Any]] | None:
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


def _entry_context(entry: dict[str, Any], index: int) -> dict[str, Any]:
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
    checks. Zero demand can pass a released finite capacity with a null margin.
    Existing sizing/assembly criteria remain in force when a lower structural
    margin is supplied; centre deflection retains its explicit limit. A name absent from the response becomes an explicit
    unavailable check, which is useful for scripted requirements.
    """
    if _number(minimum_margin) is None or minimum_margin < 0:
        raise CalcCliError("invalid_request", "minimum_margin must be finite and nonnegative")
    if isinstance(required_checks, str) or (required_checks is not None and (
        not required_checks or any(not isinstance(name, str) or not name.strip() for name in required_checks)
    )):
        raise CalcCliError("invalid_request", "required_checks must be a non-empty sequence of check names")
    batch = _batch_entries(payload)
    if batch is not None:
        assessments = []
        for index, entry in enumerate(batch):
            response = entry.get("response", {})
            assessment = assess_response(response, required_checks, minimum_margin)
            assessment["context"] = _entry_context(entry, index)
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
        released = check.get("applicability") == "released"
        eligible = released and check.get("eligible", True) and demand is not None and demand >= 0 and capacity is not None and capacity > 0
        check["eligible"] = bool(eligible)
        reasons = list(check.get("reasons", []))
        if eligible:
            assert demand is not None and capacity is not None
            # Retain a native assessment/solver decision at its own criterion:
            # C / D - 1 and C >= D * (1 + target) may round oppositely at an
            # exact boundary. New criteria use the direct capacity comparison,
            # which is also defined at zero demand. No tolerance is introduced.
            margin = _number(check.get("margin"))
            selected_margin = _number(sizing.get("selected_check_margins", {}).get(name))
            if check.get("status") in {"pass", "fail"} and target == original_target:
                passes = check["status"] == "pass"
            elif selected_margin is not None and target == declared_target:
                passes = selected_margin >= target
            else:
                passes = demand * (1.0 + target) <= capacity
            check["status"] = "pass" if passes else "fail"
            if demand == 0 and margin is None:
                reasons.append("Zero demand; margin ratio is undefined, and the released capacity meets the criterion.")
        else:
            check["status"] = "indeterminate"
            if not released:
                check["capacity"] = _quantity(None, check.get("capacity", {}).get("unit", "MPa"))
                check["margin"] = None
            if not reasons:
                reasons.append("A released demand and capacity are required to assess this check.")
        check["reasons"] = list(dict.fromkeys(reasons))
        checks.append(check)
    statuses = [check["status"] for check in checks]
    status = "fail" if "fail" in statuses else "indeterminate" if not checks or "indeterminate" in statuses else "pass"
    complete = bool(checks) and all(check["eligible"] for check in checks)
    finite_checks = [check for check in checks if check["eligible"] and _number(check.get("margin")) is not None]
    governing = min(finite_checks, key=lambda check: check["margin"] - check["required_margin"])["id"] if finite_checks and complete else None
    return {
        "status": status, "checks": checks, "governing_check": governing,
        "required_check_coverage": {
            "required": required, "evaluated": [check["id"] for check in checks if check["eligible"]],
            "indeterminate": [check["id"] for check in checks if check["status"] == "indeterminate"], "complete": complete,
        },
        "scope": payload.get("assessment", {}).get("scope", ASSESSMENT_SCOPE),
        "omissions": payload.get("assessment", {}).get("omissions", []),
    }


def _mass_summary(payload: dict[str, Any]) -> dict[str, Any]:
    mass = payload.get("mass_properties", payload if payload.get("model") == "mass-properties" else {})
    result = mass.get("result", mass)
    summary = {key: result[key] for key in (
        "structural_air_mass_kg", "displaced_fluid_mass_kg", "net_submerged_mass_kg", "buoyant_force_n",
        "solid_volume_m3", "displaced_volume_m3", "payload_mass_kg", "total_air_mass_kg", "payload_volume_m3",
    ) if key in result}
    for source, name in {
        "structural_mass": "structural_air_mass_kg", "total_air_mass": "total_air_mass_kg",
        "payload_mass": "payload_mass_kg", "payload_volume": "payload_volume_m3",
        "solid_volume": "solid_volume_m3", "displaced_volume": "displaced_volume_m3",
        "internal_geometric_volume": "internal_geometric_volume_m3",
        "remaining_internal_volume": "remaining_internal_volume_m3",
        "displaced_fluid_mass": "displaced_fluid_mass_kg", "buoyant_force": "buoyant_force_n",
        "net_submerged_mass": "net_submerged_mass_kg",
    }.items():
        if source in result:
            summary[name] = result[source]
    for key in ("status", "reasons", "volume_basis"):
        if key in mass:
            summary[key] = mass[key]
    return summary


def summarize_response(
    payload: dict[str, Any], checks: Sequence[str] | None = None,
    minimum_margin: float = 0.0,
) -> dict[str, Any]:
    """Return a compact, unit-bearing response with check status and reasons."""
    summary: dict[str, Any] = {key: payload[key] for key in ("schema_version", "model", "operation") if key in payload}
    batch = _batch_entries(payload)
    if batch is not None:
        entries = []
        for index, entry in enumerate(batch):
            context = _entry_context(entry, index)
            child = summarize_response(entry.get("response", {}), checks, minimum_margin)
            if "mass_properties" in entry:
                child["mass_properties"] = _mass_summary(entry)
            if "structural_mass" in entry:
                child["structural_mass"] = deepcopy(entry["structural_mass"])
                if entry["structural_mass"].get("status") == "available":
                    child.setdefault("mass_properties", {})["structural_air_mass_kg"] = entry["structural_mass"]["mass"]
            if "selected_geometry" in entry:
                child["selected_geometry"] = deepcopy(entry["selected_geometry"])
            entries.append({**context, "summary": child})
        summary["entries"] = entries
        summary["assessment"] = {key: value for key, value in assess_response(payload, checks, minimum_margin).items() if key != "entries"}
        return summary
    result = payload.get("result", {})
    if not result and "selected_results" in payload:
        result = payload["selected_results"].get("tube", next(iter(payload["selected_results"].values()), {})).get("result", {})
    if not result and "components" in payload:
        result = payload["components"].get("tube", {}).get("result", {})
    geometry = payload.get("geometry", {key: result[key] for key in (
        "internal_radius_mm", "external_radius_mm", "wall_thickness_mm", "shell_mid_surface_radius_mm",
        "unsupported_length_mm", "axial_length_mm", "free_radius_mm", "outside_radius_mm", "plate_thickness_mm",
    ) if key in result and _number(result[key]) is not None})
    if geometry:
        summary["geometry"] = deepcopy(geometry)
    pressure = result.get("external_pressure_mpa")
    if pressure is not None:
        summary["external_pressure"] = deepcopy(pressure)
    elif "load_case" in payload:
        summary["load_case"] = deepcopy(payload["load_case"])
    if "loading" in payload:
        summary["loading"] = deepcopy({key: payload["loading"][key] for key in (
            "input_mode", "depth", "fluid_density", "gravity", "design_factor",
            "pressure_reference", "service_external_pressure", "design_external_pressure",
        ) if key in payload["loading"]})
    material = payload.get("material", payload.get("components", {}).get("tube", {}).get("material", {}))
    if material:
        summary["material"] = {key: value for key, value in material.get("source", material).items() if key in {"name", "type", "database"}}
    summary["assessment"] = assess_response(payload, checks, minimum_margin)
    if "sizing" in payload:
        summary["sizing"] = {key: value for key, value in payload["sizing"].items() if key in {
            "selected_wall_thickness", "selected_plate_thickness", "selected_shell_mid_surface_radius",
            "selected_check_margins", "selected_minimum_margin", "selected_governing_check", "check_targets",
            "target_minimum_margin", "maximum_deflection", "solution_type", "selection_scope", "variable",
            "geometry_constraint", "selected_stock_thickness", "stock_thicknesses",
        }}
    outputs = {}
    for prefix in ("displacement", "deflection"):
        if f"{prefix}_status" in result:
            outputs[prefix] = {"status": result[f"{prefix}_status"], "reasons": result.get(f"{prefix}_validity_violations", [])}
            if prefix == "deflection":
                outputs[prefix]["value"] = result.get("released_maximum_deflection_mm")
    if outputs:
        summary["outputs"] = outputs
    mass = _mass_summary(payload)
    if mass:
        summary["mass_properties"] = mass
    return summary


def _format(value: Any) -> str:
    if isinstance(value, dict) and "unit" in value:
        number = _number(value)
        return "unavailable" if number is None else f"{number:.6g} {value['unit']}"
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def render_text(payload: dict[str, Any]) -> str:
    """Render concise human-readable results without changing detailed JSON."""
    summary = summarize_response(payload)
    if "entries" in summary:
        label = f"{summary.get('model', 'calculation')} {summary.get('operation', '')}".strip()
        lines = [f"{label}: {summary['assessment']['status'].upper()}"]
        for entry in summary["entries"]:
            context = ", ".join(f"{key}={_format(value)}" for key, value in entry.items() if key not in {"summary", "index", "details"})
            lines.append(f"[{entry['index']}] {context}")
            lines.extend(f"  {line}" for line in _render_summary(entry["summary"]))
        return "\n".join(lines)
    return "\n".join(_render_summary(summary))


def _render_summary(summary: dict[str, Any]) -> list[str]:
    assessment = summary["assessment"]
    lines = [f"{summary.get('model', 'calculation')} {summary.get('operation', '')}: {assessment['status'].upper()}".replace(" :", ":")]
    if summary.get("material", {}).get("name"):
        lines.append(f"Material: {summary['material']['name']}")
    for key in ("geometry",):
        if summary.get(key):
            lines.append(f"{key.replace('_', ' ').capitalize()}: " + "; ".join(
                f"{name}={_format(value)}" for name, value in summary[key].items()
                if isinstance(value, dict) and "unit" in value
            ))
    if "external_pressure" in summary:
        lines.append(f"External pressure: {_format(summary['external_pressure'])}")
    if "loading" in summary:
        loading = summary["loading"]
        lines.append("Depth load: " + "; ".join(f"{label} {_format(loading[key])}" for key, label in (
            ("depth", "depth"), ("design_factor", "factor"),
            ("service_external_pressure", "service pressure"), ("design_external_pressure", "design pressure"),
        ) if key in loading))
    for check in assessment["checks"]:
        margin = "undefined" if check.get("margin") is None else _format(check["margin"])
        lines.append(f"{check['id']}: {check['status'].upper()} | demand {_format(check['demand'])} | capacity {_format(check['capacity'])} | margin {margin} (required {_format(check['required_margin'])})")
        lines.extend(f"  {reason}" for reason in check["reasons"])
    for name, output in summary.get("outputs", {}).items():
        lines.append(f"{name}: {output['status']}" + (f" | {_format(output['value'])}" if output.get("value") is not None else ""))
        lines.extend(f"  {reason}" for reason in output["reasons"])
    if assessment.get("governing_check"):
        lines.append(f"Governing check: {assessment['governing_check']}")
    mass = summary.get("mass_properties", {})
    displayed_mass = {name: mass[name] for name in (
        "structural_air_mass_kg", "payload_mass_kg", "total_air_mass_kg", "net_submerged_mass_kg",
        "remaining_internal_volume_m3", "buoyant_force_n",
    ) if name in mass}
    if displayed_mass:
        lines.append("Mass properties: " + "; ".join(f"{name}={_format(value)}" for name, value in displayed_mass.items()))
    lines.extend(f"  {reason}" for reason in mass.get("reasons", []))
    if summary.get("model") == "cylinder" and mass:
        lines.append("Mass uses idealized component volumes; joint hardware is excluded.")
        if any("no closure geometry" in omission for omission in assessment.get("omissions", [])):
            lines.append("No closures supplied: mass covers the tube with massless end planes.")
    elif mass.get("volume_basis"):
        lines.append(f"Volume basis: {mass['volume_basis']}")
    if summary.get("structural_mass", {}).get("status") == "unavailable":
        lines.append("Structural mass: unavailable; " + summary["structural_mass"].get("reason", "material density is unavailable"))
    if not assessment["checks"]:
        lines.append("No acceptance checks are available in this response.")
    lines.append(assessment["scope"])
    if assessment.get("omissions"):
        lines.append("Omitted: " + " ".join(assessment["omissions"]))
    return lines


def render_csv(payload: dict[str, Any]) -> str:
    """Render one row per check and point, with stable units and no JSON cells."""
    summary = summarize_response(payload)
    entries = summary.get("entries", [{"index": 0, "summary": summary}])
    output = io.StringIO(newline="")
    writer = csv.DictWriter(output, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for entry in entries:
        child = entry["summary"]
        axis = next((key for key, value in entry.items() if isinstance(value, dict) and "unit" in value), "")
        quantity = entry.get(axis, {})
        geometry = child.get("geometry", {})
        mass = child.get("mass_properties", {})
        loading = child.get("loading", {})
        common = {
            "index": entry["index"], "model": child.get("model", summary.get("model", "")),
            "operation": summary.get("operation", "forward"),
            "material": entry.get("material", child.get("material", {}).get("name", "")),
            "axis": axis, "axis_value": quantity.get("value", ""), "axis_unit": quantity.get("unit", ""),
            "outcome": entry.get("outcome", ""), "message": entry.get("message", ""),
            "depth_m": _number(loading.get("depth")),
            "design_factor": _number(loading.get("design_factor")),
            "service_external_pressure_mpa": _number(loading.get("service_external_pressure")),
            "design_external_pressure_mpa": _number(loading.get("design_external_pressure")),
            "fluid_density_kg_per_m3": _number(loading.get("fluid_density")),
            "gravity_m_per_s2": _number(loading.get("gravity")),
            "assessment": child["assessment"]["status"],
            "scope": child["assessment"]["scope"],
            "omissions": " | ".join(child["assessment"].get("omissions", [])),
            "wall_thickness_mm": _number(geometry.get("wall_thickness_mm", geometry.get("wall_thickness"))),
            "plate_thickness_mm": _number(geometry.get("plate_thickness_mm", geometry.get("plate_thickness"))),
            "structural_air_mass_kg": _number(mass.get("structural_air_mass_kg")),
            "net_submerged_mass_kg": _number(mass.get("net_submerged_mass_kg")),
        }
        if not child["assessment"]["checks"]:
            writer.writerow({**common, "status": "indeterminate", "eligible": False, "reasons": entry.get("message", "No acceptance checks are available in this response.")})
        for check in child["assessment"]["checks"]:
            writer.writerow({
                **common, "check": check["id"], "status": check["status"], "eligible": check["eligible"],
                "demand": check["demand"].get("value"), "demand_unit": check["demand"].get("unit"),
                "capacity": check["capacity"].get("value"), "capacity_unit": check["capacity"].get("unit"),
                "margin": check["margin"], "required_margin": check["required_margin"],
                "applicability": check["applicability"], "reasons": " | ".join(check["reasons"]),
            })
    return output.getvalue()
