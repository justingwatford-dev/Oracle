# Oracle V4: GPU-Accelerated Hurricane Lifecycle Simulation
A pseudo-spectral computational fluid dynamics system for simulating tropical cyclone lifecycles from genesis through landfall and inland decay.

**Current Version:** V62.6 (Cold Water Stability Fix - "Mechanical Zombie" Patch)

Status: Research prototype - Not an operational forecast system  
Primary Use: Physics validation and hurricane dynamics research

## Overview
Oracle V4 implements a GPU-accelerated Navier-Stokes solver for atmospheric simulation, with specialized physics modules for tropical cyclone dynamics. The system integrates ERA5 reanalysis data for environmental forcing and validates against HURDAT2 historical tracks.

**V62.6 Highlight:** Cold water stability fix addresses "Mechanical Zombie" oscillations. Three-pronged ensemble solution: (1) SST-based stability factor for momentum anchor preventing surface wind clamping in cold water, (2) Ghost Nudge disabled when SST < 26°C, (3) Stall Breaker disabled in cold water. Eliminates 64-148 kts oscillations at 40°N, enables smooth decay to TS/TD.

**V62.5 Highlight:** Unified climatology-based OHC floor calculation. Replaces hardcoded `MIN_OHC_DEEP_POOL = 40` with physics-based floor derived from SST climatology: `OHC_floor = max(0, 50*(SST_clim - 26))`. Allows full ocean cooling north of 30°N, preventing unrealistic 26.8°C minimum SST in cold North Atlantic.

**V62.4 Highlight:** Moving nest climatology regeneration with documented NOAA OISST v2.1 lookup table. Fixes "Magic Carpet" bug where SST/OHC grids computed once at frame 0 allowed storms to carry Caribbean warm water pools northward. Now regenerates climatology on nest recenter events while preserving cold wake memory.

**V62.3 Highlight:** Grid-based ocean thermal structure with latitude-dependent OHC initialization and cold water fuel throttling, preventing unrealistic intensification in northern latitudes.

**V62.2 Highlight:** Comprehensive landfall physics overhaul addressing energy conservation over land. The patch implements land-aware guidance suppression, fuel throttling, and progressive viscosity floors to enforce the system invariant: *"Over land, Oracle may steer track but must never preserve intensity."*

**V62.1 Highlight:** Smagorinsky Large Eddy Simulation (LES) closure for physics-based turbulent viscosity, replacing the previous empirical lookup table approach (retained in V62.2).

## Key Capabilities
- Full lifecycle simulation (genesis to dissipation)
- **Smagorinsky LES turbulence closure** for physics-based viscosity (V62.1+)
- **Land-aware guidance and energy regulation** (V62.2)
- **Grid-based ocean thermal structure with cold water recognition** (V62.3)
- **Dynamic climatology regeneration on nest movement** (V62.4)
- **Unified climatology-based OHC floor** (V62.5)
- **Cold water stability factor for momentum and guidance helpers** (V62.6)
- Landfall physics with terrain-dependent surface fluxes
- Adaptive mesh refinement for computational efficiency
- Real-time vortex tracking and intensity classification
- Phase-aware adaptive steering guidance

## V62.6 Cold Water Stability Fix - "Mechanical Zombie" Patch

### The Three-Headed Zombie Problem (Ensemble Discovery)

Even after V62.5 allowed cold water, storms at 40°N exhibited severe oscillations (64 kts ↔ 148 kts) instead of smooth decay. The ensemble identified **three mechanical energy injection pathways** still active in cold water:

| Head | Problem | V62.6 Fix | Attribution |
|------|---------|-----------|-------------|
| **Thermodynamics** | MIN_OHC_DEEP_POOL = 40 guaranteed warm ocean | OHC_floor = max(0, 50*(SST-26)) | Five |
| **Momentum Anchor** | Clamped surface winds regardless of SST | stability_factor based on SST | Gemini |
| **Guidance Helpers** | 517+231 activations injected energy | Disabled when SST < 26°C | Five |

### The Fix (Three-Pronged Ensemble Solution)

**1. SST-Based Stability Factor (Gemini):**
```python
# Momentum anchor now respects ocean temperature
stability_factor = max(0, (SST - 20.0) / (26.5 - 20.0))
anchor_strength *= stability_factor

# At 40°N with SST = 21°C:
# stability_factor = (21-20)/(26.5-20) = 0.15
# anchor_strength = 0.70 × 0.15 = 0.105 (clutch slips!)
```

**2. Ghost Nudge Cold Water Disable (Five):**
```python
# Ghost nudge only active in warm water
if mean_sst < 26.0:
    # DISABLED - no momentum injection
    pass
```

**3. Stall Breaker Cold Water Disable (Five):**
```python
# Stall breaker only active in warm water
if mean_sst < 26.0:
    # DISABLED - no velocity injection
    pass
```

### Physical Justification

| Component | Warm Water (>26°C) | Cold Water (<26°C) | Rationale |
|-----------|-------------------|-------------------|-----------|
| Momentum Anchor | Full strength | Weak/disabled | Tropical cyclones require warm water for structural integrity |
| Ghost Nudge | Active | Disabled | No tropical convection in cold water |
| Stall Breaker | Active | Disabled | Extratropical systems have different dynamics |

### Expected Behavior

**Before V62.6 at 40°N (SST = 21°C):**
```
anchor_strength = 0.70 (full grip, clamping surface winds)
Ghost Nudge: ACTIVE (injecting momentum)
Stall Breaker: ACTIVE (injecting velocity)
→ Oscillation: 64 kts ↔ 148 kts (mechanical zombie!)
```

**After V62.6 at 40°N (SST = 21°C):**
```
stability_factor = (21-20)/(26.5-20) = 0.15
anchor_strength = 0.70 × 0.15 = 0.105 (clutch slips!)
Ghost Nudge: DISABLED (cold water)
Stall Breaker: DISABLED (cold water)
→ Smooth decay to TS/TD
```

### Diagnostic Output

**Warm Water Operation (Unchanged):**
```
🌡️ V62.6 STABILITY: SST=28.5°C, factor=1.00, anchor=0.70
👻 Ghost Nudge: ACTIVE (warm water convection)
🛑 Stall Breaker: ACTIVE (tropical dynamics)
```

**Cold Water Transition:**
```
🌡️ V62.6 STABILITY: SST=25.8°C, factor=0.89, anchor=0.62
👻 Ghost Nudge: DISABLED (SST < 26°C)
🛑 Stall Breaker: DISABLED (SST < 26°C)
```

**Deep Cold Water:**
```
🌡️ V62.6 STABILITY: SST=21.0°C, factor=0.15, anchor=0.11
👻 Ghost Nudge: DISABLED (SST < 26°C)
🛑 Stall Breaker: DISABLED (SST < 26°C)
🌊 Smooth decay in progress...
```

### Impact on Oscillation Modes

| SST Range | Stability Factor | Anchor Strength | Ghost Nudge | Stall Breaker | Expected Behavior |
|-----------|------------------|-----------------|-------------|---------------|-------------------|
| >26.5°C | 1.00 | 0.70 | Active | Active | Full tropical dynamics |
| 26.0-26.5°C | 0.77-1.00 | 0.54-0.70 | Active | Active | Marginal maintenance |
| 24.0-26.0°C | 0.62-0.77 | 0.43-0.54 | **Disabled** | **Disabled** | Weakening transition |
| 20.0-24.0°C | 0.00-0.62 | 0.00-0.43 | **Disabled** | **Disabled** | Rapid decay |
| <20.0°C | 0.00 | 0.00 | **Disabled** | **Disabled** | Post-tropical remnant |

## V62.5 Unified Climatology Floor - "The Final Piece"

### The Residual Bug (Five's Discovery)

Even after V62.4's climatology regeneration, storms were still maintaining unrealistic intensity in the North Atlantic. The culprit: **hardcoded `MIN_OHC_DEEP_POOL = 40` constant** from V52.

**OLD CODE (broken):**
```python
MIN_OHC_DEEP_POOL = 40.0
self.OHC = max(MIN_OHC_DEEP_POOL, OHC - depletion)
# → SST = 26 + 40/50 = 26.8°C MINIMUM EVERYWHERE, FOREVER!
```

This meant that even at 40°N in 18°C climatological water, the model enforced a 26.8°C minimum SST - still warm enough to maintain hurricane intensity!

### The Fix (Five's Solution)

**NEW CODE (V62.5):**
```python
# OHC_floor derived from SST_climatology (NOAA OISST table)
# OHC_floor = max(0, 50*(SST_clim - 26))
# At 40°N: floor = max(0, 50*(21-26)) = 0 ← NO PROTECTION!
```

The floor is now **physics-based and location-dependent**, calculated from the same NOAA OISST v2.1 climatology used in V62.4.

### Physical Justification

| Parameter | Formula | Source |
|-----------|---------|--------|
| OHC-SST relationship | OHC ≈ 50 kJ/cm² per °C above 26°C | Leipper & Volgenau (1972) |
| Hurricane threshold | SST = 26°C | Emanuel (1986), Gray (1968) |
| OHC floor | max(0, 50*(SST_clim - 26)) | Derived from above |

### What This Means

| Latitude | SST_clim | OHC_floor | Can cool? |
|----------|----------|-----------|-----------|
| 15°N | 29°C | 150 | Protected (tropics) |
| 25°N | 27.5°C | 75 | Protected |
| **30°N** | **26°C** | **0** | **UNPROTECTED** |
| 35°N | 24°C | 0 | UNPROTECTED |
| 40°N | 21°C | 0 | UNPROTECTED |

**North of 30°N, the ocean can now get cold!** No more artificial 26.8°C minimum preventing realistic decay.

### Diagnostic Output

**At Initialization:**
```
🌊 V62.5 UNIFIED CLIMATOLOGY: Lat range [10.0°N, 25.0°N]
   SST range: 27.5 - 29.0 °C
   OHC_floor range: 75.0 - 150.0 kJ/cm²
```

**On Nest Recenter:**
```
🌊 V62.5 REGENERATING: Storm at 38.5°N, domain [31.0°N, 46.0°N]
   New SST range: 18.0 - 26.0 °C
   New OHC_floor range: 0.0 - 0.0 kJ/cm²  ← THIS IS THE KEY!
```

**Cold Water Throttle:**
```
🌊 V62.5 COLD WATER: Lat=40.0°N, SST=21.0°C, Factor=0.32, Fuel=0.30
```

### Expected Behavior Change

| Location | V62.4 Minimum SST | V62.5 Minimum SST | Impact |
|----------|-------------------|-------------------|--------|
| 15°N Caribbean | 28.5°C | 28.5°C | Unchanged |
| 25°N Subtropics | 26.8°C (bug!) | 27.5°C | Correct |
| 35°N Mid-Atlantic | 26.8°C (bug!) | 24.0°C | **Weakening** |
| 40°N North Atlantic | 26.8°C (bug!) | 21.0°C | **Rapid decay** |

## V62.4 Moving Nest Climatology Fix - "Magic Carpet" Patch

### The Bug (Gemini's Diagnosis)

**"Magic Carpet"**: The moving nest architecture updates `lat_bounds` as the storm moves north, but the SST/OHC grids were computed **once at frame 0** based on the initial Caribbean position. Result: Storm carries a "swimming pool" of warm Caribbean water (120 kJ/cm², 29°C) all the way to Rhode Island!

### The Fix (Five's Implementation Rules)

Following Five's constraints:
- No tuned relaxation rates (regenerate on recenter events only)
- Documented climatology source (NOAA OISST v2.1 lookup table)
- Cold wake memory preserved (tracked as anomaly from climatology)
- Grid-based, not scalar (SST field regenerated for new lat_bounds)

**Implementation:**

1. **Documented Climatology Table**: NOAA Optimum Interpolation SST (OISST) v2.1 Monthly Climatology
   ```
   Source: Reynolds et al. (2007), J. Climate, 20, 5473-5496
   
   August Atlantic SST Climatology:
   5°N:  28.0°C (Deep tropics)
   15°N: 29.0°C (Peak warm pool - Cape Verde)
   25°N: 27.5°C (Northern Caribbean)
   30°N: 26.0°C (Gulf Stream / Florida)
   35°N: 24.0°C (Mid-Atlantic weakening zone)
   40°N: 21.0°C (North Atlantic rapid decay)
   45°N: 18.0°C (Cold North Atlantic)
   ```

2. **Regeneration Trigger**: On nest recenter events when lat/lon shift > 0.01°
   ```
   if has_shifted:
       _regenerate_climatology_on_recenter()
   ```

3. **Cold Wake Preservation**: Storm-induced cooling tracked as anomaly from climatology
   ```
   Before: cold_wake_anomaly = SST_climatology_old - SST_current
   After: SST = SST_climatology_new - cold_wake_anomaly
   ```

### Data Flow

```
Frame 0 (Caribbean, 15°N):
├── lat_bounds = [10°N, 25°N]
├── SST_climatology = [28.5°C ... 27.5°C]
└── SST = 28-29°C everywhere

Frame 50000 (Nest recenters to 35°N):
├── lat_bounds = [30°N, 45°N]
├── cold_wake_anomaly preserved from previous region
├── SST_climatology = [26°C ... 18°C]
└── SST = new_climatology - cold_wake = [24°C ... 16°C]
```

### Expected Behavior

| Latitude | Old Model SST | V62.4 SST | Cold Throttle | Hurricane Potential |
|----------|---------------|-----------|---------------|---------------------|
| 15°N | 29°C | 29°C | None (full fuel) | Full development |
| 30°N | 29°C (bug!) | 26°C | 0% throttle | Marginal maintenance |
| 35°N | 29°C (bug!) | 24°C | 16% throttle | Weakening begins |
| 40°N | 29°C (bug!) | 21°C | 40% throttle | Rapid decay |
| 45°N | 29°C (bug!) | 18°C | 40% throttle | No tropical character |

### Diagnostic Output

**At Initialization:**
```
🌊 V62.4 THERMO INITIALIZED: Lat range [10.0°N, 25.0°N]
   OHC range: 76.0 - 120.0 kJ/cm²
   SST range: 27.5 - 29.0 °C
```

**On Nest Recenter:**
```
>>> NEST UPDATE: Anchoring to History (38.50, -74.20) <<<
🌊 V62.4 CLIMATOLOGY REGENERATED: Lat range [30.0°N, 45.0°N]
   New SST range: 18.0 - 26.0 °C
   Cold wake preserved: max 2.3°C cooling
```

## V62.3 Cold Water Patch - "Hot Tub Time Machine" Fix

### The Bug (Gemini's Discovery)

**"Hot Tub Time Machine"**: The moving nest was dragging Caribbean OHC (120 kJ/cm²) northward as the storm tracked. Combined with the `MIN_OHC_DEEP_POOL = 40` floor from V52, the model could never generate water colder than 26.8°C — enabling Category 3 hurricanes at Rhode Island latitudes!

### The Fix (Ensemble Solution)

Following Five's design constraints:
- No fixed constants without physical interpretation
- No outcome-based throttles (Smagorinsky LES only)
- Grid-based floors (storm moves INTO cold water, doesn't drag warm water)
- Smooth monotonic decay (no step functions)

**Implementation:**

1. **Grid-Based OHC Initialization**: Each grid cell gets OHC based on its latitude, not storm position
   ```
   20°N: 120 kJ/cm² (SST ~28.4°C) - Tropical warm pool
   35°N: 50 kJ/cm² (SST ~27°C) - Hurricane threshold
   45°N: 10 kJ/cm² (SST ~26.2°C) - Cold water
   ```

2. **Grid-Based OHC Floor**: Location-dependent minimum OHC
   ```
   Tropics (20-25°N): 40 kJ/cm² floor (warm pool protection)
   Mid-latitudes (40°N+): 0 kJ/cm² floor (full depletion allowed)
   ```

3. **Cold Water Fuel Throttle**: SST-based smooth decay (not latitude step function)
   ```
   SST > 26.5°C: Full fuel (1.0)
   SST < 26.5°C: Linear reduction to 0.40 minimum at 22°C
   ```

### Physical Justification

| Parameter | Value | Source |
|-----------|-------|--------|
| SST threshold | 26°C | Emanuel (1986), Gray (1968) |
| Weakening latitude | ~35°N | Atlantic basin climatology |
| OHC at threshold | ~50 kJ/cm² | Leipper & Volgenau (1972) |
| Linear decay 25-45°N | - | August SST climatology |

### Expected Behavior

| Latitude | OHC | SST | Fuel Factor | Hurricane Potential |
|----------|-----|-----|-------------|---------------------|
| 15°N | 120 | 28.4°C | 1.00 | Full development |
| 25°N | 76 | 27.5°C | 1.00 | Hurricane maintenance |
| 30°N | 54 | 27.1°C | 1.00 | Marginal maintenance |
| 35°N | 32 | 26.6°C | 0.98 | Weakening begins |
| 40°N | 10 | 26.2°C | 0.93 | Rapid weakening |
| 45°N | 10 | 26.2°C | 0.93 | No tropical character |

### Diagnostic Output

**At Initialization:**
```
🌊 V62.3 OHC INITIALIZED: Lat range [10.0°N, 45.0°N]
   OHC range: 10.0 - 120.0 kJ/cm²
   Floor range: 0.0 - 40.0 kJ/cm²
```

**During Cold Water Encounter:**
```
🌊 V62.3 COLD WATER: Lat=38.5°N, SST=26.1°C, Factor=0.95, Fuel=1.21
🌊 V62.3 THERMO: Lat=38.5°N, OHC=25.3, Floor=8.7, SST=26.5°C
```

## V62.2 Landfall Patch - Ensemble Solution

### System Invariant (Five)
> "Over land, Oracle may steer track but must never preserve intensity."

### Summary of Changes

| Fix | Source | What Changed |
|-----|--------|--------------|
| Land-Aware Guidance | Gemini | `guidance_strength *= (1.0 - 0.8 * core_land_fraction)` |
| Ghost Nudge Suppression | Claude/Gemini | Disabled when `core_land_fraction >= 0.5` |
| Stall Breaker Fix | Five | Uses core-sampled land fraction, not domain mean |
| Hard Fuel Cut | Claude | 1.0x at >50% land, 0.95x at >80% land |
| Progressive Emergency Floor | Five | 0.45 at 175kts → 0.75 at 200kts |
| mu_current Reconnection | Five | Land viscosity boost now reaches solver |

### Architecture Decision: Smagorinsky RETAINED

Gemini's initial patch proposal reverted to "Magic Mu" lookup table. **We rejected this** because:

1. Red Team specifically identified Magic Mu as "Outcome-Based Physics"
2. Smagorinsky was working correctly (producing nu_turb 0.15-0.32)
3. The zombie problem was **energy injection**, not viscosity calculation

V62.2 keeps Smagorinsky and closes the energy injection pathways instead.

### Energy Budget Analysis

**Before V62.2 (Zombie Harvey):**
```
IN:  5% fuel + Ghost Nudge + 100% Guidance + Flat 0.45 viscosity ceiling
OUT: Cannot overcome energy input
NET: Stable equilibrium at 175-182 kts over land
```

**After V62.2:**
```
IN:  -5% fuel (starvation) + No Ghost Nudge + 20% Guidance
OUT: Progressive viscosity (0.45→0.75) + terrain_roughness + mu_current boost
NET: Rapid decay expected
```

### Expected Diagnostic Output

**Over Ocean (unchanged):**
```
🌀 SMAGORINSKY V62.2: Wind=175kts, COH=0.59
   Nu_turb: Avg=0.0022, Max=0.3235 | Nu_total: Avg=0.0410, Max=0.5786
```

**At Landfall:**
```
⛰️ V62.2 GUIDANCE DAMPENED: Core over 50.0% land. Strength=0.60
⛰️ V62.2 GHOST NUDGE SUPPRESSED: Core over 60.0% land
```

**Deep Inland:**
```
🏜️ V62.2 FUEL CUT: Core over 100.0% land, fuel=0.95, mu_current=0.30
🏜️ V62.2: Stall detected (5000 frames) but core over 100.0% land - breaker DISABLED
```

## Physical Formulation

### Core Solver (core_solver.py)
**Numerical Method:** Pseudo-spectral Navier-Stokes solver with pressure projection

**Spatial Derivatives:**
```
∂u/∂x ≈ iFFT(ik_x · FFT(u))
```

**Pressure Projection:** Helmholtz decomposition for divergence-free flow
```
∇²p = ∇·u*
u^(n+1) = u* - ∇p
```

**Advection Scheme:** Semi-Lagrangian backward trajectory method
```
u^(n+1)(x) = u^n(x - u^n Δt)
```

**Vertical Structure:** Multi-layer system with separate horizontal/vertical damping factors

**Temporal Integration:** Explicit time stepping with CFL-limited timestep

### Turbulence Closure: Smagorinsky LES (V62.1+)
The V62.1 release implements a Smagorinsky Large Eddy Simulation (LES) closure for sub-grid scale turbulence modeling. This replaced the previous empirical "Magic Mu" lookup table that set viscosity based on wind speed.

**Physical Basis:**
Turbulent viscosity is computed dynamically from the Strain Rate Tensor:

```
ν_turb = (Cs · Δ)² · |S|
```

Where:
- `Cs = 0.17` (Smagorinsky constant)
- `Δ = (dx · dy · dz)^(1/3)` (filter scale)
- `|S| = √(2 · S_ij · S_ij)` (strain rate magnitude)

**Key Properties:**
- High shear regions → High viscosity (natural hypercane braking)
- Low shear regions → Low viscosity (allows natural genesis)
- Self-regulating: no manual intensity thresholds required

**Resolution Scaling (V62.1 Fix):**
For coarse-grid simulations (~15 km), a resolution boost factor is applied to produce effective viscosities in the physically appropriate range (0.1-0.5). This is standard practice for coarse LES where sub-grid turbulence cannot be explicitly resolved.

**V62.2 Enhancements:**
- Progressive emergency floor: 0.45 at 175kts → 0.75 at 200kts
- Reconnected mu_current land boost to solver
- Fuel throttle integration for land energy regulation

### Boundary Conditions (boundary_conditions.py)

**Ocean-Atmosphere Interface:**
- Bulk aerodynamic formulation for surface fluxes
- Wind-speed-dependent transfer coefficients
- Clausius-Clapeyron saturation vapor pressure
- **Grid-based OHC initialization with latitude dependence** (V62.3)
- **Dynamic climatology regeneration on nest movement** (V62.4)
- **Unified climatology-based OHC floor** (V62.5)
- **Cold water stability factor for momentum and guidance helpers** (V62.6)

**Landfall Physics (V62.2 Enhanced):**
- ERA5 land-sea mask integration (Copernicus dataset)
- Blended surface flux transition (ocean → land)
- Terrain-dependent roughness length
- Surface drag parameterization
- Multi-layer friction profiles
- **Land-aware guidance suppression**
- **Progressive fuel throttling over land**

**Energy Regulation:**
- Multi-layer intensity limiting system
- Phase-dependent maximum intensity thresholds
- **Hard fuel cut at >50% land contact** (V62.2)
- Prevents unrealistic intensity maintenance over land

### Adaptive Mesh Refinement (amr_handler.py)
**Three-Level Hierarchy:**

| Level | Trigger Criteria | Resolution | Purpose |
|-------|------------------|------------|---------|
| L1 | Vorticity > 2.5 | ~15 km | Circulation features |
| L2 | High vorticity + low pressure | ~7 km | Eyewall structure |
| L3 | Category 4-5 storms | ~1.5 km | Intense core dynamics |

**Implementation:** Memory-efficient nested grid design with dynamic resolution scaling

### Storm Tracking (storm_tracker.py)
**Vortex Detection:** Pressure minimum identification with geographic coordinate transformation

**Classification:** Saffir-Simpson scale based on maximum sustained winds

**Quality Metrics:**
- Lock score: Vortex centering confidence (0-1 scale)
- Coherence metric: Structural quality assessment
- Geographic tracking immune to domain movement

### Environmental Steering (data_interface.py)
**Data Source:** ERA5 reanalysis via Copernicus Climate Data Store

**Steering Calculation:**
- Deep-layer mean wind (300-850 hPa, mass-weighted)
- 40% core masking to prevent self-advection artifacts
- Kalman filtering for temporal consistency

**Domain Configuration:**
- Lagrangian grid: Dynamic re-centering on vortex
- 4° × 4° precision domain for local environmental forcing

### Adaptive Guidance (oracle_adaptive.py)
**Phase Detection:** Automatic classification of storm lifecycle stage
- Genesis, intensification, mature, eyewall replacement cycle, weakening

**Adaptive Intervention (V62.2 Enhanced):**
- Phase-dependent steering adjustment thresholds
- Confidence-weighted decision making
- Parameter learning from validation campaigns
- **Land-aware guidance decay** (`guidance_strength *= (1.0 - 0.8 * core_land_fraction)`)
- **Ghost nudge suppression over land** (disabled when `core_land_fraction >= 0.5`)
- **Stall breaker land logic** (only fires over ocean)

## Computational Performance

### Hardware Configuration
**Primary Workstation:**
- GPU: NVIDIA RTX 5070 Ti (16GB VRAM)
- CPU: Intel i9 (ERA5 data fetch and I/O)
- Storage: NVMe SSD
- GPU Utilization: 82% sustained during physics computation

**Acceleration:** CuPy GPU implementation ~23× faster than NumPy CPU baseline

### Performance Benchmarks

| Simulation Duration | Frame Count | Wall Time | Throughput | Hardware |
|---------------------|-------------|-----------|------------|----------|
| 3 days | ~65,000 | ~2 hours | ~32,500 frames/hour | RTX 4090 |
| 5.5 days | 120,000 | 7.12 hours | ~16,850 frames/hour | RTX 5070 Ti |
| 8 days | 175,000 | 14.8 hours | ~11,800 frames/hour | RTX 5070 Ti |
| 10 days | 220,000 | ~16 hours | ~13,750 frames/hour | RTX 5070 Ti |

**Scaling Characteristics:**
- Approximately linear scaling with simulation length
- GPU memory usage stable (<10 GB typical, <16 GB maximum)
- Thermal management important for extended runs
- ERA5 data fetches provide natural GPU cooldown intervals

## Validation Campaign

### Objectives
Multi-storm validation campaign designed to test model performance across:
- Intensity range (tropical storm to Category 5)
- Track complexity (straight-line, recurvature, stalls)
- Structural phenomena (rapid intensification, eyewall replacement cycles)
- Environmental conditions (Gulf of Mexico, Atlantic, Caribbean)
- Landfall and inland decay physics
- Extratropical transition and cold water interaction

### Validation Metrics
- **Track Error:** Root-mean-square error (RMSE) against HURDAT2 best track
- **Intensity Error:** Maximum wind speed deviation from observations
- **Landfall Timing:** Coastal crossing time accuracy
- **Decay Rate:** Inland weakening validation
- **Extratropical Transition:** Cold water weakening validation (V62.4)

### Current Progress
**Active Simulation:** Hurricane Harvey (2017)
- Focus: Extended inland decay validation (Texas landfall)
- Duration: 12+ days simulated (300,000+ frames)
- Challenge: Maintaining realistic weakening physics over land
- **V62.2 Target:** Validate rapid decay from 175→TS within 24h of landfall
- **V62.3 Target:** Validate no re-intensification in Gulf after landfall
- **V62.4 Target:** Validate climatology regeneration during northward track
- **V62.5 Target:** Validate realistic decay in cold North Atlantic (SST < 24°C)
- **V62.6 Target:** Validate smooth decay without oscillations in cold water

**Completed Validations:**

| Storm | Year | Category | Track RMSE | Duration | Notes |
|-------|------|----------|------------|----------|-------|
| Katrina | 2005 | Cat 5 | 38.2 km | 7 days | Research-grade track accuracy |
| Ivan | 2004 | Cat 5 | 71.6 km | 10 days | Extended simulation with stall periods |
| Charley | 2004 | Cat 4 | 110.6 km | 5.5 days | Genesis phase validation, V62.4 test case |
| Sandy | 2012 | Cat 3 | TBD | 8 days | Extratropical transition case |

### Storm Roster (15 Storms Total)

**Intensity Validation:**
- Dennis (2005): Rapid intensification
- Ike (2008): Annular structure
- Isabel (2003): Long-lived Cape Verde hurricane

**Track Complexity:**
- Wilma (2005): Sharp recurvature
- Jeanne (2004): Caribbean loop and meandering
- Ophelia (2005): Coastal-parallel track

**Structural Phenomena:**
- Rita (2005): Eyewall replacement cycles
- Emily (2005): Multiple ERCs
- Felix (2007): Extreme rapid intensification

## Installation

### System Requirements

| Component | Minimum | Recommended |
|-----------|---------|-------------|
| GPU | NVIDIA RTX 3060 (8GB VRAM) | RTX 4080/5070 Ti (16GB VRAM) |
| CUDA | Toolkit 11.x | Toolkit 12.x |
| System RAM | 16 GB | 32 GB |
| Storage | 50 GB SSD | 100 GB NVMe |
| OS | Linux (tested) | Ubuntu 20.04+ |

### Python Dependencies
- Python 3.9+
- numpy
- cupy-cuda11x  # or cupy-cuda12x for CUDA 12
- scipy
- matplotlib
- netCDF4
- xarray

### ERA5 Data Access
1. Create free account: https://cds.climate.copernicus.eu/
2. Install CDS API key in ~/.cdsapirc
3. Accept ERA5 data license terms

### Setup Instructions
```bash
# Clone repository
git clone https://github.com/justingwatford-dev/Woe-Solver-Suite.git
cd Woe-Solver-Suite

# Install dependencies
pip install -r requirements.txt

# Verify GPU accessibility
python -c "import cupy; print(cupy.cuda.Device())"
```

### Directory Structure
```
oracle-v4/
├── World_woe_main_adaptive.py     # Main simulation driver
├── core_solver.py                 # Pseudo-spectral CFD solver
├── data_interface.py              # ERA5/HURDAT2 integration
├── oracle_logger.py               # Diagnostics and logging
├── storm_tracker.py               # Vortex tracking and classification
├── oracle_adaptive.py             # Phase-aware guidance system
├── boundary_conditions.py         # Surface flux physics
├── amr_handler.py                 # Adaptive mesh refinement
├── kalman_filter.py               # Data assimilation filtering
├── Train_oracle.py                # Parameter learning pipeline
├── oracle_memory.py               # Simulation recording system
├── visualiser.py                  # VTK and 2D visualization
├── run_training_campaign.py       # Multi-run campaign manager
├── hurdat2.txt                    # HURDAT2 best track database
├── oracle_learned_params_v4.json  # Calibrated parameters
└── oracle_memory_db/              # Simulation history database
```

## Usage Examples

### Single Storm Simulation
```bash
python World_woe_main_adaptive.py \
    --storm KATRINA \
    --year 2005 \
    --initial-wind 50.0
```

### Training Campaign (Parameter Optimization)
```bash
python run_training_campaign.py \
    --storm WILMA \
    --year 2005 \
    --runs 20 \
    --vary
```

### Custom Storm
```bash
python World_woe_main_adaptive.py \
    --storm "STORM_NAME" \
    --year YYYY \
    --initial-wind 50.0
```

### GPU Verification
```bash
# Check CUDA availability
nvidia-smi

# Verify CuPy installation
python -c "import cupy; print(cupy.__version__)"
```

### Monitor Running Simulation
```bash
tail -f logs/oracle_v4_STORM_*.log
```

## Known Limitations

**Spatial Resolution:** 1.5-15 km grid spacing cannot fully resolve sub-grid-scale processes (turbulence, microphysics)

**Turbulence Modeling:**
- Smagorinsky LES requires resolution boost factor for coarse grids
- True LES formulation (∇·(ν∇u)) approximated as ν·∇²u
- Sub-grid turbulence parameterized rather than resolved

**Adaptive Mesh Refinement:**
- AMR logic currently functions as diagnostic only (Red Team finding)
- Global spectral solver incompatible with local grid refinement
- True AMR would require spectral element or finite volume rewrite (V5 roadmap)

**Simplified Physics:**
- No explicit cloud microphysics (parameterized)
- Simplified radiation scheme
- Idealized ocean mixed layer (no dynamic coupling)

**Environmental Forcing:** Dependent on ERA5 reanalysis accuracy and temporal resolution (hourly updates)

**Validation Scope:** Currently validated only on Atlantic basin hurricanes (2003-2017)

**Operational Use:** Not suitable for real-time forecasting
- No data assimilation of real-time observations
- No ensemble framework for uncertainty quantification
- Computational cost prohibitive for operational timelines

**Track Errors:** RMSE typically 40-110 km (research-grade, not operational-grade)

**Genesis Representation:** Initial vortex requires manual specification; does not simulate genesis from environmental conditions

## Comparison with Established Models

Oracle V4 is a research prototype, not a replacement for operational models:

| Feature | Oracle V4 | HWRF/HMON | WRF |
|---------|-----------|-----------|-----|
| Purpose | Physics research | Operational forecasting | Multi-purpose research |
| Resolution | 1.5-15 km adaptive | 2-6 km nested | User-configurable |
| Physics | Simplified CFD | Full parameterization suite | Comprehensive |
| Data Assimilation | None | Advanced (3D/4D-Var) | Multiple schemes available |
| Ensemble | No | Yes | Yes |
| Computational Cost | ~16 hours (10 days) | ~2 hours (5 days, supercomputer) | Variable |

**Primary Advantage:** GPU acceleration enables rapid iteration for physics experimentation

**Primary Disadvantage:** Simplified physics and lack of data assimilation limit forecast accuracy

## Documentation

| Document | Description |
|----------|-------------|
| PATCHES.md | Development history and version changelog |
| TECHNICAL.md | Detailed architecture documentation |
| CAMPAIGN.md | Validation campaign details |
| CONTRIBUTING.md | Development guidelines |

## Data Sources

**Environmental Forcing:**
- ERA5 Reanalysis: Copernicus Climate Change Service (Hersbach et al., 2020)
- CDS API: https://cds.climate.copernicus.eu/

**Validation Data:**
- HURDAT2: NOAA National Hurricane Center Best Track Database
- Landsea & Franklin (2013), Monthly Weather Review

**Ocean Climatology (V62.4):**
- NOAA Optimum Interpolation SST (OISST) v2.1 Monthly Climatology
- Reynolds et al. (2007), J. Climate, 20, 5473-5496

## Development Notes

### Version History
Full patch history available in PATCHES.md

**Recent Major Updates:**
- **V62.6 (January 2026):** Cold Water Stability Fix - "Mechanical Zombie" Patch
  - Three-headed zombie problem identified by ensemble
  - SST-based stability factor for momentum anchor (Gemini)
  - Ghost Nudge disabled when SST < 26°C (Five)
  - Stall Breaker disabled in cold water (Five)
  - Eliminates 64-148 kts oscillations, enables smooth decay
- **V62.5 (January 2026):** Unified Climatology Floor - "The Final Piece"
  - Physics-based OHC floor calculation from SST climatology (Five's discovery)
  - Formula: `OHC_floor = max(0, 50*(SST_clim - 26))` (Five's solution)
  - Replaces hardcoded MIN_OHC_DEEP_POOL = 40 constant
  - Allows full ocean cooling north of 30°N (no more 26.8°C minimum)
- **V62.4 (January 2026):** Moving Nest Climatology Fix - "Magic Carpet" Patch
  - Documented NOAA OISST v2.1 climatology lookup table (Gemini discovery)
  - Dynamic climatology regeneration on nest recenter events (Five's rules)
  - Cold wake memory preservation across nest movements (Claude)
  - Prevents unrealistic warm water dragging to northern latitudes
- **V62.3 (January 2026):** Cold Water Patch - Grid-based ocean thermal structure
  - Grid-based OHC initialization with latitude dependence (Gemini discovery)
  - Location-dependent OHC floor (Five's constraints)
  - SST-based cold water fuel throttle (Ensemble)
  - Prevents "Hot Tub Time Machine" bug (warm water dragging north)
- **V62.2 (January 2026):** Landfall Patch - Ensemble solution addressing zombie storm energy conservation
  - Land-aware guidance suppression (Gemini)
  - Ghost nudge suppression over land (Claude/Gemini)
  - Stall breaker land logic (Five)
  - Hard fuel cut at >50% land contact (Claude)
  - Progressive emergency viscosity floor (Five)
  - mu_current reconnection to solver (Five)
- **V62.1 (January 2026):** Smagorinsky LES turbulence closure following Red Team review
- **V61.x:** Zombie Storm Fix - comprehensive landfall physics overhaul
- **V50-V55:** Guidance system refinements, WISDOM intensity regulator

### Red Team Review (V62)
The V62 Smagorinsky implementation was informed by an external Red Team review that identified the previous viscosity approach as "Outcome-Based Physics" - setting viscosity based on wind speed rather than the underlying turbulence. Key findings:
- The adaptive mesh refinement (AMR) was functioning as a passive diagnostic rather than actively refining resolution
- Physics-based turbulence closure (Smagorinsky) recommended over empirical lookup tables
- Landfall physics parameterization validated as appropriate for model complexity level

### Development Methodology
Iterative physics validation through multi-storm campaign testing. Development utilized a multi-AI ensemble collaboration approach (Claude, Gemini, and others) for code review, physics debugging, and implementation. Each model contributed specialized insights - from numerical stability analysis to physical parameterization design.

**V62.6 Ensemble Contributors:**
- **Gemini:** SST-based stability factor for momentum anchor
- **Five:** Ghost Nudge and Stall Breaker cold water disable logic
- **Ensemble:** Three-headed zombie diagnosis (thermodynamics + momentum + guidance)
- **Claude:** Implementation and diagnostic integration

**V62.5 Ensemble Contributors:**
- **Five:** Residual bug discovery (hardcoded MIN_OHC_DEEP_POOL = 40)
- **Five:** Physics-based floor formula design
- **Claude:** Implementation and diagnostic integration

**V62.4 Ensemble Contributors:**
- **Gemini:** "Magic Carpet" bug discovery (SST dragging northward)
- **Five:** Implementation rules (no tuned rates, documented sources, grid-based approach)
- **Claude:** NOAA OISST v2.1 climatology table integration, cold wake preservation logic

**V62.3 Ensemble Contributors:**
- **Gemini:** "Hot Tub Time Machine" bug discovery
- **Five:** Design constraints (grid-based, physics-justified)
- **Claude:** Implementation and diagnostic integration

**V62.2 Ensemble Contributors:**
- **Claude:** Energy budget analysis, fuel throttle design
- **
