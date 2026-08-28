# DTMB Report 1324 rectangular-ring benchmark

This record compares the public ring-shell calculation with the
rectangular-ring cylinder data in DTMB Report 1324. The model is not
calibrated to it.

## Primary sources

- Reynolds and Blumenberg, *General Instability of Ring-Stiffened Cylindrical
  Shells Subject to External Hydrostatic Pressure*, DTMB Report 1324, 1959:
  [MIT DOME record](https://dome.mit.edu/handle/1721.3/48982) and
  [repository PDF](https://dome.mit.edu/server/api/core/bitstreams/94999e0f-cb4b-4109-b327-6dc943dd5fe6/content).
- [NASA/SP-8007-2020/REV 2](https://ntrs.nasa.gov/api/citations/20205011530/downloads/20205011530%20Rev%202FINALa%201-2023.pdf),
  Eq. 64/65 on printed p. 37, the `0.75` recommendation on p. 38, and
  isotropic ring stiffnesses in Eqs. 82–91 on pp. 40–42.
- [NASA/TP-2011-216882](https://ntrs.nasa.gov/api/citations/20110004039/downloads/20110004039.pdf),
  Appendix A Eq. A16 on printed p. 100 for the exact rectangular
  Saint-Venant torsional constant.

The downloaded DTMB PDF used during source verification had SHA-256
`975aaf2ef7f4b0adde9cd15dd8dc5ea378e91e097d5f145d60923aeeede728a2`.
Figure 2 was visually checked for the physical dimensions and Table 2 for
pressures and circumferential lobe counts.

## Public geometry mapping

Figure 2 defines a machined external solid rectangle:

| Quantity | Source value | Public mapping |
|---|---:|---|
| Shell inside diameter | 8.118 in | internal radius 4.059 in |
| Shell thickness | 0.035 in | wall thickness |
| Ring center spacing | 1.152 in | `ring_spacing` |
| Ring axial width | 0.086 in | `ring_axial_width` |
| Ring radial height | 0.169 in | `ring_radial_height` |
| Young's modulus | 30,000,000 psi | shared shell/ring modulus |
| Poisson ratio | 0.3 | shared shell/ring ratio |
| Yield strength | 85,000 psi | material record; report states response was elastic |

The Eq. 64 radius is explicitly the fixed-ID shell mid-surface radius,
4.0765 in. The same physical rectangle is used for geometry, mass, envelope,
clear bore, `A_r`, `I_r`, and `J_r`:

- `A_r = 0.014534 in² = 9.37675544 mm²`
- centroid from shell surface `= 0.0845 in = 2.1463 mm`
- `I_r = 3.4592131167e-5 in⁴ = 14.39833207 mm⁴`, about its centroid
- `J_r = 2.4387021866e-5 in⁴ = 10.15064488 mm⁴`
- external mid-surface eccentricity `= 0.1020 in = 2.5908 mm`.

The benchmark calls `ring_stiffened_shell_external_pressure`; it does not
bypass the supported section mapping or a public applicability gate.

## Independent cross-check

[`validation/ring_shell_reference.py`](../ring_shell_reference.py) is a
standard-library reference calculation that does not import pv-calc. It
transcribes the governing source equations, calculates rectangular `A_r`,
`I_r`, and Eq. A16 `J_r` directly, and exhaustively scans `m=1..128` and
`n=2..64`. Its source inputs and published values remain separate from its
calculated values. The calculated mid-surface `L/D` values are also checked
against the two-decimal Table 2 column, so reference-to-production agreement
alone cannot conceal a shared diameter or supported-length mapping error.

[`tests/test_independent_reference_parity.py`](../../tests/test_independent_reference_parity.py)
compares that reference with the public model using the same source inputs. It
checks section properties at relative tolerance `1e-12` and pressures at
relative tolerance `1e-11` plus absolute tolerance `1e-10` in the source
pressure unit. The comparison covers all ten Table 2 geometries, the case-17
torsion isolation, governing modes, and the two committed convergence traps.
This is equation and benchmark evidence only, not calibration or an allowable
pressure.

## Case-17 migration and torsion isolation

For `L = 17(1.152) = 19.584 in`:

| Calculation | Ideal (psi) | After NASA 0.75 (psi) | Mode |
|---|---:|---:|---:|
| Eq. 64/65, mid-surface radius, before ring torsion | 536.543723 | 402.407792 | `m=1, n=3` |
| Eq. 64/65 plus Eq. 91 `G_r J_r / b_r` | 538.049867 | 403.537400 | `m=1, n=3` |

The isolated exact-`J_r` effect is +1.506144 psi ideal (+0.280711%) and
+1.129608 psi after the source-recommended factor. No section property,
geometry, mode bound, or factor was tuned. DTMB reports 428 psi from Kendrick
Part III and 473 psi experimentally, both with `n=3`.

## Multi-case comparison

The committed executable checks all ten Table 2 rows. Selected rows spanning
the predicted `n=3` and `n=2` regions are:

| Frame spaces | DTMB Kendrick psi (n) | DTMB experiment psi (n) | Eq. 64+91 ideal psi | After 0.75 psi | Model mode |
|---:|---:|---:|---:|---:|---:|
| 17 | 428 (3) | 473 (3) | 538.049867 | 403.537400 | `(1,3)` |
| 23 | 367 (2) | 412 (3) | 379.260498 | 284.445374 | `(1,2)` |
| 29 | 233 (2) | 383 (2) | 280.915571 | 210.686678 | `(1,2)` |
| 33 | 197 (2) | 281 (2) | 256.031046 | 192.023284 | `(1,2)` |

The model transitions from `n=3` to `n=2` between 19 and 20 frame spaces;
Kendrick transitions between 21 and 23 and the experiment between 28 and 29.
This discrepancy is retained as a model limitation rather than removed by
calibration.

## Applicability and maturity

NASA gives no positive lower `t/r` bound for Eq. 64, so the former `0.015`
screen was removed. DTMB has `t/r = 0.008586` and passes the public positive-
dimension and shared thin-shell checks.

The primary-source investigation is recorded in
[`validation/sources/nasa_sp8007_eq64_eq66_transition.md`](../sources/nasa_sp8007_eq64_eq66_transition.md).
It found no authoritative numeric Eq. 64/Eq. 66 transition and therefore does
not change this model's applicability boundary.

The result remains `benchmark_compared`, `partial`, and advisory because:

- NASA cautions that the shared formulation is less accurate for moderately
  long low-lobe cases; DTMB governs at `n=2–3`;
- NASA says Eq. 66 replaces Eq. 64 for long cylinders but provides no numeric
  transition criterion;
- the isolated-bay smooth-shell calculation is an ideal simply-supported
  advisory, not a validated treatment of finite ring width, rolling, or
  local/global interaction; and
- ring material strength/crippling, frame tripping, attachments/welds,
  fabrication effects, and nonlinear interaction need additional geometry,
  specialist analysis, FEA, or test evidence.

The typed result records every implemented-advisory, not-applicable, and
externally blocked complementary mode. A global pass is never represented as
complete pressure-hull coverage.

## Reproduction

From the `pv-calc` directory:

```console
uv run python validation/published/dtmb_1324_case17.py
uv run python validation/ring_shell_reference.py
uv run pytest -q tests/test_independent_reference_parity.py tests/test_dtmb_1324_case17.py tests/test_ring_shell.py
```

The harness exits nonzero on pressure, mode, convergence, or section-mapping
drift and prints deterministic JSON only after every assertion passes.
