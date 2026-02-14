#!/usr/bin/env python3
"""
ORACLE V6.0 "THETA" - POTENTIAL TEMPERATURE THERMODYNAMICS
===========================================================

V6.0 FUNDAMENTAL REWRITE (January 2026):
-----------------------------------------
This version addresses the core thermodynamic paradox identified by the
Gemini + Five + Claude ensemble analysis:

THE PROBLEM (V5.x):
    The Boussinesq framework is incompressible (∇·u = 0), meaning parcels
    cannot expand. But we were applying explicit adiabatic cooling as if
    they could. This created "phantom mass" - the pressure solver saw
    artificially dense air in updrafts, killing the storm.
    
    Setting adiabatic_rate=0 removed this brake but also removed all
    thermodynamic constraint, causing explosive unrealistic intensification.

THE SOLUTION (V6.0):
    Prognose POTENTIAL TEMPERATURE PERTURBATION (θ′) instead of temperature.
    
    θ_total(x,y,z,t) = θ₀(z) + θ′(x,y,z,t)
    
    Where θ₀(z) is a fixed reference profile (stably stratified).
    
    The evolution equation becomes:
        Dθ′/Dt = -w(dθ₀/dz) + (θ/T)(Lv/Cp)·condensation + diffusion + surface_flux
    
    Buoyancy is computed from perturbation:
        b = g × θ′ / θ₀(z)
    
    This naturally captures:
    - Adiabatic cooling (implicit in θ conservation)
    - Atmospheric stability (θ₀ increases with height)
    - Equilibrium levels (updrafts stop when θ′ → 0)

KEY CHANGES FROM V5.3.6:
    1. Prognostic variable: T (°C) → θ′ (K perturbation)
    2. Reference state: θ₀(z) linear profile, P(z) exponential
    3. Adiabatic cooling: explicit term → stratification source term (-w dθ₀/dz)
    4. Buoyancy: T-based with clamps → θ′-based (physical limits from θ₀)
    5. Diagnostic T: computed from θ for compatibility with tracker/visualizer
    6. Governor toggles: explicit flags to disable artificial limiters

NUMERICAL COMPATIBILITY:
    The solver remains triply-periodic (FFT in x,y,z). By prognosing θ′
    (perturbation) instead of total θ, we avoid the periodicity problem
    where high-θ air would wrap from tropopause to surface.

Theory: Gemini Deep Research (Boussinesq-θ analysis)
Architecture: Five (GPT-5.2 Pro Research) + Claude (Opus 4.5)
Implementation: Claude (Opus 4.5)
Testing: Justin

References:
    - Emanuel (1994): Atmospheric Convection
    - Markowski & Richardson (2010): Mesoscale Meteorology
    - CM1 model documentation (Bryan, NCAR)
"""

import argparse
import sys
from datetime import datetime

def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Oracle V6.0 "THETA" - Potential Temperature Thermodynamics',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
V6.0 Key Changes:
  • Prognostic: T → θ′ (potential temperature perturbation)
  • Stratification: -w dθ₀/dz (replaces adiabatic cooling)
  • Buoyancy: b = g θ′/θ₀ (no artificial clamps)
  • Reference: θ₀(z) = 300K + 4K/km (tunable)

Examples:
  python world_woe_main_V6_THETA.py --pure-physics --frames 50000
  python world_woe_main_V6_THETA.py --no-velocity-governor --frames 100000
        """
    )
    
    # Basic configuration
    parser.add_argument('--pure-physics', action='store_true',
                       help='Disable Oracle nudging')
    parser.add_argument('--advection-order', type=int, default=3)
    parser.add_argument('--sponge-strength', type=float, default=0.003)
    parser.add_argument('--smagorinsky-cs', type=float, default=0.17)
    parser.add_argument('--storm', type=str, default='HUGO')
    parser.add_argument('--year', type=int, default=1989)
    parser.add_argument('--frames', type=int, default=100000)
    parser.add_argument('--resolution', type=int, default=128)
    
    # =========================================================================
    # V6.20 VISUALIZATION: Track plots and wind field snapshots
    # =========================================================================
    parser.add_argument('--plot-interval', type=int, default=7200,
                       help='Frames between plot saves (default=7200, ~2 sim hours)')
    parser.add_argument('--track-plot', action='store_true',
                       help='Generate track plot at end of simulation')
    parser.add_argument('--wind-plots', action='store_true',
                       help='Generate wind field snapshots during simulation')
    parser.add_argument('--all-plots', action='store_true',
                       help='Enable all visualization (track + wind plots)')
    
    # V6 THETA: Reference state configuration
    parser.add_argument('--theta-surface', type=float, default=300.0,
                       help='Surface potential temperature [K] (default=300)')
    parser.add_argument('--gamma-theta', type=float, default=4.0,
                       help='Potential temperature lapse rate [K/km] (default=4.0)')
    parser.add_argument('--scale-height', type=float, default=8500.0,
                       help='Pressure scale height [m] (default=8500)')
    
    # V6 THETA: Warm core initialization
    parser.add_argument('--warm-core-theta-prime', type=float, default=5.0,
                       help='Initial warm core θ′ anomaly [K] (default=5.0)')
    parser.add_argument('--base-humidity', type=float, default=0.018,
                       help='Base specific humidity [kg/kg]')
    
    # V6 THETA: Governor toggles (Five's recommendation)
    parser.add_argument('--no-flux-governor', action='store_true',
                       help='Disable surface flux throttle ramp')
    parser.add_argument('--no-wisdom', action='store_true',
                       help='Disable WISDOM dampening factor')
    parser.add_argument('--no-velocity-governor', action='store_true',
                       help='Disable CoreSolver velocity damping/clamp')
    parser.add_argument('--no-thermo-firewalls', action='store_true',
                       help='Disable temperature/condensation safety limits')
    parser.add_argument('--fully-unconstrained', action='store_true',
                       help='Disable ALL governors (DANGER MODE)')
    
    # Legacy V5 parameters (kept for compatibility but may be ignored)
    parser.add_argument('--buoyancy-cap', type=float, default=0.5,
                       help='[LEGACY] Buoyancy cap - ignored in V6 unless firewalls enabled')
    parser.add_argument('--max-updraft', type=float, default=50.0,
                       help='[LEGACY] Max updraft - ignored in V6 unless firewalls enabled')
    parser.add_argument('--max-temp-anomaly', type=float, default=15.0,
                       help='[LEGACY] Max temp anomaly - ignored in V6 unless firewalls enabled')
    
    # =========================================================================
    # V6.2: ENSEMBLE-IDENTIFIED INHIBITOR CONTROLS
    # Based on Five + Gemini analysis (January 2026)
    # =========================================================================
    
    # Priority 1: Turbulence - The "Molasses Atmosphere" Fix
    parser.add_argument('--resolution-boost', type=float, default=1500.0,
                       help='Smagorinsky resolution boost factor (default=1500, try 300/150/75)')
    
    # Priority 2: Stratification - The "Buoyancy Tax" Fix  
    parser.add_argument('--moist-floor', type=float, default=0.3,
                       help='Minimum moist factor in saturated updrafts (default=0.3, try 0.0-0.1)')
    parser.add_argument('--updraft-only-moist', action='store_true',
                       help='Apply moist reduction ONLY in updrafts (w>0), not subsidence')
    
    # Priority 3: Moisture - The "Premature Saturation" Fix
    parser.add_argument('--core-rh-init', type=float, default=0.95,
                       help='Initial core relative humidity (default=0.95, try 0.82-0.85)')
    
    # V6.2: θ′ stability controls
    parser.add_argument('--theta-prime-max', type=float, default=50.0,
                       help='Upper bound for θ′ sanity check [K] (default=50, try 75-100)')
    parser.add_argument('--theta-prime-min', type=float, default=-50.0,
                       help='Lower bound for θ′ sanity check [K] (default=-50, try -75 to -100)')
    
    # =========================================================================
    # V6.3 SUSTAIN: INTENSITY MAINTENANCE CONTROLS
    # Based on Gemini analysis of "Burn Hot, Burn Short" decay pattern
    # =========================================================================
    
    # WISHE Boosting (Ck/Cd correction)
    parser.add_argument('--wishe-boost', action='store_true',
                       help='Enable Dynamic WISHE Boosting to maintain Ck/Cd > 1.2')
    parser.add_argument('--wishe-boost-max', type=float, default=1.4,
                       help='Maximum WISHE boost factor at high winds (default=1.4)')
    parser.add_argument('--wishe-wind-min', type=float, default=15.0,
                       help='Wind speed (m/s) where WISHE boost begins (default=15.0)')
    parser.add_argument('--wishe-wind-max', type=float, default=40.0,
                       help='Wind speed (m/s) where WISHE boost reaches maximum (default=40.0)')
    
    # =========================================================================
    # V6.15 STEERING: Translation Speed Fix
    # =========================================================================
    parser.add_argument('--steering-multiplier', type=float, default=1.0,
                       help='Multiply ERA5 steering winds by this factor (default=1.0)')
    parser.add_argument('--beta-drift', action='store_true',
                       help='Add beta drift component to steering (2-3 m/s NW in NH)')
    parser.add_argument('--beta-drift-speed', type=float, default=2.5,
                       help='Beta drift magnitude in m/s at 15°N (default=2.5)')
    parser.add_argument('--beta-drift-lat-scale', type=float, default=0.05,
                       help='V6.17: Beta drift increase per degree latitude above 15° (default=0.05 = 5%%)')
    
    # =========================================================================
    # V6.21 BETA FIX: Physically Correct Beta Drift (Gemini Analysis)
    # =========================================================================
    parser.add_argument('--steering-floor', type=float, default=3.0,
                       help='V6.21: Minimum steering speed in m/s to prevent stalling (default=3.0)')
    parser.add_argument('--no-steering-floor', action='store_true',
                       help='V6.21: Disable steering speed floor')
    parser.add_argument('--no-intensity-scaling', action='store_true',
                       help='V6.21: Disable Fiorino-Elsberry intensity scaling for beta drift')
    parser.add_argument('--no-longitude-scaling', action='store_true',
                       help='V6.21: Disable longitude-dependent beta weakening in western Caribbean')
    
    # =========================================================================
    # V6.22 STEERING FIX: Continuous Integration + Confidence Weighting (Five)
    # =========================================================================
    parser.add_argument('--steer-ref', type=float, default=6.0,
                       help='V6.22: Reference ERA5 speed for beta confidence weighting (default=6.0 m/s)')
    parser.add_argument('--no-basin-damping', action='store_true',
                       help='V6.22: Disable Gulf/Caribbean basin damping for beta drift')
    parser.add_argument('--no-confidence-weighting', action='store_true',
                       help='V6.22: Disable ERA5-based confidence weighting for beta drift')
    
    # =========================================================================
    # V6.23 DEEP LAYER MEAN (DLM) STEERING FIX (Gemini's Analysis)
    # Fixes "kinematically shallow despite thermodynamically deep" problem
    # =========================================================================
    parser.add_argument('--dlm-scale', type=float, default=1.0,
                       help='V6.23: DLM scaling factor (default=1.0, was 0.55 which weakened steering)')
    parser.add_argument('--dlm-inner-radius', type=float, default=300.0,
                       help='V6.23: Inner radius for DLM doughnut filter in km (default=300, was 225)')
    parser.add_argument('--no-h3-boost', action='store_true',
                       help='V6.23: Disable automatic H3+ intensity-aware beta boost and damping disable')
    
    # =========================================================================
    # V6.16 STEERING INJECTION: Pressure Solver Fix (Gemini's Analysis)
    # Injects ERA5 steering into fluid dynamics, not just domain motion
    # =========================================================================
    parser.add_argument('--steering-injection', action='store_true',
                       help='Inject ERA5 steering into pressure solver (fixes treadmill effect)')
    
    # =========================================================================
    # V6.18 ANNULAR STEERING: Vortex Contamination Fix (Kimi Swarm)
    # Sample steering from annulus excluding vortex core
    # =========================================================================
    parser.add_argument('--annular-steering', action='store_true',
                       help='Sample ERA5 steering from annulus (r=200-600km) excluding vortex core')
    parser.add_argument('--annular-inner-km', type=float, default=200.0,
                       help='Inner radius of steering annulus in km (default=200)')
    parser.add_argument('--annular-outer-km', type=float, default=600.0,
                       help='Outer radius of steering annulus in km (default=600)')
    
    # Cold Anomaly Diffusion (Anti-Crash)
    parser.add_argument('--cold-diffusion', action='store_true',
                       help='Enable selective diffusion of cold anomalies (θ′ < -4K)')
    parser.add_argument('--cold-diffusion-strength', type=float, default=0.05,
                       help='Diffusivity coefficient for cold anomalies (default=0.05)')
    
    # =========================================================================
    # V6.4 SINK: RADIATIVE COOLING + MEAN REMOVAL (Five's Fix)
    # Addresses runaway θ′ accumulation in periodic domain
    # =========================================================================
    parser.add_argument('--radiative-cooling', action='store_true',
                       help='Enable Newtonian radiative cooling (θ′ relaxation)')
    parser.add_argument('--tau-rad', type=float, default=86400.0,
                       help='Radiative cooling timescale [seconds] (default=86400 = 1 day)')
    parser.add_argument('--dynamic-cooling', action='store_true',
                       help='Enable dynamic τ_rad that scales with θ′ (Gemini V6.6 fix)')
    parser.add_argument('--tau-rad-min', type=float, default=3600.0,
                       help='Minimum τ_rad for dynamic cooling [seconds] (default=3600 = 1 hour)')
    parser.add_argument('--theta-scale', type=float, default=20.0,
                       help='θ′ scale for dynamic cooling [K] (default=20 K)')
    
    # V7.0 BETTS-MILLER: Relaxed convective adjustment (replaces instant saturation)
    parser.add_argument('--betts-miller', action='store_true',
                       help='Use Betts-Miller relaxed convective adjustment instead of instant saturation')
    parser.add_argument('--tau-bm', type=float, default=900.0,
                       help='Betts-Miller relaxation timescale [seconds] (default=900 = 15 min)')
    parser.add_argument('--bm-reference-rh', type=float, default=0.90,
                       help='BM reference profile target RH (default=0.90)')
    parser.add_argument('--bm-taper-start', type=float, default=200.0,
                       help='BM taper start height [m] — zero BM tendency below this (default=200)')
    parser.add_argument('--bm-taper-full', type=float, default=2200.0,
                       help='BM taper full height [m] — full BM tendency above this (default=2200)')
    parser.add_argument('--bm-taper-power', type=float, default=1.0,
                       help='BM taper shape exponent (1.0=linear, 2.0=quadratic, default=1.0)')
    parser.add_argument('--flux-depth', type=float, default=100.0,
                       help='Effective BL flux depth [m] — decouples surface flux from grid dz (default=100)')
    parser.add_argument('--precip-efficiency', type=float, default=0.25,
                       help='Fraction of latent heat retained as θ′ warming (default=0.25). '
                            'Implicitly represents precipitation cooling, outflow heat export, '
                            'and sub-grid radiative losses. Real hurricanes: 0.20-0.30.')
    parser.add_argument('--warm-rain', action='store_true',
                       help='Enable surface saturation cap (warm rain). Caps q at a multiple of q_sat '
                            'at the surface — excess moisture immediately precipitates, releasing latent '
                            'heat scaled by precip-efficiency. Prevents unphysical supersaturation '
                            'from low-level moisture convergence.')
    parser.add_argument('--warm-rain-cap', type=float, default=1.5,
                       help='Surface moisture cap as multiple of q_sat (default=1.5). At 15km grid '
                            'spacing, the 1250m surface cell stores BL moisture that would occupy '
                            '50-500m in reality. 1.5× compensates for this resolution effect. '
                            '1.0 = hard physical cap, 2.0 = permissive.')
    
    parser.add_argument('--mean-removal', action='store_true',
                       help='Remove horizontal mean θ′ at each level (prevents domain drift)')
    parser.add_argument('--environment-relax', action='store_true',
                       help='Relax θ′ to zero outside storm radius (mimics ventilation)')
    parser.add_argument('--relax-radius', type=float, default=300.0,
                       help='Radius [km] outside which to relax θ′ (default=300)')
    parser.add_argument('--relax-tau', type=float, default=3600.0,
                       help='Relaxation timescale [seconds] outside storm (default=3600 = 1 hour)')
    
    # =========================================================================
    # V6.5 NUMERICS: MONOTONIC ADVECTION + FLUX THROTTLE (Gemini's Fix)
    # Addresses cubic interpolation overshoot causing numerical instability
    # =========================================================================
    parser.add_argument('--monotonic-advection', action='store_true',
                       help='Enable quasi-monotonic limiter on advection (prevents Gibbs overshoot)')
    parser.add_argument('--flux-throttle', action='store_true',
                       help='Disable WISHE boost when dθ′/dt exceeds threshold (prevents runaway)')
    parser.add_argument('--flux-throttle-threshold', type=float, default=5.0,
                       help='Max dθ′/dt [K/min] before throttling WISHE (default=5.0)')
    
    # =========================================================================
    # V6.7 PROPORTIONAL: INTEGRAL FLUX THROTTLE (Gemini's Fix)
    # Addresses binary throttle causing "fuel cutoff → collapse" cycle
    # =========================================================================
    parser.add_argument('--proportional-throttle', action='store_true',
                       help='Enable proportional (not binary) WISHE throttling (V6.7)')
    parser.add_argument('--theta-prime-soft-limit', type=float, default=60.0,
                       help='θ′ value [K] where proportional throttle begins (default=60)')
    parser.add_argument('--theta-prime-hard-limit', type=float, default=100.0,
                       help='θ′ value [K] where WISHE fully disabled (default=100)')
    parser.add_argument('--moisture-floor', type=float, default=0.0001,
                       help='Minimum specific humidity [kg/kg] to prevent negative q (default=0.0001)')
    
    return parser.parse_args()


def print_configuration_banner(args, config):
    print("=" * 80)
    print("  ORACLE V6.3 'SUSTAIN' - INTENSITY MAINTENANCE FIX")
    print("=" * 80)
    print(f"  Storm: {args.storm} ({args.year}) | Frames: {args.frames:,}")
    print("")
    print("  ★★★ V6.2: THREE INHIBITORS ADDRESSED (Five + Gemini) ★★★")
    print("")
    print("  PRIORITY 1 - TURBULENCE ('Molasses Atmosphere'):")
    print(f"    • Resolution Boost: {config['resolution_boost']:.0f} (default=1500)")
    if config['resolution_boost'] < 1500:
        print(f"    • ⚡ REDUCED from 1500 → {config['resolution_boost']:.0f}")
    print("")
    print("  PRIORITY 2 - STRATIFICATION ('Buoyancy Tax'):")
    print(f"    • Moist Floor: {config['moist_floor']:.2f} (default=0.3)")
    print(f"    • Updraft-Only: {'✅ YES' if config['updraft_only_moist'] else '❌ NO'}")
    if config['moist_floor'] < 0.3 or config['updraft_only_moist']:
        print(f"    • ⚡ More permissive moist stratification")
    print("")
    print("  PRIORITY 3 - MOISTURE ('Premature Saturation'):")
    print(f"    • Core RH Init: {config['core_rh_init']*100:.0f}% (default=95%)")
    if config['core_rh_init'] < 0.95:
        print(f"    • ⚡ Lower init RH → stronger WISHE fuel gradient")
    print("")
    print("  θ′ STABILITY BOUNDS:")
    print(f"    • Max θ′: {config['theta_prime_max']:.0f} K (default=50)")
    print(f"    • Min θ′: {config['theta_prime_min']:.0f} K (default=-50)")
    if config['theta_prime_max'] > 50 or config['theta_prime_min'] < -50:
        print(f"    • ⚡ Relaxed bounds for testing")
    print("")
    print("  ★★★ V6.3 SUSTAIN: INTENSITY MAINTENANCE (Gemini Fix) ★★★")
    print("")
    print("  WISHE BOOSTING (Ck/Cd Correction):")
    print(f"    • Enabled: {'✅ YES' if config['wishe_boost_enabled'] else '❌ NO'}")
    if config['wishe_boost_enabled']:
        print(f"    • Max Boost: {config['wishe_boost_max']:.1f}x at high winds")
        print(f"    • Wind Range: {config['wishe_wind_min']:.0f} - {config['wishe_wind_max']:.0f} m/s")
        print(f"    • ⚡ Maintains Ck/Cd > 1.2 for sustained intensity")
    print("")
    print("  ★★★ V6.24 DLM + H3+ HYSTERESIS (Prevents Florida Weakening Dip) ★★★")
    print("")
    print("  DLM STEERING (Root Cause Fix - V6.23):")
    print(f"    • 🌍 Pressure Levels: 200, 300, 400, 500, 600, 700, 850 hPa")
    print(f"    • 🔺 Added 200 hPa (captures upper trough for recurvature!)")
    print(f"    • ⚡ Removed 0.55 scaling (was weakening DLM by 45%!)")
    print(f"    • 🔘 Inner radius 300km (was 225km, avoids ERA5 contamination)")
    print("")
    print("  BETA DRIFT (Physically Correct + Intensity-Aware + Hysteresis):")
    print(f"    • Enabled: {'✅ YES' if config['beta_drift_enabled'] else '❌ NO'}")
    if config['beta_drift_enabled']:
        print(f"    • Base Speed: {config['beta_drift_speed']:.1f} m/s at 15°N")
        print(f"    • 📈 Latitude Scaling: +{config['beta_drift_lat_scale']*100:.0f}% per degree")
        print(f"    • 🧭 Angle: 135° (NW) - PHYSICALLY CORRECT")
        print(f"    • 📍 Longitude Scaling: {'✅ YES' if config.get('longitude_scaling_enabled', True) else '❌ NO'}")
        print(f"    • 💪 Intensity Scaling: {'✅ YES' if config.get('intensity_scaling_enabled', True) else '❌ NO'}")
        print(f"    • 🔥 V6.25 H3+ HYSTERESIS: ON ≥96kts, OFF <83kts")
        print(f"    • 🧭 V6.25 Angle: 120° (was 135°) — more northward, less westward")
        print(f"    • 🛑 V6.25 Beta Cap: 4.0 m/s hard limit (was unbounded at 7.2 m/s!)")
        print(f"    • 🎯 Confidence Weighting: {'✅ YES' if config.get('confidence_weighting_enabled', True) else '❌ NO'} (auto-disabled for H3+)")
        print(f"    • 🌊 Basin Damping: {'✅ YES' if config.get('basin_damping_enabled', True) else '❌ NO'} (auto-disabled for H3+)")
        print(f"    • ⚠️ V6.25 Gulf Westward Cap: u ≥ -3 m/s in Gulf (prevents Texas drift)")
        print(f"    • 🔄 V6.26.4 RECURVE-B: Latitude-aware northward assist (fixes Yucatan escape)")
        print(f"    • 🏔️ V6.26 BETA LAND SUPPRESSION: Beta drift → 0 over land (Gemini fix!)")
    print("")
    print("  ★★★ V6.26.4 'RECURVE-B' - LATITUDE-AWARE STEERING ASSIST ★★★")
    print("")
    print("  RECURVE-B ASSIST (Fixes V6.26.3 Yucatan Escape Bug):")
    print(f"    • Problem: V6.26.3 lat>24° gate let storm fall to 18.79°N (Yucatan!)")
    print(f"    • Solution: Remove gate, add latitude-dependent boost instead")
    print(f"    • Physics: Storm that drifts south needs MORE correction, not less")
    print(f"    • west_factor: 0 at -88°W → 1.0 at -94°W")
    print(f"    • lat_factor: 0 at 26°N → 1.0 at 22°N (emergency boost)")
    print(f"    • Combined: nudge = west × 3.0 × (1 + lat_factor)")
    print(f"    • Result: Up to 6 m/s assist when far west AND far south")
    print("")
    print("  ADAPTIVE DLM WEIGHTING (Fixes Post-Landfall Eastward Bias):")
    print(f"    • Ocean: 200 hPa = 4x, 300 hPa = 2x (capture trough)")
    print(f"    • Land: 850 hPa = 2x, 700 hPa = 1.5x (follow terrain)")
    print(f"    • 🎯 Vortex shallows over land → lower-level steering dominates")
    print("")
    print("  HIGH-LATITUDE THERMODYNAMIC DAMPING (V6.26.1 Enhanced):")
    print(f"    • Damping begins at 30°N (was 35°N - EARLIER)")
    print(f"    • e-folding scale: 7° (was 10° - STEEPER)")
    print(f"    • 🧊 Prevents 'Zombie Thermodynamics' — tropical θ′ at high latitudes")
    print(f"    • Logging: Threshold crossings only (fixes 9MB spam!)")
    print("")
    print("  θ′ RELAXATION (V6.26.1 NEW - Gemini Fix #6):")
    print(f"    • Active north of 40°N")
    print(f"    • τ = 6 hours (drains ~16%/hour of accumulated tropical energy)")
    print(f"    • 🧟 Actively exorcises 'Zombie Thermodynamics'")
    print("")
    print("  STEERING FLOOR + CONTINUOUS INTEGRATION:")
    print(f"    • Floor Enabled: {'✅ YES' if config.get('steering_floor_enabled', True) else '❌ NO'}")
    if config.get('steering_floor_enabled', True):
        print(f"    • Floor: {config.get('steering_floor_ms', 3.0):.1f} m/s (~{config.get('steering_floor_ms', 3.0)*1.944:.0f} kts)")
        print(f"    • V6.22 Direction Fallback: Uses last known direction if near-zero")
    print(f"    • V6.22 Integration: Every 100 frames (was 3600)")
    print("")
    print("  ★★★ V6.16 STEERING INJECTION: PRESSURE SOLVER FIX (Gemini) ★★★")
    print("")
    print("  STEERING INJECTION (Treadmill Fix):")
    print(f"    • Enabled: {'✅ YES' if config['steering_injection_enabled'] else '❌ NO'}")
    if config['steering_injection_enabled']:
        print(f"    • 💉 Injects ERA5 steering into fluid dynamics")
        print(f"    • ⚡ Fixes 'vortex spins while domain slides' bug")
    print("")
    print("  ★★★ V6.18 ANNULAR STEERING: VORTEX CONTAMINATION FIX (Kimi Swarm) ★★★")
    print("")
    print("  ANNULAR STEERING (Exclude Vortex Core):")
    print(f"    • Enabled: {'✅ YES' if config['annular_steering_enabled'] else '❌ NO'}")
    if config['annular_steering_enabled']:
        print(f"    • 🔘 Inner radius: {config['annular_inner_km']:.0f} km")
        print(f"    • 🔘 Outer radius: {config['annular_outer_km']:.0f} km")
        print(f"    • ⚡ Samples ERA5 from annulus, excludes vortex circulation")
    print("")
    print("  ★★★ V6.20 VISUALIZATION ★★★")
    print("")
    print("  PLOTTING:")
    print(f"    • Track Plot: {'✅ YES' if config['track_plot_enabled'] else '❌ NO'}")
    print(f"    • Wind Plots: {'✅ YES' if config['wind_plots_enabled'] else '❌ NO'}")
    if config['wind_plots_enabled']:
        print(f"    • Plot Interval: Every {config['plot_interval']:,} frames")
    print(f"    • Output Dir: world_woe_v6_theta_plots/")
    print("")
    print("  COLD ANOMALY DIFFUSION (Anti-Crash):")
    print(f"    • Enabled: {'✅ YES' if config['cold_diffusion_enabled'] else '❌ NO'}")
    if config['cold_diffusion_enabled']:
        print(f"    • Strength: {config['cold_diffusion_strength']:.3f}")
        print(f"    • ⚡ Smooths cold holes (θ′ < -4K) to prevent crashes")
    print("")
    print("  ★★★ V6.4 SINK: θ′ ACCUMULATION FIX (Five's Analysis) ★★★")
    print("")
    print("  RADIATIVE COOLING (Newtonian relaxation):")
    print(f"    • Enabled: {'✅ YES' if config['radiative_cooling_enabled'] else '❌ NO'}")
    if config['radiative_cooling_enabled']:
        print(f"    • τ_rad (base): {config['tau_rad']/3600:.1f} hours")
        if config['dynamic_cooling_enabled']:
            print(f"    • 🔥 DYNAMIC MODE: τ scales with θ′")
            print(f"    • τ_rad (min): {config['tau_rad_min']/3600:.1f} hours")
            print(f"    • θ_scale: {config['theta_scale']:.0f} K")
        print(f"    • ⚡ Prevents 'closed box heats forever' problem")
    print("")
    print("  MEAN REMOVAL (Level-wise):")
    print(f"    • Enabled: {'✅ YES' if config['mean_removal_enabled'] else '❌ NO'}")
    if config['mean_removal_enabled']:
        print(f"    • ⚡ Removes horizontal θ′ drift at each level")
    print("")
    print("  ENVIRONMENT RELAXATION (Ventilation):")
    print(f"    • Enabled: {'✅ YES' if config['environment_relax_enabled'] else '❌ NO'}")
    if config['environment_relax_enabled']:
        print(f"    • Relax radius: {config['relax_radius_km']:.0f} km")
        print(f"    • τ_relax: {config['relax_tau']/3600:.1f} hours")
        print(f"    • ⚡ Mimics open boundaries in periodic domain")
    print("")
    print("  ★★★ V6.5 NUMERICS: STABILITY FIX (Gemini Analysis) ★★★")
    print("")
    print("  MONOTONIC ADVECTION (Bermejo Fix):")
    print(f"    • Enabled: {'✅ YES' if config['monotonic_advection'] else '❌ NO'}")
    if config['monotonic_advection']:
        print(f"    • ⚡ Prevents Gibbs overshoot at sharp gradients")
    print("")
    print("  FLUX THROTTLE (Runaway Prevention):")
    print(f"    • Enabled: {'✅ YES' if config['flux_throttle_enabled'] else '❌ NO'}")
    if config['flux_throttle_enabled']:
        print(f"    • Rate Threshold: {config['flux_throttle_threshold']:.1f} K/min")
        if config['proportional_throttle']:
            print(f"    • 🎚️ PROPORTIONAL MODE (V6.7)")
            print(f"    • θ′ Soft Limit: {config['theta_prime_soft_limit']:.0f} K (throttle begins)")
            print(f"    • θ′ Hard Limit: {config['theta_prime_hard_limit']:.0f} K (full throttle)")
        else:
            print(f"    • ⚡ Binary mode: Disables WISHE during instability")
    print("")
    print("  ★★★ V6.7 PROPORTIONAL: BALANCE FIX (Gemini Analysis) ★★★")
    print("")
    print("  MOISTURE FLOOR:")
    print(f"    • Floor: {config['moisture_floor']*1000:.2f} g/kg")
    print(f"    • ⚡ Prevents negative specific humidity")
    print("")
    print("  GOVERNOR STATUS:")
    print(f"    • Flux Governor:     {'❌ DISABLED' if config['no_flux_governor'] else '✅ Active'}")
    print(f"    • WISDOM Dampening:  {'❌ DISABLED' if config['no_wisdom'] else '✅ Active'}")
    print(f"    • Velocity Governor: {'❌ DISABLED' if config['no_velocity_governor'] else '✅ Active'}")
    print(f"    • Thermo Firewalls:  {'❌ DISABLED' if config['no_thermo_firewalls'] else '✅ Active'}")
    print("")
    if config.get('betts_miller_enabled', False):
        print("  ★★★ V7.0 BETTS-MILLER: CONVECTIVE ADJUSTMENT ★★★")
        print("")
        print("  BETTS-MILLER RELAXED CONVECTION:")
        print(f"    • Enabled: ✅ YES (replaces instant saturation)")
        print(f"    • τ_BM: {config['tau_bm']:.0f} seconds ({config['tau_bm']/60:.0f} minutes)")
        print(f"    • Reference RH: {config['bm_reference_rh']*100:.0f}%")
        print(f"    • BL Taper: {config['bm_taper_start_m']:.0f}m → {config['bm_taper_full_m']:.0f}m (power={config['bm_taper_power']:.1f})")
        print(f"    • ⚡ Senses full column including BL (no hard gate)")
        print(f"    • ⚡ Tendencies tapered near surface to protect BL moisture")
        print(f"    • 🌊 Flux Depth: {config['flux_depth_m']:.0f}m (decoupled from grid dz)")
        print("")
        print("  ★★★ V7.1: SPECTRAL SHORT-CIRCUIT FIX (Gemini Deep Research) ★★★")
        print("")
        print("  Z-BOUNDARY REMEDIATION:")
        print("    • 🔧 Advection z-clamp: departure_z ∈ [0, nz-1] (was periodic wrap)")
        print("    •    Surface parcels see ocean (not stratosphere)")
        print("    •    Tropopause parcels see dry lid (not surface moisture)")
        print("    • 🧊 Vertical sponge: top 20% domain, cos² Rayleigh damping")
        print("    •    w → 0, θ′ → 0, q → q_ref (gravity wave absorption)")
        print("    • 🌊 Far-field moisture relaxation: τ=12h, r > 400-600km")
        print("    •    Prevents environmental dryout over long integrations")
        print(f"    • 🌧️ Precipitation efficiency: {config['precip_efficiency']*100:.0f}% of latent heat → θ′")
        print("    •    Implicitly represents rain cooling + outflow export")
        if config.get('warm_rain', False):
            cap = config.get('warm_rain_cap', 1.5)
            print(f"    • 🌧️ Warm rain: ✅ ENABLED — ALL LEVELS + VIRGA (cap={cap:.1f}× q_sat)")
            print(f"    •    Moisture cap at all levels — heating only below melting level (virga taper 2-4km)")
        else:
            print("    • 🌧️ Warm rain: ❌ disabled")
    else:
        print("  CONVECTIVE SCHEME: Instant saturation (V6 legacy)")
        print("")
    if config['fully_unconstrained']:
        print("  ⚠️  FULLY UNCONSTRAINED MODE - ALL GOVERNORS DISABLED!")
        print("")
    print("  HYPOTHESIS: WISHE boost should SUSTAIN intensity after peak!")
    print("=" * 80)
    print("")


# === IMPORTS ===
import numpy as np

USE_GPU = True
try:
    if USE_GPU:
        import cupy as xp
        print(f"[{__name__}] 🚀 GPU Acceleration ENABLED (CuPy)")
    else:
        raise ImportError
except ImportError:
    import numpy as xp
    print(f"[{__name__}] 🐢 GPU Acceleration DISABLED (NumPy)")
    USE_GPU = False

from datetime import datetime, timedelta
import os

# Visualization
import matplotlib
matplotlib.use('Agg')  # Non-interactive backend for saving plots
import matplotlib.pyplot as plt
import matplotlib.colors as mcolors
from matplotlib.patches import Circle

# Core modules
from environment import BasinEnvironment
from core_solver import CoreSolver
from boundary_conditions import BoundaryConditions
from storm_tracker import StormTracker
from visualizer import Visualizer
from amr_handler import AMRHandler
from kalman_filter import KalmanFilter
from data_interface import DataInterface
from utils import LATENT_HEAT_VAPORIZATION

# V6 THETA: Import reference state module
from reference_state import ReferenceState, create_default_reference


class TeeLogger:
    """Dual output to terminal and log file."""
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'w', encoding='utf-8')
    
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
        self.log.flush()
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()
    
    def close(self):
        self.log.close()


def log_info(message):
    print(f"[INFO] {message}")


class Simulation3D:
    """
    Oracle V6.0 THETA - 3D Hurricane Simulation with θ′ Thermodynamics
    
    This class implements the core simulation loop using potential temperature
    perturbation (θ′) as the prognostic thermodynamic variable instead of
    absolute temperature (T).
    
    Key differences from V5.x:
        - self.theta_prime replaces self.T as prognostic
        - self.T is now diagnostic (computed from θ for compatibility)
        - Stratification term replaces adiabatic cooling
        - Buoyancy from θ′/θ₀ instead of T-based
    """
    
    def __init__(self, nx, ny, nz, storm_name, storm_year, config):
        self.config = config
        self.storm_name = storm_name
        self.storm_year = storm_year
        self.pure_physics = config['pure_physics']
        self.advection_order = config['advection_order']
        self.sponge_strength_config = config['sponge_strength']
        self.Cs = config['smagorinsky_cs']
        
        # V6.20 VISUALIZATION
        self.plot_interval = config.get('plot_interval', 7200)
        self.track_plot_enabled = config.get('track_plot_enabled', False)
        self.wind_plots_enabled = config.get('wind_plots_enabled', False)
        self.track_history = []  # Store (lat, lon) tuples for track plot
        
        # =====================================================================
        # V6 THETA: Governor flags
        # =====================================================================
        self.no_flux_governor = config.get('no_flux_governor', False)
        self.no_wisdom = config.get('no_wisdom', False)
        self.no_velocity_governor = config.get('no_velocity_governor', False)
        self.no_thermo_firewalls = config.get('no_thermo_firewalls', False)
        
        # =====================================================================
        # V6.2: ENSEMBLE-IDENTIFIED INHIBITOR CONTROLS
        # Priority 1: Turbulence (Five + Gemini)
        # Priority 2: Stratification
        # Priority 3: Moisture initialization
        # =====================================================================
        self.resolution_boost = config.get('resolution_boost', 1500.0)
        self.moist_floor = config.get('moist_floor', 0.3)
        self.updraft_only_moist = config.get('updraft_only_moist', False)
        self.core_rh_init = config.get('core_rh_init', 0.95)
        
        # V6.2: θ′ stability bounds (configurable for testing)
        self.theta_prime_max_bound = config.get('theta_prime_max', 50.0)
        self.theta_prime_min_bound = config.get('theta_prime_min', -50.0)
        
        # V6.3 SUSTAIN: Intensity maintenance controls
        self.wishe_boost_enabled = config.get('wishe_boost_enabled', False)
        self.wishe_boost_max = config.get('wishe_boost_max', 1.4)
        self.wishe_wind_min = config.get('wishe_wind_min', 15.0)  # m/s - boost begins
        self.wishe_wind_max = config.get('wishe_wind_max', 40.0)  # m/s - boost at max
        
        # V6.15 STEERING: Translation speed fix
        self.steering_multiplier = config.get('steering_multiplier', 1.0)
        self.beta_drift_enabled = config.get('beta_drift_enabled', False)
        self.beta_drift_speed = config.get('beta_drift_speed', 2.5)  # m/s at 15°N
        self.beta_drift_lat_scale = config.get('beta_drift_lat_scale', 0.05)  # V6.17: 5% per degree
        
        # V6.16 STEERING INJECTION: Pressure solver fix (Gemini's Analysis)
        self.steering_injection_enabled = config.get('steering_injection_enabled', False)
        self.current_u_steering_nd = 0.0  # Dimensionless, updated by nest advection
        self.current_v_steering_nd = 0.0  # Dimensionless, updated by nest advection
        
        # V6.18 ANNULAR STEERING: Vortex contamination fix (Kimi Swarm)
        self.annular_steering_enabled = config.get('annular_steering_enabled', False)
        self.annular_inner_km = config.get('annular_inner_km', 200.0)
        self.annular_outer_km = config.get('annular_outer_km', 600.0)
        
        # V6.21 BETA FIX: Physically correct beta drift (Gemini Analysis)
        self.steering_floor_enabled = config.get('steering_floor_enabled', True)
        self.steering_floor_ms = config.get('steering_floor_ms', 3.0)
        self.intensity_scaling_enabled = config.get('intensity_scaling_enabled', True)
        self.longitude_scaling_enabled = config.get('longitude_scaling_enabled', True)
        self._last_max_wind_ms = 30.0  # For intensity-based beta scaling
        
        # =====================================================================
        # V6.22 STEERING FIX: Continuous integration + confidence weighting (Five)
        # =====================================================================
        # Problem: V6.21 applied translation in coarse 3600-frame chunks ("teleport")
        # Fix: Cache steering, integrate position EVERY FRAME
        # =====================================================================
        self._cached_u_steer = 0.0  # Cached steering (m/s)
        self._cached_v_steer = 0.0
        self._cached_steer_direction = (1.0, 0.0)  # Unit vector for floor fallback
        self._last_steer_update_frame = -1
        
        # V6.22: Confidence weighting parameters
        self.steer_ref = config.get('steer_ref', 6.0)  # Reference ERA5 speed for weighting
        self.basin_damping_enabled = config.get('basin_damping_enabled', True)
        self.confidence_weighting_enabled = config.get('confidence_weighting_enabled', True)
        
        # V6.23: Deep Layer Mean (DLM) parameters (Gemini's Analysis)
        self.dlm_scale = config.get('dlm_scale', 1.0)  # Was 0.55, now 1.0 (full strength)
        self.dlm_inner_radius_km = config.get('dlm_inner_radius_km', 300.0)  # Was 225, now 300
        self.h3_boost_enabled = config.get('h3_boost_enabled', True)  # Auto-boost for H3+
        
        # V6.24: H3+ hysteresis state (prevents flickering during temporary weakening)
        # ON at ≥96 kts (Cat 3), OFF only below 83 kts (Cat 2)
        self._h3_mode_active = False
        
        # V6.25: Gulf westward cap (prevents Texas drift)
        self.gulf_westward_cap_enabled = config.get('gulf_westward_cap_enabled', True)
        self.gulf_westward_cap_ms = config.get('gulf_westward_cap_ms', -3.0)  # u >= -3 m/s in Gulf
        
        # V6.26.4 RECURVE-B: Latitude-aware northward assist
        # Fixes V6.26.3 bug where lat>24° gate let storm escape to Yucatan
        # Now: stronger assist when storm drifts further south (physically motivated)
        self.recurve_assist_enabled = config.get('recurve_assist_enabled', True)
        self.recurve_lon_start = config.get('recurve_lon_start', -88.0)      # Start assist west of Mobile
        self.recurve_lon_full = config.get('recurve_lon_full', -94.0)        # Full west factor at Texas border
        self.recurve_max_nudge_ms = config.get('recurve_max_nudge_ms', 3.0)  # Base max northward assist
        self.recurve_lat_baseline = config.get('recurve_lat_baseline', 26.0) # No lat boost at this latitude
        self.recurve_lat_emergency = config.get('recurve_lat_emergency', 22.0)  # Full lat boost (2x) here
        
        # V6.26: Beta drift land suppression (Gemini Deep Dive)
        self.beta_land_suppression_enabled = config.get('beta_land_suppression_enabled', True)
        
        # V6.26: High-latitude thermodynamic damping (Gemini Deep Dive)
        self.high_lat_damping_enabled = config.get('high_lat_damping_enabled', True)
        
        # V6.26.1: θ′ relaxation at high latitudes (Gemini Fix #6)
        self.theta_relax_enabled = config.get('theta_relax_enabled', True)
        
        self.cold_diffusion_enabled = config.get('cold_diffusion_enabled', False)
        self.cold_diffusion_strength = config.get('cold_diffusion_strength', 0.05)
        
        # V6.3 diagnostics
        self._last_wishe_boost_max = 1.0
        self._last_wishe_boost_mean = 1.0
        self._cold_diffusion_events = 0
        
        # V6.4 SINK: Radiative cooling and mean removal (Five's fix)
        self.radiative_cooling_enabled = config.get('radiative_cooling_enabled', False)
        self.tau_rad = config.get('tau_rad', 86400.0)  # Default 1 day
        self.dynamic_cooling_enabled = config.get('dynamic_cooling_enabled', False)
        self.tau_rad_min = config.get('tau_rad_min', 3600.0)  # Default 1 hour minimum
        self.theta_scale = config.get('theta_scale', 20.0)  # K - scale for exponential decay
        self.mean_removal_enabled = config.get('mean_removal_enabled', False)
        self.environment_relax_enabled = config.get('environment_relax_enabled', False)
        self.relax_radius_km = config.get('relax_radius_km', 300.0)
        self.relax_tau = config.get('relax_tau', 3600.0)  # Default 1 hour
        
        # V6.4 diagnostics
        self._total_radiative_cooling = 0.0
        self._total_mean_removed = 0.0
        self._last_effective_tau_rad = self.tau_rad  # For dynamic cooling tracking
        
        # V6.5 NUMERICS: Monotonic advection and flux throttle (Gemini's fix)
        self.monotonic_advection = config.get('monotonic_advection', False)
        
        # V7.0 BETTS-MILLER: Relaxed convective adjustment
        self.betts_miller_enabled = config.get('betts_miller_enabled', False)
        self.tau_bm = config.get('tau_bm', 900.0)  # Default 15 minutes
        self.bm_reference_rh = config.get('bm_reference_rh', 0.90)
        self.bm_taper_start_m = config.get('bm_taper_start_m', 200.0)
        self.bm_taper_full_m = config.get('bm_taper_full_m', 2200.0)
        self.bm_taper_power = config.get('bm_taper_power', 1.0)
        self.flux_depth_m = config.get('flux_depth_m', 100.0)
        self.precip_efficiency = config.get('precip_efficiency', 0.25)
        self.warm_rain = config.get('warm_rain', False)
        self.warm_rain_cap = config.get('warm_rain_cap', 1.5)
        self._warm_rain_total_precip = 0.0  # Total warm rain condensation (diagnostic)
        
        # V7.0 BM diagnostics
        self._bm_total_precip_kg = 0.0
        self._bm_columns_active = 0
        self._bm_last_precip_rate = 0.0  # mm/hr equivalent
        self._bm_level_cells = None  # per-level active cell counts
        self._bm_level_dq = None     # per-level integrated dq
        self._bm_floor_clamps_frame = 0  # per-frame moisture floor clamps
        self.flux_throttle_enabled = config.get('flux_throttle_enabled', False)
        self.flux_throttle_threshold = config.get('flux_throttle_threshold', 5.0)  # K/min
        
        # V6.5 diagnostics
        self._prev_theta_prime_max = None  # For flux throttle dθ'/dt calculation
        self._flux_throttle_active = False
        self._flux_throttle_events = 0
        
        # V6.7 PROPORTIONAL: Integral flux throttle (Gemini's fix)
        self.proportional_throttle = config.get('proportional_throttle', False)
        self.theta_prime_soft_limit = config.get('theta_prime_soft_limit', 60.0)  # K
        self.theta_prime_hard_limit = config.get('theta_prime_hard_limit', 100.0)  # K
        self.moisture_floor = config.get('moisture_floor', 0.0001)  # kg/kg
        
        # V6.7 diagnostics
        self._throttle_factor = 1.0  # Current throttle reduction factor (1.0 = no throttle)
        self._moisture_floor_events = 0
        
        # =====================================================================
        # V6 THETA: Reference State Configuration
        # =====================================================================
        self.theta_surface = config.get('theta_surface', 300.0)  # K
        self.gamma_theta = config.get('gamma_theta', 4.0)        # K/km
        self.scale_height = config.get('scale_height', 8500.0)   # m
        
        # Create reference state object
        self.ref_state = ReferenceState(
            theta_surface=self.theta_surface,
            gamma_theta=self.gamma_theta,
            scale_height=self.scale_height,
            p_surface=100000.0
        )
        
        # V6 THETA: Warm core initialization
        self.warm_core_theta_prime = config.get('warm_core_theta_prime', 5.0)  # K
        self.base_humidity = config.get('base_humidity', 0.018)
        
        # Legacy parameters (for compatibility / optional firewalls)
        self.buoyancy_cap = config.get('buoyancy_cap', 0.5)
        self.max_updraft = config.get('max_updraft', 50.0)
        self.max_temp_anomaly = config.get('max_temp_anomaly', 15.0)
        
        self.g = 9.81
        self.nx, self.ny, self.nz = nx, ny, nz
        
        # =====================================================================
        # SCALING (same as V5.3.6)
        # =====================================================================
        self.physical_domain_x_km = 2000.0
        self.physical_domain_y_km = 2000.0
        self.physical_domain_z_km = 20.0
        self.L_CHAR = self.physical_domain_x_km * 1000.0
        self.U_CHAR = 25.0
        self.T_CHAR = self.L_CHAR / self.U_CHAR  # 80,000 s
        self.dt_solver = 3e-5
        
        # Physical constants
        self.c_p = 1004.0       # Specific heat [J/(kg·K)]
        self.rho_air = 1.225    # Air density [kg/m³]
        
        # Domain dimensions (dimensionless)
        self.lx = self.ly = 1.0
        self.lz = self.physical_domain_z_km / self.physical_domain_x_km  # 0.01
        
        # Grid spacing (dimensionless)
        self.dx = self.lx / nx
        self.dy = self.ly / ny
        self.dz = self.lz / nz
        
        # Boussinesq: dimensionless density = 1.0
        self.rho = 1.0
        
        # Physical grid spacing [m]
        self.dz_physical_km = self.physical_domain_z_km / nz
        self.dx_physical = self.physical_domain_x_km * 1000.0 / nx  # m
        self.dy_physical = self.physical_domain_y_km * 1000.0 / ny  # m
        self.dz_physical = self.physical_domain_z_km * 1000.0 / nz  # m
        
        # =====================================================================
        # V6 THETA: Height arrays for reference profiles
        # =====================================================================
        # 1D height array [m]
        self.z_m_1d = np.linspace(0, self.physical_domain_z_km * 1000.0, nz)
        self.z_km_1d = self.z_m_1d / 1000.0
        
        # Reference profiles (1D)
        self.theta0_1d = self.ref_state.theta_ref(self.z_km_1d)  # K
        self.P_1d = self.ref_state.pressure(self.z_m_1d)         # Pa
        
        # Convert to GPU arrays if needed
        self.theta0_1d = xp.asarray(self.theta0_1d)
        self.P_1d = xp.asarray(self.P_1d)
        self.z_m_1d = xp.asarray(self.z_m_1d)
        
        # 3D broadcast versions (nx, ny, nz)
        self.theta0_3d = self.theta0_1d[xp.newaxis, xp.newaxis, :]
        self.P_3d = self.P_1d[xp.newaxis, xp.newaxis, :]
        self.z_m_3d = self.z_m_1d[xp.newaxis, xp.newaxis, :]
        
        # Stratification gradient (constant for linear profile)
        self.dtheta0_dz = self.ref_state.dtheta_dz()  # K/m
        
        log_info(f"V6 THETA: Reference state initialized")
        log_info(f"   θ₀(z=0) = {float(self.theta0_1d[0]):.1f} K")
        log_info(f"   θ₀(z=10km) = {float(self.theta0_1d[nz//2]):.1f} K")
        log_info(f"   θ₀(z=20km) = {float(self.theta0_1d[-1]):.1f} K")
        log_info(f"   dθ₀/dz = {self.dtheta0_dz*1000:.2f} K/km")
        
        # =====================================================================
        # FIELD INITIALIZATION
        # =====================================================================
        # Momentum (same as V5)
        self.u = xp.zeros((nx, ny, nz))
        self.v = xp.zeros((nx, ny, nz))
        self.w = xp.zeros((nx, ny, nz))
        
        # V6 THETA: θ′ is the prognostic variable (initialized to zero)
        self.theta_prime = xp.zeros((nx, ny, nz))
        
        # =====================================================================
        # V6 THETA: Moisture with realistic vertical profile
        # Real atmosphere has moisture concentrated in lower troposphere
        # Use exponential decay with ~2.5 km scale height
        # =====================================================================
        moisture_scale_height = 2500.0  # m
        q_vertical_profile = self.base_humidity * xp.exp(-self.z_m_1d / moisture_scale_height)
        self.q = xp.zeros((nx, ny, nz))
        for k in range(nz):
            self.q[:, :, k] = q_vertical_profile[k]
        
        log_info(f"   💧 Moisture profile: surface={self.base_humidity*1000:.1f} g/kg, "
                 f"5km={float(q_vertical_profile[nz//4])*1000:.2f} g/kg, "
                 f"top={float(q_vertical_profile[-1])*1000:.4f} g/kg")
        
        # V6 THETA: Diagnostic T (computed from θ for compatibility)
        # Initialize from reference state
        self.T = xp.zeros((nx, ny, nz))
        self._update_diagnostic_T()
        
        # =====================================================================
        # DIAGNOSTICS & TRACKING
        # =====================================================================
        self.total_condensation_events = 0
        self.total_latent_heat_released = 0.0
        self.condensation_blocked_events = 0
        self.temp_firewall_events = 0
        self.temp_relax_events = 0
        self.buoyancy_clamp_events = 0
        self.emergency_halted = False
        self.max_wind_history = []
        self.max_buoyancy_history = []
        self.max_w_history = []
        self.position_history = []
        
        # V6 THETA: New diagnostics
        self.stratification_cooling_total = 0.0
        self.theta_prime_max_history = []
        
        # V6.1: Moist-aware stratification diagnostics
        self._last_strat_effective_factor = 1.0
        self._last_strat_saturation_blend = 0.0
        self.moist_strat_events = 0  # Count of frames with significant moist reduction
        
        # V6.2: Additional diagnostics for ensemble analysis
        self._last_strat_eff_in_updrafts = 1.0
        self._last_nu_turb_max = 0.0
        self._last_nu_turb_mean = 0.0
        self._last_q_deficit = 0.0  # q_sat_ocean - q_sfc in core
        
        # =====================================================================
        # STORM ENVIRONMENT SETUP
        # =====================================================================
        log_info(f"   🌊 Initializing basin environment...")
        self.basin = BasinEnvironment()
        self.storm_tracker = StormTracker(self)
        
        oracle_files = {
            'ivan': 'ivan_2004_oracle.nc',
            'katrina': 'katrina_2005_oracle.nc',
            'hugo': 'hugo_1989_oracle.nc',
        }
        storm_key = storm_name.lower()
        oracle_file = oracle_files.get(storm_key, f'{storm_key}_{storm_year}_oracle.nc')
        self.oracle_available = os.path.exists(oracle_file)
        
        if self.oracle_available:
            log_info(f"   📜 Oracle track found: {oracle_file}")
        else:
            log_info(f"   ⚠️ No oracle track - using ERA5 steering only")
        
        # Genesis position
        genesis_data = {
            'HUGO': {'lat': 13.2, 'lon': -20.0, 'time': datetime(1989, 9, 10, 12)},
            'IVAN': {'lat': 9.7, 'lon': -27.6, 'time': datetime(2004, 9, 2, 18)},
            'KATRINA': {'lat': 23.2, 'lon': -75.5, 'time': datetime(2005, 8, 23, 18)},
        }
        storm_upper = storm_name.upper()
        if storm_upper in genesis_data:
            g = genesis_data[storm_upper]
            self.current_center_lat = g['lat']
            self.current_center_lon = g['lon']
            self.genesis_time = g['time']
        else:
            self.current_center_lat = 15.0
            self.current_center_lon = -30.0
            self.genesis_time = datetime(2000, 9, 1, 12)
        
        log_info(f"   📍 Genesis: ({self.current_center_lat}°N, {self.current_center_lon}°W)")
        
        # Initialize data interface (takes self reference, storm name, year)
        self.data_interface = DataInterface(self, storm_name, storm_year)
        
        # Sync environment
        self._sync_environment(frame=0)
        
        # Solver and boundary conditions
        log_info(f"   ⚙️ Initializing solver...")
        self.solver = CoreSolver(self)
        
        # Domain scaler helper (matches V5.3.6)
        class DomainScaler:
            def __init__(self, lx, ly, lz, px_km, py_km, pz_km):
                self.x_scale = px_km * 1000.0 / lx  # m per dimensionless unit
                self.y_scale = py_km * 1000.0 / ly
                self.z_scale = pz_km * 1000.0 / lz
            def dimensionless_to_physical_z(self, dz_nd):
                return dz_nd * self.z_scale
        
        self.domain_scaler = DomainScaler(
            self.nx * self.dx, self.ny * self.dy, self.nz * self.dz,
            self.physical_domain_x_km, self.physical_domain_y_km, self.physical_domain_z_km
        )
        
        # Boundary conditions (takes self reference)
        self.boundaries = BoundaryConditions(self)
        
        # V6: Pass governor disable flags to boundaries if supported
        if hasattr(self.boundaries, 'disable_flux_governor'):
            self.boundaries.disable_flux_governor = self.no_flux_governor
        if hasattr(self.boundaries, 'disable_wisdom'):
            self.boundaries.disable_wisdom = self.no_wisdom
        
        # Coriolis
        lat_rad = np.radians(self.current_center_lat)
        self.f0 = 2.0 * 7.2921e-5 * np.sin(lat_rad)
        
        # Sponge
        self._create_edge_sponge_mask()
        
        # Output directory
        self.plot_dir = f"world_woe_v6_theta_plots"
        os.makedirs(self.plot_dir, exist_ok=True)
        
        # Visualizer
        self.visualizer = Visualizer(self)
        
        # =====================================================================
        # STORM INITIALIZATION (V6 THETA: θ′ warm core)
        # =====================================================================
        log_info(f"   🌀 Initializing WARM-CORE vortex (θ′ formulation)...")
        self._initialize_storm_theta()
        
        log_info(f"   ✅ V6.0 'THETA' Ready!")
        log_info("")
        log_info("=" * 60)
        log_info("--- V6.0 THETA SIMULATION START ---")
        log_info(f"--- Frames: {config['target_frames']:,} ---")
        log_info("--- θ′ THERMODYNAMICS + PHYSICAL LIMITS ---")
        log_info("=" * 60)
        log_info("")
    
    def _create_edge_sponge_mask(self):
        """Create sponge layer mask for boundary damping."""
        x = xp.arange(self.nx) / self.nx
        y = xp.arange(self.ny) / self.ny
        xx, yy = xp.meshgrid(x, y, indexing='ij')
        edge_dist = xp.minimum(xp.minimum(xx, 1-xx), xp.minimum(yy, 1-yy))
        self.sponge_mask = xp.clip(edge_dist / 0.15, 0.0, 1.0)
        self.sponge_strength = self.sponge_strength_config
        
        # =================================================================
        # V7.1: VERTICAL SPONGE LAYER (Gemini Remediation §5.2)
        # =================================================================
        # Rayleigh damping in top 20% of domain to:
        #   1. Enforce effective rigid lid (w → 0)
        #   2. Absorb gravity waves (prevent reflection)
        #   3. Prevent moisture accumulation at model top
        #
        # Profile: cos²-shaped, zero in physical domain, max at top
        # Applied to: w, θ′, q (with different strengths)
        # =================================================================
        nz_sponge = max(3, self.nz // 5)  # Top 20%, at least 3 levels
        self.vert_sponge = xp.zeros(self.nz)
        for k in range(self.nz - nz_sponge, self.nz):
            # Smooth cos² ramp from 0 at sponge base to 1 at top
            frac = (k - (self.nz - nz_sponge)) / nz_sponge
            self.vert_sponge[k] = float(xp.cos(0.5 * xp.pi * (1.0 - frac))**2)
        
        # Sponge damping rate (fraction per timestep)
        # At dt=2.4s, strength=0.05 gives ~5% damping per step in top level
        self.vert_sponge_strength = 0.05
        
        # 3D broadcast shape for element-wise operations
        self.vert_sponge_3d = self.vert_sponge[xp.newaxis, xp.newaxis, :]
        
        # =================================================================
        # V7.1: MOISTURE REFERENCE PROFILE (for far-field relaxation)
        # =================================================================
        # Store the initial moisture profile so we can nudge the environment
        # back toward it. Prevents the storm from "drying out" its own
        # environment over long integrations (Gemini §5.1).
        # =================================================================
        moisture_scale_height = 2500.0  # m — matches initialization
        self.q_ref_profile = self.base_humidity * xp.exp(-self.z_m_1d / moisture_scale_height)
        
        log_info(f"   🧊 Vertical sponge: top {nz_sponge} levels, strength={self.vert_sponge_strength}")
        log_info(f"   🌊 Moisture reference profile stored for far-field relaxation")
    
    # =========================================================================
    # V6.18 ANNULAR STEERING (Kimi Swarm Recommendation)
    # =========================================================================
    
    def compute_annular_steering(self, u_field, v_field, inner_radius_km=200, outer_radius_km=600):
        """
        Compute steering flow from annular region EXCLUDING vortex core.
        
        The Problem:
            Domain-mean includes symmetric vortex circulation which averages to ~0,
            contaminating/diluting the environmental steering signal.
        
        The Fix:
            Sample winds from an annulus (r=200-600 km) that excludes the vortex
            core but captures the synoptic-scale steering flow.
        
        Args:
            u_field, v_field: 2D or 3D wind fields from ERA5/data_interface
            inner_radius_km: Exclude vortex core (default 200 km, outside eyewall)
            outer_radius_km: Outer edge of steering layer (default 600 km)
        
        Returns:
            u_annular, v_annular: Mean winds in annular region (dimensionless)
        
        Reference: NHC uses 300-600 km for deep-layer mean steering
        """
        # Get domain center (storm center)
        cx, cy = self.nx // 2, self.ny // 2
        
        # Create radial distance array in km
        # Physical grid spacing in km
        dx_km = self.dx * self.L_CHAR / 1000.0
        dy_km = self.dy * self.L_CHAR / 1000.0
        
        x_km = (xp.arange(self.nx) - cx) * dx_km
        y_km = (xp.arange(self.ny) - cy) * dy_km
        X_km, Y_km = xp.meshgrid(x_km, y_km, indexing='ij')
        r_km = xp.sqrt(X_km**2 + Y_km**2)
        
        # Create annular mask (2D)
        annulus_mask_2d = (r_km >= inner_radius_km) & (r_km <= outer_radius_km)
        
        # Ensure fields are on GPU (data_interface may return NumPy arrays)
        u_field_gpu = xp.asarray(u_field)
        v_field_gpu = xp.asarray(v_field)
        
        # Handle 2D or 3D fields
        if u_field_gpu.ndim == 3:
            # For 3D, take mean over all z-levels first, then apply annular mask
            # (Alternatively, we could apply mask at each level and then average)
            u_2d = xp.mean(u_field_gpu, axis=2)
            v_2d = xp.mean(v_field_gpu, axis=2)
        else:
            u_2d = u_field_gpu
            v_2d = v_field_gpu
        
        # Count valid cells in annulus
        n_cells = xp.sum(annulus_mask_2d)
        
        if n_cells < 10:
            # Fallback to domain mean if annulus is too small
            log_info(f"    ⚠️ ANNULAR: Only {int(n_cells)} cells, falling back to domain mean")
            return float(xp.mean(u_field_gpu)), float(xp.mean(v_field_gpu))
        
        # Compute mean over annular region
        u_annular = float(xp.sum(u_2d * annulus_mask_2d) / n_cells)
        v_annular = float(xp.sum(v_2d * annulus_mask_2d) / n_cells)
        
        return u_annular, v_annular
    
    # =========================================================================
    # V6.20 VISUALIZATION METHODS
    # =========================================================================
    
    def _save_wind_plot(self, frame):
        """Save wind field snapshot with storm position overlay."""
        if not getattr(self, 'wind_plots_enabled', False):
            return
            
        try:
            # Get wind field at surface level (z=0)
            u_np = self.u[:, :, 0].get() if hasattr(self.u, 'get') else self.u[:, :, 0]
            v_np = self.v[:, :, 0].get() if hasattr(self.v, 'get') else self.v[:, :, 0]
            
            # Compute wind speed in kts
            wind_speed = np.sqrt(u_np**2 + v_np**2) * self.U_CHAR * 1.944
            
            # Create figure
            fig, ax = plt.subplots(figsize=(10, 8))
            
            # Wind speed contour
            levels = [34, 64, 83, 96, 113, 137, 160, 180, 200]
            colors = ['#5ebaff', '#00faf4', '#ffffcc', '#ffe775', '#ffc140', 
                     '#ff8f20', '#ff6060', '#c00000', '#800000']
            cmap = mcolors.ListedColormap(colors)
            norm = mcolors.BoundaryNorm(levels, cmap.N)
            
            im = ax.contourf(wind_speed.T, levels=levels, cmap=cmap, norm=norm, extend='both')
            plt.colorbar(im, ax=ax, label='Wind Speed (kts)', ticks=levels)
            
            # Mark storm center
            cx, cy = self.nx // 2, self.ny // 2
            ax.plot(cx, cy, 'k+', markersize=15, markeredgewidth=3)
            ax.add_patch(Circle((cx, cy), 10, fill=False, color='black', linewidth=2))
            
            # Labels
            max_wind = np.max(wind_speed)
            ax.set_title(f'Oracle V6.20 - Frame {frame:,}\n'
                        f'{self.storm_name} ({self.storm_year}) | '
                        f'Max Wind: {max_wind:.1f} kts | '
                        f'Position: ({self.current_center_lat:.1f}°N, {abs(self.current_center_lon):.1f}°W)',
                        fontsize=12)
            ax.set_xlabel('Grid X')
            ax.set_ylabel('Grid Y')
            
            # Save
            filename = f"{self.plot_dir}/wind_{self.storm_name}_{frame:07d}.png"
            plt.savefig(filename, dpi=150, bbox_inches='tight')
            plt.close(fig)
            
        except Exception as e:
            log_info(f"    ⚠️ Wind plot failed at frame {frame}: {e}")
    
    def _save_track_plot(self):
        """Generate full track plot at end of simulation."""
        if not getattr(self, 'track_plot_enabled', False):
            return
        if not hasattr(self, 'track_history') or len(self.track_history) < 2:
            log_info("    ⚠️ Track plot skipped: insufficient track data")
            return
            
        try:
            # Extract track data
            lats = [p[0] for p in self.track_history]
            lons = [p[1] for p in self.track_history]
            winds = self.max_wind_history if hasattr(self, 'max_wind_history') else [0] * len(lats)
            
            # Create figure
            fig, ax = plt.subplots(figsize=(14, 10))
            
            # Plot track colored by intensity
            for i in range(len(lats) - 1):
                wind = winds[min(i, len(winds)-1)]
                if wind >= 137:
                    color = '#c00000'  # Cat 5
                elif wind >= 113:
                    color = '#ff6060'  # Cat 4
                elif wind >= 96:
                    color = '#ff8f20'  # Cat 3
                elif wind >= 83:
                    color = '#ffc140'  # Cat 2
                elif wind >= 64:
                    color = '#ffe775'  # Cat 1
                elif wind >= 34:
                    color = '#00faf4'  # TS
                else:
                    color = '#5ebaff'  # TD
                ax.plot([lons[i], lons[i+1]], [lats[i], lats[i+1]], 
                       color=color, linewidth=2.5, solid_capstyle='round')
            
            # Mark start and end
            ax.plot(lons[0], lats[0], 'go', markersize=12, label='Genesis', zorder=5)
            ax.plot(lons[-1], lats[-1], 'rs', markersize=12, label='Final Position', zorder=5)
            
            # Mark peak intensity
            if winds:
                peak_idx = winds.index(max(winds))
                ax.plot(lons[peak_idx], lats[peak_idx], 'k*', markersize=18, 
                       label=f'Peak: {max(winds):.0f} kts', zorder=6)
            
            # Add geographic reference lines
            ax.axhline(y=23.5, color='gray', linestyle='--', alpha=0.5, label='Tropic of Cancer')
            ax.axvline(x=-65, color='gray', linestyle=':', alpha=0.5)  # Caribbean
            ax.axvline(x=-80, color='gray', linestyle=':', alpha=0.5)  # US East Coast
            
            # Rough landmass outlines (simplified)
            # US East Coast (approximate)
            us_coast_lon = [-80, -81, -82, -83, -85, -87, -88, -90, -91, -93, -95, -97]
            us_coast_lat = [25, 27, 28, 29.5, 30, 30.5, 30, 29.5, 29.5, 29.5, 28, 26]
            ax.fill(us_coast_lon + [-97, -80], us_coast_lat + [35, 35], 
                   color='tan', alpha=0.3, label='Land')
            
            # Caribbean islands (very simplified)
            ax.plot([-61, -65, -67, -72, -75, -77, -80, -84], 
                   [15, 18, 18.5, 19, 20, 21, 22, 22], 
                   'o', color='tan', markersize=4, alpha=0.7)
            
            # Labels and formatting
            ax.set_xlim(-100, -15)
            ax.set_ylim(5, 45)
            ax.set_xlabel('Longitude (°W)', fontsize=12)
            ax.set_ylabel('Latitude (°N)', fontsize=12)
            ax.set_title(f'Oracle V6.20 - {self.storm_name} ({self.storm_year}) Track\n'
                        f'Genesis: ({lats[0]:.1f}°N, {abs(lons[0]):.1f}°W) → '
                        f'Final: ({lats[-1]:.1f}°N, {abs(lons[-1]):.1f}°W)\n'
                        f'Distance: {self._compute_track_distance():.0f} nm | '
                        f'Peak: {max(winds) if winds else 0:.0f} kts',
                        fontsize=14)
            ax.legend(loc='upper left')
            ax.grid(True, alpha=0.3)
            ax.set_aspect('equal', adjustable='box')
            
            # Intensity legend
            legend_elements = [
                plt.Line2D([0], [0], color='#c00000', linewidth=4, label='Cat 5 (≥137 kt)'),
                plt.Line2D([0], [0], color='#ff6060', linewidth=4, label='Cat 4 (113-136 kt)'),
                plt.Line2D([0], [0], color='#ff8f20', linewidth=4, label='Cat 3 (96-112 kt)'),
                plt.Line2D([0], [0], color='#ffc140', linewidth=4, label='Cat 2 (83-95 kt)'),
                plt.Line2D([0], [0], color='#ffe775', linewidth=4, label='Cat 1 (64-82 kt)'),
                plt.Line2D([0], [0], color='#00faf4', linewidth=4, label='TS (34-63 kt)'),
            ]
            ax.legend(handles=legend_elements, loc='lower right', fontsize=9)
            
            # Save
            filename = f"{self.plot_dir}/track_{self.storm_name}_{self.storm_year}_final.png"
            plt.savefig(filename, dpi=200, bbox_inches='tight')
            plt.close(fig)
            log_info(f"    📊 Track plot saved: {filename}")
            
        except Exception as e:
            log_info(f"    ⚠️ Track plot failed: {e}")
    
    def _compute_track_distance(self):
        """Compute total track distance in nautical miles."""
        if not hasattr(self, 'track_history') or len(self.track_history) < 2:
            return 0.0
        total = 0.0
        for i in range(len(self.track_history) - 1):
            lat1, lon1 = self.track_history[i]
            lat2, lon2 = self.track_history[i + 1]
            # Haversine approximation
            dlat = np.radians(lat2 - lat1)
            dlon = np.radians(lon2 - lon1)
            a = np.sin(dlat/2)**2 + np.cos(np.radians(lat1)) * np.cos(np.radians(lat2)) * np.sin(dlon/2)**2
            c = 2 * np.arctan2(np.sqrt(a), np.sqrt(1-a))
            total += 3440.065 * c  # Earth radius in nm
        return total
    
    def _sync_environment(self, frame=0):
        """Sync SST, OHC, and steering flow with current position."""
        elapsed_seconds = frame * self.dt_solver * self.T_CHAR
        current_sim_time = self.genesis_time + timedelta(seconds=elapsed_seconds)
        self.data_interface.update_steering_data(
            self.current_center_lat, self.current_center_lon, current_sim_time, frame
        )
        half_domain_deg = (self.physical_domain_x_km / 2.0) / 111.0
        lat_min = self.current_center_lat - half_domain_deg
        lat_max = self.current_center_lat + half_domain_deg
        lon_min = self.current_center_lon - half_domain_deg / np.cos(np.radians(self.current_center_lat))
        lon_max = self.current_center_lon + half_domain_deg / np.cos(np.radians(self.current_center_lat))
        sst_slice, ohc_slice = self.basin.get_slice(lat_min, lat_max, lon_min, lon_max, self.nx, self.ny)
        self.SST = xp.asarray(sst_slice)
        self.OHC = xp.asarray(ohc_slice)
        if not hasattr(self, 'total_ohc_loss'):
            self.total_ohc_loss = 0.0
    
    # =========================================================================
    # V6 THETA: DIAGNOSTIC T UPDATE
    # =========================================================================
    
    def _update_diagnostic_T(self):
        """
        Compute diagnostic temperature T (°C) from θ′.
        
        T_total = θ_total × (P/P₀)^κ
        T_celsius = T_total - 273.15
        
        This maintains compatibility with existing tracker and visualizer.
        """
        # Total potential temperature
        theta_total = self.theta0_3d + self.theta_prime
        
        # Convert to actual temperature using pressure profile
        # T = θ × (P/P₀)^κ
        P_ratio = self.P_3d / self.ref_state.P0
        T_kelvin = theta_total * (P_ratio ** self.ref_state.kappa)
        
        # Store as Celsius for compatibility
        self.T = T_kelvin - 273.15
    
    def _theta_to_T_kelvin(self, theta, k_level=None):
        """Convert θ to T in Kelvin at specified level(s)."""
        if k_level is not None:
            P = self.P_1d[k_level]
        else:
            P = self.P_3d
        return theta * (P / self.ref_state.P0) ** self.ref_state.kappa
    
    def _get_T_kelvin_3d(self):
        """Get full 3D temperature field in Kelvin."""
        theta_total = self.theta0_3d + self.theta_prime
        P_ratio = self.P_3d / self.ref_state.P0
        return theta_total * (P_ratio ** self.ref_state.kappa)
    
    # =========================================================================
    # V6 THETA: STORM INITIALIZATION
    # =========================================================================
    
    def _initialize_storm_theta(self):
        """
        Initialize vortex with warm core in θ′ space.
        
        The warm core is represented as positive θ′ in the storm center,
        with maximum anomaly in the mid-troposphere.
        """
        cx, cy = self.nx // 2, self.ny // 2
        x = xp.arange(self.nx)
        y = xp.arange(self.ny)
        xx, yy = xp.meshgrid(x, y, indexing='ij')
        r = xp.sqrt((xx - cx)**2 + (yy - cy)**2) * self.dx * self.L_CHAR / 1000.0  # km
        
        # Initialize circulation (same as V5)
        R_max = 50.0  # km
        v_max = 25.0 / self.U_CHAR  # dimensionless (now 1.0)
        v_theta = v_max * (r / R_max) * xp.exp(0.5 * (1 - (r / R_max)**2))
        theta_angle = xp.arctan2(yy - cy, xx - cx)
        
        for k in range(self.nz):
            z_decay = xp.exp(-0.5 * (k / (self.nz / 4))**2)
            self.u[:,:,k] = -v_theta * xp.sin(theta_angle) * z_decay
            self.v[:,:,k] = v_theta * xp.cos(theta_angle) * z_decay
        
        # =====================================================================
        # V6 THETA: Warm core as θ′ perturbation
        # =====================================================================
        R_warm = 100.0  # km radius of warm core
        
        for k in range(self.nz):
            # Maximum θ′ at mid-levels (around 1/3 of domain height)
            z_factor = xp.exp(-((k - self.nz/3)**2) / (self.nz/2)**2)
            
            # Gaussian warm core in θ′
            theta_prime_anomaly = self.warm_core_theta_prime * xp.exp(-r**2 / (R_warm**2)) * z_factor
            self.theta_prime[:,:,k] += theta_prime_anomaly
        
        log_info(f"   θ′ warm core: max={float(xp.max(self.theta_prime)):.2f} K")
        
        # =====================================================================
        # MOISTURE INITIALIZATION (based on saturation at actual T)
        # =====================================================================
        # Update diagnostic T first
        self._update_diagnostic_T()
        
        for k in range(self.nz):
            T_celsius = self.T[:,:,k]
            T_clipped = xp.clip(T_celsius, -40.0, 50.0)
            
            # Clausius-Clapeyron saturation
            e_sat = 610.78 * xp.exp((17.27 * T_clipped) / (T_clipped + 237.3 + 1e-9))
            q_sat_local = 0.622 * e_sat / float(self.P_1d[k])  # Use actual pressure
            
            # V6.2: Pre-moisturize core to configurable RH (default 95%)
            # Five + Gemini identified that 95% RH kills the WISHE fuel gradient
            # Lower RH (82-85%) allows stronger evaporation flux
            z_factor = xp.exp(-((k - self.nz/3)**2) / (self.nz/2)**2)
            moisture_boost = (self.core_rh_init * q_sat_local - self.base_humidity) * xp.exp(-r**2 / (R_warm**2)) * z_factor
            moisture_boost = xp.maximum(moisture_boost, 0.0)
            self.q[:,:,k] += moisture_boost
        
        log_info(f"   💧 Core RH initialized to {self.core_rh_init*100:.0f}%")
        
        # Project to ensure divergence-free
        for _ in range(10):
            self.u, self.v, self.w, _ = self.solver.project(self.u, self.v, self.w, 1.0, 1.0)
        
        # Log initial state
        max_wind_ms = float(xp.max(xp.sqrt(self.u**2 + self.v**2)) * self.U_CHAR)
        log_info(f"   📊 Initial Max Wind: {max_wind_ms:.1f} m/s ({max_wind_ms*1.944:.1f} kts)")
        log_info(f"   📊 Initial θ′ range: [{float(xp.min(self.theta_prime)):.2f}, {float(xp.max(self.theta_prime)):.2f}] K")
        log_info(f"   📊 Initial T range: [{float(xp.min(self.T)):.1f}, {float(xp.max(self.T)):.1f}] °C")
    
    # =========================================================================
    # V6 THETA: MOIST ADJUSTMENT (condensation → θ′)
    # =========================================================================
    
    def apply_moist_adjustment_theta(self):
        """
        Moist adjustment in θ′ framework.
        
        When q > q_sat:
            1. Compute excess moisture
            2. Condense to saturation
            3. Release latent heat as θ′ tendency: dθ = (θ/T) × (Lv/Cp) × dq
        
        Uses actual T (from diagnostic) for saturation check.
        """
        Lv = LATENT_HEAT_VAPORIZATION
        Cp = self.ref_state.Cp
        epsilon = 0.622
        
        # Get actual temperature for saturation check
        T_kelvin = self._get_T_kelvin_3d()
        T_celsius = T_kelvin - 273.15
        
        # Clausius-Clapeyron saturation (using actual T and P)
        T_clipped = xp.clip(T_celsius, -40.0, 50.0)
        e_sat = 610.78 * xp.exp((17.27 * T_clipped) / (T_clipped + 237.3 + 1e-9))
        q_sat = epsilon * e_sat / self.P_3d
        
        # Find supersaturated cells
        supersat_mask = self.q > q_sat
        
        # Optional: temperature gating (if firewalls enabled)
        if not self.no_thermo_firewalls:
            too_hot_mask = T_celsius > 50.0  # Condensation temperature limit
            blocked = supersat_mask & too_hot_mask
            blocked_count = int(xp.sum(blocked))
            if blocked_count > 0:
                self.condensation_blocked_events += blocked_count
            valid_condensation = supersat_mask & (~too_hot_mask)
        else:
            valid_condensation = supersat_mask
        
        cells_adjusted = int(xp.sum(valid_condensation))
        
        if cells_adjusted == 0:
            return 0.0, 0
        
        # Compute condensation
        dq = xp.zeros_like(self.q)
        dq[valid_condensation] = self.q[valid_condensation] - q_sat[valid_condensation]
        total_condensed = float(xp.sum(dq))
        
        # Update moisture
        self.q[valid_condensation] = q_sat[valid_condensation]
        
        # =====================================================================
        # V6 THETA: Convert latent heat to θ′ tendency
        # dT = (Lv/Cp) × dq
        # dθ = (θ/T) × dT
        # V7.1: Scaled by precipitation efficiency (see BM scheme for details)
        # =====================================================================
        dT = (Lv / Cp) * dq  # Temperature change in K
        
        # Get total θ for the conversion factor
        theta_total = self.theta0_3d + self.theta_prime
        
        # θ/T factor (Five's correction)
        theta_over_T = theta_total / T_kelvin
        
        # Convert to θ′ tendency (scaled by precip efficiency)
        dtheta = self.precip_efficiency * theta_over_T * dT
        
        # Apply to θ′
        self.theta_prime += dtheta
        
        return total_condensed, cells_adjusted
    
    # =========================================================================
    # V7.0 BETTS-MILLER: RELAXED CONVECTIVE ADJUSTMENT
    # =========================================================================
    
    def apply_betts_miller_theta(self, dt_phys):
        """
        V7.0 Betts-Miller relaxed convective adjustment in θ′ framework.
        
        ARCHITECTURE (post-forensic fix):
          - Senses the FULL column including BL (no hard gate)
          - Applies tendencies with a smooth vertical taper near the surface
          - BL participates in triggering and reference profile, but is protected
            from aggressive drying by the taper weight function
        
        Taper: bm_weight(z) = clip((z - z0) / (z1 - z0), 0, 1) ^ power
          z0 = bm_taper_start_m (default 200m) — zero tendency below
          z1 = bm_taper_full_m  (default 2200m) — full tendency above
          power = bm_taper_power (default 1.0 = linear)
        
        This preserves the WISHE coupling: BM sees the high-θe BL air for
        triggering, builds reference profiles from surface parcels, but only
        fully extracts moisture in the free troposphere where deep convection
        actually condenses. The BL remains a conduit, not a tomb.
        """
        Lv = LATENT_HEAT_VAPORIZATION
        Cp = self.ref_state.Cp
        epsilon = 0.622
        
        # Get actual temperature for saturation
        T_kelvin = self._get_T_kelvin_3d()
        T_celsius = T_kelvin - 273.15
        
        # Clausius-Clapeyron saturation (same as instant scheme)
        T_clipped = xp.clip(T_celsius, -40.0, 50.0)
        e_sat = 610.78 * xp.exp((17.27 * T_clipped) / (T_clipped + 237.3 + 1e-9))
        q_sat = epsilon * e_sat / self.P_3d
        
        # =====================================================================
        # FULL-COLUMN SENSING: BM sees everything including BL.
        # No hard gate — cloud detection uses the entire column so the scheme
        # can properly diagnose surface-based instability and build reference
        # profiles from the high-θe boundary layer air.
        # =====================================================================
        cloud_threshold = 0.85
        cloud_mask = self.q > (cloud_threshold * q_sat)
        
        # Temperature gating (same as instant scheme)
        if not self.no_thermo_firewalls:
            too_hot_mask = T_celsius > 50.0
            cloud_mask = cloud_mask & (~too_hot_mask)
        
        # Reference profile: sub-saturated target
        q_ref = self.bm_reference_rh * q_sat
        
        # Only relax where q exceeds reference (drying, not moistening)
        excess_mask = (self.q > q_ref) & cloud_mask
        
        cells_active = int(xp.sum(excess_mask))
        if cells_active == 0:
            self._bm_columns_active = 0
            self._bm_last_precip_rate = 0.0
            self._bm_level_cells = xp.zeros(self.nz, dtype=int)
            self._bm_level_dq = xp.zeros(self.nz)
            self._bm_floor_clamps_frame = 0
            return 0.0, 0
        
        # =====================================================================
        # VERTICAL TAPER: Protect BL moisture while maintaining coupling.
        # Full BM tendency above taper_full_m, linearly (or power-law) reduced
        # to zero below taper_start_m. BM can SENSE the BL for triggering but
        # extracts moisture primarily in the free troposphere.
        # =====================================================================
        z = self.z_m_3d  # (1, 1, nz) — broadcasts to (nx, ny, nz)
        z0 = self.bm_taper_start_m
        z1 = self.bm_taper_full_m
        p = self.bm_taper_power
        bm_weight = xp.broadcast_to(
            xp.clip((z - z0) / (z1 - z0 + 1e-9), 0.0, 1.0) ** p,
            self.q.shape
        )
        
        # Relaxation factor: dt/τ_BM (capped at 1.0 for stability)
        relax_factor = min(dt_phys / self.tau_bm, 1.0)
        
        # Compute moisture tendency with taper applied
        dq = xp.zeros_like(self.q)
        dq[excess_mask] = -(self.q[excess_mask] - q_ref[excess_mask]) * relax_factor * bm_weight[excess_mask]
        
        # =====================================================================
        # BUDGET CLOSURE: Column-integrated moisture must not increase
        # =====================================================================
        col_dq = xp.sum(dq, axis=2)  # (nx, ny)
        bad_cols = col_dq > 0
        if xp.any(bad_cols):
            for k in range(self.nz):
                dq[:,:,k][bad_cols] = 0.0
        
        # =====================================================================
        # P2 DIAGNOSTICS: Per-level activity tracking
        # =====================================================================
        self._bm_level_cells = xp.zeros(self.nz, dtype=int)
        self._bm_level_dq = xp.zeros(self.nz)
        for k in range(self.nz):
            self._bm_level_cells[k] = int(xp.sum(excess_mask[:,:,k]))
            self._bm_level_dq[k] = float(xp.sum(dq[:,:,k]))
        
        # Total condensed moisture (positive = moisture removed from air)
        total_condensed = float(-xp.sum(dq))  # dq is negative, flip sign
        
        # Apply moisture tendency
        self.q += dq
        
        # Enforce moisture floor and track clamps per frame
        if self.moisture_floor > 0:
            floor_mask = self.q < self.moisture_floor
            self._bm_floor_clamps_frame = int(xp.sum(floor_mask))
            self.q = xp.maximum(self.q, self.moisture_floor)
        else:
            self._bm_floor_clamps_frame = 0
        
        # =====================================================================
        # Convert latent heat to θ′ tendency
        # dT = -(Lv/Cp) × dq  (dq negative → dT positive → warming)
        # dθ = (θ/T) × dT
        #
        # V7.1: Precipitation efficiency — only a fraction of latent heat
        # warms the column. The rest is implicitly exported by:
        #   - Rain evaporation cooling below cloud base (~30-40%)
        #   - Outflow heat transport at 200 hPa (~20-30%)
        #   - Sub-grid radiative losses (~10-20%)
        # Real hurricane net efficiency: ~20-30% (Holland 1997)
        # =====================================================================
        dT = -(Lv / Cp) * dq
        
        theta_total = self.theta0_3d + self.theta_prime
        theta_over_T = theta_total / T_kelvin
        
        dtheta = self.precip_efficiency * theta_over_T * dT
        self.theta_prime += dtheta
        
        # BM diagnostics
        self._bm_total_precip_kg += total_condensed
        self._bm_columns_active = cells_active
        self._bm_last_precip_rate = total_condensed * 1000.0
        
        return total_condensed, cells_active
    
    # =========================================================================
    # V6.2 THETA: MOIST-AWARE STRATIFICATION TERM
    # Updated based on Five + Gemini ensemble analysis
    # =========================================================================
    
    def apply_stratification_term(self, dt_physical):
        """
        Apply stratification with MOIST-AWARE reduction.
        
        V6.2 CHANGES (Five + Gemini Ensemble):
        --------------------------------------
        1. moist_floor is now configurable (default 0.3, recommend 0.0-0.1)
           - Physical reality: N²_eff ≈ 0 in saturated eyewall (moist-neutral)
           - V6.1 enforced 30-50% of dry stability = "permanent buoyancy tax"
        
        2. Optional: Apply moist reduction ONLY in updrafts (w > 0)
           - Keeps dry stratification in subsidence regions
           - Allows eyewall to "breathe" while maintaining environmental stability
        
        References:
            - Gemini Technical Audit (Jan 2026): "Thermodynamic Braking"
            - Five Implementation Review: "Buoyancy Tax" analysis
            - Emanuel (1994): Moist-neutral eyewall dynamics
        """
        # Convert vertical velocity to physical units
        w_physical = self.w * self.U_CHAR  # m/s
        
        # =====================================================================
        # Compute saturation state for moist-awareness
        # =====================================================================
        T_kelvin = self._get_T_kelvin_3d()
        T_celsius = T_kelvin - 273.15
        T_clipped = xp.clip(T_celsius, -40.0, 50.0)
        
        # Saturation vapor pressure (Clausius-Clapeyron)
        e_sat = 610.78 * xp.exp((17.27 * T_clipped) / (T_clipped + 237.3 + 1e-9))
        q_sat = 0.622 * e_sat / self.P_3d
        
        # Relative humidity (clamped to physical range)
        RH = xp.clip(self.q / (q_sat + 1e-10), 0.0, 1.0)
        
        # =====================================================================
        # V6.2: Configurable moist factor with configurable floor
        # =====================================================================
        # Temperature-dependent moist/dry ratio
        moist_factor_raw = 0.4 + 0.003 * T_clipped
        
        # V6.2: Use configurable floor (default 0.3, can be 0.0 for moist-neutral)
        moist_floor = self.moist_floor  # From config
        moist_factor = xp.clip(moist_factor_raw, moist_floor, 0.7)
        
        # =====================================================================
        # Saturation blend - smooth transition from dry to moist
        # =====================================================================
        RH_dry_threshold = 0.80
        RH_sat_threshold = 0.95
        
        saturation_blend = xp.clip(
            (RH - RH_dry_threshold) / (RH_sat_threshold - RH_dry_threshold),
            0.0, 1.0
        )
        
        # =====================================================================
        # V6.2: Optional updraft-only moist reduction
        # =====================================================================
        # If enabled: apply moist reduction only where w > 0 (rising air)
        # Subsidence regions keep full dry stratification
        
        if self.updraft_only_moist:
            # Only reduce stratification in updrafts
            updraft_mask = (self.w > 0).astype(float)
            saturation_blend = saturation_blend * updraft_mask
        
        # =====================================================================
        # Compute effective stratification
        # =====================================================================
        # effective_factor = 1.0 in dry air (full stratification)
        # effective_factor = moist_factor in saturated updraft (reduced)
        
        effective_factor = 1.0 - saturation_blend * (1.0 - moist_factor)
        
        # Effective stratification gradient
        effective_dtheta_dz = self.dtheta0_dz * effective_factor
        
        # =====================================================================
        # Apply stratification tendency
        # =====================================================================
        dtheta_dt = -w_physical * effective_dtheta_dz  # K/s
        
        self.theta_prime += dtheta_dt * dt_physical
        
        # =====================================================================
        # V6.2 Diagnostics
        # =====================================================================
        total_cooling = float(xp.sum(xp.abs(dtheta_dt * dt_physical)))
        self.stratification_cooling_total += total_cooling
        
        # Track moist vs dry contribution
        mean_effective_factor = float(xp.mean(effective_factor))
        mean_saturation_blend = float(xp.mean(saturation_blend))
        
        # V6.2: Also track in updraft regions specifically
        updraft_mask = (self.w > 0)
        if xp.any(updraft_mask):
            eff_in_updrafts = float(xp.mean(effective_factor[updraft_mask]))
        else:
            eff_in_updrafts = 1.0
        
        # Store for logging
        self._last_strat_effective_factor = mean_effective_factor
        self._last_strat_saturation_blend = mean_saturation_blend
        self._last_strat_eff_in_updrafts = eff_in_updrafts
        
        return total_cooling
    
    # =========================================================================
    # V6 THETA: BUOYANCY (from θ′)
    # =========================================================================
    
    def apply_buoyancy_theta(self, dt_physical):
        """
        Apply buoyancy from θ′ perturbation.
        
        b = g × θ′ / θ₀(z)    [m/s²]
        
        No artificial clamping - the θ₀(z) profile provides natural
        limits through atmospheric stability.
        
        Nondimensional scaling (Five's correction):
            w_nd += b × (T_CHAR / U_CHAR) × dt_solver
        """
        # Compute buoyancy [m/s²]
        buoyancy_physical = self.g * self.theta_prime / self.theta0_3d
        
        # Track raw buoyancy for diagnostics
        b_raw = float(xp.max(xp.abs(buoyancy_physical)))
        
        # Optional: buoyancy clamping (if firewalls enabled)
        if not self.no_thermo_firewalls and self.buoyancy_cap > 0:
            buoyancy_limited = self.buoyancy_cap * xp.tanh(buoyancy_physical / self.buoyancy_cap)
            b_limited = float(xp.max(xp.abs(buoyancy_limited)))
            if b_raw > self.buoyancy_cap:
                self.buoyancy_clamp_events += 1
        else:
            buoyancy_limited = buoyancy_physical
            b_limited = b_raw
        
        # Convert to dimensionless vertical velocity tendency
        # w_nd += b × (T_CHAR / U_CHAR) × dt_solver
        dt_dimensionless = self.dt_solver
        buoyancy_dimensionless = buoyancy_limited * (self.T_CHAR / self.U_CHAR)
        
        self.w += buoyancy_dimensionless * dt_dimensionless
        
        # Optional: updraft limiting (if firewalls enabled)
        if not self.no_thermo_firewalls and self.max_updraft > 0:
            w_physical = self.w * self.U_CHAR
            excessive = xp.abs(w_physical) > self.max_updraft
            if xp.any(excessive):
                w_limited = self.max_updraft * xp.tanh(w_physical / self.max_updraft)
                self.w = w_limited / self.U_CHAR
        
        # Clamp fraction for diagnostics
        if b_raw > 0:
            clamp_frac = 1.0 - (b_limited / b_raw) if b_raw > b_limited else 0.0
        else:
            clamp_frac = 0.0
        
        return b_raw, b_limited, clamp_frac
    
    # =========================================================================
    # V6.3 SUSTAIN: SURFACE FLUXES WITH DYNAMIC WISHE BOOSTING
    # =========================================================================
    
    def apply_surface_fluxes_theta(self, dt_physical):
        """
        Apply surface fluxes to θ′ and q.
        
        V6.3 SUSTAIN: Dynamic WISHE Boosting (Gemini Fix)
        -------------------------------------------------
        Standard bulk formulas give Ck/Cd ≈ 0.9, but hurricanes need ≈ 1.2-1.5
        to sustain intensity. As winds increase, drag overtakes energy input,
        causing the "burn hot, burn short" decay pattern.
        
        Fix: Boost the θ′ surface heating as wind speed increases.
        
        V6.5: Flux Throttle (Gemini Stability Fix)
        ------------------------------------------
        If dθ'/dt exceeds threshold, disable WISHE boost to prevent runaway
        from numerical instability (cubic overshoot → WISHE feedback loop).
        
        V6.7: Proportional/Integral Throttle (Gemini Balance Fix)
        ---------------------------------------------------------
        Instead of binary on/off, proportionally reduce WISHE based on:
        1. Rate of θ′ change (derivative term)
        2. Absolute θ′ value (integral term)
        This prevents the "fuel cutoff → collapse → runaway" cycle.
        """
        land_frac = getattr(self.data_interface, 'land_fraction', None)
        
        # =====================================================================
        # V6.7: PROPORTIONAL/INTEGRAL FLUX THROTTLE
        # =====================================================================
        throttle_factor = 1.0  # 1.0 = no throttle, 0.0 = full throttle
        
        if getattr(self, 'flux_throttle_enabled', False):
            current_theta_max = float(xp.max(self.theta_prime))
            
            if getattr(self, 'proportional_throttle', False):
                # =============================================================
                # V6.7: PROPORTIONAL MODE - Gradual reduction
                # =============================================================
                
                # Component 1: DERIVATIVE (rate-based) throttle
                rate_factor = 1.0
                if self._prev_theta_prime_max is not None:
                    dtheta_dt = (current_theta_max - self._prev_theta_prime_max) / (dt_physical / 60.0)
                    
                    if dtheta_dt > self.flux_throttle_threshold:
                        # Proportionally reduce based on how much we exceed threshold
                        # At 1x threshold: factor = 1.0
                        # At 2x threshold: factor = 0.5
                        # At 3x threshold: factor = 0.33
                        rate_factor = self.flux_throttle_threshold / max(dtheta_dt, 0.001)
                        rate_factor = max(0.1, min(1.0, rate_factor))  # Clamp to [0.1, 1.0]
                        self._flux_throttle_events += 1
                
                # Component 2: INTEGRAL (absolute θ′) throttle
                # Linear ramp from soft_limit (1.0) to hard_limit (0.0)
                if current_theta_max > self.theta_prime_soft_limit:
                    range_width = self.theta_prime_hard_limit - self.theta_prime_soft_limit
                    excess = current_theta_max - self.theta_prime_soft_limit
                    integral_factor = 1.0 - (excess / range_width)
                    integral_factor = max(0.0, min(1.0, integral_factor))
                else:
                    integral_factor = 1.0
                
                # Combined factor: use the more restrictive of the two
                throttle_factor = min(rate_factor, integral_factor)
                
                # Track state
                self._throttle_factor = throttle_factor
                self._flux_throttle_active = throttle_factor < 0.99
                
            else:
                # =============================================================
                # V6.5: BINARY MODE (original behavior)
                # =============================================================
                if self._prev_theta_prime_max is not None:
                    dtheta_dt = (current_theta_max - self._prev_theta_prime_max) / (dt_physical / 60.0)
                    
                    if dtheta_dt > self.flux_throttle_threshold:
                        throttle_factor = 0.0  # Binary: completely disable
                        self._flux_throttle_active = True
                        self._flux_throttle_events += 1
                    else:
                        self._flux_throttle_active = False
                
                self._throttle_factor = throttle_factor
            
            # Store for next timestep
            self._prev_theta_prime_max = current_theta_max
        
        # =====================================================================
        # V6.3: Calculate WISHE boost factor based on surface wind
        # V6.7: Apply proportional throttle to boost
        # V6.13: Configurable wind thresholds for activation
        # =====================================================================
        
        # =====================================================================
        # V6.26 FIX: HIGH-LATITUDE THERMODYNAMIC DAMPING (Gemini Deep Dive)
        # =====================================================================
        # Problem: "Zombie Thermodynamics" - tropical θ′ conserved at high latitudes
        #          Creating 219 kt hypercane at 47°N (physical impossibility!)
        #
        # Physics: Real TCs lose intensity at high latitudes due to:
        #          - Cold SSTs (< 26°C cuts off latent heat flux)
        #          - Strong wind shear from jet stream
        #          - Baroclinic transition (different energy source)
        #
        # V6.26.1 FIX: Stronger damping, earlier onset, throttled logging
        #   - Threshold: 30°N (was 35°N) - start damping earlier
        #   - Scale: 7° (was 10°) - steeper falloff
        #   - Logging: Only on threshold crossings (fixes 9MB log spam!)
        # =====================================================================
        HIGH_LAT_DAMPING_ENABLED = getattr(self, 'high_lat_damping_enabled', True)
        HIGH_LAT_THRESHOLD = 30.0  # V6.26.1: Earlier onset (was 35°N)
        HIGH_LAT_SCALE = 7.0       # V6.26.1: Steeper decay (was 10°)
        
        if HIGH_LAT_DAMPING_ENABLED and hasattr(self, 'current_center_lat'):
            lat = abs(self.current_center_lat)  # Handle both hemispheres
            if lat > HIGH_LAT_THRESHOLD:
                lat_damping_factor = np.exp(-(lat - HIGH_LAT_THRESHOLD) / HIGH_LAT_SCALE)
                
                # V6.26.1: Throttled logging - only on threshold crossings
                last_damping = getattr(self, '_last_lat_damping_factor', 1.0)
                thresholds = [0.9, 0.75, 0.5, 0.25, 0.1]
                crossed = False
                for thresh in thresholds:
                    if (last_damping >= thresh and lat_damping_factor < thresh) or \
                       (last_damping < thresh and lat_damping_factor >= thresh):
                        crossed = True
                        break
                
                if crossed or not hasattr(self, '_last_lat_damping_factor'):
                    log_info(f"    🧊 HIGH-LAT DAMPING: lat={lat:.1f}°N → thermo×{lat_damping_factor:.3f}")
                
                self._last_lat_damping_factor = lat_damping_factor
            else:
                lat_damping_factor = 1.0
                if hasattr(self, '_last_lat_damping_factor') and self._last_lat_damping_factor < 1.0:
                    log_info(f"    🧊 HIGH-LAT DAMPING: lat={lat:.1f}°N → thermo×1.000 (damping OFF)")
                self._last_lat_damping_factor = 1.0
        else:
            lat_damping_factor = 1.0
        
        if getattr(self, 'wishe_boost_enabled', False) and throttle_factor > 0.0:
            u_sfc = self.u[:,:,0]
            v_sfc = self.v[:,:,0]
            wind_speed_dim = xp.sqrt(u_sfc**2 + v_sfc**2)
            wind_speed_phys = wind_speed_dim * self.U_CHAR  # m/s
            
            # V6.13: Configurable linear ramp
            # Default: 1.0 at 15 m/s, wishe_boost_max at 40 m/s
            wishe_boost_max = getattr(self, 'wishe_boost_max', 1.4)
            wishe_wind_min = getattr(self, 'wishe_wind_min', 15.0)
            wishe_wind_max = getattr(self, 'wishe_wind_max', 40.0)
            wind_range = wishe_wind_max - wishe_wind_min
            ramp = xp.clip((wind_speed_phys - wishe_wind_min) / wind_range, 0.0, 1.0)
            
            # V6.7: Apply throttle factor to the boost amount (not base flux)
            # When throttle_factor = 1.0: full boost (1.0 to wishe_boost_max)
            # When throttle_factor = 0.5: half boost (1.0 to 1.0 + 0.5*(max-1))
            # When throttle_factor = 0.0: no boost (1.0)
            effective_boost_max = 1.0 + (wishe_boost_max - 1.0) * throttle_factor
            boost_factor = 1.0 + (effective_boost_max - 1.0) * ramp
            
            # Track for diagnostics
            self._last_wishe_boost_max = float(xp.max(boost_factor))
            self._last_wishe_boost_mean = float(xp.mean(boost_factor))
        else:
            boost_factor = None
            self._last_wishe_boost_max = 1.0
            self._last_wishe_boost_mean = 1.0
        
        # =====================================================================
        # Standard surface flux call (handles q and returns T change)
        # =====================================================================
        q_new, T_new_celsius, mean_q_flux, mean_h_flux, damp = self.boundaries.apply_surface_fluxes(
            self.q, self.T, 1.0, land_fraction=land_frac
        )
        
        # Update moisture directly (no boost to q - focus on heat)
        self.q = q_new
        
        # =====================================================================
        # V7.1: WARM RAIN — Surface Saturation Cap
        # =====================================================================
        # Problem: BM taper has zero weight at level 0 (below 200m), so surface
        # moisture is never consumed by convection. Horizontal advection converges
        # moisture into the core, driving q_sfc to 2× saturation (unphysical).
        #
        # V7.1.2: ALL-LEVEL WARM RAIN WITH VIRGA PHYSICS
        # Physics: Supersaturation at ANY level is unphysical and must precipitate.
        # Moisture removal operates at all levels (maintaining vertical gradients).
        #
        # HEATING: Height-dependent via virga physics. In real hurricanes, rain
        # that condenses above the melting level (~0°C, ~2500m in tropics) falls
        # and partially re-evaporates below, cooling the sub-cloud layer. The net
        # column heating from upper-level condensation is near zero — the latent
        # heat released at altitude is returned to the environment via evaporative
        # cooling of falling hydrometeors (virga). Only warm rain at low levels
        # (below the melting level) represents irreversible heating.
        #
        # Without this, the cap acts as a continuous latent heat pump at upper
        # levels: advection refills moisture → cap removes it → dumps heat into
        # θ′ → every timestep → θ′ runaway.
        #
        # Implementation:
        #   - Moisture cap: all levels at warm_rain_cap × q_sat (unchanged)
        #   - Heating weight: 1.0 below 2000m, linear taper to 0.0 by 4000m, 
        #     zero above (virga zone: rain evaporates before reaching ground)
        # =====================================================================
        if self.warm_rain:
            Lv = LATENT_HEAT_VAPORIZATION
            Cp = self.ref_state.Cp
            epsilon = 0.622
            
            # Get 3D temperature for saturation at all levels
            T_kelvin_3d = self._get_T_kelvin_3d()
            T_celsius_3d = T_kelvin_3d - 273.15
            T_clipped_3d = xp.clip(T_celsius_3d, -40.0, 50.0)
            
            # Clausius-Clapeyron at all levels
            e_sat_3d = 610.78 * xp.exp((17.27 * T_clipped_3d) / (T_clipped_3d + 237.3 + 1e-9))
            q_sat_3d = epsilon * e_sat_3d / self.P_3d
            
            # Soft cap at all levels: warm_rain_cap × q_sat
            q_cap_3d = self.warm_rain_cap * q_sat_3d
            
            # Find all cells exceeding the soft cap
            excess_mask_3d = self.q > q_cap_3d
            
            if xp.any(excess_mask_3d):
                # Compute excess moisture above the soft cap
                dq_excess_3d = xp.where(excess_mask_3d, self.q - q_cap_3d, 0.0)
                
                # Cap moisture at the soft threshold (ALL levels — gradient maintenance)
                self.q = xp.where(excess_mask_3d, q_cap_3d, self.q)
                
                # Virga heating weight: only warm rain below melting level heats θ′
                # Above melting level, rain falls and re-evaporates (net heating ≈ 0)
                # z < 2000m: full heating (1.0)
                # 2000m < z < 4000m: linear taper
                # z > 4000m: no heating (0.0) — virga/ice zone
                virga_weight = xp.clip((4000.0 - self.z_m_3d) / 2000.0, 0.0, 1.0)
                
                # Convert excess to latent heat → θ′ (scaled by efficiency AND virga weight)
                dT_rain_3d = (Lv / Cp) * dq_excess_3d
                theta_total_3d = self.theta0_3d + self.theta_prime
                theta_over_T_3d = theta_total_3d / T_kelvin_3d
                dtheta_rain_3d = self.precip_efficiency * virga_weight * theta_over_T_3d * dT_rain_3d
                self.theta_prime += dtheta_rain_3d
                
                # Diagnostic tracking
                self._warm_rain_total_precip += float(xp.sum(dq_excess_3d))
        
        # =====================================================================
        # V6.7: Apply moisture floor to prevent negative specific humidity
        # =====================================================================
        if getattr(self, 'moisture_floor', 0.0) > 0.0:
            floor_violations = xp.sum(self.q < self.moisture_floor)
            if floor_violations > 0:
                self.q = xp.maximum(self.q, self.moisture_floor)
                self._moisture_floor_events += int(floor_violations)
        
        # =====================================================================
        # V6 THETA: Convert T change to θ′ change at surface
        # =====================================================================
        dT_surface = T_new_celsius[:,:,0] - self.T[:,:,0]  # Change in °C (= K)
        
        # Get θ and T at surface for conversion factor
        theta_total_surface = self.theta0_3d[:,:,0] + self.theta_prime[:,:,0]
        T_kelvin_surface = self._theta_to_T_kelvin(theta_total_surface, k_level=0)
        
        # θ/T conversion factor (Five's correction)
        theta_over_T = theta_total_surface / T_kelvin_surface
        
        # Convert to θ′ change
        dtheta_surface = theta_over_T * dT_surface
        
        # =====================================================================
        # V6.3 SUSTAIN: Apply WISHE boost to the θ′ surface heating
        # =====================================================================
        if boost_factor is not None:
            dtheta_surface = dtheta_surface * boost_factor
        
        # =====================================================================
        # V6.26: Apply high-latitude damping (Gemini's "Zombie Thermodynamics" fix)
        # =====================================================================
        if lat_damping_factor < 1.0:
            dtheta_surface = dtheta_surface * lat_damping_factor
        
        # Apply to θ′
        self.theta_prime[:,:,0] += dtheta_surface
        
        # =====================================================================
        # V6.26.1 FIX: θ′ RELAXATION AT HIGH LATITUDES (Gemini Fix #6)
        # =====================================================================
        # Problem: Even with damped surface fluxes, accumulated tropical θ′ persists
        #          This "zombie energy" sustains hypercane intensity at 47°N
        #
        # Physics: In reality, baroclinic processes drain tropical heat poleward
        #          The periodic domain can't represent this, so we add explicit relaxation
        #
        # Fix: Relax θ′ toward zero north of 40°N with τ = 6 hours
        #      This drains accumulated tropical energy at ~16%/hour
        # =====================================================================
        THETA_RELAX_ENABLED = getattr(self, 'theta_relax_enabled', True)
        THETA_RELAX_LAT_THRESHOLD = 40.0  # Start relaxation at this latitude
        THETA_RELAX_TAU_HOURS = 6.0       # e-folding time in hours
        
        if THETA_RELAX_ENABLED and hasattr(self, 'current_center_lat'):
            lat = abs(self.current_center_lat)
            if lat > THETA_RELAX_LAT_THRESHOLD:
                # Calculate relaxation factor
                # dt_solver is nondimensional, T_CHAR converts to seconds
                dt_seconds = self.dt_solver * self.T_CHAR
                tau_seconds = THETA_RELAX_TAU_HOURS * 3600.0
                relax_factor = dt_seconds / tau_seconds
                
                # Latitude-dependent relaxation (stronger further north)
                lat_boost = 1.0 + (lat - THETA_RELAX_LAT_THRESHOLD) / 10.0
                relax_factor *= lat_boost
                
                # Apply relaxation toward zero
                # θ′_new = θ′_old × (1 - relax_factor)
                relax_factor = min(relax_factor, 0.1)  # Cap at 10% per step for stability
                self.theta_prime *= (1.0 - relax_factor)
                
                # Throttled logging (only every 5000 frames)
                current_frame = getattr(self, 'frame', 0)
                if not hasattr(self, '_last_relax_log_frame') or \
                   current_frame - self._last_relax_log_frame >= 5000:
                    theta_max = float(xp.max(self.theta_prime))
                    log_info(f"    🧟 θ′ RELAXATION: lat={lat:.1f}°N, relax={relax_factor:.4f}/step, θ′_max={theta_max:.1f}K")
                    self._last_relax_log_frame = current_frame
        
        # Update diagnostic T
        self._update_diagnostic_T()
        
        return mean_q_flux, mean_h_flux, damp
    
    # =========================================================================
    # SANITY CHECK
    # =========================================================================
    
    def sanity_check(self, frame):
        """Check for NaN/Inf and extreme values."""
        has_nan = (
            not xp.all(xp.isfinite(self.u)) or
            not xp.all(xp.isfinite(self.v)) or
            not xp.all(xp.isfinite(self.w)) or
            not xp.all(xp.isfinite(self.theta_prime)) or
            not xp.all(xp.isfinite(self.q))
        )
        
        if has_nan:
            log_info(f"    🚨 EMERGENCY: NaN/Inf detected at frame {frame}!")
            return False
        
        # V6.2: Check θ′ bounds (now configurable)
        theta_prime_max = float(xp.max(self.theta_prime))
        theta_prime_min = float(xp.min(self.theta_prime))
        
        if theta_prime_max > self.theta_prime_max_bound or theta_prime_min < self.theta_prime_min_bound:
            log_info(f"    🚨 EMERGENCY: θ′ out of bounds [{theta_prime_min:.1f}, {theta_prime_max:.1f}] K")
            log_info(f"       (bounds: [{self.theta_prime_min_bound:.0f}, {self.theta_prime_max_bound:.0f}] K)")
            return False
        
        return True
    
    # =========================================================================
    # TRANSLATION SPEED CALCULATION
    # =========================================================================
    
    def calculate_translation_speed(self):
        """Calculate storm translation speed from position history."""
        if len(self.position_history) < 2:
            return 0.0
        
        p1 = self.position_history[-2]
        p2 = self.position_history[-1]
        
        lat1, lon1 = np.radians(p1['lat']), np.radians(p1['lon'])
        lat2, lon2 = np.radians(p2['lat']), np.radians(p2['lon'])
        
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        
        a = np.sin(dlat/2)**2 + np.cos(lat1) * np.cos(lat2) * np.sin(dlon/2)**2
        c = 2 * np.arcsin(np.sqrt(a))
        
        R_earth_nm = 3440.065
        distance_nm = R_earth_nm * c
        
        dframe = p2['frame'] - p1['frame']
        dt_seconds = dframe * self.dt_solver * self.T_CHAR
        dt_hours = dt_seconds / 3600.0
        
        if dt_hours > 0:
            return distance_nm / dt_hours
        return 0.0
    
    # =========================================================================
    # MAIN UPDATE LOOP
    # =========================================================================
    
    def update(self, frame):
        """
        V6 THETA: Single timestep update.
        
        Step order (Five's consensus):
            1. Advect u, v, w
            2. Advect θ′ and q
            3. Diffusion
            4. Surface drag
            5. Surface fluxes (→ θ′ and q)
            6. Moist adjustment (V7: BM relaxation or V6 instant → θ′)
            7. Stratification term: θ′ += -w dθ₀/dz
            8. Buoyancy from θ′
            9. Coriolis
            10. Pressure projection
            11. Sponge
            12. Update diagnostic T
        """
        if self.emergency_halted:
            return
        
        dt_phys = self.dt_solver * self.T_CHAR
        
        # Diagnostics at frame 100
        if frame == 100:
            log_info(f"🔍 V6 DIAGNOSTIC: θ′ mean={float(xp.mean(self.theta_prime)):.3f} K")
            log_info(f"🔍 V6 DIAGNOSTIC: θ′ range=[{float(xp.min(self.theta_prime)):.2f}, {float(xp.max(self.theta_prime)):.2f}] K")
            log_info(f"🔍 V6 DIAGNOSTIC: T (diagnostic) mean={float(xp.mean(self.T)):.1f}°C")
            log_info(f"🔍 V6 DIAGNOSTIC: SST mean={float(xp.mean(self.SST)):.1f}°C")
        
        # =====================================================================
        # 1-2: ADVECTION
        # =====================================================================
        self.u = self.solver.advect(self.u, self.u, self.v, self.w)
        self.v = self.solver.advect(self.v, self.u, self.v, self.w)
        self.w = self.solver.advect(self.w, self.u, self.v, self.w)
        self.theta_prime = self.solver.advect(self.theta_prime, self.u, self.v, self.w)
        self.q = self.solver.advect(self.q, self.u, self.v, self.w)
        
        # =====================================================================
        # 3: DIFFUSION
        # =====================================================================
        nu_t = self.solver.compute_smagorinsky_viscosity(self.u, self.v, self.w, Cs=self.Cs)
        self.u += self.dt_solver * nu_t * self.solver.laplacian(self.u)
        self.v += self.dt_solver * nu_t * self.solver.laplacian(self.v)
        self.w += self.dt_solver * nu_t * self.solver.laplacian(self.w)
        # Also diffuse θ′
        self.theta_prime += self.dt_solver * nu_t * self.solver.laplacian(self.theta_prime)
        
        # =================================================================
        # V6.3 SUSTAIN: COLD ANOMALY DIFFUSION (The "Anti-Crash" Patch)
        # =================================================================
        # Gemini identified that -17K cold "holes" from evaporative cooling
        # were causing simulation halts. These "cold rocks" of heavy air
        # crash through the updraft structure.
        # 
        # Fix: Diffuse ONLY the cold anomalies (θ′ < -4K) aggressively,
        # while leaving the warm core (updrafts) untouched.
        
        if self.cold_diffusion_enabled:
            cold_threshold = -4.0  # K
            cold_mask = self.theta_prime < cold_threshold
            num_cold_cells = int(xp.sum(cold_mask))
            
            if num_cold_cells > 0:
                # Create a diffusion coefficient that is strong ONLY where it is cold
                # Scale by dt_solver for proper time integration
                # Also scale by dx² to make coefficient dimensionally correct
                dx2 = self.dx * self.dx  # Dimensionless grid spacing squared
                cold_diffusivity = self.cold_diffusion_strength * self.dt_solver / dx2
                
                # Compute laplacian and apply ONLY to cold spots
                lap_theta = self.solver.laplacian(self.theta_prime)
                
                # Apply correction only where cold (mask out warm regions)
                correction = cold_diffusivity * lap_theta * cold_mask.astype(float)
                
                # Sanity check: don't apply if correction is too large
                max_correction = float(xp.max(xp.abs(correction)))
                if max_correction < 10.0:  # Reasonable limit
                    self.theta_prime += correction
                    self._cold_diffusion_events += num_cold_cells
        
        # =====================================================================
        # 4: SURFACE DRAG
        # =====================================================================
        u_surface = self.u[:, :, 0]
        v_surface = self.v[:, :, 0]
        land_frac = getattr(self.data_interface, 'land_fraction', None)
        tau_x, tau_y = self.boundaries.calculate_surface_drag(u_surface, v_surface, land_fraction=land_frac)
        dz_m = self.domain_scaler.dimensionless_to_physical_z(self.dz)
        rho_air = self.boundaries.air_density
        self.u[:, :, 0] += (-tau_x / (rho_air * dz_m) * dt_phys) / self.U_CHAR
        self.v[:, :, 0] += (-tau_y / (rho_air * dz_m) * dt_phys) / self.U_CHAR
        
        # =====================================================================
        # 5: SURFACE FLUXES (V6: θ′ update with θ/T factor)
        # =====================================================================
        mean_q_flux, mean_h_flux, damp = self.apply_surface_fluxes_theta(dt_phys)
        
        # =====================================================================
        # 6: MOIST ADJUSTMENT (V7: BM relaxation OR V6 instant saturation)
        # =====================================================================
        if self.betts_miller_enabled:
            condensed, cells_adjusted = self.apply_betts_miller_theta(dt_phys)
        else:
            condensed, cells_adjusted = self.apply_moist_adjustment_theta()
        if cells_adjusted > 0:
            self.total_condensation_events += 1
            self.total_latent_heat_released += condensed * LATENT_HEAT_VAPORIZATION
        
        # OHC accounting
        latent_power = mean_q_flux * LATENT_HEAT_VAPORIZATION
        total_power = latent_power + mean_h_flux
        self.total_ohc_loss += (total_power * dt_phys) / 1e7
        
        # =====================================================================
        # 7: STRATIFICATION TERM (V6: replaces adiabatic cooling!)
        # =====================================================================
        strat_cooling = self.apply_stratification_term(dt_phys)
        
        # =====================================================================
        # 8: BUOYANCY (V6: from θ′)
        # =====================================================================
        b_raw, b_limited, clamp_frac = self.apply_buoyancy_theta(dt_phys)
        
        # =====================================================================
        # 9: CORIOLIS
        # =====================================================================
        f_nd = self.f0 * self.T_CHAR
        alpha = 0.5 * f_nd * self.dt_solver
        D = 1.0 + alpha**2
        u_old, v_old = self.u.copy(), self.v.copy()
        self.u = ((1.0 - alpha**2) * u_old + 2.0 * alpha * v_old) / D
        self.v = (-2.0 * alpha * u_old + (1.0 - alpha**2) * v_old) / D
        
        # =====================================================================
        # 10: PRESSURE PROJECTION
        # =====================================================================
        self.u, self.v, self.w, p = self.solver.project(self.u, self.v, self.w, 1.0, 1.0)
        
        # =====================================================================
        # 11: SPONGE
        # =====================================================================
        if self.sponge_strength > 0:
            damping = 1.0 - self.sponge_strength * (1.0 - self.sponge_mask[:,:,xp.newaxis])
            self.u *= damping
            self.v *= damping
        
        # =====================================================================
        # 11b: VERTICAL SPONGE LAYER (V7.1 — Gemini Remediation §5.2)
        # =====================================================================
        # Rayleigh damping in top 20% of domain:
        #   w → 0 (rigid lid), θ′ → 0 (absorb gravity waves),
        #   q → q_ref (prevent moisture accumulation at model top)
        # =====================================================================
        if hasattr(self, 'vert_sponge_3d'):
            sponge = self.vert_sponge_strength * self.vert_sponge_3d
            self.w *= (1.0 - sponge)                          # w → 0
            self.theta_prime *= (1.0 - sponge)                # θ′ → 0
            # q → q_ref (not zero — maintain the reference profile shape)
            q_ref_3d = self.q_ref_profile[xp.newaxis, xp.newaxis, :]
            self.q += sponge * (q_ref_3d - self.q)
        
        # =====================================================================
        # 11c: FAR-FIELD MOISTURE RELAXATION (V7.1 — Gemini §5.1)
        # =====================================================================
        # Nudge q toward reference profile outside the storm core.
        # Prevents the storm from drying out its own environment over long runs.
        # τ_relax ~ 12 hours in far field, inactive within r < 500 km.
        # =====================================================================
        if hasattr(self, 'q_ref_profile') and frame % 10 == 0:
            # Compute distance from storm center
            cx, cy = self.nx // 2, self.ny // 2
            ix = xp.arange(self.nx)
            iy = xp.arange(self.ny)
            ixx, iyy = xp.meshgrid(ix, iy, indexing='ij')
            r_grid = xp.sqrt(((ixx - cx) * self.dx_physical / 1000.0)**2 + 
                             ((iyy - cy) * self.dy_physical / 1000.0)**2)  # km
            
            # Smooth transition: 0 inside 400km, ramping to 1 at 600km+
            r_inner, r_outer = 400.0, 600.0
            relax_mask = xp.clip((r_grid - r_inner) / (r_outer - r_inner), 0.0, 1.0)
            relax_mask_3d = relax_mask[:, :, xp.newaxis]
            
            # Relaxation rate: τ = 12 hours → per-step factor
            # Applied every 10 frames, so effective dt = 10 * 2.4s = 24s
            tau_relax = 12.0 * 3600.0  # 12 hours in seconds
            dt_relax = 10 * dt_phys
            relax_factor = dt_relax / tau_relax  # ~5.6e-4 per application
            
            q_ref_3d = self.q_ref_profile[xp.newaxis, xp.newaxis, :]
            self.q += relax_factor * relax_mask_3d * (q_ref_3d - self.q)
        
        # =====================================================================
        # V6.4 SINK: RADIATIVE COOLING + MEAN REMOVAL (Five's Fix)
        # V6.6 ENHANCEMENT: DYNAMIC COOLING (Gemini's Fix)
        # Addresses runaway θ′ accumulation in periodic domain
        # =====================================================================
        
        # 11a: Newtonian radiative cooling (relaxes θ′ toward zero)
        if self.radiative_cooling_enabled:
            if self.dynamic_cooling_enabled:
                # V6.6: Dynamic τ_rad that scales with local θ′
                # τ_rad = max(τ_min, τ_base × e^(-|θ′| / θ_scale))
                # 
                # Physical motivation: Hot cloud tops radiate more efficiently.
                # When θ′ is small, τ_rad stays at base value (gentle cooling).
                # When θ′ > θ_scale, τ_rad drops exponentially toward τ_min.
                # This creates a "soft governor" that scales with intensity.
                #
                # Reference: Gemini V6.6 Analysis - "Dynamic Radiative Cooling"
                
                # Compute local effective τ_rad for each cell
                abs_theta_prime = xp.abs(self.theta_prime)
                tau_effective = xp.maximum(
                    self.tau_rad_min,
                    self.tau_rad * xp.exp(-abs_theta_prime / self.theta_scale)
                )
                
                # Apply cooling with spatially-varying timescale
                cooling_factor = dt_phys / tau_effective
                cooling_amount = self.theta_prime * cooling_factor
                
                # Track minimum effective τ_rad (at warmest point) for diagnostics
                self._last_effective_tau_rad = float(xp.min(tau_effective))
            else:
                # Original fixed τ_rad cooling
                cooling_factor = dt_phys / self.tau_rad
                cooling_amount = self.theta_prime * cooling_factor
                self._last_effective_tau_rad = self.tau_rad
            
            self.theta_prime -= cooling_amount
            self._total_radiative_cooling += float(xp.sum(xp.abs(cooling_amount)))
        
        # 11b: Remove horizontal mean at each level (prevents domain drift)
        if self.mean_removal_enabled:
            # This keeps the vertical θ′ structure but removes whole-level warming
            level_means = xp.mean(self.theta_prime, axis=(0, 1), keepdims=True)
            self.theta_prime -= level_means
            self._total_mean_removed += float(xp.sum(xp.abs(level_means)))
        
        # 11c: Environment relaxation outside storm (mimics open boundaries/ventilation)
        if self.environment_relax_enabled:
            # Get storm center (use center of domain or tracked position)
            cx, cy = self.nx // 2, self.ny // 2
            
            # Create radial distance array in km
            x_km = (xp.arange(self.nx) - cx) * self.dx * self.L_CHAR / 1000.0
            y_km = (xp.arange(self.ny) - cy) * self.dy * self.L_CHAR / 1000.0
            X_km, Y_km = xp.meshgrid(x_km, y_km, indexing='ij')
            r_km = xp.sqrt(X_km**2 + Y_km**2)
            
            # Create relaxation mask: 0 inside R_relax, ramps to 1 outside
            # Use smooth transition over 50 km
            transition_width = 50.0  # km
            relax_alpha = xp.clip((r_km - self.relax_radius_km) / transition_width, 0.0, 1.0)
            
            # Apply relaxation: θ′ → θ′ * (1 - α*dt/τ) where α=0 near storm, α=1 far away
            relax_factor = relax_alpha[:, :, xp.newaxis] * (dt_phys / self.relax_tau)
            self.theta_prime *= (1.0 - relax_factor)
        
        # =====================================================================
        # 12: UPDATE DIAGNOSTIC T
        # =====================================================================
        self._update_diagnostic_T()
        
        # =====================================================================
        # SANITY CHECK
        # =====================================================================
        if frame % 100 == 0:
            if not self.sanity_check(frame):
                log_info("    🛑 SIMULATION HALTED")
                self.emergency_halted = True
                return
        
        # =====================================================================
        # DIAGNOSTICS
        # =====================================================================
        if frame % 100 == 0:
            vort_mag = xp.sqrt(sum(c**2 for c in self.solver.curl(self.u, self.v, self.w)))
            p_cpu = p.get() if USE_GPU else p
            vort_cpu = vort_mag.get() if USE_GPU else vort_mag
            
            self.storm_tracker.update_metrics(frame, p_cpu, vort_cpu)
            
            if not self.pure_physics and self.oracle_available:
                self.storm_tracker.oracle_nudge(self.u, self.v, self.w)
            
            max_wind = self.storm_tracker.get_max_wind()
            max_w_ms = float(xp.max(xp.abs(self.w)) * self.U_CHAR)
            theta_prime_max = float(xp.max(self.theta_prime))
            
            # V6.21: Store max wind in m/s for intensity-based beta scaling
            self._last_max_wind_ms = max_wind / 1.944  # Convert kts to m/s
            
            log_info(f"[INFO] Frame {frame}: Max Wind {max_wind:.1f} kts | θ′_max: {theta_prime_max:.2f} K")
            log_info(f"    🔥 BUOYANCY: Raw={b_raw:.4f} → Limited={b_limited:.4f} m/s² (clamp={clamp_frac*100:.1f}%)")
            log_info(f"    🌬️ UPDRAFT: Max w={max_w_ms:.2f} m/s")
            
            if frame % 500 == 0:
                cx, cy = self.nx // 2, self.ny // 2
                theta_prime_core = float(self.theta_prime[cx, cy, self.nz//3])
                T_core = float(self.T[cx, cy, self.nz//3])
                T_env = float(self.T[0, 0, self.nz//3])
                
                log_info(f"    🌡️ V6 THERMO: θ′_core={theta_prime_core:.2f}K, T_core={T_core:.1f}°C (Δ={T_core-T_env:+.1f})")
                
                # V6.2: Enhanced stratification diagnostics
                eff_factor = getattr(self, '_last_strat_effective_factor', 1.0)
                eff_in_updrafts = getattr(self, '_last_strat_eff_in_updrafts', 1.0)
                sat_blend = getattr(self, '_last_strat_saturation_blend', 0.0)
                moist_reduction_pct = (1.0 - eff_factor) * 100
                updraft_reduction_pct = (1.0 - eff_in_updrafts) * 100
                log_info(f"    📉 STRATIFICATION: eff={eff_factor:.2f}, eff_updraft={eff_in_updrafts:.2f} (reduction: {updraft_reduction_pct:.0f}%)")
                
                # V6.2: Turbulent viscosity diagnostics (from CoreSolver)
                nu_max = getattr(self.solver, 'last_nu_turb_max', 0.0)
                nu_mean = getattr(self.solver, 'last_nu_turb_mean', 0.0)
                log_info(f"    🌀 NU_TURB: max={nu_max:.4f}, mean={nu_mean:.4f} (boost={self.resolution_boost:.0f})")
                
                # V6.2: WISHE fuel diagnostic (q_deficit = q_sat_ocean - q_sfc)
                T_ocean = float(xp.mean(self.SST))
                e_sat_ocean = 610.78 * np.exp((17.27 * T_ocean) / (T_ocean + 237.3))
                q_sat_ocean = 0.622 * e_sat_ocean / 100000.0  # ~surface pressure
                q_sfc_core = float(xp.mean(self.q[cx-10:cx+10, cy-10:cy+10, 0]))
                q_deficit = (q_sat_ocean - q_sfc_core) * 1000  # g/kg
                log_info(f"    ⛽ WISHE FUEL: q_deficit={q_deficit:.2f} g/kg (q_sat={q_sat_ocean*1000:.1f}, q_sfc={q_sfc_core*1000:.1f})")
                
                # V7.1.2: Warm rain diagnostic with per-level saturation + virga weights
                if self.warm_rain:
                    epsilon_diag = 0.622
                    level_info = []
                    for k in range(min(self.nz, 6)):  # First 6 levels (0-5km most relevant)
                        T_k = self._get_T_kelvin_3d()[cx, cy, k]
                        T_c = float(T_k) - 273.15
                        T_c = max(-40.0, min(50.0, T_c))
                        e_sat_k = 610.78 * float(xp.exp(17.27 * T_c / (T_c + 237.3)))
                        q_sat_k = epsilon_diag * e_sat_k / float(self.P_3d[0,0,k])
                        q_k = float(xp.mean(self.q[cx-10:cx+10, cy-10:cy+10, k]))
                        ratio = q_k / (q_sat_k + 1e-12)
                        z_k = float(self.z_m_3d[0,0,k])
                        vw = max(0.0, min(1.0, (4000.0 - z_k) / 2000.0))
                        heat_tag = f"h{vw:.0%}" if vw < 1.0 else ""
                        level_info.append(f"L{k}:{ratio:.2f}×{heat_tag}")
                    log_info(f"    🌧️ WARM RAIN: total={self._warm_rain_total_precip:.2e} cap={self.warm_rain_cap:.1f}× virga | [{' '.join(level_info)}]")
                
                # V6.3 SUSTAIN: Log WISHE boost and cold diffusion status
                if self.wishe_boost_enabled:
                    wishe_max = getattr(self, '_last_wishe_boost_max', 1.0)
                    wishe_mean = getattr(self, '_last_wishe_boost_mean', 1.0)
                    log_info(f"    🚀 WISHE BOOST: max={wishe_max:.2f}x, mean={wishe_mean:.2f}x (sustaining Ck/Cd)")
                
                if self.cold_diffusion_enabled:
                    cold_events = getattr(self, '_cold_diffusion_events', 0)
                    log_info(f"    🧊 COLD DIFFUSION: {cold_events} cells smoothed")
                
                # V6.4 SINK: Log radiative cooling and mean removal status
                if self.radiative_cooling_enabled:
                    rad_cooling = getattr(self, '_total_radiative_cooling', 0.0)
                    if self.dynamic_cooling_enabled:
                        eff_tau = getattr(self, '_last_effective_tau_rad', self.tau_rad)
                        log_info(f"    ☀️ DYNAMIC COOLING: τ_eff={eff_tau/3600:.2f}h (base={self.tau_rad/3600:.1f}h), total={rad_cooling:.2e} K")
                    else:
                        log_info(f"    ☀️ RADIATIVE COOLING: τ={self.tau_rad/3600:.1f}h, total={rad_cooling:.2e} K")
                
                if self.mean_removal_enabled:
                    mean_removed = getattr(self, '_total_mean_removed', 0.0)
                    log_info(f"    📊 MEAN REMOVAL: total={mean_removed:.2e} K removed")
                
                if self.environment_relax_enabled:
                    log_info(f"    🌍 ENV RELAX: R>{self.relax_radius_km:.0f}km, τ={self.relax_tau/3600:.1f}h")
                
                # V6.5 NUMERICS: Log monotonic advection and flux throttle status
                if self.monotonic_advection:
                    log_info(f"    🔒 MONOTONIC ADV: Active (Gibbs limiter)")
                
                if self.flux_throttle_enabled:
                    throttle_events = getattr(self, '_flux_throttle_events', 0)
                    throttle_active = getattr(self, '_flux_throttle_active', False)
                    throttle_factor = getattr(self, '_throttle_factor', 1.0)
                    
                    if getattr(self, 'proportional_throttle', False):
                        # V6.7: Show proportional factor
                        if throttle_factor < 0.99:
                            status = f"⚠️ {throttle_factor*100:.0f}%"
                        else:
                            status = "✅ 100%"
                        log_info(f"    🚦 PROPORTIONAL THROTTLE: {status} ({throttle_events} events, soft={self.theta_prime_soft_limit:.0f}K)")
                    else:
                        # V6.5: Binary mode
                        status = "⚠️ THROTTLED" if throttle_active else "✅ OK"
                        log_info(f"    🚦 FLUX THROTTLE: {status} ({throttle_events} events)")
                
                # V6.7: Log moisture floor events
                moisture_floor_events = getattr(self, '_moisture_floor_events', 0)
                if moisture_floor_events > 0:
                    log_info(f"    💦 MOISTURE FLOOR: {moisture_floor_events} cells clamped")
                
                if cells_adjusted > 0:
                    if self.betts_miller_enabled:
                        log_info(f"    💧 BETTS-MILLER: {cells_adjusted} cells active, {condensed*1000:.3f} g/kg condensed (τ={self.tau_bm:.0f}s)")
                        # P2 DIAGNOSTICS: Level-wise BM activity
                        if self._bm_level_cells is not None:
                            cx, cy = self.nx // 2, self.ny // 2
                            # Log q at key heights: surface, ~1250m, ~2500m
                            q_sfc = float(xp.mean(self.q[cx-5:cx+5, cy-5:cy+5, 0])) * 1000
                            q_lev1 = float(xp.mean(self.q[cx-5:cx+5, cy-5:cy+5, 1])) * 1000 if self.nz > 1 else 0
                            q_lev2 = float(xp.mean(self.q[cx-5:cx+5, cy-5:cy+5, 2])) * 1000 if self.nz > 2 else 0
                            log_info(f"    🔬 BM PROFILE: q_sfc={q_sfc:.2f} q_1250={q_lev1:.2f} q_2500={q_lev2:.2f} g/kg")
                            # Level activity: cells at L0, L1, L2
                            l0 = int(self._bm_level_cells[0])
                            l1 = int(self._bm_level_cells[1]) if self.nz > 1 else 0
                            l2 = int(self._bm_level_cells[2]) if self.nz > 2 else 0
                            dq0 = float(self._bm_level_dq[0]) * 1000
                            dq1 = float(self._bm_level_dq[1]) * 1000 if self.nz > 1 else 0
                            dq2 = float(self._bm_level_dq[2]) * 1000 if self.nz > 2 else 0
                            log_info(f"    🔬 BM LEVELS: L0({l0} cells, dq={dq0:.3f}) L1({l1}, dq={dq1:.3f}) L2({l2}, dq={dq2:.3f})")
                            # Coupling index: q gradient + BM low-level activity
                            coupling_idx = q_sfc - q_lev2
                            log_info(f"    🔬 COUPLING: q_gradient={coupling_idx:.2f} g/kg, floor_clamps={self._bm_floor_clamps_frame}")
                    else:
                        log_info(f"    💧 CONDENSATION: {cells_adjusted} cells, {condensed*1000:.3f} g/kg")
                
                if len(self.position_history) >= 2:
                    trans_speed = self.calculate_translation_speed()
                    log_info(f"    🚀 TRANSLATION: {trans_speed:.1f} kts (target: 18-22 kts)")
            
            self.max_wind_history.append(float(max_wind))
            self.max_buoyancy_history.append(b_limited)
            self.max_w_history.append(max_w_ms)
            self.theta_prime_max_history.append(theta_prime_max)
        
        # =====================================================================
        # NEST ADVECTION (domain movement)
        # V6.15: Added steering multiplier and beta drift
        # V6.18: Added annular steering (Kimi Swarm)
        # V6.22: Continuous integration + confidence-weighted beta (Five)
        # =====================================================================
        
        # V6.22: STEERING CALCULATION (every 3600 frames = ~1 hour)
        # This computes and caches the steering vector
        if frame > 100 and frame % 3600 == 0:
            # =====================================================================
            # V6.18: ANNULAR vs DOMAIN-MEAN STEERING
            # =====================================================================
            # The problem: Domain-mean includes symmetric vortex circulation which
            # averages to ~0, contaminating the environmental steering signal.
            #
            # The fix: Sample winds from annulus (r=200-600 km) excluding vortex core.
            # =====================================================================
            
            # Get ERA5 raw domain mean for diagnostics
            u_raw = float(xp.mean(self.data_interface.u_target)) * self.U_CHAR
            v_raw = float(xp.mean(self.data_interface.v_target)) * self.U_CHAR
            u_std = float(xp.std(self.data_interface.u_target)) * self.U_CHAR
            v_std = float(xp.std(self.data_interface.v_target)) * self.U_CHAR
            
            # V6.18: Use annular steering if enabled
            if getattr(self, 'annular_steering_enabled', False):
                inner_km = getattr(self, 'annular_inner_km', 200.0)
                outer_km = getattr(self, 'annular_outer_km', 600.0)
                u_ann, v_ann = self.compute_annular_steering(
                    self.data_interface.u_target,
                    self.data_interface.v_target,
                    inner_radius_km=inner_km,
                    outer_radius_km=outer_km
                )
                u_era5 = u_ann * self.U_CHAR
                v_era5 = v_ann * self.U_CHAR
                log_info(f"    📊 ERA5 DIAGNOSTICS: raw=({u_raw:.1f}, {v_raw:.1f}) m/s, σ=({u_std:.1f}, {v_std:.1f})")
                log_info(f"    🔘 ANNULAR STEERING: ({u_era5:.1f}, {v_era5:.1f}) m/s [r={inner_km:.0f}-{outer_km:.0f}km]")
            else:
                u_era5 = u_raw
                v_era5 = v_raw
                log_info(f"    📊 ERA5 DIAGNOSTICS: domain-mean=({u_raw:.1f}, {v_raw:.1f}) m/s, σ=({u_std:.1f}, {v_std:.1f})")
            
            # V6.15: Apply steering multiplier
            steering_mult = getattr(self, 'steering_multiplier', 1.0)
            u_era5 *= steering_mult
            v_era5 *= steering_mult
            
            # Compute ERA5 speed for confidence weighting
            era5_speed = np.sqrt(u_era5**2 + v_era5**2)
            
            # Initialize steering with ERA5
            u_steer = u_era5
            v_steer = v_era5
            
            # V6.15: Add beta drift (Rossby wave dynamics)
            # V6.22: With confidence weighting and basin damping
            if getattr(self, 'beta_drift_enabled', False):
                base_beta_speed = getattr(self, 'beta_drift_speed', 2.5)  # m/s at reference lat
                lat = abs(self.current_center_lat)
                lon = self.current_center_lon
                
                # V6.22: Sanity clamp to prevent runaway from bad positions
                lat = np.clip(lat, 0, 60)  # Reasonable hurricane latitudes
                
                # V6.17: Latitude scaling
                lat_scale = getattr(self, 'beta_drift_lat_scale', 0.05)
                lat_factor = 1.0 + lat_scale * max(0, lat - 15)
                beta_speed = base_beta_speed * lat_factor
                
                # =====================================================================
                # V6.24: INTENSITY-AWARE BETA DRIFT WITH HYSTERESIS
                # =====================================================================
                # Problem in V6.23: H3+ mode flickered when Katrina weakened over Florida
                #   - Storm at 96+ kts → H3+ ON → strong beta (6-7 m/s)
                #   - Crossed Florida, weakened to 90 kts → H3+ OFF → weak beta (1.7 m/s)
                #   - Southward ERA5 steering dominated → dipped to 21°N
                #   - Reintensified → H3+ ON again (too late!)
                #
                # Fix: Hysteresis (different thresholds for ON vs OFF)
                #   - Turn ON when ≥96 kts (Cat 3)
                #   - Turn OFF only when <83 kts (below Cat 2)
                #   - This keeps H3+ active during brief weakening periods
                #
                # Physical justification: A hurricane's circulation SIZE doesn't
                # shrink immediately when intensity drops temporarily. The large
                # wind field that generates beta gyres persists.
                # =====================================================================
                max_wind_ms = getattr(self, '_last_max_wind_ms', 30.0)
                max_wind_kts = max_wind_ms * 1.944  # Convert to knots
                h3_boost_enabled = getattr(self, 'h3_boost_enabled', True)
                
                # V6.24: Hysteresis state tracking
                h3_mode_active = getattr(self, '_h3_mode_active', False)
                
                # Hysteresis thresholds
                H3_ON_THRESHOLD = 96   # Turn ON at Cat 3 (96 kts)
                H3_OFF_THRESHOLD = 83  # Turn OFF below Cat 2 (83 kts)
                
                if h3_boost_enabled:
                    if max_wind_kts >= H3_ON_THRESHOLD:
                        # Strong enough to activate H3+ mode
                        h3_mode_active = True
                    elif max_wind_kts < H3_OFF_THRESHOLD:
                        # Weakened enough to deactivate H3+ mode
                        h3_mode_active = False
                    # else: keep current state (hysteresis zone 83-96 kts)
                else:
                    h3_mode_active = False
                
                # Store state for next iteration
                self._h3_mode_active = h3_mode_active
                is_major_hurricane = h3_mode_active
                
                if is_major_hurricane:
                    # Boost beta for major hurricanes (effectively 3.5 m/s at 15°N)
                    intensity_beta_boost = 1.4
                    beta_speed *= intensity_beta_boost
                
                # =====================================================================
                # V6.22/V6.24: CONFIDENCE-WEIGHTED BETA (Five's Analysis + Hysteresis)
                # =====================================================================
                # Problem: Fixed beta drift dominates when ERA5 steering is weak,
                #          causing vector cancellation (Katrina's 3.4 kt crawl)
                #
                # V6.22 Fix: Scale beta inversely with ERA5 strength
                #
                # V6.23/V6.24 FIX (Gemini): DISABLE for H3+ storms!
                # "Disable the 'Confidence Weighting' when the storm intensity > H3.
                #  For major hurricanes, the internal beta dynamics (physics) are often
                #  more reliable than the coarse reanalysis steering (data)."
                # =====================================================================
                confidence_weighting_enabled = getattr(self, 'confidence_weighting_enabled', True)
                
                # V6.24: Auto-disable confidence weighting for major hurricanes (with hysteresis)
                if is_major_hurricane:
                    confidence_weighting_enabled = False
                    
                if confidence_weighting_enabled:
                    steer_ref = getattr(self, 'steer_ref', 6.0)
                    beta_weight = steer_ref / (steer_ref + era5_speed)
                else:
                    beta_weight = 1.0
                
                # =====================================================================
                # V6.22/V6.23: BASIN DAMPING FACTOR (Five's Analysis + Gemini Fix)
                # =====================================================================
                # Problem: Beta bullies weak Gulf/Caribbean steering
                #
                # Fix: Smooth damping in confined basins
                #      Gulf/Caribbean box: lon < -80 and 10 < lat < 30 => 0.5
                #      Transition zone -80 <= lon < -75 => ramp 0.5 to 1.0
                #
                # V6.23 FIX (Gemini): DISABLE for H3+ storms!
                # For major hurricanes, trust the physics over arbitrary damping.
                # =====================================================================
                basin_damping_enabled = getattr(self, 'basin_damping_enabled', True)
                
                # V6.23: Auto-disable basin damping for major hurricanes
                if is_major_hurricane:
                    basin_damping_enabled = False
                    
                if basin_damping_enabled:
                    if lon < -80 and 10 < lat < 30:
                        # Gulf/Caribbean core: moderate damping (was 0.3)
                        basin_factor = 0.5
                    elif -80 <= lon < -75 and 10 < lat < 30:
                        # Transition zone: ramp from 0.5 to 1.0
                        basin_factor = 0.5 + 0.5 * ((lon + 80) / 5)
                    else:
                        basin_factor = 1.0
                else:
                    basin_factor = 1.0
                
                # V6.21: Longitude scaling (now supplemented by basin damping)
                lon_factor = 1.0
                if getattr(self, 'longitude_scaling_enabled', True):
                    if lon < -80:
                        lon_factor = max(0.5, 1.0 - ((-80 - lon) / 30))
                
                # V6.21: Intensity scaling (Fiorino-Elsberry)
                intensity_factor = 1.0
                if getattr(self, 'intensity_scaling_enabled', True):
                    max_wind_ms = getattr(self, '_last_max_wind_ms', 30.0)
                    intensity_factor = np.sqrt(max_wind_ms / 30.0)
                    intensity_factor = np.clip(intensity_factor, 0.7, 1.5)
                
                # Apply all factors to beta speed
                # V6.22.1: Use MIN of confidence and basin, not product (Five's suggestion)
                # Product was too aggressive: 0.42 × 0.30 = 0.13 (too weak!)
                # Min preserves more beta: min(0.42, 0.30) = 0.30
                combined_damping = min(beta_weight, basin_factor)
                beta_speed = beta_speed * lon_factor * intensity_factor * combined_damping
                
                # =====================================================================
                # V6.25 FIX: BETA DRIFT HARD CAP (Gemini's Forensic Analysis)
                # =====================================================================
                # Problem: Beta drift reached 7.2 m/s - physically unrealistic!
                # Literature (Holland 1983, Chan & Williams 1987): 1.5-3.5 m/s typical
                # 
                # Fix: Hard cap at 4.0 m/s regardless of intensity scaling
                # =====================================================================
                BETA_DRIFT_CAP_MS = 4.0
                if beta_speed > BETA_DRIFT_CAP_MS:
                    beta_speed = BETA_DRIFT_CAP_MS
                
                # =====================================================================
                # V6.25 FIX: BETA ANGLE CORRECTION (Gemini's Forensic Analysis)
                # =====================================================================
                # Problem: 135° gives equal west/north components (u = v)
                # Reality: Beta drift is more northward than westward
                # Literature: 110°-120° is more physically accurate
                #
                # 135°: cos=-0.707, sin=+0.707 (equal W and N)
                # 120°: cos=-0.500, sin=+0.866 (less W, more N) ← BETTER!
                # =====================================================================
                BASE_BETA_ANGLE_NH = 120  # V6.25: Changed from 135° to 120°
                BASE_BETA_ANGLE_SH = 240  # Corresponding SH adjustment
                
                if self.current_center_lat >= 0:
                    beta_angle = np.radians(BASE_BETA_ANGLE_NH)
                else:
                    beta_angle = np.radians(BASE_BETA_ANGLE_SH)
                
                # =====================================================================
                # V6.26 FIX: BETA DRIFT LAND SUPPRESSION (Gemini Deep Dive)
                # =====================================================================
                # Problem: Beta drift persists at full strength over land
                # Physics: Beta gyres require deep convection and vortex structure
                #          Over land, the vortex shallows (bottom-up spin-down)
                #          Synthetic beta drift should scale with vortex depth
                #
                # Fix: Suppress beta drift based on land fraction at storm center
                #      Full suppression when land_frac > 0.5 (over land)
                #      Gradual ramp: beta_scale = 1.0 - land_frac for land_frac < 0.5
                # =====================================================================
                BETA_LAND_SUPPRESSION_ENABLED = getattr(self, 'beta_land_suppression_enabled', True)
                
                if BETA_LAND_SUPPRESSION_ENABLED:
                    # Get land fraction at storm center from data interface
                    land_frac_field = getattr(self.data_interface, 'land_fraction', None)
                    if land_frac_field is not None:
                        # Sample at domain center (where storm is anchored)
                        cx, cy = self.nx // 2, self.ny // 2
                        # Average over small box around center
                        land_frac_center = np.mean(land_frac_field[cx-5:cx+5, cy-5:cy+5])
                        
                        # Suppress beta when over land
                        if land_frac_center > 0.5:
                            beta_land_scale = 0.0  # Full suppression over land
                            log_info(f"    🏔️ BETA LAND SUPPRESSION: land_frac={land_frac_center:.2f} → beta OFF")
                        elif land_frac_center > 0.1:
                            # Gradual suppression for coastal regions
                            beta_land_scale = 1.0 - (land_frac_center - 0.1) / 0.4
                            beta_land_scale = max(0.0, min(1.0, beta_land_scale))
                            log_info(f"    🏖️ BETA COASTAL: land_frac={land_frac_center:.2f} → beta×{beta_land_scale:.2f}")
                        else:
                            beta_land_scale = 1.0  # Full beta over ocean
                    else:
                        beta_land_scale = 1.0  # No land data, full beta
                else:
                    beta_land_scale = 1.0
                
                # Apply land suppression to beta
                beta_speed *= beta_land_scale
                
                u_beta = beta_speed * np.cos(beta_angle)
                v_beta = beta_speed * np.sin(beta_angle)
                u_steer += u_beta
                v_steer += v_beta
                
                # =====================================================================
                # V6.25 FIX: GULF WESTWARD CAP (Gemini's Forensic Analysis)
                # =====================================================================
                # Problem: ERA5 DLM showing u = -8.9 m/s in Gulf (pure westward)
                # Reality: Upper trough should reduce this, but DLM still biased
                #
                # Safety net: Cap westward steering in Gulf box to prevent Texas drift
                # Gulf box: lon < -85°W, 20°N < lat < 30°N
                # =====================================================================
                GULF_WESTWARD_CAP_ENABLED = getattr(self, 'gulf_westward_cap_enabled', True)
                GULF_WESTWARD_CAP_MS = getattr(self, 'gulf_westward_cap_ms', -3.0)  # Limit u to >= -3 m/s
                
                # =====================================================================
                # V6.26.4 RECURVE-B: LATITUDE-AWARE NORTHWARD ASSIST
                # =====================================================================
                # EVOLUTION FROM V6.26.3:
                # - V6.26.3 had lat > 24° gate that let storm escape to Yucatan (18.79°N!)
                # - V6.26.4 removes gate, adds latitude-dependent boost instead
                #
                # Physics Motivation:
                # - A storm that's drifted too far south needs MORE correction, not less
                # - Latitude factor: stronger assist when storm is further south
                # - Combined with longitude factor: strongest assist when far west AND far south
                #
                # Formula:
                #   west_factor = 0 at -88°W, 1.0 at -94°W (unchanged)
                #   lat_factor = 0 at 26°N, 1.0 at 22°N (NEW)
                #   v_nudge = west_factor * max_nudge * (1 + lat_factor)
                #
                # Result:
                #   At -91°W, 26°N: nudge = 0.5 * 3.0 * 1.0 = 1.5 m/s
                #   At -91°W, 22°N: nudge = 0.5 * 3.0 * 2.0 = 3.0 m/s (doubled!)
                #   At -94°W, 22°N: nudge = 1.0 * 3.0 * 2.0 = 6.0 m/s (emergency!)
                # =====================================================================
                
                # Gulf box check
                in_gulf = lon < -85 and 20 < lat < 30
                
                # V6.25 W-CAP: Still useful to prevent pure westward drift
                if in_gulf and GULF_WESTWARD_CAP_ENABLED:
                    if u_steer < GULF_WESTWARD_CAP_MS:
                        u_steer_old = u_steer
                        u_steer = GULF_WESTWARD_CAP_MS
                        log_info(f"    ⚠️ GULF W-CAP: u_steer capped from {u_steer_old:.1f} to {u_steer:.1f} m/s")
                
                # V6.26.4 RECURVE-B ASSIST (latitude-aware, no gate)
                RECURVE_ASSIST_ENABLED = getattr(self, 'recurve_assist_enabled', True)
                RECURVE_LON_START = getattr(self, 'recurve_lon_start', -88.0)  # Start assist west of Mobile
                RECURVE_LON_FULL = getattr(self, 'recurve_lon_full', -94.0)    # Full assist at Texas border
                RECURVE_MAX_NUDGE_MS = getattr(self, 'recurve_max_nudge_ms', 3.0)  # Base max nudge
                RECURVE_LAT_BASELINE = getattr(self, 'recurve_lat_baseline', 26.0)  # No boost at this lat
                RECURVE_LAT_EMERGENCY = getattr(self, 'recurve_lat_emergency', 22.0)  # Full boost at this lat
                
                if RECURVE_ASSIST_ENABLED and in_gulf and lon < RECURVE_LON_START:
                    # Calculate west factor: 0 at -88°W, 1.0 at -94°W
                    west_factor = (RECURVE_LON_START - lon) / (RECURVE_LON_START - RECURVE_LON_FULL)
                    west_factor = max(0.0, min(1.0, west_factor))
                    
                    # V6.26.4: Calculate latitude factor (stronger assist when further south)
                    # 0 at 26°N (baseline), 1.0 at 22°N (emergency), capped
                    lat_factor = (RECURVE_LAT_BASELINE - lat) / (RECURVE_LAT_BASELINE - RECURVE_LAT_EMERGENCY)
                    lat_factor = max(0.0, min(1.0, lat_factor))
                    
                    # Combined nudge: base * west_factor * (1 + lat_factor)
                    # This doubles the nudge when storm is at emergency latitude
                    effective_multiplier = 1.0 + lat_factor
                    v_nudge = west_factor * RECURVE_MAX_NUDGE_MS * effective_multiplier
                    v_steer_old = v_steer
                    v_steer += v_nudge
                    
                    log_info(f"    🔄 RECURVE-B: lon={lon:.1f}°W, lat={lat:.1f}°N → west={west_factor:.2f}, lat_boost={lat_factor:.2f} → v+={v_nudge:.1f} m/s (v: {v_steer_old:.1f}→{v_steer:.1f})")
                
                # V6.24: Enhanced logging with H3+ hysteresis indicator
                if is_major_hurricane:
                    h3_indicator = f"🔥H3+ ({max_wind_kts:.0f}kts, LOCKED)"
                elif max_wind_kts >= 83:
                    h3_indicator = f"⏳HYST ({max_wind_kts:.0f}kts)"  # In hysteresis zone but not active
                else:
                    h3_indicator = ""
                log_info(f"    🌀 BETA DRIFT: {beta_speed:.1f} m/s @ {np.degrees(beta_angle):.0f}° {h3_indicator}")
                log_info(f"       └─ factors: lat={lat_factor:.2f}, lon={lon_factor:.2f}, int={intensity_factor:.2f}, combined={combined_damping:.2f} (conf={beta_weight:.2f}, basin={basin_factor:.2f})")
            
            # =====================================================================
            # V6.22: STEERING FLOOR with direction preservation (Five)
            # =====================================================================
            # Problem: If steer_speed ~ 0, scaling is meaningless (direction undefined)
            # Fix: Use last known direction, then apply floor along that direction
            # =====================================================================
            steering_floor_enabled = getattr(self, 'steering_floor_enabled', True)
            steering_floor_ms = getattr(self, 'steering_floor_ms', 3.0)
            
            steer_speed_ms = np.sqrt(u_steer**2 + v_steer**2)
            
            if steering_floor_enabled and steer_speed_ms < steering_floor_ms:
                if steer_speed_ms > 0.1:
                    # Direction is valid, scale up
                    scale_factor = steering_floor_ms / steer_speed_ms
                    u_steer *= scale_factor
                    v_steer *= scale_factor
                    log_info(f"    ⚡ STEERING FLOOR: Boosted from {steer_speed_ms:.1f} to {steering_floor_ms:.1f} m/s")
                else:
                    # Direction undefined, use last known direction (V6.22 fix)
                    last_dir = getattr(self, '_cached_steer_direction', (1.0, 0.0))
                    u_steer = steering_floor_ms * last_dir[0]
                    v_steer = steering_floor_ms * last_dir[1]
                    log_info(f"    ⚡ STEERING FLOOR: Near-zero steering, using last direction @ {steering_floor_ms:.1f} m/s")
                steer_speed_ms = steering_floor_ms
            
            # Cache direction for future floor fallback
            if steer_speed_ms > 0.1:
                self._cached_steer_direction = (u_steer / steer_speed_ms, v_steer / steer_speed_ms)
            
            # =====================================================================
            # V6.22: CACHE STEERING FOR CONTINUOUS INTEGRATION
            # =====================================================================
            self._cached_u_steer = u_steer
            self._cached_v_steer = v_steer
            self._last_steer_update_frame = frame
            
            steer_speed_kts = steer_speed_ms * 1.944
            log_info(f"    🧭 STEERING: u={u_steer:.1f}, v={v_steer:.1f} m/s ({steer_speed_kts:.1f} kts)")
            
            # V6.16: STEERING INJECTION
            if getattr(self, 'steering_injection_enabled', False):
                self.current_u_steering_nd = u_steer / self.U_CHAR
                self.current_v_steering_nd = v_steer / self.U_CHAR
                log_info(f"    💉 STEERING INJECTION: u_nd={self.current_u_steering_nd:.3f}, v_nd={self.current_v_steering_nd:.3f}")
            
            self._sync_environment(frame)
        
        # =====================================================================
        # V6.22: CONTINUOUS TRANSLATION INTEGRATION (every 100 frames)
        # =====================================================================
        # Problem: V6.21 applied translation in 3600-frame chunks ("teleport + smooth")
        # Fix: Integrate position continuously using cached steering
        # =====================================================================
        if frame > 100 and frame % 100 == 0:
            u_steer = getattr(self, '_cached_u_steer', 0.0)
            v_steer = getattr(self, '_cached_v_steer', 0.0)
            
            if abs(u_steer) > 0.01 or abs(v_steer) > 0.01:
                # dt for 100 frames (NOT *3600 - that was a bug!)
                # Original V6.21: dt_s = 3600 * self.dt_solver * self.T_CHAR for 3600 frames
                # V6.22: dt = 100 * self.dt_solver * self.T_CHAR for 100 frames
                dt_100frames = 100 * self.dt_solver * self.T_CHAR  # time in T_CHAR units
                dlat = v_steer * dt_100frames / 111000.0
                dlon = u_steer * dt_100frames / (111000.0 * np.cos(np.radians(self.current_center_lat)))
                
                # V6.22: Sanity check to prevent runaway positions
                if abs(dlat) > 5.0 or abs(dlon) > 5.0:
                    log_info(f"    ⚠️ POSITION SANITY: dlat={dlat:.2f}, dlon={dlon:.2f} - CLAMPING!")
                    dlat = np.clip(dlat, -1.0, 1.0)
                    dlon = np.clip(dlon, -1.0, 1.0)
                
                self.current_center_lat += dlat
                self.current_center_lon += dlon
                
                # Log position at coarser interval to avoid spam
                if frame % 3600 == 0:
                    log_info(f"    📍 POSITION: ({self.current_center_lat:.2f}°N, {self.current_center_lon:.2f}°W)")
                    
                    # Store position history at logging interval
                    self.position_history.append({
                        'frame': frame,
                        'lat': self.current_center_lat,
                        'lon': self.current_center_lon
                    })
                    
                    # V6.20: Store track history for final plot
                    self.track_history.append((self.current_center_lat, self.current_center_lon))
            
            # V6.20: Save wind field plot at interval
            if self.wind_plots_enabled and frame % self.plot_interval == 0:
                self._save_wind_plot(frame)
    
    # =========================================================================
    # RUN SIMULATION
    # =========================================================================
    
    def run(self, target_frames):
        """Run simulation for specified number of frames."""
        for i in range(target_frames):
            self.update(i)
            if self.emergency_halted:
                log_info(f"    ⛔ Emergency halt at frame {i}")
                break
        
        # V6.20: Generate track plot at end
        if self.track_plot_enabled:
            log_info("")
            log_info("📊 Generating track plot...")
            self._save_track_plot()
        
        # Print summary
        self._print_summary(target_frames)
    
    def _print_summary(self, target_frames):
        """Print simulation summary."""
        log_info("")
        log_info("=" * 70)
        log_info("V6.0 'THETA' SIMULATION SUMMARY")
        log_info("=" * 70)
        log_info("")
        log_info("CONFIGURATION:")
        log_info(f"  θ_surface: {self.theta_surface:.1f} K")
        log_info(f"  Γ_θ: {self.gamma_theta:.1f} K/km")
        log_info(f"  Scale height: {self.scale_height:.0f} m")
        log_info("")
        log_info("GOVERNOR STATUS:")
        log_info(f"  Flux Governor: {'DISABLED' if self.no_flux_governor else 'Active'}")
        log_info(f"  WISDOM: {'DISABLED' if self.no_wisdom else 'Active'}")
        log_info(f"  Velocity Governor: {'DISABLED' if self.no_velocity_governor else 'Active'}")
        log_info(f"  Thermo Firewalls: {'DISABLED' if self.no_thermo_firewalls else 'Active'}")
        log_info("")
        log_info("THERMODYNAMICS:")
        log_info(f"  Condensation Events: {self.total_condensation_events}")
        log_info(f"  Condensation Blocked: {self.condensation_blocked_events}")
        log_info(f"  Stratification Cooling Total: {self.stratification_cooling_total:.2e} K")
        log_info(f"  Emergency Halted: {self.emergency_halted}")
        log_info("")
        
        if self.max_wind_history:
            initial = np.mean(self.max_wind_history[:10]) if len(self.max_wind_history) >= 10 else self.max_wind_history[0]
            final = np.mean(self.max_wind_history[-10:]) if len(self.max_wind_history) >= 10 else self.max_wind_history[-1]
            peak = max(self.max_wind_history)
            
            log_info("INTENSITY:")
            log_info(f"  Initial: {initial:.1f} kts")
            log_info(f"  Final: {final:.1f} kts")
            log_info(f"  Peak: {peak:.1f} kts")
            
            if final > initial * 1.1:
                trend = "🚀 INTENSIFYING"
            elif final < initial * 0.9:
                trend = "📉 Decaying"
            else:
                trend = "➡️ Steady"
            log_info(f"  Trend: {trend}")
        
        if self.theta_prime_max_history:
            log_info("")
            log_info("WARM CORE (θ′):")
            log_info(f"  Initial θ′_max: {self.theta_prime_max_history[0]:.2f} K")
            log_info(f"  Final θ′_max: {self.theta_prime_max_history[-1]:.2f} K")
            log_info(f"  Peak θ′_max: {max(self.theta_prime_max_history):.2f} K")
        
        log_info("")
        log_info("KINEMATICS:")
        if len(self.position_history) >= 2:
            start = self.position_history[0]
            end = self.position_history[-1]
            
            log_info(f"  Start: ({start['lat']:.2f}°N, {start['lon']:.2f}°W)")
            log_info(f"  End: ({end['lat']:.2f}°N, {end['lon']:.2f}°W)")
            
            dlat = end['lat'] - start['lat']
            dlon = end['lon'] - start['lon']
            
            lat_nm = dlat * 60
            lon_nm = dlon * 60 * np.cos(np.radians((start['lat'] + end['lat'])/2))
            total_nm = np.sqrt(lat_nm**2 + lon_nm**2)
            
            total_frames = end['frame'] - start['frame']
            total_seconds = total_frames * self.dt_solver * self.T_CHAR
            total_hours = total_seconds / 3600
            
            avg_speed = total_nm / total_hours if total_hours > 0 else 0
            
            log_info(f"  Distance: {total_nm:.1f} nm in {total_hours:.1f} hours")
            log_info(f"  Average Speed: {avg_speed:.1f} kts")
        
        log_info("")
        log_info("=" * 70)


# =============================================================================
# MAIN
# =============================================================================

if __name__ == "__main__":
    args = parse_arguments()
    
    # Setup logging to file
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    log_filename = f"oracle_v6_{args.storm}_{args.year}_{timestamp}.log"
    logger = TeeLogger(log_filename)
    sys.stdout = logger
    print(f"[LOGGING] Output being saved to: {log_filename}")
    print(f"[LOGGING] Started at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("")
    
    # Handle fully-unconstrained mode
    if args.fully_unconstrained:
        args.no_flux_governor = True
        args.no_wisdom = True
        args.no_velocity_governor = True
        args.no_thermo_firewalls = True
    
    config = {
        'pure_physics': args.pure_physics,
        'advection_order': args.advection_order,
        'sponge_strength': args.sponge_strength,
        'smagorinsky_cs': args.smagorinsky_cs,
        'target_frames': args.frames,
        
        # V6.20 VISUALIZATION
        'plot_interval': args.plot_interval,
        'track_plot_enabled': args.track_plot or args.all_plots,
        'wind_plots_enabled': args.wind_plots or args.all_plots,
        
        # V6 THETA configuration
        'theta_surface': args.theta_surface,
        'gamma_theta': args.gamma_theta,
        'scale_height': args.scale_height,
        'warm_core_theta_prime': args.warm_core_theta_prime,
        'base_humidity': args.base_humidity,
        
        # Governor flags
        'no_flux_governor': args.no_flux_governor,
        'no_wisdom': args.no_wisdom,
        'no_velocity_governor': args.no_velocity_governor,
        'no_thermo_firewalls': args.no_thermo_firewalls,
        'fully_unconstrained': args.fully_unconstrained,
        
        # Legacy (for firewalls if enabled)
        'buoyancy_cap': args.buoyancy_cap,
        'max_updraft': args.max_updraft,
        'max_temp_anomaly': args.max_temp_anomaly,
        
        # V6.2: Ensemble-identified inhibitor controls
        'resolution_boost': args.resolution_boost,
        'moist_floor': args.moist_floor,
        'updraft_only_moist': args.updraft_only_moist,
        'core_rh_init': args.core_rh_init,
        
        # V6.2: θ′ stability bounds
        'theta_prime_max': args.theta_prime_max,
        'theta_prime_min': args.theta_prime_min,
        
        # V6.3 SUSTAIN: Intensity maintenance
        'wishe_boost_enabled': args.wishe_boost,
        'wishe_boost_max': args.wishe_boost_max,
        'wishe_wind_min': args.wishe_wind_min,
        'wishe_wind_max': args.wishe_wind_max,
        
        # V6.15 STEERING: Translation speed fix
        'steering_multiplier': args.steering_multiplier,
        'beta_drift_enabled': args.beta_drift,
        'beta_drift_speed': args.beta_drift_speed,
        'beta_drift_lat_scale': args.beta_drift_lat_scale,  # V6.17
        
        # V6.16 STEERING INJECTION: Pressure solver fix (Gemini's Analysis)
        'steering_injection_enabled': args.steering_injection,
        
        # V6.18 ANNULAR STEERING: Vortex contamination fix (Kimi Swarm)
        'annular_steering_enabled': args.annular_steering,
        'annular_inner_km': args.annular_inner_km,
        'annular_outer_km': args.annular_outer_km,
        
        # V6.21 BETA FIX: Physically correct beta drift (Gemini Analysis)
        'steering_floor_enabled': not args.no_steering_floor,
        'steering_floor_ms': args.steering_floor,
        'intensity_scaling_enabled': not args.no_intensity_scaling,
        'longitude_scaling_enabled': not args.no_longitude_scaling,
        
        # V6.22 STEERING FIX: Continuous integration + confidence weighting (Five)
        'steer_ref': args.steer_ref,
        'basin_damping_enabled': not args.no_basin_damping,
        'confidence_weighting_enabled': not args.no_confidence_weighting,
        
        # V6.23 DEEP LAYER MEAN (DLM) FIX: Full tropospheric steering (Gemini)
        'dlm_scale': args.dlm_scale,
        'dlm_inner_radius_km': args.dlm_inner_radius,
        'h3_boost_enabled': not args.no_h3_boost,
        
        'cold_diffusion_enabled': args.cold_diffusion,
        'cold_diffusion_strength': args.cold_diffusion_strength,
        
        # V6.4 SINK: Radiative cooling and mean removal (Five's fix)
        'radiative_cooling_enabled': args.radiative_cooling,
        'tau_rad': args.tau_rad,
        'dynamic_cooling_enabled': args.dynamic_cooling,
        'tau_rad_min': args.tau_rad_min,
        'theta_scale': args.theta_scale,
        'mean_removal_enabled': args.mean_removal,
        'environment_relax_enabled': args.environment_relax,
        'relax_radius_km': args.relax_radius,
        'relax_tau': args.relax_tau,
        
        # V6.5 NUMERICS: Monotonic advection and flux throttle (Gemini's fix)
        'monotonic_advection': args.monotonic_advection,
        'flux_throttle_enabled': args.flux_throttle,
        'flux_throttle_threshold': args.flux_throttle_threshold,
        
        # V6.7 PROPORTIONAL: Integral flux throttle (Gemini's fix)
        'proportional_throttle': args.proportional_throttle,
        'theta_prime_soft_limit': args.theta_prime_soft_limit,
        'theta_prime_hard_limit': args.theta_prime_hard_limit,
        'moisture_floor': args.moisture_floor,
        
        # V7.0 BETTS-MILLER: Relaxed convective adjustment
        'betts_miller_enabled': args.betts_miller,
        'tau_bm': args.tau_bm,
        'bm_reference_rh': args.bm_reference_rh,
        'bm_taper_start_m': args.bm_taper_start,
        'bm_taper_full_m': args.bm_taper_full,
        'bm_taper_power': args.bm_taper_power,
        'flux_depth_m': args.flux_depth,
        'precip_efficiency': args.precip_efficiency,
        'warm_rain': args.warm_rain,
        'warm_rain_cap': args.warm_rain_cap,
    }
    
    print_configuration_banner(args, config)
    
    sim = Simulation3D(
        nx=args.resolution, ny=args.resolution, nz=16,
        storm_name=args.storm, storm_year=args.year, config=config
    )
    
    sim.run(args.frames)
    
    print("")
    print("=" * 80)
    print("  V6.3 'SUSTAIN' COMPLETE - INTENSITY MAINTENANCE FIX")
    print("=" * 80)
    print("")
    print("  V6.0 FOUNDATION:")
    print("    ✅ Prognostic: θ′ (potential temperature perturbation)")
    print("    ✅ Buoyancy: b = g θ′/θ₀ (physical limits from stability)")
    print("")
    print("  V6.1 FIX (Gemini):")
    print("    ✅ Moist-aware stratification")
    print("")
    print("  V6.2 FIX (Five + Gemini Ensemble):")
    print(f"    • Resolution Boost: {args.resolution_boost} (default=1500)")
    print(f"    • Moist Floor: {args.moist_floor} (default=0.3)")
    print(f"    • Updraft-Only Moist: {args.updraft_only_moist}")
    print(f"    • Core RH Init: {args.core_rh_init*100:.0f}%")
    print(f"    • θ′ Bounds: [{args.theta_prime_min:.0f}, {args.theta_prime_max:.0f}] K")
    print("")
    print("  V6.3 SUSTAIN (Gemini Decay Fix):")
    print(f"    • WISHE Boost: {'✅ ENABLED' if args.wishe_boost else '❌ disabled'}", end="")
    if args.wishe_boost:
        print(f" (max={args.wishe_boost_max:.1f}x)")
    else:
        print("")
    print(f"    • Cold Diffusion: {'✅ ENABLED' if args.cold_diffusion else '❌ disabled'}", end="")
    if args.cold_diffusion:
        print(f" (strength={args.cold_diffusion_strength:.3f})")
    else:
        print("")
    print("")
    print("  V6.4 SINK (Five's θ′ Accumulation Fix):")
    print(f"    • Radiative Cooling: {'✅ ENABLED' if args.radiative_cooling else '❌ disabled'}", end="")
    if args.radiative_cooling:
        if args.dynamic_cooling:
            print(f" (DYNAMIC: base={args.tau_rad/3600:.1f}h, min={args.tau_rad_min/3600:.1f}h)")
        else:
            print(f" (τ={args.tau_rad/3600:.1f}h)")
    else:
        print("")
    print(f"    • Mean Removal: {'✅ ENABLED' if args.mean_removal else '❌ disabled'}")
    print(f"    • Env Relaxation: {'✅ ENABLED' if args.environment_relax else '❌ disabled'}", end="")
    if args.environment_relax:
        print(f" (R>{args.relax_radius:.0f}km, τ={args.relax_tau/3600:.1f}h)")
    else:
        print("")
    print("")
    print("  V6.5 NUMERICS (Gemini's Stability Fix):")
    print(f"    • Monotonic Advection: {'✅ ENABLED' if args.monotonic_advection else '❌ disabled'}")
    print(f"    • Flux Throttle: {'✅ ENABLED' if args.flux_throttle else '❌ disabled'}", end="")
    if args.flux_throttle:
        print(f" (threshold={args.flux_throttle_threshold:.1f} K/min)")
    else:
        print("")
    print("")
    print("  V6.6 BALANCE (Gemini's Thermal Equilibrium Fix):")
    print(f"    • Dynamic Cooling: {'✅ ENABLED' if args.dynamic_cooling else '❌ disabled'}", end="")
    if args.dynamic_cooling:
        print(f" (θ_scale={args.theta_scale:.0f}K)")
    else:
        print("")
    print("")
    print("  V6.7 PROPORTIONAL (Gemini's Fuel Balance Fix):")
    print(f"    • Proportional Throttle: {'✅ ENABLED' if args.proportional_throttle else '❌ disabled'}", end="")
    if args.proportional_throttle:
        print(f" (soft={args.theta_prime_soft_limit:.0f}K, hard={args.theta_prime_hard_limit:.0f}K)")
    else:
        print("")
    print(f"    • Moisture Floor: {args.moisture_floor*1000:.2f} g/kg")
    print("")
    print("  THEORY: Gemini Research + Five + Claude Ensemble")
    print("=" * 80)
    
    # Close logger
    print(f"\n[LOGGING] Completed at: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"[LOGGING] Log saved to: {log_filename}")
    logger.close()
    sys.stdout = logger.terminal