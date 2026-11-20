"""A small durable job worker; external work never owns a database transaction."""
import json
import logging
import os
from pathlib import Path
import shutil
import tempfile
import threading
import time
from uuid import uuid4

from sqlalchemy import text
from app.db import get_engine
from app.guide import extract_claims
from app.ingest import download_reel, prepare_media, webp_thumbnail
from app.transcribe import TranscriptionError, transcribe_audio, has_committed_transcript

ACTIVE = ('downloading', 'transcribing', 'extracting')
PIPELINE_VERSION = '1'
JOB_ROOT = Path(tempfile.gettempdir()) / 'reelnotes-jobs'


class LeaseLost(Exception):
    pass


def next_stage(video):
    # An empty committed transcript is valid and must not trigger transcription again.
    return 'extracting' if has_committed_transcript(video) else 'downloading'


def claim_job():
    with get_engine().begin() as connection:
        connection.execute(text("""UPDATE reelnotes.videos SET state='failed', error_code='attempts_exhausted',
            error_message='Processing was interrupted three times. Retry to start a new attempt.',
            lease_token=NULL, lease_until=NULL, updated_at=now()
            WHERE attempts >= 3 AND (state='queued' OR (state IN ('downloading','transcribing','extracting')
            AND (lease_until IS NULL OR lease_until < now())))"""))
        row = connection.execute(text("""SELECT * FROM reelnotes.videos WHERE attempts < 3 AND
            (state='queued' OR (state IN ('downloading','transcribing','extracting')
            AND (lease_until IS NULL OR lease_until < now()))) ORDER BY created_at
            FOR UPDATE SKIP LOCKED LIMIT 1""")).mappings().first()
        if row is None:
            return None
        job = dict(row)
        job['lease_token'] = uuid4()
        job['state'] = next_stage(job)
        connection.execute(text("""UPDATE reelnotes.videos SET state=:state, lease_token=:lease_token,
            lease_until=now()+interval '2 minutes', attempts=attempts+1, updated_at=now(),
            error_code=NULL, error_message=NULL WHERE id=:id"""), job)
        return job


def save_stage(job, **values):
    allowed = {'state', 'title', 'creator', 'duration_ms', 'thumbnail_webp', 'segments', 'claims',
               'pipeline_version', 'error_code', 'error_message', 'lease_token', 'lease_until'}
    if not values.keys() <= allowed:
        raise ValueError('Invalid worker field')
    assignments = []
    params = dict(values, job_id=job['id'], owner_token=job['lease_token'])
    for field, value in values.items():
        if field in ('segments', 'claims'):
            params[field] = json.dumps(value)
            assignments.append(f'{field}=CAST(:{field} AS jsonb)')
        else:
            assignments.append(f'{field}=:{field}')
    with get_engine().begin() as connection:
        # Token fencing prevents an old worker from overwriting a recovered job.
        changed = connection.execute(text(f"UPDATE reelnotes.videos SET {', '.join(assignments)}, updated_at=now() "
            'WHERE id=:job_id AND lease_token=:owner_token AND lease_until > now()'), params).rowcount
        if not changed:
            raise LeaseLost()


def heartbeat(job, stopped):
    while not stopped.wait(30):
        try:
            with get_engine().begin() as connection:
                changed = connection.execute(text("""UPDATE reelnotes.videos SET
                    lease_until=now()+interval '2 minutes', updated_at=now()
                    WHERE id=:id AND lease_token=:lease_token AND lease_until > now()"""), job).rowcount
                if not changed:
                    return
        except Exception:
            logging.exception('Heartbeat failed; fenced writes will reject expired ownership')
            return


def process_job(job, local_clip=None):
    stopped = threading.Event()
    thread = threading.Thread(target=heartbeat, args=(job, stopped), daemon=True)
    thread.start()
    JOB_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    try:
        with tempfile.TemporaryDirectory(prefix=f"{job['id']}_{job['lease_token']}_", dir=JOB_ROOT) as folder:
            directory = Path(folder)
            segments = job['segments']
            title = job['title'] or f"Instagram Reel {job['shortcode']}"
            if not has_committed_transcript(job):
                logging.info('Video %s: preparing media', job['id'])
                media = dict(path=str(local_clip), title='Owned local sample', creator='Local fixture') if local_clip else download_reel(job['source_url'], directory)
                audio, duration, thumbnail = prepare_media(media['path'], directory)
                for path in directory.glob('media.*'):
                    if path.suffix.lower() in ('.jpg', '.jpeg', '.png', '.webp'):
                        try:
                            thumbnail = webp_thumbnail(path) or thumbnail
                        except Exception:
                            pass  # A damaged optional thumbnail does not invalidate speech.
                title = media['title']
                save_stage(job, title=title, creator=media.get('creator'), duration_ms=duration,
                           thumbnail_webp=thumbnail, state='transcribing')
                logging.info('Video %s: transcribing with Groq', job['id'])
                segments = transcribe_audio(audio)
                save_stage(job, segments=segments, state='extracting')
            logging.info('Video %s: extracting advice with Gemini', job['id'])
            claims = extract_claims(title, segments)
            save_stage(job, claims=claims, state='ready', pipeline_version=PIPELINE_VERSION,
                       lease_token=None, lease_until=None)
            logging.info('Video %s: ready (%s claims)', job['id'], len(claims))
    except LeaseLost:
        logging.info('Discarded result after ownership expired')
    except Exception as exc:
        try:
            code = getattr(exc, 'code', 'processing_failed')
            if isinstance(exc, TranscriptionError) or code in ('source_unavailable', 'download_timeout', 'media_limit'):
                message = str(exc)
            elif isinstance(exc, FileNotFoundError):
                message = 'Required media dependency is missing. Install ffmpeg and ffprobe, then retry.'
            else:
                message = 'Processing failed. Check worker configuration, then retry or remove this clip.'
            save_stage(job, state='failed', error_code=code, error_message=message,
                       lease_token=None, lease_until=None)
        except LeaseLost:
            pass
        logging.exception('Video processing failed')
    finally:
        stopped.set()
        thread.join(timeout=1)


def sweep_abandoned():
    JOB_ROOT.mkdir(mode=0o700, parents=True, exist_ok=True)
    for directory in JOB_ROOT.iterdir():
        if not directory.is_dir() or directory.is_symlink():
            continue
        parts = directory.name.split('_')
        if len(parts) < 3:
            continue
        with get_engine().connect() as connection:
            live = connection.execute(text('SELECT 1 FROM reelnotes.videos WHERE id=:id AND lease_token=:token AND lease_until > now()'),
                                      {'id': parts[0], 'token': parts[1]}).first()
        if not live:
            shutil.rmtree(directory)


def main():
    logging.basicConfig(level=logging.INFO)
    logging.info('ReelNotes worker starting; checking queued jobs')
    sweep_abandoned()
    waiting = False
    while True:
        job = claim_job()
        if job:
            waiting = False
            logging.info('Claimed video %s', job['id'])
            process_job(job)
        else:
            if not waiting:
                logging.info('No queued jobs. Waiting for Reels added through the app.')
                waiting = True
            time.sleep(2)


if __name__ == '__main__':
    main()
