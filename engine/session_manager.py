"""
SessionManager - Manages VLN evaluation sessions.

Handles session lifecycle: creation, state management, and cleanup.
Supports concurrent sessions with isolated state.
"""
import json
import uuid
from pathlib import Path
from datetime import datetime
from typing import Optional, Dict, List, Any
from dataclasses import dataclass, field, asdict
from enum import Enum

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings, TASKS_DIR
from .cache_manager import cache_manager
from .metadata_cache import metadata_cache


class SessionStatus(str, Enum):
    """Session status values."""
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    STOPPED = "stopped"
    ERROR = "error"


class SessionMode(str, Enum):
    """Session mode - agent or human."""
    AGENT = "agent"
    HUMAN = "human"


@dataclass
class SessionState:
    """Current state of a session."""
    pano_id: str
    heading: float = 0.0
    pitch: float = 0.0
    fov: float = 90.0
    lat: Optional[float] = None
    lng: Optional[float] = None
    capture_date: Optional[str] = None


@dataclass
class Session:
    """Represents a VLN evaluation session."""
    session_id: str
    agent_id: str
    task_id: str
    mode: SessionMode = SessionMode.AGENT
    status: SessionStatus = SessionStatus.RUNNING
    state: SessionState = None
    step_count: int = 0
    start_time: datetime = None
    elapsed_time: float = 0.0
    trajectory: List[str] = field(default_factory=list)
    task_config: Dict = field(default_factory=dict)
    done_reason: Optional[str] = None
    agent_answer: Optional[str] = None
    
    def __post_init__(self):
        if self.start_time is None:
            self.start_time = datetime.now()
    
    def to_dict(self) -> Dict:
        """Convert session to dictionary."""
        return {
            'session_id': self.session_id,
            'agent_id': self.agent_id,
            'task_id': self.task_id,
            'mode': self.mode.value,
            'status': self.status.value,
            'state': asdict(self.state) if self.state else None,
            'step_count': self.step_count,
            'start_time': self.start_time.isoformat() if self.start_time else None,
            'elapsed_time': self.elapsed_time,
            'trajectory': self.trajectory,
            'done_reason': self.done_reason,
            'agent_answer': self.agent_answer
        }
    
    @property
    def geofence(self) -> Optional[str]:
        """Get the geofence list name for this session's task."""
        # Support both navigation (geofence) and height task (geofence_id) formats
        return self.task_config.get('geofence') or self.task_config.get('geofence_id')


class SessionManager:
    """
    Manages VLN evaluation sessions.
    
    Features:
    - Session creation and lifecycle management
    - State persistence in SQLite
    - Concurrent session support
    - Task configuration loading
    """
    
    def __init__(self):
        """Initialize the session manager."""
        self._sessions: Dict[str, Session] = {}
        self._task_configs: Dict[str, Dict] = {}
    
    def _generate_session_id(self, agent_id: str, task_id: str) -> str:
        """Generate a unique session ID."""
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        return f"{agent_id}_{task_id}_{timestamp}"
    
    def _load_task_config(self, task_id: str) -> Optional[Dict]:
        """Load task configuration from file."""
        if task_id in self._task_configs:
            return self._task_configs[task_id]
        
        task_path = TASKS_DIR / f"{task_id}.json"
        if not task_path.exists():
            return None
        
        with open(task_path, 'r', encoding='utf-8') as f:
            config = json.load(f)
        
        self._task_configs[task_id] = config
        return config
    
    def create_session(
        self,
        agent_id: str,
        task_id: str,
        mode: str = "agent"
    ) -> Optional[Session]:
        """
        Create a new evaluation session.
        
        Args:
            agent_id: Agent or player identifier
            task_id: Task identifier
            mode: 'agent' or 'human'
            
        Returns:
            Created Session or None if task not found
        """
        # Load task configuration
        task_config = self._load_task_config(task_id)
        if task_config is None:
            return None
        
        # Generate session ID
        session_id = self._generate_session_id(agent_id, task_id)
        
        # Get spawn point metadata (support both navigation and height task formats)
        spawn_pano_id = task_config.get('spawn_point') or task_config.get('spawn_pano_id')
        spawn_heading = task_config.get('spawn_heading', 0)
        
        if not spawn_pano_id:
            print(f"[SessionManager] Error: No spawn point found in task config for {task_id}")
            return None
        
        # Try to get location from cache
        location = metadata_cache.get_location(spawn_pano_id)
        metadata = metadata_cache.get(spawn_pano_id)
        
        # Create initial state
        state = SessionState(
            pano_id=spawn_pano_id,
            heading=spawn_heading,
            pitch=settings.RENDER_DEFAULT_PITCH,
            fov=settings.RENDER_DEFAULT_FOV,
            lat=location[0] if location else None,
            lng=location[1] if location else None,
            capture_date=metadata.get('capture_date') if metadata else None
        )
        
        # Create session
        session = Session(
            session_id=session_id,
            agent_id=agent_id,
            task_id=task_id,
            mode=SessionMode(mode),
            state=state,
            trajectory=[spawn_pano_id],
            task_config=task_config
        )
        
        # Store in memory
        self._sessions[session_id] = session
        
        # Persist to database
        # DISABLED: Avoid database lock issues during parallel execution
        # self._save_session_to_db(session)
        
        return session
    
    def get_session(self, session_id: str) -> Optional[Session]:
        """Get a session by ID."""
        return self._sessions.get(session_id)
    
    def update_session_state(
        self,
        session_id: str,
        new_state: SessionState,
        increment_step: bool = True
    ) -> bool:
        """
        Update session state after an action.
        
        Args:
            session_id: Session ID
            new_state: New state
            increment_step: Whether to increment step count
            
        Returns:
            True if updated successfully
        """
        session = self._sessions.get(session_id)
        if session is None:
            return False
        
        session.state = new_state
        if increment_step:
            session.step_count += 1
        
        # Update elapsed time
        if session.start_time:
            session.elapsed_time = (datetime.now() - session.start_time).total_seconds()
        
        # Add to trajectory if moved to new pano
        if new_state.pano_id not in session.trajectory or session.trajectory[-1] != new_state.pano_id:
            session.trajectory.append(new_state.pano_id)
        
        # Persist
        # DISABLED: Avoid database lock issues during parallel execution
        # self._save_session_to_db(session)
        
        return True
    
    def end_session(
        self,
        session_id: str,
        reason: str = "stopped",
        answer: Optional[str] = None
    ) -> Optional[Session]:
        """
        End a session.
        
        Args:
            session_id: Session ID
            reason: Reason for ending (stopped/max_steps/max_time)
            answer: Agent's final answer (for stop action)
            
        Returns:
            Ended session or None
        """
        session = self._sessions.get(session_id)
        if session is None:
            return None
        
        session.status = SessionStatus.COMPLETED
        session.done_reason = reason
        session.agent_answer = answer
        
        if session.start_time:
            session.elapsed_time = (datetime.now() - session.start_time).total_seconds()
        
        # Persist
        # DISABLED: Avoid database lock issues during parallel execution
        # self._save_session_to_db(session)
        
        return session
    
    def pause_session(self, session_id: str) -> bool:
        """Pause a human evaluation session."""
        session = self._sessions.get(session_id)
        if session is None or session.mode != SessionMode.HUMAN:
            return False
        
        session.status = SessionStatus.PAUSED
        # DISABLED: Avoid database lock issues during parallel execution
        # self._save_session_to_db(session)
        return True
    
    def resume_session(self, session_id: str) -> Optional[Session]:
        """Resume a paused session."""
        # Try memory first
        session = self._sessions.get(session_id)
        
        # Try database if not in memory
        if session is None:
            session = self._load_session_from_db(session_id)
            if session:
                self._sessions[session_id] = session
        
        if session is None:
            return None
        
        if session.status == SessionStatus.PAUSED:
            session.status = SessionStatus.RUNNING
            # DISABLED: Avoid database lock issues during parallel execution
            # self._save_session_to_db(session)
        
        return session
    
    def check_termination(self, session_id: str) -> Optional[str]:
        """
        Check if session should terminate.
        
        Returns:
            Termination reason or None if should continue
        """
        session = self._sessions.get(session_id)
        if session is None:
            return "session_not_found"
        
        task_config = session.task_config
        
        # Check max steps
        max_steps = task_config.get('max_steps')
        if max_steps and session.step_count >= max_steps:
            return "max_steps"
        
        # Check max time
        max_time = task_config.get('max_time_seconds')
        if max_time and session.elapsed_time >= max_time:
            return "max_time"
        
        # Check if reached target (DISABLED - agent must explicitly stop)
        # target_panos = task_config.get('target_pano_ids', [])
        # if target_panos and session.state.pano_id in target_panos:
        #     return "reached_target"
        
        return None
    
    def get_all_sessions(self, status: Optional[str] = None) -> List[Session]:
        """Get all sessions, optionally filtered by status."""
        sessions = list(self._sessions.values())
        if status:
            sessions = [s for s in sessions if s.status.value == status]
        return sessions
    
    def cleanup_session(self, session_id: str, delete_images: bool = None):
        """
        Clean up a session and its resources.
        
        Args:
            session_id: Session ID
            delete_images: Whether to delete temporary images.
                           Defaults to settings.AUTO_DELETE_TEMP_IMAGES.
        """
        if delete_images is None:
            delete_images = settings.AUTO_DELETE_TEMP_IMAGES
        
        if delete_images:
            from .observation_generator import ObservationGenerator
            generator = ObservationGenerator()
            generator.cleanup_session_images(session_id)
        
        # Remove from memory
        if session_id in self._sessions:
            del self._sessions[session_id]
    
    def _save_session_to_db(self, session: Session):
        """Persist session to database."""
        with cache_manager.get_connection() as conn:
            conn.execute('''
                INSERT OR REPLACE INTO sessions 
                (session_id, agent_id, task_id, mode, status,
                 current_pano_id, current_heading, current_pitch, current_fov,
                 step_count, elapsed_time, trajectory, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ''', (
                session.session_id,
                session.agent_id,
                session.task_id,
                session.mode.value,
                session.status.value,
                session.state.pano_id if session.state else None,
                session.state.heading if session.state else 0,
                session.state.pitch if session.state else 0,
                session.state.fov if session.state else 90,
                session.step_count,
                session.elapsed_time,
                json.dumps(session.trajectory),
                datetime.now().isoformat()
            ))
    
    def _load_session_from_db(self, session_id: str) -> Optional[Session]:
        """Load session from database."""
        with cache_manager.get_connection() as conn:
            cursor = conn.execute(
                'SELECT * FROM sessions WHERE session_id = ?',
                (session_id,)
            )
            row = cursor.fetchone()
            if row is None:
                return None
            
            # Load task config
            task_config = self._load_task_config(row['task_id'])
            
            # Reconstruct session
            state = SessionState(
                pano_id=row['current_pano_id'],
                heading=row['current_heading'],
                pitch=row['current_pitch'],
                fov=row['current_fov']
            )
            
            return Session(
                session_id=row['session_id'],
                agent_id=row['agent_id'],
                task_id=row['task_id'],
                mode=SessionMode(row['mode']),
                status=SessionStatus(row['status']),
                state=state,
                step_count=row['step_count'],
                elapsed_time=row['elapsed_time'],
                trajectory=json.loads(row['trajectory']) if row['trajectory'] else [],
                task_config=task_config or {}
            )


# Global instance
session_manager = SessionManager()
