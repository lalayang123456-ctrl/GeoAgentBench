"""
ObservationGenerator - Generates agent observations from panorama images.

Uses py360convert for Equirectangular to Perspective projection.
Produces the view image that agents receive as input.
"""
import os
from pathlib import Path
from typing import Tuple, Optional, Dict
import numpy as np

try:
    import cv2
except ImportError:
    cv2 = None

try:
    import py360convert
except ImportError:
    py360convert = None

import sys
sys.path.insert(0, str(Path(__file__).parent.parent))
from config.settings import settings, TEMP_IMAGES_DIR
from .panorama_cache import panorama_cache


class ObservationGenerator:
    """
    Generates perspective view images from equirectangular panoramas.
    
    Uses py360convert for the projection and OpenCV for image I/O.
    """
    
    def __init__(
        self,
        output_size: Optional[Tuple[int, int]] = None,
        default_fov: int = None
    ):
        """
        Initialize the observation generator.
        
        Args:
            output_size: Output image size (width, height)
            default_fov: Default field of view
        """
        self.output_size = output_size or settings.RENDER_OUTPUT_SIZE
        self.default_fov = default_fov or settings.RENDER_DEFAULT_FOV
        
        # Validate dependencies
        if cv2 is None:
            raise ImportError("opencv-python is required. Install with: pip install opencv-python")
        if py360convert is None:
            raise ImportError("py360convert is required. Install with: pip install py360convert")
    
    def generate_observation(
        self,
        pano_id: str,
        heading: float,
        pitch: float = 0,
        fov: float = None,
        zoom: int = None,
        session_id: Optional[str] = None,
        step: Optional[int] = None
    ) -> Optional[Dict]:
        """
        Generate a perspective observation from a panorama.
        
        Args:
            pano_id: Panorama ID
            heading: Horizontal heading (0-360)
            pitch: Vertical pitch (-85 to 85)
            fov: Field of view (30-100)
            zoom: Panorama zoom level
            session_id: Session ID for temp image path
            step: Step number for temp image naming
            
        Returns:
            Dict with image_path and metadata, or None if failed
        """
        fov = fov or self.default_fov
        zoom = zoom if zoom is not None else settings.PANORAMA_ZOOM_LEVEL
        
        # Get panorama from cache
        pano_path = panorama_cache.get(pano_id, zoom)
        if pano_path is None:
            return None
        
        # Get centerHeading for coordinate conversion
        from .metadata_cache import metadata_cache
        metadata = metadata_cache.get(pano_id)
        center_heading = 0.0
        if metadata:
            center_heading = metadata.get('center_heading', 0.0) or 0.0
        
        # Load equirectangular image
        equi_img = cv2.imread(str(pano_path))
        if equi_img is None:
            return None
        
        # Convert BGR to RGB for py360convert
        equi_img = cv2.cvtColor(equi_img, cv2.COLOR_BGR2RGB)
        
        # Perform projection
        # py360convert uses:
        # - h_fov, v_fov for field of view
        # - u_deg (yaw/heading) and v_deg (pitch)
        # Note: heading in SVS is 0=North, increases clockwise
        # py360convert uses 0=center of image
        # Convert true north heading to panorama image coordinates
        # image_u = heading - centerHeading (no 180 offset - py360convert has same convention)
        image_u = heading - center_heading
        
        # Calculate vertical FOV based on aspect ratio
        width, height = self.output_size
        aspect = width / height
        v_fov = fov / aspect
        
        try:
            perspective = py360convert.e2p(
                equi_img,
                fov_deg=(fov, v_fov),
                u_deg=image_u,
                v_deg=pitch,  # positive=UP, negative=DOWN (matching system prompt)
                out_hw=(height, width),
                mode='bilinear'
            )
        except Exception as e:
            print(f"Error generating perspective view: {e}")
            return None
        
        # Convert back to BGR for cv2
        perspective = cv2.cvtColor(perspective, cv2.COLOR_RGB2BGR)
        
        # Generate output path
        if session_id and step is not None:
            session_dir = TEMP_IMAGES_DIR / session_id
            session_dir.mkdir(parents=True, exist_ok=True)
            output_path = session_dir / f"step_{step}.jpg"
        else:
            # Temp file for one-off generation
            import tempfile
            fd, temp_path = tempfile.mkstemp(suffix='.jpg')
            os.close(fd)
            output_path = Path(temp_path)
        
        # Save image
        cv2.imwrite(str(output_path), perspective, [cv2.IMWRITE_JPEG_QUALITY, 90])
        
        return {
            'image_path': str(output_path),
            'pano_id': pano_id,
            'heading': heading,
            'pitch': pitch,
            'fov': fov,
            'size': self.output_size
        }
    
    def generate_observation_base64(
        self,
        pano_id: str,
        heading: float,
        pitch: float = 0,
        fov: float = None,
        zoom: int = None
    ) -> Optional[str]:
        """
        Generate observation and return as base64 string.
        
        Args:
            pano_id: Panorama ID
            heading: Horizontal heading (0-360)
            pitch: Vertical pitch (-85 to 85)
            fov: Field of view (30-100)
            zoom: Panorama zoom level
            
        Returns:
            Base64 encoded JPEG string, or None if failed
        """
        import base64
        
        result = self.generate_observation(pano_id, heading, pitch, fov, zoom)
        if result is None:
            return None
        
        # Read and encode
        with open(result['image_path'], 'rb') as f:
            image_data = f.read()
        
        return base64.b64encode(image_data).decode('utf-8')
    
    def cleanup_session_images(self, session_id: str):
        """
        Clean up temporary images for a session.
        
        Args:
            session_id: Session ID
        """
        session_dir = TEMP_IMAGES_DIR / session_id
        if session_dir.exists():
            import shutil
            shutil.rmtree(session_dir)
    
    @staticmethod
    def get_session_images(session_id: str) -> list:
        """
        Get list of temporary images for a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            List of image paths sorted by step number
        """
        session_dir = TEMP_IMAGES_DIR / session_id
        if not session_dir.exists():
            return []
        
        images = list(session_dir.glob("step_*.jpg"))
        # Sort by step number
        images.sort(key=lambda p: int(p.stem.split('_')[1]))
        return [str(p) for p in images]


# Global instance (lazy initialization to avoid import errors)
_observation_generator: Optional[ObservationGenerator] = None


def get_observation_generator() -> ObservationGenerator:
    """Get or create the observation generator singleton."""
    global _observation_generator
    if _observation_generator is None:
        _observation_generator = ObservationGenerator()
    return _observation_generator
