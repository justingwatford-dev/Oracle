# ORACLE — Hurricane Simulation System

ORACLE (Ocean–atmosphere Response and Cyclone Lifecycle Emulator) is a research-grade numerical hurricane simulation framework focused on physically consistent storm structure, intensity evolution, and track dynamics. The system prioritizes diagnostic transparency and physically motivated corrections over empirical tuning.

ORACLE is **not** an operational forecast model. It is designed for controlled experimentation, historical case study reproduction, and investigation of failure modes in tropical cyclone dynamics.

---

## Design Philosophy

ORACLE is built around three guiding principles:

1. **Physical consistency over parameter tuning** — model behavior is corrected by identifying and fixing structural causes, not by compensating coefficients.
2. **Diagnostics drive architecture** — unexpected behavior is treated as a signal pointing to missing or misrepresented physics.
3. **Research transparency** — mechanisms, assumptions, and limitations are explicit and inspectable.

The model includes multiple stability and realism safeguards ("governors") that may be disabled for experimentation, but all default configurations favor numerical and physical robustness.

---

## Core Capabilities

* **Three-dimensional dynamical core** with potential temperature–based thermodynamics
* **GPU acceleration** via CuPy with automatic NumPy fallback
* **ERA5 reanalysis integration** for environmental steering and land–sea masking
* **Adaptive Mesh Refinement (AMR)** for resolving inner-core structure
* **Data assimilation** using grid-based Kalman filtering
* **Storm-centric diagnostics** for intensity, structure, and track accuracy

---

## Thermodynamic Framework (V6.0 THETA)

Beginning in Version 6.0, ORACLE prognoses **potential temperature perturbation (θ′)** rather than absolute temperature. The total potential temperature field is decomposed as:

```
θ(x,y,z,t) = θ₀(z) + θ′(x,y,z,t)
```

Where θ₀(z) is a fixed, stably stratified reference profile and θ′ represents dynamically evolving departures.

This formulation:

* Captures adiabatic cooling implicitly
* Produces natural buoyancy limits without artificial clamps
* Enables periodic boundary conditions without thermodynamic drift
* Separates background stratification from storm-induced structure

Buoyancy is computed directly as:

```
b = g · θ′ / θ₀(z)
```

---

## Numerical and Physical Components

### Dynamical Core

* FFT-based pressure projection for incompressibility
* Semi-Lagrangian advection with optional quasi-monotonic limiting
* Smagorinsky subgrid-scale turbulence
* Explicit vorticity and divergence diagnostics

### Surface and Boundary Physics

* Bulk aerodynamic surface fluxes
* Wind-dependent drag coefficients
* Land–sea blending for coastal interaction
* Wind-Induced Surface Heat Exchange (WISHE)

### Adaptive Mesh Refinement

* Multi-level refinement based on vorticity and pressure signals
* Inner-core–focused resolution enhancement
* Hard caps to prevent runaway refinement

---

## Environmental Data Integration

ORACLE incorporates ERA5 reanalysis data to represent large-scale environmental steering and geographic context.

Key features include:

* Pressure-level wind retrieval
* Deep-layer mean (DLM) steering computation
* Annular sampling to exclude the storm core
* Automatic fallback on data fetch failure

ERA5 data are treated as environmental guidance rather than absolute truth, particularly for intense storms where reanalysis resolution may underestimate inner-core structure.

---

## Track and Intensity Diagnostics

Storm position, motion, and intensity are monitored using a multi-field tracking system that evaluates:

* Vorticity coherence
* Pressure minima
* Warm-core structure
* Vertical shear alignment

Storm motion arises from the combined effects of environmental steering and internal dynamics (e.g., beta drift), with configurable weighting between the two.

---

## Version History (Selected)

### V6.23 — Deep-Layer Mean Steering Correction (February 2026)

Corrects a structural steering bias affecting intense hurricanes by aligning kinematic depth with thermodynamic depth.

Key changes:

* Deep-layer steering integration expanded to **200–850 hPa**
* Removal of artificial ERA5 steering attenuation
* Increased exclusion radius to prevent vortex contamination
* Intensity-aware beta drift behavior for major hurricanes

Impact:

* Elimination of unrealistic looping behavior
* Improved recurvature timing
* Reduced landfall track error for Category 4–5 storms

---

### V6.0 THETA (January 2026)

* Thermodynamic reformulation using potential temperature perturbation
* Replacement of explicit adiabatic cooling with stratification coupling
* Physically grounded buoyancy formulation

---

## Installation

### Dependencies

```bash
pip install numpy scipy cupy-cuda11x
pip install xarray pandas netCDF4 cdsapi
pip install matplotlib geojson hurdat-parser
```

### ERA5 Access

ERA5 data access requires a Copernicus Climate Data Store (CDS) account and API key:

```bash
# ~/.cdsapirc
url: https://cds.climate.copernicus.eu/api/v2
key: <your-api-key>
```

---

## Usage

### Basic Example

```bash
python world_woe_main_V6_THETA.py \
  --storm HUGO --year 1989 --frames 50000
```

### Advanced Configuration

```bash
python world_woe_main_V6_THETA.py \
  --storm KATRINA --year 2005 \
  --steering-injection \
  --annular-steering \
  --radiative-cooling \
  --proportional-throttle
```

### Unconstrained Physics Mode

```bash
python world_woe_main_V6_THETA.py --fully-unconstrained
```

Use unconstrained configurations cautiously; numerical instability and unphysical intensities are possible.

---

## Outputs

Simulation artifacts are written to `world_woe_v6_theta_plots/`:

* Track plots with intensity coloring
* Surface wind field snapshots
* GeoJSON storm tracks for GIS analysis
* Detailed runtime logs

---

## Limitations and Scope

* Not suitable for operational forecasting
* Resolution limited by GPU memory and AMR caps
* Environmental reanalysis may underrepresent extreme intensity

Results should be interpreted as **physical experiments**, not predictions.

---

## Contributors

* Five — Architecture and diagnostic analysis
* Gemini — Thermodynamic and steering diagnostics
* Claude — Primary implementation
* Justin — Testing and validation

---

## License and Disclaimer

This project is provided for research and educational use. Outputs must not be used for emergency management or real-time decision-making. Cite appropriately when used in academic or technical work.
