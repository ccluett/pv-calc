# UnderPressure hemispherical-endcap display comparison

This record reproduces the hemispherical-endcap dialog shown in the
[UnderPressure Version 4.0 User Manual](https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf),
printed pp. 62-64.

## Source record and transcribed case

- Manual revision: 3/27/01
- Inspected PDF SHA-256:
  `7a747e6ccd7efd6fdbf0c74a295751086b861661ca6de45f277cdda30c2e43c8`
- Material shown: aluminum 6061-T6, `E = 9.9 Mpsi`, `nu = 0.33`, yield
  strength `35,000 psi`
- Hemispherical inside diameter: `3.500 in`
- Hemispherical outside diameter: `4.000 in`
- Wall thickness: `0.250 in`
- Applied external pressure row: `1,000 psi`

The screenshot geometry gives internal radius `1.75 in`, external radius
`2.00 in`, and mean radius `1.875 in`, so `R_m/t = 7.5`. The displayed
`0.54199 lb` air weight also independently agrees with that half-shell geometry
and the manual's material density. This reconstruction uses only values shown in
the manual; it does not infer a new material property or calibration coefficient.

## Display reproduction

The independent standard-library reference applies the manual's documented
thick-sphere stress branch because `R_m/t <= 10`. At `1,000 psi` it calculates:

| Quantity | Independent value | Manual display | Acceptance |
|---|---:|---:|---:|
| Governing equivalent stress | `4,544.3787 psi` | `4,544.4 psi` | `0.05 psi` absolute |
| Ductile-metal shell failure pressure | `7,701.8229 psi` | `7,701.8 psi` | `0.05 psi` absolute |
| Roark/UnderPressure probable-minimum buckling | `64,240.0 psi` | `64,240 psi` | `0.5 psi` absolute |

The first two limits are half the last displayed tenth of a psi. The buckling
limit is half the last displayed whole psi. They are reproduction tolerances,
not uncertainty or design acceptance bands.

## Validity disposition

The manual says hemisphere thin-wall buckling may be invalid when
`mean radius / thickness <= 10`; this case is `7.5`. pv-calc therefore reproduces
the displayed `64,240 psi` value only as `roark_probable_minimum_pressure_mpa`.
It does not release that value as buckling capacity or margin.

The separately released thin-shell path uses the empirical clamped-cap lower
bound from NASA SP-8032 under the gates recorded in
[`validation/sources/nasa_sp8032_hemisphere_external_pressure.md`](../sources/nasa_sp8032_hemisphere_external_pressure.md).
No UnderPressure 4.60 capture is claimed; making one would require a manual GUI
run.
