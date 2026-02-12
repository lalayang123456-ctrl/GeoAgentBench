"""
ImageStitcher - Stitches panorama tiles into a complete equirectangular image.

Takes downloaded tiles and combines them into a single panorama image.
"""
import io
from pathlib import Path
from typing import Dict, Tuple, Optional

try:
    from PIL import Image
except ImportError:
    Image = None

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import PANORAMAS_DIR
from .panorama_cache import panorama_cache


class ImageStitcher:
    """
    Stitches panorama tiles into complete equirectangular images.
    
    Tile layout:
    - Tiles are arranged in a grid
    - Grid size depends on zoom level
    - Each tile is 512x512 pixels
    """
    
    TILE_SIZE = 512  # Standard Google tile size
    
    def __init__(self):
        """Initialize the image stitcher."""
        if Image is None:
            raise ImportError("Pillow is required. Install with: pip install Pillow")
    
    @staticmethod
    def get_grid_dimensions(zoom: int) -> Tuple[int, int]:
        """
        Get grid dimensions for a zoom level.
        
        Args:
            zoom: Zoom level (0-5)
            
        Returns:
            Tuple of (cols, rows)
        """
        if zoom == 0:
            return (1, 1)
        cols = 2 ** zoom
        rows = 2 ** (zoom - 1)
        return (cols, rows)
    
    @staticmethod
    def get_output_size(zoom: int) -> Tuple[int, int]:
        """
        Get output image size for a zoom level.
        
        Args:
            zoom: Zoom level
            
        Returns:
            Tuple of (width, height)
        """
        cols, rows = ImageStitcher.get_grid_dimensions(zoom)
        return (cols * ImageStitcher.TILE_SIZE, rows * ImageStitcher.TILE_SIZE)
    
    def stitch_tiles(
        self,
        tiles: Dict[Tuple[int, int], bytes],
        zoom: int
    ) -> Optional[Image.Image]:
        """
        Stitch tiles into a complete panorama image.
        
        Args:
            tiles: Dict mapping (x, y) to tile bytes
            zoom: Zoom level
            
        Returns:
            Stitched PIL Image or None if failed
        """
        cols, rows = self.get_grid_dimensions(zoom)
        width, height = self.get_output_size(zoom)
        
        # Create output image
        output = Image.new('RGB', (width, height))
        
        for y in range(rows):
            for x in range(cols):
                if (x, y) not in tiles:
                    print(f"Missing tile at ({x}, {y})")
                    return None
                
                try:
                    tile_data = tiles[(x, y)]
                    tile_img = Image.open(io.BytesIO(tile_data))
                    
                    # Paste tile at correct position
                    paste_x = x * self.TILE_SIZE
                    paste_y = y * self.TILE_SIZE
                    output.paste(tile_img, (paste_x, paste_y))
                    
                except Exception as e:
                    print(f"Error processing tile ({x}, {y}): {e}")
                    return None
        
        return output
    
    def stitch_and_save(
        self,
        tiles: Dict[Tuple[int, int], bytes],
        pano_id: str,
        zoom: int,
        output_dir: Optional[Path] = None
    ) -> Optional[Path]:
        """
        Stitch tiles and save to file.
        
        Args:
            tiles: Dict mapping (x, y) to tile bytes
            pano_id: Panorama ID
            zoom: Zoom level
            output_dir: Output directory (defaults to panoramas cache)
            
        Returns:
            Path to saved image or None if failed
        """
        output_dir = output_dir or PANORAMAS_DIR
        output_dir.mkdir(parents=True, exist_ok=True)
        
        # Stitch tiles
        image = self.stitch_tiles(tiles, zoom)
        if image is None:
            return None
        
        # Save image
        output_path = output_dir / f"{pano_id}_z{zoom}.jpg"
        image.save(str(output_path), 'JPEG', quality=90)
        
        # Update cache database
        with open(output_path, 'rb') as f:
            image_bytes = f.read()
        panorama_cache.save(pano_id, zoom, image_bytes)
        
        return output_path
    
    def download_and_stitch(
        self,
        pano_id: str,
        zoom: int,
        progress_callback=None
    ) -> Optional[Path]:
        """
        Download tiles and stitch into complete panorama.
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level
            progress_callback: Optional callback(current, total)
            
        Returns:
            Path to saved panorama or None if failed
        """
        # Check if already cached
        if panorama_cache.has(pano_id, zoom):
            return panorama_cache.get(pano_id, zoom)
        
        # Import here to avoid circular dependency
        from .tiles_downloader import get_tiles_downloader
        
        downloader = get_tiles_downloader()
        
        # Download all tiles
        tiles = downloader.download_all_tiles(pano_id, zoom, progress_callback)
        if tiles is None:
            return None
        
        # Stitch and save
        return self.stitch_and_save(tiles, pano_id, zoom)


# Global instance
image_stitcher = ImageStitcher()
