"""
TilesDownloader - Downloads panorama tiles from Google Tiles API.

Handles session management, tile downloads, and anti-scraping measures.
"""
import time
import random
import asyncio
import aiohttp
import requests
from pathlib import Path
from typing import Optional, Dict, Tuple
from datetime import datetime, timedelta

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings


class TilesSession:
    """Manages Google Tiles API session lifecycle."""
    
    def __init__(self, session_token: str, expiry: datetime):
        self.token = session_token
        self.expiry = expiry
    
    def is_expired(self, buffer_seconds: int = 60) -> bool:
        """Check if session is expired or will expire soon."""
        return datetime.now() >= (self.expiry - timedelta(seconds=buffer_seconds))


class TilesDownloader:
    """
    Downloads panorama tiles from Google Tiles API.
    
    Features:
    - Automatic session management
    - Anti-scraping measures (random delays, retry with backoff)
    - Concurrent downloads with semaphore control
    """
    
    def __init__(self, api_key: Optional[str] = None):
        """
        Initialize the tiles downloader.
        
        Args:
            api_key: Google API key. Defaults to settings.
        """
        self.api_key = api_key or settings.GOOGLE_API_KEY
        if not self.api_key:
            raise ValueError("Google API key is required")
        
        self.base_url = settings.TILES_API_BASE_URL
        self.session: Optional[TilesSession] = None
        self.http_session = requests.Session()
        
        # Set headers to appear as normal browser
        self.http_session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

        # Increase connection pool size for high concurrency
        adapter = requests.adapters.HTTPAdapter(pool_connections=50, pool_maxsize=50)
        self.http_session.mount('https://', adapter)
        self.http_session.mount('http://', adapter)
        
        # Concurrency control for async downloads
        # 4 panoramas × 4 tiles = max 16 concurrent HTTP requests
        self.tiles_per_pano = 4           # Max 4 parallel tile downloads per panorama
        self.pano_semaphore = asyncio.Semaphore(4)  # Max 4 panoramas at once
        self.tile_semaphore = asyncio.Semaphore(4)  # Max 4 tiles per panorama
        self.min_delay = 0.1              # Min delay between requests
    
    def _create_session(self) -> TilesSession:
        """Create a new Tiles API session."""
        url = f"{self.base_url}/createSession"
        params = {'key': self.api_key}
        payload = {
            "mapType": "streetview",
            "language": "en-US",
            "region": "US"
        }
        
        try:
            response = self.http_session.post(url, params=params, json=payload)
            response.raise_for_status()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 404:
                try:
                    error_data = e.response.json()
                    if error_data.get('error', {}).get('status') == 'NOT_FOUND':
                        raise ValueError(
                            "Google Map Tiles API returned 404 Not Found. "
                            "Please ensure the 'Map Tiles API' is enabled in your Google Cloud Console "
                            "and your API key has access to it."
                        ) from e
                except ValueError:
                    pass # Not JSON or not the expected structure
            raise e
        
        data = response.json()
        session_token = data['session']
        expiry_str = data.get('expiry', '')
        
        # Parse expiry (format: "2026-01-12T19:00:00Z")
        try:
            expiry = datetime.fromisoformat(expiry_str.replace('Z', '+00:00'))
            # Convert to local time
            expiry = expiry.replace(tzinfo=None)
        except:
            # Default to 1 hour from now
            expiry = datetime.now() + timedelta(hours=1)
        
        return TilesSession(session_token, expiry)
    
    def _ensure_session(self):
        """Ensure we have a valid session."""
        if self.session is None or self.session.is_expired(settings.TILES_SESSION_REFRESH_BUFFER):
            self.session = self._create_session()
    
    def _random_delay(self):
        """Add random delay between requests for anti-scraping."""
        delay = random.uniform(
            settings.PREFETCH_REQUEST_DELAY_MIN,
            settings.PREFETCH_REQUEST_DELAY_MAX
        )
        time.sleep(delay)
    
    def download_tile(
        self,
        pano_id: str,
        zoom: int,
        x: int,
        y: int,
        retry: int = 0
    ) -> Optional[bytes]:
        """
        Download a single panorama tile (synchronous).
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level (0-5)
            x: Tile X coordinate
            y: Tile Y coordinate
            retry: Current retry count
            
        Returns:
            Tile image bytes or None if failed
        """
        self._ensure_session()
        
        url = f"{self.base_url}/streetview/tiles/{zoom}/{x}/{y}"
        params = {
            'session': self.session.token,
            'key': self.api_key,
            'panoId': pano_id
        }
        
        try:
            self._random_delay()
            response = self.http_session.get(url, params=params)
            
            if response.status_code == 200:
                return response.content
            elif response.status_code in (429, 503):
                # Rate limited or service unavailable - retry with backoff
                if retry < settings.PREFETCH_RETRY_MAX:
                    wait = settings.PREFETCH_RETRY_BACKOFF ** retry
                    time.sleep(wait)
                    return self.download_tile(pano_id, zoom, x, y, retry + 1)
            else:
                print(f"Tile download failed: {response.status_code}")
                
        except requests.RequestException as e:
            print(f"Tile download error: {e}")
            if retry < settings.PREFETCH_RETRY_MAX:
                wait = settings.PREFETCH_RETRY_BACKOFF ** retry
                time.sleep(wait)
                return self.download_tile(pano_id, zoom, x, y, retry + 1)
        
        return None
    
    async def download_tile_async(
        self,
        pano_id: str,
        zoom: int,
        x: int,
        y: int,
        retry: int = 0
    ) -> Optional[bytes]:
        """
        Download a single panorama tile (async with concurrency control).
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level (0-5)
            x: Tile X coordinate
            y: Tile Y coordinate
            retry: Current retry count
            
        Returns:
            Tile image bytes or None if failed
        """
        async with self.tile_semaphore:
            self._ensure_session()
            
            url = f"{self.base_url}/streetview/tiles/{zoom}/{x}/{y}"
            params = {
                'session': self.session.token,
                'key': self.api_key,
                'panoId': pano_id
            }
            
            try:
                await asyncio.sleep(self.min_delay)
                
                async with aiohttp.ClientSession() as session:
                    async with session.get(url, params=params) as response:
                        if response.status == 200:
                            return await response.read()
                        elif response.status in (429, 503):
                            # Rate limited - retry with backoff
                            if retry < settings.PREFETCH_RETRY_MAX:
                                wait = settings.PREFETCH_RETRY_BACKOFF ** retry
                                await asyncio.sleep(wait)
                                return await self.download_tile_async(pano_id, zoom, x, y, retry + 1)
                        else:
                            print(f"Tile download failed: {response.status}")
                            
            except Exception as e:
                print(f"Tile download error: {e}")
                if retry < settings.PREFETCH_RETRY_MAX:
                    wait = settings.PREFETCH_RETRY_BACKOFF ** retry
                    await asyncio.sleep(wait)
                    return await self.download_tile_async(pano_id, zoom, x, y, retry + 1)
        
        return None
    
    @staticmethod
    def get_tile_grid(zoom: int) -> Tuple[int, int]:
        """
        Get the tile grid dimensions for a zoom level.
        
        Args:
            zoom: Zoom level
            
        Returns:
            Tuple of (cols, rows)
        """
        if zoom == 0:
            return (1, 1)
        cols = 2 ** zoom
        rows = 2 ** (zoom - 1)
        return (cols, rows)
    
    def download_all_tiles(
        self,
        pano_id: str,
        zoom: int,
        progress_callback=None
    ) -> Optional[Dict[Tuple[int, int], bytes]]:
        """
        Download all tiles for a panorama (synchronous).
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level
            progress_callback: Optional callback(current, total)
            
        Returns:
            Dict mapping (x, y) to tile bytes, or None if failed
        """
        cols, rows = self.get_tile_grid(zoom)
        total = cols * rows
        tiles = {}
        
        for y in range(rows):
            for x in range(cols):
                tile_data = self.download_tile(pano_id, zoom, x, y)
                if tile_data is None:
                    print(f"Failed to download tile ({x}, {y})")
                    return None
                
                tiles[(x, y)] = tile_data
                
                if progress_callback:
                    progress_callback(len(tiles), total)
        
        return tiles
    
    async def download_all_tiles_async(
        self,
        pano_id: str,
        zoom: int,
        progress_callback=None
    ) -> Optional[Dict[Tuple[int, int], bytes]]:
        """
        Download all tiles for a panorama (async with concurrency).
        
        Uses pano_semaphore to limit concurrent panorama downloads.
        Uses tile_semaphore to limit concurrent tile downloads per panorama.
        
        Args:
            pano_id: Panorama ID
            zoom: Zoom level
            progress_callback: Optional callback(current, total)
            
        Returns:
            Dict mapping (x, y) to tile bytes, or None if failed
        """
        async with self.pano_semaphore:
            cols, rows = self.get_tile_grid(zoom)
            total = cols * rows
            tiles = {}
            
            # Create all download tasks
            tasks = []
            coords = []
            for y in range(rows):
                for x in range(cols):
                    tasks.append(self.download_tile_async(pano_id, zoom, x, y))
                    coords.append((x, y))
            
            # Download all tiles concurrently (limited by tile_semaphore)
            results = await asyncio.gather(*tasks, return_exceptions=True)
            
            # Process results
            for (x, y), tile_data in zip(coords, results):
                if isinstance(tile_data, Exception) or tile_data is None:
                    print(f"Failed to download tile ({x}, {y})")
                    return None
                
                tiles[(x, y)] = tile_data
                
                if progress_callback:
                    progress_callback(len(tiles), total)
            
            return tiles


# Global instance (lazy)
_tiles_downloader: Optional[TilesDownloader] = None


def get_tiles_downloader() -> TilesDownloader:
    """Get or create the tiles downloader singleton."""
    global _tiles_downloader
    if _tiles_downloader is None:
        _tiles_downloader = TilesDownloader()
    return _tiles_downloader
