# pv-calc engineering record

This document describes the released analytical models, their sources, and
the available validation evidence.

The current scope covers smooth and ring-stiffened cylindrical shells under
external hydrostatic pressure, with flat circular or hemispherical end
closures. Stress calculations support ductile metals, plastics, and brittle
materials, using a failure criterion appropriate to each category. Annular
endcaps, complete spheres, cones, and internal-pressure workflows are not yet
included. Results cover the analytical checks listed below; vessel certification
and fabrication requirements are outside the scope of the calculator.

## Requests and results

`from pv_calc.api import calculate` accepts the same versioned, unit-bearing
dictionary as CLI JSON, or a typed request object. It handles forward
calculations, sizing, sweeps, and material comparisons, returns a finite
JSON-serializable dictionary, and does not mutate the request. Invalid requests
raise `CalcCliError` with `code`, `message`, and `details`. The plain kernel APIs
remain available independently.

`pv-calc run --input FILE` dispatches any request; `-` reads stdin. Calculation
commands accept `--format json|summary|text|csv`. Detailed JSON remains the
default, `summary` is a smaller structured assessment, `text` is a terminal
report, and CSV exports check rows with batch positions. `--json` changes only
JSON whitespace and cannot be combined with another format. Material inspection
supports JSON and text. `describe MODEL` publishes request and result contracts
as JSON only.
Summaries retain depth, fluid properties, the design factor, and service/design
pressures. Text and CSV also show the depth, factor, and both pressures.

Ordinary evaluations exit zero even for a failed or withheld check.
`pv-calc check --input FILE` instead exits 0 for pass, 1 for fail, 3 for
indeterminate, and 2 for invalid input. Repeated `--check ID` options select
required checks, and `--minimum-margin` supplies an additional target. A known
failure retains `fail` even if another required check is unavailable; otherwise
missing required coverage gives `indeterminate`. The governing numerical check
is null when coverage is incomplete. Acceptance is scoped to the requested
checks, not the whole as-built vessel.
For a single request, detailed/default JSON `check` output retains each resolved
material block so its name, properties used, database, and provenance travel
with the decision. A simple calculation uses the top-level `material`; a
cylinder or combined sizing result keeps material-only projections at its
existing `components` or `selected_results` paths. Batch assessments retain
each entry's index, material or sweep coordinate, and any calculation error
under `assessment.entries[].context`.
CSV includes the operation, coordinates, material, outcome, and error message.

An ordinary forward or sizing JSON request can replace `inputs.external_pressure`
with `inputs.depth`, `inputs.fluid_density`, `inputs.gravity`, and
`inputs.design_factor`; the first three quantities carry units and the factor
is dimensionless. All four are
required. The CLI equivalents are `--depth`, `--fluid-density`, `--gravity`, and
`--design-factor`. Sizing and ring-shell commands reject fluid options without
`--depth`; other forward commands can use them for submergence calculations.
The API converts this alternate load before strict model
validation, records the conversion under `loading`, and drives the model with
design differential pressure. Optional JSON `inputs.submergence` remains a
separate request for mass and fluid results. The unchanged depth-based request
can also be nested inside `compare-materials` or `sweep`: material comparisons
and geometric sweeps retain conversion provenance in each nested response's
`loading` block. A pressure or depth sweep axis takes precedence over the base
load and does not retain stale base-loading metadata. Zero-pressure forward evaluations
have zero demand and zero deformation where available, finite formula capacities,
and null capacity/demand margins. Zero load never releases a capacity outside its model
domain. The inverse sizing operations require positive design pressure.

## Models

Seven calculation kernels are available through `pv-calc`. The five
external-pressure kernels are pure functions in
[pressure_vessel.py](../pv_calc/pressure_vessel.py) that
state their radius, load, boundary, and sign conventions; the other two live in
[hydrostatics.py](../pv_calc/hydrostatics.py), where
`submerged_mass_and_buoyancy` states its submergence, sign, and direction
conventions and `external_pressure_from_depth` states its pressure-reference
convention. All return typed results with source citations, intermediates, and
validity data. Each model carries its own version, listed below. Model
versions and the JSON contract version predate the first public release;
changes from 0.1.0 on are recorded in the [changelog](../CHANGELOG.md).

| Model ID | Version | Basis |
|---|---|---|
| `closed_end_tube_stress` | 3.1.0 | Exact closed-end Lamé stress at both wall surfaces for every thickness; the material check follows the failure category: 3D von Mises against yield strength for `ductile_metal`, maximum hoop stress against the working strength (`plastic`) or ultimate compressive strength (`brittle`), component stresses stay report-only. Scalar radial displacement at each stress-state radius, uniform axial strain, and an axial length change over a supplied gauge length, released only when the caller gives both an elastic modulus and a Poisson ratio |
| `uniformly_loaded_flat_circular_plate` | 4.1.0 | Roark cases 10a/10b for a declared fixed or simply-supported edge, the surface bending stress compared to the yield, working, or (brittle) ultimate tensile strength; requires `w <= t/2` on a shear-corrected deflection estimate, `0.05 <= nu <= 0.35`, and, from swept FEA evidence, `D_free/t >= 10` (fixed) or `>= 4` (simply supported) to release the bending margin, with the center deflection released only at `>= 20` and `>= 10`; outside those the formula values stay published and the margin or deflection is withheld with its reasons. With an optional outside radius, the average seat bearing stress on the outside annulus, its failure pressure, and margin, thickness-independent and report-only |
| `roark_nasa_hemispherical_head_external_pressure` | 5.0.0 | Exact Lamé sphere stress under the category's criterion, as for the tube, plus NASA SP-8032 clamped-cap buckling; capacity released only for a thin shell with `lambda > 2` and a source-traceable proportional limit. Reference-only limits retain the numerical result as `released_unqualified_material` but cannot support acceptance. Exact spherical radial displacement at both wall surfaces, away from the equator. The average seat bearing stress on the equator annulus, its failure pressure, and margin, report-only |
| `nasa_smooth_cylinder_external_pressure_buckling` | 5.0.0 | NASA SP-8007 Rev. 2 Eqs. 19-29 at shell mid-surface radius; capacity released at every `gamma*Z` except the moderate/long correlation overlap. A complete compressive Ramberg-Osgood curve (`ramberg_osgood_n` with `compressive_proof_stress`) applies the Eqs. 30-32 correction and releases the corrected capacity and margin. Without a curve, a result above the proportional limit remains an elastic upper bound with a null margin (`released_pending_plasticity`). Reference-only data retain the numerical result and margin as `released_unqualified_material`; neither status can pass, but an elastic upper bound below demand and the required margin establishes conservative failure. The existing `R_mid/t > 10` gate is unchanged. Reports Roark Table 35 case 20 as a comparator that sets no capacity. The `elastic_applicability` screen labels the applied `p*r/t` comparison and sets no margin |
| `nasa_ring_stiffened_shell_external_pressure` | 4.0.0 | NASA SP-8007 Rev. 2 Eq. 64/65 with Eqs. 82-91 ring stiffnesses and Eq. 91 torsion, fixed 0.75 adjustment, expanding mode search; advisory only. Its inter-ring bay reuses the smooth-cylinder model, including the Eqs. 30-32 correction when a complete compressive curve is supplied. The orthotropic global modes remain elastic: `global_elastic_applicability` labels an over-limit global pressure as an elastic upper bound but neither corrects nor withholds it. The corrected inter-ring pressure may change the advisory governing candidate, without changing the advisory status. Low-lobe theory error and the fixed 0.75 factor remain limitations |
| `archimedes_submerged_mass_and_buoyancy` | 1.0.0 | Archimedes' principle in Lautrup's constant-gravity form for a fully submerged, rigid, closed, non-flooded body; structural air mass, displaced-fluid mass, net submerged mass, and buoyant-force magnitude from two resolved volumes, two densities, and gravity |
| `hydrostatic_external_pressure_from_depth` | 1.0.0 | Lautrup Eq. (4-3) `p - p0 = rho0*g0*h` in a fluid of one uniform density under uniform gravity; service and design differential external pressure across the wall with the interior at zero gauge, the design pressure scaled by the caller's policy factor |

## Cylinder assessment and design operations

`pv-calc cylinder` composes existing kernels as `cylinder_assessment` 1.0.0.
One internal radius, wall thickness, unsupported length, material, and
closed-end differential pressure drive both `cylindrical_shell_stress` and
`smooth_cylinder_buckling`. The buckling mid-surface radius is the tube's
`internal_radius + wall_thickness / 2`. `inputs.minimum_margin` defaults to zero;
`axial_length` defaults to the unsupported length and cannot be shorter.
Detailed kernel responses remain under `components`. `assessment.checks`
reports unit-bearing demand and released capacity, margin, required margin,
applicability, and reasons for each check. Pending-plasticity and reference-only
pressures appear as estimates in `components` and summary/text output, never as
acceptance capacities. A reference-only estimate retains its numerical margin
for preliminary sizing, but the assessment suppresses that capacity. It remains
indeterminate unless the elastic upper bound under the supplied elastic
properties already proves failure; the corrected reference estimate alone never
sets that failure.

An optional `inputs.closures` array must contain exactly two closures. Each
specifies its own named or explicit material and either `model: plate` with
`plate_thickness` and `boundary_condition`, or `model: hemisphere`. Each inherits
the tube's bore and outside radius. A supplied plate `outside_radius` must match
the tube outside radius; a supplied hemisphere `wall_thickness` must match the
tube wall. These restrictions keep the butt contact annulus and volume
accounting explicit. There is no overhang, inserted spigot, or shell-transition
model. Plates add bending checks and an optional `maximum_deflection` limit;
hemispheres add stress and buckling checks. Deflection uses zero margin against
the supplied limit, independently of the structural minimum-margin target.

Each closure also adds average bearing on the common annulus, using pressure
on the outer projected disc and the weaker category strength of the two
contacting materials. Ductile metal uses yield strength, plastic uses working
strength, and brittle material uses ultimate compressive strength. Brittle
plate bending separately requires ultimate tensile strength. This is the
existing average-seat formula, not a contact-stress solution. Cylinder buckling
assumes simply supported circular ends; plates assume the requested fixed or
simply supported edge, and hemisphere buckling assumes a clamped equator.
The composition does not establish that the physical joints supply those
restraints. Attachment strength, retention, seals, junction bending,
penetrations, and manufacturing/service effects remain unassessed.

`mass_properties` adds component masses and volumes at two non-overlapping
butt planes. Flat discs extend outward, adding solid and displaced volume but
no cavity. Hemispheres extend outward, adding shell, outer-envelope, and inner
cavity volumes. `inputs.payload.mass` and `volume` default to zero, and payload
volume cannot exceed internal geometric volume; shape fit is not evaluated.
`inputs.submergence` additionally supplies buoyancy and total net submerged
mass, including payload. A missing density withholds mass while preserving
geometry and structural checks. With no closures, the displaced envelope uses
massless, zero-thickness end planes and structural mass covers only the tube.
The [housing example](../examples/cylinder_housing.json) demonstrates the full
composition. It adds no pressure-vessel equation or physical validation claim.

The `pv-calc tube size` operation contract is 3.1.0. It finds the smallest
wall thickness inside caller bounds meeting the `cylindrical_shell_stress`
margin under the material category's criterion. Exact Lamé stress is continuous
and decreases with thickness, so there is one interval and no thin/thick
transition. The legacy `branch="thick"` reports use of the exact solution;
`force_thick` remains accepted and echoed but has no effect, in both tube and
hemisphere requests. Buckling's thin-shell limits remain separate.

The `pv-calc smooth-buckling size` operation contract is 4.0.0. It sizes one
closed-end cylinder for both exact tube stress and smooth-shell buckling.
Unsupported length, pressure, and material stay fixed. Both cylinder sizing
operations require exactly one fixed radius: `internal_radius` or
`external_radius`. With fixed bore, the buckling radius is
`internal_radius + wall_thickness / 2`; with fixed outside radius it is
`external_radius - wall_thickness / 2` and the bore is
`external_radius - wall_thickness`. The upper wall bound must be smaller than
the fixed outside radius, retaining a positive bore.
Only `capacity_status="released"` supplies a sizing margin. The search excludes
the correlation overlap and `R_mid/t <= 10`. Without a complete compressive
curve, it also excludes critical membrane stress above the proportional limit.
See the [coverage investigation](../validation/external_pressure_coverage.md)
for the resulting geometry and material-data bounds.

The `pv-calc plate size` operation contract is 2.1.0. It sizes one plate with
fixed free radius, pressure, edge condition, and material for a bending margin
and, optionally, a maximum center deflection. The two checks have separate
targets: the caller's bending margin and zero margin against the supplied
deflection limit. Bending stress decreases as `1/t^2`; deflection decreases as
`1/t^3`. Eligibility is bounded above by the required output's diameter/thickness
floor and below by the shear-corrected small-deflection limit. A deflection
constraint additionally requires the supplied material strength not be exceeded.
An out-of-band Poisson ratio has no eligible thickness. Without a deflection
constraint, that output's stricter floor does not restrict sizing.

Without stock choices, all three operations search known model-eligible intervals
in increasing thickness, verify monotonicity within them, and return the first target crossing
with its forward checks. A crossing within an interval is bisected to a tolerance
of `max(1e-9 mm, 1e-9 * selected_thickness)`, so distant input bounds do not
reduce accuracy at the solution. A NASA branch can instead open above the target: switching
from Eq. 24 to Eqs. 20/22 as thickness increases raises the approximate capacity
by 6.77% under hydrostatic pressure. Such a solution is reported as `branch_start`,
with no false continuous bracket across the jump.
Known regime changes are also reported across excluded intervals, with
`governing_check`, `minimum_margin`, and `margin_jump` null wherever a required
capacity is unavailable.

"Smallest" means smallest among thicknesses the model can evaluate for the
requested checks. An excluded interval lacks a required output; this does not
mean every check is unavailable. Its `lower_check_margins` and
`upper_check_margins` retain independently released endpoint checks, including
negative bending or tube-stress margins. Missing outputs are not inferred.
Adding a deflection constraint can exclude a plate interval without changing
its known bending failure. A missing proportional limit or no eligible thickness
meeting the targets returns `no_reliable_solution`. The
selected forward checks must be released and meet every target. These operations
add no physical equation and have no separate evidence-matrix rows.

All three also accept `inputs.stock_thicknesses`, a list of positive,
unit-bearing thicknesses, or repeated CLI `--stock-thickness` options. Bounds
remain required. Each candidate is checked independently and retained in caller
order with its outcome: `outside_bounds`, `unavailable`, `fails_targets`, or
`meets_targets`. The smallest listed candidate meeting every target is selected;
the operation infers nothing between stock sizes and reports no bisection
bracket. An absent eligible candidate returns `no_reliable_solution` with the
candidate outcomes. Tube and plate sizing optionally accept `axial_length`
and `outside_radius`, respectively, to support selected-design mass in material
comparisons; these inputs do not add a sizing constraint.

The `pv-calc sweep` operation contract is 1.2.0. It runs one complete forward
request over one ordered axis, across the five external-pressure models and
the cylinder composition. The axis is exactly one variable: external pressure,
depth, or a supported geometric dimension. Each point substitutes the corresponding
input and runs that model's own single-point validation, material resolution, kernel, and
serialization path, and the response carries the axis value and the complete
single-point response for every point, so any point is reproducible by a
single-point invocation. Every axis is a list of quantities or start/stop/count;
a list axis substitutes the caller's quantities unchanged, in the order given,
and a range axis interpolates in MPa, m for depth, or mm for geometry, as
`start*(1 - w) + stop*w` with `w = i/(count - 1)`, so the first and last points
are exactly the requested endpoints. A withheld capacity is a normal point
result; a point that cannot be evaluated fails the whole sweep with that point's
own error code, message, and axis position. Like `tube size`, the operation adds
no equation of its own, so it has no row in the table above and none in the
evidence matrix. A geometry axis is declared as `inputs.geometry` plus
`inputs.axis`, for example:

```json
{"geometry": "unsupported_length",
 "axis": {"type": "range", "start": {"value": 100.0, "unit": "mm"},
          "stop": {"value": 300.0, "unit": "mm"}, "count": 5}}
```

`describe sweep` lists the supported input names per model. A cylinder's
closures follow its inherited bore and outside radius; explicitly supplied
closure dimensions must still match at every point. Unsupported substitutions
and simultaneous axes are rejected. Pressure/depth sweep options remain
available in the CLI; geometric axes use JSON.

A depth axis is a composition, not a second calculation. Each depth goes through
`external_pressure_from_depth` with the request's fluid density, gravity, and
design factor, and the resulting **design** differential external pressure is
what the model runs at; the service pressure is reported beside it and drives
nothing. Every point therefore carries its depth, service pressure, design
pressure, and the model result, and the response's `sweep.depth_to_pressure`
block names the conversion's model id and version, its source and pressure
reference convention, the three conversion inputs, and
`substituted_pressure: design_external_pressure`. Fluid density, gravity, and
the design factor are request inputs with no default; the factor is the caller's
policy multiplier, so no value for it comes from a source.

The `pv-calc compare-materials` operation contract is 1.1.0. It runs one forward
or supported sizing request against an ordered list of named materials. Each
listed material replaces the request's top-level `material` and follows the
same evaluation path as a single-material invocation. A cylinder's specified
closure materials remain as requested. Entries preserve the supplied order and
repeats. The operation neither scores materials nor infers missing properties;
it has no service, fabrication, corrosion, availability, or cost model. Records
come from the bundled database or an explicit `--materials-file` override.

Forward comparisons can supply `inputs.mass_properties`, containing the two
resolved volumes, fluid density, and gravity the mass kernel requires. Each
entry then also carries the mass response for those same inputs and its own
material. Sizing comparisons instead derive `selected_geometry` and
`structural_mass` from each selected design, and reject fixed
`inputs.mass_properties` volumes. Tube mass needs `inputs.axial_length`,
smooth-cylinder mass uses `unsupported_length`, and plate mass needs
`outside_radius`; all need material density. Missing mass inputs withhold mass
alone, with a reason, while preserving the sizing result. Shell mass excludes
closures and payload.

A material lacking a required property produces a per-entry
`outcome: invalid_material` rather than ending the comparison. Cylinder
responses instead retain calculable component checks and mark missing required
checks indeterminate. With an explicit forward `inputs.mass_properties` block,
the entry is all or nothing: an incomplete mass calculation replaces that entry
with `invalid_material`, even if its forward result was available. Sizing
comparisons also retain `no_reliable_solution` and `unknown_material` as
per-entry outcomes, allowing the other designs to finish. An unknown name still
fails a forward comparison. Other request, unit, and database faults fail the
whole comparison with their error code and entry position. The operation adds
no equation and has no separate evidence-matrix row.

For example, from a checkout, size the same envelope for two reference alloys:

```python
import json
from pathlib import Path
from pv_calc.api import calculate

sizing = json.loads(Path("examples/smooth_buckling_size_moderate.json").read_text())
comparison = calculate({
    "schema_version": "5.0.0", "model": "compare-materials",
    "inputs": {"materials": ["Al-6061-T6", "Ti-6Al-4V"]},
    "request": sizing,
})
for entry in comparison["comparison"]["entries"]:
    print(entry["material"], entry["outcome"], entry.get("structural_mass"))
```

`pv-calc mass-properties` releases the mass kernel. Net submerged mass is air
mass minus displaced mass, so it is positive when the body is heavier than the
fluid it displaces, zero at neutral buoyancy, and negative when the body is
buoyant; the buoyant force is a magnitude acting opposite gravity. Fluid
density and gravity are required request inputs. The package has no seawater or
standard-gravity default and does not include a fluid database. Both volumes
describe the caller's resolved undeformed geometry. The operation does not
compute geometry or accept an internal volume because internal volume does not
affect the reported quantities. It rejects a structural volume above the
displaced volume, since the
kernel's submergence condition puts the structural material inside the wetted
envelope and the two are equal only for a void-free solid; and a named material
carrying no density fails with `invalid_material`, the same boundary the stress
models use for a missing elastic constant.

The `tube`, `plate`, `hemisphere`, and `smooth-buckling` forward requests take an
optional `inputs.submergence` block, the fluid density and gravity, and with it
the response carries two more top-level blocks, both compositions of released
kernels rather than calculations of their own. `mass_properties` is the
`mass-properties` response for the model's own closed-body volumes and the
material density: a tube of its `axial_length` with weightless closures, a
plate as the solid disc of its `outside_radius`, a hemispherical shell, and a
smooth cylinder as the closed shell of its unsupported length at the
mid-surface radius plus or minus half the wall; each block states the formulas
it used as `volume_basis`. Smooth-shell mass additionally requires
`R_mid - t/2 > 0`; this positive-bore geometry invariant is separate from the
thin-shell buckling gate, so a physically valid thick shell retains mass while
its buckling capacity may be withheld. A tube or plate without the length or
radius the volume needs is refused as `invalid_request`. The density comes from
the named record or from an explicit record's `density`; without one the
request is refused as `invalid_material` rather than answered without weights.
`failure_depths` expresses that model's failure pressures, an explicit per-model
list of result fields, as `h = p / (rho * g)` in the same fluid, the inverse of
the depth axis's conversion, with a withheld pressure keeping its null. The
block's `basis` records that the request's density is one constant, so the
depth carries no rise in seawater density with depth; against a
depth-dependent density the same pressure sits shallower, by a margin that
grows with depth.

[pv_calc/data/materials.yaml](../pv_calc/data/materials.yaml) is the canonical
material database, bundled in the package. The repository-root
[materials.yaml](../materials.yaml) is a compatibility symlink to it.
Named-material lookup uses the bundle regardless of working directory unless
`--materials-file` (or the Python `materials_file` argument) selects another
file; a broken override never falls back. `materials list` and `materials show
NAME` expose properties, provenance, and input availability. They do not assert
that a material is qualified for a particular geometry or service.
The database contains ten SI-unit records. Seven are ductile metals, two are
plastics, and one is brittle glass. Each record carries its own `source`.
Strengths are specification minimums where a specification states one
— ASTM B211, B221/B241, B265, B348, A240, and B443 Grade 1 for the metals, ASTM
D1784 cell classification 12454 for PVC 1120, and ASME PVHO-1 Section 2 for
acrylic — and the record's source text names the basis where none does. Two
categories have none to quote: a plastic's `working_strength_mpa` is an
allowable the designer selects, so each plastic carries a
`working_strength_source` giving the basis of the stored number and what it
does and does not cover, and the brittle record's tensile and compressive
ultimates are vendor data sheet values, which for a glass are nominal figures
for a flaw-dominated property rather than material constants. For the metals,
density, elastic modulus, and Poisson ratio are not specification-governed
either, and each record names the data sheet its nominal values come from.
The generic `Al-7075-T6` record uses 54 ksi, the lowest minimum among the
product forms and thickness bands documented in its provenance.
These values are calculation inputs rather than design allowables. They are not
statistical A-basis or B-basis allowables and have no temperature derating,
weld or heat-affected-zone knockdown, fatigue or notch correction, or
environmental-cracking adjustment. The calculator applies no safety factor.

The bundled Al-6061-T6 and Ti-6Al-4V records provide a `proportional_limit_mpa`
and complete compressive Ramberg-Osgood pair. The curve representation is
`strain = s/E + 0.002*(s/s0)^n`, with `s0` supplied as
`compressive_proof_stress_mpa`, following MIL-HDBK-5J Section 9.8.4.1.2.
The source fields record shape, anchor, product form, direction, and any
substitution. The proportional
limits use this project's `E_tan = 0.99 E` screen, which differs from the
handbook convention of 0.0001 plastic strain (Section 1.4.4.2, p. 1-9).
MIL-HDBK-5J is cancelled; its notice identifies MMPDS as a successor. The
Al-6061-T6 curve describes LT extrusion compression; the Ti-6Al-4V curve describes
longitudinal compression of annealed extrusion, with a tensile minimum substituted
for compression proof stress. These assumptions are unverified for the generic
alloy records, so both use `buckling_data_qualification: reference_only`.

When the model gates pass, these records return `released_unqualified_material`
estimates for calculation and sizing. `check` returns indeterminate unless the
elastic upper bound proves failure. `material.data_qualification` records this
distinction. Explicit inputs and custom records default to `qualified`; JSON
inputs can set `reference_only` on the material object.

Named-material responses preserve relevant derivations in
`material.property_sources`, keyed by `working_strength`, `proportional_limit`,
and `compressive_stress_strain` when the corresponding property is used. The
ordinary `source.provenance` remains available. Explicit-property inputs and
records without an applicable derivation omit the map.

The direct depth input and the `pv-calc sweep` depth axis use
`hydrostatic_external_pressure_from_depth` 1.0.0,
`external_pressure_from_depth`, which returns the service and design external
pressure at a depth in a fluid of one uniform density under uniform gravity. The
returned pressures are differentials across the wall with the interior held at
zero gauge, that is at the surface pressure `p0` of the source equation: no
absolute pressure is formed, and internal gas compression, layered fluids, and
depth-varying density profiles are outside the result. Depth is one scalar below
the free surface, so the vessel's own vertical extent is not resolved. Each
pressure is a single left-to-right product of density, gravity, depth, and, for
the design pressure, the caller's factor, because floating-point multiplication
is not associative and committed evidence pins the doubles that exact
evaluation order produced.

The tube and hemisphere models report exact Lamé stress at the inner and
outer surfaces for every thickness. The thin-wall approximation previously
underestimated the governing material stress by up to about 9.30% for tubes
and 13.54% for hemispheres near the former `r_m/t = 10` switch. Using the
through-wall solution removes that discontinuity and makes the same exact
stress govern forward margins and inverse sizing.

Tube radial displacement and uniform axial strain follow Boresi and Schmidt
Eqs. (11.24) and (11.15), also obtained from the Lamé stress field through
three-dimensional Hooke's law. Radial displacement is reported at each wall
surface, positive outward; axial length change additionally needs a gauge
length. Missing modulus or Poisson ratio withholds deformation as
`withheld_missing_elastic_properties`. The
[tube source record](../validation/sources/tube_scalar_displacement.md) records
the derivation and the historical membrane comparison.

Spherical displacement follows `u/r = (sigma_theta - nu*(sigma_phi + sigma_r))/E`
on the same exact stress field. The
[hemisphere source record](../validation/sources/hemisphere_scalar_displacement.md)
includes the independently published closed form and its membrane limit.
These are complete-sphere stress and displacement values used away from a
hemisphere's equator; they do not solve junction bending or seal closure.
The clamped-equator condition belongs to the NASA buckling correlation.

All deformation formulas assume small strains and linear elasticity. Tube and
hemisphere results expose `maximum_radial_displacement_over_thickness` and
`maximum_absolute_strain`. Deformation release requires the former to be at
most 1 and the latter at most 0.01. Exceeding either gives
`withheld_applicability` and a reason; raw radial displacement and tube axial
deformation remain available as formula estimates.

These are pv-calc release screens, not universal Lamé validity limits. The
one-wall-thickness screen conservatively extends the former DTMB thin-cylinder
restriction to both exact shell models. Uniform radial contraction can exceed
a wall thickness while strains remain small, so this screen can withhold a
valid idealized solution. The separate 1% strain screen includes all three
principal strains and catches large strains in thick walls. At that threshold,
each omitted quadratic Green-strain term is at most 0.5% of its corresponding
linear term; this is not a bound on total stress or displacement error. See the
[tube source record](../validation/sources/tube_scalar_displacement.md#deformation-release-screens)
for the calculation. Neither screen replaces a stability or material check.

If the computed governing material stress exceeds the supplied strength, tube and
hemisphere displacements and plate deflection remain available as raw elastic
formula values, with `elastic_estimate_material_limit` status and a reason.
The plate's `released_maximum_deflection_mm` is then null. Geometric deformation
gates retain precedence as `withheld_applicability`. A strength-based screen
does not establish proportional behavior below yield, stability, or the
response of a material after failure; it simply avoids presenting a known
material-limit exceedance as a released deformation. Closure restraint,
ovalization, buckling, plasticity, and ring-frame deformation remain excluded.

Where a source gives no rule, capacity is withheld instead of guessed:

- Smooth buckling withholds the moderate/long overlap, where `gamma=0.5625`
  in Eqs. 23-25 and `gamma=0.90` in Eqs. 26-27 both apply and NASA gives no
  selection or blending rule. The short region is not withheld: NASA/SP-8007-2020
  Rev 2 inserts `gamma^2` in Eqs. 20/22 and introduces Eq. 23 as their
  `gamma*Z > 100` reduction; this model therefore applies Eq. 28's factor
  inside Eqs. 20/22 as well. Eq. 24 understates their minimum at that boundary
  by about 7% for hydrostatic pressure and 14% for lateral pressure; the
  transition remains a step. The separate `R_mid/t > 10` gate is this
  project's Roark thin-tube convention, not a numeric NASA limit.
- Smooth and hemisphere buckling require a source-traceable proportional limit
  or, for the smooth cylinder only, a complete compressive Ramberg-Osgood
  curve; no fraction of yield strength is substituted. The hemisphere withholds
  capacity when the correlated critical membrane stress exceeds that limit. The
  smooth cylinder corrects it with NASA Eqs. 30-32 when a curve is available,
  and otherwise releases the elastic upper bound as
  `released_pending_plasticity`, with a null ordinary margin.
- Bundled compression curves retain the product-form and direction limits
  described in the material records above. The other five bundled metals carry
  neither a curve nor a proportional limit.
- Ring global and inter-ring instability remain advisory calculator results
  (`capacity_status: advisory`). A complete compressive curve corrects the
  inter-ring smooth-shell pressure; the orthotropic global pressure remains
  elastic, and `global_elastic_applicability` only labels its material-limit
  comparison. The Eq. 64/Eq. 66
  long-cylinder transition has no numeric selector in either NASA edition
  ([source record](../validation/sources/nasa_sp8007_eq64_eq66_transition.md)),
  ring strength/tripping, attachment, and local/global interaction are outside
  the model, and NASA warns of low-lobe formulation error for `n <= 4`. Those
  four ring modes carry `external_blocker` dispositions
  ([source record](../validation/sources/ring_failure_mode_selection.md)):
  DAPS4e.6 supplies Pulos-Salerno-based ring-stress source, Kendrick
  ring-frame-instability material, and fixed BR-7M validation artifacts, but
  none of them is yet mapped independently to this repository's solid-ring
  geometry, conventions, and applicability gates. The software-parity
  cross-check recorded under Sources covers no ring-stiffened case, so these
  modes have no software oracle either.

## Failure coverage

`pv_calc.schemas.MaterialFailureCategory` has three members, the standard
division by how a material reaches its limit and the check each one calls for:
`ductile_metal`, whose von Mises (shell) or surface bending (plate) stress is
compared to a yield strength; `plastic`, whose maximum hoop (shell) or surface
bending (plate) stress is compared to a designer-selected working strength
that carries creep and temperature; and `brittle`, whose compressive shell
hoop stress and seat are compared to an ultimate compressive strength and
whose plate bending stress, on the convex face in tension, to an ultimate
tensile strength. Each result names the criterion it applied as
`failure_criterion`. The category records the *material behavior* a result
assumes and is not the structural failure-mode list. Only the tube, plate, and
hemisphere kernels take it; the two buckling kernels take elastic constants,
an optional proportional limit, and an optional complete compressive curve,
plus a yield strength that only bounds the proportional limit. Structural coverage is the matrix
below, which is documentation: no runtime registry or enum enumerates it.

Column conventions. *Calculated* is what the kernel returns. *Missing* uses
the two omission tokens the ring result already publishes in
`RingModeDisposition` — `not_applicable` (cannot arise for the supported
section or method) and `external_blocker` (an input or source this repository
does not have) — plus `not_implemented` for a mode that is in scope and
sourceable but simply not built. `not_implemented` is a label in this record
only; `RingModeDisposition` does not define it.

| Geometry (model, version) | Material behavior | Structural failures calculated | Known missing structural failures |
|---|---|---|---|
| Tube / cylindrical shell (`closed_end_tube_stress` 3.1.0) | `ductile_metal`, first yield of the exact Lamé stress state against yield strength; `plastic` and `brittle`, the largest hoop stress magnitude against the working or ultimate compressive strength; no post-yield or fracture model. Displacement additionally needs an elastic modulus and a Poisson ratio and is linearly elastic | Exact through-wall radial, hoop, and axial stress at both wall surfaces, principal ordering, 3D von Mises, the category's failure criterion, theoretical failure pressure, margin; scalar radial displacement at each stress-state radius, uniform axial strain, and the axial length change over a supplied gauge length | Tube/endcap junction and interface response — `external_blocker`: the stresses apply away from that interface, and no seat, attachment, or restraint detail exists to model, which is equally why junction bending is outside the displacement. Ovalization, initial out-of-roundness, and plastic deformation — `external_blocker` for the same missing fabrication and post-yield inputs. Shell stability and closure bending are not gaps here; they are the other rows |
| Flat circular plate (`uniformly_loaded_flat_circular_plate` 4.1.0) | Governing surface bending stress against the yield strength (`ductile_metal`), working strength (`plastic`), or ultimate tensile strength (`brittle`); a brittle seat reads the ultimate compressive strength | Maximum radial and tangential bending stress with locations and governing direction, and the margin, released inside the evidence floors; transverse shear `p*D_free/(4*t)` at the support; Kirchhoff center deflection, released on its own stricter floor; with an outside radius, the average seat bearing stress `p*R_o^2/(R_o^2 - R_free^2)`, its failure pressure, and margin | Thick-plate shear-deformation bending below the released `D_free/t` floors — `not_implemented`, those requests are withheld rather than approximated; large-deflection membrane action past `w <= t/2` — `not_implemented`, gated rather than modeled; bearing-contact distribution beyond the average seat stress, attachment, seal, penetration, and compliant real edge restraint — `external_blocker` |
| Hemispherical head (`roark_nasa_hemispherical_head_external_pressure` 5.0.0) | The category's criterion for the stress check, as for the tube; released buckling additionally requires a source-traceable proportional limit at or above the correlated critical membrane stress. Reference-only data return an estimate but not an acceptance capacity. The displacement is linearly elastic and reads the elastic modulus and Poisson ratio this model already requires | Exact Lamé meridional, hoop, and radial stress, von Mises, the category's failure criterion and stress margin; classical sphere critical pressure; NASA SP-8032 clamped-cap correlated pressure and buckling margin, released only for a thin shell with `lambda > 2` and proportional-limit support. The Roark Table 35 case 22 probable minimum is a published comparator and sets no capacity. Exact spherical radial displacement at both wall surfaces, away from the equator. The average seat bearing stress on the equator annulus, its failure pressure, and margin | Equator junction bending, actual restraint, attachments, penetrations, imperfections, residual stress, and plastic interaction — `external_blocker`, and equally why the equator boundary layer is outside the displacement; inelastic buckling correction — `not_implemented`, capacity is withheld instead |
| Smooth cylinder buckling (`nasa_smooth_cylinder_external_pressure_buckling` 5.0.0) | Isotropic; linear elastic unless a complete compressive Ramberg-Osgood curve is supplied. With only a proportional limit, a correlated stress above it remains an elastic upper bound as `released_pending_plasticity`; with a curve, NASA Eqs. 30-32 correct the capacity and release its margin | External-pressure instability of an unstiffened, simply supported cylinder: short, moderate, and long candidates, regime selection, corrected or elastic critical pressure and membrane stress, and margin; the Roark case-20 probable minimum is a comparator only | The moderate/long overlap is withheld because NASA gives no selector; the hydrostatic case uses the lateral-pressure Eqs. 30-32 as NASA directs when biaxial factors are unavailable. The `R_mid/t > 10` gate is unchanged and no new thickness-domain evidence or physical validation was established. End-restraint credit remains `not_implemented` |
| Ring-stiffened shell (`nasa_ring_stiffened_shell_external_pressure` 4.0.0) | One isotropic material for shell and ring. A complete curve corrects the inter-ring smooth-shell result. The orthotropic global mode remains elastic; its applicability screen may use the proportional limit or yield strength but only labels the advisory result | `global_ring_stiffened_shell_eq64_eq91` and `inter_ring_shell_buckling`; both remain `implemented_advisory`, and a corrected inter-ring pressure may change the advisory governing candidate | `long_cylinder_global_eq66_transition`, ring material strength and crippling, frame tripping, attachment and fabrication effects, and local/global interaction remain `external_blocker`; section rules inapplicable to the supported solid ring remain `not_applicable` |

Every row also inherits the service, fabrication, and environment inputs a
real design would still need — tolerances, as-built imperfections, corrosion,
residual stress, attachment route and welds, fatigue and cycling, creep,
temperature, and material variability. Those are design inputs the calculator
does not take rather than omitted equations, so the matrix names one only
where a released result publishes it as its own disposition.

## Sources

| Question | Source |
|---|---|
| Tube, plate, and hemisphere stress | Roark's Formulas for Stress and Strain, 6th ed.: Table 32 cases 1a-1d (tube), Table 24 cases 10a-10b, p. 429 (plate), Table 32 cases 2a-2b, p. 640 (hemisphere) |
| Probable-minimum buckling comparators | Roark's Formulas for Stress and Strain, 6th ed., Table 35 case 22, p. 691 (sphere) and Table 35 case 20 (cylinder), the table's probable minimums; each is reported beside the released capacity and sets none |
| Historical tube membrane limit | DTMB Report 1497 (Pulos and Salerno, 1961), Eq. [5] with Eqs. [A7]-[A10] |
| Exact tube radial displacement and axial strain | Boresi and Schmidt, *Advanced Mechanics of Materials*, 6th ed., Eqs. (11.24) and (11.15) |
| Exact spherical radial displacement | Spherical strain compatibility and 3D Hooke's law; [Coreform verification manual, section 6](https://docs.coreform.com/cifa/verification-manual/problems/solid_mechanics/linear_elastic_stress/pressurized-sphere/pressurized-sphere.html) |
| Hemisphere external-pressure buckling | NASA SP-8032, Section 4.2.1.1, Eqs. 1-4 |
| Historical hemisphere membrane limit | NASA Technical Memorandum 4579 (Ko, 1994), Eq. (5), printed p. 6 |
| Smooth-cylinder buckling | NASA SP-8007 Rev. 2, Eqs. 19-32 |
| Compressive Ramberg-Osgood material curves | MIL-HDBK-5J (31 January 2003), Section 9.8.4.1.2 for the 0.002 power-law form, Section 1.4.4.2 for the proportional-limit convention, and Figures 3.6.2.2.6(i) and 5.4.1.1.6(b,c) for the explicitly supplied illustrative exponents |
| Smooth-cylinder rounded Eq. 25 comparator | NASA SP-8007 Rev. 2, Eq. 25, printed p. 27, which states it only for `nu = 0.316`; its rounded `0.926` stands 0.0873% above the Eq. 24 capacity at that ratio, so it is reported beside Eq. 24 and sets no capacity |
| Ring-stiffened global instability | NASA SP-8007 Rev. 2, Eq. 64/65 and Eqs. 82-91 |
| Rectangular ring torsion constant | NASA/TP-2011-216882, Eq. A16 |
| Experimental ring benchmark | DTMB Report 1324, all ten Table 2 geometries |
| Submerged mass and buoyancy | Archimedes, On Floating Bodies, Book I, Props. 6-7; Lautrup, Physics of Continuous Matter, sec. 5.1, Eqs. (5-5)-(5-8) |
| Hydrostatic pressure at depth | Lautrup, Physics of Continuous Matter, sec. 4.1 "Incompressible sea", Eqs. (4-3) and (4-4) |

- [NASA/SP-8007-2020/REV 2](https://ntrs.nasa.gov/api/citations/20205011530/downloads/20205011530%20Rev%202FINALa%201-2023.pdf)
- [NASA SP-8032](https://shellbuckling.com/papers/classicNASAReports/NASASP-8032.pdf)
- [NASA TM-4579](https://ntrs.nasa.gov/api/citations/19950011002/downloads/19950011002.pdf)
- [NASA/TP-2011-216882](https://ntrs.nasa.gov/api/citations/20110004039/downloads/20110004039.pdf)
- [UnderPressure 4.0 manual](https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf)
- [DTMB Report 1324](https://dome.mit.edu/handle/1721.3/48982)
- [DTMB Report 1497](https://dome.mit.edu/handle/1721.3/48806)
- [B. Lautrup, *Physics of Continuous Matter*, ch. 4 "Fluids at rest", draft revision 7.7 of 2004-01-22](https://cns.gatech.edu/~predrag/courses/PHYS-4421-04/lautrup/7.7/fluids.pdf)
- [B. Lautrup, *Physics of Continuous Matter*, ch. 5 "Buoyancy", draft revision 7.7 of 2004-01-22](https://cns.gatech.edu/~predrag/courses/PHYS-4421-04/lautrup/7.7/buoyancy.pdf)

The UnderPressure 4.0 manual is listed as a comparison target, not as an
equation source. Its published worked examples are the software-parity cases
the evidence matrix records for the tube, plate, hemisphere, and
smooth-cylinder models, and version 4.60 is a version-stamped, human-operated
cross-check of the same kind; `pv-calc` never invokes either, and neither
supplies an equation, a convention, a category definition, or a material value
used here. Parity with it verifies the shared idealized equations, not
real-world behavior, because both implementations share the same analytical
ancestry.

## Validation approach

- **Independent references.** [non_ring_reference.py](../validation/non_ring_reference.py),
  [ring_shell_reference.py](../validation/ring_shell_reference.py),
  [tube_displacement_reference.py](../validation/tube_displacement_reference.py), and
  [hemisphere_displacement_reference.py](../validation/hemisphere_displacement_reference.py)
  re-derive every committed golden, released example, and validity boundary
  from the primary sources using only the standard library, without importing
  production code. Tests compare them against production at tight tolerances
  (non-ring values at `1e-9` relative, ring pressures at `1e-11` relative,
  section properties at `1e-12`). The inventory mapping evidence cases to
  repository artifacts lives in
  [coverage_inventory.py](../validation/coverage_inventory.py), split from the
  reference implementation so artifact moves cannot change the pinned
  `reference_sha256`. Tube displacement remains in a third module because the
  committed P5-03 FEA
  summaries record `manifest.reference_sha256` as the SHA-256 of
  `non_ring_reference.py`, that hash identifies the code that produced the
  committed analytical targets, and no FEA rerun is available to restore it, so
  extending that file would have meant re-stamping a provenance record without
  regenerating it. The module can be folded back in during the next P5-03
  rerun. Hemisphere displacement is a fourth module for the same hash reason.
  It is kept separate from the tube module because it transcribes a different
  source and a different shell geometry.
- **Goldens and examples.** [examples/](../examples/) reproduces the
  software-parity worked cases (9.0401 ksi tube, 9.0384 ksi simply-supported
  plate), the NASA smooth cases, the source-gated hemisphere screen, and all
  ten DTMB ring cases. Beside those it pins the operations that reproduce no
  published result of their own: one case for each of the three sizing
  operations, one pressure and one depth sweep, one material comparison, and
  one illustrative mass-properties case, which is Archimedes arithmetic over
  caller-resolved volumes. Kernel and CLI parity is tested for identical
  inputs.
- **Published benchmark.** The Eq. 64/91 model is compared with Kendrick
  Part III and experiment across the DTMB Table 2 series and reproduces the
  reported `n = 3` and `n = 2` modes. For case 17 the adjusted result is 5.7%
  below Kendrick Part III and 14.7% below experiment; nothing was calibrated
  to the experiment. This establishes
  `benchmark_compared` maturity for the ring model, not general accuracy.
- **FEA.** A pinned, opt-in CalculiX 2.20 container ran the P5-03 tube/plate
  CAX8R comparisons and the P5-04 perfect-geometry ring eigenvalue cases.
  Compact summaries with solver numbers are committed and pinned by tests. The
  converged fixed-plate deflection sits 17.2% above the Roark thin-plate value,
  a failure against the preset 5% limit that is retained and attributed to
  thick-plate shear deformation (`t/a = 0.2`). A 144-solve plate sweep — 126
  primary solves over seven `D_free/t` ratios, three Poisson values, and both
  edges, plus an 18-solve deep-mesh sensitivity study — converts that
  disagreement into the released per-output validity floors, each a solved
  ratio that holds at every solved Poisson value; the deep-mesh study at the
  floor-adjacent cases shows no within-budget decision changes at eight times
  the primary finest mesh. The fixed-edge
  margin-governing stress is compared through its convergent reaction-moment
  resultant, where Kirchhoff errs slightly conservative; the pointwise
  ideal-corner stress is singular and is not used. Across the ten-length ring
  series the finest-mesh eigenvalues run from 14.3% below to 17.3% above the
  unadjusted equation, and two of the ten comparisons cross mode families.
  Nonlinear ring cases stay open: CalculiX has no documented arc-length
  method.
- **Evidence matrix.** [evidence_matrix.yaml](../validation/evidence_matrix.yaml)
  carries one row per released model: maturity (`experimental`,
  `verified_equation`, `benchmark_compared`, `validated_for_scope`),
  completeness, and per-category evidence status. Tube, plate, hemisphere,
  smooth buckling, submerged mass, and hydrostatic pressure at depth are
  `verified_equation`; ring shell is `benchmark_compared`; all seven are
  `partial` because known related failure modes or quantities remain outside
  the models.
- **Evidence dispositions.** Some matrix entries record decisions rather than
  executed artifacts, and this record states them: experimental evidence is
  not required for the tube, plate, submerged-mass, and depth-pressure models,
  whose `verified_equation` maturity claims equation verification against the
  published sources, not physical validation; FEA has
  been executed for the tube and plate models (P5-03) and the ring model's
  eigenvalue cases (P5-04) only, remains not executed for the hemisphere and
  smooth-cylinder models, and is not applicable to the submerged-mass and
  depth-pressure models, which compute no stress or deformation field; and no
  software-parity oracle was selected for the ring, submerged-mass, or
  depth-pressure models, whose comparison evidence is the published
  DTMB/Kendrick benchmark and hand calculation respectively, nor for either
  released displacement, the tube's or the hemisphere's, which the parity
  software does not report. The submerged-mass and depth-pressure models'
  independent-equation evidence is hand-computed values in
  `tests/test_hydrostatics.py` rather than an entry in the two
  reference modules: re-deriving `rho*V`, `rho_f*V*g`, and `rho*g*h` in a
  separate module would restate the kernels line for line instead of checking
  them.
- **Change control.** A change to a formula, convention, factor, applicability
  rule, or model version invalidates every evidence item that depends on it;
  affected cases must be rerun before the matrix status is restored.
  Evidence-only changes do not bump model versions. Whether a consumer
  gates on an advisory result is that consumer's policy, not the
  calculator's.
