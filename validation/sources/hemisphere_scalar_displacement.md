# Hemispherical-head scalar radial displacement

The model reports the exact spherical Lamé displacement at the inner and
outer wall surfaces for every thickness. It uses the same complete-sphere
idealization as the stress calculation, applied away from the hemisphere's
equator. It does not calculate equator restraint or seal closure; the
clamped-equator assumption belongs to the separate NASA buckling correlation.

## Sources

- [Coreform IGA verification manual, section 6](https://docs.coreform.com/cifa/verification-manual/problems/solid_mechanics/linear_elastic_stress/pressurized-sphere/pressurized-sphere.html)
  gives the Lamé radial displacement alongside radial and tangential stresses
  for a sphere with internal and external pressure. Its reference is
  Timoshenko and Goodier, *Theory of Elasticity*, 3rd ed. (1970).
- [IIT Kharagpur, Mechanics of Solids, tutorial 7, problem 8](https://facweb.iitkgp.ac.in/~jeevanjyoti/teaching/mechsolids/2024/ts/ts7.pdf)
  states the spherical strain-displacement relations and generalized Hooke's
  law used below.
- [NASA TM-4579](https://ntrs.nasa.gov/api/citations/19950011002/downloads/19950011002.pdf),
  Ko (1994), Eq. (5), printed p. 6, supplies the membrane displacement used
  by the former implementation. Its hemisphere/cylinder junction discussion
  explains why uniform spherical displacement cannot resolve the junction.

## Derivation and sign convention

For external pressure `p > 0`, zero internal gauge pressure, inner radius `a`,
outer radius `b`, Young's modulus `E`, and Poisson's ratio `nu`, define:

```text
A = -p b^3 / (b^3 - a^3)
B = A a^3
sigma_r = A - B/r^3
sigma_theta = sigma_phi = A + B/(2 r^3)
```

Spherical symmetry gives `epsilon_theta = epsilon_phi = u/r`. Isotropic
three-dimensional Hooke's law therefore gives the displacement directly:

```text
u(r) = r [sigma_theta - nu*(sigma_phi + sigma_r)] / E
     = [(1 - 2 nu) A r + (1 + nu) B/(2 r^2)] / E
```

The radial derivative also satisfies
`E du/dr = sigma_r - nu*(sigma_theta + sigma_phi)`, so both radial and
tangential compatibility can be checked. The pressure tractions are
`sigma_r(a) = 0` and `sigma_r(b) = -p`. Outward displacement and tension are
positive, so external pressure contracts the sphere.

In the limit `t/a -> 0`, both surface displacements tend to NASA TM-4579's
membrane value `-p R^2 (1 - nu)/(2 E t)`. At finite thickness the exact
surface values differ; a median-surface membrane value must not be assigned
to an inner or outer radius. There is no stress or displacement switch at
`R/t = 10`. The buckling model retains its own thin-shell gate.

## Applicability and verification

This is a small-strain, linearly elastic, isotropic solution. It excludes
junction bending, local restraint, imperfections, buckling deformation,
plasticity, and ring-frame response. When the governing material stress
exceeds the supplied strength, displacement remains an elastic formula value
with `elastic_estimate_material_limit` and a reason. Passing that screen
alone does not establish elastic behavior or stability.

Tests check surface traction, equatorial force balance, radial and tangential
Hooke-law identities, the membrane limit, and continuity. The historical
`validation/hemisphere_displacement_reference.py` remains a membrane
comparator; its former thick-branch withholding is not current model behavior.
No hemisphere displacement FEA or experiment is claimed by these checks.
