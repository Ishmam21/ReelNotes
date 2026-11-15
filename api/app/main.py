import base64
import json
import logging
import os
from datetime import datetime, timezone
from uuid import UUID, uuid4
from fastapi import FastAPI, HTTPException, Response
from fastapi.encoders import jsonable_encoder
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import select, func, delete, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.exc import SQLAlchemyError
from starlette.responses import JSONResponse
from .db import get_engine, playlists, videos, playlist_items, guides
from .transcribe import has_committed_transcript
from .schemas import (PlaylistCreate, ItemCreate, PlaylistResponse, PlaylistSummary, PlaylistDetail, VideoCard, GuideResponse, RetryResponse)

app = FastAPI(title="ReelNotes")
logger = logging.getLogger(__name__)
web_origin = os.getenv("WEB_ORIGIN", "http://localhost:3000").rstrip("/")
allowed_origins = [web_origin]
# Browsers treat localhost and 127.0.0.1 as distinct origins.
from urllib.parse import urlsplit
origin = urlsplit(web_origin)
if origin.scheme == "http" and origin.hostname in ("localhost", "127.0.0.1"):
    port = f":{origin.port}" if origin.port else ""
    allowed_origins = [f"http://localhost{port}", f"http://127.0.0.1{port}"]
app.add_middleware(CORSMiddleware, allow_origins=allowed_origins, allow_methods=["GET", "POST", "DELETE"], allow_headers=["Content-Type"])

@app.exception_handler(SQLAlchemyError)
def database_error(request, exc):
    # FastAPI may run this handler outside the original except block.
    logger.exception("Database request failed: %s %s", request.method, request.url.path,
                     exc_info=(type(exc), exc, exc.__traceback__))
    original = getattr(exc, "orig", None)
    code = getattr(original, "sqlstate", None)
    # Return fixed descriptions, never raw errors, SQL parameters or connection URLs.
    messages = {
        "42P01": "A required database table is missing. Check the owner-managed reelnotes schema.",
        "42703": "A required database column is missing. Check the owner-managed reelnotes schema.",
        "42501": "The database user lacks permission for this operation.",
        "23502": "The database requires a field the app did not supply. Check the API terminal for the column name.",
        "23514": "The database rejected a value under a check constraint. Check the API terminal for the constraint name.",
        "23505": "This operation conflicts with an existing database record.",
        "22P02": "A value does not match the database's expected type or enum. Check the API terminal.",
        "28P01": "Database authentication failed. Check the configured database credentials.",
    }
    detail = messages.get(code)
    if detail is None and "certificate verify failed" in str(original).lower():
        detail = "Database TLS certificate verification failed. Restart the API to load api/.env and its SSL_CERT_FILE setting."
    if detail is None:
        detail = "Database request failed. The API terminal contains the underlying error and traceback."
    return JSONResponse(status_code=503, content={"detail": detail})

@app.exception_handler(RuntimeError)
def configuration_error(request, exc):
    return JSONResponse(status_code=503, content={"detail": "Service unavailable. Check the API configuration, then try again."})

def require_playlist(conn, playlist_id, lock=False):
    query = select(playlists).where(playlists.c.id == playlist_id)
    if lock:
        query = query.with_for_update()
    row = conn.execute(query).mappings().first()
    if row is None:
        raise HTTPException(404, "Playlist not found")
    return row

def require_video(conn, video_id):
    row = conn.execute(select(videos).where(videos.c.id == video_id)).mappings().first()
    if row is None:
        raise HTTPException(404, "Video not found")
    return row

def ordered_items(conn, playlist_id):
    return conn.execute(select(videos, playlist_items.c.position).join(playlist_items, videos.c.id == playlist_items.c.video_id).where(playlist_items.c.playlist_id == playlist_id).order_by(playlist_items.c.position)).mappings().all()

def card(row):
    if row['state'] == 'ready' and not has_committed_transcript(row):
        row = dict(row, state='failed', error_code='incomplete_processing',
                   error_message='Media processing was skipped. Click Retry to download and transcribe this Reel.')
    return {"video_id": row["id"], "position": row["position"], "title": row["title"], "source_url": row["source_url"], "thumbnail_url": f'/videos/{row["id"]}/thumbnail' if row["thumbnail_webp"] else None, "state": row["state"], "error_code": row["error_code"], "error_message": row["error_message"], "claims_count": len(row["claims"]) if row["claims"] is not None else None}

@app.post("/playlists", status_code=201, response_model=PlaylistResponse)
def create_playlist(body: PlaylistCreate):
    with get_engine().begin() as conn:
        return dict(conn.execute(insert(playlists).values(id=uuid4(), name=body.name, created_at=datetime.now(timezone.utc)).returning(playlists)).mappings().one())

@app.get("/playlists", response_model=list[PlaylistSummary])
def list_playlists():
    with get_engine().connect() as conn:
        rows = conn.execute(select(playlists, func.count(playlist_items.c.video_id).label("item_count")).outerjoin(playlist_items, playlists.c.id == playlist_items.c.playlist_id).group_by(playlists.c.id).order_by(playlists.c.created_at.desc())).mappings().all()
        return [dict(row) for row in rows]

@app.get("/playlists/{playlist_id}", response_model=PlaylistDetail)
def playlist_detail(playlist_id: UUID):
    with get_engine().connect() as conn:
        row = require_playlist(conn, playlist_id)
        return {**dict(row), "items": [card(item) for item in ordered_items(conn, playlist_id)]}

@app.post("/playlists/{playlist_id}/items", response_model=VideoCard)
def add_item(playlist_id: UUID, body: ItemCreate, response: Response):
    from .ingest import canonicalize_url
    try:
        shortcode, url = canonicalize_url(body.url)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    with get_engine().begin() as conn:
        # Serialize membership/position changes, including simultaneous duplicate imports.
        require_playlist(conn, playlist_id, lock=True)
        existing = conn.execute(select(videos, playlist_items.c.position).join(playlist_items, videos.c.id == playlist_items.c.video_id).where(playlist_items.c.playlist_id == playlist_id, videos.c.shortcode == shortcode)).mappings().first()
        if existing:
            return card(existing)
        count, highest = conn.execute(select(func.count(), func.max(playlist_items.c.position)).where(playlist_items.c.playlist_id == playlist_id)).one()
        if count >= 10:
            raise HTTPException(409, "A playlist can contain at most ten videos. Remove one before adding another.")
        now = datetime.now(timezone.utc)
        conn.execute(insert(videos).values(id=uuid4(), shortcode=shortcode, source_url=url, title=f"Instagram Reel {shortcode}", state="queued", attempts=0, created_at=now, updated_at=now).on_conflict_do_nothing(index_elements=[videos.c.shortcode]))
        video = conn.execute(select(videos).where(videos.c.shortcode == shortcode)).mappings().one()
        position = (highest if highest is not None else 0) + 1
        conn.execute(insert(playlist_items).values(playlist_id=playlist_id, video_id=video["id"], position=position))
        response.status_code = 202 if video["state"] in ("queued", "downloading", "transcribing", "extracting") else 200
        return card({**video, "position": position})

@app.delete("/playlists/{playlist_id}/items/{video_id}", status_code=204)
def remove_item(playlist_id: UUID, video_id: UUID):
    with get_engine().begin() as conn:
        require_playlist(conn, playlist_id, lock=True)
        conn.execute(delete(playlist_items).where(playlist_items.c.playlist_id == playlist_id, playlist_items.c.video_id == video_id))
    return Response(status_code=204)

@app.post("/videos/{video_id}/retry", response_model=RetryResponse)
def retry_video(video_id: UUID):
    with get_engine().begin() as conn:
        row = require_video(conn, video_id)
        if row["state"] == "failed" or (row['state'] == 'ready' and not has_committed_transcript(row)):
            conn.execute(update(videos).where(videos.c.id == video_id, videos.c.state == row['state']).values(state="queued", attempts=0, lease_token=None, lease_until=None, error_code=None, error_message=None, updated_at=datetime.now(timezone.utc)))
        state = conn.execute(select(videos.c.state).where(videos.c.id == video_id)).scalar_one()
        return {"video_id": video_id, "state": state}

@app.get("/videos/{video_id}/thumbnail")
def thumbnail(video_id: UUID):
    with get_engine().connect() as conn:
        row = require_video(conn, video_id)
        if not row["thumbnail_webp"]:
            raise HTTPException(404, "Thumbnail unavailable")
        return Response(bytes(row["thumbnail_webp"]), media_type="image/webp")

@app.get("/videos/{video_id}/transcript")
def transcript(video_id: UUID):
    with get_engine().connect() as conn:
        row = require_video(conn, video_id)
        return {"video_id": video_id, "segments": row["segments"] or []}

@app.get("/playlists/{playlist_id}/manifest")
def manifest(playlist_id: UUID):
    with get_engine().connect() as conn:
        playlist = require_playlist(conn, playlist_id)
        items = []
        for row in ordered_items(conn, playlist_id):
            item = card(row)
            item.pop("thumbnail_url")
            item["thumbnail_data_uri"] = "data:image/webp;base64," + base64.b64encode(row["thumbnail_webp"]).decode("ascii") if row["thumbnail_webp"] else None
            items.append(item)
        data = {"id": playlist_id, "name": playlist["name"], "items": items}
    return Response(json.dumps(jsonable_encoder(data), ensure_ascii=False, indent=2), media_type="application/json", headers={"Content-Disposition": 'attachment; filename="playlist.json"'})

@app.post("/playlists/{playlist_id}/guides", response_model=GuideResponse)
def generate(playlist_id: UUID):
    from .guide import build_snapshot, snapshot_hash, generate_guide
    with get_engine().begin() as conn:
        playlist = require_playlist(conn, playlist_id, lock=True)
        items = ordered_items(conn, playlist_id)
        blocking = [str(row["id"]) for row in items if row["state"] != "ready" or not has_committed_transcript(row)]
        if not items or blocking:
            raise HTTPException(409, {"message": "Add a video and wait for every clip to be ready; retry or remove failed clips.", "blocking_item_ids": blocking})
        snapshot_items = [{key: value for key, value in dict(row).items() if key != "thumbnail_webp"} for row in items]
        snapshot = build_snapshot(playlist["name"], jsonable_encoder(snapshot_items))
        digest = snapshot_hash(snapshot)
        existing = conn.execute(select(guides.c.id, guides.c.markdown, guides.c.created_at).where(guides.c.playlist_id == playlist_id, guides.c.input_hash == digest)).mappings().first()
        if existing:
            return dict(existing)
    # The connection is released before the model call; snapshots are immutable.
    try:
        result, markdown = generate_guide(snapshot)
    except Exception as exc:
        raise HTTPException(502, "Guide generation failed. Check model configuration and try again.") from exc
    with get_engine().begin() as conn:
        conn.execute(insert(guides).values(id=uuid4(), playlist_id=playlist_id, input_hash=digest, input_snapshot=snapshot, result=result, markdown=markdown, created_at=datetime.now(timezone.utc)).on_conflict_do_nothing(index_elements=[guides.c.playlist_id, guides.c.input_hash]))
        return dict(conn.execute(select(guides.c.id, guides.c.markdown, guides.c.created_at).where(guides.c.playlist_id == playlist_id, guides.c.input_hash == digest)).mappings().one())

@app.get("/playlists/{playlist_id}/guides", response_model=list[GuideResponse])
def guide_versions(playlist_id: UUID):
    with get_engine().connect() as conn:
        require_playlist(conn, playlist_id)
        return [dict(row) for row in conn.execute(select(guides.c.id, guides.c.markdown, guides.c.created_at).where(guides.c.playlist_id == playlist_id).order_by(guides.c.created_at.desc())).mappings()]

@app.get("/guides/{guide_id}/download")
def download_guide(guide_id: UUID):
    with get_engine().connect() as conn:
        markdown = conn.execute(select(guides.c.markdown).where(guides.c.id == guide_id)).scalar_one_or_none()
        if markdown is None:
            raise HTTPException(404, "Guide not found")
        return Response(markdown, media_type="text/markdown; charset=utf-8", headers={"Content-Disposition": 'attachment; filename="AGENTS.md"'})

@app.get("/guides/{guide_id}/evidence")
def guide_evidence(guide_id: UUID):
    with get_engine().connect() as conn:
        row = conn.execute(select(guides.c.input_snapshot, guides.c.result).where(guides.c.id == guide_id)).mappings().first()
        if row is None:
            raise HTTPException(404, "Guide not found")
        # Read the immutable saved evidence, not the playlist's current videos.
        return {"snapshot": row['input_snapshot'], "result": row['result']}
