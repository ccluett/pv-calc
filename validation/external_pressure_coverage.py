"""Reproduce the illustrative 6000 m housing coverage study.

Run from the checkout: uv run python validation/external_pressure_coverage.py
"""

from __future__ import annotations

import json
import math
from typing import Any

from pv_calc.api import calculate
from pv_calc.errors import CalcCliError
from pv_calc.materials import load_calc_materials


RHO = 1046.0
GRAVITY = 9.81
FACTOR = 1.5
DEPTH = 6000.0
LENGTH = 609.6
PRESSURE_PER_METRE = RHO * GRAVITY * FACTOR / 1e6
DESIGN_PRESSURE = DEPTH * PRESSURE_PER_METRE
YIELD_GATE_RATIO = 80.0 / (441.0 * math.sqrt(3.0))
ILLUSTRATIVE_TITANIUM_CURVE = {
    "type": "explicit",
    "name": "Illustrative Ti-6Al-4V curve assumption",
    "provenance": (
        "Illustrative assumption from historical MIL-HDBK-5J Figures "
        "5.4.1.1.6(b,c), "
        "p. 5-65: typical longitudinal annealed-extrusion n = 21 with the "
        "827 MPa tensile minimum substituted as the compression anchor. "
        "MIL-HDBK-5J is cancelled and MMPDS is its successor; verify current "
        "hoop-direction, product-form, heat-treatment, and proof-stress data."
    ),
    "properties": {
        "failure_category": "ductile_metal",
        "yield_strength": {"value": 827.0, "unit": "MPa"},
        "elastic_modulus": {"value": 113800.0, "unit": "MPa"},
        "poisson_ratio": 0.34,
        "proportional_limit": {"value": 602.0, "unit": "MPa"},
        "ramberg_osgood_n": 21.0,
        "compressive_proof_stress": {"value": 827.0, "unit": "MPa"},
    },
}


def q(value: float, unit: str = "mm") -> dict[str, Any]:
    return {"value": value, "unit": unit}


def request(
    model: str,
    inputs: dict[str, Any],
    material: str | dict[str, Any] = "Ti-6Al-4V",
) -> dict[str, Any]:
    return {
        "schema_version": "5.0.0", "model": model, "inputs": inputs,
        "material": (
            {"type": "named", "name": material}
            if isinstance(material, str)
            else material
        ),
    }


def size(
    model: str,
    outside: float,
    pressure: float,
    material: str | dict[str, Any],
) -> dict[str, Any]:
    inputs = {
        "external_pressure": q(pressure, "MPa"), "external_radius": q(outside),
        "wall_thickness_bounds": {"lower": q(1), "upper": q(60)},
    }
    if model == "smooth-buckling":
        inputs["unsupported_length"] = q(LENGTH)
    return calculate({**request(model, inputs, material), "operation": "size"})


def main() -> None:
    materials = load_calc_materials()
    thresholds = []
    for name, material in sorted(materials.items(), key=lambda item: item[1].yield_strength_mpa or math.inf):
        if material.failure_category != "ductile_metal":
            continue
        assert material.yield_strength_mpa is not None
        gate_pressure = material.yield_strength_mpa * YIELD_GATE_RATIO
        sized = size("tube", 101.6, gate_pressure, name)
        wall = sized["sizing"]["selected_wall_thickness"]["value"]
        ratio = 101.6 / wall - 0.5
        assert math.isclose(ratio, 10.0, rel_tol=1e-8)
        thresholds.append({
            "material": name, "yield_mpa": material.yield_strength_mpa,
            "yield_geometry_gate_depth_m": gate_pressure / PRESSURE_PER_METRE,
            "tool_sized_radius_thickness_ratio": ratio,
        })

    housings = []
    for diameter in (8, 10, 12, 14, 16):
        outside = diameter * 25.4 / 2.0
        bore_fraction = math.sqrt(1.0 - math.sqrt(3.0) * DESIGN_PRESSURE / 827.0)
        yield_wall = outside * (1.0 - bore_fraction)
        sized = size("tube", outside, DESIGN_PRESSURE, "Ti-6Al-4V")
        assert math.isclose(sized["sizing"]["selected_wall_thickness"]["value"], yield_wall, rel_tol=1e-8)
        for material in ("Ti-6Al-4V", ILLUSTRATIVE_TITANIUM_CURVE):
            try:
                size("smooth-buckling", outside, DESIGN_PRESSURE, material)
            except CalcCliError as exc:
                assert exc.code == "no_reliable_solution"
            else:
                raise AssertionError("Expected the released combined-sizing coverage gap")

        wall = outside / 10.55
        cylinder = calculate(request(
            "cylinder",
            {
                "external_pressure": q(DESIGN_PRESSURE, "MPa"),
                "internal_radius": q(outside - wall), "wall_thickness": q(wall),
                "unsupported_length": q(LENGTH),
            },
            ILLUSTRATIVE_TITANIUM_CURVE,
        ))
        buckling = cylinder["components"]["smooth_buckling"]["result"]
        # The explicit illustrative curve exercises the NASA Eq. 30-32
        # correction without promoting it into the generic named record.
        capacity = buckling["correlated_critical_pressure_mpa"]["value"]
        elastic = next(
            candidate["correlated_critical_pressure_mpa"]["value"]
            for candidate in buckling["candidates"]
            if candidate["applicable"]
        )
        checks = {item["id"]: item for item in cylinder["assessment"]["checks"]}
        assert cylinder["assessment"]["status"] == "fail"
        row = {
            "outside_diameter_in": diameter, "yield_wall_mm": yield_wall,
            "yield_radius_thickness_ratio": outside / yield_wall - 0.5,
            "combined_sizing": "no_reliable_solution",
            "comparison_radius_thickness_ratio": 10.05,
            "comparison_wall_mm": wall,
            "comparison_elastic_buckling_pressure_mpa": elastic,
            "comparison_released_buckling_pressure_mpa": capacity,
            "comparison_plasticity_factor": buckling["plasticity_factor"],
            "comparison_buckling_status": buckling["capacity_status"],
            "comparison_yield_pressure_mpa": checks["cylindrical_shell_stress"]["capacity"]["value"],
            "comparison_assessment_buckling_capacity": checks["smooth_cylinder_buckling"]["capacity"]["value"],
            "comparison_overall_assessment": cylinder["assessment"]["status"],
        }
        housings.append(row)
    print(json.dumps({
        "service_pressure_mpa": DESIGN_PRESSURE / FACTOR,
        "design_pressure_mpa": DESIGN_PRESSURE,
        "yield_gate_pressure_ratio": YIELD_GATE_RATIO,
        "thresholds": thresholds, "housings": housings,
    }, indent=2, allow_nan=False))


if __name__ == "__main__":
    main()
