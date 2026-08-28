# Changelog

Notable changes to pv-calc are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and the package
follows [Semantic Versioning](https://semver.org/spec/v2.0.0.html). The
JSON request/response contract carries its own version
(`CALC_SCHEMA_VERSION`), independent of the package version, as does each
model; both predate this changelog.

## [Unreleased]

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
  [validation/](https://github.com/ccluett/pv-calc/tree/main/validation):
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
