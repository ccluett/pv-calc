# UnderPressure Example 2: Simply-Supported Flat Circular Plate

- **Role:** Independent equation-verification case for the pv-calc flat circular plate result
- **Source:** DeepSea Power & Light, *Under Pressure Version 4.0 User Manual*, Example 2, pp. 18-21; Appendix B; Appendix C, Roark Table 24 case 10a (simply supported) and case 10b (fixed)
- **Source URL:** [DeepSea Power & Light manual PDF](https://www.deepsea.com/wp-content/uploads/2021/06/UnderPressure_Manual.pdf)
- **Validation meaning:** Software/equation traceability only

## Inputs and convention

| Quantity | Value |
|---|---:|
| Boundary condition | simply supported |
| Applied pressure | 4.500 ksi |
| Plate free diameter | 6.000 in |
| Plate free radius | 3.000 in |
| Plate thickness | 1.280 in |
| 7075-T6 yield strength | 62.000 ksi |
| 7075-T6 elastic modulus | 10.3 Mpsi |
| Poisson ratio | 0.33 |

The manual defines the free diameter as the unsupported diameter and describes a simply-supported edge as preventing transverse deflection while permitting radial rotation and displacement.

## Traced response equations

With free radius `a`, thickness `t`, pressure `p`, elastic modulus `E`, Poisson ratio `nu`, and plate rigidity `D = E t^3 / [12(1 - nu^2)]`:

```text
Simply supported (Roark Table 24 case 10a):
  sigma_r,max = sigma_theta,max = [3(3 + nu)/8] p (a/t)^2, at center
  w_max = [p a^4/(64 D)] [(5 + nu)/(1 + nu)], at center

Fixed (Roark Table 24 case 10b):
  sigma_r,max = (3/4) p (a/t)^2, at the plate free diameter/support boundary
  sigma_theta,max = [3(1 + nu)/8] p (a/t)^2, at center
  w_max = p a^4/(64 D), at center

Both boundaries (UnderPressure Example 2 shear convention):
  tau_max = p D_free/(4t), at the plate free diameter/support boundary
```

## Independent calculation

For a uniformly loaded simply-supported circular plate, the maximum radial and tangential surface bending stresses are equal at the plate center:

```text
sigma_max = [3(3 + nu)/8] p (a/t)^2

p_failure = S_y / ([3(3 + nu)/8] (a/t)^2)
          = 62 ksi / ([3(3 + 0.33)/8] (3.000/1.280)^2)
          = 9.038442887 ksi
          = 9.0384 ksi to four decimal places
```

The UnderPressure manual reports 9,038 psi at its displayed precision. The committed test uses the independently calculated 9.0384 ksi value and does not obtain the expected result from pv-calc production code.

## Additional source checks

UnderPressure Appendix E gives a 5.00 in free-diameter, 0.625 in thick plate at 1,000 psi and `nu = 0.30`. It reports 19,800 psi radial and tangential stress for the simply-supported edge, and 12,000 psi radial plus 7,800 psi tangential stress for the fixed edge. Both cases are asserted in the plate tests.

## Seat bearing stress

The manual's plate outside diameter is 6.94 in, the Example 1 tube O.D., and it reports seat failure at 15,658 psi (printed p. 21). The manual defines the average seat stress as the bearing stress on the annular area between the plate outside diameter and the free diameter (printed p. 69) and compares it to yield strength (Appendix C criterion N):

```text
sigma_seat = p D_o^2 / (D_o^2 - D_free^2)
           = 4.5 ksi * 6.94^2 / (6.94^2 - 6.00^2) = 17.818 ksi

p_seat_failure = S_y (D_o^2 - D_free^2) / D_o^2
               = 62 ksi * (6.94^2 - 6.00^2) / 6.94^2 = 15.658 ksi
```

The manual also notes that this seat stress equals the axial stress in the Example 1 tube, which the closed-end Lamé axial stress `p R_o^2 / (R_o^2 - R_i^2)` on the same radii confirms. The plate model releases the seat values only when an outside radius is supplied; they are thickness-independent and enter no bending margin. Bearing-contact distribution across the annulus is not modeled.
