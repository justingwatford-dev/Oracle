# Oracle V7.0 CLI Cheat Sheet

## Quick Reference: Common Run Configurations

```bash
# V7 β-plane baseline (recommended starting point)
python world_woe_main_V7_BETA_PLANE.py --beta-plane --storm HUGO --frames 300000

# V7 β-plane + relaxed governors (test if governors are bottleneck)
python world_woe_main_V7_BETA_PLANE.py --beta-plane --storm HUGO --frames 50000 \
  --no-flux-governor --buoyancy-cap 1.5

# V7 β-plane + full thermodynamic package
python world_woe_main_V7_BETA_PLANE.py --beta-plane --storm HUGO --frames 300000 \
  --wishe-boost --radiative-cooling --mean-removal

# V7 β-plane + governors OFF (full send)
python world_woe_main_V7_BETA_PLANE.py --beta-plane --storm HUGO --frames 50000 \
  --no-flux-governor --no-thermo-firewalls --no-wisdom --no-velocity-governor

# Legacy f-plane (V6 behavior, for comparison)
python world_woe_main_V7_BETA_PLANE.py --storm HUGO --frames 300000 --beta-drift

# Full unconstrained (everything off — expect fireworks)
python world_woe_main_V7_BETA_PLANE.py --beta-plane --storm HUGO --frames 50000 \
  --fully-unconstrained
```

---

## Storm Selection

| Flag | Default | Description |
|------|---------|-------------|
| `--storm NAME` | HUGO | Storm name from HURDAT2 |
| `--year YYYY` | 1989 | Storm year |
| `--frames N` | 100000 | Total simulation frames |

**Validated storms:** HUGO (1989), ANDREW (1992), KATRINA (2005), HARVEY (2017)

**Time conversion:** ~3600 frames ≈ 2.4 sim hours (at dt=3e-5, T_CHAR=80000s)
- 50,000 frames ≈ 33 hours
- 150,000 frames ≈ 100 hours (~4 days)
- 300,000 frames ≈ 200 hours (~8 days)

---

## V7.0: Beta-Plane Dynamics

| Flag | Default | Description |
|------|---------|-------------|
| `--beta-plane` | OFF | **V7.0** Spatially-varying f(y). Emergent beta drift. Auto-disables synthetic beta drift |

**When active:** Replaces ~200 lines of synthetic drift heuristics with one physical term.
Beta gyres produce NW self-advection at 1-3 m/s naturally.

---

## Governor Stack (Safety Limiters)

All governors are ON by default. Disable individually or all at once.

| Flag | What It Controls | Risk If Disabled |
|------|-----------------|------------------|
| `--no-flux-governor` | Surface flux throttle ramp | Runaway moisture injection |
| `--no-wisdom` | WISDOM dampening factor | Overshoot in pressure/wind |
| `--no-velocity-governor` | CoreSolver velocity damping | Supersonic winds |
| `--no-thermo-firewalls` | Buoyancy cap + temp limits | Thermal runaway |
| `--fully-unconstrained` | **ALL of the above at once** | 💥 Numerical explosion likely |

### Tuning (instead of disabling)

| Flag | Default | Range | Description |
|------|---------|-------|-------------|
| `--buoyancy-cap` | **0.5** m/s² | 0.5–2.0 | Soft clamp via tanh. Higher = more buoyancy allowed |
| `--max-updraft` | **50.0** m/s | 30–100 | Max vertical velocity (firewalls only) |
| `--max-temp-anomaly` | **15.0** K | 10–30 | Max temperature anomaly |
| `--theta-prime-max` | **50** K | 50–100 | Upper θ′ sanity bound |
| `--theta-prime-min` | **-50** K | -100–-50 | Lower θ′ sanity bound |

**Recommended relaxation order:**
1. Raise `--buoyancy-cap 1.5` (safest)
2. `--no-flux-governor` (moderate risk)
3. `--no-thermo-firewalls` (high risk)
4. `--no-wisdom` + `--no-velocity-governor` (expect instability)

---

## Thermodynamic Engine

### WISHE Feedback (Wind-Induced Surface Heat Exchange)

| Flag | Default | Description |
|------|---------|-------------|
| `--wishe-boost` | OFF | Enable Ck/Cd boost with wind speed |
| `--wishe-boost-max` | **1.4** | Maximum boost factor |
| `--wishe-wind-min` | **15.0** m/s | Wind speed where boost begins |
| `--wishe-wind-max` | **40.0** m/s | Wind speed where boost maxes out |

**Note:** WISHE only helps if storm is already >15 m/s (~30 kts). Useless for weak storms.

### Radiative Cooling (Newtonian Relaxation)

| Flag | Default | Description |
|------|---------|-------------|
| `--radiative-cooling` | OFF | Enable θ′ relaxation toward zero |
| `--tau-rad` | **86400** s (24h) | Relaxation timescale |
| `--dynamic-cooling` | OFF | Scale τ with θ′ magnitude |
| `--tau-rad-min` | **3600** s (1h) | Minimum τ for dynamic mode |
| `--theta-scale` | **20.0** K | θ′ scale for dynamic τ |

**⚠️ Warning:** At τ=24h, this removes ~4% of θ′ per hour.
On a starving storm (~15 kts), this drains the warm core faster than latent heat replenishes it.

### Mean Removal

| Flag | Default | Description |
|------|---------|-------------|
| `--mean-removal` | OFF | Remove horizontal-mean θ′ at each level |

**Purpose:** Prevents domain-wide θ′ drift. Additional energy sink.

### Environment Relaxation

| Flag | Default | Description |
|------|---------|-------------|
| `--environment-relax` | OFF | Relax θ′ to zero outside storm radius |
| `--relax-radius` | **300** km | Radius beyond which relaxation applies |
| `--relax-tau` | **3600** s (1h) | Relaxation timescale |

### Cold Anomaly Diffusion

| Flag | Default | Description |
|------|---------|-------------|
| `--cold-diffusion` | OFF | Selectively diffuse cold anomalies (θ′ < -4K) |
| `--cold-diffusion-strength` | **0.05** | Diffusion coefficient |

---

## Steering & Track

### ERA5 / DLM Steering

| Flag | Default | Description |
|------|---------|-------------|
| `--steering-multiplier` | **1.0** | Scale ERA5 steering winds |
| `--dlm-scale` | **1.0** | DLM weighting factor (was 0.55 in old versions) |
| `--dlm-inner-radius` | **300** km | Inner radius for DLM doughnut filter |
| `--steering-floor` | **3.0** m/s | Minimum steering speed |
| `--no-steering-floor` | OFF | Disable minimum steering speed |
| `--steering-injection` | OFF | V6.16 "Treadmill" pressure injection |

### Annular Steering

| Flag | Default | Description |
|------|---------|-------------|
| `--annular-steering` | OFF | Sample steering from annulus (exclude vortex) |
| `--annular-inner-km` | **200** km | Inner annulus radius |
| `--annular-outer-km` | **600** km | Outer annulus radius |

### Synthetic Beta Drift (Legacy — V6)

*Auto-disabled when `--beta-plane` is active*

| Flag | Default | Description |
|------|---------|-------------|
| `--beta-drift` | OFF | Inject synthetic NW drift vector |
| `--beta-drift-speed` | **2.5** m/s | Base drift speed at 15°N |
| `--beta-drift-lat-scale` | **0.05** | +5% per degree latitude |
| `--no-intensity-scaling` | OFF | Disable Fiorino-Elsberry scaling |
| `--no-longitude-scaling` | OFF | Disable west-of-80°W scaling |
| `--no-basin-damping` | OFF | Disable Gulf/Caribbean damping |
| `--no-confidence-weighting` | OFF | Disable ERA5 confidence weighting |
| `--steer-ref` | **6.0** m/s | Reference speed for confidence weighting |
| `--no-h3-boost` | OFF | Disable H3+ hysteresis mode |

---

## Atmosphere Initialization

| Flag | Default | Description |
|------|---------|-------------|
| `--theta-surface` | **300.0** K | Surface potential temperature |
| `--gamma-theta` | **4.0** K/km | θ lapse rate |
| `--scale-height` | **8500** m | Humidity scale height |
| `--warm-core-theta-prime` | **5.0** K | Initial warm core anomaly |
| `--base-humidity` | **0.018** kg/kg | Surface specific humidity |
| `--core-rh-init` | **0.95** | Core relative humidity at genesis |
| `--moisture-floor` | **0.0001** g/kg | Absolute minimum specific humidity |

---

## Numerics & Stability

| Flag | Default | Description |
|------|---------|-------------|
| `--resolution` | **128** | Grid: 128³ default |
| `--advection-order` | **3** | Advection scheme order |
| `--sponge-strength` | **0.003** | Edge sponge damping |
| `--smagorinsky-cs` | **0.17** | Smagorinsky turbulence coefficient |
| `--resolution-boost` | **1500** | Turbulence resolution parameter |
| `--moist-floor` | **0.3** | Minimum moist factor in updrafts |
| `--monotonic-advection` | OFF | Quasi-monotonic limiter (anti-Gibbs) |
| `--flux-throttle` | OFF | Runaway flux prevention |
| `--flux-throttle-threshold` | **5.0** | Flux throttle trigger level |
| `--proportional-throttle` | OFF | V6.7 proportional balance fix |
| `--theta-prime-soft-limit` | **60.0** K | Proportional throttle soft limit |
| `--theta-prime-hard-limit` | **100.0** K | Proportional throttle hard limit |

---

## Visualization

| Flag | Default | Description |
|------|---------|-------------|
| `--track-plot` | OFF | Generate track plot at end |
| `--wind-plots` | OFF | Wind field snapshots during sim |
| `--all-plots` | OFF | Enable all plotting |
| `--plot-interval` | **7200** | Frames between plot saves |

---

## Diagnostic Flags (Read the Logs)

**Key log patterns to grep for:**

```bash
# Intensity timeline
grep "Frame.*Max Wind" oracle_v6_*.log

# Position tracking
grep "POSITION" oracle_v6_*.log

# Governor activity
grep "BUOYANCY.*clamp\|MOISTURE FLOOR\|GOVERNOR" oracle_v6_*.log

# Moisture health
grep "WISHE FUEL" oracle_v6_*.log

# ERA5 steering
grep "WEIGHTED DLM\|ERA5 DIAG" oracle_v6_*.log

# Beta-plane status
grep "β-plane" oracle_v6_*.log

# Stage transitions
grep "STAGE TRANSITION" oracle_v6_*.log

# Thermal energy budget
grep "RADIATIVE COOL\|MEAN REMOVAL\|WISHE BOOST" oracle_v6_*.log
```

---

## Decision Tree: "What Should I Try?"

```
Storm too weak / not intensifying?
├── Check q_sfc in logs → Below 2 g/kg? → MOISTURE STARVATION
│   ├── Root cause: instantaneous saturation (needs Betts-Miller)
│   ├── Band-aid: --buoyancy-cap 1.5 (let burst be stronger)
│   └── Band-aid: --no-flux-governor (let more moisture in)
│
├── Check BUOYANCY clamp% → Above 30%? → GOVERNORS TOO AGGRESSIVE
│   ├── --buoyancy-cap 1.5 (first try)
│   ├── --no-thermo-firewalls (aggressive)
│   └── --no-flux-governor (let surface fluxes work)
│
├── Check RADIATIVE COOLING total → Growing fast? → ENERGY DRAIN
│   └── Don't use --radiative-cooling until storm sustains >40 kts
│
└── Check θ′_max → Below 5K? → WARM CORE COLLAPSED
    └── Increase --warm-core-theta-prime 8.0 or relax governors

Storm too strong / blowing up?
├── Enable governors: remove any --no-* flags
├── Lower --buoyancy-cap 0.3
├── Enable --radiative-cooling --tau-rad 43200
└── Enable --proportional-throttle

Track too far west?
├── β-plane active? Good — provides natural NW component
├── Check DLM diagnostics → u too negative? → upper trough missing
│   └── Verify 200 hPa weight in adaptive DLM
└── Legacy: --beta-drift --beta-drift-speed 2.0

Track not recurving?
├── Check ERA5 v-component → should go positive >25°N
├── Legacy: RECURVE-B assist is still active
└── Future: spectral nudging (Pillar 2) replaces both
```