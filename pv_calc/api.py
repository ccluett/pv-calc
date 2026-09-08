"""Public, unit-aware calculation interface shared by Python and the CLI."""

from __future__ import annotations

from collections.abc import Mapping
from copy import deepcopy
from pathlib import Path
from typing import Any, Annotated

from pydantic import Field, ValidationError

from pv_calc.contracts import (
    ContractModel, Length, Density, Acceleration, MaterialComparisonRequest,
    SweepRequest, RequestType, _quantity, _to_unit, _validate_request,
)
from pv_calc.errors import CalcCliError
from pv_calc.hydrostatics import external_pressure_from_depth
from pv_calc.serialize import _ensure_json_representable


class DepthLoad(ContractModel):
    """One constant-density depth load with a caller-selected policy factor."""

    depth: Length
    fluid_density: Density
    gravity: Acceleration
    design_factor: Annotated[float, Field(gt=0, allow_inf_nan=False)]


def _prepare_request(raw: Mapping[str, Any]) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """Resolve a single request's alternate depth load without mutating the caller."""
    payload = deepcopy(dict(raw))
    inputs = payload.get("inputs")
    model = payload.get("model")
    if model in ("sweep", "compare-materials"):
        nested = payload.get("request")
        if isinstance(nested, Mapping):
            payload["request"], nested_loading = _prepare_request(nested)
            # A pressure/depth sweep replaces the base load at every point.
            # Its own axis provenance takes precedence over that base load.
            keeps_base_load = model == "compare-materials" or (
                isinstance(inputs, dict) and "geometry" in inputs
            )
            if nested_loading is not None and keeps_base_load:
                return payload, {"request_loading": nested_loading}
        return payload, None
    if not isinstance(inputs, dict) or "depth" not in inputs:
        return payload, None
    if "external_pressure" in inputs:
        raise CalcCliError("input_source_conflict", "choose external_pressure or depth, not both")
    fields = ("depth", "fluid_density", "gravity", "design_factor")
    try:
        load = DepthLoad.model_validate({key: inputs[key] for key in fields if key in inputs})
    except ValidationError as exc:
        raise CalcCliError("invalid_request", "invalid depth load", [
            {"location": ["inputs", *item["loc"]], "message": item["msg"]}
            for item in exc.errors(include_url=False, include_context=False, include_input=False)
        ]) from exc
    try:
        converted = external_pressure_from_depth(
            depth_m=_to_unit(load.depth, "m", "inputs.depth"),
            fluid_density_kg_per_m3=_to_unit(load.fluid_density, "kg/m^3", "inputs.fluid_density"),
            gravity_m_per_s2=_to_unit(load.gravity, "m/s^2", "inputs.gravity"),
            design_factor=load.design_factor,
        )
    except (ArithmeticError, TypeError, ValueError) as exc:
        raise CalcCliError("unevaluable_model", str(exc)) from exc
    for key in fields:
        inputs.pop(key, None)
    inputs["external_pressure"] = _quantity(converted.design_external_pressure_mpa, "MPa")
    return payload, {
        "input_mode": "depth",
        "model_id": converted.model_id,
        "model_version": converted.model_version,
        "source_reference": converted.source_reference,
        "pressure_reference": converted.pressure_reference_convention,
        "depth": _quantity(converted.depth_m, "m"),
        "fluid_density": _quantity(converted.fluid_density_kg_per_m3, "kg/m^3"),
        "gravity": _quantity(converted.gravity_m_per_s2, "m/s^2"),
        "design_factor": converted.design_factor,
        "service_external_pressure": _quantity(converted.service_external_pressure_mpa, "MPa"),
        "design_external_pressure": inputs["external_pressure"],
        "substituted_pressure": "design_external_pressure",
    }


def _attach_loading(response: dict[str, Any], loading: dict[str, Any] | None) -> None:
    """Attach resolved load provenance after strict validation and evaluation.

    Batch contracts carry normalized engineering inputs, so the conversion
    travels separately until the result exists. Failed comparison entries have
    no selected result to annotate and retain their original error details.
    """
    if loading is None:
        return
    nested_loading = loading.get("request_loading")
    if nested_loading is not None:
        entries = response.get("comparison", {}).get(
            "entries", response.get("sweep", {}).get("points", []),
        )
        for entry in entries:
            if "response" in entry:
                _attach_loading(entry["response"], nested_loading)
    else:
        response["loading"] = deepcopy(loading)


def _calculate_for_command(
    request_type: type[RequestType], raw: dict[str, Any], materials_file: Path | None,
) -> dict[str, Any]:
    """Retain each command's strict model/operation validation before dispatch."""
    payload, loading = _prepare_request(raw)
    validated = _validate_request(request_type, payload)
    response = calculate(validated, materials_file=materials_file)
    _attach_loading(response, loading)
    return response


def calculate(
    request: Mapping[str, Any] | ContractModel,
    *,
    materials_file: str | Path | None = None,
) -> dict[str, Any]:
    """Evaluate a versioned forward, sizing, sweep, or material-comparison request.

    Quantities have explicit units, exactly as in CLI JSON. Returns a finite,
    JSON-serializable response. Invalid requests raise ``CalcCliError`` with
    ``code``, ``message``, and ``details``; evaluated failed/withheld checks are
    normal results. The caller's input is never modified.
    """
    from pv_calc.evaluate import (
        _evaluate_material_comparison, _evaluate_single_request, _evaluate_sweep,
    )

    raw = request.model_dump(mode="json") if isinstance(request, ContractModel) else request
    if not isinstance(raw, Mapping):
        raise CalcCliError("invalid_request", "request must be an object")
    payload, loading = _prepare_request(raw)
    path = Path(materials_file) if materials_file is not None else None
    model = payload.get("model")
    if not isinstance(model, str):
        raise CalcCliError("unknown_model", f"unknown model {model!r}")
    if model == "sweep":
        response = _evaluate_sweep(_validate_request(SweepRequest, payload), path)
    elif model == "compare-materials":
        response = _evaluate_material_comparison(_validate_request(MaterialComparisonRequest, payload), path)
    else:
        response = _evaluate_single_request(model, payload, path)
    _attach_loading(response, loading)
    _ensure_json_representable(response)
    return response
