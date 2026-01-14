#!/usr/bin/env python3
"""
ORACLE V5.2 "SURGICAL STRIKE" - ABLATION TEST SUITE
====================================================

Scientific validation framework for pure physics testing.

Usage Examples:
    # Test A: Pure Physics (no Oracle nudging)
    python World_woe_main_adaptive.py --pure-physics
    
    # Test B: Advection Ablation (prove linear was the killer)
    python World_woe_main_adaptive.py --pure-physics --advection-order 1
    
    # Test C: Sponge Ablation (test boundary importance)
    python World_woe_main_adaptive.py --pure-physics --sponge-strength 0.0
    
    # Default: V5.2 with all features
    python World_woe_main_adaptive.py

Credits:
    Framework design: Gemini & Five
    Implementation: Claude
    Testing: Justin
"""

import argparse
import sys
from datetime import datetime

# === PARSE COMMAND LINE ARGUMENTS ===
def parse_arguments():
    parser = argparse.ArgumentParser(
        description='Oracle V5.2 Ablation Test Suite',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  Test A (Pure Physics):
    python World_woe_main_adaptive.py --pure-physics
  
  Test B (Advection Ablation):
    python World_woe_main_adaptive.py --pure-physics --advection-order 1
  
  Test C (Sponge Ablation):
    python World_woe_main_adaptive.py --pure-physics --sponge-strength 0.0
        """
    )
    
    # Physics Mode
    parser.add_argument('--pure-physics', action='store_true',
                       help='Disable Oracle nudging (pure thermodynamics only)')
    
    # Numerical Settings
    parser.add_argument('--advection-order', type=int, default=3, choices=[1, 2, 3],
                       help='Advection interpolation order (1=linear, 3=cubic, default=3)')
    parser.add_argument('--sponge-strength', type=float, default=0.003,
                       help='Edge sponge damping strength (default=0.003, 0.0=disabled)')
    parser.add_argument('--smagorinsky-cs', type=float, default=0.17,
                       help='Smagorinsky coefficient (default=0.17)')
    
    # Simulation Settings
    parser.add_argument('--storm', type=str, default='HUGO',
                       help='Storm name (default=HUGO)')
    parser.add_argument('--year', type=int, default=1989,
                       help='Storm year (default=1989)')
    parser.add_argument('--frames', type=int, default=25600,
                       help='Number of frames to run (default=25600)')
    parser.add_argument('--resolution', type=int, default=128,
                       help='Grid resolution (nx=ny=resolution, default=128)')
    
    # Output
    parser.add_argument('--output-tag', type=str, default=None,
                       help='Custom tag for output files')
    
    return parser.parse_args()

# === CONFIGURATION BANNER ===
def print_configuration_banner(args, config):
    """Print detailed configuration banner for logs."""
    print("=" * 80)
    print("  ORACLE V5.2 ABLATION TEST SUITE")
    print("=" * 80)
    print(f"  Test Mode: {'PURE PHYSICS' if args.pure_physics else 'STANDARD (with Oracle assist)'}")
    print(f"  Storm: {args.storm} ({args.year})")
    print(f"  Frames: {args.frames:,}")
    print(f"  Resolution: {args.resolution}³")
    print("")
    print("  NUMERICAL CONFIGURATION:")
    print(f"    Advection Order: {args.advection_order} ({'CUBIC' if args.advection_order==3 else 'LINEAR' if args.advection_order==1 else 'QUADRATIC'})")
    print(f"    Sponge Strength: {args.sponge_strength:.4f} ({'DISABLED' if args.sponge_strength==0 else 'SOFT BEACH'})")
    print(f"    Smagorinsky Cs: {args.smagorinsky_cs:.3f}")
    print(f"    Coriolis: Cayley Transform (Energy-Conserving)")
    print("")
    print("  PHYSICS CONFIGURATION:")
    print(f"    Oracle Nudging: {'DISABLED ⚠️' if args.pure_physics else 'ENABLED (V47/V50)'}")
    print(f"    Surface Fluxes: ENABLED (Bulk Aerodynamic)")
    print(f"    Ocean Coupling: ENABLED (Static Basin)")
    print(f"    Thermodynamic Driver: {'Surface Fluxes ONLY' if args.pure_physics else 'Surface + Oracle'}")
    print("")
    if args.pure_physics:
        print("  ⚠️  PURE PHYSICS MODE ACTIVE")
        print("  → Storm must survive on thermodynamics alone!")
        print("  → Success: Survives >5,000 frames")
        print("  → Failure: Slow decay → Need Boussinesq buoyancy (V5.3)")
        print("")
    print("  Credits: Gemini (Framework) + Five (Analysis) + Claude (Code)")
    print("=" * 80)
    print("")

# === NOW IMPORT THE REST (after argument parsing) ===
# This allows --help to work without GPU initialization

import numpy as np

# GPU Toggle
USE_GPU = True
try:
    if USE_GPU:
        import cupy as xp
        from cupyx.scipy import ndimage
        import cupyx.scipy.fft as fft
        print(f"[{__name__}] 🚀 GPU Acceleration ENABLED (CuPy)")
    else:
        raise ImportError
except ImportError:
    import numpy as xp
    from scipy import ndimage
    import scipy.fft as fft
    print(f"[{__name__}] 🐢 GPU Acceleration DISABLED (NumPy)")
    USE_GPU = False

from datetime import datetime, timedelta
import os

# === V5.2 IMPORTS ===
from environment import BasinEnvironment
from core_solver import CoreSolver
from boundary_conditions import BoundaryConditions
from storm_tracker import StormTracker
from visualizer import Visualizer
from amr_handler import AMRHandler
from kalman_filter import KalmanFilter
from data_interface import DataInterface

# === LOGGING UTILITIES ===
class TeeLogger:
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

# === MAIN SIMULATION CLASS ===
class Simulation3D:
    def __init__(self, nx, ny, nz, storm_name, storm_year, config):
        """
        Initialize V5.2 simulation with configurable physics.
        
        Args:
            nx, ny, nz: Grid dimensions
            storm_name, storm_year: Storm to simulate
            config: Configuration dictionary from command line args
        """
        # Store configuration
        self.config = config
        self.pure_physics = config['pure_physics']
        self.advection_order = config['advection_order']
        self.sponge_strength_config = config['sponge_strength']
        self.Cs = config['smagorinsky_cs']
        
        # Grid dimensions
        self.nx, self.ny, self.nz = nx, ny, nz
        
        # Physical Scales (SI Units)
        self.physical_domain_x_km = 2000.0
        self.physical_domain_y_km = 2000.0
        self.physical_domain_z_km = 20.0
        self.L_CHAR = self.physical_domain_x_km * 1000.0
        self.U_CHAR = 50.0  # m/s
        self.T_CHAR = self.L_CHAR / self.U_CHAR
        self.dt_solver = 5e-5  # HOTFIX #6: Reduced from 1e-4 for pure physics stability
        
        # Physical Constants
        self.c_p = 1004.0  # Specific heat of air at constant pressure (J/(kg·K))
        self.rho_air = 1.225  # Air density at sea level (kg/m³)
        
        # Grid spacing (MUST BE DEFINED BEFORE DomainScaler!)
        self.lx = self.ly = 1.0
        self.lz = self.physical_domain_z_km / self.physical_domain_x_km
        self.dx = self.lx / nx
        self.dy = self.ly / ny
        self.dz = self.lz / nz
        
        # Domain scaler for unit conversions
        self.domain_scaler = DomainScaler(
            self.nx * self.dx, self.ny * self.dy, self.nz * self.dz,
            self.physical_domain_x_km,
            self.physical_domain_y_km,
            self.physical_domain_z_km
        )
        
        log_info(f"⚡ ORACLE V5.2 INITIALIZATION: {storm_name} {storm_year} ⚡")
        log_info(f"   Version: V5.2 'SURGICAL STRIKE' (Ablation Test Suite)")
        log_info(f"   Mode: {'PURE PHYSICS' if self.pure_physics else 'STANDARD (Oracle Assist)'}")
        
        # Console logging
        test_tag = "PURE" if self.pure_physics else "ORACLE"
        adv_tag = f"ADV{self.advection_order}"
        sponge_tag = f"SPG{int(self.sponge_strength_config*1000)}"
        
        self.console_log_file = f"console_v5_2_{test_tag}_{adv_tag}_{sponge_tag}_{storm_name}_{storm_year}.log"
        self.tee_logger = TeeLogger(self.console_log_file)
        sys.stdout = self.tee_logger
        log_info(f"   📝 Console output logging to: {self.console_log_file}")
        
        # Diagnostics
        self.frame_history = []
        self.max_wind_history = []
        
        # === STATE ARRAYS (GPU or CPU) ===
        self.u = xp.zeros((nx, ny, nz))
        self.v = xp.zeros((nx, ny, nz))
        self.w = xp.zeros((nx, ny, nz))
        self.T = xp.ones((nx, ny, nz)) * 15.0
        self.q = xp.ones((nx, ny, nz)) * 0.010
        self.rho = 1.0  # Air density (constant for incompressible approximation)
        
        # === V5: STATIC BASIN ENVIRONMENT ===
        log_info("   🌊 Initializing Static Basin Environment...")
        self.basin = BasinEnvironment()
        
        # === DATA INTERFACE (ERA5 + HURDAT2) ===
        self.data_interface = DataInterface(self, storm_name, storm_year)
        
        # Extract genesis point
        first_point = self.data_interface.historical_track.iloc[0]
        self.current_center_lat = float(first_point['latitude'])
        self.current_center_lon = float(first_point['longitude'])
        self.genesis_time = first_point['datetime']
        
        log_info(f"   🎯 Genesis Point: ({self.current_center_lat:.2f}°N, {self.current_center_lon:.2f}°W)")
        
        # Initial environment sync
        self._sync_environment()  # Defaults to frame=0
        
        # === CORIOLIS PARAMETERS ===
        self.f0 = 2 * 7.2921e-5 * xp.sin(xp.radians(self.current_center_lat))
        self.beta = 2 * 7.2921e-5 * xp.cos(xp.radians(self.current_center_lat)) / 6.371e6
        
        log_info(f"   🌍 Coriolis f0: {self.f0:.2e} rad/s (V5.2: Cayley Transform)")
        log_info(f"   🌍 Beta: {self.beta:.2e} (1/m/s)")
        
        # === SUBSYSTEMS ===
        log_info("   🔧 Initializing Subsystems...")
        
        # Pass config to core solver
        self.solver = CoreSolver(self)
        self.solver.advection_order = self.advection_order  # Set advection order
        
        self.boundaries = BoundaryConditions(self)
        self.storm_tracker = StormTracker(self)
        
        # Check if tracker has Oracle capability
        self.oracle_available = hasattr(self.storm_tracker, 'oracle_nudge')
        if self.pure_physics and self.oracle_available:
            log_info("   ⚠️  Oracle nudging DISABLED for pure physics test")
        
        # === OUTPUT DIRECTORY (for Visualizer) ===
        self.plot_dir = f"world_woe_v5_2_plots"
        os.makedirs(self.plot_dir, exist_ok=True)
        os.makedirs(os.path.join(self.plot_dir, "vtk_frames_final"), exist_ok=True)
        
        self.visualizer = Visualizer(self)
        self.amr = AMRHandler(self)
        self.kalman = KalmanFilter(nx, ny, process_noise=1e-5, measurement_noise=0.01)
        
        # === EDGE SPONGE MASK ===
        log_info("   🛡️ Creating Edge Sponge Mask...")
        self._create_edge_sponge_mask()
        
        # === INITIALIZATION ===
        log_info("   🌀 Initializing Storm (V5.2 Gaussian Soft Start)...")
        self._initialize_storm_gaussian()
        
        log_info("   ✅ V5.2 Initialization Complete!")
        log_info("")
        log_info(f"--- BEGINNING V5.2 SIMULATION ---")
        log_info(f"--- Target Frames: {config['target_frames']:,} ---")
        if self.pure_physics:
            log_info(f"--- TEST A: PURE PHYSICS (No Oracle) ---")
            log_info(f"--- SUCCESS CRITERIA: Survive >5,000 frames ---")
        log_info("")
    
    def _create_edge_sponge_mask(self):
        """
        Create damping mask for boundaries (Five's V5.2 corrected geometry).
        """
        x = xp.arange(self.nx) / self.nx
        y = xp.arange(self.ny) / self.ny
        xx, yy = xp.meshgrid(x, y, indexing='ij')
        
        # Distance to nearest edge
        edge_dist = xp.minimum(
            xp.minimum(xx, 1-xx),
            xp.minimum(yy, 1-yy)
        )
        
        # Five's corrected geometry: Ramp over outer 15% only
        band = 0.15
        self.sponge_mask = xp.clip(edge_dist / band, 0.0, 1.0)
        
        # Use configured strength
        self.sponge_strength = self.sponge_strength_config
        
        if self.sponge_strength == 0.0:
            log_info(f"   🛡️ Sponge DISABLED for ablation test")
        else:
            log_info(f"   🛡️ Sponge configured: strength={self.sponge_strength:.4f}, band=15%")
    
    def _sync_environment(self, frame=0):
        """Fetch ERA5 + SST/OHC at current geographic center."""
        elapsed_seconds = frame * self.dt_solver * self.T_CHAR
        current_sim_time = self.genesis_time + timedelta(seconds=elapsed_seconds)
        
        self.data_interface.update_steering_data(
            self.current_center_lat, 
            self.current_center_lon,
            current_sim_time,
            frame
        )
        
        # Calculate domain bounds
        half_domain_deg = (self.physical_domain_x_km / 2.0) / 111.0
        
        lat_min = self.current_center_lat - half_domain_deg
        lat_max = self.current_center_lat + half_domain_deg
        lon_min = self.current_center_lon - half_domain_deg / np.cos(np.radians(self.current_center_lat))
        lon_max = self.current_center_lon + half_domain_deg / np.cos(np.radians(self.current_center_lat))
        
        # Sample basin
        sst_slice, ohc_slice = self.basin.get_slice(
            lat_min, lat_max, lon_min, lon_max,
            self.nx, self.ny
        )
        
        # Store on GPU
        self.SST = xp.asarray(sst_slice)
        self.OHC = xp.asarray(ohc_slice)
        
        if not hasattr(self, 'total_ohc_loss'):
            self.total_ohc_loss = 0.0
    
    def _initialize_storm_gaussian(self):
        """V5.2 Gaussian vortex initialization (Soft Start)."""
        log_info("   🌀 Genesis Protocol: Gaussian Vortex (Lamb-Oseen)")
        
        cx, cy = self.nx // 2, self.ny // 2
        x = xp.arange(self.nx)
        y = xp.arange(self.ny)
        xx, yy = xp.meshgrid(x, y, indexing='ij')
        
        r = xp.sqrt((xx - cx)**2 + (yy - cy)**2) * self.dx * self.L_CHAR / 1000.0
        
        R_max = 50.0
        v_max = 25.0 / self.U_CHAR  # HOTFIX #6: Reduced from 50.0 to prevent explosion in pure physics mode
        
        # Lamb-Oseen profile
        v_theta = v_max * (r / R_max) * xp.exp(0.5 * (1 - (r / R_max)**2))
        
        theta = xp.arctan2(yy - cy, xx - cx)
        
        for k in range(self.nz):
            strength = xp.exp(-0.5 * (k / (self.nz / 4))**2)
            self.u[:,:,k] = -v_theta * xp.sin(theta) * strength
            self.v[:,:,k] = v_theta * xp.cos(theta) * strength
        
        # The Pressurizer
        log_info("   🔧 The Pressurizer: Pre-solving pressure field (10 iterations)...")
        for _ in range(10):  # HOTFIX #6: Reduced from 20 to preserve vortex energy
            self.u, self.v, self.w, _ = self.solver.project(
                self.u, self.v, self.w,
                damping_factor_h=1.0,
                damping_factor_w=1.0
            )
        
        log_info("   ✅ Gaussian Initialization Complete. System Balanced.")
    
    def update(self, frame):
        """Single timestep update."""
        
        # 1-6: Standard physics (advection, diffusion, etc.)
        self.u = self.solver.advect(self.u, self.u, self.v, self.w)
        self.v = self.solver.advect(self.v, self.u, self.v, self.w)
        self.w = self.solver.advect(self.w, self.u, self.v, self.w)
        self.T = self.solver.advect(self.T, self.u, self.v, self.w)
        self.q = self.solver.advect(self.q, self.u, self.v, self.w)
        
        nu_t = self.solver.compute_smagorinsky_viscosity(self.u, self.v, self.w, Cs=self.Cs)
        
        self.u += self.dt_solver * nu_t * self.solver.laplacian(self.u)
        self.v += self.dt_solver * nu_t * self.solver.laplacian(self.v)
        self.w += self.dt_solver * nu_t * self.solver.laplacian(self.w)
        
        # Surface fluxes (boundary_conditions accesses self.sim.q and self.sim.T internally)
        q_new, T_new, q_f, h_f, damp = self.boundaries.apply_surface_fluxes(
            self.u, self.v, self.SST
        )
        self.q = q_new
        self.T = T_new
        
        # q_f and h_f are already scalar totals, not arrays
        self.total_ohc_loss += float(q_f + h_f) * self.dt_solver * self.T_CHAR
        
        # 7. V5.2: CAYLEY CORIOLIS
        f_nd = self.f0 * self.T_CHAR
        alpha = 0.5 * f_nd * self.dt_solver
        D = 1.0 + alpha**2
        
        u_old = self.u.copy()
        v_old = self.v.copy()
        
        self.u = ((1.0 - alpha**2) * u_old + 2.0 * alpha * v_old) / D
        self.v = (-2.0 * alpha * u_old + (1.0 - alpha**2) * v_old) / D
        
        if frame % 1000 == 0:
            KE_before = float(xp.mean(u_old**2 + v_old**2))
            KE_after = float(xp.mean(self.u**2 + self.v**2))
            conservation_error = abs(KE_after - KE_before) / (KE_before + 1e-16)
            log_info(f"    🌍 Cayley Coriolis: KE conservation error = {conservation_error:.2e}")
        
        # 8. Pressure Projection
        self.u, self.v, self.w, p = self.solver.project(
            self.u, self.v, self.w,
            damping_factor_h=1.0,
            damping_factor_w=1.0
        )
        
        # 9. SOFT BEACH SPONGE (V5.2: Configurable)
        if self.sponge_strength > 0:
            damping = 1.0 - self.sponge_strength * (1.0 - self.sponge_mask[:,:,xp.newaxis])
            self.u *= damping
            self.v *= damping
            
            if frame % 1000 == 0:
                edge_ke = float(xp.mean((self.u[:,:,0]**2 + self.v[:,:,0]**2) * (1.0 - self.sponge_mask)))
                log_info(f"    🛡️ Soft Beach: Edge KE = {edge_ke:.2e}")
        
        # 10. Diagnostics
        if frame % 100 == 0:
            vort_mag = xp.sqrt(sum(c**2 for c in self.solver.curl(self.u, self.v, self.w)))
            p_cpu = p.get() if USE_GPU else p
            vort_cpu = vort_mag.get() if USE_GPU else vort_mag
            
            # Update tracker
            self.storm_tracker.update_metrics(frame, p_cpu, vort_cpu)
            
            # PURE PHYSICS CHECK: Disable Oracle if configured
            if self.pure_physics and self.oracle_available:
                # Skip Oracle nudging - let physics run naturally
                pass
            elif not self.pure_physics and self.oracle_available:
                # Allow Oracle nudging
                self.storm_tracker.oracle_nudge(self.u, self.v, self.w)
            
            max_wind = self.storm_tracker.get_max_wind()
            ohc_loss_display = self.total_ohc_loss / 1e6
            log_info(f"[INFO] Frame {frame}: Max Wind {max_wind:.1f} kts | OHC Loss: {ohc_loss_display:.2e} kJ/cm² | Camera Shifts: 0")
            
            # Storm health
            avg_wind_ms = float(xp.mean(xp.sqrt(self.u**2 + self.v**2)) * self.U_CHAR)
            max_vort = float(xp.max(vort_mag))
            log_info(f"    💨 Storm Health: Avg Wind={avg_wind_ms:.1f} m/s, Max Vort={max_vort:.2e}")
            
            self.max_wind_history.append(float(max_wind))
            
            # Smagorinsky diagnostic
            if frame % 1000 == 0:
                nu_t_cpu = nu_t.get() if USE_GPU else nu_t
                log_info(f"    📊 V5.2 Smagorinsky Viscosity: min={float(nu_t_cpu.min()):.2e}, mean={float(nu_t_cpu.mean()):.2e}, max={float(nu_t_cpu.max()):.2e}")
        
        # 11. Visualization (wrapped to prevent crashes if methods differ)
        if frame % 1000 == 0 and frame > 0:
            try:
                self.visualizer.save_2d_wind_map(
                    self.u[:,:,0], self.v[:,:,0],
                    frame, self.U_CHAR
                )
            except (AttributeError, TypeError) as e:
                # Visualizer method signature might differ - skip visualization
                pass
            
            if frame % 5000 == 0:
                try:
                    self.visualizer.plot_diagnostic_overlay(
                        self.u[:,:,0], self.v[:,:,0],
                        self.data_interface.u_target[:,:,0] if hasattr(self.data_interface, 'u_target') else None,
                        self.data_interface.v_target[:,:,0] if hasattr(self.data_interface, 'v_target') else None,
                        self.data_interface.historical_track,
                        self.current_center_lat, self.current_center_lon,
                        frame, self.U_CHAR
                    )
                except (AttributeError, TypeError) as e:
                    # Visualizer method signature might differ - skip visualization
                    pass
        
        # 12. Nest Advection (every 3600 frames = 4 hours)
        if frame > 100 and frame % 3600 == 0:
            u_steer_ms = float(xp.mean(self.data_interface.u_target)) * self.U_CHAR
            v_steer_ms = float(xp.mean(self.data_interface.v_target)) * self.U_CHAR
            
            dt_physical_s = self.dt_solver * self.T_CHAR
            dlat = v_steer_ms * dt_physical_s / 111000.0
            dlon = u_steer_ms * dt_physical_s / (111000.0 * np.cos(np.radians(self.current_center_lat)))
            
            self.current_center_lat += dlat
            self.current_center_lon += dlon
            
            self._sync_environment(frame)
            log_info(f"    📍 V5.2 NEST ADVECTION: Center now at ({self.current_center_lat:.2f}°N, {self.current_center_lon:.2f}°W)")
    
    def run(self, target_frames):
        """Main simulation loop."""
        for i in range(target_frames):
            self.update(i)
        
        # Cleanup
        self.tee_logger.close()
        sys.stdout = self.tee_logger.terminal
        log_info(f"   ✅ Simulation complete: {target_frames} frames")
        log_info(f"   ✅ Console log saved: {self.console_log_file}")

# === DUMMY CLASSES (if missing) ===
class DomainScaler:
    """
    Unit conversion between dimensionless simulation coordinates and physical units.
    
    V5.2 Implementation: Simple scaling based on domain size.
    """
    def __init__(self, lx, ly, lz, px, py, pz):
        """
        Args:
            lx, ly, lz: Dimensionless domain size (usually 1.0, 1.0, ~0.01)
            px, py, pz: Physical domain size in km
        """
        self.lx = lx
        self.ly = ly
        self.lz = lz
        self.px = px  # km
        self.py = py  # km
        self.pz = pz  # km
        
        # Conversion factors
        self.x_scale = px * 1000.0 / lx  # m per dimensionless unit
        self.y_scale = py * 1000.0 / ly
        self.z_scale = pz * 1000.0 / lz
    
    def dimensionless_to_physical_z(self, dz_dimensionless):
        """Convert dimensionless vertical spacing to physical meters."""
        return dz_dimensionless * self.z_scale
    
    def dimensionless_to_physical_x(self, dx_dimensionless):
        """Convert dimensionless horizontal spacing to physical meters."""
        return dx_dimensionless * self.x_scale
    
    def dimensionless_to_physical_y(self, dy_dimensionless):
        """Convert dimensionless horizontal spacing to physical meters."""
        return dy_dimensionless * self.y_scale
    
    def physical_to_dimensionless_z(self, z_physical_m):
        """Convert physical vertical distance (m) to dimensionless."""
        return z_physical_m / self.z_scale
    
    def physical_to_dimensionless_x(self, x_physical_m):
        """Convert physical horizontal distance (m) to dimensionless."""
        return x_physical_m / self.x_scale
    
    def physical_to_dimensionless_y(self, y_physical_m):
        """Convert physical horizontal distance (m) to dimensionless."""
        return y_physical_m / self.y_scale

# === MAIN ENTRY POINT ===
if __name__ == "__main__":
    # Parse arguments
    args = parse_arguments()
    
    # Build configuration dictionary
    config = {
        'pure_physics': args.pure_physics,
        'advection_order': args.advection_order,
        'sponge_strength': args.sponge_strength,
        'smagorinsky_cs': args.smagorinsky_cs,
        'target_frames': args.frames,
    }
    
    # Print configuration banner
    print_configuration_banner(args, config)
    
    # Create simulation
    sim = Simulation3D(
        nx=args.resolution,
        ny=args.resolution,
        nz=16,
        storm_name=args.storm,
        storm_year=args.year,
        config=config
    )
    
    # Run!
    sim.run(args.frames)
    
    print("")
    print("=" * 80)
    print("  SIMULATION COMPLETE")
    print("=" * 80)
    if args.pure_physics:
        print("  Test A (Pure Physics) finished!")
        print("  Check max wind values to determine if thermodynamics alone sustained storm.")
    print("=" * 80)
