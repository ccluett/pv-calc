# Smooth-cylinder buckling coverage

This record describes the pv-calc 0.2.0 equations and bundled material values.
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
at greater pressure. A stronger necessary bound follows from elastic release:

```text
P_cr >= P_target,   P_cr q <= sigma_proportional,   q > 10
                => P_target < sigma_proportional / 10
```

| Material | Yield, MPa | Yield/geometric boundary depth, m | Elastic necessary depth bound, m |
|---|---:|---:|---:|
| SS-316-316L | 207 | 1408.540 | No adopted proportional limit |
| Al-6061-T6 | 241 | 1639.894 | 1191.537 |
| Ti-Grade-2 | 276 | 1878.053 | No adopted proportional limit |
| Ni-625 | 414 | 2817.080 | No adopted proportional limit |
| Al-7075-T6 | 427 | 2905.539 | No adopted proportional limit |
| SS-2507 | 552 | 3756.106 | No adopted proportional limit |
| Ti-6Al-4V | 827 | 5627.355 | 3911.151 |

Five of seven bundled metals have no fully released named-material smooth-shell
buckling capacity at any depth or geometry. Supplying suitable material data can
open elastic coverage; it does not supply the missing inelastic calculation.

The necessary bounds are not attainable depths for every geometry. Critical
pressure and its membrane stress depend on geometry and material, not applied
pressure. Lowering demand can change a margin or the working-stress screen,
but cannot change the same geometry's `capacity_status`.

For a fixed 10 in OD, 24 in span, Al-6061-T6 cylinder, the whole q > 10 domain
uses NASA's moderate branch. With b the outside radius, Eq. 24 gives:

```text
K = 0.855 E sqrt(gamma) b / [(1-nu^2)^(3/4) L]
sigma_cr = P_cr q = K / [sqrt(q) (q+1/2)]
```

Solving sigma_cr = 183.4 MPa gives q = 14.082264, t = 8.709210 mm, and
P_cr = 13.023474 MPa, corresponding to 846.126 m at the stated design factor.
Thicker walls exceed the proportional limit; thinner walls have lower capacity.
This family's released sizing ceiling is therefore about 846 m, below 1192 m.

The geometric cutoff is the project's conventional Roark thin-tube gate, not a
numerical NASA limit. ASME's D_o/t >= 10 route corresponds to q >= 4.5 because
D_o/t = 2q+1; the current gate corresponds to D_o/t > 21. UG-28's own geometry
and material charts cannot establish applicability of NASA's equations.
[ASME VIII-1, 2025, UG-28, pp. 24-26, primary-text mirror](https://tg.government.bg/docu/dokladi2019/ASME%20BPVC.VIII.1%20%28ASME%20BPVC%20Section%208%20Division%201%29%202025.pdf).

At q = 10.05, the composition already retains these elastic estimates under
`components.smooth_buckling.result.correlated_critical_pressure_mpa`:

| OD, in | Elastic estimate, MPa | First-yield pressure, MPa | Overall assessment at 92.35134 MPa |
|---|---:|---:|---|
| 12 | 63.685457 | 86.225559 | fail |
| 16 | 86.908397 | 86.225559 | fail |

Both buckling results are `released_pending_plasticity`. Summary/text output
shows the existing estimate separately from acceptance capacity and margin,
which remain null. The stress check already establishes the overall failure.

Within the implemented correlation, a plasticity reduction <= 1 cannot make an
elastic estimate below demand pass.

The material-source claims were checked against the actual handbook pages:

| MIL-HDBK-5J location | Verified content |
|---|---|
| Section 1.4.4.2, p. 1-9 (PDF page 21) | Tension and compression proportional-limit convention: plastic strain 0.0001 |
| Figure 3.6.2.2.6(i), p. 3-283 (PDF page 585) | 6061-T6 extrusion: typical n(LT compression) = 28 |
| Figures 5.4.1.1.6(b,c), p. 5-65 (PDF page 957) | Annealed Ti-6Al-4V extrusion: typical longitudinal compression n = 21 at room temperature |
| Figure 3.7.6.1.6(h), p. 3-399 (PDF page 701) | 7075-T651 plate, 0.250-2.000 in: n(L) = 16, n(LT) = 19 in compression |
| Figure 3.7.6.1.6(j), p. 3-400 (PDF page 702) | 7075-T6/T651 rolled bar, rod, shape, <= 3.000 in: n(L compression) = 13 |
| Figure 3.7.6.1.6(l), p. 3-401 (PDF page 703) | 7075-T651X extrusion, 0.500-0.749 in: n(L) = 26, n(LT) = 27 in compression |

These product and directional distinctions prevent treating any one curve as
a universal alloy property. The existing titanium record uses a longitudinal
shape for hoop compression; that substitution remains unverified.
[MIL-HDBK-5J, primary-text mirror](https://kaspercalc.com/downloadable/MIL-HDBK-5J-1.pdf).
