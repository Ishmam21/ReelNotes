"""Fixture-backed HTTP tests. These do not verify PostgreSQL concurrency."""
from contextlib import contextmanager
from datetime import datetime, timezone
from uuid import uuid4
from unittest.mock import MagicMock
import pytest
from fastapi.testclient import TestClient
from sqlalchemy.dialects import postgresql
from app import main
from app.schemas import PlaylistCreate


def test_duplicate_tracking_urls_return_existing_membership(monkeypatch):
    playlist_id, video_id = uuid4(), uuid4()
    row = dict(id=video_id, position=0, title="Constraint advice", source_url="https://www.instagram.com/reel/AbC/", thumbnail_webp=None, state="queued", error_code=None, error_message=None, claims=None)
    connection = MagicMock()
    connection.execute.return_value.mappings.return_value.first.return_value = row
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    monkeypatch.setattr(main, "require_playlist", lambda *args, **kwargs: {"id": playlist_id})
    client = TestClient(main.app)
    responses = [client.post(f"/playlists/{playlist_id}/items", json={"url": url}) for url in ("https://instagram.com/reel/AbC/?igsh=1", "https://www.instagram.com/reel/AbC/#tracking")]
    assert [response.status_code for response in responses] == [200, 200]
    assert responses[0].json() == responses[1].json()
    assert responses[0].json()["video_id"] == str(video_id)
    # Reused membership must not insert a second video or membership.
    assert all(str(call.args[0]).startswith("SELECT") for call in connection.execute.call_args_list)


def test_reject_url_before_database(monkeypatch):
    monkeypatch.setattr(main, "get_engine", lambda: pytest.fail("Invalid URLs must not access the database"))
    response = TestClient(main.app).post(f"/playlists/{uuid4()}/items", json={"url": "https://evil.test/reel/test/"})
    assert response.status_code == 422


def test_empty_playlist_name_rejected():
    response = TestClient(main.app).post("/playlists", json={"name": "   "})
    assert response.status_code == 422


def test_card_excludes_binary_and_transcripts():
    row = dict(id=uuid4(), position=3, title="Test", source_url="https://www.instagram.com/reel/Test/", thumbnail_webp=b"webp", duration_ms=1000, segments=[{"text": "private payload"}], state="ready", error_code=None, error_message=None, claims=[])
    result = main.card(row)
    assert "segments" not in result and "thumbnail_webp" not in result
    assert result["thumbnail_url"].endswith("/thumbnail")
    assert result["claims_count"] == 0


def test_remove_only_membership(monkeypatch):
    connection = MagicMock()
    engine = MagicMock()
    engine.begin.return_value.__enter__.return_value = connection
    monkeypatch.setattr(main, "get_engine", lambda: engine)
    monkeypatch.setattr(main, "require_playlist", lambda *args, **kwargs: {})
    assert TestClient(main.app).delete(f"/playlists/{uuid4()}/items/{uuid4()}").status_code == 204
    query = str(connection.execute.call_args.args[0].compile(dialect=postgresql.dialect()))
    assert query.startswith("DELETE FROM reelnotes.playlist_items")
    assert "DELETE FROM reelnotes.videos" not in query

@pytest.mark.parametrize('origin', ['http://localhost:3000', 'http://127.0.0.1:3000'])
def test_loopback_cors_preflight(origin):
    response = TestClient(main.app).options('/playlists', headers={
        'Origin': origin, 'Access-Control-Request-Method': 'POST',
        'Access-Control-Request-Headers': 'content-type'})
    assert response.status_code == 200
    assert response.headers['access-control-allow-origin'] == origin


def test_cors_rejects_unrelated_origin():
    response = TestClient(main.app).options('/playlists', headers={
        'Origin': 'https://unrelated.example', 'Access-Control-Request-Method': 'POST'})
    assert response.status_code == 400
    assert 'access-control-allow-origin' not in response.headers


def test_database_handler_logs_original_traceback(monkeypatch, caplog):
    from sqlalchemy.exc import OperationalError
    def broken_engine():
        raise OperationalError('SELECT 1', {'secret': 'must-not-be-logged'},
                               RuntimeError('connection diagnostic'), hide_parameters=True)
    monkeypatch.setattr(main, 'get_engine', broken_engine)
    with caplog.at_level('ERROR', logger='app.main'):
        response = TestClient(main.app).get('/playlists')
    assert response.status_code == 503
    assert 'connection diagnostic' in caplog.text
    assert 'broken_engine' in caplog.text
    assert 'must-not-be-logged' not in caplog.text
