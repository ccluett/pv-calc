"""Concise views of calculation responses, preserving per-check applicability.

These functions consume the public JSON-shaped response and never rerun a
kernel. Detailed responses remain the provenance record. Acceptance policy
lives in pv_calc.assessment; assess_response remains importable here.
"""

from __future__ import annotations

import csv
import io
import math
from collections.abc import Sequence
from copy import deepcopy
from functools import cache
from typing import Any

from pv_calc.assessment import (
    ASSESSMENT_SCOPE as ASSESSMENT_SCOPE,
    batch_entries,
    entry_context,
    _number,
    assess_response as assess_response,
)
from pv_calc.errors import CalcCliError
from pv_calc.pressure_vessel import BUCKLING_REFERENCE_ONLY_REASON
from pv_calc.units import Q_, UNIT_EVALUATION_ERRORS


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
        # Every candidate is compared on the record's data, so reference-only
        # data mark the minimum whichever mode governs it.
        if result.get("buckling_data_qualification") == "reference_only":
            summary["ring_buckling"]["buckling_data_qualification"] = "reference_only"
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
        if "ring_location" in result:
            summary["ring_yield"]["ring_location"] = result["ring_location"]
        collapse = result.get("axisymmetric_collapse")
        if collapse is not None:
            summary["ring_collapse"] = deepcopy({key: collapse[key] for key in (
                "status", "collapse_pressure_mpa", "first_yield_pressure_mpa",
                "plastic_reserve_factor_phi3", "outer_midbay_bending_compressive",
            ) if key in collapse})
        bay = result.get("beam_column_bay")
        if bay is not None:
            summary["ring_bay_stress"] = deepcopy({
                **{
                    f"{station}_{key}": bay[station][key]
                    for station in ("midbay", "frame")
                    for key in ("von_mises_outer_mpa", "von_mises_inner_mpa")
                },
                "midbay_von_mises_membrane_mpa": bay["midbay_von_mises_membrane_mpa"],
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


UNIT_SYSTEMS = ("si", "us")
# Text output converts every quantity to one unit per dimension. Depth is a
# length with its own unit, so it is converted only where it is labelled.
_DISPLAY_UNITS = {
    "si": {"pressure": "MPa", "length": "mm", "depth": "m", "mass": "kg", "volume": "L", "force": "N",
           "density": "kg/m^3"},
    "us": {"pressure": "psi", "length": "in", "depth": "ft", "mass": "lb", "volume": "in^3", "force": "lbf",
           "density": "lb/in^3"},
}
_PINT_NAMES = {
    "in": "inch", "ft": "foot", "lb": "pound", "in^3": "inch**3", "lbf": "force_pound", "L": "liter",
    "lb/in^3": "pound/inch**3",
}
_REFERENCE_UNITS = {
    "pressure": "MPa", "length": "mm", "mass": "kg", "volume": "m**3", "force": "N", "density": "kg/m**3",
}
_GEOMETRY_LABELS = {
    "internal_radius": "internal radius", "external_radius": "external radius",
    "wall_thickness": "wall", "shell_mid_surface_radius": "mid-surface radius",
    "unsupported_length": "unsupported length", "axial_length": "axial length",
    "free_radius": "free radius", "outside_radius": "outside radius",
    "plate_thickness": "thickness",
}
_REFERENCE_ONLY = "reference-only material data"
_RING_STATUS_LABELS = {
    "advisory_pending_plasticity": "elastic upper bound: stress exceeds the material limit",
    "advisory_plasticity_undetermined": "proportional limit not supplied",
    "advisory_unqualified_material": _REFERENCE_ONLY,
}
_RING_FIRST_YIELD_LABELS = {"internal": "inner free edge", "external": "ring base at the shell"}
# Below this, the plasticity correction moves the elastic pressure by more than
# half a percent and the report shows both.
_PLASTICITY_SHOWN_BELOW = 0.995


@cache
def _dimension(unit: str) -> str | None:
    try:
        dimensionality = Q_(1.0, unit).dimensionality
        for name, reference in _REFERENCE_UNITS.items():
            if Q_(1.0, reference).dimensionality == dimensionality:
                return name
    except UNIT_EVALUATION_ERRORS:
        pass
    return None


def _converted(quantity: Any, units: str, kind: str | None = None) -> tuple[float | None, str]:
    value = _number(quantity)
    unit = quantity.get("unit", "") if isinstance(quantity, dict) else ""
    dimension = _dimension(unit) if unit else None
    if value is None or dimension is None:
        return value, unit
    target = _DISPLAY_UNITS[units]["depth" if kind == "depth" and dimension == "length" else dimension]
    if target != unit:
        value = Q_(value, unit).to(_PINT_NAMES.get(target, target)).magnitude
    return value, target


def _num(value: float) -> str:
    """Four significant figures, without exponents in the usual range."""
    magnitude = abs(value)
    if magnitude == 0.0:
        return "0"
    if 1e-4 <= magnitude:
        text = f"{value:.4g}"
        if "e" not in text:
            return text
        return f"{round(value, 3 - math.floor(math.log10(magnitude))):,.0f}"
    return f"{value:.3e}"


def _qty(quantity: Any, units: str, kind: str | None = None) -> str:
    value, unit = _converted(quantity, units, kind)
    return "n/a" if value is None else f"{_num(value)} {unit}"


def _margin(value: Any) -> str:
    margin = _number(value)
    if margin is None:
        return "n/a"
    # A sizing solution meets its target to bisection tolerance.
    return f"{0.0 if abs(margin) < 5e-4 else margin:.3f}"


def _table(rows: Sequence[Sequence[str]]) -> list[str]:
    if not rows:
        return []
    widths = [max(len(row[column]) for row in rows) for column in range(len(rows[0]))]
    return ["  ".join(cell.ljust(width) for cell, width in zip(row, widths)).rstrip() for row in rows]


def _material_name(record: Any) -> str | None:
    if not isinstance(record, dict):
        return None
    return record.get("source", record).get("name")


def _material_line(payload: dict[str, Any], summary: dict[str, Any]) -> str | None:
    if payload.get("model") == "cylinder" and "components" in payload:
        components = payload["components"]
        names = [("tube", _material_name(components.get("tube", {}).get("material")))]
        names += [(item.get("id", "closure"), _material_name(item.get("material"))) for item in components.get("closures", [])]
        distinct = {name for _, name in names if name}
        if len(distinct) > 1:
            return "Materials: " + "; ".join(f"{part} {name}" for part, name in names if name)
        if distinct:
            return f"Material: {distinct.pop()}"
    name = summary.get("material", {}).get("name")
    return f"Material: {name}" if name else None


def _geometry_line(payload: dict[str, Any], summary: dict[str, Any], units: str) -> str | None:
    parts = _geometry_parts(payload, summary, units)
    return "Geometry: " + ", ".join(parts) if parts else None


def _geometry_parts(payload: dict[str, Any], summary: dict[str, Any], units: str) -> list[str]:
    items = {
        key.removesuffix("_mm"): value for key, value in summary.get("geometry", {}).items()
        if isinstance(value, dict) and "unit" in value
    }
    if "internal_radius" in items:
        items.pop("shell_mid_surface_radius", None)
    if _number(items.get("axial_length")) == _number(items.get("unsupported_length")):
        items.pop("axial_length", None)
    parts = [f"{_GEOMETRY_LABELS.get(key, key.replace('_', ' '))} {_qty(value, units)}" for key, value in items.items()]
    result = payload.get("result", {})
    if payload.get("model") == "ring-shell" and _number(result.get("ring_spacing_mm")) is not None:
        parts.append(
            f"{result.get('ring_location', '')} rings {_qty(result.get('ring_axial_width_mm'), units)} axial"
            f" x {_qty(result.get('ring_radial_height_mm'), units)} radial"
            f" at {_qty(result.get('ring_spacing_mm'), units)} spacing".lstrip()
        )
    return parts


def _pressure_line(summary: dict[str, Any], units: str) -> str | None:
    loading = summary.get("loading", {})
    if "depth" in loading:
        return (
            f"Pressure: {_qty(loading.get('design_external_pressure'), units)} design "
            f"({_qty(loading['depth'], units, 'depth')} depth, "
            f"{_qty(loading.get('service_external_pressure'), units)} service x "
            f"{_num(_number(loading.get('design_factor')) or 0.0)})"
        )
    if "external_pressure" in summary:
        return f"Pressure: {_qty(summary['external_pressure'], units)}"
    return None


def _kernel_result(payload: dict[str, Any], check_id: str) -> dict[str, Any] | None:
    """The kernel result behind a buckling check, wherever the response keeps it."""
    model = payload.get("model")
    if model == "cylinder":
        components = payload.get("components", {})
        if check_id == "smooth_cylinder_buckling":
            return components.get("smooth_buckling", {}).get("result")
        closure, _, name = check_id.partition(".")
        if name == "hemisphere_buckling":
            for item in components.get("closures", []):
                if item.get("id") == closure:
                    return item.get("result")
        return None
    if check_id == "smooth_cylinder_buckling" and model == "smooth-buckling":
        return payload.get("result") or payload.get("selected_results", {}).get("smooth-buckling", {}).get("result")
    if check_id == "hemisphere_buckling" and model == "hemisphere":
        return payload.get("result")
    return None


def _elastic_pressure(result: dict[str, Any]) -> Any:
    values = [
        candidate.get("correlated_critical_pressure_mpa") for candidate in result.get("candidates", [])
        if candidate.get("applicable") and _number(candidate.get("correlated_critical_pressure_mpa")) is not None
    ]
    return values[0] if len(values) == 1 else None


def _buckling_detail(result: dict[str, Any], hemisphere: bool, units: str) -> dict[str, Any]:
    """A reference-only estimate, and the elastic pressure behind a buckling value.

    Reference-only estimates keep their numerical margin for preliminary
    sizing but never become acceptance capacities. A plasticity factor shows
    how far the corrected pressure sits below the elastic one.
    """
    detail: dict[str, Any] = {"estimate": None, "margin": None, "notes": []}
    if hemisphere:
        status = result.get("buckling_capacity_status")
        if status == "released_unqualified_material":
            detail.update(estimate=result.get("released_buckling_pressure_mpa"), margin=result.get("buckling_margin"))
            detail["notes"].append(_REFERENCE_ONLY)
        elif (
            status != "released"
            and _number(result.get("nasa_candidate_design_pressure_mpa")) is not None
            and (_number(result.get("mean_radius_over_thickness")) or 0.0)
            > (_number(result.get("thin_wall_threshold_mean_radius_over_thickness")) or math.inf)
        ):
            detail["notes"].append(f"elastic upper bound {_qty(result['nasa_candidate_design_pressure_mpa'], units)}")
        return detail
    status = result.get("capacity_status")
    if status == "released_pending_plasticity":
        detail["notes"].append(f"elastic upper bound {_qty(result.get('correlated_critical_pressure_mpa'), units)}")
        return detail
    if status == "released_unqualified_material":
        detail.update(estimate=result.get("correlated_critical_pressure_mpa"), margin=result.get("margin"))
        detail["notes"].append(_REFERENCE_ONLY)
    factor = _number(result.get("plasticity_factor"))
    elastic = _elastic_pressure(result)
    if status in {"released", "released_unqualified_material"} and factor is not None \
            and factor < _PLASTICITY_SHOWN_BELOW and elastic is not None:
        detail["notes"].append(f"elastic {_qty(elastic, units)} x plasticity factor {factor:.3f}")
    return detail


def _check_basis(model: str | None, check: dict[str, Any]) -> str:
    unit = check.get("demand", {}).get("unit") or check.get("capacity", {}).get("unit", "")
    if _dimension(unit) == "length":
        return "deflection"
    # The cylinder composition and ring model compare pressures throughout; the
    # single-component kernels compare stress with strength.
    if model in {"cylinder", "ring-shell"} or check["id"].endswith("buckling"):
        return "pressure"
    return "stress"


def _check_view(payload: dict[str, Any], check: dict[str, Any], units: str) -> dict[str, Any]:
    capacity, margin = check.get("capacity"), check.get("margin")
    notes: list[str] = []
    reasons = list(check.get("reasons", []))
    result = _kernel_result(payload, check["id"])
    if result:
        detail = _buckling_detail(result, check["id"].endswith("hemisphere_buckling"), units)
        if _number(capacity) is None and _number(detail["estimate"]) is not None:
            capacity, margin = detail["estimate"], detail["margin"]
        notes = detail["notes"]
        if _REFERENCE_ONLY in notes:
            reasons = [reason for reason in reasons if reason != BUCKLING_REFERENCE_ONLY_REASON]
    demand_value, unit = _converted(check.get("demand"), units)
    capacity_value, capacity_unit = _converted(capacity, units)
    unit = unit or capacity_unit
    required = _number(check.get("required_margin")) or 0.0
    return {
        "id": check["id"], "status": check["status"].upper(),
        "basis": _check_basis(payload.get("model"), check),
        "demand": "n/a" if demand_value is None else _num(demand_value),
        "capacity": "n/a" if capacity_value is None else _num(capacity_value),
        "unit": unit, "margin": _margin(margin), "margin_value": _number(margin),
        "required": f" (required {_num(required)})" if required else "",
        "notes": notes, "reasons": reasons,
    }


def _pair(view: dict[str, Any]) -> str:
    if view["capacity"] == "n/a":
        return f"{view['demand']} {view['unit']} / n/a"
    return f"{view['demand']} / {view['capacity']} {view['unit']}"


def _check_lines(payload: dict[str, Any], checks: Sequence[dict[str, Any]], units: str, shown: set[str]) -> list[str]:
    views = [_check_view(payload, check, units) for check in checks]
    rows = _table([
        [view["id"], view["status"], f"{view['basis']} {_pair(view)}", f"margin {view['margin']}{view['required']}"]
        for view in views
    ])
    lines: list[str] = []
    for row, view in zip(rows, views):
        lines.append(row)
        if view["notes"]:
            lines.append("  " + "; ".join(view["notes"]))
        for reason in view["reasons"]:
            if reason not in shown:
                shown.add(reason)
                lines.append(f"  {reason}")
    return lines


def _displacement_lines(payload: dict[str, Any], units: str, shown: set[str]) -> list[str]:
    model = payload.get("model")
    if model in {"tube", "hemisphere", "plate"}:
        result = payload.get("result", {})
    elif model == "cylinder":
        result = payload.get("components", {}).get("tube", {}).get("result", {})
    elif model == "smooth-buckling":
        result = payload.get("selected_results", {}).get("tube", {}).get("result", {})
    else:
        return []
    if model == "plate":
        status, reasons = result.get("deflection_status"), result.get("deflection_validity_violations", [])
        value = result.get("released_maximum_deflection_mm")
        line = f"Deflection: {_qty(value, units)} at centre" if _number(value) is not None else None
        label = "Deflection"
    else:
        status, reasons = result.get("displacement_status"), result.get("displacement_validity_violations", [])
        states = {state.get("radius_convention"): state for state in result.get("stress_states", [])}
        radial = [
            f"{_qty(states[side]['radial_displacement_mm'], units)} {name}"
            for side, name in (("internal", "inner"), ("external", "outer"))
            if side in states and _number(states[side].get("radial_displacement_mm")) is not None
        ]
        line = None
        if radial and status in {"released", "elastic_estimate_material_limit"}:
            line = "Displacement: radial " + ", ".join(radial)
            if _number(result.get("axial_length_change_mm")) is not None:
                line += (f"; axial {_qty(result['axial_length_change_mm'], units)}"
                         f" over {_qty(result.get('axial_length_mm'), units)}")
            elif _number(result.get("axial_strain")) is not None:
                line += f"; axial strain {_num(result['axial_strain'])}"
        label = "Displacement"
    if status is None:
        return []
    if status == "withheld_missing_elastic_properties":
        missing = [reason.split(" is required", 1)[0] for reason in reasons if " is required" in reason]
        if missing:
            return [f"{label}: not calculated (needs {', '.join(missing)})"]
    if line is None:
        line = f"{label}: withheld"
    elif status == "elastic_estimate_material_limit":
        line += " (elastic estimate)"
    lines = [line]
    for reason in reasons:
        if reason not in shown:
            shown.add(reason)
            lines.append(f"  {reason}")
    return lines


def _mass_line(summary: dict[str, Any], payload: dict[str, Any], units: str) -> str | None:
    mass = summary.get("mass_properties", {})
    if not mass:
        return None
    structure = mass.get("structural_air_mass_kg")
    total = mass.get("total_air_mass_kg", structure)
    payload_mass = _number(mass.get("payload_mass_kg")) or 0.0
    parts: list[str] = []
    if _number(total) is None:
        reasons = [reason[:1].lower() + reason[1:].rstrip(".") for reason in mass.get("reasons", [])]
        parts.append("unavailable" + (f" ({'; '.join(reasons)})" if reasons else ""))
    else:
        air = f"{_qty(total, units)} in air"
        if payload_mass > 0.0:
            air += f" ({_qty(structure, units)} structure + {_qty(mass.get('payload_mass_kg'), units)} payload)"
        parts.append(air)
    if _number(mass.get("displaced_fluid_mass_kg")) is not None:
        parts.append(f"displaces {_qty(mass['displaced_fluid_mass_kg'], units)}")
    net = _number(mass.get("net_submerged_mass_kg"))
    if net is not None:
        state = "buoyant" if net < 0 else "sinks" if net > 0 else "neutral"
        parts.append(f"net {_qty(mass['net_submerged_mass_kg'], units)} ({state})")
    if _number(mass.get("remaining_internal_volume_m3")) is not None:
        parts.append(f"free volume {_qty(mass['remaining_internal_volume_m3'], units)}")
    basis = mass.get("volume_basis")
    if basis and payload.get("model") != "cylinder":
        parts.append(basis.split(":", 1)[0].split(",", 1)[0])
    return "Mass: " + "; ".join(parts)


def _ring_lines(result: dict[str, Any], checks: Sequence[dict[str, Any]], units: str, shown: set[str]) -> list[str]:
    demand = _number(result.get("external_pressure_mpa"))
    governing = result.get("advisory_governing_mode")
    governing_notes = [
        label for label in (
            _RING_STATUS_LABELS.get(result.get("advisory_governing_status", "")),
            # Every mode is compared on the record's data, so reference-only
            # data mark the minimum whichever mode governs.
            _REFERENCE_ONLY if result.get("buckling_data_qualification") == "reference_only" else None,
        ) if label
    ]

    def row(label: str, pressure: Any, notes: list[str], mode: str | None = None) -> list[str]:
        value = _number(pressure)
        margin = value / demand - 1.0 if value is not None and demand else None
        if mode is not None and mode == governing:
            notes = ["lowest", *notes, *(note for note in governing_notes if note not in notes)]
        return [label, _qty(pressure, units), f"margin {_margin(margin)}", "; ".join(notes)]

    rows: list[list[str]] = []
    global_mode = result.get("global_with_ring_torsion") or {}
    notes = []
    if global_mode.get("critical_circumferential_lobes_n") is not None:
        notes.append(f"m={global_mode.get('critical_axial_half_waves_m')}, n={global_mode['critical_circumferential_lobes_n']}")
    if result.get("global_elastic_applicability") == "exceeded":
        notes.append("elastic upper bound")
    rows.append(row("global buckling, Eq. 64 x 0.75", global_mode.get("adjusted_critical_pressure_mpa"),
                    notes, "global_eq64_with_eq91_ring_torsion"))

    bay = result.get("inter_ring_shell_buckling") or {}
    bay_status = bay.get("capacity_status", "")
    bay_pressure = bay.get("correlated_critical_pressure_mpa") if not bay_status.startswith("withheld") else None
    notes = [] if bay_pressure is not None or not bay_status else [bay_status.replace("_", " ")]
    if bay_pressure is not None:
        notes = [note for note in _buckling_detail(bay, False, units)["notes"] if not note.startswith("elastic upper bound")]
        if bay_status == "released_pending_plasticity":
            notes.append("elastic upper bound")
    rows.append(row("inter-ring bay buckling", bay_pressure, notes, "inter_ring_smooth_shell"))

    collapse = result.get("axisymmetric_collapse")
    if collapse is not None:
        established = _number(collapse.get("collapse_pressure_mpa")) is not None
        rows.append(row("axisymmetric collapse, Lunchick", collapse.get("collapse_pressure_mpa"),
                        ["perfect shell"] if established else ["closed form ends before first yield"],
                        "axisymmetric_collapse_lunchick"))
    yield_evaluated = _number(result.get("shell_yield_between_rings_pressure_mpa")) is not None
    if yield_evaluated:
        location = _RING_FIRST_YIELD_LABELS.get(result.get("ring_location", ""), "smallest radius")
        rows += [
            row("shell hoop yield at mid-bay (Pc5)", result.get("shell_yield_between_rings_pressure_mpa"), []),
            row("ring mean hoop yield", result.get("ring_yield_pressure_mpa"), []),
            row(f"ring first yield ({location})", result.get("ring_first_yield_pressure_mpa"), []),
        ]
    lines = _table(rows)
    if governing is None and result.get("capacity_status") == "advisory":
        lines.append(f"Lowest buckling or collapse pressure: not established (inter-ring bay {bay_status})")
    if not yield_evaluated:
        lines.append("Yield pressures: not evaluated without a yield strength")
    bay_stress = result.get("beam_column_bay")
    if bay_stress is not None:
        def stress(station: str, surface: str) -> str:
            return _qty(bay_stress[station][f"von_mises_{surface}_mpa"], units)
        lines.append(
            f"Bay von Mises at {_qty(result.get('external_pressure_mpa'), units)}: mid-bay outer {stress('midbay', 'outer')}, "
            f"inner {stress('midbay', 'inner')}, membrane {_qty(bay_stress['midbay_von_mises_membrane_mpa'], units)}; "
            f"frame outer {stress('frame', 'outer')}, inner {stress('frame', 'inner')}"
        )
    reference_only = any(_REFERENCE_ONLY in line for line in lines)
    for check in checks:
        for reason in check.get("reasons", []):
            if reason in shown or (reference_only and reason == BUCKLING_REFERENCE_ONLY_REASON):
                continue
            shown.add(reason)
            lines.append(f"  {reason}")
    return lines


def _render_single(payload: dict[str, Any], summary: dict[str, Any], units: str) -> list[str]:
    assessment = summary["assessment"]
    title = " ".join(part for part in (summary.get("model", "calculation"), summary.get("operation")) if part)
    lines = [f"{title}: {assessment['status'].upper()}" if assessment["checks"] else title]
    lines += [line for line in (
        _material_line(payload, summary), _geometry_line(payload, summary, units), _pressure_line(summary, units),
    ) if line]
    shown: set[str] = set()
    if payload.get("model") == "ring-shell" and "result" in payload:
        lines += _ring_lines(payload["result"], assessment["checks"], units, shown)
    else:
        lines += _check_lines(payload, assessment["checks"], units, shown)
    lines += _displacement_lines(payload, units, shown)
    if assessment.get("governing_check") and len(assessment["checks"]) > 1:
        lines.append(f"Governing: {assessment['governing_check']}")
    mass = _mass_line(summary, payload, units)
    if mass:
        lines.append(mass)
    if payload.get("model") == "cylinder" and not payload.get("components", {}).get("closures", [None]):
        lines.append("No closures supplied.")
    return lines


def _batch_axis(context: dict[str, Any]) -> list[tuple[str, Any]]:
    """The entry's coordinates: material, or the swept quantity."""
    if "material" in context:
        return [("material", context["material"])]
    return [(key, value) for key, value in context.items()
            if isinstance(value, dict) and "unit" in value and key != "service_external_pressure"]


def _render_batch(payload: dict[str, Any], summary: dict[str, Any], units: str) -> list[str]:
    raw_entries = batch_entries(payload) or []
    entries = summary["entries"]
    title = " ".join(part for part in (summary.get("model"), summary.get("operation")) if part)
    lines = [f"{title}: {summary['assessment']['status'].upper()}"]
    children = [entry["summary"] for entry in entries]
    responses = [raw.get("response", {}) for raw in raw_entries]
    comparison = "comparison" in payload

    def shared(render: Any) -> str | None:
        values = {render(response, child) for response, child in zip(responses, children) if response}
        return values.pop() if len(values) == 1 else None

    if not comparison:
        lines += [line for line in (shared(_material_line),) if line]
    sized = any("sizing" in child for child in children)
    if not sized:
        # A geometry sweep varies one dimension and those derived from it; the
        # rest are common to every point.
        part_lists = [_geometry_parts(response, child, units) for response, child in zip(responses, children) if response]
        common = [part for part in part_lists[0] if all(part in parts for parts in part_lists)] if part_lists else []
        if common:
            lines.append("Geometry: " + ", ".join(common))
    depth_conversion = payload.get("sweep", {}).get("depth_to_pressure")
    if depth_conversion:
        lines.append(
            f"Pressure: from depth at {_qty(depth_conversion['fluid_density'], units)}, "
            f"g = {_qty(depth_conversion['gravity'], units)}, "
            f"design factor {_num(depth_conversion['design_factor'])}"
        )
    elif not payload.get("sweep", {}).get("swept_input", "").endswith("external_pressure"):
        lines += [line for line in (shared(lambda response, child: _pressure_line(child, units)),) if line]

    check_ids = list(dict.fromkeys(
        check["id"] for child in children for check in child["assessment"]["checks"]
    ))
    single_check = len(check_ids) == 1
    first_axis = _batch_axis(entries[0]) if entries else []
    header = [key.replace("_external_pressure", " pressure").replace("_", " ") for key, _ in first_axis] + ["status"]
    if sized:
        header.append("selected")
    basis = ""
    if single_check:
        for response, child in zip(responses, children):
            if child["assessment"]["checks"]:
                basis = _check_basis(response.get("model"), child["assessment"]["checks"][0])
                break
        header += [basis, "capacity", "margin"]
    else:
        header += ["lowest margin", "check"]
    masses = [_batch_mass(raw, child) for raw, child in zip(raw_entries, children)]
    show_mass = any(mass[0] is not None for mass in masses)
    show_net = any(mass[1] is not None for mass in masses)
    if show_mass:
        header.append("air mass")
    if show_net:
        header.append("net")

    rows = [header]
    footnotes: list[str] = []
    for entry, response, child, (air, net) in zip(entries, responses, children, masses):
        row = []
        for key, value in _batch_axis(entry):
            row.append(_qty(value, units, "depth" if key == "depth" else None) if isinstance(value, dict) else str(value))
        if not response:
            rows.append(row + ["ERROR"] + [""] * (len(header) - len(row) - 1))
            footnotes.append(f"{row[0] if row else entry['index']}: {entry.get('message', entry.get('outcome', 'error'))}")
            continue
        row.append(child["assessment"]["status"].upper())
        if sized:
            selected = next((value for key, value in child.get("sizing", {}).items() if key.startswith("selected_") and isinstance(value, dict) and "unit" in value), None)
            row.append(_qty(selected, units))
        views = {check["id"]: _check_view(response, check, units) for check in child["assessment"]["checks"]}
        if single_check:
            view = views.get(check_ids[0])
            row += ([f"{view['demand']} {view['unit']}",
                     view["capacity"] if view["capacity"] == "n/a" else f"{view['capacity']} {view['unit']}",
                     view["margin"]]
                    if view else ["n/a"] * 3)
        else:
            row += _lowest_margin(child["assessment"]["checks"], views)
        if show_mass:
            row.append(_qty(air, units))
        if show_net:
            row.append(_qty(net, units))
        rows.append(row)
        for view in views.values():
            for text in (*view["notes"], *view["reasons"]):
                if text.startswith("elastic "):
                    continue
                note = f"{view['id']}: {text}"
                if note not in footnotes:
                    footnotes.append(note)
    lines += _table(rows)
    lines += [f"  {note}" for note in footnotes]
    return lines


def _lowest_margin(checks: Sequence[dict[str, Any]], views: dict[str, dict[str, Any]]) -> list[str]:
    """The check with the least margin over its requirement, among those with a margin."""
    candidates = [
        (views[check["id"]]["margin_value"] - (_number(check.get("required_margin")) or 0.0), check["id"])
        for check in checks
        if views[check["id"]]["margin_value"] is not None
    ]
    if not candidates:
        return ["n/a", ""]
    _, check_id = min(candidates)
    return [views[check_id]["margin"], check_id]


def _batch_mass(raw: dict[str, Any], child: dict[str, Any]) -> tuple[Any, Any]:
    if raw.get("structural_mass", {}).get("status") == "available":
        return raw["structural_mass"]["mass"], None
    mass = child.get("mass_properties", {})
    return mass.get("total_air_mass_kg", mass.get("structural_air_mass_kg")), mass.get("net_submerged_mass_kg")


def render_text(
    payload: dict[str, Any], units: str = "si", assessment: dict[str, Any] | None = None,
) -> str:
    """Render a concise terminal report without changing detailed JSON.

    ``assessment`` replaces the response's own when ``check`` has applied
    selected checks or a minimum margin.
    """
    if units not in UNIT_SYSTEMS:
        raise CalcCliError("invalid_request", "--units must be si or us")
    summary = summarize_response(payload)
    if assessment is not None:
        if "entries" in summary:
            for entry, entry_assessment in zip(summary["entries"], assessment.get("entries", [])):
                entry["summary"]["assessment"] = entry_assessment
        summary["assessment"] = assessment
    if "entries" in summary:
        return "\n".join(_render_batch(payload, summary, units))
    return "\n".join(_render_single(payload, summary, units))


_STRENGTH_FIELDS = {
    "ductile_metal": ("yield", "yield_strength_mpa"),
    "plastic": ("working", "working_strength_mpa"),
    "brittle": ("compressive", "ultimate_compressive_strength_mpa"),
}


def _modulus(value_mpa: Any, units: str) -> str:
    """Elastic modulus in GPa or Mpsi, which keep the column short."""
    value = _number(value_mpa)
    if value is None:
        return "n/a"
    if units == "us":
        return f"{_num(Q_(value, 'MPa').to('psi').magnitude / 1e6)} Mpsi"
    return f"{_num(value / 1e3)} GPa"


def render_material_table(records: Sequence[dict[str, Any]], units: str = "si") -> str:
    """One row per material record: strength, stiffness, density, and buckling data."""
    rows = [["material", "category", "strength", "E", "density", "buckling data"]]
    for record in records:
        properties = record.get("properties", {})
        category = properties.get("failure_category", "")
        label, field = _STRENGTH_FIELDS.get(category, ("", ""))
        strength = properties.get(field)
        buckling = record.get("capabilities", {}).get("smooth_cylinder_buckling_capacity", {})
        if buckling.get("available"):
            data = (buckling.get("buckling_data_qualification") or "qualified").replace("_", "-")
        else:
            data = "missing " + ", ".join(buckling.get("missing_properties", []))
        rows.append([
            record["name"], category.replace("_", " "),
            f"{label} {_qty({'value': strength, 'unit': 'MPa'}, units)}" if strength is not None else "n/a",
            _modulus(properties.get("elastic_modulus_mpa"), units),
            _qty({"value": properties.get("density_kg_per_m3"), "unit": "kg/m^3"}, units),
            data,
        ])
    database = {record.get("database") for record in records}
    lines = _table(rows)
    if len(database) == 1:
        lines.append(f"Database: {database.pop()}")
    return "\n".join(lines)


# Schema errors on a union list every branch; the first few name the problem.
_ERROR_DETAIL_LINES = 6


def render_error_text(error: dict[str, Any], units: str = "si") -> str:
    """Render the CLI error contract as text: the message and its key details."""
    lines = [f"error ({error['code']}): {error['message']}"]
    for detail in error.get("details", []):
        if not isinstance(detail, dict):
            continue
        if "location" in detail and "message" in detail:
            location = ".".join(str(part) for part in detail["location"])
            if f"{location}: {detail['message']}" not in error["message"]:
                lines.append(f"  {location}: {detail['message']}")
        if "available_materials" in detail:
            lines.append("  available: " + ", ".join(detail["available_materials"]))
        if "bounds" in detail:
            bounds = detail["bounds"]
            lines.append(f"  bounds: {_qty(bounds.get('lower'), units)} to {_qty(bounds.get('upper'), units)}")
        for key in ("lower_evaluation", "upper_evaluation"):
            evaluation = detail.get(key)
            if not isinstance(evaluation, dict):
                continue
            at = _qty(next((value for name, value in evaluation.items() if isinstance(value, dict) and "unit" in value), None), units)
            if evaluation.get("withheld_reasons"):
                lines.append(f"  at {at}: withheld ({'; '.join(evaluation['withheld_reasons'])})")
            elif evaluation.get("governing_check") is not None:
                lines.append(f"  at {at}: {evaluation['governing_check']} governs, margin {_margin(evaluation.get('minimum_margin'))}")
        for candidate in detail.get("stock_candidates", []):
            lines.append(f"  stock {_qty(candidate.get('thickness'), units)}: {candidate.get('outcome', '').replace('_', ' ')}")
    if len(lines) > _ERROR_DETAIL_LINES + 1:
        hidden = len(lines) - 1 - _ERROR_DETAIL_LINES
        lines = [*lines[:_ERROR_DETAIL_LINES + 1], f"  ({hidden} more in --format json)"]
    return "\n".join(lines)


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
