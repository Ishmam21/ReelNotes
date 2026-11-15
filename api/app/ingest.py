"""Bounded public Reel downloading and local media preparation."""
import io
import json
import re
import subprocess
import sys
from pathlib import Path
from urllib.parse import urlsplit

MAX_BYTES = 50 * 1024 * 1024
MAX_SECONDS = 180


class IngestError(Exception):
    def __init__(self, code, message):
        self.code = code
        super().__init__(message)


def canonicalize_url(value):
    try:
        parsed = urlsplit(value)
        if parsed.scheme != 'https' or parsed.netloc not in ('instagram.com', 'www.instagram.com'):
            raise ValueError('Use an HTTPS instagram.com Reel URL without a port or credentials.')
        match = re.fullmatch(r'/(?:[A-Za-z0-9_.]+/)?reel/([A-Za-z0-9_-]+)/?', parsed.path)
        if not match:
            raise ValueError('Use a URL in the form https://www.instagram.com/reel/SHORTCODE/.')
        code = match.group(1)
        return code, f'https://www.instagram.com/reel/{code}/'
    except (TypeError, AttributeError) as exc:
        raise ValueError('Invalid Reel URL') from exc


def choose_title(info, shortcode):
    title = (info.get('title') or '').strip()
    if title and title.lower() not in ('instagram', 'video', 'reel'):
        return title[:120]
    for line in (info.get('description') or '').splitlines():
        if line.strip():
            return line.strip()[:120]
    return f'Instagram Reel {shortcode}'


def webp_thumbnail(path):
    from PIL import Image, ImageOps
    with Image.open(path) as original:
        image = ImageOps.exif_transpose(original).convert('RGB')
        image.thumbnail((480, 480))
        for quality in (80, 60, 40, 20):
            output = io.BytesIO()
            image.save(output, format='WEBP', quality=quality)
            if len(output.getvalue()) < 200 * 1024:
                return output.getvalue()
    return None


def prepare_media(path, directory):
    path, directory = Path(path), Path(directory)
    if path.stat().st_size > MAX_BYTES:
        raise IngestError('media_limit', 'Clip exceeds 50 MiB; use a shorter clip.')
    probe = subprocess.run(['ffprobe', '-v', 'error', '-show_format', '-show_streams', '-of', 'json', str(path)],
                           capture_output=True, check=True, timeout=20)
    metadata = json.loads(probe.stdout)
    duration = float(metadata['format']['duration'])
    if not 0 < duration <= MAX_SECONDS:
        raise IngestError('media_limit', 'Clip must be at most 180 seconds.')
    thumbnail = None
    if any(s['codec_type'] == 'video' for s in metadata['streams']):
        frame = directory / 'frame.jpg'
        try:
            subprocess.run(['ffmpeg', '-nostdin', '-y', '-i', str(path), '-frames:v', '1', '-vf', 'scale=480:-1', str(frame)],
                           capture_output=True, check=True, timeout=30)
            thumbnail = webp_thumbnail(frame)
        except (subprocess.SubprocessError, OSError, ValueError):
            # A thumbnail is optional; continue decoding the usable audio track.
            thumbnail = None
    audio = directory / 'speech.wav'
    subprocess.run(['ffmpeg', '-nostdin', '-y', '-i', str(path), '-vn', '-ac', '1', '-ar', '16000', str(audio)],
                   capture_output=True, check=True, timeout=60)
    return audio, round(duration * 1000), thumbnail


def download_child(url, directory):
    import yt_dlp
    shortcode, url = canonicalize_url(url)
    directory = Path(directory)
    downloaded = []
    def progress(event):
        if event.get('downloaded_bytes', 0) > MAX_BYTES:
            raise IngestError('media_limit', 'Download exceeds 50 MiB.')
        if event['status'] == 'finished':
            downloaded.append(event['filename'])
    options = dict(noplaylist=True, socket_timeout=15, retries=2, fragment_retries=2,
                   format='bestaudio/best', outtmpl=str(directory / 'media.%(ext)s'),
                   progress_hooks=[progress], quiet=True, max_filesize=MAX_BYTES,
                   writethumbnail=True, ignoreerrors="only_download")
    with yt_dlp.YoutubeDL(options) as downloader:
        info = downloader.extract_info(url, download=False)
        if not info or info.get('_type') in ('playlist', 'multi_video') or 'entries' in info:
            raise IngestError('source_unavailable', 'Expected a single public Reel.')
        if info.get('duration') and info['duration'] > MAX_SECONDS:
            raise IngestError('media_limit', 'Clip exceeds 180 seconds.')
        info = downloader.process_ie_result(info, download=True)
    if not downloaded:
        raise IngestError('source_unavailable', 'The Reel could not be downloaded.')
    path = Path(downloaded[-1]).resolve()
    if not path.is_relative_to(directory.resolve()) or not path.is_file():
        raise IngestError('source_unavailable', 'Downloader returned an invalid media path.')
    if path.stat().st_size > MAX_BYTES:
        raise IngestError('media_limit', 'Download exceeds 50 MiB.')
    result = dict(path=str(path), title=choose_title(info, shortcode), creator=info.get('uploader'))
    (directory / 'download.json').write_text(json.dumps(result), encoding='utf-8')


def download_reel(url, directory):
    canonicalize_url(url)
    try:
        subprocess.run([sys.executable, '-m', 'app.ingest', url, str(directory)],
                       capture_output=True, check=True, timeout=150)
        return json.loads((Path(directory) / 'download.json').read_text())
    except subprocess.TimeoutExpired as exc:
        raise IngestError('download_timeout', 'Download timed out. Retry or remove this Reel.') from exc
    except subprocess.CalledProcessError as exc:
        raise IngestError('source_unavailable', 'Public Reel unavailable. Check the link, then retry or remove it.') from exc


if __name__ == '__main__':
    download_child(sys.argv[1], sys.argv[2])
