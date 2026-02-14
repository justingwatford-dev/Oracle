"""
Oracle V6.16 Core Solver - Steering Injection Fix

Key Changes:
    V6.2: resolution_boost configurable (Five + Gemini "Molasses" fix)
    V6.16: Steering flow injection in project() (Gemini "Treadmill" fix)

The V6.16 STEERING FIX:
    Problem: The pressure projection preserved domain-mean velocity, but a 
    symmetric vortex has mean ≈ 0. ERA5 steering was only used to move domain
    boundaries, never injected into fluid dynamics. Result: vortex spins in 
    place while domain slides underneath ("treadmill effect").
    
    Solution: After projection, restore ENVIRONMENTAL STEERING velocity 
    (from ERA5) instead of the vortex's self-mean. This couples the fluid
    to the large-scale flow.

Modification: Claude (Opus 4.5), January 2026
Based on: Gemini's forensic analysis of "Steering Cancellation Paradox"
"""
import numpy as np
import sys

# === GPU ACCELERATION TOGGLE ===
USE_GPU = True

try:
    if USE_GPU:
        import cupy as xp
        import cupyx.scipy.ndimage as ndimage
        import cupyx.scipy.fft as fft
        print(f"[{__name__}] 🚀 GPU Acceleration ENABLED (CuPy)")
    else:
        raise ImportError
except ImportError:
    import numpy as xp
    import scipy.ndimage as ndimage
    import scipy.fft as fft
    print(f"[{__name__}] 🐢 GPU Acceleration DISABLED (NumPy)")


class CoreSolver:
    def __init__(self, sim_instance):
        self.sim = sim_instance
        self.kx = xp.fft.fftfreq(self.sim.nx, d=self.sim.dx)
        self.ky = xp.fft.fftfreq(self.sim.ny, d=self.sim.dy)
        self.kz = xp.fft.fftfreq(self.sim.nz, d=self.sim.dz)
        self.k_squared = self.kx[:, xp.newaxis, xp.newaxis]**2 + \
                         self.ky[xp.newaxis, :, xp.newaxis]**2 + \
                         self.kz[xp.newaxis, xp.newaxis, :]**2
        # PATCH V38: k=0 mode is now handled properly in project() method
        
        self.grid_points = xp.mgrid[0:self.sim.nx, 0:self.sim.ny, 0:self.sim.nz]
        
        # V6.2: Diagnostic storage for turbulent viscosity
        self.last_nu_turb_max = 0.0
        self.last_nu_turb_mean = 0.0

    def gradient_x(self, f):
        return fft.ifftn(1j * self.kx[:, xp.newaxis, xp.newaxis] * fft.fftn(f)).real

    def gradient_y(self, f):
        return fft.ifftn(1j * self.ky[xp.newaxis, :, xp.newaxis] * fft.fftn(f)).real

    def gradient_z(self, f):
        return fft.ifftn(1j * self.kz[xp.newaxis, xp.newaxis, :] * fft.fftn(f)).real

    def laplacian(self, f):
        return fft.ifftn(-self.k_squared * fft.fftn(f)).real

    # === V6.2 PATCH: CONFIGURABLE RESOLUTION BOOST ===
    # === Based on Five + Gemini "Molasses Atmosphere" Analysis ===
    def compute_smagorinsky_viscosity(self, u, v, w, Cs=0.17):
        """
        Computes dynamic eddy viscosity based on the Strain Rate Tensor (S_ij).
        
        V6.2 CHANGE (Five + Gemini Ensemble Fix):
        ------------------------------------------
        The 1500× resolution_boost was identified as creating a "viscous wall"
        that dynamically strengthens as the storm intensifies (because νt ∝ |S|).
        
        This makes the atmosphere behave like "molasses" - the harder the storm
        spins, the more viscous it becomes, creating an artificial intensity ceiling.
        
        FIX: resolution_boost is now configurable via self.sim.resolution_boost
        
        Recommended test sweep: 1500 → 300 → 150 → 75
        Hypothesis: Ceiling should rise as boost decreases
        """
        # 1. Compute velocity gradients (Strain Rate Tensor Components)
        du_dx = self.gradient_x(u)
        du_dy = self.gradient_y(u)
        du_dz = self.gradient_z(u)

        dv_dx = self.gradient_x(v)
        dv_dy = self.gradient_y(v)
        dv_dz = self.gradient_z(v)

        dw_dx = self.gradient_x(w)
        dw_dy = self.gradient_y(w)
        dw_dz = self.gradient_z(w)

        # 2. Compute Symmetric Strain Tensor elements
        S_xx = du_dx
        S_yy = dv_dy
        S_zz = dw_dz
        S_xy = 0.5 * (du_dy + dv_dx)
        S_xz = 0.5 * (du_dz + dw_dx)
        S_yz = 0.5 * (dv_dz + dw_dy)

        # 3. Compute Magnitude of Strain Rate |S|
        S_squared = (S_xx**2 + S_yy**2 + S_zz**2) + \
                    2.0 * (S_xy**2 + S_xz**2 + S_yz**2)
        
        S_magnitude = xp.sqrt(2.0 * S_squared)

        # 4. Filter Scale (Delta) - Dimensionless
        delta = (self.sim.dx * self.sim.dy * self.sim.dz)**(1/3)

        # 5. V6.2: CONFIGURABLE Resolution Boost Factor
        # Read from simulation config, default to 1500.0 for backwards compatibility
        resolution_boost = getattr(self.sim, 'resolution_boost', 1500.0)

        # 6. Compute Eddy Viscosity with Resolution Scaling
        nu_turb = resolution_boost * (Cs * delta)**2 * S_magnitude
        
        # V6.2: Store diagnostics for monitoring
        self.last_nu_turb_max = float(xp.max(nu_turb))
        self.last_nu_turb_mean = float(xp.mean(nu_turb))
        
        return nu_turb
    # === END V6.2 SMAGORINSKY PATCH ===

    def advect(self, f, u, v, w):
        departure_x = self.grid_points[0] - u * self.sim.dt_solver / self.sim.dx
        departure_y = self.grid_points[1] - v * self.sim.dt_solver / self.sim.dy
        departure_z = self.grid_points[2] - w * self.sim.dt_solver / self.sim.dz
        
        # =====================================================================
        # V7.1 FIX: Z-CLAMP — BREAK THE SPECTRAL SHORT-CIRCUIT
        # =====================================================================
        # Gemini Deep Research diagnosis: The FFT basis e^(ikz) enforces
        # f(z) = f(z+Lz), topologically connecting the moist boundary layer
        # (18 g/kg) directly to the dry stratosphere (0.006 g/kg).
        #
        # With mode='wrap', any updraft at Level 0 samples Level 15 (dry),
        # and any subsidence at Level 15 samples Level 0 (moist). This
        # homogenizes the moisture column to its mean (~1.8 g/kg) in ~100
        # frames — the "Moisture Starvation" crash seen in all four V7.0 runs.
        #
        # Fix: Clamp z departure points to [0, nz-1] BEFORE interpolation.
        # x,y remain periodic (wrap) for the horizontal domain.
        # z now has effective rigid-lid / ocean-floor boundaries:
        #   - Parcels "below" z=0 see surface values (ocean source)
        #   - Parcels "above" z=nz-1 see tropopause values (dry lid)
        #
        # This is the semi-Lagrangian equivalent of Gemini's recommended
        # "CLAMP (Nearest Neighbor)" boundary mode for vertical interpolation.
        # The full DST/DCT hybrid solver is deferred to V8.0.
        #
        # Reference: Gemini Remediation Report §3.1.1, §6.2
        # =====================================================================
        departure_z = xp.clip(departure_z, 0.0, self.sim.nz - 1.0)
        
        departure_points = xp.array([departure_x, departure_y, departure_z])
        
        # V5.2: Configurable interpolation (order set by simulation class, default=3)
        # mode='wrap' now only affects x,y (z is pre-clamped above)
        f_advected = ndimage.map_coordinates(f, departure_points, order=getattr(self, "advection_order", 3), mode='wrap')
        
        # =====================================================================
        # V6.5 FIX: QUASI-MONOTONIC LIMITER (Gemini's "Bermejo Fix")
        # =====================================================================
        # Problem: Cubic spline interpolation (order=3) is NOT monotonic.
        # At sharp gradients (like eyewall), it produces Gibbs overshoots -
        # "phantom energy" that triggers the WISHE feedback loop.
        #
        # Solution: After interpolation, clip values to the local min/max
        # of the original field. This ensures advection NEVER creates new
        # extrema, eliminating the phantom heat source.
        #
        # Reference: Bermejo & Staniforth (1992), MWR
        # =====================================================================
        
        if getattr(self.sim, 'monotonic_advection', False):
            try:
                # Get global bounds from the ORIGINAL field (before advection)
                # This is a simpler, more robust approach than local neighborhood
                f_global_min = float(xp.min(f))
                f_global_max = float(xp.max(f))
                
                # Add small buffer to avoid over-clamping (1% of range)
                f_range = f_global_max - f_global_min
                buffer = 0.01 * max(f_range, 1.0)  # At least 1K buffer
                
                # Clip the cubic-interpolated values to enforce monotonicity
                # Advection should NEVER create values outside the original field's range
                f_advected = xp.clip(f_advected, f_global_min - buffer, f_global_max + buffer)
                
                # Secondary safety: check for any remaining NaN/Inf
                if xp.any(xp.isnan(f_advected)) or xp.any(xp.isinf(f_advected)):
                    print("[WARNING] Monotonic advection produced NaN/Inf, reverting to unclamped")
                    f_advected = ndimage.map_coordinates(f, departure_points, order=getattr(self, "advection_order", 3), mode='wrap')
                    
            except Exception as e:
                # If anything goes wrong, fall back to standard advection
                print(f"[WARNING] Monotonic advection failed: {e}, using standard")
                f_advected = ndimage.map_coordinates(f, departure_points, order=getattr(self, "advection_order", 3), mode='wrap')
        
        return f_advected

    def project(self, u, v, w, damping_factor_h, damping_factor_w):
        """
        PATCH V38: SPECTRAL POISSON SOLVER (The Iron Foundation).
        Solves ∇²p = ∇·u to enforce incompressibility.
        
        V50.5 UPDATE: Surgical Governor application.
        
        V6.16 UPDATE: STEERING INJECTION FIX (Gemini's "Treadmill" Fix)
        ================================================================
        Problem: Previously, we preserved domain-mean velocity after projection.
        But a symmetric vortex has mean ≈ 0, so the storm spun in place while
        the domain boundaries moved ("treadmill effect").
        
        Solution: After projection, restore ENVIRONMENTAL STEERING velocity
        (from ERA5) instead of the vortex's self-mean. This couples the fluid
        to the large-scale synoptic flow.
        
        The steering values are stored in self.sim by the main simulation loop
        as current_u_steering_nd and current_v_steering_nd (dimensionless).
        """
        
        # 1. SEPARATE MEAN FLOW (The "DC Component")
        u_mean = xp.mean(u)
        v_mean = xp.mean(v)
        w_mean = xp.mean(w)
        
        u -= u_mean
        v -= v_mean
        w -= w_mean

        # 2. COMPUTE DIVERGENCE
        divergence = self.gradient_x(u) + self.gradient_y(v) + self.gradient_z(w)
        
        # 3. TRANSFORM TO FREQUENCY SPACE
        div_hat = fft.fftn(divergence)
        
        # 4. ENFORCE GLOBAL MASS CONSERVATION
        div_hat[0, 0, 0] = 0.0
        
        # 5. SOLVE POISSON EQUATION: k² p_hat = -div_hat
        k_squared_safe = self.k_squared.copy()
        k_squared_safe[0, 0, 0] = 1.0  # Dummy value to avoid Inf/NaN
        
        p_hat = -div_hat / k_squared_safe
        
        # 6. SET MEAN PRESSURE GAUGE
        p_hat[0, 0, 0] = 0.0
        
        # 7. TRANSFORM BACK TO PHYSICAL SPACE
        p = fft.ifftn(p_hat).real
        
        # 8. APPLY PRESSURE CORRECTION (Project onto divergence-free space)
        inv_rho = 1.0 / self.sim.rho
        
        u -= damping_factor_h * inv_rho * self.gradient_x(p)
        v -= damping_factor_h * inv_rho * self.gradient_y(p)
        w -= damping_factor_w * inv_rho * self.gradient_z(p)

        # === V50.5 PATCH: SURGICAL INTENSITY GOVERNOR ===
        # === V53.1 UPDATE: Proper 3D Velocity Clamping ===
        # === V54 UPDATE: Stronger Damping (Gemini's Fix) ===
        
        MAX_REALISTIC_WIND_MS = 95.0  # ~185 kts (Strongest observed Atlantic hurricane)
        EMERGENCY_DAMPING_THRESHOLD = 85.0  # ~165 kts (Start damping at strong H5)
        
        # Calculate current max 3D spin magnitude (perturbation)
        velocity_magnitude_3d = xp.sqrt(u**2 + v**2 + w**2)
        max_spin_ms = float(xp.max(velocity_magnitude_3d) * self.sim.U_CHAR)
        
        if max_spin_ms > EMERGENCY_DAMPING_THRESHOLD:
            overshoot = max_spin_ms - EMERGENCY_DAMPING_THRESHOLD
            excess_ratio = overshoot / EMERGENCY_DAMPING_THRESHOLD
            
            # V54: Stronger progressive damping (0.35 max vs 0.15)
            emergency_damping = 1.0 - min(0.35, excess_ratio * 0.7)
            
            u *= emergency_damping
            v *= emergency_damping
            w *= emergency_damping
            
            # Recalculate after damping
            velocity_magnitude_3d = xp.sqrt(u**2 + v**2 + w**2)
            max_spin_ms = float(xp.max(velocity_magnitude_3d) * self.sim.U_CHAR)
            
            if max_spin_ms > MAX_REALISTIC_WIND_MS:
                # V53.1 VECTOR MAGNITUDE CLAMPING
                velocity_magnitude_3d_physical = velocity_magnitude_3d * self.sim.U_CHAR
                
                scale_factor = xp.where(
                    velocity_magnitude_3d_physical > MAX_REALISTIC_WIND_MS,
                    MAX_REALISTIC_WIND_MS / (velocity_magnitude_3d_physical + 1e-12),
                    1.0
                )
                
                u *= scale_factor
                v *= scale_factor
                w *= scale_factor
                
                if max_spin_ms > MAX_REALISTIC_WIND_MS:
                     print(f"    ⚠️ V54 SURGICAL GOVERNOR: Clamped 3D Spin {max_spin_ms:.1f} -> {MAX_REALISTIC_WIND_MS:.1f} m/s")
        # === END V50.5/V53.1/V54 PATCH ===
        
        # =====================================================================
        # 9. V6.16 STEERING INJECTION (Gemini's "Treadmill" Fix)
        # =====================================================================
        # Instead of restoring the vortex's domain mean (which is ~0 for a
        # symmetric vortex), we restore the ENVIRONMENTAL STEERING flow.
        # This couples the fluid to the large-scale synoptic flow.
        #
        # The steering values come from ERA5 via the main simulation loop.
        # They are stored as dimensionless values (divided by U_CHAR).
        # =====================================================================
        
        # Check if steering injection is enabled and values are available
        steering_injection = getattr(self.sim, 'steering_injection_enabled', False)
        
        if steering_injection:
            # Get environmental steering (dimensionless, from ERA5)
            u_steering_nd = getattr(self.sim, 'current_u_steering_nd', 0.0)
            v_steering_nd = getattr(self.sim, 'current_v_steering_nd', 0.0)
            
            # Restore steering flow instead of domain mean
            u += u_steering_nd
            v += v_steering_nd
            w += w_mean  # Vertical mean is fine (no large-scale vertical steering)
        else:
            # Backwards compatibility: restore domain mean
            u += u_mean
            v += v_mean
            w += w_mean
        
        return u, v, w, p


    def get_max_velocity(self, u, v, w):
        if not xp.all(xp.isfinite(u)):
            return xp.inf
        return float(xp.max(xp.sqrt(u**2 + v**2 + w**2)))

    def curl(self, u, v, w):
        dw_dy = self.gradient_y(w); dv_dz = self.gradient_z(v)
        du_dz = self.gradient_z(u); dw_dx = self.gradient_x(w)
        dv_dx = self.gradient_x(v); du_dy = self.gradient_y(u)
        return (dw_dy - dv_dz, du_dz - dw_dx, dv_dx - du_dy)

    def generate_3d_divergence_free_noise(self, amplitude):
        potential_shape = (self.sim.nx // 4, self.sim.ny // 4, self.sim.nz // 4)
        coords = xp.mgrid[0:self.sim.nx, 0:self.sim.ny, 0:self.sim.nz] / 4.0
        
        if USE_GPU:
             noise_x = xp.random.randn(*potential_shape)
             noise_y = xp.random.randn(*potential_shape)
             noise_z = xp.random.randn(*potential_shape)
        else:
             noise_x = xp.asarray(np.random.randn(*potential_shape))
             noise_y = xp.asarray(np.random.randn(*potential_shape))
             noise_z = xp.asarray(np.random.randn(*potential_shape))

        Ax = ndimage.map_coordinates(noise_x, coords, order=3, mode='wrap')
        Ay = ndimage.map_coordinates(noise_y, coords, order=3, mode='wrap')
        Az = ndimage.map_coordinates(noise_z, coords, order=3, mode='wrap')
        
        u_turb, v_turb, w_turb = self.curl(Ax, Ay, Az)
        norm_factor = amplitude / (xp.mean(xp.sqrt(u_turb**2 + v_turb**2 + w_turb**2)) + 1e-12)
        return u_turb * norm_factor, v_turb * norm_factor, w_turb * norm_factor
