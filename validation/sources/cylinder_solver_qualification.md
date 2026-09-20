# Cylinder benchmark procedure qualification

20 September 2026. The tested CalculiX 2.20 procedure did not qualify against
the published benchmark. Cylinder coverage remains unchanged.

## Reference and acceptance limits

The published reference is Abaqus's
[elastic ring under external pressure](https://docs.software.vt.edu/abaqusv2025/English/SIMACAEBMKRefMap/simabmk-c-ringbuckling.htm):
mean radius 2540 mm, square section 25.4 mm, elastic modulus 206800 MPa,
Poisson ratio zero, and the first in-plane buckling mode with two lobes.
Its reported critical pressure is approximately 0.05171 MPa.

The selected existing tool is the repository's CalculiX 2.20 container.
The candidate procedure applies pressure in a geometrically nonlinear static
step, then extracts signed tangent eigenvalues in a prestressed frequency step.
A zero crossing locates loss of stiffness; a failed static solve alone does not
establish a buckling pressure.

Before comparison, the limits were set at 5% pressure error against the
reference, 2% change between the finest meshes, and 0.5% change under equivalent
rigid-motion constraints. The lowest physical mode must be the two-lobe mode;
higher modes cannot substitute for an unexplained lower mode. Three meshes and
both symmetric mean constraints and point constraints are checked.

## Pressure-load stiffness

The CalculiX 2.20 source distinguishes this procedure from `*BUCKLE`.
[`arpack.c`](https://sources.debian.org/src/calculix-ccx/2.20-1/ccx_2.20/src/arpack.c/)
selects the prestressed frequency assembly;
[`e_c3d.f`](https://sources.debian.org/src/calculix-ccx/2.20-1/ccx_2.20/src/e_c3d.f/)
includes the distributed-pressure stiffness in that path. Signed eigenvalues
must be read from the text results: displayed frequencies alone lose the sign
needed to identify instability.

## Result: not qualified

The full-circle C3D20 model restrains axial displacement, consistent with the
reference's zero Poisson ratio and in-plane mode. Pressure acts on its outer
surface. The first signed eigenvalue is followed through zero; every reported
crossing has the expected two-lobe shape.

| Circumferential × radial × axial elements | Critical pressure, MPa |
|---|---:|
| 32 × 2 × 2 | 0.083534 |
| 48 × 3 × 3 | 0.049987 |
| 64 × 4 × 4 | 0.044304 |
| 96 × 4 × 4 | 0.042162 |
| 128 × 4 × 4 | 0.041790 |

The initial three meshes did not converge, so two further circumferential
refinements were checked. The last change is 0.891%, within the 2% limit, but
the finest result is 19.184% below the published pressure, failing the 5% limit.
Point and mean rigid-motion constraints at the 48-element mesh change the
minimum critical pressure by only 0.00008%, but the point constraints split
the two-lobe mode pair. Agreement of the minimum does not establish invariance
of the spectrum. An independent linear-static preload check gives the same
crossing as the nonlinear preload at the 64-element mesh; that choice does not
explain the pressure discrepancy.

The [focused runner](../fea/pressure_ring_qualification.py) and
[comparison data](../fea/results/pressure_ring_qualification.json) retain the
failed comparison. Raw solver files stay in the requested work directory.
Pressure-load stiffness being present was necessary, but did not establish
accuracy for this procedure and model. No correction factor was fitted.

**Investigation closed under the stop condition.** A suitable accessible
procedure was not demonstrated. The four-point cylinder comparison is not
resumed, `R_mid/t > 10` stays unchanged, and no cylinder capability is added.
