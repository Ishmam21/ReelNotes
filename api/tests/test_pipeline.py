from types import SimpleNamespace
import httpx
import pytest
from app import transcribe
from app.ingest import canonicalize_url, choose_title
from app.transcribe import normalize_segments


def test_duplicate_tracking_urls():
    assert canonicalize_url('https://instagram.com/reel/Ab_-1/?utm=a#b') == canonicalize_url('https://www.instagram.com/reel/Ab_-1/')


def test_creator_prefixed_reel_url():
    expected = ('DbO58xwPayj', 'https://www.instagram.com/reel/DbO58xwPayj/')
    assert canonicalize_url('https://www.instagram.com/millee.md/reel/DbO58xwPayj/') == expected
    assert canonicalize_url('https://instagram.com/millee.md/reel/DbO58xwPayj?igsh=tracking#fragment') == expected


@pytest.mark.parametrize('url', ['http://instagram.com/reel/a', 'https://instagram.com:443/reel/a', 'https://user@instagram.com/reel/a', 'https://evilinstagram.com/reel/a', 'https://instagram.com/p/a', 'https://instagram.com/reel/a/b', 'https://instagram.com/reel/a%20'])
def test_reject_url(url):
    with pytest.raises(ValueError):
        canonicalize_url(url)


def test_missing_caption():
    assert choose_title({}, 'ABC') == 'Instagram Reel ABC'
    assert choose_title({'description': '\n Caption\nrest'}, 'ABC') == 'Caption'


def test_empty_speech_and_ids():
    assert normalize_segments([]) == []
    segments = [SimpleNamespace(start=0, end=1.2, text='  '), SimpleNamespace(start=1.2, end=2.4, text=' Advice ')]
    assert normalize_segments(segments) == [dict(id='s001', start_ms=1200, end_ms=2400, text='Advice')]


def test_invalid_timestamps():
    with pytest.raises(ValueError):
        normalize_segments([SimpleNamespace(start=1, end=1, text='Advice')])


@pytest.mark.parametrize('payload, expected', [
    ({'segments': [{'start': 0.25, 'end': 1.5, 'text': ' Advice '}]},
     [dict(id='s001', start_ms=250, end_ms=1500, text='Advice')]),
    ({'segments': []}, []),
])
def test_groq_upload_returns_normalized_segments(monkeypatch, tmp_path, payload, expected):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    audio = tmp_path / 'speech.wav'
    audio.write_bytes(b'fake-wav-data')

    def respond(request):
        assert request.method == 'POST'
        assert str(request.url) == 'https://api.groq.com/openai/v1/audio/transcriptions'
        assert request.headers['authorization'] == 'Bearer test-key'
        assert 'multipart/form-data' in request.headers['content-type']
        for field in (
            b'name="model"\r\n\r\nwhisper-large-v3-turbo',
            b'name="response_format"\r\n\r\nverbose_json',
            b'name="timestamp_granularities[]"\r\n\r\nsegment',
            b'name="file"; filename="speech.wav"',
            b'fake-wav-data',
        ):
            assert field in request.content
        return httpx.Response(200, json=payload)

    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        monkeypatch.setattr(transcribe.httpx, 'post', client.post)
        assert transcribe.transcribe_audio(audio) == expected


@pytest.mark.parametrize('status, payload, code', [
    (401, {'error': 'provider detail'}, 'transcription_config'),
    (429, {'error': 'provider detail'}, 'transcription_rate_limit'),
    (200, {'text': 'Missing the timestamped segments'}, 'transcription_invalid'),
])
def test_groq_failure_uses_safe_message(monkeypatch, tmp_path, status, payload, code):
    monkeypatch.setenv('GROQ_API_KEY', 'test-key')
    audio = tmp_path / 'speech.wav'
    audio.touch()
    monkeypatch.setattr(transcribe.httpx, 'post', lambda *args, **kwargs: httpx.Response(status, json=payload))
    with pytest.raises(transcribe.TranscriptionError) as error:
        transcribe.transcribe_audio(audio)
    assert error.value.code == code
    assert 'provider detail' not in str(error.value)


def test_groq_requires_worker_key_before_upload(monkeypatch, tmp_path):
    monkeypatch.delenv('GROQ_API_KEY', raising=False)
    with pytest.raises(transcribe.TranscriptionError, match='Set GROQ_API_KEY'):
        transcribe.transcribe_audio(tmp_path / 'unused.wav')


def test_resume_extraction_without_transcription():
    from app.worker import next_stage
    assert next_stage({'segments': [], 'duration_ms': 1000}) == 'extracting'
    assert next_stage({'segments': None}) == 'downloading'


def test_download_failure_is_actionable(monkeypatch, tmp_path):
    import subprocess
    from app import ingest
    def unavailable(*args, **kwargs):
        raise subprocess.CalledProcessError(1, ['downloader'])
    monkeypatch.setattr(ingest.subprocess, 'run', unavailable)
    with pytest.raises(ingest.IngestError) as error:
        ingest.download_reel('https://instagram.com/reel/abc/', tmp_path)
    assert error.value.code == 'source_unavailable'


def test_thumbnail_is_small_webp(tmp_path):
    from PIL import Image
    from app.ingest import webp_thumbnail
    import io
    path = tmp_path / 'large.png'
    Image.new('RGB', (900, 1000), color='red').save(path)
    data = webp_thumbnail(path)
    assert len(data) < 200 * 1024
    with Image.open(io.BytesIO(data)) as image:
        assert image.format == 'WEBP'
        assert image.width <= 480


def test_lost_lease_rejects_stage_write(monkeypatch):
    from contextlib import contextmanager
    from app import worker
    statements = []
    class Connection:
        def execute(self, query, params):
            statements.append(str(query))
            return SimpleNamespace(rowcount=0)
    class Engine:
        @contextmanager
        def begin(self):
            yield Connection()
    monkeypatch.setattr(worker, 'get_engine', lambda: Engine())
    with pytest.raises(worker.LeaseLost):
        worker.save_stage({'id': 'id', 'lease_token': 'token'}, state='ready')
    assert 'lease_token=:owner_token' in statements[0]
    assert 'lease_until > now()' in statements[0]


def test_retry_uses_committed_segments_and_cleans_temp(monkeypatch, tmp_path):
    from app import worker
    monkeypatch.setattr(worker, 'JOB_ROOT', tmp_path)
    monkeypatch.setattr(worker, 'heartbeat', lambda job, event: None)
    monkeypatch.setattr(worker, 'download_reel', lambda *args: pytest.fail('must reuse transcript'))
    monkeypatch.setattr(worker, 'transcribe_audio', lambda *args: pytest.fail('must reuse transcript'))
    monkeypatch.setattr(worker, 'extract_claims', lambda *args: [])
    writes = []
    monkeypatch.setattr(worker, 'save_stage', lambda job, **fields: writes.append(fields))
    worker.process_job(dict(id='video', lease_token='lease', segments=[], duration_ms=1000, title='Empty', shortcode='abc'))
    assert writes[-1]['state'] == 'ready'
    assert writes[-1]['lease_token'] is None
    assert list(tmp_path.iterdir()) == []


def test_optional_frame_failure_keeps_audio(monkeypatch, tmp_path):
    import json
    import subprocess
    from app import ingest
    path = tmp_path / 'clip.mp4'
    path.write_bytes(b'fixture')
    calls = []
    def run(command, **kwargs):
        calls.append(command)
        if command[0] == 'ffprobe':
            return SimpleNamespace(stdout=json.dumps({'format': {'duration': '2'}, 'streams': [{'codec_type': 'video'}]}).encode())
        if '-frames:v' in command:
            raise subprocess.CalledProcessError(1, command)
        return SimpleNamespace(returncode=0)
    monkeypatch.setattr(ingest.subprocess, 'run', run)
    audio, duration, thumbnail = ingest.prepare_media(path, tmp_path)
    assert duration == 2000
    assert thumbnail is None
    assert audio == tmp_path / 'speech.wav'
    assert calls[-1][-1] == str(audio)


def test_default_empty_segments_without_processed_media_requires_download():
    from app.worker import next_stage
    assert next_stage({'segments': [], 'duration_ms': None}) == 'downloading'
    assert next_stage({'segments': [], 'duration_ms': 1000}) == 'extracting'
    assert next_stage({'segments': None, 'duration_ms': 1000}) == 'downloading'
