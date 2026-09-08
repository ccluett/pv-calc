"""Named-material loading for the pv-calc surface.

The calculator validates only the properties it reads and ignores the rest, so
one ``materials.yaml`` can serve a stricter consumer at the same time, while a
calculator-only database needs no ultimate-strength data and needs a density
only for the mass-properties operation.
"""

from __future__ import annotations

import math
from importlib.resources import files
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from pv_calc.schemas import MaterialFailureCategory


BUNDLED_MATERIAL_DATABASE = "bundled:pv_calc/data/materials.yaml"


class CalcMaterial(BaseModel):
    """The material properties the pv-calc models read, and nothing else.

    Every strength is optional because each failure category reads its own:
    ``yield_strength_mpa`` for ``ductile_metal``, ``working_strength_mpa`` for
    ``plastic``, and ``ultimate_compressive_strength_mpa`` for ``brittle``, whose
    ``ultimate_tensile_strength_mpa`` only the plate reads. ``elastic_modulus_mpa``,
    ``poisson_ratio``, and ``density_kg_per_m3`` are optional because no model
    reads all of them: tube displacement reads both elastic constants when they
    are available, while only the mass-properties operation reads density, so a
    yield-only database still runs the tube stress model with displacement
    withheld. A named material missing what its model needs reaches the
    per-model `invalid_material` error at the point of use. That is a different
    path from an explicit property set, which the request schema rejects up
    front with `invalid_request` because each request model requires the fields
    its own model reads.
    """

    model_config = ConfigDict(extra="ignore")

    failure_category: MaterialFailureCategory | None = None
    source: str
    yield_strength_mpa: float | None = None
    working_strength_mpa: float | None = None
    working_strength_source: str | None = None
    ultimate_tensile_strength_mpa: float | None = None
    ultimate_compressive_strength_mpa: float | None = None
    elastic_modulus_mpa: float | None = None
    poisson_ratio: float | None = None
    proportional_limit_mpa: float | None = None
    proportional_limit_source: str | None = None
    density_kg_per_m3: float | None = None

    @field_validator(
        "yield_strength_mpa",
        "working_strength_mpa",
        "ultimate_tensile_strength_mpa",
        "ultimate_compressive_strength_mpa",
        "elastic_modulus_mpa",
        "poisson_ratio",
        "proportional_limit_mpa",
        "density_kg_per_m3",
        mode="before",
    )
    @classmethod
    def numeric_not_bool(cls, value: Any) -> Any:
        if isinstance(value, bool):
            raise ValueError("must be numeric")
        return value

    @field_validator(
        "yield_strength_mpa",
        "working_strength_mpa",
        "ultimate_tensile_strength_mpa",
        "ultimate_compressive_strength_mpa",
        "elastic_modulus_mpa",
        "proportional_limit_mpa",
        "density_kg_per_m3",
    )
    @classmethod
    def positive(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or value <= 0:
            raise ValueError("value must be finite and positive")
        return value

    @field_validator("poisson_ratio")
    @classmethod
    def poisson_range(cls, value: float | None) -> float | None:
        if value is None:
            return None
        if not math.isfinite(value) or not 0 < value < 0.5:
            raise ValueError("poisson_ratio must be between 0 and 0.5")
        return value

    @field_validator("source", "working_strength_source", "proportional_limit_source")
    @classmethod
    def source_present(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            raise ValueError("source must not be empty")
        return value

    @model_validator(mode="after")
    def strength_ordering(self) -> "CalcMaterial":
        if (
            self.proportional_limit_mpa is not None
            and self.yield_strength_mpa is not None
            and self.proportional_limit_mpa > self.yield_strength_mpa
        ):
            raise ValueError("proportional_limit_mpa must be <= yield_strength_mpa")
        return self


def load_calc_materials(path: str | Path | None = None) -> dict[str, CalcMaterial]:
    """Load an explicit database, or the package's reference records.

    The default is independent of the working directory. Supplying a path
    always selects that file; an unreadable override never falls back.
    """
    source = Path(path) if path is not None else files("pv_calc").joinpath("data/materials.yaml")
    with source.open("r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    if not isinstance(data, dict):
        raise ValueError("materials file must contain a mapping")
    raw_materials = data.get("materials", {})
    if not isinstance(raw_materials, dict) or not raw_materials:
        raise ValueError("materials file must contain a non-empty materials mapping")
    materials: dict[str, CalcMaterial] = {}
    for name, raw in raw_materials.items():
        # YAML reads an unquoted 316 as a number and an unquoted on as a
        # boolean, and a record under such a name could never be found by the
        # string every lookup sends.
        if not isinstance(name, str):
            raise ValueError(
                f"material name {name!r} must be a string; quote it in the file"
            )
        materials[name] = CalcMaterial.model_validate(raw)
    return materials


def material_capabilities(material: CalcMaterial) -> dict[str, dict[str, Any]]:
    """Material-property availability, before geometry and load applicability.

    ``available`` means the inputs for the named calculation are present. It
    does not promise that a capacity will be released at a particular geometry
    or load, or qualify the reference properties as design allowables.
    """
    strength_field = {
        "ductile_metal": "yield_strength_mpa",
        "plastic": "working_strength_mpa",
        "brittle": "ultimate_compressive_strength_mpa",
    }.get(material.failure_category or "")
    shell = ["failure_category", strength_field or "failure_category"]
    elastic = ["elastic_modulus_mpa", "poisson_ratio"]
    bending = shell if material.failure_category != "brittle" else [
        "failure_category", "ultimate_tensile_strength_mpa", "ultimate_compressive_strength_mpa",
    ]
    buckling = ["failure_category", *elastic, "proportional_limit_mpa"]
    requirements = {
        "tube_stress": shell,
        "tube_displacement": [*shell, *elastic],
        "plate_bending": [*bending, *elastic],
        "plate_deflection": [*bending, *elastic],
        "hemisphere_stress": [*shell, *elastic],
        "hemisphere_buckling_capacity": [*shell, *buckling],
        "smooth_cylinder_buckling_capacity": buckling,
        "cylinder": [*shell, *buckling],
        "mass_properties": ["density_kg_per_m3"],
    }
    return {
        name: {
            "available": not (missing := sorted({
                field for field in required if getattr(material, field) is None
            })),
            "missing_properties": missing,
        }
        for name, required in requirements.items()
    }


def _material_record(name: str, material: CalcMaterial, database: str) -> dict[str, Any]:
    return {
        "name": name,
        "database": database,
        "properties": material.model_dump(exclude_none=True),
        "capabilities": material_capabilities(material),
        "capability_scope": "Property availability only; geometry, load, and source applicability must still be evaluated.",
    }


def list_materials(materials_file: str | Path | None = None) -> list[dict[str, Any]]:
    """List named records and calculation-property availability in name order."""
    database = str(materials_file) if materials_file is not None else BUNDLED_MATERIAL_DATABASE
    return [
        {
            "name": name,
            "database": database,
            "failure_category": material.failure_category,
            "capabilities": material_capabilities(material),
        }
        for name, material in sorted(load_calc_materials(materials_file).items())
    ]


def show_material(name: str, materials_file: str | Path | None = None) -> dict[str, Any]:
    """Return one record, its property sources, and capability availability.

    Unknown names raise ``KeyError``; malformed or unreadable databases raise
    the same exceptions as :func:`load_calc_materials`.
    """
    materials = load_calc_materials(materials_file)
    database = str(materials_file) if materials_file is not None else BUNDLED_MATERIAL_DATABASE
    return _material_record(name, materials[name], database)
