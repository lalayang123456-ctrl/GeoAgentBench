"""
CacheManager - SQLite database initialization and connection management.

Provides a unified cache database with ACID guarantees and WAL mode for
concurrent read/write operations.
"""
import sqlite3
import threading
from pathlib import Path
from typing import Optional
from contextlib import contextmanager

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import CACHE_DB_PATH


class CacheManager:
    """
    Manages SQLite database connections and schema initialization.
    
    Uses WAL mode for better concurrent access and thread-local connections
    for thread safety.
    """
    
    _instance: Optional['CacheManager'] = None
    _lock = threading.Lock()
    
    def __new__(cls, db_path: Optional[Path] = None):
        """Singleton pattern to ensure single database instance."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    instance = super().__new__(cls)
                    instance._initialized = False
                    cls._instance = instance
        return cls._instance
    
    def __init__(self, db_path: Optional[Path] = None):
        """
        Initialize the cache manager.
        
        Args:
            db_path: Path to SQLite database file. Defaults to settings.CACHE_DB_PATH
        """
        if self._initialized:
            return
            
        self.db_path = db_path or CACHE_DB_PATH
        self._local = threading.local()
        self._init_database()
        self._initialized = True
    
    def _get_connection(self) -> sqlite3.Connection:
        """Get thread-local database connection."""
        if not hasattr(self._local, 'connection') or self._local.connection is None:
            conn = sqlite3.connect(str(self.db_path), check_same_thread=False)
            # Enable WAL mode for better concurrency
            conn.execute('PRAGMA journal_mode=WAL')
            conn.execute('PRAGMA synchronous=NORMAL')
            conn.execute('PRAGMA cache_size=-64000')  # 64MB cache
            conn.row_factory = sqlite3.Row
            self._local.connection = conn
        return self._local.connection
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connection with auto-commit."""
        conn = self._get_connection()
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
    
    def _init_database(self):
        """Initialize database schema."""
        with self.get_connection() as conn:
            cursor = conn.cursor()
            
            # Panorama index table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS panoramas (
                    pano_id TEXT NOT NULL,
                    zoom INTEGER NOT NULL,
                    image_path TEXT NOT NULL,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (pano_id, zoom)
                )
            ''')
            
            # Metadata table
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS metadata (
                    pano_id TEXT PRIMARY KEY,
                    lat REAL NOT NULL,
                    lng REAL NOT NULL,
                    capture_date TEXT,
                    links TEXT,
                    center_heading REAL,
                    fetched_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    source TEXT
                )
            ''')
            
            # Migration: add center_heading column if not exists
            cursor.execute("PRAGMA table_info(metadata)")
            columns = [row[1] for row in cursor.fetchall()]
            if 'center_heading' not in columns:
                cursor.execute('ALTER TABLE metadata ADD COLUMN center_heading REAL')
            
            # Locations table (for fast coordinate lookup)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS locations (
                    pano_id TEXT PRIMARY KEY,
                    lat REAL NOT NULL,
                    lng REAL NOT NULL
                )
            ''')
            
            # Player progress table (for human evaluation)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS player_progress (
                    player_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    session_id TEXT,
                    status TEXT DEFAULT 'not_started',
                    score REAL,
                    attempts INTEGER DEFAULT 0,
                    last_attempt_at TIMESTAMP,
                    PRIMARY KEY (player_id, task_id)
                )
            ''')
            
            # Sessions table (for session persistence)
            cursor.execute('''
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    agent_id TEXT NOT NULL,
                    task_id TEXT NOT NULL,
                    mode TEXT DEFAULT 'agent',
                    status TEXT DEFAULT 'running',
                    current_pano_id TEXT,
                    current_heading REAL DEFAULT 0,
                    current_pitch REAL DEFAULT 0,
                    current_fov REAL DEFAULT 90,
                    step_count INTEGER DEFAULT 0,
                    elapsed_time REAL DEFAULT 0,
                    trajectory TEXT,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            ''')
            
            # Create indexes for faster lookups
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_panoramas_pano_id ON panoramas(pano_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_metadata_pano_id ON metadata(pano_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_locations_pano_id ON locations(pano_id)')
            cursor.execute('CREATE INDEX IF NOT EXISTS idx_sessions_status ON sessions(status)')
    
    def close(self):
        """Close the database connection for current thread."""
        if hasattr(self._local, 'connection') and self._local.connection:
            self._local.connection.close()
            self._local.connection = None
    
    def close_all(self):
        """Reset singleton to allow fresh initialization."""
        self.close()
        CacheManager._instance = None


# Global instance
cache_manager = CacheManager()
