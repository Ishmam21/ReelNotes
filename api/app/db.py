"""Mappings only: the owner creates the reelnotes schema outside this application."""
import os
from functools import lru_cache
from pathlib import Path
from dotenv import load_dotenv
from sqlalchemy import MetaData, Table, Column, String, Integer, DateTime, LargeBinary, ForeignKey, create_engine
from sqlalchemy.dialects.postgresql import UUID, JSONB
from sqlalchemy.engine import make_url

# This local app uses api/.env as its configuration, even if the shell has older exports.
load_dotenv(Path(__file__).resolve().parents[1] / ".env", override=True)
metadata = MetaData(schema="reelnotes")
accounts = Table("accounts", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True), Column("email", String, nullable=False, unique=True),
    Column("password_hash", String, nullable=False))
sessions = Table("sessions", metadata,
    Column("token_hash", LargeBinary, primary_key=True),
    Column("account_id", UUID(as_uuid=True), ForeignKey("reelnotes.accounts.id", ondelete="CASCADE"), nullable=False),
    Column("expires_at", DateTime(timezone=True), nullable=False))
playlists = Table("playlists", metadata, Column("id", UUID(as_uuid=True), primary_key=True), Column("name", String),
    Column("created_at", DateTime(timezone=True)), Column("owner_id", UUID(as_uuid=True), ForeignKey("reelnotes.accounts.id")))
videos = Table("videos", metadata,
    Column("id", UUID(as_uuid=True), primary_key=True), Column("shortcode", String), Column("source_url", String),
    Column("owner_id", UUID(as_uuid=True), ForeignKey("reelnotes.accounts.id")),
    Column("title", String), Column("creator", String), Column("duration_ms", Integer), Column("thumbnail_webp", LargeBinary),
    Column("state", String), Column("attempts", Integer), Column("lease_token", UUID(as_uuid=True)), Column("lease_until", DateTime(timezone=True)),
    Column("error_code", String), Column("error_message", String), Column("segments", JSONB), Column("claims", JSONB), Column("pipeline_version", String),
    Column("created_at", DateTime(timezone=True)), Column("updated_at", DateTime(timezone=True)))
playlist_items = Table("playlist_items", metadata, Column("playlist_id", UUID(as_uuid=True), primary_key=True), Column("video_id", UUID(as_uuid=True), primary_key=True), Column("position", Integer))
guides = Table("guides", metadata, Column("id", UUID(as_uuid=True), primary_key=True), Column("playlist_id", UUID(as_uuid=True)), Column("input_hash", String), Column("input_snapshot", JSONB), Column("result", JSONB), Column("markdown", String), Column("created_at", DateTime(timezone=True)))

@lru_cache
def get_engine():
    value = os.getenv("DATABASE_URL")
    if not value:
        raise RuntimeError("Set DATABASE_URL in api/.env to the owner-provided PostgreSQL database.")
    url = make_url(value)
    if url.get_backend_name() not in ("postgres", "postgresql"):
        raise RuntimeError("DATABASE_URL must use PostgreSQL.")
    return create_engine(url.set(drivername="postgresql+psycopg"), pool_size=3, max_overflow=2, pool_pre_ping=True, hide_parameters=True)
