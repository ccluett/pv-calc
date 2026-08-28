"""Conventions the kernels state in their signatures and results."""

from __future__ import annotations

from typing import Literal


StressStateRadiusConvention = Literal["internal", "external", "mean"]
PressureLoadCase = Literal["lateral_only", "hydrostatic_closed_end"]
TubeEndCondition = Literal["closed"]
PlateBoundaryCondition = Literal["fixed", "simply_supported"]
StressSignConvention = Literal["tension_positive"]
PrincipalStressOrdering = Literal["descending_algebraic"]

# The material behavior a stress result assumes: a ductile metal yields, so
# its von Mises or surface bending stress is compared to the yield strength; a
# plastic is governed by a designer-selected working strength that carries
# creep and temperature; a brittle material has separate ultimate tensile and
# compressive strengths and no yield.
MaterialFailureCategory = Literal["ductile_metal", "plastic", "brittle"]

# Which stress each category compares to which strength, as the shell (tube and
# hemisphere) and plate results report it.
ShellFailureCriterion = Literal[
    "von_mises_stress_vs_yield_strength",
    "maximum_hoop_stress_vs_working_strength",
    "maximum_hoop_stress_vs_ultimate_compressive_strength",
]
PlateFailureCriterion = Literal[
    "surface_bending_stress_vs_yield_strength",
    "surface_bending_stress_vs_working_strength",
    "surface_bending_stress_vs_ultimate_tensile_strength",
]
