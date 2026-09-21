# Ring-cylinder supports, DTMB end closures, and NASA experimental evidence

Follow-up to the [initial investigation](../ring_shell_investigation.md),
20 September 2026. Production equations, factors, and mode limits are
unchanged; ring model 4.1.0 reports the mode domain, boundary assumptions,
and the missing mode found here.

## Direct answer about the boundary conditions

**The implementation uses the boundary condition of the selected NASA theory.
The DTMB Table 2 tests approximate, but do not reproduce, that boundary
condition.**

The public result identifies `boundary_condition="simply_supported"` and
`load_case="hydrostatic_closed_end"`. NASA defines the ends as restrained
against radial displacement, with rotation about the tangent free. Pressure
on the ends supplies the axial compression included through Eq. 65. It is
not a lateral-pressure-only calculation, and there is no unselected clamped
option or plate-thickness setting in the public API.

In Table 2, internal disks support the shell beneath rings while the shell
continues beyond the disks. DTMB explicitly identifies shell continuity as
the source of rotational restraint. The investigators expected this arrangement
to be closer to simple support than their previous end closures; they did
not establish that it was an exact simple support. Thus the old comparison is
useful experimental context, but its residuals combine support effects with
theory and measurement differences.

Nor does the evidence justify replacing those supports with fully clamped
ones. Their actual stiffness depends on the continuing shell, disks, contact,
and spacers. A complete fixture model needs those physical details.

## The separate DTMB closure tests

DTMB 1324 Fig. 3 and Table 1, printed pp. 5–6, separate these configurations:

| Closure | Physical distinction |
|---|---|
| I | Two 1/2-in closure plates; tightly fitting inserts restrain radial motion. This is the most flexible tested closure arrangement, not a mathematical hinge. |
| II | Pressure caps transfer the end load around the edges of the thin closure plates, altering plate loading and deformation. |
| III | A 2-in plate at one end and a 1/2-in plate at the other. |
| IV | The original arrangement attached to the pressure-tank head at one end and a closure plate at the other. |
| V | Two 2-in closure plates. Greater restraint, but not demonstrated perfect clamping. |

All experimental entries below are nondestructive Southwell estimates in psi;
parentheses give circumferential lobes. Repeated configurations of one specimen
are not independent specimens.

| Cylinder | Case I | Case II | Case III | Case IV | Case V |
|---|---:|---:|---:|---:|---:|
| 6 | 504 (3) | 576 (3) | 576 (3) | not reported | 700 (3) |
| 2-A | 339 (2) | 365 (2) | 394 (3) | 398 (3) | 409 (3) |
| 3-A | 229 (2) | 246 (2) | 298 (2) | 315 (2) | 378 (2) |
| 4-A | 178 (2) | 189 (2) | 231 (2) | 228 (2) | 289 (2) |

For 3-A, rotating the Case II plates through 90 degrees produced a second
estimate of 238 psi and rotated the lobar pattern. That is additional evidence
that actual closure behavior matters, not just an ideal boundary label. The
primary report gives 700 psi for cylinder 6 Case V; the 703 psi in Gordon's
later DAPS comparison is not substituted for it.

The same specimen gains 21–65% between Cases I and V, and 2-A changes from
two lobes to three. Our present model has no input representing that change,
so it predicts the same pressure and mode for all closures of a given span.

### New calculation and its geometry qualification

The [runner](../dtmb_end_closure_investigation.py) compares the independent
NASA transcription with the public model at the four archived DAPS4 input
lengths. It then varies the diameter interpretation and L/D rounding, checks
the nominal end-bay interpretation, and retains all results in
[JSON](../results/dtmb_end_closure_investigation.json).

These lengths are reconstructed, not measured: the DAPS4 values agree to
their displayed precision with DTMB's rounded `L/D` multiplied by the
8.188-in shell outside diameter.

| Cylinder | Archived input length, in | NASA ideal, psi (n) | NASA × 0.75, psi | Case I, psi | Adjusted vs Case I |
|---|---:|---:|---:|---:|---:|
| 6 | 15.639 | 596.0 (3) | 447.0 | 504 | −11.3% |
| 2-A | 27.512 | 356.5 (2) | 267.3 | 339 | −21.1% |
| 3-A | 35.290 | 268.6 (2) | 201.5 | 229 | −12.0% |
| 4-A | 42.250 | 244.2 (2) | 183.2 | 178 | +2.9% |

All four lobe counts agree with Case I. The ideal results are 5.2–37.2% above
the Case I estimates, so better support matching does not eliminate theory
differences. For comparison, DTMB's own Kendrick predictions for these rows
are 499, 317, 216, and 180 psi, within about −6.5% to +1.1% of Case I.

The adjusted discrepancies are smaller than the worst Table 2 discrepancies,
but these are different lengths; the percentage reduction is not a controlled
estimate of the restraint contribution. The slightly high adjusted prediction
for 4-A also prevents claiming that the factor always yields a lower bound.

Using ID, mid-surface diameter, or OD with the displayed L/D and a half-digit
rounding interval changes calculated pressure by at most 1.63% across these
cases. A separate inconsistency remains:
interpreting the tabulated space count with two 0.959-in end bays from Fig. 2
gives `(N−2) × 1.152 + 2 × 0.959`. For 2/2-A, the printed count 25 gives
28.414 in, versus the archived 27.512 in. At 28.414 in, the adjusted prediction
is 254.6 psi, 24.9% below Case I. The report does not reconcile these
quantities, and neither the count nor the better-fitting length is chosen here.

### DAPS4 support comparison: what reproduced and what failed

The pinned release reproduces all sixteen archived ideal simply-supported
and clamped global outputs. A further detail matters for Table 1: its global
routine rounds the input length to the nearest integer multiple of ring pitch
and prints a warning. The effective spans are 16.128, 27.648, 35.712, and
42.624 in for cylinders 6, 2-A, 3-A, and 4-A respectively. These are retained
explicitly, including NASA calculations at the same rounded spans. The earlier
Table 2 comparison already used exact integer-pitch spans and is unaffected.

The additional intermediate-restraint audit **failed** against archived
outputs:

- With `Jer = 0`, none of eight rows reproduced; each returned the solver's
  `1e10 psi` sentinel, not a physical pressure.
- With `Jer = IXer`, five of eight reproduced; the current solver forced
  clamped conditions for all eight. The three flexible-closure mismatches
  therefore cannot be treated as predictions of the intended restraint.

The [DAPS runner](../daps4_ring_crosscheck.py) now records these sixteen probes
separately from the successful controls, including source/fixture hashes,
expected and actual outputs, and solver warnings. The failures do not negate
the successful simple-support/clamped checks, but they prevent using this
execution to interpolate the real fixture stiffness. Whether the differences
arise from solver revision, mode filtering, or numerical behavior is not
resolved here; the external solver was not modified.

## What NASA actually cites as experimental support

**Yes: NASA explicitly cites experimental evidence for the exact pressure
equation.** SP-8007 Rev. 2, Section 4.1.2.3, printed p. 38, says experiments
in references 188–191 agree reasonably with Eq. 64. The section supplies
references rather than a worked numerical validation table or residual plot.

| NASA reference | Experimental source | What has been established here |
|---|---|---|
| 188 | Galletly, Slankard, and Wenk (1958), *General Instability of Ring-Stiffened Cylindrical Shells Subject to External Hydrostatic Pressure—A Comparison of Theory and Experiment*, ASME J. Applied Mechanics 25, 259–266, [DOI](https://doi.org/10.1115/1.4011754) | The principal historical experimental citation. DTMB 1324 identifies this paper with the earlier DD-8 series varying frame size; its Table 1/2 specimens come from the later DD8-2 length series. Related program, not the same dataset. The complete ASME paper was not accessible in this session. |
| 189 | Yamamoto et al. (1989), *General Instability of Ring-stiffened Cylindrical Shells under External Pressure*, Marine Structures 2, 133–149, [publisher](https://www.sciencedirect.com/science/article/pii/0951833989900099) | The publisher/author abstract describes machined-model comparisons and imperfection effects for welded shells. The full geometry and test tables were not retrieved, so no new numerical benchmark is claimed. |
| 190 | Miller and Kinra (1981), *External Pressure Tests of Ring Stiffened Fabricated Steel Cylinders*, Offshore Technology Conference, OTC 4107 | Direct NASA citation to fabricated-steel pressure tests. Source dimensions, failure mechanisms, and end conditions still require full-paper extraction before selecting cases. |
| 191 | Miller, Frieze, Zimmer, and Jan (1983), *Collapse Tests of Fabricated Stiffened Steel Cylinders under Combined Loads*, ASME pressure-vessel conference | Direct NASA citation, but combined loads must be separated from the specific closed-end hydrostatic load ratio our model implements. Full numerical source tables were not retrieved. |

The [1968 edition](https://ntrs.nasa.gov/api/citations/19690013955/downloads/19690013955.pdf),
printed p. 20, gives the same statement for its Eq. 49 using only reference 45,
Galletly et al. (1958). The current edition adds the three later sources.
This makes the 1958 paper a particularly valuable next acquisition; replacing
it with a later related DTMB table does not reproduce NASA's cited comparison.
DTMB 1324 also identifies the earlier series with Slankard and Galletly's
Report C-822 (June 1957), *The Effect of Reinforcing Rings on the General-
Instability Strength of Machined Cylindrical Shells under External Hydrostatic
Pressure*. That is a second source lead, not a retrieved or reproduced dataset.

Both editions recommend 0.75 by reference to the recommendation for moderate-
length unstiffened isotropic cylinders. Neither pressure section presents a
ring-specific statistical fit establishing 0.75 from the cited ring datasets.

The earlier long-cylinder finding also has explicit historical support:
[NACA TN 4237](https://ntrs.nasa.gov/api/citations/19930085193/downloads/19930085193.pdf),
printed p. 6, identifies the Donnell long-cylinder overprediction factor of
4/3 and explains replacing it with the ring solution; the algebraic limit
found in the initial investigation is this known approximation.

## NASA's own pressure tests and an additional coverage gap

Two publicly available NASA reports provide useful experimental data:

- [TN D-3111, Dow (1965)](https://ntrs.nasa.gov/api/citations/19660001966/downloads/19660001966.pdf):
  ten aluminum cylinders with Z-section rings, local buckling preceding
  general collapse. They test local/postbuckling interaction, not just the
  global elastic pressure of an initially unbuckled rectangular-ring shell.
- [TN D-3647, Dow and Peterson (1966)](https://ntrs.nasa.gov/api/citations/19660029121/downloads/19660029121.pdf):
  one 10-ft-diameter aluminum cylinder with 36 hat-section rings, measured
  imperfections, splices, and spot-welded attachments. It failed at 5.71 psi,
  approximately 76% of the report's classical prediction.

TN D-3647 is particularly instructive. The final damaged shape suggested
`m=1, n=5–6`, but the report's calculation predicted a lower axisymmetric
`m≈39, n=0` mode, largely driven by axial end compression. The authors proposed
that initiation in that mode led rapidly to the visible final pattern; the
initial mode was not directly observed. The report warns against fixing
`m=1` and discusses the questionable smearing assumption when buckle length
approaches ring pitch.

Our implementation varies `m`, but its circumferential scan begins at `n=2`.
**It therefore excludes the axisymmetric hydrostatic branch.** The existing
independent reference repeats that domain, so production/reference parity
alone could not reveal this coverage gap. This is distinct from the low-lobe
two-/three-wave disagreement in DTMB.

The new diagnostic extends the *same smeared equations*, without modifying
production, to `n=0` and scans `m=1..512`. It independently checks the reduced
axisymmetric formula:

```text
alpha = m*pi/L
S = E_y - E_xy²/E_x
p(n=0) = (2/r) * [D_x*alpha² + S/(r²*alpha²)]
```

For all ten Table 2 configurations, that branch is about 3,122–3,123 psi,
at least 5.8 times the governing ideal lobar pressure. For the four Table 1
reconstructed spans it is at least 5.2 times the lobar pressure. It does not
explain the DTMB discrepancies. These are elastic diagnostics; smeared-
stiffener applicability at such short axial wavelengths has not been checked.

The NASA specimens' Z/hat sections are outside the current physical solid-
rectangle API, so neither is installed as a direct public-model golden by
inventing an equivalent rectangular ring. TN D-3647 should nevertheless be
part of the validation requirements for expanded section/mode coverage.

## Decision and reproduction

Keep Table 2 as the primary comparison, and record the Table 1 results as
reconstructed-span comparisons with the geometry uncertainty visible.

The next model-development priority is to account explicitly for the missing
axisymmetric hydrostatic branch and its applicability, while separately
obtaining a source-complete experimental set with known supports. The original
NASA-cited DD-8 dataset and Yamamoto's machined-model data are higher-value
targets for that purpose than additional lengths of the same 4-A cylinder.

```console
uv run python validation/dtmb_end_closure_investigation.py --output validation/results/dtmb_end_closure_investigation.json
uv run python validation/daps4_ring_crosscheck.py --release /path/to/DAPS4e.6 --work-directory /tmp/daps-crosscheck --output validation/results/daps4_ring_crosscheck.json
```

The first command checks public/reference pressure and mode agreement for
each span variant. The second
requires the pinned external source and GFortran; it requires reproduction
of the ideal support controls and records the intermediate-support failures
as failures. No external source is a package dependency.

Additional inspected PDF SHA-256 values:

- NASA SP-8007 (1968): `6eb451ac9dadf2c0605d343398e6b92175c2d96fda5afaceee118583cc2a5e9c`.
- NACA TN 4237: `4236308ac7d98f4b931a863e05b74dd2fff05f03c4252b5f24b32e22d559d1ae`.
- NASA TN D-3647: `9277b49392ab0439dbebf67bc208ddebaf0dd23d06591df70a36131b86069cc9`.

DTMB, NASA Rev. 2, and TN D-3111 hashes are retained in the initial report;
the DAPS artifact now pins all eight source and eight input/output fixture
files used in the support audit. Primary figures and relevant equation/result
pages were visually checked, not accepted from OCR alone.
