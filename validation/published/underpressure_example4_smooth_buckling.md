# UnderPressure Example 4 smooth-cylinder buckling comparison

This record compares the NASA smooth-cylinder kernel with a published,
valid-thin-tube UnderPressure/Roark case.

## Primary references

- NASA/SP-8007-2020/REV 2, Eqs. 17-29:
  <https://ntrs.nasa.gov/api/citations/20205011530/downloads/20205011530%20Rev%202FINALa%201-2023.pdf>
- Under Pressure Version 4.0 User Manual, Example 4, printed pp. 27-33
  (material and final geometry/result screenshots on PDF pp. 31 and 35):
  <https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf>
- Roark's Formulas for Stress and Strain, 6th ed., Table 35 case 20, cited by
  UnderPressure Appendix C. The equivalent current-edition expression appears
  in the 7th ed., Table 15.2 case 20a, p. 736.

## Published case

- Material: Acetal, `E = 0.41 Mpsi`, `nu = 0.4`
- Tube ID: `5.000 in`
- Wall: `0.240 in`
- Supported length: `10.000 in`
- Mean radius: `2.620 in`
- Mean-radius/thickness: `10.9167`, above UnderPressure's `> 10` warning limit
- Displayed thin-wall buckling: `266.60 psi`, three circumferential nodes

An independent transcription of Roark case 20 gives `333.2478203 psi` ideal at
three nodes and `266.5982562 psi` after Roark's recommended `0.80` probable-
minimum factor, reproducing the displayed result to its precision.

For the same mid-surface geometry, the NASA kernel gives `Z = 145.7562244`.
The printed Eq. 24 coefficient `0.855` gives `265.8377633 psi` with `gamma = 1`,
0.286% below the UnderPressure display. NASA's Eq. 28 moderate correlation gives
`199.3783225 psi`. Because `0.5625 Z <= 100`, the production kernel classifies
this point in the `short` regime, where Eqs. 20/22 carry that same factor. It
still releases neither capacity nor margin, but only because Acetal has no
proportional limit: the status is `withheld_applicability`.

The production kernel now reports the same Roark case-20 probable minimum as
`roark_probable_minimum_pressure_mpa` with its lobe count, a software-parity
candidate that sets no capacity. Beyond this example, the same fields
reproduce the manual's three other displayed Thin Wall Buckling values,
none of which is a valid thin tube: Example 1 at 81,941 psi (6061-T6) and
10,632 psi (7075-T6), both by 2 nodes (printed pp. 16-17), and the PVC report
sample at 2,498.4 psi by 2 nodes (printed p. 76).

The committed fixture
`tests/fixtures/software_parity/underpressure_example4_tube_buckling.yaml` and
`tests/test_smooth_cylinder_buckling.py` preserve the source inputs, independent
Roark result, NASA candidates, validity classification, and displayed precision.
The same test module also checks a valid `r/t = 20` Roark case-20 matrix spanning
short, moderate, factor-overlap, and unambiguous long geometries.

## Remaining external comparison

This record does not claim an UnderPressure 4.60 GUI result. Producing a
version-stamped 4.60 capture would require a manual GUI run.
