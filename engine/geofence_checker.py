"""
GeofenceChecker - Validates moves against task geofence boundaries.

Ensures agents can only navigate within the defined whitelist of panoramas
for each task.
"""
import json
from pathlib import Path
from typing import Dict, List, Set, Optional

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings


class GeofenceChecker:
    """
    Checks if panorama IDs are within the allowed geofence for a task.
    
    Uses a whitelist approach - only panoramas listed in the geofence
    configuration file are considered valid.
    """
    
    def __init__(self, config_path: Optional[Path] = None):
        """
        Initialize the geofence checker.
        
        Args:
            config_path: Path to geofence_config.json
        """
        self.config_path = config_path or settings.GEOFENCE_CONFIG_PATH
        self._geofences: Dict[str, Set[str]] = {}
        self._load_config()
    
    def _load_config(self):
        """Load geofence configuration from file."""
        if not self.config_path.exists():
            # Create empty config if not exists
            self.config_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self.config_path, 'w') as f:
                json.dump({}, f)
            return
        
        with open(self.config_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        # Convert lists to sets for O(1) lookup
        self._geofences = {
            task_id: set(pano_ids) 
            for task_id, pano_ids in config.items()
        }
    
    def reload_config(self):
        """Reload configuration from file."""
        self._load_config()
    
    def is_valid(self, geofence_name: str, pano_id: str) -> bool:
        """
        Check if a panorama is within the geofence.
        
        Args:
            geofence_name: Geofence list name (e.g., "list001")
            pano_id: Panorama ID to check
            
        Returns:
            True if panorama is in the whitelist
        """
        if geofence_name not in self._geofences:
            # If no geofence defined, allow all
            return True
        
        return pano_id in self._geofences[geofence_name]
    
    def filter_links(
        self, 
        geofence_name: str, 
        links: List[Dict]
    ) -> List[Dict]:
        """
        Filter links to only include those within the geofence.
        
        Args:
            geofence_name: Geofence list name (e.g., "list001")
            links: List of adjacent panoramas [{panoId, heading}, ...]
            
        Returns:
            Filtered list of links
        """
        if geofence_name not in self._geofences:
            # No geofence = allow all
            return links
        
        valid_panos = self._geofences[geofence_name]
        
        return [
            link for link in links
            if (link.get('panoId') or link.get('pano_id')) in valid_panos
        ]
    
    def get_geofence(self, geofence_name: str) -> Set[str]:
        """
        Get the set of allowed panorama IDs for a geofence.
        
        Args:
            geofence_name: Geofence list name (e.g., "list001")
            
        Returns:
            Set of allowed panorama IDs (empty set if no geofence)
        """
        return self._geofences.get(geofence_name, set())
    
    def get_all_geofences(self) -> List[str]:
        """Get list of all geofence names."""
        return list(self._geofences.keys())
    
    def add_geofence(self, geofence_name: str, pano_ids: List[str], save: bool = True):
        """
        Add or update a geofence.
        
        Args:
            geofence_name: Geofence list name (e.g., "list001")
            pano_ids: List of allowed panorama IDs
            save: Whether to save to config file
        """
        self._geofences[geofence_name] = set(pano_ids)
        
        if save:
            self._save_config()
    
    def add_pano_to_geofence(self, geofence_name: str, pano_id: str, save: bool = True):
        """
        Add a single panorama to a geofence.
        
        Args:
            geofence_name: Geofence list name (e.g., "list001")
            pano_id: Panorama ID to add
            save: Whether to save to config file
        """
        if geofence_name not in self._geofences:
            self._geofences[geofence_name] = set()
        
        self._geofences[geofence_name].add(pano_id)
        
        if save:
            self._save_config()
    
    def _save_config(self):
        """Save current configuration to file."""
        config = {
            task_id: list(pano_ids)
            for task_id, pano_ids in self._geofences.items()
        }
        
        with open(self.config_path, 'w', encoding='utf-8') as f:
            json.dump(config, f, indent=2)
    
    def get_stats(self) -> Dict:
        """Get geofence statistics."""
        return {
            'total_geofences': len(self._geofences),
            'geofence_sizes': {
                geofence_name: len(pano_ids) 
                for geofence_name, pano_ids in self._geofences.items()
            }
        }


# Global instance
geofence_checker = GeofenceChecker()
