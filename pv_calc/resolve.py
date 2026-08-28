"""Material resolution: a request's named or explicit record into kernel properties."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from yaml import YAMLError

from pv_calc.contracts import (
    CATEGORY_STRENGTHS,
    STRENGTH_FIELDS,
    ExplicitBucklingMaterialInput,
    ExplicitHemisphereMaterialInput,
    ExplicitMassMaterialInput,
    ExplicitPlateMaterialInput,
    ExplicitTubeMaterialInput,
    NamedMaterialInput,
    _to_unit,
)
from pv_calc.errors import CalcCliError
from pv_calc.materials import CalcMaterial, load_calc_materials
from pv_calc.schemas import MaterialFailureCategory


@dataclass(frozen=True)
class ResolvedMaterial:
    """A resolved stress-or-buckling material record.

    Every strength is optional at this level: a named record carries what its
    database gives it, and only the stress models need one.
    """

    source_type: Literal["named", "explicit"]
    name: str | None
    database: str | None
    provenance: str | None
    failure_category: MaterialFailureCategory
    yield_strength_mpa: float | None = None
    working_strength_mpa: float | None = None
    ultimate_tensile_strength_mpa: float | None = None
    ultimate_compressive_strength_mpa: float | None = None
    elastic_modulus_mpa: float | None = None
    poisson_ratio: float | None = None
    proportional_limit_mpa: float | None = None
    density_kg_per_m3: float | None = None

    def strengths_mpa(self) -> dict[str, float]:
        """The category's strengths this record carries, keyed by property name."""
        return {
            name: value
            for name in CATEGORY_STRENGTHS[self.failure_category]
            if (value := getattr(self, f"{name}_mpa")) is not None
        }

    def shell_strength_mpa(self) -> float:
        """The strength a shell kernel compares against: the category's first strength.

        A named record may lack it, since the buckling models read none; the
        stress models ask here, at their point of use.
        """
        name = CATEGORY_STRENGTHS[self.failure_category][0]
        value = getattr(self, f"{name}_mpa")
        if value is None:
            raise CalcCliError(
                "invalid_material",
                f"strength material properties are incomplete: {self.failure_category} "
                f"requires {name}",
            )
        return value

    def elastic_constants_mpa(self, model_label: str) -> tuple[float, float]:
        """The elastic modulus and Poisson ratio a model reads at its boundary.

        Rejects a record missing either, in the style of ``shell_strength_mpa``:
        a stress-only named record stays valid until a model asks, at its point
        of use, for what the record lacks.
        """
        if self.elastic_modulus_mpa is None or self.poisson_ratio is None:
            raise CalcCliError(
                "invalid_material",
                f"{model_label} material properties are incomplete",
            )
        return self.elastic_modulus_mpa, self.poisson_ratio


@dataclass(frozen=True)
class ResolvedMassMaterial:
    """A mass-properties material record.

    Mass properties read a density and no strength property, so this is a
    separate record rather than a `ResolvedMaterial` with every strength field
    emptied. A named entry may still be a stress-only record, so the density is
    optional here and rejected at the model boundary.
    """

    source_type: Literal["named", "explicit"]
    name: str | None
    database: str | None
    provenance: str | None
    density_kg_per_m3: float | None


# Parsed databases keyed by resolved path plus stat identity (mtime_ns and
# size), so a batch operation reads its unchanged file once while an edited,
# replaced, or deleted file is never served stale. A rewrite preserving both
# the size and the nanosecond mtime would be missed; no editor or filesystem
# this package supports produces one.
_LOADED_DATABASES: dict[tuple[Path, int, int], dict[str, CalcMaterial]] = {}


def _load_named_material(
    name: str,
    materials_file: Path | None,
) -> tuple[CalcMaterial, str]:
    if materials_file is None:
        raise CalcCliError(
            "missing_materials_file",
            "a named material requires --materials-file; there is no default database",
        )
    try:
        stat = Path(materials_file).stat()
        key = (Path(materials_file).resolve(), stat.st_mtime_ns, stat.st_size)
        if key not in _LOADED_DATABASES:
            _LOADED_DATABASES[key] = load_calc_materials(materials_file)
    except (OSError, ValueError, YAMLError) as exc:
        raise CalcCliError("invalid_material_database", str(exc)) from exc
    materials = _LOADED_DATABASES[key]
    try:
        material = materials[name]
    except KeyError as exc:
        raise CalcCliError(
            "unknown_material",
            f"material {name!r} is not present in {materials_file}",
            [{"available_materials": sorted(materials)}],
        ) from exc
    return material, str(materials_file)


def _resolve_material(
    material: (
        NamedMaterialInput
        | ExplicitTubeMaterialInput
        | ExplicitPlateMaterialInput
        | ExplicitHemisphereMaterialInput
        | ExplicitBucklingMaterialInput
    ),
    materials_file: Path | None,
) -> ResolvedMaterial:
    if isinstance(material, NamedMaterialInput):
        named, database = _load_named_material(material.name, materials_file)
        # The category is needed to read any strength; whether a strength is
        # needed at all is the model's question, asked by shell_strength_mpa().
        if named.failure_category is None:
            raise CalcCliError(
                "invalid_material",
                "strength material properties are incomplete: failure_category is required",
            )
        return ResolvedMaterial(
            source_type="named",
            name=material.name,
            database=database,
            provenance=named.source,
            failure_category=named.failure_category,
            yield_strength_mpa=named.yield_strength_mpa,
            working_strength_mpa=named.working_strength_mpa,
            ultimate_tensile_strength_mpa=named.ultimate_tensile_strength_mpa,
            ultimate_compressive_strength_mpa=named.ultimate_compressive_strength_mpa,
            elastic_modulus_mpa=named.elastic_modulus_mpa,
            poisson_ratio=named.poisson_ratio,
            proportional_limit_mpa=named.proportional_limit_mpa,
            density_kg_per_m3=named.density_kg_per_m3,
        )
    properties = material.properties
    elastic_modulus = getattr(properties, "elastic_modulus", None)
    proportional_limit = getattr(properties, "proportional_limit", None)
    density = properties.density
    strengths = {
        f"{name}_mpa": _to_unit(quantity, "MPa", f"material.properties.{name}")
        for name in STRENGTH_FIELDS
        if (quantity := getattr(properties, name)) is not None
    }
    return ResolvedMaterial(
        source_type="explicit",
        name=material.name,
        database=None,
        provenance=material.provenance,
        failure_category=properties.failure_category,
        **strengths,
        elastic_modulus_mpa=(
            _to_unit(elastic_modulus, "MPa", "material.properties.elastic_modulus")
            if elastic_modulus is not None
            else None
        ),
        poisson_ratio=getattr(properties, "poisson_ratio", None),
        proportional_limit_mpa=(
            _to_unit(
                proportional_limit,
                "MPa",
                "material.properties.proportional_limit",
            )
            if proportional_limit is not None
            else None
        ),
        density_kg_per_m3=(
            _to_unit(density, "kg/m^3", "material.properties.density")
            if density is not None
            else None
        ),
    )


def _resolve_mass_material(
    material: NamedMaterialInput | ExplicitMassMaterialInput,
    materials_file: Path | None,
) -> ResolvedMassMaterial:
    if isinstance(material, NamedMaterialInput):
        named, database = _load_named_material(material.name, materials_file)
        return ResolvedMassMaterial(
            source_type="named",
            name=material.name,
            database=database,
            provenance=named.source,
            density_kg_per_m3=named.density_kg_per_m3,
        )
    return ResolvedMassMaterial(
        source_type="explicit",
        name=material.name,
        database=None,
        provenance=material.provenance,
        density_kg_per_m3=_to_unit(
            material.properties.density,
            "kg/m^3",
            "material.properties.density",
        ),
    )
