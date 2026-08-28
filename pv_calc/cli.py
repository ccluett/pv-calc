from __future__ import annotations

import inspect
import json
import math
import re
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Annotated, Any, Literal, NoReturn, overload

import typer

from pv_calc import __version__
from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    HemisphereRequest,
    MassPropertiesRequest,
    MaterialComparisonRequest,
    PlateRequest,
    PlateSizeRequest,
    RingShellRequest,
    SmoothBucklingRequest,
    SmoothBucklingSizeRequest,
    SweepRequest,
    TubeRequest,
    TubeSizeRequest,
    _validate_request,
)
from pv_calc.describe import (
    _describe_material_comparison,
    _describe_model,
    _describe_sweep,
)
from pv_calc.errors import CalcCliError
from pv_calc.evaluate import (
    _evaluate_hemisphere,
    _evaluate_mass_properties,
    _evaluate_material_comparison,
    _evaluate_plate,
    _evaluate_ring_shell,
    _evaluate_smooth_buckling,
    _evaluate_sweep,
    _evaluate_tube,
)
from pv_calc.serialize import _json_text
from pv_calc.sizing import (
    _evaluate_plate_size,
    _evaluate_smooth_buckling_size,
    _evaluate_tube_size,
)
from pv_calc.units import (
    Q_,
    UNIT_EVALUATION_ERRORS,
    dimensionless_factor,
    unit_expression_problem,
)

app = typer.Typer(
    no_args_is_help=True,
    help=(
        "Run pressure-vessel calculations based on published formulas. Results"
        " come from idealized models and are not a design approval."
    ),
    epilog="Example: pv-calc describe hemisphere --json",
)
tube_app = typer.Typer(
    invoke_without_command=True,
    help="Run the tube calculation or its wall-thickness sizing operation.",
    epilog=(
        "Example: pv-calc tube --input request.json --json"
    ),
)
app.add_typer(tube_app, name="tube")
plate_app = typer.Typer(
    invoke_without_command=True,
    help="Run the flat-plate calculation or its plate-thickness sizing operation.",
    epilog=(
        "Example: pv-calc plate --input request.json --json"
    ),
)
app.add_typer(plate_app, name="plate")
smooth_buckling_app = typer.Typer(
    invoke_without_command=True,
    help="Run the smooth-cylinder buckling calculation or its wall-thickness sizing operation.",
    epilog=(
        "Example: pv-calc smooth-buckling --input request.json --json"
    ),
)
app.add_typer(smooth_buckling_app, name="smooth-buckling")


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(__version__)
        raise typer.Exit()


@app.callback()
def main(
    version: Annotated[
        bool | None,
        typer.Option(
            "--version",
            callback=_version_callback,
            is_eager=True,
            help="Show the pv-calc package version and exit.",
        ),
    ] = None,
) -> None:
    """Run pressure-vessel calculations based on published formulas.

    Results come from idealized models and are not a design approval.
    """


def _emit(payload: dict[str, Any], *, compact: bool) -> None:
    try:
        text = _json_text(payload, compact=compact)
    except (TypeError, ValueError) as exc:
        raise CalcCliError(
            "unevaluable_model",
            "calculation produced a result that cannot be represented as finite JSON",
        ) from exc
    typer.echo(text)


def _exit_with_error(error: CalcCliError) -> NoReturn:
    payload = {
        "schema_version": CALC_SCHEMA_VERSION,
        "error": {
            "code": error.code,
            "details": error.details,
            "message": error.message,
        },
    }
    typer.echo(_json_text(payload, compact=True), err=True)
    raise typer.Exit(2)


def _read_json_input(input_path: str) -> dict[str, Any]:
    try:
        text = sys.stdin.read() if input_path == "-" else Path(input_path).read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise CalcCliError("input_read_error", str(exc)) from exc
    try:
        payload = json.loads(text)
    except json.JSONDecodeError as exc:
        raise CalcCliError(
            "invalid_json",
            f"invalid JSON at line {exc.lineno}, column {exc.colno}: {exc.msg}",
        ) from exc
    if not isinstance(payload, dict):
        raise CalcCliError("invalid_request", "JSON input must be an object")
    return payload


# One numeric literal, then the unit. The split happens before pint sees the
# string because Q_(str) is an expression evaluator: it deletes commas, inserts
# implicit multiplication, and drops non-ASCII characters, so '1,5 MPa' would
# become 15 MPa, '1 psi 2' would become 2 psi, and a U+2212 minus would lose its
# sign -- a different number, silently, instead of a rejection. The digits are
# ASCII only, as on the JSON path, where a magnitude is a JSON number; the one
# form beyond JSON is Python's underscore digit grouping ('1_000 psi'), which
# float() reads unambiguously. No unit starts with a digit or a decimal point,
# and saying so keeps the split deterministic: without it '0.1' backtracks into
# the number '0' and the "unit" '.1' rather than being reported as the unitless
# value it is.
_GROUPED_DIGITS = r"[0-9](?:_?[0-9])*"
_NUMBER_THEN_UNIT = re.compile(
    rf"^\s*([+-]?(?:{_GROUPED_DIGITS}(?:\.(?:{_GROUPED_DIGITS})?)?|\.{_GROUPED_DIGITS})"
    rf"(?:[eE][+-]?{_GROUPED_DIGITS})?)\s*([^0-9.\s].*)$"
)


def _quantity_from_option(value: str | None, field_name: str) -> dict[str, Any] | None:
    if value is None:
        return None
    match = _NUMBER_THEN_UNIT.match(value)
    if match is None:
        # ascii(), not repr(): the offending character is often one a terminal
        # renders as an ordinary one, such as a U+2212 minus pasted from a PDF.
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} must be one number followed by a unit, like"
            f" '1000 psi' or '8mm'; got {ascii(value)}",
        )
    number, unit = match.groups()
    problem = unit_expression_problem(unit)
    if problem is not None:
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} must be one number followed by a unit, and the unit"
            f" {problem}; got {ascii(value)}",
        )
    try:
        scalar = float(number)
        quantity = Q_(scalar, unit)
        hidden_factor = dimensionless_factor(quantity)
        # Resolving .dimensionless is what applies the exponent, so it belongs
        # inside the guard: '1 psi^999999999' raises here, not at Q_.
        dimensionless = quantity.dimensionless
    except UNIT_EVALUATION_ERRORS as exc:
        # pint names the token it could not read ('PSI' is not defined ...), but
        # a bare AssertionError carries nothing; only append what it says, minus
        # the sentence period some of its messages carry and this one does not.
        detail = str(exc).strip().rstrip(".")
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} must be a scalar value with an explicit unit"
            + (f": {detail}" if detail else "")
            + f"; got {ascii(value)}",
        ) from exc
    if hidden_factor is not None:
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} must be one number followed by a unit, and"
            f" '{hidden_factor}' is a number, not a unit; got {ascii(value)}",
        )
    if dimensionless:
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} must include an explicit dimensional unit",
        )
    return {"value": scalar, "unit": str(quantity.units)}


@overload
def _number_from_option(value: str, field_name: str) -> float: ...
@overload
def _number_from_option(value: None, field_name: str) -> None: ...
def _number_from_option(value: str | None, field_name: str) -> float | None:
    if value is None:
        return None
    try:
        result = float(value)
    except ValueError as exc:
        raise CalcCliError("invalid_number", f"{field_name} must be numeric") from exc
    if not math.isfinite(result):
        raise CalcCliError("invalid_number", f"{field_name} must be finite")
    return result


def _named_material_selection(
    named_material: str | None,
    explicit_values: tuple[str | None, ...],
) -> dict[str, Any] | None:
    """Return the named selection, or None to build an explicit property block."""
    has_explicit_value = any(value is not None for value in explicit_values)
    if named_material is not None and has_explicit_value:
        raise CalcCliError(
            "material_source_conflict",
            "choose exactly one material source: --material or an explicit property record",
        )
    if named_material is not None:
        return {"type": "named", "name": named_material}
    if not has_explicit_value:
        raise CalcCliError(
            "missing_material_source",
            "choose exactly one material source: --material or an explicit property record",
        )
    return None


def _material_selection(
    *,
    named_material: str | None,
    failure_category: str | None,
    material_provenance: str | None,
    yield_strength: str | None = None,
    working_strength: str | None = None,
    ultimate_tensile_strength: str | None = None,
    ultimate_compressive_strength: str | None = None,
    elastic_modulus: str | None = None,
    poisson_ratio: str | None = None,
    proportional_limit: str | None = None,
    material_density: str | None = None,
) -> dict[str, Any]:
    strengths = {
        "yield_strength": yield_strength,
        "working_strength": working_strength,
        "ultimate_tensile_strength": ultimate_tensile_strength,
        "ultimate_compressive_strength": ultimate_compressive_strength,
    }
    named = _named_material_selection(
        named_material,
        (
            *strengths.values(),
            failure_category,
            material_provenance,
            elastic_modulus,
            poisson_ratio,
            proportional_limit,
            material_density,
        ),
    )
    if named is not None:
        return named
    properties: dict[str, Any] = {
        "failure_category": failure_category,
        **{
            name: _quantity_from_option(value, name)
            for name, value in strengths.items()
            if value is not None
        },
    }
    if elastic_modulus is not None or poisson_ratio is not None:
        properties.update(
            {
                "elastic_modulus": _quantity_from_option(elastic_modulus, "elastic_modulus"),
                "poisson_ratio": _number_from_option(poisson_ratio, "poisson_ratio"),
            }
        )
    if proportional_limit is not None:
        properties["proportional_limit"] = _quantity_from_option(
            proportional_limit,
            "proportional_limit",
        )
    if material_density is not None:
        properties["density"] = _quantity_from_option(material_density, "material_density")
    return {
        "type": "explicit",
        "provenance": material_provenance,
        "properties": properties,
    }


def _mass_material_selection(
    *,
    named_material: str | None,
    material_density: str | None,
    material_provenance: str | None,
) -> dict[str, Any]:
    named = _named_material_selection(
        named_material,
        (material_density, material_provenance),
    )
    if named is not None:
        return named
    return {
        "type": "explicit",
        "provenance": material_provenance,
        "properties": {
            "density": _quantity_from_option(material_density, "material_density"),
        },
    }


def _integer_from_option(value: str | None, field_name: str) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except ValueError as exc:
        raise CalcCliError(
            "invalid_number",
            f"{field_name} must be an integer",
        ) from exc


def _axis_from_options(
    *,
    name: Literal["depth", "pressure"],
    values: list[str] | None,
    start: str | None,
    stop: str | None,
    count: str | None,
) -> dict[str, Any] | None:
    """Build one list-or-range axis, or None when no option was supplied."""
    has_range_value = any(value is not None for value in (start, stop, count))
    if values and has_range_value:
        raise CalcCliError(
            "axis_source_conflict",
            f"choose exactly one {name} axis: --{name}, or"
            f" --{name}-start/--{name}-stop/--{name}-count",
        )
    if values:
        return {
            "type": "list",
            "values": [_quantity_from_option(value, name) for value in values],
        }
    if not has_range_value:
        return None
    return {
        "type": "range",
        "count": _integer_from_option(count, f"{name}_count"),
        "start": _quantity_from_option(start, f"{name}_start"),
        "stop": _quantity_from_option(stop, f"{name}_stop"),
    }


def _sweep_inputs_from_options(
    *,
    pressure_axis: dict[str, Any] | None,
    depth_axis: dict[str, Any] | None,
    fluid_density: str | None,
    gravity: str | None,
    design_factor: str | None,
) -> dict[str, Any] | None:
    """Build the `inputs` block the request would carry, or None for neither."""
    has_depth_value = depth_axis is not None or any(
        value is not None for value in (fluid_density, gravity, design_factor)
    )
    if pressure_axis is not None and has_depth_value:
        raise CalcCliError(
            "axis_source_conflict",
            "choose exactly one sweep axis: pressure or depth",
        )
    if has_depth_value:
        return {
            "depth": depth_axis,
            "design_factor": _number_from_option(design_factor, "design_factor"),
            "fluid_density": _quantity_from_option(fluid_density, "fluid_density"),
            "gravity": _quantity_from_option(gravity, "gravity"),
        }
    if pressure_axis is None:
        return None
    return {"external_pressure": pressure_axis}


# Options whose help text is the same in every command that declares them; an
# option whose wording differs between commands stays declared per command.
MaterialOption = Annotated[
    str | None,
    typer.Option(help="Named --materials-file entry; exclusive with explicit properties."),
]
WorkingStrengthOption = Annotated[
    str | None,
    typer.Option(help="Explicit plastic working strength with unit."),
]
UltimateTensileStrengthOption = Annotated[
    str | None,
    typer.Option(help="Explicit brittle ultimate tensile strength with unit."),
]
UltimateCompressiveStrengthOption = Annotated[
    str | None,
    typer.Option(help="Explicit brittle ultimate compressive strength with unit."),
]
FailureCategoryOption = Annotated[
    str | None,
    typer.Option(help="Explicit category: ductile_metal, plastic, or brittle."),
]
MaterialProvenanceOption = Annotated[
    str | None,
    typer.Option(help="Optional source note for explicit material properties."),
]
BoundaryConditionOption = Annotated[
    str | None,
    typer.Option(help="Required: fixed or simply_supported."),
]
ShellMidSurfaceRadiusOption = Annotated[
    str | None,
    typer.Option(help="Shell mid-surface radius with unit."),
]
MaterialsFileOption = Annotated[
    Path | None,
    typer.Option(help="Materials database read by --material; required with it."),
]
JsonOutputOption = Annotated[
    bool,
    typer.Option("--json", help="Emit compact deterministic JSON."),
]


# The options every command reads beside its calculation and material values.
_NON_REQUEST_OPTIONS = frozenset({"input_path", "materials_file", "json_output"})


def _given_options(ctx: typer.Context, *, exclude: frozenset[str] = frozenset()) -> list[str]:
    """The CLI spellings of the options the command was given a value for."""
    spellings = {
        param.name: next(
            (opt for opt in param.opts if opt.startswith("--")), param.opts[0]
        )
        for param in ctx.command.params
        if param.name and param.opts
    }
    return sorted(
        spellings.get(name, name)
        for name, value in ctx.params.items()
        if name not in exclude and value is not None and value is not False
    )


def _ensure_file_input_is_exclusive(ctx: typer.Context) -> None:
    """Reject --input beside any calculation or material option value the command was given."""
    if ctx.params.get("input_path") is None:
        return
    names = _given_options(ctx, exclude=_NON_REQUEST_OPTIONS)
    if names:
        raise CalcCliError(
            "input_source_conflict",
            "--input cannot be combined with calculation or material option values",
            [{"conflicting_options": names}],
        )


def _ensure_no_options_before_subcommand(ctx: typer.Context) -> None:
    """Reject option values typed before a subcommand; the subcommand would never see them."""
    names = _given_options(ctx)
    if names:
        raise CalcCliError(
            "invalid_request",
            f"options must follow the {ctx.invoked_subcommand} subcommand; these were given"
            f" before it and would be ignored",
            [{"ignored_options": names}],
        )


def _submergence_from_options(fluid_density: str | None, gravity: str | None) -> dict[str, Any]:
    """The ``submergence`` block, present once either fluid option is given."""
    if fluid_density is None and gravity is None:
        return {}
    return {
        "submergence": {
            "fluid_density": _quantity_from_option(fluid_density, "fluid_density"),
            "gravity": _quantity_from_option(gravity, "gravity"),
        }
    }


def _minimum_margin_from_option(minimum_margin: str | None) -> float:
    return (
        _number_from_option(minimum_margin, "minimum_margin")
        if minimum_margin is not None
        else 0.0
    )


def _thickness_bounds_from_options(
    lower: str | None,
    upper: str | None,
    *,
    variable: str,
) -> dict[str, Any]:
    return {
        "lower": _quantity_from_option(lower, f"{variable}_lower"),
        "upper": _quantity_from_option(upper, f"{variable}_upper"),
    }


@tube_app.callback(invoke_without_command=True)
def tube(
    ctx: typer.Context,
    external_pressure: Annotated[str | None, typer.Option(help="Pressure with unit, e.g. '1000 psi'.")] = None,
    internal_radius: Annotated[str | None, typer.Option(help="Internal radius with unit, e.g. '3 in'.")] = None,
    wall_thickness: Annotated[str | None, typer.Option(help="Wall thickness with unit, e.g. '0.470 in'.")] = None,
    axial_length: Annotated[
        str | None,
        typer.Option(help="Optional gauge length with unit; releases the axial length change."),
    ] = None,
    material: MaterialOption = None,
    yield_strength: Annotated[
        str | None, typer.Option(help="Explicit ductile_metal yield strength with unit, e.g. '62 ksi'.")
    ] = None,
    working_strength: WorkingStrengthOption = None,
    ultimate_compressive_strength: UltimateCompressiveStrengthOption = None,
    material_density: Annotated[
        str | None,
        typer.Option(help="Explicit material density with unit; read only with --fluid-density."),
    ] = None,
    fluid_density: Annotated[
        str | None,
        typer.Option(help="Optional fluid density with unit; with --gravity adds mass properties and failure depths."),
    ] = None,
    gravity: Annotated[
        str | None,
        typer.Option(help="Optional gravity with unit, e.g. '9.81 m/s^2'; required with --fluid-density."),
    ] = None,
    elastic_modulus: Annotated[
        str | None,
        typer.Option(help="Optional explicit elastic modulus with unit; releases displacement."),
    ] = None,
    poisson_ratio: Annotated[
        str | None,
        typer.Option(help="Optional explicit dimensionless Poisson ratio; releases displacement."),
    ] = None,
    failure_category: FailureCategoryOption = None,
    material_provenance: MaterialProvenanceOption = None,
    force_thick: Annotated[bool, typer.Option("--force-thick", help="Force the thick-wall branch.")] = False,
    input_path: Annotated[str | None, typer.Option("--input", help="JSON request file, or '-' for stdin.")] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Calculate closed-end tube stress, material failure pressure, and displacement."""
    try:
        if ctx.invoked_subcommand is not None:
            _ensure_no_options_before_subcommand(ctx)
            return
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "tube",
                "inputs": {
                    "external_pressure": _quantity_from_option(
                        external_pressure, "external_pressure"
                    ),
                    "force_thick": force_thick,
                    "internal_radius": _quantity_from_option(internal_radius, "internal_radius"),
                    "wall_thickness": _quantity_from_option(wall_thickness, "wall_thickness"),
                    **(
                        {"axial_length": _quantity_from_option(axial_length, "axial_length")}
                        if axial_length is not None
                        else {}
                    ),
                    **_submergence_from_options(fluid_density, gravity),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    working_strength=working_strength,
                    ultimate_compressive_strength=ultimate_compressive_strength,
                    material_density=material_density,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                ),
            }
        request = _validate_request(TubeRequest, raw)
        _emit(_evaluate_tube(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@tube_app.command(
    "size",
    epilog=(
        "Example: pv-calc tube size --input request.json --json"
    ),
)
def tube_size(
    ctx: typer.Context,
    external_pressure: Annotated[str | None, typer.Option(help="Pressure with unit, e.g. '7000 psi'.")] = None,
    internal_radius: Annotated[str | None, typer.Option(help="Fixed internal radius with unit, e.g. '3 in'.")] = None,
    wall_thickness_lower: Annotated[
        str | None,
        typer.Option(help="Explicit lower wall-thickness bound with unit, e.g. '0.1 in'."),
    ] = None,
    wall_thickness_upper: Annotated[
        str | None,
        typer.Option(help="Explicit upper wall-thickness bound with unit, e.g. '0.5 in'."),
    ] = None,
    minimum_margin: Annotated[
        str | None,
        typer.Option(help="Required minimum over the declared tube check set; must be nonnegative."),
    ] = None,
    material: MaterialOption = None,
    yield_strength: Annotated[
        str | None, typer.Option(help="Explicit ductile_metal yield strength with unit, e.g. '62 ksi'.")
    ] = None,
    working_strength: WorkingStrengthOption = None,
    ultimate_compressive_strength: UltimateCompressiveStrengthOption = None,
    failure_category: FailureCategoryOption = None,
    elastic_modulus: Annotated[
        str | None,
        typer.Option(help="Optional explicit elastic modulus with unit; releases displacement."),
    ] = None,
    poisson_ratio: Annotated[
        str | None,
        typer.Option(help="Optional explicit dimensionless Poisson ratio; releases displacement."),
    ] = None,
    material_provenance: MaterialProvenanceOption = None,
    force_thick: Annotated[bool, typer.Option("--force-thick", help="Force the thick-wall branch.")] = False,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON sizing request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Find the minimum reliable wall thickness within explicit bounds."""
    try:
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "tube",
                "operation": "size",
                "inputs": {
                    "external_pressure": _quantity_from_option(
                        external_pressure,
                        "external_pressure",
                    ),
                    "force_thick": force_thick,
                    "internal_radius": _quantity_from_option(
                        internal_radius,
                        "internal_radius",
                    ),
                    "minimum_margin": _minimum_margin_from_option(minimum_margin),
                    "wall_thickness_bounds": _thickness_bounds_from_options(
                        wall_thickness_lower,
                        wall_thickness_upper,
                        variable="wall_thickness",
                    ),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    working_strength=working_strength,
                    ultimate_compressive_strength=ultimate_compressive_strength,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                ),
            }
        request = _validate_request(TubeSizeRequest, raw)
        _emit(_evaluate_tube_size(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@plate_app.callback(invoke_without_command=True)
def plate(
    ctx: typer.Context,
    external_pressure: Annotated[str | None, typer.Option(help="Pressure with unit, e.g. '4500 psi'.")] = None,
    free_radius: Annotated[str | None, typer.Option(help="Unsupported radius with unit, e.g. '3 in'.")] = None,
    plate_thickness: Annotated[str | None, typer.Option(help="Plate thickness with unit, e.g. '1.280 in'.")] = None,
    boundary_condition: BoundaryConditionOption = None,
    outside_radius: Annotated[
        str | None,
        typer.Option(help="Optional plate outside radius with unit; releases the seat bearing stress."),
    ] = None,
    material: MaterialOption = None,
    elastic_modulus: Annotated[str | None, typer.Option(help="Explicit elastic modulus with unit.")] = None,
    poisson_ratio: Annotated[str | None, typer.Option(help="Explicit dimensionless Poisson ratio.")] = None,
    yield_strength: Annotated[str | None, typer.Option(help="Explicit ductile_metal yield strength with unit.")] = None,
    working_strength: WorkingStrengthOption = None,
    ultimate_tensile_strength: UltimateTensileStrengthOption = None,
    ultimate_compressive_strength: UltimateCompressiveStrengthOption = None,
    material_density: Annotated[
        str | None,
        typer.Option(help="Explicit material density with unit; read only with --fluid-density."),
    ] = None,
    fluid_density: Annotated[
        str | None,
        typer.Option(help="Optional fluid density with unit; with --gravity adds mass properties and failure depths."),
    ] = None,
    gravity: Annotated[
        str | None,
        typer.Option(help="Optional gravity with unit, e.g. '9.81 m/s^2'; required with --fluid-density."),
    ] = None,
    failure_category: FailureCategoryOption = None,
    material_provenance: MaterialProvenanceOption = None,
    input_path: Annotated[str | None, typer.Option("--input", help="JSON request file, or '-' for stdin.")] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Calculate a uniformly pressure-loaded flat circular plate."""
    try:
        if ctx.invoked_subcommand is not None:
            _ensure_no_options_before_subcommand(ctx)
            return
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "plate",
                "inputs": {
                    "boundary_condition": boundary_condition,
                    "external_pressure": _quantity_from_option(
                        external_pressure, "external_pressure"
                    ),
                    "free_radius": _quantity_from_option(free_radius, "free_radius"),
                    "plate_thickness": _quantity_from_option(
                        plate_thickness, "plate_thickness"
                    ),
                    **(
                        {"outside_radius": _quantity_from_option(outside_radius, "outside_radius")}
                        if outside_radius is not None
                        else {}
                    ),
                    **_submergence_from_options(fluid_density, gravity),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    working_strength=working_strength,
                    ultimate_tensile_strength=ultimate_tensile_strength,
                    ultimate_compressive_strength=ultimate_compressive_strength,
                    material_density=material_density,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                ),
            }
        request = _validate_request(PlateRequest, raw)
        _emit(_evaluate_plate(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@plate_app.command(
    "size",
    epilog=(
        "Example: pv-calc plate size --input request.json --json"
    ),
)
def plate_size(
    ctx: typer.Context,
    external_pressure: Annotated[
        str | None,
        typer.Option(help="Applied external pressure with unit."),
    ] = None,
    free_radius: Annotated[
        str | None,
        typer.Option(help="Fixed unsupported radius with unit."),
    ] = None,
    boundary_condition: BoundaryConditionOption = None,
    plate_thickness_lower: Annotated[
        str | None,
        typer.Option(help="Explicit lower plate-thickness bound with unit."),
    ] = None,
    plate_thickness_upper: Annotated[
        str | None,
        typer.Option(help="Explicit upper plate-thickness bound with unit."),
    ] = None,
    minimum_margin: Annotated[
        str | None,
        typer.Option(help="Required bending margin; must be nonnegative."),
    ] = None,
    maximum_deflection: Annotated[
        str | None,
        typer.Option(
            help="Optional centre-deflection limit with unit; requires the"
            " stricter deflection evidence floor."
        ),
    ] = None,
    material: MaterialOption = None,
    elastic_modulus: Annotated[
        str | None,
        typer.Option(help="Explicit elastic modulus with unit."),
    ] = None,
    poisson_ratio: Annotated[
        str | None,
        typer.Option(help="Explicit dimensionless Poisson ratio."),
    ] = None,
    yield_strength: Annotated[
        str | None,
        typer.Option(help="Explicit ductile_metal yield strength with unit."),
    ] = None,
    working_strength: WorkingStrengthOption = None,
    ultimate_tensile_strength: UltimateTensileStrengthOption = None,
    ultimate_compressive_strength: UltimateCompressiveStrengthOption = None,
    failure_category: FailureCategoryOption = None,
    material_provenance: MaterialProvenanceOption = None,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON sizing request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Find the minimum plate thickness within explicit bounds."""
    try:
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "plate",
                "operation": "size",
                "inputs": {
                    "boundary_condition": boundary_condition,
                    "external_pressure": _quantity_from_option(
                        external_pressure,
                        "external_pressure",
                    ),
                    "free_radius": _quantity_from_option(free_radius, "free_radius"),
                    **(
                        {
                            "maximum_deflection": _quantity_from_option(
                                maximum_deflection,
                                "maximum_deflection",
                            )
                        }
                        if maximum_deflection is not None
                        else {}
                    ),
                    "minimum_margin": _minimum_margin_from_option(minimum_margin),
                    "plate_thickness_bounds": _thickness_bounds_from_options(
                        plate_thickness_lower,
                        plate_thickness_upper,
                        variable="plate_thickness",
                    ),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    working_strength=working_strength,
                    ultimate_tensile_strength=ultimate_tensile_strength,
                    ultimate_compressive_strength=ultimate_compressive_strength,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                ),
            }
        request = _validate_request(PlateSizeRequest, raw)
        _emit(_evaluate_plate_size(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@app.command(
    epilog=(
        "Example: pv-calc hemisphere --input request.json --json"
    )
)
def hemisphere(
    ctx: typer.Context,
    external_pressure: Annotated[
        str | None,
        typer.Option(help="Applied external pressure with unit."),
    ] = None,
    internal_radius: Annotated[
        str | None,
        typer.Option(help="Hemispherical-head internal radius with unit."),
    ] = None,
    wall_thickness: Annotated[
        str | None,
        typer.Option(help="Uniform head wall thickness with unit."),
    ] = None,
    material: MaterialOption = None,
    elastic_modulus: Annotated[
        str | None,
        typer.Option(help="Explicit elastic modulus with unit."),
    ] = None,
    poisson_ratio: Annotated[
        str | None,
        typer.Option(help="Explicit dimensionless Poisson ratio."),
    ] = None,
    yield_strength: Annotated[
        str | None,
        typer.Option(help="Explicit ductile_metal yield strength with unit."),
    ] = None,
    working_strength: WorkingStrengthOption = None,
    ultimate_compressive_strength: UltimateCompressiveStrengthOption = None,
    material_density: Annotated[
        str | None,
        typer.Option(help="Explicit material density with unit; read only with --fluid-density."),
    ] = None,
    fluid_density: Annotated[
        str | None,
        typer.Option(help="Optional fluid density with unit; with --gravity adds mass properties and failure depths."),
    ] = None,
    gravity: Annotated[
        str | None,
        typer.Option(help="Optional gravity with unit, e.g. '9.81 m/s^2'; required with --fluid-density."),
    ] = None,
    proportional_limit: Annotated[
        str | None,
        typer.Option(
            help="Explicit source-traceable proportional limit required for buckling capacity."
        ),
    ] = None,
    failure_category: FailureCategoryOption = None,
    material_provenance: MaterialProvenanceOption = None,
    force_thick: Annotated[
        bool,
        typer.Option("--force-thick", help="Force the thick-wall stress branch."),
    ] = False,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Calculate hemispherical-head stress, material failure, external-pressure buckling, and displacement."""
    try:
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "hemisphere",
                "inputs": {
                    "external_pressure": _quantity_from_option(
                        external_pressure,
                        "external_pressure",
                    ),
                    "force_thick": force_thick,
                    "internal_radius": _quantity_from_option(
                        internal_radius,
                        "internal_radius",
                    ),
                    "wall_thickness": _quantity_from_option(
                        wall_thickness,
                        "wall_thickness",
                    ),
                    **_submergence_from_options(fluid_density, gravity),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    working_strength=working_strength,
                    ultimate_compressive_strength=ultimate_compressive_strength,
                    material_density=material_density,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                    proportional_limit=proportional_limit,
                ),
            }
        request = _validate_request(HemisphereRequest, raw)
        _emit(_evaluate_hemisphere(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@smooth_buckling_app.callback(invoke_without_command=True)
def smooth_buckling(
    ctx: typer.Context,
    external_pressure: Annotated[
        str | None,
        typer.Option(help="Applied external pressure with unit."),
    ] = None,
    shell_mid_surface_radius: ShellMidSurfaceRadiusOption = None,
    wall_thickness: Annotated[
        str | None,
        typer.Option(help="Uniform shell wall thickness with unit."),
    ] = None,
    unsupported_length: Annotated[
        str | None,
        typer.Option(help="Length between idealized circular end supports with unit."),
    ] = None,
    load_case: Annotated[
        str | None,
        typer.Option(help="Required: lateral_only or hydrostatic_closed_end."),
    ] = None,
    material: MaterialOption = None,
    elastic_modulus: Annotated[
        str | None,
        typer.Option(help="Explicit elastic modulus with unit."),
    ] = None,
    poisson_ratio: Annotated[
        str | None,
        typer.Option(help="Explicit dimensionless Poisson ratio."),
    ] = None,
    yield_strength: Annotated[
        str | None,
        typer.Option(help="Optional explicit ductile_metal yield strength with unit; bounds the proportional limit."),
    ] = None,
    material_density: Annotated[
        str | None,
        typer.Option(help="Explicit material density with unit; read only with --fluid-density."),
    ] = None,
    fluid_density: Annotated[
        str | None,
        typer.Option(help="Optional fluid density with unit; with --gravity adds mass properties and failure depths."),
    ] = None,
    gravity: Annotated[
        str | None,
        typer.Option(help="Optional gravity with unit, e.g. '9.81 m/s^2'; required with --fluid-density."),
    ] = None,
    proportional_limit: Annotated[
        str | None,
        typer.Option(
            help="Explicit source-traceable proportional limit required for released capacity."
        ),
    ] = None,
    failure_category: FailureCategoryOption = None,
    material_provenance: MaterialProvenanceOption = None,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Calculate source-gated NASA smooth-cylinder external-pressure buckling."""
    try:
        if ctx.invoked_subcommand is not None:
            _ensure_no_options_before_subcommand(ctx)
            return
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "smooth-buckling",
                "inputs": {
                    "external_pressure": _quantity_from_option(
                        external_pressure,
                        "external_pressure",
                    ),
                    "load_case": load_case,
                    "shell_mid_surface_radius": _quantity_from_option(
                        shell_mid_surface_radius,
                        "shell_mid_surface_radius",
                    ),
                    "unsupported_length": _quantity_from_option(
                        unsupported_length,
                        "unsupported_length",
                    ),
                    "wall_thickness": _quantity_from_option(
                        wall_thickness,
                        "wall_thickness",
                    ),
                    **_submergence_from_options(fluid_density, gravity),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    material_density=material_density,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                    proportional_limit=proportional_limit,
                ),
            }
        request = _validate_request(SmoothBucklingRequest, raw)
        _emit(_evaluate_smooth_buckling(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@smooth_buckling_app.command(
    "size",
    epilog=(
        "Example: pv-calc smooth-buckling size --input request.json --json"
    ),
)
def smooth_buckling_size(
    ctx: typer.Context,
    external_pressure: Annotated[
        str | None,
        typer.Option(help="Applied external pressure with unit."),
    ] = None,
    internal_radius: Annotated[
        str | None,
        typer.Option(help="Fixed internal radius with unit; the mid-surface radius follows."),
    ] = None,
    unsupported_length: Annotated[
        str | None,
        typer.Option(help="Length between idealized circular end supports with unit."),
    ] = None,
    wall_thickness_lower: Annotated[
        str | None,
        typer.Option(help="Explicit lower wall-thickness bound with unit."),
    ] = None,
    wall_thickness_upper: Annotated[
        str | None,
        typer.Option(help="Explicit upper wall-thickness bound with unit."),
    ] = None,
    minimum_margin: Annotated[
        str | None,
        typer.Option(
            help="Required minimum across shell stress and buckling; must be nonnegative."
        ),
    ] = None,
    material: MaterialOption = None,
    elastic_modulus: Annotated[
        str | None,
        typer.Option(help="Explicit elastic modulus with unit."),
    ] = None,
    poisson_ratio: Annotated[
        str | None,
        typer.Option(help="Explicit dimensionless Poisson ratio."),
    ] = None,
    yield_strength: Annotated[
        str | None,
        typer.Option(help="Explicit ductile_metal yield strength with unit."),
    ] = None,
    working_strength: WorkingStrengthOption = None,
    ultimate_compressive_strength: UltimateCompressiveStrengthOption = None,
    proportional_limit: Annotated[
        str | None,
        typer.Option(
            help="Explicit source-traceable proportional limit required for released capacity."
        ),
    ] = None,
    failure_category: FailureCategoryOption = None,
    material_provenance: MaterialProvenanceOption = None,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON sizing request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Find the minimum wall thickness within explicit bounds for both checks."""
    try:
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "smooth-buckling",
                "operation": "size",
                "inputs": {
                    "external_pressure": _quantity_from_option(
                        external_pressure,
                        "external_pressure",
                    ),
                    "internal_radius": _quantity_from_option(
                        internal_radius,
                        "internal_radius",
                    ),
                    "minimum_margin": _minimum_margin_from_option(minimum_margin),
                    "unsupported_length": _quantity_from_option(
                        unsupported_length,
                        "unsupported_length",
                    ),
                    "wall_thickness_bounds": _thickness_bounds_from_options(
                        wall_thickness_lower,
                        wall_thickness_upper,
                        variable="wall_thickness",
                    ),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    working_strength=working_strength,
                    ultimate_compressive_strength=ultimate_compressive_strength,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                    proportional_limit=proportional_limit,
                ),
            }
        request = _validate_request(SmoothBucklingSizeRequest, raw)
        _emit(
            _evaluate_smooth_buckling_size(request, materials_file),
            compact=json_output,
        )
    except CalcCliError as exc:
        _exit_with_error(exc)


@app.command(
    "ring-shell",
    epilog=(
        "Example: pv-calc ring-shell --input request.json --json"
    ),
)
def ring_shell(
    ctx: typer.Context,
    external_pressure: Annotated[
        str | None,
        typer.Option(help="Applied external pressure with unit."),
    ] = None,
    shell_mid_surface_radius: ShellMidSurfaceRadiusOption = None,
    wall_thickness: Annotated[
        str | None,
        typer.Option(help="Uniform shell wall thickness with unit."),
    ] = None,
    unsupported_length: Annotated[
        str | None,
        typer.Option(help="Global length between idealized circular supports with unit."),
    ] = None,
    ring_spacing: Annotated[
        str | None,
        typer.Option(help="Ring center-to-center spacing with unit."),
    ] = None,
    ring_axial_width: Annotated[
        str | None,
        typer.Option(help="Solid rectangular ring axial width with unit."),
    ] = None,
    ring_radial_height: Annotated[
        str | None,
        typer.Option(help="Solid rectangular ring radial height with unit."),
    ] = None,
    ring_location: Annotated[
        str | None,
        typer.Option(help="Required: internal or external."),
    ] = None,
    material: MaterialOption = None,
    elastic_modulus: Annotated[
        str | None,
        typer.Option(help="Explicit shared shell/ring elastic modulus with unit."),
    ] = None,
    poisson_ratio: Annotated[
        str | None,
        typer.Option(help="Explicit shared shell/ring dimensionless Poisson ratio."),
    ] = None,
    yield_strength: Annotated[
        str | None,
        typer.Option(help="Optional explicit ductile_metal yield strength with unit; bounds the proportional limit."),
    ] = None,
    proportional_limit: Annotated[
        str | None,
        typer.Option(help="Optional explicit proportional limit for the inter-ring gate."),
    ] = None,
    failure_category: FailureCategoryOption = None,
    material_provenance: MaterialProvenanceOption = None,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Calculate NASA ring-stiffened shell external-pressure response."""
    try:
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "ring-shell",
                "inputs": {
                    "external_pressure": _quantity_from_option(
                        external_pressure,
                        "external_pressure",
                    ),
                    "ring_axial_width": _quantity_from_option(
                        ring_axial_width,
                        "ring_axial_width",
                    ),
                    "ring_location": ring_location,
                    "ring_radial_height": _quantity_from_option(
                        ring_radial_height,
                        "ring_radial_height",
                    ),
                    "ring_spacing": _quantity_from_option(
                        ring_spacing,
                        "ring_spacing",
                    ),
                    "shell_mid_surface_radius": _quantity_from_option(
                        shell_mid_surface_radius,
                        "shell_mid_surface_radius",
                    ),
                    "unsupported_length": _quantity_from_option(
                        unsupported_length,
                        "unsupported_length",
                    ),
                    "wall_thickness": _quantity_from_option(
                        wall_thickness,
                        "wall_thickness",
                    ),
                },
                "material": _material_selection(
                    named_material=material,
                    yield_strength=yield_strength,
                    failure_category=failure_category,
                    material_provenance=material_provenance,
                    elastic_modulus=elastic_modulus,
                    poisson_ratio=poisson_ratio,
                    proportional_limit=proportional_limit,
                ),
            }
        request = _validate_request(RingShellRequest, raw)
        _emit(_evaluate_ring_shell(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@app.command(
    "mass-properties",
    epilog=(
        "Example: pv-calc mass-properties --input request.json --json"
    ),
)
def mass_properties(
    ctx: typer.Context,
    solid_volume: Annotated[
        str | None,
        typer.Option(help="Resolved structural material volume with unit, e.g. '2.5 L'."),
    ] = None,
    displaced_volume: Annotated[
        str | None,
        typer.Option(help="Resolved wetted-envelope volume with unit, e.g. '6 L'."),
    ] = None,
    fluid_density: Annotated[
        str | None,
        typer.Option(help="Fluid density with unit, e.g. '1025 kg/m^3'; no default."),
    ] = None,
    gravity: Annotated[
        str | None,
        typer.Option(help="Gravitational acceleration with unit, e.g. '9.81 m/s^2'; no default."),
    ] = None,
    material: MaterialOption = None,
    material_density: Annotated[
        str | None,
        typer.Option(help="Explicit material density with unit, e.g. '2700 kg/m^3'."),
    ] = None,
    material_provenance: MaterialProvenanceOption = None,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Calculate submerged mass and buoyancy for resolved volumes."""
    try:
        _ensure_file_input_is_exclusive(ctx)
        if input_path is not None:
            raw = _read_json_input(input_path)
        else:
            raw = {
                "schema_version": CALC_SCHEMA_VERSION,
                "model": "mass-properties",
                "inputs": {
                    "displaced_volume": _quantity_from_option(
                        displaced_volume,
                        "displaced_volume",
                    ),
                    "fluid_density": _quantity_from_option(
                        fluid_density,
                        "fluid_density",
                    ),
                    "gravity": _quantity_from_option(gravity, "gravity"),
                    "solid_volume": _quantity_from_option(
                        solid_volume,
                        "solid_volume",
                    ),
                },
                "material": _mass_material_selection(
                    named_material=material,
                    material_density=material_density,
                    material_provenance=material_provenance,
                ),
            }
        request = _validate_request(MassPropertiesRequest, raw)
        _emit(_evaluate_mass_properties(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@app.command(
    epilog=(
        "Example: pv-calc sweep --input request.json --json"
    ),
)
def sweep(
    pressure: Annotated[
        list[str] | None,
        typer.Option(
            "--pressure",
            help="Swept pressure with unit; repeat once per ordered axis point.",
        ),
    ] = None,
    pressure_start: Annotated[
        str | None,
        typer.Option(help="First swept pressure with unit."),
    ] = None,
    pressure_stop: Annotated[
        str | None,
        typer.Option(help="Last swept pressure with unit."),
    ] = None,
    pressure_count: Annotated[
        str | None,
        typer.Option(help="Number of evenly spaced points, at least 2."),
    ] = None,
    depth: Annotated[
        list[str] | None,
        typer.Option(
            "--depth",
            help="Swept depth with unit; repeat once per ordered axis point.",
        ),
    ] = None,
    depth_start: Annotated[
        str | None,
        typer.Option(help="First swept depth with unit."),
    ] = None,
    depth_stop: Annotated[
        str | None,
        typer.Option(help="Last swept depth with unit."),
    ] = None,
    depth_count: Annotated[
        str | None,
        typer.Option(help="Number of evenly spaced depths, at least 2."),
    ] = None,
    fluid_density: Annotated[
        str | None,
        typer.Option(help="Depth axis only: fluid density with unit; no default."),
    ] = None,
    gravity: Annotated[
        str | None,
        typer.Option(help="Depth axis only: gravitational acceleration with unit."),
    ] = None,
    design_factor: Annotated[
        str | None,
        typer.Option(help="Depth axis only: dimensionless factor on the service pressure."),
    ] = None,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON sweep request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Run one forward request over an ordered external-pressure or depth axis."""
    try:
        if input_path is None:
            raise CalcCliError(
                "missing_input",
                "sweep requires --input: the swept forward request has no"
                " command-line option surface",
            )
        raw = _read_json_input(input_path)
        inputs = _sweep_inputs_from_options(
            pressure_axis=_axis_from_options(
                name="pressure",
                values=pressure,
                start=pressure_start,
                stop=pressure_stop,
                count=pressure_count,
            ),
            depth_axis=_axis_from_options(
                name="depth",
                values=depth,
                start=depth_start,
                stop=depth_stop,
                count=depth_count,
            ),
            fluid_density=fluid_density,
            gravity=gravity,
            design_factor=design_factor,
        )
        if inputs is not None:
            if "inputs" in raw:
                raise CalcCliError(
                    "axis_source_conflict",
                    "choose exactly one sweep axis: the request's inputs or the"
                    " --pressure/--depth options",
                )
            raw = {**raw, "inputs": inputs}
        request = _validate_request(SweepRequest, raw)
        _emit(_evaluate_sweep(request, materials_file), compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


@app.command(
    "compare-materials",
    epilog=(
        "Example: pv-calc compare-materials --input request.json --json"
    ),
)
def compare_materials(
    material: Annotated[
        list[str] | None,
        typer.Option(
            "--material",
            help="Named --materials-file entry; repeat once per compared material, in order.",
        ),
    ] = None,
    input_path: Annotated[
        str | None,
        typer.Option("--input", help="JSON comparison request file, or '-' for stdin."),
    ] = None,
    materials_file: MaterialsFileOption = None,
    json_output: JsonOutputOption = False,
) -> None:
    """Run one fixed forward request against an ordered list of named materials."""
    try:
        if input_path is None:
            raise CalcCliError(
                "missing_input",
                "compare-materials requires --input: the compared forward"
                " request has no command-line option surface",
            )
        raw = _read_json_input(input_path)
        if material:
            existing_inputs = raw.get("inputs", {})
            if not isinstance(existing_inputs, dict):
                raise CalcCliError(
                    "invalid_request",
                    "compare-materials inputs must be an object",
                )
            if "materials" in existing_inputs:
                raise CalcCliError(
                    "material_source_conflict",
                    "choose exactly one material list: the request's inputs or"
                    " the --material options",
                )
            raw = {
                **raw,
                "inputs": {**existing_inputs, "materials": material},
            }
        request = _validate_request(MaterialComparisonRequest, raw)
        _emit(
            _evaluate_material_comparison(request, materials_file),
            compact=json_output,
        )
    except CalcCliError as exc:
        _exit_with_error(exc)


# The dimension of every unit-carrying option, by parameter name; a command's
# contract lists the ones its signature declares. Options that take a plain
# number (--poisson-ratio, --minimum-margin, --design-factor, counts) are not
# quantities and are absent, as they are from json_quantity_dimensions.
_OPTION_DIMENSIONS = {
    "axial_length": "length",
    "depth": "length",
    "depth_start": "length",
    "depth_stop": "length",
    "displaced_volume": "volume",
    "elastic_modulus": "pressure",
    "external_pressure": "pressure",
    "fluid_density": "density",
    "free_radius": "length",
    "gravity": "acceleration",
    "internal_radius": "length",
    "material_density": "density",
    "maximum_deflection": "length",
    "outside_radius": "length",
    "plate_thickness": "length",
    "plate_thickness_lower": "length",
    "plate_thickness_upper": "length",
    "pressure": "pressure",
    "pressure_start": "pressure",
    "pressure_stop": "pressure",
    "proportional_limit": "pressure",
    "ring_axial_width": "length",
    "ring_radial_height": "length",
    "ring_spacing": "length",
    "shell_mid_surface_radius": "length",
    "solid_volume": "volume",
    "ultimate_compressive_strength": "pressure",
    "ultimate_tensile_strength": "pressure",
    "unsupported_length": "length",
    "wall_thickness": "length",
    "wall_thickness_lower": "length",
    "wall_thickness_upper": "length",
    "working_strength": "pressure",
    "yield_strength": "pressure",
}


def _dimensioned_options(command: Callable[..., None]) -> dict[str, str]:
    """The unit-carrying options a command declares, as ``--name`` to dimension."""
    return {
        "--" + name.replace("_", "-"): _OPTION_DIMENSIONS[name]
        for name in inspect.signature(command).parameters
        if name in _OPTION_DIMENSIONS
    }


# The commands whose signatures each describe target's option maps are read from.
_DESCRIBED_COMMANDS: dict[str, tuple[Callable[..., None], Callable[..., None] | None]] = {
    "hemisphere": (hemisphere, None),
    "mass-properties": (mass_properties, None),
    "plate": (plate, plate_size),
    "ring-shell": (ring_shell, None),
    "smooth-buckling": (smooth_buckling, smooth_buckling_size),
    "tube": (tube, tube_size),
}


@app.command(epilog="Example: pv-calc describe hemisphere --json")
def describe(
    model: str,
    json_output: JsonOutputOption = False,
) -> None:
    """Describe a model's or operation's versioned machine-readable contract."""
    try:
        if model == "sweep":
            description = _describe_sweep(_dimensioned_options(sweep))
        elif model == "compare-materials":
            description = _describe_material_comparison()
        elif model in _DESCRIBED_COMMANDS:
            forward, size = _DESCRIBED_COMMANDS[model]
            description = _describe_model(
                model,
                cli_options=_dimensioned_options(forward),
                size_cli_options=None if size is None else _dimensioned_options(size),
            )
        else:
            description = _describe_model(model, cli_options={})
        _emit(description, compact=json_output)
    except CalcCliError as exc:
        _exit_with_error(exc)


if __name__ == "__main__":
    app()
