# pv-calc

pv-calc is a command-line tool and Python library for external-pressure vessel
calculations. It combines tube stress and buckling checks for a cylindrical
housing, with optional flat or hemispherical closures, payload volume, mass,
and buoyancy. Individual plate, hemisphere, smooth-cylinder, and ring-stiffened
shell calculations remain available. Bounded sizing, stock-thickness selection,
geometric sweeps, and material comparisons support iterative design.

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
pv-calc cylinder \
  --depth "10 m" --fluid-density "1025 kg/m^3" \
  --gravity "9.81 m/s^2" --design-factor 1.0 \
  --internal-radius "50 mm" --wall-thickness "1 mm" \
  --unsupported-length "300 mm" \
  --material Al-6061-T6 --format text
```

Every dimensioned input carries a unit, quoted (`"8 mm"`) or attached (`8mm`).
The default output is detailed JSON with `{"value", "unit"}` quantities,
source citations, and validity status. `--format text` gives a concise terminal
report; `--format summary` gives a compact structured assessment; and
`--format csv` exports check rows, including sweep and comparison results.
Depth-based results retain the depth, design factor, and service/design pressures
in these formats. Batch `check` results retain material names, sweep coordinates,
and calculation errors. A single-request `check` JSON result retains each
resolved material block and its provenance: at `material` for a simple
calculation, or in material-only `components` and `selected_results`
projections for composed workflows.
`--json` only compacts the detailed JSON onto one line. Tube and hemisphere
material checks use exact Lamé stresses at both wall surfaces for every thickness. `--force-thick` is
accepted for compatibility and has no effect.

Status fields distinguish usable capacities from estimates:

- `released_pending_plasticity`: critical membrane stress exceeds the supplied
  proportional limit, with no curve to correct the elastic pressure; `margin` is null.
- `released_unqualified_material`: a buckling estimate from reference-only
  material data. It can be used for exploratory sizing.
- `elastic_estimate_material_limit`: a deformation kept as an elastic formula
  value although the governing stress exceeds the supplied strength.

The first two buckling statuses give `indeterminate` in `check`, or `fail` when
the elastic upper bound is below demand including the required margin.

`ring-shell` implements NASA SP-8007 Eqs. 64/65 and 82-91, verified against an
independent calculation. It reports the lowest buckling or collapse pressure
and its mode, when one can be formed: global buckling including NASA's
recommended 0.75 factor, buckling of the shell between rings, or, with a yield
strength, axisymmetric collapse. The global calculation is elastic; the
inter-ring bay includes NASA's plasticity correction, read at the bay's mid-bay
membrane stress, when a complete compressive curve is supplied. The bay's surface
stresses at the applied pressure and its axisymmetric collapse come from the
Pulos-Salerno beam-column solution and Lunchick's plastic reserve, as
documented for DAPS4, and reproduce DAPS4's published example. With a yield
strength it also reports Pc5 and ring yield: the pressures at which the mean
hoop stress in the shell at mid-bay, and in the rings, reaches yield in a
perfect periodic bay, and ring first yield, where the ring's largest hoop
stress, at its smallest radius, does. Collapse is a perfect-shell estimate;
interframe collapse of an imperfect shell, ring tripping, and ring spacing are
not checked, so `check` stays indeterminate.

Thickness sizing selects the smallest solution among model-eligible intervals
within the requested bounds and reports excluded intervals below the selection.
Zero-pressure forward requests are supported: demand and available deformation
are zero, capacities retain their applicability gates, and capacity/demand
margins are null. Sizing requires positive pressure.

Smooth-cylinder and hemispherical buckling require shell mid-surface radius /
thickness `> 10`. Thicker shells need a separate collapse model.

For a direct depth load, density, gravity, and the design factor are all
required; there is no default factor. The resulting design differential
pressure drives the calculation. Use `--external-pressure` instead when pressure
is already known. Depth conversion and the optional JSON `inputs.submergence`
block for mass/buoyancy are separate inputs.
The same depth-based request can also be nested in a material comparison or
geometry sweep. A pressure or depth sweep axis overrides the base request's load.

Material properties can be entered directly on the command line or loaded
with `--material NAME` from the bundled reference records. An explicit
`--materials-file FILE` selects a replacement database. Inspect records with:

```bash
pv-calc materials list --format text
pv-calc materials show Al-6061-T6 --format json
```

The record's `failure_category` selects the strength and failure criterion.
A `ductile_metal` is checked by
von Mises stress against yield strength. A `plastic` is checked by its largest
stress against a designer-selected working strength that accounts for creep.
A `brittle` material is checked against separate tensile and compressive
ultimate strengths because it has no yield strength. The buckling models use
elastic properties. Smooth-cylinder capacity additionally needs either a
proportional limit or a complete compressive Ramberg-Osgood curve; hemisphere
buckling needs a proportional limit.

The Al-6061-T6 and Ti-6Al-4V records mark their handbook compression data
`reference_only`: the curves describe specific extrusion forms and loading
directions that a generic alloy name does not establish. For acceptance checks,
supply data applicable to the part through explicit inputs or a custom record.

The generic `Al-7075-T6` yield value is 372 MPa (54 ksi), from ASTM B209 plate
at 3.501–4.000 inches thick: the lowest minimum among the surveyed product forms.
For a higher form-specific strength, use explicit inputs or a custom record.

[pv_calc/data/materials.yaml](https://github.com/ccluett/pv-calc/blob/main/pv_calc/data/materials.yaml)
is the canonical bundled database; the repository-root `materials.yaml` is a
compatibility symlink to it. It contains ten records across the three failure
categories. Each property identifies its source. The stored strengths are
reference inputs, not design allowables. Derivations of working strengths,
proportional limits, and compressive curves appear in `material.property_sources`
when a model reads them, and `material.data_qualification` says whether the
buckling inputs are qualified or reference-only.

Use the same unit-bearing forward, sizing, sweep, or comparison request from
Python through `calculate`. It returns a JSON-serializable dictionary without
mutating the request:

```python
from pv_calc.api import calculate

request = {
    "schema_version": "5.0.0",
    "model": "cylinder",
    "inputs": {
        "external_pressure": {"value": 0.1, "unit": "MPa"},
        "internal_radius": {"value": 50.0, "unit": "mm"},
        "wall_thickness": {"value": 1.0, "unit": "mm"},
        "unsupported_length": {"value": 300.0, "unit": "mm"},
    },
    "material": {"type": "named", "name": "Al-6061-T6"},
}
response = calculate(request)
print(response["assessment"]["status"])
```

The individual kernels remain plain Python functions in MPa and mm in
`pv_calc.pressure_vessel`, returning frozen dataclasses. `calculate` also accepts
typed request objects and an optional `materials_file` override.

## Commands

| Command | Calculates |
|---|---|
| `cylinder` | Shared-geometry tube stress and buckling; optional two-closure housing, payload, mass, and buoyancy |
| `tube` | Closed-end tube stress, failure pressure, margin, and elastic displacement |
| `tube size` | The wall thickness meeting a `cylindrical_shell_stress` margin, inside bounds |
| `plate` | Flat circular plate bending, shear-corrected centre deflection, and seat bearing stress |
| `plate size` | The plate thickness meeting a bending margin and an optional deflection limit |
| `hemisphere` | Hemispherical head stress, NASA SP-8032 buckling, displacement, and seat stress |
| `smooth-buckling` | NASA SP-8007 smooth-cylinder external-pressure buckling |
| `smooth-buckling size` | The wall thickness meeting a margin across shell stress and buckling |
| `ring-shell` | Ring-stiffened shell: NASA SP-8007 buckling pressure and mode, bay surface stresses, axisymmetric collapse, and shell and ring yield pressures (advisory) |
| `mass-properties` | Submerged mass and buoyancy from resolved volumes, fluid density, and gravity |
| `sweep` | One forward request over pressure, depth, or a supported geometric dimension |
| `compare-materials` | One forward or sizing request against an ordered list of named materials |
| `run --input FILE` | Any forward, sizing, sweep, or comparison request |
| `check --input FILE` | Acceptance assessment with pass/fail/indeterminate exit status |
| `materials list/show` | Bundled or supplied records, provenance, and input availability |
| `describe MODEL` | The model's versioned input/output contract |

Every calculation takes `--input FILE` (or `-` for stdin) for the
same request as JSON; `pv-calc describe MODEL --json` prints the contract that
request must satisfy, and `pv-calc COMMAND --help` lists the options. The
tube, plate, hemisphere, smooth-buckling, and cylinder commands also take
`--fluid-density` and `--gravity` to report the body's weight in air and in
that fluid when using a pressure load. The individual forward models also
express their failure pressures as depths. Calculation, `run`, and `check`
commands accept `--format json|summary|text|csv`; material inspection supports
`json|text`, and `describe` remains JSON-only.

## Housing and design loops

The cylinder request checks `cylindrical_shell_stress` and
`smooth_cylinder_buckling` at one closed-end pressure. Any failed required check
gives `fail`; otherwise a withheld required check gives `indeterminate`. The
assessment names omissions and reports required-check coverage. It never
qualifies seals, attachments, or the assumed support conditions.

An optional `inputs.closures` array contains exactly two flat plates or
hemispheres, each with its own material. These are simple butt closures sharing
the tube's bore and outside radius; overhangs, inserted spigots, and unequal
hemisphere walls are unsupported. `inputs.payload` accepts mass and volume;
payload volume cannot exceed the internal geometric cavity. See the runnable
[housing request](https://github.com/ccluett/pv-calc/blob/main/examples/cylinder_housing.json).
From a checkout:

```bash
pv-calc run --input examples/cylinder_housing.json --format text
pv-calc check --input examples/cylinder_check.json --format summary
pv-calc check --input examples/cylinder_check.json --check smooth_cylinder_buckling
```

`check --minimum-margin M` requires `capacity >= demand * (1 + M)` for the
selected structural checks; for a stress check, `M = 0.5` limits stress to
two-thirds of the supplied strength. Cylinder and sizing requests accept the
same target as `inputs.minimum_margin`. Encode policy factors this way rather
than by reducing a material strength. These targets are not code-defined
membrane or membrane-plus-bending stress checks; see
[acceptance criteria and allowable stresses](https://github.com/ccluett/pv-calc/blob/main/docs/engineering.md#acceptance-criteria-and-allowable-stresses).

For tube and combined smooth-cylinder sizing, fix either the internal or
external radius. Optional stock thicknesses select the smallest eligible listed
choice inside the explicit bounds:

```bash
pv-calc smooth-buckling size \
  --external-pressure "1 MPa" --external-radius "55 mm" \
  --unsupported-length "300 mm" \
  --wall-thickness-lower "0.5 mm" --wall-thickness-upper "4 mm" \
  --stock-thickness "1 mm" --stock-thickness "2 mm" --stock-thickness "3 mm" \
  --material Al-6061-T6 --format text
```

The Al-6061-T6 compression curve is reference-only, so the selected wall is
exploratory and `check` reports indeterminate.

A geometry sweep uses `inputs.geometry` and a unit-bearing `inputs.axis` in
its JSON request. For example, following the Python request above:

```python
sweep = calculate({
    "schema_version": "5.0.0", "model": "sweep",
    "inputs": {
        "geometry": "unsupported_length",
        "axis": {"type": "range", "start": {"value": 100.0, "unit": "mm"},
                 "stop": {"value": 300.0, "unit": "mm"}, "count": 5},
    },
    "request": request,
})
```

Material comparisons also accept sizing requests, reporting each selected
geometry and its structural mass when the geometry and material density permit
it. This compares designs meeting the same requirements. It does not score
materials by corrosion, cost, or availability. Use `--format csv` to export
sweep or comparison check rows.

## Errors

Ordinary calculation commands exit zero for an evaluated negative margin or
withheld capacity. `check` instead exits **0 for pass, 1 for fail, and 3 for
indeterminate**; repeat `--check ID` to select required checks. An unavailable
requested check stays indeterminate. A request that cannot be evaluated exits 2 with one
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
| `missing_input` | a request-file operation was run without `--input` |
| `input_source_conflict`, `material_source_conflict`, `missing_material_source`, `axis_source_conflict` | `--input` beside option values; both or neither of `--material` and explicit properties; two sweep axes |
| `invalid_material_database`, `unknown_material`, `invalid_material` | an unreadable database; a name it lacks (`details` lists every name); a record missing a property the model reads |
| `unknown_model` | `describe` was given a name that is not a model or batch operation |
| `invalid_bounds`, `no_reliable_solution` | a sizing operation's bounds are malformed, or no thickness inside them meets the target; `details` names the bracket evaluated |
| `unevaluable_model` | the kernel rejected the resolved inputs, a sizing sample fell outside a model's validity, or the result is not finite |

## Documentation

- [docs/engineering.md](https://github.com/ccluett/pv-calc/blob/main/docs/engineering.md):
  models, sources, sizing and batch operation contracts, failure coverage,
  and testing.
- [tests/reference/](https://github.com/ccluett/pv-calc/tree/main/tests/reference):
  independent reference implementations of the source equations, which the
  tests compare against production results.
- [examples/](https://github.com/ccluett/pv-calc/tree/main/examples):
  committed example requests for every command; a golden-response test pins
  their output.

Links are absolute because this file is also the PyPI page, and the packaged
distribution ships the reference material database but not the docs, tests,
or examples.

Released under the
[MIT License](https://github.com/ccluett/pv-calc/blob/main/LICENSE). Changes
are recorded in the
[changelog](https://github.com/ccluett/pv-calc/blob/main/CHANGELOG.md), and
citation metadata is in
[CITATION.cff](https://github.com/ccluett/pv-calc/blob/main/CITATION.cff).
