"""
Logger - Logs session events in JSON Lines format.

Records actions, observations, and session summaries for analysis and replay.
"""
import json
from pathlib import Path
from datetime import datetime
from typing import Dict, Optional, Any, List
from dataclasses import asdict

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import LOGS_DIR

HUMAN_LOGS_DIR = LOGS_DIR / "log_human"
from .session_manager import Session, SessionState


class SessionLogger:
    """
    Logs session events to JSON Lines files.
    
    Each session gets its own log file: {session_id}.jsonl
    Log entries include timestamps, actions, states, and observations.
    """
    
    def __init__(self, logs_dir: Optional[Path] = None):
        """
        Initialize the logger.
        
        Args:
            logs_dir: Directory for log files
        """
        self.logs_dir = logs_dir or LOGS_DIR
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        self._file_handles: Dict[str, Any] = {}
        self._session_log_dirs: Dict[str, Path] = {}  # per-session log dir overrides
    
    def _find_log_path(self, session_id: str) -> Path:
        """
        Find the log file for a session, checking subdirectories recursively.
        """
        # First check the default flat location
        default_path = self.logs_dir / f"{session_id}.jsonl"
        if default_path.exists():
            return default_path
            
        # If not found, search recursively
        # limiting to 2 levels deep to avoid massive performance hit if logs_dir is huge
        for file_path in self.logs_dir.rglob(f"{session_id}.jsonl"):
            return file_path
            
        return default_path

    def _get_log_path(self, session_id: str) -> Path:
        """Get the log file path for a session."""
        # Use per-session override if set (e.g. human sessions)
        if session_id in self._session_log_dirs:
            return self._session_log_dirs[session_id] / f"{session_id}.jsonl"
        return self._find_log_path(session_id)
    
    def _get_file_handle(self, session_id: str):
        """Get or create file handle for a session."""
        if session_id not in self._file_handles:
            log_path = self._get_log_path(session_id)
            self._file_handles[session_id] = open(log_path, 'a', encoding='utf-8')
        return self._file_handles[session_id]
    
    def _write_entry(self, session_id: str, entry: Dict):
        """Write a log entry."""
        f = self._get_file_handle(session_id)
        f.write(json.dumps(entry, ensure_ascii=False) + '\n')
        f.flush()
    
    def log_session_start(self, session: Session):
        """
        Log session start event.
        
        Args:
            session: The session that started
        """
        # Route human evaluation logs to logs/log_human/
        if session.mode.value == 'human':
            HUMAN_LOGS_DIR.mkdir(parents=True, exist_ok=True)
            self._session_log_dirs[session.session_id] = HUMAN_LOGS_DIR
        
        entry = {
            'event': 'session_start',
            'session_id': session.session_id,
            'agent_id': session.agent_id,
            'task_id': session.task_id,
            'mode': session.mode.value,
            'timestamp': datetime.now().isoformat(),
            'initial_state': asdict(session.state) if session.state else None,
            'task_description': session.task_config.get('description', '')
        }
        self._write_entry(session.session_id, entry)
    
    def log_action(
        self,
        session: Session,
        action: Dict,
        result: Dict,
        available_moves: List[Dict],
        response_time_ms: Optional[int] = None
    ):
        """
        Log an action event.
        
        Args:
            session: Current session
            action: Action that was executed
            result: Result of the action
            available_moves: Available moves at the time
            response_time_ms: Agent response time (for human mode)
        """
        entry = {
            'event': 'action',
            'session_id': session.session_id,
            'timestamp': datetime.now().isoformat(),
            'step': session.step_count,
            'state': asdict(session.state) if session.state else None,
            'action': action,
            'available_moves': available_moves,
            'image_path': f"temp_images/{session.session_id}/step_{session.step_count}.jpg",
            'agent_type': session.mode.value
        }
        
        # Add human-specific fields
        if session.mode.value == 'human' and response_time_ms is not None:
            entry['response_time_ms'] = response_time_ms
        
        # Add action result info
        if 'direction' in action:
            entry['action']['direction'] = action.get('direction')
        if 'target_pano_id' in action:
            entry['action']['target_pano_id'] = action.get('target_pano_id')
        
        self._write_entry(session.session_id, entry)
    
    def log_session_end(self, session: Session):
        """
        Log session end event with summary.
        
        Args:
            session: The session that ended
        """
        # Check if reached target
        target_panos = session.task_config.get('target_pano_ids', [])
        reached_target = (
            session.state.pano_id in target_panos if target_panos else None
        )
        
        entry = {
            'event': 'session_end',
            'session_id': session.session_id,
            'agent_id': session.agent_id,
            'task_id': session.task_id,
            'timestamp': datetime.now().isoformat(),
            'total_steps': session.step_count,
            'elapsed_time': session.elapsed_time,
            'status': session.status.value,
            'done_reason': session.done_reason,
            'final_pano_id': session.state.pano_id if session.state else None,
            'reached_target': reached_target,
            'agent_answer': session.agent_answer,
            'trajectory': session.trajectory
        }
        self._write_entry(session.session_id, entry)
        
        # Close file handle
        self._close_session_log(session.session_id)
    
    def _close_session_log(self, session_id: str):
        """Close the log file for a session."""
        if session_id in self._file_handles:
            self._file_handles[session_id].close()
            del self._file_handles[session_id]
        self._session_log_dirs.pop(session_id, None)
    
    def close_all(self):
        """Close all open log files."""
        for session_id in list(self._file_handles.keys()):
            self._close_session_log(session_id)
    
    def read_session_log(self, session_id: str) -> List[Dict]:
        """
        Read all entries from a session log.
        
        Args:
            session_id: Session ID
            
        Returns:
            List of log entries
        """
        log_path = self._get_log_path(session_id)
        if not log_path.exists():
            return []
        
        entries = []
        with open(log_path, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if line:
                    entries.append(json.loads(line))
        
        return entries
    
    def get_session_summary(self, session_id: str) -> Optional[Dict]:
        """
        Get the session end summary from log.
        
        Args:
            session_id: Session ID
            
        Returns:
            Session summary dict or None
        """
        entries = self.read_session_log(session_id)
        for entry in reversed(entries):
            if entry.get('event') == 'session_end':
                return entry
        return None
    
    def list_sessions(self) -> List[str]:
        """List all session IDs with logs (recursive)."""
        return [p.stem for p in self.logs_dir.rglob("*.jsonl")]
    
    def get_log_path(self, session_id: str) -> Path:
        """Get the log file path for a session."""
        return self._get_log_path(session_id)


# Global instance
session_logger = SessionLogger()
