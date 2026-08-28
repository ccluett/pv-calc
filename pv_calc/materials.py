"""Named-material loading for the pv-calc surface.

The calculator validates only the properties it reads and ignores the rest, so
one ``materials.yaml`` can serve a stricter consumer at the same time, while a
calculator-only database needs no ultimate-strength data and needs a density
only for the mass-properties operation.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict, field_validator, model_validator

from pv_calc.schemas import MaterialFailureCategory


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
    ultimate_tensile_strength_mpa: float | None = None
    ultimate_compressive_strength_mpa: float | None = None
    elastic_modulus_mpa: float | None = None
    poisson_ratio: float | None = None
    proportional_limit_mpa: float | None = None
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

    @field_validator("source")
    @classmethod
    def source_present(cls, value: str) -> str:
        if not value.strip():
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


def load_calc_materials(path: str | Path) -> dict[str, CalcMaterial]:
    with Path(path).open("r", encoding="utf-8") as handle:
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
