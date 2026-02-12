"""
VLN Benchmark Platform - Main Application Entry Point

FastAPI application with static file serving and API routes.
"""
import uvicorn
from pathlib import Path
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware

# Add project root to path
import sys
sys.path.insert(0, str(Path(__file__).parent))

from config.settings import settings, TEMP_IMAGES_DIR, PANORAMAS_DIR
from api.routes import router


# Create FastAPI app
app = FastAPI(
    title="VLN Benchmark Platform",
    description="Vision-Language Navigation Benchmark for testing LLM/VLM navigation capabilities",
    version="1.0.0"
)

# Add CORS middleware for web UI
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include API routes
app.include_router(router)

# Serve static files
WEB_UI_DIR = Path(__file__).parent / "web_ui"

# Mount static directories
app.mount("/temp_images", StaticFiles(directory=str(TEMP_IMAGES_DIR)), name="temp_images")
app.mount("/data/panoramas", StaticFiles(directory=str(PANORAMAS_DIR)), name="panoramas")
app.mount("/css", StaticFiles(directory=str(WEB_UI_DIR / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(WEB_UI_DIR / "js")), name="js")

# Mount static HTML files at root
app.mount("/", StaticFiles(directory=str(WEB_UI_DIR), html=True), name="web_ui")


@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    # Ensure directories exist
    TEMP_IMAGES_DIR.mkdir(parents=True, exist_ok=True)
    (WEB_UI_DIR / "css").mkdir(parents=True, exist_ok=True)
    (WEB_UI_DIR / "js").mkdir(parents=True, exist_ok=True)
    
    print("")
    print("=" * 50)
    print("  VLN Benchmark Platform started!")
    print("=" * 50)
    print("")
    print(f"  Homepage:   http://localhost:{settings.PORT}/")
    print(f"  API Docs:   http://localhost:{settings.PORT}/docs")
    print(f"  Human Eval: http://localhost:{settings.PORT}/human_eval.html")
    print(f"  Preload:    http://localhost:{settings.PORT}/ -> Preload Data")
    print("")
    print("=" * 50)


@app.on_event("shutdown")
async def shutdown_event():
    """Cleanup on shutdown."""
    from engine.logger import session_logger
    session_logger.close_all()
    print("VLN Benchmark Platform stopped")


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.DEBUG
    )
