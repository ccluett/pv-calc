# pv-calc engineering record

This document describes the released analytical models, their sources, and
the available validation evidence.

The current scope covers smooth and ring-stiffened cylindrical shells under
external hydrostatic pressure, with flat circular or hemispherical end
closures. Stress calculations support ductile metals, plastics, and brittle
materials, using a failure criterion appropriate to each category. Annular
endcaps, complete spheres, cones, and internal-pressure workflows are not yet
included. All released calculations are advisory. Fabrication,
service use, and certification require separate qualification outside this
repository.

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
| `closed_end_tube_stress` | 2.0.0 | Thin membrane stress at mean radius above `r_m/t = 10`, closed-end Lamé at or below it; the material check follows the failure category: 3D von Mises against yield strength for `ductile_metal`, maximum hoop stress against the working strength (`plastic`) or ultimate compressive strength (`brittle`), component stresses stay report-only. Scalar radial displacement at each stress-state radius, uniform axial strain, and an axial length change over a supplied gauge length, released only when the caller gives both an elastic modulus and a Poisson ratio |
| `uniformly_loaded_flat_circular_plate` | 3.0.0 | Roark cases 10a/10b for a declared fixed or simply-supported edge, the surface bending stress compared to the yield, working, or (brittle) ultimate tensile strength; requires `w <= t/2` on a shear-corrected deflection estimate, `0.05 <= nu <= 0.35`, and, from swept FEA evidence, `D_free/t >= 10` (fixed) or `>= 4` (simply supported) to release the bending margin, with the center deflection released only at `>= 20` and `>= 10`; outside those the formula values stay published and the margin or deflection is withheld with its reasons. With an optional outside radius, the average seat bearing stress on the outside annulus, its failure pressure, and margin, thickness-independent and report-only |
| `roark_nasa_hemispherical_head_external_pressure` | 3.0.0 | Roark thin/thick sphere stress under the category's criterion, as for the tube, plus NASA SP-8032 clamped-cap buckling; capacity released only for a thin shell with `lambda > 2` and a source-traceable proportional limit. One scalar membrane radial displacement at the thin branch's median surface, away from the equator; the thick-sphere branch withholds it for want of a source. The average seat bearing stress on the equator annulus, its failure pressure, and margin, report-only |
| `nasa_smooth_cylinder_external_pressure_buckling` | 3.0.0 | NASA SP-8007 Rev. 2 Eqs. 19-29 at shell mid-surface radius; capacity released at every `gamma*Z` except the moderate/long correlation overlap, and released as an elastic upper bound (`released_pending_plasticity`) where the correlated critical membrane stress exceeds the proportional limit. A yield strength is optional and only bounds the proportional limit. Reports Roark Table 35 case 20, its theoretical pressure minimized over integer lobes and reduced by the table's 0.80 probable-minimum factor, as a published comparator that sets no capacity. An `elastic_applicability` screen compares the applied `p*r/t` with the proportional limit, or with yield strength when no proportional limit is supplied, and names which it used; it withholds nothing and sets no margin |
| `nasa_ring_stiffened_shell_external_pressure` | 2.0.0 | NASA SP-8007 Rev. 2 Eq. 64/65 with Eqs. 82-91 ring stiffnesses and Eq. 91 torsion, fixed 0.75 adjustment, expanding mode search; advisory only. A yield strength is optional; besides bounding the proportional limit as for the smooth cylinder, it is the fallback applicability limit here. `global_elastic_applicability` compares the shell membrane stress the global capacity implies, `p_cr*r/t`, with the proportional limit or, failing that, the yield strength; NASA states plasticity factors for unstiffened cylinders only, so an over-limit global pressure is labelled an elastic upper bound, not corrected and not withheld. `advisory_candidate_modes` lists the modes that actually entered the `advisory_governing_mode` minimum, which admits every mode whose pressure was not withheld — one labelled an elastic upper bound included, since plasticity could only reduce that elastic estimate — and a mode absent from the list was withheld rather than compared. `advisory_governing_status` says whether the selected pressure is such a bound, and describes that mode alone: the global capacity is regularly over the limit while a lower inter-ring capacity wins the minimum, so read `global_elastic_applicability` alongside it. None of these pressures is a rigorous bound on the real structure; the low-lobe theory error and the 0.75 factor keep them advisory elastic estimates |
| `archimedes_submerged_mass_and_buoyancy` | 1.0.0 | Archimedes' principle in Lautrup's constant-gravity form for a fully submerged, rigid, closed, non-flooded body; structural air mass, displaced-fluid mass, net submerged mass, and buoyant-force magnitude from two resolved volumes, two densities, and gravity |
| `hydrostatic_external_pressure_from_depth` | 1.0.0 | Lautrup Eq. (4-3) `p - p0 = rho0*g0*h` in a fluid of one uniform density under uniform gravity; service and design differential external pressure across the wall with the interior at zero gauge, the design pressure scaled by the caller's policy factor |

The `pv-calc tube size` operation contract is 2.1.0. It sizes any failure
category under the `cylindrical_shell_stress` check, the tube's material check
under the category's own criterion, named for the structural mode as the
plate's `flat_endcap_bending` is; the selected forward result's
`failure_criterion` says which stress met which strength. It partitions the
wall-thickness bounds at the tube kernel's documented thin/thick transition,
uses the monotonic margin on each known branch, and bisects the first fail/pass
bracket. Its one boundary steps the margin down, never up, so a bracket is the
only way this operation reaches a target above the lower bound.

The `pv-calc smooth-buckling size` operation contract is 2.1.0. It solves the
same one variable, wall thickness, inside caller bounds, for a target minimum
margin taken across both `cylindrical_shell_stress` and `smooth_cylinder_buckling`,
and shares the bracket, monotonicity, and bisection mechanics with `tube size`;
only the margin function and the branch partition differ. One cylinder carries
both checks, so the internal radius is the fixed input and the buckling model's
shell mid-surface radius is `internal_radius + wall_thickness / 2` at every
candidate, which is the tube model's own mean radius; the load case is not an
input, because the tube kernel calculates only the closed-end hydrostatic
one and `lateral_only` would put a different axial load on the wall that kernel
reads. The partition covers every branch boundary that applies: the tube
thin/thick transition, the buckling thin-shell limit, and the four NASA regime
boundaries. None of them is a constant in thickness. The two ratio limits have
an exact root, `t = r_i / (limit - 0.5)`, because the mean radius is
`r_i + t/2`; the four regime boundaries have no closed form, so each is
bisected on the comparison the kernel itself reports, which is monotone in
thickness because `Z = L^2*sqrt(1-v^2)/(r*t)` falls as `r*t` rises and the sign
of `gamma*Z - 11.8*(r/t)^2*(1-v^2)` is the sign of
`gamma*L^2*t/r^3 - 11.8*sqrt(1-v^2)`, whose `t/r^3` rises while `t < r_i`. The
derived thicknesses are reported, inside the bounds or not.

Capacity is not continuous across those boundaries, and one of them steps it
up: at `gamma*Z = 100` the released capacity switches from Eq. 24 to the
Eqs. 20/22 minimization and rises by 6.77% for `hydrostatic_closed_end`, or
14.31% for `lateral_only`, as the wall thickens. A target between the margin
the moderate branch reaches at that thickness and the one the short branch
opens with is met by no bracket at all, because no evaluated pair straddles it.
The solver therefore walks the branch intervals upward and takes the first one
whose opening thickness already meets every target, reported as a
`solution_type` of `branch_start` with no verified bracket. Every branch below
it was evaluated failing at both ends first, so that thickness is still the
smallest in the bounds that meets the target. `tube size` shares the mechanics
but not the case: its only boundary steps the margin down.

A smooth-cylinder capacity that is withheld, or released only as an elastic
upper bound pending plasticity, is not a sizing margin, so any thickness the
search has to evaluate that reaches either state ends the operation with
`no_reliable_solution` naming the thickness, the regime, the capacity status,
the reasons, and the derived partition. Only Al-6061-T6 and Ti-6Al-4V carry a
proportional limit in `materials.yaml`, so every other named record reaches
that path; the null is intended, and is not to be filled with a fraction of
yield. The exercised cases cover a material with no proportional limit, a
mid-surface radius to thickness ratio at or below 10, a correlated critical
membrane stress above the proportional limit, and bounds that span the withheld
moderate/long overlap, which have to be narrowed to one released region. Both
bounds and the thicknesses either side of every interior boundary are evaluated
before a solution is returned, so a selected thickness is the smallest in the
bounds that meets the target and every thickness below it was evaluated on a
released basis.

For a ductile metal, **the buckling margin does not exceed the stress margin
when the buckling capacity is fully released.** This relationship
determines what the sizing operation can report. The `released` status — not
`released_pending_plasticity`, which sizing refuses — requires the correlated
critical circumferential stress to be at or below the proportional limit,
which the kernel requires to be at or below the yield strength. Yielding
governs only when that same stress is above `2/sqrt(3)` times the yield strength,
because the closed-end thin-wall
von Mises stress is `sqrt(3)/2` times the hoop stress and both checks read one
hoop stress at one `r/t`. The two cannot hold together. A released capacity
also forces the thin tube branch, since both models put their own limit at
`r_m/t = 10`, so the tube thin/thick boundary is in the partition for
completeness and never separates two released thicknesses. A plastic's working
strength or a brittle material's ultimate compressive strength is not ordered
against its proportional limit, so for those categories either check may
govern and a governing-check change can occur inside the bounds. The governing
check is therefore calculated and reported at every evaluated thickness rather
than assumed; for a ductile metal a governing-check change is reportable but
does not occur, while a buckling-regime change does, and is reported.

This sizing operation adds no equation of its own and therefore has no row in
the model table or evidence matrix.

The `pv-calc plate size` operation contract is 1.1.0. It solves one variable,
the plate thickness, inside caller bounds, for a target bending margin and an
optional maximum centre deflection, and shares the bracket, monotonicity, and
bisection mechanics with the two wall-thickness operations. No shell variable
is coupled to it: the free radius, pressure, edge condition, and material are
fixed, and the closure is sized on its own.

Its two constraints are not the same kind of thing, so they carry separate
targets, which is the one change the shared solver needed:
`inputs.minimum_margin` is the bending margin, and `inputs.maximum_deflection`
is a limit, met at margin zero rather than at the bending target. Both margins
keep the allowable/actual − 1 form the kernels use, the second against the
caller's own limit and the released Kirchhoff centre deflection, so the
operation adds no equation and has no row in the table above or in the evidence
matrix. The reported decision quantity is therefore the smallest slack against
those targets rather than the smallest margin, and the governing constraint is
the check holding it.

Plate sizing does not need a branch partition. Both released margins are smooth
and strictly rising in thickness
across the whole released band — the governing bending stress goes as
`(free_radius/thickness)^2` and the centre deflection as `1/thickness^3`, with
coefficients that depend on the Poisson ratio and the edge alone — so the
bounds are one continuous piece with nothing to split at. The evidence floors
are refusal conditions, not branch boundaries: they withhold an output rather
than move a margin. The rise is still verified against every evaluated
thickness, the same guarantee the wall-thickness operations give.

What does move with the thickness is the validity, and in both directions, so
the floors are re-read at every candidate rather than resolved once. The two
`D_free/t` evidence floors are upper limits on thickness — 10 and 4 for
bending, 20 and 10 for the centre deflection, fixed and simply supported
respectively — while the `w <= t/2` small-deflection gate on the
shear-corrected estimate is a lower limit, so the released band is bounded on
both sides and its ends depend on the pressure, radius, edge, and elastic
properties. Only the outputs a request needs are required: without a maximum
deflection the centre deflection constrains nothing and its stricter floor
decides nothing, which is why the same bounds can be answerable with the
bending target alone and refused once a deflection limit is added. A needed
output the model withholds is not a margin, so any thickness the search has to
evaluate that withholds one ends the operation with `no_reliable_solution`
naming the thickness, the withheld outputs, the reasons, both floors, and the
achieved ratios. That covers a Poisson ratio outside the `0.05 <= nu <= 0.35`
evidence band, which withholds both outputs at every thickness.

The `pv-calc sweep` operation contract is 1.1.0. It runs one complete forward
request over one ordered axis, across the five external-pressure models. The
axis is exactly one variable: external pressure, or depth. Each point
substitutes a pressure into the request's `inputs.external_pressure` and runs
that model's own single-point validation, material resolution, kernel, and
serialization path, and the response carries the axis value and the complete
single-point response for every point, so any point is reproducible by a
single-point invocation. Either axis is a list of quantities or start/stop/count;
a list axis substitutes the caller's quantities unchanged, in the order given,
and a range axis interpolates in MPa, or in m for a depth axis, as
`start*(1 - w) + stop*w` with `w = i/(count - 1)`, so the first and last points
are exactly the requested endpoints. A withheld capacity is a normal point
result; a point that cannot be evaluated fails the whole sweep with that point's
own error code, message, and axis position. Like `tube size`, the operation adds
no equation of its own, so it has no row in the table above and none in the
evidence matrix.

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

The `pv-calc compare-materials` operation contract is 1.0.0. It runs one fixed
forward request against an ordered list of named materials across the same five
external-pressure models. Because it adds no equation, it has no row in the
model table or evidence matrix.
Each listed material replaces the request's own `material` field and runs that
model's single-point validation, material resolution, kernel, and serialization
path, so an entry equals the response of the same single-material invocation.
Entries come back once per listed name, in the caller's order, including
repeats. The operation preserves the list without scoring or recommending
materials because the package has no information about service, fabrication,
corrosion, availability, or cost. Every compared material is a named entry in
the explicit `--materials-file` database. The list does not accept explicit
property records or infer one property from another. When
the request supplies `inputs.mass_properties`, the two volumes, fluid density,
and gravity the mass kernel needs, each entry also carries the
`mass-properties` response for the same material from those same inputs, so the
entries differ only by the material.

If a listed material lacks a property needed by the requested calculation, its
entry carries
`outcome: invalid_material` with that model's own message and no result, and
every other entry is unaffected. That is the per-model `invalid_material`
boundary a single-material invocation already reports, carried as one entry's
outcome instead of ending the run, and the comparison still exits zero, because
a database that mixes stress-only and complete records is the ordinary case this
operation exists to survey. An entry is all or nothing: when the forward model
succeeds and the mass properties do not, or the reverse, the entry is
`invalid_material` and the message names which of the two was incomplete.
Everything else, an unknown name, a missing or unreadable database, a request or
unit fault, is a property of the list or of the request rather than of one
material, so it fails the whole comparison with its own error code and the
failing entry's position.

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
it used as `volume_basis`, and a tube or plate without the length or radius the
volume needs is refused as `invalid_request`. The density comes from the named
record or from an explicit record's `density`; without one the request is
refused as `invalid_material` rather than answered without weights.
`failure_depths` expresses that model's failure pressures, an explicit per-model
list of result fields, as `h = p / (rho * g)` in the same fluid, the inverse of
the depth axis's conversion, with a withheld pressure keeping its null. The
block's `basis` records that the request's density is one constant, so the
depth carries no rise in seawater density with depth; against a
depth-dependent density the same pressure sits shallower, by a margin that
grows with depth.

[materials.yaml](../materials.yaml) is the material database published with the
repository. It contains ten SI-unit records. Seven are ductile metals, two are
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
These values are calculation inputs rather than design allowables. They are not
statistical A-basis or B-basis allowables and have no temperature derating,
weld or heat-affected-zone knockdown, fatigue or notch correction, or
environmental-cracking adjustment. The calculator applies no safety factor.

`proportional_limit_mpa` is not a specification minimum, and no consulted
handbook tabulates one, so only Al-6061-T6 and Ti-6Al-4V carry a value; each
is derived, and its `proportional_limit_source` records the MIL-HDBK-5J
compressive Ramberg-Osgood shape used, the specification-minimum yield it is
anchored at, and the tangent-modulus-at-0.99-E criterion, which is this
project's choice because the handbook states none. Every other record is null:
no compressive Ramberg-Osgood shape was located for the remaining metals, the
plastics' stored allowable is a long-term quantity that no elastic-limit
criterion attaches to, and releasing a buckling capacity for a flaw-dominated
glass on an elastic screen would claim more than its data sheet supports. A
null limit withholds elastic buckling capacity rather than defaulting it, which
is what the hemisphere and smooth-cylinder buckling models require of it.

The `pv-calc sweep` depth axis releases
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

The tube model reports deformation as well as stress. Radial displacement is
positive outward, so external pressure gives a negative value, and it is carried
by each stress state at that state's own radius: the median surface on the thin
branch, the internal and external surfaces on the thick branch. Axial strain is
positive in extension and is one number, uniform through the wall and along the
tube in both branches; the axial length change is that strain times a gauge
length the caller may supply. Both branches take their equations from a source
that states them for this load case and end condition — DTMB 1497 Eq. [5] with
Eqs. [A7]-[A10] for the thin branch, Boresi and Schmidt Eqs. (11.24) and (11.15)
for the thick one — and both are recorded per branch, with their conventions,
surfaces, assumptions, and exclusions, in
[the displacement source record](../validation/sources/tube_scalar_displacement.md).
An elastic modulus and a Poisson ratio are optional inputs: without both, every
stress result is unchanged and displacement is withheld as
`withheld_missing_elastic_properties` with one violation string per missing
property, the same shape the buckling models use for a missing proportional
limit. The two branches differ at the `r_m/t = 10` switch by the amount the
thin-wall approximation is wrong by, and two of those ratios are free of the
Poisson ratio: `b^2/r_m^2` for the axial strain, exactly 1.1025 at the switch and
the same discrete step already documented for the equivalent stress, and
`a b^2/r_m^3` for the internal-surface displacement, exactly 1.047375. Junction
effects, local restraint at closures, ovalization, instability, plasticity, and
ring-frame restraint are outside the displacement exactly as they are outside the
stress. On the thin branch the deformation quantities are withheld when
`abs(radial_displacement) > wall_thickness`, the explicit DTMB 1497 reliability
boundary; equality remains released. No unsourced counterpart is imposed on the
thick branch.

The hemisphere model reports one deformation quantity, and only where a source
states it. Its thin branch carries the membrane radial displacement
`-p r_m^2 (1 - nu) / (2 E t)` at the median surface, positive outward; its
thick-sphere branch reports none. The source is NASA TM-4579 Eq. (5), which
states that displacement on the same line as the membrane stress
`sigma_theta = sigma_phi = p R / (2 t)` this branch already releases, and
applies both to the hemispherical bulkheads of the vessel it analyses. The
displacement is therefore the kinematic companion of the released membrane
stress and carries the same assumptions. The clamped-equator condition applies
only to the SP-8032 buckling correlation. The released value
is therefore the value away from the equator — not the equator's radial closure
and not a seal-gap estimate — and the same source draws that line itself, in
attributing the deformed shapes at its cylinder-hemisphere junctures to the
radial-displacement mismatch there. The thick branch withholds with
`withheld_missing_thick_branch_source`: no consulted primary source states a
thick-sphere radial displacement, and none is derived from the released Lamé
field here. Both the equation and that recorded gap are in
[the hemisphere displacement source record](../validation/sources/hemisphere_scalar_displacement.md).
No numeric validity gate is added to the hemisphere displacement; it inherits
the model's existing `r_m/t = 10` switch, and its source states no counterpart
to the tube's DTMB displacement/thickness boundary. The two
released thin displacements come from different sources, DTMB 1497 Eq. [5] and
NASA TM-4579 Eq. (5), and their ratio at one shared geometry is the
`(2 - nu)/(1 - nu)` that TM-4579 Eq. (6) publishes.

Where a source gives no rule, capacity is withheld instead of guessed:

- Smooth buckling withholds only the moderate/long overlap, where `gamma=0.5625`
  in Eqs. 23-25 and `gamma=0.90` in Eqs. 26-27 both apply and NASA gives no
  selection or blending rule. The short region is not withheld: NASA/SP-8007-2020
  Rev 2 states that "The term `gamma^2` has been added to Eq. 20 and Eq. 22 as a
  correction for the difference between theory and test", and introduces Eq. 23
  as what those reduce to "For `gamma*Z > 100`", so Eq. 28's factor belongs
  inside the general equations rather than only in their simplification. Eqs.
  20/22 are minimized over `beta` at every `gamma*Z`, which is what Figure 4-3
  plots. Eq. 24 remains the released capacity above `gamma*Z = 100`, where the
  source prescribes it; it understates the exact minimum at that boundary by
  about 7% for `hydrostatic_closed_end` and about 14% for `lateral_only`, and
  that step is reported rather than smoothed.
- Smooth and hemisphere buckling require a source-traceable proportional limit;
  no fraction of yield strength is substituted. The hemisphere additionally
  withholds capacity when the correlated critical membrane stress exceeds that
  limit; the smooth cylinder releases the elastic upper bound instead, as
  `released_pending_plasticity`.
- The hemisphere's thick-sphere branch withholds radial displacement. Its
  released stress source is a stress table, the released displacement source is
  a thin-shell membrane result, and no consulted source states the thick-sphere
  displacement in a form this repository could verify.
- Ring global and inter-ring instability remain advisory calculator results
  (`capacity_status: advisory`), and neither the global plasticity screen nor
  the advisory minimum changes that: both label a pressure, neither releases or
  withholds one. The Eq. 64/Eq. 66
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
hemisphere kernels take it; the two buckling kernels take elastic constants
and an optional proportional limit, plus an optional yield strength that only
bounds that limit. Structural coverage is the matrix
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
| Tube / cylindrical shell (`closed_end_tube_stress` 2.0.0) | `ductile_metal`, first yield of the membrane or Lamé stress state against yield strength; `plastic` and `brittle`, the largest hoop stress magnitude against the working or ultimate compressive strength; no post-yield or fracture model. Displacement additionally needs an elastic modulus and a Poisson ratio and is linearly elastic | Through-wall radial, hoop, and axial stress (thin membrane at mean radius above `r_m/t = 10`, closed-end Lamé at or below), principal ordering, 3D von Mises, the category's failure criterion, theoretical failure pressure, margin; scalar radial displacement at each stress-state radius, uniform axial strain, and the axial length change over a supplied gauge length | Tube/endcap junction and interface response — `external_blocker`: the stresses apply away from that interface, and no seat, attachment, or restraint detail exists to model, which is equally why junction bending is outside the displacement. Ovalization, initial out-of-roundness, and plastic deformation — `external_blocker` for the same missing fabrication and post-yield inputs. Shell stability and closure bending are not gaps here; they are the other rows |
| Flat circular plate (`uniformly_loaded_flat_circular_plate` 3.0.0) | Governing surface bending stress against the yield strength (`ductile_metal`), working strength (`plastic`), or ultimate tensile strength (`brittle`); a brittle seat reads the ultimate compressive strength | Maximum radial and tangential bending stress with locations and governing direction, and the margin, released inside the evidence floors; transverse shear `p*D_free/(4*t)` at the support; Kirchhoff center deflection, released on its own stricter floor; with an outside radius, the average seat bearing stress `p*R_o^2/(R_o^2 - R_free^2)`, its failure pressure, and margin | Thick-plate shear-deformation bending below the released `D_free/t` floors — `not_implemented`, those requests are withheld rather than approximated; large-deflection membrane action past `w <= t/2` — `not_implemented`, gated rather than modeled; bearing-contact distribution beyond the average seat stress, attachment, seal, penetration, and compliant real edge restraint — `external_blocker` |
| Hemispherical head (`roark_nasa_hemispherical_head_external_pressure` 3.0.0) | The category's criterion for the stress check, as for the tube; released buckling additionally requires a source-traceable proportional limit at or above the correlated critical membrane stress. The displacement is linearly elastic and reads the elastic modulus and Poisson ratio this model already requires | Thin/thick meridional, hoop, and radial stress, von Mises, the category's failure criterion and stress margin; classical sphere critical pressure; NASA SP-8032 clamped-cap correlated pressure and buckling margin, released only for a thin shell with `lambda > 2` and proportional-limit support. The Roark Table 35 case 22 probable minimum is a published comparator and sets no capacity. One scalar membrane radial displacement at the thin branch's median surface, away from the equator. The average seat bearing stress on the equator annulus, its failure pressure, and margin | Equator junction bending, actual restraint, attachments, penetrations, imperfections, residual stress, and plastic interaction — `external_blocker`, and equally why the equator boundary layer is outside the displacement; inelastic buckling correction — `not_implemented`, capacity is withheld instead; thick-sphere radial displacement — `external_blocker`, no consulted source states it, so it is withheld rather than derived |
| Smooth cylinder buckling (`nasa_smooth_cylinder_external_pressure_buckling` 3.0.0) | Isotropic and linear elastic; `MaterialFailureCategory` is not an input. Release requires a source-traceable proportional limit; a correlated critical membrane stress above it releases an elastic upper bound as `released_pending_plasticity`. Applying the same comparison to the working stress `p*r/t` says whether every capacity at or above the applied pressure is such a bound, which is what `elastic_applicability` reports | Elastic external-pressure instability of an unstiffened, simply supported cylinder: short, moderate, and long candidates, regime selection, correlated critical pressure and circumferential membrane stress, margin; the Roark case-20 probable-minimum pressure and lobe count as a published comparator that sets no capacity. Capacity is released at every `gamma*Z` except the moderate/long overlap | Moderate/long factor-transition correlation — `external_blocker`: NASA gives no rule where `gamma=0.5625` and `gamma=0.90` both apply; inelastic correction from NASA Eqs. 30-32 — `not_implemented`, so a critical membrane stress above the proportional limit releases an elastic upper bound as `released_pending_plasticity`; longitudinal and rotational end-restraint credit — `not_implemented`, no capacity increase is taken |
| Ring-stiffened shell (`nasa_ring_stiffened_shell_external_pressure` 2.0.0) | Isotropic and linear elastic, one material for shell and ring; `MaterialFailureCategory` is not an input. The inter-ring result inherits the smooth kernel's proportional-limit gate, which requires that limit to release at all and takes no yield fallback. The global mode has no such gate: `global_elastic_applicability` only labels the comparison, and it falls back to the yield strength when no proportional limit is given, because NASA offers no plasticity factor for the smeared orthotropic mode to correct an over-limit result with | `global_ring_stiffened_shell_eq64_eq91` (Eq. 64/65 with Eqs. 82-91 smeared ring stiffnesses, Eq. 91 rectangular-ring torsion, the fixed 0.75 adjustment, and an expanding mode search) and `inter_ring_shell_buckling` (the smooth kernel over ring center-to-center spacing); both are `implemented_advisory`, because NASA reports 10-40% low-lobe theory error and states no numeric Eq. 64/Eq. 66 transition | `long_cylinder_global_eq66_transition`, `ring_material_strength_and_crippling`, `frame_tripping_or_out_of_plane_rolling`, `attachment_weld_and_fabrication_effects`, and `local_global_interaction` — `external_blocker`, the last four surveyed and left open in [the ring failure-mode selection record](../validation/sources/ring_failure_mode_selection.md); `separate_frame_inertia_rule`, `web_and_flange_local_slenderness`, and `classification_inter_stiffener_strength` — `not_applicable` |

Every row also inherits the service, fabrication, and environment inputs a
real design would still need — tolerances, as-built imperfections, corrosion,
residual stress, attachment route and welds, fatigue and cycling, creep,
temperature, and material variability. Those are design inputs the calculator
does not take rather than omitted equations, so the matrix names one only
where a released result publishes it as its own disposition.

## Sources

| Question | Source |
|---|---|
| Tube, plate, and hemisphere stress | Roark's Formulas for Stress and Strain, 6th ed.: Table 28 case 1c and Table 32 cases 1a-1d (tube), Table 24 cases 10a-10b, p. 429 (plate), Table 28 case 3a, p. 523 and Table 32 cases 2a-2b, p. 640 (hemisphere) |
| Probable-minimum buckling comparators | Roark's Formulas for Stress and Strain, 6th ed., Table 35 case 22, p. 691 (sphere) and Table 35 case 20 (cylinder), the table's probable minimums; each is reported beside the released capacity and sets none |
| Thin-branch tube radial displacement and axial strain | DTMB Report 1497 (Pulos and Salerno, 1961), Eq. [5] with Eqs. [A7]-[A10] |
| Thick-branch tube radial displacement and axial strain | Boresi and Schmidt, *Advanced Mechanics of Materials*, 6th ed., Eqs. (11.24) and (11.15) |
| Hemisphere external-pressure buckling | NASA SP-8032, Section 4.2.1.1, Eqs. 1-4 |
| Hemisphere thin-branch radial displacement | NASA Technical Memorandum 4579 (Ko, 1994), Eq. (5), printed p. 6 |
| Smooth-cylinder buckling | NASA SP-8007 Rev. 2, Eqs. 19-29 |
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
