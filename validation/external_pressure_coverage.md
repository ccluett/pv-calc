# Smooth-cylinder buckling coverage

This record is an illustrative coverage study for the existing 6000 m housing
case. It is separate from the generic equation evidence indexed in
`validation/coverage_inventory.py`.
Reproduce the sizing and composition results with
`uv run python validation/external_pressure_coverage.py` from the checkout.

The example uses 6000 m depth, density 1046 kg/m^3, gravity 9.81 m/s^2,
design factor 1.5, and 609.6 mm unsupported length. Service pressure is
61.56756 MPa; design pressure is 92.35134 MPa. Minimum margin is zero.

For Ti-6Al-4V, closed-end first-yield sizing succeeds at these walls, while
combined stress/buckling sizing returns `no_reliable_solution` for each:

| OD, in | First-yield wall, mm | R_mid/t |
|---|---:|---:|
| 8 | 10.353167 | 9.313422 |
| 10 | 12.941459 | 9.313422 |
| 12 | 15.529751 | 9.313422 |
| 14 | 18.118042 | 9.313422 |
| 16 | 20.706334 | 9.313422 |

At 8 in OD, stress requires t >= 10.353167 mm and the buckling gate requires
t < 9.676190 mm. No search interval satisfies both. This establishes missing
model coverage, not physical impossibility or a governing collapse mode.

The NASA Eqs. 30-32 material correction does not change that conclusion. All
five still return `no_reliable_solution`: first-yield sizing lands at
q = 9.313422, while the existing model requires q > 10.

Let a and b be the inner and outer radii, t = b-a, and q = R_mid/t. For the
closed-end Lamé model, bore von Mises stress and the first-yield boundary give:

```text
sigma_VM(a) = sqrt(3) P / (1 - (a/b)^2)
x = a/b = sqrt(1 - sqrt(3) P / sigma_y)
q = 1/(1-x) - 1/2
q = 10 => x = 19/21 => P/sigma_y = 80/(441 sqrt(3)) = 0.1047347427
```

Here P is the design pressure multiplied by one plus any required margin.
The q > 10 gate excludes the boundary itself and every stress-compliant wall
at greater pressure. For a record without a complete compressive curve, an
additional necessary bound follows from elastic release:

```text
P_cr >= P_target,   P_cr q <= sigma_proportional,   q > 10
                => P_target < sigma_proportional / 10
```

| Material | Yield, MPa | Yield/geometric boundary depth, m |
|---|---:|---:|
| SS-316-316L | 207 | 1408.540 |
| Al-6061-T6 | 241 | 1639.894 |
| Ti-Grade-2 | 276 | 1878.053 |
| Ni-625 | 414 | 2817.080 |
| Al-7075-T6 | 427 | 2905.539 |
| SS-2507 | 552 | 3756.106 |
| Ti-6Al-4V | 827 | 5627.355 |

The bundled generic Al-6061-T6 and Ti-6Al-4V records retain historical curves
as reference-only data. They can produce a corrected numerical estimate and
drive exploratory sizing, but their `released_unqualified_material` status
cannot pass acceptance. A separately retained elastic upper bound can still
establish conservative failure when it falls below demand and the required
margin. The other five metals carry neither a proportional limit nor a
compressive curve. Qualified limits and curves can be supplied explicitly or
through a deliberately scoped custom record. The correction remains inside the
same geometric domain.

## The q > 10 geometric cutoff

The geometric cutoff is the project's conventional Roark thin-tube gate, not a
numerical NASA limit. NASA/SP-8007-2020/REV 2 states no numeric radius/thickness
bound for Eqs. 19-29; the equations descend from Batdorf's simplified analysis
for thin cylindrical shells, so what the source establishes is a thin-shell
assumption, not a cutoff value. ASME's D_o/t >= 10 route corresponds to
q >= 4.5 because D_o/t = 2q+1; the current gate corresponds to D_o/t > 21.
UG-28's own geometry and material charts cannot establish applicability of
NASA's equations. ASME BPVC Section VIII, Division 1 (2025), UG-28, pp. 24-26.

The model retains q > 10 and has no thick-shell capacity, collapse analysis, or
physical validation. The material correction therefore establishes no new
thickness coverage for the five housings above.

At q = 10.05 the composition reports these when supplied the illustrative
titanium curve assumption (n = 21 anchored at 827 MPa) explicitly:

| OD, in | Elastic estimate, MPa | Corrected estimate, MPa | eta | First-yield pressure, MPa | Overall at 92.35134 MPa |
|---|---:|---:|---:|---:|---|
| 12 | 63.685457 | 62.716193 | 0.984780 | 86.225559 | fail |
| 16 | 86.908397 | 72.966922 | 0.839584 | 86.225559 | fail |

Both report a corrected estimate and margin with `released_unqualified_material`
status; the assessment capacity remains unset. In the 16-inch row, the corrected
estimate falls below both the elastic estimate and first yield; a simple minimum
of the two uncorrected limits would give a different result.

Within the implemented correlation, a plasticity reduction <= 1 cannot make an
elastic estimate below demand pass. Both cases still fail; the stress check
already established that.

The material-source claims were checked against the actual handbook pages:

| MIL-HDBK-5J location | Verified content |
|---|---|
| Section 9.8.4.1.2 | Compressive Ramberg-Osgood form `strain = s/E + 0.002*(s/s0)^n`, anchored at 0.2% proof stress |
| Section 1.4.4.2, p. 1-9 (PDF page 21) | Tension and compression proportional-limit convention: plastic strain 0.0001 |
| Figure 3.6.2.2.6(i), p. 3-283 (PDF page 585) | 6061-T6 extrusion: typical n(LT compression) = 28 |
| Figures 5.4.1.1.6(b,c), p. 5-65 (PDF page 957) | Annealed Ti-6Al-4V extrusion: typical longitudinal compression n = 21 at room temperature |
| Figure 3.7.6.1.6(h), p. 3-399 (PDF page 701) | 7075-T651 plate, 0.250-2.000 in: n(L) = 16, n(LT) = 19 in compression |
| Figure 3.7.6.1.6(j), p. 3-400 (PDF page 702) | 7075-T6/T651 rolled bar, rod, shape, <= 3.000 in: n(L compression) = 13 |
| Figure 3.7.6.1.6(l), p. 3-401 (PDF page 703) | 7075-T651X extrusion, 0.500-0.749 in: n(L) = 26, n(LT) = 27 in compression |

MIL-HDBK-5J is historical: the DLA cancellation notice identifies MMPDS as a
suitable successor and cautions users to evaluate it for their application.
These product and directional distinctions prevent treating any one curve as
a universal alloy property. The generic aluminium record therefore does not
adopt the LT-extrusion curve, and the generic titanium record does not adopt the
longitudinal-extrusion curve, for unspecified hoop compression and product
forms. The values above are an explicit illustrative assumption whose
substitutions remain unverified. Source: MIL-HDBK-5J (31 January 2003), cited
locations above.

## Bounded elastic benchmark outcome

A four-point continuum benchmark was specified at q values 9.313422, 10.0,
10.5, and 20.0, with three mesh levels and separate outer-radius and NASA
mid-surface load resultants. The target was an 8 in OD, 609.6 mm long cylinder
with E = 113800 MPa and nu = 0.34. The comparison limits were 2% finest-mesh
change and 5% absolute NASA error relative to FEA. It was stopped after the
target case exposed two limitations.

First, a one-node rigid-motion gauge produced a lower, mesh-sensitive `n = 1`
mode. A symmetric mean-displacement gauge recovered a degenerate `n = 2` pair,
but the spectrum's gauge sensitivity prevents treating that result as a unique
physical eigenproblem. At `q = 9.313422`, the first two C3D20 meshes gave
64.17199 and 63.73910 MPa for that `n = 2` branch, compared with the unadjusted
NASA value 63.75088 MPa. These values are diagnostic only.

More decisively, CalculiX 2.20 `*BUCKLE` uses the pressure load to establish the
reference stress but omits the distributed-pressure load tangent from the
eigenmatrix. This was verified in the Debian 2.20-1 source:
[`arpackbu.c`](https://sources.debian.org/src/calculix-ccx/2.20-1/ccx_2.20/src/arpackbu.c/)
selects the buckling matrix, while the distributed-load block in
[`e_c3d.f`](https://sources.debian.org/src/calculix-ccx/2.20-1/ccx_2.20/src/e_c3d.f/)
is excluded when `buckling == 1`. The matching
[upstream source archive](https://www.dhondt.de/ccx_2.20.src.tar.bz2) has SHA-256
`63bf6ea09e7edcae93e0145b1bb0579ea7ae82e046f6075a27c8145b72761bcf`.

The partial comparison therefore cannot validate NASA's pressure-bifurcation
prediction or the current geometric cutoff. No runner or result artifact is
retained, and `q > 10` remains unchanged. A future study needs a verified
pressure-load tangent, matched closure and end restraints, and evidence for
imperfections and material nonlinearity before it can address vessel collapse.
