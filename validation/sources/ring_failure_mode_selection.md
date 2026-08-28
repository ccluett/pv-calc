# Ring failure-mode selection for the supported rectangular ring

- **Status:** no mode selected; the four ring `external_blocker` dispositions stand;
  focused DAPS/Kendrick source mapping is open
- **Investigation date:** 2026-07-31
- **Scope:** one solid, non-overlapping rectangular ring, internal or external, on
  a thin isotropic cylindrical shell under external hydrostatic pressure,
  ductile metal
- **Decision effect:** calculations, applicability, model version, and the
  evidence matrix remain unchanged

This is a source investigation, not a qualified external engineering review. No
equation, coefficient, symbol mapping, or applicability boundary below is
inferred from a plot, from a neighbouring clause, from a different section
shape, or from engineering intuition. A candidate is recorded as selectable only
if one obtainable source states its equations, its inputs, its validity
boundaries, and its applicability rules for *this* section, and only if an
independent comparison case exists to verify an implementation against.

## Sources inspected

| Source | Exact edition and location | Result |
|---|---|---|
| [NASA/SP-8007-2020/REV 2](https://ntrs.nasa.gov/api/citations/20205011530/downloads/20205011530%20Rev%202FINALa%201-2023.pdf) | *Buckling of Thin-Walled Circular Cylinders*, Rev. 2; orthotropic-cylinder scope, printed p. 34; smeared-stiffener limitations, printed p. 44; joints, printed p. 57; design of ring frames, printed p. 58; discretization guidance, printed p. 62 | Names stiffener buckling, stiffener crippling, stiffener rolling, joint/weld-land effects, and local/global interaction as things that must be investigated, and supplies no equation for any of them. Its only cited ring-frame criterion is empirical, is for bending or compression rather than external pressure, and NASA itself calls its test configurations not often relevant |
| [DTMB Report 1497](https://dome.mit.edu/handle/1721.3/48806) | Pulos and Salerno, *Axisymmetric Elastic Deformations and Stresses in a Ring-Stiffened, Perfectly Circular Cylindrical Shell under External Hydrostatic Pressure*, September 1961; assumptions on printed p. 1; frame boundary condition and effective frame area, Eqs. [17]-[25]; ring load and frame stress, Eqs. [56]-[58], printed p. 16; case-1 parameters, Eqs. [59]-[60]; stress functions, Eqs. [72]-[75], printed p. 23; Appendix B | Gives the complete closed-form axisymmetric solution, the total ring load, and the circumferential stress at the frame flange. Offers two non-agreeing effective-frame-area definitions and states the frame-flange equation only for an external frame |
| [DTMB Report 1639](https://dome.mit.edu/handle/1721.3/49013) | Pulos, *Structural Analysis and Design Considerations for Cylindrical Pressure Hulls*, April 1963; effective frame area Eq. (9), printed p. 22; ring load Eq. (21); frame flange stress Eq. (175), printed p. 111 | Closes both DTMB 1497 gaps: it assigns one effective-area form to internal and the other to external framing, and gives the internal-frame denominator. Contains no worked numerical example |
| [DTMB Report 1255](https://dome.mit.edu/handle/1721.3/48926) | Lunchick and Overby, *An Experimental Investigation of the Yield Strength of a Machined Ring-Stiffened Cylindrical Shell (Model BR-7M) under Hydrostatic Pressure*, November 1958; Table 1 geometry, Table 4 yield pressures | Externally framed machined rectangular-frame model with a full geometry table, but the tabulated theory is shell-plating yield pressure under five yield criteria. No frame stress is tabulated |
| [ABS Rules for Building and Classing Underwater Vehicles, Systems and Hyperbaric Facilities](https://ww2.eagle.org/content/dam/eagle/rules-and-guides/archives/special_service/7_underwater_vehicles_systems_hyperbaric_facilities_2018/uwvs-rules-jan18.pdf) | January 2018 edition, publisher-hosted; Section 6, 19.3 stiffener properties, printed p. 31; 19.5 inter-stiffener strength, printed pp. 31-32; 19.15 stiffeners, printed pp. 33-34 | The only obtainable source that states a criterion naming flat bars. Its stiffener clauses open with a continuous-welding premise and sit inside a package of usage factors and an out-of-roundness allowance |
| [DNV-RP-C202](https://www.dnv.com/energy/standards-guidelines/dnv-rp-c202-buckling-strength-of-shells/) | *Buckling strength of shells*, publisher page checked 2026-07-30 | Publisher supplies the document by subscription only. In the copies that can be retrieved, every equation in [3.9] and [3.10] is a page image with no text layer, so nothing can be transcribed. Its ring-stiffener torsional-buckling length is the arc length between tripping brackets, an input this geometry does not have |
| `apps.dtic.mil` | Any report PDF | TLS certificate expired; the host cannot be verified, so nothing hosted only there is citable here |
| [UnderPressure 4.0 User Manual](https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf) | revision 3/27/01; analysis types on printed pp. 45-68; Appendix C formulas | The commercial cross-check has no ring-stiffened analysis at all. Its analysis types are tube, sphere, and flat annular, conical, hemispherical, and flat circular endcaps. The word "ring" occurs twice in the manual, both times about O-ring grooves |
| [DAPS4 SourceForge project](https://sourceforge.net/projects/daps4/) and [DAPS4e.6 release](https://sourceforge.net/projects/daps4/files/) | Release modified 2026-04-12; `Documentation/Primary/Gordon, Evolution of DAPS4.pdf`, `Gordon, Analysis of Ring-Frame Elastic Stability in DAPS4.pdf`, `Gordon, Comparisons of DAPS4 Predictions with Model Test Results.pdf`, `Renzi, IHTR 2944.pdf`; secondary Pulos-Salerno and Kendrick reports; `Source Code/Fortran/GFortran/DAPS4e.for`; DTMB 1255 BR-7M validation input/output | Contains source and derivation material for Pulos-Salerno-based ring-frame stress and Kendrick ring-frame instability, plus fixed validation artifacts. Sources and a comparison case therefore exist for both the ring strength and ring tripping modes, but the bundle has not yet been mapped independently to this repository's geometry and conventions |

The external PDFs are not vendored. The inspected file records, all retrieved
2026-07-30, are:

- DTMB 1497: SHA-256
  `10234c9a5d2651e603749782ae3fe93352af674d9a12da3cdd3c913e14795835`
- DTMB 1639: SHA-256
  `962dba65c94affbc83e92fbd0fd7bf0b12806aee99a5a88a18d67e7b7497d13c`
- DTMB 1255: SHA-256
  `c7f38a251cb8637b108894ee83082b46abb0ad678049648e236ee658ebbb0523`
- ABS January 2018 rules: SHA-256
  `ccd1b3a0056288ae8ad772bc7909059933e1a2bae9c18b2c0f5d89a604fc323f`
- NASA/SP-8007 Rev. 2 and the UnderPressure manual re-hashed to the values
  already recorded in the two existing source records.
- DAPS4e.6 release archive metadata reported by SourceForge: 356,498,034 bytes,
  MD5 `0faccf73e4ef749838dcc87652a137d4`; the full archive is not vendored.
- Extracted DAPS members, with SHA-256:
  - `Gordon, Evolution of DAPS4.pdf`:
    `3bade3e56c821879e96b1d0b54d334765ddec8bdbbf348511393769d5834ee6f`
  - `Gordon, Comparisons of DAPS4 Predictions with Model Test Results.pdf`:
    `0cc742239fa795cfabcd004cec70c159ab45b7d3d867b84066badbb4078de6d5`
  - `Gordon, Analysis of Ring-Frame Elastic Stability in DAPS4.pdf`:
    `ae980f136d7eb9d117e8bb9c7f6f07b79fef53cb20391ebbef67a17f39ed7f29`
  - `DAPS4e.for`:
    `ab25f070f5bcdad21071c0760be12b6161df8cd86297283cebbbc9f3529a8723`
  - uncompressed `BR-7M.txt` input, 358 bytes:
    `9453d085bde85104401a82f1c44106e843b36ce3ca5a724f7b467cd8d519bfd9`
  - uncompressed `BR-7M.out.txt` output, 4,539 bytes:
    `4b0ff80a8870c3d7961b632193d6ccdb62bec6f15e06b925fd4c5ad0ec69b8f3`

## What the ring model can and cannot supply

The one supported section is a solid rectangle of axial width `b` and radial
height `d`, sitting on the shell outside or inside surface without overlapping
it, so `A_f = b d`, the centroid is `d/2` from the shell surface, and
`R_cg = R +/- (h/2 + d/2)`. A request supplies `p`, the shell mid-surface radius
`R`, wall thickness `h`, ring center-to-center spacing, ring location, one
shared `E`, `nu`, and yield strength, and an optional proportional limit.

A request supplies no attachment route, weld profile or throat, heat-affected
zone properties, residual stress, fabrication tolerance, out-of-roundness
amplitude, or tripping-bracket spacing. Any criterion that needs one of those is
incomplete before its equations are even considered.

## `ring_material_strength_and_crippling`

### Strength half: axisymmetric frame stress

**Equations.** DTMB 1497 Eq. [56] (and Eq. [57] for equal roots) gives the total
radial load on a frame per unit circumferential length, and Eq. [58], restated
as DTMB 1639 Eq. (175), converts it to the circumferential stress at the frame
flange:

```text
Q* = E h^3 / (6 (1 - nu^2)) [B l1^3 sinh(l1 L/2) + F l3^3 sinh(l3 L/2)] - p b (1 - nu/2)

sigma_phi_f = Q* R^2 / [(A_eff + b h)(R + d + h/2)]     external frame
sigma_phi_f = Q* R^2 / [(A_eff + b h)(R - d - h/2)]     internal frame
```

DTMB 1497 gives `B` and `F` in Eq. [59], the non-dimensional parameters in
Eq. [60], and the stress functions `F1` through `F4` in Eqs. [72]-[75]; DTMB 1639
Eq. (21) gives the same `Q*` in a compact form in those parameters. The scanned
Eqs. [72]-[75] page is fully legible, so transcription is a reading task, not a
recovery task.

**Inputs.** `p`, `R`, `h`, frame spacing, faying width `b`, frame depth `d`,
`A_f`, `E`, `nu`, and a yield strength to compare against. All are available.

**Applicability boundaries.** DTMB 1497 states small deformations, with results
not likely reliable when any shell element's radial displacement exceeds the
shell thickness; a perfectly circular, initially stress-free structure; elastic
behaviour; and uniformly spaced identical ring frames. Its summary of formulas
covers case (1), which the report defines as an applied pressure less than the
one that would cause axisymmetric elastic buckling of an *unstiffened* shell of
the same dimensions; the other three cases are in Appendix B.

**Completeness for this rectangle.** Two of the three gaps in DTMB 1497 are
closed by DTMB 1639 and need not be guessed. First, DTMB 1497 offers
`A_eff = A_f (R/R_cg)` from its Eq. [18] and `A_eff = A_f (R/R_cg)^2` from its
Eq. [20], notes that the two frame-rigidity constants do not agree exactly, and
selects neither; DTMB 1639 Eq. (9) assigns the first form to internal and the
second to external framing. Second, DTMB 1497 Eq. [58] is written only with
`(R + d + h/2)`, an external frame; DTMB 1639 Eq. (175) supplies
`(R - d - h/2)` for an internal frame. The `(R + d + h/2)` radius is the tip of
the outstand, which for a solid rectangle is unambiguous, so the word "flange"
costs nothing here.

One gap remains open. DTMB 1497 states that Eq. [58] holds only for frames that
are "not too deep according to the same criterion which governs the use of
either Equation [20] or [21] for the frame stiffness K", and otherwise directs
the Lame thick-cylinder distribution "in place of [58]" without stating how to
apply it. The only numeric hook the report offers for that criterion is a
depth-to-shell-radius ratio greater than 0.2, and it is stated for deep frames
*with thin webs*. A solid rectangle has no web, so the report states no numeric
depth boundary for this section, and no gate can be written without choosing one.

**Comparison case.** DAPS4e.6 includes
`Validation Problems/DTMB Models/1255/Rev C/BR-7M.txt` and its fixed
`BR-7M.out.txt`. The input represents the machined, externally framed BR-7M at
1,500 psi: shell outside diameter 27.110 in, shell thickness 0.2110 in, ring
spacing 2.570 in, ring axial width 0.330 in, and ring radial height 1.225 in.
The output reports ring area 0.4043 in2, ring centroid radius 14.168 in,
circumferential ring stress -47,677 psi, and radial ring-centroid displacement
-0.0225 in. It also reports axisymmetric yield onset at 1,197 psi,
axisymmetric collapse at 1,450 psi, and ring-frame elastic instability at
70,060 psi in mode 15.

This is a real fixed software oracle, not yet a qualified repository benchmark.
The bundled output identifies itself as revision C.1 from 2018 even though it is
distributed in DAPS4e.6, and DAPS generalizes the original Pulos-Salerno theory.
Its input fields, effective shell/ring geometry, radius and sign conventions,
and current-source execution must therefore be mapped and reproduced
independently before any number is used as an acceptance test. UnderPressure
4.0 and the currently documented UnderPressure 4.60 product shapes still offer
no ring comparison.

### Crippling half: local buckling of the outstand

**Equation.** ABS 6/19.15.1(c) states, for flat bars and other outstands, a
single slenderness limit:

```text
width / thickness <= 0.3 sqrt(E / sigma_y)
```

**Inputs.** The outstand width and thickness, `E`, and yield strength. All are
available, and this is the one obtainable criterion whose own text names a flat
bar rather than a web-and-flange section.

**Applicability boundaries and completeness.** ABS 6/19.15 opens by requiring
that all stiffeners be attached to the shell by continuous welding, and
6/19.15.1(c) is about "a stiffener cross section welded to the shell". The
calculator takes no manufacturing route as an input, so that premise cannot
be asserted for the current geometry. The clause is also one item in a package
that fixes usage factors and an out-of-roundness allowance of `0.005R` that this
repository does not model, and taking it would be a decision to adopt a
classification-society route, which the shipped
`classification_inter_stiffener_strength` disposition records as not taken.

**Comparison case.** None. A proportion inequality has no published worked case;
verifying an implementation against it reduces to repeating its own arithmetic.

**Note for a later decision.** The shipped `web_and_flange_local_slenderness`
disposition is `not_applicable` because the supported rectangle has no separate
web or flange, which remains true. It is worth recording that ABS states a
separate flat-bar outstand limit that would apply to this section; that does not
change the shipped disposition, whose subject is web and flange slenderness.

## `frame_tripping_or_out_of_plane_rolling`

**Sources and equations.** NASA SP-8007 Rev. 2 requires stiffener buckling and
crippling to be investigated (printed p. 34) and points out-of-plane stiffener
rolling at discrete-stiffener analysis (printed pp. 44 and 62); it gives no
equation. ABS 6/19.15.1(b) gives a circumferential tripping stress

```text
sigma_T = E I_z / (A_s R z),   required to exceed the applicable yield stress
```

with `I_z`, `A_s`, and `z` defined in 6/19.3. DNV-RP-C202 [3.9] and [3.10.1]
have expressions labelled for flat bar ring stiffeners and flat bar ring frames.

**Inputs.** The ABS symbols map onto the rectangle without invention:
`A_s = b d`, `z = d/2`, and `R` is the shell mean radius. The DNV route
additionally needs the arc length between tripping brackets, which this geometry
does not define.

**Completeness for this rectangle.** Not complete. ABS scopes 6/19.15.1(b)
explicitly to *flanged* stiffeners, and 6/19.15 sends other geometries to
"special consideration", so the rule's own text does not authorise applying it
to an unflanged flat bar; `I_z`, "moment of inertia of stiffener alone about the
radial axis through the web", is defined for a section that has a web. The DNV
expressions cannot be transcribed at all from any obtainable copy, and their
bracket-spacing input does not exist here. The DAPS4e.6 bundle does make
Kendrick's report, a modern derivation, the implementing Fortran, and numerical
comparison tables obtainable, so source material for this mode is available. It
does not by itself establish that DAPS's ring-root boundary conditions, section
mapping, and applicability limits match this repository's supported solid
rectangle.

**Comparison case.** DAPS supplies Kendrick comparison tables and the BR-7M
ring-frame-instability output above. Their exact applicability to the supported
rectangle remains part of the open source mapping.

## `attachment_weld_and_fabrication_effects`

**Sources and equations.** NASA SP-8007 Rev. 2 printed p. 57 discusses weld
lands qualitatively and reports a large-scale compression result, not an
external-pressure rule. ABS requires continuous welding in 6/19.15 but states no
weld-behaviour equation there.

**Inputs.** Every candidate needs a weld profile or throat, heat-affected-zone
properties, residual stress, and a fabrication tolerance. The geometry supplies
none of them, and the manufacturing route is not selected.

**Completeness and comparison case.** Not complete, and no comparison case is
relevant while the inputs are absent. This mode is an external blocker on inputs
before it is one on sources.

## `local_global_interaction`

**Sources and equations.** NASA SP-8007 Rev. 2 printed p. 58 states that
interactions between failure modes are likely, that heavier rings than the
calculations indicate should therefore be used, and that the interactions should
be assessed by geometrically nonlinear analysis validated by suitable tests. It
gives no closed-form interaction rule. The published interaction formulations
combine per-mode strengths, including tripping and inelastic collapse, that this
repository does not compute, and they are in paywalled journals.

**Completeness and comparison case.** Not complete. An interaction rule cannot
precede the individual modes it interacts.

## Disposition and open work

No mode is selected. The four ring dispositions
`ring_material_strength_and_crippling`,
`frame_tripping_or_out_of_plane_rolling`,
`attachment_weld_and_fabrication_effects`, and `local_global_interaction` remain
`external_blocker`, unchanged.

The axisymmetric frame stress of DTMB 1497 and 1639 remains the closest strength
candidate. DAPS changes the next step from an open-ended source search to a
bounded source mapping, in this order:

1. map every BR-7M input and output convention to the DTMB reports and this
   repository's solid rectangular ring, then reproduce the fixed DAPS output
   with the distributed current source or document why that cannot be done;
2. determine from the bundled primary/derivation material whether the
   solid-frame depth applicability boundary is actually supplied or whether
   DAPS merely chooses an internal convention outside the DTMB statement;
3. separately map the Kendrick ring-frame-instability formulation, boundary
   condition, section properties, and required imperfection inputs to the
   supported geometry; and
4. make a new implementation decision only after those records exist, using an
   independent implementation and the fixed artifacts as tests rather than
   copying DAPS into `pv-calc`.

Until that mapping is complete, selecting a ring strength or tripping check
would still put an insufficiently mapped result into a released interface. The
four blocker dispositions stand. Sources for the ring strength and ring tripping
modes do exist, in the DAPS4 bundle above; they are not yet mapped.
