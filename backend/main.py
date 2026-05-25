from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from app.config import get_config, patch_config
from app.game_loop import GameLoop
from app.state_store import store

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")

# ── Lifespan ──────────────────────────────────────────────────────────────────

game_loop = GameLoop(store)


@asynccontextmanager
async def lifespan(app: FastAPI):
    cfg = get_config()
    store.init({
        "model": cfg.ai_model,
        "mgbaUrl": cfg.mgba_http_base_url,
        "startedAt": datetime.utcnow().isoformat(),
    })
    log.info("FastAPI server ready. Dashboard at http://0.0.0.0:8000/")
    yield
    game_loop.stop()


# ── App ───────────────────────────────────────────────────────────────────────

app = FastAPI(title="Pokemon Agent Controller", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Static files (controller dashboard) ───────────────────────────────────────

_dashboard_dir = Path(__file__).parent.parent / "dashboard"
if _dashboard_dir.exists():
    app.mount("/dashboard", StaticFiles(directory=str(_dashboard_dir), html=True), name="dashboard")


# ── WebSocket ─────────────────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await store.connect(ws)
    try:
        while True:
            await ws.receive_text()   # keep connection alive, ignore pings
    except WebSocketDisconnect:
        store.disconnect(ws)
    except Exception:
        store.disconnect(ws)


# ── REST: State ───────────────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state():
    from app.state_store import _serialize_state
    return JSONResponse(_serialize_state(store.get_state()))


# ── REST: Loop Control ────────────────────────────────────────────────────────

@app.post("/api/loop/start")
async def loop_start():
    if game_loop.status == "running":
        raise HTTPException(400, "Loop is already running")
    cfg = get_config()
    store.get_state().meta.update({"model": cfg.ai_model})
    game_loop.start()
    return {"status": game_loop.status}


@app.post("/api/loop/stop")
async def loop_stop():
    game_loop.stop()
    return {"status": game_loop.status}


@app.post("/api/loop/pause")
async def loop_pause():
    game_loop.pause()
    return {"status": game_loop.status}


@app.post("/api/loop/resume")
async def loop_resume():
    game_loop.resume()
    return {"status": game_loop.status}


@app.get("/api/loop/status")
async def loop_status():
    return {"status": game_loop.status}


# ── REST: Config ──────────────────────────────────────────────────────────────

class ConfigPatch(BaseModel):
    ai_model: str | None = None
    system_prompt: str | None = None
    directional_hold_frames: int | None = None
    button_tap_frames: int | None = None
    post_action_settle_frames: int | None = None
    black_frame_max_polls: int | None = None
    min_turns_to_keep: int | None = None
    max_tokens: int | None = None
    mgba_http_base_url: str | None = None


@app.get("/api/config")
async def get_config_endpoint():
    cfg = get_config()
    return {
        "ai_model": cfg.ai_model,
        "system_prompt": cfg.system_prompt,
        "directional_hold_frames": cfg.directional_hold_frames,
        "button_tap_frames": cfg.button_tap_frames,
        "post_action_settle_frames": cfg.post_action_settle_frames,
        "black_frame_max_polls": cfg.black_frame_max_polls,
        "min_turns_to_keep": cfg.min_turns_to_keep,
        "max_tokens": cfg.max_tokens,
        "mgba_http_base_url": cfg.mgba_http_base_url,
    }


@app.patch("/api/config")
async def patch_config_endpoint(body: ConfigPatch):
    updates = {k: v for k, v in body.model_dump().items() if v is not None}
    if not updates:
        raise HTTPException(400, "No fields to update")
    cfg = patch_config(**updates)
    # Update meta in store
    store.get_state().meta.update({"model": cfg.ai_model})
    return {"updated": updates, "config": {
        "ai_model": cfg.ai_model,
        "system_prompt": cfg.system_prompt,
        "directional_hold_frames": cfg.directional_hold_frames,
        "button_tap_frames": cfg.button_tap_frames,
        "post_action_settle_frames": cfg.post_action_settle_frames,
        "black_frame_max_polls": cfg.black_frame_max_polls,
        "min_turns_to_keep": cfg.min_turns_to_keep,
        "max_tokens": cfg.max_tokens,
        "mgba_http_base_url": cfg.mgba_http_base_url,
    }}


# ── REST: Emulator direct access ──────────────────────────────────────────────

@app.get("/api/emulator/status")
async def emulator_status():
    from app.emulator import MgbaHttpClient
    cfg = get_config()
    client = MgbaHttpClient(cfg.mgba_http_base_url)
    try:
        status = await client.status()
        return {
            "frame": status.frame,
            "gameTitle": status.game_title,
            "gameCode": status.game_code,
            "activeButtons": status.active_buttons,
        }
    except Exception as exc:
        raise HTTPException(503, f"Emulator unreachable: {exc}")
    finally:
        await client.close()


@app.get("/api/emulator/screenshot")
async def emulator_screenshot():
    from app.emulator import MgbaHttpClient
    from app.screenshot import process_screenshot, make_screenshot_path
    cfg = get_config()
    client = MgbaHttpClient(cfg.mgba_http_base_url)
    try:
        path = make_screenshot_path()
        await client.screenshot(path)
        data = process_screenshot(path, overlay_grid=True)
        return {"data": data, "mediaType": "image/png"}
    except Exception as exc:
        raise HTTPException(503, f"Screenshot failed: {exc}")
    finally:
        await client.close()


# ── Redirect root to dashboard ────────────────────────────────────────────────

@app.get("/")
async def root():
    from fastapi.responses import RedirectResponse
    return RedirectResponse("/dashboard/")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=8000, reload=False)
