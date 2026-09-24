# Changelog

Notable changes to pv-calc are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The
JSON request/response contract carries its own version
(`CALC_SCHEMA_VERSION`), independent of the package version, as does each
model; both predate this changelog.

## [Unreleased]

- Ring-shell model 5.1.0 -> 6.0.0:
  - When the inter-ring bay falls in the NASA moderate/long correlation
    overlap, the lowest buckling pressure is no longer the global mode alone.
    The bay is withheld there on every material path, so the old minimum
    could sit far above both bay candidates (over 100 times in one synthetic
    case). The lowest pressure is now not established: the candidate list is
    empty, the governing fields are null, and a note says why. The global and
    yield pressures are still reported, and text and summary output say the
    lowest pressure is not established.
  - The smeared global search admits only axial half-waves longer than one
    ring spacing, and always `m = 1`. Sampled at the rings, a longer sine
    moves them with the smeared strain energy; at one spacing the rings can
    sit at the nodes, and shorter waves fall between rings, where the smeared
    ring stiffness does not apply and the inter-ring check does. One
    committed test case had governed at `(m, n) = (42, 2)`, an 11.9 mm
    half-wave against a 20 mm spacing; the smeared branch now stops at
    `(24, 2)`, ideal 19.45 -> 30.63 MPa, and the inter-ring bay still governs.
    A half-wave between one and two spacings is kept: in a case governing at
    1.54 spacings, an independent discrete-ring model agrees with the smeared
    value to 0.1%, and a two-spacing screen would have reported it 10% high.
    When the minimum sits on the limit and a shorter wave would be lower,
    `axial_half_wave_limit_binding` is true and a note says so. Every
    admissible `m` is evaluated from the first pass, so only `n` expands.
    `mode_domain` becomes `1<=m<=maximum_axial_half_waves_m,n>=2`, with
    `maximum_axial_half_waves_m`, `axial_half_wave_limit_binding`, and
    `critical_half_wave_over_ring_spacing` added. The smeared-ring note cites
    NASA's own caveats: its orthotropic equations lose accuracy for `n <= 4`
    (printed p. 35), and a discrete-ring theory gives somewhat lower pressures
    (p. 38). The DTMB examples keep their `m = 1` modes and pressures; their
    search evidence (bounds, mode counts, frontier) changes.
  - Report `ring_first_yield_pressure_mpa`: the pressure at which the ring's
    largest hoop stress, at its smallest radius, reaches yield. That is the
    free edge of an internal ring and the base of an external ring at the
    shell, because each ring section translates radially and its hoop strain
    is `w_ring / r`. It is below the centroid (mean) ring yield by the
    ring's half-depth over its centroid radius, `(h/2)/R_c`: 2.0% for the
    DTMB 1324 examples. It is hoop stress only, in a perfect shell.
    `axisymmetric_stress` adds the location, radius, and stress per unit
    pressure; text and summary output show it beside the mean ring yield,
    which is unchanged.
  - The inter-ring bay's material comparisons read the periodic bay's
    mid-bay hoop membrane stress instead of the unstiffened `p*r/t`. NASA
    defines its Eqs. 30-32 plasticity factor at the circumferential stress
    `p*r/t` of an unstiffened shell; between rings, which carry part of the
    hoop load, this extends that definition to the bay's own mid-bay stress.
    With a compressive curve the corrected bay pressure now solves
    `p = p_elastic * eta(k * p)` with the bay's own `k`. In invented titanium
    bays it rises 3-27%, and up to about 2x for heavily ringed short bays;
    where a long bay's mid-bay deflection overshoots the free shell's, the
    stress is up to about 7% above `p*r/t` and the pressure falls slightly.
    The committed ring display test's corrected aluminium bay moves from
    7.33657 to 7.76432 MPa. Without a curve the pressure is unchanged, but
    the proportional-limit label and the reported critical stresses use the
    bay stress, so a bay whose own stress is within the limit is no longer
    called an elastic upper bound. When a corrected bay pressure exceeds Pc5,
    a note says interframe collapse can govern.
  - The ring result's yield note, the model assumptions, and the engineering
    record state that the pressure acts at the shell mid-surface radius, as in
    the PD 5500 form and as DAPS4 takes the hoop load. Exact equilibrium with
    the load on the outer surface would raise the unstiffened mean hoop
    stress by `R_o/R = 1 + t/(2R)` and the bay's slightly less. The numbers
    are unchanged.
- Smooth-buckling model 5.0.0 -> 5.1.0: results add
  `circumferential_stress_basis` and `circumferential_stress_per_unit_pressure`,
  naming the stress compared with material data. A smooth shell uses
  `p*r/t` as before; its numbers are unchanged.
- The tests pass the bundled `pv_calc/data/materials.yaml` by path instead of
  the root compatibility symlink, so they run in a checkout without symlink
  support, and the zip-import test no longer assumes `/` separators.
- Model versions: tube 3.1.0, hemisphere 5.0.0, plate 5.0.0, smooth buckling
  5.1.0, ring shell 6.0.0; cylinder composition 1.0.0. Sizing operation
  versions: tube 3.1.0, smooth buckling 4.0.0, plate 3.0.0. Sweep 1.2.0 and
  material comparison 1.1.0. Request schema remains 5.0.0.

## [0.4.0] - 2026-09-23

- Ring-shell model 4.0.0 -> 5.1.0:
  - Without a proportional limit or compressive curve, the inter-ring bay
    enters the lowest buckling pressure at its elastic value instead of being
    left out, so the lowest pressure can be below what 0.3.0 reported.
  - A mode pressure is `advisory` only when its nominal stress is within a
    supplied proportional limit or a compressive curve corrects it. With only
    a yield strength it is an elastic upper bound above yield and
    `advisory_plasticity_undetermined` ("proportional limit not supplied")
    below it.
  - With a yield strength, report Pc5 and ring yield as
    `shell_yield_between_rings_pressure_mpa` and `ring_yield_pressure_mpa`:
    the pressures at which the mean hoop stress in the shell at mid-bay, and
    in the ring at its centroid, reaches yield, from the classical
    axisymmetric solution for a periodic bay. `axisymmetric_stress` carries
    the intermediates. They are not collapse pressures and do not enter the
    lowest buckling pressure.
  - Text and summary output show the lowest buckling pressure and its mode,
    and the two yield pressures.
  - The result reports the `m>=1,n>=2` mode domain and its boundary
    assumptions, including freely warping ends, adds `not_implemented`
    (axisymmetric `n=0` buckling) and `external_blocker` (physical end
    restraint) mode dispositions, and states which failure modes it does not
    check. Routine notes are shorter. Acceptance rules are unchanged, and
    `check` stays indeterminate.
- Research records (`validation/`) leave the repository; they remain in its
  history at [446ac81](https://github.com/ccluett/pv-calc/tree/446ac81/validation).
  The independent reference implementations move to `tests/reference/` and
  check the released rules directly. The plate result's
  `envelope_source_reference` links the FEA sweep at the v0.3.0 tag.
- Model versions: tube 3.1.0, hemisphere 5.0.0, plate 5.0.0, smooth buckling
  5.0.0, ring shell 5.1.0; cylinder composition 1.0.0. Sizing operation
  versions: tube 3.1.0, smooth buckling 4.0.0, plate 3.0.0. Sweep 1.2.0 and
  material comparison 1.1.0. Request schema remains 5.0.0.

## [0.3.0] - 2026-09-20

- Release shear-corrected plate deflection for `D_free/t >= 10` (fixed) or
  `>= 6` (simply supported), retaining the stress, material, and small-deflection
  gates. Plate model 5.0.0 and sizing operation 3.0.0 use the corrected value;
  raw Kirchhoff fields remain available.
- Move the acceptance rules shared by `check` and the cylinder composition into
  `pv_calc.assessment`. `pv_calc.presentation.assess_response` still works and
  returns the same results.
- Correct the `sweep` and `compare-materials` CLI help. Document required
  margins, their equivalent strength fractions, and how they differ from
  code-defined membrane and membrane-plus-bending checks.
- Mark the illustrative titanium curve as reference-only, consistent with its
  source assumptions. Shorten repeated qualification notes in documentation and
  output; text reports show shared check/estimate reasons once.
- Change the generic `Al-7075-T6` yield reference from the 62 ksi minimum for
  one B211 bar-size band to the 54 ksi minimum already documented for thick
  B209 plate. Higher form-specific strengths remain available through explicit
  inputs or scoped custom records instead of being implied by the generic name.
  Single-request JSON `check` output now retains each resolved material block
  and provenance beside its assessment, including material-only component and
  selected-result projections for composed calculations.
- Keep the ring-shell inter-ring smooth-shell estimate advisory in concise
  assessments. Selecting that check can no longer promote it to a released
  passing capacity, and invalid parent ring geometry is carried into the
  selected check across summary, text, and CSV output.
- Implement the NASA SP-8007 Rev. 2 Eqs. 30-32 material correction for
  smooth-cylinder external-pressure buckling
  (`nasa_smooth_cylinder_external_pressure_buckling` 4.1.0 -> 5.0.0). A
  complete compressive Ramberg-Osgood curve corrects the smooth-cylinder
  capacity and the ring model's inter-ring bay (ring model 4.0.0); the
  orthotropic global mode remains elastic and advisory. The correction has no
  strength limit; a corrected critical stress above the supplied yield strength
  is noted. The `R_mid/t > 10` domain and the moderate/long overlap withholding
  are unchanged.
- Add `ramberg_osgood_n` and `compressive_proof_stress` to named and explicit
  material records, required together, with `compressive_stress_strain_source`
  for provenance; supplying half a curve is an `invalid_request`. The bundled
  Al-6061-T6 and Ti-6Al-4V curves and derived limits are `reference_only`:
  calculations and exploratory sizing return a `released_unqualified_material`
  estimate that cannot pass acceptance, and `check` is indeterminate unless the
  elastic upper bound already falls below demand and the required margin.
  `materials show` reports the qualification on the buckling capabilities.
  Explicit and custom records are qualified unless marked otherwise. The
  hemisphere model becomes 5.0.0 to carry the same qualification status.
- Stop partitioning smooth-buckling sizing at the proportional limit when a
  complete curve is present, because the correction is continuous through that
  limit; without a curve the partition stands. Sizing operation 3.1.0 -> 4.0.0.
- Show the pending-plasticity pressure as an elastic estimate in
  smooth-buckling and cylinder summary/text output, with null acceptance
  capacity and margin, when a proportional limit is supplied without a curve.
  Replace an unofficial ASME full-text link with an edition-and-clause citation.
- Reject a smooth-cylinder `inputs.submergence` request whose mid-surface
  radius does not exceed half the wall thickness, instead of reporting a mass
  for a closed shell with no bore. A thick shell with a positive bore keeps its
  mass while its buckling capacity is withheld.
- Model versions: tube 3.1.0, hemisphere 5.0.0, plate 5.0.0, smooth buckling
  5.0.0, ring shell 4.0.0; cylinder composition 1.0.0. Sizing operation
  versions: tube 3.1.0, smooth buckling 4.0.0, plate 3.0.0. Sweep 1.2.0 and
  material comparison 1.1.0. Request schema remains 5.0.0.

## [0.2.0] - 2026-09-09

- Add `cylinder`, a combined closed-end stress and smooth-buckling assessment
  using one geometry and material. Optional two-closure butt assemblies reuse
  plate/hemisphere models and check common-annulus bearing, with per-closure
  materials, optional deflection limits, payload volume, mass, and buoyancy.
  Assessments retain known failures and missing required coverage separately;
  seals, attachments, and actual boundary restraints remain outside the checks.
- Add the public `pv_calc.api.calculate` entry point for forward, sizing, and
  batch requests, plus `run --input` for generic CLI dispatch. Add concise
  structured summaries, terminal reports, and CSV check rows through
  `--format json|summary|text|csv`. Detailed JSON remains the default and
  `--json` still only compacts whitespace.
- Add `check --input`, optional repeated `--check ID`, and acceptance exit
  codes: 0 pass, 1 fail, 3 indeterminate, and 2 invalid input. Ordinary
  calculation commands keep their existing evaluation exit behavior.
- Bundle the ten reference material records in `pv_calc/data/materials.yaml`
  and use them by default. Keep root `materials.yaml` as a compatibility
  symlink. Add `materials list/show` with provenance and input availability;
  explicit database overrides remain authoritative.
- Add geometric sweeps, fixed-outside-radius cylinder sizing, and optional
  stock-thickness selection inside explicit bounds. Material comparisons can
  size each material against the same requirements and report selected geometry
  and structural mass when sufficient geometry and density are available.
- Accept direct depth loads for ordinary forward and sizing requests using
  explicit density, gravity, and design factor, including unchanged base
  requests nested in comparisons and sweeps. A pressure/depth sweep axis takes
  precedence over its base load. Support zero-pressure forward
  cases and depth sweeps starting at zero: zero demand/deformation, finite
  formula capacities, unchanged applicability gates, and null margins. Inverse
  sizing continues to require positive design pressure. These workflow changes
  add no pressure-vessel physics or new FEA evidence.
- Use exact Lamé stresses for tube and hemisphere material checks at every
  thickness, including inverse sizing. The former membrane branch could
  overstate failure pressure near its cutoff by about 10.25% for tubes and
  15.67% for hemispheres. Both wall surfaces now report exact stress and
  displacement. `branch` is always `thick`; `force_thick` is an accepted no-op.
- Derive spherical displacement from the Lamé stress field and 3D Hooke's law.
  Label tube, hemisphere, and plate deformation beyond the supplied material
  strength as `elastic_estimate_material_limit`; retain raw elastic formula
  values and withhold the plate's released deflection in that state.
- Report maximum radial displacement/thickness and absolute principal strain
  for both shells. Withhold deformation release above 1 wall thickness or 1%
  strain, retaining raw formula values and all violation reasons. These are
  explicit pv-calc screens, not universal Lamé validity limits.
- Set the ordinary smooth-cylinder buckling margin to null for
  `released_pending_plasticity`, retaining the elastic candidate pressure.
- Preserve relevant named-material working-strength and proportional-limit
  derivations in optional `material.property_sources` output.
- Search model-eligible portions of sizing bounds, including when an endpoint
  is outside applicability. Report excluded intervals and verify the selected
  forward checks; no solution is inferred inside withheld regions. Exclusions
  retain released endpoint margins so a known material failure remains visible
  when another required output is unavailable.
- Preserve known sizing regime changes across excluded intervals without
  inventing missing margins. Distinguish model-inapplicable bounds from failed
  targets, exclude wholly ineligible intervals despite irrelevant regime
  changes, and scale bisection tolerance to the solution thickness.
- Model versions: tube 3.1.0, hemisphere 4.1.0, plate 4.1.0, smooth buckling
  4.1.0, ring shell 3.1.0 (nested smooth result); cylinder composition 1.0.0.
  Sizing operation versions: tube and smooth buckling 3.1.0, plate 2.1.0.
  Sweep 1.2.0 and material comparison 1.1.0. Request schema remains 5.0.0.

## [0.1.0] - 2026-08-28

Initial release.

### Added

- Five external-pressure models with primary-source references: closed-end
  tube stress with
  elastic displacement, flat circular plate bending and deflection,
  hemispherical head stress and NASA SP-8032 buckling, NASA SP-8007
  smooth-cylinder buckling, and NASA SP-8007 ring-stiffened shell general
  instability (advisory). Plate and hemisphere also report seat bearing
  stress; smooth buckling also reports the Roark Table 35 case 20 probable
  minimum as a comparator. The plate result's `envelope_source_reference`
  names the committed sweep summary by its content,
  `validation/fea/results/plate_sweep_fea_summary.json`.
- `elastic_applicability` on smooth-cylinder buckling (model 3.0.0), with
  `working_circumferential_membrane_stress_mpa`,
  `elastic_applicability_limit_mpa`, and `elastic_applicability_limit_basis`:
  whether a capacity is released only as an elastic upper bound, at every
  unsupported length. The regime boundary is
  `short_regime_gamma_z_boundary`, not `short_theoretical_gamma_z_boundary`:
  that branch carries correlation factor 0.5625 and releases a correlated
  capacity, so the previous name was inaccurate. Semantics in
  [docs/engineering.md](https://github.com/ccluett/pv-calc/blob/main/docs/engineering.md).
- `advisory_candidate_modes`, `advisory_governing_status`,
  `global_elastic_applicability`, and a global plasticity screen on the
  ring-stiffened shell result (model 2.0.0). NASA states plasticity factors
  for unstiffened cylinders only, so an over-limit global pressure is
  labelled, never corrected or withheld. A mode-search iteration reports
  `governing_mode_below_frontier`, not `comfortably_interior`; the name now
  states the condition, matching its `frontier_above_governing` sibling.
  Semantics in
  [docs/engineering.md](https://github.com/ccluett/pv-calc/blob/main/docs/engineering.md).
- Three failure categories — `ductile_metal`, `plastic`, and `brittle` —
  each read against its own strength; every stress result names its
  `failure_criterion`.
- Three bounded thickness sizing operations: `tube size`,
  `smooth-buckling size` (shell stress and buckling together), and
  `plate size` (bending margin and optional deflection limit), each reporting
  branch and governing-check changes and verifying its bracket when one
  exists. A capacity that steps upward at a regime boundary can open a branch
  already meeting the target; the opening thickness is then selected as
  `branch_start`, with no bracket to verify.
- `mass-properties`, and an optional `inputs.submergence` block on the four
  closed-body forward models for weight in air and in fluid plus failure
  depths. The `failure_depths` basis states only the direction of the
  constant-density approximation; the percentages it used to quote were
  measured against a citation since removed.
- `sweep` over a pressure or depth axis and `compare-materials` over an
  ordered list of named materials, each capped at 1,000 points.
- `pv-calc` CLI with unit-carrying options, JSON requests via `--input`,
  `--json` output, structured JSON errors with nonzero exit, and
  `pv-calc describe MODEL --json` for each versioned contract
  (`CALC_SCHEMA_VERSION` 5.0.0). An option's quantity is one ASCII number
  (underscore digit grouping included, `1_000 psi`) followed by one unit,
  quoted or attached. A unit is unit names joined by `*`, `/`, `**`/`^`, and
  parentheses; it may spell a number only in an unparenthesized exponent
  (`m/s^2`), may not name a dimensionless factor (`pi`, `ppm`), and may not
  contain any other character — a decimal comma, a quote, `#`, `%` — so a
  second magnitude, a bare unit, or a typographic minus is rejected as
  `invalid_quantity` rather than silently normalized. The JSON `--input`
  path's unit strings pass the same screen, and a unit pint cannot evaluate
  (`mm/0`, an unbalanced bracket) is a structured error on both paths, never
  a traceback. The `hemisphere` and `tube` help names everything each
  command calculates — stress, material failure, buckling, displacement —
  rather than yielding alone, which no brittle material has, and
  `--proportional-limit` is required for `released` capacity, the status the
  contract documents.
- Named-material loading from an explicit `--materials-file`, or fully
  explicit properties; `materials.yaml` is the project's database, ten
  records over the three failure categories, with every value cited to its own
  source and documented as a calculation input.
- Validation evidence under
  [validation/](https://github.com/ccluett/pv-calc/tree/v0.1.0/validation):
  independent reference implementations, the DTMB report 1324 case 17
  benchmark, and FEA comparisons, with a golden response-contract snapshot
  test. The committed FEA summaries are named for their content:
  `tube_plate_fea_summary.json`, `plate_sweep_fea_summary.json`, and
  `ring_shell_eigenvalue_fea_summary.json`. Not shipped in the package.

### Changed

- The probable-minimum buckling comparator now names its source in the
  response: `underpressure_probable_minimum_coefficient` and
  `underpressure_probable_minimum_pressure_mpa` on `hemisphere`, and
  `underpressure_probable_minimum_factor`,
  `underpressure_probable_minimum_pressure_mpa`, and
  `underpressure_probable_minimum_lobes_n` on `smooth-buckling`, are
  `roark_probable_minimum_*`. The value is Roark's Table 35 case 22 (sphere)
  and case 20 (cylinder) probable minimum.
- `CALC_SCHEMA_VERSION` 5.0.0 for that rename; hemisphere and smooth-cylinder
  buckling models 3.0.0. Model source citations name the primary reference
  rather than a third-party implementation of it; no formula, factor, or
  applicability rule changed. The two result-field renames above fold into
  the same 5.0.0 rather than bumping it again: nothing has been released.
- One material database, `materials.yaml` at the repository root, containing
  ten records across `ductile_metal`, `plastic`, and `brittle`. Each property
  is cited to an ASTM specification, MIL-HDBK-5J, ASME
  PVHO-1, or a named manufacturer data sheet, and strengths are specification
  minimums where a specification states one. The database values are not
  design allowables; a null `proportional_limit_mpa` withholds elastic
  buckling capacity rather than defaulting it.
