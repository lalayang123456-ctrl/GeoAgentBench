"""
PanoramaCache - Manages panorama image file storage and database indexing.

Handles saving, retrieving, and checking existence of panorama images
at different zoom levels.
"""
import shutil
from pathlib import Path
from typing import Optional

from .cache_manager import cache_manager

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import PANORAMAS_DIR


class PanoramaCache:
    """
    Cache for panorama images stored as files with database indexing.
    
    File naming: {pano_id}_z{zoom}.jpg
    Example: wwkpfmLCWlQ0vinOvd0TpQ_z2.jpg
    """
    
    def __init__(self, panoramas_dir: Optional[Path] = None):
        """
        Initialize panorama cache.
        
        Args:
            panoramas_dir: Directory for panorama images. Defaults to settings.
        """
        self.panoramas_dir = panoramas_dir or PANORAMAS_DIR
        self.panoramas_dir.mkdir(parents=True, exist_ok=True)
    
    def _get_image_path(self, pano_id: str, zoom: int) -> Path:
        """Get the file path for a panorama image."""
        return self.panoramas_dir / f"{pano_id}_z{zoom}.jpg"
    
    def has(self, pano_id: str, zoom: int) -> bool:
        """
        Check if a panorama image exists in cache.
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level (0-5)
            
        Returns:
            True if image exists in cache
        """
        # First check file system (more reliable)
        image_path = self._get_image_path(pano_id, zoom)
        if not image_path.exists():
            return False
        
        # Also verify database record exists
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT 1 FROM panoramas WHERE pano_id = ? AND zoom = ?',
                (pano_id, zoom)
            )
            return cursor.fetchone() is not None
    
    def get(self, pano_id: str, zoom: int) -> Optional[Path]:
        """
        Get the path to a cached panorama image.
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level
            
        Returns:
            Path to image file if exists, None otherwise
        """
        image_path = self._get_image_path(pano_id, zoom)
        if image_path.exists():
            return image_path
        return None
    
    def save(self, pano_id: str, zoom: int, image_data: bytes) -> Path:
        """
        Save a panorama image to cache.
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level
            image_data: Raw image bytes (JPEG)
            
        Returns:
            Path to saved image file
        """
        image_path = self._get_image_path(pano_id, zoom)
        
        # Write image file
        with open(image_path, 'wb') as f:
            f.write(image_data)
        
        # Insert or update database record
        with cache_manager.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO panoramas (pano_id, zoom, image_path)
                VALUES (?, ?, ?)
            ''', (pano_id, zoom, str(image_path)))
        
        return image_path
    
    def save_from_file(self, pano_id: str, zoom: int, source_path: Path) -> Path:
        """
        Save a panorama image from an existing file.
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level
            source_path: Path to source image file
            
        Returns:
            Path to cached image file
        """
        image_path = self._get_image_path(pano_id, zoom)
        
        # Copy file
        shutil.copy2(source_path, image_path)
        
        # Insert or update database record
        with cache_manager.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO panoramas (pano_id, zoom, image_path)
                VALUES (?, ?, ?)
            ''', (pano_id, zoom, str(image_path)))
        
        return image_path
    
    def delete(self, pano_id: str, zoom: int) -> bool:
        """
        Delete a panorama image from cache.
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level
            
        Returns:
            True if deleted, False if not found
        """
        image_path = self._get_image_path(pano_id, zoom)
        
        # Delete file if exists
        if image_path.exists():
            image_path.unlink()
        
        # Delete database record
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'DELETE FROM panoramas WHERE pano_id = ? AND zoom = ?',
                (pano_id, zoom)
            )
            return cursor.rowcount > 0
    
    def get_all_for_pano(self, pano_id: str) -> list:
        """
        Get all zoom levels cached for a panorama.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            List of zoom levels that are cached
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT zoom FROM panoramas WHERE pano_id = ? ORDER BY zoom',
                (pano_id,)
            )
            return [row['zoom'] for row in cursor.fetchall()]
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        with cache_manager.get_connection() as conn:
            cursor = conn.execute('''
                SELECT COUNT(*) as total, COUNT(DISTINCT pano_id) as unique_panos
                FROM panoramas
            ''')
            row = cursor.fetchone()
            return {
                'total_images': row['total'],
                'unique_panoramas': row['unique_panos']
            }


# Global instance
panorama_cache = PanoramaCache()
