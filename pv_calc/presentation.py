"""Concise views of calculation responses, preserving per-check applicability.

These functions consume the public JSON-shaped response and never rerun a
kernel. Detailed responses remain the provenance record. Acceptance policy
lives in pv_calc.assessment; assess_response remains importable here.
"""

from __future__ import annotations

import csv
import io
from collections.abc import Sequence
from copy import deepcopy
from typing import Any

from pv_calc.assessment import (
    ASSESSMENT_SCOPE as ASSESSMENT_SCOPE,
    batch_entries,
    entry_context,
    _number,
    assess_response as assess_response,
)


CSV_FIELDS = (
    "index", "model", "operation", "material", "axis", "axis_value", "axis_unit",
    "outcome", "message", "depth_m", "design_factor", "service_external_pressure_mpa",
    "design_external_pressure_mpa", "fluid_density_kg_per_m3", "gravity_m_per_s2",
    "assessment", "scope", "omissions", "check", "status", "eligible", "demand", "demand_unit",
    "capacity", "capacity_unit", "upper_bound", "upper_bound_unit", "margin",
    "required_margin", "applicability",
    "reasons", "wall_thickness_mm", "plate_thickness_mm", "structural_air_mass_kg",
    "net_submerged_mass_kg",
)


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
    batch = batch_entries(payload)
    if batch is not None:
        entries = []
        for index, entry in enumerate(batch):
            context = entry_context(entry, index)
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
    # A valid ring record reports its yield pressures even when the bay leaves
    # the lowest buckling pressure unestablished; then ring_buckling says why.
    ring_governed = _number(result.get("advisory_governing_pressure_mpa")) is not None
    ring_unestablished = result.get("capacity_status") == "advisory" and not ring_governed
    if payload.get("model") == "ring-shell" and (ring_governed or ring_unestablished):
        summary["ring_buckling"] = deepcopy({key: result[key] for key in (
            "advisory_governing_pressure_mpa", "advisory_governing_mode", "advisory_governing_status",
        ) if key in result})
        if ring_unestablished:
            summary["ring_buckling"]["inter_ring_capacity_status"] = result.get(
                "inter_ring_shell_buckling", {}
            ).get("capacity_status")
        if result.get("advisory_governing_mode") == "global_eq64_with_eq91_ring_torsion":
            global_mode = result.get("global_with_ring_torsion", {})
            summary["ring_buckling"].update({key: global_mode[key] for key in (
                "critical_axial_half_waves_m", "critical_circumferential_lobes_n",
            ) if key in global_mode})
        summary["ring_yield"] = deepcopy({key: result[key] for key in (
            "shell_yield_between_rings_pressure_mpa", "ring_yield_pressure_mpa",
            "ring_first_yield_pressure_mpa",
        ) if key in result})
        location = (result.get("axisymmetric_stress") or {}).get("ring_maximum_hoop_stress_location")
        if location is not None:
            summary["ring_yield"]["ring_maximum_hoop_stress_location"] = location
        collapse = result.get("axisymmetric_collapse")
        if collapse is not None:
            summary["ring_collapse"] = deepcopy({key: collapse[key] for key in (
                "status", "collapse_pressure_mpa", "first_yield_pressure_mpa",
                "plastic_reserve_factor_phi3", "outer_midbay_bending_compressive",
            ) if key in collapse})
        bay = result.get("beam_column_bay")
        if bay is not None:
            summary["ring_bay_stress"] = deepcopy({
                f"{station}_{key}": bay[station][key]
                for station in ("midbay", "frame")
                for key in ("von_mises_outer_mpa", "von_mises_inner_mpa", "von_mises_membrane_mpa")
            })
    if "sizing" in payload:
        summary["sizing"] = {key: value for key, value in payload["sizing"].items() if key in {
            "selected_wall_thickness", "selected_plate_thickness", "selected_shell_mid_surface_radius",
            "selected_check_margins", "selected_minimum_margin", "selected_governing_check", "check_targets",
            "target_minimum_margin", "maximum_deflection", "solution_type", "selection_scope", "variable",
            "geometry_constraint", "selected_stock_thickness", "stock_thicknesses",
            "buckling_data_qualification",
        }}
    outputs = {}
    for prefix in ("displacement", "deflection"):
        if f"{prefix}_status" in result:
            outputs[prefix] = {"status": result[f"{prefix}_status"], "reasons": result.get(f"{prefix}_validity_violations", [])}
            if prefix == "deflection":
                outputs[prefix]["value"] = result.get("released_maximum_deflection_mm")
    if (
        payload.get("model") == "hemisphere"
        and result.get("buckling_capacity_status") == "released_unqualified_material"
    ):
        outputs["reference_buckling_estimate"] = {
            "status": result["buckling_capacity_status"],
            "value": deepcopy(result.get("released_buckling_pressure_mpa")),
            "reasons": list(result.get("buckling_validity_violations", [])),
        }
    if payload.get("model") == "cylinder":
        buckling = payload.get("components", {}).get("smooth_buckling", {}).get("result", {})
    elif payload.get("model") == "smooth-buckling":
        buckling = payload.get(
            "result",
            payload.get("selected_results", {}).get("smooth-buckling", {}).get("result", {}),
        )
    else:
        buckling = {}
    if buckling.get("capacity_status") == "released_pending_plasticity":
        outputs["elastic_buckling_estimate"] = {
            "status": buckling["capacity_status"],
            "value": deepcopy(buckling.get("correlated_critical_pressure_mpa")),
            "reasons": [],
        }
    elif buckling.get("capacity_status") == "released_unqualified_material":
        outputs["reference_buckling_estimate"] = {
            "status": buckling["capacity_status"],
            "value": deepcopy(buckling.get("correlated_critical_pressure_mpa")),
            "reasons": list(buckling.get("release_gate_violations", [])),
        }
    if outputs:
        summary["outputs"] = outputs
    mass = _mass_summary(payload)
    if mass:
        summary["mass_properties"] = mass
    return summary


_RING_MODE_LABELS = {
    "global_eq64_with_eq91_ring_torsion": "global, NASA SP-8007 Eq. 64 x 0.75",
    "inter_ring_smooth_shell": "inter-ring bay",
    "axisymmetric_collapse_lunchick": "axisymmetric collapse, Lunchick",
}
_RING_FIRST_YIELD_LABELS = {
    "internal_ring_free_edge": "inner free edge",
    "external_ring_base_at_shell": "ring base at the shell",
}
_RING_STATUS_LABELS = {
    "advisory_pending_plasticity": "elastic upper bound: stress exceeds the material limit",
    "advisory_plasticity_undetermined": "proportional limit not supplied",
    "advisory_unqualified_material": "reference-only material data",
}


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
    if "ring_buckling" in summary and "inter_ring_capacity_status" in summary["ring_buckling"]:
        lines.append(
            "Lowest buckling or collapse pressure: not established (inter-ring bay "
            f"{summary['ring_buckling']['inter_ring_capacity_status']})"
        )
    elif "ring_buckling" in summary:
        buckling = summary["ring_buckling"]
        detail = [_RING_MODE_LABELS.get(buckling.get("advisory_governing_mode"), str(buckling.get("advisory_governing_mode")))]
        if "critical_circumferential_lobes_n" in buckling:
            detail.append(f"m={buckling.get('critical_axial_half_waves_m')}, n={buckling['critical_circumferential_lobes_n']}")
        if buckling.get("advisory_governing_status") in _RING_STATUS_LABELS:
            detail.append(_RING_STATUS_LABELS[buckling["advisory_governing_status"]])
        lines.append(f"Lowest buckling or collapse pressure: {_format(buckling['advisory_governing_pressure_mpa'])} ({'; '.join(detail)})")
    if "ring_yield" in summary:
        shell_yield = summary["ring_yield"].get("shell_yield_between_rings_pressure_mpa")
        ring_yield = summary["ring_yield"].get("ring_yield_pressure_mpa")
        if _number(shell_yield) is None or _number(ring_yield) is None:
            lines.append("Mean hoop yield: not evaluated without a yield strength")
        else:
            lines.append(f"Shell mean hoop yield at mid-bay (Pc5): {_format(shell_yield)}")
            lines.append(f"Ring mean hoop yield: {_format(ring_yield)}")
            first_yield = summary["ring_yield"].get("ring_first_yield_pressure_mpa")
            if _number(first_yield) is not None:
                location = _RING_FIRST_YIELD_LABELS.get(
                    summary["ring_yield"].get("ring_maximum_hoop_stress_location"), "smallest radius"
                )
                lines.append(f"Ring first yield ({location}): {_format(first_yield)}")
    if "ring_collapse" in summary:
        collapse = summary["ring_collapse"]
        if _number(collapse.get("collapse_pressure_mpa")) is None:
            lines.append("Axisymmetric collapse: withheld (the periodic-bay closed form ends before first yield)")
        else:
            lines.append(
                f"Axisymmetric collapse (Lunchick, perfect shell): {_format(collapse['collapse_pressure_mpa'])}"
                f"; mid-bay outer-surface first yield {_format(collapse['first_yield_pressure_mpa'])}"
            )
    if "ring_bay_stress" in summary:
        bay = summary["ring_bay_stress"]
        lines.append(
            "Bay surface von Mises at the applied pressure: mid-bay outer "
            f"{_format(bay['midbay_von_mises_outer_mpa'])}, inner {_format(bay['midbay_von_mises_inner_mpa'])}, "
            f"membrane {_format(bay['midbay_von_mises_membrane_mpa'])}; frame outer "
            f"{_format(bay['frame_von_mises_outer_mpa'])}, inner {_format(bay['frame_von_mises_inner_mpa'])}"
        )
    check_reasons: set[str] = set()
    for check in assessment["checks"]:
        margin = "undefined" if check.get("margin") is None else _format(check["margin"])
        upper_bound = (
            f" | upper bound {_format(check['upper_bound'])}"
            if check.get("upper_bound") is not None
            else ""
        )
        lines.append(f"{check['id']}: {check['status'].upper()} | demand {_format(check['demand'])} | capacity {_format(check['capacity'])}{upper_bound} | margin {margin} (required {_format(check['required_margin'])})")
        lines.extend(f"  {reason}" for reason in check["reasons"])
        check_reasons.update(check["reasons"])
    for name, output in summary.get("outputs", {}).items():
        lines.append(f"{name}: {output['status']}" + (f" | {_format(output['value'])}" if output.get("value") is not None else ""))
        lines.extend(f"  {reason}" for reason in output["reasons"] if reason not in check_reasons)
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
                "upper_bound": check.get("upper_bound", {}).get("value"),
                "upper_bound_unit": check.get("upper_bound", {}).get("unit"),
                "margin": check["margin"], "required_margin": check["required_margin"],
                "applicability": check["applicability"], "reasons": " | ".join(check["reasons"]),
            })
    return output.getvalue()
