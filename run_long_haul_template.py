"""
ORACLE V5 - LONG HAUL RUNNER (PURE PHYSICS MODE)

Goal:
  Long-haul runner for V5 pure physics simulations.
  No Oracle guidance, no heuristics, no fudge factors - just honest physics.

Examples:
  # Run Hugo for 3 simulated days
  python run_long_haul_v5.py --storm HUGO --year 1989 --target-days 3 --seed 1989 --wind 50

  # Run Ivan for 300k frames (explicit frame count)
  python run_long_haul_v5.py --storm IVAN --year 2004 --frames 300000 --seed 2004 --wind 40

  # Run Katrina for a full week
  python run_long_haul_v5.py --storm KATRINA --year 2005 --target-days 7 --seed 2005 --wind 35
"""

from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime

from world_woe_v5_enhanced import Simulation3D


DEFAULT_FRAMES_PER_DAY = 21600  # ~4 s/frame -> 21600 frames/day (based on current sim scaling)


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Oracle V5 Long Haul Runner (Pure Physics)",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    # Mission identity
    p.add_argument("--storm", required=True, type=str, help="Storm name (e.g., HUGO, IVAN, KATRINA)")
    p.add_argument("--year", required=True, type=int, help="Storm year (e.g., 1989, 2004, 2005)")

    # Duration controls (pick ONE)
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--frames", type=int, help="Total frames to run")
    g.add_argument("--target-days", type=float, help="Target simulated days (converted to frames)")

    # Initial conditions
    p.add_argument("--seed", type=int, default=None, help="Random seed for reproducibility (default: year)")
    p.add_argument("--wind", type=float, default=50.0, help="Initial wind speed (knots)")

    # Grid resolution
    p.add_argument("--nx", type=int, default=128, help="X grid points")
    p.add_argument("--ny", type=int, default=128, help="Y grid points")
    p.add_argument("--nz", type=int, default=64, help="Z grid points")

    # Output control
    p.add_argument("--write-manifest", action="store_true",
                   help="Write a run manifest JSON alongside the logs (recommended)")
    p.add_argument("--manifest-dir", type=str, default="run_manifests")

    # Safety
    p.add_argument("--dry-run", action="store_true", help="Initialize + print computed timing, but do not run")

    return p


def _now_tag() -> str:
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def main() -> int:
    args = _build_parser().parse_args()

    storm = args.storm.strip().upper()
    year = int(args.year)
    
    # Default seed to year if not specified
    seed = args.seed if args.seed is not None else year

    # Convert target-days to frames (before we init Simulation3D)
    if args.target_days is not None:
        frames = int(round(args.target_days * DEFAULT_FRAMES_PER_DAY))
    else:
        frames = int(args.frames)

    run_tag = f"V5_{storm}_{year}_{_now_tag()}_seed{seed}"

    print(f"\n╔═══════════════════════════════════════════════════════════════╗")
    print(f"║         ORACLE V5: PURE PHYSICS LONG-HAUL PROTOCOL           ║")
    print(f"╚═══════════════════════════════════════════════════════════════╝")
    print(f"")
    print(f" Storm: {storm} ({year})")
    print(f" Run tag: {run_tag}")
    print(f" Frames: {frames:,}")
    if args.target_days is not None:
        print(f" Target days requested: {args.target_days:.2f}")
        print(f" (Using {DEFAULT_FRAMES_PER_DAY:,} frames/day conversion)")
    print(f" Seed: {seed}")
    print(f" Initial wind: {args.wind:.1f} kts")
    print(f" Grid: {args.nx} x {args.ny} x {args.nz}")
    print(f"")
    print(f" V5 MODE: Pure Physics (No Oracle, No Heuristics, No Fudge Factors)")
    print(f" ├─ Pure Smagorinsky turbulence (no resolution boost)")
    print(f" ├─ Reactive camera (follows simulated storm)")
    print(f" ├─ Static basin environment (no warm puddle bug)")
    print(f" └─ Edge sponge damping (boundary artifact suppression)")
    print(f"")

    # Initialize Simulation
    sim = Simulation3D(
        nx=args.nx,
        ny=args.ny,
        nz=args.nz,
        num_frames=frames,
        initial_wind_kts=args.wind,
        storm_name=storm,
        storm_year=year,
        random_seed=seed,
    )

    # Compute actual simulated-time scaling
    sec_per_frame = float(sim.dt_solver) * float(sim.T_CHAR)
    sim_seconds = frames * sec_per_frame
    sim_days = sim_seconds / 86400.0
    sim_hours = sim_seconds / 3600.0
    frames_per_day_actual = 86400.0 / sec_per_frame if sec_per_frame > 0 else float("inf")

    print("─────────────────────────────────────────────────────────────────")
    print(" SIMULATION TIME SCALING")
    print("─────────────────────────────────────────────────────────────────")
    print(f" Seconds per frame: {sec_per_frame:.3f} s")
    print(f" Frames per day (actual): {frames_per_day_actual:,.0f}")
    print(f" Simulation duration: {sim_days:.2f} days ({sim_hours:.1f} hours)")
    
    if args.target_days is not None:
        # Warn if the hard-coded conversion doesn't match actual scaling
        mismatch = abs(frames_per_day_actual - DEFAULT_FRAMES_PER_DAY) / DEFAULT_FRAMES_PER_DAY
        if mismatch > 0.05:
            print(f" ⚠️  WARNING: Actual frames/day differs from default by {mismatch*100:.1f}%")
    print("")

    # Optional run manifest
    if args.write_manifest:
        os.makedirs(args.manifest_dir, exist_ok=True)
        manifest_path = os.path.join(args.manifest_dir, f"{run_tag}.json")
        manifest = {
            "version": "V5_PURE_PHYSICS",
            "run_tag": run_tag,
            "storm_name": storm,
            "storm_year": year,
            "frames": frames,
            "target_days_requested": args.target_days,
            "seed": seed,
            "initial_wind_kts": args.wind,
            "grid": {"nx": args.nx, "ny": args.ny, "nz": args.nz},
            "v5_features": {
                "pure_smagorinsky": True,
                "no_resolution_boost": True,
                "no_oracle_guidance": True,
                "no_heuristic_nudges": True,
                "reactive_camera": True,
                "static_basin": True,
                "edge_sponge_damping": True,
            },
            "sim_scaling": {
                "sec_per_frame": sec_per_frame,
                "frames_per_day_actual": frames_per_day_actual,
                "sim_days": sim_days,
                "sim_hours": sim_hours,
            },
            "timestamp_local": datetime.now().isoformat(timespec="seconds"),
        }
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)
        print(f"📄 Manifest written: {manifest_path}")
        print("")

    if args.dry_run:
        print("🔍 Dry-run requested: exiting before sim.run().")
        print("")
        return 0

    # Execute
    print("─────────────────────────────────────────────────────────────────")
    print(" BEGINNING SIMULATION")
    print("─────────────────────────────────────────────────────────────────")
    print(f" Expected completion: {frames:,} frames")
    print(f" Simulated time: {sim_days:.2f} days")
    print(f" Pure physics mode - let it break, then we'll debug!")
    print("")
    
    start_time = time.time()
    start_datetime = datetime.now()
    
    try:
        sim.run()
    except KeyboardInterrupt:
        print("\n\n⚠️  INTERRUPTED BY USER")
        wall_hrs = (time.time() - start_time) / 3600.0
        print(f" Wall Time: {wall_hrs:.2f} hours")
        print(f" Check logs and outputs for partial results")
        return 1
    except Exception as e:
        print(f"\n\n❌ SIMULATION CRASHED: {e}")
        wall_hrs = (time.time() - start_time) / 3600.0
        print(f" Wall Time: {wall_hrs:.2f} hours")
        print(f" This is EXPECTED in V5 - we're debugging pure physics!")
        raise
    finally:
        wall_hrs = (time.time() - start_time) / 3600.0
        end_datetime = datetime.now()
        
        print("")
        print("╔═══════════════════════════════════════════════════════════════╗")
        print("║              LONG HAUL PROTOCOL COMPLETE                      ║")
        print("╚═══════════════════════════════════════════════════════════════╝")
        print(f"")
        print(f" Start: {start_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f" End:   {end_datetime.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f" Wall Time: {wall_hrs:.2f} hours")
        print(f" Simulated Time: {sim_days:.2f} days ({sim_hours:.1f} hours)")
        print(f"")
        print(f" Results:")
        print(f" ├─ Logs: {sim.log_file}")
        print(f" ├─ Plots: {sim.plot_dir}")
        print(f" └─ Max Wind History: {len(sim.max_wind_history)} data points")
        print(f"")
        
    return 0


if __name__ == "__main__":
    raise SystemExit(main())