"""The JSON request and sizing-metadata contracts, their versions, and unit conversion."""

from __future__ import annotations

import math
import tokenize
from dataclasses import dataclass
from types import UnionType
from typing import (
    Annotated,
    Any,
    ClassVar,
    Final,
    Literal,
    TypeVar,
    Union,
    get_args,
    get_origin,
)

from pint.errors import PintError, UndefinedUnitError
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    ValidationError,
    model_validator,
)

from pv_calc.errors import CalcCliError
from pv_calc.schemas import MaterialFailureCategory
from pv_calc.units import Q_, dimensionless_factor, magnitude, unit_expression_problem

CALC_SCHEMA_VERSION = "5.0.0"
TUBE_SIZE_OPERATION_VERSION = "2.1.0"
# The tube's material check under the category's own criterion, named for the
# structural mode as the plate's flat_endcap_bending is; the selected forward
# result's failure_criterion says which stress met which strength.
TUBE_SIZING_CHECK: Final = "cylindrical_shell_stress"
TUBE_SIZING_CHECK_SET: tuple[Literal["cylindrical_shell_stress"], ...] = (TUBE_SIZING_CHECK,)
SMOOTH_BUCKLING_SIZE_OPERATION_VERSION = "2.1.0"
SMOOTH_BUCKLING_SIZING_CHECK_SET: tuple[
    Literal["cylindrical_shell_stress", "smooth_cylinder_buckling"], ...
] = (TUBE_SIZING_CHECK, "smooth_cylinder_buckling")
PLATE_SIZE_OPERATION_VERSION = "1.1.0"
# The plate's bending failure mode, and the caller's own serviceability limit.
# The second is declared only when the request carries a maximum deflection.
PLATE_SIZING_BENDING_CHECK = "flat_endcap_bending"
PLATE_SIZING_DEFLECTION_CHECK = "center_deflection"
# The tube stress kernel calculates one load case, closed-end hydrostatic, so
# the buckling check of the same wall uses the matching one; lateral_only would
# put a different axial load on the wall the shell stress check reads.
SMOOTH_BUCKLING_SIZING_LOAD_CASE: Final = "hydrostatic_closed_end"
# One cylinder, one thickness: the buckling model's shell mid-surface radius is
# the tube model's own mean radius at the same wall thickness.
SMOOTH_BUCKLING_SIZING_RADIUS_CONVENTION: Final = "internal_radius_plus_half_wall_thickness"
SWEEP_OPERATION_VERSION = "1.1.0"
# The forward models both multi-point operations accept.
FORWARD_MODELS = ("hemisphere", "plate", "ring-shell", "smooth-buckling", "tube")
SWEEP_SWEPT_INPUT = "inputs.external_pressure"
SWEEP_AXIS_VARIABLES = ("depth", "external_pressure")
# A depth axis drives the model with the design differential external pressure,
# not the service pressure; both are reported at every point.
SWEEP_DEPTH_SUBSTITUTED_PRESSURE = "design_external_pressure"
COMPARE_MATERIALS_OPERATION_VERSION = "1.0.0"
COMPARE_MATERIALS_SUBSTITUTED_INPUT = "request.material"
MAX_BATCH_POINTS = 1_000


NonBlankString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]
FiniteFloat = Annotated[float, Field(allow_inf_nan=False)]


class ContractModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class QuantityInput(ContractModel):
    value: FiniteFloat
    unit: NonBlankString


@dataclass(frozen=True)
class Dimension:
    """The physical dimension a quantity field carries, declared once on its type.

    ``quantity_dimensions`` reads it back for the ``describe`` contracts, so a
    quantity field without one has no contract entry and is refused there. A
    dimension on a nested field applies to every quantity below it, which is
    how one ``SweepAxis`` type serves both the pressure and the depth axis.
    """

    name: str


Pressure = Annotated[QuantityInput, Dimension("pressure")]
Length = Annotated[QuantityInput, Dimension("length")]
Density = Annotated[QuantityInput, Dimension("density")]
Acceleration = Annotated[QuantityInput, Dimension("acceleration")]
Volume = Annotated[QuantityInput, Dimension("volume")]

# Marks a nested request that is described by its own contract and is not
# walked for quantity dimensions.
OWN_CONTRACT = Dimension("own_contract")


class NamedMaterialInput(ContractModel):
    type: Literal["named"]
    name: NonBlankString


# The strengths each failure category carries: the first is required and is
# the strength every stress model compares against; a brittle record's
# ultimate tensile strength is optional and read by the plate alone.
CATEGORY_STRENGTHS: dict[MaterialFailureCategory, tuple[str, ...]] = {
    "ductile_metal": ("yield_strength",),
    "plastic": ("working_strength",),
    "brittle": ("ultimate_compressive_strength", "ultimate_tensile_strength"),
}
STRENGTH_FIELDS = tuple(name for names in CATEGORY_STRENGTHS.values() for name in names)


class TubeMaterialProperties(ContractModel):
    # A stress model compares against the category's strength, so it is
    # required here; the buckling models read elastic constants only and set
    # this False, still rejecting a strength another category carries.
    strength_required: ClassVar[bool] = True

    failure_category: MaterialFailureCategory
    yield_strength: Pressure | None = None
    working_strength: Pressure | None = None
    ultimate_tensile_strength: Pressure | None = None
    ultimate_compressive_strength: Pressure | None = None
    # Optional here and required in the subclasses below: the tube model reads
    # them only to release displacement, and a stress-only record stays valid.
    elastic_modulus: Pressure | None = None
    poisson_ratio: Annotated[float, Field(gt=0, lt=0.5, allow_inf_nan=False)] | None = None
    # Read only by the mass properties an ``inputs.submergence`` block asks for.
    density: Density | None = None

    @model_validator(mode="after")
    def strengths_match_failure_category(self) -> "TubeMaterialProperties":
        allowed = CATEGORY_STRENGTHS[self.failure_category]
        present = [name for name in STRENGTH_FIELDS if getattr(self, name) is not None]
        if self.strength_required and allowed[0] not in present:
            raise ValueError(f"{self.failure_category} requires {allowed[0]}")
        foreign = [name for name in present if name not in allowed]
        if foreign:
            raise ValueError(
                f"{self.failure_category} does not carry {', '.join(foreign)}; "
                f"it carries {', '.join(allowed)}"
            )
        return self


class PlateMaterialProperties(TubeMaterialProperties):
    elastic_modulus: Pressure
    poisson_ratio: Annotated[float, Field(gt=0, lt=0.5, allow_inf_nan=False)]


class HemisphereMaterialProperties(PlateMaterialProperties):
    proportional_limit: Pressure | None = None


class BucklingMaterialProperties(HemisphereMaterialProperties):
    """The smooth-buckling and ring-shell record: no strength is required.

    Buckling reads the elastic constants and the proportional limit; a yield
    strength, when a ductile metal carries one, only bounds that limit.
    """

    strength_required: ClassVar[bool] = False


class ExplicitTubeMaterialInput(ContractModel):
    type: Literal["explicit"]
    name: NonBlankString | None = None
    provenance: NonBlankString | None = None
    properties: TubeMaterialProperties


class ExplicitPlateMaterialInput(ExplicitTubeMaterialInput):
    properties: PlateMaterialProperties


class ExplicitHemisphereMaterialInput(ExplicitTubeMaterialInput):
    properties: HemisphereMaterialProperties


class ExplicitBucklingMaterialInput(ExplicitTubeMaterialInput):
    properties: BucklingMaterialProperties


class SubmergenceInputs(ContractModel):
    """The fluid a closed body sits in, for its mass properties and failure depths.

    With this block a forward response also carries ``mass_properties`` for the
    model's own closed-body volumes and the material density, and
    ``failure_depths``, each failure pressure expressed as the depth
    ``p / (rho * g)`` in this fluid. There is no fluid database, so both values
    are the caller's.
    """

    fluid_density: Density
    gravity: Acceleration


class TubeInputs(ContractModel):
    external_pressure: Pressure
    internal_radius: Length
    wall_thickness: Length
    # Gauge length over which the uniform far-field axial strain is integrated.
    # Optional: without it the axial strain is still reported. It is also the
    # tube length the submergence block's volumes need.
    axial_length: Length | None = None
    force_thick: bool = False
    submergence: SubmergenceInputs | None = None


class ThicknessBounds(ContractModel):
    lower: Length
    upper: Length


class TubeSizeInputs(ContractModel):
    external_pressure: Pressure
    internal_radius: Length
    wall_thickness_bounds: ThicknessBounds
    minimum_margin: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0
    force_thick: bool = False


class PlateInputs(ContractModel):
    external_pressure: Pressure
    free_radius: Length
    plate_thickness: Length
    boundary_condition: Literal["fixed", "simply_supported"]
    # Optional: releases the seat bearing stress on the annulus outside the
    # free radius, which is independent of thickness and so has no sizing role.
    # It is also the disc radius the submergence block's volumes need.
    outside_radius: Length | None = None
    submergence: SubmergenceInputs | None = None


class PlateSizeInputs(ContractModel):
    """One plate, sized on its thickness alone.

    ``minimum_margin`` is the bending target. ``maximum_deflection`` is a limit
    rather than a margin, so it is met at margin zero and is optional: without
    it the centre deflection constrains nothing and its own stricter evidence
    floor is never required.
    """

    external_pressure: Pressure
    free_radius: Length
    boundary_condition: Literal["fixed", "simply_supported"]
    plate_thickness_bounds: ThicknessBounds
    minimum_margin: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0
    maximum_deflection: Length | None = None


class TubeRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["tube"]
    inputs: TubeInputs
    material: Annotated[
        NamedMaterialInput | ExplicitTubeMaterialInput,
        Field(discriminator="type"),
    ]


class TubeSizeRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["tube"]
    operation: Literal["size"]
    inputs: TubeSizeInputs
    material: Annotated[
        NamedMaterialInput | ExplicitTubeMaterialInput,
        Field(discriminator="type"),
    ]


class PlateRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["plate"]
    inputs: PlateInputs
    material: Annotated[
        NamedMaterialInput | ExplicitPlateMaterialInput,
        Field(discriminator="type"),
    ]


class PlateSizeRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["plate"]
    operation: Literal["size"]
    inputs: PlateSizeInputs
    material: Annotated[
        NamedMaterialInput | ExplicitPlateMaterialInput,
        Field(discriminator="type"),
    ]


class SmoothBucklingInputs(ContractModel):
    external_pressure: Pressure
    shell_mid_surface_radius: Length
    wall_thickness: Length
    unsupported_length: Length
    load_case: Literal["lateral_only", "hydrostatic_closed_end"]
    submergence: SubmergenceInputs | None = None


class SmoothBucklingRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["smooth-buckling"]
    inputs: SmoothBucklingInputs
    material: Annotated[
        NamedMaterialInput | ExplicitBucklingMaterialInput,
        Field(discriminator="type"),
    ]


class SmoothBucklingSizeInputs(ContractModel):
    """One cylinder, sized on wall thickness alone.

    The internal radius, not the shell mid-surface radius, is the fixed one:
    the mid-surface radius moves with the wall thickness being solved for, and
    is ``internal_radius + wall_thickness / 2`` at every candidate, which is
    the tube model's own mean radius. The load case is not an input, because
    the shell stress check has only the closed-end hydrostatic one.
    """

    external_pressure: Pressure
    internal_radius: Length
    unsupported_length: Length
    wall_thickness_bounds: ThicknessBounds
    minimum_margin: Annotated[float, Field(ge=0, allow_inf_nan=False)] = 0.0


class SmoothBucklingSizeRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["smooth-buckling"]
    operation: Literal["size"]
    inputs: SmoothBucklingSizeInputs
    # The sizing operation's shell stress check reads the strength, so its record
    # is the hemisphere's strict one, not the forward buckling record.
    material: Annotated[
        NamedMaterialInput | ExplicitHemisphereMaterialInput,
        Field(discriminator="type"),
    ]


class HemisphereInputs(ContractModel):
    external_pressure: Pressure
    internal_radius: Length
    wall_thickness: Length
    force_thick: bool = False
    submergence: SubmergenceInputs | None = None


class HemisphereRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["hemisphere"]
    inputs: HemisphereInputs
    material: Annotated[
        NamedMaterialInput | ExplicitHemisphereMaterialInput,
        Field(discriminator="type"),
    ]


class RingShellInputs(ContractModel):
    external_pressure: Pressure
    shell_mid_surface_radius: Length
    wall_thickness: Length
    unsupported_length: Length
    ring_spacing: Length
    ring_axial_width: Length
    ring_radial_height: Length
    ring_location: Literal["internal", "external"]


class RingShellRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["ring-shell"]
    inputs: RingShellInputs
    material: Annotated[
        NamedMaterialInput | ExplicitBucklingMaterialInput,
        Field(discriminator="type"),
    ]


class MassPropertiesInputs(ContractModel):
    solid_volume: Volume
    displaced_volume: Volume
    fluid_density: Density
    gravity: Acceleration


class MassMaterialProperties(ContractModel):
    density: Density


class ExplicitMassMaterialInput(ContractModel):
    type: Literal["explicit"]
    name: NonBlankString | None = None
    provenance: NonBlankString | None = None
    properties: MassMaterialProperties


class MassPropertiesRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["mass-properties"]
    inputs: MassPropertiesInputs
    material: Annotated[
        NamedMaterialInput | ExplicitMassMaterialInput,
        Field(discriminator="type"),
    ]


class SweepAxisList(ContractModel):
    type: Literal["list"]
    values: Annotated[
        list[QuantityInput],
        Field(min_length=1, max_length=MAX_BATCH_POINTS),
    ]


class SweepAxisRange(ContractModel):
    type: Literal["range"]
    start: QuantityInput
    stop: QuantityInput
    count: Annotated[int, Field(ge=2, le=MAX_BATCH_POINTS)]


SweepAxis = Annotated[SweepAxisList | SweepAxisRange, Field(discriminator="type")]


class PressureSweepInputs(ContractModel):
    """An external-pressure axis: the axis value is the model's own input."""

    external_pressure: Annotated[SweepAxis, Dimension("pressure")]


class DepthSweepInputs(ContractModel):
    """A depth axis converted to pressure before the model runs.

    Each depth is converted by `pv_calc.hydrostatics.external_pressure_from_depth`
    with this fluid density, gravity, and design factor, and the resulting design
    differential external pressure is what the model is run at.
    """

    depth: Annotated[SweepAxis, Dimension("length")]
    fluid_density: Density
    gravity: Acceleration
    design_factor: Annotated[float, Field(gt=0, allow_inf_nan=False)]


# One complete forward request. The inverse tube sizing request is excluded
# because it carries an `operation` field this union forbids.
ForwardRequest = Annotated[
    TubeRequest
    | PlateRequest
    | SmoothBucklingRequest
    | HemisphereRequest
    | RingShellRequest,
    Field(discriminator="model"),
    OWN_CONTRACT,
]


class SweepRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["sweep"]
    # Exactly one axis. The two blocks share no field name and both forbid
    # extras, so the axis variable identifies the block without a tag field.
    inputs: PressureSweepInputs | DepthSweepInputs
    # The request's own inputs.external_pressure is replaced at every point.
    request: ForwardRequest


class MaterialComparisonInputs(ContractModel):
    """The ordered material list, and the volumes mass properties would need.

    Without ``mass_properties`` an entry carries the forward result alone; with
    it, the same volumes, fluid density, and gravity are used for every listed
    material, so the entries differ only by the material.
    """

    materials: Annotated[
        list[NonBlankString],
        Field(min_length=1, max_length=MAX_BATCH_POINTS),
    ]
    mass_properties: MassPropertiesInputs | None = None


class MaterialComparisonRequest(ContractModel):
    schema_version: Literal[CALC_SCHEMA_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    model: Literal["compare-materials"]
    inputs: MaterialComparisonInputs
    # The request's own `material` is replaced by every listed material.
    request: ForwardRequest


RequestType = TypeVar(
    "RequestType",
    TubeRequest,
    TubeSizeRequest,
    PlateRequest,
    PlateSizeRequest,
    SmoothBucklingRequest,
    SmoothBucklingSizeRequest,
    HemisphereRequest,
    RingShellRequest,
    MassPropertiesRequest,
    SweepRequest,
    MaterialComparisonRequest,
)


class MillimeterQuantity(ContractModel):
    value: FiniteFloat
    unit: Literal["mm"]


class NormalizedThicknessBounds(ContractModel):
    lower: MillimeterQuantity
    upper: MillimeterQuantity


class TubeSizingPoint(ContractModel):
    wall_thickness: MillimeterQuantity
    branch: Literal["thin", "thick"]
    governing_location: Literal["internal", "external", "mean"]
    check_margins: dict[str, FiniteFloat]
    minimum_margin: FiniteFloat


class TubeSizingBracket(ContractModel):
    lower: TubeSizingPoint
    upper: TubeSizingPoint
    wall_thickness_width: MillimeterQuantity


class TubeSizingStateChange(ContractModel):
    lower: TubeSizingPoint
    upper: TubeSizingPoint
    from_state: NonBlankString
    to_state: NonBlankString
    margin_jump: FiniteFloat


class TubeSizingMetadata(ContractModel):
    operation: Literal["wall_thickness_inverse_sizing"]
    operation_version: Literal[TUBE_SIZE_OPERATION_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    variable: Literal["wall_thickness"]
    declared_check_set: list[Literal["cylindrical_shell_stress"]]
    target_minimum_margin: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    bounds: NormalizedThicknessBounds
    selected_wall_thickness: MillimeterQuantity
    selected_check_margins: dict[str, FiniteFloat]
    selected_minimum_margin: FiniteFloat
    solution_type: Literal["lower_bound", "branch_start", "interior_root"]
    algorithm: Literal["known_branch_partition_and_bisection"]
    evaluation_count: Annotated[int, Field(ge=1)]
    bisection_iterations: Annotated[int, Field(ge=0)]
    wall_thickness_tolerance: MillimeterQuantity
    verified_bracket: TubeSizingBracket | None
    branch_changes: list[TubeSizingStateChange]
    governing_location_changes: list[TubeSizingStateChange]


SizingCheckName = Literal["cylindrical_shell_stress", "smooth_cylinder_buckling"]
BucklingRegimeName = Literal[
    "short",
    "moderate",
    "moderate_long_correlation_overlap",
    "long",
]


class SmoothBucklingSizingPoint(ContractModel):
    wall_thickness: MillimeterQuantity
    tube_branch: Literal["thin", "thick"]
    buckling_regime: BucklingRegimeName
    governing_check: SizingCheckName
    check_margins: dict[str, FiniteFloat]
    minimum_margin: FiniteFloat


class SmoothBucklingSizingBracket(ContractModel):
    lower: SmoothBucklingSizingPoint
    upper: SmoothBucklingSizingPoint
    wall_thickness_width: MillimeterQuantity


class SmoothBucklingSizingStateChange(ContractModel):
    lower: SmoothBucklingSizingPoint
    upper: SmoothBucklingSizingPoint
    from_state: NonBlankString
    to_state: NonBlankString
    margin_jump: FiniteFloat


class DerivedBranchBoundary(ContractModel):
    """One branch boundary, solved for the wall thickness that reaches it."""

    boundary: NonBlankString
    wall_thickness: MillimeterQuantity
    inside_bounds: bool


class SmoothBucklingSizingMetadata(ContractModel):
    operation: Literal["wall_thickness_inverse_sizing"]
    operation_version: Literal[SMOOTH_BUCKLING_SIZE_OPERATION_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    variable: Literal["wall_thickness"]
    declared_check_set: list[SizingCheckName]
    load_case: Literal["hydrostatic_closed_end"]
    shell_mid_surface_radius_convention: Literal[
        "internal_radius_plus_half_wall_thickness"
    ]
    target_minimum_margin: Annotated[float, Field(ge=0, allow_inf_nan=False)]
    bounds: NormalizedThicknessBounds
    selected_wall_thickness: MillimeterQuantity
    selected_shell_mid_surface_radius: MillimeterQuantity
    selected_check_margins: dict[str, FiniteFloat]
    selected_minimum_margin: FiniteFloat
    selected_governing_check: SizingCheckName
    solution_type: Literal["lower_bound", "branch_start", "interior_root"]
    algorithm: Literal["known_branch_partition_and_bisection"]
    evaluation_count: Annotated[int, Field(ge=1)]
    bisection_iterations: Annotated[int, Field(ge=0)]
    wall_thickness_tolerance: MillimeterQuantity
    derived_branch_partition: list[DerivedBranchBoundary]
    verified_bracket: SmoothBucklingSizingBracket | None
    tube_branch_changes: list[SmoothBucklingSizingStateChange]
    buckling_regime_changes: list[SmoothBucklingSizingStateChange]
    governing_check_changes: list[SmoothBucklingSizingStateChange]


PlateSizingCheckName = Literal["flat_endcap_bending", "center_deflection"]


class PlateSizingPoint(ContractModel):
    """One evaluated plate thickness, with both floors' ratio beside it.

    ``minimum_target_slack`` is the decision quantity, not ``check_margins``:
    the two checks carry different targets, so the smallest margin need not be
    the closest to binding one.
    """

    plate_thickness: MillimeterQuantity
    free_diameter_over_thickness: FiniteFloat
    governing_check: PlateSizingCheckName
    check_margins: dict[str, FiniteFloat]
    minimum_target_slack: FiniteFloat


class PlateSizingBracket(ContractModel):
    lower: PlateSizingPoint
    upper: PlateSizingPoint
    plate_thickness_width: MillimeterQuantity


class PlateSizingStateChange(ContractModel):
    lower: PlateSizingPoint
    upper: PlateSizingPoint
    from_state: NonBlankString
    to_state: NonBlankString
    # The change in the decision quantity, not in the smallest margin: the two
    # checks are measured against different targets.
    target_slack_jump: FiniteFloat


class PlateSizingMetadata(ContractModel):
    operation: Literal["plate_thickness_inverse_sizing"]
    operation_version: Literal[PLATE_SIZE_OPERATION_VERSION]  # type: ignore[valid-type]  # mypy has no Literal[<constant>]; pydantic reads it
    variable: Literal["plate_thickness"]
    boundary_condition: Literal["fixed", "simply_supported"]
    declared_check_set: list[PlateSizingCheckName]
    # One target per declared check: the bending margin the caller asked for,
    # and zero for the centre-deflection limit, which is a limit and not a
    # margin.
    check_targets: dict[str, FiniteFloat]
    maximum_deflection: MillimeterQuantity | None
    bounds: NormalizedThicknessBounds
    selected_plate_thickness: MillimeterQuantity
    selected_check_margins: dict[str, FiniteFloat]
    selected_governing_check: PlateSizingCheckName
    selected_minimum_target_slack: FiniteFloat
    solution_type: Literal["lower_bound", "branch_start", "interior_root"]
    algorithm: Literal["known_branch_partition_and_bisection"]
    evaluation_count: Annotated[int, Field(ge=1)]
    bisection_iterations: Annotated[int, Field(ge=0)]
    plate_thickness_tolerance: MillimeterQuantity
    verified_bracket: PlateSizingBracket | None
    governing_check_changes: list[PlateSizingStateChange]


def _validation_details(exc: ValidationError) -> list[dict[str, Any]]:
    return [
        {
            "location": [str(part) for part in item["loc"]],
            "message": item["msg"],
            "type": item["type"],
        }
        for item in exc.errors(include_context=False, include_input=False, include_url=False)
    ]


def _validate_request(
    model: type[RequestType], payload: dict[str, Any]
) -> RequestType:
    try:
        return model.model_validate(payload)
    except ValidationError as exc:
        details = _validation_details(exc)
        first = details[0]
        location = ".".join(first["location"])
        raise CalcCliError(
            "invalid_request",
            (
                f"input does not satisfy the pv-calc {CALC_SCHEMA_VERSION} schema: "
                f"{location}: {first['message']}"
            ),
            details,
        ) from exc


def quantity_dimensions(model: type[BaseModel]) -> dict[str, str]:
    """Every quantity path in a request model, dotted from its root, with its dimension.

    Unions contribute every member, lists their item type without an index,
    and a nested field marked ``OWN_CONTRACT`` is left to its own contract.
    A quantity reached without a ``Dimension`` in scope raises, so a new
    quantity field cannot enter a request without declaring one.
    """
    found: dict[str, str] = {}

    def walk(annotation: Any, path: str, dimension: str | None) -> None:
        origin = get_origin(annotation)
        if origin is Annotated:
            inner, *extras = get_args(annotation)
            if any(extra is OWN_CONTRACT for extra in extras):
                return
            for extra in extras:
                if isinstance(extra, Dimension):
                    dimension = extra.name
            walk(inner, path, dimension)
        elif origin is Union or origin is UnionType:
            for member in get_args(annotation):
                walk(member, path, dimension)
        elif origin is list:
            walk(get_args(annotation)[0], path, dimension)
        elif isinstance(annotation, type) and issubclass(annotation, BaseModel):
            if annotation is QuantityInput:
                if dimension is None:
                    raise TypeError(f"{path} is a quantity with no declared Dimension")
                found[path] = dimension
                return
            for name, field in annotation.model_fields.items():
                field_dimension = dimension
                if any(extra is OWN_CONTRACT for extra in field.metadata):
                    continue
                for extra in field.metadata:
                    if isinstance(extra, Dimension):
                        field_dimension = extra.name
                walk(field.annotation, f"{path}.{name}" if path else name, field_dimension)

    walk(model, "", None)
    return found


def _to_unit(quantity: QuantityInput, unit: str, field_name: str) -> float:
    # The same unit-expression screen the CLI option path applies: a JSON
    # magnitude is a number by construction, but the unit string would still
    # reach pint's expression evaluator, which silently normalizes commas,
    # factor-1 scales, and named constants, and raises bare tracebacks on
    # 'mm/0', 'mm^0', or an unbalanced bracket.
    problem = unit_expression_problem(quantity.unit)
    if problem is not None:
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} unit {problem}",
            [{"location": field_name, "unit": quantity.unit}],
        )
    try:
        parsed = Q_(quantity.value, quantity.unit)
        hidden_factor = dimensionless_factor(parsed)
        normalized_value = magnitude(parsed, unit)
    except OverflowError as exc:
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} must convert to a finite value in {unit}",
            [{"location": field_name, "unit": quantity.unit}],
        ) from exc
    except (ArithmeticError, KeyError, tokenize.TokenError) as exc:
        detail = str(exc).strip().rstrip(".")
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} unit is not a readable unit expression"
            + (f": {detail}" if detail else ""),
            [{"location": field_name, "unit": quantity.unit}],
        ) from exc
    except UndefinedUnitError as exc:
        # An unknown unit name (kg/m3, gee) is an invalid quantity, not an
        # incompatible one; only a defined unit has a dimension to compare.
        detail = str(exc).strip().rstrip(".")
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} unit names an unknown unit"
            + (f": {detail}" if detail else ""),
            [{"location": field_name, "unit": quantity.unit}],
        ) from exc
    except (AssertionError, PintError, TypeError, ValueError) as exc:
        raise CalcCliError(
            "incompatible_unit",
            f"{field_name} must have units compatible with {unit}",
            [{"location": field_name, "unit": quantity.unit}],
        ) from exc
    if hidden_factor is not None:
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} unit names '{hidden_factor}', which is a number, not a unit",
            [{"location": field_name, "unit": quantity.unit}],
        )
    if not math.isfinite(normalized_value):
        raise CalcCliError(
            "invalid_quantity",
            f"{field_name} must convert to a finite value in {unit}",
            [{"location": field_name, "unit": quantity.unit}],
        )
    return normalized_value


def _quantity(
    value: float | tuple[float, ...] | list[float] | None,
    unit: str,
) -> dict[str, Any]:
    return {"value": value, "unit": unit}


def _millimeters(value: float) -> MillimeterQuantity:
    return MillimeterQuantity(value=value, unit="mm")
