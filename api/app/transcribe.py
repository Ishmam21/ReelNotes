"""Transcribe prepared Reel audio with Groq and normalize timestamped segments."""
import os
from pathlib import Path

import httpx
from pydantic import BaseModel

GROQ_TRANSCRIPTION_URL = 'https://api.groq.com/openai/v1/audio/transcriptions'
GROQ_TRANSCRIPTION_MODEL = 'whisper-large-v3-turbo'


class TranscriptionError(RuntimeError):
    """A transcription failure with a message safe to show in the playlist."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


class GroqSegment(BaseModel):
    start: float
    end: float
    text: str


class GroqTranscript(BaseModel):
    segments: list[GroqSegment]


def has_committed_transcript(video):
    # A database default [] alone is not evidence that media was processed.
    return video.get('segments') is not None and (video.get('duration_ms') or 0) > 0


def normalize_segments(segments):
    result = []
    for segment in segments:
        text = segment.text.strip()
        if not text:
            continue
        start, end = round(segment.start * 1000), round(segment.end * 1000)
        if not 0 <= start < end:
            raise ValueError('Invalid speech segment timestamps')
        result.append(dict(id=f's{len(result) + 1:03}', start_ms=start, end_ms=end, text=text))
    return result


def transcribe_audio(path):
    api_key = os.getenv('GROQ_API_KEY', '').strip()
    if not api_key:
        raise TranscriptionError('transcription_config', 'Set GROQ_API_KEY on the worker, then retry.')

    audio_path = Path(path)
    try:
        with audio_path.open('rb') as audio:
            response = httpx.post(
                GROQ_TRANSCRIPTION_URL,
                headers={'Authorization': f'Bearer {api_key}'},
                data={
                    'model': GROQ_TRANSCRIPTION_MODEL,
                    'response_format': 'verbose_json',
                    'timestamp_granularities[]': 'segment',
                },
                files={'file': (audio_path.name, audio, 'audio/wav')},
                timeout=httpx.Timeout(90, connect=10),
            )
    except httpx.TimeoutException:
        raise TranscriptionError('transcription_timeout', 'Groq transcription timed out. Retry this Reel.') from None
    except httpx.RequestError:
        raise TranscriptionError('transcription_unavailable', 'Could not reach Groq. Retry this Reel.') from None

    if response.status_code in (401, 403):
        raise TranscriptionError('transcription_config', 'Groq denied transcription. Check the worker API key and model access, then retry.')
    if response.status_code == 429:
        raise TranscriptionError('transcription_rate_limit', 'Groq’s transcription limit was reached. Retry after the limit resets.')
    if not response.is_success:
        raise TranscriptionError('transcription_failed', f'Groq transcription failed (HTTP {response.status_code}). Retry this Reel.')

    try:
        transcript = GroqTranscript.model_validate_json(response.content)
        return normalize_segments(transcript.segments)
    except (ValueError, OverflowError):
        raise TranscriptionError('transcription_invalid', 'Groq returned invalid transcript segments. Retry this Reel.') from None
