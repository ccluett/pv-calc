# Closed-end tube radial displacement and axial strain

The model uses the exact closed-end Lamé solution at every wall thickness,
at sections away from closures. Both stress and displacement are reported at
the inner and outer surfaces. The former membrane branch is retained only in
historical reference calculations for comparison.

## Sources

- Boresi and Schmidt, *Advanced Mechanics of Materials*, 6th ed. (2003),
  Ch. 11: strain-displacement Eq. (11.2), constitutive Eq. (11.4), uniform
  closed-end axial strain Eq. (11.15), Lamé stresses Eqs. (11.20)-(11.23),
  and radial displacement Eq. (11.24), printed pp. 391-396.
- Roark, *Formulas for Stress and Strain*, 6th ed. (1989), Table 32 cases
  1a-1d, for the same pressure stress field.
- [DTMB Report 1497](https://dome.mit.edu/handle/1721.3/48806), Pulos and
  Salerno (1961), Eq. [5] and Eqs. [A7]-[A10]: the membrane limit, used as
  a historical comparator rather than a separate production branch.
  The inspected PDF SHA-256 is
  `10234c9a5d2651e603749782ae3fe93352af674d9a12da3cdd3c913e14795835`.

## Equation and conventions

Let `p > 0` be external differential pressure with zero internal gauge
pressure, `a` and `b` the inner and outer radii, `E` Young's modulus, and
`nu` Poisson's ratio. Tension and outward displacement are positive.

```text
A = -p b^2 / (b^2 - a^2)
B = A a^2
sigma_r = A - B/r^2
sigma_theta = A + B/r^2
sigma_z = A
u_r(r) = [(1 - 2 nu) A r + (1 + nu) B/r] / E
epsilon_z = (1 - 2 nu) A / E
delta_L = epsilon_z L
```

The displacement follows directly from `u_r/r = epsilon_theta` and
`E epsilon_theta = sigma_theta - nu*(sigma_r + sigma_z)`. Likewise,
`E epsilon_z = sigma_z - nu*(sigma_r + sigma_theta)`. These identities
check the radius, signs, and closed-end condition independently of the
expanded displacement expression. The axial force equals `-p pi b^2`.

As `t/a` approaches zero, the result tends to DTMB's membrane displacement
`-p R^2 (1 - nu/2)/(E t)` and axial strain `-p R (1/2 - nu)/(E t)`.
The exact solution has no discontinuity at the former `R/t = 10` switch.
`force_thick` is accepted as a compatibility no-op and `branch` is `thick`.

## Applicability and verification

Both elastic properties are required for deformation; a gauge length is
required only for `delta_L`. Missing properties give
`withheld_missing_elastic_properties`. When the governing material stress
exceeds the supplied strength, raw deformation values remain available with
`elastic_estimate_material_limit` and an explanation. That screen does not
establish proportional material behavior or stability below the strength.

The solution assumes small strains, linear isotropic elasticity, uniform
pressure and thickness, and the axial resultant of closed ends. It excludes
junction bending, local closure restraint, ovalization, instability,
plasticity, and ring-frame response.

### Deformation release screens

Both exact shell models report `maximum_radial_displacement_over_thickness`
and `maximum_absolute_strain`. Release requires `max |u| / t <= 1` and
`max |epsilon_i| <= 0.01`. These numerical thresholds are pv-calc policy:

- The displacement/thickness screen conservatively extends the former DTMB
  thin-cylinder restriction to every thickness and to the sphere. DTMB does
  not establish that extension. Uniform Lamé contraction can have `|u| > t`
  while strains remain small; the screen may therefore withhold an otherwise
  valid idealized result. It is not the plate's bending-deflection criterion.
- The strain screen includes radial, circumferential, and axial strains.
  For these radial fields the displacement gradient is diagonal, and each
  Green strain is `epsilon_i + epsilon_i^2/2`. A 1% linear-strain limit bounds
  the omitted quadratic term to 0.5% of its corresponding nonzero linear
  term. This is a kinematic screen, not a source-prescribed threshold or a
  bound on total solution error, and does not establish material linearity.

Principal linear strains are calculated from each surface stress state using
`epsilon_i = [sigma_i - nu*(sigma_j + sigma_k)]/E`. Each strain is affine in
`1/r^2` (tube) or `1/r^3` (sphere), so its absolute maximum occurs at a surface.
For the supported `0 < nu < 0.5`, `|u(r)|` is convex and also has its maximum
at a surface. No interior sampling is needed.

Exceeding either threshold gives `withheld_applicability`, with all geometric
and material reasons retained in `displacement_validity_violations`. Raw
radial displacement, axial strain, and length change remain formula estimates.
Missing elastic properties still withhold the calculation entirely. These
screens apply to deformation release; stress values and material margins
remain separate linear-model results, not a nonlinear capacity prediction.

`validation/tube_displacement_reference.py` preserves the independently
transcribed membrane and Lamé equations. Current production comparisons
select its exact branch. Constitutive, surface-traction, force-balance,
thin-limit, and continuity tests supplement those comparisons. The committed
FEA record verifies the tube stress field, not displacement.
