# Ring-shell FEA evidence specification

- **Status:** Partially executed. Three-mesh `RS-EIG-17` and `RS-EIG-33`
  evidence and the finest-mesh ten-length series are recorded in
  [`results/ring_shell_eigenvalue_fea_summary.json`](results/ring_shell_eigenvalue_fea_summary.json).
  `RS-EIG-17-J0`, the refined ring representation, and both continuation cases
  remain open for the exact reasons recorded there.
- **Purpose:** Define later independent, discrete-stiffener eigenvalue and
  geometrically nonlinear evidence for the advisory ring-shell model
- **Modeling boundary:** Executable- and solver-neutral; not a solver
  abstraction, calibration plan, allowable-pressure method, or design approval

The first executed FEA set uses DTMB Report 1324 because its published geometry,
elastic properties, pressures, and lobe counts support an idealized comparison.
The source does not provide enough as-built, fixture, or imperfection information
to reproduce its experiments as a validated nonlinear model.

## 1. Source geometry and comparison set

Use the fixed-inside-diameter interpretation already recorded in
[`validation/published/dtmb_1324_case17.md`](../published/dtmb_1324_case17.md).

| Quantity | DTMB source value | FEA convention |
|---|---:|---|
| Shell inside diameter | 8.118 in | Shell mid-surface radius 4.0765 in |
| Shell thickness | 0.035 in | Uniform shell thickness |
| Ring center spacing | 1.152 in | Discrete ring centroid planes |
| Ring axial width | 0.086 in | Solid external rectangle |
| Ring radial height | 0.169 in | Solid external rectangle |
| Young's modulus | 30,000,000 psi | Shared shell/ring linear-elastic modulus |
| Poisson ratio | 0.3 | Shared shell/ring value |
| Reported yield strength | 85,000 psi | Context only; not a plastic material curve |

The ten supported lengths are `N * 1.152 in` for `N = 17, 21, 23, 25,
26, 27, 28, 29, 31, 33` frame spaces. Keep source pressures and mode counts
separate from calculated FEA values. Do not tune geometry, stiffness,
imperfection amplitude, boundary stiffness, or a factor to match a DTMB result.

## 2. Required analysis cases

| Case ID | Geometry | Analysis | Imperfection | Required comparison |
|---|---|---|---|---|
| `RS-EIG-17-J0` | DTMB 17 spaces | Linear eigenvalue, perfect geometry; ring torsional stiffness suppressed only for equation isolation | none | Independent Eq. 64/65 result without the Eq. 91 ring term |
| `RS-EIG-17` | DTMB 17 spaces | Linear eigenvalue, perfect geometry; physical rectangle `A`, `I`, and `J` | none | Independent Eq. 64/65 plus Eq. 91 ideal pressure and `(m,n)=(1,3)`; Kendrick and experiment shown only as benchmark context |
| `RS-EIG-33` | DTMB 33 spaces | Linear eigenvalue, perfect geometry | none | Independent ideal pressure and predicted `(m,n)=(1,2)`; published Kendrick and experiment |
| `RS-EIG-SERIES` | All ten DTMB lengths | Same converged linear eigenvalue model | none | Pressure trend and governing `m,n` across Table 2 without calibration |
| `RS-GNL-17` | DTMB 17 spaces | Geometrically nonlinear, elastic, pressure-path analysis | bounded sensitivity matrix in Section 6 | Limit/load path, deformation mode, and sensitivity; no test-correlation claim without measured imperfections |
| `RS-GNL-33` | DTMB 33 spaces | Geometrically nonlinear, elastic, pressure-path analysis | bounded sensitivity matrix in Section 6 | Same outputs in the low-lobe long-geometry region |

The artificial `J0` case is equation evidence only. It is not a physical
structure. The physical eigenvalue cases use the rectangle's independently
calculated NASA/TP Eq. A16 Saint-Venant torsional constant.

## 3. Geometry and element idealization

Every ring must be represented discretely at its source center plane; no smeared
ring properties are permitted in the FEA evidence model.

For a case with `N` frame spaces, use a supported length `L = N * 1.152 in`
and place `N + 1` ring centroid planes at `x = 0, 1.152, ..., N * 1.152 in`.
The two radial support lines coincide with the end ring centroid planes. This
matches the DTMB Table 2 setup, which located each movable internal bulkhead
directly beneath a stiffener; it does not prescribe the unknown contact or
rotational stiffness of that support.

For the initial global-mode models:

- represent the shell at its mid-surface with a thin-shell formulation that
  supports geometric stiffness and finite rotations;
- represent each ring as a curved beam at its section centroid with the source
  rectangle's independent `A`, circumferential bending `I`, Saint-Venant `J`,
  and an external radial offset of `t/2 + h/2` from the shell mid-surface;
- align ring section axes and torsional degrees of freedom explicitly and
  document the orientation check; and
- impose perfect compatibility between the ring attachment line and shell for
  this idealized global comparison.

Repeat at least `RS-EIG-17` with a refined ring representation that resolves
the 0.086 in by 0.169 in rectangle using shell or continuum elements. Its
perfectly bonded interface remains an idealization. Root fillets, contact,
partial attachment, welds, and local attachment stresses cannot be validated
until the missing geometry in Section 9 is supplied.

## 4. Boundary conditions and hydrostatic load

Use the NASA Eq. 64 ideal boundary for the primary equation comparison:

- restrain radial displacement on both end circular lines;
- leave rotation about the end tangent free;
- suppress rigid axial translation at one reference location without fixing
  the compatible axial contraction of both end circles;
- suppress rigid circumferential rotation with the minimum additional
  constraint; and
- report every constrained degree of freedom and demonstrate that no
  unintended end moment or ovality restraint is introduced.

Apply hydrostatic external pressure as:

1. uniform inward normal pressure on the cylindrical shell; and
2. the closed-end axial membrane resultant `N_x = p r / 2`, distributed at the
   ends without introducing a local bending moment.

An explicitly modeled end closure may apply the end pressure instead, but the
resultant axial load must be shown to equal `p r / 2` and must not be applied a
second time. Use a unit reference pressure for eigenvalue cases and a monotonic
pressure parameter for nonlinear cases. Report applied and reaction resultants;
their imbalance must be below 0.5% before a result is compared.

The source does not establish that the DTMB test fixture exactly imposed this
ideal boundary. Boundary-restraint sensitivity is required after fixture data
are recovered; it must not be tuned to the test pressure.

## 5. Material assumptions

The baseline material is homogeneous, isotropic, and linear elastic with
`E = 30,000,000 psi` and `nu = 0.3` for shell and rings. Geometrically nonlinear
does not mean material nonlinear.

DTMB reports 85,000 psi yield strength and describes the response as elastic,
but it does not provide a source-traceable proportional limit, full stress-strain
curve, anisotropy, or residual-stress state. Do not introduce an elastic-plastic
model or claim material-collapse validation until those inputs are obtained.

## 6. Imperfection shapes and amplitudes

Run each nonlinear case with both signs of each applicable imperfection:

1. the converged first global eigenmode of the matching physical-`J` model;
2. a clean `m=1` global form with the published DTMB circumferential lobe count
   (`n=3` for case 17 and `n=2` for case 33), tapered to satisfy the end radial
   restraint; and
3. a superposition of the first three distinct global eigenmodes, normalized by
   maximum shell-normal displacement and with the coefficients recorded.

Until measured geometry or fabrication tolerances are available, use the
following dimensionless amplitudes only as a sensitivity study:

```text
w0 / t = 0.1, 0.5, 1.0
```

Include the perfect-geometry nonlinear result as `w0/t = 0`. These amplitudes
are not asserted to represent the DTMB specimens or pv-calc fabrication. They
cannot support experiment correlation, a knockdown factor, or an allowable.
Once an as-built surface map exists, run its measured field at 1.0x amplitude
and bounded 0.5x/2.0x measurement-sensitivity cases without replacing the
generic mode-shape results.

## 7. Mesh, formulation, and numerical convergence evidence

Use at least three systematically refined meshes. Record element family,
order, integration, characteristic dimensions, element counts, ring-shell
connection, and solver/version for each mesh.

The coarsest admissible mesh should have at least:

- 16 elements per circumferential full wavelength of the highest relevant
  lobe count;
- 12 elements per axial half wave of the governing global mode;
- matching or conservatively transferred ring/shell circumferential
  discretization; and
- four elements across ring width when the ring rectangle is resolved with
  shell or continuum elements.

Refine circumferential, axial, and ring dimensions together. The two finest
meshes must satisfy:

- eigenvalue pressure change no greater than 2%;
- unchanged governing `m,n` and unchanged global/local mode classification;
- nonlinear first-limit-pressure change no greater than 5%, with the same
  qualitative equilibrium path and failure mode; and
- stable strain-energy partition and no material hourglass, locking, or
  artificial-stabilization contribution.

If these criteria are not met, continue refinement or record the case as
non-converged. A converged pressure with a changing mode is not sufficient.

## 8. Nonlinear solution and requested outputs

Use a geometrically nonlinear equilibrium-path method capable of passing limit
points (arc-length, continuation, or an equivalent neutral method). Record load
increments, convergence norms, stabilization controls, and termination reason.
Repeat a selected case with tighter tolerances or smaller characteristic steps
to show solution-control insensitivity.

Archive and report:

- unscaled eigenvalues and ideal critical pressures;
- mode plots and independently counted axial half waves `m` and
  circumferential lobes `n`;
- shell-normal displacement and ring radial/torsional rotation fields;
- membrane forces, bending moments, strains, and reactions at the critical
  state;
- nonlinear pressure-displacement paths at the maximum-displacement point and
  selected ring and bay locations;
- first limit point or loss-of-stiffness pressure, with the criterion stated;
- mesh-convergence and solution-control tables; and
- model files, input decks, logs, post-processing scripts, hashes, units, and
  solver/version provenance sufficient for independent rerun.

Compare perfect linear eigenvalues with the independent ideal Eq. 64/65 plus
Eq. 91 pressure. Show the NASA 0.75-adjusted value in a separate column; do not
compare an ideal eigenvalue as though it already contained that empirical
factor. Show Kendrick Part III and experiment separately as published benchmark
evidence. Nonlinear sensitivity curves must remain uncalibrated.

## 9. Inputs still required for physical-validation claims

The ideal DTMB eigenvalue cases can proceed with the published geometry, but a
physical or fabrication-representative nonlinear validation remains blocked by:

- measured full-field shell out-of-roundness and local imperfection shape;
- shell-thickness, ring-dimension, and ring-spacing measurements/tolerances;
- ring-root fillet and integral/attachment geometry details;
- test-fixture radial, rotational, circumferential, and axial stiffness;
- end-closure/load-introduction geometry and pressure-loading details;
- source-traceable proportional limit and full material stress-strain data;
- material anisotropy, machining history, and residual-stress information; and
- specimen-specific defects, repairs, instrumentation locations, and test
  uncertainty.

For a fabricated design, weld profile, attachment continuity, heat-affected-zone
properties, corrosion allowance, fabrication tolerances, and measured
imperfection data are additionally required where applicable.

## 10. Evidence disposition

The current partial executions add FEA comparison evidence; they do not promote
ring global or inter-ring stability to a released, non-advisory capacity. The
remaining cases above, their applicable completion criteria, an independent
rerun, published benchmarks, review by someone other than the implementer, and a
recorded decision to promote the model's maturity must still be complete. The
executions linked at the top make no physical-validation claim.
