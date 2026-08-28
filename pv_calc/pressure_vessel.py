from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, Literal, get_args

from pv_calc.ring_section import rectangular_ring_section_properties
from pv_calc.schemas import (
    MaterialFailureCategory,
    PlateBoundaryCondition,
    PlateFailureCriterion,
    PrincipalStressOrdering,
    PressureLoadCase,
    ShellFailureCriterion,
    StressSignConvention,
    StressStateRadiusConvention,
    TubeEndCondition,
)


MATERIAL_FAILURE_SOURCE = (
    "Standard failure criteria by material class: a ductile metal compares the von Mises "
    "distortion-energy stress (shells) or the surface bending stress (plates) to the yield "
    "strength; a plastic compares the maximum hoop stress (shells) or the surface bending "
    "stress (plates) to the designer-selected working strength; a brittle material has no "
    "yield and separate ultimate strengths, so it compares the maximum hoop stress under "
    "external pressure to the ultimate compressive strength (shells) and the surface bending "
    "stress to the ultimate tensile strength (plates)"
)
SHELL_FAILURE_CRITERION: dict[MaterialFailureCategory, ShellFailureCriterion] = {
    "ductile_metal": "von_mises_stress_vs_yield_strength",
    "plastic": "maximum_hoop_stress_vs_working_strength",
    "brittle": "maximum_hoop_stress_vs_ultimate_compressive_strength",
}
PLATE_FAILURE_CRITERION: dict[MaterialFailureCategory, PlateFailureCriterion] = {
    "ductile_metal": "surface_bending_stress_vs_yield_strength",
    "plastic": "surface_bending_stress_vs_working_strength",
    "brittle": "surface_bending_stress_vs_ultimate_tensile_strength",
}
# Neither category is read against a yield strength, so what the margin is
# actually taken against travels with every result that carries one.
PLASTIC_NOTE = (
    "Plastic strength depends on service temperature and load duration (creep); the working "
    "strength is the designer's allowance for both, and the margin is against that allowance."
)
SHELL_CATEGORY_NOTES: dict[MaterialFailureCategory, tuple[str, ...]] = {
    "ductile_metal": (),
    "plastic": (PLASTIC_NOTE,),
    "brittle": (
        "Brittle materials are intended for compression; under external pressure the shell "
        "hoop stress is compressive and is compared to the ultimate compressive strength.",
    ),
}
PLATE_CATEGORY_NOTES: dict[MaterialFailureCategory, tuple[str, ...]] = {
    "ductile_metal": (),
    "plastic": (PLASTIC_NOTE,),
    "brittle": (
        "Brittle materials are intended for compression, but the convex face of a "
        "pressure-loaded plate is in tension, so the surface bending stress is compared to the "
        "ultimate tensile strength; the seat is compressive and is compared to the ultimate "
        "compressive strength.",
    ),
}


FLAT_CIRCULAR_PLATE_SOURCE = (
    "Roark's Formulas for Stress and Strain, 6th ed., Table 24 cases 10a-10b, p. 429; "
    "transverse shear is the average on the support perimeter from equilibrium, "
    "tau = p * D_free / (4 * t), the pressure load over the free area divided by the "
    "cylindrical area pi * D_free * t it crosses; the small-deflection gate's shear-corrected "
    "deflection estimate uses kappa = 5/6 from Reissner, J. Appl. Mech. 12 (1945) A69-A77"
)
SEAT_BEARING_STRESS_SOURCE = (
    "Equilibrium on the flat annular seat: the total pressure load on the closure's outside "
    "radius, p * pi * R_o^2, is carried by the annulus area pi * (R_o^2 - R_i^2) inside it, "
    "so the average bearing stress is sigma_seat = p * R_o^2 / (R_o^2 - R_i^2), compared to "
    "the material's uniaxial strength"
)


TUBE_STRESS_MODEL_ID = "closed_end_tube_stress"
TUBE_STRESS_MODEL_VERSION = "2.0.0"
TUBE_THIN_WALL_MEAN_RADIUS_RATIO = 10.0
TUBE_THIN_SOURCE = "Roark's Formulas for Stress and Strain, 6th ed., Table 28 case 1c"
TUBE_THICK_SOURCE = (
    "Lamé closed-end thick-cylinder stresses from Roark's Formulas for Stress and Strain, "
    "6th ed., Table 32 cases 1a-1d"
)
TUBE_THIN_DISPLACEMENT_SOURCE = (
    "DTMB Report 1497 (Pulos and Salerno, 1961), Eq. [5], printed p. 2, for the "
    "median-surface radial displacement of a long unstiffened shell under external "
    "hydrostatic pressure, with Eqs. [A7]-[A10] and the stated N_x = -p*R/2, printed "
    "p. 43, for the axial strain"
)
TUBE_THICK_DISPLACEMENT_SOURCE = (
    "Boresi and Schmidt, Advanced Mechanics of Materials, 6th ed., 2003, Eq. (11.24), "
    "printed p. 396, for the closed-cylinder radial displacement and Eq. (11.15), printed "
    "p. 394, for the closed-cylinder axial strain, both at sections far from the end-cap "
    "junction"
)
TUBE_DISPLACEMENT_MISSING_MODULUS = (
    "elastic_modulus_mpa is required to calculate radial displacement and axial strain"
)
TUBE_DISPLACEMENT_MISSING_POISSON = (
    "poisson_ratio is required to calculate radial displacement and axial strain"
)
TUBE_DISPLACEMENT_EXCEEDS_THICKNESS = (
    "absolute radial displacement exceeds wall_thickness_mm; DTMB 1497 states its "
    "thin-shell results are not likely reliable beyond that limit"
)
TUBE_SCOPE_NOTES = (
    "Closed ends transmit uniform external-pressure axial load.",
    "Results apply away from the tube/endcap interface.",
    "Compression is negative and tension is positive.",
    "The documented branch switch is discrete: at mean-radius/thickness = 10, the thick-wall "
    "equivalent stress is 10.25% above the thin-wall limiting value.",
    "This result covers material failure under the category's own criterion: von Mises stress "
    "against yield strength for a ductile metal, maximum hoop stress against the working strength "
    "for a plastic or the ultimate compressive strength for a brittle material. Shell stability "
    "and end closures are separate checks.",
    "Radial displacement and axial strain need an elastic modulus and a Poisson ratio; without "
    "both, every stress result is unchanged and displacement is withheld with its reason.",
    "Radial displacement is positive outward, so external pressure gives a negative value, and "
    "each stress state carries the displacement at its own radius: the median surface on the "
    "thin branch, the internal and external surfaces on the thick branch.",
    "Axial strain is uniform through the wall and along the tube in both branches; the axial "
    "length change is that strain times the caller's gauge length, which is null when no length "
    "is supplied.",
    "Displacement excludes tube/endcap junction effects, local restraint at closures, "
    "ovalization and initial out-of-roundness, instability, plasticity, and ring-frame restraint.",
    "The displacement equations assume small deformations. On the thin branch, displacement is "
    "withheld when its absolute radial value exceeds the wall thickness, the explicit reliability "
    "limit stated by DTMB 1497; no unsourced counterpart is imposed on the thick branch.",
)

HEMISPHERE_MODEL_ID = "roark_nasa_hemispherical_head_external_pressure"
HEMISPHERE_MODEL_VERSION = "3.0.0"
HEMISPHERE_THIN_WALL_MEAN_RADIUS_RATIO = 10.0
HEMISPHERE_NASA_MINIMUM_LAMBDA = 2.0
HEMISPHERE_ROARK_PROBABLE_MINIMUM_COEFFICIENT = 0.365
HEMISPHERE_THIN_STRESS_SOURCE = (
    "Roark's Formulas for Stress and Strain, 6th ed., Table 28 case 3a, p. 523"
)
HEMISPHERE_THICK_STRESS_SOURCE = (
    "Roark's Formulas for Stress and Strain, 6th ed., Table 32 cases 2a-2b, p. 640"
)
HEMISPHERE_BUCKLING_SOURCE = (
    "NASA SP-8032, Buckling of Thin-Walled Doubly Curved Shells, sec. 4.2.1.1, "
    "Eqs. 1-4, pp. 4-6"
)
HEMISPHERE_SOFTWARE_PARITY_SOURCE = (
    "Roark's Formulas for Stress and Strain, 6th ed., Table 35 case 22, p. 691, the table's "
    "probable-minimum external pressure for a thin spherical shell"
)
HEMISPHERE_MEMBRANE_DISPLACEMENT_SOURCE = (
    "NASA Technical Memorandum 4579 (W. L. Ko, 1994), Eq. (5), printed p. 6, which states "
    "the spherical-shell membrane stress sigma_theta = sigma_phi = p*R/(2*t) and the radial "
    "displacement p*R^2*(1 - nu)/(2*E*t) in one equation and applies both to the "
    "hemispherical bulkheads of the analyzed vessel, citing Timoshenko and "
    "Woinowsky-Krieger, Theory of Plates and Shells, 1959, pp. 481-485"
)
HEMISPHERE_DISPLACEMENT_MISSING_THICK_SOURCE = (
    "the released displacement equation is a thin-shell membrane result; no consulted "
    "primary source states a radial displacement for the thick-sphere branch, and none is "
    "derived here"
)
HEMISPHERE_SCOPE_NOTES = (
    "Uniform external pressure acts on a constant-thickness isotropic hemispherical head.",
    "The radius input is internal; thin stress and both buckling comparisons use the shell mean radius.",
    "The NASA SP-8032 result assumes a clamped equator and a 180-degree included spherical cap.",
    "The SP-8032 correlation is the source's lower bound to clamped-cap test data.",
    "The release gate adopts mean-radius/thickness > 10 from the conventional thin-shell "
    "domain Roark states; NASA SP-8032 does not state that numeric cutoff.",
    "Elastic buckling capacity requires a proportional limit at or above the NASA-correlated "
    "critical membrane stress; no inelastic correction is implemented.",
    "The Roark probable-minimum pressure is reported only as a published comparator and does "
    "not set released capacity.",
    "The seat bearing stress is the average over the flat equator annulus between the internal "
    "and external radii, reported as a positive compressive magnitude with its own failure "
    "pressure and margin; it does not enter the shell stress margin.",
    "Radial displacement is released on the thin branch only, at that branch's own median-surface "
    "radius, and is positive outward, so external pressure gives a negative value.",
    "The source states that displacement in the same equation as the membrane stress reported "
    "here, so it carries that stress's idealization and no further assumption; the clamped "
    "equator belongs to the buckling correlation and not to either of them.",
    "The displacement holds away from the equator. A restrained equator suppresses it locally, so "
    "the released value is not the equator's radial closure and not a seal-gap estimate.",
    "The thick-sphere branch withholds displacement with its reason. Displacement fields, junction "
    "analysis, post-buckling deformation, and ring-stiffened service displacement are outside "
    "this result.",
)

FLAT_CIRCULAR_PLATE_MODEL_ID = "uniformly_loaded_flat_circular_plate"
FLAT_CIRCULAR_PLATE_MODEL_VERSION = "3.0.0"

FLAT_CIRCULAR_PLATE_ENVELOPE_SOURCE = (
    "validation/fea/results/plate_sweep_fea_summary.json: "
    "mesh-converged CAX8R comparison swept over D_free/t and Poisson ratio, "
    "released against the 5% agreement budget"
)

# Each floor is the coarsest *solved* free-diameter/thickness ratio from which
# every thinner solved ratio holds the mesh-converged three-dimensional
# comparison inside the 5% budget, at every solved Poisson value in the
# evidence band.  Floors sit on solved ratios; releasing the continuous range
# above a floor relies on the monotone decrease of the model-form error with
# thinness that the seven solved ratios demonstrate.  Bending stress and
# center deflection diverge from Kirchhoff at very different rates, so they
# carry separate floors: at D_free/t = 4 the solved result exceeds a
# simply-supported plate's Kirchhoff center stress by at most 2.4% across the
# band, but exceeds its Kirchhoff center deflection by up to 24.3%.  The
# fixed-edge margin is governed by the edge radial stress, compared through
# its convergent reaction-moment resultant — the one compared quantity
# Kirchhoff over-predicts, so the governing comparison errs conservative at
# the floor.  The fixed bending floor is set by the also-published center
# stress; the fixed deflection floor is the stricter because transverse shear
# is a larger fraction of a clamped plate's smaller deflection.
FLAT_CIRCULAR_PLATE_BENDING_MINIMUM_RATIO: dict[str, float] = {
    "fixed": 10.0,
    "simply_supported": 4.0,
}
FLAT_CIRCULAR_PLATE_DEFLECTION_MINIMUM_RATIO: dict[str, float] = {
    "fixed": 20.0,
    "simply_supported": 10.0,
}
# The sweep solved Poisson ratios 0.05, 0.30, and 0.35, and every floor above
# holds at all three.  Releasing the band interior is the judgment that a
# smooth error surface stays bounded by the three solved values, not proven
# monotonicity; outside the band nothing is solved at all.
FLAT_CIRCULAR_PLATE_POISSON_EVIDENCE_BAND: tuple[float, float] = (0.05, 0.35)

# The w <= t/2 small-deflection limit bounds the plate's actual deflection, so
# the gate cannot read the Kirchhoff value the same sweep shows is low by up
# to 24.3% at the thick end.  It reads a first-order shear-corrected estimate
# instead: axisymmetric equilibrium fixes the transverse shear resultant at
# Q = p*r/2 whatever the edge does, so integrating Q/(kappa*G*t) in from the
# edge adds p*a^2/(4*kappa*G*t) at the center, with kappa = 5/6 from
# E. Reissner, "The effect of transverse shear deformation on the bending of
# elastic plates," J. Appl. Mech. 12 (1945) A69-A77.  The correction factor
# is conventional, not exact: the optimal value depends on the boundary
# realization, which is why the estimate is checked against solved evidence
# rather than trusted.  The sweep found the estimate above the solved
# three-dimensional deflection at every case, for both edges, and again at
# the deep-mesh sensitivity points — including the thinnest, low-Poisson
# corner, where the margin is smallest (about +0.005% at the deepest mesh)
# and a deep mesh could most plausibly have overturned it.  Between solved
# points, and beyond D_free/t = 40 (production sets no upper ratio limit),
# the gate relies on that margin persisting; with the shear increment and
# the Kirchhoff error both vanishing with thinness, that is an engineering
# judgment, not a measured bound.  Only applicability reads the estimate;
# the released deflection stays Kirchhoff.
FLAT_CIRCULAR_PLATE_SHEAR_CORRECTION_FACTOR = 5.0 / 6.0

FLAT_CIRCULAR_PLATE_SCOPE_NOTES = (
    "The free radius is half the plate free/unsupported diameter at the support or seal line.",
    "Maximum radial and tangential values are absolute surface bending-stress magnitudes; the "
    "opposite plate surfaces carry equal tensile and compressive magnitudes in linear plate theory.",
    "Transverse shear is the average on the support perimeter, tau = p * D_free / (4 * t), "
    "at the free-diameter support boundary.",
    "Transverse shear is reported as plate response and does not replace the existing bending/yield gate.",
    "With an outside radius, the seat bearing stress is the average over the annulus between the "
    "free and outside radii, reported as a positive compressive magnitude with its own failure "
    "pressure and margin; it is independent of thickness and does not enter the bending margin.",
    "Bearing-contact distribution, attachment, seal compression, penetrations, and local edge "
    "details are not evaluated.",
    "Kirchhoff theory omits transverse-shear deformation, so the center deflection is released "
    "on its own measured floor and is withheld before the bending/yield gate closes.",
    "The w <= t/2 small-deflection limit is applied to a shear-corrected deflection estimate "
    "(Reissner kappa = 5/6), because the released Kirchhoff deflection is measurably below "
    "the three-dimensional value. The swept evidence found the estimate above the solved "
    "deflection at every solved case; between solved points, and beyond D_free/t = 40, that "
    "margin persisting is engineering judgment, not a bound.",
    "The validity floors are evidenced for 0.05 <= poisson_ratio <= 0.35; outside that band "
    "both the bending margin and the deflection are withheld.",
)

SMOOTH_CYLINDER_BUCKLING_MODEL_ID = "nasa_smooth_cylinder_external_pressure_buckling"
SMOOTH_CYLINDER_BUCKLING_MODEL_VERSION = "3.0.0"
SMOOTH_CYLINDER_BUCKLING_SOURCE = (
    "NASA/SP-8007-2020/REV 2, Eqs. 3-5 and 17-29, pp. 22 and 26-29"
)
SMOOTH_CYLINDER_ROARK_OVERLAP_SOURCE = (
    "Roark's Formulas for Stress and Strain, 6th ed., Table 35 case 20, its theoretical "
    "pressure minimized over integer lobe counts and reduced by the table's 0.80 "
    "probable-minimum factor"
)
SMOOTH_CYLINDER_ROARK_PROBABLE_MINIMUM_FACTOR = 0.8
SMOOTH_CYLINDER_MODERATE_GAMMA = 0.75**2
SMOOTH_CYLINDER_LONG_GAMMA = 0.90
SMOOTH_CYLINDER_SHORT_GAMMA_Z_LIMIT = 100.0
SMOOTH_CYLINDER_MORE_THAN_TWO_WAVE_COEFFICIENT = 11.8
SMOOTH_CYLINDER_MIN_RADIUS_THICKNESS_RATIO = 10.0
SMOOTH_CYLINDER_PLASTICITY_PENDING_REASON = (
    "correlated critical circumferential membrane stress {stress:.6g} MPa exceeds the "
    "supplied proportional limit {limit:.6g} MPa; NASA inelastic corrections are not "
    "implemented, so this capacity is an elastic upper bound pending validation"
)
SMOOTH_CYLINDER_SCOPE_NOTES = (
    "The NASA equations assume a thin, circular, isotropic, unstiffened shell with uniform "
    "thickness, elastic response, membrane prebuckling, and simply supported ends.",
    "Radius is the shell mid-surface radius; callers starting from an internal radius must add "
    "one-half the wall thickness.",
    "Lateral pressure acts on the curved wall only. Hydrostatic pressure also acts on closed "
    "ends and produces axial line load p*r/2.",
    "Circumferential and axial line loads are reported as positive compression magnitudes.",
    "Longitudinal end restraint can increase theoretical capacity, and rotational restraint can "
    "affect short cylinders; those boundary-condition sensitivities are not credited.",
    "NASA Eq. 28 states sqrt(gamma)=0.75 for Eqs. 23-25; because the source adds the gamma^2 "
    "term to Eqs. 20/22 and introduces Eq. 23 as their gamma*Z > 100 reduction, this model "
    "applies the same factor inside Eqs. 20/22 at every gamma*Z. gamma=0.90 belongs to Eqs. "
    "26-27; the moderate/long overlap created by the two factors has no selection rule and "
    "stays withheld from capacity.",
    "The release gate adopts mean-radius/thickness > 10 from the conventional thin-tube "
    "domain Roark states; NASA does not state that numeric cutoff.",
    "Inelastic corrections in NASA Eqs. 30-32 are outside this model: they need secant and "
    "tangent moduli this model does not carry. The source calls plasticity factors for the "
    "biaxial hydrostatic state unavailable and directs that Eqs. 30-32 may be used for lack "
    "of better information; without those moduli, a correlated critical membrane stress above "
    "the proportional limit is an elastic upper bound reported as released_pending_plasticity, "
    "not a capacity.",
    "Moderate-regime beta and continuous wave count are Eq. 20/22 mode diagnostics; the released "
    "capacity follows the printed 0.855 coefficient in Eq. 24.",
    "The Roark probable-minimum pressure and its lobe count are reported only as a published "
    "comparator at the mid-surface radius and set no released capacity or margin. It does not "
    "reduce to the classical long-tube E*t^3/(4*R^3*(1-nu^2)), of which it is 4/3 at long "
    "length: it is Roark's own probable-minimum value, not a capacity.",
    "elastic_applicability compares the applied working membrane stress p*r/t with the same limit "
    "the plasticity check applies to the correlated critical stress. 'exceeded' means every "
    "capacity at or above the applied pressure exceeds that limit too, at every unsupported "
    "length, because only wall thickness moves this stress: with a proportional limit supplied "
    "such a capacity is an elastic upper bound reported as released_pending_plasticity, and with "
    "only a yield strength it is withheld for the missing limit. It is a screen on "
    "applicability, not a capacity or a margin.",
)


@dataclass(frozen=True)
class TubeStressState:
    radius_mm: float
    radius_convention: StressStateRadiusConvention
    radial_stress_mpa: float
    hoop_stress_mpa: float
    axial_stress_mpa: float
    principal_stresses_mpa: tuple[float, float, float]
    von_mises_stress_mpa: float
    radial_displacement_mm: float | None


@dataclass(frozen=True)
class TubeStressResult:
    model_id: str
    model_version: str
    source_reference: str
    displacement_source_reference: str
    material_failure_category: MaterialFailureCategory
    failure_criterion: ShellFailureCriterion
    load_case: PressureLoadCase
    end_condition: TubeEndCondition
    stress_sign_convention: StressSignConvention
    principal_stress_ordering: PrincipalStressOrdering
    branch: Literal["thin", "thick"]
    force_thick: bool
    thin_wall_threshold_mean_radius_over_thickness: float
    internal_radius_mm: float
    external_radius_mm: float
    mean_radius_mm: float
    wall_thickness_mm: float
    mean_radius_over_thickness: float
    external_pressure_mpa: float
    strength_mpa: float
    elastic_modulus_mpa: float | None
    poisson_ratio: float | None
    axial_length_mm: float | None
    stress_states: tuple[TubeStressState, ...]
    governing_radius_mm: float
    governing_stress_mpa: float
    theoretical_failure_pressure_mpa: float
    margin: float
    displacement_status: Literal[
        "released",
        "withheld_missing_elastic_properties",
        "withheld_applicability",
    ]
    displacement_validity_violations: tuple[str, ...]
    axial_strain: float | None
    axial_length_change_mm: float | None
    validity_violations: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class HemisphereStressState:
    radius_mm: float
    radius_convention: StressStateRadiusConvention
    radial_stress_mpa: float
    meridional_stress_mpa: float
    hoop_stress_mpa: float
    principal_stresses_mpa: tuple[float, float, float]
    von_mises_stress_mpa: float
    radial_displacement_mm: float | None


@dataclass(frozen=True)
class HemisphereResult:
    model_id: str
    model_version: str
    stress_source_reference: str
    buckling_source_reference: str
    software_parity_source_reference: str
    displacement_source_reference: str | None
    seat_source_reference: str
    material_failure_category: MaterialFailureCategory
    failure_criterion: ShellFailureCriterion
    load_case: Literal["uniform_external_pressure"]
    buckling_boundary_condition: Literal["clamped_equator"]
    radius_convention: Literal["internal_input_mean_surface_analysis"]
    stress_sign_convention: StressSignConvention
    principal_stress_ordering: PrincipalStressOrdering
    branch: Literal["thin", "thick"]
    force_thick: bool
    thin_wall_threshold_mean_radius_over_thickness: float
    internal_radius_mm: float
    external_radius_mm: float
    mean_radius_mm: float
    wall_thickness_mm: float
    mean_radius_over_thickness: float
    included_angle_degrees: float
    half_included_angle_degrees: float
    external_pressure_mpa: float
    elastic_modulus_mpa: float
    poisson_ratio: float
    strength_mpa: float
    proportional_limit_mpa: float | None
    stress_states: tuple[HemisphereStressState, ...]
    governing_radius_mm: float
    governing_stress_mpa: float
    theoretical_stress_failure_pressure_mpa: float
    stress_margin: float
    seat_bearing_stress_mpa: float
    theoretical_seat_failure_pressure_mpa: float
    seat_margin: float
    classical_critical_pressure_mpa: float
    nasa_geometry_parameter_lambda: float
    nasa_minimum_lambda: float
    nasa_correlation_factor: float | None
    nasa_candidate_design_pressure_mpa: float | None
    nasa_candidate_critical_membrane_stress_mpa: float | None
    roark_probable_minimum_coefficient: float
    roark_probable_minimum_pressure_mpa: float
    buckling_capacity_status: Literal["released", "withheld_applicability"]
    released_buckling_pressure_mpa: float | None
    released_buckling_critical_membrane_stress_mpa: float | None
    buckling_margin: float | None
    buckling_validity_violations: tuple[str, ...]
    displacement_status: Literal["released", "withheld_missing_thick_branch_source"]
    displacement_validity_violations: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class FlatCircularPlateResult:
    model_id: str
    model_version: str
    source_reference: str
    seat_source_reference: str
    source_equation_case: Literal["Roark Table 24 case 10a", "Roark Table 24 case 10b"]
    material_failure_category: MaterialFailureCategory
    failure_criterion: PlateFailureCriterion
    load_type: Literal["uniform_transverse_pressure"]
    boundary_condition: PlateBoundaryCondition
    external_pressure_mpa: float
    free_radius_mm: float
    free_diameter_mm: float
    outside_radius_mm: float | None
    plate_thickness_mm: float
    free_diameter_over_thickness: float
    elastic_modulus_mpa: float
    poisson_ratio: float
    strength_mpa: float
    compressive_strength_mpa: float | None
    flexural_rigidity_n_mm: float
    radial_bending_stress_coefficient: float
    tangential_bending_stress_coefficient: float
    deflection_coefficient: float
    maximum_radial_bending_stress_mpa: float
    maximum_radial_stress_location: Literal["center", "free_diameter"]
    maximum_tangential_bending_stress_mpa: float
    maximum_tangential_stress_location: Literal["center"]
    governing_bending_direction: Literal["radial", "tangential"]
    governing_bending_stress_mpa: float
    transverse_shear_stress_mpa: float
    transverse_shear_location: Literal["free_diameter"]
    maximum_deflection_mm: float
    maximum_deflection_location: Literal["center"]
    maximum_deflection_over_thickness: float
    shear_corrected_deflection_estimate_mm: float
    shear_corrected_deflection_estimate_over_thickness: float
    deflection_status: Literal["released", "withheld_applicability"]
    released_maximum_deflection_mm: float | None
    deflection_validity_violations: tuple[str, ...]
    bending_minimum_free_diameter_over_thickness: float
    deflection_minimum_free_diameter_over_thickness: float
    poisson_ratio_evidence_band: tuple[float, float]
    envelope_source_reference: str
    theoretical_radial_failure_pressure_mpa: float
    theoretical_tangential_failure_pressure_mpa: float
    theoretical_failure_pressure_mpa: float
    bending_status: Literal["released", "withheld_applicability"]
    margin: float | None
    seat_bearing_stress_mpa: float | None
    theoretical_seat_failure_pressure_mpa: float | None
    seat_margin: float | None
    validity_violations: tuple[str, ...]
    notes: tuple[str, ...]


@dataclass(frozen=True)
class SmoothCylinderBucklingCandidate:
    regime: Literal["short", "moderate", "long"]
    source_equations: tuple[str, ...]
    correlation_factor_gamma: float
    sqrt_correlation_factor: float
    gamma_z: float
    applicable: bool
    critical_buckling_coefficient: float
    critical_aspect_ratio_beta: float | None
    continuous_circumferential_wave_count: float
    circumferential_wave_count_n: int | None
    ideal_critical_pressure_mpa: float
    correlated_critical_pressure_mpa: float | None
    correlated_critical_circumferential_stress_mpa: float | None
    eq25_simplified_critical_pressure_mpa: float | None
    applicability_conditions: tuple[str, ...]


@dataclass(frozen=True)
class SmoothCylinderBucklingResult:
    model_id: str
    model_version: str
    source_reference: str
    comparison_source_reference: str
    load_case: PressureLoadCase
    boundary_condition: Literal["simply_supported"]
    radius_convention: Literal["shell_mid_surface"]
    regime: Literal[
        "short",
        "moderate",
        "moderate_long_correlation_overlap",
        "long",
    ]
    capacity_status: Literal[
        "released",
        "released_pending_plasticity",
        "withheld_correlation_overlap",
        "withheld_applicability",
    ]
    source_equations: tuple[str, ...]
    external_pressure_mpa: float
    shell_mid_surface_radius_mm: float
    wall_thickness_mm: float
    unsupported_length_mm: float
    shell_mid_surface_radius_over_thickness: float
    unsupported_length_over_radius: float
    elastic_modulus_mpa: float
    poisson_ratio: float
    yield_strength_mpa: float | None
    proportional_limit_mpa: float | None
    flexural_rigidity_n_mm: float
    curvature_parameter_z: float
    geometry_mode_parameter: float
    line_load_sign_convention: Literal["positive_compression_magnitude"]
    circumferential_line_load_n_per_mm: float
    axial_line_load_n_per_mm: float
    short_regime_gamma_z_boundary: float
    moderate_gamma_z_lower_boundary: float
    moderate_long_boundary_parameter: float
    moderate_long_overlap_start_z: float
    moderate_long_overlap_end_z: float
    correlation_factor_gamma: float | None
    sqrt_correlation_factor: float | None
    critical_buckling_coefficient: float | None
    critical_aspect_ratio_beta: float | None
    continuous_circumferential_wave_count: float | None
    circumferential_wave_count_n: int | None
    ideal_critical_pressure_mpa: float | None
    correlated_critical_pressure_mpa: float | None
    correlated_critical_circumferential_stress_mpa: float | None
    working_circumferential_membrane_stress_mpa: float
    elastic_applicability_limit_mpa: float | None
    elastic_applicability_limit_basis: Literal[
        "proportional_limit",
        "yield_strength",
        "unavailable",
    ]
    elastic_applicability: Literal["within", "exceeded", "undetermined"]
    margin: float | None
    roark_probable_minimum_factor: float
    roark_probable_minimum_pressure_mpa: float
    roark_probable_minimum_lobes_n: int
    candidates: tuple[SmoothCylinderBucklingCandidate, ...]
    validity_violations: tuple[str, ...]
    release_gate_violations: tuple[str, ...]
    boundary_assumptions: tuple[str, ...]
    notes: tuple[str, ...]


RING_SHELL_MODEL_ID = "nasa_ring_stiffened_shell_external_pressure"
RING_SHELL_MODEL_VERSION = "2.0.0"
RING_SHELL_EQ64_ADJUSTMENT_FACTOR = 0.75
RING_SHELL_MIN_RADIUS_THICKNESS_RATIO = 10.0
RING_SHELL_DEFAULT_MAX_MODE_EVALUATIONS = 2_000_000
RING_SHELL_SOURCE = (
    "NASA/SP-8007-2020/REV 2, Eqs. 64-65 and 82-91, pp. 37 and 40-42"
)
RING_SHELL_SECTION_SOURCE = (
    "NASA/TP-2011-216882, Appendix A, Eq. A16, p. 100"
)
RING_SHELL_BENCHMARK_SOURCE = (
    "DTMB Report 1324, Figure 2 and Table 2, case-17 rectangular-ring cylinders"
)
GENERAL_INSTABILITY_SCOPE_NOTE = (
    "Ring material stress, frame tripping/crippling, attachment and weld effects, fabrication "
    "imperfections, residual stress, and local/global interaction are not evaluated."
)
GENERAL_INSTABILITY_SMEARED_NOTE = (
    "The smeared-ring model assumes uniformly spaced rings; widely spaced rings and local/global "
    "interaction need a discrete-shell or code-rule check."
)
RING_SHELL_GLOBAL_PLASTICITY_PENDING_REASON = (
    "the global Eq. 64/65 capacity implies a shell circumferential membrane stress "
    "{stress:.6g} MPa above the supplied {basis} {limit:.6g} MPa; NASA states plasticity "
    "factors for unstiffened cylinders only (Eqs. 30-32) and none for the smeared "
    "orthotropic mode, so this advisory pressure is an elastic upper bound pending validation"
)
RingShellAdvisoryStatus = Literal[
    "advisory",
    "advisory_pending_plasticity",
    "advisory_plasticity_undetermined",
]
RING_SHELL_ADVISORY_STATUS_BY_APPLICABILITY: dict[str, RingShellAdvisoryStatus] = {
    "within": "advisory",
    "exceeded": "advisory_pending_plasticity",
    "undetermined": "advisory_plasticity_undetermined",
}
RING_SHELL_ADVISORY_STATUS_BY_INTER_RING_STATUS: dict[str, RingShellAdvisoryStatus] = {
    "released": "advisory",
    "released_pending_plasticity": "advisory_pending_plasticity",
}


def capacity_status_not_withheld(capacity_status: str) -> bool:
    """The advisory admission rule: every status outside the ``withheld_*``
    family produced a pressure, so it may enter a comparison; a withheld one
    has no number to compare."""
    return not capacity_status.startswith("withheld")


def _elastic_applicability_screen(
    stress_mpa: float | None,
    proportional_mpa: float | None,
    yield_mpa: float | None,
) -> tuple[
    float | None,
    Literal["proportional_limit", "yield_strength", "unavailable"],
    Literal["within", "exceeded", "undetermined"],
]:
    """Resolve the elastic-applicability limit and compare a stress with it.

    The limit is the proportional limit, falling back to the yield strength;
    yield is a valid fallback because ``proportional_limit_mpa <= yield_mpa``,
    so yield bounds every admissible proportional limit from above. Returns
    ``(limit_mpa, basis, verdict)`` with basis one of ``proportional_limit`` /
    ``yield_strength`` / ``unavailable`` and verdict one of ``within`` /
    ``exceeded`` / ``undetermined``.
    """
    limit: float | None
    basis: Literal["proportional_limit", "yield_strength", "unavailable"]
    verdict: Literal["within", "exceeded", "undetermined"]
    if proportional_mpa is not None:
        limit, basis = proportional_mpa, "proportional_limit"
    elif yield_mpa is not None:
        limit, basis = yield_mpa, "yield_strength"
    else:
        limit, basis = None, "unavailable"
    if stress_mpa is None or limit is None:
        verdict = "undetermined"
    elif stress_mpa > limit:
        verdict = "exceeded"
    else:
        verdict = "within"
    return limit, basis, verdict


@dataclass(frozen=True)
class RingModeSearchIteration:
    axial_half_wave_bound: int
    circumferential_lobe_bound: int
    newly_evaluated_modes: int
    cumulative_evaluated_modes: int
    critical_axial_half_waves_m: int
    critical_circumferential_lobes_n: int
    ideal_critical_pressure_mpa: float
    relative_pressure_change: float | None
    governing_mode_stable: bool
    governing_mode_below_frontier: bool
    frontier_minimum_pressure_mpa: float
    frontier_above_governing: bool


@dataclass(frozen=True)
class RingGlobalBucklingResult:
    ring_torsion_included: bool
    converged: bool
    termination_reason: Literal[
        "stable_interior_governing_mode",
        "mode_evaluation_limit",
        "no_positive_mode",
    ]
    ideal_critical_pressure_mpa: float | None
    adjusted_critical_pressure_mpa: float | None
    adjustment_factor: float
    critical_axial_half_waves_m: int | None
    critical_circumferential_lobes_n: int | None
    evaluated_axial_half_waves: int
    evaluated_circumferential_lobes: int
    evaluated_mode_count: int
    iterations: tuple[RingModeSearchIteration, ...]
    ring_eccentricity_from_shell_mid_surface_mm: float
    ring_torsion_contribution_n_mm: float
    orthotropic_extensional_x_n_per_mm: float
    orthotropic_extensional_y_n_per_mm: float
    orthotropic_extensional_xy_n_per_mm: float
    orthotropic_shear_xy_n_per_mm: float
    orthotropic_bending_x_n_mm: float
    orthotropic_bending_y_n_mm: float
    orthotropic_bending_xy_n_mm: float
    orthotropic_coupling_y_n: float


@dataclass(frozen=True)
class RingModeDisposition:
    mode: str
    disposition: Literal[
        "implemented_advisory",
        "not_applicable",
        "external_blocker",
    ]
    source_reference: str
    basis: str


@dataclass(frozen=True)
class RingShellResult:
    model_id: str
    model_version: str
    source_reference: str
    section_source_reference: str
    benchmark_source_reference: str
    capacity_status: Literal[
        "advisory",
        "withheld_invalid_applicability",
        "withheld_nonconvergence",
    ]
    load_case: Literal["hydrostatic_closed_end"]
    boundary_condition: Literal["simply_supported"]
    radius_convention: Literal["shell_mid_surface"]
    external_pressure_mpa: float
    shell_mid_surface_radius_mm: float
    wall_thickness_mm: float
    unsupported_length_mm: float
    ring_spacing_mm: float
    ring_location: Literal["internal", "external"]
    elastic_modulus_mpa: float
    poisson_ratio: float
    yield_strength_mpa: float | None
    proportional_limit_mpa: float | None
    ring_section_type: Literal["solid_rectangle"]
    ring_axial_width_mm: float
    ring_radial_height_mm: float
    ring_area_mm2: float
    ring_centroid_from_shell_surface_mm: float
    ring_centroidal_inertia_mm4: float
    ring_torsional_constant_mm4: float
    ring_eccentricity_from_shell_mid_surface_mm: float
    global_without_ring_torsion: RingGlobalBucklingResult
    global_with_ring_torsion: RingGlobalBucklingResult
    torsion_ideal_pressure_effect_mpa: float | None
    torsion_adjusted_pressure_effect_mpa: float | None
    torsion_relative_pressure_effect: float | None
    torsion_changes_governing_mode: bool | None
    global_critical_circumferential_membrane_stress_mpa: float | None
    elastic_applicability_limit_mpa: float | None
    elastic_applicability_limit_basis: Literal[
        "proportional_limit",
        "yield_strength",
        "unavailable",
    ]
    global_elastic_applicability: Literal["within", "exceeded", "undetermined"]
    inter_ring_shell_buckling: SmoothCylinderBucklingResult
    advisory_candidate_modes: tuple[str, ...]
    advisory_governing_mode: str | None
    advisory_governing_status: (
        Literal["advisory", "advisory_pending_plasticity", "advisory_plasticity_undetermined"]
        | None
    )
    advisory_governing_pressure_mpa: float | None
    advisory_margin: float | None
    validity_violations: tuple[str, ...]
    mode_dispositions: tuple[RingModeDisposition, ...]
    notes: tuple[str, ...]


def _validated_poisson_ratio(poisson_ratio: float) -> float:
    if isinstance(poisson_ratio, bool):
        raise ValueError("poisson_ratio must be numeric")
    try:
        value = float(poisson_ratio)
    except (TypeError, ValueError) as exc:
        raise ValueError("poisson_ratio must be numeric") from exc
    if not math.isfinite(value) or not 0 < value < 0.5:
        raise ValueError("poisson_ratio must be finite and between 0 and 0.5")
    return value


def _positive_finite(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric")
    try:
        result = float(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{name} must be numeric") from exc
    if not math.isfinite(result) or result <= 0.0:
        raise ValueError(f"{name} must be finite and positive")
    return result


def _validated_failure_category(value: Any) -> MaterialFailureCategory:
    categories = get_args(MaterialFailureCategory)
    if value not in categories:
        raise ValueError(
            "material_failure_category must be one of " + ", ".join(categories)
        )
    return value


def _shell_governing_state(
    states: Sequence[TubeStressState | HemisphereStressState],
    category: MaterialFailureCategory,
) -> tuple[TubeStressState | HemisphereStressState, float]:
    """Return the state and stress magnitude the category's shell criterion compares.

    A ductile metal is governed by the largest von Mises stress; a plastic or
    brittle material, neither of which yields, by the largest hoop stress
    magnitude.
    """
    if category == "ductile_metal":
        governing = max(states, key=lambda state: state.von_mises_stress_mpa)
        return governing, governing.von_mises_stress_mpa
    governing = max(states, key=lambda state: abs(state.hoop_stress_mpa))
    return governing, abs(governing.hoop_stress_mpa)


def _principal_and_von_mises(
    stresses: tuple[float, float, float],
) -> tuple[tuple[float, float, float], float]:
    s1, s2, s3 = sorted(stresses, reverse=True)
    von_mises = math.sqrt(0.5 * ((s1 - s2) ** 2 + (s2 - s3) ** 2 + (s3 - s1) ** 2))
    return (s1, s2, s3), von_mises


def _seat_bearing(
    *,
    pressure_mpa: float,
    outside_radius_mm: float,
    inside_radius_mm: float,
    strength_mpa: float,
) -> tuple[float, float, float]:
    """Return the average seat bearing stress, its failure pressure, and margin.

    The pressure load on the closure's outside radius is carried by the flat
    annulus between the inside and outside radii; the stress is a positive
    compressive magnitude compared to the uniaxial strength.
    """
    bearing_stress = (
        pressure_mpa * outside_radius_mm**2 / (outside_radius_mm**2 - inside_radius_mm**2)
    )
    margin = strength_mpa / bearing_stress - 1.0
    return bearing_stress, pressure_mpa * (margin + 1.0), margin


def _tube_stress_state(
    *,
    radius_mm: float,
    radius_convention: StressStateRadiusConvention,
    radial_stress_mpa: float,
    hoop_stress_mpa: float,
    axial_stress_mpa: float,
    radial_displacement_mm: float | None,
) -> TubeStressState:
    principal, von_mises = _principal_and_von_mises(
        (radial_stress_mpa, hoop_stress_mpa, axial_stress_mpa)
    )
    return TubeStressState(
        radius_mm=radius_mm,
        radius_convention=radius_convention,
        radial_stress_mpa=radial_stress_mpa,
        hoop_stress_mpa=hoop_stress_mpa,
        axial_stress_mpa=axial_stress_mpa,
        principal_stresses_mpa=principal,
        von_mises_stress_mpa=von_mises,
        radial_displacement_mm=radial_displacement_mm,
    )


def closed_end_tube_stress(
    *,
    external_pressure_mpa: float,
    internal_radius_mm: float,
    wall_thickness_mm: float,
    material_failure_category: MaterialFailureCategory,
    strength_mpa: float,
    elastic_modulus_mpa: float | None = None,
    poisson_ratio: float | None = None,
    axial_length_mm: float | None = None,
    force_thick: bool = False,
) -> TubeStressResult:
    """Calculate closed-end tube stress, material failure pressure, and displacement.

    Numeric inputs are explicitly MPa and mm. The thin branch applies only when
    mean-radius/thickness is greater than 10; the thick Lamé branch is used at
    or below 10 or when ``force_thick`` is true.

    ``strength_mpa`` is the uniaxial strength the category's criterion compares
    against: the yield strength of a ``ductile_metal``, read against the von
    Mises stress; the working strength of a ``plastic`` or the ultimate
    compressive strength of a ``brittle`` material, each read against the
    largest hoop stress magnitude. The result names the criterion applied.

    ``elastic_modulus_mpa`` and ``poisson_ratio`` are optional and change no
    stress result. Supplied together they release the branch's radial
    displacement, positive outward and reported at each stress state's own
    radius, and its axial strain, positive in extension and uniform through
    the wall; ``axial_length_mm`` converts that strain to a length change over
    the caller's gauge length. Without both elastic properties, displacement is
    withheld and the reason is reported.
    """
    pressure = _positive_finite(external_pressure_mpa, "external_pressure_mpa")
    internal_radius = _positive_finite(internal_radius_mm, "internal_radius_mm")
    thickness = _positive_finite(wall_thickness_mm, "wall_thickness_mm")
    category = _validated_failure_category(material_failure_category)
    strength = _positive_finite(strength_mpa, "strength_mpa")
    elastic_modulus = (
        _positive_finite(elastic_modulus_mpa, "elastic_modulus_mpa")
        if elastic_modulus_mpa is not None
        else None
    )
    poisson = (
        _validated_poisson_ratio(poisson_ratio) if poisson_ratio is not None else None
    )
    axial_length = (
        _positive_finite(axial_length_mm, "axial_length_mm")
        if axial_length_mm is not None
        else None
    )
    if not isinstance(force_thick, bool):
        raise ValueError("force_thick must be a boolean")

    displacement_violations: list[str] = []
    if elastic_modulus is None:
        displacement_violations.append(TUBE_DISPLACEMENT_MISSING_MODULUS)
    if poisson is None:
        displacement_violations.append(TUBE_DISPLACEMENT_MISSING_POISSON)
    missing_elastic_properties = bool(displacement_violations)

    external_radius = internal_radius + thickness
    mean_radius = internal_radius + 0.5 * thickness
    radius_ratio = mean_radius / thickness
    branch: Literal["thin", "thick"] = (
        "thick" if force_thick or radius_ratio <= TUBE_THIN_WALL_MEAN_RADIUS_RATIO else "thin"
    )

    axial_strain: float | None = None
    if branch == "thin":
        hoop_stress = -pressure * mean_radius / thickness
        median_displacement: float | None = None
        if elastic_modulus is not None and poisson is not None:
            # DTMB 1497 Eq. [5] at the median surface, and Eq. [A7] with the
            # membrane resultants N_x = -p*R/2 and N_phi = -p*R.
            candidate_displacement = (
                -pressure * mean_radius**2 * (1.0 - poisson / 2.0)
                / (elastic_modulus * thickness)
            )
            candidate_axial_strain = (
                -pressure * mean_radius * (1.0 - 2.0 * poisson)
                / (2.0 * elastic_modulus * thickness)
            )
            if abs(candidate_displacement) > thickness:
                displacement_violations.append(
                    TUBE_DISPLACEMENT_EXCEEDS_THICKNESS
                )
            else:
                median_displacement = candidate_displacement
                axial_strain = candidate_axial_strain
        states: tuple[TubeStressState, ...] = (
            _tube_stress_state(
                radius_mm=mean_radius,
                radius_convention="mean",
                radial_stress_mpa=0.0,
                hoop_stress_mpa=hoop_stress,
                axial_stress_mpa=0.5 * hoop_stress,
                radial_displacement_mm=median_displacement,
            ),
        )
        source = TUBE_THIN_SOURCE
        displacement_source = TUBE_THIN_DISPLACEMENT_SOURCE
    else:
        radius_squared_difference = external_radius**2 - internal_radius**2
        lame_a = -pressure * external_radius**2 / radius_squared_difference
        lame_b = -pressure * internal_radius**2 * external_radius**2 / radius_squared_difference
        if elastic_modulus is not None and poisson is not None:
            # Boresi and Schmidt Eq. (11.15) with no temperature change and no
            # separately applied axial load.
            axial_strain = (
                -(1.0 - 2.0 * poisson) * pressure * external_radius**2
                / (elastic_modulus * radius_squared_difference)
            )

        def displacement_at(radius: float) -> float | None:
            # Boresi and Schmidt Eq. (11.24) under external pressure only.
            if elastic_modulus is None or poisson is None:
                return None
            return (
                -pressure
                * radius
                * (
                    (1.0 - 2.0 * poisson) * external_radius**2
                    + (1.0 + poisson) * internal_radius**2 * external_radius**2 / radius**2
                )
                / (elastic_modulus * radius_squared_difference)
            )

        def state_at(radius: float, convention: StressStateRadiusConvention) -> TubeStressState:
            return _tube_stress_state(
                radius_mm=radius,
                radius_convention=convention,
                radial_stress_mpa=lame_a - lame_b / radius**2,
                hoop_stress_mpa=lame_a + lame_b / radius**2,
                axial_stress_mpa=lame_a,
                radial_displacement_mm=displacement_at(radius),
            )

        states = (
            state_at(internal_radius, "internal"),
            state_at(external_radius, "external"),
        )
        source = TUBE_THICK_SOURCE
        displacement_source = TUBE_THICK_DISPLACEMENT_SOURCE

    axial_length_change = (
        axial_strain * axial_length
        if axial_strain is not None and axial_length is not None
        else None
    )

    governing, governing_stress = _shell_governing_state(states, category)
    margin = strength / governing_stress - 1.0
    failure_pressure = pressure * (margin + 1.0)
    return TubeStressResult(
        model_id=TUBE_STRESS_MODEL_ID,
        model_version=TUBE_STRESS_MODEL_VERSION,
        source_reference=source,
        displacement_source_reference=displacement_source,
        material_failure_category=category,
        failure_criterion=SHELL_FAILURE_CRITERION[category],
        load_case="hydrostatic_closed_end",
        end_condition="closed",
        stress_sign_convention="tension_positive",
        principal_stress_ordering="descending_algebraic",
        branch=branch,
        force_thick=force_thick,
        thin_wall_threshold_mean_radius_over_thickness=TUBE_THIN_WALL_MEAN_RADIUS_RATIO,
        internal_radius_mm=internal_radius,
        external_radius_mm=external_radius,
        mean_radius_mm=mean_radius,
        wall_thickness_mm=thickness,
        mean_radius_over_thickness=radius_ratio,
        external_pressure_mpa=pressure,
        strength_mpa=strength,
        elastic_modulus_mpa=elastic_modulus,
        poisson_ratio=poisson,
        axial_length_mm=axial_length,
        stress_states=states,
        governing_radius_mm=governing.radius_mm,
        governing_stress_mpa=governing_stress,
        theoretical_failure_pressure_mpa=failure_pressure,
        margin=margin,
        displacement_status=(
            "released"
            if not displacement_violations
            else (
                "withheld_missing_elastic_properties"
                if missing_elastic_properties
                else "withheld_applicability"
            )
        ),
        displacement_validity_violations=tuple(displacement_violations),
        axial_strain=axial_strain,
        axial_length_change_mm=axial_length_change,
        validity_violations=(),
        notes=(*TUBE_SCOPE_NOTES, *SHELL_CATEGORY_NOTES[category]),
    )


def _hemisphere_stress_state(
    *,
    radius_mm: float,
    radius_convention: StressStateRadiusConvention,
    radial_stress_mpa: float,
    meridional_stress_mpa: float,
    hoop_stress_mpa: float,
    radial_displacement_mm: float | None,
) -> HemisphereStressState:
    principal, von_mises = _principal_and_von_mises(
        (radial_stress_mpa, meridional_stress_mpa, hoop_stress_mpa)
    )
    return HemisphereStressState(
        radius_mm=radius_mm,
        radius_convention=radius_convention,
        radial_stress_mpa=radial_stress_mpa,
        meridional_stress_mpa=meridional_stress_mpa,
        hoop_stress_mpa=hoop_stress_mpa,
        principal_stresses_mpa=principal,
        von_mises_stress_mpa=von_mises,
        radial_displacement_mm=radial_displacement_mm,
    )


def hemispherical_head_external_pressure(
    *,
    external_pressure_mpa: float,
    internal_radius_mm: float,
    wall_thickness_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    material_failure_category: MaterialFailureCategory,
    strength_mpa: float,
    proportional_limit_mpa: float | None = None,
    force_thick: bool = False,
) -> HemisphereResult:
    """Calculate hemispherical-head stress, material failure, buckling, and displacement.

    Numeric inputs are explicitly MPa and mm. Stress uses Roark's thin-shell
    branch only when mean-radius/thickness is greater than 10 and otherwise
    uses the thick-sphere Lamé branch. Buckling capacity is released only when
    the NASA SP-8032 clamped-cap recommendation is in its stated ``lambda > 2``
    range, the geometry remains in the thin-shell domain, and the correlated
    response remains elastic.

    ``strength_mpa`` is the uniaxial strength the category's criterion compares
    against, as for the tube: yield strength against von Mises stress for a
    ``ductile_metal``, working strength (``plastic``) or ultimate compressive
    strength (``brittle``) against the largest hoop stress magnitude. The seat
    bearing stress is compared to the same strength. A ductile metal's
    proportional limit may not exceed its yield strength; no ordering is
    asserted for the other categories.

    The thin branch also reports the membrane radial displacement that its
    source states in the same equation as the membrane stress, at the median
    surface and positive outward, so external pressure gives a negative value.
    It applies away from the equator; the thick branch withholds it, because
    no consulted source states a thick-sphere displacement.
    """
    pressure = _positive_finite(external_pressure_mpa, "external_pressure_mpa")
    internal_radius = _positive_finite(internal_radius_mm, "internal_radius_mm")
    thickness = _positive_finite(wall_thickness_mm, "wall_thickness_mm")
    elastic_modulus = _positive_finite(elastic_modulus_mpa, "elastic_modulus_mpa")
    poisson = _validated_poisson_ratio(poisson_ratio)
    category = _validated_failure_category(material_failure_category)
    strength = _positive_finite(strength_mpa, "strength_mpa")
    proportional_limit = (
        _positive_finite(proportional_limit_mpa, "proportional_limit_mpa")
        if proportional_limit_mpa is not None
        else None
    )
    if (
        category == "ductile_metal"
        and proportional_limit is not None
        and proportional_limit > strength
    ):
        raise ValueError(
            "proportional_limit_mpa must be <= strength_mpa (the yield strength) for ductile_metal"
        )
    if not isinstance(force_thick, bool):
        raise ValueError("force_thick must be a boolean")

    external_radius = internal_radius + thickness
    mean_radius = internal_radius + thickness / 2.0
    radius_ratio = mean_radius / thickness
    branch: Literal["thin", "thick"] = (
        "thick"
        if force_thick or radius_ratio <= HEMISPHERE_THIN_WALL_MEAN_RADIUS_RATIO
        else "thin"
    )

    displacement_source: str | None
    displacement_violations: tuple[str, ...]
    if branch == "thin":
        membrane_stress = -pressure * mean_radius / (2.0 * thickness)
        # NASA TM-4579 Eq. (5), the membrane radial displacement stated with
        # the membrane stress above, signed for external pressure.
        membrane_displacement = (
            -pressure
            * mean_radius**2
            * (1.0 - poisson)
            / (2.0 * elastic_modulus * thickness)
        )
        stress_states: tuple[HemisphereStressState, ...] = (
            _hemisphere_stress_state(
                radius_mm=mean_radius,
                radius_convention="mean",
                radial_stress_mpa=0.0,
                meridional_stress_mpa=membrane_stress,
                hoop_stress_mpa=membrane_stress,
                radial_displacement_mm=membrane_displacement,
            ),
        )
        stress_source = HEMISPHERE_THIN_STRESS_SOURCE
        displacement_source = HEMISPHERE_MEMBRANE_DISPLACEMENT_SOURCE
        displacement_violations = ()
    else:
        denominator = external_radius**3 - internal_radius**3
        lame_a = -pressure * external_radius**3 / denominator
        lame_b = lame_a * internal_radius**3

        def state_at(
            radius: float,
            convention: StressStateRadiusConvention,
        ) -> HemisphereStressState:
            radial_stress = lame_a - lame_b / radius**3
            tangential_stress = lame_a + lame_b / (2.0 * radius**3)
            return _hemisphere_stress_state(
                radius_mm=radius,
                radius_convention=convention,
                radial_stress_mpa=radial_stress,
                meridional_stress_mpa=tangential_stress,
                hoop_stress_mpa=tangential_stress,
                radial_displacement_mm=None,
            )

        stress_states = (
            state_at(internal_radius, "internal"),
            state_at(external_radius, "external"),
        )
        stress_source = HEMISPHERE_THICK_STRESS_SOURCE
        displacement_source = None
        displacement_violations = (HEMISPHERE_DISPLACEMENT_MISSING_THICK_SOURCE,)

    governing, governing_stress = _shell_governing_state(stress_states, category)
    stress_margin = strength / governing_stress - 1.0
    stress_failure_pressure = pressure * (stress_margin + 1.0)
    seat_stress, seat_failure_pressure, seat_margin = _seat_bearing(
        pressure_mpa=pressure,
        outside_radius_mm=external_radius,
        inside_radius_mm=internal_radius,
        strength_mpa=strength,
    )

    one_minus_poisson_squared = 1.0 - poisson**2
    classical_pressure = (
        2.0
        * elastic_modulus
        / math.sqrt(3.0 * one_minus_poisson_squared)
        * (thickness / mean_radius) ** 2
    )
    half_included_angle_radians = math.pi / 2.0
    nasa_lambda = (
        (12.0 * one_minus_poisson_squared) ** 0.25
        * math.sqrt(radius_ratio)
        * 2.0
        * math.sin(half_included_angle_radians / 2.0)
    )
    roark_pressure = (
        HEMISPHERE_ROARK_PROBABLE_MINIMUM_COEFFICIENT
        * elastic_modulus
        * (thickness / mean_radius) ** 2
    )
    if not all(
        math.isfinite(value)
        for value in (classical_pressure, nasa_lambda, roark_pressure)
    ):
        raise ValueError("hemisphere buckling parameters must be finite")

    nasa_factor = (
        0.14 + 3.2 / nasa_lambda**2
        if nasa_lambda > HEMISPHERE_NASA_MINIMUM_LAMBDA
        else None
    )
    nasa_candidate_pressure = (
        nasa_factor * classical_pressure if nasa_factor is not None else None
    )
    nasa_candidate_stress = (
        nasa_candidate_pressure * mean_radius / (2.0 * thickness)
        if nasa_candidate_pressure is not None
        else None
    )

    buckling_violations: list[str] = []
    if radius_ratio <= HEMISPHERE_THIN_WALL_MEAN_RADIUS_RATIO:
        buckling_violations.append(
            "mean_radius_mm / wall_thickness_mm must be > 10 for the "
            "Roark thin-shell buckling gate"
        )
    if nasa_lambda <= HEMISPHERE_NASA_MINIMUM_LAMBDA:
        buckling_violations.append(
            "NASA SP-8032 Eq. 4 is stated only for geometry parameter lambda > 2"
        )
    if nasa_candidate_stress is not None:
        if proportional_limit is None:
            buckling_violations.append(
                "proportional_limit_mpa is required to establish elastic buckling applicability"
            )
        elif nasa_candidate_stress > proportional_limit:
            buckling_violations.append(
                "NASA-correlated critical membrane stress exceeds the supplied proportional limit; "
                "no inelastic correction is implemented"
            )

    capacity_released = not buckling_violations and nasa_candidate_pressure is not None
    released_pressure = nasa_candidate_pressure if capacity_released else None
    released_stress = nasa_candidate_stress if capacity_released else None
    buckling_margin = released_pressure / pressure - 1.0 if released_pressure is not None else None

    return HemisphereResult(
        model_id=HEMISPHERE_MODEL_ID,
        model_version=HEMISPHERE_MODEL_VERSION,
        stress_source_reference=stress_source,
        buckling_source_reference=HEMISPHERE_BUCKLING_SOURCE,
        software_parity_source_reference=HEMISPHERE_SOFTWARE_PARITY_SOURCE,
        displacement_source_reference=displacement_source,
        seat_source_reference=SEAT_BEARING_STRESS_SOURCE,
        material_failure_category=category,
        failure_criterion=SHELL_FAILURE_CRITERION[category],
        load_case="uniform_external_pressure",
        buckling_boundary_condition="clamped_equator",
        radius_convention="internal_input_mean_surface_analysis",
        stress_sign_convention="tension_positive",
        principal_stress_ordering="descending_algebraic",
        branch=branch,
        force_thick=force_thick,
        thin_wall_threshold_mean_radius_over_thickness=(
            HEMISPHERE_THIN_WALL_MEAN_RADIUS_RATIO
        ),
        internal_radius_mm=internal_radius,
        external_radius_mm=external_radius,
        mean_radius_mm=mean_radius,
        wall_thickness_mm=thickness,
        mean_radius_over_thickness=radius_ratio,
        included_angle_degrees=180.0,
        half_included_angle_degrees=90.0,
        external_pressure_mpa=pressure,
        elastic_modulus_mpa=elastic_modulus,
        poisson_ratio=poisson,
        strength_mpa=strength,
        proportional_limit_mpa=proportional_limit,
        stress_states=stress_states,
        governing_radius_mm=governing.radius_mm,
        governing_stress_mpa=governing_stress,
        theoretical_stress_failure_pressure_mpa=stress_failure_pressure,
        stress_margin=stress_margin,
        seat_bearing_stress_mpa=seat_stress,
        theoretical_seat_failure_pressure_mpa=seat_failure_pressure,
        seat_margin=seat_margin,
        classical_critical_pressure_mpa=classical_pressure,
        nasa_geometry_parameter_lambda=nasa_lambda,
        nasa_minimum_lambda=HEMISPHERE_NASA_MINIMUM_LAMBDA,
        nasa_correlation_factor=nasa_factor,
        nasa_candidate_design_pressure_mpa=nasa_candidate_pressure,
        nasa_candidate_critical_membrane_stress_mpa=nasa_candidate_stress,
        roark_probable_minimum_coefficient=(
            HEMISPHERE_ROARK_PROBABLE_MINIMUM_COEFFICIENT
        ),
        roark_probable_minimum_pressure_mpa=roark_pressure,
        buckling_capacity_status=(
            "released" if capacity_released else "withheld_applicability"
        ),
        released_buckling_pressure_mpa=released_pressure,
        released_buckling_critical_membrane_stress_mpa=released_stress,
        buckling_margin=buckling_margin,
        buckling_validity_violations=tuple(buckling_violations),
        displacement_status=(
            "released"
            if not displacement_violations
            else "withheld_missing_thick_branch_source"
        ),
        displacement_validity_violations=displacement_violations,
        notes=(*HEMISPHERE_SCOPE_NOTES, *SHELL_CATEGORY_NOTES[category]),
    )


def flat_circular_plate(
    *,
    external_pressure_mpa: float,
    free_radius_mm: float,
    plate_thickness_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    material_failure_category: MaterialFailureCategory,
    strength_mpa: float,
    boundary_condition: PlateBoundaryCondition,
    outside_radius_mm: float | None = None,
    compressive_strength_mpa: float | None = None,
) -> FlatCircularPlateResult:
    """Calculate a uniformly pressure-loaded flat circular plate.

    Numeric inputs are explicitly MPa and mm. ``boundary_condition`` is
    required so a simply-supported plate can never be evaluated implicitly as
    fixed. The result reports linear small-deflection bending, center
    deflection, and the average transverse shear on the support perimeter.
    The bending margin and the released deflection are each withheld, with
    their reasons, outside their evidence floors or past the small-deflection
    limit; the formula values themselves stay published.

    ``strength_mpa`` is the uniaxial strength the surface bending stress is
    compared against: the yield strength of a ``ductile_metal``, the working
    strength of a ``plastic``, or the ultimate tensile strength of a
    ``brittle`` material, whose convex face is in tension. The seat bearing
    stress is compared to the same strength except for a brittle material,
    which must supply its ultimate compressive strength as
    ``compressive_strength_mpa``; the other categories reject that argument.

    ``outside_radius_mm`` is optional and changes no bending result. Supplied,
    it releases the average seat bearing stress on the annulus between the free
    and outside radii, with its own failure pressure and margin; without it the
    three seat values are ``None``.
    """
    pressure = _positive_finite(external_pressure_mpa, "external_pressure_mpa")
    free_radius = _positive_finite(free_radius_mm, "free_radius_mm")
    thickness = _positive_finite(plate_thickness_mm, "plate_thickness_mm")
    elastic_modulus = _positive_finite(elastic_modulus_mpa, "elastic_modulus_mpa")
    poisson = _validated_poisson_ratio(poisson_ratio)
    category = _validated_failure_category(material_failure_category)
    strength = _positive_finite(strength_mpa, "strength_mpa")
    outside_radius = (
        _positive_finite(outside_radius_mm, "outside_radius_mm")
        if outside_radius_mm is not None
        else None
    )
    if category == "brittle":
        if compressive_strength_mpa is None:
            raise ValueError(
                "compressive_strength_mpa is required for brittle: the seat is compared to the "
                "ultimate compressive strength while strength_mpa is the ultimate tensile strength"
            )
        compressive_strength: float | None = _positive_finite(
            compressive_strength_mpa, "compressive_strength_mpa"
        )
    elif compressive_strength_mpa is not None:
        raise ValueError(
            "compressive_strength_mpa applies only to brittle; ductile_metal and plastic compare "
            "the seat to strength_mpa"
        )
    else:
        compressive_strength = None
    if boundary_condition not in ("fixed", "simply_supported"):
        raise ValueError("boundary_condition must be fixed or simply_supported")
    if outside_radius is not None and outside_radius <= free_radius:
        raise ValueError("outside_radius_mm must exceed free_radius_mm")

    free_diameter = 2.0 * free_radius
    diameter_thickness_ratio = free_diameter / thickness
    flexural_rigidity = elastic_modulus * thickness**3 / (12.0 * (1.0 - poisson**2))
    radius_thickness_squared = (free_radius / thickness) ** 2

    if boundary_condition == "fixed":
        source_equation_case: Literal[
            "Roark Table 24 case 10a", "Roark Table 24 case 10b"
        ] = "Roark Table 24 case 10b"
        radial_coefficient = 3.0 / 4.0
        tangential_coefficient = 3.0 * (1.0 + poisson) / 8.0
        deflection_coefficient = 3.0 * (1.0 - poisson**2) / 16.0
        radial_location: Literal["center", "free_diameter"] = "free_diameter"
        boundary_note = (
            "boundary_condition: fixed edge prevents radial rotation and transverse deflection "
            "while allowing radial displacement."
        )
    else:
        source_equation_case = "Roark Table 24 case 10a"
        radial_coefficient = 3.0 * (3.0 + poisson) / 8.0
        tangential_coefficient = radial_coefficient
        deflection_coefficient = 3.0 * (1.0 - poisson) * (5.0 + poisson) / 16.0
        radial_location = "center"
        boundary_note = (
            "boundary_condition: simply-supported edge prevents transverse deflection while "
            "allowing radial rotation and displacement."
        )

    radial_stress = radial_coefficient * pressure * radius_thickness_squared
    tangential_stress = tangential_coefficient * pressure * radius_thickness_squared
    maximum_deflection = (
        deflection_coefficient
        * pressure
        * free_radius**4
        / (elastic_modulus * thickness**3)
    )
    transverse_shear = pressure * free_diameter / (4.0 * thickness)
    shear_modulus = elastic_modulus / (2.0 * (1.0 + poisson))
    shear_corrected_deflection = maximum_deflection + pressure * free_radius**2 / (
        4.0 * FLAT_CIRCULAR_PLATE_SHEAR_CORRECTION_FACTOR * shear_modulus * thickness
    )

    if radial_stress >= tangential_stress:
        governing_direction: Literal["radial", "tangential"] = "radial"
        governing_stress = radial_stress
    else:
        governing_direction = "tangential"
        governing_stress = tangential_stress

    radial_failure_pressure = pressure * strength / radial_stress
    tangential_failure_pressure = pressure * strength / tangential_stress
    theoretical_failure_pressure = min(radial_failure_pressure, tangential_failure_pressure)
    seat_stress = seat_failure_pressure = seat_margin = None
    if outside_radius is not None:
        seat_stress, seat_failure_pressure, seat_margin = _seat_bearing(
            pressure_mpa=pressure,
            outside_radius_mm=outside_radius,
            inside_radius_mm=free_radius,
            strength_mpa=strength if compressive_strength is None else compressive_strength,
        )
    deflection_thickness_ratio = maximum_deflection / thickness
    estimate_thickness_ratio = shear_corrected_deflection / thickness
    bending_minimum_ratio = FLAT_CIRCULAR_PLATE_BENDING_MINIMUM_RATIO[boundary_condition]
    deflection_minimum_ratio = FLAT_CIRCULAR_PLATE_DEFLECTION_MINIMUM_RATIO[
        boundary_condition
    ]
    poisson_band_low, poisson_band_high = FLAT_CIRCULAR_PLATE_POISSON_EVIDENCE_BAND
    poisson_in_band = poisson_band_low <= poisson <= poisson_band_high
    poisson_band_violation = (
        f"poisson_ratio is outside the swept evidence band "
        f"{poisson_band_low} <= poisson_ratio <= {poisson_band_high}"
    )
    small_deflection_violation = (
        "shear_corrected_deflection_estimate_mm exceeds plate_thickness_mm / 2, "
        "the small-deflection limit"
    )
    violations: list[str] = []
    if diameter_thickness_ratio < bending_minimum_ratio:
        violations.append(
            f"free_diameter_mm / plate_thickness_mm is below {bending_minimum_ratio}, "
            f"the {boundary_condition} bending-stress evidence floor"
        )
    if not poisson_in_band:
        violations.append(poisson_band_violation)
    # Past the small-deflection limit membrane action invalidates the bending
    # result too, so this gates the whole result wherever it trips — including
    # the band below the deflection floor, where the Kirchhoff deflection is
    # not fit to publish but the applicability question still has to be asked.
    if estimate_thickness_ratio > 0.5:
        violations.append(small_deflection_violation)

    deflection_violations: list[str] = []
    if diameter_thickness_ratio < deflection_minimum_ratio:
        deflection_violations.append(
            f"free_diameter_mm / plate_thickness_mm is below {deflection_minimum_ratio}, "
            f"the {boundary_condition} center-deflection evidence floor"
        )
    if not poisson_in_band:
        deflection_violations.append(poisson_band_violation)
    # A deflection beyond the small-deflection limit is itself invalid, not
    # merely a gate on the stress result, so it withholds the deflection too.
    if estimate_thickness_ratio > 0.5:
        deflection_violations.append(small_deflection_violation)
    deflection_released = not deflection_violations
    # The Kirchhoff stresses and their theoretical failure pressures are
    # published as the formula's own values; the margin is the verdict, and
    # like the released deflection it is withheld outside the evidence.
    bending_released = not violations

    return FlatCircularPlateResult(
        model_id=FLAT_CIRCULAR_PLATE_MODEL_ID,
        model_version=FLAT_CIRCULAR_PLATE_MODEL_VERSION,
        source_reference=FLAT_CIRCULAR_PLATE_SOURCE,
        seat_source_reference=SEAT_BEARING_STRESS_SOURCE,
        source_equation_case=source_equation_case,
        material_failure_category=category,
        failure_criterion=PLATE_FAILURE_CRITERION[category],
        load_type="uniform_transverse_pressure",
        boundary_condition=boundary_condition,
        external_pressure_mpa=pressure,
        free_radius_mm=free_radius,
        free_diameter_mm=free_diameter,
        outside_radius_mm=outside_radius,
        plate_thickness_mm=thickness,
        free_diameter_over_thickness=diameter_thickness_ratio,
        elastic_modulus_mpa=elastic_modulus,
        poisson_ratio=poisson,
        strength_mpa=strength,
        compressive_strength_mpa=compressive_strength,
        flexural_rigidity_n_mm=flexural_rigidity,
        radial_bending_stress_coefficient=radial_coefficient,
        tangential_bending_stress_coefficient=tangential_coefficient,
        deflection_coefficient=deflection_coefficient,
        maximum_radial_bending_stress_mpa=radial_stress,
        maximum_radial_stress_location=radial_location,
        maximum_tangential_bending_stress_mpa=tangential_stress,
        maximum_tangential_stress_location="center",
        governing_bending_direction=governing_direction,
        governing_bending_stress_mpa=governing_stress,
        transverse_shear_stress_mpa=transverse_shear,
        transverse_shear_location="free_diameter",
        maximum_deflection_mm=maximum_deflection,
        maximum_deflection_location="center",
        maximum_deflection_over_thickness=deflection_thickness_ratio,
        shear_corrected_deflection_estimate_mm=shear_corrected_deflection,
        shear_corrected_deflection_estimate_over_thickness=estimate_thickness_ratio,
        deflection_status="released" if deflection_released else "withheld_applicability",
        released_maximum_deflection_mm=(
            maximum_deflection if deflection_released else None
        ),
        deflection_validity_violations=tuple(deflection_violations),
        bending_minimum_free_diameter_over_thickness=bending_minimum_ratio,
        deflection_minimum_free_diameter_over_thickness=deflection_minimum_ratio,
        poisson_ratio_evidence_band=FLAT_CIRCULAR_PLATE_POISSON_EVIDENCE_BAND,
        envelope_source_reference=FLAT_CIRCULAR_PLATE_ENVELOPE_SOURCE,
        theoretical_radial_failure_pressure_mpa=radial_failure_pressure,
        theoretical_tangential_failure_pressure_mpa=tangential_failure_pressure,
        theoretical_failure_pressure_mpa=theoretical_failure_pressure,
        bending_status="released" if bending_released else "withheld_applicability",
        margin=strength / governing_stress - 1.0 if bending_released else None,
        seat_bearing_stress_mpa=seat_stress,
        theoretical_seat_failure_pressure_mpa=seat_failure_pressure,
        seat_margin=seat_margin,
        validity_violations=tuple(violations),
        notes=(boundary_note, *FLAT_CIRCULAR_PLATE_SCOPE_NOTES, *PLATE_CATEGORY_NOTES[category]),
    )


def _smooth_continuous_mode(
    gamma_z: float,
    load_case: PressureLoadCase,
) -> tuple[float, float]:
    """Minimize NASA Eqs. 20/22 over continuous beta using their stationary polynomial."""
    coefficient = 12.0 * gamma_z**2 / math.pi**4
    if not math.isfinite(coefficient) or coefficient <= 0.0:
        raise ValueError("gamma * Z is outside the finite smooth-cylinder solution range")

    if load_case == "lateral_only":
        def stationarity(y: float) -> float:
            return y**5 - 2.0 * y**4 - 3.0 * coefficient * y + 2.0 * coefficient
    else:
        def stationarity(y: float) -> float:
            return y**5 - y**4 - 3.0 * coefficient * y + coefficient

    lower = 1.0
    upper = 2.0
    while stationarity(upper) <= 0.0:
        upper *= 2.0
        if not math.isfinite(upper):
            raise ValueError("smooth-cylinder mode minimization did not find a finite bracket")
    for _ in range(180):
        midpoint = lower + (upper - lower) / 2.0
        if stationarity(midpoint) <= 0.0:
            lower = midpoint
        else:
            upper = midpoint
    y = lower + (upper - lower) / 2.0
    beta_squared = y - 1.0
    beta = math.sqrt(beta_squared)
    bracket = y**2 + coefficient / y**2
    denominator = beta_squared if load_case == "lateral_only" else beta_squared + 0.5
    return beta, bracket / denominator


def _smooth_short_candidate(
    *,
    load_case: PressureLoadCase,
    curvature_parameter_z: float,
    flexural_rigidity_n_mm: float,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
) -> SmoothCylinderBucklingCandidate:
    """Eqs. 20/22 minimized over beta, with the Eq. 28 correlation factor inside.

    NASA/SP-8007-2020/REV 2 states between Eq. 22 and Eq. 23 that "The term
    gamma^2 has been added to Eq. 20 and Eq. 22 as a correction for the
    difference between theory and test", and Eq. 28 supplies that factor as
    sqrt(gamma) = 0.75. Eq. 23 is introduced as what ky and kp reduce to "For
    gamma*Z > 100", so it is the large-gamma*Z simplification of this branch,
    not the only place the factor applies. Figure 4-3 plots the minimized
    coefficients across gamma*Z, so this branch carries the correlated capacity
    below that boundary rather than a theoretical-only result.
    """
    gamma = SMOOTH_CYLINDER_MODERATE_GAMMA
    gamma_z = gamma * curvature_parameter_z
    _, ideal_coefficient = _smooth_continuous_mode(curvature_parameter_z, load_case)
    beta, coefficient = _smooth_continuous_mode(gamma_z, load_case)
    scale = (
        math.pi**2
        * flexural_rigidity_n_mm
        / (shell_mid_surface_radius_mm * unsupported_length_mm**2)
    )
    ideal_pressure = ideal_coefficient * scale
    correlated_pressure = coefficient * scale
    continuous_waves = (
        beta * math.pi * shell_mid_surface_radius_mm / unsupported_length_mm
    )
    return SmoothCylinderBucklingCandidate(
        regime="short",
        source_equations=("NASA Eq. 19" if load_case == "lateral_only" else "NASA Eq. 21",
                          "NASA Eq. 20" if load_case == "lateral_only" else "NASA Eq. 22",
                          "NASA Eq. 28"),
        correlation_factor_gamma=gamma,
        sqrt_correlation_factor=math.sqrt(gamma),
        gamma_z=gamma_z,
        applicable=gamma_z <= SMOOTH_CYLINDER_SHORT_GAMMA_Z_LIMIT,
        critical_buckling_coefficient=coefficient,
        critical_aspect_ratio_beta=beta,
        continuous_circumferential_wave_count=continuous_waves,
        circumferential_wave_count_n=None,
        ideal_critical_pressure_mpa=ideal_pressure,
        correlated_critical_pressure_mpa=correlated_pressure,
        correlated_critical_circumferential_stress_mpa=(
            correlated_pressure * shell_mid_surface_radius_mm / wall_thickness_mm
        ),
        eq25_simplified_critical_pressure_mpa=None,
        applicability_conditions=(
            "gamma*Z <= 100, below the Eq. 23 simplification boundary",
            "sqrt(gamma)=0.75 from NASA Eq. 28, applied inside Eqs. 20/22",
        ),
    )


def _smooth_moderate_candidate(
    *,
    load_case: PressureLoadCase,
    curvature_parameter_z: float,
    geometry_mode_parameter: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
) -> SmoothCylinderBucklingCandidate:
    gamma = SMOOTH_CYLINDER_MODERATE_GAMMA
    gamma_z = gamma * curvature_parameter_z
    beta, _ = _smooth_continuous_mode(gamma_z, load_case)
    continuous_waves = (
        beta * math.pi * shell_mid_surface_radius_mm / unsupported_length_mm
    )
    radius_thickness = shell_mid_surface_radius_mm / wall_thickness_mm
    length_radius = unsupported_length_mm / shell_mid_surface_radius_mm
    ideal_pressure = (
        0.855
        * elastic_modulus_mpa
        / (
            (1.0 - poisson_ratio**2) ** 0.75
            * radius_thickness**2.5
            * length_radius
        )
    )
    correlated_pressure = ideal_pressure * math.sqrt(gamma)
    # NASA/SP-8007-2020/REV 2, printed p. 27, introduces Eq. 25 with "For
    # nu = 0.316, Eq. 24 further simplifies to", so both the 0.926 coefficient
    # and the single Poisson ratio it is stated for are the source's own; the
    # sqrt(gamma) is printed inside Eq. 25 as it is inside Eq. 24. The source
    # rounds: at nu = 0.316 the Eq. 24 coefficient is 0.855/(1-nu^2)^0.75 =
    # 0.92519, which NASA prints as 0.926, so Eq. 25 stands 0.0873% above
    # Eq. 24 at the one ratio it is stated for. Reporting it beside the Eq. 24
    # capacity keeps that printed value traceable without letting the rounding
    # move a released number, so this is a comparator only and no nu branch.
    eq25_pressure = (
        0.926
        * elastic_modulus_mpa
        * math.sqrt(gamma)
        / (radius_thickness**2.5 * length_radius)
        if math.isclose(poisson_ratio, 0.316, rel_tol=0.0, abs_tol=1.0e-12)
        else None
    )
    boundary = (
        SMOOTH_CYLINDER_MORE_THAN_TWO_WAVE_COEFFICIENT
        * geometry_mode_parameter**2
    )
    return SmoothCylinderBucklingCandidate(
        regime="moderate",
        source_equations=(
            "NASA Eq. 23",
            "NASA Eq. 24",
            *(("NASA Eq. 25",) if eq25_pressure is not None else ()),
            "NASA Eq. 28",
        ),
        correlation_factor_gamma=gamma,
        sqrt_correlation_factor=math.sqrt(gamma),
        gamma_z=gamma_z,
        applicable=(
            gamma_z > SMOOTH_CYLINDER_SHORT_GAMMA_Z_LIMIT
            and gamma_z <= boundary
        ),
        critical_buckling_coefficient=1.04 * math.sqrt(gamma_z),
        critical_aspect_ratio_beta=beta,
        continuous_circumferential_wave_count=continuous_waves,
        circumferential_wave_count_n=None,
        ideal_critical_pressure_mpa=ideal_pressure,
        correlated_critical_pressure_mpa=correlated_pressure,
        correlated_critical_circumferential_stress_mpa=(
            correlated_pressure * radius_thickness
        ),
        eq25_simplified_critical_pressure_mpa=eq25_pressure,
        applicability_conditions=(
            "gamma*Z > 100 for NASA Eq. 23",
            "gamma*Z <= 11.8*(r/t)^2*(1-v^2) for the more-than-two-wave branch",
            "sqrt(gamma)=0.75 from NASA Eq. 28",
        ),
    )


def _smooth_long_candidate(
    *,
    curvature_parameter_z: float,
    geometry_mode_parameter: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
) -> SmoothCylinderBucklingCandidate:
    gamma = SMOOTH_CYLINDER_LONG_GAMMA
    gamma_z = gamma * curvature_parameter_z
    radius_thickness = shell_mid_surface_radius_mm / wall_thickness_mm
    ideal_pressure = (
        elastic_modulus_mpa
        / (4.0 * (1.0 - poisson_ratio**2))
        * (wall_thickness_mm / shell_mid_surface_radius_mm) ** 3
    )
    correlated_pressure = gamma * ideal_pressure
    boundary = (
        SMOOTH_CYLINDER_MORE_THAN_TWO_WAVE_COEFFICIENT
        * geometry_mode_parameter**2
    )
    return SmoothCylinderBucklingCandidate(
        regime="long",
        source_equations=("NASA Eq. 26", "NASA Eq. 27", "NASA Eq. 29"),
        correlation_factor_gamma=gamma,
        sqrt_correlation_factor=math.sqrt(gamma),
        gamma_z=gamma_z,
        applicable=gamma_z >= boundary,
        critical_buckling_coefficient=(
            3.0 * gamma_z / (math.pi**2 * geometry_mode_parameter)
        ),
        critical_aspect_ratio_beta=None,
        continuous_circumferential_wave_count=2.0,
        circumferential_wave_count_n=2,
        ideal_critical_pressure_mpa=ideal_pressure,
        correlated_critical_pressure_mpa=correlated_pressure,
        correlated_critical_circumferential_stress_mpa=(
            correlated_pressure * radius_thickness
        ),
        eq25_simplified_critical_pressure_mpa=None,
        applicability_conditions=(
            "gamma*Z >= 11.8*(r/t)^2*(1-v^2) for the oval n=2 branch",
            "gamma=0.90 from NASA Eq. 29",
        ),
    )


def _roark_case20_probable_minimum(
    *,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    mean_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
) -> tuple[float, int]:
    """Return the Roark case 20 probable-minimum pressure and its lobe count.

    Roark Table 35 case 20 gives the theoretical external pressure of a tube
    with ends held circular as a function of the circumferential lobe count
    ``n``; the theoretical minimum over integer ``n >= 2`` is scaled by the 0.80
    probable-minimum factor. The pressure falls with ``n`` and then rises, so
    the walk stops at the first increase.
    """
    ratio = math.pi * mean_radius_mm / unsupported_length_mm
    stiffness = wall_thickness_mm**2 / (
        12.0 * mean_radius_mm**2 * (1.0 - poisson_ratio**2)
    )

    def pressure(lobes: int) -> float:
        lambda_over_n = ratio / lobes
        n_over_lambda = lobes / ratio
        return (
            elastic_modulus_mpa
            * wall_thickness_mm
            / mean_radius_mm
            / (1.0 + 0.5 * lambda_over_n**2)
            * (
                1.0 / (lobes**2 * (1.0 + n_over_lambda**2) ** 2)
                + lobes**2 * stiffness * (1.0 + lambda_over_n**2) ** 2
            )
        )

    lobes = 2
    minimum = pressure(lobes)
    while (candidate := pressure(lobes + 1)) < minimum:
        minimum = candidate
        lobes += 1
    return SMOOTH_CYLINDER_ROARK_PROBABLE_MINIMUM_FACTOR * minimum, lobes


def _det2(a11: float, a12: float, a21: float, a22: float) -> float:
    return a11 * a22 - a12 * a21


def _det3(
    a11: float,
    a12: float,
    a13: float,
    a21: float,
    a22: float,
    a23: float,
    a31: float,
    a32: float,
    a33: float,
) -> float:
    return (
        a11 * (a22 * a33 - a23 * a32)
        - a12 * (a21 * a33 - a23 * a31)
        + a13 * (a21 * a32 - a22 * a31)
    )


def _ring_stiffened_orthotropic_external_pressure_pcr(
    *,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
    ring_spacing_mm: float,
    ring_area_mm2: float,
    ring_centroid_from_shell_surface_mm: float,
    ring_centroidal_inertia_mm4: float,
    ring_torsional_constant_mm4: float,
    ring_location: str,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    include_ring_torsion: bool,
    max_mode_evaluations: int = RING_SHELL_DEFAULT_MAX_MODE_EVALUATIONS,
) -> RingGlobalBucklingResult:
    """Evaluate NASA Eq. 64/65 with an expanding, evidenced mode search."""
    e_mpa = elastic_modulus_mpa
    v = poisson_ratio
    r_mm = shell_mid_surface_radius_mm
    t_mm = wall_thickness_mm
    length_mm = unsupported_length_mm
    z_sign = 1.0 if ring_location == "external" else -1.0
    z_ring_mm = z_sign * (0.5 * t_mm + ring_centroid_from_shell_surface_mm)
    ring_shear_modulus_mpa = e_mpa / (2.0 * (1.0 + v))
    ring_torsion_contribution_n_mm = (
        ring_shear_modulus_mpa * ring_torsional_constant_mm4 / ring_spacing_mm
        if include_ring_torsion
        else 0.0
    )

    extensional_x = e_mpa * t_mm / (1.0 - v**2)
    extensional_y = extensional_x + e_mpa * ring_area_mm2 / ring_spacing_mm
    extensional_xy = v * e_mpa * t_mm / (1.0 - v**2)
    shear_xy = e_mpa * t_mm / (2.0 * (1.0 + v))

    bending_x = e_mpa * t_mm**3 / (12.0 * (1.0 - v**2))
    bending_y = (
        bending_x
        + e_mpa * ring_centroidal_inertia_mm4 / ring_spacing_mm
        + z_ring_mm**2 * e_mpa * ring_area_mm2 / ring_spacing_mm
    )
    bending_xy = (
        v * e_mpa * t_mm**3 / (6.0 * (1.0 - v**2))
        + e_mpa * t_mm**3 / (6.0 * (1.0 + v))
        + ring_torsion_contribution_n_mm
    )
    # coupling_x, coupling_xy, and shear_coupling_xy are structurally zero for
    # a smeared ring set on one shell surface; they are carried so the
    # determinant terms below stay isomorphic to NASA Eqs. 82-91 as printed.
    coupling_x = 0.0
    coupling_y = z_ring_mm * e_mpa * ring_area_mm2 / ring_spacing_mm
    coupling_xy = 0.0
    shear_coupling_xy = 0.0

    def mode_pressure(axial_half_waves: int, circumferential_lobes: int) -> float | None:
        alpha = axial_half_waves * math.pi / length_mm
        hydrostatic_axial_term = 0.5 * (axial_half_waves * math.pi * r_mm / length_mm) ** 2
        beta = circumferential_lobes / r_mm
        a11 = extensional_x * alpha**2 + shear_xy * beta**2
        a22 = extensional_y * beta**2 + shear_xy * alpha**2
        a33 = (
            bending_x * alpha**4
            + bending_xy * alpha**2 * beta**2
            + bending_y * beta**4
            + extensional_y / r_mm**2
            + 2.0 * coupling_y * beta**2 / r_mm
            + 2.0 * coupling_xy * alpha**2 / r_mm
        )
        a12 = (extensional_xy + shear_xy) * alpha * beta
        a21 = a12
        a13 = (
            extensional_xy * alpha / r_mm
            + coupling_x * alpha**3
            + (coupling_xy + 2.0 * shear_coupling_xy) * alpha * beta**2
        )
        a31 = a13
        a23 = (
            (coupling_xy + 2.0 * shear_coupling_xy) * alpha**2 * beta
            + extensional_y * beta / r_mm
            + coupling_y * beta**3
        )
        a32 = a23
        denominator = _det2(a11, a12, a21, a22)
        if denominator <= 0.0:
            return None
        numerator = _det3(a11, a12, a13, a21, a22, a23, a31, a32, a33)
        mode_term = circumferential_lobes**2 + hydrostatic_axial_term
        pcr_mpa = (r_mm / mode_term) * numerator / denominator
        return pcr_mpa if math.isfinite(pcr_mpa) and pcr_mpa > 0.0 else None

    # The initial bounds scale with both the number of ring spaces in the
    # modeled length and the shell slenderness.  Stability is not considered
    # until the winner is away from the newly added outer strips.
    axial_bound = max(8, int(math.ceil(2.0 * length_mm / ring_spacing_mm)))
    circumferential_bound = max(8, int(math.ceil(2.0 * math.sqrt(r_mm / t_mm))))
    evaluated: dict[tuple[int, int], float] = {}
    iterations: list[RingModeSearchIteration] = []
    previous_best: tuple[int, int, float] | None = None
    stable_confirmations = 0
    best: tuple[int, int, float] | None = None

    while True:
        projected_count = axial_bound * (circumferential_bound - 1)
        if projected_count > max_mode_evaluations:
            termination_reason: Literal[
                "stable_interior_governing_mode",
                "mode_evaluation_limit",
                "no_positive_mode",
            ] = "mode_evaluation_limit"
            converged = False
            break

        newly_evaluated = 0
        for axial_half_waves in range(1, axial_bound + 1):
            for circumferential_lobes in range(2, circumferential_bound + 1):
                key = (axial_half_waves, circumferential_lobes)
                if key in evaluated:
                    continue
                pressure = mode_pressure(axial_half_waves, circumferential_lobes)
                if pressure is not None:
                    evaluated[key] = pressure
                newly_evaluated += 1

        if not evaluated:
            termination_reason = "no_positive_mode"
            converged = False
            break

        (best_m, best_n), best_pressure = min(evaluated.items(), key=lambda item: item[1])
        best = (best_m, best_n, best_pressure)
        frontier_m_start = max(1, int(math.floor(0.75 * axial_bound)) + 1)
        frontier_n_start = max(2, int(math.floor(0.75 * circumferential_bound)) + 1)
        frontier_pressures = [
            pressure
            for (mode_m, mode_n), pressure in evaluated.items()
            if mode_m >= frontier_m_start or mode_n >= frontier_n_start
        ]
        frontier_minimum = min(frontier_pressures)
        governing_mode_below_frontier = (
            best_m < frontier_m_start and best_n < frontier_n_start
        )
        frontier_above = frontier_minimum > best_pressure * (1.0 + 1.0e-10)
        if previous_best is None:
            relative_change = None
            mode_stable = False
        else:
            previous_m, previous_n, previous_pressure = previous_best
            relative_change = abs(best_pressure - previous_pressure) / best_pressure
            mode_stable = best_m == previous_m and best_n == previous_n
        stable_iteration = (
            mode_stable
            and relative_change is not None
            and relative_change <= 1.0e-10
            and governing_mode_below_frontier
            and frontier_above
        )
        stable_confirmations = stable_confirmations + 1 if stable_iteration else 0
        iterations.append(
            RingModeSearchIteration(
                axial_half_wave_bound=axial_bound,
                circumferential_lobe_bound=circumferential_bound,
                newly_evaluated_modes=newly_evaluated,
                cumulative_evaluated_modes=projected_count,
                critical_axial_half_waves_m=best_m,
                critical_circumferential_lobes_n=best_n,
                ideal_critical_pressure_mpa=best_pressure,
                relative_pressure_change=relative_change,
                governing_mode_stable=mode_stable,
                governing_mode_below_frontier=governing_mode_below_frontier,
                frontier_minimum_pressure_mpa=frontier_minimum,
                frontier_above_governing=frontier_above,
            )
        )
        if stable_confirmations >= 2:
            termination_reason = "stable_interior_governing_mode"
            converged = True
            break
        previous_best = best
        axial_bound *= 2
        circumferential_bound *= 2

    ideal_pressure = best[2] if converged and best is not None else None
    return RingGlobalBucklingResult(
        ring_torsion_included=include_ring_torsion,
        converged=converged,
        termination_reason=termination_reason,
        ideal_critical_pressure_mpa=ideal_pressure,
        adjusted_critical_pressure_mpa=(
            ideal_pressure * RING_SHELL_EQ64_ADJUSTMENT_FACTOR
            if ideal_pressure is not None
            else None
        ),
        adjustment_factor=RING_SHELL_EQ64_ADJUSTMENT_FACTOR,
        critical_axial_half_waves_m=best[0] if converged and best is not None else None,
        critical_circumferential_lobes_n=best[1] if converged and best is not None else None,
        evaluated_axial_half_waves=iterations[-1].axial_half_wave_bound if iterations else 0,
        evaluated_circumferential_lobes=(
            iterations[-1].circumferential_lobe_bound if iterations else 0
        ),
        evaluated_mode_count=len(evaluated),
        iterations=tuple(iterations),
        ring_eccentricity_from_shell_mid_surface_mm=z_ring_mm,
        ring_torsion_contribution_n_mm=ring_torsion_contribution_n_mm,
        orthotropic_extensional_x_n_per_mm=extensional_x,
        orthotropic_extensional_y_n_per_mm=extensional_y,
        orthotropic_extensional_xy_n_per_mm=extensional_xy,
        orthotropic_shear_xy_n_per_mm=shear_xy,
        orthotropic_bending_x_n_mm=bending_x,
        orthotropic_bending_y_n_mm=bending_y,
        orthotropic_bending_xy_n_mm=bending_xy,
        orthotropic_coupling_y_n=coupling_y,
    )


def smooth_cylinder_external_pressure_buckling(
    *,
    external_pressure_mpa: float,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    load_case: PressureLoadCase,
    proportional_limit_mpa: float | None = None,
    yield_strength_mpa: float | None = None,
) -> SmoothCylinderBucklingResult:
    """Calculate elastic external-pressure buckling of a smooth cylinder.

    Buckling reads the elastic constants only. ``yield_strength_mpa`` is
    optional and, when given, only bounds the proportional limit; a plastic or
    brittle material has no yield strength to give.
    """
    p_mpa = _positive_finite(external_pressure_mpa, "external_pressure_mpa")
    r_mm = _positive_finite(
        shell_mid_surface_radius_mm,
        "shell_mid_surface_radius_mm",
    )
    t_mm = _positive_finite(wall_thickness_mm, "wall_thickness_mm")
    length_mm = _positive_finite(unsupported_length_mm, "unsupported_length_mm")
    e_mpa = _positive_finite(elastic_modulus_mpa, "elastic_modulus_mpa")
    yield_mpa = (
        _positive_finite(yield_strength_mpa, "yield_strength_mpa")
        if yield_strength_mpa is not None
        else None
    )
    proportional_mpa = (
        _positive_finite(proportional_limit_mpa, "proportional_limit_mpa")
        if proportional_limit_mpa is not None
        else None
    )
    if proportional_mpa is not None and yield_mpa is not None and proportional_mpa > yield_mpa:
        raise ValueError("proportional_limit_mpa must be <= yield_strength_mpa")
    v = _validated_poisson_ratio(poisson_ratio)
    if load_case not in {"lateral_only", "hydrostatic_closed_end"}:
        raise ValueError("load_case must be lateral_only or hydrostatic_closed_end")

    radius_thickness = r_mm / t_mm
    length_radius = length_mm / r_mm
    one_minus_v_squared = 1.0 - v**2
    # Products, not powers: an extreme input overflows to inf, which the check
    # below rejects, where ** would raise OverflowError instead.
    flexural_rigidity = e_mpa * (t_mm * t_mm * t_mm) / (12.0 * one_minus_v_squared)
    z = length_mm * length_mm / (r_mm * t_mm) * math.sqrt(one_minus_v_squared)
    geometry_mode_parameter = radius_thickness * math.sqrt(one_minus_v_squared)
    if not all(
        math.isfinite(value)
        for value in (flexural_rigidity, z, geometry_mode_parameter)
    ):
        raise ValueError("smooth-cylinder dimensionless parameters must be finite")

    boundary = (
        SMOOTH_CYLINDER_MORE_THAN_TWO_WAVE_COEFFICIENT
        * geometry_mode_parameter
        * geometry_mode_parameter
    )
    short_candidate = _smooth_short_candidate(
        load_case=load_case,
        curvature_parameter_z=z,
        flexural_rigidity_n_mm=flexural_rigidity,
        shell_mid_surface_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
        unsupported_length_mm=length_mm,
    )
    moderate_candidate = _smooth_moderate_candidate(
        load_case=load_case,
        curvature_parameter_z=z,
        geometry_mode_parameter=geometry_mode_parameter,
        elastic_modulus_mpa=e_mpa,
        poisson_ratio=v,
        shell_mid_surface_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
        unsupported_length_mm=length_mm,
    )
    long_candidate = _smooth_long_candidate(
        curvature_parameter_z=z,
        geometry_mode_parameter=geometry_mode_parameter,
        elastic_modulus_mpa=e_mpa,
        poisson_ratio=v,
        shell_mid_surface_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
    )
    candidates = (short_candidate, moderate_candidate, long_candidate)

    selected: SmoothCylinderBucklingCandidate | None = None
    release_gate_violations: list[str] = []
    regime: Literal["short", "moderate", "moderate_long_correlation_overlap", "long"]
    gate_status: Literal["released", "withheld_correlation_overlap"]
    if short_candidate.applicable:
        regime = "short"
        source_equations = short_candidate.source_equations
        gate_status = "released"
        selected = short_candidate
    elif moderate_candidate.applicable and long_candidate.applicable:
        regime = "moderate_long_correlation_overlap"
        source_equations = (
            *moderate_candidate.source_equations,
            *long_candidate.source_equations,
        )
        gate_status = "withheld_correlation_overlap"
        release_gate_violations.append(
            "NASA gives no selection or blending rule for the overlap created by gamma=0.5625 "
            "in Eqs. 23-25 and gamma=0.90 in Eqs. 26-27"
        )
    elif moderate_candidate.applicable:
        regime = "moderate"
        source_equations = moderate_candidate.source_equations
        gate_status = "released"
        selected = moderate_candidate
    else:
        # Short and moderate share gamma=0.5625, so they tile gamma*Z with no gap:
        # short holds gamma*Z <= 100, moderate holds 100 < gamma*Z <= boundary, and
        # anything above that has 0.90*Z >= boundary, which is the long branch.
        regime = "long"
        source_equations = long_candidate.source_equations
        gate_status = "released"
        selected = long_candidate

    validity_violations: list[str] = []
    plasticity_pending: str | None = None
    if radius_thickness <= SMOOTH_CYLINDER_MIN_RADIUS_THICKNESS_RATIO:
        validity_violations.append(
            "shell_mid_surface_radius_mm / wall_thickness_mm must be > 10 for the "
            "Roark thin-tube overlap gate"
        )
    if selected is not None:
        if proportional_mpa is None:
            validity_violations.append(
                "proportional_limit_mpa is required to establish elastic applicability for "
                "a released capacity; NASA inelastic corrections are not implemented"
            )
        elif (
            selected.correlated_critical_circumferential_stress_mpa is not None
            and selected.correlated_critical_circumferential_stress_mpa > proportional_mpa
        ):
            if validity_violations:
                # The capacity is withheld on another gate, so the exceedance is one
                # more violation on the withheld record, not a pending release.
                validity_violations.append(
                    "correlated critical circumferential membrane stress exceeds the "
                    "supplied proportional limit; NASA inelastic corrections are not "
                    "implemented"
                )
            else:
                # Plasticity would reduce this capacity, so the released number is an
                # elastic upper bound rather than a withheld result; the scope note
                # carries why NASA Eqs. 30-32 cannot correct it here.
                plasticity_pending = SMOOTH_CYLINDER_PLASTICITY_PENDING_REASON.format(
                    stress=selected.correlated_critical_circumferential_stress_mpa,
                    limit=proportional_mpa,
                )

    capacity_status: Literal[
        "released",
        "released_pending_plasticity",
        "withheld_correlation_overlap",
        "withheld_applicability",
    ]
    if validity_violations:
        capacity_status = "withheld_applicability"
    elif plasticity_pending is not None:
        capacity_status = "released_pending_plasticity"
    else:
        capacity_status = gate_status
    correlated_pressure: float | None = None
    correlated_stress: float | None = None
    if capacity_status_not_withheld(capacity_status) and selected is not None:
        correlated_pressure = selected.correlated_critical_pressure_mpa
        correlated_stress = selected.correlated_critical_circumferential_stress_mpa
    margin = correlated_pressure / p_mpa - 1.0 if correlated_pressure is not None else None
    # A correlated critical stress above the proportional limit makes that capacity an
    # elastic upper bound, so applying the same test to the working stress p*r/t says,
    # with no buckling result, whether every capacity at or above p is such a bound at
    # every unsupported length: only thickness moves this stress.
    working_stress = p_mpa * radius_thickness
    applicability_limit, applicability_basis, elastic_applicability = (
        _elastic_applicability_screen(working_stress, proportional_mpa, yield_mpa)
    )
    roark_pressure, roark_lobes = _roark_case20_probable_minimum(
        elastic_modulus_mpa=e_mpa,
        poisson_ratio=v,
        mean_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
        unsupported_length_mm=length_mm,
    )
    if not math.isfinite(roark_pressure):
        raise ValueError("Roark case 20 probable-minimum pressure must be finite")
    boundary_assumptions = (
        "Simply supported ends: zero radial deflection and zero bending moment.",
        "Eqs. 20/22 use the source's continuous beta minimization with axial half-wave m=1.",
        "Eq. 27 long-cylinder capacity is the axial-invariant oval mode n=2.",
        "Unsupported length is the distance between the idealized circular end supports.",
        "No capacity increase from longitudinal or rotational end restraint is credited.",
    )
    notes = (
        *SMOOTH_CYLINDER_SCOPE_NOTES,
        *release_gate_violations,
        *((plasticity_pending,) if plasticity_pending is not None else ()),
    )
    return SmoothCylinderBucklingResult(
        model_id=SMOOTH_CYLINDER_BUCKLING_MODEL_ID,
        model_version=SMOOTH_CYLINDER_BUCKLING_MODEL_VERSION,
        source_reference=SMOOTH_CYLINDER_BUCKLING_SOURCE,
        comparison_source_reference=SMOOTH_CYLINDER_ROARK_OVERLAP_SOURCE,
        load_case=load_case,
        boundary_condition="simply_supported",
        radius_convention="shell_mid_surface",
        regime=regime,
        capacity_status=capacity_status,
        source_equations=source_equations,
        external_pressure_mpa=p_mpa,
        shell_mid_surface_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
        unsupported_length_mm=length_mm,
        shell_mid_surface_radius_over_thickness=radius_thickness,
        unsupported_length_over_radius=length_radius,
        elastic_modulus_mpa=e_mpa,
        poisson_ratio=v,
        yield_strength_mpa=yield_mpa,
        proportional_limit_mpa=proportional_mpa,
        flexural_rigidity_n_mm=flexural_rigidity,
        curvature_parameter_z=z,
        geometry_mode_parameter=geometry_mode_parameter,
        line_load_sign_convention="positive_compression_magnitude",
        circumferential_line_load_n_per_mm=p_mpa * r_mm,
        axial_line_load_n_per_mm=(
            0.0 if load_case == "lateral_only" else p_mpa * r_mm / 2.0
        ),
        short_regime_gamma_z_boundary=SMOOTH_CYLINDER_SHORT_GAMMA_Z_LIMIT,
        moderate_gamma_z_lower_boundary=SMOOTH_CYLINDER_SHORT_GAMMA_Z_LIMIT,
        moderate_long_boundary_parameter=boundary,
        moderate_long_overlap_start_z=boundary / SMOOTH_CYLINDER_LONG_GAMMA,
        moderate_long_overlap_end_z=boundary / SMOOTH_CYLINDER_MODERATE_GAMMA,
        correlation_factor_gamma=(
            selected.correlation_factor_gamma if selected is not None else None
        ),
        sqrt_correlation_factor=(
            selected.sqrt_correlation_factor if selected is not None else None
        ),
        critical_buckling_coefficient=(
            selected.critical_buckling_coefficient if selected is not None else None
        ),
        critical_aspect_ratio_beta=(
            selected.critical_aspect_ratio_beta if selected is not None else None
        ),
        continuous_circumferential_wave_count=(
            selected.continuous_circumferential_wave_count
            if selected is not None
            else None
        ),
        circumferential_wave_count_n=(
            selected.circumferential_wave_count_n if selected is not None else None
        ),
        ideal_critical_pressure_mpa=(
            selected.ideal_critical_pressure_mpa if selected is not None else None
        ),
        correlated_critical_pressure_mpa=correlated_pressure,
        correlated_critical_circumferential_stress_mpa=correlated_stress,
        working_circumferential_membrane_stress_mpa=working_stress,
        elastic_applicability_limit_mpa=applicability_limit,
        elastic_applicability_limit_basis=applicability_basis,
        elastic_applicability=elastic_applicability,
        margin=margin,
        roark_probable_minimum_factor=SMOOTH_CYLINDER_ROARK_PROBABLE_MINIMUM_FACTOR,
        roark_probable_minimum_pressure_mpa=roark_pressure,
        roark_probable_minimum_lobes_n=roark_lobes,
        candidates=candidates,
        validity_violations=tuple(validity_violations),
        release_gate_violations=tuple(release_gate_violations),
        boundary_assumptions=boundary_assumptions,
        notes=notes,
    )


def ring_stiffened_shell_external_pressure(
    *,
    external_pressure_mpa: float,
    shell_mid_surface_radius_mm: float,
    wall_thickness_mm: float,
    unsupported_length_mm: float,
    ring_spacing_mm: float,
    ring_axial_width_mm: float,
    ring_radial_height_mm: float,
    ring_location: Literal["internal", "external"],
    elastic_modulus_mpa: float,
    poisson_ratio: float,
    proportional_limit_mpa: float | None = None,
    yield_strength_mpa: float | None = None,
    max_mode_evaluations: int = RING_SHELL_DEFAULT_MAX_MODE_EVALUATIONS,
) -> RingShellResult:
    """Return the source-gated rectangular-ring external-pressure calculation.

    ``yield_strength_mpa`` is optional. It bounds the proportional limit as for
    the smooth cylinder, and it stands in as the elastic-applicability limit the
    global mode is screened against when no proportional limit is supplied.
    """

    p_mpa = _positive_finite(external_pressure_mpa, "external_pressure_mpa")
    r_mm = _positive_finite(
        shell_mid_surface_radius_mm,
        "shell_mid_surface_radius_mm",
    )
    t_mm = _positive_finite(wall_thickness_mm, "wall_thickness_mm")
    length_mm = _positive_finite(unsupported_length_mm, "unsupported_length_mm")
    spacing_mm = _positive_finite(ring_spacing_mm, "ring_spacing_mm")
    width_mm = _positive_finite(ring_axial_width_mm, "ring_axial_width_mm")
    height_mm = _positive_finite(ring_radial_height_mm, "ring_radial_height_mm")
    e_mpa = _positive_finite(elastic_modulus_mpa, "elastic_modulus_mpa")
    yield_mpa = (
        _positive_finite(yield_strength_mpa, "yield_strength_mpa")
        if yield_strength_mpa is not None
        else None
    )
    proportional_mpa = (
        _positive_finite(proportional_limit_mpa, "proportional_limit_mpa")
        if proportional_limit_mpa is not None
        else None
    )
    if proportional_mpa is not None and yield_mpa is not None and proportional_mpa > yield_mpa:
        raise ValueError("proportional_limit_mpa must be <= yield_strength_mpa")
    v = _validated_poisson_ratio(poisson_ratio)
    if ring_location not in {"internal", "external"}:
        raise ValueError("ring_location must be internal or external")
    if (
        isinstance(max_mode_evaluations, bool)
        or not isinstance(max_mode_evaluations, int)
        or max_mode_evaluations < 1
    ):
        raise ValueError("max_mode_evaluations must be a positive integer")

    section = rectangular_ring_section_properties(
        axial_width_mm=width_mm,
        radial_height_mm=height_mm,
    )
    area_mm2 = float(section["ring_area_mm2"])
    centroid_mm = float(section["ring_centroid_from_shell_surface_mm"])
    inertia_mm4 = float(section["ring_centroidal_inertia_mm4"])
    torsional_constant_mm4 = float(section["ring_torsional_constant_mm4"])

    validity_violations: list[str] = []
    if r_mm / t_mm <= RING_SHELL_MIN_RADIUS_THICKNESS_RATIO:
        validity_violations.append(
            "shell_mid_surface_radius_mm / wall_thickness_mm must be > 10 for the "
            "shared Roark thin-shell overlap gate; NASA states a thin-shell "
            "assumption but no lower t/r cutoff"
        )
    if width_mm >= spacing_mm:
        validity_violations.append(
            "ring_axial_width_mm must be less than ring_spacing_mm so adjacent physical "
            "rectangular rings do not overlap"
        )
    if spacing_mm > length_mm:
        validity_violations.append(
            "ring_spacing_mm must not exceed unsupported_length_mm so at least one ring "
            "bay fits between the supports; the smeared ring stiffness and the inter-ring "
            "check both read the spacing as a bay length inside that span"
        )
    shell_internal_radius_mm = r_mm - 0.5 * t_mm
    if ring_location == "internal" and height_mm >= shell_internal_radius_mm:
        validity_violations.append(
            "ring_radial_height_mm must be less than the shell internal radius "
            "shell_mid_surface_radius_mm - wall_thickness_mm / 2 so an internal "
            "rectangular ring preserves a positive clear bore"
        )

    ring_global_inputs: dict[str, Any] = dict(
        shell_mid_surface_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
        unsupported_length_mm=length_mm,
        ring_spacing_mm=spacing_mm,
        ring_area_mm2=area_mm2,
        ring_centroid_from_shell_surface_mm=centroid_mm,
        ring_centroidal_inertia_mm4=inertia_mm4,
        ring_torsional_constant_mm4=torsional_constant_mm4,
        ring_location=ring_location,
        elastic_modulus_mpa=e_mpa,
        poisson_ratio=v,
        max_mode_evaluations=max_mode_evaluations,
    )
    without_torsion = _ring_stiffened_orthotropic_external_pressure_pcr(
        include_ring_torsion=False, **ring_global_inputs
    )
    with_torsion = _ring_stiffened_orthotropic_external_pressure_pcr(
        include_ring_torsion=True, **ring_global_inputs
    )
    inter_ring = smooth_cylinder_external_pressure_buckling(
        external_pressure_mpa=p_mpa,
        shell_mid_surface_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
        unsupported_length_mm=spacing_mm,
        elastic_modulus_mpa=e_mpa,
        poisson_ratio=v,
        yield_strength_mpa=yield_mpa,
        proportional_limit_mpa=proportional_mpa,
        load_case="hydrostatic_closed_end",
    )

    capacity_status: Literal[
        "advisory",
        "withheld_invalid_applicability",
        "withheld_nonconvergence",
    ]
    if validity_violations:
        capacity_status = "withheld_invalid_applicability"
    elif not with_torsion.converged or not without_torsion.converged:
        capacity_status = "withheld_nonconvergence"
    else:
        capacity_status = "advisory"

    torsion_ideal_effect: float | None = None
    torsion_adjusted_effect: float | None = None
    torsion_relative_effect: float | None = None
    torsion_mode_change: bool | None = None
    if (
        without_torsion.ideal_critical_pressure_mpa is not None
        and with_torsion.ideal_critical_pressure_mpa is not None
        and without_torsion.adjusted_critical_pressure_mpa is not None
        and with_torsion.adjusted_critical_pressure_mpa is not None
    ):
        torsion_ideal_effect = (
            with_torsion.ideal_critical_pressure_mpa
            - without_torsion.ideal_critical_pressure_mpa
        )
        torsion_adjusted_effect = (
            with_torsion.adjusted_critical_pressure_mpa
            - without_torsion.adjusted_critical_pressure_mpa
        )
        torsion_relative_effect = (
            torsion_ideal_effect / without_torsion.ideal_critical_pressure_mpa
        )
        torsion_mode_change = (
            with_torsion.critical_axial_half_waves_m,
            with_torsion.critical_circumferential_lobes_n,
        ) != (
            without_torsion.critical_axial_half_waves_m,
            without_torsion.critical_circumferential_lobes_n,
        )

    # The global mode's counterpart of the smooth kernel's plasticity gate. NASA
    # gives plasticity factors for unstiffened cylinders only, so an over-limit
    # smeared-orthotropic capacity is labelled an elastic upper bound rather than
    # corrected or withheld; this model releases nothing either way.
    global_pressure = with_torsion.adjusted_critical_pressure_mpa
    global_stress = None if global_pressure is None else global_pressure * r_mm / t_mm
    applicability_limit, applicability_basis, global_applicability = (
        _elastic_applicability_screen(global_stress, proportional_mpa, yield_mpa)
    )
    global_plasticity_pending: str | None = None
    if global_applicability == "exceeded":
        if capacity_status == "advisory":
            global_plasticity_pending = RING_SHELL_GLOBAL_PLASTICITY_PENDING_REASON.format(
                stress=global_stress,
                basis=applicability_basis.replace("_", " "),
                limit=applicability_limit,
            )
        elif validity_violations:
            # The record is withheld on another gate, so the exceedance is one
            # more violation on the withheld record -- not a pending-validation
            # label on an advisory pressure this result does not publish. The
            # smooth kernel applies the same rule to its release gate.
            validity_violations.append(
                "the global Eq. 64/65 capacity implies a shell circumferential membrane "
                "stress above the supplied elastic applicability limit; NASA inelastic "
                "corrections are not implemented for the smeared orthotropic mode"
            )

    # Every candidate pressure is an elastic upper bound on its mode, so the
    # minimum over all of them is the tightest bound the model can state;
    # dropping a labelled bound could only raise it.
    advisory_candidates: list[tuple[str, float, RingShellAdvisoryStatus]] = []
    if capacity_status == "advisory" and global_pressure is not None:
        advisory_candidates.append(
            (
                "global_eq64_with_eq91_ring_torsion",
                global_pressure,
                RING_SHELL_ADVISORY_STATUS_BY_APPLICABILITY[global_applicability],
            )
        )
    if (
        capacity_status == "advisory"
        and capacity_status_not_withheld(inter_ring.capacity_status)
        and inter_ring.correlated_critical_pressure_mpa is not None
    ):
        advisory_candidates.append(
            (
                "inter_ring_smooth_shell",
                inter_ring.correlated_critical_pressure_mpa,
                # A KeyError here is a new non-withheld status the advisory
                # taxonomy has not classified yet; fail loudly over mislabeling.
                RING_SHELL_ADVISORY_STATUS_BY_INTER_RING_STATUS[
                    inter_ring.capacity_status
                ],
            )
        )
    if advisory_candidates:
        advisory_mode, advisory_pressure, advisory_status = min(
            advisory_candidates, key=lambda item: item[1]
        )
        advisory_margin = advisory_pressure / p_mpa - 1.0
    else:
        advisory_mode = None
        advisory_status = None
        advisory_pressure = None
        advisory_margin = None

    mode_dispositions = (
        RingModeDisposition(
            mode="global_ring_stiffened_shell_eq64_eq91",
            disposition="implemented_advisory",
            source_reference=RING_SHELL_SOURCE,
            basis=(
                "Equation and rectangular-section mapping are verified and DTMB-compared, but "
                "NASA reports 10-40% low-lobe theory error and gives no numeric Eq. 64/Eq. 66 "
                "finite-to-long transition; in-service pressure-hull use is not justified."
            ),
        ),
        RingModeDisposition(
            mode="inter_ring_shell_buckling",
            disposition="implemented_advisory",
            source_reference=SMOOTH_CYLINDER_BUCKLING_SOURCE,
            basis=(
                "The source-gated smooth-shell method is evaluated over ring center-to-center "
                "spacing with ideal simply supported circular lines; its own capacity_status "
                f"is {inter_ring.capacity_status}."
            ),
        ),
        RingModeDisposition(
            mode="long_cylinder_global_eq66_transition",
            disposition="external_blocker",
            source_reference="NASA/SP-8007-2020/REV 2 Eq. 66, p. 37",
            basis=(
                "NASA says Eq. 66 replaces Eq. 64 for long cylinders but supplies no numeric "
                "transition criterion; the calculation therefore does not claim all-length coverage."
            ),
        ),
        RingModeDisposition(
            mode="separate_frame_inertia_rule",
            disposition="not_applicable",
            source_reference="NASA/SP-8007-2020/REV 2 Eq. 90, p. 42",
            basis=(
                "The selected NASA basis uses the physical ring's centroidal I_r plus z_r^2 A_r "
                "directly in global stiffness and does not prescribe a separate minimum-inertia rule."
            ),
        ),
        RingModeDisposition(
            mode="web_and_flange_local_slenderness",
            disposition="not_applicable",
            source_reference=RING_SHELL_SECTION_SOURCE,
            basis="The only supported ring is a solid rectangle; it has no separate web or flange.",
        ),
        RingModeDisposition(
            mode="classification_inter_stiffener_strength",
            disposition="not_applicable",
            source_reference="classification-society rules, no edition retained",
            basis=(
                "No classification-society route is retained because no exact edition, clause, "
                "equation, and applicability basis was established."
            ),
        ),
        RingModeDisposition(
            mode="ring_material_strength_and_crippling",
            disposition="external_blocker",
            source_reference="NASA/SP-8007-2020/REV 2, orthotropic-cylinder scope, p. 34",
            basis=(
                "NASA requires stiffener buckling/crippling investigation; a source-verified local "
                "stress model and attachment restraint are not available for the current geometry."
            ),
        ),
        RingModeDisposition(
            mode="frame_tripping_or_out_of_plane_rolling",
            disposition="external_blocker",
            source_reference="NASA/SP-8007-2020/REV 2, ring-frame guidance, p. 58",
            basis="Discrete nonlinear shell/frame analysis or test evidence is required.",
        ),
        RingModeDisposition(
            mode="attachment_weld_and_fabrication_effects",
            disposition="external_blocker",
            source_reference="NASA/SP-8007-2020/REV 2, joints and discontinuities, p. 57",
            basis=(
                "The public geometry has no weld profile, heat-affected-zone properties, residual "
                "stress, or fabrication-tolerance inputs."
            ),
        ),
        RingModeDisposition(
            mode="local_global_interaction",
            disposition="external_blocker",
            source_reference="NASA/SP-8007-2020/REV 2, smeared-stiffener limitations, pp. 44 and 58",
            basis="NASA directs detailed nonlinear analysis or tests for interaction effects.",
        ),
    )
    notes = (
        "The 0.75 multiplier is NASA's recommendation immediately following Eq. 68; it is not tuned to DTMB.",
        "The shell radius is explicitly the shell mid-surface radius, consistent with the Eq. 82-91 reference surface.",
        "I_r is centroidal; Eq. 90 adds the separate z_r^2 A_r parallel-axis term.",
        "J_r is the exact Saint-Venant constant for the same solid rectangle used by geometry and mass.",
        "The inter-ring ideal supports are ring center lines; no end-restraint capacity increase is credited.",
        "advisory_governing_mode is the minimum over advisory_candidate_modes, which admits "
        "every mode whose pressure was not withheld, one labelled an elastic upper bound "
        "included, because plasticity could only reduce that elastic estimate. A mode absent "
        "from the list was withheld rather than compared, so read the list before reading "
        "advisory_margin; capacity_status and inter_ring_shell_buckling.capacity_status say "
        "which withheld it.",
        "advisory_governing_status describes the selected mode only, so read "
        "global_elastic_applicability alongside it: the global capacity can stand above the "
        "material limit while a lower inter-ring capacity wins the minimum. Neither pressure "
        "is a rigorous bound on the real structure; NASA's 10-40% low-lobe theory error and "
        "the recommended 0.75 factor keep both advisory elastic estimates.",
        GENERAL_INSTABILITY_SMEARED_NOTE,
        GENERAL_INSTABILITY_SCOPE_NOTE,
        *((global_plasticity_pending,) if global_plasticity_pending is not None else ()),
    )
    return RingShellResult(
        model_id=RING_SHELL_MODEL_ID,
        model_version=RING_SHELL_MODEL_VERSION,
        source_reference=RING_SHELL_SOURCE,
        section_source_reference=RING_SHELL_SECTION_SOURCE,
        benchmark_source_reference=RING_SHELL_BENCHMARK_SOURCE,
        capacity_status=capacity_status,
        load_case="hydrostatic_closed_end",
        boundary_condition="simply_supported",
        radius_convention="shell_mid_surface",
        external_pressure_mpa=p_mpa,
        shell_mid_surface_radius_mm=r_mm,
        wall_thickness_mm=t_mm,
        unsupported_length_mm=length_mm,
        ring_spacing_mm=spacing_mm,
        ring_location=ring_location,
        elastic_modulus_mpa=e_mpa,
        poisson_ratio=v,
        yield_strength_mpa=yield_mpa,
        proportional_limit_mpa=proportional_mpa,
        ring_section_type="solid_rectangle",
        ring_axial_width_mm=width_mm,
        ring_radial_height_mm=height_mm,
        ring_area_mm2=area_mm2,
        ring_centroid_from_shell_surface_mm=centroid_mm,
        ring_centroidal_inertia_mm4=inertia_mm4,
        ring_torsional_constant_mm4=torsional_constant_mm4,
        ring_eccentricity_from_shell_mid_surface_mm=(
            without_torsion.ring_eccentricity_from_shell_mid_surface_mm
        ),
        global_without_ring_torsion=without_torsion,
        global_with_ring_torsion=with_torsion,
        torsion_ideal_pressure_effect_mpa=torsion_ideal_effect,
        torsion_adjusted_pressure_effect_mpa=torsion_adjusted_effect,
        torsion_relative_pressure_effect=torsion_relative_effect,
        torsion_changes_governing_mode=torsion_mode_change,
        global_critical_circumferential_membrane_stress_mpa=global_stress,
        elastic_applicability_limit_mpa=applicability_limit,
        elastic_applicability_limit_basis=applicability_basis,
        global_elastic_applicability=global_applicability,
        inter_ring_shell_buckling=inter_ring,
        advisory_candidate_modes=tuple(mode for mode, _, _ in advisory_candidates),
        advisory_governing_mode=advisory_mode,
        advisory_governing_status=advisory_status,
        advisory_governing_pressure_mpa=advisory_pressure,
        advisory_margin=advisory_margin,
        validity_violations=tuple(validity_violations),
        mode_dispositions=mode_dispositions,
        notes=notes,
    )
