# Hemispherical-head scalar radial displacement

- **Status:** thin membrane branch approved for release at `verified_equation`,
  advisory and partial; thick-sphere branch withheld for want of a source
- **Investigation date:** 2026-07-31
- **Scope:** constant-thickness isotropic hemispherical head under uniform
  external pressure with the interior at zero gauge, at points away from the
  equator
- **Decision effect:** add one scalar radial displacement to
  `roark_nasa_hemispherical_head_external_pressure`, on the thin branch only,
  at that branch's own median-surface radius; every existing stress, yield,
  and buckling quantity and its release condition are unchanged

This record documents the equation and the withholding decision. It leaves the
existing branches, load case, and boundary conditions unchanged.

## Compatibility with the released model

The released model mixes two edge idealizations already. Its stress is a
complete-sphere result — thin biaxial membrane above `r_m/t = 10`, thick-sphere
Lamé at or below it — without an equator condition. Its NASA SP-8032 buckling
correlation uses a *clamped*-cap lower bound. On the thin branch, the membrane
radial displacement is compatible with the released membrane stress under the
same assumptions. The evidence is summarized below.

1. The released source states the displacement *in the same equation* as the
   membrane stress this model already reports. NASA TM-4579 Eq. (5) is one
   line giving `sigma_theta = sigma_phi = p R / (2 t)` and
   `dR_s = p R^2 (1 - nu) / (2 E t)` together. The displacement is the
   kinematic companion of the released membrane state — same shell, same load,
   same idealization — so releasing it introduces no assumption the released
   stress does not already make.
2. The source applies both quantities to a *hemispherical bulkhead*, not to a
   complete sphere in the abstract. The step from sphere solution to
   hemispherical closure is taken by the source.
3. The clamped-equator condition applies to the buckling correlation. The
   released stress has no equator boundary condition, and reporting
   displacement does not add one. The result therefore retains the existing
   edge idealizations used for stress and buckling.
4. Where the equator really is restrained, the membrane displacement is wrong
   locally — and the source says that too, in its own terms. Ko attributes the
   deformed shapes at the cylinder-hemisphere junctures to the radial
   displacement mismatch there, quantifies it as
   `dR_c / dR_s = (2 - nu)/(1 - nu)`, which he evaluates at `nu = 0.28` in his
   Eq. (7), and warns that the sharp transitions in tangential stress and
   radial displacement at those junctures could generate high transverse
   shear. That exclusion is the same one the released stress already carries;
   it is not a new limitation introduced by reporting displacement.

The released value therefore applies to the bulkhead away from the equator. It
does not represent radial closure at the equator, seal gap, or joint clearance.
At a genuinely clamped equator the local radial displacement is zero and the
response is bending, which is outside this model.

## Sources inspected

| Source | Exact location | Outcome |
|---|---|---|
| [NASA Technical Memorandum 4579](https://ntrs.nasa.gov/api/citations/19950011002/downloads/19950011002.pdf), W. L. Ko, *Thermocryogenic Buckling and Stress Analyses of a Partially Filled Cryogenic Tank Subjected to Cylindrical Strip Heating*, Dryden Flight Research Center, 1994 | Nomenclature, printed pp. 1-2 (`dR_c`, `dR_s`, `R`, `t`, `p`, `v`); geometry, printed p. 3; Eqs. (4), (5), (6), printed p. 6; internal-pressure discussion and Eq. (7), printed p. 11; ref. 1, printed p. 66 | **Released.** States the spherical-shell membrane stress and radial displacement together and applies them to the hemispherical bulkheads of the analyzed vessel |
| "Stress Analysis Manual", Air Force Flight Dynamics Laboratory, sec. 8.4.2 "Thick Spherical Pressure Vessels", Eqs. 8-44 to 8-47, as [transcribed by Engineering Library](https://engineeringlibrary.org/reference/thick-pressure-vessels-air-force-stress-manual) | Thick-sphere radial and tangential stress under internal and external pressure | Stress only. The section states no displacement or deflection |
| A. E. H. Love, *A Treatise on the Mathematical Theory of Elasticity*, 4th ed., Art. 98, "Radial displacement. Spherical shell under internal and external pressure", printed p. 142 | Located by title in the contents of the [Internet Archive scan](https://archive.org/details/in.ernet.dli.2015.462644) | **Not verified.** The article body could not be retrieved in this investigation, so nothing here rests on it |
| A. F. Bower, *Applied Mechanics of Solids*, sec. 4.1.4 "Pressurized hollow sphere", [free online edition](http://solidmechanics.org/text/Chapter4_1/Chapter4_1.htm) | Hollow sphere under internal and external pressure | **Not verified.** The displacement, strain, and stress expressions and the integration constants are page images, not transcribable text |
| NASA CR-912 *Shell Analysis Manual*; NASA CR-189079 (BEM thermal stress analysis, sec. 2.6.3 hollow sphere) | Searched for a closed-form thick-sphere displacement | Nothing usable. CR-189079's hollow-sphere case is a plotted elastoplastic boundary-element result, not a closed form |
| Roark's *Formulas for Stress and Strain*, 6th ed., Table 28 case 3a and Table 32 cases 2a-2b | The released stress sources | Not re-opened here. This investigation had no copy, and the record does not assume what those table cases print beyond the stresses already cited |
| UnderPressure 4.0 | Recorded in [tube_scalar_displacement.md](tube_scalar_displacement.md) and the evidence matrix | Reports no displacement, so there is no software-parity oracle for this quantity either |

The external PDF is not vendored. The inspected file record is:

- NASA TM-4579: SHA-256
  `dafa8fee4428e30bc8cef2225c5e74e19226b2b6e3a2bdbcea232831a8b38e68`,
  retrieved 2026-07-31 from the NTRS URL above.

## Released equation transcription

NASA TM-4579 introduces Eqs. (4) and (5) with the sentence, printed p. 6:
"Under the internal pressure loading, the stresses and radial displacements
induced in a long circular cylindrical shell (`dR_c`) and a spherical shell
(`dR_s`), respectively, may be calculated from the following equations
(ref. 1)". Ref. 1, printed p. 66, is Timoshenko and Woinowsky-Krieger, *Theory
of Plates and Shells*, McGraw-Hill, 1959, pp. 481-485. The two equations are

```text
Cylinder:   sigma_theta = p R / t,   sigma_z = p R / (2 t),   dR_c = p R^2 (2 - nu) / (2 E t)      (4)
Sphere:     sigma_theta = sigma_phi = p R / (2 t),            dR_s = p R^2 (1 - nu) / (2 E t)      (5)
```

and Eq. (6) is their ratio, `dR_c / dR_s = (2 - nu)/(1 - nu)`.

### Transcription caveat

The scanned NTRS document is text under OCR, and the OCR drops the superscript
on `R^2` in both
`dR` expressions. Two independent checks fix it, so the exponent is not a
guess. Dimensionally, `p R / (2 E t)` is a strain, not a length; only `R^2`
gives a displacement. And Eq. (4) is the same quantity this repository already
releases for the tube from a different source: DTMB 1497 Eq. [5] gives
`w_p = -(p R^2 / (E h)) (1 - nu/2)`, which is `-p R^2 (2 - nu) / (2 E h)`,
identical to Ko's `dR_c` in magnitude. That agreement also fixes the sign
mapping used below, since DTMB states its result for external pressure and Ko
states his for internal.

## Symbols, signs, and the mapping onto this model

`p` is the external pressure, positive as a compressive pressure on the outside
wall, with the interior at zero gauge. `R` is the shell mean radius, `t` the
wall thickness, `E` the elastic modulus, `nu` the Poisson ratio. Ko's `p` is an
internal pressure; the equation is odd in `p`, so external pressure flips the
sign of both the stress and the displacement, and the released model already
reports `sigma_theta = sigma_phi = -p R / (2 t)` on this branch. Applied to the
released thin branch, with `R = r_m` the model's mean radius:

```text
u(r_m) = - p r_m^2 (1 - nu) / (2 E t)          at the median surface
```

Radial displacement is positive outward, so external pressure gives a negative
value. That is the convention the released tube displacement already uses and
the sense Ko's `dR` carries under internal pressure. The quantity is a single
scalar: the membrane solution is a uniform radial contraction of the shell, so
there is no meridional variation to report, and unlike the tube there is no
axial direction and therefore no axial strain or length change.

Boundary and end-condition assumptions, from the source: a thin spherical shell
of uniform thickness, isotropic and linearly elastic, small deformations,
uniform pressure, membrane response, and a location away from a junction or
restrained edge. Ko applies the equations at `R/t = 95.5`.

## Withheld quantities and release conditions

### Thick-sphere branch

The thick-sphere branch withholds displacement. NASA TM-4579 Eq. (5) is a
thin-shell membrane result and says nothing about a thick sphere, and no source
in the table above states a thick-sphere radial displacement in a form this
investigation could verify. The value is therefore withheld with
`displacement_status = "withheld_missing_thick_branch_source"` and one violation
string, rather than derived here from the released Lamé stress field. That is a
recorded evidence gap, not a claim that the quantity does not exist; the two
unverified entries in the table are the places to look when it is closed. It is
also consistent with the model's other gates, in that the thin/thick switch at
`r_m/t = 10` is where this model stops being a shell.

### Numeric validity gate

The source states no thin-wall
cutoff of its own — it simply applies the equations to an `R/t = 95.5` shell —
so the released displacement inherits the model's existing
`r_m/t > 10` thin/thick switch and adds nothing. This is the same position
[the tube record](tube_scalar_displacement.md) took: the small-deformation
premise already underlies the released stresses, which carry no such gate, and
inventing a displacement-only boundary would be this repository choosing a
number no source states.

### Material inputs

Unlike the tube, this model already
requires an elastic modulus and a Poisson ratio, because its buckling
correlation cannot be evaluated without them, so there is no stress-only
request to protect and no missing-elastic-property withholding to add.

## Scope boundary

The released displacement excludes, and the source does not cover at this
equation:

- the equator boundary layer and any junction, seat, seal, or attachment
  response — Ko's own junctures discussion is exactly this exclusion;
- displacement fields — one scalar is released, and no meridional or
  through-wall distribution is computed;
- the thick-sphere branch, as recorded above;
- nonlinear and post-buckling deformation — the equation is linear and elastic,
  it contains no buckling criterion, and shell stability stays the separate
  SP-8032 correlation;
- ring-stiffened service displacement, cutouts, penetrations, thickness
  transitions, initial shape deviations, residual stress, and plasticity.

Physical testing has not been performed. The maturity level remains unchanged.
