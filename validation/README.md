# Validation

This directory holds the independent reference implementations, published
benchmark comparisons, FEA records, source records, and the evidence matrix
for every released model. The [engineering notes](../docs/engineering.md)
describe the validation approach. This page summarizes the ring-shell
evidence, which is the most involved.

## Ring-shell evidence

The ring calculation is `benchmark_compared`, `partial`, and advisory. Each
item below states what it establishes and where it stops.

| Evidence | Establishes | Limit |
|---|---|---|
| [Independent NASA transcription](ring_shell_reference.py) | Pressure, section-property, and mode parity for the checked inputs | Both searches cover `m>=1,n>=2`; agreement cannot detect a shared source interpretation |
| [DTMB 1324 Table 2](published/dtmb_1324_case17.md) | Comparison with cylinder 4-A at ten bulkhead spacings, with the lobe-transition discrepancy retained | Southwell estimates; the bulkhead supports approximate simple support, with rotational restraint from the continuing shell |
| [DTMB 1324 Table 1 closures](sources/ring_boundary_and_nasa_evidence.md) | Closure stiffness changes the same specimen's pressure by 21–65% and sometimes its mode | Spans are reconstructed from the report's rounded `L/D`; the 2-A length is unresolved |
| [DAPS4 cross-check](ring_shell_investigation.md) | Sixteen archived ideal-support global results reproduced; the simply supported and clamped DAPS4 curves bracket the Table 2 estimates | Different theory; the intermediate-restraint probes did not reproduce the archived outputs |
| [Saved ring FEA](fea/README.md) | Mesh convergence of the CalculiX eigenvalues | The `*BUCKLE` procedure omits pressure-load stiffness, so the eigenvalues do not validate hydrostatic buckling |
| [NASA experimental references](sources/ring_boundary_and_nasa_evidence.md#what-nasa-actually-cites-as-experimental-support) | SP-8007 cites pressure experiments in references 188–191 for Eq. 64 | Those datasets have not been reproduced here |

The 0.75 multiplier is NASA's published recommendation, applied once. No
support factor, effective length, or tolerance was chosen to improve
agreement, and the ideal and adjusted pressures are always shown separately.

## What ring model 4.1.0 reports

- `mode_domain: "m>=1,n>=2"` on each global result; `converged` refers to
  that domain.
- `boundary_assumptions`: radially restrained, freely rotating global ends
  under closed-end pressure, and ideal circular inter-ring supports.
- `mode_dispositions` includes `axisymmetric_hydrostatic_buckling` as
  `not_implemented` and `physical_end_restraint` as `external_blocker`.
- `advisory_governing_pressure_mpa` is the minimum over the available modes
  and `advisory_margin` its pressure ratio minus one. Neither can pass `check`.

The `n=0` diagnostic lives in the validation code only. For the DTMB
geometries it is more than five times the lobar pressure, and adding the
smeared branch to the candidate list would not by itself establish
discrete-ring applicability at short axial wavelengths. A regression test
with a lower `n=0` pressure checks that the assessment stays indeterminate.

## Next steps for the ring model

1. Obtain a source-complete experimental set with known supports. Galletly,
   Slankard and Wenk (1958), NASA reference 188, and Yamamoto et al. (1989),
   reference 189, are the first targets.
2. Qualify a pressure-buckling FEA procedure that includes pressure-load
   stiffness against a published ring benchmark before running more cylinder
   cases.
3. Compare the lobar and axisymmetric branches against discrete-ring models,
   including axial wavelengths near the ring spacing, and settle the
   long-cylinder treatment.
4. Ring strength and tripping, attachment, imperfections, material
   nonlinearity, and local/global interaction remain separate work before any
   housing-collapse claim.

## Reproduction

```console
uv run pytest
uv run python validation/published/dtmb_1324_case17.py
uv run python validation/dtmb_end_closure_investigation.py --output validation/results/dtmb_end_closure_investigation.json
uv run --with matplotlib python validation/ring_shell_investigation.py --output validation/results/ring_shell_investigation.json --plot validation/figures/ring_shell_dtmb_investigation.svg
```

The DAPS4 cross-check needs the external release and GFortran; see the
[investigation](ring_shell_investigation.md#reproduction-and-source-provenance).
