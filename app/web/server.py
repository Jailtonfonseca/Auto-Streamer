"""
The main FastAPI application for the Auto-Streamer web UI and API.

This module initializes the FastAPI app, sets up routes, middleware,
and orchestrates the interaction between the web interface and the
backend pipeline components.
"""
import asyncio
import json
import logging
from pathlib import Path
from typing import Dict, List

from fastapi import FastAPI, Request, Form, Depends, HTTPException, status, Body
from fastapi.responses import HTMLResponse, RedirectResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sse_starlette.sse import EventSourceResponse

from .. import config, manifest, metrics, security, streamer
from ..models import ItemState, ManifestItem, UpdateConfigRequest
from ..utils import format_sse, OUTPUT_DIR

# --- Globals and App Initialization ---
logger = logging.getLogger(__name__)

# This is a simple way to manage global state. For a larger application,
# a more robust state management class might be preferable.
class AppState:
    def __init__(self):
        self.streamer_instance: streamer.Streamer | None = None
        self.log_queue = asyncio.Queue()

app_state = AppState()

app = FastAPI(title="Auto-Streamer")

# --- Middleware ---
metrics.setup_metrics_middleware(app)

# --- Static Files and Templates ---
WEB_DIR = Path(__file__).parent.resolve()
app.mount("/static", StaticFiles(directory=WEB_DIR / "static"), name="static")
templates = Jinja2Templates(directory=WEB_DIR / "templates")

# --- Helper Functions ---
async def log_event(event_type: str, data: Dict):
    """Puts a log event into the SSE queue."""
    await app_state.log_queue.put({"event": event_type, "data": data})

# --- Background Tasks ---
@app.on_event("startup")
async def startup_event():
    """Tasks to run on application startup."""
    # Load configuration and set up paths
    try:
        from ..utils import setup_paths, setup_logging
        setup_paths()
        setup_logging()
        config.app_config.load()
    except config.ConfigError as e:
        logger.critical(f"Failed to load configuration on startup: {e}")
        # In a real app, you might want to prevent startup entirely
        return

    # Periodically update system metrics
    async def update_metrics_task():
        while True:
            metrics.update_system_metrics()
            await asyncio.sleep(30) # Update every 30 seconds

    asyncio.create_task(update_metrics_task())
    logger.info("Auto-Streamer application started.")
    await log_event("status", {"message": "Server started successfully."})

# --- SSE Log Stream ---
@app.get("/api/v1/logs/stream")
async def log_stream(request: Request):
    """Server-Sent Events endpoint for real-time logs and status updates."""
    async def event_generator():
        while True:
            if await request.is_disconnected():
                break
            try:
                log_item = await asyncio.wait_for(app_state.log_queue.get(), timeout=30)
                yield format_sse(data=log_item['data'], event=log_item['event'])
            except asyncio.TimeoutError:
                # Send a keep-alive comment every 30s if no new logs
                yield ": keep-alive\n\n"

    return EventSourceResponse(event_generator())

# --- Authentication Routes ---
@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    return templates.TemplateResponse("login.html", {"request": request})

@app.post("/login")
async def handle_login(request: Request, password: str = Form(...)):
    if security.verify_password(password, security.ADMIN_PASS_HASH):
        response = RedirectResponse(url="/", status_code=status.HTTP_303_SEE_OTHER)
        session_cookie = security.create_session_cookie("admin")
        response.set_cookie(
            key=security.SESSION_COOKIE_NAME,
            value=session_cookie,
            httponly=True,
            secure=config.app_config.get("ui", {}).get("secure_cookie"),
            max_age=security.SESSION_MAX_AGE_SECONDS,
        )
        return response
    else:
        return templates.TemplateResponse("login.html", {"request": request, "error": "Invalid password"})

@app.get("/logout")
async def logout(request: Request):
    response = RedirectResponse(url="/login")
    response.delete_cookie(security.SESSION_COOKIE_NAME)
    return response

# --- HTML Page Routes ---
@app.get("/", response_class=HTMLResponse)
async def dashboard_page(request: Request, user: str = Depends(security.require_authentication)):
    # In a real app, you'd fetch dynamic data here
    return templates.TemplateResponse("dashboard.html", {"request": request, "page": "dashboard"})

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, user: str = Depends(security.require_authentication)):
    return templates.TemplateResponse("settings.html", {"request": request, "page": "settings"})

@app.get("/review", response_class=HTMLResponse)
async def review_page(request: Request, user: str = Depends(security.require_authentication)):
    queue = manifest.get_by_state(ItemState.AWAITING_APPROVAL)
    return templates.TemplateResponse("review.html", {"request": request, "page": "review", "queue": queue})

@app.get("/playlist", response_class=HTMLResponse)
async def playlist_page(request: Request, user: str = Depends(security.require_authentication)):
    playlist = manifest.get_by_state(ItemState.APPROVED)
    return templates.TemplateResponse("playlist.html", {"request": request, "page": "playlist", "playlist": playlist})

# --- API v1 Routes ---

# --- Status/Health ---
@app.get("/api/v1/status")
async def get_status(user: str = Depends(security.require_authentication)):
    is_streaming = app_state.streamer_instance.is_streaming() if app_state.streamer_instance else False
    return {"streaming_status": "ONLINE" if is_streaming else "OFFLINE", "pipeline_status": "IDLE"}

@app.get("/healthz")
async def health_check():
    return {"status": "ok"}

# --- Pipeline ---
@app.post("/api/v1/pipeline/start")
async def start_pipeline(user: str = Depends(security.require_authentication)):
    from ..workers import run_full_pipeline
    run_full_pipeline()
    return JSONResponse({"message": "Pipeline started in background."}, status_code=202)

# --- Review & Playlist ---
@app.get("/api/v1/review/queue", response_model=List[ManifestItem])
async def get_review_queue(user: str = Depends(security.require_authentication)):
    return manifest.get_by_state(ItemState.AWAITING_APPROVAL)

@app.post("/api/v1/review/{item_id}/approve")
async def approve_item(item_id: str, user: str = Depends(security.require_authentication)):
    item = manifest.get_by_id(item_id)
    if not item or item['state'] != ItemState.AWAITING_APPROVAL:
        raise HTTPException(status_code=404, detail="Item not found or not awaiting approval")

    manifest.update_item(item_id, {"state": ItemState.APPROVED, "approved_by": "human"})
    await log_event("review", {"item_id": item_id, "action": "approved"})
    return {"message": f"Item {item_id} approved."}

@app.post("/api/v1/review/{item_id}/reject")
async def reject_item(item_id: str, reason: str = Form("No reason provided"), user: str = Depends(security.require_authentication)):
    item = manifest.get_by_id(item_id)
    if not item or item['state'] != ItemState.AWAITING_APPROVAL:
        raise HTTPException(status_code=404, detail="Item not found or not awaiting approval")

    manifest.update_item(item_id, {"state": ItemState.REJECTED, "rejected_reason": reason})
    await log_event("review", {"item_id": item_id, "action": "rejected", "reason": reason})
    return {"message": f"Item {item_id} rejected."}

@app.get("/api/v1/playlist", response_model=List[ManifestItem])
async def get_playlist(user: str = Depends(security.require_authentication)):
    return manifest.get_by_state(ItemState.APPROVED)

# --- Publish/Stream ---
@app.post("/api/v1/publish/start")
async def start_stream(user: str = Depends(security.require_authentication)):
    if app_state.streamer_instance and app_state.streamer_instance.is_streaming():
        raise HTTPException(status_code=400, detail="Stream is already running.")

    video_path = OUTPUT_DIR / "final_video.mp4"
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="Final video not found. Please render first.")

    app_state.streamer_instance = streamer.Streamer(video_path)
    app_state.streamer_instance.start()
    await log_event("stream", {"status": "started"})
    return {"message": "Stream started."}

@app.post("/api/v1/publish/stop")
async def stop_stream(user: str = Depends(security.require_authentication)):
    if not app_state.streamer_instance or not app_state.streamer_instance.is_streaming():
        raise HTTPException(status_code=400, detail="Stream is not running.")

    app_state.streamer_instance.stop()
    app_state.streamer_instance = None
    await log_event("stream", {"status": "stopped"})
    return {"message": "Stream stopped."}

# --- Config ---
@app.get("/api/v1/config")
async def get_config(user: str = Depends(security.require_authentication)):
    """Returns the current configuration, with sensitive keys masked."""
    # In a real app, you would implement proper masking
    return config.app_config.all_settings

@app.put("/api/v1/config")
async def update_config(
    user: str = Depends(security.require_authentication),
    rtmp_url: str = Form(None),
    stream_key: str = Form(None),
    openai_api_key: str = Form(None),
    admin_pass_hash: str = Form(None),
):
    """Updates and saves the application's configuration."""
    update_data = UpdateConfigRequest(
        rtmp_url=rtmp_url,
        stream_key=stream_key,
        openai_api_key=openai_api_key,
        admin_pass_hash=admin_pass_hash,
    )

    # Convert Pydantic model to a dictionary, excluding unset fields
    update_dict = update_data.model_dump(exclude_unset=True)

    # Filter out any empty string values so we don't overwrite with blank data
    filtered_updates = {k: v for k, v in update_dict.items() if v}

    if not filtered_updates:
        return HTMLResponse(
            "<div id='settings-form-response' class='text-yellow-600 font-semibold'>No new settings provided.</div>",
            status_code=200
        )

    try:
        # Save the filtered updates
        config.app_config.save(filtered_updates)
        # Reload the configuration in the running application
        config.app_config.load()
        await log_event("config", {"status": "updated", "keys": list(filtered_updates.keys())})

        return HTMLResponse(
            "<div id='settings-form-response' class='text-green-600 font-semibold p-4 bg-green-50 rounded-lg'>Settings updated successfully! The application has been reloaded with the new configuration.</div>",
            status_code=200
        )
    except config.ConfigError as e:
        await log_event("error", {"message": f"Failed to update config: {e}"})
        return HTMLResponse(
            f"<div id='settings-form-response' class='text-red-600 font-semibold p-4 bg-red-50 rounded-lg'>Error saving settings: {e}</div>",
            status_code=400
        )

# --- Exception Handler for redirects ---
@app.exception_handler(HTTPException)
async def http_exception_handler(request, exc):
    if exc.status_code == 401:
        return RedirectResponse(url='/login')
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
    )
