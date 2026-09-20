# Deferred methods and references

Released methods and their limits are documented in
[engineering.md](engineering.md). This note records stress-component
terminology the tool does not implement and the references and decisions
behind methods that were considered and deferred.

## Stress separation

| Term | Meaning |
|---|---|
| Directional components | Radial, hoop, axial/meridional, and shear stresses at a specified point |
| Section decomposition | Membrane, linear bending, and the nonlinear residual through the wall |
| Code classification | Primary, secondary, and peak categories determined by load origin, equilibrium, geometry, and the selected rules |

For a straight rectangular section of unit width, with `-t/2 <= z <= t/2`,
component-wise linearization is:

```text
N_i = integral(sigma_i(z) dz)
M_i = integral(z * sigma_i(z) dz)
sigma_membrane_i = N_i / t
sigma_bending_i(z) = 12 * M_i * z / t^3
sigma_residual_i(z) = sigma_i(z) - sigma_membrane_i - sigma_bending_i(z)
```

Curved sections require a stated integration convention. Calculate equivalent
stress after combining components at the same location:

```text
sigma_eq_m+b = von_mises(sigma_membrane + sigma_bending)
```

Adding separate von Mises magnitudes, or combining maxima from different
points, is incorrect. The residual is not automatically a peak stress, and
linearizing a Lamé profile does not recover junction bending. ASME BPVC
Section VIII, Division 2, Part 5, Annex 5-A describes component-based
linearization and stress classification.

Tube and hemisphere results report signed surface components, principal
stresses, and von Mises stress. Interior sampling would not improve their
first-yield check. A membrane or membrane-plus-bending requirement would need
those quantities defined and the assessment layer extended; see
[acceptance criteria](engineering.md#acceptance-criteria-and-allowable-stresses).

## Deferred references

References kept for a demonstrated future need, each with the decision taken.

| Topic | Reference and decision |
|---|---|
| Shell junctions | [Johns and Orange, NASA TR R-103](https://ntrs.nasa.gov/citations/19980223076): thin-shell influence coefficients. Requires one specified physical joint, dimensional range, and benchmark. A seated plug needs a different load-transfer model from a continuous joint. [NASA junction experiments](https://ntrs.nasa.gov/citations/19630002603) are a potential stress benchmark. |
| Plate shear deformation | [Reissner (1945)](https://doi.org/10.1115/1.4009435): basis for the existing shear correction. Deflection evidence does not expand stress or collapse validity. |
| Large-deflection plates | [Way](https://cybra.lodz.pl/Content/6370/APM_56_12.pdf) and [NACA pressure tests](https://ntrs.nasa.gov/citations/19930084884): revisit only for a required large-deflection case with explicit rotational and radial edge restraint. |
| Finite-thickness elastic cylinders | [Filippidis and Sadowski (2025)](https://doi.org/10.1016/j.istruc.2025.109146), [companion code](https://github.com/AchilleasF/Structures-ThickCylinders): the pressure specialization sets axial membrane force to zero. It needs separate verification for closed-end hydrostatic loading and predicts elastic bifurcation, not imperfect plastic collapse. |
| Elastoplastic cylinders | [Takla (2019)](https://doi.org/10.1016/j.marstruc.2018.11.009): combined radial/axial loading and nonsymmetric modes. Only the abstract and scope were reviewed; no implementation selected. |
| Empirical cylinder collapse | [Ross et al. (2009)](https://researchportal.port.ac.uk/en/publications/buckling-of-near-perfect-thick-walled-circular-cylinders-under-ex/): stainless-steel experiments. Obtain the calibration data and scatter before evaluating transfer to titanium or aluminium; only the abstract was reviewed. |
| Ring stresses | [Pulos and Salerno](https://dome.mit.edu/handle/1721.3/48806): continue the existing [ring investigation](../validation/sources/ring_failure_mode_selection.md) and its unresolved applicability/benchmark mapping. [Reijmers et al. (2022)](https://doi.org/10.1016/j.marstruc.2022.103161) is a related interframe-collapse reference. |
| Numerical shells | [BOSOR4](https://ntrs.nasa.gov/citations/19740044382), [BOSOR5](https://shellbuckling.com/papers/bosor5/1976.2ndpaper.pdf): outside the active scope. Axisymmetric geometry does not permit restricting buckling to axisymmetric deformation. |
| Attachments and pipelines | [WRC 537](https://store.accuristech.com/wrc/products/preview/3060583) and [DNV-ST-F101](https://www.dnv.com/energy/standards-guidelines/dnv-st-f101-submarine-pipeline-systems/): different loading or structural scopes; no method selected for short closed housings. |

The [January 2025 ABS underwater rules](https://ww2.eagle.org/content/dam/eagle/rules-and-guides/current/special_service/7-rules-for-building-and-classing-underwater-vehicles,-systems-and-hyperbaric-facilities-2025/7-uwvs-rules-jan25.pdf)
are a failure-coverage reference. A narrowly scoped, edition-specific method may
be useful later; whole-code compliance also covers materials, fabrication,
inspection, and testing and is outside these tasks.
