"""
API Routes for VLN Benchmark Platform.

Implements all HTTP endpoints for session management, actions, and tasks.
"""
import json
import asyncio
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, BackgroundTasks

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import settings, TASKS_DIR
from engine.session_manager import session_manager, SessionStatus as EngineSessionStatus
from engine.action_executor import action_executor
from engine.logger import session_logger
from engine.geofence_checker import geofence_checker
from engine.observation_generator import get_observation_generator

from .models import (
    CreateSessionRequest, CreateSessionResponse,
    ActionRequest, ActionResponse,
    SessionStateResponse, EndSessionResponse,
    TaskListResponse, TaskInfo, TaskDetail,
    PreloadRequest, PreloadStatusResponse,
    PlayerProgressResponse, PlayerProgress,
    ResumeSessionResponse, PauseSessionResponse,
    Observation, AvailableMove, SessionStatus,
    ErrorResponse, SessionInfo, SessionListResponse, SessionLogResponse,
    GeofenceInfo, GeofenceListResponse
)



router = APIRouter(prefix="/api", tags=["VLN Benchmark"])


# === Session Management ===

@router.post("/session/create", response_model=CreateSessionResponse)
async def create_session(request: CreateSessionRequest):
    """
    Create a new evaluation session.
    
    Creates a session for the specified agent and task, returning
    the initial observation.
    """
    session = session_manager.create_session(
        agent_id=request.agent_id,
        task_id=request.task_id,
        mode=request.mode
    )
    
    if session is None:
        raise HTTPException(status_code=404, detail=f"Task not found: {request.task_id}")
    
    # Log session start
    session_logger.log_session_start(session)
    
    # Generate initial view image
    try:
        generator = get_observation_generator()
        generator.generate_observation(
            pano_id=session.state.pano_id,
            heading=session.state.heading,
            pitch=session.state.pitch,
            fov=session.state.fov,
            session_id=session.session_id,
            step=session.step_count
        )
    except Exception as e:
        print(f"Error generating initial observation: {e}")
    
    # Generate initial observation
    initial_observation = _build_observation(session)
    
    return CreateSessionResponse(
        session_id=session.session_id,
        observation=initial_observation
    )


@router.get("/session/{session_id}/state", response_model=SessionStateResponse)
async def get_session_state(session_id: str):
    """
    Get current session state.
    
    Returns the current status and observation for the session.
    """
    session = session_manager.get_session(session_id)
    
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    observation = _build_observation(session)
    
    return SessionStateResponse(
        session_id=session.session_id,
        status=SessionStatus(session.status.value),
        step_count=session.step_count,
        elapsed_time=session.elapsed_time,
        observation=observation
    )


@router.post("/session/{session_id}/action", response_model=ActionResponse)
async def execute_action(session_id: str, request: ActionRequest):
    """
    Execute an action in a session.
    
    Supports move, rotation, and stop actions.
    """
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Build action dict
    action = {"type": request.type.value}
    if request.move_id is not None:
        action["move_id"] = request.move_id
    if request.heading is not None:
        action["heading"] = request.heading
    if request.pitch is not None:
        action["pitch"] = request.pitch
    if request.fov is not None:
        action["fov"] = request.fov
    if request.answer is not None:
        action["answer"] = request.answer
    if request.agent_vlm_duration_seconds is not None:
        action["agent_vlm_duration_seconds"] = request.agent_vlm_duration_seconds
    if request.agent_total_duration_seconds is not None:
        action["agent_total_duration_seconds"] = request.agent_total_duration_seconds
    
    # Execute action
    result = action_executor.execute(session_id, action)
    
    # Log action
    if result.success:
        session = session_manager.get_session(session_id)
        available_moves = _get_available_moves(session)
        session_logger.log_action(session, action, result.to_dict(), available_moves)
        
        # Log session end if done
        if result.done:
            session_logger.log_session_end(session)
    
    # Build response
    observation = None
    if result.observation:
        observation = Observation(
            task_description=result.observation.get('task_description', ''),
            current_image=result.observation.get('current_image'),
            panorama_url=result.observation.get('panorama_url'),
            heading=result.observation.get('heading', 0.0),
            pitch=result.observation.get('pitch', 0.0),
            fov=result.observation.get('fov', 90.0),
            center_heading=result.observation.get('center_heading', 0.0),
            available_moves=[
                AvailableMove(**m) for m in result.observation.get('available_moves', [])
            ]
        )
    
    return ActionResponse(
        success=result.success,
        observation=observation,
        done=result.done,
        done_reason=result.done_reason,
        error=result.error
    )


@router.post("/session/{session_id}/end", response_model=EndSessionResponse)
async def end_session(session_id: str):
    """
    End a session manually.
    
    Terminates the session and returns summary information.
    """
    session = session_manager.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # End session
    session = session_manager.end_session(session_id, "manual_end")
    
    # Log end
    session_logger.log_session_end(session)
    
    return EndSessionResponse(
        status=session.status.value,
        total_steps=session.step_count,
        elapsed_time=session.elapsed_time,
        log_path=str(session_logger.get_log_path(session_id))
    )


@router.post("/session/{session_id}/pause", response_model=PauseSessionResponse)
async def pause_session(session_id: str):
    """
    Pause a human evaluation session.
    
    Only works for human mode sessions.
    """
    success = session_manager.pause_session(session_id)
    
    if not success:
        raise HTTPException(status_code=400, detail="Cannot pause this session")
    
    return PauseSessionResponse(
        success=True,
        status="paused",
        can_resume=True
    )


@router.post("/session/{session_id}/resume", response_model=ResumeSessionResponse)
async def resume_session(session_id: str):
    """
    Resume a paused session.
    
    Restores session state and returns current observation.
    """
    session = session_manager.resume_session(session_id)
    
    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or cannot resume")
    
    observation = _build_observation(session)
    
    return ResumeSessionResponse(
        success=True,
        observation=observation,
        restored_state={
            "step_count": session.step_count,
            "elapsed_time": session.elapsed_time,
            "trajectory_length": len(session.trajectory)
        }
    )



@router.get("/sessions", response_model=SessionListResponse)
async def list_sessions():
    """
    List all available session logs.
    """
    sessions = []
    
    # Get all log files
    for log_file in session_logger.logs_dir.rglob("*.jsonl"):
        session_id = log_file.stem
        
        # Read summary from end of file
        summary = session_logger.get_session_summary(session_id)
        
        # Read start info from beginning of file
        start_info = None
        try:
            with open(log_file, 'r', encoding='utf-8') as f:
                first_line = f.readline()
                if first_line:
                    start_info = json.loads(first_line)
        except Exception:
            pass
            
        info = SessionInfo(
            session_id=session_id,
            agent_id=start_info.get('agent_id') if start_info else None,
            task_id=start_info.get('task_id') if start_info else None,
            mode=start_info.get('mode') if start_info else None,
            start_time=start_info.get('timestamp') if start_info else None,
            total_steps=summary.get('total_steps') if summary else 0,
            status=summary.get('status') if summary else "running" # simplistic assumption
        )
        sessions.append(info)
    
    # Sort by timestamp descending
    sessions.sort(key=lambda s: s.start_time or "", reverse=True)
    
    return SessionListResponse(sessions=sessions)


@router.get("/sessions/{session_id}/log", response_model=SessionLogResponse)
async def get_session_log(session_id: str):
    """
    Get full log for a session.
    """
    entries = session_logger.read_session_log(session_id)
    
    if not entries:
         raise HTTPException(status_code=404, detail="Session log not found or empty")
         
    return SessionLogResponse(
        session_id=session_id,
        entries=entries
    )


# === Task Management ===


@router.get("/tasks", response_model=TaskListResponse)
async def list_tasks():
    """
    Get list of all available tasks.
    """
    tasks = []
    
    for task_file in TASKS_DIR.glob("*.json"):
        try:
            with open(task_file, 'r', encoding='utf-8') as f:
                config = json.load(f)
                # Use filename as authoritative task_id
                tasks.append(TaskInfo(
                    task_id=task_file.stem,
                    description=config.get('description', '')
                ))
        except Exception as e:
            continue
    
    return TaskListResponse(tasks=tasks)


@router.get("/tasks/{task_id}", response_model=TaskDetail)
async def get_task(task_id: str):
    """
    Get full task details.
    """
    task_path = TASKS_DIR / f"{task_id}.json"
    
    if not task_path.exists():
        raise HTTPException(status_code=404, detail="Task not found")
    
    with open(task_path, 'r', encoding='utf-8') as f:
        config = json.load(f)
    
    # Ensure task_id matches filename
    real_task_id = task_path.stem
    
    return TaskDetail(
        task_id=real_task_id,
        spawn_point=config.get('spawn_point', ''),
        spawn_heading=config.get('spawn_heading', 0),
        description=config.get('description', ''),
        answer=config.get('answer'),
        target_pano_ids=config.get('target_pano_ids'),
        max_steps=config.get('max_steps'),
        max_time_seconds=config.get('max_time_seconds')
    )


# Preload status tracking (simple in-memory)
_preload_status = {}


@router.post("/tasks/{task_id}/preload", response_model=PreloadStatusResponse)
async def preload_task(task_id: str, request: PreloadRequest, background_tasks: BackgroundTasks):
    """
    Start preloading panoramas for a task.
    
    Downloads all panoramas in the task's geofence.
    """
    # Load task config to get geofence name
    task_path = TASKS_DIR / f"{task_id}.json"
    if not task_path.exists():
        raise HTTPException(status_code=404, detail=f"Task not found: {task_id}")
    
    with open(task_path, 'r', encoding='utf-8') as f:
        task_config = json.load(f)
    
    geofence_name = task_config.get('geofence')
    if not geofence_name:
        raise HTTPException(status_code=404, detail="No geofence specified in task")
    
    # Get geofence by name
    geofence = geofence_checker.get_geofence(geofence_name)
    if not geofence:
        raise HTTPException(status_code=404, detail=f"Geofence not found: {geofence_name}")
    
    total = len(geofence)
    zoom_level = request.zoom_level or settings.PANORAMA_ZOOM_LEVEL
    
    # Initialize status
    _preload_status[task_id] = {
        "status": "in_progress",
        "progress": 0,
        "total": total,
        "message": f"Preloading {total} panoramas at zoom level {zoom_level}"
    }
    
    # Start background task
    background_tasks.add_task(_preload_panoramas, task_id, list(geofence), zoom_level)
    
    return PreloadStatusResponse(
        status="started",
        progress=0,
        total=total,
        percentage=0.0,
        message=f"Preloading {total} panoramas at zoom level {zoom_level}"
    )


@router.get("/tasks/{task_id}/preload/status", response_model=PreloadStatusResponse)
async def get_preload_status(task_id: str):
    """
    Get preload status for a task.
    """
    if task_id not in _preload_status:
        return PreloadStatusResponse(
            status="not_started",
            progress=0,
            total=0,
            percentage=0.0
        )
    
    status = _preload_status[task_id]
    percentage = (status["progress"] / status["total"] * 100) if status["total"] > 0 else 0
    
    return PreloadStatusResponse(
        status=status["status"],
        progress=status["progress"],
        total=status["total"],
        percentage=round(percentage, 1),
        message=status.get("message")
    )


# === Geofence Management ===

@router.get("/geofences", response_model=GeofenceListResponse)
async def list_geofences():
    """
    List all available geofences.
    """
    stats = geofence_checker.get_stats()
    sizes = stats.get('geofence_sizes', {})
    
    geofences = [
        GeofenceInfo(name=name, pano_count=count)
        for name, count in sizes.items()
    ]
    
    return GeofenceListResponse(geofences=geofences)


@router.post("/geofences/{geofence_name}/preload", response_model=PreloadStatusResponse)
async def preload_geofence(geofence_name: str, request: PreloadRequest, background_tasks: BackgroundTasks):
    """
    Start preloading panoramas for a geofence.
    """
    geofence = geofence_checker.get_geofence(geofence_name)
    if not geofence:
        raise HTTPException(status_code=404, detail=f"Geofence not found: {geofence_name}")
    
    total = len(geofence)
    zoom_level = request.zoom_level or settings.PANORAMA_ZOOM_LEVEL
    
    # Initialize status (using geofence_name as key)
    _preload_status[geofence_name] = {
        "status": "in_progress",
        "progress": 0,
        "total": total,
        "message": f"Preloading {total} panoramas for {geofence_name}"
    }
    
    # Start background task
    background_tasks.add_task(_preload_panoramas, geofence_name, list(geofence), zoom_level)
    
    return PreloadStatusResponse(
        status="started",
        progress=0,
        total=total,
        percentage=0.0,
        message=f"Preloading {total} panoramas for {geofence_name}"
    )


@router.get("/geofences/{geofence_name}/preload/status", response_model=PreloadStatusResponse)
async def get_geofence_preload_status(geofence_name: str):
    """
    Get preload status for a geofence.
    """
    if geofence_name not in _preload_status:
        # Check if maybe it was preloaded as a task? No, separate keys.
        return PreloadStatusResponse(
            status="not_started",
            progress=0,
            total=0,
            percentage=0.0
        )
    
    status = _preload_status[geofence_name]
    percentage = (status["progress"] / status["total"] * 100) if status["total"] > 0 else 0
    
    return PreloadStatusResponse(
        status=status["status"],
        progress=status["progress"],
        total=status["total"],
        percentage=round(percentage, 1),
        message=status.get("message")
    )


# === Player Progress ===

@router.get("/players/{player_id}/progress", response_model=PlayerProgressResponse)
async def get_player_progress(player_id: str):
    """
    Get evaluation progress for a player.
    """
    # Get all tasks
    all_tasks = []
    for task_file in TASKS_DIR.glob("*.json"):
        all_tasks.append(task_file.stem)
    
    # TODO: Query actual progress from database
    # For now, return placeholder
    tasks = [
        PlayerProgress(task_id=tid, status="not_started")
        for tid in all_tasks
    ]
    
    return PlayerProgressResponse(
        player_id=player_id,
        total_tasks=len(all_tasks),
        completed=0,
        in_progress=0,
        not_started=len(all_tasks),
        tasks=tasks
    )


# === Helper Functions ===

def _build_observation(session) -> Observation:
    """Build observation from session state."""
    from engine.session_manager import SessionMode
    from engine.metadata_cache import metadata_cache
    
    available_moves = _get_available_moves(session)
    
    image_url = None
    panorama_url = None
    center_heading = 0.0
    
    if session.step_count >= 0:
        # Perspective image for agent mode
        image_url = f"/temp_images/{session.session_id}/step_{session.step_count}.jpg"
        
        # Get center_heading for panorama coordinate conversion
        pano_id = session.state.pano_id
        metadata = metadata_cache.get(pano_id)
        if metadata:
            center_heading = metadata.get('center_heading', 0.0) or 0.0
        
        # Full panorama for human mode (360° interactive viewing)
        # Check both enum and string value for robustness
        is_human_mode = (session.mode == SessionMode.HUMAN or 
                         session.mode.value == "human" or 
                         str(session.mode) == "SessionMode.HUMAN")
        
        if is_human_mode:
            zoom_level = settings.PANORAMA_ZOOM_LEVEL
            panorama_url = f"/data/panoramas/{pano_id}_z{zoom_level}.jpg"
            print(f"[Human Mode] panorama_url = {panorama_url}, center_heading = {center_heading}")
    
    return Observation(
        task_description=session.task_config.get('description', ''),
        current_image=image_url,
        panorama_url=panorama_url,
        heading=session.state.heading if session.state else 0.0,
        pitch=session.state.pitch if session.state else 0.0,
        fov=session.state.fov if session.state else 90.0,
        center_heading=center_heading,
        available_moves=[AvailableMove(**m) for m in available_moves]
    )


def _get_available_moves(session) -> list:
    """Get available moves for a session."""
    from engine.direction_calculator import direction_calculator
    from engine.metadata_cache import metadata_cache
    
    current_pano_id = session.state.pano_id
    
    # Get metadata
    metadata = metadata_cache.get(current_pano_id)
    if not metadata:
        return []
    
    links = metadata.get('links', [])
    if not links:
        return []
    
    # Filter by geofence
    links = geofence_checker.filter_links(session.geofence, links)
    
    # Get locations
    current_location = (session.state.lat, session.state.lng)
    if current_location[0] is None:
        current_location = metadata_cache.get_location(current_pano_id)
    
    link_pano_ids = [l.get('panoId') or l.get('pano_id') for l in links]
    locations = metadata_cache.get_all_locations(link_pano_ids)
    
    # Calculate moves (link.heading is already true north reference)
    moves = direction_calculator.calculate_available_moves(
        links, session.state.heading, current_location, locations
    )
    moves = direction_calculator.sort_moves_by_direction(moves)
    
    return [{"id": m["id"], "direction": m["direction"], "distance": m.get("distance"), "heading": m.get("heading")} for m in moves]


async def _process_single_pano(pano_id: str, zoom_level: int, semaphore: asyncio.Semaphore, progress_tracker: dict, task_id_or_name: str):
    """Process a single panorama (metadata + image) with concurrency limit."""
    from engine.image_stitcher import image_stitcher
    from engine.metadata_fetcher import metadata_fetcher
    
    async with semaphore:
        try:
            # 1. Metadata (Async)
            await metadata_fetcher.fetch_and_cache_async(pano_id)
            
            # 2. Image (Sync in Thread)
            # image_stitcher.download_and_stitch checks cache internally
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(
                None, 
                image_stitcher.download_and_stitch,
                pano_id, 
                zoom_level,
                None
            )
            
        except Exception as e:
            print(f"[Preload] Error processing {pano_id}: {e}")
        finally:
            progress_tracker["progress"] += 1
            curr = progress_tracker["progress"]
            total = progress_tracker["total"]
            
            # Update global status
            if task_id_or_name in _preload_status:
                _preload_status[task_id_or_name]["progress"] = curr
                _preload_status[task_id_or_name]["message"] = f"Processed {curr}/{total} panoramas"
                print(f"[Preload-Progress] {curr}/{total} ({round(curr/total*100, 1)}%)")


async def _preload_panoramas(task_id_or_name: str, pano_ids: list, zoom_level: int):
    """
    Background task to preload panoramas (Fully Async & Parallel).
    """
    import asyncio
    
    total = len(pano_ids)
    print(f"[Preload] Starting parallel preload for {total} panoramas (Task/List: {task_id_or_name})...")
    
    # Update status
    if task_id_or_name in _preload_status:
        _preload_status[task_id_or_name]["status"] = "in_progress"
        # Reset progress if restarting? keeping message.
        _preload_status[task_id_or_name]["total"] = total
    
    # Concurrency limit (8 parallel downloads)
    # This limits how many panos are processed at once.
    # Metadata fetching has its own internal pool (4 workers).
    # Image downloading happens in threads.
    semaphore = asyncio.Semaphore(12)
    progress_tracker = {"progress": 0, "total": total}
    
    tasks = []
    for pano_id in pano_ids:
        tasks.append(_process_single_pano(pano_id, zoom_level, semaphore, progress_tracker, task_id_or_name))
    
    if not tasks:
        _preload_status[task_id_or_name]["status"] = "completed"
        _preload_status[task_id_or_name]["progress"] = 0
        return

    # Run all
    await asyncio.gather(*tasks)
    
    # Complete
    if task_id_or_name in _preload_status:
        _preload_status[task_id_or_name]["status"] = "completed"
        _preload_status[task_id_or_name]["progress"] = total
        _preload_status[task_id_or_name]["message"] = f"Completed preloading {total} panoramas."
    
    print(f"[Preload] Finished {task_id_or_name}!")

