"""
DirectionCalculator - Calculates relative directions and distances.

Converts absolute headings to human-readable relative directions
based on the agent's current heading.
"""
import math
from typing import Tuple, List, Dict, Optional
from dataclasses import dataclass


@dataclass
class RelativeDirection:
    """Represents a relative direction with description and angle."""
    description: str  # e.g., "front-right 15°"
    relative_angle: float  # 0-360
    absolute_heading: float  # Original heading


def calculate_distance(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """
    Calculate distance between two coordinates using Haversine formula.
    
    Args:
        lat1, lng1: First point coordinates
        lat2, lng2: Second point coordinates
        
    Returns:
        Distance in meters
    """
    R = 6371000  # Earth radius in meters
    
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lng2 - lng1)
    
    a = (math.sin(delta_phi / 2) ** 2 +
         math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2)
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    
    return R * c


class DirectionCalculator:
    """
    Calculates relative directions based on agent's current heading.
    
    Direction mapping:
    - 0°: front
    - 0° < x < 90°: front-right X°
    - 90°: right
    - 90° < x < 180°: right-back (X-90)°
    - 180°: back
    - 180° < x < 270°: left-back (270-X)°
    - 270°: left
    - 270° < x < 360°: front-left (360-X)°
    """
    
    @staticmethod
    def get_relative_angle(link_heading: float, agent_heading: float) -> float:
        """
        Calculate relative angle from agent's perspective.
        
        Args:
            link_heading: Absolute heading to the adjacent point
            agent_heading: Agent's current heading
            
        Returns:
            Relative angle (0-360)
        """
        relative = (link_heading - agent_heading + 360) % 360
        return relative
    
    @staticmethod
    def angle_to_direction(relative_angle: float) -> str:
        """
        Convert relative angle to human-readable direction.
        
        Args:
            relative_angle: Angle from agent's perspective (0-360)
            
        Returns:
            Direction description string
        """
        # Normalize to 0-360
        angle = relative_angle % 360
        
        # Threshold for cardinal directions (±10 degrees)
        threshold = 10
        
        # Handle cardinal directions with threshold
        if angle <= threshold or angle >= 360 - threshold:
            return "front"
        elif 90 - threshold <= angle <= 90 + threshold:
            return "right"
        elif 180 - threshold <= angle <= 180 + threshold:
            return "back"
        elif 270 - threshold <= angle <= 270 + threshold:
            return "left"
        
        # Handle intermediate angles
        if threshold < angle < 90 - threshold:
            return f"front-right {angle:.0f}°"
        elif 90 + threshold < angle < 180 - threshold:
            offset = angle - 90
            return f"right-back {offset:.0f}°"
        elif 180 + threshold < angle < 270 - threshold:
            offset = 270 - angle
            return f"left-back {offset:.0f}°"
        else:  # 270 + threshold < angle < 360 - threshold
            offset = 360 - angle
            return f"front-left {offset:.0f}°"
    
    def calculate_relative_direction(
        self, 
        link_heading: float, 
        agent_heading: float
    ) -> RelativeDirection:
        """
        Calculate relative direction for a single link.
        
        Args:
            link_heading: Absolute heading to the adjacent point
            agent_heading: Agent's current heading
            
        Returns:
            RelativeDirection object
        """
        relative_angle = self.get_relative_angle(link_heading, agent_heading)
        description = self.angle_to_direction(relative_angle)
        
        return RelativeDirection(
            description=description,
            relative_angle=relative_angle,
            absolute_heading=link_heading
        )
    
    def calculate_available_moves(
        self,
        links: List[Dict],
        agent_heading: float,
        current_location: Optional[Tuple[float, float]] = None,
        locations: Optional[Dict[str, Tuple[float, float]]] = None
    ) -> List[Dict]:
        """
        Calculate available moves with relative directions and distances.
        
        Args:
            links: List of adjacent panoramas [{panoId, heading}, ...]
            agent_heading: Agent's current heading (true north reference)
            current_location: Current (lat, lng) for distance calculation
            locations: Dict of pano_id -> (lat, lng) for distance calculation
            
        Returns:
            List of available moves:
            [
                {
                    "id": 1,
                    "pano_id": "xxx",
                    "direction": "front-left 15°",
                    "distance": 10.5,
                    "heading": 345  (true north reference)
                },
                ...
            ]
        """
        moves = []
        
        for idx, link in enumerate(links, start=1):
            pano_id = link.get('panoId') or link.get('pano_id')
            # link.heading is already true north reference (verified)
            heading = float(link.get('heading', 0))
            
            # Calculate relative direction
            rel_dir = self.calculate_relative_direction(heading, agent_heading)
            
            move = {
                "id": idx,
                "pano_id": pano_id,
                "direction": rel_dir.description,
                "heading": heading  # Already true north reference
            }
            
            # Calculate distance if locations provided
            if current_location and locations and pano_id in locations:
                target_location = locations[pano_id]
                distance = calculate_distance(
                    current_location[0], current_location[1],
                    target_location[0], target_location[1]
                )
                move["distance"] = round(distance, 1)
            
            moves.append(move)
        
        return moves
    
    @staticmethod
    def sort_moves_by_direction(moves: List[Dict]) -> List[Dict]:
        """
        Sort moves by relative direction (front first, then clockwise).
        
        This helps agents understand the spatial layout better.
        """
        def direction_priority(move: Dict) -> float:
            direction = move.get('direction', '')
            
            # Extract angle from direction string
            if direction == 'front':
                return 0
            elif direction == 'right':
                return 90
            elif direction == 'back':
                return 180
            elif direction == 'left':
                return 270
            elif 'front-right' in direction:
                # Extract angle
                try:
                    angle = float(direction.split()[-1].replace('°', ''))
                    return angle
                except:
                    return 45
            elif 'right-back' in direction:
                try:
                    angle = float(direction.split()[-1].replace('°', ''))
                    return 90 + angle
                except:
                    return 135
            elif 'left-back' in direction:
                try:
                    angle = float(direction.split()[-1].replace('°', ''))
                    return 270 - angle
                except:
                    return 225
            elif 'front-left' in direction:
                try:
                    angle = float(direction.split()[-1].replace('°', ''))
                    return 360 - angle
                except:
                    return 315
            return 180  # Default to back
        
        sorted_moves = sorted(moves, key=direction_priority)
        
        # Re-assign IDs based on new order
        for idx, move in enumerate(sorted_moves, start=1):
            move['id'] = idx
        
        return sorted_moves


# Global instance
direction_calculator = DirectionCalculator()
