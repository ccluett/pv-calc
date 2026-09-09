# Independent non-ring equation audit

- **Status:** current equations checked against preserved independent references
- **Executable reference:** [`non_ring_reference.py`](non_ring_reference.py)
- **Scope:** released closed-end tube stress, hemispherical-head stress and buckling, flat circular plate, and smooth-cylinder buckling goldens and examples
- **Evidence role:** independent equation verification and accepted manual software-parity provenance

Run the standard-library reference from the `pv-calc` directory:

```text
uv run python validation/non_ring_reference.py
```

The JSON output keeps source inputs, published/manual values, independent
calculations, tolerances, and comparisons in separate top-level records. The
focused test parses the module's imports and rejects any `pv_calc` or `yaml`
import; the module itself performs no file reads, so it cannot consume
fixtures, production configuration, or expected outputs.

The executable reference retains the original thin/thick stress switch and
historical sizing calculations. It is preserved byte for byte because the
committed FEA evidence identifies that source by SHA-256. Current production
uses exact Lamé stresses at every wall thickness, so the parity tests select
the reference's existing exact path with `force_thick=True`, including at
thin geometries. Production's `force_thick` option is now a compatibility
no-op; selecting it in the historical reference still has its original
meaning. No FEA source hash, solver result, or manifest has been restamped.

## Sources and conventions

| Model | Primary equation source | Convention |
|---|---|---|
| Closed-end tube | Roark 6th ed., Table 32 cases 1a-1d; UnderPressure 4.0 Appendix C criterion B; Table 28 case 1c retained as a membrane comparator | External pressure; internal surface traction-free; closed ends; exact Lamé stresses at internal and external surfaces at every thickness; compression negative; 3D von Mises failure for ductile metal |
| Hemispherical head | Roark 6th ed., Table 32 cases 2a-2b for stress; Table 28 case 3a retained as a membrane comparator; NASA SP-8032 Section 4.2.1.1, Eqs. 1-4 for buckling | Uniform external pressure; exact spherical surface stresses at every thickness; mean-radius buckling analysis with clamped equator and 180-degree included cap; elastic capacity only for `r_m/t > 10`, `lambda > 2`, and a sufficient supplied proportional limit |
| Flat circular plate | Roark 6th ed., Table 24 cases 10a-10b, p. 429; UnderPressure 4.0 Example 2 shear convention | Uniform pressure over free radius; explicitly simply supported or fixed; center deflection; support-line transverse shear |
| Smooth cylinder | NASA/SP-8007-2020/REV 2, Eqs. 3-5 and 17-29, pp. 22 and 26-29 | Shell mid-surface radius; simply-supported circular ends; lateral-only or closed-end hydrostatic load; short and moderate `sqrt(gamma)=0.75`, and long `gamma=0.90` candidates kept separate |
| Smooth software overlap | Roark 6th ed., Table 35 case 20; UnderPressure 4.0 Appendix C | Mean radius; integer circumferential-node search; Roark 0.80 probable-minimum factor; validity classified separately from numerical parity |

Closed-end tube **displacement** has a separate independent module,
[`tube_displacement_reference.py`](tube_displacement_reference.py), from
DTMB Report 1497 Eq. [5] with Eqs. [A7]-[A10] for its historical thin branch and
Boresi and Schmidt Eqs. (11.24) and (11.15) for the exact closed-cylinder
solution. The parity tests select the exact reference at every thickness;
its conventions, surfaces,
assumptions, and exclusions are recorded in
[`sources/tube_scalar_displacement.md`](sources/tube_scalar_displacement.md).
It is a separate file because this module's SHA-256 is recorded as
`manifest.reference_sha256` in the committed tube/plate FEA summaries. The
source revision recorded in those manifests is retained. Comparisons use the same `1e-9`
relative and `1e-10` absolute limits stated below and run in the same test
module.

Hemispherical-head membrane **displacement** remains in
[`hemisphere_displacement_reference.py`](hemisphere_displacement_reference.py),
from NASA Technical Memorandum 4579 Eq. (5), which states the spherical-shell
membrane stress and radial displacement together and applies both to a
hemispherical bulkhead. Its original thin-branch displacement and withheld
thick-branch behavior are preserved as historical evidence. Production now
derives exact spherical displacement from the Lamé stresses and 3D Hooke's
law. The parity test checks it against the independently expressed closed
form `u(r) = C1*r + C2/r^2`, with the constants fixed by the surface pressure
tractions. The derivation and scope are recorded in
[`sources/hemisphere_scalar_displacement.md`](sources/hemisphere_scalar_displacement.md).
The NASA and DTMB membrane displacement transcriptions still reproduce
NASA TM-4579 Eq. (6), `u_cylinder/u_sphere = (2 - nu)/(1 - nu)`, at their mean
surface. The current exact bore ratio includes the finite-thickness factor
`2*(a^2 + a*b + b^2)/(3*b*(a+b))`; the tests check that correction and its
approach to one as the wall thins. Membrane approximation error is kept
separate from the unchanged numerical equation tolerances.

The smooth-cylinder reference likewise retains its historical margin against
an elastic pressure estimate when plasticity is pending. Tests continue to
check that pressure and its historical ratio, while requiring current
production to report a usable margin only for `capacity_status="released"`.

The pinned plate reference predates `elastic_estimate_material_limit`: its
deflection status tests geometry only. Plate parity therefore compares the
raw stresses and deflections unchanged, then checks current release policy
separately using the reference's governing bending stress and the supplied
strength. Above that strength, production retains the formula value and
withholds the released deflection; geometric violations still take status
precedence. Tests cover either side of the material limit, equality, and
combined material and geometric violations. The historical oracle and FEA
hashes remain unchanged.

The inspected external PDFs are not vendored:

| Source | Exact record | URL | SHA-256 (retrieved 2026-07-22) |
|---|---|---|---|
| UnderPressure | Version 4.0 User Manual, manual revision 3/27/01 | <https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf> | `7a747e6ccd7efd6fdbf0c74a295751086b861661ca6de45f277cdda30c2e43c8` |
| NASA cylinder | NASA/SP-8007-2020/REV 2, second revision November 2020, issued December 2020 | <https://ntrs.nasa.gov/api/citations/20205011530/downloads/20205011530%20Rev%202FINALa%201-2023.pdf> | `299dfb8807862f174768356353f39c6bf6993596cb6f5933dd4fd23181e8837b` |
| NASA doubly curved shell | NASA SP-8032, August 1969 | <https://shellbuckling.com/papers/classicNASAReports/NASASP-8032.pdf> | `440e309c04bf6f0833e91e1781cb1de398baf7b8ddd2e83a52c47a5bf442f5b2` |

## Preset tolerances

These acceptance limits were fixed before the comparisons ran:

- independent equation output versus production: `1e-9` relative and `1e-10` absolute in the compared unit;
- continuous short/moderate mode-location diagnostics: `1e-8` relative because the independently minimized objective is locally flat, while its pressure/coefficient still uses the tighter equation-output limit;
- the manual's displayed Example 2 failure, `9,038 psi`: half the last displayed digit, `0.0005 ksi`;
- the repository's committed four-decimal manual-traceable goldens `9.0401 ksi` and `9.0384 ksi` (these are not manual displays): half the last recorded digit, `0.00005 ksi`;
- displayed `266.60 psi` value: half the last displayed digit, `0.005 psi`;
- hemisphere dialog values displayed to one decimal place: half the last
  displayed digit, `0.05 psi`;
- Appendix E whole-psi stresses and the invalid Example 1 `10,632 psi` display: half the last displayed digit, `0.5 psi`.

These are numerical reproduction tolerances, not model uncertainty or design
acceptance limits. Every limit above is enforced directly by
`tests/test_independent_reference_parity.py`, which reads the tolerances
from this reference module.

Comments inside the two pinned reference modules still call that test file by
its former name, `test_phase5_validation.py`, and the plate sweep summary by
its former `p5_03_plate_sweep_summary.json`. Editing a comment would change
the `reference_sha256` and `ring_reference_sha256` pins in the committed FEA
summaries, so the historical source text remains intact. The current artifact
names are the ones given here.

## Inventory and independent results

| Family | Committed values/behavior independently covered | Representative independent result |
|---|---|---:|
| Tube | UnderPressure Example 1 and released CLI input; exact Lamé inner/outer stresses for thin and thick geometries; both sides of the former `r_m/t = 10` stress switch; three worked component-stress fixtures; exact and historical membrane sizing solutions | Example 1 failure `9.0401211605 ksi`; worked governing von Mises `80.0056865866 MPa`; exact sizing thickness `8.7584452920 mm`, with historical membrane result `7.8335845425 mm` retained separately |
| Hemisphere | UnderPressure 4.0 dialog geometry and displays; exact spherical stresses and displacement for thin and thick geometries; both sides of the former stress switch; preserved membrane displacement comparator; NASA `lambda` and proportional-limit release gates; committed CLI case | Manual case stress `4,544.3787 psi` and failure `7,701.8229 psi`; invalid Roark comparator `64,240 psi`; CLI NASA capacity `8.01884900543 MPa` |
| Plate | UnderPressure Example 2 and released CLI input; Appendix E fixed and simply-supported stresses; both deflections and shear; `D/t = 4`, just-invalid diameter, and the large-deflection and shear-corrected small-deflection boundaries; fixed worked fixture | Example 2 failure `9.0384428873 ksi`; Appendix E simply-supported `19,800/19,800 psi`, fixed `12,000/7,800 psi` |
| Smooth short | lateral and hydrostatic Eqs. 19-22, line loads, `K`, `beta`, pressure, and released status; released short example | `Z = 34.3418112510`; ideal pressures `1.3537046232 MPa` lateral and `1.1992415550 MPa` hydrostatic |
| Smooth moderate | Eqs. 23-25 and 28, both load-case mode diagnostics, rounded `nu=0.316` comparator, released moderate example | `Z = 1236.30520504`; recommended `0.133826423960 MPa` |
| Smooth long | Eqs. 26-27 and 29, released long example, internal-to-mid-surface adapter fixture | released example `2.16346153846 MPa`; migrated fixture `0.135083144592 MPa` |
| Smooth boundaries | short/moderate boundary sides at `gamma*Z = 100`, moderate/long overlap sides, the committed exact-`K` discontinuity goldens at the moderate-boundary `Z` under both load cases, `r/t = 10` exact, the next representable radius above 10, the released `r/t = 10,000` classification, and the missing/at/below proportional-limit gates | Production and reference return identical release/withhold classifications and candidate values; independent exact pressures `0.4034234742` and `0.3768160035 MPa` with drops `0.125208` and `0.063438` |
| Software comparisons | invalid UnderPressure Example 1, valid Example 4 with its checked NASA comparison block, and all four Roark short/moderate/overlap/long matrix rows including their checked NASA comparator pressures and statuses | invalid Example 1 `10,631.7518 psi`, `n=2`, versus displayed `10,632 psi`; valid Example 4 `266.5982562 psi`, `n=3`, versus displayed `266.60 psi` |

The machine-readable inventory in
[`coverage_inventory.py`](coverage_inventory.py) maps each case to every
committed test, fixture, published record, and released input it covers; it
is kept apart from the executable reference so that moving an artifact cannot
change the reference's pinned hash. The test suite freezes the exact unique
inventory and its artifact paths. The inventory is not updated automatically;
a new golden must be added to it by hand.

For the tube sizing example (`a = 3 in`, `p = 7 ksi`, `S_y = 62 ksi`), the
exact bore condition is
`sigma_VM(a) = sqrt(3)*p*b^2/(b^2-a^2) = S_y`. Solving it gives
`t = a*(sqrt(S_y/(S_y-sqrt(3)*p)) - 1) = 8.7584452920 mm`.
The test checks this thickness against both current production and the
preserved reference's Lamé equations. It also retains the reference's old
membrane sizing result and verifies that result has a negative margin under
the exact calculation. The older output is evidence of the original model,
not a current thickness recommendation.

## Manual-oracle boundary

The checked results from the Version 4.0 manual remain software/equation
parity evidence. No UnderPressure 4.60 GUI report exists in the repository;
the capture has not been made, and making one would require a manual GUI run.
The executable reference records that status explicitly and does not relabel a
Version 4.0 display or independent calculation as Version 4.60 evidence.
