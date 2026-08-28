# External FEA validation evidence

This directory contains opt-in, development-only FEA inputs and summarized
evidence comparing solver results with the implemented equations. FEA is not
part of pv-calc's runtime dependencies or default pytest suite.

## Selected toolchain

The reproducible toolchain is a Linux container built from
[`toolchain/Dockerfile`](toolchain/Dockerfile):

- Debian `bookworm-slim` image digest
  `sha256:7b140f374b289a7c2befc338f42ebe6441b7ea838a042bbd5acbfca6ec875818`; and
- CalculiX CrunchiX `2.20-1` (`ccx` 2.20), GPL v2 upstream (the Debian
  packaging is GPL v2 or later), for recognized
  implicit linear-static and linear-eigenvalue finite-element analysis.

Authoritative project and package records:

- CalculiX project and license: <https://www.calculix.de/>;
- CalculiX 2.20 manual: <https://www.dhondt.de/ccx_2.20.pdf>, SHA-256
  `684564dd9dbd18e3da4e3c4443b8546a99ba62b71dc7f88e31cfe80eab4d0e57`
  as retrieved 2026-07-22;
- Debian `calculix-ccx` 2.20-1 record:
  <https://packages.debian.org/bookworm/calculix-ccx>.

The pinning is the base-image digest plus the exact `calculix-ccx` package
version. Transitive Debian dependencies are not individually pinned, so a
rebuilt image is functionally but not bit-for-bit reproducible. The image
that produced the committed results was arm64, ID
`sha256:4e0cc7560c9dee55446691d1f88c56b89732e38d2a0482ab8eeff508c5f3c5c5`,
with 59,422,299 bytes of image content and a 252 MB displayed local
footprint. The recorded image's installed solver executable `/usr/bin/ccx`
(aarch64) has SHA-256
`55949b455cf6f2ce78da087b2e60199f65a64433a7bc36ac809ab09f073dde34`. The
Debian arm64 package SHA-256 resolved at the original 2026-07-22 build was
`4aa9be426558b36206ba402b3c4b1bee713d9b1f7a60c01cd0907d535a143af8` for
`calculix-ccx_2.20-1`; the rebuilt image installs the same archive package
version. No host package, Python dependency, or system-wide solver was
installed.

Build, check, and rerun commands, from the `pv-calc` directory, are:

```console
docker build --tag pv-gen-fea:ccx2.20 validation/fea/toolchain
uv run python validation/fea/run_fea.py check
uv run python validation/fea/run_fea.py p5-03 --work-directory /tmp/pv-gen-p5-03 --output /tmp/p5_03_summary.json
uv run python validation/fea/run_fea.py p5-04 --include-series --work-directory /tmp/pv-gen-p5-04 --output /tmp/p5_04_summary.json
uv run python validation/fea/run_fea.py p5-03-plate-sweep --work-directory /tmp/pv-gen-plate-sweep --output /tmp/p5_03_plate_sweep_summary.json
```

The image tag, the `p5-*` subcommand names, and the `/tmp` paths above are
literal strings inside `run_fea.py`, whose SHA-256 is the `runner_sha256`
provenance pin in each committed summary; they are reproduced here verbatim so
the commands work, and are not re-stamped, because re-stamping without a solver
rerun would claim results the current file never produced. The outputs are
committed under the descriptive names used throughout this document.

The `p5-03`, `p5-03-plate-sweep`, and `p5-04` commands write the committed
compact summary schema directly, so a rerun regenerates
[`results/tube_plate_fea_summary.json`](results/tube_plate_fea_summary.json),
[`results/plate_sweep_fea_summary.json`](results/plate_sweep_fea_summary.json),
and
[`results/ring_shell_eigenvalue_fea_summary.json`](results/ring_shell_eigenvalue_fea_summary.json)
in place; only the recorded `runtime_seconds`, stdout hashes, and toolchain
host observations are run-specific. [`run_fea.py`](run_fea.py) fails with an
actionable message when Docker, its daemon, the pinned image, or `ccx` is
unavailable. Each solver process mounts only its requested temporary job
directory. The observed solver time for the three P5-03 comparisons was below
one second; the fourteen P5-04 jobs totaled about 437 solver-seconds on the
recorded arm64 Docker host. These are observations, not runtime guarantees.

CalculiX 2.20 supports the required axisymmetric, shell, beam, and `*BUCKLE`
formulations. Its manual documents nonlinear geometry but no arc-length/Riks
continuation procedure capable of reliably passing a limit point. Therefore
the generic `RS-GNL-17/33` work is outside this selected toolchain's credible
capability and must remain open unless a separately approved continuation
solver is added. A load-controlled nonlinear run will not be relabeled as a
limit-point analysis.

## Acceptance limits fixed before result comparison

These numerical limits were selected on 2026-07-22 before examining final FEA
comparisons. They are verification limits for these idealized models, not
physical uncertainty or design acceptance criteria.

P5-03 axisymmetric tube:

- three systematically refined quadratic axisymmetric meshes;
- no more than 0.5% change in each reported Lamé stress component between the
  two finest meshes;
- no more than 1.0% difference from the independent Lamé radial, hoop, and
  closed-end axial stresses at the declared non-singular extraction points;
- the axial reaction resultant on the unloaded bottom constraint plane within
  0.5% of the analytically applied closed-end force.

P5-03 circular plates, separately for fixed and simply-supported boundaries:

- three systematically refined quadratic axisymmetric meshes;
- no more than 1.0% change in center deflection and 2.0% change in the reported
  non-singular center surface bending stress between the two finest meshes;
- no more than 5.0% difference from independent thin-plate center deflection
  and center bending stress.

Both plate boundary conditions restrain the whole cylindrical edge face,
which includes a pressure-loaded corner node whose consistent load share
appears in the printed nodal forces, so no clean reaction-versus-applied
check exists for the plates; the raw support-face resultant and the
`global_equilibrium_residual_fraction` solver identity are recorded instead.
The tube keeps its discriminating reaction-resultant check on its unloaded
bottom constraint plane (and the ring end-load checks below remain).

The plate validity sweep (2026-07-24) applies the plate limits above to every
solved case and predeclares one addition in the runner before execution: a
2.0% finest-mesh change limit for the fixed-edge reaction-moment stress. Its
deep-mesh sensitivity study reuses the same change limits at the deep meshes
rather than declaring new ones.

P5-04 ring shell uses the limits already frozen in
[`ring_shell_fea_specification.md`](ring_shell_fea_specification.md): at least
three jointly refined meshes, no more than 2% eigenvalue change with unchanged
governing `(m,n)` and global/local classification, and the end-set axial
resultants within 0.5% of the analytic closed-end force `pi R^2 p` on each
end. Nonlinear cases additionally require a continuation/limit-point method,
5% limit-pressure convergence, and stable path/mode/energy behavior.

Before the final ring comparisons were inspected, a 0.02 absolute limit was
also selected for the change in ring strain-energy fraction between the two
finest eigenvalue meshes. CalculiX does not expose a separate artificial or
hourglass-energy channel for these modes, so that distinct specification check
remains open even where the recorded shell/ring partition is stable.

Any disagreement is retained. Geometry, materials, boundaries, meshes,
factors, and tolerances are not adjusted to make a comparison pass.

## Executed P5-03 equation comparisons

[`results/tube_plate_fea_summary.json`](results/tube_plate_fea_summary.json) is
compact extracted evidence. The runner regenerates the text input decks and
full text `.dat` and stdout files in the requested temporary directory.

- The tube is the committed UnderPressure 4.0 Example 1 geometry. A CAX8R
  meridional section receives 1,000 psi on the outside and the closed-end
  axial traction on one cut end; the other cut end is axially restrained.
  Surface stresses are linearly extrapolated from the two radial Gauss
  stations in a mid-length element.
- Each plate is a CAX8R solid model of the committed 50 mm free-radius,
  10 mm thick, 2 MPa example. Both idealized edges restrain the whole
  cylindrical edge face, matching the restraints the production model
  declares (UnderPressure 4.0 Appendix B). The simple support — transverse
  deflection prevented, radial rotation and displacement allowed — fixes the
  face axially pointwise (`w = 0` through the thickness) and leaves both
  radial components free, so the section rotates through unconstrained
  through-thickness radial displacement. Supporting only the mid-plane edge
  line instead idealizes the seat as a zero-width knife-edge whose
  compliance is singular in the continuum: its center deflection showed
  continued nonconvergence under refinement, consistent with a line-support
  singularity, so that realization is not used. The fixed edge — no radial
  rotation or
  transverse deflection, radial displacement allowed — additionally couples
  every edge node's radial component to the mid-plane edge node, which
  removes cross-section rotation and warping while leaving the uniform
  radial slide free. A pointwise hard clamp would additionally suppress the
  Poisson-driven through-thickness radial strain at the edge, a stiffer
  restraint than the one declared; it changes only the center stress
  (raising the +2.49% error below to +4.16% at `D_free/t = 10, nu = 0.30`),
  not the deflection or the edge moment. Center deflection is read at the
  mid-plane; the reported non-singular center surface stress is the mean
  magnitude of radial and hoop stress extrapolated to the top center.
- CalculiX `RF` includes pressure-load contributions at loaded constrained
  nodes (manual Sections 5.18 and 6.11.5). The acceptance checks therefore
  compare reaction resultants only on unloaded constraint sets — the tube's
  bottom plane — and the committed summary retains the raw support-face
  resultants for both plates, whose restrained faces include loaded corner
  nodes.

| Case | Finest mesh | Finest change | FEA versus independent equation | Disposition |
|---|---:|---:|---:|---|
| Tube inner hoop | 16 radial × 32 axial | 0.00696% | -0.0125% | pass |
| Tube outer hoop | 16 radial × 32 axial | 0.00474% | -0.0102% | pass |
| Simply-supported plate deflection | 32 radial × 8 thickness | 0.0062% | +3.61% | pass |
| Simply-supported plate center stress | same | 0.0212% | +0.354% | pass |
| Fixed plate deflection | same | 0.216% | +17.16% | **preset 5% agreement check failed** |
| Fixed plate center stress | same | 0.0348% | +2.49% | pass |

The converged fixed-plate deflection disagreement is retained as a thin-plate
equation versus three-dimensional model-form disagreement. P5-03 has
executed, converged evidence, but not every predeclared agreement check
passes.

Review explained the disagreement quantitatively. The first-order
shear-deformation (Mindlin, `kappa = 5/6`) center-deflection increment for a
uniformly loaded circular plate, `q a^2 / (4 kappa G t)`, is 0.005571 mm for
this 50 mm x 10 mm, 2 MPa, `E = 70,000 MPa`, `nu = 0.30` plate. That predicts
+18.29% over the Kirchhoff fixed deflection and +4.49% over the
simply-supported one at `t/a = 0.2`; the observed +17.16% and +3.61% sit just
below both predictions, consistent with the three-dimensional restrained face
being slightly stiffer than the Mindlin idealization. The same increment
explains both boundary conditions, which supports a shear-deformation
attribution over a support-radius, load-face, or boundary-condition defect
— it cannot exclude compensating or shared modeling errors, only make them
less plausible. The comparison remains a failed
check against the preset 5% Kirchhoff-agreement limit.

## Executed plate validity sweep

[`results/plate_sweep_fea_summary.json`](results/plate_sweep_fea_summary.json)
reruns the same three-mesh plate ladder over seven free-diameter/thickness
ratios and three Poisson ratios (0.05, 0.30, 0.35)
at a fixed 50 mm free radius, for both edges — 126 primary solves — plus an
18-solve deep-mesh sensitivity study described below. The
`D_free/t = 10, nu = 0.30` point is the committed P5-03 plate case — a
pinning test asserts deck and `.dat` hashes are identical — and the manifest
hashes the runner, the container recipe, and the independent reference that
supplies every Kirchhoff target. Both compared models are linear, so every
relative error below is independent of the applied pressure.

The fixed-edge margin is governed by the edge radial stress
`0.75 p (a/t)^2`, not the center stress, and the pointwise three-dimensional
stress at an ideal sharp clamped corner is singular — a surface-extrapolated
corner stress grows without converging under refinement. The sweep therefore
compares the governing quantity through its section moment: the first moment
of the clamped-face radial nodal reactions about the plate mid-plane, an
equilibrium resultant that passes the 2% mesh-change check at every solved
case, converted as `sigma = 6 M / t^2`.

Errors at the band edge `nu = 0.35` (`nu = 0.30` matches the P5-03 numbers).
Near the floors this is the worst solved Poisson value for every column
below. The simply-supported center-stress error crosses over — it rises
with `nu` at the thick end but falls with `nu` from `D_free/t = 10` up,
where `nu = 0.05` is worst — while staying far inside the budget
everywhere at or above its floor.

| `D_free/t` | Fixed deflection | Fixed center stress | Fixed edge stress (moment) | SS deflection | SS center stress |
|---:|---:|---:|---:|---:|---:|
| 4 | +116.01% | +19.03% | -8.05% | +24.29% | +2.38% |
| 6 | +51.41% | +8.07% | -3.37% | +10.84% | +1.01% |
| 10 | +18.05% | +2.64% | -1.09% | +3.89% | +0.35% |
| 14 | +8.93% | +1.22% | -0.53% | +1.97% | +0.18% |
| 20 | +4.15% | +0.52% | -0.27% | +0.96% | +0.09% |
| 30 | +1.68% | +0.19% | -0.16% | +0.42% | +0.05% |
| 40 | +0.85% | +0.09% | -0.14% | +0.23% | +0.04% |

Kirchhoff under-predicts every deflection and center stress — the
unconservative direction — while it slightly over-predicts the
margin-governing fixed-edge stress at every solved case, so that comparison
errs conservative. The fixed *bending* floor is set by the also-published
center stress (+8.07% at `D_free/t = 6` against the 5% budget, +2.64% at
the floor), with the governing edge stress verified within 1.1% at the
floor.

With the whole-face support realization every compared quantity meets its
predeclared mesh-change tolerance at every one of the 42 case/boundary
combinations. The deep-mesh sensitivity study then re-solves the
floor-adjacent cases — the last ratio outside and the first ratio inside
each output's budget at its worst solved Poisson value, the thickest
simply-supported case at the low band edge, and the thinnest low-Poisson
case for both edges, where the shear-corrected estimate's margin is
smallest — at four and eight times the primary finest mesh (`128x32` and
`256x64`, 49,793 nodes). Across those nine points the deepest-mesh change
is at most 0.027%, the drift from the primary finest mesh to the deepest is
at most 0.23%, and no within-budget decision changes at the deepest mesh,
so no floor reading hinges on residual discretization drift.

Production reuses the first-order shear increment `q a^2 / (4 kappa G t)`
for its small-deflection applicability gate. Because Kirchhoff sits below
the solved deflection everywhere, comparing the raw Kirchhoff value with
`t/2` releases results whose actual deflection is already past the
small-deflection limit, so the released model applies that limit to
`Kirchhoff + Mindlin` instead, with `kappa = 5/6` after Reissner (J. Appl.
Mech. 12, 1945); the correction factor is conventional, not exact, which is
why the estimate is checked against solved evidence rather than trusted.
The sweep found that estimate above the solved deflection at every one of
the 42 combinations (residuals from -5.17% to -0.006%) and above the
deepest solved deflection at every sensitivity point — including the
thinnest, low-Poisson corner, where the deepest-mesh margin is about
+0.005% and a deep mesh could most plausibly have overturned it. The margin
shrinks toward zero with thinness because the increment and the Kirchhoff
error both vanish there, so this is a measured fact about the solved cases,
not a claimed mathematical bound; between solved points, and beyond
`D_free/t = 40` (production sets no upper ratio limit), the gate relies on
that margin persisting as an engineering judgment. The released deflection
remains the Kirchhoff value; only applicability reads the estimate.

Deflection and bending stress leave the 5% budget at very different ratios,
so the released model gates them separately. Each floor is the coarsest
**solved** ratio from which every thinner solved ratio stays inside the
budget, at every solved Poisson value:

| Released output | Fixed | Simply supported |
|---|---:|---:|
| Bending stresses (edge stress sets the fixed margin) | `D_free/t >= 10` | `D_free/t >= 4` |
| Center deflection | `D_free/t >= 20` | `D_free/t >= 10` |

Floors sit on solved ratios; releasing the continuous range above a floor
relies on the monotone decrease of the model-form error with thinness that
the seven solved ratios demonstrate. Releasing Poisson values inside the
band is the engineering judgment that a smooth error surface stays bounded
by the three solved values, not proven monotonicity: the simply-supported
center-stress error rises with `nu` at the thick end but falls with `nu`
from `D_free/t = 10` up, so no single monotone Poisson trend covers every
quantity. Outside `0.05 <= nu <= 0.35`, and below `D_free/t = 4`, nothing
is solved and the production model withholds rather than extrapolates.

Retained failures, not tuned away: against the 5% budget, the
simply-supported deflection fails at `D_free/t = 4` and `6`, and the fixed
deflection fails through `14`, at every solved Poisson value. The fixed
center stress fails at `4` for all three Poisson values (`+8.04%` even at
`nu = 0.05`) and at `6` only for `nu >= 0.30`. The fixed edge-moment
comparison fails at `4` only for `nu >= 0.30` (`-0.91%` at `nu = 0.05`).
All stay committed as failed checks.

## Executed P5-04 ideal eigenvalue comparisons

[`results/ring_shell_eigenvalue_fea_summary.json`](results/ring_shell_eigenvalue_fea_summary.json)
records three jointly refined meshes for `RS-EIG-17` and `RS-EIG-33`,
followed by the ten-row
`RS-EIG-SERIES` at the finest primary discretization. Each model uses an S8R
shell, a discrete B32R rectangular ring at all `N+1` source planes, shared-node
perfect attachment, the specified external centroid offset, end-line radial
supports, unit inward shell pressure, and consistent quadratic nodal weights
for both closed-end axial resultants. Static displacement verifies pressure
orientation before each eigenvalue solve. Modes are counted independently by
a DFT of shell-normal displacement and a complex projection onto
`sin(m*pi*x/L)`.

| Case | M1 / M2 / M3 ideal psi | Finest change | FEA mode | Equation ideal psi | Difference |
|---|---:|---:|---:|---:|---:|
| `RS-EIG-17` | 546.014 / 459.471 / 460.897 | 0.310% | `(1,3)` | 538.050 | -14.34% |
| `RS-EIG-33` | 286.665 / 256.997 / 257.526 | 0.206% | `(1,2)` | 256.031 | +0.584% |

The finest two meshes preserve mode and classification, the end-set axial
resultants match the analytic closed-end force to well below 0.5%, and the
ring energy-fraction changes are 0.00102 and 0.00125. The ring centroid
offset direction was verified externally: the committed `OFFSET2` places the
rings outside the shell, and the long-cylinder series converges toward the
external-ring equation (+0.58% at 33 spaces) while diverging monotonically
from the internal-ring alternative, which uniquely identifies the modeled
placement; the offset values are retained per mesh in the committed summary.
The NASA 0.75-adjusted equation values remain separate from the unadjusted FEA
eigenvalues. Across the series, FEA changes from `n=3` to `n=2` between 23 and
25 spaces, while the independent smeared-ring equation changes by 21 spaces;
the full numerical trend and disagreement are retained without calibration.

P5-04 remains incomplete. `RS-EIG-17-J0` cannot be represented with a native
CalculiX rectangle while independently setting `J=0` and preserving `A` and
`I`; its `GENERAL` section is limited to a user element. The separate refined
shell/continuum ring model with four elements across the width has not been
run. CalculiX 2.20 has no documented arc-length/Riks continuation method, so
`RS-GNL-17/33` remain tool-blocked rather than being replaced by load control.
Physical correlation additionally remains blocked by the as-built and fixture
inputs listed in the specification.
