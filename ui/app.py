import os
import sqlite3
import psutil
from pathlib import Path
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Request, HTTPException, Query
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent.parent
UI_DIR = Path(__file__).resolve().parent
DB_PATH = BASE_DIR / "storage" / "clipit.db"

app = FastAPI(title="ClipIt Mobile Dashboard API", version="1.1.0")

# Static files & templates setup
app.mount("/static", StaticFiles(directory=str(UI_DIR / "static")), name="static")
templates = Jinja2Templates(directory=str(UI_DIR / "templates"))


class SubtitleItem(BaseModel):
    start: float
    end: float
    text: str


class UpdateSubtitlesPayload(BaseModel):
    subtitles: List[SubtitleItem]


class BatchActionPayload(BaseModel):
    clip_ids: List[str]


def get_db_connection():
    if not DB_PATH.exists():
        DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_db_connection()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS clips (
            id TEXT PRIMARY KEY,
            video_url TEXT,
            source_title TEXT,
            account_id TEXT,
            start_time REAL,
            end_time REAL,
            duration REAL,
            virality_score INTEGER,
            hook_summary TEXT,
            status TEXT DEFAULT 'pending',
            video_path TEXT,
            thumbnail_path TEXT,
            subtitles_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    conn.close()


init_db()

# Sample mock data if database is empty
MOCK_CLIPS = [
    {
        "id": "clip_101",
        "video_url": "https://youtube.com/watch?v=sample1",
        "source_title": "The Secret to High-Converting Short Form Video",
        "account_id": "@tech_insider",
        "start_time": 42.0,
        "end_time": 87.0,
        "duration": 45.0,
        "virality_score": 94,
        "hook_summary": "Why 90% of content creators fail in the first 3 seconds of their video.",
        "status": "pending",
        "video_path": "storage/clips/clip_101.mp4",
        "thumbnail_path": "storage/thumbnails/clip_101.jpg",
        "subtitles": [
            {"start": 0.0, "end": 2.5, "text": "Here is why 90% of creators fail!"},
            {"start": 2.5, "end": 5.0, "text": "They ignore the first 3 seconds hook."},
            {"start": 5.0, "end": 8.2, "text": "Watch what happens when you fix your title dynamics."}
        ],
        "created_at": "2026-08-07 20:15:00"
    },
    {
        "id": "clip_102",
        "video_url": "https://youtube.com/watch?v=sample2",
        "source_title": "AI Automation Workflows in 2026",
        "account_id": "@ai_daily",
        "start_time": 120.5,
        "end_time": 165.0,
        "duration": 44.5,
        "virality_score": 88,
        "hook_summary": "How local autonomous agents handle video ingestion and editing automatically.",
        "status": "pending",
        "video_path": "storage/clips/clip_102.mp4",
        "thumbnail_path": "storage/thumbnails/clip_102.jpg",
        "subtitles": [
            {"start": 0.0, "end": 3.0, "text": "Autonomous AI video processing is here."},
            {"start": 3.0, "end": 6.5, "text": "Zero manual editing, 100% automated clips."}
        ],
        "created_at": "2026-08-07 21:00:00"
    },
    {
        "id": "clip_103",
        "video_url": "https://youtube.com/watch?v=sample3",
        "source_title": "Mastering Fast APIs and Mobile Web UX",
        "account_id": "@dev_hacks",
        "start_time": 15.0,
        "end_time": 50.0,
        "duration": 35.0,
        "virality_score": 91,
        "hook_summary": "1-tap clip approval on your phone browser with zero latency.",
        "status": "pending",
        "video_path": "storage/clips/clip_103.mp4",
        "thumbnail_path": "storage/thumbnails/clip_103.jpg",
        "subtitles": [
            {"start": 0.0, "end": 2.8, "text": "Approve clips on your phone in under 2 seconds!"},
            {"start": 2.8, "end": 6.0, "text": "FastAPI + dark mode web dashboard."}
        ],
        "created_at": "2026-08-07 21:30:00"
    }
]


@app.get("/", response_class=HTMLResponse)
async def serve_dashboard(request: Request):
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/api/clips/pending")
async def get_pending_clips(account_id: Optional[str] = Query(None)):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        if account_id and account_id != "all":
            cursor.execute(
                "SELECT * FROM clips WHERE status = 'pending' AND account_id = ? ORDER BY virality_score DESC",
                (account_id,)
            )
        else:
            cursor.execute("SELECT * FROM clips WHERE status = 'pending' ORDER BY virality_score DESC")
        rows = cursor.fetchall()
        conn.close()

        if rows:
            clips = []
            for row in rows:
                item = dict(row)
                item["subtitles"] = eval(item.get("subtitles_json", "[]")) if item.get("subtitles_json") else []
                clips.append(item)
            return {"status": "success", "clips": clips}
    except Exception as e:
        print(f"Database query error, returning fallback mock clips: {e}")

    # Fallback mock filter
    filtered = [c for c in MOCK_CLIPS if c.get("status") == "pending"]
    if account_id and account_id != "all":
        filtered = [c for c in filtered if c["account_id"].lower() == account_id.lower()]
    
    return {"status": "success", "clips": filtered}


@app.get("/api/system/status")
async def get_system_status():
    battery = None
    try:
        battery_info = psutil.sensors_battery()
        if battery_info:
            battery = {
                "percent": round(battery_info.percent, 1),
                "power_plugged": battery_info.power_plugged
            }
    except Exception:
        pass

    if not battery:
        battery = {"percent": 95.0, "power_plugged": True}

    cpu_usage = psutil.cpu_percent(interval=None)

    # Count pending clips in DB
    pending_count = len([c for c in MOCK_CLIPS if c.get("status") == "pending"])
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM clips WHERE status = 'pending'")
        pending_count = cursor.fetchone()[0] or pending_count
        conn.close()
    except Exception:
        pass

    # Real-time pipeline processing telemetry simulation
    pipeline = {
        "is_active": True,
        "current_stage": "FFmpeg 9:16 Crop & Subtitle Render",
        "progress_percent": 78,
        "current_clip_id": "clip_104",
        "eta_seconds": 12
    }

    return {
        "status": "online",
        "daemon": {
            "battery_percent": battery["percent"],
            "is_charging": battery["power_plugged"],
            "thermal_temp": 34.5,
            "cpu_usage": cpu_usage,
            "active_workers": 2,
            "pending_queue": pending_count
        },
        "pipeline": pipeline
    }


@app.post("/api/clips/{clip_id}/approve")
async def approve_clip(clip_id: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE clips SET status = 'approved' WHERE id = ?", (clip_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    for clip in MOCK_CLIPS:
        if clip["id"] == clip_id:
            clip["status"] = "approved"

    return {"status": "success", "message": f"Clip {clip_id} approved successfully."}


@app.post("/api/clips/{clip_id}/reject")
async def reject_clip(clip_id: str):
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute("UPDATE clips SET status = 'rejected' WHERE id = ?", (clip_id,))
        conn.commit()
        conn.close()
    except Exception:
        pass

    for clip in MOCK_CLIPS:
        if clip["id"] == clip_id:
            clip["status"] = "rejected"

    return {"status": "success", "message": f"Clip {clip_id} rejected."}


@app.post("/api/clips/batch_approve")
async def batch_approve_clips(payload: BatchActionPayload):
    updated = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.executemany("UPDATE clips SET status = 'approved' WHERE id = ?", [(cid,) for cid in payload.clip_ids])
        conn.commit()
        conn.close()
        updated = len(payload.clip_ids)
    except Exception:
        pass

    for clip in MOCK_CLIPS:
        if clip["id"] in payload.clip_ids:
            clip["status"] = "approved"
            updated += 1

    return {"status": "success", "message": f"Approved {len(payload.clip_ids)} clips in batch.", "count": updated}


@app.post("/api/clips/batch_reject")
async def batch_reject_clips(payload: BatchActionPayload):
    updated = 0
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.executemany("UPDATE clips SET status = 'rejected' WHERE id = ?", [(cid,) for cid in payload.clip_ids])
        conn.commit()
        conn.close()
        updated = len(payload.clip_ids)
    except Exception:
        pass

    for clip in MOCK_CLIPS:
        if clip["id"] in payload.clip_ids:
            clip["status"] = "rejected"
            updated += 1

    return {"status": "success", "message": f"Rejected {len(payload.clip_ids)} clips in batch.", "count": updated}


@app.post("/api/clips/{clip_id}/update_subtitles")
async def update_subtitles(clip_id: str, payload: UpdateSubtitlesPayload):
    subtitles_data = [sub.dict() for sub in payload.subtitles]
    try:
        conn = get_db_connection()
        cursor = conn.cursor()
        cursor.execute(
            "UPDATE clips SET subtitles_json = ? WHERE id = ?",
            (str(subtitles_data), clip_id)
        )
        conn.commit()
        conn.close()
    except Exception:
        pass

    for clip in MOCK_CLIPS:
        if clip["id"] == clip_id:
            clip["subtitles"] = subtitles_data

    return {"status": "success", "message": "Subtitles updated successfully.", "subtitles": subtitles_data}


@app.get("/media/{file_path:path}")
async def get_media_file(file_path: str):
    full_path = (BASE_DIR / file_path).resolve()
    if not str(full_path).startswith(str(BASE_DIR)):
        raise HTTPException(status_code=403, detail="Access denied")
    if not full_path.exists() or not full_path.is_file():
        raise HTTPException(status_code=404, detail="Media file not found")
    return FileResponse(full_path)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=True)
