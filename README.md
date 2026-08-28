# pv-calc

pv-calc is a command-line tool and Python library for external-pressure vessel
calculations. It covers tube stress, flat circular
plates, hemispherical heads, NASA smooth-cylinder buckling, and NASA
ring-stiffened shell general instability. Bounded thickness sizing is
available for tubes, plates, and smooth cylinders. The package also calculates
submerged mass properties.

Results include the formula sources, assumptions, and validity checks used in
the calculation. They come from idealized models and do not constitute design
approval.

## Install

```bash
pip install pv-calc
```

Python 3.11 or later; depends on pydantic, pint, PyYAML, and typer. From a
checkout, `pip install .`.

## Quick start

```bash
pv-calc tube \
  --external-pressure "1000 psi" \
  --internal-radius "3 in" \
  --wall-thickness "0.470 in" \
  --yield-strength "62 ksi" \
  --failure-category ductile_metal \
  --json
```

Every dimensioned input carries a unit, quoted (`"8 mm"`) or attached (`8mm`).
Results are JSON with `{"value", "unit"}` quantities, model and source
citations, and validity status.

Material properties can be entered directly on the command line, as above, or
loaded from a named record with
`--material NAME --materials-file FILE`. The record's `failure_category`
selects the strength and failure criterion. A `ductile_metal` is checked by
von Mises stress against yield strength. A `plastic` is checked by its largest
stress against a designer-selected working strength that accounts for creep.
A `brittle` material is checked against separate tensile and compressive
ultimate strengths because it has no yield strength. The buckling models use
only the elastic properties.

[materials.yaml](https://github.com/ccluett/pv-calc/blob/main/materials.yaml)
contains ten material records across the three failure categories. Each
property identifies its source. The stored strengths are reference inputs,
not design allowables.

The same kernels are plain Python functions in MPa and mm, returning frozen
dataclasses:

```python
from pv_calc.pressure_vessel import closed_end_tube_stress

result = closed_end_tube_stress(
    external_pressure_mpa=6.895,
    internal_radius_mm=76.2,
    wall_thickness_mm=11.94,
    material_failure_category="ductile_metal",
    strength_mpa=427.5,
)
print(result.branch, result.governing_stress_mpa, result.margin)
```

## Commands

| Command | Calculates |
|---|---|
| `tube` | Closed-end tube stress, failure pressure, margin, and elastic displacement |
| `tube size` | The wall thickness meeting a `cylindrical_shell_stress` margin, inside bounds |
| `plate` | Flat circular plate bending, shear, centre deflection, and seat bearing stress |
| `plate size` | The plate thickness meeting a bending margin and an optional deflection limit |
| `hemisphere` | Hemispherical head stress, NASA SP-8032 buckling, displacement, and seat stress |
| `smooth-buckling` | NASA SP-8007 smooth-cylinder external-pressure buckling |
| `smooth-buckling size` | The wall thickness meeting a margin across shell stress and buckling |
| `ring-shell` | NASA SP-8007 ring-stiffened shell general instability (advisory) |
| `mass-properties` | Submerged mass and buoyancy from resolved volumes, fluid density, and gravity |
| `sweep` | One forward request over a pressure or depth axis |
| `compare-materials` | One forward request against an ordered list of named materials |
| `describe MODEL` | The model's versioned input/output contract |

Output is always JSON, indented by default and compact on one line with
`--json`. Every calculation takes `--input FILE` (or `-` for stdin) for the
same request as JSON; `pv-calc describe MODEL --json` prints the contract that
request must satisfy, and `pv-calc COMMAND --help` lists the options. The
tube, plate, hemisphere, and smooth-buckling commands also take
`--fluid-density` and `--gravity` to report the body's weight in air and in
that fluid and each failure pressure as a depth.

## Errors

An evaluated negative margin, or a capacity the model withholds, is a normal
result and exits zero. A request that cannot be evaluated exits 2 with one
JSON object on stderr:

```json
{"schema_version": "5.0.0",
 "error": {"code": "unknown_material", "message": "...", "details": [...]}}
```

`details` is a list of objects whose shape depends on the code, and may be
empty; `message` always says what went wrong. The codes:

| Code | Cause |
|---|---|
| `input_read_error`, `invalid_json` | `--input` cannot be read, or is not JSON |
| `invalid_request` | the request does not satisfy the model's contract, including a missing option; `details` lists each pydantic error with its `location` |
| `invalid_quantity`, `invalid_number`, `incompatible_unit` | a quantity has no unit, an unknown unit, or no finite value; a plain number is not numeric or finite; a quantity's unit has the wrong dimension |
| `missing_input` | `sweep` or `compare-materials` was run without `--input` |
| `input_source_conflict`, `material_source_conflict`, `missing_material_source`, `axis_source_conflict` | `--input` beside option values; both or neither of `--material` and explicit properties; two sweep axes |
| `missing_materials_file`, `invalid_material_database`, `unknown_material`, `invalid_material` | a named material without `--materials-file`; an unreadable database; a name it lacks (`details` lists every name); a record missing a property the model reads |
| `unknown_model` | `describe` was given a name that is not a model or batch operation |
| `invalid_bounds`, `no_reliable_solution` | a sizing operation's bounds are malformed, or no thickness inside them meets the target; `details` names the bracket evaluated |
| `unevaluable_model` | the kernel rejected the resolved inputs, a sizing sample fell outside a model's validity, or the result is not finite |

## Documentation

- [docs/engineering.md](https://github.com/ccluett/pv-calc/blob/main/docs/engineering.md):
  models, sources, sizing and batch operation contracts, failure coverage,
  and validation approach.
- [validation/](https://github.com/ccluett/pv-calc/tree/main/validation):
  independent reference implementations, published benchmarks (DTMB report
  1324 case 17), and FEA comparisons. The reference implementations
  derive the published equations independently of the production code. This
  separation catches calculation regressions, although it cannot rule out a
  shared interpretation error in the source material.
- [examples/](https://github.com/ccluett/pv-calc/tree/main/examples):
  committed example requests for every command; a golden-response test pins
  their output.

Links are absolute because this file is also the PyPI page, and the packaged
distribution does not ship the docs, validation, examples, or material
database.

Released under the
[MIT License](https://github.com/ccluett/pv-calc/blob/main/LICENSE). Changes
are recorded in the
[changelog](https://github.com/ccluett/pv-calc/blob/main/CHANGELOG.md), and
citation metadata is in
[CITATION.cff](https://github.com/ccluett/pv-calc/blob/main/CITATION.cff).
