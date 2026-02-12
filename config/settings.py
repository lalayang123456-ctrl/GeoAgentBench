"""
VLN Benchmark Platform - Global Configuration Settings
"""
import os
from pathlib import Path
from typing import Tuple, List
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Base directories
BASE_DIR = Path(__file__).parent.parent
DATA_DIR = BASE_DIR / "data"
# PANORAMAS_DIR = Path("c:/GitHub/StreetView/VLN_BENCHMARK/data/panoramas")
PANORAMAS_DIR = DATA_DIR / "panoramas"
CACHE_DB_PATH = DATA_DIR / "cache.db"
TASKS_DIR = BASE_DIR / "tasks"
LOGS_DIR = BASE_DIR / "logs"
TEMP_IMAGES_DIR = BASE_DIR / "temp_images"
CONFIG_DIR = BASE_DIR / "config"


class Settings:
    """Global settings for VLN Benchmark platform."""
    
    # === Google API ===
    GOOGLE_API_KEY: str = os.getenv("GOOGLE_API_KEY", "")
    GOOGLE_API_KEYS: List[str] = [
        k.strip() for k in os.getenv("GOOGLE_API_KEYS", "").split(",") if k.strip()
    ]
    
    # === Server ===
    HOST: str = os.getenv("HOST", "0.0.0.0")
    PORT: int = int(os.getenv("PORT", "8000"))
    DEBUG: bool = os.getenv("DEBUG", "true").lower() == "true"
    
    # === Panorama Quality ===
    # Zoom level: 0-5, higher = better resolution
    # | Zoom | Image Size   | Recommended Use      |
    # |------|--------------|----------------------|
    # | 0    | 512×512      | Quick debug          |
    # | 1    | 1024×512     | Development          |
    # | 2    | 2048×1024    | Development          |
    # | 3    | 4096×2048    | Benchmark recommended|
    # | 4    | 8192×4096    | High precision       |
    # | 5    | 16384×8192   | Maximum quality      |
    PANORAMA_ZOOM_LEVEL: int = 2  # Default 2 for development, set to 3 for benchmark
    
    # === Temporary Image Management ===
    # If True, temp images are automatically deleted when a session ends.
    # If False, temp images are kept for debugging/replay.
    # AUTO_DELETE_TEMP_IMAGES: bool = os.getenv("AUTO_DELETE_TEMP_IMAGES", "false").lower() == "true"
    AUTO_DELETE_TEMP_IMAGES: bool = os.getenv("AUTO_DELETE_TEMP_IMAGES", "true").lower() == "true"
    
    # === Server-side Rendering ===
    # Output size with 16:10 aspect ratio (1280/800 = 1.6)
    # With h_fov=120° and aspect=1.6, v_fov = 120/1.6 = 75°
    RENDER_OUTPUT_SIZE: Tuple[int, int] = (1280, 800)  # Agent observation size
    RENDER_DEFAULT_FOV: int = 90  # Default horizontal field of view (degrees)
    RENDER_DEFAULT_PITCH: int = 0  # Default pitch angle
    
    # === Pre-download Settings ===
    PREFETCH_REQUEST_DELAY_MIN: float = 1.0  # Minimum delay between requests (seconds)
    PREFETCH_REQUEST_DELAY_MAX: float = 3.0  # Maximum delay between requests (seconds)
    PREFETCH_RETRY_MAX: int = 3  # Maximum retry attempts
    PREFETCH_RETRY_BACKOFF: float = 2.0  # Exponential backoff multiplier
    PREFETCH_PARALLEL_WORKERS: int = 4  # Number of parallel download workers
    
    # === Session Settings ===
    SESSION_DEFAULT_MAX_STEPS: int = 100  # Default max steps if not specified in task
    SESSION_DEFAULT_MAX_TIME: int = 600  # Default max time in seconds (10 minutes)
    
    # === Geofence ===
    GEOFENCE_CONFIG_PATH: Path = CONFIG_DIR / "perception_whitelist.json"
    
    # === Tiles API ===
    TILES_API_BASE_URL: str = "https://tile.googleapis.com/v1"
    TILES_SESSION_REFRESH_BUFFER: int = 60  # Refresh session 60 seconds before expiry
    
    # === Static API ===
    STATIC_API_BASE_URL: str = "https://maps.googleapis.com/maps/api/streetview"


# Create singleton instance
settings = Settings()

# Ensure directories exist
for directory in [DATA_DIR, PANORAMAS_DIR, TASKS_DIR, LOGS_DIR, TEMP_IMAGES_DIR]:
    directory.mkdir(parents=True, exist_ok=True)