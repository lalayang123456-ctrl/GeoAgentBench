"""
Metadata Fetcher - Downloads panorama metadata from Google APIs.

Fetches:
- Coordinates (lat/lng) and capture date via Static API
- Adjacent panorama links via Maps JS API (Selenium)
"""
import os
import sys
import json
import time
import random
import requests
import asyncio
import threading
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from concurrent.futures import ThreadPoolExecutor

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings
from .metadata_cache import metadata_cache



class MetadataFetcherWorker:
    """
    Single worker that manages one Selenium instance.
    """
    def __init__(self, api_key: str, driver_path: str = None):
        self.api_key = api_key
        self.driver_path = driver_path
        self.driver = None
        self._init_driver()
        
    def _init_driver(self):
        """Initialize Selenium WebDriver."""
        from selenium import webdriver
        from selenium.webdriver.chrome.service import Service
        from selenium.webdriver.chrome.options import Options
        # Note: webdriver_manager is now handled in the parent class
        
        chrome_options = Options()
        chrome_options.add_argument("--headless")
        chrome_options.add_argument("--no-sandbox")
        chrome_options.add_argument("--disable-dev-shm-usage")
        chrome_options.add_argument("--disable-gpu")
        # Suppress logging
        chrome_options.add_argument("--log-level=3")
        
        try:
            service = Service(self.driver_path) if self.driver_path else None
            self.driver = webdriver.Chrome(service=service, options=chrome_options)
        except Exception as e:
            print(f"[Worker] Failed to init driver: {e}")
            self.driver = None

    def fetch_links(self, pano_id: str) -> Optional[Dict]:
        """Fetch links using this worker's Selenium instance."""
        if not self.driver:
            self._init_driver()
            if not self.driver:
                return None
        
        from selenium.webdriver.common.by import By
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        
        html_content = f'''
        <!DOCTYPE html>
        <html>
        <head>
            <script src="https://maps.googleapis.com/maps/api/js?key={self.api_key}"></script>
        </head>
        <body>
            <div id="result"></div>
            <script>
                const sv = new google.maps.StreetViewService();
                sv.getPanorama({{pano: "{pano_id}"}}, function(data, status) {{
                    if (status === "OK") {{
                        const links = data.links || [];
                        const linksData = links.map(link => ({{
                            panoId: link.pano,
                            heading: link.heading,
                            description: link.description || ""
                        }}));
                        const centerHeading = data.tiles ? data.tiles.centerHeading : 0;
                        const result = {{
                            links: linksData,
                            centerHeading: centerHeading
                        }};
                        document.getElementById("result").textContent = JSON.stringify(result);
                    }} else {{
                        document.getElementById("result").textContent = "ERROR:" + status;
                    }}
                }});
            </script>
        </body>
        </html>
        '''
        
        try:
            # Using data URL to avoid file I/O
            self.driver.get("data:text/html;charset=utf-8," + html_content)
            
            # Wait for result to be populated (non-empty text)
            WebDriverWait(self.driver, 10).until(
                lambda d: d.find_element(By.ID, "result").text.strip() != ""
            )
            
            element = self.driver.find_element(By.ID, "result")
            
            result_text = element.text
            if result_text.startswith("ERROR:"):
                # ZERO_RESULTS is common and not an error
                if "ZERO_RESULTS" not in result_text:
                     print(f"[Worker] API Error: {result_text}")
                return None
            
            return json.loads(result_text)
            
        except Exception as e:
            print(f"[Worker] Selenium error: {e}")
            # Restart driver on error
            self.quit()
            self._init_driver()
            return None

    def quit(self):
        """Clean up resources."""
        if self.driver:
            try:
                self.driver.quit()
            except:
                pass
            self.driver = None


class MetadataFetcher:
    """
    Fetches panorama metadata using a pool of Selenium workers.
    """
    
    def __init__(self, api_key: Optional[str] = None, num_workers: int = 4):
        """
        Initialize with API key and worker pool.
        
        Args:
            api_key: Google API Key
            num_workers: Number of parallel Selenium instances (default: 4)
        """
        self.api_key = api_key or settings.GOOGLE_API_KEY
        self.num_workers = num_workers
        self.workers: List[MetadataFetcherWorker] = []
        self.worker_queue = asyncio.Queue()
        self.is_initialized = False
        self._lock = asyncio.Lock()
    
    async def initialize(self):
        """Initialize worker pool asynchronously."""
        async with self._lock:
            if self.is_initialized:
                return
            
            # 1. Resolve driver path ONCE
            from webdriver_manager.chrome import ChromeDriverManager
            print("[MetadataFetcher] Checking ChromeDriver version...")
            try:
                # Use loop.run_in_executor because install() is blocking network IO
                loop = asyncio.get_running_loop()
                driver_path = await loop.run_in_executor(None, lambda: ChromeDriverManager().install())
                print(f"[MetadataFetcher] Driver ready at: {driver_path}")
            except Exception as e:
                print(f"[MetadataFetcher] Failed to install driver: {e}")
                return

            print(f"[MetadataFetcher] Initializing {self.num_workers} Selenium workers...")
            
            # Create workers in thread pool to avoid blocking
            # loop is already defined above
            with ThreadPoolExecutor(max_workers=self.num_workers) as executor:
                futures = [
                    loop.run_in_executor(executor, MetadataFetcherWorker, self.api_key, driver_path)
                    for _ in range(self.num_workers)
                ]
                self.workers = await asyncio.gather(*futures)
            
            # Add to queue
            for worker in self.workers:
                self.worker_queue.put_nowait(worker)
            
            self.is_initialized = True
            print(f"[MetadataFetcher] Worker pool ready.")
    
    async def cleanup(self):
        """Close all workers gracefully."""
        print("[MetadataFetcher] Cleaning up workers...")
        
        # Graceful shutdown (Try to quit drivers first)
        for i, worker in enumerate(self.workers):
            try:
                print(f"[MetadataFetcher] Closing worker {i+1}...")
                # Run quit in thread to avoid blocking loop if it hangs
                await asyncio.to_thread(worker.quit)
            except Exception as e:
                print(f"[MetadataFetcher] Error closing worker {i+1}: {e}")
        
        self.workers = []
        self.is_initialized = False
        print("[MetadataFetcher] Worker pool shutdown complete.")
    
    def fetch_basic_metadata(self, pano_id: str) -> Optional[Dict]:
        """
        Fetch basic metadata (coords, date) via Static API.
        This is lightweight and doesn't need Selenium workers.
        """
        if not self.api_key:
            return None
        
        url = "https://maps.googleapis.com/maps/api/streetview/metadata"
        params = {"pano": pano_id, "key": self.api_key}
        
        try:
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data.get("status") == "OK":
                    return {
                        "pano_id": data["pano_id"],
                        "lat": data["location"]["lat"],
                        "lng": data["location"]["lng"],
                        "capture_date": data.get("date", "")
                    }
        except Exception:
            pass
        return None
    
    async def fetch_links(self, pano_id: str, max_retries: int = 2) -> Optional[Dict]:
        """
        Fetch links using a worker from the pool.
        
        Args:
            pano_id: Panorama ID
            max_retries: Retry attempts
        """
        if not self.is_initialized:
            await self.initialize()
            
        last_error = None
        
        for attempt in range(max_retries + 1):
            # 1. Borrow a worker
            worker = await self.worker_queue.get()
            
            try:
                # 2. Run in thread (blocking Selenium op)
                result = await asyncio.to_thread(worker.fetch_links, pano_id)
                
                if result is not None:
                    return result
                else:
                    last_error = "Empty response or API check failed"
                    
            except Exception as e:
                last_error = str(e)
            finally:
                # 3. Return worker to queue
                self.worker_queue.put_nowait(worker)
            
            # Retry delay
            if attempt < max_retries:
                wait_time = random.uniform(0.5, 1.5)
                await asyncio.sleep(wait_time)
        
        return None

    async def fetch_and_cache_async(self, pano_id: str) -> bool:
        """
        Fetch and cache all metadata for a panorama asynchronously.
        
        Args:
            pano_id: Panorama ID
            
        Returns:
            True if successful
        """
        try:
            # 1. Check cache
            if metadata_cache.has(pano_id):
                return True
                
            # 2. Fetch basic metadata (lightweight, sync)
            basic = await asyncio.to_thread(self.fetch_basic_metadata, pano_id)
            if not basic:
                return False
                
            # 3. Fetch links (heavy, async worker)
            links_data = await self.fetch_links(pano_id)
            if not links_data:
                return False
                
            # 4. Save to cache
            await asyncio.to_thread(
                metadata_cache.save,
                pano_id=pano_id,
                lat=basic['lat'],
                lng=basic['lng'],
                capture_date=basic['capture_date'],
                links=links_data.get('links', []),
                center_heading=links_data.get('centerHeading', 0),
                source='maps_js_api'
            )
            return True
            
        except Exception as e:
            print(f"[MetadataFetcher] Error fetching/caching {pano_id}: {e}")
            return False

    def fetch_and_cache_all(self, pano_id: str):
        """Synchronous wrapper for backward compatibility."""
        # Note: This is hacky if called from inside an event loop.
        # Ideally, callers should be async.
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # We are in a loop, create task? No, cannot wait sync.
                # Just error or print warning.
                print(f"[Warning] fetch_and_cache_all called sync from async context")
            else:
                loop.run_until_complete(self.fetch_and_cache_async(pano_id))
        except Exception:
             asyncio.run(self.fetch_and_cache_async(pano_id))


# Global instance
metadata_fetcher = MetadataFetcher()
