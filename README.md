# ORACLE — Tropical Cyclone Simulation from First Principles

**A physics-driven 3D spectral tropical cyclone model built to replace heuristic corrections with emergent atmospheric dynamics.**

![Version](https://img.shields.io/badge/version-7.1%20WARM--RAIN-blue)
![Python](https://img.shields.io/badge/python-3.8+-green)
![License](https://img.shields.io/badge/license-Research-orange)

---

## 🌀 Overview

Oracle is a high-resolution 3D tropical cyclone simulation that progresses from reactive heuristic-based modeling to predictive first-principles physics. The project addresses the fundamental "**Core Tension**" in TC modeling: legacy simulation architectures require artificial corrections (drift injections, intensity governors, steering overrides) to compensate for missing physics terms in the governing equations.

**The Vision:** Replace every heuristic with the actual physics that causes the phenomenon.

### Key Achievements (8 Months of Development)

- ✅ **V6.0 THETA**: Potential temperature (θ′) thermodynamics with Boussinesq framework
- ✅ **V6.3-V6.26**: WISHE feedback, landfall physics, GPU acceleration (23× via CuPy)
- ✅ **V7.0 BETA-PLANE**: Spatially-varying Coriolis f(y) enabling emergent beta drift
- ✅ **V7.0 BETTS-MILLER**: Relaxed convective adjustment replacing instantaneous saturation
- ✅ **V7.1 SPECTRAL FIX**: Z-clamp advection breaking spectral short-circuit
- 🔄 **V7.1 WARM RAIN**: Soft saturation cap with precipitation efficiency (tuning in progress)
- 🔭 **V8.0 Roadmap**: Spectral nudging + organized convection (planned)

---

## 🎯 The Core Tension

Traditional TC models face a fundamental paradox:

```
┌─────────────────────────────────────────────────────┐
│  Simplified Physics  →  Unrealistic Behavior        │
│           ↓                                          │
│  Add Heuristic Corrections  →  Loss of Predictivity │
│           ↓                                          │
│  Need More Corrections  →  Fragile Architecture     │
└─────────────────────────────────────────────────────┘
```

**Oracle's Approach:**

```
┌─────────────────────────────────────────────────────┐
│  First-Principles Physics  →  Emergent Behavior     │
│           ↓                                          │
│  Natural Constraints  →  Robust Predictions         │
│           ↓                                          │
│  Physics-Based Tuning  →  Scalable Architecture     │
└─────────────────────────────────────────────────────┘
```

---

## 🏗️ Architecture

### Computational Framework

- **Solver**: Pseudo-spectral FFT-based method with 3/2 padding for de-aliasing
- **Grid**: Triply-periodic domain (2000 km × 2000 km × 16 km)
- **Resolution**: Configurable (default 128³ grid points, ~15 km horizontal)
- **Vertical Levels**: 5 levels (0, 1250, 2500, 5000, 10000 m)
- **Time Integration**: Crank-Nicolson implicit scheme for stability
- **Parallelization**: GPU-accelerated via CuPy (23× speedup over NumPy)

### Thermodynamic Core (V6.0 Foundation)

**The Problem (V5.x):**
The Boussinesq framework is incompressible (∇·**u** = 0), meaning parcels cannot expand. Applying explicit adiabatic cooling created "phantom mass" that killed the storm. Removing it caused explosive intensification.

**The Solution (V6.0):**
Prognose **potential temperature perturbation** θ′ instead of temperature:

```
θ_total(x,y,z,t) = θ₀(z) + θ′(x,y,z,t)

Evolution:
  Dθ′/Dt = -w(dθ₀/dz) + (θ/T)(Lv/Cp)·condensation + diffusion + surface_flux

Buoyancy:
  b = g × θ′ / θ₀(z)
```

This naturally captures:
- Adiabatic cooling (implicit in θ conservation)
- Atmospheric stability (θ₀ increases with height)
- Equilibrium levels (updrafts stop when θ′ → 0)

### Dynamical Core (V7.0 Upgrade)

**The Problem:**
f-plane approximation (constant Coriolis parameter) cannot generate beta gyres. Storms don't drift without manual injection of a "beta vector."

**The Solution:**
β-plane dynamics with spatially-varying Coriolis:

```
f(y) = f₀ + β·Δy

Vorticity equation:
  ∂ζ/∂t + u·∇ζ + v·β = 0

Result: Beta gyres emerge naturally
  → Northwest drift without heuristic injection
  → Storm size affects drift speed automatically
  → Structural evolution matches observations
```

**Impact:** Replaces ~200 lines of tuned heuristics with one physics term.

### Convective Core (V7.0 Betts-Miller)

**The Problem (Instantaneous Saturation):**
The V6.x scheme removed 100% of supersaturation every timestep, crashing boundary layer humidity from 40% to 1-3% RH in the first ERA5 cycle. Three controlled experiments confirmed this was the root cause of intensity failure, not governors.

**The Solution:**
Betts-Miller relaxed convective adjustment:

```
∂q/∂t = -(q - q_ref) / τ_BM    (τ_BM ~ 900s at 15km resolution)

Features:
  - Vertical taper: Full tendency above 2500m, zero at surface
  - BL coupling: BM senses surface moisture for triggering but
    extracts moisture primarily in the free troposphere
  - Level-wise diagnostics: Per-level cell counts and dq tracking
```

**Impact:** Surface humidity holds at 19-24 g/kg instead of crashing to <1 g/kg. WISHE feedback loop activates for the first time.

### Vertical Boundary Remediation (V7.1)

**The Problem (Spectral Short-Circuit):**
The triply-periodic spectral solver allows vertical spectral modes to wrap from z_top → z_bottom. Dry upper-troposphere air (q ≈ 0) mixes directly into the boundary layer via the highest-wavenumber vertical modes, crashing surface moisture from 24 → 0.8 g/kg within hours.

**The Solution (Three-Layer Fix, Gemini Deep Research):**

| Priority | Fix | Description |
|----------|-----|-------------|
| P0 | Z-Clamp | `mode='nearest'` for vertical advection (kills spectral wrap) |
| P1 | Vertical Sponge | Rayleigh damping in top 20% (absorbs reflected waves) |
| P2 | Far-Field Relaxation | τ=12h moisture nudging at r > 400-600 km |

**Impact:** Surface moisture holds at 24.4 g/kg for 200k+ frames. First self-sustaining tropical storm achieved.

### Thermodynamic Cycle (V7.1 — Active Development)

**The Problem (θ′ Runaway):**
With the spectral short-circuit fixed, moisture holds — but every condensation event dumps heat into θ′ with no exit path. In real hurricanes, only ~20-30% of latent heat warms the column; the rest exits via rain evaporation (30-40%), outflow export (20-30%), and radiative losses (10-20%). Oracle V7.0 retained ~90-95%, causing monotonic θ′ growth to crash boundaries.

**The Solution (Three Mechanisms):**

| Mechanism | Parameter | Role |
|-----------|-----------|------|
| Precipitation Efficiency | `--precip-efficiency 0.50` | Fraction of latent heat retained as θ′ warming |
| Dynamic Cooling | `--dynamic-cooling` | Radiative relaxation with wind-adaptive τ (24h → 2h) |
| Warm Rain | `--warm-rain --warm-rain-cap 1.5` | Soft surface saturation cap (BL resolution compensation) |

**Current Status:** The precipitation efficiency parameter achieved the first 200k-frame sustained tropical storm (5.5 simulated days, mean 37 kts). The warm rain soft cap is currently being tuned to balance surface moisture (BL compensation vs vertical gradient preservation).

**Thermal Budget Comparison:**

| Sink | Real Hurricane | Oracle V7.0 | Oracle V7.1 |
|------|---------------|-------------|-------------|
| Net column warming | 20-30% | ~90-95% | ~50% (tuning) |
| Rain evaporation | 30-40% | 0% | Via precip_efficiency |
| Outflow export | 20-30% | 0% | Via precip_efficiency |
| Radiative losses | 10-20% | ~5% | Dynamic cooling |

---

## 📊 Physics Modules

### ✅ Implemented

| Module | Description | Version |
|--------|-------------|---------|
| **Potential Temperature** | θ′ prognostic variable with reference state θ₀(z) | V6.0 |
| **Beta-Plane Dynamics** | Spatially-varying f(y) for emergent drift | V7.0 |
| **Betts-Miller Convection** | Relaxed adjustment (τ ~ 900s) with vertical taper | V7.0 |
| **Surface Fluxes (WISHE)** | Wind-Induced Surface Heat Exchange with dynamic boosting | V6.3 |
| **Precipitation Efficiency** | Parameterized Carnot cycle losses | V7.1 |
| **Dynamic Radiative Cooling** | Wind-adaptive τ (24h calm → 2h intense) | V7.1 |
| **Warm Rain** | Soft surface saturation cap (configurable multiplier) | V7.1 |
| **Z-Clamp Advection** | Nearest-neighbor vertical BC (breaks spectral wrap) | V7.1 |
| **Vertical Sponge** | Rayleigh damping in top 20% of domain | V7.1 |
| **Far-Field Relaxation** | Moisture nudging outside storm radius (τ=12h) | V7.1 |
| **Landfall Physics** | Land fraction blending for drag, flux cutoff, roughness | V6.60 |
| **Smagorinsky Turbulence** | Subgrid-scale eddy viscosity | V6.2 |
| **ERA5 Steering** | Deep-layer mean (DLM) environmental wind | V6.23 |
| **Sponge Layer** | Non-reflective lateral boundaries | V6.0 |
| **GPU Acceleration** | CuPy backend with 23× speedup | V6.0 |

### 🔄 In Development

| Module | Purpose | Status |
|--------|---------|--------|
| **Organized Convection** | Focused eyewall updrafts vs diffuse BM | Active tuning |
| **Pressure Minimum** | Surface pressure drop from warm core | Not yet emergent |

### 🔭 Planned (V8.0+)

| Module | Purpose | Status |
|--------|---------|--------|
| **Spectral Nudging** | Scale-selective constraint to ERA5 (λ > 1000 km) | Planned |
| **Explicit Convection** | Resolve individual updrafts at Δx < 4 km | Future |

---

## 🚀 Quick Start

### Requirements

```bash
# Core dependencies
numpy >= 1.20
scipy >= 1.7
matplotlib >= 3.5

# Optional (GPU acceleration — strongly recommended)
cupy >= 10.0

# Data (for ERA5 steering)
cdsapi
netCDF4 >= 1.5
```

### Installation

```bash
# Clone repository
git clone https://github.com/yourusername/oracle-tc-sim.git
cd oracle-tc-sim

# Install dependencies
pip install -r requirements.txt

# Verify installation
python world_woe_main_V7_beta_plane.py --help
```

### Basic Usage

**Current recommended configuration (V7.1):**
```bash
python world_woe_main_V7_beta_plane.py \
    --storm HUGO --year 1989 \
    --betts-miller --flux-depth 100 \
    --precip-efficiency 0.50 \
    --radiative-cooling --dynamic-cooling \
    --theta-bounds -80 80 \
    --warm-rain --warm-rain-cap 1.5 \
    --frames 200000
```

**Minimal beta-plane run:**
```bash
python world_woe_main_V7_beta_plane.py \
    --storm HUGO --year 1989 \
    --betts-miller \
    --frames 50000
```

**Legacy V6.26 mode (synthetic drift):**
```bash
python world_woe_main_V6_THETA.py \
    --beta-drift \
    --storm HUGO --year 1989 \
    --frames 50000
```

### Command-Line Options

#### Convection & Thermodynamics
```
--betts-miller              Enable Betts-Miller relaxed convective adjustment
--tau-bm T                  BM relaxation timescale in seconds (default: 900)
--bm-taper-start Z          BM taper start height in meters (default: 200)
--bm-taper-full Z           BM taper full height in meters (default: 2500)
--precip-efficiency F       Fraction of latent heat retained as θ′ (default: 0.25)
--radiative-cooling         Enable Newtonian cooling (θ′ → 0)
--dynamic-cooling           Wind-adaptive cooling timescale (24h → 2h)
--tau-rad T                 Base radiative cooling timescale in seconds (default: 86400)
--warm-rain                 Enable surface saturation cap (warm rain)
--warm-rain-cap F           Saturation cap multiplier (default: 1.5)
--flux-depth D              Surface flux skin depth in meters (default: 1250)
```

#### Core Physics
```
--beta-plane                Enable spatially-varying Coriolis (V7.0)
--pure-physics              Disable Oracle nudging/corrections
--fully-unconstrained       Disable ALL governors
--theta-bounds MIN MAX      θ′ clamp bounds in Kelvin (e.g., -80 80)
```

#### WISHE & Surface Coupling
```
--wishe-boost               Enable dynamic Ck/Cd correction
--wishe-boost-max F         Maximum boost factor (default: 1.4)
--flux-throttle             Enable flux throttle (prevents runaway)
--proportional-throttle     Gradual (vs binary) WISHE throttle
```

#### Governor Controls
```
--no-flux-governor          Disable surface flux throttle
--no-wisdom                 Disable WISDOM dampening
--no-velocity-governor      Disable velocity damping/clamp
--no-thermo-firewalls       Disable temperature safety limits
```

#### Resolution & Domain
```
--resolution N              Grid points per dimension (default: 128)
--theta-surface T           Surface potential temp [K] (default: 300)
--gamma-theta G             θ lapse rate [K/km] (default: 4.0)
```

#### Visualization
```
--track-plot                Generate track plot at simulation end
--wind-plots                Save wind field snapshots
--all-plots                 Enable all visualization
--plot-interval N           Frames between snapshots (default: 7200)
```

See `--help` for complete list of 80+ tunable parameters.

---

## 📈 Validation

### V7.1 Sustained Tropical Storm (Best Run to Date)

**Configuration:** Hugo 1989, eff=0.50, dynamic cooling, no warm rain, ±80K bounds
**Duration:** 199,900 frames (133 hours / 5.5 simulated days)

| Metric | Value |
|--------|-------|
| Peak Wind | 50.2 kts |
| Mean Wind (last 100k frames) | 35.4 kts |
| TS Classifications | 213 / 1999 diagnostic intervals (11%) |
| θ′ Behavior | Self-regulating oscillation (30-60K) |
| Surface Moisture | Held at 24.4 g/kg (no starvation) |
| WISHE Feedback | Active throughout |

**Wind Trajectory:**

| Block | Mean Wind | θ′ Mean |
|-------|-----------|---------|
| 0-25k | 25.4 kts | — |
| 25-50k | 28.6 kts | — |
| 50-75k | 33.5 kts | — |
| 75-100k | 33.9 kts | — |
| 100-150k | 34.2 kts | — |
| 150-200k | 36.2 kts | — |

**Status:** Sustained TS intensity with slow intensification trend. H1 (64 kts) not yet reached — pending resolution of organized convection structure.

### Quiescent Vortex Test (V7.0 Benchmark)

**Setup:** Isolated vortex, no environmental wind, 48-hour simulation

| Configuration | Drift Distance | Drift Speed | Direction |
|---------------|----------------|-------------|-----------|
| f-plane | 0 km | 0 m/s | N/A |
| β-plane (V7.0) | 243 km | 1.41 m/s | Northwest |
| Observed (typical) | ~200-300 km | 1-2 m/s | Northwest |

✅ **Result:** Beta drift emerges naturally without heuristic injection.

### Betts-Miller Column Verification (V7.0)

**Setup:** Single-column τ sweep comparing instantaneous saturation vs BM adjustment

| Metric | Instant Saturation | Betts-Miller (τ=900s) |
|--------|-------------------|----------------------|
| Precipitation | ~1× baseline | ~6× baseline |
| Heating Variance | Boom-bust oscillation | Near-zero variance |
| BL Moisture | Crashes to <1 g/kg | Holds at 19-24 g/kg |
| Stability | Gravity wave noise | Smooth adjustment |

---

## 🧬 Technical Deep Dive

### The Spectral Short-Circuit (V7.0 → V7.1)

**Issue:** The pseudo-spectral solver treats the domain as triply-periodic. While horizontal periodicity is physically reasonable (large domain), vertical periodicity creates an unphysical pathway: dry stratospheric air at z_top wraps to z_bottom via the highest vertical Fourier modes, draining boundary layer moisture in ~hours.

**Diagnosis (Gemini Deep Research):** The vertical spectral modes create a "short-circuit" — an O(1) wavenumber connection between the upper and lower boundaries. Standard padding and de-aliasing cannot prevent this because it's a feature of the periodic basis, not an aliasing artifact.

**Fix:** Three-layer defense:
1. **Z-Clamp** — `mode='nearest'` in vertical advection extrapolation prevents spectral wrap at boundaries
2. **Vertical Sponge** — Rayleigh damping coefficient increases in top 20% of domain, absorbing upward-propagating disturbances before they wrap
3. **Far-Field Relaxation** — Moisture nudged toward climatological values at r > 400-600 km with τ = 12 hours

### The Moisture Starvation Lineage (V6 → V7.1)

The single most persistent bug family across Oracle's history:

| Version | Symptom | Root Cause | Fix |
|---------|---------|------------|-----|
| V6.x | q_sfc → 0 in hours | Instantaneous saturation dries BL | Betts-Miller (V7.0) |
| V7.0 | q_sfc → 0.8 g/kg | Z-periodic spectral wrap | Z-clamp + sponge (V7.1) |
| V7.0 | q_sfc at 2× saturation | No moisture removal mechanism | Warm rain cap (V7.1) |
| V7.1 | θ′ → 50K runaway | No precipitation heat sink | Precip efficiency (V7.1) |

Each fix revealed the next physics gap — a natural consequence of building a simulation from first principles rather than top-down parameter fitting.

### The Phantom Mass Problem (V5 → V6)

**Issue:** Boussinesq incompressibility (∇·**u** = 0) forbids volume expansion, but explicit adiabatic cooling formula assumed parcels *could* expand:

```python
# V5.x BAD CODE
T_new = T_old - adiabatic_rate * w * dt  # Assumes expansion!
```

This created artificially dense air in updrafts → pressure solver saw "phantom mass" → killed convection.

**Solution:** Potential temperature θ conserves *naturally* in adiabatic motion:

```python
# V6.0 CORRECT CODE  
# Stratification term replaces explicit cooling
dtheta_dt = -w * dtheta0_dz  # Implicit adiabatic effect
```

### The Beta Drift Heuristic Problem (V6 → V7)

**Issue:** f-plane cannot generate vorticity asymmetry. Required manual calculation (~200 lines of tuned heuristics with basin-specific damping, latitude scaling, and intensity corrections).

**Solution:** β-plane vorticity dynamics (~4 lines):

```python
# V7.0 PHYSICS CODE
if beta_plane_enabled:
    f_nd = beta_plane.get_f_nd_3d(nz)  # f(y) varies with latitude
else:
    f_nd = f0 * T_CHAR  # Legacy constant f
```

Beta gyres emerge → vortex self-advects → drift is *consequence*, not *input*.

---

## 📚 Theoretical Foundation

### Key References

1. **Emanuel, K. A. (1994).** *Atmospheric Convection.* Oxford University Press.
   - MPI theory, WISHE mechanism, convective adjustment

2. **Betts, A. K. & Miller, M. J. (1986).** "A new convective adjustment scheme." *QJRMS.*
   - Relaxed convective adjustment theory and timescale derivation

3. **Holland, G. J. (1997).** "The Maximum Potential Intensity of Tropical Cyclones." *J. Atmos. Sci.*
   - Precipitation efficiency estimates (20-30% net column warming)

4. **Nolan, D. S. & Grasso, L. D. (2003).** "Nonhydrostatic, Three-Dimensional Perturbations to Balanced, Hurricane-like Vortices." *J. Atmos. Sci.*
   - Latent heat partitioning in TC warm cores

5. **Markowski & Richardson (2010).** *Mesoscale Meteorology in Midlatitudes.* Wiley.
   - Boussinesq dynamics, potential temperature framework

6. **Peng, M. S., et al. (1999).** "Simulations of Tropical Cyclone Movement Using a Barotropic Model." *Monthly Weather Review.*
   - Beta-plane TC dynamics, three-stage evolution

7. **Bryan, G. H.** *CM1 Model Documentation.* NCAR.
   - Numerical methods for cloud-resolving models

### Governing Equations

**Momentum (Boussinesq):**
```
∂u/∂t + u·∇u = -∇p'/ρ₀ - f(y)×u + g(θ′/θ₀)ẑ + ∇·τ
∇·u = 0
```

**Potential Temperature:**
```
∂θ′/∂t + u·∇θ′ = -w·dθ₀/dz + η·(Lv/Cp)·(θ/T)·C + ∇·(K∇θ′) + F_surface - θ′/τ_rad
```

**Moisture:**
```
∂q/∂t + u·∇q = -(q - q_ref)/τ_BM · W(z) + ∇·(K∇q) + E_surface - WR
```

Where:
- f = f₀ + β·Δy on β-plane (V7.0)
- C = condensation rate (Betts-Miller relaxation)
- η = precipitation efficiency (fraction of latent heat retained)
- W(z) = vertical taper weight (0 at surface → 1 above BL)
- τ_BM = Betts-Miller relaxation timescale (~900s)
- τ_rad = radiative cooling timescale (dynamic: 24h → 2h)
- WR = warm rain removal (excess above cap × q_sat)

---

## 🎨 Project Structure

```
oracle-tc-sim/
├── world_woe_main_V7_beta_plane.py    # Main simulation driver (V7.0+)
├── world_woe_main_V6_THETA.py         # Thermodynamic engine (V6-V7.1)
├── beta_plane.py                       # Beta-plane dynamics module
├── boundary_conditions.py              # Surface fluxes, drag, landfall physics
├── core_solver.py                      # Pressure projection solver
├── reference_state.py                  # θ₀(z) atmospheric profile
├── storm_tracker.py                    # Vorticity-based center detection
├── era5_interface.py                   # ERA5 data ingestion (CDS API)
├── visualizer.py                       # Plotting and analysis tools
├── docs/
│   ├── architectural_renovation.pdf    # Technical design document
│   ├── v7_integration_guide.md         # Beta-plane integration notes
│   └── cli_cheatsheet.md              # Quick reference for all flags
├── tests/
│   ├── test_beta_plane.py              # Quiescent vortex validation
│   ├── test_betts_miller_column.py     # Single-column BM verification
│   └── test_theta_thermodynamics.py    # θ′ framework tests
└── requirements.txt                    # Python dependencies
```

---

## 🤖 Development Methodology

Oracle is developed through a **multi-AI ensemble** — a collaborative approach where specialized AI models contribute domain expertise under human scientific direction.

### Ensemble Roles

| Model | Primary Contributions |
|-------|----------------------|
| **Gemini Deep Research** (Google DeepMind) | Boussinesq-θ analysis, spectral short-circuit diagnosis, beta-plane vorticity theory, three-layer vertical boundary fix |
| **Five** (OpenAI GPT-5) | Ensemble debugging, thermodynamic stability analysis, BL exclusion gate design, flux depth parameterization |
| **Claude Opus** (Anthropic) | Code implementation, integration architecture, diagnostic infrastructure, systematic parameter sweeps |
| **Justin** (Human) | Scientific direction, experimental design, validation campaigns, multi-model orchestration |

### Development Philosophy

The ensemble operates on a principle of **adversarial collaboration**: models propose competing hypotheses for observed bugs, then controlled experiments determine which diagnosis is correct. This has proven remarkably effective — the spectral short-circuit bug, for example, was identified by Gemini's deep literature review after Claude and Five had narrowed the symptom space through 12+ diagnostic runs.

### Timeline

| Date | Milestone |
|------|-----------|
| August 2025 | Project inception |
| January 2026 | V6.0 THETA — Potential temperature rewrite |
| January 2026 | V6.3-V6.26 — WISHE, landfall physics, GPU acceleration |
| February 2026 | V7.0 — Beta-plane dynamics + Betts-Miller convection |
| February 2026 | V7.1 — Spectral short-circuit fix, first sustained TS |
| February 2026 | V7.1 — Precipitation efficiency, warm rain (active) |

---

## 🗺️ Roadmap

### V7.2 — Organized Convection (Current Focus)

**Goal:** Transition from diffuse BM condensation to focused eyewall updrafts

Current state: BM fires in ~220,000 cells simultaneously (entire domain saturated). Need vertical moisture gradient restoration to concentrate convection into organized structures. The warm rain soft cap is the active mechanism being tuned to achieve this.

**Success Criteria:**
- Focused convective cores (< 10,000 BM cells active)
- Measurable pressure minimum (Pmin < -2 hPa)
- Sustained H1 intensity (64+ kts)

### V8.0 — Spectral Nudging (Q2-Q3 2026)

**Goal:** Eliminate ERA5 steering heuristics

Replace domain-mean steering with scale-selective nudging:
- Large scales (λ > 1000 km): Constrained to ERA5
- Small scales (λ < 500 km): Free evolution (TC vortex)
- Vertical masking: Protect boundary layer

**Impact:** Accurate environmental steering without vortex contamination, natural shear-TC interaction.

### V9.0 — Higher Resolution / Explicit Convection (Future)

**Goal:** Resolve individual updrafts (Δx < 4 km)

Turn off parameterizations, let physics emerge:
- Direct numerical simulation of eyewall convection
- Eyewall replacement cycles from first principles
- Spiral rainband genesis

---

## 📖 Documentation

### Key Documents

- **[Architectural Renovation Paper](docs/architectural_renovation.pdf)** — Technical analysis of the Core Tension and renovation roadmap
- **[V7 Integration Guide](docs/v7_integration_guide.md)** — Beta-plane implementation notes
- **[CLI Cheatsheet](docs/cli_cheatsheet.md)** — Quick reference for all 80+ flags
- **[Validation Report](docs/validation_report.md)** — Historical storm benchmarks

### Related Publications

*Manuscript in preparation documenting both Oracle's computational framework and the multi-AI ensemble methodology that created it.*

---

## 🤝 Contributing

This is currently a research project in active development. Contributions are welcome in the form of:

- **Bug reports** — Especially numerical instabilities or unphysical behavior
- **Validation cases** — Historical storm simulations with known tracks
- **Physics improvements** — Suggestions backed by literature references
- **Documentation** — Clarifications, tutorials, worked examples

Please open an issue or pull request on GitHub.

---

## 📝 License

This project is released under a **Research License** — free for academic and educational use. Commercial applications require explicit permission.

---

## 🌟 Why "Oracle"?

The name reflects the project's philosophy:

> "An oracle doesn't predict the future by looking at tea leaves (heuristics).  
> It reveals what *must* happen given the laws that govern reality (physics)."

Every heuristic in Oracle is a *temporary* oracle — a placeholder until we implement the actual physics. The goal is zero heuristics: a simulation where tropical cyclones emerge purely from conservation laws.

---

## 📬 Contact

**Project Lead:** Justin  
**Email:** Justin.G.Watford@gmail.com  
**GitHub:** https://github.com/justingwatford-dev/Oracle

---

## 🙏 Acknowledgments

Special thanks to:
- The atmospheric science community for open research and CM1 model inspiration
- ECMWF for ERA5 reanalysis data
- Anthropic, OpenAI, and Google DeepMind for AI research assistance tools
- NCAR for mesoscale modeling resources

---

*"From heuristics to physics, one equation at a time."* 

---

**Last Updated:** February 9, 2026  
**Version:** 7.1 WARM-RAIN  
**Status:** Active Development — Thermodynamic cycle tuning
