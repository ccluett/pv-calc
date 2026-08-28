# Closed-end tube radial displacement and axial strain

- **Status:** equation release approved at `verified_equation`; advisory and partial
- **Investigation date:** 2026-07-30
- **Scope:** constant-thickness isotropic closed-end circular cylinder under
  uniform external pressure with the interior at zero gauge, at sections away
  from the closures
- **Decision effect:** add scalar radial displacement, axial strain, and axial
  length change to `closed_end_tube_stress`, released only when
  the caller supplies an elastic modulus and a Poisson ratio; every existing
  stress quantity and its release condition are unchanged

This record documents the equations for the model's two existing branches: the
thin membrane branch above `r_m/t = 10` and the closed-end Lamé branch at or
below it. The branch structure, load case, and end condition remain unchanged.

## Sources inspected

| Source | Exact edition and location | Use |
|---|---|---|
| [DTMB Report 1497](https://dome.mit.edu/handle/1721.3/48806) | Pulos and Salerno, *Axisymmetric Elastic Deformations and Stresses in a Ring-Stiffened, Perfectly Circular Cylindrical Shell under External Hydrostatic Pressure*, September 1961; notation, printed p. vii; assumptions, printed p. 1; Eqs. [1]-[5], printed p. 2; Eqs. [7]-[8], printed p. 3; Appendix A sign conventions, printed p. 41; Eqs. [A7]-[A11] with `P_r` and `N_x` for external hydrostatic pressure, printed p. 43 | Thin branch: median-surface radial displacement of a long unstiffened shell, the two-dimensional Hooke's law and axisymmetric strain-displacement relation the axial strain follows from, and the sign conventions |
| Boresi and Schmidt, *Advanced Mechanics of Materials*, 6th ed., John Wiley & Sons, 2003 | Ch. 11 "The Thick-Wall Cylinder"; scope and end-cap statement, printed pp. 389-390; strain-displacement Eqs. (11.2), printed p. 391; stress-strain-temperature Eqs. (11.4), printed p. 392; closed-end axial strain Eq. (11.15), printed p. 394; closed-end stress components Eqs. (11.20)-(11.23), printed pp. 395-396; closed-cylinder radial displacement Eq. (11.24), printed p. 396 | Thick branch: closed-end radial displacement and axial strain, on the same Lamé stress field the released thick branch already computes |
| Roark's *Formulas for Stress and Strain*, 6th ed., 1989 | Table 28 case 1c; Table 32 cases 1a-1d | Already-released stress states the two displacement results are attached to; no new use here |

The external PDF is not vendored. The inspected file record is:

- DTMB 1497: SHA-256
  `10234c9a5d2651e603749782ae3fe93352af674d9a12da3cdd3c913e14795835`,
  retrieved 2026-07-30, the same file already recorded in
  [ring_failure_mode_selection.md](ring_failure_mode_selection.md).

Boresi and Schmidt is a printed reference and is cited by edition, chapter,
section, and equation number, the same way this repository cites Roark.

## Symbols and sign conventions

`p` is the external pressure, positive as a compressive pressure on the outside
wall, with the interior at zero gauge. `a` and `b` are the internal and external
radii, `t = b - a` the wall thickness, `r_m = a + t/2` the median-surface
radius, `E` the elastic modulus, and `nu` the Poisson ratio.

Radial displacement is positive outward, so external pressure gives a negative
value. This is DTMB 1497's own convention: its notation list names `w` the
radial displacement and `r` the radial coordinate, and Eq. [5] is negative under
external pressure. It is also Boresi's, whose `u` is the displacement component
in the `+r` direction. It matches the released `tension_positive` stress
convention, in that both take the outward/tensile sense as positive.

Axial strain is positive in extension. Both branches give a negative value here,
because a closed end under external pressure carries axial compression, and both
report a single value: the axial strain is uniform through the wall and along
the tube in each branch. The axial length change is that strain times the
caller's gauge length.

## Thin branch: DTMB 1497

DTMB 1497 Eq. [1] (its Eq. [A12]) governs the axisymmetric elastic deformation
of a circular cylindrical shell of median-surface radius `R` and thickness `h`
under external hydrostatic pressure. Appendix A, printed p. 43, states the load
case explicitly as `P_r = -p` and `N_x = -p R / 2`, that is a radial pressure
acting inward and the closed-end longitudinal resultant. Eq. [5] is its
particular integral:

```text
w_p = - (p R^2 / (E h)) (1 - nu/2)
```

and the report states in the sentence that follows that `w_p` is the
axisymmetric radial displacement of a long unstiffened cylindrical shell under
hydrostatic pressure. Two properties of that equation matter here:

- The nonlinear beam-column term `(p R / 2) w,xx` of Eq. [1] vanishes for a
  constant `w`, so Eq. [5] carries no pressure nonlinearity and no dependence on
  the report's beam-column parameter.
- Eqs. [7] and [8] show the complete solution as Eq. [5] plus a complementary
  solution whose constants are set by continuity at the ring frames. Ring and
  end restraint therefore live entirely in the complementary part. Releasing
  only the particular integral is exactly the "long unstiffened shell, away from
  restraint" result and nothing more.

The axial strain follows from the report's own two-dimensional Hooke's law,
Eq. [A7], with no added assumption:

```text
eps_x = (1 / (E h)) [N_x - nu N_phi]
```

`N_phi` is not assumed: Eq. [A9] gives `N_phi = E h eps_phi + nu N_x` and
Eq. [A10] gives `eps_phi = w / (R - r) ~= w / R`, so substituting Eq. [5] gives
`N_phi = -p R (1 - nu/2) - nu p R / 2 = -p R`. With `N_x = -p R / 2`,

```text
eps_x = - (p R / (2 E h)) (1 - 2 nu)
```

Consistency with the released stress state is exact rather than assumed:
`N_phi / h = -p R / h` and `N_x / h = -p R / (2 h)` are the released thin hoop
and axial stresses, and Eq. [A10] places `w` at the median surface, which is the
`mean` radius the released thin stress state already reports.

Applied to the released model, `R = r_m` and `h = t`, so the thin branch reports

```text
u(r_m) = - (p r_m^2 / (E t)) (1 - nu/2)          at the median surface
eps_z  = - (p r_m / (2 E t)) (1 - 2 nu)
```

Boundary and end-condition assumptions, from printed p. 1 and Appendix A: a thin
circular cylindrical shell of uniform thickness, isotropic and linearly elastic,
perfectly circular and initially stress-free, small deformations, uniform
external hydrostatic pressure with the closed-end longitudinal resultant
`N_x = -p R / 2`, and, for Eq. [5] alone, no ring or end restraint.

## Thick branch: Boresi and Schmidt

Boresi and Schmidt Ch. 11 treats a constant-thickness cylinder under uniform
internal pressure `p_1`, uniform external pressure `p_2`, axial load `P`, and
temperature change `AT`, at sections far removed from the junction of the
cylinder and its end caps. Sec. 11.1 opens by stating that the deformation and
stress near a support or end-cap junction depend on the axial coordinate, that
the treatment covers locations far from the end caps, and that the junction
problem is outside its scope.

With `AT = 0`, its closed-end stress components Eqs. (11.20)-(11.22) are the
released thick branch term for term: substituting `p_1 = 0` and `p_2 = p` gives
`sigma_r = A - B/r^2`, `sigma_theta = A + B/r^2`, and `sigma_z = A` with
`A = -p b^2/(b^2 - a^2)` and `B = -p a^2 b^2/(b^2 - a^2)`, which are the
released model's own Lamé constants.

Eq. (11.24) gives the radial displacement of a closed cylinder, and Eq. (11.15)
the closed-end axial strain. With `AT = 0`, `P = 0`, `p_1 = 0`, and `p_2 = p`:

```text
u(r)  = - (p r / (E (b^2 - a^2))) [ (1 - 2 nu) b^2 + (1 + nu) a^2 b^2 / r^2 ]
eps_z = - (1 - 2 nu) p b^2 / (E (b^2 - a^2))
```

Both are exact consequences of Boresi Eqs. (11.2) and (11.4) — the axisymmetric
strain-displacement relations `eps_theta = u/r` and `eps_z = dw/dz` constant, and
the isotropic linear-elastic stress-strain law — applied to the same stress field
the released model already computes. The released thick branch reports its stress
state at `r = a` and `r = b`, so it reports `u(a)` and `u(b)` at exactly those
two surfaces; `eps_z` is constant through the wall, which Boresi states directly
after Eq. (11.23).

Boundary and end-condition assumptions, from printed pp. 389-392: axisymmetric
loading and constraint, isotropic and linearly elastic material, uniform wall
thickness, closed ends with no separately applied axial load, no temperature
change, and a section far enough from the end-cap junction that the response is
independent of the axial coordinate.

## Agreement of the two branches

The two branches are different idealizations of the same cylinder, so at the
`r_m/t = 10` switch they differ by the amount the thin-wall approximation is
wrong by, not by rounding. Two of those differences are exact ratios,
independent of `nu`, and they are what the tests pin:

```text
eps_z(thick) / eps_z(thin) = b^2 / r_m^2 = (1 + t/(2 r_m))^2
u(a)(thick)  / u(r_m)(thin) = a b^2 / r_m^3
```

At `r_m/t = 10` the first is exactly `1.1025`, the same 10.25% discrete step the
released model already documents for the equivalent stress, and the second is
exactly `1.047375`. Both tend to 1 as `r_m/t` grows: at `r_m/t = 100` they are
exactly `1.010025` and `1.004974875`. The outer-surface and median-surface comparisons
depend on `nu`; at `r_m/t = 10` and `nu = 0.33` the thick value at the median
radius is 1.69% above the thin value and the value at `r = b` is 0.96% below it.

## Withheld quantities and release condition

Displacement is released only when the caller supplies both an elastic modulus
and a Poisson ratio, because neither branch's equation exists without them. A
stress-only request keeps every stress quantity it had, unchanged, and reports
`displacement_status = "withheld_missing_elastic_properties"` with one violation
string per missing property — the same shape the buckling models use when they
withhold capacity for want of a proportional limit. The axial length change
additionally needs a caller gauge length; without one it is null beside the
axial strain that would produce it.

The thin branch implements DTMB 1497's explicit reliability boundary. When the
calculated median-surface radial displacement has absolute value greater than
the wall thickness, the displacement, axial strain, and axial length change are
withheld as `withheld_applicability`; equality remains released. Stress results
are unchanged because this is the applicability contract for the newly released
deformation quantities, not a new stress model. No corresponding gate is
invented for the thick branch: Boresi states no numeric counterpart, so its
small-deformation scope remains a stated limitation.

## Scope boundary

The released displacement excludes, and neither source covers at these
equations:

- tube/endcap junction effects and the local bending they produce — Boresi
  places them outside its treatment, and in DTMB 1497 they are the
  complementary solution of Eqs. [7]-[8], not the particular integral;
- local restraint at closures, seats, seals, attachments, and penetrations;
- ovalization and initial out-of-roundness — DTMB 1497 assumes a perfectly
  circular, initially stress-free shell;
- instability — the released value is the particular integral, which is
  independent of the report's beam-column parameter and contains no buckling
  criterion, and shell stability stays the separate smooth-cylinder model;
- plasticity — both sources are linearly elastic, and no post-yield or residual
  deformation is modeled;
- ring effects — Eq. [5] is stated for an unstiffened shell, and ring-frame
  restraint is the part of the DTMB solution that is deliberately not used.

Deformed-geometry mass and buoyancy, thermal expansion, creep, and time-dependent
response are also outside this result. Physical testing has not been performed,
and the maturity level remains unchanged.
