"""
MetadataCache - Manages panorama metadata and location data in SQLite.

Stores metadata (lat, lng, capture_date, links) and provides fast
coordinate lookups for distance calculations.
"""
import json
from typing import Optional, Dict, List, Tuple
from pathlib import Path

from .cache_manager import cache_manager


class MetadataCache:
    """
    Cache for panorama metadata using SQLite storage.
    
    Stores:
    - lat, lng: Coordinates
    - capture_date: When the panorama was captured
    - links: Adjacent panorama IDs with their headings
    - fetched_at: When the data was fetched
    - source: Which API was used (maps_js_api / static_api)
    """
    
    def has(self, pano_id: str) -> bool:
        """
        Check if metadata exists for a panorama.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            True if metadata exists
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT 1 FROM metadata WHERE pano_id = ?',
                (pano_id,)
            )
            return cursor.fetchone() is not None
    
    def get(self, pano_id: str) -> Optional[Dict]:
        """
        Get metadata for a panorama.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            Metadata dict or None if not found
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT * FROM metadata WHERE pano_id = ?',
                (pano_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            
            return {
                'pano_id': row['pano_id'],
                'lat': row['lat'],
                'lng': row['lng'],
                'capture_date': row['capture_date'],
                'links': json.loads(row['links']) if row['links'] else [],
                'center_heading': row['center_heading'] if row['center_heading'] is not None else 0.0,
                'fetched_at': row['fetched_at'],
                'source': row['source']
            }
    
    def save(self, pano_id: str, lat: float, lng: float,
             capture_date: Optional[str] = None,
             links: Optional[List[Dict]] = None,
             center_heading: Optional[float] = None,
             source: str = 'unknown') -> None:
        """
        Save or update metadata for a panorama.
        
        Args:
            pano_id: Panorama ID
            lat: Latitude
            lng: Longitude
            capture_date: Capture date string (e.g., "2016-05")
            links: List of adjacent panoramas [{panoId, heading}, ...]
            center_heading: The heading at the origin of the panorama tile set (north offset)
            source: Data source ('maps_js_api' / 'static_api')
        """
        links_json = json.dumps(links) if links else None
        
        with cache_manager.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO metadata 
                (pano_id, lat, lng, capture_date, links, center_heading, source)
                VALUES (?, ?, ?, ?, ?, ?, ?)
            ''', (pano_id, lat, lng, capture_date, links_json, center_heading, source))
            
            # Also update locations table for fast coordinate lookup
            conn.execute('''
                INSERT OR REPLACE INTO locations (pano_id, lat, lng)
                VALUES (?, ?, ?)
            ''', (pano_id, lat, lng))
    
    def get_links(self, pano_id: str) -> Optional[List[Dict]]:
        """
        Get links (adjacent panoramas) for a panorama.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            List of link dicts [{panoId, heading}, ...] or None
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT links FROM metadata WHERE pano_id = ?',
                (pano_id,)
            )
            row = cursor.fetchone()
            if row is None or row['links'] is None:
                return None
            return json.loads(row['links'])
    
    def get_center_heading(self, pano_id: str) -> Optional[float]:
        """
        Get the center heading (north offset) for a panorama.
        
        The centerHeading indicates the heading at the origin of the panorama
        tile set. Use this to calculate where true North is in the image.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            Center heading in degrees (0-360) or None if not found
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT center_heading FROM metadata WHERE pano_id = ?',
                (pano_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return row['center_heading'] if row['center_heading'] is not None else 0.0
    
    def get_location(self, pano_id: str) -> Optional[Tuple[float, float]]:
        """
        Get coordinates for a panorama.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            Tuple of (lat, lng) or None if not found
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT lat, lng FROM locations WHERE pano_id = ?',
                (pano_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            return (row['lat'], row['lng'])
    
    def get_all_locations(self, pano_ids: List[str]) -> Dict[str, Tuple[float, float]]:
        """
        Get coordinates for multiple panoramas.
        
        Args:
            pano_ids: List of panorama IDs
            
        Returns:
            Dict mapping pano_id to (lat, lng) tuples
        """
        if not pano_ids:
            return {}
        
        placeholders = ','.join('?' * len(pano_ids))
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                f'SELECT pano_id, lat, lng FROM locations WHERE pano_id IN ({placeholders})',
                pano_ids
            )
            return {row['pano_id']: (row['lat'], row['lng']) for row in cursor.fetchall()}
    
    def has_links(self, pano_id: str) -> bool:
        """
        Check if links are cached for a panorama.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            True if links exist and are not empty
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT links FROM metadata WHERE pano_id = ? AND links IS NOT NULL',
                (pano_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return False
            links = json.loads(row['links']) if row['links'] else []
            return len(links) > 0
    
    def delete(self, pano_id: str) -> bool:
        """
        Delete metadata for a panorama.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            True if deleted, False if not found
        """
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'DELETE FROM metadata WHERE pano_id = ?',
                (pano_id,)
            )
            conn.execute(
                'DELETE FROM locations WHERE pano_id = ?',
                (pano_id,)
            )
            return cursor.rowcount > 0
    
    def get_stats(self) -> dict:
        """Get cache statistics."""
        with cache_manager.get_connection() as conn:
            cursor = conn.execute('''
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN links IS NOT NULL THEN 1 ELSE 0 END) as with_links
                FROM metadata
            ''')
            row = cursor.fetchone()
            return {
                'total_metadata': row['total'],
                'with_links': row['with_links']
            }


# Global instance
metadata_cache = MetadataCache()
