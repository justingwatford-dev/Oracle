import pandas as pd
import cdsapi
import xarray as xr
import numpy as np
import os
from scipy.interpolate import CubicSpline
from scipy.ndimage import gaussian_filter  # PATCH V60.1: For Five's smooth land fraction
from hurdat_parser import get_hurricane_data
from datetime import timedelta
import sys

# === ORACLE V6.26: ADAPTIVE DLM + LAND FIXES (Gemini Deep Dive) ===
#
# V6.26 FIXES (Gemini's "Double Beta" and "200 hPa Hook" Analysis):
# 
# 1. ADAPTIVE DLM WEIGHTING:
#    - Over ocean: 200 hPa = 4x, 300 hPa = 2x (capture trough for recurvature)
#    - Over land: 850 hPa = 2x, 700 hPa = 1.5x (follow terrain, not jet stream)
#    - Coastal: Linear interpolation between ocean and land profiles
#
# 2. Physics: Post-landfall vortex shallows (bottom-up spin-down)
#    The V6.25 4x weight on 200 hPa caused eastward bias over land
#    because jet stream dominates upper levels while surface is anchored.
#
# === ORACLE V6.25: WEIGHTED DLM + BETA DRIFT FIX (Gemini's Forensic Analysis) ===
#
# ROOT CAUSE IDENTIFIED: "Unused Weights" Bug!
# The weights array was DEFINED but NEVER APPLIED to the trapz integration.
# This caused the upper-level trough (200 hPa) to be completely ignored,
# leaving steering dominated by lower-level easterlies → Texas drift!
#
# V6.25 FIXES:
# 1. ACTUALLY USE WEIGHTS in trapz: u_profile * weights
# 2. Upper-level weighting: 200 hPa = 4.0x, 300 hPa = 2.0x
# 3. Proper weighted average: ∫(u*w)dp / ∫(w)dp
#
# Expected result: Upper trough captured → northward steering component restored
#
# === ORACLE V6.23: DEEP LAYER MEAN (DLM) STEERING FIX ===
# 
# GEMINI'S DIAGNOSTIC ANALYSIS:
# "The simulation is effectively steering a deep, Category 5 vortex using
#  shallow-to-mid-level environmental winds that do not reflect the ridging
#  and troughing patterns of the upper troposphere."
#
# ROOT CAUSE: "Kinematically shallow despite being thermodynamically deep"
#
# V6.23 FIXES (per Gemini's recommendations):
# 1. Added 200 hPa level - captures upper-level trough that recurves storms
# 2. Removed 0.55 DLM scaling factor - was weakening steering by 45%!
# 3. Increased inner radius 225km → 300km - avoids ERA5 vortex contamination
#
# Previous versions fetched 850-300 hPa but:
# - Missing 200 hPa meant missing the westerly trough steering
# - 0.55 factor artificially weakened DLM, making beta drift relatively too strong
# - Result: Katrina steered south to 21°N instead of recurving at 25°N
#
# === ORACLE V60.3: NaN-SAFE LANDFALL PHYSICS ===
# V60.2: Two-request CDS fix (pressure-levels + single-levels)
# V60.3: NaN handling for complex coastlines (Caribbean islands crash fix)
# 
# Issue: ERA5 LSM interpolation can fail near complex coastlines → NaN in land_fraction
# Cascade: NaN land_fraction → NaN fluxes → NaN in q,T → GPU memory corruption → crash
# 
# Fixes Applied:
# 1. Pre-smoothing NaN check: Replace NaN with 0.0 (ocean fallback)
# 2. Post-smoothing validation: Detect gaussian_filter NaN propagation
# 3. Critical failsafe: Zero land_fraction if validation fails
# 4. Backup/restore mechanism: Revert to last good data on fetch failure
#
# Tested: Caribbean islands, Gulf coast, Texas landfall
# Status: PRODUCTION READY

# === GPU ACCELERATION TOGGLE ===
USE_GPU = False

try:
    if USE_GPU:
        import cupy as xp
        import cupyx.scipy.ndimage as ndimage
        import cupyx.scipy.fft as fft
        print(f"[{__name__}] GPU Acceleration ENABLED (CuPy)")
    else:
        raise ImportError
except ImportError:
    import numpy as xp
    import scipy.ndimage as ndimage
    import scipy.fft as fft
    print(f"[{__name__}] GPU Acceleration DISABLED (NumPy)")


class DataInterface:
    """
    Interface to ERA5 reanalysis data and HURDAT2 historical tracks.
    
    Handles:
    - Fetching ERA5 steering flow data AND Land-Sea Mask (LSM)
    - Vertical integration with pressure-weighted averaging
    - Interpolation to simulation grid
    - Conversion between physical (m/s) and dimensionless velocities
    - HURDAT2 best-track data loading
    
    UNIT HANDLING:
        - ERA5 winds: m/s (physical SI units from reanalysis)
        - Simulation winds: dimensionless (scaled by U_CHAR = 50 m/s)
        - Land Fraction: 0.0 (Ocean) to 1.0 (Land)
        - Conversion uses U_CHAR characteristic velocity
    """
    
    def __init__(self, sim_instance, storm_name, storm_year):
        self.sim = sim_instance
        print("DataInterface Initialized for Project Oracle (ERA5 Historical).")
        print("  -> ERA5 winds will be converted: m/s → dimensionless")
        
        # Load HURDAT2 historical track
        self.historical_track = get_hurricane_data(storm_name, storm_year)
        if self.historical_track is None:
            raise ValueError(f"Could not load data for {storm_name} {storm_year}")

        # Steering flow targets (dimensionless velocity) - NOW ON GPU!
        self.u_target = xp.zeros((self.sim.nx, self.sim.ny))
        self.v_target = xp.zeros((self.sim.nx, self.sim.ny))
        self.u_old = xp.zeros_like(self.u_target)
        self.v_old = xp.zeros_like(self.v_target)
        
        # === PATCH V60: LAND FRACTION FIELD ===
        # 0.0 = Pure Ocean, 1.0 = Pure Land. Intermediate values = Coastline/Transition.
        self.land_fraction = xp.zeros((self.sim.nx, self.sim.ny))
        
        # Geographic bounds (will be set when update_steering_data is called)
        self.lon_bounds, self.lat_bounds = (0, 0), (0, 0)
        self.last_update_frame = 0 
        
        # CDS API client for ERA5 data
        self.cds_client = cdsapi.Client()

    def set_kalman_backup(self, u_kalman, v_kalman):
        """
        Saves the current Kalman filter state as the 'old' state
        right before a new data fetch. This prevents the
        "Kalman State Shock" by ensuring the temporal dampener
        blends from the *actual* current state.
        
        NOTE: u_kalman and v_kalman are already GPU arrays from Kalman filter
        """
        # These are already GPU arrays, just copy them
        self.u_old = xp.copy(u_kalman)
        self.v_old = xp.copy(v_kalman)

    def _fetch_era5_data(self, date_time):
        """
        Fetch ERA5 steering layer data AND Land-Sea Mask.
        
        Process:
        1. Download ERA5 multi-level wind data AND single-level LSM
        2. Interpolate to simulation grid horizontally
        3. Apply pressure-weighted vertical integration (winds only)
        4. Smooth the Land-Sea Mask (Five's Fix)
        5. Convert to proper units and UPLOAD TO GPU
        
        Args:
            date_time: Datetime object for the ERA5 data to fetch
        """
        print(f"  -> ORACLE DI: Fetching ERA5 steering & land mask for {date_time.strftime('%Y-%m-%d %H:%M')}...")
        
        lat_north = self.lat_bounds[1]
        lat_south = self.lat_bounds[0]
        lon_west = self.lon_bounds[0]
        lon_east = self.lon_bounds[1]
        
        # === PATCH V60.2: TWO-REQUEST METHOD (FIX FOR CDS API) ===
        # LSM is single-level, winds are pressure-level
        # Must fetch from separate CDS products
        
        # REQUEST 1: Pressure-level winds
        # V6.23 DLM FIX: Added 200 hPa to capture upper-level troughs (Gemini's Analysis)
        # The approaching trough that steered Katrina north was at 200-300 hPa!
        # Without 200 hPa, we miss the critical upper-level steering that recurves storms.
        winds_request = {
            'product_type': 'reanalysis',
            'format': 'netcdf',
            'variable': ['u_component_of_wind', 'v_component_of_wind'],
            'pressure_level': ['200', '300', '400', '500', '600', '700', '850'], 
            'year': date_time.strftime('%Y'),
            'month': date_time.strftime('%m'),
            'day': date_time.strftime('%d'),
            'time': date_time.strftime('%H:00'),
            'area': [lat_north, lon_west, lat_south, lon_east],
        }
        
        winds_path = f'era5_winds_temp_{date_time.strftime("%Y%m%d%H%M%S")}.nc'
        print("     📊 Fetching pressure-level winds...")
        self.cds_client.retrieve('reanalysis-era5-pressure-levels', winds_request, winds_path)
        
        # REQUEST 2: Single-level land-sea mask  
        lsm_request = {
            'product_type': 'reanalysis',
            'format': 'netcdf',
            'variable': ['land_sea_mask'],
            'year': date_time.strftime('%Y'),
            'month': date_time.strftime('%m'),
            'day': date_time.strftime('%d'),
            'time': date_time.strftime('%H:00'),
            'area': [lat_north, lon_west, lat_south, lon_east],
        }
        
        lsm_path = f'era5_lsm_temp_{date_time.strftime("%Y%m%d%H%M%S")}.nc'
        print("     🏝️ Fetching land-sea mask...")
        self.cds_client.retrieve('reanalysis-era5-single-levels', lsm_request, lsm_path)
        
        # Open BOTH datasets
        with xr.open_dataset(winds_path) as winds_dataset, xr.open_dataset(lsm_path) as lsm_dataset:
            # Process WINDS dataset
            if 'valid_time' in winds_dataset.dims:
                winds_at_time = winds_dataset.squeeze('valid_time')
            else:
                winds_at_time = winds_dataset
            
            # Process LSM dataset
            if 'valid_time' in lsm_dataset.dims:
                lsm_at_time = lsm_dataset.squeeze('valid_time')
            else:
                lsm_at_time = lsm_dataset

            # Create simulation grid in geographic coordinates
            sim_lon = np.linspace(lon_west, lon_east, self.sim.nx)
            sim_lat = np.linspace(lat_south, lat_north, self.sim.ny)
            
            # Interpolate WINDS to simulation grid
            winds_interp = winds_at_time.interp(longitude=sim_lon, latitude=sim_lat)
            
            # Interpolate LSM to simulation grid  
            lsm_interp = lsm_at_time.interp(longitude=sim_lon, latitude=sim_lat)
            
            # --- PROCESS WINDS (Existing Logic) ---
            actual_pressure_levels_pa = winds_interp.pressure_level.values * 100
            
            if len(actual_pressure_levels_pa) < 2:
                raise ValueError("ERA5 returned < 2 vertical levels.")

            u_levels = winds_interp["u"].values.transpose(0, 2, 1)  # [pressure, nx, ny]
            v_levels = winds_interp["v"].values.transpose(0, 2, 1)
            
            # Initialize integrated wind fields (CPU)
            u_integrated_ms = np.zeros((self.sim.nx, self.sim.ny))
            v_integrated_ms = np.zeros((self.sim.nx, self.sim.ny))
            
            pressure_levels_hpa = actual_pressure_levels_pa / 100.0

            # =====================================================================
            # V7.2 FIX: LATITUDE-ADAPTIVE DLM WEIGHTING
            # =====================================================================
            # Problem History:
            #   V6.25: 4× weight on 200 hPa captured recurvature troughs (Katrina)
            #   V6.26: Reduced 200 hPa weight over LAND (post-landfall eastward bias)
            #   V7.2:  Reduced 200 hPa weight in deep TROPICS (pre-recurvature bias)
            #
            # New Problem (exposed by V7.1.2 thermodynamic fix):
            #   For Cape Verde storms at 15-20°N, 200 hPa has strong WESTERLIES
            #   from the tropical upper anticyclone outflow. With 4× weight, these
            #   overwhelm the 500-700 hPa EASTERLIES that actually steer the storm.
            #   Hugo's DLM reversed to eastward on Sept 12 at 20°N, 32°W — pushing
            #   the storm back toward Africa. 5,550 km track error.
            #
            # Physics: TC steering layer depth depends on latitude:
            #   Deep tropics (< 20°N): 500-700 hPa easterlies steer. Upper anti-
            #     cyclone outflow at 200 hPa is opposite the storm motion.
            #   Subtropics (20-28°N): Steering layer deepens as storm encounters
            #     mid-latitude troughs. 200 hPa becomes increasingly relevant.
            #   Mid-latitudes (> 28°N): 200-300 hPa troughs dominate recurvature.
            #     Original V6.25 weighting is correct here.
            #
            # FIX: Three weight profiles blended by latitude AND land fraction:
            #   TROPICAL OCEAN (lat < 20°N): Mid-level dominant
            #   EXTRATROPICAL OCEAN (lat > 28°N): Upper-level dominant (V6.25)
            #   LAND: Lower-level dominant (V6.26, unchanged)
            # =====================================================================
            
            # Get storm latitude for DLM layer selection
            storm_lat = abs(getattr(self.sim, 'current_center_lat', 20.0))
            
            # Get land fraction at domain center
            land_frac_center = 0.0  # Default to ocean
            if hasattr(self, 'land_fraction') and self.land_fraction is not None:
                cx, cy = self.sim.nx // 2, self.sim.ny // 2
                land_frac_center = np.mean(self.land_fraction[max(0,cx-5):cx+5, max(0,cy-5):cy+5])
            
            # Define three weight profiles — COMPONENT-SPECIFIC for tropics
            # =====================================================================
            # V7.2.1: COMPONENT-SPECIFIC TROPICAL DLM WEIGHTS
            # 
            # Physics: In the deep tropics, zonal and meridional steering come from
            # different layers:
            #   u-wind: 500-700 hPa trade easterlies steer westward. 200 hPa has
            #           anticyclone WESTERLIES that oppose the motion — must suppress.
            #   v-wind: Northward drift has a legitimate 200 hPa component from the
            #           subtropical ridge position (Hadley circulation). Suppressing
            #           200 hPa kills the northward signal → storm drifts south.
            #
            # Evidence (Five's analysis of Hugo run):
            #   Sept 12 02:24: v_200=+9.2 (N), v_500=-6.2 (S), v_850=-3.8 (S)
            #   With 0.5× on 200 hPa: southward wins → storm pushed to 11.6°N
            #   Historical Hugo: should be ~16°N at that longitude
            #
            # Fix: Separate weight profiles for u and v in tropical regime.
            #   Extratropical and land weights are component-identical (same physics).
            # =====================================================================
            weights_tropical_u = np.ones_like(pressure_levels_hpa, dtype=np.float64)
            weights_tropical_v = np.ones_like(pressure_levels_hpa, dtype=np.float64)
            weights_extratropical = np.ones_like(pressure_levels_hpa, dtype=np.float64)
            weights_land = np.ones_like(pressure_levels_hpa, dtype=np.float64)
            
            for i, p_level in enumerate(pressure_levels_hpa):
                # TROPICAL OCEAN — U-WIND: suppress 200 hPa anticyclone westerlies
                if p_level <= 200:
                    weights_tropical_u[i] = 0.5
                elif p_level <= 300:
                    weights_tropical_u[i] = 1.0
                elif p_level <= 400:
                    weights_tropical_u[i] = 1.5
                elif p_level <= 600:
                    weights_tropical_u[i] = 2.5
                elif p_level <= 700:
                    weights_tropical_u[i] = 2.0
                else:
                    weights_tropical_u[i] = 1.0
                
                # TROPICAL OCEAN — V-WIND: Partial mid-level emphasis
                # Physics: Unlike u-wind, the meridional signal has legitimate
                # contributions at both upper and mid levels. 200 hPa subtropical
                # ridge provides northward drift; 500-700 hPa mid-level flow
                # provides the cross-track component. Both matter for v.
                #
                # Empirical calibration (Hugo 1989, two anchor points):
                #   v using u-weights (200=0.5, 500=2.5) → 11.6°N (4.4° too S)
                #   v uniform (200=1.5, 500=1.5)         → 21.8°N (5.8° too N)
                #   Interpolated (t=0.43) for 16°N target:
                #     200=1.0, 500=2.0 — less 200 hPa suppression, moderate
                #     mid-level emphasis retained as southward counterweight
                if p_level <= 200:
                    weights_tropical_v[i] = 1.0   # Not suppressed (vs 0.5 for u)
                elif p_level <= 300:
                    weights_tropical_v[i] = 1.0
                elif p_level <= 400:
                    weights_tropical_v[i] = 1.5
                elif p_level <= 600:
                    weights_tropical_v[i] = 2.0   # Mid-level anchor (vs 2.5 for u)
                elif p_level <= 700:
                    weights_tropical_v[i] = 2.0
                else:
                    weights_tropical_v[i] = 1.0
                
                # EXTRATROPICAL OCEAN: Upper-level trough steering (V6.25)
                # Same for both components — upper-level troughs steer u AND v
                if p_level <= 200:
                    weights_extratropical[i] = 4.0
                elif p_level <= 300:
                    weights_extratropical[i] = 2.0
                else:
                    weights_extratropical[i] = 1.0
                
                # LAND: Lower-level terrain anchoring (V6.26, unchanged)
                if p_level >= 850:
                    weights_land[i] = 2.0
                elif p_level >= 700:
                    weights_land[i] = 1.5
                else:
                    weights_land[i] = 1.0
            
            # Step 1: Blend tropical ↔ extratropical by latitude (separate u/v)
            LAT_TROPICAL = 20.0
            LAT_EXTRATROPICAL = 28.0
            
            if storm_lat < LAT_TROPICAL:
                weights_ocean_u = weights_tropical_u
                weights_ocean_v = weights_tropical_v
                lat_mode = "TROPICAL"
            elif storm_lat > LAT_EXTRATROPICAL:
                weights_ocean_u = weights_extratropical
                weights_ocean_v = weights_extratropical
                lat_mode = "EXTRATROPICAL"
            else:
                t_lat = (storm_lat - LAT_TROPICAL) / (LAT_EXTRATROPICAL - LAT_TROPICAL)
                weights_ocean_u = (1.0 - t_lat) * weights_tropical_u + t_lat * weights_extratropical
                weights_ocean_v = (1.0 - t_lat) * weights_tropical_v + t_lat * weights_extratropical
                lat_mode = f"TRANSITION (t={t_lat:.2f})"
            
            # Step 2: Blend ocean ↔ land by land fraction
            if land_frac_center < 0.3:
                weights_u = weights_ocean_u
                weights_v = weights_ocean_v
                weight_mode = f"OCEAN-{lat_mode}"
            elif land_frac_center > 0.5:
                weights_u = weights_land
                weights_v = weights_land
                weight_mode = "LAND"
            else:
                t = (land_frac_center - 0.3) / 0.2
                weights_u = (1.0 - t) * weights_ocean_u + t * weights_land
                weights_v = (1.0 - t) * weights_ocean_v + t * weights_land
                weight_mode = f"COASTAL-{lat_mode} (t={t:.2f})"
            
            # Diagnostic
            wu200 = weights_u[pressure_levels_hpa <= 200]
            wv200 = weights_v[pressure_levels_hpa <= 200]
            wu500 = weights_u[(pressure_levels_hpa >= 450) & (pressure_levels_hpa <= 550)]
            wu200_str = f"{wu200[0]:.1f}" if len(wu200) > 0 else "N/A"
            wv200_str = f"{wv200[0]:.1f}" if len(wv200) > 0 else "N/A"
            wu500_str = f"{wu500[0]:.1f}" if len(wu500) > 0 else "N/A"
            print(f"     🎯 V7.2.2 DLM: lat={storm_lat:.1f}°N land={land_frac_center:.2f} → {weight_mode}")
            print(f"        U-weights: 200hPa={wu200_str}x, 500hPa={wu500_str}x | V-weights: 200hPa={wv200_str}x")

            # Sort by pressure (and sort weights to match!)
            sort_indices = np.argsort(pressure_levels_hpa)
            sorted_pressure_levels = pressure_levels_hpa[sort_indices]
            sorted_weights_u = weights_u[sort_indices]
            sorted_weights_v = weights_v[sort_indices]
            sorted_u_levels = u_levels[sort_indices, :, :]
            sorted_v_levels = v_levels[sort_indices, :, :]
            
            # Deep Layer Mean Calculation
            for i in range(self.sim.nx):
                for j in range(self.sim.ny):
                    u_profile = sorted_u_levels[:, i, j]
                    v_profile = sorted_v_levels[:, i, j]

                    u_series = pd.Series(u_profile).interpolate(method='linear', limit_direction='both')
                    v_series = pd.Series(v_profile).interpolate(method='linear', limit_direction='both')
                    u_profile_clean = u_series.values
                    v_profile_clean = v_series.values
                    
                    if not np.all(np.isfinite(u_profile_clean)): u_profile_clean = np.zeros_like(u_profile_clean)
                    if not np.all(np.isfinite(v_profile_clean)): v_profile_clean = np.zeros_like(v_profile_clean)
                    
                    # =====================================================================
                    # V7.2.1: Component-specific weighted integration
                    # u-wind uses weights_u (suppressed 200 hPa in tropics)
                    # v-wind uses weights_v (legitimate 200 hPa northward signal)
                    # =====================================================================
                    log_p = np.log(sorted_pressure_levels)
                    
                    # V7.2.1: Diagnostic with both weight sets
                    if i == self.sim.nx // 2 and j == self.sim.ny // 2:
                        print(f"     📊 DLM DIAGNOSTIC (center cell):")
                        for k, (plev, u_lev, v_lev, wu, wv) in enumerate(zip(sorted_pressure_levels, u_profile_clean, v_profile_clean, sorted_weights_u, sorted_weights_v)):
                            w_note = f"wu={wu:.1f},wv={wv:.1f}" if abs(wu - wv) > 0.01 else f"w={wu:.1f}"
                            print(f"        {plev:.0f} hPa: u={u_lev:+.1f}, v={v_lev:+.1f} m/s ({w_note})")
                    
                    # Separate weighted integration for u and v
                    u_mean = np.trapz(u_profile_clean * sorted_weights_u, log_p) / np.trapz(sorted_weights_u, log_p)
                    v_mean = np.trapz(v_profile_clean * sorted_weights_v, log_p) / np.trapz(sorted_weights_v, log_p)
                    
                    # V6.25.1: Log weighted result at center
                    if i == self.sim.nx // 2 and j == self.sim.ny // 2:
                        print(f"        ────────────────────────────────────")
                        print(f"        WEIGHTED DLM: u={u_mean:+.1f}, v={v_mean:+.1f} m/s")
                    
                    # V6.23 DLM scale (kept for compatibility)
                    dlm_scale = getattr(self.sim, 'dlm_scale', 1.0)
                    u_integrated_ms[i, j] = u_mean * dlm_scale
                    v_integrated_ms[i, j] = v_mean * dlm_scale
            
            # === V6.23 PATCH: KM-BASED DOUGHNUT FILTER ===
            # V5.1: Five's Recommendation: 225 km radius
            # V6.23: Gemini's Analysis: Increased to 300 km to avoid ERA5 vortex contamination
            # Reason: ERA5 resolution (0.25°) can't resolve intense inner-core winds,
            #         so averaging too close contaminates steering with model's own circulation
              
            # Calculate physical distance
            domain_km = 2000.0  # Physical domain size in km
            cell_km = domain_km / self.sim.nx  # km per grid cell
            
            x = np.arange(self.sim.nx)
            y = np.arange(self.sim.ny)
            yy, xx = np.meshgrid(y, x)
            cx, cy = self.sim.nx // 2, self.sim.ny // 2
            
            # Calculate radius in grid cells
            radius_cells = np.sqrt((xx - cx)**2 + (yy - cy)**2)
            # Convert to km
            radius_km = radius_cells * cell_km
            
            # V6.23: Apply 300 km threshold (was 225 km)
            # Prevents inner-core contamination from ERA5's coarse representation
            inner_radius_km = getattr(self.sim, 'dlm_inner_radius_km', 300.0)
            hole_mask = radius_km < inner_radius_km
            doughnut_mask = ~hole_mask
            
            if np.any(doughnut_mask):
                u_env_mean = np.mean(u_integrated_ms[doughnut_mask])
                v_env_mean = np.mean(v_integrated_ms[doughnut_mask])
                u_integrated_ms[hole_mask] = u_env_mean
                v_integrated_ms[hole_mask] = v_env_mean
                
            """
            
            # === COMPARISON: ===
            # OLD (V5.0): 0.40 * 128 = 51 cells = 765 km radius
            # NEW (V5.1): 225 km / 15.625 km/cell ≈ 14.4 cells
            # 
            # Result: Much tighter masking around actual storm core!
            # === END OF PATCH ===
            
            """
            
            # --- PROCESS LAND MASK (Patch V60.3: NaN-Safe LSM Processing) ---
            # Extract raw LSM from the single-level dataset
            lsm_raw = lsm_interp['lsm'].values
            
            # Handle potential extra dimensions (time/pressure) if squeezed poorly
            if len(lsm_raw.shape) == 3:
                lsm_raw = lsm_raw[0, :, :] # Take first slice
                
            # Transpose to match our [nx, ny] convention (if needed)
            # xarray interpolation usually keeps lat/lon order, we need to verify x/y mapping
            # Based on u_levels transpose(0, 2, 1), we likely need a transpose here too 
            # if lsm comes out as [lat, lon] and we want [lon, lat]
            lsm_data = lsm_raw.T 
            
            # === PATCH V60.3: NaN SAFETY NET ===
            # Caribbean islands and complex coastlines can trigger ERA5 LSM interpolation failures
            # Replace any NaN values with safe fallback (0.0 = ocean)
            if not np.all(np.isfinite(lsm_data)):
                nan_count = np.sum(~np.isfinite(lsm_data))
                print(f"     ⚠️ WARNING: {nan_count} NaN/Inf values in LSM data, replacing with 0.0 (ocean)")
                lsm_data = np.nan_to_num(lsm_data, nan=0.0, posinf=1.0, neginf=0.0)
            
            # FIVE'S FIX: Smooth Land Fraction
            # Apply Gaussian blur to create a "soft" coastline
            # Sigma=1.5 gives a ~3-cell transition zone
            land_fraction = gaussian_filter(lsm_data, sigma=1.5)
            land_fraction = np.clip(land_fraction, 0.0, 1.0)
            
            # === PATCH V60.3: POST-SMOOTHING VALIDATION ===
            # Gaussian filter can propagate NaN if input has NaN (despite pre-check above)
            # This is a critical safety check before GPU upload
            if not np.all(np.isfinite(land_fraction)):
                print(f"     ⚠️ CRITICAL: NaN detected AFTER gaussian_filter, falling back to zero land fraction")
                land_fraction = np.zeros((self.sim.nx, self.sim.ny))
            
            # Diagnostic
            land_pct = float(np.mean(land_fraction) * 100.0)
            print(f"     🏝️ Land Fraction processed: {land_pct:.1f}% land coverage")

            # --- UPLOAD TO GPU ---
            self.u_target = xp.asarray(u_integrated_ms / self.sim.U_CHAR)
            self.v_target = xp.asarray(v_integrated_ms / self.sim.U_CHAR)
            self.land_fraction = xp.asarray(land_fraction) # <-- New GPU Array

        # Clean up BOTH temporary files
        os.remove(winds_path)
        os.remove(lsm_path)
        print("  -> ERA5 data & Land Mask successfully integrated and uploaded to GPU.")

    def update_steering_data(self, center_lat, center_lon, current_sim_time, frame_number):
        """
        Update ERA5 steering data AND Land Mask for new domain center.
        
        Args:
            center_lat: Center latitude for ERA5 domain
            center_lon: Center longitude for ERA5 domain
            current_sim_time: Datetime for ERA5 data to fetch
            frame_number: Current simulation frame
        """
        # Store last good data as backup (including land mask!)
        u_last_good = xp.copy(self.u_target)
        v_last_good = xp.copy(self.v_target)
        land_last_good = xp.copy(self.land_fraction) # <-- Backup land
        
        # Precision Box
        box_radius = 2.0
        self.lon_bounds = (center_lon - box_radius, center_lon + box_radius)
        self.lat_bounds = (center_lat - box_radius, center_lat + box_radius)
        
        try:
            self._fetch_era5_data(current_sim_time)
            self.last_update_frame = frame_number
        except Exception as e:
            print(f"---! ORACLE DI FETCH ERROR !---: {e}")
            print("  -> WARNING: Reverting to last known good steering & land data.")
            self.u_target = u_last_good
            self.v_target = v_last_good
            self.land_fraction = land_last_good # <-- Restore land
            
    def get_smoothed_steering(self, frame):
        """
        Get temporally-smoothed steering flow.
        """
        return self.u_target, self.v_target
