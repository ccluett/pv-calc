# Independent non-ring golden audit

- **Status:** non-ring audit complete
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

## Sources and conventions

| Model | Primary equation source | Convention |
|---|---|---|
| Closed-end tube | Roark 6th ed., Table 28 case 1c (thin) and Table 32 cases 1a-1d (Lamé thick); UnderPressure 4.0 Appendix C criterion B | External pressure; internal surface traction-free; closed ends; mean radius only for `r_m/t > 10`; through-wall Lamé solution at `r_m/t <= 10`; compression negative; 3D von Mises failure for ductile metal |
| Hemispherical head | Roark 6th ed., Table 28 case 3a and Table 32 cases 2a-2b for stress; NASA SP-8032 Section 4.2.1.1, Eqs. 1-4 for buckling | Uniform external pressure; internal input and mean-radius analysis; thin biaxial membrane or through-wall thick-sphere stress; clamped equator; 180-degree included cap; elastic capacity only for `r_m/t > 10`, `lambda > 2`, and a sufficient supplied proportional limit |
| Flat circular plate | Roark 6th ed., Table 24 cases 10a-10b, p. 429; UnderPressure 4.0 Example 2 shear convention | Uniform pressure over free radius; explicitly simply supported or fixed; center deflection; support-line transverse shear |
| Smooth cylinder | NASA/SP-8007-2020/REV 2, Eqs. 3-5 and 17-29, pp. 22 and 26-29 | Shell mid-surface radius; simply-supported circular ends; lateral-only or closed-end hydrostatic load; short and moderate `sqrt(gamma)=0.75`, and long `gamma=0.90` candidates kept separate |
| Smooth software overlap | Roark 6th ed., Table 35 case 20; UnderPressure 4.0 Appendix C | Mean radius; integer circumferential-node search; Roark 0.80 probable-minimum factor; validity classified separately from numerical parity |

Closed-end tube **displacement** is re-derived in a separate module,
[`tube_displacement_reference.py`](tube_displacement_reference.py), from
DTMB Report 1497 Eq. [5] with Eqs. [A7]-[A10] for the thin branch and Boresi and
Schmidt Eqs. (11.24) and (11.15) for the thick one; its conventions, surfaces,
assumptions, and exclusions are recorded in
[`sources/tube_scalar_displacement.md`](sources/tube_scalar_displacement.md).
It is a separate file because this module's SHA-256 is recorded as
`manifest.reference_sha256` in the committed tube/plate FEA summaries, and no
rerun is available to restore that hash. Its comparisons use the same `1e-9`
relative and `1e-10` absolute limits stated below and run in the same test
module.

Hemispherical-head membrane **displacement** is re-derived in a fourth module,
[`hemisphere_displacement_reference.py`](hemisphere_displacement_reference.py),
from NASA Technical Memorandum 4579 Eq. (5), which states the spherical-shell
membrane stress and radial displacement together and applies both to a
hemispherical bulkhead; its conventions, the thin-branch-only release, and the
withheld thick-sphere branch are recorded in
[`sources/hemisphere_scalar_displacement.md`](sources/hemisphere_scalar_displacement.md).
It is separate from this module for the same `manifest.reference_sha256`
reason. It is also separate from the tube reference because it transcribes a
different source and shell geometry. Its comparisons use the same limits and
run in the same test module.

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
summaries, and no rerun is available to restore them, so the stale names stand
and the current names are the ones given here.

## Inventory and independent results

| Family | Committed values/behavior independently covered | Representative independent result |
|---|---|---:|
| Tube | UnderPressure Example 1 and released CLI input; Lamé inner/outer stresses; thin mean-radius branch; forced-thick branch; exact `r_m/t = 10` and just-above boundary; the CLI thin-branch sizing golden `7.83358455 mm` by independent bisection; three worked component-stress fixtures | Example 1 failure `9.0401211605 ksi`; worked governing von Mises `80.0056865866 MPa`; sizing thickness `7.8335845425 mm` |
| Hemisphere | UnderPressure 4.0 dialog geometry and displays; thick and thin stress branches; exact `r_m/t = 10` and just-above boundary; NASA `lambda` and proportional-limit release gates; committed CLI case | Manual case stress `4,544.3787 psi` and failure `7,701.8229 psi`; invalid Roark comparator `64,240 psi`; CLI NASA capacity `8.01884900543 MPa` |
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

## Manual-oracle boundary

The checked results from the Version 4.0 manual remain software/equation
parity evidence. No UnderPressure 4.60 GUI report exists in the repository;
the capture has not been made, and making one would require a manual GUI run.
The executable reference records that status explicitly and does not relabel a
Version 4.0 display or independent calculation as Version 4.60 evidence.
