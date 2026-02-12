"""
API module for VLN Benchmark Platform.
Contains FastAPI routes and Pydantic models.
"""
from .routes import router
from .models import *

__all__ = ["router"]
