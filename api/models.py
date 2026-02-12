"""
Pydantic models for API requests and responses.
"""
from typing import List, Optional, Dict, Any
from pydantic import BaseModel, Field
from enum import Enum


# === Enums ===

class ActionType(str, Enum):
    """Supported action types."""
    MOVE = "move"
    ROTATION = "rotation"
    STOP = "stop"


class SessionStatus(str, Enum):
    """Session status values."""
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    TIMEOUT = "timeout"
    STOPPED = "stopped"
    ERROR = "error"


# === Request Models ===

class CreateSessionRequest(BaseModel):
    """Request to create a new session."""
    agent_id: str = Field(..., description="Agent or player identifier")
    task_id: str = Field(..., description="Task identifier")
    mode: str = Field("agent", description="Session mode: 'agent' or 'human'")


class ActionRequest(BaseModel):
    """Request to execute an action."""
    type: ActionType = Field(..., description="Action type")
    move_id: Optional[int] = Field(None, description="Move ID for 'move' action")
    heading: Optional[float] = Field(None, description="Heading for 'rotation' action (0-360)")
    pitch: Optional[float] = Field(None, description="Pitch for 'rotation' action (-85 to 85)")
    fov: Optional[float] = Field(None, description="FOV for 'rotation' action (30-100)")
    answer: Optional[str] = Field(None, description="Answer for 'stop' action")
    agent_vlm_duration_seconds: Optional[float] = Field(None, description="Time taken for VLM generation (seconds)")
    agent_total_duration_seconds: Optional[float] = Field(None, description="Total step processing time (seconds)")


class PreloadRequest(BaseModel):
    """Request to preload panoramas for a task."""
    zoom_level: Optional[int] = Field(None, description="Zoom level (0-5), defaults to settings")


# === Response Models ===

class AvailableMove(BaseModel):
    """An available move option."""
    id: int = Field(..., description="Move ID (1-indexed)")
    direction: str = Field(..., description="Direction description (e.g., 'front-left 15°')")
    distance: Optional[float] = Field(None, description="Distance in meters")
    heading: Optional[float] = Field(None, description="Absolute heading to this move (true north reference)")


class Observation(BaseModel):
    """Agent observation."""
    task_description: str = Field(..., description="Task description")
    current_image: Optional[str] = Field(None, description="URL to current view image (perspective for agent)")
    panorama_url: Optional[str] = Field(None, description="URL to full panorama image (for human 360° view)")
    heading: float = Field(0.0, description="Current heading (0-360, true north reference)")
    pitch: float = Field(0.0, description="Current pitch (-85 to 85)")
    fov: float = Field(90.0, description="Current FOV (30-100)")
    center_heading: float = Field(0.0, description="Panorama tile origin heading for coordinate conversion")
    available_moves: List[AvailableMove] = Field(default_factory=list)


class SessionState(BaseModel):
    """Current session state."""
    pano_id: str
    heading: float
    pitch: float
    fov: float
    lat: Optional[float] = None
    lng: Optional[float] = None
    capture_date: Optional[str] = None


class CreateSessionResponse(BaseModel):
    """Response from session creation."""
    session_id: str
    observation: Observation


class SessionStateResponse(BaseModel):
    """Response with session state."""
    session_id: str
    status: SessionStatus
    step_count: int
    elapsed_time: float
    observation: Observation


class ActionResponse(BaseModel):
    """Response from action execution."""
    success: bool
    observation: Optional[Observation] = None
    done: bool = False
    done_reason: Optional[str] = None
    error: Optional[str] = None


class EndSessionResponse(BaseModel):
    """Response from ending a session."""
    status: str
    total_steps: int
    elapsed_time: float
    log_path: str


class TaskInfo(BaseModel):
    """Task summary info."""
    task_id: str
    description: str


class TaskDetail(BaseModel):
    """Full task details."""
    task_id: str
    spawn_point: str
    spawn_heading: float
    description: str
    answer: Optional[str] = None
    target_pano_ids: Optional[List[str]] = None
    max_steps: Optional[int] = None
    max_time_seconds: Optional[int] = None


class TaskListResponse(BaseModel):
    """Response with list of tasks."""
    tasks: List[TaskInfo]


class PreloadStatusResponse(BaseModel):
    """Response with preload status."""
    status: str  # pending / in_progress / completed / failed
    progress: int = 0
    total: int = 0
    percentage: float = 0.0
    message: Optional[str] = None


class GeofenceInfo(BaseModel):
    """Geofence summary info."""
    name: str
    pano_count: int


class GeofenceListResponse(BaseModel):
    """Response with list of geofences."""
    geofences: List[GeofenceInfo]


class PlayerProgress(BaseModel):
    """Player progress info."""
    task_id: str
    status: str  # not_started / in_progress / completed
    score: Optional[float] = None
    session_id: Optional[str] = None


class PlayerProgressResponse(BaseModel):
    """Response with player progress."""
    player_id: str
    total_tasks: int
    completed: int
    in_progress: int
    not_started: int
    tasks: List[PlayerProgress]


class ResumeSessionResponse(BaseModel):
    """Response from resuming a session."""
    success: bool
    observation: Optional[Observation] = None
    restored_state: Optional[Dict[str, Any]] = None
    error: Optional[str] = None


class PauseSessionResponse(BaseModel):
    """Response from pausing a session."""
    success: bool
    status: str
    can_resume: bool



class ErrorResponse(BaseModel):
    """Error response."""
    error: str
    detail: Optional[str] = None


class SessionLogEntry(BaseModel):
    """A single entry in the session log."""
    event: str
    session_id: str
    timestamp: str
    step: Optional[int] = None
    state: Optional[Dict[str, Any]] = None
    action: Optional[Dict[str, Any]] = None
    available_moves: Optional[List[Dict[str, Any]]] = None
    image_path: Optional[str] = None
    agent_type: Optional[str] = None
    response_time_ms: Optional[int] = None
    reached_target: Optional[bool] = None
    agent_answer: Optional[str] = None
    trajectory: Optional[List[Any]] = None


class SessionInfo(BaseModel):
    """Summary info for a session."""
    session_id: str
    agent_id: Optional[str] = None
    task_id: Optional[str] = None
    mode: Optional[str] = None
    start_time: Optional[str] = None
    total_steps: Optional[int] = None
    status: Optional[str] = None


class SessionListResponse(BaseModel):
    """Response with list of sessions."""
    sessions: List[SessionInfo]


class SessionLogResponse(BaseModel):
    """Response with full session log."""
    session_id: str
    entries: List[Dict[str, Any]]

