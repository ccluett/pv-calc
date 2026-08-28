# NASA SP-8007 Eq. 64 / Eq. 66 transition investigation

- **Status:** No authoritative numeric transition rule established; external
  blocker retained
- **Investigation date:** 2026-07-20
- **Scope:** Orthotropic and ring-stiffened cylinders under lateral or
  hydrostatic external pressure
- **Decision effect:** Eq. 66 remains unimplemented; advisory status is
  unchanged

This is a source investigation rather than a qualified external engineering
review. It does not infer a threshold from plots, equality of equations, DTMB
agreement, the computed lobe count, or engineering intuition.

## Primary sources checked

| Source | Exact edition and location | Result |
|---|---|---|
| [NASA/SP-8007-2020/REV 2](https://ntrs.nasa.gov/api/citations/20205011530/downloads/20205011530%20Rev%202FINALa%201-2023.pdf) | *Buckling of Thin-Walled Circular Cylinders*, second revision November 2020, issued December 2020; Section 4.1.2.3, printed pp. 37-38, Eqs. 64-68; definitions on printed pp. 35 and 40-42 | Gives the exact Eq. 66 expression, introduced only by “For long cylinders, Eq. 64 is replaced by.” It gives no numeric Eq. 64/Eq. 66 transition. |
| [NASA SP-8007, revised August 1968](https://ntrs.nasa.gov/api/citations/19690013955/downloads/19690013955.pdf) | *Buckling of Thin-Walled Circular Cylinders*, September 1965, revised August 1968; Section 4.3.3, printed pp. 19-20, Eqs. 49-52 | Gives the same qualitative instruction: “For long cylinders, equation (49) is replaced by” Eq. 50. No numeric transition is supplied. |
| [NACA TN 4237](https://ntrs.nasa.gov/api/citations/19930085193/downloads/19930085193.pdf) | Herbert Becker, *General Instability of Stiffened Cylinders*, July 1958; printed pp. 1-2 and 6, Appendix C on printed pp. 14-19 | Defines moderate-length cylinders qualitatively as boundary-influenced and long cylinders as having no boundary influence. It provides no dimensionless or numeric boundary between them. |
| [Becker and Gerard NTRS record](https://ntrs.nasa.gov/citations/19620003091) | H. Becker and G. Gerard, “Elastic Stability of Orthotropic Shells,” *Journal of the Aerospace Sciences*, vol. 29, no. 5, May 1962, pp. 505-512 and 520 | NASA catalogs the source cited for related closed-form orthotropic approximations, but the NTRS record supplies no downloadable text. It therefore cannot establish transition language for this model. |

The inspected PDF SHA-256 values were:

- Rev. 2: `299dfb8807862f174768356353f39c6bf6993596cb6f5933dd4fd23181e8837b`
- revised 1968 edition: `6eb451ac9dadf2c0605d343398e6b92175c2d96fda5afaceee118583cc2a5e9c`
- NACA TN 4237: `4236308ac7d98f4b931a863e05b74dd2fff05f03c4252b5f24b32e22d559d1ae`

## Exact Rev. 2 equation and definitions

On printed p. 37, Eq. 64 is the finite-length determinant solution. For
hydrostatic pressure, Eq. 65 replaces its `n^2` denominator term with:

```text
n^2 + (1/2) (m pi r / L)^2
```

The source directs `m` and `n` to be varied for the hydrostatic minimum. On
printed p. 35, `m` and `n` are the number of axial half waves and
circumferential full waves. The cylinder edges are simply supported: radial
displacement is restrained and tangent rotation is free.

Rev. 2 Eq. 66 on printed p. 37 is:

```text
p_cr = 3 (D_y_bar - C_y_bar^2 / E_y_bar) / r^3
```

For the isotropic ring-only specialization on printed pp. 40-42:

- `r` is the radius of the shell reference surface and `L` is the supported
  cylinder length;
- `E_y_bar` is circumferential extensional stiffness (Eq. 83);
- `C_y_bar` is circumferential extension-bending coupling from ring
  eccentricity (Eq. 87); and
- `D_y_bar` is circumferential bending stiffness, including ring centroidal
  inertia and its eccentric parallel-axis term (Eq. 90).

Thus, the Eq. 66 formulation is known. Its defensible applicability boundary is
not.

## Numeric statements that are not the transition rule

Two nearby numeric statements cannot be reassigned to Eq. 66:

1. Eq. 68 on printed p. 38 is introduced as the condition for the separate
   coupling-neglected approximation in Eq. 67. Its dimensionless expression
   greater than 500 is not stated as the Eq. 64/Eq. 66 transition and does not
   apply when the Eq. 66 coupling term is retained.
2. The `Z < 100` and `Z > 500` discussion on printed p. 38 concerns the relative
   effectiveness of outside and inside rings. It does not select Eq. 64 or 66.

Rev. 2 also cautions in its general length-classification discussion on printed
p. 22 that short, moderately long, and long definitions are load-case-specific,
not rigid, and may differ between analyses. A cutoff from the unstiffened-shell,
compression, or torsion sections therefore cannot be transferred to Eq. 64/66
without explicit source authority.

## Disposition and exact remaining requirement

The production blocker remains `long_cylinder_global_eq66_transition`.
Implementing Eq. 66 requires both of the following:

1. an authoritative, inspectable source that explicitly defines the quantitative
   “long cylinder” applicability boundary for the Eq. 64/Eq. 66 orthotropic
   external-pressure pair, with its variables, load case, boundary conditions,
   coupling assumptions, and applicable construction; and
2. a qualified engineering decision that adopts that source and specifies
   behavior at and around the boundary, followed by independent cases,
   published-benchmark reruns, model-version change control, and reapproval.

If no such source can be obtained, a qualified engineering authority must make
and record a project-specific selection based on an identified governing basis
and validated higher-fidelity evidence. This record is a source survey, not that
review. Until one of those paths is complete, Eq. 64 remains finite-length,
partial, and advisory, and Eq. 66 remains unimplemented.
