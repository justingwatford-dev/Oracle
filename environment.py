import numpy as np
from scipy.interpolate import RegularGridInterpolator

class BasinEnvironment:
    """
    ORACLE V5: STATIC BASIN ENVIRONMENT
    
    Represents the "Ground Truth" of the North Atlantic basin.
    Fixed in Earth coordinates. Does NOT move with the storm.
    
    Coordinate System:
    - Latitude: 0°N to 60°N
    - Longitude: -100°W to -10°W
    - Resolution: 0.1° (approx 11km)
    
    Physics:
    - SST: Derived from NOAA OISST Climatology (August)
    - OHC: Derived from SST using Five's Formula (OHC = 50 * (SST - 26))
    - Land Mask: (Placeholder for V5.1 - currently pure ocean for V5.0 baseline)
    """
    
    # NOAA OISST v2.1 Climatology (August)
    # Latitude (°N) -> SST (°C)
    ATLANTIC_SST_CLIMATOLOGY = {
        0:  27.0,   # Equator
        5:  28.0,   # Deep tropics
        10: 28.5,   # Tropical Atlantic
        15: 29.0,   # Peak warm pool (Cape Verde region)
        20: 28.5,   # Subtropical
        25: 27.5,   # Northern Caribbean / Gulf Stream origin
        30: 26.0,   # Gulf Stream / Florida Straits
        35: 24.0,   # Mid-Atlantic / weakening zone
        40: 21.0,   # North Atlantic / rapid weakening
        45: 18.0,   # Cold North Atlantic
        50: 15.0,   # Subpolar
        55: 12.0,
        60: 10.0
    }

    def __init__(self):
        print("[BasinEnvironment] Initializing V5 Static North Atlantic Basin...")
        
        # 1. Define Basin Boundaries (Fixed Earth Coordinates)
        self.lat_min, self.lat_max = 0.0, 60.0
        self.lon_min, self.lon_max = -100.0, -10.0
        self.res = 0.1  # 0.1 degrees (~11 km)
        
        # 2. Create the Fixed Grid
        self.lats = np.arange(self.lat_min, self.lat_max, self.res)
        self.lons = np.arange(self.lon_min, self.lon_max, self.res)
        
        self.n_lat = len(self.lats)
        self.n_lon = len(self.lons)
        
        print(f"  -> Grid Size: {self.n_lon} x {self.n_lat} points")
        
        # 3. Initialize Fields (Numpy Arrays - CPU)
        # Shape is [lon, lat] to match x, y convention
        self.SST_basin = np.zeros((self.n_lon, self.n_lat), dtype=np.float32)
        self.OHC_basin = np.zeros((self.n_lon, self.n_lat), dtype=np.float32)
        
        # 4. Populate Climatology
        self._build_climatology()
        
        # 5. Create Interpolators for Fast Sampling
        # These allow us to sample the basin at any arbitrary (lat, lon)
        self.sst_interp = RegularGridInterpolator(
            (self.lons, self.lats), self.SST_basin, 
            bounds_error=False, fill_value=None
        )
        self.ohc_interp = RegularGridInterpolator(
            (self.lons, self.lats), self.OHC_basin, 
            bounds_error=False, fill_value=None
        )
        print("  -> Basin Initialized. Ready for sampling.")

    def _get_climatological_sst(self, lat):
        """Interpolate SST from the NOAA table based on latitude."""
        # Extract table
        table_lats = sorted(self.ATLANTIC_SST_CLIMATOLOGY.keys())
        table_ssts = [self.ATLANTIC_SST_CLIMATOLOGY[l] for l in table_lats]
        return np.interp(lat, table_lats, table_ssts)

    def _build_climatology(self):
        """Populate the basin grids based on latitude."""
        print("  -> Building Climatology Layers...")
        
        # We can vectorize this since SST is currently purely lat-dependent
        # In V5.1, we can load a 2D NetCDF here for real geography
        
        # Create a 2D mesh of latitudes
        _, lat_grid = np.meshgrid(self.lons, self.lats, indexing='ij')
        
        # 1. Compute SST Basin-Wide
        # For now, it's a function of latitude only (zonal symmetry)
        # But stored as a 2D field so we can add cold wakes later
        for j in range(self.n_lat):
            lat_val = self.lats[j]
            sst_val = self._get_climatological_sst(lat_val)
            self.SST_basin[:, j] = sst_val
            
        # 2. Compute OHC Basin-Wide (Five's Formula)
        # OHC_floor = max(0, 50 * (SST - 26))
        # +20 kJ/cm² margin for initial state
        self.OHC_basin = np.maximum(0.0, 50.0 * (self.SST_basin - 26.0)) + 20.0
        
        print(f"     SST Range: {np.min(self.SST_basin):.1f}°C to {np.max(self.SST_basin):.1f}°C")
        print(f"     OHC Range: {np.min(self.OHC_basin):.1f} to {np.max(self.OHC_basin):.1f} kJ/cm²")

    def get_slice(self, lat_min, lat_max, lon_min, lon_max, nx, ny):
        """
        Extract a slice of the environment for the simulation window.
        
        Args:
            lat_min, lat_max: Latitude bounds of the simulation nest
            lon_min, lon_max: Longitude bounds of the simulation nest
            nx, ny: Resolution of the simulation nest (e.g., 128x128)
            
        Returns:
            sst_slice, ohc_slice: 2D Numpy arrays (nx, ny)
        """
        # 1. Create the query grid (the coordinates of the simulation pixels)
        sim_lons = np.linspace(lon_min, lon_max, nx)
        sim_lats = np.linspace(lat_min, lat_max, ny)
        
        # Create meshgrid of coordinates to query
        # RegularGridInterpolator expects shape (nx*ny, 2) for points
        query_lons, query_lats = np.meshgrid(sim_lons, sim_lats, indexing='ij')
        query_points = np.stack((query_lons.flatten(), query_lats.flatten()), axis=1)
        
        # 2. Interpolate SST
        sst_flat = self.sst_interp(query_points)
        sst_slice = sst_flat.reshape(nx, ny)
        
        # 3. Interpolate OHC
        ohc_flat = self.ohc_interp(query_points)
        ohc_slice = ohc_flat.reshape(nx, ny)
        
        return sst_slice.astype(np.float32), ohc_slice.astype(np.float32)

    def update_basin_state(self, lat_min, lat_max, lon_min, lon_max, new_sst, new_ohc):
        """
        Feedback loop (V5.2): Update the basin with the cold wake from the storm.
        The storm modifies the slice, we paste it back into the basin.
        (Placeholder for future implementation)
        """
        pass