"""Local speech recognition. Model weights remain in the normal Hugging Face cache."""
import os
from functools import lru_cache


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


@lru_cache(maxsize=1)
def speech_model():
    from faster_whisper import WhisperModel
    return WhisperModel(os.getenv('WHISPER_MODEL', 'base'), device=os.getenv('WHISPER_DEVICE', 'cpu'),
                        compute_type=os.getenv('WHISPER_COMPUTE_TYPE', 'int8'))


def transcribe_audio(path):
    segments, _ = speech_model().transcribe(str(path), beam_size=5)
    return normalize_segments(segments)  # Consuming the generator actually runs inference.
