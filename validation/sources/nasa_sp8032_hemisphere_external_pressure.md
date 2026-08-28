# NASA SP-8032 hemispherical-head external-pressure disposition

- **Status:** equation release approved at `verified_equation`; advisory and partial
- **Investigation date:** 2026-07-22
- **Scope:** constant-thickness isotropic hemispherical head under uniform external pressure
- **Decision effect:** release the clamped-equator elastic correlation only inside explicit thin-shell, geometry, and proportional-limit gates

This is a source disposition for an advisory calculation.

## Sources inspected

| Source | Exact location | Use |
|---|---|---|
| [NASA SP-8032](https://shellbuckling.com/papers/classicNASAReports/NASASP-8032.pdf), *Buckling of Thin-Walled Doubly Curved Shells*, August 1969 | Section 4.2.1.1, printed pp. 4-6, Eqs. 1-4 and Figures 1-2 | Classical Zoelly pressure, spherical-cap geometry parameter, and empirical lower bound for clamped caps |
| [UnderPressure 4.0 User Manual](https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf), revision 3/27/01 | printed pp. 7-8 and 62-64; Appendix C, printed p. C-1 | `mean radius / thickness > 10` thin-wall convention, thin/thick stress selection, ductile-metal equivalent-stress criterion, and Roark software-parity formula |
| Roark's *Formulas for Stress and Strain*, 6th ed., 1989 | Table 28 case 3a, p. 523; Table 32 cases 2a-2b, p. 640; Table 35 case 22, p. 691 | Thin and thick sphere stress and the `0.365 E(t/R)^2` probable-minimum comparator cited by UnderPressure |

The external PDFs are not vendored. The inspected file records are:

- NASA SP-8032 mirror: SHA-256
  `440e309c04bf6f0833e91e1781cb1de398baf7b8ddd2e83a52c47a5bf442f5b2`
- UnderPressure 4.0 manual: SHA-256
  `7a747e6ccd7efd6fdbf0c74a295751086b861661ca6de45f277cdda30c2e43c8`

Both were retrieved on 2026-07-22.

## Released equation transcription

NASA defines the complete-sphere classical pressure and the cap parameter as:

```text
p_cl = 2 E (t/R)^2 / sqrt(3 (1 - nu^2))
lambda = [12 (1 - nu^2)]^(1/4) sqrt(R/t) 2 sin(phi/2)
```

Here `R` is the shell mean radius and `phi` is half the cap's included angle.
For a hemisphere, `phi = 90 degrees`, so the last factor is `sqrt(2)`.
NASA's Eq. 4 gives the lower bound to the cited clamped-cap data:

```text
p_cr / p_cl = 0.14 + 3.2 / lambda^2,  lambda > 2
```

The text immediately following Eq. 4 permits its Figure 2 correlation for deep
as well as shallow shells. That supports a hemispherical cap. It does not remove
the document's thin-walled, elastic, isotropic, uniform-shell, uniform-pressure,
and clamped-edge assumptions.

The source attributes the gap between classical theory and the cited tests
largely to initial shape deviations and differences in actual edge conditions.
Therefore the Eq. 4 factor is retained as the source's empirical lower bound; no
additional pv-calc knockdown or fitted factor is applied.

## Release gates and withheld regimes

The production kernel releases `released_buckling_pressure_mpa` only when all of
the following are true:

1. `mean_radius / wall_thickness > 10`, the documented UnderPressure/Roark
   thin-wall convention;
2. `lambda > 2`, the explicit NASA Eq. 4 bound;
3. a source-traceable material proportional limit is supplied; and
4. the NASA-correlated critical membrane stress is no greater than that
   proportional limit.

Outside any gate, the kernel reports the classical value, the NASA candidate
where Eq. 4 is defined, the UnderPressure/Roark comparator, and explicit
violations, but withholds released capacity and margin. No thick-shell or
inelastic knockdown is inferred.

The UnderPressure/Roark `0.365 E(t/R)^2` value is retained only as a separately
labeled software-parity oracle. It does not replace NASA Eq. 4 and does not set
released capacity.

## Scope boundary

The calculation excludes equator-junction bending, real seat restraint,
attachments, openings, thickness transitions, fabrication imperfections,
residual stress, plastic buckling interaction, safety factors, environmental
degradation, and load combinations. NASA's source-level test correlation is not
pv-calc-specific physical validation. Physical testing has not been performed,
and the maturity level remains unchanged.
