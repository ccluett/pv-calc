"""The bounded thickness sizing operations: tube, plate, and smooth-buckling size."""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal, cast

from pv_calc.contracts import (
    CALC_SCHEMA_VERSION,
    PLATE_SIZE_OPERATION_VERSION,
    PLATE_SIZING_BENDING_CHECK,
    PLATE_SIZING_DEFLECTION_CHECK,
    SMOOTH_BUCKLING_SIZE_OPERATION_VERSION,
    SMOOTH_BUCKLING_SIZING_CHECK_SET,
    SMOOTH_BUCKLING_SIZING_LOAD_CASE,
    SMOOTH_BUCKLING_SIZING_RADIUS_CONVENTION,
    TUBE_SIZE_OPERATION_VERSION,
    TUBE_SIZING_CHECK,
    TUBE_SIZING_CHECK_SET,
    DerivedBranchBoundary,
    NormalizedThicknessBounds,
    PlateSizeRequest,
    PlateSizingBracket,
    PlateSizingCheckName,
    PlateSizingMetadata,
    PlateSizingPoint,
    PlateSizingStateChange,
    SizingCheckName,
    SmoothBucklingSizeRequest,
    SmoothBucklingSizingBracket,
    SmoothBucklingSizingMetadata,
    SmoothBucklingSizingPoint,
    SmoothBucklingSizingStateChange,
    TubeSizeRequest,
    TubeSizingBracket,
    TubeSizingMetadata,
    TubeSizingPoint,
    TubeSizingStateChange,
    _millimeters,
    _quantity,
    _to_unit,
)
from pv_calc.errors import CalcCliError
from pv_calc.evaluate import (
    _calculate_plate_result,
    _calculate_smooth_buckling_result,
    _calculate_tube_result,
)
from pv_calc.pressure_vessel import (
    SMOOTH_CYLINDER_MIN_RADIUS_THICKNESS_RATIO,
    SMOOTH_CYLINDER_PLASTICITY_PENDING_REASON,
    TUBE_THIN_WALL_MEAN_RADIUS_RATIO,
    FlatCircularPlateResult,
    SmoothCylinderBucklingResult,
    TubeStressResult,
)
from pv_calc.resolve import ResolvedMaterial, _resolve_material
from pv_calc.serialize import _json_text, _response, _serialize_result

_SIZING_MAX_BISECTION_ITERATIONS = 100
_SIZING_RELATIVE_THICKNESS_TOLERANCE = 1.0e-9
_SIZING_ABSOLUTE_THICKNESS_TOLERANCE_MM = 1.0e-9
_SIZING_MARGIN_COMPARISON_TOLERANCE = 1.0e-12
# A derived branch boundary is a real number; the branch a kernel reports flips
# at a representable one. Only a few units in the last place separate the two,
# and a boundary that moves no branch within that window does not split these
# bounds at all.
_SIZING_MAX_BRANCH_SNAP_STEPS = 8


@dataclass(frozen=True)
class _SizingSample:
    """One evaluated thickness, with the labels the solver reasons on.

    ``branch`` names the continuous piece the sample sits on: the solver splits
    the bounds where it changes, brackets only inside one piece, and requires
    every check to rise against its target along each piece. ``states`` carries
    every reported label, that one included, so a change in any of them is
    reported even when it moves no branch.
    """

    thickness_mm: float
    branch: str
    states: dict[str, str]
    check_margins: dict[str, float]

    @property
    def minimum_margin(self) -> float:
        return min(self.check_margins.values())


def _target_slack(sample: _SizingSample, check_targets: Mapping[str, float]) -> float:
    """How far the closest-to-binding check sits above its own target margin.

    Each declared check carries its own target because they are not all
    margins: a plate's caller-supplied centre-deflection limit is a limit, met
    at margin zero, while a bending target is a margin. Where every target is
    the same number this is the minimum margin shifted by it, which is what
    both wall-thickness operations ask for.
    """
    return min(
        margin - check_targets[name] for name, margin in sample.check_margins.items()
    )


@dataclass(frozen=True)
class _SizingStateChange:
    """Two adjacent samples that report different values of one state."""

    lower: _SizingSample
    upper: _SizingSample
    from_state: str
    to_state: str

    @property
    def margin_jump(self) -> float:
        return self.upper.minimum_margin - self.lower.minimum_margin


@dataclass(frozen=True)
class _SizingSolution:
    """The thickness the shared solver selected, and its evidence."""

    selected: _SizingSample
    solution_type: Literal["lower_bound", "branch_start", "interior_root"]
    bracket: tuple[_SizingSample, _SizingSample] | None
    samples: tuple[_SizingSample, ...]
    bisection_iterations: int
    thickness_tolerance_mm: float


def _sizing_state_changes(
    samples: Sequence[_SizingSample],
    state_name: str,
) -> list[_SizingStateChange]:
    changes: list[_SizingStateChange] = []
    for lower, upper in zip(samples, samples[1:]):
        from_state = lower.states[state_name]
        to_state = upper.states[state_name]
        if from_state == to_state:
            continue
        changes.append(
            _SizingStateChange(
                lower=lower,
                upper=upper,
                from_state=from_state,
                to_state=to_state,
            )
        )
    return changes


def _branch_split(
    *,
    boundary_mm: float,
    branch: str,
    lower_mm: float,
    upper_mm: float,
    sample: Callable[[float], _SizingSample],
) -> tuple[float, float] | None:
    """Place a derived branch boundary on the representable values around it.

    Returns the last thickness still on ``branch`` and the first past it, or
    None when no branch change is observed within a few units in the last place
    of the derived boundary, which means it separates nothing inside these
    bounds. Subtracting a fixed epsilon can skip a valid solution on the low
    side, and one nextafter is not always enough for a given floating-point
    radius, so the walk is stepwise in both directions.
    """
    low_mm = boundary_mm
    for _ in range(_SIZING_MAX_BRANCH_SNAP_STEPS):
        if sample(low_mm).branch == branch:
            break
        low_mm = math.nextafter(low_mm, -math.inf)
        if low_mm <= lower_mm:
            return None
    else:
        return None
    high_mm = math.nextafter(low_mm, math.inf)
    for _ in range(_SIZING_MAX_BRANCH_SNAP_STEPS):
        if high_mm >= upper_mm:
            return None
        if sample(high_mm).branch != branch:
            return low_mm, high_mm
        high_mm = math.nextafter(high_mm, math.inf)
    return None


def _validate_thickness_bounds(
    lower_bound_mm: float,
    upper_bound_mm: float,
    *,
    variable: str,
) -> None:
    if (
        not math.isfinite(lower_bound_mm)
        or not math.isfinite(upper_bound_mm)
        or lower_bound_mm <= 0
        or upper_bound_mm <= lower_bound_mm
    ):
        raise CalcCliError(
            "invalid_bounds",
            f"{variable} bounds must be finite and positive, with lower less than upper",
            [
                {
                    "lower": _quantity(lower_bound_mm, "mm"),
                    "upper": _quantity(upper_bound_mm, "mm"),
                }
            ],
        )


def _solve_thickness(
    *,
    lower_bound_mm: float,
    upper_bound_mm: float,
    bounds_variable: str,
    check_targets: Mapping[str, float],
    evaluate: Callable[[float], _SizingSample],
    partition_thicknesses: Sequence[float],
    branch_label: str,
    failure_details: Callable[[tuple[_SizingSample, ...]], list[dict[str, Any]]],
) -> _SizingSolution:
    """Select the smallest thickness inside the bounds that meets every target.

    The lower bound wins outright when it already meets every check's own
    target, before anything else is evaluated. Otherwise the bounds are split
    at every supplied branch-boundary thickness so that each interval carries
    one continuous branch, and the intervals are walked in ascending thickness
    until one either opens at a thickness that already meets them or has
    failing and passing ends, which is bisected.
    The slack against those targets is only assumed monotonic inside a branch,
    and that assumption is checked against every evaluated sample before a
    solution is returned.
    """
    _validate_thickness_bounds(
        lower_bound_mm,
        upper_bound_mm,
        variable=bounds_variable,
    )

    thickness_tolerance = max(
        _SIZING_ABSOLUTE_THICKNESS_TOLERANCE_MM,
        _SIZING_RELATIVE_THICKNESS_TOLERANCE
        * max(abs(lower_bound_mm), abs(upper_bound_mm)),
    )
    cache: dict[float, _SizingSample] = {}

    def sample(thickness_mm: float) -> _SizingSample:
        cached = cache.get(thickness_mm)
        if cached is not None:
            return cached
        evaluated = evaluate(thickness_mm)
        cache[thickness_mm] = evaluated
        return evaluated

    def slack(evaluated: _SizingSample) -> float:
        return _target_slack(evaluated, check_targets)

    def ordered() -> tuple[_SizingSample, ...]:
        return tuple(sorted(cache.values(), key=lambda item: item.thickness_mm))

    lower_sample = sample(lower_bound_mm)

    solution_type: Literal["lower_bound", "branch_start", "interior_root"]
    bracket: tuple[_SizingSample, _SizingSample] | None = None
    bisection_iterations = 0
    if slack(lower_sample) >= 0.0:
        # The winning lower bound is the whole answer, so nothing above it is
        # evaluated: an upper bound or a partition probe the models cannot
        # answer for must not fail a search whose result never depends on it.
        selected = lower_sample
        solution_type = "lower_bound"
    else:
        # Evaluated up front so a bound the models cannot answer for fails
        # before any partitioning or bisection depends on it.
        sample(upper_bound_mm)

        intervals: list[tuple[float, float]] = []
        interval_lower_mm = lower_bound_mm
        interval_branch = lower_sample.branch
        for boundary_mm in sorted(set(partition_thicknesses)):
            if not interval_lower_mm < boundary_mm < upper_bound_mm:
                continue
            split = _branch_split(
                boundary_mm=boundary_mm,
                branch=interval_branch,
                lower_mm=interval_lower_mm,
                upper_mm=upper_bound_mm,
                sample=sample,
            )
            if split is None:
                continue
            interval_upper_mm, next_lower_mm = split
            intervals.append((interval_lower_mm, interval_upper_mm))
            interval_lower_mm = next_lower_mm
            interval_branch = sample(next_lower_mm).branch
        intervals.append((interval_lower_mm, upper_bound_mm))

        opening_sample: _SizingSample | None = None
        candidate_bracket: tuple[_SizingSample, _SizingSample] | None = None
        for lower_mm, upper_mm in intervals:
            interval_lower = sample(lower_mm)
            interval_upper = sample(upper_mm)
            # Capacity can jump at a boundary, so a branch can open above every
            # target where the branch below it closed short of one, and there is
            # no root to bracket. Reaching this interval leaves both ends of
            # every earlier one failing, and the slack rises inside a branch, so
            # nothing below this thickness meets the targets and it is the
            # smallest that does.
            if slack(interval_lower) >= 0.0:
                opening_sample = interval_lower
                break
            if slack(interval_upper) >= 0.0:
                candidate_bracket = (interval_lower, interval_upper)
                break

        if opening_sample is not None:
            selected = opening_sample
            solution_type = "branch_start"
        elif candidate_bracket is None:
            raise CalcCliError(
                "no_reliable_solution",
                f"no fail/pass margin bracket exists within the supplied {bounds_variable} bounds",
                failure_details(ordered()),
            )
        else:
            solution_type = "interior_root"
            bracket_lower, bracket_upper = candidate_bracket
            for iteration in range(1, _SIZING_MAX_BISECTION_ITERATIONS + 1):
                if (
                    bracket_upper.thickness_mm - bracket_lower.thickness_mm
                    <= thickness_tolerance
                ):
                    break
                midpoint = bracket_lower.thickness_mm + (
                    bracket_upper.thickness_mm - bracket_lower.thickness_mm
                ) / 2.0
                middle = sample(midpoint)
                if slack(middle) >= 0.0:
                    bracket_upper = middle
                else:
                    bracket_lower = middle
                bisection_iterations = iteration
            selected = bracket_upper
            bracket = (bracket_lower, bracket_upper)

    samples = ordered()
    if any(
        low.branch == high.branch
        and slack(high) + _SIZING_MARGIN_COMPARISON_TOLERANCE < slack(low)
        for low, high in zip(samples, samples[1:])
    ):
        raise CalcCliError(
            "no_reliable_solution",
            f"evaluated margin decreased against its target within a continuous {branch_label}",
            failure_details(samples),
        )
    return _SizingSolution(
        selected=selected,
        solution_type=solution_type,
        bracket=bracket,
        samples=samples,
        bisection_iterations=bisection_iterations,
        thickness_tolerance_mm=thickness_tolerance,
    )


def _tube_governing_location(
    result: TubeStressResult,
) -> Literal["internal", "external", "mean"]:
    governing = next(
        state for state in result.stress_states if state.radius_mm == result.governing_radius_mm
    )
    return governing.radius_convention


def _tube_sizing_sample(result: TubeStressResult) -> _SizingSample:
    return _SizingSample(
        thickness_mm=result.wall_thickness_mm,
        branch=result.branch,
        states={
            "branch": result.branch,
            "governing_location": _tube_governing_location(result),
        },
        check_margins={TUBE_SIZING_CHECK: result.margin},
    )


def _tube_sizing_point(sample: _SizingSample) -> TubeSizingPoint:
    # The sample's states dict erases the kernel's Literal types; restore them.
    return TubeSizingPoint(
        wall_thickness=_millimeters(sample.thickness_mm),
        branch=cast(Literal["thin", "thick"], sample.states["branch"]),
        governing_location=cast(
            Literal["internal", "external", "mean"],
            sample.states["governing_location"],
        ),
        check_margins=dict(sample.check_margins),
        minimum_margin=sample.minimum_margin,
    )


def _tube_state_changes(
    samples: Sequence[_SizingSample],
    *,
    state_name: Literal["branch", "governing_location"],
) -> list[TubeSizingStateChange]:
    return [
        TubeSizingStateChange(
            lower=_tube_sizing_point(change.lower),
            upper=_tube_sizing_point(change.upper),
            from_state=change.from_state,
            to_state=change.to_state,
            margin_jump=change.margin_jump,
        )
        for change in _sizing_state_changes(samples, state_name)
    ]


def _tube_sizing_error_details(
    *,
    lower_bound_mm: float,
    upper_bound_mm: float,
    target_minimum_margin: float,
    samples: tuple[_SizingSample, ...],
) -> list[dict[str, Any]]:
    by_thickness = {sample.thickness_mm: sample for sample in samples}
    return [
        {
            "variable": "wall_thickness",
            "declared_check_set": list(TUBE_SIZING_CHECK_SET),
            "target_minimum_margin": target_minimum_margin,
            "bounds": {
                "lower": _millimeters(lower_bound_mm).model_dump(mode="json"),
                "upper": _millimeters(upper_bound_mm).model_dump(mode="json"),
            },
            "lower_evaluation": _tube_sizing_point(
                by_thickness[lower_bound_mm]
            ).model_dump(mode="json"),
            "upper_evaluation": _tube_sizing_point(
                by_thickness[upper_bound_mm]
            ).model_dump(mode="json"),
            "branch_changes": [
                change.model_dump(mode="json")
                for change in _tube_state_changes(samples, state_name="branch")
            ],
            "governing_location_changes": [
                change.model_dump(mode="json")
                for change in _tube_state_changes(
                    samples,
                    state_name="governing_location",
                )
            ],
        }
    ]


def _solve_tube_wall_thickness(
    *,
    external_pressure_mpa: float,
    internal_radius_mm: float,
    lower_bound_mm: float,
    upper_bound_mm: float,
    target_minimum_margin: float,
    material: ResolvedMaterial,
    force_thick: bool,
) -> tuple[TubeStressResult, TubeSizingMetadata]:
    results: dict[float, TubeStressResult] = {}

    def evaluate(wall_thickness_mm: float) -> _SizingSample:
        try:
            result = _calculate_tube_result(
                external_pressure_mpa=external_pressure_mpa,
                internal_radius_mm=internal_radius_mm,
                wall_thickness_mm=wall_thickness_mm,
                material=material,
                force_thick=force_thick,
            )
            # Admit only forward results that the final JSON response can emit.
            _json_text({"result": _serialize_result(result)}, compact=True)
        except (TypeError, ValueError) as exc:
            raise CalcCliError("unevaluable_model", str(exc)) from exc
        results[wall_thickness_mm] = result
        return _tube_sizing_sample(result)

    # The current tube model has one known discontinuity, where its own branch
    # rule puts the mean-radius to thickness ratio at the thin-wall limit:
    # r_m = r_i + t/2, so r_m/t = limit at t = r_i / (limit - 0.5). Holding the
    # thick branch with ``force_thick`` removes the discontinuity entirely.
    # The margin steps down across it by a constant factor, never up, so the
    # thick branch cannot open already meeting a target the thin one missed:
    # the shared solver's "branch_start" is unreachable here.
    branch_transition_mm = internal_radius_mm / (
        TUBE_THIN_WALL_MEAN_RADIUS_RATIO - 0.5
    )
    solution = _solve_thickness(
        lower_bound_mm=lower_bound_mm,
        upper_bound_mm=upper_bound_mm,
        bounds_variable="wall-thickness",
        check_targets=dict.fromkeys(TUBE_SIZING_CHECK_SET, target_minimum_margin),
        evaluate=evaluate,
        partition_thicknesses=() if force_thick else (branch_transition_mm,),
        branch_label="tube branch",
        failure_details=lambda samples: _tube_sizing_error_details(
            lower_bound_mm=lower_bound_mm,
            upper_bound_mm=upper_bound_mm,
            target_minimum_margin=target_minimum_margin,
            samples=samples,
        ),
    )

    verified_bracket = None
    if solution.bracket is not None:
        bracket_lower, bracket_upper = solution.bracket
        verified_bracket = TubeSizingBracket(
            lower=_tube_sizing_point(bracket_lower),
            upper=_tube_sizing_point(bracket_upper),
            wall_thickness_width=_millimeters(
                bracket_upper.thickness_mm - bracket_lower.thickness_mm
            ),
        )
    metadata = TubeSizingMetadata(
        operation="wall_thickness_inverse_sizing",
        operation_version=TUBE_SIZE_OPERATION_VERSION,
        variable="wall_thickness",
        declared_check_set=list(TUBE_SIZING_CHECK_SET),
        target_minimum_margin=target_minimum_margin,
        bounds=NormalizedThicknessBounds(
            lower=_millimeters(lower_bound_mm),
            upper=_millimeters(upper_bound_mm),
        ),
        selected_wall_thickness=_millimeters(solution.selected.thickness_mm),
        selected_check_margins=dict(solution.selected.check_margins),
        selected_minimum_margin=solution.selected.minimum_margin,
        solution_type=solution.solution_type,
        algorithm="known_branch_partition_and_bisection",
        evaluation_count=len(solution.samples),
        bisection_iterations=solution.bisection_iterations,
        wall_thickness_tolerance=_millimeters(solution.thickness_tolerance_mm),
        verified_bracket=verified_bracket,
        branch_changes=_tube_state_changes(solution.samples, state_name="branch"),
        governing_location_changes=_tube_state_changes(
            solution.samples,
            state_name="governing_location",
        ),
    )
    return results[solution.selected.thickness_mm], metadata


def _evaluate_tube_size(request: TubeSizeRequest, materials_file: Path | None) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    lower_bound_mm = _to_unit(
        request.inputs.wall_thickness_bounds.lower,
        "mm",
        "inputs.wall_thickness_bounds.lower",
    )
    upper_bound_mm = _to_unit(
        request.inputs.wall_thickness_bounds.upper,
        "mm",
        "inputs.wall_thickness_bounds.upper",
    )
    result, sizing = _solve_tube_wall_thickness(
        external_pressure_mpa=_to_unit(
            request.inputs.external_pressure,
            "MPa",
            "inputs.external_pressure",
        ),
        internal_radius_mm=_to_unit(
            request.inputs.internal_radius,
            "mm",
            "inputs.internal_radius",
        ),
        lower_bound_mm=lower_bound_mm,
        upper_bound_mm=upper_bound_mm,
        target_minimum_margin=request.inputs.minimum_margin,
        material=material,
        force_thick=request.inputs.force_thick,
    )
    response = _response(
        model="tube",
        result=result,
        material=material,
        function="closed_end_tube_stress",
        module="pv_calc.pressure_vessel",
    )
    response.update(
        {
            "operation": "size",
            "sizing": sizing.model_dump(mode="json"),
        }
    )
    return response


def _plate_sizing_point(
    sample: _SizingSample,
    *,
    results: Mapping[float, FlatCircularPlateResult],
    check_targets: Mapping[str, float],
) -> PlateSizingPoint:
    return PlateSizingPoint(
        plate_thickness=_millimeters(sample.thickness_mm),
        # The ratio both evidence floors are stated against, reported so a
        # point can be placed against them without re-running the model.
        free_diameter_over_thickness=results[
            sample.thickness_mm
        ].free_diameter_over_thickness,
        # The sample's states dict erases the kernel's Literal type; restore it.
        governing_check=cast(PlateSizingCheckName, sample.states["governing_check"]),
        check_margins=dict(sample.check_margins),
        minimum_target_slack=_target_slack(sample, check_targets),
    )


def _plate_governing_check_changes(
    samples: Sequence[_SizingSample],
    *,
    results: Mapping[float, FlatCircularPlateResult],
    check_targets: Mapping[str, float],
) -> list[PlateSizingStateChange]:
    return [
        PlateSizingStateChange(
            lower=_plate_sizing_point(
                change.lower,
                results=results,
                check_targets=check_targets,
            ),
            upper=_plate_sizing_point(
                change.upper,
                results=results,
                check_targets=check_targets,
            ),
            from_state=change.from_state,
            to_state=change.to_state,
            target_slack_jump=(
                _target_slack(change.upper, check_targets)
                - _target_slack(change.lower, check_targets)
            ),
        )
        for change in _sizing_state_changes(samples, "governing_check")
    ]


def _plate_sizing_sample(
    result: FlatCircularPlateResult,
    *,
    maximum_deflection_mm: float | None,
    check_targets: Mapping[str, float],
) -> _SizingSample:
    # Only reached for released outputs; the caller refuses a thickness that
    # withholds a needed one.
    if result.margin is None:
        raise CalcCliError(
            "unevaluable_model",
            "released plate bending margin is required for sizing",
        )
    check_margins = {PLATE_SIZING_BENDING_CHECK: result.margin}
    if maximum_deflection_mm is not None:
        # The margin keeps the allowable/actual - 1 form the kernels use, here
        # against the caller's own limit rather than a material strength.
        actual_deflection_mm = result.released_maximum_deflection_mm
        if (
            actual_deflection_mm is None
            or not math.isfinite(actual_deflection_mm)
            or actual_deflection_mm <= 0.0
        ):
            raise CalcCliError(
                "unevaluable_model",
                "released plate deflection must be finite and positive for sizing",
            )
        deflection_margin = maximum_deflection_mm / actual_deflection_mm - 1.0
        if not math.isfinite(deflection_margin):
            raise CalcCliError(
                "unevaluable_model",
                "plate deflection margin cannot be represented as a finite number",
            )
        check_margins[PLATE_SIZING_DEFLECTION_CHECK] = deflection_margin
    return _SizingSample(
        thickness_mm=result.plate_thickness_mm,
        # Both margins are smooth and rising in thickness across the whole
        # released band — the bending stress goes as (a/t)^2 and the deflection
        # as 1/t^3, with coefficients that depend on the Poisson ratio and the
        # edge alone — so the bounds are one continuous piece and there is no
        # branch to partition at. The evidence floors are refusal conditions,
        # not branch boundaries: they withhold an output rather than move the
        # margin.
        branch="released",
        states={
            "governing_check": min(
                check_targets,
                key=lambda name: (check_margins[name] - check_targets[name], name),
            )
        },
        check_margins=check_margins,
    )


def _plate_withheld_details(
    result: FlatCircularPlateResult,
    *,
    withheld: Sequence[str],
    reasons: Sequence[str],
) -> list[dict[str, Any]]:
    return [
        {
            "plate_thickness": _quantity(result.plate_thickness_mm, "mm"),
            "free_diameter_over_thickness": result.free_diameter_over_thickness,
            "withheld_outputs": list(withheld),
            "withheld_reasons": list(reasons),
            "bending_minimum_free_diameter_over_thickness": (
                result.bending_minimum_free_diameter_over_thickness
            ),
            "deflection_minimum_free_diameter_over_thickness": (
                result.deflection_minimum_free_diameter_over_thickness
            ),
            "shear_corrected_deflection_estimate_over_thickness": (
                result.shear_corrected_deflection_estimate_over_thickness
            ),
        }
    ]


def _plate_sizing_error_details(
    *,
    lower_bound_mm: float,
    upper_bound_mm: float,
    check_targets: Mapping[str, float],
    results: Mapping[float, FlatCircularPlateResult],
    samples: tuple[_SizingSample, ...],
) -> list[dict[str, Any]]:
    by_thickness = {sample.thickness_mm: sample for sample in samples}

    def point(thickness_mm: float) -> dict[str, Any]:
        return _plate_sizing_point(
            by_thickness[thickness_mm],
            results=results,
            check_targets=check_targets,
        ).model_dump(mode="json")

    return [
        {
            "variable": "plate_thickness",
            "declared_check_set": list(check_targets),
            "check_targets": dict(check_targets),
            "bounds": {
                "lower": _millimeters(lower_bound_mm).model_dump(mode="json"),
                "upper": _millimeters(upper_bound_mm).model_dump(mode="json"),
            },
            "lower_evaluation": point(lower_bound_mm),
            "upper_evaluation": point(upper_bound_mm),
            "governing_check_changes": [
                change.model_dump(mode="json")
                for change in _plate_governing_check_changes(
                    samples,
                    results=results,
                    check_targets=check_targets,
                )
            ],
        }
    ]


def _evaluate_plate_size(
    request: PlateSizeRequest,
    materials_file: Path | None,
) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    # Fail fast, before bounds validation: every sample reads these constants.
    material.elastic_constants_mpa("plate")
    external_pressure_mpa = _to_unit(
        request.inputs.external_pressure,
        "MPa",
        "inputs.external_pressure",
    )
    free_radius_mm = _to_unit(request.inputs.free_radius, "mm", "inputs.free_radius")
    lower_bound_mm = _to_unit(
        request.inputs.plate_thickness_bounds.lower,
        "mm",
        "inputs.plate_thickness_bounds.lower",
    )
    upper_bound_mm = _to_unit(
        request.inputs.plate_thickness_bounds.upper,
        "mm",
        "inputs.plate_thickness_bounds.upper",
    )
    boundary_condition = request.inputs.boundary_condition
    maximum_deflection_mm: float | None = None
    check_targets = {PLATE_SIZING_BENDING_CHECK: request.inputs.minimum_margin}
    if request.inputs.maximum_deflection is not None:
        maximum_deflection_mm = _to_unit(
            request.inputs.maximum_deflection,
            "mm",
            "inputs.maximum_deflection",
        )
        if maximum_deflection_mm <= 0.0:
            raise CalcCliError(
                "invalid_request",
                "inputs.maximum_deflection must be positive",
                [{"location": "inputs.maximum_deflection"}],
            )
        # A limit, not a margin: it is met exactly at margin zero.
        check_targets[PLATE_SIZING_DEFLECTION_CHECK] = 0.0

    results: dict[float, FlatCircularPlateResult] = {}

    def evaluate(plate_thickness_mm: float) -> _SizingSample:
        result = _calculate_plate_result(
            external_pressure_mpa=external_pressure_mpa,
            free_radius_mm=free_radius_mm,
            plate_thickness_mm=plate_thickness_mm,
            material=material,
            boundary_condition=boundary_condition,
        )
        try:
            # Admit only forward results that the final JSON response can emit.
            _json_text({"result": _serialize_result(result)}, compact=True)
        except (TypeError, ValueError) as exc:
            raise CalcCliError("unevaluable_model", str(exc)) from exc

        # The two outputs carry separate evidence floors and both floors move
        # with the thickness, so they are re-read at every candidate rather
        # than resolved once. Only the outputs this request needs are required:
        # without a deflection limit the stricter deflection floor never
        # decides anything.
        withheld: list[str] = []
        reasons: list[str] = []
        if result.bending_status != "released":
            withheld.append(PLATE_SIZING_BENDING_CHECK)
            reasons.extend(result.validity_violations)
        if maximum_deflection_mm is not None and result.deflection_status != "released":
            withheld.append(PLATE_SIZING_DEFLECTION_CHECK)
            reasons.extend(result.deflection_validity_violations)
        if withheld:
            raise CalcCliError(
                "no_reliable_solution",
                "the flat-plate model withholds a needed output at a plate thickness"
                " the search has to evaluate",
                _plate_withheld_details(result, withheld=withheld, reasons=reasons),
            )

        results[plate_thickness_mm] = result
        return _plate_sizing_sample(
            result,
            maximum_deflection_mm=maximum_deflection_mm,
            check_targets=check_targets,
        )

    solution = _solve_thickness(
        lower_bound_mm=lower_bound_mm,
        upper_bound_mm=upper_bound_mm,
        bounds_variable="plate-thickness",
        check_targets=check_targets,
        evaluate=evaluate,
        # No partition: see _plate_sizing_sample for why the released band is
        # one continuous piece. One interval means its lower end is the bounds'
        # own, which the lower-bound case already claims, so the shared solver's
        # "branch_start" is unreachable here.
        partition_thicknesses=(),
        branch_label="released plate-thickness band",
        failure_details=lambda samples: _plate_sizing_error_details(
            lower_bound_mm=lower_bound_mm,
            upper_bound_mm=upper_bound_mm,
            check_targets=check_targets,
            results=results,
            samples=samples,
        ),
    )

    selected = solution.selected
    verified_bracket = None
    if solution.bracket is not None:
        bracket_lower, bracket_upper = solution.bracket
        verified_bracket = PlateSizingBracket(
            lower=_plate_sizing_point(
                bracket_lower,
                results=results,
                check_targets=check_targets,
            ),
            upper=_plate_sizing_point(
                bracket_upper,
                results=results,
                check_targets=check_targets,
            ),
            plate_thickness_width=_millimeters(
                bracket_upper.thickness_mm - bracket_lower.thickness_mm
            ),
        )
    metadata = PlateSizingMetadata(
        operation="plate_thickness_inverse_sizing",
        operation_version=PLATE_SIZE_OPERATION_VERSION,
        variable="plate_thickness",
        boundary_condition=boundary_condition,
        # check_targets is keyed by the two declared plate checks only.
        declared_check_set=cast("list[PlateSizingCheckName]", list(check_targets)),
        check_targets=dict(check_targets),
        maximum_deflection=(
            None if maximum_deflection_mm is None else _millimeters(maximum_deflection_mm)
        ),
        bounds=NormalizedThicknessBounds(
            lower=_millimeters(lower_bound_mm),
            upper=_millimeters(upper_bound_mm),
        ),
        selected_plate_thickness=_millimeters(selected.thickness_mm),
        selected_check_margins=dict(selected.check_margins),
        selected_governing_check=cast(
            PlateSizingCheckName, selected.states["governing_check"]
        ),
        selected_minimum_target_slack=_target_slack(selected, check_targets),
        solution_type=solution.solution_type,
        algorithm="known_branch_partition_and_bisection",
        evaluation_count=len(solution.samples),
        bisection_iterations=solution.bisection_iterations,
        plate_thickness_tolerance=_millimeters(solution.thickness_tolerance_mm),
        verified_bracket=verified_bracket,
        governing_check_changes=_plate_governing_check_changes(
            solution.samples,
            results=results,
            check_targets=check_targets,
        ),
    )
    response = _response(
        model="plate",
        result=results[selected.thickness_mm],
        material=material,
        function="flat_circular_plate",
        module="pv_calc.pressure_vessel",
    )
    response.update(
        {
            "operation": "size",
            "sizing": metadata.model_dump(mode="json"),
        }
    )
    return response


_SMOOTH_BUCKLING_TUBE_BRANCH_BOUNDARY = "tube_thin_to_thick_transition"
_SMOOTH_BUCKLING_THIN_SHELL_BOUNDARY = "buckling_thin_shell_radius_thickness_limit"
# The NASA regime boundaries the buckling kernel applies, each named, then the
# candidate whose gamma*Z the kernel compares, the reported boundary it is
# compared with, and the sign that makes the comparison rise through zero as the
# wall thickens at a fixed internal radius and unsupported length. Z falls with
# thickness because Z = L^2*sqrt(1-v^2)/(r*t) and r*t = (r_i + t/2)*t rises; the
# sign of gamma*Z - 11.8*(r/t)^2*(1-v^2) is the sign of
# gamma*L^2*t/r^3 - 11.8*sqrt(1-v^2), and t/r^3 rises while t < r_i. So each
# boundary has one root in thickness, and none of them is a constant.
_SMOOTH_BUCKLING_REGIME_BOUNDARIES = (
    ("short_regime_gamma_z_limit", "short", "short_regime_gamma_z_boundary", -1.0),
    (
        "moderate_regime_gamma_z_limit",
        "moderate",
        "moderate_gamma_z_lower_boundary",
        -1.0,
    ),
    (
        "moderate_regime_more_than_two_wave_limit",
        "moderate",
        "moderate_long_boundary_parameter",
        1.0,
    ),
    ("long_regime_oval_wave_limit", "long", "moderate_long_boundary_parameter", 1.0),
)


def _rising_condition_thickness(
    condition: Callable[[float], float],
    *,
    lower_mm: float,
    upper_mm: float,
) -> float | None:
    """Bisect a condition that rises through zero once for its wall thickness.

    Returns the largest evaluated thickness still below the boundary, or None
    when the condition keeps one sign across the interval, which means the
    boundary is outside it.
    """
    if lower_mm >= upper_mm or condition(lower_mm) >= 0.0 or condition(upper_mm) < 0.0:
        return None
    low_mm, high_mm = lower_mm, upper_mm
    while math.nextafter(low_mm, math.inf) < high_mm:
        middle_mm = low_mm + (high_mm - low_mm) / 2.0
        if condition(middle_mm) < 0.0:
            low_mm = middle_mm
        else:
            high_mm = middle_mm
    return low_mm


def _smooth_buckling_regime_condition(
    *,
    regime: str,
    boundary_field: str,
    sign: float,
    buckling_at: Callable[[float], SmoothCylinderBucklingResult],
) -> Callable[[float], float]:
    def condition(wall_thickness_mm: float) -> float:
        result = buckling_at(wall_thickness_mm)
        candidate = next(item for item in result.candidates if item.regime == regime)
        return sign * (candidate.gamma_z - getattr(result, boundary_field))

    return condition


def _smooth_buckling_branch_partition(
    *,
    internal_radius_mm: float,
    lower_bound_mm: float,
    upper_bound_mm: float,
    buckling_at: Callable[[float], SmoothCylinderBucklingResult],
) -> tuple[tuple[str, float], ...]:
    """Derive the wall thickness of every branch boundary that applies here.

    Two boundaries are stated mean-radius to thickness ratios and have an exact
    root, because the mean radius is r_i + t/2, so the ratio reaches a stated
    limit at t = r_i / (limit - 0.5): the tube model's thin-to-thick transition
    and the buckling model's thin-shell applicability limit, which are the same
    thickness while both models state the same limit. The four NASA regime
    boundaries have no closed form in thickness, so each is bisected on the
    comparison the kernel itself reports, inside the thin-shell limit, past
    which no capacity is released for any regime.
    """
    thin_shell_mm = internal_radius_mm / (
        SMOOTH_CYLINDER_MIN_RADIUS_THICKNESS_RATIO - 0.5
    )
    boundaries = [
        (
            _SMOOTH_BUCKLING_TUBE_BRANCH_BOUNDARY,
            internal_radius_mm / (TUBE_THIN_WALL_MEAN_RADIUS_RATIO - 0.5),
        ),
        (_SMOOTH_BUCKLING_THIN_SHELL_BOUNDARY, thin_shell_mm),
    ]
    for name, regime, boundary_field, sign in _SMOOTH_BUCKLING_REGIME_BOUNDARIES:
        thickness_mm = _rising_condition_thickness(
            _smooth_buckling_regime_condition(
                regime=regime,
                boundary_field=boundary_field,
                sign=sign,
                buckling_at=buckling_at,
            ),
            lower_mm=lower_bound_mm,
            upper_mm=min(upper_bound_mm, thin_shell_mm),
        )
        if thickness_mm is not None:
            boundaries.append((name, thickness_mm))
    return tuple(sorted(boundaries, key=lambda item: item[1]))


def _smooth_buckling_sizing_sample(
    tube: TubeStressResult,
    buckling: SmoothCylinderBucklingResult,
) -> _SizingSample:
    check_margins = {
        TUBE_SIZING_CHECK: tube.margin,
        # The caller admits only released capacities, so the margin exists;
        # the result type cannot say so, hence the cast.
        "smooth_cylinder_buckling": cast(float, buckling.margin),
    }
    governing = min(check_margins, key=lambda name: (check_margins[name], name))
    return _SizingSample(
        thickness_mm=tube.wall_thickness_mm,
        # A continuous piece needs both kernels continuous, so the branch is the
        # tube branch and the buckling regime together. The governing check is
        # not part of it: the smaller of two margins that both rise with
        # thickness rises with thickness whichever one it is.
        branch=f"{tube.branch}/{buckling.regime}",
        states={
            "tube_branch": tube.branch,
            "buckling_regime": buckling.regime,
            "governing_check": governing,
        },
        check_margins=check_margins,
    )


def _smooth_buckling_sizing_point(sample: _SizingSample) -> SmoothBucklingSizingPoint:
    # The sample's states dict erases the kernels' Literal types; restore them.
    return SmoothBucklingSizingPoint(
        wall_thickness=_millimeters(sample.thickness_mm),
        tube_branch=cast(Literal["thin", "thick"], sample.states["tube_branch"]),
        buckling_regime=cast(
            Literal["short", "moderate", "moderate_long_correlation_overlap", "long"],
            sample.states["buckling_regime"],
        ),
        governing_check=cast(SizingCheckName, sample.states["governing_check"]),
        check_margins=dict(sample.check_margins),
        minimum_margin=sample.minimum_margin,
    )


def _smooth_buckling_state_changes(
    samples: Sequence[_SizingSample],
    *,
    state_name: Literal["tube_branch", "buckling_regime", "governing_check"],
) -> list[SmoothBucklingSizingStateChange]:
    return [
        SmoothBucklingSizingStateChange(
            lower=_smooth_buckling_sizing_point(change.lower),
            upper=_smooth_buckling_sizing_point(change.upper),
            from_state=change.from_state,
            to_state=change.to_state,
            margin_jump=change.margin_jump,
        )
        for change in _sizing_state_changes(samples, state_name)
    ]


def _derived_branch_partition(
    partition: tuple[tuple[str, float], ...],
    *,
    lower_bound_mm: float,
    upper_bound_mm: float,
) -> list[DerivedBranchBoundary]:
    return [
        DerivedBranchBoundary(
            boundary=name,
            wall_thickness=_millimeters(thickness_mm),
            inside_bounds=lower_bound_mm < thickness_mm < upper_bound_mm,
        )
        for name, thickness_mm in partition
    ]


def _smooth_buckling_sizing_error_details(
    *,
    lower_bound_mm: float,
    upper_bound_mm: float,
    target_minimum_margin: float,
    partition: tuple[tuple[str, float], ...],
    samples: tuple[_SizingSample, ...],
) -> list[dict[str, Any]]:
    by_thickness = {sample.thickness_mm: sample for sample in samples}
    return [
        {
            "variable": "wall_thickness",
            "declared_check_set": list(SMOOTH_BUCKLING_SIZING_CHECK_SET),
            "target_minimum_margin": target_minimum_margin,
            "bounds": {
                "lower": _millimeters(lower_bound_mm).model_dump(mode="json"),
                "upper": _millimeters(upper_bound_mm).model_dump(mode="json"),
            },
            "lower_evaluation": _smooth_buckling_sizing_point(
                by_thickness[lower_bound_mm]
            ).model_dump(mode="json"),
            "upper_evaluation": _smooth_buckling_sizing_point(
                by_thickness[upper_bound_mm]
            ).model_dump(mode="json"),
            "derived_branch_partition": [
                boundary.model_dump(mode="json")
                for boundary in _derived_branch_partition(
                    partition,
                    lower_bound_mm=lower_bound_mm,
                    upper_bound_mm=upper_bound_mm,
                )
            ],
            "tube_branch_changes": [
                change.model_dump(mode="json")
                for change in _smooth_buckling_state_changes(
                    samples,
                    state_name="tube_branch",
                )
            ],
            "buckling_regime_changes": [
                change.model_dump(mode="json")
                for change in _smooth_buckling_state_changes(
                    samples,
                    state_name="buckling_regime",
                )
            ],
            "governing_check_changes": [
                change.model_dump(mode="json")
                for change in _smooth_buckling_state_changes(
                    samples,
                    state_name="governing_check",
                )
            ],
        }
    ]


def _evaluate_smooth_buckling_size(
    request: SmoothBucklingSizeRequest,
    materials_file: Path | None,
) -> dict[str, Any]:
    material = _resolve_material(request.material, materials_file)
    # Fail fast, before bounds validation: every sample reads these constants.
    material.elastic_constants_mpa("smooth-buckling")
    external_pressure_mpa = _to_unit(
        request.inputs.external_pressure,
        "MPa",
        "inputs.external_pressure",
    )
    internal_radius_mm = _to_unit(
        request.inputs.internal_radius,
        "mm",
        "inputs.internal_radius",
    )
    unsupported_length_mm = _to_unit(
        request.inputs.unsupported_length,
        "mm",
        "inputs.unsupported_length",
    )
    lower_bound_mm = _to_unit(
        request.inputs.wall_thickness_bounds.lower,
        "mm",
        "inputs.wall_thickness_bounds.lower",
    )
    upper_bound_mm = _to_unit(
        request.inputs.wall_thickness_bounds.upper,
        "mm",
        "inputs.wall_thickness_bounds.upper",
    )
    target_minimum_margin = request.inputs.minimum_margin
    # Checked before the boundaries are derived, because the derivation runs the
    # buckling kernel at thicknesses inside the bounds.
    _validate_thickness_bounds(
        lower_bound_mm,
        upper_bound_mm,
        variable="wall-thickness",
    )

    evaluations: dict[float, tuple[TubeStressResult, SmoothCylinderBucklingResult]] = {}

    def buckling_at(wall_thickness_mm: float) -> SmoothCylinderBucklingResult:
        return _calculate_smooth_buckling_result(
            external_pressure_mpa=external_pressure_mpa,
            # One cylinder: the buckling model's shell mid-surface radius is the
            # tube model's mean radius at this same wall thickness.
            shell_mid_surface_radius_mm=internal_radius_mm + 0.5 * wall_thickness_mm,
            wall_thickness_mm=wall_thickness_mm,
            unsupported_length_mm=unsupported_length_mm,
            material=material,
            load_case=SMOOTH_BUCKLING_SIZING_LOAD_CASE,
        )

    partition = _smooth_buckling_branch_partition(
        internal_radius_mm=internal_radius_mm,
        lower_bound_mm=lower_bound_mm,
        upper_bound_mm=upper_bound_mm,
        buckling_at=buckling_at,
    )

    def evaluate(wall_thickness_mm: float) -> _SizingSample:
        tube = _calculate_tube_result(
            external_pressure_mpa=external_pressure_mpa,
            internal_radius_mm=internal_radius_mm,
            wall_thickness_mm=wall_thickness_mm,
            material=material,
            force_thick=False,
        )
        buckling = buckling_at(wall_thickness_mm)
        try:
            # Admit only forward results that the final JSON response can emit.
            _json_text(
                {"results": [_serialize_result(tube), _serialize_result(buckling)]},
                compact=True,
            )
        except (TypeError, ValueError) as exc:
            raise CalcCliError("unevaluable_model", str(exc)) from exc
        if buckling.capacity_status != "released":
            # An elastic upper bound is not a sizing capacity, and its reason is
            # stated in the result's notes rather than in either violation tuple.
            pending = buckling.capacity_status == "released_pending_plasticity"
            reasons = [
                *buckling.validity_violations,
                *buckling.release_gate_violations,
            ]
            if pending:
                reasons.append(
                    SMOOTH_CYLINDER_PLASTICITY_PENDING_REASON.format(
                        stress=buckling.correlated_critical_circumferential_stress_mpa,
                        limit=buckling.proportional_limit_mpa,
                    )
                )
            raise CalcCliError(
                "no_reliable_solution",
                "smooth-cylinder buckling capacity is released only as an elastic"
                " upper bound pending plasticity validation, not as a sizing"
                " capacity, at a wall thickness the search has to evaluate"
                if pending
                else "smooth-cylinder buckling capacity is withheld at a wall"
                " thickness the search has to evaluate",
                [
                    {
                        "wall_thickness": _quantity(wall_thickness_mm, "mm"),
                        "buckling_regime": buckling.regime,
                        "capacity_status": buckling.capacity_status,
                        "withheld_reasons": reasons,
                        "derived_branch_partition": [
                            boundary.model_dump(mode="json")
                            for boundary in _derived_branch_partition(
                                partition,
                                lower_bound_mm=lower_bound_mm,
                                upper_bound_mm=upper_bound_mm,
                            )
                        ],
                    }
                ],
            )
        evaluations[wall_thickness_mm] = (tube, buckling)
        return _smooth_buckling_sizing_sample(tube, buckling)

    solution = _solve_thickness(
        lower_bound_mm=lower_bound_mm,
        upper_bound_mm=upper_bound_mm,
        bounds_variable="wall-thickness",
        check_targets=dict.fromkeys(
            SMOOTH_BUCKLING_SIZING_CHECK_SET,
            target_minimum_margin,
        ),
        evaluate=evaluate,
        partition_thicknesses=tuple(thickness for _, thickness in partition),
        branch_label="tube branch and buckling regime",
        failure_details=lambda samples: _smooth_buckling_sizing_error_details(
            lower_bound_mm=lower_bound_mm,
            upper_bound_mm=upper_bound_mm,
            target_minimum_margin=target_minimum_margin,
            partition=partition,
            samples=samples,
        ),
    )

    selected = solution.selected
    tube_result, buckling_result = evaluations[selected.thickness_mm]
    verified_bracket = None
    if solution.bracket is not None:
        bracket_lower, bracket_upper = solution.bracket
        verified_bracket = SmoothBucklingSizingBracket(
            lower=_smooth_buckling_sizing_point(bracket_lower),
            upper=_smooth_buckling_sizing_point(bracket_upper),
            wall_thickness_width=_millimeters(
                bracket_upper.thickness_mm - bracket_lower.thickness_mm
            ),
        )
    metadata = SmoothBucklingSizingMetadata(
        operation="wall_thickness_inverse_sizing",
        operation_version=SMOOTH_BUCKLING_SIZE_OPERATION_VERSION,
        variable="wall_thickness",
        declared_check_set=list(SMOOTH_BUCKLING_SIZING_CHECK_SET),
        load_case=SMOOTH_BUCKLING_SIZING_LOAD_CASE,
        shell_mid_surface_radius_convention=SMOOTH_BUCKLING_SIZING_RADIUS_CONVENTION,
        target_minimum_margin=target_minimum_margin,
        bounds=NormalizedThicknessBounds(
            lower=_millimeters(lower_bound_mm),
            upper=_millimeters(upper_bound_mm),
        ),
        selected_wall_thickness=_millimeters(selected.thickness_mm),
        selected_shell_mid_surface_radius=_millimeters(
            buckling_result.shell_mid_surface_radius_mm
        ),
        selected_check_margins=dict(selected.check_margins),
        selected_minimum_margin=selected.minimum_margin,
        # The sample's states dict erases the kernel's Literal type; restore it.
        selected_governing_check=cast(
            SizingCheckName, selected.states["governing_check"]
        ),
        solution_type=solution.solution_type,
        algorithm="known_branch_partition_and_bisection",
        evaluation_count=len(solution.samples),
        bisection_iterations=solution.bisection_iterations,
        wall_thickness_tolerance=_millimeters(solution.thickness_tolerance_mm),
        derived_branch_partition=_derived_branch_partition(
            partition,
            lower_bound_mm=lower_bound_mm,
            upper_bound_mm=upper_bound_mm,
        ),
        verified_bracket=verified_bracket,
        tube_branch_changes=_smooth_buckling_state_changes(
            solution.samples,
            state_name="tube_branch",
        ),
        buckling_regime_changes=_smooth_buckling_state_changes(
            solution.samples,
            state_name="buckling_regime",
        ),
        governing_check_changes=_smooth_buckling_state_changes(
            solution.samples,
            state_name="governing_check",
        ),
    )
    return {
        "model": "smooth-buckling",
        "operation": "size",
        "schema_version": CALC_SCHEMA_VERSION,
        "selected_results": {
            "smooth-buckling": _response(
                model="smooth-buckling",
                result=buckling_result,
                material=material,
                function="smooth_cylinder_external_pressure_buckling",
                module="pv_calc.pressure_vessel",
            ),
            "tube": _response(
                model="tube",
                result=tube_result,
                material=material,
                function="closed_end_tube_stress",
                module="pv_calc.pressure_vessel",
            ),
        },
        "sizing": metadata.model_dump(mode="json"),
    }
