"""
ActionExecutor - Executes agent actions and updates session state.

Handles move, rotation, and stop actions with validation.
"""
from pathlib import Path
from typing import Dict, Optional, Any, Tuple
from dataclasses import asdict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings
from .metadata_cache import metadata_cache
from .session_manager import session_manager, Session, SessionState
from .direction_calculator import direction_calculator
from .geofence_checker import geofence_checker
from .observation_generator import get_observation_generator


class ActionResult:
    """Result of an action execution."""
    
    def __init__(
        self,
        success: bool,
        observation: Optional[Dict] = None,
        done: bool = False,
        done_reason: Optional[str] = None,
        error: Optional[str] = None
    ):
        self.success = success
        self.observation = observation
        self.done = done
        self.done_reason = done_reason
        self.error = error
    
    def to_dict(self) -> Dict:
        return {
            'success': self.success,
            'observation': self.observation,
            'done': self.done,
            'done_reason': self.done_reason,
            'error': self.error
        }


class ActionExecutor:
    """
    Executes agent actions within a session.
    
    Supported actions:
    - move: Move to an adjacent panorama
    - rotation: Change view angle (heading, pitch, fov)
    - stop: End the session with an optional answer
    """
    
    def execute(
        self,
        session_id: str,
        action: Dict[str, Any]
    ) -> ActionResult:
        """
        Execute an action in a session.
        
        Args:
            session_id: Session ID
            action: Action dict with 'type' and type-specific params
            
        Returns:
            ActionResult with success status and new observation
        """
        session = session_manager.get_session(session_id)
        if session is None:
            return ActionResult(False, error="Session not found")
        
        if session.status.value not in ("running", "paused"):
            return ActionResult(False, error=f"Session is {session.status.value}")
        
        action_type = action.get('type')
        
        if action_type == 'move':
            return self._execute_move(session, action)
        elif action_type == 'rotation':
            return self._execute_rotation(session, action)
        elif action_type == 'stop':
            return self._execute_stop(session, action)
        else:
            return ActionResult(False, error=f"Unknown action type: {action_type}")
    
    def _execute_move(self, session: Session, action: Dict) -> ActionResult:
        """Execute a move action."""
        move_id = action.get('move_id')
        if move_id is None:
            return ActionResult(False, error="move_id is required")
        
        # Get current state
        current_state = session.state
        current_pano_id = current_state.pano_id
        
        # Get available moves
        available_moves = self._get_available_moves(session)
        if not available_moves:
            return ActionResult(False, error="No available moves")
        
        # Find the move by ID
        target_move = None
        for move in available_moves:
            if move['id'] == move_id:
                target_move = move
                break
        
        if target_move is None:
            return ActionResult(
                False, 
                error=f"Invalid move_id: {move_id}. Available: {[m['id'] for m in available_moves]}"
            )
        
        # Get target panorama
        target_pano_id = target_move['pano_id']
        
        # Validate against geofence
        if not geofence_checker.is_valid(session.geofence, target_pano_id):
            return ActionResult(False, error="Move target is outside geofence")
        
        # Get target location
        target_location = metadata_cache.get_location(target_pano_id)
        target_metadata = metadata_cache.get(target_pano_id)
        
        # Create new state
        # When moving, face the direction of movement
        new_state = SessionState(
            pano_id=target_pano_id,
            heading=target_move['heading'],  # Face the direction we moved
            pitch=current_state.pitch,
            fov=settings.RENDER_DEFAULT_FOV,
            lat=target_location[0] if target_location else None,
            lng=target_location[1] if target_location else None,
            capture_date=target_metadata.get('capture_date') if target_metadata else None
        )
        
        # Update session
        session_manager.update_session_state(session.session_id, new_state)
        
        # Check termination
        term_reason = session_manager.check_termination(session.session_id)
        if term_reason:
            session_manager.end_session(session.session_id, term_reason)
            return ActionResult(
                success=True,
                observation=self._generate_observation(session, new_state),
                done=True,
                done_reason=term_reason
            )
        
        return ActionResult(
            success=True,
            observation=self._generate_observation(session, new_state),
            done=False
        )
    
    def _execute_rotation(self, session: Session, action: Dict) -> ActionResult:
        """Execute a rotation action."""
        current_state = session.state
        
        # Get new angles (use current if not specified)
        new_heading = action.get('heading', current_state.heading)
        new_pitch = action.get('pitch', current_state.pitch)
        new_fov = 90.0
        
        # Validate ranges
        new_heading = new_heading % 360
        new_pitch = max(-85, min(85, new_pitch))
        # Force FOV to be fixed at default (90)
        new_fov = settings.RENDER_DEFAULT_FOV
        
        # Create new state
        new_state = SessionState(
            pano_id=current_state.pano_id,
            heading=new_heading,
            pitch=new_pitch,
            fov=new_fov,
            lat=current_state.lat,
            lng=current_state.lng,
            capture_date=current_state.capture_date
        )
        
        # Update session (rotation doesn't count as a step for termination)
        session_manager.update_session_state(
            session.session_id, 
            new_state, 
            increment_step=True  # Still count for logging
        )
        
        return ActionResult(
            success=True,
            observation=self._generate_observation(session, new_state),
            done=False
        )
    
    def _execute_stop(self, session: Session, action: Dict) -> ActionResult:
        """Execute a stop action."""
        answer = action.get('answer', '')
        
        # End session
        session_manager.end_session(session.session_id, "stopped", answer)
        
        return ActionResult(
            success=True,
            observation=self._generate_observation(session, session.state),
            done=True,
            done_reason="stopped"
        )
    
    def _get_available_moves(self, session: Session) -> list:
        """Get available moves for current position."""
        current_pano_id = session.state.pano_id
        
        # Get metadata including center_heading
        metadata = metadata_cache.get(current_pano_id)
        if not metadata:
            return []
        
        links = metadata.get('links', [])
        if not links:
            return []
        
        # Filter by geofence
        links = geofence_checker.filter_links(session.geofence, links)
        
        # Get current location for distance calculation
        current_location = (session.state.lat, session.state.lng)
        if current_location[0] is None:
            current_location = metadata_cache.get_location(current_pano_id)
        
        # Get locations for all link targets
        link_pano_ids = [l.get('panoId') or l.get('pano_id') for l in links]
        locations = metadata_cache.get_all_locations(link_pano_ids)
        
        # Calculate available moves with directions
        # Note: link.heading is already true north reference (verified)
        moves = direction_calculator.calculate_available_moves(
            links,
            session.state.heading,
            current_location,
            locations
        )
        
        # Sort by direction (front first)
        moves = direction_calculator.sort_moves_by_direction(moves)
        
        return moves
    
    def _generate_observation(
        self,
        session: Session,
        state: SessionState
    ) -> Dict:
        """Generate observation dict for agent."""
        from .session_manager import SessionMode
        
        # Generate view image
        try:
            generator = get_observation_generator()
            image_result = generator.generate_observation(
                pano_id=state.pano_id,
                heading=state.heading,
                pitch=state.pitch,
                fov=state.fov,
                session_id=session.session_id,
                step=session.step_count
            )
            image_url = f"/temp_images/{session.session_id}/step_{session.step_count}.jpg"
        except Exception as e:
            # If image generation fails, return None for image
            image_result = None
            image_url = None
        
        # Get available moves
        available_moves = self._get_available_moves(session)
        
        # Get center_heading for panorama coordinate conversion
        pano_metadata = metadata_cache.get(state.pano_id)
        center_heading = 0.0
        if pano_metadata:
            center_heading = pano_metadata.get('center_heading', 0.0) or 0.0
        
        # Build observation
        observation = {
            'task_description': session.task_config.get('description', ''),
            'current_image': image_url,
            'available_moves': [
                {
                    'id': m['id'],
                    'direction': m['direction'],
                    'distance': m.get('distance'),
                    'heading': m.get('heading')  # Add absolute heading for dynamic updates
                }
                for m in available_moves
            ],
            'heading': state.heading,
            'pitch': state.pitch,
            'fov': state.fov,
            'center_heading': center_heading
        }
        
        # Add panorama_url for human mode (360° interactive viewing)
        is_human_mode = (session.mode == SessionMode.HUMAN or 
                         session.mode.value == "human" or 
                         str(session.mode) == "SessionMode.HUMAN")
        
        if is_human_mode:
            pano_id = state.pano_id
            zoom_level = settings.PANORAMA_ZOOM_LEVEL
            observation['panorama_url'] = f"/data/panoramas/{pano_id}_z{zoom_level}.jpg"
            print(f"[Human Mode] _generate_observation: panorama_url = {observation['panorama_url']}, center_heading = {center_heading}")
        
        return observation


# Global instance
action_executor = ActionExecutor()
